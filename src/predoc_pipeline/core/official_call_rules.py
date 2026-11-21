"""Dependency-free funding-call identity and reviewed digest safety rules.

Both the Telegram publisher and the stdlib-only ingestion watchdog must apply
the SAME no-replay and group-completeness policy. Neither module sends anything.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

MAX_GROUP_ROWS = 6
_GROUP = re.compile(r"[a-z][a-z0-9-]{2,47}\Z")


def call_key(row: Mapping[str, Any]) -> str:
    """Stable historical URL/intake identity; do not change existing keys."""
    parsed = urlsplit(row["official_url"])
    host = (parsed.hostname or "").lower().removeprefix("www.")
    identity = f"{host}|{parsed.path.rstrip('/').lower()}|{row['intake_year']}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def receipt_key(
    row: Mapping[str, Any], deliveries: Mapping[str, Any],
) -> str | None:
    """Existing attempts block replays, including a *proven* off-by-one cycle fix.

    One legacy parser picked the closed 2026/27 cycle from a source which
    explicitly opened 2027/28, so its permanent receipt was keyed to 2026.
    Suppress only when the old receipt's original hashed key, official URL,
    institution, and funding deadline match. Genuine
    future cycles with a DIFFERENT funding deadline remain new opportunities.
    Pending, uncertain, and failed attempts also block automatic retries.
    """
    key = call_key(row)
    if key in deliveries:
        return key
    target_year = row.get("intake_year")
    if type(target_year) is not int:
        return None
    # One institution may expose the same call from /en/, /ca/ and its
    # language-neutral URL. Do not replay a durable Telegram attempt merely
    # because an index discovered a second HTML alias. This is deliberately
    # narrow: same exact title, institution, deadline, intake, kind and host.
    target_title = row.get("title")
    target_url = row.get("official_url")
    target_institution = row.get("institution")
    target_deadline = row.get("deadline_iso")
    if (isinstance(target_title, str) and isinstance(target_url, str)
            and isinstance(target_institution, str)
            and isinstance(target_deadline, str)):
        target_host = (urlsplit(target_url).hostname or "").lower().removeprefix("www.")
        for existing_key, receipt in deliveries.items():
            if not isinstance(receipt, dict):
                continue
            previous_url = receipt.get("official_url")
            if (not isinstance(previous_url, str) or previous_url == target_url
                    or (urlsplit(previous_url).hostname or "").lower()
                        .removeprefix("www.") != target_host
                    or receipt.get("title") != target_title
                    or receipt.get("institution") != target_institution
                    or receipt.get("deadline_iso") != target_deadline
                    or receipt.get("intake_year") != target_year
                    or (receipt.get("kind") is not None and row.get("kind") is not None
                        and receipt["kind"] != row["kind"])):
                continue
            if call_key(receipt) == existing_key:
                return existing_key
    for legacy_key, receipt in deliveries.items():
        if not isinstance(receipt, dict):
            continue
        old_year = receipt.get("intake_year")
        if (type(old_year) is not int or old_year != target_year - 1
                or receipt.get("official_url") != row.get("official_url")
                or receipt.get("institution") != row.get("institution")
                or receipt.get("deadline_iso") != row.get("deadline_iso")):
            continue
        if (receipt.get("kind") and row.get("kind")
                and receipt["kind"] != row["kind"]):
            continue
        if call_key(receipt) == legacy_key:
            return legacy_key
    return None


def group_signature(row: Mapping[str, Any]) -> tuple[Any, ...] | None:
    """Only explicitly approved, otherwise-identical funding calls may group."""
    name = row.get("posting_group")
    if not isinstance(name, str) or not _GROUP.fullmatch(name):
        return None
    return (
        name, row.get("institution"), row.get("country_code"), row.get("kind"),
        row.get("deadline_kind"), row.get("deadline_iso"),
        row.get("recommended_admission_iso"), row.get("intake_year"),
    )


def group_members(
    row: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    deliveries: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return the entire safe posting unit; [] means hold without sending.

    Reviewed groups declare how many department pages are required. Partial,
    conflicting, or previously attempted groups never degrade into a smaller
    digest or several single posts. Unreviewed legacy groups without a
    declared size keep the original conservative matching behavior.
    """
    signature = group_signature(row)
    if signature is None:
        # Invalid reviewed metadata must not silently become a normal post.
        if (row.get("posting_group") is not None
                or row.get("posting_group_expected") is not None):
            return []
        return [row]
    members = [candidate for candidate in candidates
               if group_signature(candidate) == signature]
    expected = row.get("posting_group_expected")
    if expected is None:
        if len(members) > MAX_GROUP_ROWS:
            return []  # A truncated digest would silently omit opportunities.
        if len(members) < 2:
            return [row]
        if any(receipt_key(member, deliveries) is not None for member in members):
            return []
        return members
    if type(expected) is not int or not 2 <= expected <= MAX_GROUP_ROWS:
        return []
    # Group identity covers one department bundle per institution and intake.
    # Disagreeing deadlines, funding types or admission dates require review,
    # not automatic splitting into different messages.
    related = []
    for candidate in candidates:
        candidate_signature = group_signature(candidate)
        if (candidate_signature is not None
                and candidate_signature[0] == signature[0]
                and candidate_signature[-1] == signature[-1]):
            related.append(candidate)
    if (len(members) != expected or len(related) != expected
            or any(candidate.get("posting_group_expected") != expected
                   for candidate in members)
            or len({call_key(candidate) for candidate in members}) != expected
            or any(receipt_key(member, deliveries) is not None for member in members)):
        return []
    return members
