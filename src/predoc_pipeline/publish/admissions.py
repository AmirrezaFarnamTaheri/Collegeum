"""Officially corroborated non-US Economics PhD programme announcements.

Admissions are NOT vacancies, and are never added to listings, X, or private
subscriber alerts. Reuse the existing public Telegram bot and an independent
append-preserving delivery ledger. When delivery is uncertain, fail closed;
never silently send the same programme again.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..logging_setup import get_logger
from .telegram import TelegramClient, TelegramError

log = get_logger(__name__)

MAX_EVIDENCE_AGE = timedelta(days=14)
MAX_DEADLINE_AHEAD = timedelta(days=366)
NEW_CYCLE_GAP = timedelta(days=180)
YEAR_IN_TEXT = re.compile(r"\b20\d{2}\b")
DEADLINE_CONTEXT = re.compile(r"\b(?:deadline|closes?|closing)\b", re.I)
ISO_DAY = re.compile(r"20\d{2}-\d{2}-\d{2}\Z")
COUNTRY_TLD_EXCEPTIONS = {"GB": "uk", "UK": "uk"}
SCHEMA_VERSION = 1


def _utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.astimezone(UTC) if stamp.tzinfo is not None else None


def _official_host(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    if (
        url.scheme != "https" or not url.hostname or
        url.username is not None or url.password is not None or
        url.port not in (None, 443)
    ):
        return None
    return url.hostname.lower().removeprefix("www.")


def _independently_non_us(row: dict[str, Any], official_host: str) -> bool:
    """Do not trust country from a third-party discovery list by itself.

    Country has to be non-US in the catalogue AND corroborated by a matching
    university-country domain. International .org/.com/.edu pages are held
    until another official-source country proof can be captured.
    """
    country = row.get("country_code")
    if not isinstance(country, str) or not re.fullmatch(r"[A-Z]{2}", country):
        return False
    if country == "US":
        return False
    suffix = COUNTRY_TLD_EXCEPTIONS.get(country, country.lower())
    return official_host.endswith("." + suffix)


def eligible_official_admissions(
    catalog: dict[str, Any], *, now: datetime,
) -> list[dict[str, Any]]:
    """Current verified university admissions only, never upstream assumptions."""
    if (
        catalog.get("kind") != "economics_phd_admissions_observations" or
        catalog.get("scope") != "official_programme_sources_only" or
        not isinstance(catalog.get("source"), dict) or
        catalog["source"].get("deadline_values_reused") is not False
    ):
        return []
    rows = catalog.get("programmes")
    if not isinstance(rows, list):
        return []
    qualified: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("status") != "verified":
            continue
        deadline_value = row.get("deadline_iso")
        if not isinstance(deadline_value, str) or ISO_DAY.fullmatch(deadline_value) is None:
            continue
        try:
            deadline = date.fromisoformat(deadline_value)
        except ValueError:
            continue
        if deadline < now.date() or deadline > (now + MAX_DEADLINE_AHEAD).date():
            continue
        verified_at = _utc_timestamp(row.get("checked_at"))
        if verified_at is None or verified_at > now or now - verified_at > MAX_EVIDENCE_AGE:
            continue
        programme_host = _official_host(row.get("official_programme_url"))
        evidence_host = _official_host(row.get("evidence_url"))
        if (
            programme_host is None or evidence_host != programme_host or
            not _independently_non_us(row, programme_host)
        ):
            continue
        excerpt = row.get("evidence_excerpt")
        institution = row.get("institution")
        if (
            not isinstance(excerpt, str) or
            not YEAR_IN_TEXT.search(excerpt) or
            deadline_value[:4] not in excerpt or
            not DEADLINE_CONTEXT.search(excerpt) or
            not isinstance(institution, str) or not institution.strip()
        ):
            continue
        qualified.append(row)
    return sorted(qualified, key=lambda r: (r["deadline_iso"], r["institution"].casefold()))


def _delivery_key(row: dict[str, Any]) -> str:
    # Stable programme identity across URL changes and minor deadline edits.
    identity = f"{row['country_code']}|{row['institution'].strip().casefold()}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _read_receipts(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": SCHEMA_VERSION, "deliveries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Unreadable PhD admission receipt journal; refuse to resend") from exc
    if not isinstance(payload, dict) or payload.get("version") != SCHEMA_VERSION:
        raise ValueError("Unknown PhD admission delivery journal version")
    entries = payload.get("deliveries")
    if not isinstance(entries, dict):
        raise ValueError("Malformed PhD admission delivery journal")
    for key, receipt in entries.items():
        if (
            not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{32}", key) or
            not isinstance(receipt, dict) or
            receipt.get("state") not in {
                "pending", "confirmed", "uncertain", "permanent_failure",
            }
        ):
            raise ValueError("Corrupted delivery receipt; hold all sends")
        if receipt["state"] == "confirmed" and (
            type(receipt.get("message_id")) is not int or receipt["message_id"] < 1
        ):
            raise ValueError("Missing confirmed Telegram message ID")
    return payload


def _checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _has_prior_send(
    receipt: dict[str, Any], *, deadline: date, now: datetime,
) -> bool:
    if receipt.get("state") != "confirmed":
        # Pending, uncertain, and permanently refused sends require operator
        # reconciliation; restarting a runner never authorizes retry.
        return True
    previous = receipt.get("deadline_iso")
    sent_at = _utc_timestamp(receipt.get("sent_at"))
    try:
        old_date = date.fromisoformat(previous) if isinstance(previous, str) else None
    except ValueError:
        old_date = None
    if old_date is None or sent_at is None or sent_at > now:
        return True
    return (
        deadline <= old_date or
        deadline - old_date < NEW_CYCLE_GAP or
        now - sent_at < NEW_CYCLE_GAP
    )


def _message(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    institution = escape(row["institution"][:170])
    country = escape(row["country_code"])
    deadline = date.fromisoformat(row["deadline_iso"]).strftime("%d %b %Y")
    checked = escape(row["checked_at"][:10])
    html = (
        "🎓 <b>PhD programme admission · Economics</b>\n"
        f"<b>{institution}</b> · {country}\n\n"
        f"📅 <b>Official application deadline: {deadline}</b>\n"
        f"🔎 Official source checked: {checked} UTC\n\n"
        "<i>General programme admission, not an employment vacancy. "
        "Funding and salary: not verified. Applications may not yet be open; "
        "confirm eligibility and current availability on the university page.</i>"
    )
    primary = row["evidence_url"]
    programme = row["official_programme_url"]
    keyboard = {"inline_keyboard": [
        [{"text": "University admissions", "url": primary}],
        *([[{"text": "Programme details", "url": programme}]] if programme != primary else []),
    ]}
    return html, keyboard


def publish_official_admissions(
    catalog_path: str | Path,
    receipt_path: str | Path,
    telegram: TelegramClient | None,
    *, chat_id: str, enabled: bool, max_messages: int = 2,
    now: datetime | None = None,
) -> int:
    """Bounded, separate announcements through the EXISTING Telegram channel.

    Never touches the vacancies database, published count, or private bot state.
    Failure to restore an existing receipt ledger aborts the send (fail closed).
    """
    if not enabled or telegram is None or not chat_id:
        return 0
    if not 1 <= max_messages <= 10:
        raise ValueError("Maximum 1..10 admissions per run")
    stamp = now or datetime.now(UTC)
    try:
        catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("telegram_admissions_catalog_unavailable", error=str(exc))
        return 0
    if not isinstance(catalog, dict):
        return 0
    # Restore BEFORE determining candidates: a corrupted journal is a hard
    # stop, not permission to resend entire history.
    ledger_path = Path(receipt_path)
    ledger = _read_receipts(ledger_path)
    candidates = eligible_official_admissions(catalog, now=stamp)
    sent = 0
    for row in candidates:
        if sent >= max_messages:
            break
        key = _delivery_key(row)
        previous = ledger["deliveries"].get(key)
        deadline = date.fromisoformat(row["deadline_iso"])
        if previous is not None and _has_prior_send(previous, deadline=deadline, now=stamp):
            continue
        attempt = {
            "state": "pending",
            "institution": row["institution"],
            "country_code": row["country_code"],
            "deadline_iso": row["deadline_iso"],
            "evidence_url": row["evidence_url"],
            "attempted_at": stamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        ledger["deliveries"][key] = attempt
        # Persist a hold before attempting a potentially accepted remote send.
        # The pipeline's normal checkpoint commit preserves the journal in git.
        _checkpoint(ledger_path, ledger)
        html, buttons = _message(row)
        try:
            message_id = telegram.send_message(
                chat_id=chat_id, html=html, keyboard=buttons,
            )
        except TelegramError as exc:
            if exc.uncertain:
                attempt["state"] = "uncertain"
            elif exc.permanent:
                attempt["state"] = "permanent_failure"
            else:
                # Known no-delivery rate limits can retry in a later cycle.
                ledger["deliveries"].pop(key, None)
            _checkpoint(ledger_path, ledger)
            log.warning("telegram_phd_admission_not_confirmed",
                        institution=row["institution"], uncertain=exc.uncertain,
                        error=str(exc))
            if exc.status in (401, 403, 404):
                break
            continue
        if type(message_id) is not int or message_id <= 0:
            attempt["state"] = "uncertain"
            _checkpoint(ledger_path, ledger)
            log.warning("telegram_phd_admission_invalid_receipt",
                        institution=row["institution"])
            continue
        attempt.update(
            state="confirmed", message_id=message_id,
            sent_at=stamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
        )
        _checkpoint(ledger_path, ledger)
        sent += 1
        log.info("telegram_phd_admission_published",
                 institution=row["institution"], deadline=row["deadline_iso"],
                 message_id=message_id)
    return sent
