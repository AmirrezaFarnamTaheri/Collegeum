"""The ETL orchestrator.

Lifecycle of one candidate, in the order the stages actually run:

    seen? -> gate -> budget -> extract -> coerce -> threshold -> preferences
          -> dedupe -> INSERT(pending) -> still open? -> broadcast -> mark published

and, once per run, for listings already sent: re-check the preferences, and
re-visit a few links every day so filled positions drop off /positions and the
dashboard.

Two orderings here differ from the reviewed implementation and both are
correctness fixes, not preferences.

**The seen-check runs before extraction, not after.** The reviewed pipeline
sent every ingested item to the model and only then checked whether it was a
duplicate. Feeds re-serve the same entries every day, so that design pays a
model request per listing per day, forever. With a daily request quota as the
binding constraint, it exhausts the budget on re-reading yesterday's postings
and never reaches today's. Checking ``seen_items`` first makes spend
proportional to genuinely new items.

**The row is inserted before the broadcast, not after.** The reviewed code
broadcast first and inserted second, so a crash in between left a message in
the channel with no record of it -- and the next run would send it again. Here
the row goes in as ``pending``, the broadcast happens, and success flips it to
``published``. A crash leaves a recoverable pending row, which the next run
loads before broadcasting. An uncertain remote acceptance still requires
reconciliation; inserting first does not establish exactly-once delivery.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast

from . import state
from .boards.config import Preferences, load_preferences
from .core import gating
from .core.db import Database
from .core.db import init as init_db
from .core.dedupe import Deduplicator
from .core.health import source_error_count, source_summary
from .core.ratelimit import QuotaExceeded
from .core.textproc import escape_telegram_html, truncate
from .core.timeparse import format_ts, parse_datetime, utcnow
from .core.urls import url_hash
from .extract import ExtractionError, RateLimited, build_extractor
from .extract.heuristic import UNKNOWN_INSTITUTION, HeuristicExtractor, _deadline_iso
from .ingest.collectors import gather
from .ingest.http import PoliteClient
from .ingest.sources import load_sources
from .logging_setup import get_logger
from .models import CoercionError, ExtractionResult, PredocListing, RawItem, coerce
from .policy import Policy
from .publish.feedback import FeedbackStore
from .publish.telegram import (
    TelegramClient,
    TelegramError,
    render_card,
    render_digest_batches,
    render_keyboard,
)
from .routing import Channel, Router
from .settings import Settings

log = get_logger(__name__)

__all__ = ["RunStats", "run", "EXIT_OK", "EXIT_PARTIAL", "EXIT_FATAL"]

EXIT_OK = 0
EXIT_PARTIAL = 1  # completed, but some items landed in the dead-letter queue
EXIT_FATAL = 2  # could not complete


@dataclass
class RunStats:
    run_id: str = ""
    ingested: int = 0
    already_seen: int = 0
    gated: int = 0
    extracted: int = 0
    low_confidence: int = 0
    duplicates: int = 0
    refreshed: int = 0
    published: int = 0
    errors: int = 0
    source_errors: int = 0
    sources: dict[str, int] = field(default_factory=dict)
    llm_calls: int = 0
    quota_stopped: bool = False
    expired: int = 0
    not_wanted: int = 0  # failed config/preferences.toml (region, field, employer...)
    closed_before_send: int = 0  # link dead / "position filled" when checked just before sending
    closed_found: int = 0  # sent earlier, found filled/closed on a later re-check
    refiltered: int = 0  # sent earlier, no longer matches the (edited) preferences
    outcome: str = "ok"
    gate_reasons: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _run_id() -> str:
    return os.environ.get("GITHUB_RUN_ID") or uuid.uuid4().hex[:12]


def _listing_row(
    listing: PredocListing,
    *,
    source: str,
    signature: bytes | None,
    hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hints = hints or {}
    return {
        "url_hash": url_hash(listing.apply_url),
        "apply_url": listing.apply_url,
        "source_url": listing.source_url,
        "source": source,
        "title": listing.title,
        "institution": listing.institution,
        "principal_investigator": listing.principal_investigator,
        "country": listing.location.country,
        "city": listing.location.city,
        "is_remote": int(listing.location.is_remote),
        "duration_years": listing.duration_years,
        "deadline": format_ts(listing.deadline) if listing.deadline else None,
        "disciplines": json.dumps([d.value for d in listing.disciplines]),
        "visa_sponsorship_status": listing.visa_sponsorship_status.value,
        "summary": listing.summary,
        "language": listing.language,
        "model_confidence": listing.model_confidence,
        "rule_score": listing.rule_score,
        "confidence": listing.confidence,
        "signature": signature,
        "first_seen_at": None,
        "last_seen_at": None,
        "status": "pending",
        "deadline_note": listing.deadline_note,
        "visa_note": listing.visa_note,
        # What the job board said about department / research fields: kept so
        # the daily preference re-check sees what the first check saw.
        "department": hints.get("department"),
        "fields": hints.get("fields"),
        "salary_min": listing.salary_min,
        "salary_max": listing.salary_max,
        "salary_currency": listing.salary_currency,
        "salary_period": listing.salary_period,
        "salary_raw": listing.salary_raw,
        "tools_required": json.dumps(listing.tools_required),
        "tools_preferred": json.dumps(listing.tools_preferred),
        "min_degree": listing.min_degree,
        "degree_note": listing.degree_note,
        "start_term": listing.start_term,
        "start_date": listing.start_date,
    }


def _listing_from_row(row: Any) -> PredocListing:
    """Rebuild a domain object from a stored row, for republishing."""
    from .core.timeparse import parse_datetime
    from .models import Discipline, Location, VisaStatus, sanitize_summary

    raw_disc = row.get("disciplines") if isinstance(row, dict) else row["disciplines"]
    if isinstance(raw_disc, list):
        disc_names = raw_disc
    elif isinstance(raw_disc, str):
        try:
            disc_names = json.loads(raw_disc or "[]")
        except (ValueError, TypeError):
            disc_names = []
    else:
        disc_names = []
    disciplines = [Discipline(d) for d in disc_names if d in Discipline._value2member_map_] or [
        Discipline.OTHER
    ]

    def _get(key: str) -> Any:
        try:
            return row[key]
        except (KeyError, IndexError):
            return None

    raw_req = _get("tools_required")
    if isinstance(raw_req, list):
        tools_req = raw_req
    elif isinstance(raw_req, str):
        try:
            tools_req = json.loads(raw_req or "[]")
        except (ValueError, TypeError):
            tools_req = []
    else:
        tools_req = []

    raw_pref = _get("tools_preferred")
    if isinstance(raw_pref, list):
        tools_pref = raw_pref
    elif isinstance(raw_pref, str):
        try:
            tools_pref = json.loads(raw_pref or "[]")
        except (ValueError, TypeError):
            tools_pref = []
    else:
        tools_pref = []

    clean_summary = sanitize_summary(
        row["summary"] or "",
        title=row["title"],
        institution=row["institution"],
        pi=row["principal_investigator"],
    )

    return PredocListing(
        title=row["title"],
        institution=row["institution"],
        principal_investigator=row["principal_investigator"],
        location=Location(
            country=row["country"] or "",
            city=row["city"],
            is_remote=bool(row["is_remote"]),
        ),
        duration_years=row["duration_years"],
        deadline=parse_datetime(row["deadline"]),
        disciplines=disciplines,
        visa_sponsorship_status=VisaStatus(row["visa_sponsorship_status"]),
        summary=clean_summary,
        language=row["language"] or "en",
        apply_url=row["apply_url"],
        source_url=row["source_url"],
        model_confidence=row["model_confidence"] or 0.0,
        rule_score=row["rule_score"] or 0.0,
        confidence=row["confidence"] or 0.0,
        deadline_note=_get("deadline_note"),
        visa_note=_get("visa_note"),
        salary_min=_get("salary_min"),
        salary_max=_get("salary_max"),
        salary_currency=_get("salary_currency"),
        salary_period=_get("salary_period"),
        salary_raw=_get("salary_raw"),
        tools_required=tools_req,
        tools_preferred=tools_pref,
        min_degree=_get("min_degree"),
        degree_note=_get("degree_note"),
        start_term=_get("start_term"),
        start_date=_get("start_date"),
    )


def _merge_hints(result: ExtractionResult, hints: dict[str, Any]) -> ExtractionResult:
    """Fill what a model missed with what the job-board scraper already knew."""
    if not hints.get("board"):
        return result
    update: dict[str, Any] = {}
    if not result.institution and hints.get("institution"):
        update["institution"] = hints["institution"]
    if not result.country and hints.get("country") not in (None, "Europe", "Other"):
        update["country"] = hints["country"]
    if not result.deadline and hints.get("deadline"):
        update["deadline"] = _deadline_iso(hints["deadline"])
    if not result.principal_investigator and hints.get("pi"):
        update["principal_investigator"] = hints["pi"]
    if not result.application_url and hints.get("final_url"):
        update["application_url"] = hints["final_url"]
    if not result.visa_note and hints.get("visa_note"):
        update["visa_note"] = hints["visa_note"]
    return result.model_copy(update=update) if update else result


def _really_same(db: Database, other_id: int, listing: PredocListing, item: RawItem) -> bool:
    """Veto a near-duplicate match that is really two different jobs.

    Cross-posting happens *between* boards. Two postings on the same board
    with different addresses are two jobs (Stockholm University often has
    several "Research assistant in economics" posts at once), and two named
    supervisors who differ mean two jobs too.
    """
    other = db.listing(other_id)
    if other is None:
        return True
    if item.hints.get("board") and other["source"] == item.source:
        from .core.urls import canonicalize_url

        if canonicalize_url(other["source_url"]) != canonicalize_url(item.source_url):
            return False
    mine, theirs = (
        _surnames(listing.principal_investigator),
        _surnames(other["principal_investigator"]),
    )
    # "Jane Doe" vs "J. Doe", or "A. Smith, J. Doe" vs "Jane Doe": same people.
    return not (mine and theirs and not mine & theirs)


def _surnames(names: str | None) -> set[str]:
    parts = re.split(r",|;|&|\band\b", names or "", flags=re.IGNORECASE)
    return {p.split()[-1].strip(".").lower() for p in parts if p.split()}


def _dedupe_institution(listing: PredocListing, item: RawItem) -> str:
    """Two unrelated "Research Assistant" posts with no named employer are not duplicates."""
    if listing.institution == UNKNOWN_INSTITUTION:
        return f"unknown-{url_hash(item.source_url)[:12]}"
    return listing.institution


def _pre_extract(
    item: RawItem,
    *,
    db: Database,
    stats: RunStats,
    policy: Policy | None = None,
) -> tuple[gating.GateResult, str, str] | None:
    """Evaluate seen-check and pre-extraction gating for one item."""
    source_key = url_hash(item.source_url)
    # The verdict also depends on title and structured collector evidence.
    # Version the digest so legacy text-only verdicts are reconsidered once.
    evidence = json.dumps(
        {"text": item.text, "title": item.title, "apply_url_hint": item.apply_url_hint,
         "hints": item.hints},
        sort_keys=True, ensure_ascii=False, default=str,
    )
    digest = "candidate-v3:" + hashlib.sha256(evidence.encode("utf-8")).hexdigest()
    board = bool(item.hints.get("board"))

    seen = db.seen(source_key)
    # A recurring board URL may change its deadline, cohort, or vacancy status.
    # Only unchanged candidate evidence can reuse its prior verdict.
    if seen is not None and seen["content_hash"] == digest:
        # Same URL, same body: we already decided about this one.
        stats.already_seen += 1
        if seen["listing_id"]:
            db.touch_listing(int(seen["listing_id"]))
        return None

    if item.hints.get("reject"):
        # The board collector already read the job page and found a reason
        # (filled, wrong field, US, PhD required...). Record it; no extraction.
        reason = f"board:{item.hints['reject']}"
        stats.not_wanted += 1
        stats.gate_reasons[reason] = stats.gate_reasons.get(reason, 0) + 1
        db.mark_seen(
            source_key,
            source=item.source,
            decision="rejected",
            reason=reason,
            content_hash=digest,
        )
        return None

    allow_phd = not policy.prefs.filters.exclude_phd_positions if policy and policy.prefs else True
    gate = gating.evaluate(
        item.text,
        title=item.title,
        url=item.source_url,
        known_vacancy=board,
        allow_phd=allow_phd,
        allow_postdoc=True,
    )
    if not gate.passed:
        stats.gated += 1
        stats.gate_reasons[gate.reason] = stats.gate_reasons.get(gate.reason, 0) + 1
        db.mark_seen(
            source_key,
            source=item.source,
            decision="rejected",
            reason=gate.reason,
            content_hash=digest,
        )
        return None

    return gate, source_key, digest


def _post_extract(
    item: RawItem,
    *,
    gate_score: float,
    gate_lang: str,
    source_key: str,
    digest: str,
    result: Any,
    db: Database,
    deduper: Deduplicator,
    settings: Settings,
    stats: RunStats,
    policy: Policy | None = None,
) -> PredocListing | None:
    """Coerce, check policy, deduplicate, and persist an extracted listing."""
    if result is None:
        return None

    stats.extracted += 1
    result = _merge_hints(result, item.hints)

    try:
        listing = coerce(
            result,
            source_url=item.source_url,
            rule_score=gate_score,
            language=gate_lang,
            fallback_summary=item.text,
            confidence=gating.blend_confidence(
                result.confidence, gate_score, weight=settings.model_confidence_weight
            ),
        )
    except CoercionError as exc:
        stats.gated += 1
        reason = f"model:{result.rejection_reason or 'rejected'}"
        stats.gate_reasons[reason] = stats.gate_reasons.get(reason, 0) + 1
        db.mark_seen(
            source_key,
            source=item.source,
            decision="rejected",
            reason=str(exc)[:200],
            content_hash=digest,
        )
        return None

    if (listing.apply_url and gating._EXCLUDED_URL_RX.search(listing.apply_url)) or (
        listing.source_url and gating._EXCLUDED_URL_RX.search(listing.source_url)
    ):
        stats.gated += 1
        stats.gate_reasons["not-a-vacancy"] = stats.gate_reasons.get("not-a-vacancy", 0) + 1
        db.mark_seen(
            source_key,
            source=item.source,
            decision="rejected",
            reason="not-a-vacancy",
            content_hash=digest,
        )
        return None

    allow_phd = not policy.prefs.filters.exclude_phd_positions if policy and policy.prefs else True
    title_gate = gating.evaluate(
        "", title=listing.title, known_vacancy=True,
        allow_phd=allow_phd, allow_postdoc=True,
    )
    if not title_gate.passed:
        stats.gated += 1
        reason = f"title:{title_gate.reason.removeprefix('reject:')}"
        stats.gate_reasons[reason] = stats.gate_reasons.get(reason, 0) + 1
        db.mark_seen(
            source_key,
            source=item.source,
            decision="rejected",
            reason=reason,
            content_hash=digest,
        )
        return None

    if listing.confidence < settings.confidence_threshold:
        stats.low_confidence += 1
        db.mark_seen(
            source_key,
            source=item.source,
            decision="rejected",
            reason=f"low-confidence:{listing.confidence:.2f}",
            content_hash=digest,
        )
        return None

    if policy is not None:
        trust_model = False if getattr(result, "is_heuristic_fallback", False) else None
        why = policy.check(listing, item, trust_model_fields=trust_model)
        if why:
            stats.not_wanted += 1
            reason = f"preferences:{why}"
            stats.gate_reasons[reason] = stats.gate_reasons.get(reason, 0) + 1
            db.mark_seen(
                source_key,
                source=item.source,
                decision="rejected",
                reason=reason,
                content_hash=digest,
            )
            return None

    # Tier 1: exact canonical application URL or source URL.
    apply_key = url_hash(listing.apply_url)
    existing = db.listing_by_url_hash(apply_key)
    if existing is None and listing.source_url:
        existing = db.listing_by_url(listing.source_url)
    if existing is None and listing.apply_url and listing.apply_url != listing.source_url:
        existing = db.listing_by_url(listing.apply_url)

    if existing is not None:
        stats.duplicates += 1
        # Only refresh the exact application identity. A shared programme or
        # publisher URL alone does not establish the same vacancy/cohort.
        if (existing["url_hash"] == apply_key
                and existing["title"].strip().casefold() == listing.title.strip().casefold()
                and existing["institution"].strip().casefold()
                == listing.institution.strip().casefold()
                and _really_same(db, int(existing["id"]), listing, item)):
            facts = _listing_row(listing, source=item.source, signature=None, hints=item.hints)
            for key in ("url_hash", "apply_url", "source_url", "source", "first_seen_at",
                        "last_seen_at", "status", "signature"):
                facts.pop(key)
            # Partial extraction must not erase previously observed nullable facts.
            facts = {key: value for key, value in facts.items()
                     if value not in (None, "", "[]", "unknown")}
            db.refresh_listing_facts(int(existing["id"]), facts)
            stats.refreshed += 1
        db.add_alternate_source(int(existing["id"]), listing.source_url)
        db.mark_seen(
            source_key,
            source=item.source,
            decision="duplicate",
            reason="url",
            content_hash=digest,
            listing_id=int(existing["id"]),
        )
        return None

    # Tiers 2 and 3.
    dedupe_text = Deduplicator.text_for(listing.title, listing.summary)
    dedupe_inst = _dedupe_institution(listing, item)
    signature = Deduplicator.signature(dedupe_text, deduper.num_perm)
    duplicate = deduper.find(
        text=dedupe_text,
        institution=dedupe_inst,
        title=listing.title,
        principal_investigator=listing.principal_investigator,
        deadline=listing.deadline,
        signature=signature,
    )
    if duplicate is not None and not _really_same(db, duplicate.listing_id, listing, item):
        duplicate = None
    if duplicate is not None:
        stats.duplicates += 1
        db.add_alternate_source(duplicate.listing_id, listing.source_url)
        db.mark_seen(
            source_key,
            source=item.source,
            decision="duplicate",
            reason=duplicate.tier,
            content_hash=digest,
            listing_id=duplicate.listing_id,
        )
        log.info(
            "duplicate",
            tier=duplicate.tier,
            score=round(duplicate.score, 3),
            against=duplicate.listing_id,
        )
        return None

    listing_id = db.insert_listing(
        _listing_row(
            listing,
            source=item.source,
            signature=signature.to_bytes() if signature else None,
            hints=item.hints,
        )
    )
    deduper.add(
        listing_id,
        text=dedupe_text,
        institution=dedupe_inst,
        title=listing.title,
        principal_investigator=listing.principal_investigator,
        deadline=listing.deadline,
        signature=signature,
    )
    db.mark_seen(
        source_key,
        source=item.source,
        decision="accepted",
        content_hash=digest,
        listing_id=listing_id,
    )
    listing.__dict__["_listing_id"] = listing_id  # carried to the broadcast step
    listing.__dict__["_page_read"] = bool(item.hints.get("enriched"))
    return listing


def _process(
    item: RawItem,
    *,
    db: Database,
    extractor: Any,
    deduper: Deduplicator,
    settings: Settings,
    stats: RunStats,
    policy: Policy | None = None,
) -> PredocListing | None:
    """Run one candidate through the funnel. Returns a listing to broadcast."""
    pre = _pre_extract(item, db=db, stats=stats, policy=policy)
    if pre is None:
        return None
    gate, source_key, digest = pre

    try:
        result = extractor.extract(
            text=item.text, source_url=item.source_url, title=item.title, hints=item.hints
        )
    except RateLimited:
        raise
    except QuotaExceeded:
        raise
    except ExtractionError as exc:
        stats.errors += 1
        db.log_dlq(
            run_id=stats.run_id,
            stage="extract",
            source=item.source,
            source_url=item.source_url,
            payload=truncate(item.text, 2000),
            error=str(exc),
        )
        return None

    return _post_extract(
        item,
        gate_score=gate.score,
        gate_lang=gate.language,
        source_key=source_key,
        digest=digest,
        result=result,
        db=db,
        deduper=deduper,
        settings=settings,
        stats=stats,
        policy=policy,
    )


def _publish_to_x(
    x_client: Any,
    listing_id: int,
    listing: PredocListing,
    db: Database,
    stats: RunStats,
) -> str | None:
    row = db.listing(listing_id)
    if row is not None and row["x_post_id"]:
        return str(row["x_post_id"])
    try:
        tweet_id = x_client.post_listing(listing)
        db.mark_x_published(listing_id, tweet_id)
        log.info("x_published", listing_id=listing_id, tweet_id=tweet_id)
        return cast(str, tweet_id)
    except Exception as exc:
        stats.errors += 1
        db.log_dlq(
            run_id=stats.run_id,
            stage="publish_x",
            source=listing.source_url,
            source_url=listing.source_url,
            payload=truncate(listing.title, 300),
            error=str(exc),
        )
        log.warning("x_publish_failed", listing_id=listing_id, error=str(exc))
        return None


def _retry_x_publications(
    x_client: Any,
    settings: Settings,
    db: Database,
    stats: RunStats,
    prefs: Preferences,
    policy: Policy,
    feedback: FeedbackStore,
    router: Router,
    *,
    skip: set[int],
    transport: Any = None,
) -> None:
    """Recover independent X delivery without changing website publication history."""
    if x_client is None or settings.x_retry_limit == 0:
        return
    candidates = []
    for row in reversed(db.active_listings()):
        lid = int(row["id"])
        if lid in skip or row["x_post_id"] or row["url_hash"] in feedback.hidden:
            continue
        if policy.check_stored(row):
            continue
        listing = _listing_from_row(row)
        if listing.deadline is not None and listing.deadline < utcnow():
            continue
        if router.channel_for(listing) is not Channel.WEB:
            continue
        candidates.append((lid, listing))
        if len(candidates) >= settings.x_retry_limit:
            break
    candidates = _verify_before_sending(candidates, prefs, db, stats, transport)
    for lid, listing in candidates:
        _publish_to_x(x_client, lid, listing, db, stats)


def _broadcast(
    listings: list[tuple[int, PredocListing]],
    telegram: TelegramClient | None,
    settings: Settings,
    db: Database,
    stats: RunStats,
    *,
    router: Router | None = None,
    x_client: Any | None = None,
    feedback: FeedbackStore | None = None,
    digest_page_size: int = 6,
    sleep: Any = None,
) -> None:
    """Deliver accepted listings to the channel the router picks for each.

    Web listings (US, PhD/postdoc, banks, international organizations, firms) are
    published by the dashboard export and posted to X when configured. Telegram
    listings (non-US predocs) go out as cards or as a few numbered digest messages;
    with a personal chat configured (see ``Settings.owner_ids``) every card and
    digest carries ✅ ❌ 📝 buttons and ``telegram-sync`` records the taps.
    """
    if not listings:
        return

    include_feedback = settings.telegram_feedback_buttons
    digest_page_size = max(1, digest_page_size)
    status_of = feedback.status if feedback is not None else (lambda _h: None)
    send_kw: dict[str, Any] = {"sleep": sleep} if sleep else {}

    from .core.urls import canonicalize_url

    # Track URLs already broadcast to prevent any repeated Telegram post
    seen_urls: set[str] = set()

    for pub_row in db.published_listings():
        if pub_row["telegram_message_id"]:
            if pub_row["apply_url"]:
                seen_urls.add(canonicalize_url(pub_row["apply_url"]))
            if pub_row["source_url"]:
                seen_urls.add(canonicalize_url(pub_row["source_url"]))

    kept: list[tuple[int, PredocListing]] = []
    for lid, lst in listings:
        row = db.listing(lid)
        if row is not None and row["telegram_message_id"]:
            log.info("skip_already_published", listing_id=lid)
            continue

        canon_apply = canonicalize_url(lst.apply_url)
        canon_source = canonicalize_url(lst.source_url)
        keys = {k for k in (canon_apply, canon_source) if k}
        if keys & seen_urls:
            log.info(
                "skip_duplicate_post_url",
                listing_id=lid,
                url=canon_apply or canon_source,
            )
            db.mark_status(lid, "published")
            continue

        existing = None
        if lst.apply_url:
            existing = db.listing_by_url(lst.apply_url)
        if existing is None and lst.source_url:
            existing = db.listing_by_url(lst.source_url)
        if (
            existing is not None
            and int(existing["id"]) != lid
            and existing["telegram_message_id"]
        ):
            log.info(
                "skip_duplicate_post_existing_db",
                listing_id=lid,
                existing_id=existing["id"],
            )
            db.mark_published(lid, existing["telegram_message_id"])
            continue

        seen_urls |= keys
        kept.append((lid, lst))

    listings = kept
    if not listings:
        return

    web: list[tuple[int, PredocListing]] = []
    cards: list[tuple[int, PredocListing]] = []
    for lid, listing in listings:
        target = web if router is not None and router.channel_for(listing) is Channel.WEB else cards
        target.append((lid, listing))
    listings = cards

    # The website is regenerated from the database on every run, so a web listing
    # is live once it is marked published. X is best effort: a failed post is
    # logged to the dead-letter table and does not hold the listing back.
    for listing_id, listing in web:
        x_post_id = _publish_to_x(x_client, listing_id, listing, db, stats) if x_client else None
        db.mark_published(listing_id, None, x_post_id=x_post_id)
        stats.published += 1
        log.info(
            "published_web", listing_id=listing_id, institution=truncate(listing.institution, 60)
        )

    if not listings:
        return
    if telegram is None:
        for listing_id, _ in listings:
            db.mark_status(listing_id, "unpublished")
        log.warning("telegram_not_configured", held=len(listings))
        return

    hashes = {lid: url_hash(listing.apply_url) for lid, listing in listings}

    if (
        settings.telegram_digest_threshold > 0
        and len(listings) > settings.telegram_digest_threshold
    ):
        # A backfill should not fire forty separate notifications.
        pages = render_digest_batches(
            [(hashes[lid], listing) for lid, listing in listings],
            site_url=settings.site_url,
            page_size=digest_page_size,
            feedback=include_feedback,
            status_of=status_of,
        )
        for page in pages:
            chunk = listings[page.start:page.end]
            try:
                message_id = telegram.send_message(
                    chat_id=settings.telegram_public_channel_id,
                    html=page.html,
                    keyboard=page.keyboard,
                    **send_kw,
                )
            except TelegramError as exc:
                stats.errors += 1
                db.log_dlq(
                    run_id=stats.run_id,
                    stage="digest",
                    source="telegram",
                    source_url="",
                    payload=f"{len(chunk)} listings",
                    error=str(exc),
                )
                if _chat_level(exc):
                    _telegram_setup_problem(settings, exc)
                    return
                continue  # these stay pending and are retried next run
            for listing_id, _ in chunk:
                db.mark_published(listing_id, message_id)
            stats.published += len(chunk)
        return

    for listing_id, listing in listings:
        keyboard = render_keyboard(
            listing,
            url_hash=hashes[listing_id] if include_feedback else None,
            status=status_of(hashes[listing_id]) if include_feedback else None,
        )
        try:
            try:
                message_id = telegram.send_message(
                    chat_id=settings.telegram_public_channel_id,
                    html=render_card(listing),
                    keyboard=keyboard,
                    **send_kw,
                )
            except TelegramError as exc:
                if exc.status != 400 or not keyboard:
                    raise
                # Telegram refuses the whole message when one button URL is
                # malformed; the link is also in the text, so send it without.
                link = escape_telegram_html(listing.apply_url)
                message_id = telegram.send_message(
                    chat_id=settings.telegram_public_channel_id,
                    html=render_card(listing) + f'\n\n<a href="{link}">Open the advert</a>',
                    keyboard=None,
                    **send_kw,
                )
        except TelegramError as exc:
            stats.errors += 1
            db.log_dlq(
                run_id=stats.run_id,
                stage="publish",
                source=listing.source_url,
                source_url=listing.source_url,
                payload=truncate(listing.title, 300),
                error=str(exc),
            )
            if _chat_level(exc):
                # Bad token, bot blocked, "chat not found": no message can get
                # through. Keep everything pending for the next run.
                _telegram_setup_problem(settings, exc)
                return
            if exc.permanent:
                db.mark_status(listing_id, "undeliverable")
            continue

        db.mark_published(listing_id, message_id)
        stats.published += 1
        log.info(
            "published",
            listing_id=listing_id,
            institution=truncate(listing.institution, 60),
            confidence=round(listing.confidence, 2),
        )


def _chat_level(exc: TelegramError) -> bool:
    """Errors about the chat or the bot, not about one message."""
    text = str(exc).lower()
    return exc.status in (401, 403, 404) or "chat not found" in text or "bot was blocked" in text


def _telegram_setup_problem(settings: Settings, exc: TelegramError) -> None:
    log.error(
        "telegram_setup_problem",
        error=str(exc),
        channel_id=settings.telegram_public_channel_id,
        advice=(
            "Telegram refused the message. Check TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_PUBLIC_CHANNEL_ID, and press Start in your chat with the bot. "
            "Nothing was lost: the positions will be sent on the next run."
        ),
    )


def _verify_before_sending(
    candidates: list[tuple[int, PredocListing]],
    prefs: Preferences,
    db: Database,
    stats: RunStats,
    transport: Any = None,
) -> list[tuple[int, PredocListing]]:
    """Open the link of every listing whose page this run did not read.

    Feed items, and pending rows from earlier runs, may point at an advert
    that has since been filled (a bit.ly link that now answers 410, a page
    reading "this position has been filled"). Those are dropped here.
    """
    if not prefs.enrich.fetch_details:
        return candidates
    from .boards.collector import check_links

    todo = {
        lid: (
            listing.title,
            listing.apply_url,
            listing.deadline.date() if listing.deadline else None,
        )
        for lid, listing in candidates
        if not listing.__dict__.get("_page_read")
    }
    verdicts = check_links(
        todo, prefs.http, concurrency=prefs.enrich.detail_concurrency, transport=transport
    )
    kept = []
    for lid, listing in candidates:
        reason = verdicts.get(lid)
        if reason:
            db.mark_closed(lid, reason)
            stats.closed_before_send += 1
            log.info("closed_before_send", listing_id=lid, reason=reason)
            continue
        if lid in todo:
            db.mark_checked(lid)
        kept.append((lid, listing))
    return kept


def _recheck_published(
    db: Database, prefs: Preferences, stats: RunStats, transport: Any = None
) -> None:
    """Re-visit a few sent listings a day; mark the filled ones closed."""
    cfg = prefs.enrich
    if not (cfg.fetch_details and cfg.recheck_open_jobs):
        return
    from .boards.collector import check_links

    rows = db.due_for_recheck(cfg.recheck_every_days, cfg.recheck_max_per_run)
    todo = {}
    for r in rows:
        when = parse_datetime(r["deadline"])
        todo[int(r["id"])] = (r["title"], r["apply_url"], when.date() if when else None)
    for lid, reason in check_links(
        todo, prefs.http, concurrency=cfg.detail_concurrency, transport=transport
    ).items():
        if reason:
            db.mark_closed(lid, reason)
            stats.closed_found += 1
            log.info("closed_on_recheck", listing_id=lid, reason=reason)
        else:
            db.mark_checked(lid)


def _refilter_published(
    db: Database,
    policy: Policy,
    feedback: FeedbackStore,
    stats: RunStats,
    skip: set[int] | None = None,
) -> None:
    """Apply today's preferences to listings sent by earlier runs."""
    skip = skip or set()
    for row in db.active_listings():
        if int(row["id"]) in skip:
            continue  # judged a minute ago with the same rules and more context
        if feedback.status(row["url_hash"]) in ("valid", "applied"):
            continue  # you confirmed it yourself: don't second-guess
        why = policy.check_stored(row)
        if why:
            db.mark_closed(int(row["id"]), f"no longer matches your preferences ({why})")
            stats.refiltered += 1


