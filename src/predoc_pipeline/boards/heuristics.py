"""Detail-page heuristics: deadline, PI, visa / citizenship rules, "PhD required", filled/closed.

No API, no cost: plain regular expressions over the job page's text. Ported from the
predoc-bot project, where each rule was added after a real false positive.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from typing import Any

from .config import EnrichConfig
from .http import FetchError, HttpClient
from .models import JobPostSchema
from .utils.dates import extract_deadline
from .utils.geo import (
    is_confident_single_region,
    location_from_labels,
    region_from_url,
    us_signal_count,
)
from .utils.text import truncate

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- visa rules
_C = r"(?:u\.?s\.?|american|eu|eea|e\.u\.|european|uk|british|canadian|swiss|norwegian|danish|swedish)"
VISA_NEGATIVE = [
    re.compile(p, re.IGNORECASE) for p in (
        r"(unable|not\s+able|cannot|can\s*not|can't|will\s+not|won't|do(?:es)?\s+not|are\s+not\s+able\s+to)\s+"
        r"(?:to\s+)?(?:offer|provide|sponsor|support)\s+(?:a\s+|any\s+)?(?:visa|sponsorship|work\s+permit)",
        r"no\s+visa\s+sponsorship", r"sponsorship\s+(?:is\s+)?not\s+(?:available|possible|provided|offered)",
        _C + r"\s+citizens?(?:hip)?\s+(?:only|is\s+required|required)",
        r"must\s+be\s+(?:a\s+)?" + _C + r"\s+(?:citizen|national|permanent\s+resident)",
        r"open\s+only\s+to\s+" + _C + r"\s+(?:citizens|nationals)",
    )
]
VISA_PRIORITY = [
    re.compile(p, re.IGNORECASE) for p in (
        r"(?:canadians?|citizens?|nationals?|permanent\s+residents?)[^.]{0,60}(?:will\s+be\s+)?given\s+priority",
        r"priority\s+(?:will\s+be\s+)?given\s+to\s+(?:canadians?|citizens?|nationals?|permanent\s+residents?)",
    )
]
VISA_WORK_AUTH = [
    re.compile(p, re.IGNORECASE) for p in (
        r"(?:must|should|need\s+to|required\s+to)\s+(?:already\s+)?(?:have|hold|possess)\s+(?:the\s+)?"
        r"(?:right|authori[sz]ation|permission)\s+to\s+work",
        r"(?:eligible|authori[sz]ed|legally\s+entitled)\s+to\s+work\s+in\s+(?:the\s+)?"
        r"(?:us|u\.s\.|uk|eu|canada|united\s+states|united\s+kingdom|european\s+union)",
    )
]
VISA_POSITIVE = [
    re.compile(p, re.IGNORECASE) for p in (
        r"visa\s+sponsorship\s+(?:is\s+|will\s+be\s+)?(?:available|provided|offered|possible|supported)",
        r"(?:will|can|may|able\s+to)\s+(?:sponsor|support)\s+(?:a\s+|the\s+)?(?:visa|work\s+permit|skilled\s+worker)",
        r"visas?\s+for\s+international\s+(?:candidates|applicants)[^.]{0,80}(?:supported|sponsored|provided)",
        r"(?:eligible\s+for|qualif(?:y|ies)\s+for)\s+(?:visa\s+)?sponsorship",
    )
]
VISA_CONTEXT = [
    (re.compile(r"international\s+(?:applicants|candidates)\s+(?:are\s+)?(?:welcome|encouraged)", re.I),
     "International applications welcome; sponsorship unstated"),
    (re.compile(r"relocation\s+(?:support|assistance|package)", re.I),
     "Relocation assistance mentioned; sponsorship unstated"),
]

PHD_REQUIRED = re.compile(
    r"(?:must|should|will)\s+(?:have|hold)\s+(?:been\s+awarded\s+)?(?:a\s+|an\s+)?(?:ph\.?d|doctorate|doctoral\s+degree)|"
    r"ph\.?d\.?\s+(?:degree\s+)?(?:is\s+)?(?:required|essential|mandatory)|"
    r"(?:completed|been\s+awarded|holding|hold)\s+(?:a\s+)?(?:ph\.?d|doctorate)\b(?!\s+(?:program|programme|studies))|"
    r"(?:ph\.?d|doctorate)\s*\(?\s*or\s+(?:be\s+)?(?:close\s+to|near(?:ing)?)\s+(?:its\s+)?complet",
    re.IGNORECASE,
)
_NEGATION_BEFORE = re.compile(r"\b(?:not|no|never|without|non)\b[\w\s-]{0,20}$|n't\s+[\w\s]{0,15}$",
                              re.IGNORECASE)
_NEGATION_AFTER = re.compile(r"^[^.;]{0,40}\b(?:(?:are|is)\s+not\s+eligible|ineligible|cannot\s+apply|"
                             r"not\s+required|need\s+not|do\s+not\s+qualify)", re.IGNORECASE)


def phd_required(text: str | None) -> bool:
    """True when the ad requires a completed PhD.

    "Candidates holding a PhD are not eligible", "must not hold a PhD" and
    "have not completed a PhD" say the opposite, so negated matches are skipped.
    """
    text = text or ""
    for m in PHD_REQUIRED.finditer(text):
        before = text[max(0, m.start() - 30): m.start()]
        after = text[m.end(): m.end() + 60]
        if _NEGATION_BEFORE.search(before) or _NEGATION_AFTER.search(after):
            continue
        return True
    return False


# Case-insensitive cue words, case-sensitive capitalised name ("Professor Jane Doe").
PI_RX = re.compile(
    r"(?i:supervis(?:ed\s+by|ion\s+of|or)|work(?:ing)?\s+(?:closely\s+)?(?:with|for|under)|principal\s+investigator|"
    r"\bPI\b|sponsoring\s+researchers?|led\s+by)\s*[:\-]?\s*(?i:the\s+)?(?i:professors?|prof\.?|dr\.?)\s+"
    r"(?P<name>[A-Z][a-zà-ÿ'\-]+(?:\s+(?:[A-Z]\.|[A-Z][a-zà-ÿ'\-]+)){1,2})"
)


# --------------------------------------------------------------------------- filled / closed
CLOSED_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"(?:position|vacancy|job|role|post|opening|fellowship|call)\s+(?:has\s+(?:now\s+)?been\s+|is\s+(?:now\s+)?|was\s+)"
        r"(?:filled|closed|cancelled|canceled|withdrawn)",
        r"no\s+longer\s+(?:accepting|taking|receiving|open|available|active|online)",
        r"form\s+is\s+no\s+longer\s+accepting\s+responses",
        r"(?:applications?|recruitment|the\s+call|the\s+search|this\s+competition)\s+(?:is|are|has|have)\s+(?:now\s+)?"
        r"(?:been\s+)?closed",
        r"(?:this|the)\s+(?:job\s+(?:posting|ad|advert|offer|listing|opening)|job|position|posting|vacancy|advert|"
        r"advertisement|listing|offer)\s+"
        r"(?:has\s+)?(?:expired|been\s+removed|been\s+closed|is\s+closed|is\s+no\s+longer)",
        r"(?:job|position|posting|vacancy)\s+(?:not\s+found|does\s+not\s+exist|is\s+unavailable)",
        r"\bposition\s+filled\b", r"\bvacancy\s+filled\b", r"\b(?:we\s+have|has\s+been)\s+(?:now\s+)?filled\b",
        r"application\s+(?:period|deadline)\s+has\s+(?:now\s+)?(?:ended|passed|expired)",
        r"(?:bewerbungsfrist|ausschreibung)\s+(?:ist\s+)?(?:abgelaufen|beendet)",
    )
]
# "reviewed until the position is filled" is an OPEN job: ignore matches preceded by these words.
_OPEN_CONTEXT = re.compile(r"\b(?:until|unless|once|when|if|before|till|after)\b[\w\s]{0,12}$", re.IGNORECASE)


# Status fields that boards print anywhere on the page (EURAXESS: "STATUS: EXPIRED" at the bottom).
STATUS_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"\bstatus\s*:?\s*(?:expired|closed|filled|withdrawn|cancell?ed|archived)\b",
        r"\b(?:this\s+)?(?:job\s+)?offer\s+(?:has\s+)?(?:expired|been\s+withdrawn|is\s+closed)",
    )
]


def detect_closed(text: str | None) -> str | None:
    """Return the phrase showing the posting is filled/closed, or None."""
    text = text or ""
    head = text[:5000]
    for rx in CLOSED_PATTERNS:
        for m in rx.finditer(head):
            if not _OPEN_CONTEXT.search(head[max(0, m.start() - 25): m.start()]):
                return truncate(m.group(0), 80)
    for rx in STATUS_PATTERNS:
        status_match = rx.search(text)
        if status_match:
            return truncate(status_match.group(0), 80)
    return None


_START_LABEL = re.compile(r"(?:start(?:ing)?\s+date|start\s*:|expected\s+start|position\s+starts?|to\s+start\s+(?:on|in))"
                          r"[^.\n]{0,15}", re.IGNORECASE)
_MONTH_YEAR = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(20\d{2})\b", re.IGNORECASE)
_MONTH_NUM = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
                                            "oct", "nov", "dec"], 1)}


def _today() -> date:
    from .utils import dates as _d  # looked up at call time (tests pin "today")
    return _d.today()


def start_date_passed(text: str | None, grace_days: int = 30) -> str | None:
    """Return a stale-start suspicion cue; this is never proof that recruitment closed."""
    from datetime import date as _date
    from datetime import timedelta

    from .utils.dates import find_dates
    ref = _today()
    for m in _START_LABEL.finditer(text or ""):
        window = (text or "")[m.start(): m.end() + 70]
        latest = None
        for _, d in find_dates(window, ref):
            latest = max(latest or d, d)
        for mm in _MONTH_YEAR.finditer(window):
            month, year = _MONTH_NUM[mm.group(1).lower()[:3]], int(mm.group(2))
            last = _date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
            latest = max(latest or last, last)
        if latest and latest < ref - timedelta(days=grace_days):
            return f"start date ({latest:%b %Y}) has passed"
    return None


def detect_visa(text: str) -> str | None:
    def evidence(rx: re.Pattern[str]) -> re.Match[str] | None:
        for match in rx.finditer(text):
            # Local negation must not turn a denied cue into an affirmative fact.
            before = text[max(0, match.start() - 30):match.start()]
            after = text[match.end():match.end() + 60]
            if _NEGATION_BEFORE.search(before) or re.search(
                r"\b(?:cannot|can't|unable\s+to|may\s+not)\s+(?:confirm|guarantee|promise)\s+(?:that\s+)?$",
                before, re.I
            ) or re.match(
                r"\s+(?:is|are|will\s+be)\s+not\b", after, re.I
            ):
                continue
            return match
        return None

    context = []
    for rx in VISA_PRIORITY:
        m = evidence(rx)
        if m:
            context.append(f"Priority to citizens/residents (“{truncate(m.group(0), 90)}”)")
            break
    for rx, label in VISA_CONTEXT:
        m = evidence(rx)
        if m:
            context.append(f"{label} (“{truncate(m.group(0), 80)}”)")

    def note(primary: str) -> str:
        return "; ".join([primary, *context])

    for rx in VISA_NEGATIVE:
        m = evidence(rx)
        if m:
            return note(f"No sponsorship / citizenship restriction (“{truncate(m.group(0), 80)}”)")
    for rx in VISA_POSITIVE:
        m = evidence(rx)
        if m:
            return note(f"Visa support mentioned (“{truncate(m.group(0), 80)}”)")
    for rx in VISA_WORK_AUTH:
        m = evidence(rx)
        if m:
            return note(f"Existing work authorisation may be required (“{truncate(m.group(0), 80)}”)")
    return "; ".join(context) or None


def apply_heuristics(post: JobPostSchema, text: str) -> None:
    """Mutates post in place with whatever the detail text reveals."""
    if not text:
        return
    if not post.deadline:
        d, raw = extract_deadline(text)
        if d or raw:
            post.deadline, post.deadline_text = d, raw
    if not post.visa_note:
        post.visa_note = detect_visa(text)
    if not post.pi_name:
        m = PI_RX.search(text)
        if m:
            post.pi_name = m.group("name")
    post.extra["phd_required"] = phd_required(text)
    closed = detect_closed(text)
    if closed and not post.extra.get("closed"):
        post.extra["closed"] = f"page says \u201c{closed}\u201d"
    stale = start_date_passed(text)
    post.extra.pop("stale_start_note", None)
    if stale and not post.extra.get("closed") and not (post.deadline and post.deadline >= _today()):
        post.extra["stale_start_note"] = stale
    # Attempt detail-page location when: region is absent OR when region came only from a
    # source-config default (not from the actual job text).  A "Location:" label or a
    # confident single-region signal in the advert is more reliable than a US-based
    # aggregator's configured country default (F03).
    source_default = post.extra.get("source_country_default") and not post.extra.get("region_from_detail")
    if not post.region or source_default:
        # Most to least reliable: a "Location:" line, the domain the link landed on,
        # a page that only ever mentions one region, then typical US-only wording.
        country, region = location_from_labels(text[:6000])
        if not region:
            country, region = region_from_url(post.extra.get("final_url"))
        if not region:
            country, region = is_confident_single_region(text[:4000])
        if not region and us_signal_count(text) >= 2:
            country, region = "United States", "US"
        if region:
            post.country = (country if country not in ("Europe", "Other")
                            else None if source_default else post.country)
            post.region = region
            post.extra["region_from_detail"] = True
            post.extra.pop("source_country_default", None)  # resolved; no longer a bare default
    if len(post.description_snippet) < 200 and not text.startswith("%PDF-"):
        post.description_snippet = truncate(text, 600)
    post.extra["detail_text"] = text[:6000] if not text.startswith("%PDF-") else ""


# --------------------------------------------------------------------------- orchestration
DEAD_STATUS = {404, 410}  # bit.ly answers 410/404 for deactivated links; boards 404 removed ads


async def check_still_open(scraper: Any, post: JobPostSchema) -> str | None:
    """Re-visit a posting. Returns why it's closed, or None if it still looks open/unknown."""
    try:
        text = await scraper.fetch_detail(post)
    except FetchError as exc:
        return f"link no longer works (HTTP {exc.status})" if exc.status in DEAD_STATUS else None
    except Exception:  # noqa: BLE001 - unreachable != closed
        return None
    if post.extra.get("closed"):  # e.g. Workday: canApply=false / posting end date passed
        return str(post.extra["closed"])
    closed = detect_closed(text)
    if closed:
        return f"page says \u201c{closed}\u201d"
    d, _ = extract_deadline(text or "")
    if d and d < _today() and not post.deadline:
        return f"deadline passed ({d:%d %b %Y})"
    stale = start_date_passed(text)
    post.extra.pop("stale_start_note", None)
    if stale and not (post.deadline and post.deadline >= _today()):
        post.extra["stale_start_note"] = stale
    return None


