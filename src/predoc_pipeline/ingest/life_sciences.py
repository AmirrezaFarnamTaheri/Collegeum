"""Independent, opt-in European life-sciences doctoral discovery.

Uses the existing bounded board adapters without the economics relevance
filter. The public career journal is shared, but this category is only
matched for subscribers who select life_sciences_phd. A job must have
doctoral-role evidence, life-science content and a known European country.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ..boards.collector import build_http
from ..boards.config import HttpConfig, load_board_sources
from ..boards.filter import PHD_POSITION
from ..boards.models import JobPostSchema
from ..boards.scrapers import SCRAPERS
from ..boards.scrapers.base import SourceSkipped
from ..boards.utils.dates import extract_deadline
from ..boards.utils.geo import detect_location
from .career import load_career, save_career
from .life_health import read_life_health, write_life_health
from .rotation import load_rotation, save_rotation

CATEGORY = "life_sciences_phd"
MAX_SOURCES = 12  # Sources attempted per scheduled run
MAX_REGISTERED = 128
MAX_CATALOG = 256
MAX_PER_SOURCE = 60
MAX_TOTAL = 200
MAX_DETAIL_PER_SOURCE = 6
MAX_DETAILS_TOTAL = 24
DETAIL_TIMEOUT = 18

# Primary research interests and nearby areas are separate so the alert can
# communicate why a posting matched without pretending to verify funding.
PRIMARY_FIELD = re.compile(
    r"\b(?:epigenetic\w*|epiallel\w*|chromatin|histone\w*|"
    r"regulatory genom\w*|functional genom\w*|gene regulat\w*|"
    r"transcriptional regulat\w*|neurodevelop\w*|"
    r"psychiatric genetic\w*|psychiatric genomic\w*|"
    r"dna methylat\w*)\b", re.I,
)
RELATED_FIELD = re.compile(
    r"\b(?:molecular biolog\w*|cell(?:ular)? biolog\w*|"
    r"developmental biolog\w*|biochem\w*|microbiolog\w*|"
    r"genom\w*|genetic\w*|"
    r"bioinformatic\w*|computational biolog\w*|systems biolog\w*|"
    r"transcriptom\w*|proteom\w*|crispr|rna biolog\w*|"
    r"single[\s-]cell|stem[\s-]cell\w*|ipsc\w*|"
    r"organoid\w*|neuroscien\w*|neurobiolog\w*)\b", re.I,
)
UNFUNDED = re.compile(
    r"\b(?:self[\s-]funded|self[\s-]financed|unfunded|"
    r"no funding available|no stipend provided)\b", re.I,
)
WRONG_ROLE = re.compile(
    r"\bpost[\s-]?doc(?:toral)?\b|"
    r"\b(?:requires?|required)\s+(?:an?\s+)?(?:completed\s+)?ph\.?d\.?\b|"
    r"\bph\.?d\.?\s+(?:degree|qualification)\s+(?:required|essential)\b",
    re.I,
)
COUNTRY_EXCLUDE = frozenset(("Europe", "United Kingdom", "United States", "Canada"))
# Reviewed official employer advertisements whose biological keywords hide a
# role requiring physics/engineering rather than an eligible life-science MSc.
# Match only exact employer vacancy identities, never broad project titles.
REVIEWED_NON_LIFE_VACANCIES = frozenset((
    "https://jobs.unibe.ch/job-vacancies/phd-position-nccr-genesis-remote-sensing-of-microorganisms-in-extreme-environments/a5825edd-e430-405e-a30e-935d10b872db",
    "https://jobs.unibe.ch/job-vacancies/phd-position-in-multisensory-development/63cc79b4-88b8-4d0b-b4df-67ad952ed3de",
))
APPLICANT_REQUIRES_PHD = re.compile(
    r"\b(?:applicants?|candidates?|you)\s+"
    r"(?:must|should|need(?:s)?(?:\s+to)?)\s+"
    r"(?:already\s+)?(?:hold|have|possess)\s+"
    r"(?:an?\s+)?(?:completed\s+)?ph\.?d\.?(?:\s+degree)?\b", re.I,
)
PHD_CALL = re.compile(
    r"\b(?:international\s+)?ph\.?d\.?\s+(?:call|recruitment|admissions?)\b",
    re.I,
)
SEASONAL_CALL = re.compile(r"\b(?:autumn|spring|winter|summer)\s+call\b", re.I)
ADDITIONAL_DOCTORAL_ROLE = re.compile(
    r"\b(?:predoctoral|pre-doctoral)\s+(?:researcher|fellow|student)\b|"
    r"\b(?:offre\s+de\s+th[eè]se|doctorand[oa]|dottorand[oa]|"
    r"doktorgradsstipendiat|väitöskirjatutkija|"
    r"tes[iie]\s+de\s+doutoramento|promotionsstelle)\b",
    re.I,
)
# A small class of employer adverts genuinely recruits either a Master's-entry
# PhD student or an already-qualified postdoc. Never infer the PhD track from
# the slash title alone: require explicit degree requirements in the detail.
DUAL_DOCTORAL_ROLE = re.compile(
    r"\b(?:ph\.?d\.?\s*(?:/|or|and|\+)\s*post[\s-]?doc(?:toral)?|"
    r"post[\s-]?doc(?:toral)?\s*(?:/|or|and|\+)\s*ph\.?d\.?)\b",
    re.I,
)
MASTERS_FOR_PHD = re.compile(
    r"\b(?:master(?:['’]s)?|msc)\b.{0,120}\b"
    r"(?:ph\.?d\.?\s+(?:applicants?|students?|candidates?)|doctoral\s+candidates?)\b"
    r"|\b(?:ph\.?d\.?\s+(?:applicants?|students?|candidates?)|doctoral\s+candidates?)\b"
    r".{0,120}\b(?:master(?:['’]s)?|msc)\b",
    re.I | re.S,
)

OUT_OF_SCOPE_TITLE = re.compile(
    r"\b(?:experimental physics|physics|statistics|statistical sciences|"
    r"classroom|educational science|education research|social science|"
    r"economic\w*|econometrics|business administration|political science)\b",
    re.I,
)


def _doctoral_title(title: str) -> bool:
    return bool(
        PHD_POSITION.search(title) or PHD_CALL.search(title)
        or ADDITIONAL_DOCTORAL_ROLE.search(title)
        or DUAL_DOCTORAL_ROLE.search(title)
    )
def historical_life_title_disqualified(title: str, url: str = "") -> bool:
    """Quarantine unmistakably off-field historical titles without guessing.

    Old journal rows lack the full vacancy detail used by classification.
    Only rule out a title that explicitly names an excluded field *and*
    does not itself name an allowed biological research domain. Ambiguous
    titles remain eligible for separate human/detail review.
    """
    if url in REVIEWED_NON_LIFE_VACANCIES:
        return True
    if WRONG_ROLE.search(title) and not DUAL_DOCTORAL_ROLE.search(title):
        return True
    return bool(
        OUT_OF_SCOPE_TITLE.search(title)
        and not (PRIMARY_FIELD.search(title) or RELATED_FIELD.search(title))
    )


EXPLICIT_LOCATION = re.compile(
    r"\b(?:location|workplace|place of work|work location|based in)"
    r"\s*[:\-]\s*([^;\n.]{2,90})", re.I,
)


def classify_post(post: JobPostSchema, *, today: date | None = None) -> dict[str, str] | None:
    """Fail closed on unknown geography, broad roles and unfunded adverts."""
    if post.url in REVIEWED_NON_LIFE_VACANCIES:
        return None
    # An index end date that the Bern adapter quarantined is never proof
    # of a deadline, even if later enrichment sets post.deadline from a
    # priority-review date. Manual verification needs a separate lifecycle.
    if (
        post.source == "life_dach_bern"
        and "prospective_unverified_end_date" in post.extra
    ):
        return None
    if not _doctoral_title(post.title):
        return None
    dual_track = bool(DUAL_DOCTORAL_ROLE.search(post.title))
    if WRONG_ROLE.search(post.title) and not (
        dual_track and MASTERS_FOR_PHD.search(post.description_snippet or "")
    ):
        return None
    # The official job-detail API may explicitly close applications even
    # before the advertised date, or without providing a date at all.
    if post.extra.get("closed"):
        return None
    if APPLICANT_REQUIRES_PHD.search(post.description_snippet or ""):
        return None
    # Board and university boilerplate often mentions unrelated research
    # (for example, a university's CRISPR discovery). Don't let that text
    # turn an explicitly non-life-science title into a life-sciences match.
    title_is_life_science = bool(
        PRIMARY_FIELD.search(post.title) or RELATED_FIELD.search(post.title)
    )
    if OUT_OF_SCOPE_TITLE.search(post.title) and not title_is_life_science:
        return None
    context = " ".join(x for x in (
        post.title, post.department, post.fields_of_research,
        post.description_snippet,
    ) if x)
    primary = bool(PRIMARY_FIELD.search(context))
    if not primary and not RELATED_FIELD.search(context):
        return None
    if UNFUNDED.search(context):
        return None
    # Source-level country is only an institutional hint. A vacancy's
    # specific workplace takes precedence, especially for universities
    # advertising international and remote positions.
    if post.extra.get("source_country_default"):
        country, region = detect_location(post.location, post.country)
    else:
        country, region = detect_location(post.country, post.location)
    if not country and not post.country and not post.location:
        # A broad European research organization can recruit internationally.
        # Only a labelled location in the vacancy itself is evidence of where
        # the position is based; collaborator addresses do not qualify.
        match = EXPLICIT_LOCATION.search(post.description_snippet)
        if match:
            country, region = detect_location(match.group(1))
    if region != "Europe" or not country or country in COUNTRY_EXCLUDE:
        return None
    current = today or datetime.now(UTC).date()
    # Cohort recruitment landing pages frequently remain indexed after
    # applications close. A dated *current* deadline is mandatory for calls.
    needs_deadline = (
        PHD_CALL.search(post.title) or SEASONAL_CALL.search(post.title)
        or post.extra.get("require_deadline")
        or dual_track
    )
    if needs_deadline and post.deadline is None:
        return None
    if post.deadline and post.deadline < current:
        return None
    # An unusually distant ATS end_date is not credible evidence of a
    # currently actionable application. Bern's live feed has an advert
    # claiming a 2036 closing date in October 2026. Preserve it in the
    # discovery journal, but require manual verification before publication.
    if post.deadline and post.deadline > current + timedelta(days=366 * 3):
        return None
    if post.date_posted and post.date_posted < current - timedelta(days=60):
        return None
    try:
        parsed = urlsplit(post.url)
        valid = parsed.scheme == "https" and bool(parsed.hostname)
        _ = parsed.port
    except ValueError:
        return None
    if not valid or len(post.url) > 1024 or not 5 <= len(post.title) <= 500:
        return None
    key = "career:" + hashlib.sha256(post.url.encode("utf-8")).hexdigest()[:32]
    result = {
        "key": key, "category": CATEGORY, "scope": "",
        "title": post.title[:200],
        "employer": (post.institution or "Research institution")[:160],
        "location": (post.location or country)[:100],
        "country": country, "source": post.source[:80], "url": post.url,
        "research_priority": "focus" if primary else "related",
        "funding_status": "unverified",
    }
    # Retain authoritative vacancy metadata already extracted from the job
    # detail. The CSV and later status audits cannot reconstruct discarded
    # deadlines, application instructions or subject classifications.
    # Do not set availability=active: a dated advertisement is not proof
    # that a previously closed listing has reopened.
    if post.deadline is not None:
        result["deadline"] = post.deadline.isoformat()
        if post.deadline_text:
            result["deadline_note"] = post.deadline_text.strip()[:160]
    if post.date_posted is not None:
        result["date_posted"] = post.date_posted.isoformat()
    if post.fields_of_research:
        result["research_fields"] = post.fields_of_research.strip()[:240]
    return result


def load_life_sources(sources_path: str | Path) -> list[Any]:
    """Load core plus regional catalogues, rejecting duplicate provider names.

    A custom test/third-party TOML is standalone unless its sibling
    life_sciences_sources/ directory exists. Disabled candidates stay visible
    in the registry but are never fetched.
    """
    base = Path(sources_path)
    entries = load_board_sources(base)
    directory = base.parent / "life_sciences_sources"
    if directory.is_dir():
        for filename in sorted(directory.glob("*.toml")):
            entries.extend(load_board_sources(filename))
    if len(entries) > MAX_CATALOG:
        raise ValueError("Life Sciences source catalogue exceeds safe limit")
    seen: set[str] = set()
    for entry in entries:
        if entry.name in seen:
            raise ValueError(f"Duplicate Life Sciences source: {entry.name}")
        seen.add(entry.name)
    return entries


def select_sources(
    sources_path: str | Path, rotation_path: str | Path | None = None,
    health_path: str | Path | None = None,
) -> set[str]:
    """Rotate oldest attempts, prioritizing feeds lacking a recorded health result.

    An attempted but never-observed source should not be starved by sources
    whose successful outcomes are already checkpointed. Once observed, a
    provider returns to the normal oldest-attempt-first rotation.
    """
    sources = [source for source in load_life_sources(sources_path) if source.enabled]
    if len(sources) > MAX_REGISTERED:
        raise ValueError("Too many enabled Life Sciences providers")
    attempts = (
        load_rotation(rotation_path).get("attempts", {})
        if rotation_path is not None else {}
    )
    report = read_life_health(health_path).get("sources", {}) if health_path else {}
    history = report if isinstance(report, dict) else {}

    def priority(source: Any) -> tuple[int, str, str]:
        result = history.get(source.name)
        observed = (
            isinstance(result, dict)
            and isinstance(result.get("last_checked_at"), str)
            and bool(result["last_checked_at"])
        )
        return (int(observed), attempts.get(source.name, ""), source.name)

    return {source.name for source in sorted(sources, key=priority)[:MAX_SOURCES]}



_VIB_OLD_JOB_PATH = re.compile(r"/j/([1-9]\d{0,11})(?:/[^/?#]+)?/?$")
_VIB_JOB_IDENTIFIER = re.compile(r"[1-9]\d{0,11}$")

def _vib_job_identifier(url: str) -> str | None:
    """Employer Jobsoid requisition identity, independent of URL format/order."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "jobs.vib.be":
            return None
    except ValueError:
        return None
    old = _VIB_OLD_JOB_PATH.fullmatch(parsed.path)
    if old:
        return old.group(1)
    if parsed.path != "/PortalJob/IntegratedJobDetails":
        return None
    ids = parse_qs(parsed.query).get("id", [])
    if len(ids) != 1 or not _VIB_JOB_IDENTIFIER.fullmatch(ids[0]):
        return None
    return ids[0]