def run(
    settings: Settings | None = None,
    *,
    only_sources: set[str] | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    board_transport: Any = None,
    telegram_client: Any = None,
    x_client: Any = None,
    sync_telegram: bool = True,
) -> RunStats:
    """Execute one full cycle. Never raises for per-item failures.

    ``board_transport`` / ``telegram_client`` let tests replace the network.
    """
    settings = settings or Settings()
    stats = RunStats(run_id=_run_id())
    log.info("run_start", run_id=stats.run_id, dry_run=dry_run)

    # Answer /positions and save button taps first, so today's run already
    # knows which positions you hid.
    if sync_telegram and not dry_run and settings.telegram_bot_token and settings.owner_ids:
        try:
            from .publish.bot import telegram_sync

            telegram_sync(settings, http_client=telegram_client)
        except Exception as exc:  # never let the chat side stop the run
            log.warning("telegram_sync_failed", error=str(exc))

    init_db(settings.db_path)
    db = Database(settings.db_path)
    run_row = db.start_run(stats.run_id)
    source_stats: dict[str, Any] = {}
    state_ready = False  # never overwrite the committed journal from an unrestored DB

    try:
        restored = state.restore_if_needed(db, settings.state_path, settings.seen_state_path)
        if restored:
            log.info("state_restored", listings=restored)
        state.restore_runs(db, settings.health_json)
        state_ready = True

        prefs = load_preferences(settings.preferences_config)
        feedback = FeedbackStore.from_settings(settings)
        sources = load_sources(settings.sources_config)
        unverified = [s.name for s in sources if s.enabled and not s.verified]
        if unverified:
            log.warning("unverified_sources", names=unverified[:10])

        with PoliteClient(
            user_agent=settings.http_user_agent,
            timeout=settings.http_timeout_seconds,
            per_host_delay=settings.per_host_delay_seconds,
            respect_robots=settings.respect_robots_txt,
            store=db,
        ) as client:
            items, source_stats = gather(
                settings,
                sources,
                client,
                only=only_sources,
                prefs=prefs,
                known=lambda url: db.knows_url(url_hash(url)),
                board_transport=board_transport,
            )

        stats.ingested = len(items)
        stats.sources = source_summary(source_stats)
        stats.source_errors = source_error_count(source_stats)
        log.info("ingest_complete", items=len(items), sources=len(source_stats))

        if limit:
            items = items[:limit]
        if dry_run:
            stats.outcome = "dry-run"
            allow_phd = not prefs.filters.exclude_phd_positions if prefs else True
            for item in items[:25]:
                gate = gating.evaluate(
                    item.text,
                    title=item.title,
                    url=item.source_url,
                    known_vacancy=bool(item.hints.get("board")),
                    allow_phd=allow_phd,
                    allow_postdoc=True,
                )
                log.info(
                    "dry_run_item",
                    source=item.source,
                    url=item.source_url,
                    passes_gate=gate.passed and not item.hints.get("reject"),
                    reason=item.hints.get("reject") or gate.reason,
                    score=gate.score,
                )
            return stats

        telegram = (
            TelegramClient(bot_token=settings.telegram_bot_token, client=telegram_client)
            if settings.telegram_configured
            else None
        )
        if x_client is None and settings.x_broadcast_configured:
            try:
                from .publish.x import XClient

                x_client = XClient.from_settings(settings)
            except Exception as exc:
                log.warning("x_client_init_failed", error=str(exc))
                x_client = None

        try:
            deduper = Deduplicator(
                jaccard_threshold=settings.dedupe_jaccard_threshold,
                fuzzy_threshold=settings.dedupe_fuzzy_threshold,
                deadline_window_days=settings.dedupe_deadline_window_days,
            )
            deduper.seed(db.recent_listings(settings.dedupe_lookback_days))
            log.info("dedupe_seeded", records=len(deduper), banding=deduper.banding)

            accepted: list[tuple[int, PredocListing]] = []
            sent_now: set[int] = set()
            with build_extractor(settings, store=db, prefs=prefs) as extractor:
                is_heuristic = isinstance(extractor, HeuristicExtractor)
                policy = Policy(prefs, trust_model_fields=not is_heuristic)
                if is_heuristic or settings.extraction_concurrency <= 1:
                    for item in items:
                        try:
                            listing = _process(
                                item,
                                db=db,
                                extractor=extractor,
                                deduper=deduper,
                                settings=settings,
                                stats=stats,
                                policy=policy,
                            )
                        except (QuotaExceeded, RateLimited) as exc:
                            stats.quota_stopped = True
                            stats.outcome = "quota-stopped"
                            log.warning("quota_stopped", error=str(exc))
                            break
                        except Exception as exc:
                            stats.errors += 1
                            log.exception("item_failed", source=item.source)
                            db.log_dlq(
                                run_id=stats.run_id,
                                stage="process",
                                source=item.source,
                                source_url=item.source_url,
                                payload=truncate(item.text, 1500),
                                error=repr(exc),
                            )
                            continue
                        if listing is not None:
                            accepted.append((listing.__dict__["_listing_id"], listing))
                else:
                    from concurrent.futures import ThreadPoolExecutor, as_completed

                    def _do_extract(
                        raw_item: RawItem, gate_score: float, gate_lang: str, skey: str, dig: str
                    ) -> tuple[
                        RawItem, float, str, str, str, ExtractionResult | None, Exception | None,
                    ]:
                        try:
                            res = extractor.extract(
                                text=raw_item.text,
                                source_url=raw_item.source_url,
                                title=raw_item.title,
                                hints=raw_item.hints,
                            )
                            return raw_item, gate_score, gate_lang, skey, dig, res, None
                        except Exception as exc:
                            return raw_item, gate_score, gate_lang, skey, dig, None, exc

                    batch_size = max(1, settings.extraction_concurrency * 2)
                    item_iter = iter(items)
                    stop_pipeline = False

                    while not stop_pipeline:
                        to_submit: list[tuple[RawItem, float, str, str, str]] = []
                        while len(to_submit) < batch_size:
                            try:
                                item = next(item_iter)
                            except StopIteration:
                                break

                            pre = _pre_extract(item, db=db, stats=stats, policy=policy)
                            if pre is None:
                                continue
                            gate, source_key, digest = pre
                            to_submit.append((item, gate.score, gate.language, source_key, digest))

                        if not to_submit:
                            break

                        workers = min(len(to_submit), settings.extraction_concurrency)
                        with ThreadPoolExecutor(max_workers=workers) as pool:
                            futures = [
                                pool.submit(_do_extract, it, score, lang, skey, dig)
                                for it, score, lang, skey, dig in to_submit
                            ]
                            for fut in as_completed(futures):
                                if fut.cancelled():
                                    continue
                                it, score, lang, skey, dig, result, extraction_error = fut.result()

                                if extraction_error is not None:
                                    if isinstance(extraction_error, (QuotaExceeded, RateLimited)):
                                        stats.quota_stopped = True
                                        stats.outcome = "quota-stopped"
                                        log.warning("quota_stopped", error=str(extraction_error))
                                        stop_pipeline = True
                                        for f in futures:
                                            f.cancel()
                                        # Drain workers already running: their completed
                                        # results still consume quota and must be saved.
                                        continue
                                    stats.errors += 1
                                    log.exception("item_failed", source=it.source)
                                    db.log_dlq(
                                        run_id=stats.run_id,
                                        stage="extract",
                                        source=it.source,
                                        source_url=it.source_url,
                                        payload=truncate(it.text, 2000),
                                        error=str(extraction_error),
                                    )
                                    continue

                                if result is None:
                                    continue

                                try:
                                    listing = _post_extract(
                                        it,
                                        gate_score=score,
                                        gate_lang=lang,
                                        source_key=skey,
                                        digest=dig,
                                        result=result,
                                        db=db,
                                        deduper=deduper,
                                        settings=settings,
                                        stats=stats,
                                        policy=policy,
                                    )
                                except Exception as exc:
                                    stats.errors += 1
                                    log.exception("item_failed", source=it.source)
                                    db.log_dlq(
                                        run_id=stats.run_id,
                                        stage="process",
                                        source=it.source,
                                        source_url=it.source_url,
                                        payload=truncate(it.text, 1500),
                                        error=repr(exc),
                                    )
                                    continue

                                if listing is not None:
                                    accepted.append((listing.__dict__["_listing_id"], listing))
                stats.llm_calls = getattr(extractor, "calls", 0)

            # Rows inserted by an earlier run that never reached Telegram
            # (a crash, or Telegram not configured yet) go out with today's.
            new_ids = {lid for lid, _ in accepted}
            for row in db.pending_listings():
                if int(row["id"]) not in new_ids:
                    accepted.append((int(row["id"]), _listing_from_row(row)))
            hidden = feedback.hidden
            accepted = [
                (lid, lst) for lid, lst in accepted if url_hash(lst.apply_url) not in hidden
            ]
            accepted = _verify_before_sending(accepted, prefs, db, stats, board_transport)
            sent_now = {lid for lid, _ in accepted}
            router = Router(prefs)
            _broadcast(
                accepted,
                telegram,
                settings,
                db,
                stats,
                router=router,
                x_client=x_client,
                feedback=feedback,
                digest_page_size=prefs.telegram.digest_page_size,
            )
            _retry_x_publications(
                x_client, settings, db, stats, prefs, policy, feedback, router,
                skip=sent_now, transport=board_transport,
            )
        finally:
            if telegram is not None:
                telegram.close()
            if x_client is not None and hasattr(x_client, "close"):
                x_client.close()

        _refilter_published(db, policy, feedback, stats, skip=sent_now)
        _recheck_published(db, prefs, stats, board_transport)
        stats.expired = db.expire_past_deadline(grace_days=settings.expiry_grace_days)
        db.prune()

        dlq_rows = [dict(row) for row in db.dlq_for_run(stats.run_id)]
        Path(settings.dlq_path).write_text(
            json.dumps(dlq_rows, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        if (stats.errors or stats.source_errors) and stats.outcome == "ok":
            stats.outcome = "partial"

        journal = state.write_journal(db, settings.state_path)
        router = Router(prefs)
        dashboard = state.export_dashboard(
            db, settings.dashboard_json, hidden=hidden, router=router
        )
        state.export_feed(
            db, settings.feed_path, site_url=settings.site_url, hidden=hidden, router=router
        )

        log.info(
            "run_complete",
            **{k: v for k, v in stats.as_dict().items() if k != "gate_reasons"},
            journal=journal,
            dashboard=dashboard,
        )
        _maybe_alert(db, settings, stats, source_stats, prefs)
        return stats

    except Exception:
        stats.outcome = "fatal"
        log.exception("run_failed", run_id=stats.run_id)
        raise
    finally:
        db.finish_run(run_row, {**stats.as_dict(), "outcome": stats.outcome}, source_stats)
        if state_ready and stats.outcome != "dry-run":
            # Also after a crash: whatever was sent must be in the committed
            # journal, or the next run (fresh database) would send it again.
            try:
                state.write_journal(db, settings.state_path)
                state.write_seen(db, settings.seen_state_path)
            except Exception:  # pragma: no cover
                log.exception("journal_write_failed")
        if stats.outcome != "dry-run":
            # After finish_run, so the run history includes this run.
            try:
                state.export_health(
                    db, settings.health_json, stats=stats.as_dict(),
                    preserve_existing=not state_ready,
                )
            except Exception:  # pragma: no cover - never mask the real outcome
                log.exception("health_export_failed")
        db.close()


def _maybe_alert(
    db: Database,
    settings: Settings,
    stats: RunStats,
    source_stats: dict[str, Any],
    prefs: Preferences | None = None,
) -> None:
    """Notify the maintainer about silence and about sources that keep failing.

    Silent failure is the characteristic way an unattended scraper dies: the
    workflow stays green while every source returns nothing. Two triggers here
    catch that -- a run of zero-publish days, and a source that has failed (or
    returned nothing although it normally has postings) N runs in a row. Small
    department pages marked ``may_be_empty`` are allowed to be empty.
    """
    from .alerts import notify_admin
    from .core.db import _source_failed

    messages: list[str] = []
    empty_runs = db.consecutive_empty_runs() + (0 if stats.published else 1)
    over = empty_runs - settings.empty_run_alert_threshold
    if over >= 0 and over % 7 == 0 and not stats.published:
        messages.append(
            f"{empty_runs} consecutive runs published nothing. "
            f"Last run ingested {stats.ingested} items, "
            f"{stats.gated} gated, {stats.errors} errors."
        )

    threshold = prefs.telegram.alert_on_source_failures if prefs else 3
    if threshold:
        previous = db.source_failure_streaks()
        failing = []
        for name, data in source_stats.items():
            if not isinstance(data, dict) or name.startswith("_"):
                continue
            streak = previous.get(name, 0) + 1 if _source_failed(data) else 0
            # Alert when the streak reaches the threshold, then weekly while it lasts.
            if streak >= threshold and (streak - threshold) % 7 == 0:
                note = (data.get("messages") or [""])[0] or "returned 0 postings"
                failing.append(f"{name} ({str(note)[:80]})")
        if failing:
            messages.append(
                f"{len(failing)} source(s) failing for {threshold}+ runs in a row: "
                + "; ".join(failing[:10])
            )

    if stats.quota_stopped:
        messages.append("Stopped early: model request budget exhausted.")

    for message in messages:
        notify_admin(settings, message)
