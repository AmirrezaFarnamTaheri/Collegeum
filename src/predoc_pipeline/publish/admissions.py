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
                "reissue_authorized",
            }
        ):
            raise ValueError("Corrupted delivery receipt; hold all sends")
        if receipt["state"] == "confirmed" and (
            type(receipt.get("message_id")) is not int or receipt["message_id"] < 1
        ):
            raise ValueError("Missing confirmed Telegram message ID")
        if receipt["state"] == "reissue_authorized" and (
            type(receipt.get("prior_message_id")) is not int
            or receipt["prior_message_id"] < 1
        ):
            raise ValueError("Missing removed message ID for authorized reissue")
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
    if receipt.get("state") == "reissue_authorized":
        # A named operator confirmed removal of the exact prior message ID.
        # A new pending checkpoint is recorded BEFORE any Telegram send.
        return False
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


COUNTRY_NAMES = {
    "AT": "Austria", "AU": "Australia", "BE": "Belgium",
    "CA": "Canada", "CH": "Switzerland", "CL": "Chile", "CN": "China",
    "CZ": "Czechia", "DE": "Germany", "DK": "Denmark", "ES": "Spain",
    "FI": "Finland", "FR": "France", "GR": "Greece", "HK": "Hong Kong",
    "IE": "Ireland", "IT": "Italy", "JP": "Japan",
    "KR": "South Korea", "MY": "Malaysia", "NL": "Netherlands",
    "NO": "Norway", "NZ": "New Zealand", "PH": "Philippines",
    "PL": "Poland", "PT": "Portugal", "RS": "Serbia",
    "SE": "Sweden", "SG": "Singapore", "TH": "Thailand",
    "TW": "Taiwan", "UK": "United Kingdom", "US": "United States",
    "ZA": "South Africa",
}


def _verified_detail(row: dict[str, Any], field: str) -> str | None:
    """Never echo a claimed fact without fresh same-university evidence."""
    details = row.get("official_details")
    if not isinstance(details, dict):
        return None
    fact = details.get(field)
    if not isinstance(fact, dict):
        return None
    value = fact.get("value")
    if not isinstance(value, str) or not value.strip():
        return None
    checked = row.get("checked_at")
    if fact.get("checked_at") != checked:
        return None
    host = _official_host(row.get("official_programme_url"))
    if not host or _official_host(fact.get("evidence_url")) != host:
        return None
    if not isinstance(fact.get("evidence_excerpt"), str):
        return None
    if not fact["evidence_excerpt"].strip():
        return None
    return value.strip()[:175]


def _message(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Native Collegeum-style card; admissions remain distinct from vacancies."""
    institution = escape(row["institution"][:140])
    country = COUNTRY_NAMES.get(row["country_code"], row["country_code"])
    deadline = date.fromisoformat(row["deadline_iso"]).strftime("%d %b %Y")
    checked = escape(row["checked_at"][:10])
    lines = [
        "🎓 <b>PhD programme admission · Economics</b>",
        f"<i>{institution}</i>",
        "",
        f"📍 {escape(country)}",
        "🔬 Economics",
    ]
    duration = _verified_detail(row, "duration")
    if duration:
        lines.append("⏳ " + escape(duration))
    lines.append(f"📅 <b>{escape(deadline)}</b>")
    opening = _verified_detail(row, "application_open_iso")
    if opening:
        try:
            date_label = date.fromisoformat(opening).strftime("%d %b %Y")
            lines.append("🗓 Opens: " + escape(date_label))
        except ValueError:
            pass
    language = _verified_detail(row, "language")
    if language:
        lines.append("🗣 Language: " + escape(language))
    entry = _verified_detail(row, "entry_requirement")
    if entry:
        lines.append("🎓 Entry: " + escape(entry))
    funding = _verified_detail(row, "funding_note")
    if funding:
        lines.append("💰 Funding: " + escape(funding))
    else:
        lines.append("💰 Funding: not verified")
    stipend = _verified_detail(row, "stipend")
    if stipend:
        lines.append("💶 Stipend: " + escape(stipend))
    tuition = _verified_detail(row, "tuition")
    if tuition:
        lines.append("🏛 Tuition: " + escape(tuition))
    semester_fee = _verified_detail(row, "semester_fee")
    if semester_fee:
        lines.append("💳 Other fees: " + escape(semester_fee))
    tests = _verified_detail(row, "tests")
    if tests:
        lines.append("📝 Tests: " + escape(tests))
    references = _verified_detail(row, "references")
    if references:
        lines.append("✉️ References: " + escape(references))
    lines.append("🛂 Visa: not verified")
    lines.extend([
        "",
        "<i>General PhD admission, not an employment vacancy. "
        "Funding and eligibility depend on official university terms; "
        "the application portal may not be open yet.</i>",
        f"🔎 Official university source checked: {checked} UTC",
        "",
        f"#Economics #{''.join(country.split())} #PhD #Admissions",
    ])
    html = "\n".join(lines)
    primary = row["evidence_url"]
    programme = row["official_programme_url"]
    keyboard = {"inline_keyboard": [
        [{"text": "Official admissions", "url": primary}],
        *([[{"text": "Programme details", "url": programme}]] if programme != primary else []),
    ]}
    return html, keyboard



def authorize_reissue(
    receipt_path: str | Path, *, institution: str, country_code: str,
    original_message_id: int, deleted_confirmed: bool,
    now: datetime | None = None,
) -> None:
    """Allow one replacement only after an operator confirms *actual* removal.

    A future intention to delete a message is not confirmation. This method
    never calls Telegram and does not reset any other programme's receipt.
    """
    if not deleted_confirmed:
        raise ValueError("Do not reissue before the old channel post is deleted")
    if type(original_message_id) is not int or original_message_id < 1:
        raise ValueError("Expected positive original Telegram message ID")
    ledger_path = Path(receipt_path)
    ledger = _read_receipts(ledger_path)
    key = _delivery_key({"institution": institution, "country_code": country_code})
    old = ledger["deliveries"].get(key)
    if not isinstance(old, dict) or old.get("state") != "confirmed":
        raise ValueError("Only a confirmed delivery can be replaced")
    if old.get("message_id") != original_message_id:
        raise ValueError("Message ID differs; never replace another post")
    stamp = (now or datetime.now(UTC)).isoformat(
        timespec="seconds",
    ).replace("+00:00", "Z")
    history = list(old.get("history", []))
    history.append({
        "message_id": original_message_id,
        "deleted_confirmed_at": stamp,
        "state": "operator_confirmed_removed",
    })
    old["state"] = "reissue_authorized"
    old["prior_message_id"] = original_message_id
    old["reissue_authorized_at"] = stamp
    old["history"] = history
    _checkpoint(ledger_path, ledger)


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
        if previous is not None and previous.get("state") == "reissue_authorized":
            attempt["replaces_message_id"] = previous["prior_message_id"]
            attempt["history"] = list(previous.get("history", []))
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
                # Known no-delivery rate limits can retry later. For an
                # authorised reissue, never discard the prior-message audit.
                if previous is not None and previous.get("state") == "reissue_authorized":
                    ledger["deliveries"][key] = previous
                else:
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