def _vib_career_key(identifier: str, historical: dict[str, str]) -> str:
    """Use the first recorded identity if this employer migrated URL formats."""
    return historical.get(identifier) or (
        "career:" + hashlib.sha256(f"vib:job:{identifier}".encode()).hexdigest()[:32]
    )


def _needs_detail(post: JobPostSchema) -> bool:
    """Only enrich a doctoral card if research field or location is incomplete."""
    # UniBE's official Prospective API already includes the full employer
    # description. Its fetch_detail returns the SAME text, so a second pass
    # can only duplicate it and reintroduce a review date as a hard cutoff.
    if post.source == "life_dach_bern" and "prospective_full_text" in post.extra:
        return False
    if not _doctoral_title(post.title):
        return False
    if DUAL_DOCTORAL_ROLE.search(post.title):
        # The index title cannot establish the Master's-entry option or
        # whether applications remain open; fetch the job-specific evidence.
        return True
    if post.extra.get("require_deadline") and post.deadline is None:
        return True
    if PHD_CALL.search(post.title) or SEASONAL_CALL.search(post.title):
        # Doctoral school calls often put the closing date on the detail page,
        # not on the searchable index, even when the field is in the title.
        return True
    text = " ".join(
        value for value in (
            post.title, post.fields_of_research, post.department,
            post.description_snippet,
        ) if value
    )
    missing_field = not (PRIMARY_FIELD.search(text) or RELATED_FIELD.search(text))
    return missing_field or (not post.country and not post.location)


