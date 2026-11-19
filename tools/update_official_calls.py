"""Bounded, robots-aware discovery of independent official Economics PhD calls.

Independent of LinkedIn feed posts, third-party deadlines and the 251-programme
admissions directory. No Telegram credentials, vacancy ingestion or remote sends.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "config/official_phd_calls_sources.json"
CATALOG = ROOT / "docs/data/official_phd_calls.json"
USER_AGENT = "CollegeumOfficialCalls/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)"
MAX_HTML_BYTES = 1024 * 1024
MAX_ROBOTS_BYTES = 256 * 1024
MAX_INDEX_LINKS = 6
MAX_SOURCES = 20
MAX_CALLS = 100
MAX_CHECK_AGE = timedelta(days=14)
STATUSES = {"verified", "no_explicit_deadline", "ambiguous_deadline", "unrelated",
            "robots_unavailable", "robots_disallowed", "fetch_failed", "unsafe_redirect",
            "not_seen"}
DATE_RE = re.compile(
    r"\b(?P<iso>20\d{2}-\d{2}-\d{2})\b|"
    r"\b(?P<d1>\d{1,2})(?:st|nd|rd|th)?\s+(?P<m1>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
    r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s*,?\s*(?P<y1>20\d{2})\b|"
    r"\b(?P<m2>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
    r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+(?P<d2>\d{1,2})(?:st|nd|rd|th)?"
    r"\s*,?\s*(?P<y2>20\d{2})\b",
    re.I,
)
CALL_TITLE = re.compile(r"\bph\.?\s*d\.?\b.*\b(?:scholarships?|fellowships?|studentships?)\b|"
                        r"\b(?:scholarships?|fellowships?|studentships?)\b.*\bph\.?\s*d\.?\b", re.I)
EXCLUDE = re.compile(r"\b(?:post[-\s]?doc(?:toral)?|assistant professor|"
                     r"visiting professor|workshop|seminar|conference)\b", re.I)
SUBJECT = re.compile(r"\b(?:economics?|finance|account(?:ing|ancy)|"
                     r"business|econometrics?|climate|energy|"
                     r"quantitative|strategy|informatics|operations)\b", re.I)
_RESTRICTED_PATH = re.compile(
    r"(?:\.(?:pdf|docx?|xlsx?|zip|png|jpe?g)$|"
    r"/(?:login|log-in|signup|register|api|wp-admin|job-market|events?)(?:/|$))", re.I,
)


class CallHTML(HTMLParser):
    """Tiny stdlib HTML-to-text/anchor parser; never runs page scripts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        # Keep the article beginning at its first H1 distinct from site navigation.
        self.content_chunks: list[str] = []
        self._content_started = False
        self.headings: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._ignored = 0
        self._heading: list[str] | None = None
        self._link: list[str] | None = None
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self._ignored += 1
            return
        if self._ignored:
            return
        if tag == "h1":
            self._content_started = True
            self._heading = []
        if tag in {"p", "li", "div", "h1", "h2", "h3", "footer", "br", "tr"}:
            self.chunks.append(" ")
            if self._content_started:
                self.content_chunks.append(" ")
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._link = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self._ignored = max(0, self._ignored - 1)
            return
        if self._ignored:
            return
        if tag == "h1" and self._heading is not None:
            heading = " ".join(" ".join(self._heading).split())
            if heading:
                self.headings.append(heading)
            self._heading = None
        if tag == "a":
            label = " ".join(" ".join(self._link or []).split())
            if self._href and label:
                self.links.append((self._href, label))
            self._link, self._href = None, None
        if tag in {"p", "li", "div", "h1", "h2", "h3", "footer", "tr"}:
            self.chunks.append(" ")
            if self._content_started:
                self.content_chunks.append(" ")

    def handle_data(self, data: str) -> None:
        if self._ignored:
            return
        self.chunks.append(data)
        if self._content_started:
            self.content_chunks.append(data)
        if self._heading is not None:
            self._heading.append(data)
        if self._link is not None:
            self._link.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self.chunks).split())

    def content_text(self) -> str:
        return " ".join(" ".join(self.content_chunks).split())


