"""Inspect Telegram delivery; --activate registers a verified, seeded Worker.

Uses existing environment credentials. Never prints tokens, chat IDs or raw
provider errors, and never drops Telegram's pending updates.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url: str, *, payload: dict | None = None, bearer: str = '',
                 webhook_secret: str = '') -> dict:
    headers = {'Content-Type': 'application/json'}
    if bearer:
        headers['Authorization'] = f'Bearer {bearer}'
    if webhook_secret:
        headers['X-Telegram-Bot-Api-Secret-Token'] = webhook_secret
    request = Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                      headers=headers)
    try:
        with build_opener(_NoRedirects()).open(request, timeout=30) as response:
            result = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(f'Connection check failed ({type(exc).__name__})') from None
    if not isinstance(result, dict):
        raise RuntimeError('Invalid connection response')
    return result


def smoke_test(env: dict[str, str], report: dict[str, Any], *,
               request: Any = request_json) -> dict[str, Any]:
    """Send one owner menu through the authenticated Worker and confirm delivery."""
    if not report.get('ready'):
        raise ValueError('Verified webhook readiness is required before a live menu test')
    identifier = env.get('TELEGRAM_ADMIN_CHAT_ID', '')
    if not identifier.isascii() or not identifier.isdecimal() or int(identifier) <= 0:
        raise ValueError('A positive TELEGRAM_ADMIN_CHAT_ID is required for a live menu test')
    secret = env.get('TELEGRAM_WEBHOOK_SECRET', '')
    if not secret:
        raise ValueError('TELEGRAM_WEBHOOK_SECRET is required for a live menu test')
    # This private test ID does not alter Telegram's polling cursor. The real
    # webhook and the test share the Worker's ordinary delivery checkpoints.
    update_id = 2**52 + secrets.randbelow(2**50)
    started = time.perf_counter()
    result = request(env['TELEGRAM_WORKER_URL'].rstrip('/') + '/webhook',
                     webhook_secret=secret, payload={
        'update_id': update_id, 'message': {
            'chat': {'id': int(identifier), 'type': 'private'},
            'from': {'id': int(identifier)}, 'text': '/menu',
        },
    })
    if result != {'ok': True}:
        raise RuntimeError('Worker did not confirm owner menu delivery')
    return {'menu_delivery_confirmed': True,
            'menu_response_ms': round((time.perf_counter() - started) * 1000)}


def inspect_connection(env: dict[str, str], *, activate: bool = False,
                       request: Any = request_json) -> dict[str, Any]:
    token = env.get('TELEGRAM_BOT_TOKEN', '')
    origin = env.get('TELEGRAM_WORKER_URL', '').rstrip('/')
    sync_token = env.get('TELEGRAM_WORKER_SYNC_TOKEN', '')
    webhook_secret = env.get('TELEGRAM_WEBHOOK_SECRET', '')
    enabled = env.get('TELEGRAM_WEBHOOK_ENABLED', '').lower() == 'true'
    result: dict[str, Any] = {'webhook_mode_enabled': enabled,
                              'worker_configured': bool(origin and sync_token)}
    if not token:
        raise ValueError('TELEGRAM_BOT_TOKEN is required for the connection check')
    api = f'https://api.telegram.org/bot{token}/'
    info = request(api + 'getWebhookInfo', payload={})
    if not info.get('ok') or not isinstance(info.get('result'), dict):
        raise RuntimeError('Telegram webhook inspection failed')
    webhook = info['result']
    result.update({'telegram_delivery': 'webhook' if webhook.get('url') else 'polling',
                   'webhook_matches_worker': bool(
                       origin and webhook.get('url') == origin + '/webhook'),
                   'pending_updates': webhook.get('pending_update_count', 0),
                   'last_delivery_error_at': webhook.get('last_error_date')})
    status = None
    if origin:
        parts = urlsplit(origin)
        if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment or parts.path):
            raise ValueError('TELEGRAM_WORKER_URL must be an HTTPS origin')
        if not sync_token:
            raise ValueError('TELEGRAM_WORKER_SYNC_TOKEN is required')
        started = time.perf_counter()
        status = request(origin + '/status', bearer=sync_token)
        result['worker_status_ms'] = round((time.perf_counter() - started) * 1000)
        result['worker'] = {field: status.get(field) for field in (
            'subscriber_protocol', 'subscribers_initialized', 'snapshot_at', 'pending_updates')}
    if activate:
        if not enabled or not webhook_secret or not status:
            raise ValueError('Activation requires webhook mode, Worker URL, sync token '
                             'and webhook secret')
        if (status.get('subscriber_protocol') != 1
                or status.get('subscribers_initialized') is not True):
            raise ValueError('Seed subscriber preferences with telegram-sync before activation')
        try:
            timestamp = datetime.fromisoformat(
                str(status.get('snapshot_at')).replace('Z', '+00:00'))
            age = datetime.now(UTC) - timestamp
        except (ValueError, TypeError):
            raise ValueError('Worker has no valid snapshot') from None
        if not timedelta(0) <= age <= timedelta(hours=8):
            raise ValueError('Refresh the Worker snapshot before activation')
        applied = request(api + 'setWebhook', payload={
            'url': origin + '/webhook', 'secret_token': webhook_secret,
            'allowed_updates': ['message', 'callback_query'], 'max_connections': 40,
            'drop_pending_updates': False,
        })
        if applied.get('ok') is not True:
            raise RuntimeError('Telegram refused webhook activation')
        checked = request(api + 'getWebhookInfo', payload={})
        if not checked.get('ok') or checked.get('result', {}).get('url') != origin + '/webhook':
            raise RuntimeError('Telegram did not confirm the intended Worker webhook')
        result['telegram_delivery'] = 'webhook'
        result['webhook_matches_worker'] = True
    result['ready'] = bool(enabled and result['webhook_matches_worker'] and status and
                           status.get('subscribers_initialized') is True and
                           status.get('subscriber_protocol') == 1)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--smoke', action='store_true', help='Send one test menu to the owner')
    args = parser.parse_args()
    try:
        report = inspect_connection(dict(os.environ), activate=args.activate)
        if args.smoke:
            report['live_test'] = smoke_test(dict(os.environ), report)
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
