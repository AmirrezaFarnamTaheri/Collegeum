"""Small, independently filtered career-job feeds for opt-in Telegram alerts.

This is deliberately separate from academic extraction and web/X publication.
Jobicy exposes a documented public remote feed. Jobinja search returns
Iran-market jobs as HTML; no location is guessed from a vacancy title. Both
sources are polled only when subscribers request the relevant market.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from ..core.textproc import truncate
from ..logging_setup import get_logger
from .http import PoliteClient
from .rotation import SCHEDULE_INTERVAL_HOURS

log = get_logger(__name__)

REMOTE_API = "https://jobicy.com/api/v2/remote-jobs?count=200&geo=anywhere"
IRAN_SEARCH_TERMS = (
    "تحلیلگر داده", "دانشمند داده", "تحلیل اقتصادی", "مشاور مدیریت",
)
MAX_STORED_JOBS = 3000
MAX_AGE_DAYS = 21

# Match actual role descriptions in the title. Do not classify unrelated ads
# because a generic page sidebar mentions Python or analytics.
ROLE_PATTERNS = (
    ("data_scientist", re.compile(
        r"\bdata\s+scientist\b|\bmachine\s+learning\s+(?:scientist|researcher)\b|"
        r"دانشمند\s+داده|متخصص\s+علم\s+داده", re.I)),
    ("data_analyst", re.compile(
        r"\bdata\s+analyst\b|\b(?:product|business\s+intelligence|bi)\s+analyst\b|"
        r"تحلیلگر\s+داده|تحلیل\s*گر\s+داده|کارشناس\s+تحلیل\s+داده|"
        r"تحلیلگر\s+هوش\s+تجاری", re.I)),
    ("econ_consulting", re.compile(
        r"\b(?:economic|economics|econometric|policy)\s+(?:consultant|advisor)\b|"
        r"\bmanagement\s+consultant\b|مشاور\s+(?:اقتصادی|مدیریت)|"
        r"کارشناس\s+مشاوره\s+اقتصادی", re.I)),
    ("research_analyst", re.compile(
        r"\b(?:economic|economics|financial|market|quantitative|research)\s+analyst\b|"
        r"\bresearch\s+associate\b|تحلیلگر\s+(?:اقتصادی|تحقیقات|بازار)|"
        r"کارشناس\s+(?:تحقیقات\s+بازار|پژوهش\s+اقتصادی)", re.I)),
)

def classify_career(title: str) -> str | None:
    """Return a supported occupation, or None for irrelevant roles."""
    for kind, pattern in ROLE_PATTERNS:
        if pattern.search(title):
            return kind
    return None


def _key(url: str) -> str:
    return "career:" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


def _job(
    *,
    url: str, title: str, employer: str, location: str, source: str, scope: str,
) -> dict[str, str] | None:
    kind = classify_career(title)
    parts = urlsplit(url)
    if not kind or parts.scheme != "https" or not parts.hostname:
        return None
    return {
        "key": _key(url), "title": title[:200], "employer": employer[:160],
        "location": location[:100], "source": source, "scope": scope,
        "category": kind, "url": url,
    }


def parse_remote_jobs(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Accept only jobs explicitly open to applicants worldwide/Iran.

    A 'remote US' job is not automatically accessible to someone in Iran.
    """
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("Jobicy response has no jobs array")
    output: list[dict[str, str]] = []
    for data in jobs[:200]:
        if not isinstance(data, dict):
            continue
        geo = str(data.get("jobGeo") or "").strip()
        allowed = re.search(r"\b(anywhere|worldwide|world|global|iran)\b", geo, re.I)
        if not allowed:
            continue
        title = str(data.get("jobTitle") or "")
        url = str(data.get("url") or "")
        if urlsplit(url).hostname not in ("jobicy.com", "www.jobicy.com"):
            continue
        result = _job(
            url=url, title=title, employer=str(data.get("companyName") or "Unknown"),
            location=geo, source="Jobicy", scope="remote",
        )
        if result:
            output.append(result)
    return output


def iran_search_url(slot: int) -> str:
    keyword = IRAN_SEARCH_TERMS[slot % len(IRAN_SEARCH_TERMS)]
    return "https://jobinja.ir/jobs?" + urlencode({"filters[keywords]": keyword})