async def discover(
    sources_path: str | Path, http_config: HttpConfig, *,
    selected_names: set[str] | None = None,
    diagnostics: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[JobPostSchema], list[str]]:
    """Discover bounded, fair interleaved candidates from selected boards."""
    configs = [
        source for source in load_life_sources(sources_path)
        if source.enabled and (selected_names is None or source.name in selected_names)
    ]
    if not configs:
        return [], ["No enabled life-sciences PhD providers"]
    if len(configs) > MAX_SOURCES:
        raise ValueError("Run budget exceeded; call select_sources first")
    posts: list[JobPostSchema] = []
    errors: list[str] = []
    semaphore = asyncio.Semaphore(3)
    detail_remaining = MAX_DETAILS_TOTAL
    async with build_http(http_config) as http:

        async def one(source: Any) -> tuple[list[JobPostSchema], list[str]]:
            nonlocal detail_remaining
            if source.type not in ("rss", "link_scan", "bite_jobs", "prospective_jobs", "workday"):
                if diagnostics is not None:
                    diagnostics[source.name] = {
                        "status": "unsupported", "vacancy_links": 0,
                        "doctoral_candidates": 0, "matched_candidates": 0,
                        "discovery_issues": 1, "detail_failures": 0,
                    }
                return [], [f"{source.name}: unsupported scraper type"]
            scraper = SCRAPERS[source.type](source, http)
            async with semaphore:
                try:
                    result, _ = await asyncio.wait_for(
                        scraper.run(), timeout=min(http_config.source_timeout, 120),
                    )
                except SourceSkipped:
                    if diagnostics is not None:
                        diagnostics[source.name] = {
                            "status": "skipped", "vacancy_links": 0,
                            "doctoral_candidates": 0, "matched_candidates": 0,
                            "discovery_issues": 0, "detail_failures": 0,
                        }
                    return [], []
                except Exception as exc:  # noqa: BLE001 - isolate provider outages
                    if diagnostics is not None:
                        diagnostics[source.name] = {
                            "status": "failed", "vacancy_links": 0,
                            "doctoral_candidates": 0, "matched_candidates": 0,
                            "discovery_issues": 1, "detail_failures": 0,
                        }
                    # Preserve a useful, bounded cause in the export report
                    # while removing URLs that could contain query tokens.
                    detail = re.sub(r"https?://\S+", "<source URL>", str(exc))
                    detail = " ".join(detail.split())[:240]
                    suffix = f": {detail}" if detail else ""
                    return [], [f"{source.name}: {type(exc).__name__}{suffix}"]
                # Indexes can contain hundreds of unrelated staff jobs.
                # Give actual doctoral listings first access to the per-source
                # budget before applying the cap.
                result.sort(
                    key=lambda post: (
                        not _doctoral_title(post.title),
                        not bool(PRIMARY_FIELD.search(post.haystack())
                                 or RELATED_FIELD.search(post.haystack())),
                    ),
                )
                scoped = result[:MAX_PER_SOURCE]
                detail_used = 0
                detail_failures = 0
                for post in scoped:
                    if detail_used >= MAX_DETAIL_PER_SOURCE or detail_remaining <= 0:
                        break
                    if not _needs_detail(post):
                        continue
                    detail_remaining -= 1
                    detail_used += 1
                    try:
                        full_text = await asyncio.wait_for(
                            scraper.fetch_detail(post), timeout=DETAIL_TIMEOUT,
                        )
                    except Exception:  # noqa: BLE001 - keep listing-only evidence
                        detail_failures += 1
                        continue
                    if full_text:
                        post.description_snippet = (
                            post.description_snippet + " " + full_text[:3600]
                        )[:4300]
                        if post.deadline is None:
                            deadline, deadline_text = extract_deadline(full_text)
                            if deadline is not None:
                                post.deadline = deadline
                                post.deadline_text = deadline_text
            problems = (
                len(scraper.discovery_fetch_errors) +
                len(scraper.discovery_parse_errors) +
                len(scraper.discovery_limits)
            )
            if diagnostics is not None:
                status = (
                    "partial" if problems or detail_failures else
                    "discovered" if result else
                    "verified_empty" if getattr(scraper, "verified_empty_evidence", False)
                    else "unverified_empty"
                )
                diagnostics[source.name] = {
                    "status": status, "vacancy_links": len(result),
                    "doctoral_candidates": sum(
                        _doctoral_title(post.title) for post in scoped
                    ),
                    "matched_candidates": 0,
                    "discovery_issues": problems,
                    "detail_failures": detail_failures,
                }
            warnings = [f"{source.name}: {problems} discovery issues"] if problems else []
            return scoped, warnings

        results = await asyncio.gather(*(one(config) for config in configs))
    # High-volume aggregators must not consume the whole candidate budget
    # before smaller institutional PhD pages can contribute.
    queues = [list(found) for found, _ in results]
    while len(posts) < MAX_TOTAL and any(queues):
        for queue in queues:
            if queue and len(posts) < MAX_TOTAL:
                posts.append(queue.pop(0))
    for _, problems in results:
        errors.extend(problems)
    return posts, errors