class Enricher:
    def __init__(self, cfg: EnrichConfig, http: HttpClient | None = None):
        self.cfg = cfg
        self.http = http

    async def enrich_many(self, items: list[tuple[Any, JobPostSchema]]) -> set[str]:
        """items: (scraper, post). Returns job_ids whose detail page was read (or found dead)."""
        if not self.cfg.fetch_details:
            return set()
        sem = asyncio.Semaphore(self.cfg.detail_concurrency)
        ok: set[str] = set()

        async def one(scraper: Any, post: JobPostSchema) -> None:
            async with sem:
                try:
                    text = await scraper.fetch_detail(post)
                except FetchError as exc:
                    if exc.status in DEAD_STATUS:
                        post.extra["closed"] = f"link no longer works (HTTP {exc.status})"
                        ok.add(post.job_id)
                    else:
                        log.info("detail fetch failed for %s: %s", post.url, exc)
                    return
                except Exception as exc:  # noqa: BLE001 - detail pages are best-effort
                    log.info("detail fetch failed for %s: %s", post.url, exc)
                    return
                if not text:
                    return
                apply_heuristics(post, text)
                ok.add(post.job_id)

        await asyncio.gather(*(one(s, p) for s, p in items[: self.cfg.max_details_per_run]))
        return ok


class _GenericOpenerForTests:
    """Minimal 'scraper' that opens any URL the generic way (used in tests)."""

    def __init__(self, http: HttpClient):
        self.http = http

    async def fetch_detail(self, post: JobPostSchema) -> str | None:
        from .scrapers.base import generic_fetch_detail
        return await generic_fetch_detail(self.http, post)
