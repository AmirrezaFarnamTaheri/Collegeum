"""Explicitly approved, robots-aware PDF evidence review; never publishes.

Use with the installed pypdf dependency, e.g.
    uv run --locked python tools/official_call_pdf_review.py --source-id \
      ieb-document-index --url https://ieb.ub.edu/...pdf --fetch
The existing stdlib-only daily HTML monitor never invokes this reviewer.
Its output is a *separate review artifact*, not a publishable call catalogue.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.official_pdf_worker import MAX_PDF_BYTES
from tools.update_official_calls import (
    CALL_TITLE,
    EXCLUDE,
    SUBJECT,
    USER_AGENT,
    SafeRedirect,
    _date_candidates,
    _funding_closed,
    _intake,
    _stamp,
    safe_official_url,
)

ROOT = Path(__file__).resolve().parents[1]
MAX_PDF_TEXT = 24000
MAX_PDF_SECONDS = 8
MAX_ROBOTS_BYTES = 256 * 1024


def safe_pdf_url(raw: str, root: str) -> str | None:
    """Only HTTPS, same-host, direct PDF paths without query/credentials."""
    try:
        base = urllib.parse.urlsplit(root)
        url = urllib.parse.urlsplit(urllib.parse.urljoin(root, raw))
        host = (url.hostname or "").lower().removeprefix("www.")
        expected = (base.hostname or "").lower().removeprefix("www.")
        port, base_port = url.port, base.port
    except (TypeError, ValueError):
        return None
    if (url.scheme != "https" or base.scheme != "https" or not host or host != expected
            or port not in (None, 443) or base_port not in (None, 443)
            or url.username or url.password or base.username or base.password
            or url.query or url.fragment or "%" in url.path
            or not url.path.startswith("/") or len(url.path) > 350
            or not re.search(r"\.pdf\Z", url.path, re.I)):
        return None
    return urllib.parse.urlunsplit(("https", url.netloc, url.path, "", ""))


def approved_pdf(source: dict[str, Any], url: str) -> dict[str, str] | None:
    """Registry review must whitelist each exact URL and title/identity pair."""
    root = source.get("url")
    if not isinstance(root, str) or safe_pdf_url(url, root) != url:
        return None
    approved = source.get("approved_documents", [])
    if not isinstance(approved, list) or len(approved) > 6:
        return None
    for item in approved:
        if not isinstance(item, dict) or item.get("url") != url:
            continue
        title = item.get("title")
        marker = item.get("institution_marker")
        canonical = item.get("canonical_html_url")
        if (not isinstance(title, str) or not CALL_TITLE.search(title)
                or EXCLUDE.search(title) or len(title) > 150
                or not isinstance(marker, str) or not 8 <= len(marker) <= 100
                or not isinstance(canonical, str)
                or safe_official_url(canonical, root) != canonical):
            return None
        return {"title": title, "institution_marker": marker,
                "canonical_html_url": canonical}
    return None


def fetch_reviewed_pdf(url: str, source: dict[str, Any]) -> dict[str, Any]:
    """Fetch only one explicitly approved direct PDF after a robots check.

    Never follows off-host/non-PDF/unapproved redirects and never fetches
    documents opportunistically from HTML indexes. No unsafe file macros.
    """
    approval = approved_pdf(source, url)
    if approval is None:
        return {"status": "document_unverified", "reason": "not_approved"}
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    robot = urllib.robotparser.RobotFileParser()
    robot.set_url(f"https://{host}/robots.txt")
    opener = urllib.request.build_opener(SafeRedirect(
        host, lambda candidate: (
            safe_pdf_url(candidate, source["url"]) == candidate
            and robot.can_fetch(USER_AGENT, candidate)
        ),
    ))
    try:
        req = urllib.request.Request(
            f"https://{host}/robots.txt", headers={"User-Agent": USER_AGENT},
        )
        try:
            with opener.open(req, timeout=8) as reply:
                robots = reply.read(MAX_ROBOTS_BYTES + 1)
                if len(robots) > MAX_ROBOTS_BYTES:
                    return {"status": "robots_unavailable"}
                robot.parse(robots.decode("utf-8", errors="replace").splitlines())
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                return {"status": "robots_unavailable"}
            robot.allow_all = True
        if not robot.can_fetch(USER_AGENT, url):
            return {"status": "robots_disallowed"}
        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Accept": "application/pdf",
        })
        with opener.open(request, timeout=8) as reply:
            if reply.geturl() != url:
                return {"status": "unsafe_redirect"}
            kind = reply.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if kind != "application/pdf":
                return {"status": "document_unverified", "reason": "wrong_content_type"}
            data = reply.read(MAX_PDF_BYTES + 1)
            if len(data) > MAX_PDF_BYTES:
                return {"status": "document_unverified", "reason": "oversize"}
            if not data.startswith(b"%PDF-"):
                return {"status": "document_unverified", "reason": "not_pdf"}
            return {"status": "ok", "content": data, "content_type": kind}
    except (OSError, TimeoutError, UnicodeError, ValueError, urllib.error.URLError):
        return {"status": "fetch_failed"}


def _limits() -> None:
    if os.name == "posix":
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (5, 6))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)


def _extract_text(content: bytes) -> dict[str, Any]:
    """Run pypdf in a separate memory/CPU/time-constrained, network-free worker."""
    try:
        response = subprocess.run(
            [sys.executable, "-m", "tools.official_pdf_worker"],
            input=content, capture_output=True, check=False,
            cwd=ROOT, timeout=MAX_PDF_SECONDS,
            **({"preexec_fn": _limits} if os.name == "posix" else {}),
        )
        if (response.returncode != 0 or len(response.stdout) > MAX_PDF_TEXT * 5):
            return {"status": "document_unverified", "reason": "worker_failed"}
        result = json.loads(response.stdout.decode("utf-8"))
        if not isinstance(result, dict) or result.get("status") not in {
            "ok", "document_unverified",
        }:
            raise ValueError("Unexpected PDF worker result")
        return result
    except (OSError, subprocess.TimeoutExpired, ValueError, UnicodeError):
        return {"status": "document_unverified", "reason": "worker_failed"}


def review_pdf_bytes(
    content: bytes, *, url: str, source: dict[str, Any], now: datetime,
    content_type: str,
) -> dict[str, Any]:
    """Return independently extracted evidence for *review*, never Telegram."""
    result: dict[str, Any] = {
        "status": "document_unverified",
        "reason": "not_approved",
        "source_id": source.get("id"),
        "official_url": url,
        "evidence_url": url,
        "reviewed_at": _stamp(now),
    }
    if now.tzinfo is None:
        raise ValueError("Expected aware clock")
    approval = approved_pdf(source, url)
    if approval is None:
        return result
    if not isinstance(content, bytes) or len(content) > MAX_PDF_BYTES:
        result["reason"] = "oversize"
        return result
    if content_type.split(";", 1)[0].strip().lower() != "application/pdf":
        result["reason"] = "wrong_content_type"
        return result
    if not content.startswith(b"%PDF-"):
        result["reason"] = "not_pdf"
        return result
    parsed = _extract_text(content)
    if parsed.get("status") != "ok":
        result["reason"] = parsed.get("reason", "invalid_pdf")
        return result
    text = parsed.get("text")
    if not isinstance(text, str) or not 100 <= len(text) <= MAX_PDF_TEXT:
        result["reason"] = "no_usable_text"
        return result
    if (approval["institution_marker"].casefold() not in text.casefold()
            or approval["title"].casefold() not in text.casefold()
            or not SUBJECT.search(text) or not CALL_TITLE.search(approval["title"])):
        result["reason"] = "missing_institution_or_title"
        return result
    # One explicit candidate requirement is mandatory: the document cannot
    # merely mention the institution and an arbitrary distant date.
    if not re.search(r"\b(?:candidates?|applicants?)\s+must\b|\beligib(?:le|ility)\b",
                     text, re.I):
        result["reason"] = "missing_eligibility"
        return result
    intake = _intake(approval["title"], text)
    if intake is None or not now.year <= intake <= now.year + 2:
        result["reason"] = "invalid_intake"
        return result
    if _funding_closed(text, intake):
        result["reason"] = "closed"
        return result
    dates = _date_candidates(text, kind="phd_scholarship", now=now)
    unique = {day for day, _, _ in dates}
    if (len(unique) != 1 or not dates or
            any(kind == "ambiguous" for _, kind, _ in dates)):
        result["reason"] = "ambiguous_or_missing_funding_deadline"
        return result
    deadline, deadline_kind, excerpt = dates[0]
    result.update(
        status="document_review_only", reason=None, title=approval["title"],
        institution=source.get("institution"), country_code=source.get("country_code"),
        kind="phd_scholarship", intake_year=intake,
        deadline_iso=deadline.isoformat(), deadline_kind=deadline_kind,
        evidence_excerpt=excerpt,
        canonical_html_url=approval["canonical_html_url"],
        document_sha256=hashlib.sha256(content).hexdigest(),
        automatic_publication=False,
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--url", required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--file", type=Path, help="Review a locally supplied PDF")
    selection.add_argument("--fetch", action="store_true",
                           help="Fetch a previously approved PDF, subject to robots")
    args = parser.parse_args(argv)
    registry = json.loads((ROOT / "config/official_phd_calls_sources.json").read_text())
    source = next((item for item in registry["sources"]
                   if item.get("id") == args.source_id), None)
    if source is None or approved_pdf(source, args.url) is None:
        print(json.dumps({"status": "document_unverified", "reason": "not_approved"}))
        return 2
    if args.file is not None:
        with args.file.open("rb") as handle:
            content = handle.read(MAX_PDF_BYTES + 1)
        fetched = {"status": "ok", "content": content, "content_type": "application/pdf"}
    else:
        fetched = fetch_reviewed_pdf(args.url, source)
    if fetched["status"] != "ok":
        print(json.dumps(fetched, ensure_ascii=True))
        return 2
    row = review_pdf_bytes(
        fetched["content"], url=args.url, source=source,
        now=datetime.now(UTC), content_type=fetched["content_type"],
    )
    print(json.dumps(row, indent=2, ensure_ascii=True))
    return 0 if row["status"] == "document_review_only" else 2


if __name__ == "__main__":
    sys.exit(main())
