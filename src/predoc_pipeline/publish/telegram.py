"""Telegram broadcasting.

Corrections against the reviewed implementation, each of which is a real
failure mode rather than a style preference:

* **Retries no longer punish permanent errors.** A blanket
  ``retry_if_exception_type(HTTPStatusError)`` retries a 400 "can't parse
  entities" four times with exponential backoff, turning an instant, permanent
  failure into thirty wasted seconds. Only 429 and 5xx are retryable here.

* **429 honours the server.** Telegram returns ``parameters.retry_after``;
  ignoring it and sleeping a fixed two seconds invites a longer ban.

* **The 4096-character limit is measured after entity parsing**, as the API
  documents. Capping only the summary leaves a long institution name free to
  push the card over the limit; measuring raw HTML instead truncates far too
  early. ``telegram_visible_length`` uses a conservative UTF-16 budget on
  parsed text, preserving complete Unicode code points and HTML tags.

* **``disable_web_page_preview`` is deprecated** -- Bot API 7.0 replaced it
  with ``link_preview_options``. The old field is sent as a fallback for
  self-hosted Bot API servers pinned below 7.0.

* **Pacing is bounded and per-chat.** A flat ``sleep(1.2)`` after every send
  adds a minute of idle runner time to a fifty-message run; a monotonic
  token check sleeps only when a send is genuinely too soon.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from html import escape as escape_attribute
from typing import Any

import httpx

from ..core.textproc import (
    escape_telegram_html,
    hashtag,
    squish,
    telegram_visible_length,
    truncate_utf16,
)
from ..models import PredocListing
from .keyboards import LEGEND, feedback_row

__all__ = [
    "TelegramError",
    "TelegramClient",
    "render_card",
    "render_keyboard",
    "render_digest",
    "render_digest_pages",
    "render_digest_batches",
    "pack_html_blocks",
    "RenderedPage",
    "deadline_label",
]

MAX_MESSAGE_CHARS = 4096
SAFETY_CHARS = 64          # headroom for entity-parsing differences
MAX_SUMMARY_CHARS = 420
MIN_SEND_INTERVAL = 1.05   # Telegram allows ~1 message/second/chat
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class RenderedPage:
    start: int
    end: int
    html: str
    keyboard: dict[str, Any] | None = None


def pack_html_blocks(
    blocks: list[str], *, header: str = "", footer: str = "", page_size: int = 6,
) -> list[RenderedPage]:
    """Pack complete bounded blocks, retaining their exact input membership."""
    pages = []
    start = 0
    size = max(1, page_size)
    limit = MAX_MESSAGE_CHARS - SAFETY_CHARS
    while start < len(blocks):
        head = header if start == 0 else ""
        chosen: list[str] = []
        end = start
        while end < len(blocks) and len(chosen) < size:
            trial = head + "\n\n".join([*chosen, blocks[end]]) + footer
            if telegram_visible_length(trial) > limit:
                break
            chosen.append(blocks[end])
            end += 1
        if not chosen:
            raise ValueError(f"Telegram block {start + 1} cannot fit the message budget")
        body = head + "\n\n".join(chosen)
        if end == len(blocks):
            body += footer
        pages.append(RenderedPage(start, end, body))
        start = end
    return pages


def _field(text: str, limit: int) -> str:
    return escape_telegram_html(truncate_utf16(squish(text), limit))


class TelegramError(RuntimeError):
    """The Bot API rejected the request, or was unreachable."""

    def __init__(self, message: str, *, status: int | None = None, permanent: bool = False):
        super().__init__(message)
        self.status = status
        self.permanent = permanent


def _visa_badge(status: str) -> str:
    return {
        "explicit": "\u2705 stated",
        "inferred": "\U0001f7e1 likely",
        "unknown": "\u2753 unknown",
        "not_offered": "\u26a0\ufe0f not offered / eligibility restricted",
    }.get(status, "\u2753 unknown")


_HAS_YEAR = re.compile(r"(?:19|20)\d{2}|\d{1,2}/\d{1,2}/\d{2}\b")


def deadline_label(deadline: Any, note: str | None = None, *, relative: bool = True) -> str:
    """'15 Nov 2026', '15 Nov 2026 \u2014 3 days left', 'Rolling', '28 Feb (year not stated...)'."""
    from ..core.timeparse import parse_datetime, utcnow

    when = parse_datetime(deadline) if isinstance(deadline, str) else deadline
    if when is None:
        if note and "rolling" in note.lower():
            return "rolling"
        return f"not stated ({note})" if note else "rolling / not stated"
    if note and not _HAS_YEAR.search(note):
        # e.g. PREDOC.org "Deadline: Feb 28" -- could be last year's cycle
        return f"{when:%d %b} (year not stated \u2014 check the ad)"
    days = (when.date() - utcnow().date()).days
    stamp = when.strftime("%d %b %Y")
    if not relative:
        return stamp
    if days < 0:
        return f"{stamp} (closed)"
    if days == 0:
        return f"{stamp} \u2014 today"
    if days <= 7:
        return f"{stamp} \u2014 {days} day{'s' if days != 1 else ''} left"
    return stamp


def _deadline_line(listing: PredocListing) -> str:
    return deadline_label(listing.deadline, listing.deadline_note)


def _detect_situation(listing: PredocListing) -> str:
    if listing.location.is_remote:
        return "Remote"
    blob = (
        f"{listing.title} {listing.summary} "
        f"{listing.location.city} {listing.location.country}"
    ).lower()
    if "hybrid" in blob:
        return "Hybrid"
    if listing.location.city or listing.location.country:
        return "On-site"
    return "not stated"


def _format_requirements(listing: PredocListing) -> str | None:
    parts = []
    tools: list[str] = []
    legacy_tools = getattr(listing, "tools", None)
    if getattr(listing, "tools_required", None):
        tools.extend(listing.tools_required)
    elif legacy_tools:
        tools.extend(legacy_tools)
    if getattr(listing, "tools_preferred", None):
        pref = [t for t in listing.tools_preferred if t not in tools]
        if pref:
            tools.extend(f"{p} (preferred)" for p in pref)
    if tools:
        parts.append(", ".join(tools))
    deg = getattr(listing, "min_degree", None)
    if deg and deg.lower() not in ("unstated", "none"):
        deg_map = {"bachelors": "Bachelor's", "masters": "Master's", "phd": "PhD"}
        deg_label = deg_map.get(deg.lower(), deg.title())
        parts.append(f"{deg_label} degree")
    return "; ".join(parts) if parts else None


def _format_other(listing: PredocListing) -> str | None:
    notes: list[str] = []
    if listing.visa_note:
        notes.append(listing.visa_note)
    deg_note = getattr(listing, "degree_note", None)
    min_deg = getattr(listing, "min_degree", None)
    if deg_note and deg_note != min_deg and deg_note not in notes:
        notes.append(deg_note)
    summary_lower = (listing.summary or "").lower()
    for pattern, label in (
        (r"\bwomen\s+only\b|\bonly\s+women\b", "Woman Only"),
        (
            r"\b(?:women|female)\s+candidates?\s+(?:are\s+)?(?:strongly\s+)?encouraged\b",
            "Women encouraged",
        ),
        (
            r"\b(?:underrepresented|minority)\s+candidates?\s+(?:are\s+)?(?:strongly\s+)?encouraged\b",
            "Diversity initiative",
        ),
        (r"\bcitizens?\s+only\b|\bnationals?\s+only\b", "Citizens/Residents only"),
    ):
        if re.search(pattern, summary_lower) and label not in notes:
            notes.append(label)
    return "; ".join(notes) if notes else None


def render_card(listing: PredocListing) -> str:
    """One vacancy as an enriched Telegram HTML card, guaranteed under the length limit."""
    esc = escape_telegram_html
    location_bits = [b for b in (listing.location.city, listing.location.country) if b]
    location = ", ".join(location_bits) or "not stated"

    duration = (
        f"{listing.duration_years:g} year{'s' if listing.duration_years != 1 else ''}"
        if listing.duration_years
        else "not stated"
    )

    situation = _detect_situation(listing)
    requirements = _format_requirements(listing)
    other = _format_other(listing)

    lines = [
        f"🎓 <b>{_field(listing.title, 140)}</b>",
        f"<i>{_field(listing.institution, 120)}</i>",
    ]
    if listing.principal_investigator:
        lines.append(f"👤 {_field(listing.principal_investigator, 80)}")
    lines.append("")
    lines.extend([
        f"📍 {_field(location, 160)}",
        f"🔬 {_field(', '.join(d.value for d in listing.disciplines), 160)}",
        f"⏳ {esc(duration)}",
        f"📅 <b>{_field(_deadline_line(listing), 120)}</b>",
        f"🛂 visa: {_visa_badge(listing.visa_sponsorship_status.value)}",
        f"Situation: {esc(situation)}",
    ])
    if requirements:
        lines.append(f"Requirements: {_field(requirements, 200)}")
    salary = getattr(listing, "salary_raw", None)
    if salary:
        lines.append(f"💰 Compensation: {_field(salary, 200)}")
    start = getattr(listing, "start_term", None) or getattr(listing, "start_date", None)
    if start:
        lines.append(f"🗓 Start: {_field(start, 100)}")
    if other:
        lines.append(f"Other: {_field(other, 140)}")

    tags = [
        hashtag(listing.disciplines[0].value) if listing.disciplines else "",
        hashtag(listing.location.country),
        "Predoc",
    ]
    tag_line = " ".join(f"#{t}" for t in tags if t)

    # Build the body last and size it against what remains of the budget.
    fixed = "\n".join(lines) + "\n\n\n" + tag_line
    budget = MAX_MESSAGE_CHARS - SAFETY_CHARS - telegram_visible_length(fixed)
    summary_budget = max(0, min(MAX_SUMMARY_CHARS, budget))
    summary = truncate_utf16(squish(listing.summary), summary_budget) if summary_budget > 40 else ""

    body = "\n".join(lines)
    if summary:
        body += f"\n\n{esc(summary)}"
    body += f"\n\n{tag_line}"

    return body


def render_keyboard(
    listing: PredocListing,
    *,
    url_hash: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Inline buttons. The apply button is only shown when it means something.

    When the model found no application URL, ``apply_url`` falls back to the
    discovery URL. Labelling that "Apply" would be a lie, so a single "Open"
    button is shown instead of two buttons pointing at the same page.

    With ``url_hash`` a second row of ✅ ❌ 📝 buttons is added (personal bots).
    """
    if listing.apply_url and listing.apply_url != listing.source_url:
        rows = [
            [
                {"text": "Apply", "url": listing.apply_url},
                {"text": "Source", "url": listing.source_url},
            ]
        ]
    else:
        rows = [[{"text": "Open listing", "url": listing.source_url}]]
    if url_hash:
        rows.append(feedback_row(url_hash, status))
    return {"inline_keyboard": rows}


