"""Connection diagnostics are read-only unless activation is explicit."""
from datetime import UTC, datetime

import pytest

from tools.telegram_connection import inspect_connection


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
