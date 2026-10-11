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
import shutil
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
REMOTE_STATUS_API = "https://jobicy.com/api/v2/remote-jobs/status"
IRANTALENT_URL = "https://www.irantalent.com/en/jobs"
MAX_PROVIDER_ID = 9_007_199_254_740_991
IRAN_SEARCH_TERMS = (
    "تحلیلگر داده", "دانشمند داده", "تحلیل اقتصادی", "مشاور مدیریت",
)
MAX_STORED_JOBS = 3000
MAX_AGE_DAYS = 21
MAX_REMOTE_PAGES = 2  # capped cursor traversal keeps four-hour runs light

# Match actual role descriptions in the title. Do not classify unrelated ads
# because a generic page sidebar mentions Python or analytics.
ROLE_PATTERNS = (
    ("data_scientist", re.compile(
        r"\bdata\s+scientists?\b|\bdata\s+science\s+(?:intern|internship)\b|"
        r"\bmachine\s+learning\s+(?:scientist|researcher)s?\b|"
        r"دانشمند\s+داده|متخصص\s+علم\s+داده", re.I)),
    ("data_analyst", re.compile(
        r"\bdata\s+analysts?\b|\b(?:business\s+intelligence|bi)\s+analysts?\b|"
        r"تحلیلگر[\s\u200c]*داده|تحلیل[\s\u200c]*گر[\s\u200c]*داده|"
        r"کارشناس[\s\u200c]+تحلیل[\s\u200c]+داده|"
        r"تحلیلگر\s+هوش\s+تجاری", re.I)),
    ("econ_consulting", re.compile(
        r"\b(?:economic|economics|econometric|policy)\s+(?:consultant|advisor)\b|"
        r"\bmanagement\s+consultants?\b|مشاور\s+(?:اقتصادی|مدیریت)|"
        r"کارشناس\s+مشاوره\s+اقتصادی", re.I)),
    ("research_analyst", re.compile(
        r"\b(?:economic|economics|financial|market|quantitative|research)\s+analysts?\b|"
        r"\b(?:industry|market|business)\s+research\s+associate\b|"
        r"تحلیلگر\s+(?:اقتصادی|تحقیقات|بازار)|"
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
    if (not kind or parts.scheme != "https" or not parts.hostname
            or len(url) > 1024 or len(title) > 500):
        return None
    return {
        "key": _key(url), "title": title[:200], "employer": employer[:160],
        "location": location[:100], "source": source, "scope": scope,
        "category": kind, "url": url,
    }


def _remote_geo_allowed(geo: str) -> bool:
    """Follow positive provider eligibility, never infer eligibility from 'remote'.

    Jobicy's jobGeo describes where a person is allowed to work. Explicit
    Iran exclusions override apparently worldwide phrases.
    """
    if (re.search(
        r"\b(?:excluding|except|excludes|not|outside|no)\b[^.;]{0,55}\biran\b",
        geo, re.I,
    ) or re.search(
        r"\biran\b[^.;]{0,50}\b(?:excluded|ineligible|not eligible)\b",
        geo, re.I,
    )):
        return False
    # An Iran-only remote vacancy belongs to the Iran market, not to
    # the independently selectable worldwide-remote topic.
    # The provider's free-text geography is not an unrestricted keyword bag:
    # "Anywhere in the US" and "Europe, anywhere" are NOT worldwide.
    normalized = re.sub(r"\s+", " ", geo.strip().lower()).strip(" .")
    return normalized in {
        "anywhere", "worldwide", "global", "anywhere in the world",
        "worldwide remote", "global remote", "remote worldwide",
    }


def parse_remote_jobs(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Accept only jobs explicitly open to worldwide applicants.

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
        if not _remote_geo_allowed(geo):
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
            job_id = data.get("id")
            if type(job_id) is int and 0 < job_id <= MAX_PROVIDER_ID:
                result["jobicy_id"] = str(job_id)
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



# IranTalent's public /en/jobs page serves job cards without requiring login.
# The unfiltered path avoids search parameters disallowed by its robots.txt.
# Do not infer Iran-based location from the company domain alone.
_IRAN_CITIES_EN = (
    "tehran", "karaj", "mashhad", "isfahan", "shiraz", "tabriz", "ahvaz",
    "qom", "rasht", "yazd", "kish", "qazvin", "kerman", "ardabil", "arak",
    "urmia", "orumiyeh", "zanjan", "hamadan", "sanandaj", "bandar abbas",
    "kermanshah", "sari", "gorgan", "bushehr", "iran",
)
_IRAN_CITIES_FA = (
    "تهران", "کرج", "مشهد", "اصفهان", "شیراز", "تبریز", "اهواز", "قم",
    "رشت", "یزد", "کیش", "قزوین", "کرمان", "اراک", "ارومیه", "زنجان",
    "همدان", "سنندج", "بندرعباس", "کرمانشاه", "ساری", "گرگان",
    "بوشهر", "ایران",
)
_IRANTALENT_JOB = re.compile(r"/(?:en|fa)/job/[^/]+/[1-9]\d{3,10}/?$", re.I)


def _iran_location(card_text: str) -> str | None:
    if re.search(r"\b(?:outside (?:of )?iran|abroad)\b", card_text, re.I):
        return None
    for place in _IRAN_CITIES_FA:
        # Persian has no ASCII word boundaries; negative Unicode lookarounds
        # avoid matching قم inside رقم and adjacent zero-width joiners.
        if re.search(rf"(?<![\w\u200c]){re.escape(place)}(?![\w\u200c])", card_text):
            return place
    for place in _IRAN_CITIES_EN:
        if place in {"sari", "kish", "arak"} and not re.search(
            r"(?i)(?:location|city|شهر|موقعیت)\s*[:：]\s*" + re.escape(place) + r"\b",
            card_text,
        ):
            continue
        if re.search(rf"\b{re.escape(place)}\b", card_text, re.I):
            return place.title()
    return None


def parse_irantalent_jobs(html: str) -> list[dict[str, str]]:
    """Extract validated Iran-based career cards from the public listing page.

    A job link alone cannot establish location; cards with no explicit Iranian
    place are excluded. The surrounding navigation and similar-jobs links
    never count as title evidence.
    """
    soup = BeautifulSoup(html, "lxml")
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for a in soup.select("a[href]")[:500]:
        raw = str(a.get("href") or "")
        link = urlsplit(urljoin(IRANTALENT_URL, raw))
        if (link.scheme != "https" or link.hostname not in
                {"www.irantalent.com", "irantalent.com"} or
                not _IRANTALENT_JOB.fullmatch(link.path)):
            continue
        url = "https://www.irantalent.com" + link.path.rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        title_element = a.select_one("h2, h3, h4, [class*='job-title']")
        title = (title_element.get_text(" ", strip=True)
                 if title_element else next(a.stripped_strings, ""))
        card = a.find_parent(["article", "li"]) or a
        details = card.get_text(" ", strip=True)[:800]
        location = _iran_location(details)
        if not location:
            continue
        company = card.select_one("[class*='company'], [class*='employer']")
        employer = (
            company.get_text(" ", strip=True)
            if company else "IranTalent employer"
        )
        parsed = _job(
            url=url, title=title, employer=employer, location=location,
            source="IranTalent", scope="iran",
        )
        if parsed is not None:
            output.append(parsed)
        if len(output) >= 30:
            break
    return output


def load_career(
    path: str | Path, *, tolerant: bool = False,
) -> list[dict[str, str]]:
    """Strictly validate stored jobs; optionally quarantine individual bad rows.

    Tolerant reads preserve a byte-for-byte backup *before* omitting any
    invalid row. This allows scheduled collection to recover without silently
    losing forensic evidence. Direct callers remain strict by default.
    """
    p = Path(path)
    if not p.exists():
        return []
    if p.stat().st_size > 8_000_000:
        raise ValueError("career journal exceeds its resource budget")
    result: list[dict[str, str]] = []
    quarantined = 0
    content = p.read_text("utf-8").splitlines()
    if len(content) > MAX_STORED_JOBS:
        raise ValueError("career journal exceeds its record budget")
    for index, line in enumerate(content, 1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError(f"invalid job journal record in {p}")
            required = {
                "key", "category", "scope", "url", "title",
                "first_seen_at", "employer", "location", "source",
            }
            if (not required.issubset(data)
                    or not all(isinstance(v, str) for v in data.values())):
                raise ValueError(f"corrupt job journal record in {p}")
            life = data["category"] == "life_sciences_phd"
            valid_scopes = (
                data["scope"] == "" if life
                else data["scope"] in ("iran", "remote")
            )
            if not valid_scopes or (not life and data["category"] not in {
                "data_scientist", "data_analyst", "econ_consulting", "research_analyst",
            }):
                raise ValueError(f"invalid career category or scope in {p}")
            if data.get("availability", "unknown") not in ("active", "closed", "unknown"):
                raise ValueError(f"invalid career availability in {p}")
            provider_id = data.get("jobicy_id")
            if provider_id is not None and (
                not isinstance(provider_id, str) or not provider_id.isascii()
                or not provider_id.isdecimal() or not 0 < int(provider_id) <= MAX_PROVIDER_ID
            ):
                raise ValueError(f"invalid Jobicy ID in {p}")
            if (not data["key"].startswith("career:")
                    or len(data["url"]) > 1024
                    or urlsplit(data["url"]).scheme != "https"):
                raise ValueError(f"invalid career URL or identity in {p}")
            timestamp = datetime.fromisoformat(data["first_seen_at"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError(f"invalid career timestamp in {p}")
            result.append(data)
        except (TypeError, ValueError, OverflowError) as exc:
            if not tolerant:
                raise
            if quarantined == 0:
                suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
                backup = p.with_name(f"{p.name}.corrupt-{suffix}")
                shutil.copy2(p, backup)
            quarantined += 1
            log.warning("career_record_quarantined", row=index, reason=str(exc)[:120])
    return result


def save_career(path: str | Path, previous: list[dict[str, str]],
                fresh: list[dict[str, str]]) -> int:
    """Atomic upsert without losing first-seen times or re-alerting existing jobs."""
    p = Path(path)
    cutoff = datetime.now(UTC) - timedelta(days=MAX_AGE_DAYS)
    now = datetime.now(UTC).isoformat()
    existing = {job["key"]: job for job in previous}
    added = 0
    for job in fresh:
        if job["key"] not in existing:
            existing[job["key"]] = {**job, "first_seen_at": now, "last_seen_at": now}
            added += 1
        else:
            old = existing[job["key"]]
            current = {
                **old, **job, "first_seen_at": old["first_seen_at"],
                "last_seen_at": now,
            }
            if old.get("availability") == "closed" and "availability" not in job:
                current["availability"] = "closed"
            existing[job["key"]] = current
    filtered: list[dict[str, str]] = []
    for job in existing.values():
        try:
            if datetime.fromisoformat(
                job.get("last_seen_at", job["first_seen_at"]).replace("Z", "+00:00")
            ) >= cutoff:
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



def _verify_remote_status(
    client: PoliteClient,
    previous: list[dict[str, str]],
    fresh: list[dict[str, str]],
    errors: list[str],
    stats: dict[str, Any],
) -> None:
    """One optional Jobicy status request for at most 100 IDs per four-hour run.

    Only explicit 'closed' proves closure. Missing/unknown/failed responses
    never turn unknown listings into closed ones.
    """
    selected: list[str] = []
    # Older unchecked records go first. Each successful response records when
    # a status was checked, so repeated runs advance fairly through the backlog.
    ordered = sorted(
        [*previous, *fresh],
        key=lambda job: (
            job.get("status_checked_at", ""),
            job.get("first_seen_at", ""),
            job.get("key", ""),
        ),
    )
    for job in ordered:
        identifier = job.get("jobicy_id")
        if identifier and identifier not in selected:
            selected.append(identifier)
        if len(selected) == 100:
            break
    if not selected:
        return
    request_url = REMOTE_STATUS_API + "?" + urlencode({"ids": ",".join(selected)})
    response = client.get(request_url)
    stats["fetched"] += 1
    if not response.ok:
        errors.append(f"Jobicy status fetch: {response.error or response.status}")
        return
    try:
        data = json.loads(response.text)
        if not isinstance(data, dict) or data.get("success") is False:
            raise ValueError("status response is invalid")
        entries = data.get("jobs")
        if not isinstance(entries, list):
            raise ValueError("status result has no jobs array")
        statuses: dict[str, str] = {}
        for entry in entries[:100]:
            if not isinstance(entry, dict):
                continue
            identifier = entry.get("id")
            status = entry.get("status")
            if (type(identifier) is int and str(identifier) in selected
                    and status in ("active", "closed", "unknown")):
                statuses[str(identifier)] = status
        for job in [*previous, *fresh]:
            state = statuses.get(job.get("jobicy_id", ""))
            if state is None:
                continue
            job["status_checked_at"] = datetime.now(UTC).isoformat()
            if state == "unknown" and job.get("availability") == "closed":
                continue
            job["availability"] = state
        stats["closed"] = sum(1 for state in statuses.values() if state == "closed")
    except (ValueError, TypeError):
        errors.append("Jobicy status response has an invalid schema")


def poll_career(
    path: str | Path, *, client: PoliteClient, needs_iran: bool,
    needs_remote: bool, slot: int | None = None,
    health_path: str | Path | None = None,
) -> tuple[int, list[str]]:
    """Bounded public-source polling with separately persisted source health."""
    previous = load_career(path, tolerant=True)
    fresh: list[dict[str, str]] = []
    errors: list[str] = []
    started = datetime.now(UTC).isoformat()
    sources: dict[str, dict[str, Any]] = {
        "jobicy": {"requested": needs_remote, "fetched": 0, "accepted": 0},
        "jobinja": {"requested": needs_iran, "fetched": 0, "accepted": 0},
        "irantalent": {"requested": needs_iran, "fetched": 0, "accepted": 0},
    }
    if needs_remote:
        cursor: str | None = None
        visited: set[str] = set()
        for page in range(MAX_REMOTE_PAGES):
            url = REMOTE_API
            if cursor:
                url += "&" + urlencode({"cursor": cursor})
            res = client.get(url)
            sources["jobicy"]["fetched"] += 1
            if not res.ok:
                errors.append(f"Jobicy fetch: {res.error or res.status}")
                break
            try:
                payload = json.loads(res.text)
                if not isinstance(payload, dict) or payload.get("success") is False:
                    raise ValueError("invalid or failed Jobicy response")
                parsed = parse_remote_jobs(payload)
                fresh.extend(parsed)
                sources["jobicy"]["accepted"] += len(parsed)
                following = payload.get("nextCursor")
                if not isinstance(following, str) or not following:
                    break
                if len(following) > 512 or following in visited:
                    raise ValueError("Jobicy cursor invalid or repeated")
                visited.add(following)
                cursor = following
            except (ValueError, TypeError) as exc:
                errors.append(f"Jobicy parse: {exc}")
                break
            if page == MAX_REMOTE_PAGES - 1:
                log.info("career_remote_feed_page_cap", pages=MAX_REMOTE_PAGES)
        _verify_remote_status(
            client, previous, fresh, errors, sources["jobicy"],
        )
    if needs_iran:
        if slot is None:
            slot = int(datetime.now(UTC).timestamp()) // (SCHEDULE_INTERVAL_HOURS * 3600)
        res = client.get(iran_search_url(slot))
        sources["jobinja"]["fetched"] += 1
        if res.ok:
            parsed = parse_iran_jobs(res.text)
            sources["jobinja"]["accepted"] += len(parsed)
            # Valid listings with irrelevant titles can legitimately produce
            # zero career matches. Only missing recognizable job links signals
            # a markup change; do not report ordinary empty results as outages.
            if not parsed and not re.search(
                r"/companies/[^/]+/jobs/[^/]+", res.text,
            ):
                errors.append("Jobinja returned no recognizable job cards; verify markup")
            fresh.extend(parsed)
        else:
            errors.append(f"Jobinja fetch: {res.error or res.status}")

        # One unfiltered, robots-allowed IranTalent listing request.
        other = client.get(IRANTALENT_URL)
        sources["irantalent"]["fetched"] += 1
        if other.ok:
            parsed = parse_irantalent_jobs(other.text)
            sources["irantalent"]["accepted"] += len(parsed)
            if "/en/job/" not in other.text and "/fa/job/" not in other.text:
                errors.append("IranTalent returned no job links; verify page markup")
            fresh.extend(parsed)
        else:
            errors.append(f"IranTalent fetch: {other.error or other.status}")
    new_count = save_career(path, previous, fresh)
    for error in errors:
        log.warning("career_source_failed", error=truncate(error, 200))
    if health_path is not None:
        # A successful HTTP fetch with no relevant roles is different from a
        # failed request, malformed HTML, or an unrequested source.
        old_health = _read_career_health(health_path)
        historical = old_health.get("sources", {})
        for name, info in sources.items():
            issues = [error for error in errors if error.lower().startswith(name)]
            if name == "irantalent":
                issues = [error for error in errors if error.startswith("IranTalent")]
            if not info["requested"]:
                info["status"] = "idle"
            elif issues:
                info["status"] = "degraded" if info["accepted"] else "error"
            elif info["fetched"]:
                info["status"] = "ok" if info["accepted"] else "empty"
            else:
                info["status"] = "error"
            info["error_count"] = len(issues)
            previous_info = historical.get(name, {}) if isinstance(historical, dict) else {}
            last_success = (
                previous_info.get("last_success_at")
                if isinstance(previous_info, dict) else None
            )
            if info["status"] in ("ok", "empty"):
                last_success = started
            if isinstance(last_success, str) and len(last_success) <= 40:
                info["last_success_at"] = last_success
        data = {
            "checked_at": started, "added": new_count,
            "sources": sources, "errors": [truncate(error, 200) for error in errors[:8]],
        }
        destination = Path(health_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_name(destination.name + ".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(destination)
    return new_count, errors


def _read_career_health(path: str | Path) -> dict[str, Any]:
    """Read only a small allowlisted public-source health payload."""
    target = Path(path)
    try:
        if not target.exists() or target.stat().st_size > 65536:
            return {}
        data = json.loads(target.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, UnicodeError, ValueError):
        return {}


def idle_career_health(path: str | Path) -> None:
    """Report sources as not requested without claiming a successful fetch."""
    previous = _read_career_health(path)
    old = previous.get("sources", {})
    current = {}
    for name in ("jobicy", "jobinja", "irantalent"):
        past = old.get(name, {}) if isinstance(old, dict) else {}
        success = past.get("last_success_at") if isinstance(past, dict) else None
        info: dict[str, Any] = {
            "requested": False, "fetched": 0, "accepted": 0,
            "status": "idle", "error_count": 0,
        }
        if isinstance(success, str) and len(success) <= 40:
            info["last_success_at"] = success
        current[name] = info
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_name(dest.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump({
                "checked_at": datetime.now(UTC).isoformat(),
                "sources": current, "errors": [],
            }, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(dest)
    finally:
        temp.unlink(missing_ok=True)
