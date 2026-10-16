"""Decide where an accepted listing is published.

Two destinations, never both:

* ``web``: the website and X. US positions; PhD, postdoctoral, and
  PhD-qualified staff research positions; and institutional employers
  explicitly included by routing configuration.
* ``telegram``: pre-doctoral roles outside the US at universities and
  research institutes.

The rules live in ``[routing]`` of ``config/preferences.toml``.
"""

from __future__ import annotations

import re
import sqlite3
from enum import StrEnum

from .boards.config import Preferences
from .boards.filter import PHD_POSITION, RelevanceFilter
from .boards.heuristics import phd_required
from .boards.utils.geo import detect_location
from .extract.heuristic import UNKNOWN_INSTITUTION
from .models import PredocListing

__all__ = ["Channel", "Router"]

_POSTDOC = re.compile(r"\bpost-?\s?doc(?:tor(?:al)?)?\b", re.IGNORECASE)
_PREDOC = re.compile(r"\bpre-?\s?(doc(toral)?|phd)\b", re.IGNORECASE)
_PHD_JOB_MARKET = re.compile(
    r"\bph\.?d\.?\s+researcher\b.*\bph\.?d\.?\s+job\s+market\b", re.I
)
_PERMANENT = re.compile(r"\b(?:permanent|indeterminate|continuing)\b", re.I)
_DOCTORAL_DUTY = re.compile(
    r"\b(?:holder|appointee|candidate|you|employee|successful applicant)\b"
    r"[^.!?\n]{0,100}?\b(?:enroll?|register|complete|undertake|pursue|write)\w*"
    r"[^.!?\n]{0,45}?\b(?:doctoral candidate|doctoral student|"
    r"(?:ph\.?d\.?|doctoral)\s+(?:dissertation|thesis|degree|program(?:me)?))\b",
    re.IGNORECASE,
)
_COMPLETED_PHD_REQUIRED = re.compile(
    r"\b(?:completed|earned)\s+(?:a\s+)?(?:ph\.?d\.?|doctorate)\s+"
    r"(?:is\s+)?required\b|\brequires?\s+(?:a\s+)?completed\s+(?:ph\.?d\.?|doctorate)\b",
    re.IGNORECASE,
)
_POSTDOC_ROLE = re.compile(
    r"\bpost-?\s?doc(?:toral)?\s+(?:position|appointment|fellowship|role)\b|"
    r"\b(?:position|appointment|fellowship|role)\s+is\s+(?:a\s+)?post-?\s?doc(?:toral)?\b",
    re.IGNORECASE,
)
# Explicit qualification wording missed by the baseline completed-PhD heuristic.
_PHD_IN_FIELD_REQUIRED = re.compile(
    r"\b(?:ph\.?d\.?|doctorate|doctoral\s+degree)\b"
    r"(?:\s+(?:in\s+[a-z][\w&/-]*(?:\s+[\w&/-]+){0,7}|or\s+(?:an?\s+)?equivalent))?"
    r"\s+(?:is\s+)?(?:required|essential|mandatory)\b", re.IGNORECASE,
)
_US_NAMES = frozenset({"united states", "united states of america", "usa", "us", "u.s.", "u.s.a."})


class Channel(StrEnum):
    WEB = "web"
    TELEGRAM = "telegram"


