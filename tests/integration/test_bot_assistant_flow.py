"""End-to-end Telegram polling regression tests for grounded database chat.

These exercise getUpdates, identity checks, durable private state, OpenRouter
intent parsing, sendMessage and update-cursor replay together.
"""

import json

import httpx
import pytest

from predoc_pipeline.publish.feedback import FeedbackStore, load_state, save_state
from tests.integration.test_bot import FakeTelegram, add_listings, msg, run_sync
from tests.integration.test_bot import settings as bot_settings

settings = bot_settings


class AssistantTelegram(FakeTelegram):
    """Telegram transport with an isolated, deterministic OpenRouter endpoint."""

    def __init__(self, updates):
        super().__init__(updates)
        self.provider_calls = 0
        self.interrupt_provider = False
        self.tool_arguments = {"action": "count"}

    def handler(self, request):
        if request.url.host == "openrouter.ai":
            self.provider_calls += 1
            if self.interrupt_provider:
                raise KeyboardInterrupt("simulated process termination during provider call")
            return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [{
                "function": {"name": "query_database",
                             "arguments": json.dumps(self.tool_arguments)},
            }]}}]})
        return super().handler(request)


def public_message(update_id, text, *, user_id=101):
    return {"update_id": update_id, "message": {
        "message_id": update_id,
        "chat": {"id": user_id, "type": "private"},
        "from": {"id": user_id},
        "text": text,
    }}


def test_owner_question_reply_and_replayed_polling_update_use_one_result(settings):
    add_listings(settings)
    settings.openrouter_api_key = "offline-only"
    fake = AssistantTelegram([msg(70, "/ask Count open roles")])

    first = run_sync(settings, fake)
    assert first["commands"] == 1
    assert fake.provider_calls == 1
    assert "matching record" in fake.sent()[0]["text"]
    assert "Snapshot:" in fake.sent()[0]["text"]

    store = FeedbackStore(settings.feedback_path)
    assert store.data["assistant_replies"]["42:70"]["stage"] == "sent"

    # Simulate lost update-cursor checkpoint after reply delivery.
    cursor = load_state(settings.telegram_state_path)
    cursor["offset"] = 70
    save_state(settings.telegram_state_path, cursor)
    second = run_sync(settings, fake)
    assert second["failed"] == 0
    assert fake.provider_calls == 1
    assert len(fake.sent()) == 1
    assert load_state(settings.telegram_state_path)["offset"] == 71


def test_public_query_is_grounded_but_owner_browsing_is_not_exposed(settings):
    add_listings(settings)
    settings.openrouter_api_key = "offline-only"
    fake = AssistantTelegram([
        public_message(80, "/positions"),
        public_message(81, "/ask Count open roles"),
        public_message(82, "/forget"),
    ])

    summary = run_sync(settings, fake)
    assert summary["failed"] == 0
    assert fake.provider_calls == 1
    assert len(fake.sent()) == 2
    assert "matching record" in fake.sent()[0]["text"]
    assert "follow-up context has been cleared" in fake.sent()[1]["text"]
    assert FeedbackStore(settings.feedback_path).data["assistant_queries"] == {}


def test_crash_between_quota_reservation_and_provider_response_is_idempotent(settings):
    add_listings(settings)
    settings.openrouter_api_key = "offline-only"
    fake = AssistantTelegram([public_message(90, "/ask Count open roles")])
    fake.interrupt_provider = True

    with pytest.raises(KeyboardInterrupt, match="simulated process termination"):
        run_sync(settings, fake)

    persisted = FeedbackStore(settings.feedback_path)
    assert len(persisted.data["assistant_usage"]["public"]) == 1
    assert persisted.data["assistant_usage"]["reservations"]["101:90"]["denial"] is None

    fake.interrupt_provider = False
    result = run_sync(settings, fake)
    assert result["failed"] == 0
    assert fake.provider_calls == 2
    assert len(fake.sent()) == 1
    assert len(FeedbackStore(settings.feedback_path).data["assistant_usage"]["public"]) == 1
    assert FeedbackStore(settings.feedback_path).data["assistant_replies"]["101:90"]["stage"] == "sent"
