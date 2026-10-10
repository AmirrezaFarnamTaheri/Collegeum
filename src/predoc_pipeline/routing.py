"""Decide where an accepted listing is published.

Two destinations, never both:

* ``web``: the website and X. US positions, PhD and postdoc positions, and
  anything from a bank, international organization, consultancy or company
  that is explicitly named in the routing config.
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
from .boards.utils.geo import detect_location
from .extract.heuristic import UNKNOWN_INSTITUTION
from .models import PredocListing

__all__ = ["Channel", "Router"]

_POSTDOC = re.compile(r"\bpost-?\s?doc(toral)?\b", re.IGNORECASE)
_PREDOC = re.compile(r"\bpre-?\s?(doc(toral)?|phd)\b", re.IGNORECASE)
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
    def position_kind(title: str, summary: str = "") -> str:
        """``predoc``, ``phd`` or ``postdoc``. Predoc is the default."""
        if _POSTDOC.search(title):
            return "postdoc"
        if _COMPLETED_PHD_REQUIRED.search(summary):
            return "postdoc"
        for match in _DOCTORAL_DUTY.finditer(summary):
            if not re.search(r"\b(?:not|no|may|can|optional|opportunity)\b", match[0], re.I):
                return "phd"
        if _PREDOC.search(title):
            return "predoc"
        if PHD_POSITION.search(title):
            return "phd"
        if _POSTDOC_ROLE.search(summary):
            return "postdoc"
        return "predoc"

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
    ) -> Channel:
        if self.region(country or "", city, institution) in self.cfg.web_regions:
            return Channel.WEB
        if self.position_kind(title, summary) in self.cfg.web_position_kinds:
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
        )

    def channel_for_row(self, row: sqlite3.Row) -> Channel:
        return self.channel(
            title=row["title"],
            institution=row["institution"] or "",
            country=row["country"] or "",
            city=row["city"],
            summary=row["summary"] or "",
        )
