"""Integration tests for the Telegram Bot API client.

Skipped when httpx/pydantic/respx are unavailable. Covers the three behaviours
that were wrong in the reviewed implementation: retrying permanent errors,
ignoring the server's requested backoff on 429, and measuring message length
before entity parsing rather than after.
"""

from __future__ import annotations

import unittest

try:
    import httpx
    import respx

    from predoc_pipeline.core.timeparse import parse_datetime
    from predoc_pipeline.models import Discipline, Location, PredocListing, VisaStatus
    from predoc_pipeline.publish.telegram import (
        TelegramClient,
        TelegramError,
        render_card,
        render_keyboard,
    )

    DEPS_AVAILABLE = True
except ImportError:
    DEPS_AVAILABLE = False

# See test_extraction.py for why this alias exists: `@respx_mock` is evaluated
# at class-body-execution time, before `unittest.skipUnless` can act, so a
# bare `@respx_mock` would raise NameError whenever respx is not installed.
if DEPS_AVAILABLE:
    respx_mock = respx.mock
else:  # pragma: no cover - exercised only when the optional deps are absent
    def respx_mock(func):
        return func


def _sleeps() -> tuple[list, callable]:
    calls: list = []
    return calls, calls.append


@unittest.skipUnless(DEPS_AVAILABLE, "requires httpx, respx and pydantic")
class TestTelegramClient(unittest.TestCase):
    @respx_mock
    def test_success_returns_message_id(self):
        respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 55}})
        )
        client = TelegramClient(bot_token="token")
        message_id = client.send_message(chat_id="@chan", html="hi")
        self.assertEqual(message_id, 55)

    @respx_mock
    def test_permanent_400_raises_without_retry(self):
        route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
            return_value=httpx.Response(
                400, json={"ok": False, "description": "can't parse entities"}
            )
        )
        client = TelegramClient(bot_token="token")
        sleeps, sleep_fn = _sleeps()
        with self.assertRaises(TelegramError) as ctx:
            client.send_message(chat_id="@chan", html="<b>bad", sleep=sleep_fn)
        self.assertTrue(ctx.exception.permanent)
        self.assertEqual(route.call_count, 1)
        self.assertEqual(sleeps, [])

    @respx_mock
    def test_429_honours_server_retry_after(self):
        route = respx.post("https://api.telegram.org/bottoken/sendMessage")
        route.side_effect = [
            httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 7}}),
            httpx.Response(200, json={"ok": True, "result": {"message_id": 9}}),
        ]
        client = TelegramClient(bot_token="token")
        sleeps, sleep_fn = _sleeps()
        message_id = client.send_message(chat_id="@chan", html="hi", sleep=sleep_fn)
        self.assertEqual(message_id, 9)
        # The server's 7-second instruction must be used, not a fixed guess.
        self.assertTrue(any(s >= 7 for s in sleeps))

    @respx_mock
    def test_5xx_is_uncertain_and_not_replayed(self):
        route = respx.post("https://api.telegram.org/bottoken/sendMessage")
        route.mock(return_value=httpx.Response(500, text="internal error"))
        client = TelegramClient(bot_token="token")
        _, sleep_fn = _sleeps()
        with self.assertRaises(TelegramError) as error:
            client.send_message(chat_id="@chan", html="hi", sleep=sleep_fn)
        self.assertTrue(error.exception.uncertain)
        self.assertEqual(route.call_count, 1)

    @respx_mock
    def test_link_preview_options_and_legacy_field_both_sent(self):
        route = respx.post("https://api.telegram.org/bottoken/sendMessage").mock(
            return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        )
        client = TelegramClient(bot_token="token")
        client.send_message(chat_id="@chan", html="hi")
        body = route.calls.last.request.content
        import json as _json

        payload = _json.loads(body)
        self.assertIn("link_preview_options", payload)
        self.assertIn("disable_web_page_preview", payload)
        self.assertTrue(payload["link_preview_options"]["is_disabled"])


@unittest.skipUnless(DEPS_AVAILABLE, "requires httpx and pydantic")
class TestCardRendering(unittest.TestCase):
    def _listing(self, **overrides) -> PredocListing:
        values = dict(
            title="Predoctoral Research Fellow" * 3,  # deliberately long
            institution="A University With An Extremely Long Official Name" * 2,
            principal_investigator="Prof. Ada Lovelace",
            location=Location(country="United Kingdom", city="London", is_remote=False),
            duration_years=2.0,
            deadline=parse_datetime("2027-03-01"),
            disciplines=[Discipline.APPLIED_MICRO],
            visa_sponsorship_status=VisaStatus.INFERRED,
            summary="A very long summary. " * 60,  # force truncation
            language="en",
            apply_url="https://example.org/apply",
            source_url="https://example.org/source",
            model_confidence=0.9,
            rule_score=0.8,
            confidence=0.87,
        )
        values.update(overrides)
        return PredocListing(**values)

    def test_card_never_exceeds_message_limit(self):
        from predoc_pipeline.core.textproc import telegram_visible_length

        card = render_card(self._listing())
        self.assertLessEqual(telegram_visible_length(card), 4096)

    def test_keyboard_uses_open_when_apply_equals_source(self):
        listing = self._listing(apply_url="https://example.org/x", source_url="https://example.org/x")
        keyboard = render_keyboard(listing)
        buttons = keyboard["inline_keyboard"][0]
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0]["text"], "Open listing")

    def test_keyboard_offers_apply_and_source_when_distinct(self):
        listing = self._listing(apply_url="https://example.org/apply", source_url="https://example.org/src")
        keyboard = render_keyboard(listing)
        labels = [b["text"] for b in keyboard["inline_keyboard"][0]]
        self.assertEqual(labels, ["Apply", "Source"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
