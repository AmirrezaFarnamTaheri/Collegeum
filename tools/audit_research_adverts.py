"""Validate a fixed research-advert review without fetching or publishing jobs.

The completed-review count includes recorded access failures. Readable advert
bodies, removed links and unavailable sources have separate counts. Neither a
completed check nor an HTTP 200 response establishes that applications are open.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from predoc_pipeline.core.output_quality import application_url_issue
from predoc_pipeline.core.urls import canonicalize_url

EXPECTED_ADVERTS = 251
DEFAULT_REVIEW = Path(__file__).resolve().parents[1] / (
    "review/2026-11-24/research-adverts-251.json"
)
OUTCOMES = frozenset({
    "readable_advert", "closed_advert", "removed_advert", "access_unavailable",
    "fetch_failed", "unverified_page",
})
ELIGIBILITY = frozenset({
    "collector_eligible", "subject_rejected", "deferred", "expired", "not_assessed",
})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(UTC) if result.tzinfo is not None else None


def _url(value: object) -> bool:
    if not isinstance(value, str) or application_url_issue(value):
        return False
    try:
        parts = urlsplit(value)
        return bool(parts.scheme == "https" and parts.hostname and
                    not parts.username and not parts.password and parts.port in (None, 443))
    except ValueError:
        return False


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", unescape(text)).casefold().split())


class _VisibleText(HTMLParser):
    """A dependency-free plausibility check, not an employer-specific parser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input",
                   "link", "meta", "param", "source", "track", "wbr"}:
            return
        values = dict(attrs)
        hidden = (tag in {"script", "style", "template", "noscript"} or
                  "hidden" in values or values.get("aria-hidden") == "true" or
                  re.search(r"display\s*:\s*none|visibility\s*:\s*hidden",
                            values.get("style") or "", re.I))
        if self.hidden or hidden:
            self.hidden.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.hidden:
            index = len(self.hidden) - 1 - self.hidden[::-1].index(tag)
            del self.hidden[index:]

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _capture_text(content: bytes) -> str | None:
    # PDFs need the separately recorded PDF review. Hash verification of a PDF
    # is deliberately not represented as independent text/identity validation.
    if content.startswith(b"%PDF-"):
        return None
    decoded = content.decode("utf-8", errors="replace")
    if decoded.lstrip().startswith("{"):
        try:
            data = json.loads(decoded)
        except ValueError:
            return ""
        info = data.get("jobPostingInfo") if isinstance(data, dict) else None
        if not isinstance(info, dict):
            return ""
        decoded = " ".join(info.get(key, "") for key in ("title", "jobDescription")
                           if isinstance(info.get(key, ""), str))
    parser = _VisibleText()
    parser.feed(decoded)
    return _normalized(" ".join(parser.parts))


