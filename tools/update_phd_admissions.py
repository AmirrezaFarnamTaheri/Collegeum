"""Rotate official Economics PhD admissions checks without reusing third-party dates.

Only programme URLs are adopted as discovery leads from the MIT-licensed source.
A date is surfaced only when the university's own page explicitly contains a
current-year/future-year date with local Economics PhD + deadline context.

This standalone monitor never imports the vacancies pipeline, touches journals,
publishes to Telegram, or uses LLM guesses. A failed/blocked check fails closed.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "config/phd_admissions_seeds.json"
PUBLIC = ROOT / "docs/data/phd_admissions.json"
USER_AGENT = "CollegeumAdmissionsMonitor/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)"
CHECK_INTERVAL = timedelta(days=11)
EXPIRY = timedelta(days=14)
MAX_HTML_BYTES = 1024 * 1024
MAX_ROBOTS_BYTES = 256 * 1024
DATE_PATTERN = re.compile(
    r"\b(?P<iso>20\d{2}-\d{2}-\d{2})\b|"
    r"\b(?P<day>\d{1,2})\s+(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s*,?\s*(?P<year>20\d{2})\b|"
    r"\b(?P<month2>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(?P<day2>\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(?P<year2>20\d{2})\b",
    re.I,
)
PROGRAMME = re.compile(
    r"(?:economics?\s+(?:ph\.?d\.?|doctor(?:al|ate))|"
    r"(?:ph\.?d\.?|doctor(?:al|ate))\s+(?:in\s+)?economics?)",
    re.I,
)
DEADLINE = re.compile(
    r"(?:application(?:s)?\s+)?deadlines?|"
    r"applications?\s+(?:close|due|must\s+be\s+submitted)|"
    r"apply\s+by|"
    r"submission\s+deadline",
    re.I,
)
STATUSES = {
    "unverified", "verified", "no_explicit_deadline", "ambiguous_deadline",
    "robots_disallowed", "robots_unavailable", "fetch_failed",
    "unsafe_redirect", "insecure_source", "stale",
}


class PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg", "noscript", "template"}:
            self.ignored += 1
        elif tag in {"p", "div", "h1", "h2", "h3", "li", "tr", "br"}:
            self.chunks.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "noscript", "template"}:
            self.ignored = max(0, self.ignored - 1)
        elif tag in {"p", "div", "h1", "h2", "h3", "li", "tr"}:
            self.chunks.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.chunks.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self.chunks).split())


def _parse_date(match: re.Match[str]) -> date | None:
    try:
        if match.group("iso"):
            return date.fromisoformat(match.group("iso"))
        day = int(match.group("day") or match.group("day2"))
        month_name = (match.group("month") or match.group("month2")).lower()[:3]
        months = (
            "jan", "feb", "mar", "apr", "may", "jun",
            "jul", "aug", "sep", "oct", "nov", "dec",
        )
        month = months.index(month_name) + 1
        return date(int(match.group("year") or match.group("year2")), month, day)
    except (ValueError, TypeError):
        return None


def collect_official_deadline(html: str, *, now: datetime) -> tuple[str, str | None, str | None]:
    """Extract only an explicit, unambiguous date near PhD economics context.

    No inference from month/day without a year, academic intake, an expired date,
    another subject, or an admissions aggregator is allowed.
    """
    parser = PageText()
    parser.feed(html[:MAX_HTML_BYTES])
    text = parser.text()[:MAX_HTML_BYTES]
    candidates: list[tuple[str, str]] = []
    for match in DATE_PATTERN.finditer(text):
        day = _parse_date(match)
        if day is None or not (now.date() <= day <= date(now.year + 2, 12, 31)):
            continue
        before = text[max(0, match.start() - 310):match.start()]
        # The school/programme and the deadline must be before the date,
        # not mentioned afterwards in a list of unrelated courses.
        programmes = list(PROGRAMME.finditer(before))
        deadlines = list(DEADLINE.finditer(before))
        if not programmes or not deadlines:
            continue
        programme = programmes[-1]
        deadline = deadlines[-1]
        if programme.start() > deadline.start() or deadline.start() - programme.end() > 165:
            continue
        if len(before) - deadline.end() > 110:
            continue
        excerpt = text[max(0, match.start() - 115):min(len(text), match.end() + 20)]
        candidates.append((day.isoformat(), excerpt.strip()))
    distinct = {day for day, _ in candidates}
    if len(distinct) > 1:
        return "ambiguous_deadline", None, None
    if len(distinct) == 1:
        day, excerpt = candidates[0]
        return "verified", day, excerpt[:180]
    return "no_explicit_deadline", None, None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except ValueError:
        return None


def eligible_for_check(entry: dict, *, now: datetime) -> bool:
    checked = _timestamp(entry.get("checked_at"))
    return checked is None or checked > now or now - checked >= CHECK_INTERVAL


def _key(item: dict) -> tuple[str, str]:
    return item["institution"], item["country_code"]


def validate_catalogues(seeds: dict, public: dict) -> None:
    if seeds.get("kind") != "economics_phd_admissions_seeds":
        raise ValueError("Unexpected seed type")
    if public.get("kind") != "economics_phd_admissions_observations":
        raise ValueError("Unexpected public catalogue type")
    if public.get("scope") != "official_programme_sources_only":
        raise ValueError("Public observations must be official-source only")
    if public.get("source", {}).get("deadline_values_reused") is not False:
        raise ValueError("Upstream dates must never be reused")
    rows = seeds.get("programmes")
    observations = public.get("programmes")
    if not isinstance(rows, list) or len(rows) != 251:
        raise ValueError("Unexpected seed count")
    if not isinstance(observations, list) or len(observations) != len(rows):
        raise ValueError("Unexpected public count")
    if len({_key(r) for r in rows}) != len(rows):
        raise ValueError("Duplicate seeds")
    if [_key(r) for r in rows] != [_key(r) for r in observations]:
        raise ValueError("Seed/observation ordering mismatch")
    for seed, observation in zip(rows, observations, strict=True):
        if not isinstance(seed.get("institution"), str) or not isinstance(
            seed.get("country_code"), str
        ):
            raise ValueError("Invalid programme")
        if not re.fullmatch(r"[A-Z]{2}", seed["country_code"]):
            raise ValueError("Invalid country code")
        if any(k in seed for k in ("deadline", "deadline_guidance", "deadline_iso")):
            raise ValueError("Unverified upstream deadline in seeds")
        url = seed.get("official_programme_url")
        if not isinstance(url, str) or urllib.parse.urlsplit(url).scheme not in {"https", "http"}:
            raise ValueError("Invalid institutional lead")
        if observation.get("official_programme_url") != url:
            raise ValueError("Source URLs must not be overwritten")
        if observation.get("status") not in STATUSES:
            raise ValueError("Unknown verification state")
        if "deadline_guidance" in observation or "published" in observation:
            raise ValueError("Upstream/reference values leaked")
        if observation["status"] == "verified":
            dt = observation.get("deadline_iso")
            if not isinstance(dt, str):
                raise ValueError("Invalid verified deadline")
            try:
                date.fromisoformat(dt)
            except ValueError as exc:
                raise ValueError("Malformed verified deadline") from exc
            if not observation.get("evidence_url") or not observation.get("evidence_excerpt"):
                raise ValueError("Verified dates require official evidence")
        elif observation.get("deadline_iso") is not None:
            raise ValueError("Unverified deadline must not be published")


class OfficialOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_host: str) -> None:
        self.allowed_host = allowed_host.lower().removeprefix("www.")

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if parsed.scheme != "https" or host != self.allowed_host:
            raise ValueError("unsafe_redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _read_url(url: str, *, host: str, limit: int) -> tuple[int, bytes, str]:
    opener = urllib.request.build_opener(OfficialOnlyRedirect(host))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with opener.open(req, timeout=9) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("response_too_large")
        return response.status, data, response.geturl()


def check_official_url(url: str, *, now: datetime) -> dict:
    """Respect robots.txt and use a single institutional host. Never crawl links."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return {"status": "insecure_source"}
    base = f"https://{parsed.hostname}"
    robots_url = base + "/robots.txt"
    try:
        _, data, _ = _read_url(robots_url, host=parsed.hostname, limit=MAX_ROBOTS_BYTES)
        robot = urllib.robotparser.RobotFileParser()
        robot.set_url(robots_url)
        robot.parse(data.decode("utf-8", errors="replace").splitlines())
        if not robot.can_fetch(USER_AGENT, url):
            return {"status": "robots_disallowed"}
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            return {"status": "robots_unavailable"}
    except (OSError, TimeoutError, ValueError, UnicodeError):
        return {"status": "robots_unavailable"}
    try:
        code, data, final_url = _read_url(url, host=parsed.hostname, limit=MAX_HTML_BYTES)
        if code != 200:
            return {"status": "fetch_failed"}
        html = data.decode("utf-8", errors="replace")
        status, deadline, excerpt = collect_official_deadline(html, now=now)
        return {"status": status, "deadline_iso": deadline,
                "evidence_url": final_url if status == "verified" else None,
                "evidence_excerpt": excerpt}
    except ValueError as exc:
        return {"status": "unsafe_redirect" if str(exc) == "unsafe_redirect" else "fetch_failed"}
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError, UnicodeError):
        return {"status": "fetch_failed"}


