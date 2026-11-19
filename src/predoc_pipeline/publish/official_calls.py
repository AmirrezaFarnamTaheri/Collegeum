"""Independent official PhD scholarship/fellowship Telegram channel announcements.

These are not automatically paid vacancies, do not enter the vacancy journal,
and must not inherit private subscription alerts. Stable per-call/cycle ledger
provides at-most-once attempts after potentially accepted Telegram requests.
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
MAX_AGE = timedelta(days=14)
MAX_AHEAD = timedelta(days=366)
KINDS = {"phd_scholarship", "phd_studentship", "phd_fellowship"}
DELIVERY_STATES = {"pending", "confirmed", "uncertain", "permanent_failure"}
TITLE_RE = re.compile(r"\bph\.?\s*d\.?\b|doctoral", re.I)
DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}\Z")


def call_key(row: dict[str, Any]) -> str:
    """Same official call in multiple institutional indexes maps to one post."""
    url = row["official_url"]
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    identity = f"{host}|{parsed.path.rstrip('/').lower()}|{row['intake_year']}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _stamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(UTC) if result.tzinfo else None


def _host(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password or port not in (None, 443)
            or parsed.query or parsed.fragment):
        return None
    return parsed.hostname.lower().removeprefix("www.")


def _location_verified(row: dict[str, Any], host: str) -> bool:
    country = row.get("country_code")
    if country not in {"UK", "GB", "ES", "DE", "FI", "FR", "NL", "IT",
                       "SE", "NO", "DK", "CH", "AT", "BE"}:
        return False
    location = row.get("location_evidence")
    if row.get("location_evidence_url") != row.get("official_url"):
        return False
    if not isinstance(location, str):
        return False
    national = "uk" if country in {"UK", "GB"} else country.lower()
    if host.endswith("." + national):
        return location == f"{country}: official national institutional domain {host}"
    # Exact same-source institutional address proof for IEB's generic .edu.
    return (
        country == "ES"
        and host == "ieb.ub.edu"
        and location == "ES: official postal address 08034 Barcelona and telephone +34"
    )


def eligible_calls(catalog: Any, *, now: datetime) -> list[dict[str, Any]]:
    """Only checked, official, open PhD scholarship/fellowship calls are eligible."""
    if (now.tzinfo is None or not isinstance(catalog, dict)
            or catalog.get("version") != 1
            or catalog.get("kind") != "official_phd_call_observations"
            or not isinstance(catalog.get("calls"), list)
            or len(catalog["calls"]) > 100):
        return []
    results: dict[str, dict[str, Any]] = {}
    for row in catalog["calls"]:
        if not isinstance(row, dict) or row.get("status") != "verified":
            continue
        if row.get("kind") not in KINDS or row.get("deadline_kind") not in {
            "scholarship", "funding",
        }:
            continue
        if not isinstance(row.get("intake_year"), int):
            continue
        if not now.year <= row["intake_year"] <= now.year + 2:
            continue
        verified = _stamp(row.get("checked_at"))
        if verified is None or verified > now or now - verified > MAX_AGE:
            continue
        if not isinstance(row.get("deadline_iso"), str) or not DATE_RE.fullmatch(
            row["deadline_iso"]
        ):
            continue
        try:
            deadline = date.fromisoformat(row["deadline_iso"])
        except ValueError:
            continue
        if not now.date() <= deadline <= (now + MAX_AHEAD).date():
            continue
        host = _host(row.get("official_url"))
        if host is None or _host(row.get("evidence_url")) != host:
            continue
        if row["official_url"] != row["evidence_url"]:
            continue
        if not _location_verified(row, host):
            continue
        excerpt = row.get("evidence_excerpt")
        title = row.get("title")
        if (not isinstance(title, str) or not TITLE_RE.search(title)
                or not isinstance(excerpt, str)
                or row["deadline_iso"][:4] not in excerpt
                or not re.search(r"\b(?:by|before|deadline|close|closing|due)\b",
                                 excerpt, re.I)):
            continue
        ident = call_key(row)
        # If a source unexpectedly emits the same identity with conflicting
        # deadlines, suppress both records rather than pick an arbitrary one.
        previous = results.get(ident)
        if previous and previous["deadline_iso"] != row["deadline_iso"]:
            results.pop(ident, None)
            continue
        results[ident] = row
    return sorted(results.values(), key=lambda row: (
        row["deadline_iso"], row["institution"], row["official_url"],
    ))


def _load_receipts(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "deliveries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Unreadable official-call ledger; no sends permitted") from exc
    if (not isinstance(data, dict) or data.get("version") != 1
            or not isinstance(data.get("deliveries"), dict)):
        raise ValueError("Invalid official-call ledger; no sends permitted")
    for key, receipt in data["deliveries"].items():
        if (not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{32}", key)
                or not isinstance(receipt, dict)
                or receipt.get("state") not in DELIVERY_STATES):
            raise ValueError("Corrupt official-call receipt; no sends permitted")
        if receipt["state"] == "confirmed" and (
            type(receipt.get("message_id")) is not int or receipt["message_id"] <= 0
        ):
            raise ValueError("Confirmed call receipt lacks message ID")
    return data


def _checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def _message(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    title = escape(row["title"][:140])
    institution = escape(row["institution"][:125])
    label = {"phd_studentship": "PhD studentship", "phd_fellowship": "PhD fellowship",
             "phd_scholarship": "PhD scholarship"}[row["kind"]]
    deadline = date.fromisoformat(row["deadline_iso"]).strftime("%d %b %Y")
    lines = [
        f"🎓 <b>{escape(label)} · Official institutional call</b>",
        f"<b>{title}</b>", institution, "",
        f"📍 {escape(row['country_code'])}",
        f"📅 <b>{'Funding' if row['deadline_kind'] == 'funding' else 'Call'} "
        f"deadline: {escape(deadline)}</b>",
    ]
    recommended = row.get("recommended_admission_iso")
    if isinstance(recommended, str) and DATE_RE.fullmatch(recommended):
        try:
            day = date.fromisoformat(recommended)
        except ValueError:
            day = None
        if day is not None:
            lines.append(
                "💡 Recommended PhD admission submission (not scholarship deadline): "
                + escape(day.strftime("%d %b %Y"))
            )
    if row["kind"] == "phd_studentship":
        lines.append("ℹ️ A prior PhD admission offer may be required; check the official terms.")
    lines.extend([
        "",
        "<i>This is an independent doctoral funding call, not necessarily "
        "a salaried job or an ordinary university admission deadline. "
        "Verify eligibility and funding conditions with the institution.</i>",
        f"🔎 Official call checked: {escape(row['checked_at'][:10])} UTC",
        "#PhD #Scholarships" + (
            " #Economics" if re.search(r"\beconomics?\b", row["title"], re.I) else ""
        ),
    ])
    keyboard = {"inline_keyboard": [[{
        "text": "Open official call",
        "url": row["official_url"],
    }]]}
    return "\n".join(lines), keyboard


def publish_official_calls(
    catalog_path: str | Path, receipt_path: str | Path,
    telegram: TelegramClient | None, *, chat_id: str,
    enabled: bool, max_messages: int = 2, now: datetime | None = None,
) -> int:
    """One bounded Telegram message per independent, source-verified call."""
    if not enabled or telegram is None or not chat_id:
        return 0
    if not 1 <= max_messages <= 10:
        raise ValueError("Official call publication must be limited to 1..10 messages")
    try:
        catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("telegram_official_calls_catalog_unavailable")
        return 0
    ledger_path = Path(receipt_path)
    ledger = _load_receipts(ledger_path)
    timestamp = now or datetime.now(UTC)
    sent = 0
    for row in eligible_calls(catalog, now=timestamp):
        if sent >= max_messages:
            break
        key = call_key(row)
        if key in ledger["deliveries"]:
            continue
        attempt = {
            "state": "pending", "title": row["title"],
            "institution": row["institution"], "deadline_iso": row["deadline_iso"],
            "official_url": row["official_url"], "intake_year": row["intake_year"],
            "attempted_at": timestamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        ledger["deliveries"][key] = attempt
        _checkpoint(ledger_path, ledger)  # Hold before any network send.
        message, keyboard = _message(row)
        try:
            receipt = telegram.send_message(chat_id=chat_id, html=message, keyboard=keyboard)
        except TelegramError as exc:
            if exc.uncertain:
                attempt["state"] = "uncertain"
            elif exc.permanent:
                attempt["state"] = "permanent_failure"
            else:
                # Only errors known not to have reached Telegram can be retried.
                ledger["deliveries"].pop(key, None)
            _checkpoint(ledger_path, ledger)
            log.warning("telegram_official_call_not_confirmed",
                        institution=row["institution"], uncertain=exc.uncertain)
            if exc.status in (401, 403, 404):
                break
            continue
        if type(receipt) is not int or receipt <= 0:
            attempt["state"] = "uncertain"
            _checkpoint(ledger_path, ledger)
            continue
        attempt.update(
            state="confirmed", message_id=receipt,
            sent_at=timestamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
        )
        _checkpoint(ledger_path, ledger)
        sent += 1
        log.info("telegram_official_call_published", message_id=receipt,
                 institution=row["institution"], deadline=row["deadline_iso"])
    return sent


def official_calls_health(
    catalog_path: str | Path, receipt_path: str | Path, *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Public-safe counts distinguish monitored sources from actual delivery."""
    checked = now or datetime.now(UTC)
    try:
        catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
        if not isinstance(catalog, dict) or not isinstance(catalog.get("sources"), list):
            raise ValueError("Invalid official call catalogue")
        ledger = _load_receipts(Path(receipt_path))
    except (OSError, json.JSONDecodeError, ValueError):
        return {"status": "unavailable", "eligible": None, "unpublished": None}
    eligible = eligible_calls(catalog, now=checked)
    delivered = ledger["deliveries"]
    backlog = sum(call_key(row) not in delivered for row in eligible)
    state_counts: dict[str, int] = {}
    for source in catalog["sources"]:
        raw_label = source.get("status") if isinstance(source, dict) else None
        label = raw_label if isinstance(raw_label, str) else "invalid"
        state_counts[label] = state_counts.get(label, 0) + 1
    confirmed = [receipt for receipt in delivered.values()
                 if receipt.get("state") == "confirmed" and receipt.get("sent_at")]
    last = max((item["sent_at"] for item in confirmed), default=None)
    uncertain = sum(1 for item in delivered.values() if item.get("state") == "uncertain")
    return {
        "status": "ok" if not any(k != "ok" for k in state_counts) else "degraded",
        "sources": state_counts,
        "eligible": len(eligible),
        "unpublished": backlog,
        "confirmed": len(confirmed),
        "uncertain": uncertain,
        "last_confirmed_at": last,
        "generated_at": catalog.get("generated_at"),
    }
