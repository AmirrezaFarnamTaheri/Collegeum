"""Read-only, no-network triage of institutional funding-document index candidates.

This command never promotes a PDF/DOC/DOCX into a verified scholarship call,
changes an official-call delivery ledger, or sends a Telegram message.
A reviewed PDF with the same official HTML URL, intake and funding deadline as
a confirmed historical receipt is recognized as already delivered.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any

from tools.official_document_review_journal import load_review_records
from tools.update_official_calls import validate_catalog, validate_sources

ROOT = Path(__file__).resolve().parents[1]
MAX_CANDIDATES = 300
MAX_INPUT_BYTES = 4 * 1024 * 1024
_FORMAT = re.compile(r"\.(pdf|docx|doc)\Z", re.I)


def _trusted_document_url(url: Any, root: str) -> bool:
    if not isinstance(url, str) or len(url) > 500:
        return False
    try:
        base = urllib.parse.urlsplit(root)
        candidate = urllib.parse.urlsplit(url)
        host = (candidate.hostname or "").lower().removeprefix("www.")
        expected = (base.hostname or "").lower().removeprefix("www.")
        port, base_port = candidate.port, base.port
    except (TypeError, ValueError):
        return False
    return bool(
        candidate.scheme == base.scheme == "https"
        and host and host == expected
        and port in (None, 443) and base_port in (None, 443)
        and not candidate.username and not candidate.password
        and not base.username and not base.password
        and not candidate.query and not candidate.fragment
        and "%" not in candidate.path and candidate.path.startswith("/")
        and len(candidate.path) <= 350 and _FORMAT.search(candidate.path)
    )


def _current_receipt(
    deliveries: dict[str, Any], canonical: str, institution: str,
    intake: int, deadline: str,
) -> int | None:
    """Exact same funding cycle only; prior years never suppress new rounds."""
    ids = []
    for value in deliveries.values():
        if not isinstance(value, dict):
            continue
        message_id = value.get("message_id")
        if (
            value.get("state") == "confirmed"
            and value.get("official_url") == canonical
            and value.get("institution") == institution
            and type(value.get("intake_year")) is int
            and value["intake_year"] == intake
            and value.get("deadline_iso") == deadline
            and type(message_id) is int and message_id > 0
        ):
            ids.append(message_id)
    return min(ids) if ids else None


def _has_prior_attempt(
    deliveries: dict[str, Any], canonical: str, institution: str,
    intake: int, deadline: str,
) -> bool:
    """An attempted send without a receipt must never look like a new call.

    Prior off-by-one intake parsing is also an operator-reconciliation case
    until source identity is independently checked; this never authorizes
    deletion, retry, or change to existing Telegram receipt history.
    """
    for value in deliveries.values():
        if not isinstance(value, dict):
            continue
        year = value.get("intake_year")
        if (
            value.get("official_url") == canonical
            and value.get("institution") == institution
            and value.get("deadline_iso") == deadline
            and (year is None or (type(year) is int and year in {intake, intake - 1}))
            and value.get("state") is not None
        ):
            return True
    return False


def build_document_triage(
    catalog: dict[str, Any], registry: dict[str, Any],
    deliveries: dict[str, Any], reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a bounded human-review queue from approved public-source observations."""
    validate_sources(registry)
    validate_catalog(catalog)
    if not isinstance(deliveries, dict) or not isinstance(reviews, list):
        raise ValueError("Invalid document triage input")
    source_map = {row["id"]: row for row in registry["sources"]}
    if len(catalog["sources"]) > len(source_map):
        raise ValueError("Unbounded document source observations")
    seen_source_ids: set[str] = set()
    candidates: dict[str, set[str]] = {}
    for observation in catalog["sources"]:
        if not isinstance(observation, dict):
            raise ValueError("Invalid document-source observation")
        sid = observation.get("id")
        if not isinstance(sid, str) or sid not in source_map or sid in seen_source_ids:
            raise ValueError("Unknown or duplicate document-source observation")
        seen_source_ids.add(sid)
        listed = observation.get("document_candidates", [])
        if not isinstance(listed, list) or len(listed) > 500:
            raise ValueError("Unbounded document candidates")
        for url in listed:
            if not _trusted_document_url(url, source_map[sid]["url"]):
                raise ValueError("Untrusted institutional document link")
            candidates.setdefault(url, set()).add(sid)
            if len(candidates) > MAX_CANDIDATES:
                raise ValueError("Document queue requires bounded operator review")

    documents = []
    for url, source_ids in sorted(candidates.items()):
        suffix = url.rsplit(".", 1)[-1].lower()
        sources = [source_map[sid] for sid in sorted(source_ids)]
        institutions = {item["institution"] for item in sources}
        approvals = [
            (source, approval)
            for source in sources
            for approval in source.get("approved_documents", [])
            if approval["url"] == url
        ]
        signatures = {
            (source["institution"], approval["canonical_html_url"], approval["title"])
            for source, approval in approvals
        }
        conflict = len(institutions) > 1 or len(signatures) > 1
        approved = bool(approvals) and not conflict and suffix != "doc"
        canonical = next(iter(signatures))[1] if approved else None
        row: dict[str, Any] = {
            "official_url": url,
            "document_format": suffix,
            "source_ids": sorted(source_ids),
            "institution": next(iter(institutions)) if len(institutions) == 1 else None,
            "approved": approved,
            "canonical_html_url": canonical,
            "review_status": "unreviewed",
            "prior_message_id": None,
            "automatic_publication": False,
        }
        if suffix == "doc":
            row["next_action"] = "unsupported_legacy_doc"
        elif conflict:
            row["next_action"] = "conflicting_approvals"
        elif not approved:
            row["next_action"] = "approval_required"
        else:
            row["next_action"] = "review_required"
            relevant = [
                review for review in reviews
                if isinstance(review, dict)
                and review.get("official_url") == url
                and review.get("source_id") in source_ids
                and review.get("status") in {
                    "document_review_only", "document_unverified",
                    "robots_disallowed", "robots_unavailable",
                    "unsafe_redirect", "fetch_failed",
                }
            ]
            if relevant:
                review = max(relevant, key=lambda item: (
                    str(item.get("reviewed_at", "")),
                    item.get("method") == "live_fetch",
                ))
                row["review_status"] = review["status"]
                if review["status"] == "document_review_only":
                    deadline = review.get("deadline_iso")
                    intake = review.get("intake_year")
                    if (
                        isinstance(deadline, str)
                        and type(intake) is int
                        and review.get("canonical_html_url") == canonical
                        and review.get("institution") == row["institution"]
                    ):
                        row["intake_year"] = intake
                        row["deadline_iso"] = deadline
                        row["evidence_excerpt"] = review.get("evidence_excerpt")
                        receipt = _current_receipt(
                            deliveries, canonical, row["institution"], intake, deadline,
                        )
                        row["prior_message_id"] = receipt
                        if receipt is not None:
                            row["next_action"] = "already_delivered_same_cycle"
                        elif _has_prior_attempt(
                            deliveries, canonical, row["institution"], intake, deadline,
                        ):
                            row["next_action"] = "prior_attempt_requires_reconciliation"
                        else:
                            row["next_action"] = "review_complete_no_delivery"
                    else:
                        row["next_action"] = "review_failed"
                elif review["status"] in {"robots_disallowed", "robots_unavailable"}:
                    row["next_action"] = "permission_blocked"
                else:
                    row["next_action"] = "review_failed"
        documents.append(row)

    return {
        "kind": "official_phd_document_triage",
        "version": 1,
        "generated_at": catalog.get("generated_at"),
        "document_count": len(documents),
        "documents": documents,
    }


def _load_json(path: Path) -> Any:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("Unbounded document-triage input")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path,
                        default=ROOT / "docs/data/official_phd_calls.json")
    parser.add_argument("--registry", type=Path,
                        default=ROOT / "config/official_phd_calls_sources.json")
    parser.add_argument("--ledger", type=Path,
                        default=ROOT / "data/official_phd_calls_telegram.json")
    parser.add_argument("--reviews", type=Path,
                        default=ROOT / "docs/data/official_document_reviews.json")
    args = parser.parse_args(argv)
    registry = _load_json(args.registry)
    result = build_document_triage(
        _load_json(args.catalog),
        registry,
        _load_json(args.ledger).get("deliveries", {}),
        load_review_records(args.reviews, registry=registry),
    )
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