def parse_iran_jobs(html: str) -> list[dict[str, str]]:
    """Extract actual Jobinja job URLs, not navigation or company pages.

    Fail closed if the site switches to a script-only shell.
    """
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for a in soup.select("a[href]"):
        url = urljoin("https://jobinja.ir", str(a.get("href") or ""))
        parsed = urlsplit(url)
        if parsed.hostname not in {"jobinja.ir", "www.jobinja.ir"}:
            continue
        if not re.fullmatch(r"/companies/[^/]+/jobs/[^/]+(?:/[^/]*)?/?", parsed.path):
            continue
        url = "https://jobinja.ir" + parsed.path.rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        title = a.get_text(" ", strip=True)
        if not 5 <= len(title) <= 200:
            continue
        container = a.find_parent(["li", "article"])
        if container is None:
            container = a.find_parent("div", class_=re.compile("jobList|job-list", re.I))
        employer = ""
        location = "Iran (location not specified)"
        if container:
            company = container.select_one("a[href*='/companies/']:not([href*='/jobs/'])")
            if company:
                employer = company.get_text(" ", strip=True)
            # Location is displayed separately by Jobinja in many templates.
            loc = container.select_one("[class*='location'], [class*='Location']")
            if loc:
                location = loc.get_text(" ", strip=True) or location
        result = _job(
            url=url, title=title, employer=employer or "Jobinja employer",
            location=location, source="Jobinja", scope="iran",
        )
        if result:
            out.append(result)
        if len(out) >= 30:
            break
    return out


def load_career(path: str | Path) -> list[dict[str, str]]:
    p = Path(path)
    if not p.exists():
        return []
    result: list[dict[str, str]] = []
    for line in p.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        if not isinstance(data, dict):
            raise ValueError(f"invalid job journal record in {p}")
        required = {"key", "category", "scope", "url", "title", "first_seen_at"}
        if not required.issubset(data) or not all(isinstance(v, str) for v in data.values()):
            raise ValueError(f"corrupt job journal record in {p}")
        result.append(data)
    return result


def save_career(path: str | Path, previous: list[dict[str, str]],
                fresh: list[dict[str, str]]) -> int:
    """Atomic upsert without losing first-seen times or re-alerting existing jobs."""
    p = Path(path)
    cutoff = datetime.now(UTC) - timedelta(days=MAX_AGE_DAYS)
    existing = {job["key"]: job for job in previous}
    added = 0
    for job in fresh:
        if job["key"] not in existing:
            existing[job["key"]] = {**job, "first_seen_at": datetime.now(UTC).isoformat()}
            added += 1
        else:
            old = existing[job["key"]]
            existing[job["key"]] = {**job, "first_seen_at": old["first_seen_at"]}
    filtered: list[dict[str, str]] = []
    for job in existing.values():
        try:
            if datetime.fromisoformat(job["first_seen_at"].replace("Z", "+00:00")) >= cutoff:
                filtered.append(job)
        except ValueError:
            raise ValueError("invalid first_seen_at in job journal") from None
    filtered.sort(key=lambda x: (x["first_seen_at"], x["key"]), reverse=True)
    filtered = filtered[:MAX_STORED_JOBS]
    p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_name(p.name + ".tmp")
    payload = "".join(json.dumps(j, ensure_ascii=False, sort_keys=True) + "\n"
                      for j in filtered)
    with temp.open("w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    temp.replace(p)
    return added


def poll_career(
    path: str | Path, *, client: PoliteClient, needs_iran: bool,
    needs_remote: bool, slot: int | None = None,
) -> tuple[int, list[str]]:
    """Maximum two HTTP fetches per 4-hour run, without extra model calls."""
    previous = load_career(path)
    fresh: list[dict[str, str]] = []
    errors: list[str] = []
    if needs_remote:
        res = client.get(REMOTE_API)
        if res.ok:
            try:
                payload = json.loads(res.text)
                if not isinstance(payload, dict):
                    raise ValueError("invalid Jobicy response")
                fresh.extend(parse_remote_jobs(payload))
            except (ValueError, TypeError) as exc:
                errors.append(f"Jobicy parse: {exc}")
        else:
            errors.append(f"Jobicy fetch: {res.error or res.status}")
    if needs_iran:
        slot = slot if slot is not None else int(datetime.now(UTC).timestamp()) // (SCHEDULE_INTERVAL_HOURS * 3600)
        res = client.get(iran_search_url(slot))
        if res.ok:
            parsed = parse_iran_jobs(res.text)
            if not parsed:
                errors.append("Jobinja produced zero matching job cards; verify markup")
            fresh.extend(parsed)
        else:
            errors.append(f"Jobinja fetch: {res.error or res.status}")
    new_count = save_career(path, previous, fresh)
    for error in errors:
        log.warning("career_source_failed", error=truncate(error, 200))
    return new_count, errors