def audit_review(
    document: dict, *, now: datetime, capture_dir: Path | None = None,
) -> dict:
    """Derive coverage from unique, complete observations, ignoring claimed totals.

    With capture_dir, every successful raw page capture is also verified against
    its recorded byte count and digest. Without it this is a metadata/provenance
    audit, not independent verification of the original employer page.
    """
    if now.tzinfo is None:
        raise ValueError("The audit time must include a timezone")
    now = now.astimezone(UTC)
    if not isinstance(document, dict) or not isinstance(document.get("adverts"), list):
        raise ValueError("The review must contain an adverts list")
    adverts = document["adverts"]
    if any(not isinstance(row, dict) for row in adverts):
        raise ValueError("Advert observations must be objects")

    metadata_issues = []
    if document.get("kind") != "research_advert_review" or document.get("version") != 1:
        metadata_issues.append("invalid_review_kind_or_version")
    if type(document.get("target")) is not int or document["target"] != EXPECTED_ADVERTS:
        metadata_issues.append("invalid_review_target")
    if len(adverts) != EXPECTED_ADVERTS:
        metadata_issues.append("unexpected_advert_count")
    if not _nonempty(document.get("selection_rule")):
        metadata_issues.append("missing_cohort_selection_rule")
    reviewed = _timestamp(document.get("reviewed_at"))
    if reviewed is None or reviewed > now:
        metadata_issues.append("invalid_review_timestamp")

    observations = []
    identities: dict[str, list[int]] = defaultdict(list)
    urls: dict[str, set[int]] = defaultdict(set)
    pages: dict[str, set[int]] = defaultdict(set)
    digests: dict[str, set[int]] = defaultdict(set)
    for index, row in enumerate(adverts):
        issues: list[str] = []
        identity = row.get("advert_id")
        if _nonempty(identity):
            identities[identity].append(index)
        else:
            issues.append("missing_advert_identity")
        for field in ("title", "institution", "source", "identity_basis", "discovered_from"):
            if not _nonempty(row.get(field)):
                issues.append("missing_" + field)
        if not _url(row.get("url")):
            issues.append("invalid_advert_url")
        else:
            urls[canonicalize_url(row["url"])].add(index)
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list) or any(not _url(url) for url in aliases):
            issues.append("invalid_alias_urls")
        else:
            for url in aliases:
                urls[canonicalize_url(url)].add(index)
        checked = _timestamp(row.get("checked_at"))
        if checked is None or checked > now or (reviewed is not None and checked > reviewed):
            issues.append("invalid_check_timestamp")
        outcome = row.get("outcome")
        if not isinstance(outcome, str) or outcome not in OUTCOMES:
            issues.append("incomplete_or_unknown_outcome")
            outcome = None
        eligibility = row.get("eligibility")
        if not isinstance(eligibility, str) or eligibility not in ELIGIBILITY:
            issues.append("unknown_eligibility")
        if not _nonempty(row.get("reason")):
            issues.append("missing_outcome_reason")
        if type(row.get("body_evidence")) is not bool:
            issues.append("invalid_body_evidence_flag")

        evidence = row.get("evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        if not _url(evidence.get("url")):
            issues.append("invalid_evidence_url")
        elif (canonicalize_url(evidence["url"]) not in {
                canonicalize_url(value) for value in [row.get("url"), *(
                    aliases if isinstance(aliases, list) else []
                )] if _url(value)
        }):
            issues.append("evidence_not_bound_to_advert_or_reviewed_alias")
        observed = _timestamp(evidence.get("checked_at"))
        if observed is None or observed > now or (checked is not None and observed > checked):
            issues.append("invalid_evidence_timestamp")
        kind, status = evidence.get("kind"), evidence.get("status")
        if kind == "access_decision":
            # A robots/cooldown decision is not an HTTP response from the advert.
            if status is not None or evidence.get("request_sent") is not False:
                issues.append("access_decision_misrepresented_as_response")
            if not _nonempty(evidence.get("access_reason")):
                issues.append("missing_access_reason")
            policy = evidence.get("policy_evidence")
            if not isinstance(policy, dict):
                issues.append("missing_access_policy_evidence")
            else:
                policy_time = _timestamp(policy.get("checked_at"))
                if (not _url(policy.get("url")) or policy_time is None or
                        observed is None or policy_time > observed or
                        type(policy.get("status")) is not int or
                        not 0 <= policy["status"] <= 599):
                    issues.append("invalid_access_policy_evidence")
                elif (_url(evidence.get("url")) and
                      urlsplit(canonicalize_url(policy["url"])).netloc !=
                      urlsplit(canonicalize_url(evidence["url"])).netloc):
                    issues.append("access_policy_for_unrelated_origin")
        elif kind == "page_response":
            if type(status) is not int or status < 100 or status > 599:
                issues.append("invalid_http_status")
            if evidence.get("request_sent") is not True:
                issues.append("response_without_request")
        elif kind == "request_error":
            if status is not None or evidence.get("request_sent") is not True:
                issues.append("invalid_request_error")
            if not _nonempty(evidence.get("error")):
                issues.append("missing_request_error")
        else:
            issues.append("unknown_evidence_kind")

        capture_verified = False
        capture_text = None
        if kind == "page_response" and status == 200:
            digest = evidence.get("sha256")
            size = evidence.get("bytes")
            if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
                issues.append("missing_capture_hash")
            elif row.get("body_evidence") is True:
                digests[digest].add(index)
            if type(size) is not int or size <= 0:
                issues.append("missing_capture_size")
            if not _url(evidence.get("final_url")):
                issues.append("invalid_capture_final_url")
            elif row.get("body_evidence") is True:
                pages[canonicalize_url(evidence["final_url"])].add(index)
                if canonicalize_url(evidence["final_url"]) not in {
                    canonicalize_url(value) for value in [row.get("url"), *(
                        aliases if isinstance(aliases, list) else []
                    )] if _url(value)
                }:
                    issues.append("final_page_not_bound_to_advert_or_reviewed_alias")
            if capture_dir is not None and _url(evidence.get("url")):
                # The filename is derived here, never taken from untrusted metadata.
                name = hashlib.sha256(evidence["url"].encode()).hexdigest()[:20] + ".html"
                path = capture_dir / name
                if not path.is_file() or not path.resolve().is_relative_to(capture_dir.resolve()):
                    issues.append("missing_raw_capture")
                else:
                    content = path.read_bytes()
                    if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
                        issues.append("raw_capture_mismatch")
                    else:
                        capture_verified = True
                        capture_text = _capture_text(content)

        body = row.get("body_evidence") is True
        if body:
            if outcome not in {"readable_advert", "closed_advert"}:
                issues.append("body_claim_conflicts_with_outcome")
            if kind != "page_response" or status != 200:
                issues.append("body_without_successful_capture")
            if row.get("identity_matched") is not True:
                issues.append("body_identity_not_established")
            if type(row.get("body_characters")) is not int or row["body_characters"] < 160:
                issues.append("missing_substantive_body")
            if not _nonempty(row.get("evidence_excerpt")):
                issues.append("missing_body_excerpt")
            elif capture_text is not None:
                if _normalized(row["evidence_excerpt"]) not in capture_text:
                    issues.append("body_excerpt_absent_from_raw_capture")
                if (len(capture_text) < 160 or
                        (type(row.get("body_characters")) is int and
                         row["body_characters"] > len(capture_text) * 1.25 + 200)):
                    issues.append("body_size_not_supported_by_raw_capture")
        elif outcome == "readable_advert":
            issues.append("advert_outcome_without_body_evidence")
        if outcome == "removed_advert" and (type(status) is not int or status not in {404, 410}):
            issues.append("removed_link_without_http_evidence")
        if outcome == "unverified_page" and status != 200:
            issues.append("unverified_page_without_response")
        if outcome == "closed_advert":
            if not _nonempty(row.get("closure_evidence")):
                issues.append("missing_explicit_closure_evidence")
            if kind != "page_response" or status != 200 or row.get("identity_matched") is not True:
                issues.append("closure_without_primary_advert_identity")
        if row.get("eligibility") == "collector_eligible" and not body:
            issues.append("eligible_without_advert_body")
        observations.append({
            "advert_id": identity, "outcome": outcome, "body_evidence": body,
            "eligibility": row.get("eligibility"), "capture_verified": capture_verified,
            "issues": issues,
        })

    for mapping, issue in (
        (identities, "duplicate_advert_identity"), (urls, "duplicate_advert_url_or_alias"),
        (pages, "same_final_page_for_multiple_adverts"),
        (digests, "same_capture_for_multiple_adverts"),
    ):
        for indices in mapping.values():
            if len(indices) > 1:
                for index in indices:
                    observations[index]["issues"].append(issue)

    valid = [row for row in observations if not row["issues"]]
    completed = len(valid)
    body_count = sum(row["body_evidence"] for row in valid)
    return {
        "kind": "research_advert_review_audit", "as_of": now.isoformat(),
        "metadata_issues": metadata_issues,
        "summary": {
            "target": EXPECTED_ADVERTS, "records": len(adverts),
            "distinct_research_adverts_checked": completed,
            "coverage_label": (
                f"Distinct research adverts checked {completed} of {EXPECTED_ADVERTS}"
            ),
            "target_met": completed == EXPECTED_ADVERTS and not metadata_issues,
            "adverts_with_body_evidence": body_count,
            "all_adverts_have_body_evidence": (
                body_count == EXPECTED_ADVERTS and not metadata_issues
            ),
            "raw_capture_hashes_verified": sum(row["capture_verified"] for row in valid),
            "outcome_counts": dict(sorted(Counter(row["outcome"] for row in valid).items())),
            "eligibility_counts": dict(sorted(Counter(
                row["eligibility"] for row in valid
            ).items())),
            "invalid_records": len(adverts) - completed,
        },
        "observations": observations,
        "meaning": (
            "Checked means a recorded review outcome, including access failures. "
            "Body evidence, collector eligibility and an open application are different claims. "
            "This audit does not publish jobs or re-confirm present availability. "
            "Raw-capture checks verify hashes and HTML/JSON excerpt plausibility; "
            "PDF text and employer-specific semantics remain recorded review judgments."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--capture-dir", type=Path)
    parser.add_argument("--now", type=str)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-all-bodies", action="store_true")
    args = parser.parse_args(argv)
    now = _timestamp(args.now) if args.now else datetime.now(UTC)
    if now is None:
        parser.error("--now must include a valid date, time and timezone")
    report = audit_review(json.loads(args.review.read_text(encoding="utf-8")),
                          now=now, capture_dir=args.capture_dir)
    summary = report["summary"]
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(summary["coverage_label"])
        print(f"Advert bodies recorded: {summary['adverts_with_body_evidence']}")
        print("Outcomes: " + json.dumps(summary["outcome_counts"], sort_keys=True))
        print(f"Invalid records: {summary['invalid_records']}")
        print(report["meaning"])
        if report["metadata_issues"]:
            print("Metadata issues: " + ", ".join(report["metadata_issues"]))
    return int(not summary["target_met"] or
               (args.require_all_bodies and not summary["all_adverts_have_body_evidence"]))


if __name__ == "__main__":
    raise SystemExit(main())
