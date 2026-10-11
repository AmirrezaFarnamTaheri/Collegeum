#!/usr/bin/env python3
"""Audit Collegeum's committed state, dashboard, RSS and source-health snapshot.

All checks are offline and use only the Python standard library. Structural
errors block CI; semantic warnings remain visible without pretending to prove
whether an external job is open. The original journals are never modified.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = (
    "data/listings.ndjson",
    "data/seen.ndjson",
    "docs/data/listings.json",
    "docs/data/health.json",
    "docs/feed.xml",
)
ATOMIC_FIELDS = ("title", "institution", "country", "city", "source_url", "deadline")
HEX64 = re.compile(r"^[a-f0-9]{64}$")
OLD_SITE = "predoc-not-org"
EXPECTED_SITE = "/Collegeum"


def _date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(UTC) if result.tzinfo else None
    except (ValueError, OverflowError):
        return None


def _web_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        url = urlsplit(value)
        return url.scheme in ("https", "http") and bool(url.hostname) and not (
            url.username or url.password
        )
    except ValueError:
        return False


def _strict_json(text: str) -> Any:
    """Reject JSON values that JavaScript cannot parse or consumers interpret differently."""

    def invalid_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON value {value}")

    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise ValueError(f"duplicate JSON field {key}")
            output[key] = value
        return output

    return json.loads(text, parse_constant=invalid_constant, object_pairs_hook=unique_keys)


def audit(root: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Return a summary and machine-readable defects, without changing files."""
    findings: list[dict[str, str]] = []
    summary: dict[str, Any] = {}

    def finding(severity: str, code: str, message: str) -> None:
        # Bound untrusted record text before printing public CI logs.
        findings.append({"severity": severity, "code": code, "message": message[:220]})

    loaded: dict[str, Any] = {}
    for name in REQUIRED:
        path = root / name
        if not path.is_file():
            finding("error", "missing-file", name)
            continue
        try:
            if name.endswith(".ndjson"):
                rows = []
                for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if not line.strip():
                        continue
                    value = _strict_json(line)
                    if not isinstance(value, dict):
                        raise ValueError(f"line {lineno} must be a JSON object")
                    rows.append(value)
                loaded[name] = rows
            elif name.endswith(".json"):
                loaded[name] = _strict_json(path.read_text(encoding="utf-8"))
            else:
                loaded[name] = ET.parse(path).getroot()
        except (OSError, UnicodeError, ValueError, ET.ParseError) as exc:
            finding("error", "unreadable-file", f"{name}: {type(exc).__name__}")

    if len(loaded) != len(REQUIRED):
        return summary, findings

    state = loaded["data/listings.ndjson"]
    seen = loaded["data/seen.ndjson"]
    public = loaded["docs/data/listings.json"]
    health = loaded["docs/data/health.json"]
    feed = loaded["docs/feed.xml"]
    if not isinstance(public, dict) or not isinstance(health, dict):
        finding("error", "invalid-top-level", "Dashboard and health must be JSON objects")
        return summary, findings
    rows = public.get("listings")
    if not isinstance(rows, list):
        finding("error", "invalid-listings", "Dashboard listings must be an array")
        return summary, findings
    summary.update(state=len(state), seen=len(seen), dashboard=len(rows))

    state_by_id: dict[int, dict[str, Any]] = {}
    state_by_hash: dict[str, dict[str, Any]] = {}
    state_by_apply: dict[str, dict[str, Any]] = {}
    for item in state:
        uid = item.get("id")
        if type(uid) is not int or uid <= 0:
            finding("error", "bad-state-id", f"State ID: {uid!r}")
            continue
        if uid in state_by_id:
            finding("error", "duplicate-state-id", f"ID {uid}")
        state_by_id[uid] = item
        link_hash = item.get("url_hash")
        if link_hash in state_by_hash:
            finding("error", "duplicate-listing-identity", f"ID {uid}")
        state_by_hash[link_hash] = item
        if item.get("apply_url") in state_by_apply:
            finding("error", "duplicate-listing-application", f"ID {uid}")
        state_by_apply[item.get("apply_url")] = item
        if not HEX64.fullmatch(str(item.get("url_hash") or "")):
            finding("error", "bad-identity-hash", f"State ID {uid}")
        for field in ("apply_url", "source_url"):
            if not _web_url(item.get(field)):
                finding("error", "bad-state-url", f"State ID {uid}, {field}")
        for stamp in ("first_seen_at", "last_seen_at", "published_at", "closed_at", "expired_at"):
            value = item.get(stamp)
            if value is not None and _date(value) is None:
                finding("error", "bad-state-date", f"State ID {uid}, {stamp}")
        first = _date(item.get("first_seen_at"))
        last = _date(item.get("last_seen_at"))
        if first and last and last < first:
            finding("error", "state-clock-reversal", f"State ID {uid}")
        cutoff = _date(item.get("deadline"))
        publication = _date(item.get("published_at"))
        if cutoff and publication and publication > cutoff:
            finding("warning", "published-after-deadline", f"Historical state ID {uid}")
        if item.get("status") == "pending" and item.get("telegram_message_id"):
            finding("error", "pending-with-delivery", f"State ID {uid}")

    seen_hashes = set()
    accepted_without_reference = 0
    for item in seen:
        key = item.get("url_hash")
        if not HEX64.fullmatch(str(key or "")):
            finding("error", "bad-seen-hash", "Malformed seen-item identity")
        if key in seen_hashes:
            finding("error", "duplicate-seen", "Repeated seen-item identity")
        seen_hashes.add(key)
        reference = item.get("listing_url_hash")
        if reference is not None and reference not in state_by_hash:
            finding("error", "orphan-seen-listing-reference",
                    "Seen record points to missing listing identity")
        if item.get("decision") == "accepted" and not reference:
            accepted_without_reference += 1
    if accepted_without_reference:
        finding("warning", "accepted-without-listing-reference",
                f"{accepted_without_reference} historical accepted decisions lack back-references")
    summary["unlinked_accepted"] = accepted_without_reference

    if public.get("count") != len(rows):
        finding("error", "count-mismatch", "Dashboard count disagrees with array length")
    stamp = _date(public.get("generated_at"))
    if not stamp:
        finding("error", "bad-snapshot-timestamp", "Dashboard generated_at missing or invalid")

    public_ids: set[int] = set()
    urls: set[str] = set()
    links: set[str] = set()
    public_by_source: dict[str, dict[str, Any]] = {}
    suspicious_salary: list[int] = []
    for item in rows:
        if not isinstance(item, dict):
            finding("error", "bad-public-row", "Dashboard entry must be an object")
            continue
        uid = item.get("id")
        if type(uid) is not int or uid in public_ids:
            finding("error", "bad-or-duplicate-public-id", f"Dashboard ID {uid!r}")
            continue
        public_ids.add(uid)
        old = state_by_id.get(uid)
        source_url = item.get("source_url")
        if isinstance(source_url, str):
            if source_url in public_by_source:
                finding("error", "duplicate-public-source-url", f"ID {uid}")
            public_by_source[source_url] = item
        if old is None:
            finding("error", "orphan-public-record", f"ID {uid}")
            continue
        if old.get("status") != "published" or old.get("closed_at") or old.get("expired_at"):
            finding("error", "ineligible-public-record", f"ID {uid}")
        for key in ATOMIC_FIELDS:
            if item.get(key) != old.get(key):
                finding("error", "public-state-divergence", f"ID {uid}, field {key}")
        for key in ("apply_url", "source_url"):
            if not _web_url(item.get(key)):
                finding("error", "bad-public-url", f"ID {uid}, {key}")
            if isinstance(item.get(key), str):
                links.add(item[key])
        url = item.get("apply_url")
        if isinstance(url, str):
            if url in urls:
                finding("error", "duplicate-public-apply-url", f"ID {uid}")
            urls.add(url)
            parsed = urlsplit(url)
            if parsed.hostname == "accounts.google.com":
                finding("warning", "auth-url", f"ID {uid}: Google login URL instead of vacancy")
            if parsed.hostname == "job-boards.greenhouse.io" and "true" in [
                x.lower() for x in parse_qs(parsed.query).get("error", [])
            ]:
                finding("warning", "error-page-url", f"ID {uid}: Greenhouse error=true")
            if parsed.scheme == "http":
                finding("warning", "insecure-apply-url", f"ID {uid}")
        for key in ("tools_required", "tools_preferred", "disciplines"):
            val = item.get(key)
            if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
                finding("error", "public-list-type", f"ID {uid}, field {key}")
        if item.get("kind") not in {"predoc", "phd", "postdoc", "research", None}:
            finding("error", "invalid-position-kind", f"ID {uid}")
        if not isinstance(item.get("title"), str) or not item["title"].strip():
            finding("error", "missing-title", f"ID {uid}")
        deadline = _date(item.get("deadline"))
        if item.get("deadline") is not None and deadline is None:
            finding("error", "invalid-deadline", f"ID {uid}")
        if stamp and deadline:
            delta = (deadline.date() - stamp.date()).days
            if item.get("days_left") != delta:
                finding("warning", "stale-countdown", f"ID {uid}: expected {delta}")
            if deadline < stamp:
                finding("error", "expired-in-publication", f"ID {uid}")
        amount = item.get("salary_min")
        raw_salary = str(item.get("salary_raw") or "")
        if amount is not None and (not isinstance(amount, (int, float))
                                   or isinstance(amount, bool) or amount < 0):
            finding("error", "invalid-salary-amount", f"ID {uid}")
        maximum = item.get("salary_max")
        if (isinstance(amount, (int, float)) and
                (not math.isfinite(amount) or amount < 0)):
            finding("error", "nonfinite-public-salary", f"ID {uid}")
        if (isinstance(amount, (int, float)) and
                isinstance(maximum, (int, float)) and maximum < amount):
            finding("error", "inverted-salary-range", f"ID {uid}")
        score = item.get("confidence")
        if (type(score) not in (float, int) or
                not math.isfinite(score) or not (0 <= score <= 1)):
            finding("error", "invalid-confidence", f"ID {uid}")
        if isinstance(amount, (int, float)) and (
            not item.get("salary_currency") or
            (re.search(r"\b(?:TV-L|grade)\b", raw_salary, re.I) and amount < 1000)
            or (amount == 2026 and not item.get("salary_currency"))
        ):
            suspicious_salary.append(uid)
        if str(item.get("summary") or "").lower().startswith("sign in to continue"):
            finding("warning", "login-page-summary", f"ID {uid}")
    if suspicious_salary:
        finding("warning", "unverified-pay-numbers",
                f"Records with unsubstantiated numeric compensation: {suspicious_salary[:20]}")

    if feed.tag != "rss" or feed.get("version") != "2.0":
        finding("error", "invalid-rss-root", "Feed must be RSS 2.0")
    channel = feed.find("channel")
    if channel is None:
        finding("error", "missing-channel", "RSS channel missing")
    else:
        entries = channel.findall("item")
        summary["rss"] = len(entries)
        if len(entries) > len(rows):
            finding("error", "rss-exceeds-public", "RSS has more entries than dashboard")
        guid_seen: set[str] = set()
        for i, record in enumerate(entries):
            guid = record.findtext("guid")
            link = record.findtext("link")
            title = record.findtext("title")
            published = record.findtext("pubDate")
            if not guid or not link or not title or not published:
                finding("error", "incomplete-rss-item", f"RSS entry {i}")
                continue
            if guid in guid_seen:
                finding("error", "duplicate-rss-guid", f"RSS entry {i}")
            guid_seen.add(guid)
            if i < len(rows) and isinstance(rows[i], dict) and (
                rows[i].get("source_url") != guid
            ):
                finding("error", "rss-order-divergence", f"RSS entry {i}")
            match = public_by_source.get(guid)
            if match is None:
                finding("error", "rss-source-absent-public", f"RSS entry {i}")
            else:
                expected_title = f"{match['title']} \u2014 {match['institution']}"
                if title != expected_title:
                    finding("error", "rss-title-divergence", f"RSS entry {i}")
                if link != match.get("apply_url"):
                    finding("error", "rss-application-divergence", f"RSS entry {i}")
                expected_description = (
                    f"{match['institution']} \u2014 "
                    f"{match.get('city') or ''} {match.get('country') or ''}"
                ).strip() + (
                    f". Deadline: {match.get('deadline') or 'rolling'}. "
                    + (match.get("summary") or "")
                )
                if record.findtext("description") != expected_description:
                    finding("error", "rss-description-divergence", f"RSS entry {i}")
                categories = [c.text or "" for c in record.findall("category")]
                if categories != match.get("disciplines"):
                    finding("error", "rss-category-divergence", f"RSS entry {i}")
                original = _date(match.get("first_seen_at"))
                if original is not None:
                    try:
                        in_feed = parsedate_to_datetime(published)
                        if in_feed.tzinfo is None or (
                            abs((in_feed.astimezone(UTC) - original).total_seconds()) > 1
                        ):
                            finding("error", "rss-publish-date-divergence", f"RSS entry {i}")
                    except (TypeError, ValueError, IndexError):
                        pass
            if link not in links:
                finding("error", "rss-link-absent-public", f"RSS entry {i}")
            if not _web_url(link):
                finding("error", "invalid-rss-link", f"RSS entry {i}")
            try:
                parsedate_to_datetime(published)
            except (TypeError, ValueError, IndexError):
                finding("error", "invalid-rss-date", f"RSS entry {i}")
        site = channel.findtext("link") or ""
        atom = channel.find("{http://www.w3.org/2005/Atom}link")
        self_url = atom.get("href", "") if atom is not None else ""
        if not _web_url(site):
            finding("error", "invalid-feed-site-url", "RSS channel homepage is not a URL")
        if atom is None or not _web_url(self_url):
            finding("error", "invalid-feed-self-url", "RSS self-link absent or invalid")
        built = channel.findtext("lastBuildDate")
        if stamp and built:
            try:
                rss_generated = parsedate_to_datetime(built)
                if rss_generated.tzinfo is None or abs(
                    (rss_generated.astimezone(UTC) - stamp).total_seconds()
                ) > 300:
                    finding("warning", "rss-snapshot-clock-skew",
                            "RSS lastBuildDate and dashboard generated_at differ")
            except (TypeError, ValueError, IndexError):
                finding("error", "invalid-rss-build-date", "RSS lastBuildDate invalid")
        if OLD_SITE in site or OLD_SITE in self_url:
            finding("warning", "obsolete-feed-origin", "RSS still advertises legacy host path")
        if EXPECTED_SITE not in site and OLD_SITE not in site:
            finding("warning", "unverified-feed-origin", "RSS is on a non-default site URL")

    health_stamp = _date(health.get("generated_at"))
    if not health_stamp:
        finding("error", "invalid-health-timestamp", "Health generated_at missing or invalid")
    elif stamp and abs((health_stamp - stamp).total_seconds()) > 300:
        finding("warning", "cross-snapshot-clock-skew",
                "Dashboard and health snapshots appear to come from different runs")

    source = health.get("source_summary")
    if isinstance(source, dict):
        categories = ("successful", "empty", "failed", "partial", "skipped")
        values = [source.get(k, 0) for k in categories]
        if any(type(x) is not int or x < 0 for x in values):
            finding("error", "bad-health-counts", "Health counters must be nonnegative integers")
        elif sum(values) != source.get("total", -1):
            finding("warning", "overlapping-health-categories",
                    "Public source categories are not mutually exclusive")
    else:
        finding("error", "bad-health-summary", "Source-health summary missing")
    runs = health.get("runs")
    if not isinstance(runs, list):
        finding("error", "bad-health-runs", "Run history must be an array")
    else:
        for run in runs:
            if not isinstance(run, dict):
                finding("error", "bad-run-entry", "Run history contains a non-object")
                continue
            if run.get("outcome") == "ok":
                s = run.get("source_summary") or {}
                if s.get("failed") or s.get("partial") or run.get("errors"):
                    finding("warning", "misclassified-run",
                            f"Run {str(run.get('run_id'))[:32]} marked ok despite failures")
    return summary, findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--strict", action="store_true",
                        help="Exit nonzero for structural errors, never for semantic warnings")
    parser.add_argument("--json-report", type=Path,
                        help="Write complete findings as a GitHub Actions artifact")
    args = parser.parse_args()
    summary, findings = audit(args.root)
    counts = Counter(item["severity"] for item in findings)
    if args.json_report:
        target = args.json_report
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps({
            "summary": summary, "counts": dict(counts), "findings": findings,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
    print("Publication snapshot:", json.dumps(summary, sort_keys=True))
    print(f"Integrity issues: {counts['error']} errors, {counts['warning']} warnings")
    for item in findings[:60]:
        print(f"{item['severity'].upper()} [{item['code']}] {item['message']}")
    if len(findings) > 60:
        print(f"... {len(findings) - 60} additional findings omitted")
    return int(args.strict and counts["error"] > 0)


if __name__ == "__main__":
    sys.exit(main())
