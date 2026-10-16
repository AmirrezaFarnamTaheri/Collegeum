"""Webhook sync validates private feedback before changing local state."""

import json
from pathlib import Path

import httpx
import pytest

from predoc_pipeline.core.timeparse import format_ts
from predoc_pipeline.publish.bot import telegram_sync
from predoc_pipeline.publish.feedback import FeedbackStore
from tests.integration.test_bot import add_listings
from tests.integration.test_bot import settings as bot_settings

settings = bot_settings


def test_subscriber_sync_preserves_delivery_receipts_and_honors_deletion(settings):
    from predoc_pipeline.publish.cloud import PREFERENCE_FIELDS
    from predoc_pipeline.publish.feedback import generate_key

    configure(settings)
    settings.feedback_encryption_key = generate_key()
    store = FeedbackStore.from_settings(settings)
    store.toggle_subscription(101, 'topics', 'predoc')
    store.reserve_delivery(101, 'academic:already-sent')
    store.save()
    preferences = {key: store.subscriber(101)[key] for key in PREFERENCE_FIELDS}
    preferences['paused'] = True

    def handler(request):
        sent = json.loads(request.content)['subscribers']['101']
        assert 'deliveries' not in sent
        return httpx.Response(200, json={'marks': {}, 'subscriber_protocol': 1,
                                        'subscribers': {'101': preferences}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        telegram_sync(settings, http_client=client)
    member = FeedbackStore.from_settings(settings).subscriber(101)
    assert member['paused']
    assert member['deliveries']['academic:already-sent']['state'] == 'sending'
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
        200, json={'marks': {}, 'subscriber_protocol': 1, 'subscribers': {'101': None}},
    ))) as client:
        telegram_sync(settings, http_client=client)
    assert FeedbackStore.from_settings(settings).subscriber(101) is None


def configure(settings):
    settings.telegram_webhook_enabled = True
    settings.telegram_worker_url = 'https://collegeum.example.org'
    settings.telegram_worker_sync_token = 'offline-sync-secret'


def test_old_worker_cannot_disable_existing_subscriber_controls(settings):
    from predoc_pipeline.publish.cloud import sync_cloud
    from predoc_pipeline.publish.feedback import generate_key

    configure(settings)
    settings.feedback_encryption_key = generate_key()
    store = FeedbackStore.from_settings(settings)
    store.toggle_subscription(101, 'topics', 'predoc')
    store.save()
    calls = []
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: calls.append(request) or httpx.Response(
                200, json={'marks': {}}))) as client:
        for function in (telegram_sync, sync_cloud):
            with pytest.raises(ValueError, match='subscriber-capable Worker'):
                function(settings, http_client=client)
    assert len(calls) == 2
    assert FeedbackStore.from_settings(settings).subscriber(101)['topics']['predoc']


def test_webhook_mode_sends_snapshot_and_imports_marks_without_polling(settings):
    ids = add_listings(settings)
    configure(settings)
    key = ids['Research Assistant in Finance']
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == '/sync'
        assert request.headers['Authorization'] == 'Bearer offline-sync-secret'
        payload = json.loads(request.content)
        assert len(payload['listings']) == 5
        assert all('telegram_message_id' not in r for r in payload['listings'])
        return httpx.Response(200, json={'subscriber_protocol': 1, 'subscribers': {},
                                        'marks': {key: {'status': 'applied', 'at': format_ts()}}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = telegram_sync(settings, http_client=client)
    assert len(calls) == 1 and result['taps'] == 1
    assert FeedbackStore(settings.feedback_path).status(key) == 'applied'


def test_undo_tombstone_removes_existing_feedback(settings):
    ids = add_listings(settings)
    configure(settings)
    key = ids['Research Assistant in Finance']
    store = FeedbackStore(settings.feedback_path)
    store.set(key, 'valid')
    store.save()
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
            200, json={'subscriber_protocol': 1, 'subscribers': {},
                       'marks': {key: {'status': None, 'at': format_ts()}}}))) as client:
        telegram_sync(settings, http_client=client)
    assert FeedbackStore(settings.feedback_path).status(key) is None


@pytest.mark.parametrize('mark', [{'status': 'applied'}, {'status': 'bad', 'at': format_ts()},
                                 {'status': 'valid', 'at': '2099-01-01T00:00:00Z'},
                                 {'status': 'valid', 'at': format_ts(), 'url': {}}])
def test_invalid_cloud_feedback_preserves_local_marks(settings, mark):
    ids = add_listings(settings)
    configure(settings)
    key = ids['Research Assistant in Finance']
    store = FeedbackStore(settings.feedback_path)
    store.set(key, 'valid')
    store.save()
    before = Path(settings.feedback_path).read_bytes()
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
            200, json={'subscriber_protocol': 1, 'subscribers': {},
                       'marks': {key: mark}}))) as client, pytest.raises(ValueError):
        telegram_sync(settings, http_client=client)
    assert Path(settings.feedback_path).read_bytes() == before


def test_cloud_mode_requires_https_and_no_credentials_in_url(settings):
    configure(settings)
    settings.telegram_worker_url = 'http://example.org'
    with pytest.raises(ValueError, match='HTTPS'):
        telegram_sync(settings)


def test_cloud_export_failure_retries_even_when_feedback_is_already_saved(settings, monkeypatch):
    from predoc_pipeline import state

    ids = add_listings(settings)
    configure(settings)
    key = ids['Research Assistant in Finance']
    original = state.export_feed
    attempts = []

    def fail_once(*args, **kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError('temporary export failure')
        return original(*args, **kwargs)

    monkeypatch.setattr(state, 'export_feed', fail_once)
    timestamp = format_ts()
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
            200, json={'subscriber_protocol': 1, 'subscribers': {},
                       'marks': {key: {'status': 'invalid', 'at': timestamp}}}))) as client:
        with pytest.raises(OSError, match='export'):
            telegram_sync(settings, http_client=client)
        assert FeedbackStore(settings.feedback_path).data['cloud_exports_pending']
        result = telegram_sync(settings, http_client=client)
    assert result['taps'] == 0 and len(attempts) == 2
    assert not FeedbackStore(settings.feedback_path).data['cloud_exports_pending']