def render_digest(listings: list[PredocListing], *, site_url: str = "") -> str:
    """Compact multi-listing message for high-volume runs and backfills."""
    header = f"\U0001f393 <b>{len(listings)} new predoc listings</b>"
    footer = (
        f'\n\n<a href="{escape_attribute(site_url, quote=True)}">Browse and filter all listings</a>'
        if site_url else ""
    )
    rows = []
    for listing in listings:
        where = listing.location.country or "\u2014"
        deadline = listing.deadline.strftime("%d %b") if listing.deadline else "rolling"
        rows.append(
            f'\u2022 <a href="{escape_attribute(listing.apply_url, quote=True)}">'
            f"{_field(listing.title, 70)}</a>\n"
            f"  {_field(listing.institution, 60)} \u00b7 {_field(where, 100)} "
            f"\u00b7 closes {_field(deadline, 40)}"
        )
    body = header + "\n\n" + "\n".join(rows) + footer
    while telegram_visible_length(body) > MAX_MESSAGE_CHARS - SAFETY_CHARS and rows:
        rows.pop()
        omitted = len(listings) - len(rows)
        body = (header + "\n\n" + "\n".join(rows)
                + f"\n\u2026{omitted} more listings omitted from this preview." + footer)
    return body


def render_digest_batches(
    listings: list[tuple[str, PredocListing]],
    *,
    site_url: str = "",
    page_size: int = 6,
    feedback: bool = True,
    status_of: Any = None,
) -> list[RenderedPage]:
    """Many new listings as a few numbered messages, each with ✅ ❌ 📝 rows.

    ``listings`` is ``[(url_hash, listing), ...]``. Numbering continues across
    messages, so "📝 7" always means the seventh position of this batch.
    """
    esc = escape_telegram_html
    status_of = status_of or (lambda _h: None)
    total = len(listings)
    blocks = []
    for i, (_, listing) in enumerate(listings, 1):
        where = ", ".join(b for b in (listing.location.city, listing.location.country) if b)
        place = f" — {_field(where, 120)}" if where else ""
        blocks.append(
            f"<b>{i}. {_field(listing.title, 110)}</b>\n"
            f"🏛 {_field(listing.institution, 90)}{place}\n"
            f"📅 {_field(deadline_label(listing.deadline, listing.deadline_note), 120)}"
            f' · <a href="{escape_attribute(listing.apply_url, quote=True)}">open ad</a>'
        )
    head = f"🎓 <b>{total} new predoc listing{'s' if total != 1 else ''}</b>\n\n"
    footer = ""
    if site_url:
        footer += (f'\n\n<a href="{escape_attribute(site_url, quote=True)}">'
                   'Browse and filter all listings</a>')
    if feedback:
        footer += f"\n\n<i>{esc(LEGEND)}</i>"
    pages = []
    for page in pack_html_blocks(blocks, header=head, footer=footer,
                                 page_size=min(page_size, 30)):
        chunk = listings[page.start:page.end]
        keyboard = None
        if feedback:
            keyboard = {"inline_keyboard": [
                feedback_row(h, status_of(h), i) for i, (h, _) in enumerate(chunk, page.start + 1)
            ]}
        pages.append(RenderedPage(page.start, page.end, page.html, keyboard))
    return pages


