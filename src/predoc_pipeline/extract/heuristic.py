"""Rule-based extraction: no model, no API key, no quota.

Used automatically when ``GEMINI_API_KEY`` is empty (``EXTRACTION_BACKEND=auto``)
or when ``EXTRACTION_BACKEND=heuristic``. Before this backend existed the
pipeline fell back to the null extractor, which rejects everything -- so
without a Gemini key nothing was ever published. Gemini is also not reachable
from some countries (Iran among them), so a keyless path is not optional.

For job-board items (``hints["board"]``) the board scraper has already parsed
the posting and read its page; this backend mostly copies those facts across.
For feed / portal / social items it reads the text with the same regular
expressions (deadline, visa rules, PI, location, field) that the board path uses.
"""

from __future__ import annotations

import re
from typing import Any

from ..boards.config import Preferences
from ..boards.filter import PHD_POSITION, RelevanceFilter
from ..boards.heuristics import PI_RX, detect_visa
from ..boards.models import JobPostSchema
from ..boards.utils.dates import extract_deadline
from ..boards.utils.geo import detect_location, is_confident_single_region, location_from_labels
from ..boards.utils.text import split_role_at_institution
from ..core.textproc import squish, truncate
from ..models import Discipline, ExtractionResult

__all__ = ["HeuristicExtractor", "UNKNOWN_INSTITUTION", "disciplines_for", "visa_status"]

#: Shown when neither the board nor the text names the employer.
UNKNOWN_INSTITUTION = "Employer not stated (see ad)"

_DISCIPLINE_WORDS: tuple[tuple[str, Discipline], ...] = (
    (r"macro", Discipline.MACRO),
    (r"monetary|fiscal|central bank", Discipline.MACRO),
    (r"econometric", Discipline.ECONOMETRICS),
    (r"financ|asset pricing|banking|corporate governance", Discipline.FINANCE),
    (r"labou?r|employment|wage", Discipline.LABOR),
    (r"development econ|developing countr|poverty", Discipline.DEVELOPMENT),
    (r"behaviou?ral|experimental econ", Discipline.BEHAVIORAL),
    (r"industrial organi[sz]ation|\bIO\b|competition|antitrust", Discipline.IO),
    (r"international trade|\btrade\b|globali[sz]ation", Discipline.TRADE),
    (r"environment|energy|climate", Discipline.ENVIRONMENTAL),
    (r"health econ", Discipline.HEALTH),
    (r"political econom|political science|politics|international relations",
     Discipline.POLITICAL_ECONOMY),
    (r"public polic|public econ|public finance|taxation|\btax\b", Discipline.PUBLIC_POLICY),
    (r"management|marketing|accounting|strategy|entrepreneur|business school|organi[sz]ational",
     Discipline.BUSINESS),
    (r"\blaw\b|legal", Discipline.LAW),
    (r"sociolog|demograph|quantitative social|social science", Discipline.QUANT_SOCIAL),
    (r"micro|applied econ|empirical econ", Discipline.APPLIED_MICRO),
)
_DISCIPLINE_RE = [(re.compile(p, re.IGNORECASE), d) for p, d in _DISCIPLINE_WORDS]

# "... at the Department of Economics, University of Oslo" -> the employer.
_EMPLOYER_RX = re.compile(
    r"((?:[A-Z][\w&'’.\-]*\s+){0,5}"
    r"(?:University|Universit[äa]t|Universit[àé]|Universidad|Universiteit|Institute|Institut|"
    r"School of [A-Z][\w]+(?:\s+[A-Z][\w]+)?|Business School|College|Centre|Center|"
    r"Hochschule|[ÉE]cole)"
    r"(?:\s+(?:of|for|de|di|in|zu|at)\s+(?:[A-Z][\w'’\-]*\s*){1,4})?)"
)


def disciplines_for(*texts: str | None) -> list[str]:
    """Up to three discipline labels, most specific first."""
    blob = " ".join(t for t in texts if t)
    out: list[str] = []
    for rx, discipline in _DISCIPLINE_RE:
        if rx.search(blob) and discipline.value not in out:
            out.append(discipline.value)
    return out[:3] or [Discipline.OTHER.value]


def visa_status(note: str | None) -> str:
    if not note:
        return "unknown"
    if note.startswith(("No sponsorship", "Priority to citizens")):
        return "not_offered"
    if note.startswith("Visa support"):
        return "explicit"
    return "unknown"


def _summary(text: str, limit: int = 420) -> str:
    """The first couple of sentences that are about the job, not the menu."""
    clean = squish(text)
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    picked: list[str] = []
    for sentence in sentences:
        if len(sentence) < 25 or ":" in sentence[:20]:
            continue
        picked.append(sentence)
        if sum(len(s) for s in picked) > 220 or len(picked) == 2:
            break
    return truncate(" ".join(picked) or clean, limit)