def refresh(seeds: dict, public: dict, *, now: datetime, batch_size: int,
            fetcher=check_official_url) -> dict:
    if batch_size < 1 or batch_size > 40:
        raise ValueError("batch_size must be 1..40")
    validate_catalogues(seeds, public)
    programmes = [dict(item) for item in public["programmes"]]
    # Stable daily shards, covers all 251 records in ceil(251 / batch_size) days.
    shard_count = math.ceil(len(programmes) / batch_size)
    shard = now.date().toordinal() % shard_count
    start, end = shard * batch_size, min((shard + 1) * batch_size, len(programmes))
    stamp = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    for index, entry in enumerate(programmes):
        old = _timestamp(entry.get("checked_at"))
        if entry.get("status") == "verified" and (
            old is None or now - old > EXPIRY or
            entry.get("deadline_iso", "") < now.date().isoformat()
        ):
            entry.update(status="stale", deadline_iso=None, evidence_url=None,
                         evidence_excerpt=None)
        if not (start <= index < end) or not eligible_for_check(entry, now=now):
            continue
        result = fetcher(entry["official_programme_url"], now=now)
        status = result.get("status")
        if status not in STATUSES - {"unverified", "stale"}:
            raise ValueError("Untrusted verifier status")
        entry.update(status=status, checked_at=stamp, deadline_iso=None,
                     evidence_url=None, evidence_excerpt=None)
        if status == "verified":
            entry.update(deadline_iso=result["deadline_iso"],
                         evidence_url=result["evidence_url"],
                         evidence_excerpt=result["evidence_excerpt"])
    result = dict(public)
    result["generated_at"] = stamp
    result["programmes"] = programmes
    validate_catalogues(seeds, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate offline; never fetch")
    parser.add_argument("--batch-size", type=int, default=25)
    args = parser.parse_args(argv)
    seeds = json.loads(SEEDS.read_text(encoding="utf-8"))
    public = json.loads(PUBLIC.read_text(encoding="utf-8"))
    validate_catalogues(seeds, public)
    if args.check:
        print("PhD admissions: catalogue and provenance valid; network not used")
        return 0
    now = datetime.now(UTC)
    updated = refresh(seeds, public, now=now, batch_size=args.batch_size)
    PUBLIC.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    statuses: dict[str, int] = {}
    for entry in updated["programmes"]:
        statuses[entry["status"]] = statuses.get(entry["status"], 0) + 1
    print("Official-only PhD admissions rotation:", json.dumps(statuses, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
