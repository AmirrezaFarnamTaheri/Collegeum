"""Telegram response and Retry-After processing must remain bounded."""

import httpx
import pytest

from predoc_pipeline.publish.telegram import TelegramClient, TelegramError


@pytest.mark.parametrize("method", ["sendMessage", "getUpdates"])
def test_excessive_retry_after_defers_instead_of_blocking_worker(method):
    requests = []
    sleeping = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429, json={
            "ok": False, "parameters": {"retry_after": 86400},
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        telegram = TelegramClient(bot_token="test", client=http)
        with pytest.raises(TelegramError) as error:
            if method == "sendMessage":
                telegram.send_message(
                    chat_id="123", html="Example", sleep=sleeping.append,
                )
            else:
                telegram.call("getUpdates", {"timeout": 0}, sleep=sleeping.append)
    assert error.value.status == 429
    assert not error.value.uncertain
    assert len(requests) == 1
    assert sleeping == []


def test_malformed_retry_after_is_normalized_to_bounded_default():
    requests = []
    sleeps = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, json={
                "ok": False, "parameters": {"retry_after": "NaN"},
            })
        return httpx.Response(200, json={"ok": True, "result": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        telegram = TelegramClient(bot_token="test", client=http)
        assert telegram.call("getUpdates", {"timeout": 0}, sleep=sleeps.append) == []
    assert len(requests) == 2
    assert any(delay >= 5 for delay in sleeps)


def test_unexpected_json_response_shape_is_reported_not_crashed():
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=["not", "an", "object"])
    )) as http:
        telegram = TelegramClient(bot_token="test", client=http)
        with pytest.raises(TelegramError) as error:
            telegram.call("getUpdates", {"timeout": 0}, sleep=lambda _: None)
    assert error.value.permanent
    assert error.value.status == 200