def safe_official_url(raw: str, root: str) -> str | None:
    """HTTPS exact-host links only, without tracking queries, credentials or files."""
    try:
        base = urllib.parse.urlsplit(root)
        parsed = urllib.parse.urlsplit(urllib.parse.urljoin(root, raw))
        host = (parsed.hostname or "").lower().removeprefix("www.")
        expected = (base.hostname or "").lower().removeprefix("www.")
        port, base_port = parsed.port, base.port
    except (ValueError, TypeError):
        return None
    if (parsed.scheme != "https" or base.scheme != "https" or host != expected
            or not host or port not in (None, 443) or base_port not in (None, 443)
            or parsed.username or parsed.password or base.username or base.password
            or _RESTRICTED_PATH.search(parsed.path)
            or not parsed.path.startswith("/") or len(parsed.path) > 350):
        return None
    # Avoid query-driven search requests, tracking aliases and duplicate variants.
    if parsed.query:
        return None
    return urllib.parse.urlunsplit(("https", parsed.netloc, parsed.path, "", ""))


def _date(match: re.Match[str]) -> date | None:
    try:
        if match.group("iso"):
            return date.fromisoformat(match.group("iso"))
        month = (match.group("m1") or match.group("m2")).lower()[:3]
        m = ("jan", "feb", "mar", "apr", "may", "jun", "jul",
             "aug", "sep", "oct", "nov", "dec").index(month) + 1
        return date(int(match.group("y1") or match.group("y2")), m,
                    int(match.group("d1") or match.group("d2")))
    except (TypeError, ValueError):
        return None


def _stamp(now: datetime) -> str:
    return now.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _location_proof(text: str, country: str, url: str) -> str | None:
    host = (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")
    suffix = "uk" if country in {"UK", "GB"} else country.lower()
    if host.endswith("." + suffix):
        return f"{country}: official national institutional domain {host}"
    # The generic .edu domain needs independent contact evidence, not the
    # institution name or an upstream discovery-list country assumption.
    if country == "ES" and re.search(
        r"(?:C/\s*John\s+M\.\s*Keynes.{0,55}08034\s+Barcelona|"
        r"08034\s+Barcelona.{0,80}(?:Tel\.?\s*)?\+\s*34)", text, re.I,
    ) and re.search(r"(?:Tel\.?\s*)?\+\s*34\s*\d{2}", text, re.I):
        return "ES: official postal address 08034 Barcelona and telephone +34"
    return None


def _intake(title: str, text: str) -> int | None:
    match = re.search(r"\b(20\d{2})\b", title)
    if match:
        return int(match.group(1))
    for match in re.finditer(
        r"(?:studentship|scholarship) applications for the (20\d{2})/\d{2} academic year",
        text, re.I,
    ):
        # A previous, closed cycle is not an open scholarship.
        if re.search(r"\bnow\s+open\b", text[match.end():match.end() + 95], re.I):
            return int(match.group(1))
    match = re.search(
        r"(?:starting|start(?:s|ing)?)\s+(?:in\s+)?"
        r"(?:September|October|Autumn)"
        r"(?:\s*(?:/|or)\s*(?:September|October))?\s+(20\d{2})", text, re.I,
    )
    return int(match.group(1)) if match else None


def _date_candidates(text: str, *, kind: str, now: datetime) -> list[tuple[date, str, str]]:
    candidates: list[tuple[date, str, str]] = []
    for match in DATE_RE.finditer(text):
        day = _date(match)
        if day is None or not now.date() <= day <= date(now.year + 2, 12, 31):
            continue
        before = text[max(0, match.start() - 190):match.start()]
        after = text[match.end():match.end() + 38]
        # These are application-funding cutoffs, never generic PhD admissions,
        # orientation dates, recommendations or grant decision announcements.
        funding = bool(re.search(
            r"(?:scholarship|studentship|fellowship)\s+applications?.{0,125}"
            r"(?:deadline|close(?:s|d)?\s+on|due(?:\s+to)?|by)\s*$",
            before, re.I,
        ))
        if not funding:
            funding = bool(re.search(
                r"(?:studentship|scholarship)\s+applications?.{0,125}"
                r"(?:will\s+close\s+on)\s*$", before, re.I,
            ))
        if not funding and kind == "phd_studentship":
            # On a PhD-studentship-specific official page, a clearly marked
            # funding Deadline section may say "deadline for applications"
            # instead of repeating "studentship". Never generalize this to
            # a university-wide PhD admissions page.
            funding = bool(re.search(
                r"\bDeadline\s+(?:The\s+)?deadline\s+for\s+applications\s+is\s+"
                r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+)?$",
                before, re.I,
            ))
        submission = kind != "phd_studentship" and bool(re.search(
            r"interested\s+candidates\s+must\s+complete\s+both.{0,100}"
            r"(?:steps\s+)?(?:by|before)\s*$", before, re.I,
        ))
        if not (funding or submission):
            continue
        # An "or" alternative may be a second distinct legal cutoff.
        candidate_excerpt = " ".join(
            (text[max(0, match.start() - 120):match.end() + 40]).split()
        )
        candidates.append((day, "funding" if funding else "scholarship",
                           candidate_excerpt[:230]))
        if re.match(r"\s+or\s+", after, re.I):
            return [(day, "ambiguous", candidate_excerpt)]
    return candidates