def render_digest_pages(
    listings: list[tuple[str, PredocListing]], **kwargs: Any,
) -> list[tuple[str, dict[str, Any] | None]]:
    """Compatibility surface for callers that only need text and buttons."""
    return [(page.html, page.keyboard) for page in render_digest_batches(listings, **kwargs)]


@dataclass
class TelegramClient:
    """Minimal Bot API client with correct rate-limit and retry semantics."""

    bot_token: str
    timeout: float = 20.0
    max_attempts: int = 4
    client: httpx.Client | None = None
    link_previews: bool = False
    _last_send: dict[str, float] = field(default_factory=dict)
    _owns_client: bool = False

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = httpx.Client(timeout=self.timeout)
            self._owns_client = True

    def close(self) -> None:
        if self._owns_client and self.client is not None:
            self.client.close()

    def __enter__(self) -> TelegramClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _pace(self, chat_id: str, sleep: Callable[[float], None] = time.sleep) -> None:
        elapsed = time.monotonic() - self._last_send.get(chat_id, 0.0)
        if elapsed < MIN_SEND_INTERVAL:
            sleep(MIN_SEND_INTERVAL - elapsed)

    def send_message(
        self,
        *,
        chat_id: str,
        html: str,
        keyboard: dict[str, Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> int:
        """Send one HTML message. Returns the Telegram message id."""
        if not self.bot_token or not chat_id:
            raise TelegramError("missing bot token or chat id", permanent=True)

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": html,
            "parse_mode": "HTML",
            # Bot API 7.0+ field, plus the pre-7.0 name for older self-hosted
            # Bot API servers. Unknown fields are ignored by the API.
            "link_preview_options": {"is_disabled": not self.link_previews},
            "disable_web_page_preview": not self.link_previews,
        }
        if keyboard:
            payload["reply_markup"] = keyboard

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        last: TelegramError | None = None

        for attempt in range(self.max_attempts):
            self._pace(chat_id, sleep=sleep)
            try:
                response = self.client.post(url, json=payload)  # type: ignore[union-attr]
            except httpx.RequestError as exc:
                last = TelegramError(f"transport error: {exc}")
                sleep(min(2**attempt, 15))
                continue

            if response.status_code == 200:
                self._last_send[chat_id] = time.monotonic()
                try:
                    return int(response.json()["result"]["message_id"])
                except (KeyError, ValueError, TypeError) as exc:
                    raise TelegramError(f"unexpected success payload: {exc}") from exc

            detail = response.text[:300]
            if response.status_code == 429:
                retry_after = 5.0
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        params = data.get("parameters")
                        if isinstance(params, dict) and "retry_after" in params:
                            retry_after = float(params["retry_after"])
                except (ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError):
                    pass
                # The server told us how long to wait; local guesses lose.
                sleep(retry_after + 0.5)
                self._last_send[chat_id] = time.monotonic()
                last = TelegramError(f"429: {detail}", status=429)
                continue

            if response.status_code not in _RETRYABLE_STATUS:
                # 400 "can't parse entities", 403 "bot was blocked": retrying
                # these changes nothing and delays the rest of the run.
                raise TelegramError(
                    f"{response.status_code}: {detail}",
                    status=response.status_code,
                    permanent=True,
                )

            last = TelegramError(f"{response.status_code}: {detail}", status=response.status_code)
            sleep(min(2**attempt, 15))

        raise last or TelegramError("send failed")

    def call(
        self, method: str, payload: dict[str, Any], *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> Any:
        """Any other Bot API method (getUpdates, answerCallbackQuery...). Returns ``result``."""
        url = f"https://api.telegram.org/bot{self.bot_token}/{method}"
        last: TelegramError | None = None
        for attempt in range(self.max_attempts):
            try:
                response = self.client.post(url, json=payload)  # type: ignore[union-attr]
            except httpx.RequestError as exc:
                last = TelegramError(f"transport error: {exc}")
                sleep(min(2**attempt, 15))
                continue
            try:
                data = response.json()
            except ValueError:
                data = {}
            if response.status_code == 200 and data.get("ok"):
                return data.get("result")
            detail = str(data.get("description") or response.text[:300])
            if response.status_code == 429:
                retry_after = float((data.get("parameters") or {}).get("retry_after", 5))
                sleep(min(retry_after, 60) + 0.5)
                last = TelegramError(f"429: {detail}", status=429)
                continue
            if response.status_code not in _RETRYABLE_STATUS:
                raise TelegramError(f"{method} {response.status_code}: {detail}",
                                    status=response.status_code, permanent=True)
            last = TelegramError(f"{response.status_code}: {detail}", status=response.status_code)
            sleep(min(2**attempt, 15))
        raise last or TelegramError(f"{method} failed")

    def send_plain(
        self, *, chat_id: str, text: str, sleep: Callable[[float], None] = time.sleep,
    ) -> int:
        """Escaped plain-text send. Used for operational alerts."""
        return self.send_message(
            chat_id=chat_id, html=escape_telegram_html(text), sleep=sleep
        )