class Router:
    def __init__(self, prefs: Preferences) -> None:
        self.cfg = prefs.routing
        self.flt = RelevanceFilter(prefs.filters)
        self._employer_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.cfg.web_employer_patterns
        ]
        self._employer_names = [
            re.compile(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", re.IGNORECASE)
            for n in self.cfg.web_employer_names
        ]

    @staticmethod
    def position_kind(
        title: str, summary: str = "", *, min_degree: str | None = None,
        degree_note: str | None = None,
    ) -> str:
        """Classify the *role*, using both vacancy text and structured degree facts.

        A qualification that requires an already-completed PhD is NOT a predoc,
        even if the title is simply 'Research Fellow' or 'Research Assistant'.
        Future plans to pursue a PhD are not completed-degree requirements.
        """
        # A permanent PhD job-market hire does not enroll a doctoral student.
        if _PHD_JOB_MARKET.search(title) or (
            _COMPLETED_PHD_REQUIRED.search(summary) and _PERMANENT.search(summary)
        ):
            return "research"
        if _POSTDOC.search(title):
            return "postdoc"
        if _COMPLETED_PHD_REQUIRED.search(summary):
            # A doctoral qualification is not evidence of a *postdoctoral*
            # appointment. Only explicitly postdoctoral roles get that label.
            return "postdoc" if _POSTDOC_ROLE.search(summary) else "research"
        for match in _DOCTORAL_DUTY.finditer(summary):
            if not re.search(r"\b(?:not|no|may|can|optional|opportunity)\b", match[0], re.I):
                return "phd"
        if PHD_POSITION.search(title):
            return "phd"
        if _POSTDOC_ROLE.search(summary):
            return "postdoc"
        normalized_degree = re.sub(r"[^a-z]", "", str(min_degree or "").lower())
        qualified = normalized_degree in {"phd", "doctorate", "doctoral", "doctoraldegree"}
        qualified = qualified or phd_required(summary) or phd_required(degree_note)
        # The generic heuristic misses 'a PhD in economics is required'. The
        # positive language here is deliberately narrow; a PhD *preference* or
        # 'PhD not required' must not trigger it.
        required_in_field = _PHD_IN_FIELD_REQUIRED.search(summary) or (
            _PHD_IN_FIELD_REQUIRED.search(degree_note or "")
        )
        if required_in_field and not re.search(
            r"\b(?:not|never|no)\s+(?:actually\s+)?"
            r"(?:required|essential|mandatory)\b", required_in_field.group(0), re.I,
        ):
            qualified = True
        if qualified:
            return "research"
        if _PREDOC.search(title):
            return "predoc"
        return "predoc"

    @staticmethod
    def kind_for_row(row: sqlite3.Row) -> str:
        """One classification contract for exports, bots, and subscriptions."""
        keys = row.keys()
        return Router.position_kind(
            row["title"], row["summary"] or "",
            min_degree=row["min_degree"] if "min_degree" in keys else None,
            degree_note=row["degree_note"] if "degree_note" in keys else None,
        )

    def region(self, country: str, city: str | None, institution: str) -> str | None:
        if country.strip().lower() in _US_NAMES:
            return "US"
        return detect_location(city, country, institution)[1]

    def sector(self, institution: str) -> str:
        """``institutional`` (central banks, international organizations,
        consultancies on the explicit web routing lists) or ``academic``
        (universities, research institutes, and everything else)."""
        if not institution or institution == UNKNOWN_INSTITUTION:
            return "academic"
        if any(rx.search(institution) for rx in self._employer_patterns) or any(
            rx.search(institution) for rx in self._employer_names
        ):
            return "institutional"
        return "academic"

    def _web_employer(self, institution: str) -> bool:
        """True only for institutions explicitly on the web routing allow-lists."""
        return self.sector(institution) == "institutional"

    def channel(
        self,
        *,
        title: str,
        institution: str,
        country: str = "",
        city: str | None = None,
        summary: str = "",
        min_degree: str | None = None,
        degree_note: str | None = None,
    ) -> Channel:
        if self.region(country or "", city, institution) in self.cfg.web_regions:
            return Channel.WEB
        kind = self.position_kind(
            title, summary, min_degree=min_degree, degree_note=degree_note,
        )
        # The public Telegram channel is explicitly predoc-only: a future
        # preference edit cannot silently send doctorate-qualified or doctoral
        # student vacancies into that channel.
        if kind != "predoc" or kind in self.cfg.web_position_kinds:
            return Channel.WEB
        if self._web_employer(institution):
            return Channel.WEB
        return Channel.TELEGRAM

    def channel_for(self, listing: PredocListing) -> Channel:
        return self.channel(
            title=listing.title,
            institution=listing.institution,
            country=listing.location.country,
            city=listing.location.city,
            summary=listing.summary,
            min_degree=getattr(listing, "min_degree", None),
            degree_note=getattr(listing, "degree_note", None),
        )

    def channel_for_row(self, row: sqlite3.Row) -> Channel:
        keys = row.keys()
        return self.channel(
            title=row["title"],
            institution=row["institution"] or "",
            country=row["country"] or "",
            city=row["city"],
            summary=row["summary"] or "",
            min_degree=row["min_degree"] if "min_degree" in keys else None,
            degree_note=row["degree_note"] if "degree_note" in keys else None,
        )