def extract_call(
    html: str, *, url: str, source: dict[str, Any], now: datetime,
) -> dict[str, Any]:
    """Pure extraction. Missing or conflicting official evidence fails closed."""
    if now.tzinfo is None:
        raise ValueError("Expected timezone-aware clock")
    parsed = CallHTML()
    parsed.feed(html[:MAX_HTML_BYTES])
    text = parsed.text()
    # Long institutional menus can exceed 450 characters; only the primary
    # funding call's article, not navigation/footer, establishes subject fit.
    article = parsed.content_text() or text
    title = (parsed.headings[0] if parsed.headings else source.get("title", "")).strip()
    label = f"{title} {source.get('title', '')}"
    invalid = (not title or len(title) > 150
               or not SUBJECT.search(label + " " + article[:1800])
               or EXCLUDE.search(title)
               or not safe_official_url(url, source["url"]))
    # Mentioning scholarship terms somewhere in a generic admissions page
    # does not create an independent current funding call.
    relevant = CALL_TITLE.search(label) is not None
    status = "unrelated" if invalid or not relevant else "no_explicit_deadline"
    kind = ("phd_studentship" if "studentship" in (label + " " + article[:500]).lower()
            else "phd_fellowship" if "fellowship" in label.lower()
            else "phd_scholarship")
    intake_year = _intake(title, article)
    date_iso = None
    deadline_kind = None
    excerpt = None
    if status != "unrelated":
        values = _date_candidates(article, kind=kind, now=now)
        dates = {item[0] for item in values}
        if any(item[1] == "ambiguous" for item in values) or len(dates) > 1:
            status = "ambiguous_deadline"
        elif len(dates) == 1 and intake_year is not None:
            chosen = values[0]
            date_iso, deadline_kind, excerpt = (chosen[0].isoformat(), chosen[1], chosen[2])
            status = "verified"
    recommended = None
    if kind == "phd_studentship":
        rec = re.search(r"(?:strongly\s+advise|recommend)\s+submitting\s+your\s+"
                        r"application\s+no\s+later\s+than\s+", article, re.I)
        if rec:
            match = DATE_RE.search(article, rec.end())
            if match and match.start() - rec.end() <= 6:
                day = _date(match)
                if day and now.date() <= day <= date(now.year + 2, 12, 31):
                    recommended = day.isoformat()
    proof = _location_proof(text, str(source["country_code"]), url)
    # A broad, multi-disciplinary funding scheme is eligible, but must never
    # be advertised as Economics-only merely because one eligible school is
    # Henley. Only an Economics-specific call title earns the Economics label.
    scope = (
        "economics" if re.search(r"\b(?:economics?|econometrics?)\b", title, re.I)
        else "finance" if re.search(r"\b(?:finance|accounting|accountancy)\b", title, re.I)
        else "multidisciplinary"
    )
    return {
        "source_id": source["id"],
        "institution": source["institution"],
        "country_code": source["country_code"],
        "official_url": url,
        "title": title if status != "unrelated" else source.get("title", title)[:150],
        "status": status,
        "kind": kind,
        "subject_scope": scope,
        "intake_year": intake_year,
        "deadline_iso": date_iso,
        "deadline_kind": deadline_kind,
        "recommended_admission_iso": recommended,
        "evidence_url": url if date_iso else None,
        "evidence_excerpt": excerpt,
        "location_evidence": proof,
        "location_evidence_url": url if proof else None,
        "checked_at": _stamp(now),
    }


