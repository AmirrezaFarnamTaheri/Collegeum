"""Synchronize the optional webhook bot without changing Telegram's webhook."""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from .. import state
from ..core.db import Database
from ..core.db import init as init_db
from ..core.timeparse import format_ts, parse_datetime, utcnow
from ..routing import Router
from ..settings import Settings
from .feedback import STATUS_BY_CODE, FeedbackStore


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
    if store.subscribers:
        raise ValueError('Webhook mode cannot replace active subscriber polling')
    init_db(settings.db_path)
    with Database(settings.db_path) as db:
        state.restore_if_needed(db, settings.state_path, settings.seen_state_path)
        router = Router(load_preferences(settings.preferences_config))
        records = []
        for row in db.published_listings():
            data = state._public_record(row)
            data.update({key: row[key] for key in (
                'url_hash', 'first_seen_at', 'last_seen_at', 'closed_at', 'expired_at',
                'deadline_note',
            )})
            data['kind'] = router.position_kind(row['title'], row['summary'] or '')
            records.append(data)
    if len(records) > 2000:
        raise ValueError('Webhook snapshot exceeds 2,000 listings; archive history before syncing')
    payload = {'generated_at': format_ts(), 'listings': records, 'marks': store.marks}
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
