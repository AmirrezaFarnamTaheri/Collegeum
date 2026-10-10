"""Regression guards for ambiguous Telegram sendMessage outcomes."""

from unittest.mock import Mock

import httpx
import pytest

from predoc_pipeline.publish.telegram import TelegramClient, TelegramError


def _client(handler):
    return TelegramClient(bot_token="test-token", client=httpx.Client(
        transport=httpx.MockTransport(handler)
    ))


def test_transport_error_is_not_automatically_replayed():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("response lost", request=request)

    client = _client(handler)
    with pytest.raises(TelegramError) as exc:
        client.send_message(chat_id="100", html="Example", sleep=lambda _: None)
    assert exc.value.uncertain
    assert len(calls) == 1


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_server_errors_do_not_repeat_potentially_accepted_messages(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="server error")

    with pytest.raises(TelegramError) as exc:
        _client(handler).send_message(chat_id="100", html="Example", sleep=lambda _: None)
    assert exc.value.uncertain
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [
    {"ok": True, "result": {}},
    {"ok": True, "result": {"message_id": 0}},
    {"ok": True, "result": {"message_id": "55"}},
    {"ok": True, "result": {"message_id": True}},
])
def test_malformed_success_acknowledgement_blocks_replay(payload):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload)

    with pytest.raises(TelegramError) as exc:
        _client(handler).send_message(chat_id="100", html="Example", sleep=lambda _: None)
    assert exc.value.uncertain
    assert len(calls) == 1


def test_definite_400_response_is_permanent_not_uncertain():
    with pytest.raises(TelegramError) as exc:
        _client(lambda req: httpx.Response(400, text="bad request")).send_message(
            chat_id="100", html="Example", sleep=lambda _: None
        )
    assert exc.value.permanent
    assert not exc.value.uncertain
