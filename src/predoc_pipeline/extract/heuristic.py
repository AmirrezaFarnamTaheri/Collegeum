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
from datetime import date, datetime
from typing import Any

from ..boards.config import Preferences
from ..boards.filter import RelevanceFilter
from ..boards.heuristics import PI_RX, detect_visa
from ..boards.models import JobPostSchema
from ..boards.utils.dates import extract_deadline
from ..boards.utils.geo import detect_location, is_confident_single_region, location_from_labels
from ..boards.utils.text import split_role_at_institution
from ..core.textproc import squish, truncate
from ..core.timeparse import valid_iso_offset
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
    (
        r"political econom|political science|politics|international relations",
        Discipline.POLITICAL_ECONOMY,
    ),
    (r"public polic|public econ|public finance|taxation|\btax\b", Discipline.PUBLIC_POLICY),
    (
        r"management|marketing|accounting|strategy|entrepreneur|business school|organi[sz]ational",
        Discipline.BUSINESS,
    ),
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
    # Board-labelled notes may contain the original advert, not a generated prefix.
    note = detect_visa(note) or note
    if note.startswith("No sponsorship"):
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
    """Preserve explicit times; use the legacy day-end convention for bare dates.

    Date-only persistence still needs a separate precision contract. Never
    erase an advertised time/offset or manufacture a date from a string prefix.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = value.isoformat() if isinstance(value, date) else str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            day = date.fromisoformat(text)
        except ValueError:
            return None
        return f"{day.isoformat()}T23:59:59Z"
    if not re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", text):
        return None
    if not valid_iso_offset(text):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


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


_SALARY_RX = re.compile(
    r"(?:(?:salary|stipend|remuneration|compensation|pay)[\s:]*)?"
    r"([$£€]\s*\d[\d,k\.]*(?:\s*(?:-|to|–)\s*[$£€]?\s*\d[\d,k\.]*)?"
    r"(?:\s*(?:per\s+(?:annum|year|month|hour)|p\.a\.|annually|annual|monthly|hourly|/yr|/year|/month|/mo|/hr))?)",
    re.IGNORECASE,
)

_START_RX = re.compile(
    r"(?:start(?:s|ing)?\s*(?:date)?|commencing|commencement)[\s:]*"
    r"([A-Za-z]+\s+\d{4}|Summer\s+\d{4}|Fall\s+\d{4}|Spring\s+\d{4}|Immediate(?:ly)?|ASAP)",
    re.IGNORECASE,
)

_DEGREE_RX = re.compile(
    r"\b(bachelor(?:'s)?|undergraduate|ba|bs|bsc|master(?:'s)?|msc|ma|mphil|phd|doctorate)\b",
    re.IGNORECASE,
)


_EXCLUDED_URL_RX = re.compile(
    r"/people/(?:faculty/|staff/|index|$|\?)|"
    r"/faculty/(?:index|pages/profile|personal|$|\?)|"
    r"/staff/(?:index|directory|$|\?)|"
    r"/alumni/|/experts?/|"
    r"/news/stories/|"
    r"/was-wir-bieten|/diversitaet|/studierende|/stellenangebote|"
    r"/ra-matching|/learn-more|/before-applying|/courses|/private-firms|/pre-workshop|"
    r"facid=|facId=",
    re.IGNORECASE,
)

_EXCLUDED_TITLE_RX = re.compile(
    r"^(?:(?:our\s+|current\s+|former\s+|meet\s+(?:our|the)\s+|external\s+|academic\s+)?"
    r"(?:faculty|staff|people|team|alumni|directors|board|students|studierende)|"
    r"was\s+wir\s+bieten|studierende|diversit[äa]t|stellenangebote|karriere|"
    r"why\s+do\s+a\s+pre-?doc\??|ra\s+award\s+program|before\s+applying|"
    r"benefits|our\s+culture|work\s+with\s+us|join\s+us|contact\s+us|"
    r"postdocs?|faq|privacy\s+policy|asynchronous\s+courses|pre-?docs?\s+in\s+industry|"
    r".*pre-?doctoral\s+research\s+in\s+economics\s+\(pre\)\s+workshop.*|"
    r".*students\s+achieve\s+outstanding\s+placements.*)$",
    re.IGNORECASE,
)

_BIO_PROFILE_RX = re.compile(
    r"(?:is\s+(?:an?\s+)?(?:associate\s+|assistant\s+|full\s+|adjunct\s+)?professor|teaches\s+in|"
    r"received\s+(?:his|her|their)\s+ph\.?d|earned\s+(?:his|her|their)\s+ph\.?d|joined\s+the\s+faculty)",
    re.IGNORECASE,
)


def _extract_salary(text: str, hints: dict[str, Any]) -> str | None:
    if hints.get("salary"):
        return str(hints["salary"])
    match = _SALARY_RX.search(text)
    if match:
        raw = squish(match.group(1) or "").rstrip(".,;")
        if len(raw) >= 4 and any(c.isdigit() for c in raw):
            return raw[:80]
    return None


def _extract_start(text: str, hints: dict[str, Any]) -> str | None:
    if hints.get("start_date"):
        return str(hints["start_date"])
    match = _START_RX.search(text)
    if match:
        return squish(match.group(1))[:50]
    return None


def _extract_degree(text: str, hints: dict[str, Any]) -> str | None:
    if hints.get("degree"):
        return str(hints["degree"])
    match = _DEGREE_RX.search(text)
    if match:
        return match.group(1).lower()
    return None


_TOOL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bpython\b", re.IGNORECASE), "Python"),
    (re.compile(r"\bstata\b", re.IGNORECASE), "Stata"),
    (re.compile(r"\bmatlab\b", re.IGNORECASE), "MATLAB"),
    (re.compile(r"\bjulia\b", re.IGNORECASE), "Julia"),
    (re.compile(r"\bsql\b", re.IGNORECASE), "SQL"),
    (re.compile(r"\bc\+\+\b", re.IGNORECASE), "C++"),
    (re.compile(r"\b(?:git|github)\b", re.IGNORECASE), "Git"),
    (re.compile(r"\b(?:latex|tex)\b", re.IGNORECASE), "LaTeX"),
    (
        re.compile(
            r"(?:\bR\b(?:\s+(?:programming|code|language|scripting|software|package|environment))?"
            r"|\busing\s+R\b|\bin\s+R\b|,\s*R[,;\s])"
        ),
        "R",
    ),
)


def _extract_tools(text: str, hints: dict[str, Any]) -> list[str]:
    if hints.get("tools"):
        return list(hints["tools"])
    found: list[str] = []
    for rx, name in _TOOL_PATTERNS:
        if rx.search(text) and name not in found:
            found.append(name)
    return found


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
            disciplines=disciplines_for(
                title, hints.get("department"), hints.get("fields"), text[:3000]
            ),
            visa_sponsorship_status=visa_status(visa_note),
            visa_note=visa_note,
            application_url=hints.get("final_url"),
            summary=hints.get("summary") or _summary(text),
            confidence=0.95 if hints.get("strong") else 0.9,
            salary_raw=_extract_salary(text, hints),
            min_degree=_extract_degree(text, hints),
            start_date=_extract_start(text, hints),
            tools=_extract_tools(text, hints),
        )

    def _from_text(self, *, text: str, title: str, source_url: str) -> ExtractionResult:
        title = squish(title) or squish(text.split("\n", 1)[0])[:140]
        role, inst, _loc = split_role_at_institution(title)
        institution = inst

        if _EXCLUDED_TITLE_RX.search(title) or _EXCLUDED_URL_RX.search(source_url):
            return ExtractionResult(
                is_vacancy=False,
                rejection_reason="not_a_vacancy",
                title=title,
                institution=institution or "",
                confidence=0.95,
            )

        if _BIO_PROFILE_RX.search(text[:1200]) and not any(
            t in title.lower()
            for t in (
                "assistant",
                "fellow",
                "associate",
                "intern",
                "predoc",
                "pre-doc",
                "phd",
                "candidate",
                "position",
                "scholar",
                "analyst",
            )
        ):
            return ExtractionResult(
                is_vacancy=False,
                rejection_reason="faculty",
                title=title,
                institution=institution or "",
                confidence=0.95,
            )
        if not institution:
            match = _EMPLOYER_RX.search(text[:3000])
            institution = squish(match.group(1)) if match else None
        post = JobPostSchema(
            title=role or title,
            url=source_url or "https://invalid.example/",
            source="text",
            institution=institution or "",
            description_snippet=text[:600],
        )
        verdict = self.flt.evaluate(post)
        # Only "is this a vacancy at all?" is decided here; whether it is one
        # *you* want (title, employer, field, region) is policy.py's job.
        if not verdict.keep and verdict.reason in (
            "no-role-term",
            "phd-position",
            "social-no-hiring-cue",
        ):
            reason = "phd_studentship" if verdict.reason == "phd-position" else "not_a_vacancy"
            return ExtractionResult(
                is_vacancy=False,
                rejection_reason=reason,
                title=title,
                institution=institution or "",
                confidence=0.8,
            )
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
            deadline_note=_deadline_note(
                deadline_date.isoformat() if deadline_date else None, deadline_raw,
            ),
            disciplines=disciplines_for(title, text[:3000]),
            visa_sponsorship_status=visa_status(visa_note),
            visa_note=visa_note,
            summary=_summary(text),
            confidence=confidence,
            salary_raw=_extract_salary(text, {}),
            min_degree=_extract_degree(text, {}),
            start_date=_extract_start(text, {}),
            tools=_extract_tools(text, {}),
        )
