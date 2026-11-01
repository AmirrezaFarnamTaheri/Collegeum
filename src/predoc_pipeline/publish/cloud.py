"""Synchronize the optional webhook bot without changing Telegram's webhook."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from .. import state
from ..core.db import Database
from ..core.db import init as init_db
from ..core.timeparse import format_ts, parse_datetime, utcnow
from ..routing import Router
from ..settings import Settings
from .feedback import STATUS_BY_CODE, FeedbackStore

PREFERENCE_FIELDS = ('topics', 'scopes', 'paused', 'language', 'delivery_mode',
                     'daily_limit', 'quiet_hours', 'timezone', 'academic_regions')


def _validate_subscribers(profiles: object) -> dict[str, Any]:
    from .feedback import DAILY_LIMITS, DELIVERY_ZONES, MAX_SUBSCRIBERS
    from .subscriptions import ACADEMIC_REGIONS, CAREER_SCOPES, TOPICS

    if not isinstance(profiles, dict) or len(profiles) > MAX_SUBSCRIBERS:
        raise ValueError('Invalid webhook subscriber response')
    for identifier, member in profiles.items():
        if (not isinstance(identifier, str) or not identifier.isascii()
                or not identifier.isdecimal() or not 0 < int(identifier) <= 2**53 - 1):
            raise ValueError('Invalid webhook subscriber identity')
        if member is None:
            continue
        required = set(PREFERENCE_FIELDS) - {'academic_regions'}
        if (not isinstance(member, dict) or not required.issubset(member)
                or set(member) - set(PREFERENCE_FIELDS)):
            raise ValueError('Invalid webhook subscriber preferences')
        member.setdefault('academic_regions', {})
        for field, allowed in (('topics', TOPICS), ('scopes', CAREER_SCOPES),
                               ('academic_regions', (*ACADEMIC_REGIONS, 'all')):
            choices = member[field]
            if not isinstance(choices, dict) or any(
                key not in allowed or not isinstance(at, str)
                or (parsed := parse_datetime(at)) is None or parsed > utcnow()
                for key, at in choices.items()
            ):
                raise ValueError('Invalid webhook subscriber selections')
        if (type(member['paused']) is not bool or member['language'] not in ('en', 'fa')
                or member['delivery_mode'] not in ('instant', 'digest')
                or type(member['daily_limit']) is not int
                or member['daily_limit'] not in DAILY_LIMITS
                or type(member['quiet_hours']) is not bool
                or member['timezone'] not in DELIVERY_ZONES):
            raise ValueError('Invalid webhook delivery preferences')
    return profiles


def sync_cloud(
    settings: Settings, *, http_client: httpx.Client | None = None,
) -> dict[str, int]:
    """Upload a snapshot and import authoritative, private webhook feedback.

    Polling and webhook delivery are mutually exclusive. Credentials authorize
    only this worker's sync endpoint; this function never calls setWebhook.
    """
    from ..boards.config import load_preferences

    parts = urlsplit(settings.telegram_worker_url)
    if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or not settings.telegram_worker_sync_token):
        raise ValueError('Webhook mode needs an HTTPS TELEGRAM_WORKER_URL and sync token')
    store = FeedbackStore.from_settings(settings)
    if store.subscribers and not store.key:
        raise ValueError('Webhook subscriber sync requires encrypted local storage')
    init_db(settings.db_path)
    with Database(settings.db_path) as db:
        state.restore_if_needed(db, settings.state_path, settings.seen_state_path)
        router = Router(load_preferences(settings.preferences_config))
        records = []
        for row in db.published_listings():
            data = state._public_record(row)
            data.update({key: row[key] for key in (
                'url_hash', 'first_seen_at', 'last_seen_at', 'published_at',
                'closed_at', 'expired_at',
                'deadline_note',
            )})
            data['kind'] = router.kind_for_row(row)
            records.append(data)
    if len(records) > 2000:
        raise ValueError('Webhook snapshot exceeds 2,000 listings; archive history before syncing')
    # Keep an empty academic region selection implicit for older Worker builds.
    # New selections are enabled only after the compatible Worker is deployed.
    profiles = {identifier: {
        field: member[field] for field in PREFERENCE_FIELDS
        if field != 'academic_regions' or member.get('academic_regions')
    } for identifier, member in store.subscribers.items()}
    from ..ingest.career import load_career

    careers = load_career(settings.career_state_path)
    from .ui import sources_panel

    source_status = {lang: sources_panel(settings.career_health_path, lang=lang)[0]
                     for lang in ('en', 'fa')}
    payload = {'generated_at': format_ts(), 'listings': records, 'marks': store.marks,
               'subscriber_protocol': 1, 'subscribers': profiles, 'career_listings': careers,
               'source_status': source_status}
    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=30)
    try:
        response = client.post(
            settings.telegram_worker_url.rstrip('/') + '/sync', json=payload,
            headers={'Authorization': f'Bearer {settings.telegram_worker_sync_token}'},
        )
        response.raise_for_status()
        data = response.json()
    finally:
        if owns_client:
            client.close()
    marks = data.get('marks') if isinstance(data, dict) else None
    if not isinstance(marks, dict) or len(marks) > 2000:
        raise ValueError('Invalid webhook feedback response')
    if data.get('subscriber_protocol') != 1:
        raise ValueError('Deploy a subscriber-capable Worker before enabling webhook mode')
    incoming = _validate_subscribers(data.get('subscribers'))
    if incoming and not store.key:
        raise ValueError('Webhook subscriber sync requires encrypted local storage')
    if set(store.subscribers) - incoming.keys():
        raise ValueError('Worker omitted existing subscribers; refusing incomplete migration')
    for key, mark in marks.items():
        if (not isinstance(key, str) or len(key) != 64
                or any(c not in '0123456789abcdef' for c in key) or not isinstance(mark, dict)
                or mark.get('status') not in (*STATUS_BY_CODE.values(), None)):
            raise ValueError('Invalid webhook mark')
        timestamp = parse_datetime(mark.get('at')) if isinstance(mark.get('at'), str) else None
        if timestamp is None or timestamp > utcnow():
            raise ValueError('Invalid webhook mark timestamp')
        if any(mark.get(field) is not None and not isinstance(mark[field], str)
               for field in ('title', 'institution', 'url')):
            raise ValueError('Invalid webhook mark metadata')
    changed = 0
    for identifier, preferences in incoming.items():
        if preferences is None:
            store.remove_subscriber(int(identifier))
        else:
            existed = identifier in store.subscribers
            member = store._member(int(identifier))
            if not existed or any(
                member[field] != preferences[field] for field in PREFERENCE_FIELDS
            ):
                member.update(preferences)
                store.mark_dirty()
    for key, mark in marks.items():
        if store.status(key) == mark['status'] and (
            mark['status'] is None or store.marked_at(key) == mark['at']
        ):
            continue
        store.set(key, mark['status'])
        if mark['status'] is not None:
            store.marks[key] = dict(mark)
        changed += 1
    if changed:
        store.data['cloud_exports_pending'] = True
        store.mark_dirty()
    store.save()
    if store.data.get('cloud_exports_pending'):
        router = Router(load_preferences(settings.preferences_config))
        with Database(settings.db_path) as db:
            state.export_dashboard(db, settings.dashboard_json, hidden=store.hidden, router=router)
            state.export_feed(db, settings.feed_path, site_url=settings.site_url,
                              hidden=store.hidden, router=router)
        store.data['cloud_exports_pending'] = False
        store.mark_dirty()
        store.save()
    return {'received': changed, 'commands': 0, 'taps': changed, 'ignored': 0,
            'failed': 0, 'dropped': 0}
