"""The owner's preferences, applied to every listing before it can be published.

The gate and the extractor answer "is this a predoc vacancy?". This module
answers "is it one *I* want?" -- and it runs whichever extractor produced the
listing, so a confident model can never send a position these rules forbid:

* region: UK, Europe or Canada only (US and elsewhere dropped);
* employer: universities, business/economics schools and research institutes
  only -- no companies, no banks, never J-PAL (``excluded_employers``);
* field: economics / business / political science / law, not medicine,
  biology, engineering, psychology, arts or humanities;
* no PhD-student positions, no "PhD required" roles;
* no expired deadlines, no pages that say the position is filled.

All of it is configured in ``config/preferences.toml``.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .boards.config import Preferences
from .boards.filter import RelevanceFilter
from .boards.heuristics import detect_closed, phd_required
from .boards.models import JobPostSchema
from .boards.utils.geo import (
    is_confident_single_region,
    location_from_labels,
    region_from_url,
    us_signal_count,
)
from .core.textproc import truncate
from .core.timeparse import parse_datetime
from .extract.heuristic import UNKNOWN_INSTITUTION
from .models import Discipline, PredocListing, RawItem

__all__ = ["Policy"]


class Policy:
    def __init__(self, prefs: Preferences, *, trust_model_fields: bool = False) -> None:
        self.prefs = prefs
        self.flt = RelevanceFilter(prefs.filters)
        # With a language model, its discipline labels count as evidence of the
        # field; with the heuristic backend they are keyword guesses and don't.
        self.trust_model_fields = trust_model_fields

    def _post(self, *, title: str, url: str, source: str, institution: str,
              country: str | None, deadline: Any, summary: str,
              hints: dict[str, Any] | None = None, final_url: str = "") -> JobPostSchema:
        hints = hints or {}
        when = parse_datetime(deadline) if isinstance(deadline, str) else deadline
        return JobPostSchema(
            title=title,
            url=url,
            source=source,
            institution="" if institution == UNKNOWN_INSTITUTION else institution,
            department=hints.get("department"),
            fields_of_research=hints.get("fields"),
            location=hints.get("location"),
            country=country or hints.get("country"),
            region=hints.get("region"),
            deadline=when.date() if when else None,
            description_snippet=truncate(summary or "", 600),
            field_implied=bool(hints.get("field_implied")),
            extra={"employer_required": bool(hints.get("employer_required")),
                   "final_url": final_url},
        )

    def check(self, listing: PredocListing, item: RawItem) -> str | None:
        """None if the listing may be published, else the reason it may not."""
        hints = item.hints
        if hints.get("reject"):
            return str(hints["reject"])
        post = self._post(
            title=listing.title, url=item.source_url, source=item.source,
            institution=listing.institution, country=listing.location.country,
            deadline=listing.deadline, summary=listing.summary, hints=hints,
            final_url=listing.apply_url,
        )
        verdict = self.flt.evaluate(post, require_role=False)
        if not verdict.keep:
            return verdict.reason
        board = bool(hints.get("board"))  # board items had these checks on the job page
        if not board and any(rx.search((item.text or "")[:2000]) for rx in self.flt.emp_banned):
            return "excluded-employer"  # "J-PAL Europe is hiring..." with no employer field

        self.flt.assign_region(post)
        if not post.region and not board:
            text = item.text or ""
            for country, region in (location_from_labels(text[:6000]),
                                    region_from_url(listing.apply_url),
                                    is_confident_single_region(text[:4000])):
                if region:
                    post.country, post.region = country, region
                    break
            if not post.region and us_signal_count(text) >= 2:
                post.region = "US"
        ok, why = self.flt.region_ok(post)
        if not ok:
            return why

        if board:
            return None
        text = item.text or ""
        if detect_closed(text):
            return "filled-or-closed"
        field = self.flt.field_verdict_long(f"{listing.title}\n{text}")
        if field == "unwanted" and not post.field_implied:
            return "wrong-field"
        model_field = self.trust_model_fields and any(
            d is not Discipline.OTHER for d in listing.disciplines)
        if verdict.needs_field_check and field != "wanted" and not model_field:
            return "no-field"
        if self.prefs.filters.exclude_phd_positions and phd_required(text) and not verdict.strong:
            return "requires-phd"
        return None

    def check_stored(self, row: sqlite3.Row) -> str | None:
        """Today's (offline) rules on a listing saved by an earlier run.

        Tightening the preferences -- a new banned employer, a region, an
        excluded field -- then also clears positions already sent.
        """
        keys = row.keys()
        context = {
            "department": row["department"] if "department" in keys else None,
            "fields": row["fields"] if "fields" in keys else None,
        }
        post = self._post(
            title=row["title"], url=row["source_url"], source=row["source"] or "",
            institution=row["institution"], country=row["country"],
            deadline=row["deadline"], summary=row["summary"] or "",
            hints=context, final_url=row["apply_url"],
        )
        verdict = self.flt.evaluate(post, require_role=False)
        if not verdict.keep and verdict.reason not in ("stale", "expired"):
            return verdict.reason
        self.flt.assign_region(post)
        ok, why = self.flt.region_ok(post)
        return None if ok else why