def _deadline_iso(value: Any) -> str | None:
    """Store the end of the deadline day, so a card never says "closed" on the day itself."""
    if not value:
        return None
    return f"{str(value)[:10]}T23:59:59Z"


_HAS_YEAR = re.compile(r"(?:19|20)\d{2}|\d{1,2}/\d{1,2}/\d{2}\b")


def _deadline_note(deadline: str | None, raw: str | None) -> str | None:
    """Keep the ad's own wording when the date alone would mislead.

    "Feb 28" (no year) is parsed to the next Feb 28 but might be last year's
    cycle, and "rolling" has no date at all -- both are shown on the card.
    """
    if not raw:
        return None
    if not deadline or not _HAS_YEAR.search(raw):
        return raw
    return None


def _country(country: str | None) -> str | None:
    return country if country and country not in ("Europe", "Other") else None


class HeuristicExtractor:
    """Same interface as the Gemini ``Extractor``; never touches the network."""

    calls = 0  # no model calls, ever

    def __init__(self, prefs: Preferences | None = None) -> None:
        self.prefs = prefs or Preferences()
        self.flt = RelevanceFilter(self.prefs.filters)

    def close(self) -> None:
        return None

    def __enter__(self) -> HeuristicExtractor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    # ------------------------------------------------------------------------
    def extract(
        self,
        *,
        text: str,
        source_url: str,
        title: str = "",
        hints: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        hints = hints or {}
        if hints.get("board"):
            return self._from_board(text=text, title=title, hints=hints)
        return self._from_text(text=text, title=title, source_url=source_url)

    def _from_board(self, *, text: str, title: str, hints: dict[str, Any]) -> ExtractionResult:
        deadline = _deadline_iso(hints.get("deadline"))
        visa_note = hints.get("visa_note") or detect_visa(text)
        pi = hints.get("pi")
        if not pi:
            match = PI_RX.search(text)
            pi = match.group("name") if match else None
        city = None
        location = hints.get("location") or ""
        if location and "," in location:
            city = squish(location.split(",")[0]) or None
        return ExtractionResult(
            is_vacancy=True,
            title=title,
            institution=hints.get("institution") or UNKNOWN_INSTITUTION,
            principal_investigator=pi,
            country=_country(hints.get("country")),
            city=city,
            deadline=deadline,
            deadline_note=_deadline_note(deadline, hints.get("deadline_text")),
            disciplines=disciplines_for(title, hints.get("department"), hints.get("fields"),
                                        text[:3000]),
            visa_sponsorship_status=visa_status(visa_note),
            visa_note=visa_note,
            application_url=hints.get("final_url"),
            summary=hints.get("summary") or _summary(text),
            confidence=0.95 if hints.get("strong") else 0.9,
        )

    def _from_text(self, *, text: str, title: str, source_url: str) -> ExtractionResult:
        title = squish(title) or squish(text.split("\n", 1)[0])[:140]
        role, inst, _loc = split_role_at_institution(title)
        institution = inst
        if not institution:
            match = _EMPLOYER_RX.search(text[:3000])
            institution = squish(match.group(1)) if match else None
        post = JobPostSchema(title=role or title, url=source_url or "https://invalid.example/",
                             source="text", institution=institution or "",
                             description_snippet=text[:600])
        verdict = self.flt.evaluate(post)
        # Only "is this a vacancy at all?" is decided here; whether it is one
        # *you* want (title, employer, field, region) is policy.py's job.
        if not verdict.keep and verdict.reason in ("no-role-term", "phd-position",
                                                    "social-no-hiring-cue"):
            reason = "phd_studentship" if verdict.reason == "phd-position" else "not_a_vacancy"
            return ExtractionResult(is_vacancy=False, rejection_reason=reason, title=title,
                                    institution=institution or "", confidence=0.8)
        if PHD_POSITION.search(title) and not verdict.strong:
            return ExtractionResult(is_vacancy=False, rejection_reason="phd_studentship",
                                    title=title, institution=institution or "", confidence=0.8)

        deadline_date, deadline_raw = extract_deadline(text)
        country, _region = location_from_labels(text[:6000])
        if not country:
            country, _region = detect_location(institution)
        if not country:
            country, _region = is_confident_single_region(text[:4000])
        visa_note = detect_visa(text)
        match = PI_RX.search(text)
        confidence = 0.9 if verdict.strong else 0.8 if not verdict.needs_field_check else 0.7
        return ExtractionResult(
            is_vacancy=True,
            title=role or title,
            institution=institution or UNKNOWN_INSTITUTION,
            principal_investigator=match.group("name") if match else None,
            country=_country(country),
            deadline=_deadline_iso(deadline_date.isoformat() if deadline_date else None),
            deadline_note=_deadline_note(deadline_date and deadline_date.isoformat(), deadline_raw),
            disciplines=disciplines_for(title, text[:3000]),
            visa_sponsorship_status=visa_status(visa_note),
            visa_note=visa_note,
            summary=_summary(text),
            confidence=confidence,
        )
