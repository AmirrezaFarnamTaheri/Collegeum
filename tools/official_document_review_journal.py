"""Opt-in, bounded, review-only evidence journal for official PhD documents.

This module performs *no* network IO and never inserts a scholarship
observation into the admission, funding, watchdog or Telegram catalogues.
Only an operator's explicit --record action may update the local audit file.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from tools.update_official_calls import DATE_RE, _date, validate_sources

KIND = "official_phd_document_reviews"
VERSION = 1
MAX_REVIEWS = 200
MAX_JOURNAL_BYTES = 128 * 1024
STATES = frozenset({
    "document_review_only", "document_unverified",
    "robots_unavailable", "robots_disallowed", "unsafe_redirect", "fetch_failed",
})
METHODS = frozenset({"local_file", "live_fetch"})
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _utc(value: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Document review timestamps must be UTC")
    try:
        day = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid document review timestamp") from exc
    if day.tzinfo is None or day.utcoffset().total_seconds() != 0:
        raise ValueError("Document review timestamp needs UTC offset")
    return day.isoformat(timespec="seconds").replace("+00:00", "Z")


def _approval(registry: dict[str, Any], source_id: str, url: str) -> dict[str, Any]:
    for source in registry["sources"]:
        if source["id"] != source_id:
            continue
        for approved in source.get("approved_documents", []):
            if approved["url"] == url:
                return approved
    raise ValueError("No exact approved source/document pair")


def _normalise(
    candidate: dict[str, Any], *, registry: dict[str, Any], method: str | None,
) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise ValueError("Invalid document review entry")
    source_id = candidate.get("source_id")
    url = candidate.get("official_url")
    status = candidate.get("status")
    if (not isinstance(source_id, str) or not isinstance(url, str)
            or not isinstance(status, str) or status not in STATES):
        raise ValueError("Unrecognized document review identity or state")
    approved = _approval(registry, source_id, url)
    review_method = method if method is not None else candidate.get("method")
    if review_method not in METHODS:
        raise ValueError("Review method must be explicitly identified")
    if candidate.get("automatic_publication") is True:
        raise ValueError("Document review cannot authorize publication")
    if (candidate.get("canonical_html_url") is not None
            and candidate["canonical_html_url"] != approved["canonical_html_url"]):
        raise ValueError("Document review canonical identity drift")
    format_ = "pdf" if url.lower().endswith(".pdf") else "docx"
    if not url.lower().endswith((".pdf", ".docx")):
        raise ValueError("Unsupported document type")
    if candidate.get("document_format", format_) != format_:
        raise ValueError("Document format mismatch")
    reviewed_at = _utc(candidate.get("reviewed_at"))
    reason = candidate.get("reason")
    digest = candidate.get("document_sha256")
    evidence: dict[str, Any] = {}
    if status == "document_review_only":
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ValueError("Accepted review needs real content digest")
        if reason is not None or candidate.get("automatic_publication") is not False:
            raise ValueError("Accepted review is never publication approval")
        institution = next(
            source["institution"] for source in registry["sources"]
            if source["id"] == source_id
        )
        country = next(
            source["country_code"] for source in registry["sources"]
            if source["id"] == source_id
        )
        title = candidate.get("title")
        intake = candidate.get("intake_year")
        cutoff = candidate.get("deadline_iso")
        excerpt = candidate.get("evidence_excerpt")
        kind = candidate.get("kind")
        deadline_kind = candidate.get("deadline_kind")
        try:
            day = date.fromisoformat(cutoff)
        except (ValueError, TypeError):
            raise ValueError("Accepted review needs a valid funding cutoff") from None
        if (title != approved["title"] or candidate.get("institution") != institution
                or candidate.get("country_code") != country
                or type(intake) is not int or not 2025 <= intake <= 2100
                or not day.year <= intake <= day.year + 2
                or kind not in {"phd_scholarship", "phd_fellowship"}
                or deadline_kind not in {"funding", "scholarship"}
                or not isinstance(excerpt, str) or not 12 <= len(excerpt) <= 230
                or re.search(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", excerpt, re.I)
                or not any(_date(m) == day for m in DATE_RE.finditer(excerpt))):
            raise ValueError("Document review missing independent cycle/deadline evidence")
        evidence = {
            "title": title, "institution": institution, "country_code": country,
            "kind": kind, "intake_year": intake,
            "deadline_iso": day.isoformat(), "deadline_kind": deadline_kind,
            "evidence_excerpt": excerpt,
        }
    elif not isinstance(reason, str) or not 1 <= len(reason) <= 100:
        raise ValueError("Failed review must describe its nonpublishable reason")
    if digest is not None and (not isinstance(digest, str) or not DIGEST.fullmatch(digest)):
        raise ValueError("Invalid content fingerprint")
    return {
        "source_id": source_id,
        "official_url": url,
        "canonical_html_url": approved["canonical_html_url"],
        "document_format": format_,
        "status": status,
        "reason": reason,
        "method": review_method,
        "reviewed_at": reviewed_at,
        "document_sha256": digest,
        "automatic_publication": False,
        **evidence,
    }


def load_review_records(
    path: str | Path, *, registry: dict[str, Any],
) -> list[dict[str, Any]]:
    """Reject corrupt/unapproved prior entries instead of silently discarding them."""
    validate_sources(registry)
    file = Path(path)
    if not file.exists():
        return []
    raw = file.read_bytes()
    if len(raw) > MAX_JOURNAL_BYTES:
        raise ValueError("Document review journal exceeds hard byte limit")
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Unparseable document review journal") from exc
    if (not isinstance(parsed, dict) or parsed.get("kind") != KIND
            or parsed.get("version") != VERSION
            or not isinstance(parsed.get("reviews"), list)
            or len(parsed["reviews"]) > MAX_REVIEWS):
        raise ValueError("Invalid document review journal schema")
    rows = parsed["reviews"]
    for row in rows:
        if _normalise(row, registry=registry, method=None) != row:
            raise ValueError("Noncanonical document review journal entry")
    return rows


def record_review(
    path: str | Path, result: dict[str, Any], *, registry: dict[str, Any],
    method: str,
) -> bool:
    """Atomically append one explicit review result; idempotent for unchanged state.

    For the rare case of two simultaneous operator sessions, serialize at the
    operator/branch level before committing the resulting ledger to Git.
    """
    validate_sources(registry)
    row = _normalise(result, registry=registry, method=method)
    file = Path(path)
    rows = load_review_records(file, registry=registry)
    previous = next((item for item in reversed(rows)
                     if item["source_id"] == row["source_id"]
                     and item["official_url"] == row["official_url"]
                     and item["method"] == row["method"]), None)
    if previous is not None and all(
        previous[field] == row[field]
        for field in (
            "status", "reason", "document_sha256", "canonical_html_url",
            "title", "institution", "country_code", "kind", "intake_year",
            "deadline_iso", "deadline_kind", "evidence_excerpt",
        )
    ):
        return False
    if len(rows) >= MAX_REVIEWS:
        raise ValueError("Document review journal is full; archival review required")
    payload = {
        "kind": KIND, "version": VERSION,
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds").replace(
            "+00:00", "Z"),
        "reviews": [*rows, row],
    }
    encoded = (json.dumps(payload, ensure_ascii=True, indent=2) + "\n").encode()
    if len(encoded) > MAX_JOURNAL_BYTES:
        raise ValueError("Document review journal exceeds hard byte limit")
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=file.parent, prefix=".review-", suffix=".tmp", delete=False,
        ) as stream:
            temporary = stream.name
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, file)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
    return True
