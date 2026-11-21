"""Independent official PhD scholarship/fellowship Telegram channel announcements.

These are not automatically paid vacancies, do not enter the vacancy journal,
and must not inherit private subscription alerts. Stable per-call/cycle ledger
provides at-most-once attempts after potentially accepted Telegram requests.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..core.official_call_rules import call_key, group_members, group_signature, receipt_key
from ..logging_setup import get_logger
from .telegram import TelegramClient, TelegramError
from .telegram_intents import enforce_production_outcome, enforce_production_reservation

log = get_logger(__name__)
MAX_AGE = timedelta(days=14)
MAX_AHEAD = timedelta(days=366)
KINDS = {"phd_scholarship", "phd_studentship", "phd_fellowship", "phd_bursary"}
DELIVERY_STATES = {
    "pending", "confirmed", "uncertain", "permanent_failure", "retry_held",
}
TITLE_RE = re.compile(r"\bph\.?\s*d\.?\b|doctoral", re.I)
DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}\Z")


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
    conflicting: set[str] = set()
    for row in catalog["calls"]:
        if not isinstance(row, dict) or row.get("status") != "verified":
            continue
        if row.get("kind") not in KINDS or row.get("deadline_kind") not in {
            "scholarship", "funding",
        }:
            continue
        if type(row.get("intake_year")) is not int:
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
        recommended = row.get("recommended_admission_iso")
        if recommended is not None:
            if not isinstance(recommended, str) or not DATE_RE.fullmatch(recommended):
                continue
            try:
                application_day = date.fromisoformat(recommended)
            except ValueError:
                continue
            if application_day > deadline:
                continue
        institution = row.get("institution")
        if not isinstance(institution, str) or not 5 <= len(institution) <= 120:
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
        # Any inconsistent observation for one canonical identity makes
        # every duplicate unpublishable, even if a third entry agrees later.
        if ident in conflicting:
            continue
        previous = results.get(ident)
        stable = ("deadline_iso", "deadline_kind", "kind",
                  "institution", "country_code", "title")
        if previous and any(previous.get(field) != row.get(field) for field in stable):
            conflicting.add(ident)
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
             "phd_scholarship": "PhD scholarship", "phd_bursary": "PhD bursary"}[row["kind"]]
    deadline = date.fromisoformat(row["deadline_iso"]).strftime("%d %b %Y")
    # Broad university-wide schemes must not be tagged Economics-only.
    scope = row.get("subject_scope")
    if scope not in {"economics", "finance", "multidisciplinary"}:
        if re.search(r"\b(?:economics?|econometrics?)\b", row["title"], re.I):
            scope = "economics"
        elif re.search(r"\b(?:finance|accounting|accountancy)\b", row["title"], re.I):
            scope = "finance"
    tags = "#PhD #Scholarships"
    if scope == "economics":
        tags += " #Economics"
    elif scope == "finance":
        tags += " #Finance"
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
    elif row["kind"] == "phd_bursary":
        if (row.get("eligibility_scope") == "home_only"
                and re.search(
                    r"\bHome\s+students?\s+only\b",
                    str(row.get("eligibility_evidence_excerpt") or ""), re.I,
                )):
            lines.append("🎓 Eligibility: Home-fee applicants only")
        if (row.get("funding_scope") == "home_rate_tuition"
                and re.search(
                    r"\btuition\s+fees?\s+at\s+the\s+Home\s+rate\b",
                    str(row.get("funding_evidence_excerpt") or ""), re.I,
                )):
            lines.append("💰 Funding: Home-rate PhD tuition; verify duration and terms")
        else:
            lines.append(
                "💰 Bursary coverage varies; verify stipend and tuition conditions"
            )
    lines.extend([
        "",
        "<i>This is an independent doctoral funding call, not necessarily "
        "a salaried job or an ordinary university admission deadline. "
        "Verify eligibility and funding conditions with the institution.</i>",
        f"🔎 Official call checked: {escape(row['checked_at'][:10])} UTC",
        tags,
    ])
    keyboard = {"inline_keyboard": [[{
        "text": "Open official call",
        "url": row["official_url"],
    }]]}
    return "\n".join(lines), keyboard


def _group_message(rows: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """One succinct channel post, but each official position retains its own link."""
    first = rows[0]
    deadline = date.fromisoformat(first["deadline_iso"]).strftime("%d %b %Y")
    place = {"UK": "United Kingdom", "GB": "United Kingdom",
             "ES": "Spain"}.get(first["country_code"], first["country_code"])
    lines = [
        f"🎓 <b>{len(rows)} PhD funding opportunities · "
        f"{escape(first['institution'][:125])}</b>",
        f"📍 {escape(place)}",
        f"📅 <b>{'Funding' if first['deadline_kind'] == 'funding' else 'Call'} "
        f"deadline: {escape(deadline)}</b>",
    ]
    recommended = first.get("recommended_admission_iso")
    if isinstance(recommended, str) and DATE_RE.fullmatch(recommended):
        day = date.fromisoformat(recommended)
        lines.append(
            "💡 Recommended PhD admission submission (not funding deadline): "
            + escape(day.strftime("%d %b %Y"))
        )
    lines.extend(["", "<b>Available positions</b>"])
    for row in rows:
        lines.append("• " + escape(row["title"][:105]))
    lines.extend([
        "",
        "ℹ️ These are separate departmental calls with shared dates. "
        "Funding, eligibility and admission requirements may vary; "
        "open each official page before applying.",
        f"🔎 Official sources checked: {min(row['checked_at'][:10] for row in rows)} UTC",
        "#PhD #Scholarships",
    ])
    keyboard = {"inline_keyboard": [[{
        "text": row["title"][:58],
        "url": row["official_url"],
    }] for row in rows]}
    return "\n".join(lines), keyboard


def publish_official_calls(
    catalog_path: str | Path, receipt_path: str | Path,
    telegram: TelegramClient | None, *, chat_id: str,
    enabled: bool, max_messages: int = 2, now: datetime | None = None,
    reserve_intent: Callable[[str, str, str], None] | None = None,
    record_outcome: Callable[[str, str, str, str, int | None], None] | None = None,
) -> int:
    """Send bounded attempts, consolidating explicitly reviewed related calls.

    A combined post still reserves and checkpoints EACH per-call identity before
    sending. Thus a runner crash cannot turn a new grouping into a blind resend.
    """
    if not enabled or telegram is None or not chat_id:
        return 0
    enforce_production_reservation(reserve_intent)
    enforce_production_outcome(record_outcome)
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
    eligible = eligible_calls(catalog, now=timestamp)
    outstanding = [
        row for row in eligible
        if receipt_key(row, ledger["deliveries"]) is None
    ]
    handled: set[str] = set()
    sent = 0
    attempts = 0
    for row in outstanding:
        if attempts >= max_messages:
            break
        key = call_key(row)
        if key in handled:
            continue
        signature = group_signature(row)
        group = group_members(row, eligible, ledger["deliveries"])
        if not group:
            continue  # Incomplete or partly delivered group; fail closed.
        if any(call_key(member) in handled for member in group):
            continue
        keys = [call_key(member) for member in group]
        handled.update(keys)
        for member, member_key in zip(group, keys, strict=True):
            ledger["deliveries"][member_key] = {
                "state": "pending", "title": member["title"],
                "institution": member["institution"],
                "deadline_iso": member["deadline_iso"],
                "official_url": member["official_url"],
                "intake_year": member["intake_year"],
                "posting_group": signature[0] if signature is not None and len(group) > 1 else None,
                "group_size": len(group),
                "attempted_at": timestamp.isoformat(timespec="seconds").replace(
                    "+00:00", "Z"),
            }
        _checkpoint(ledger_path, ledger)  # Every identity held before any network send.
        if reserve_intent is not None:
            # A failure halfway through reservations leaves all members held.
            # It MUST NOT fall back to a smaller group or a retry.
            for member_key in keys:
                reserve_intent("calls", member_key, "initial")
        message, keyboard = (
            _group_message(group) if len(group) > 1 else _message(group[0])
        )
        try:
            # Budget the actual Bot API calls, even when every request fails.
            attempts += 1
            receipt = telegram.send_message(
                chat_id=chat_id, html=message, keyboard=keyboard,
            )
        except TelegramError as exc:
            for member_key in keys:
                attempt = ledger["deliveries"][member_key]
                if exc.uncertain:
                    attempt["state"] = "uncertain"
                elif exc.permanent:
                    attempt["state"] = "permanent_failure"
                elif reserve_intent is not None:
                    attempt["state"] = "retry_held"
                else:
                    ledger["deliveries"].pop(member_key, None)
            _checkpoint(ledger_path, ledger)
            if record_outcome is not None:
                for member_key in keys:
                    held = ledger["deliveries"].get(member_key)
                    if held is not None:
                        record_outcome("calls", member_key, "initial", held["state"], None)
            log.warning("telegram_official_call_not_confirmed",
                        institution=row["institution"], group_size=len(group),
                        uncertain=exc.uncertain)
            if exc.status in (401, 403, 404, 429):
                # Authentication/permission failures and rate limits apply to
                # the whole channel, not just this particular opportunity.
                break
            continue
        if type(receipt) is not int or receipt <= 0:
            for member_key in keys:
                ledger["deliveries"][member_key]["state"] = "uncertain"
            _checkpoint(ledger_path, ledger)
            if record_outcome is not None:
                for member_key in keys:
                    record_outcome("calls", member_key, "initial", "uncertain", None)
            continue
        for member_key in keys:
            ledger["deliveries"][member_key].update(
                state="confirmed", message_id=receipt,
                sent_at=timestamp.isoformat(timespec="seconds").replace(
                    "+00:00", "Z"),
            )
        _checkpoint(ledger_path, ledger)
        if record_outcome is not None:
            for member_key in keys:
                record_outcome("calls", member_key, "initial", "confirmed", receipt)
        sent += 1
        log.info("telegram_official_call_published", message_id=receipt,
                 institution=row["institution"], group_size=len(group),
                 deadline=row["deadline_iso"])
    return sent


def _document_review_health(catalog_path: Path) -> dict[str, Any]:
    """Counts manually recorded reviews, never promoting them to calls."""
    empty: dict[str, Any] = {
        "document_review_status": "not_recorded",
        "document_review_successes": 0,
        "document_review_failures": 0,
        "document_review_live_failures": 0,
        "document_review_robots_blocks": 0,
        "document_review_revisions": 0,
        "last_document_review_at": None,
    }
    path = catalog_path.with_name("official_document_reviews.json")
    if not path.exists():
        return empty
    try:
        with path.open("rb") as handle:
            raw = handle.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            raise ValueError("Review journal too large")
        data = json.loads(raw)
        if (not isinstance(data, dict)
                or data.get("kind") != "official_phd_document_reviews"
                or data.get("version") != 1
                or not isinstance(data.get("reviews"), list)
                or len(data["reviews"]) > 200):
            raise ValueError("Malformed document review journal")
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        seen_revisions: set[tuple[str, str, str]] = set()
        last: str | None = None
        for row in data["reviews"]:
            if not isinstance(row, dict):
                raise ValueError("Invalid document review entry")
            status = row.get("status")
            source_id = row.get("source_id")
            url = row.get("official_url")
            method = row.get("method")
            digest = row.get("document_sha256")
            reviewed_at = row.get("reviewed_at")
            if (status not in {"document_review_only", "document_unverified",
                               "robots_unavailable", "robots_disallowed",
                               "unsafe_redirect", "fetch_failed"}
                    or not isinstance(source_id, str) or len(source_id) > 50
                    or not isinstance(url, str) or len(url) > 400
                    or _host(url) is None or not url.lower().endswith((".pdf", ".docx"))
                    or method not in {"live_fetch", "local_file"}
                    or not isinstance(reviewed_at, str)
                    or _stamp(reviewed_at) is None
                    or row.get("automatic_publication") is not False):
                raise ValueError("Invalid document review safety contract")
            if status == "document_review_only":
                if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                    raise ValueError("Review-only result lacks content fingerprint")
            elif not isinstance(row.get("reason"), str):
                raise ValueError("Failed review must explain its reason")
            latest[(source_id, url)] = row
            if digest is not None:
                seen_revisions.add((source_id, url, digest))
            if last is None or reviewed_at > last:
                last = reviewed_at
        recent = list(latest.values())
        return {
            "document_review_status": "recorded",
            "document_review_successes": sum(
                item["status"] == "document_review_only" for item in recent
            ),
            "document_review_failures": sum(
                item["status"] != "document_review_only" for item in recent
            ),
            "document_review_live_failures": sum(
                item["status"] != "document_review_only"
                and item["method"] == "live_fetch" for item in recent
            ),
            "document_review_robots_blocks": sum(
                item["status"] in {"robots_unavailable", "robots_disallowed"}
                for item in recent
            ),
            "document_review_revisions": max(0, len(seen_revisions) - len({
                (item["source_id"], item["official_url"])
                for item in data["reviews"] if item.get("document_sha256")
            })),
            "last_document_review_at": last,
        }
    except (OSError, ValueError, UnicodeError, TypeError, json.JSONDecodeError):
        return {**empty, "document_review_status": "unavailable"}


def official_calls_health(
    catalog_path: str | Path, receipt_path: str | Path, *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Public-safe counts distinguish monitored sources from actual delivery."""
    checked = now or datetime.now(UTC)
    try:
        catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
        if (not isinstance(catalog, dict)
                or catalog.get("kind") != "official_phd_call_observations"
                or catalog.get("version") != 1
                or not isinstance(catalog.get("calls"), list)
                or len(catalog["calls"]) > 100
                or not isinstance(catalog.get("sources"), list)):
            raise ValueError("Invalid official call catalogue")
        ledger = _load_receipts(Path(receipt_path))
    except (OSError, json.JSONDecodeError, ValueError):
        return {"status": "unavailable", "eligible": None, "unpublished": None}
    eligible = eligible_calls(catalog, now=checked)
    delivered = ledger["deliveries"]
    unpublished = [
        row for row in eligible
        if ((key := receipt_key(row, delivered)) is None
            or delivered[key]["state"] != "confirmed")
    ]
    backlog = len(unpublished)
    group_waiting = sum(
        bool(group_signature(row)) and not group_members(row, eligible, delivered)
        for row in unpublished
    )
    state_counts: dict[str, int] = {}
    for source in catalog["sources"]:
        raw_label = source.get("status") if isinstance(source, dict) else None
        label = raw_label if isinstance(raw_label, str) else "invalid"
        state_counts[label] = state_counts.get(label, 0) + 1
    confirmed = [receipt for receipt in delivered.values()
                 if receipt.get("state") == "confirmed" and receipt.get("sent_at")]
    last = max((item["sent_at"] for item in confirmed), default=None)
    uncertain = sum(1 for item in delivered.values() if item.get("state") == "uncertain")
    pending = sum(1 for item in delivered.values() if item.get("state") == "pending")
    retry_held = sum(1 for item in delivered.values() if item.get("state") == "retry_held")
    permanent = sum(
        1 for item in delivered.values() if item.get("state") == "permanent_failure"
    )
    empty_indexes = sum(
        isinstance(source, dict) and source.get("index_empty") is True
        for source in catalog["sources"]
    )
    unsupported_documents = sum(
        source.get("unsupported_documents", 0)
        for source in catalog["sources"]
        if isinstance(source, dict)
        and type(source.get("unsupported_documents", 0)) is int
        and 0 <= source.get("unsupported_documents", 0) <= 500
    )
    document_only_indexes = sum(
        isinstance(source, dict) and source.get("document_only_index") is True
        for source in catalog["sources"]
    )
    html_index_empty = sum(
        isinstance(source, dict) and source.get("html_index_empty") is True
        for source in catalog["sources"]
    )
    # Count distinct institutional document URLs across multiple translated
    # or parallel indexes without reclassifying them as verified scholarships.
    candidate_urls: set[str] = set()
    for source in catalog["sources"]:
        urls = source.get("document_candidates") if isinstance(source, dict) else None
        if not isinstance(urls, list) or len(urls) > 100:
            continue
        for url in urls:
            if (isinstance(url, str) and len(url) <= 400
                    and _host(url) is not None
                    and url.lower().endswith((".pdf", ".doc", ".docx"))):
                candidate_urls.add(url)
    def count_source_metric(name: str) -> int:
        return sum(
            value for source in catalog["sources"] if isinstance(source, dict)
            if type(value := source.get(name, 0)) is int and 0 <= value <= 500
        )

    formats = {"pdf": 0, "doc": 0, "docx": 0}
    for source in catalog["sources"]:
        raw = source.get("document_links_by_format") if isinstance(source, dict) else None
        if isinstance(raw, dict):
            for key in formats:
                value = raw.get(key, 0)
                if type(value) is int and 0 <= value <= 500:
                    formats[key] += value
    review = _document_review_health(Path(catalog_path))
    robots_sources = sum(
        isinstance(source, dict)
        and source.get("status") in {"robots_unavailable", "robots_disallowed"}
        for source in catalog["sources"]
    )
    degraded = any(k != "ok" for k in state_counts) or bool(
        uncertain or pending or retry_held or permanent
        or empty_indexes or unsupported_documents
        or review["document_review_status"] == "unavailable"
    )
    return {
        "status": "degraded" if degraded else "ok",
        "sources": state_counts,
        "empty_indexes": empty_indexes,
        "unsupported_documents": unsupported_documents,
        "document_link_occurrences": unsupported_documents,
        "unique_document_candidates": len(candidate_urls),
        "document_only_indexes": document_only_indexes,
        "html_index_empty": html_index_empty,
        "discovered_html_links": count_source_metric("discovered_links"),
        "new_html_links": count_source_metric("new_html_links"),
        "historical_rechecks": count_source_metric("rechecked_links"),
        "document_links_by_format": formats,
        "robots_blocked_sources": robots_sources,
        "robots_blocked_details": count_source_metric("blocked_details"),
        **review,
        "eligible": len(eligible),
        "unpublished": backlog,
        "group_waiting": group_waiting,
        "confirmed": len(confirmed),
        "confirmed_messages": len({item["message_id"] for item in confirmed}),
        "pending": pending,
        "retry_held": retry_held,
        "permanent_failure": permanent,
        "uncertain": uncertain,
        "last_confirmed_at": last,
        "generated_at": catalog.get("generated_at"),
    }
