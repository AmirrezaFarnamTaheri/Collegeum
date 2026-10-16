"""Connection diagnostics are read-only unless activation is explicit."""
from datetime import UTC, datetime, timedelta

import pytest

from tools.telegram_connection import inspect_connection, smoke_test


@pytest.mark.parametrize('snapshot', [
    None, 'invalid', '2026-01-01T12:00:00',
    (datetime.now(UTC) - timedelta(hours=9)).isoformat(),
    (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
])
def test_stale_or_invalid_snapshot_is_not_ready(snapshot):
    calls = []
    env = {'TELEGRAM_BOT_TOKEN': 'secret', 'TELEGRAM_WORKER_URL': 'https://bot.workers.dev',
           'TELEGRAM_WEBHOOK_ENABLED': 'true', 'TELEGRAM_WORKER_SYNC_TOKEN': 'sync',
           'TELEGRAM_WEBHOOK_SECRET': 'webhook-secret'}

    def request(url, **kwargs):
        calls.append(url)
        if url.endswith('/status'):
            return {'subscriber_protocol': 1, 'subscribers_initialized': True,
                    'snapshot_at': snapshot}
        return {'ok': True, 'result': {'url': 'https://bot.workers.dev/webhook'}}

    report = inspect_connection(env, request=request)
    assert report['snapshot_fresh'] is False
    assert report['ready'] is False
    with pytest.raises(ValueError, match='Refresh the Worker snapshot'):
        inspect_connection(env, activate=True, request=request)
    assert not any(url.endswith('setWebhook') for url in calls)


def test_polling_diagnosis_does_not_change_webhook():
    calls = []

    def request(url, **kwargs):
        calls.append(url)
        return {'ok': True, 'result': {'url': '', 'pending_update_count': 3}}

    result = inspect_connection({'TELEGRAM_BOT_TOKEN': 'secret'}, request=request)
    assert result['telegram_delivery'] == 'polling'
    assert result['pending_updates'] == 3
    assert not result['ready']
    assert len(calls) == 1 and calls[0].endswith('getWebhookInfo')
    assert 'secret' not in str(result)


def test_live_menu_test_requires_readiness_and_confirms_worker_send():
    env = {'TELEGRAM_ADMIN_CHAT_ID': '42', 'TELEGRAM_WORKER_URL': 'https://bot.workers.dev',
           'TELEGRAM_WEBHOOK_SECRET': 'secret'}
    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return {'ok': True}

    with pytest.raises(ValueError, match='readiness'):
        smoke_test(env, {'ready': False}, request=request)
    assert not calls
    result = smoke_test(env, {'ready': True}, request=request)
    assert result['menu_delivery_confirmed']
    assert calls[0][0] == 'https://bot.workers.dev/webhook'
    assert calls[0][1]['payload']['message']['text'] == '/menu'
    assert calls[0][1]['webhook_secret'] == 'secret'
    assert 'secret' not in str(result)
    with pytest.raises(RuntimeError, match='confirm'):
        smoke_test(env, {'ready': True}, request=lambda *a, **k: {'ok': True, 'rejected': True})


@pytest.mark.parametrize('seeded', [False, True])
def test_activation_requires_seeded_profiles_and_preserves_pending_updates(seeded):
    calls = []
    env = {'TELEGRAM_BOT_TOKEN': 'secret', 'TELEGRAM_WORKER_URL': 'https://bot.workers.dev',
           'TELEGRAM_WEBHOOK_ENABLED': 'true', 'TELEGRAM_WORKER_SYNC_TOKEN': 'sync',
           'TELEGRAM_WEBHOOK_SECRET': 'webhook-secret'}

    def request(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith('/status'):
            return {'subscriber_protocol': 1, 'subscribers_initialized': seeded,
                    'snapshot_at': datetime.now(UTC).isoformat()}
        if url.endswith('setWebhook'):
            assert kwargs['payload']['drop_pending_updates'] is False
            return {'ok': True}
        return {'ok': True, 'result': {'url': 'https://bot.workers.dev/webhook'}}

    if seeded:
        assert inspect_connection(env, activate=True, request=request)['ready']
    else:
        with pytest.raises(ValueError, match='Seed subscriber'):
            inspect_connection(env, activate=True, request=request)
        assert not any(url.endswith('setWebhook') for url, _ in calls)