def discover_links(html: str, source: dict[str, Any]) -> list[str]:
    """Find all distinct relevant same-host HTML call pages, within a cap."""
    parser = CallHTML()
    parser.feed(html[:MAX_HTML_BYTES])
    root = source["url"]
    result: list[str] = []
    seen: set[str] = set()
    for href, label in parser.links[:500]:
        if not CALL_TITLE.search(label) or not SUBJECT.search(label) or EXCLUDE.search(label):
            continue
        candidate = safe_official_url(href, root)
        if (candidate is not None and candidate != root and candidate not in seen
                and candidate not in result):
            result.append(candidate)
            seen.add(candidate)
            if len(result) >= MAX_INDEX_LINKS:
                break
    return result


def validate_sources(config: Any) -> None:
    if (not isinstance(config, dict)
            or config.get("kind") != "official_phd_call_sources"
            or config.get("version") != 1
            or not isinstance(config.get("sources"), list)
            or not 1 <= len(config["sources"]) <= MAX_SOURCES):
        raise ValueError("Invalid approved official-call source registry")
    ids: set[str] = set()
    for source in config["sources"]:
        if not isinstance(source, dict):
            raise ValueError("Invalid call source")
        name = source.get("id")
        url = source.get("url")
        if (not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,45}", name)
                or name in ids or not isinstance(url, str)
                or safe_official_url(url, url) != url
                or source.get("mode") not in {"index", "detail"}
                or not isinstance(source.get("institution"), str)
                or not 5 <= len(source["institution"]) <= 120
                or source.get("country_code") not in {"ES", "UK", "GB", "DE", "FI",
                                                      "FR", "NL", "IT", "SE", "NO",
                                                      "DK", "CH", "AT", "BE"}):
            raise ValueError("Unapproved or malformed official-call source")
        ids.add(name)


def validate_catalog(catalog: Any) -> None:
    if (not isinstance(catalog, dict)
            or catalog.get("kind") != "official_phd_call_observations"
            or catalog.get("version") != 1
            or not isinstance(catalog.get("calls"), list)
            or not isinstance(catalog.get("sources"), list)
            or len(catalog["calls"]) > MAX_CALLS):
        raise ValueError("Invalid official-call catalogue")