def poll_life_sciences(
    journal_path: str | Path, *, sources_path: str | Path,
    http_config: HttpConfig,
    rotation_path: str | Path | None = None,
    health_path: str | Path | None = None,
) -> tuple[int, list[str]]:
    """Append vetted life-sciences PhDs to the existing durable career journal.

    Preserves economics/other career records and first-seen timestamps. Only
    posts first discovered after subscription are eligible for new alerts.
    """
    started = datetime.now(UTC)
    # Always bound direct calls too; optional journaling must not disable
    # selection when the catalogue exceeds the per-run budget.
    selected = select_sources(sources_path, rotation_path, health_path)
    if not selected:
        return 0, ["No enabled life-sciences PhD providers"]
    diagnostics: dict[str, dict[str, Any]] | None = (
        {} if health_path is not None else None
    )
    discover_kwargs: dict[str, Any] = {"selected_names": selected}
    if diagnostics is not None:
        discover_kwargs["diagnostics"] = diagnostics
    posts, errors = asyncio.run(
        discover(sources_path, http_config, **discover_kwargs),
    )
    previous = load_career(journal_path, tolerant=True)
    historical_vib_ids: dict[str, str] = {}
    for old_job in previous:
        if old_job.get("source") != "life_vib":
            continue
        identifier = _vib_job_identifier(str(old_job.get("url") or ""))
        if identifier and old_job.get("key"):
            historical_vib_ids.setdefault(identifier, old_job["key"])
    matches: dict[str, dict[str, str]] = {}
    for post in posts:
        item = classify_post(post)
        if item:
            if item.get("source") == "life_vib":
                identifier = _vib_job_identifier(item["url"])
                if identifier:
                    item["key"] = _vib_career_key(identifier, historical_vib_ids)
            matches.setdefault(item["key"], item)
    added = save_career(journal_path, previous, list(matches.values()))
    if health_path is not None and diagnostics is not None:
        per_source: dict[str, int] = {}
        for match in matches.values():
            key = match["source"]
            per_source[key] = per_source.get(key, 0) + 1
        for name, info in diagnostics.items():
            info["matched_candidates"] = per_source.get(name, 0)
        write_life_health(
            health_path, sources=load_life_sources(sources_path),
            diagnostics=diagnostics, started=started,
        )
    if rotation_path is not None:
        save_rotation(rotation_path, selected, timestamp=started)
    return added, errors