def refresh_sources(
    config: dict[str, Any], previous: dict[str, Any], *,
    now: datetime, fetcher: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    validate_sources(config)
    # An empty fixture may supply calls without source summaries.
    if previous.get("calls") and previous.get("sources") is None:
        previous = {**previous, "sources": []}
    if previous.get("sources") is None:
        previous = {**previous, "sources": []}
    validate_catalog(previous)
    calls: dict[str, dict[str, Any]] = {}
    prior = previous.get("calls", [])
    if len(prior) > MAX_CALLS:
        raise ValueError("Unbounded prior call catalogue")
    for row in prior:
        if not isinstance(row, dict):
            raise ValueError("Invalid prior call")
        url = row.get("official_url")
        if isinstance(url, str):
            calls[url] = {**row, "status": "not_seen", "deadline_iso": None}
    summaries = []
    for source in config["sources"]:
        response = fetcher(source["url"])
        status = response.get("status") if isinstance(response, dict) else "fetch_failed"
        urls: list[str] = []
        failures = 0
        if status == "ok" and isinstance(response.get("html"), str):
            if source["mode"] == "index":
                urls = discover_links(response["html"], source)
                # Older but still-open official calls can scroll off a paginated
                # university index. Recheck at most two within the same source
                # and deadline window, without trusting cached dates for sending.
                historical = sorted(
                    (
                        row for row in prior
                        if row.get("source_id") == source["id"]
                        and row.get("status") == "verified"
                        and isinstance(row.get("deadline_iso"), str)
                        and row["deadline_iso"] >= now.date().isoformat()
                        and isinstance(row.get("official_url"), str)
                        and safe_official_url(row["official_url"], source["url"])
                            == row["official_url"]
                        and row["official_url"] not in urls
                    ),
                    key=lambda item: (item["deadline_iso"], item["official_url"]),
                )[:2]
                urls.extend(row["official_url"] for row in historical)
            else:
                urls = [source["url"]]
        elif status not in STATUSES:
            status = "fetch_failed"
        for url in urls:
            detail = response if url == source["url"] else fetcher(url)
            if not isinstance(detail, dict) or detail.get("status") != "ok":
                failures += 1
                calls[url] = {
                    "source_id": source["id"], "institution": source["institution"],
                    "country_code": source["country_code"], "official_url": url,
                    "status": str(detail.get("status", "fetch_failed"))
                    if isinstance(detail, dict) else "fetch_failed",
                    "checked_at": _stamp(now), "deadline_iso": None,
                }
                continue
            final_url = detail.get("final_url", url)
            if (not isinstance(final_url, str)
                    or safe_official_url(final_url, source["url"]) != final_url):
                failures += 1
                continue
            html = detail.get("html")
            if not isinstance(html, str) or len(html.encode("utf-8")) > MAX_HTML_BYTES:
                failures += 1
                continue
            row = extract_call(html, url=final_url, source=source, now=now)
            calls[final_url] = row
        summaries.append({
            "id": source["id"], "institution": source["institution"],
            "index_url": source["url"], "status": (
                "partial" if failures else status
            ),
            "failed_details": failures, "candidate_count": len(urls),
            "checked_at": _stamp(now),
        })
    return {
        "kind": "official_phd_call_observations", "version": 1,
        "generated_at": _stamp(now), "sources": summaries,
        "calls": sorted(calls.values(), key=lambda row: row.get("official_url", "")),
    }


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, host: str, allowed: Callable[[str], bool]) -> None:
        self.host = host
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            parsed = urllib.parse.urlsplit(newurl)
        except ValueError:
            raise ValueError("unsafe_redirect") from None
        if (parsed.scheme != "https"
                or (parsed.hostname or "").lower() != self.host
                or not self.allowed(newurl)):
            raise ValueError("unsafe_redirect") from None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_official(url: str) -> dict[str, Any]:
    """One robots check per host, fail-closed for blocked or unavailable sites."""
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname
        if parsed.scheme != "https" or not host or safe_official_url(url, url) != url:
            return {"status": "unsafe_redirect"}
        robot = urllib.robotparser.RobotFileParser()
        robot.set_url(f"https://{host}/robots.txt")
        opener = urllib.request.build_opener(
            SafeRedirect(host, lambda candidate: robot.can_fetch(USER_AGENT, candidate))
        )
        def read(address: str, limit: int) -> tuple[bytes, str]:
            req = urllib.request.Request(address, headers={
                "User-Agent": USER_AGENT, "Accept": "text/html",
            })
            with opener.open(req, timeout=9) as reply:
                data = reply.read(limit + 1)
                if len(data) > limit:
                    raise ValueError("response_too_large")
                return data, reply.geturl()
        try:
            robots, _ = read(f"https://{host}/robots.txt", MAX_ROBOTS_BYTES)
            robot.parse(robots.decode("utf-8", errors="replace").splitlines())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                robot.allow_all = True
            else:
                return {"status": "robots_unavailable"}
        except (OSError, TimeoutError, UnicodeError, ValueError):
            return {"status": "robots_unavailable"}
        if not robot.can_fetch(USER_AGENT, url):
            return {"status": "robots_disallowed"}
        body, final = read(url, MAX_HTML_BYTES)
        if safe_official_url(final, url) != final or body.lstrip().startswith(b"%PDF"):
            return {"status": "unsafe_redirect"}
        if not body.lstrip().lower().startswith((b"<", b"<!doctype")):
            return {"status": "fetch_failed"}
        return {"status": "ok", "html": body.decode("utf-8", errors="replace"),
                "final_url": final}
    except (OSError, TimeoutError, UnicodeError, ValueError, urllib.error.HTTPError):
        return {"status": "fetch_failed"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Offline validation only")
    args = parser.parse_args(argv)
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))
    old = json.loads(CATALOG.read_text(encoding="utf-8"))
    validate_sources(sources)
    validate_catalog(old)
    if args.check:
        print("Official calls: registry and catalogue valid; network not used")
        return 0
    new = refresh_sources(sources, old, now=datetime.now(UTC), fetcher=fetch_official)
    CATALOG.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    counts: dict[str, int] = {}
    for row in new["calls"]:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print("Official PhD call discovery:", json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
