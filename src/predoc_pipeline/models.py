"""Domain models and the model-facing wire contract.

Two schemas, deliberately.

``ExtractionResult`` is the **wire** schema: everything optional, everything a
string or an enum, no formats the provider's JSON-Schema subset does not
document. ``PredocListing`` is the **domain** schema: validated, typed, and the
only thing the rest of the pipeline sees. ``coerce`` is the one-way bridge.

Splitting them is not ceremony. Generating the request schema from the strict
Pydantic model, as the reviewed implementation did, emits ``format: "uri"``
(undocumented in the supported subset), ``$defs``/``$ref`` indirection for
nested models, and ``minItems`` on a required array -- so a model that returns
an empty discipline list triggers a validation error, a retry, and another
charge against a daily quota that is the pipeline's scarcest resource. Accept
loosely, normalise deterministically in code, and spend retries only on genuine
parse failures.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .core.textproc import squish, truncate
from .core.timeparse import parse_datetime
from .core.urls import clean_url

__all__ = [
    "Discipline",
    "VisaStatus",
    "Location",
    "PredocListing",
    "ExtractionResult",
    "RawItem",
    "EXTRACTION_JSON_SCHEMA",
    "CANONICAL_TOOLS",
    "parse_salary",
    "normalize_tools",
    "normalize_degree",
    "normalize_start_date",
    "coerce",
    "CoercionError",
]


class Discipline(StrEnum):
    APPLIED_MICRO = "Applied Microeconomics"
    MACRO = "Macroeconomics"
    ECONOMETRICS = "Econometrics"
    FINANCE = "Finance"
    PUBLIC_POLICY = "Public Policy"
    LABOR = "Labor Economics"
    DEVELOPMENT = "Development Economics"
    BEHAVIORAL = "Behavioral/Experimental Economics"
    IO = "Industrial Organization"
    TRADE = "International Trade"
    ENVIRONMENTAL = "Environmental and Energy Economics"
    HEALTH = "Health Economics"
    POLITICAL_ECONOMY = "Political Economy"
    QUANT_SOCIAL = "Quantitative Social Sciences"
    BUSINESS = "Business and Management"
    LAW = "Law and Economics"
    OTHER = "Other"


class VisaStatus(StrEnum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    UNKNOWN = "unknown"
    NOT_OFFERED = "not_offered"  # "no visa sponsorship" / citizens only / priority to citizens


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country: str = ""
    city: str | None = None
    is_remote: bool = False


class PredocListing(BaseModel):
    """A validated vacancy. The only shape the pipeline works with."""

    model_config = ConfigDict(extra="forbid")

    title: str
    institution: str
    principal_investigator: str | None = None
    location: Location = Field(default_factory=Location)
    duration_years: float | None = None
    deadline: datetime | None = None
    disciplines: list[Discipline] = Field(default_factory=lambda: [Discipline.OTHER])
    visa_sponsorship_status: VisaStatus = VisaStatus.UNKNOWN
    summary: str = ""
    language: str = "en"
    apply_url: str
    source_url: str
    model_confidence: float = Field(0.0, ge=0.0, le=1.0)
    rule_score: float = Field(0.0, ge=0.0, le=1.0)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    # Human-readable extras from the job page: "15 March (year not stated)",
    # "Visa support mentioned ("...")". Shown on the card, never used for logic.
    deadline_note: str | None = None
    visa_note: str | None = None

    # Candidate-facing attributes
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    salary_raw: str | None = None
    tools_required: list[str] = Field(default_factory=list)
    tools_preferred: list[str] = Field(default_factory=list)
    min_degree: str | None = None
    degree_note: str | None = None
    start_term: str | None = None
    start_date: str | None = None

    @field_validator("title", "institution")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        cleaned = squish(value)
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned[:300]

    @field_validator("duration_years")
    @classmethod
    def _sane_duration(cls, value: float | None) -> float | None:
        # A 40-year "predoc" is a parse failure, not a long contract.
        if value is None:
            return None
        return value if 0 < value <= 10 else None

    @field_validator("salary_min", "salary_max")
    @classmethod
    def _sane_salary(cls, value: float | None) -> float | None:
        if value is None:
            return None
        return value if 0 <= value <= 2_000_000 else None


class RawItem(BaseModel):
    """An unprocessed candidate emitted by an ingestion source."""

    model_config = ConfigDict(extra="forbid")

    source: str
    source_url: str
    title: str = ""
    text: str
    html: str | None = None
    published_at: datetime | None = None
    apply_url_hint: str | None = None
    # Structured facts a job-board scraper already knows (institution, country,
    # deadline, the page the link finally landed on, a rejection reason...).
    # See boards/collector.py. Empty for feed/portal/social items.
    hints: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Wire contract
# --------------------------------------------------------------------------

_DISCIPLINE_VALUES = [d.value for d in Discipline]

#: Hand-written JSON Schema restricted to the documented supported subset:
#: type (including nullable unions), enum, format date-time, properties,
#: required, additionalProperties, items, minimum/maximum, description.
#: No $ref, no $defs, no format: uri, no minItems.
EXTRACTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_vacancy": {
            "type": "boolean",
            "description": (
                "True only if the text advertises an open, full-time pre-doctoral "
                "or pre-PhD research position that someone can apply to now."
            ),
        },
        "rejection_reason": {
            "type": ["string", "null"],
            "enum": [
                "celebration",
                "admissions",
                "paper_or_discourse",
                "postdoc",
                "phd_studentship",
                "faculty",
                "student_job",
                "unrelated_field",
                "not_a_vacancy",
                "already_closed",
                None,
            ],
            "description": "Why this is not a predoctoral vacancy. Null if it is one.",
        },
        "title": {
            "type": ["string", "null"],
            "description": "Position title, in English. Null if not a vacancy.",
        },
        "institution": {
            "type": ["string", "null"],
            "description": (
                "Hiring university, institute, central bank or research centre. "
                "Copy it from the text; never infer one."
            ),
        },
        "principal_investigator": {
            "type": ["string", "null"],
            "description": "Named supervising faculty member or lab director, if stated.",
        },
        "country": {"type": ["string", "null"], "description": "Country, standard English name."},
        "city": {"type": ["string", "null"], "description": "Campus city or metro area."},
        "is_remote": {"type": "boolean", "description": "True only if advertised fully remote."},
        "duration_years": {
            "type": ["number", "null"],
            "minimum": 0,
            "maximum": 10,
            "description": "Contract length in years. Null if unstated or open-ended.",
        },
        "deadline": {
            "type": ["string", "null"],
            "format": "date-time",
            "description": (
                "Application deadline as ISO 8601. Null if rolling or unstated. "
                "Day-first for European dates: 03/01/2027 is 3 January 2027."
            ),
        },
        "disciplines": {
            "type": ["array", "null"],
            "items": {"type": "string", "enum": _DISCIPLINE_VALUES},
            "description": "One to three fields. Use 'Other' when unclear.",
        },
        "visa_sponsorship_status": {
            "type": ["string", "null"],
            "enum": ["explicit", "inferred", "unknown", "not_offered", None],
            "description": (
                "'explicit' if the text states sponsorship or eligibility; "
                "'inferred' if standard institutional policy clearly applies; "
                "'not_offered' if it says no sponsorship or citizens/residents only; "
                "otherwise 'unknown'."
            ),
        },
        "application_url": {
            "type": ["string", "null"],
            "description": (
                "Direct application or job-detail URL if one appears in the text. "
                "Null if none appears -- do not construct one."
            ),
        },
        "summary": {
            "type": ["string", "null"],
            "description": (
                "Two neutral sentences in English: what the role is and who it "
                "suits. No marketing language, no invented detail."
            ),
        },
        "salary_raw": {
            "type": ["string", "null"],
            "description": (
                "Compensation, salary or stipend if stated in the advert "
                "(e.g. '£35,000 p.a.' or '$60,000/yr'). Null if unstated."
            ),
        },
        "tools": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": (
                "Programming languages, software or tools mentioned "
                "(e.g. Python, Stata, R, SQL, Julia). Empty if none stated."
            ),
        },
        "min_degree": {
            "type": ["string", "null"],
            "enum": ["bachelors", "masters", "phd", "unstated", None],
            "description": "Minimum required degree. Null or 'unstated' if not specified.",
        },
        "start_date": {
            "type": ["string", "null"],
            "description": (
                "Anticipated start date or season (e.g. 'Summer 2027', 'July 2027', "
                "'Immediate'). Null if unstated."
            ),
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Calibrated probability that is_vacancy is correct.",
        },
    },
    "required": ["is_vacancy", "confidence"],
    "additionalProperties": False,
}


class ExtractionResult(BaseModel):
    """Validated form of the model's JSON, before domain coercion."""

    model_config = ConfigDict(extra="ignore")

    is_vacancy: bool = False
    rejection_reason: str | None = None
    title: str = ""
    institution: str = ""
    principal_investigator: str | None = None
    country: str | None = None
    city: str | None = None
    is_remote: bool = False
    duration_years: float | None = None
    deadline: str | None = None
    disciplines: list[str] = Field(default_factory=list)
    visa_sponsorship_status: str = "unknown"
    application_url: str | None = None
    summary: str = ""
    confidence: float = 0.0
    # Filled by the heuristic backend only (not part of the model's JSON schema).
    deadline_note: str | None = None
    visa_note: str | None = None
    is_heuristic_fallback: bool = False

    # Candidate-facing additions (from LLM or heuristic)
    salary_raw: str | None = None
    tools: list[str] = Field(default_factory=list)
    min_degree: str | None = None
    start_date: str | None = None

    # Pre-parsed bounds if provided by heuristic backend
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    tools_required: list[str] = Field(default_factory=list)
    tools_preferred: list[str] = Field(default_factory=list)
    degree_note: str | None = None
    start_term: str | None = None

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, value: Any) -> float:
        try:
            return min(max(float(value), 0.0), 1.0)
        except (TypeError, ValueError):
            return 0.0

    @field_validator("title", "summary", "institution", mode="before")
    @classmethod
    def _coerce_str(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("visa_sponsorship_status", mode="before")
    @classmethod
    def _coerce_visa(cls, value: Any) -> str:
        if not value or not isinstance(value, str):
            return "unknown"
        val = value.strip().lower()
        if val in ("explicit", "inferred", "unknown", "not_offered"):
            return val
        return "unknown"

    @field_validator("is_remote", mode="before")
    @classmethod
    def _coerce_bool(cls, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes")
        return bool(value)

    @field_validator("disciplines", "tools", mode="before")
    @classmethod
    def _listify(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return [str(v) for v in value]


class CoercionError(ValueError):
    """The model returned JSON that cannot describe a usable listing."""


_DISCIPLINE_LOOKUP = {d.value.lower(): d for d in Discipline}
_DISCIPLINE_ALIASES = {
    "applied micro": Discipline.APPLIED_MICRO,
    "microeconomics": Discipline.APPLIED_MICRO,
    "macro": Discipline.MACRO,
    "metrics": Discipline.ECONOMETRICS,
    "labour economics": Discipline.LABOR,
    "behavioural economics": Discipline.BEHAVIORAL,
    "experimental economics": Discipline.BEHAVIORAL,
    "development": Discipline.DEVELOPMENT,
    "io": Discipline.IO,
    "trade": Discipline.TRADE,
    "political economy": Discipline.POLITICAL_ECONOMY,
    "economics": Discipline.OTHER,
    "business": Discipline.BUSINESS,
    "management": Discipline.BUSINESS,
    "law": Discipline.LAW,
}


def _disciplines(values: list[str]) -> list[Discipline]:
    out: list[Discipline] = []
    for value in values:
        key = squish(value).lower()
        match = _DISCIPLINE_LOOKUP.get(key) or _DISCIPLINE_ALIASES.get(key)
        if match and match not in out:
            out.append(match)
    return out[:3] or [Discipline.OTHER]


CANONICAL_TOOLS: tuple[str, ...] = (
    "Python",
    "R",
    "Stata",
    "Julia",
    "MATLAB",
    "SQL",
    "C++",
    "Git",
    "LaTeX",
)

_TOOL_ALIASES: dict[str, str] = {
    "python": "Python",
    "r": "R",
    "r programming": "R",
    "rstudio": "R",
    "stata": "Stata",
    "julia": "Julia",
    "matlab": "MATLAB",
    "sql": "SQL",
    "c++": "C++",
    "cpp": "C++",
    "c/c++": "C++",
    "git": "Git",
    "github": "Git",
    "latex": "LaTeX",
}

_DEGREE_ALIASES: dict[str, str] = {
    "bachelor": "bachelors",
    "bachelors": "bachelors",
    "bachelor's": "bachelors",
    "undergraduate": "bachelors",
    "ba": "bachelors",
    "bs": "bachelors",
    "bsc": "bachelors",
    "master": "masters",
    "masters": "masters",
    "master's": "masters",
    "msc": "masters",
    "ma": "masters",
    "mphil": "masters",
    "phd": "phd",
    "ph.d": "phd",
    "ph.d.": "phd",
    "doctoral": "phd",
    "doctorate": "phd",
}


def parse_salary(
    raw: str | None,
) -> tuple[float | None, float | None, str | None, str | None]:
    """Parse raw compensation text into (min, max, currency, period).

    Returns (None, None, None, None) if no recognizable amounts are present.
    """
    if not raw:
        return (None, None, None, None)
    text = raw.replace(",", "").strip()

    # Currency detection
    currency = None
    if "£" in text or re.search(r"\bGBP\b", text, re.IGNORECASE):
        currency = "GBP"
    elif "€" in text or re.search(r"\bEUR\b", text, re.IGNORECASE):
        currency = "EUR"
    elif "$" in text or re.search(r"\bUSD\b", text, re.IGNORECASE):
        currency = "USD"
    elif re.search(r"\bCHF\b", text, re.IGNORECASE):
        currency = "CHF"
    elif re.search(r"\b(CAD|C\$)\b", text, re.IGNORECASE):
        currency = "CAD"
    elif re.search(r"\b(AUD|A\$)\b", text, re.IGNORECASE):
        currency = "AUD"
    elif re.search(r"\bSEK\b", text, re.IGNORECASE):
        currency = "SEK"
    elif re.search(r"\bNOK\b", text, re.IGNORECASE):
        currency = "NOK"
    elif re.search(r"\bDKK\b", text, re.IGNORECASE):
        currency = "DKK"

    # Period detection
    period = None
    if re.search(r"\b(hour|hourly|hr|p/h)\b", text, re.IGNORECASE):
        period = "hour"
    elif re.search(r"\b(month|monthly|mo|p\.m\.|pcm)\b", text, re.IGNORECASE):
        period = "month"
    elif re.search(
        r"\b(year|yearly|annum|annual|annually|p\.a\.|per annum|pa)\b", text, re.IGNORECASE
    ):
        period = "year"

    # Numbers detection, handling 'k' (e.g. 35k -> 35000)
    matches = re.findall(r"\b(\d+(?:\.\d+)?)\s*(k|kilo)?\b", text, re.IGNORECASE)
    nums: list[float] = []
    for val, k in matches:
        try:
            n = float(val)
            if k:
                n *= 1000.0
            if n > 0:
                nums.append(n)
        except ValueError:
            continue

    if not nums:
        return (None, None, currency, period)

    # Filter out potential years like 2024, 2025, 2026, 2027 if they look like calendar years
    valid_nums = [n for n in nums if not (1990 <= n <= 2040 and not currency)]
    if not valid_nums:
        valid_nums = nums

    s_min: float | None = min(valid_nums)
    s_max: float | None = max(valid_nums) if len(valid_nums) > 1 else s_min

    # Default period heuristic if unstated:
    if not period and s_min is not None:
        if s_min >= 15000:
            period = "year"
        elif 1000 <= s_min < 15000:
            period = "month"
        elif 10 <= s_min < 200:
            period = "hour"

    # Clamp sane limits
    if s_min is not None and s_min > 2_000_000:
        s_min = None
    if s_max is not None and s_max > 2_000_000:
        s_max = None

    return (s_min, s_max, currency, period)


def normalize_tools(
    tools: list[str] | None,
    text_context: str = "",
) -> tuple[list[str], list[str]]:
    """Normalize tool mentions into (required_tools, preferred_tools)."""
    req: list[str] = []
    pref: list[str] = []

    def _add(canonical: str, is_preferred: bool) -> None:
        if is_preferred:
            if canonical not in pref and canonical not in req:
                pref.append(canonical)
        else:
            if canonical not in req:
                req.append(canonical)
            if canonical in pref:
                pref.remove(canonical)

    if tools:
        for t in tools:
            clean = squish(str(t)).lower()
            if not clean:
                continue
            is_pref = bool(re.search(r"\b(prefer|plus|desir|bonus|option|nice)\b", clean))
            for k, canonical in _TOOL_ALIASES.items():
                if re.search(rf"\b{re.escape(k)}\b", clean):
                    _add(canonical, is_pref)

    # Contextual regex sweep if text context is provided
    if text_context:
        lower_ctx = text_context.lower()
        for k, canonical in _TOOL_ALIASES.items():
            if re.search(rf"\b{re.escape(k)}\b", lower_ctx) and (
                canonical not in req and canonical not in pref
            ):
                match = re.search(
                    rf"(?:prefer|plus|desirable|advantage)[\w\s,]{{0,30}}\b{re.escape(k)}\b",
                    lower_ctx,
                )
                _add(canonical, bool(match))

    return req, pref


def normalize_degree(raw: str | None) -> tuple[str, str | None]:
    """Map raw degree mention to (min_degree, degree_note)."""
    if not raw:
        return ("unstated", None)
    clean = squish(raw)
    lower = clean.lower()
    lower_normalized = re.sub(r"\.(?!\d)", "", lower)
    for k, canonical in _DEGREE_ALIASES.items():
        if re.search(rf"\b{re.escape(k)}\b", lower) or re.search(
            rf"\b{re.escape(k)}\b", lower_normalized
        ):
            return (canonical, clean if clean.lower() != canonical else None)
    return ("unstated", clean)


def normalize_start_date(raw: str | None) -> tuple[str | None, str | None]:
    """Return (start_term, start_date_iso) from a raw start date string."""
    if not raw:
        return (None, None)
    clean = squish(raw)
    dt = parse_datetime(clean)
    if not dt:
        for fmt in ("%B %Y", "%b %Y"):
            try:
                dt = datetime.strptime(clean, fmt).replace(tzinfo=UTC)
                break
            except ValueError:
                pass
    iso_date = dt.strftime("%Y-%m-%d") if dt else None
    return (clean, iso_date)


def sanitize_summary(
    raw_summary: str,
    *,
    title: str = "",
    institution: str = "",
    pi: str | None = None,
    disciplines: list[str] | None = None,
    deadline: str | None = None,
) -> str:
    """Ensure summary is clean, natural English prose free of raw PDF binary or pipe delimiters."""
    clean = squish(raw_summary)

    # 1. Detect and strip raw PDF binary leak or browser warning banners
    lower_c = clean.lower()
    if (
        "%pdf-" in lower_c
        or "/filter/flatedecode" in lower_c
        or "/xref/w" in lower_c
        or "switch to a supported browser" in lower_c
        or "please enable javascript" in lower_c
        or "javascript is disabled" in lower_c
    ):
        clean = ""
        lower_c = ""

    # 2. Strip navigation breadcrumbs and skip links
    clean = re.sub(
        r"^(?:skip to (?:main )?content\s*|back to search results\s*)+",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()
    lower_c = clean.lower()

    # 3. Detect and transform sponsoring researcher patterns
    if "sponsoring researcher" in lower_c or "sponsoring institution" in lower_c:
        m_pi = re.search(
            r"sponsoring researcher\s*:\s*([^:]+?)"
            r"(?=\s*sponsoring institution|\s*fields of research|\s*deadline|$)",
            clean,
            re.IGNORECASE,
        )
        m_inst = re.search(
            r"sponsoring institution\s*:\s*([^:]+?)"
            r"(?=\s*sponsoring researcher|\s*fields of research|\s*deadline|$)",
            clean,
            re.IGNORECASE,
        )
        m_fields = re.search(
            r"fields of research\s*:\s*([^:]+?)"
            r"(?=\s*sponsoring researcher|\s*sponsoring institution|\s*deadline|$)",
            clean,
            re.IGNORECASE,
        )
        m_dl = re.search(
            r"deadline\s*:\s*([^:]+?)"
            r"(?=\s*sponsoring researcher|\s*sponsoring institution|\s*fields of research|$)",
            clean,
            re.IGNORECASE,
        )

        pi_val = m_pi.group(1).strip() if m_pi else pi
        inst_val = m_inst.group(1).strip() if m_inst else institution
        fields_val = (
            m_fields.group(1).strip()
            if m_fields
            else (", ".join(disciplines) if disciplines else None)
        )
        dl_val = m_dl.group(1).strip() if m_dl else deadline

        prose_parts = []
        if inst_val and pi_val:
            prose_parts.append(
                f"Predoctoral research position at {inst_val}, working with {pi_val}."
            )
        elif inst_val:
            prose_parts.append(f"Predoctoral research position at {inst_val}.")
        elif pi_val:
            prose_parts.append(f"Predoctoral research position working with {pi_val}.")
        if fields_val:
            prose_parts.append(f"Research focus includes {fields_val}.")
        if dl_val:
            prose_parts.append(f"Application deadline: {dl_val}.")
        clean = " ".join(prose_parts)
        lower_c = clean.lower()

    # 4. Extract description from location/description structured headers or strip portal preamble
    if clean.lower().startswith("location :") or "description:" in clean.lower()[:150]:
        m_desc = re.search(r"description\s*:\s*(.*)", clean, re.IGNORECASE | re.DOTALL)
        if m_desc and len(m_desc.group(1).strip()) > 30:
            clean = m_desc.group(1).strip()
            lower_c = clean.lower()
    elif "about us" in lower_c and (
        clean.lower().startswith("research fellow") or "salary:" in lower_c[:150]
    ):
        clean = re.sub(r"^.*?about us\s*", "", clean, flags=re.IGNORECASE).strip()
        lower_c = clean.lower()

    # 5. Detect and transform pipe-delimited summary (e.g. pi_name: ... | institution: ...)
    if "pi_name:" in lower_c or "fields:" in lower_c or (" | " in clean and ":" in clean):
        parts: dict[str, str] = {}
        for chunk in clean.split(" | "):
            if ":" in chunk:
                k, v = chunk.split(":", 1)
                parts[k.strip().lower()] = v.strip()

        pi_val = parts.get("pi_name") or pi
        inst_val = parts.get("institution") or institution
        fields_val = parts.get("fields") or (", ".join(disciplines) if disciplines else None)
        dl_val = parts.get("deadline") or deadline

        prose_parts: list[str] = []
        if inst_val and pi_val:
            prose_parts.append(
                f"Predoctoral research position at {inst_val}, working with {pi_val}."
            )
        elif inst_val:
            prose_parts.append(f"Predoctoral research position at {inst_val}.")
        elif pi_val:
            prose_parts.append(f"Predoctoral research position working with {pi_val}.")

        if fields_val:
            prose_parts.append(f"Research focus includes {fields_val}.")
        if dl_val:
            prose_parts.append(f"Application deadline: {dl_val}.")

        clean = " ".join(prose_parts)

    # 3. Detect and replace German / foreign boilerplate summaries
    lower_s = clean.lower()
    german_indicators = (
        "wissenschaftliche", "mitarbeiter", "forschungsprojekt", "stellenangebot",
        "wir bieten", "ihre aufgaben", "ihr profil", "promotion", "vergütung", "entgeltgruppe"
    )
    if any(g in lower_s for g in german_indicators) and (
        "the role" not in lower_s and "position" not in lower_s
    ):
        clean = (
            f"Research assistant position at {institution or 'the university'}. "
            "The role involves supporting empirical research projects and academic coursework, "
            "suitable for candidates preparing for doctoral studies."
        )

    # 4. Fallback if empty
    if not clean:
        if institution and pi:
            clean = (
                f"Full-time predoctoral research assistant position at {institution}, "
                f"working with {pi}."
            )
        elif institution:
            clean = (
                f"Full-time predoctoral research position at {institution} "
                "supporting empirical and quantitative research."
            )
        elif title:
            clean = f"{title} position supporting empirical research projects."
        else:
            clean = (
                "Full-time predoctoral research position supporting quantitative "
                "academic research."
            )

    return clean


def coerce(
    result: ExtractionResult,
    *,
    source_url: str,
    rule_score: float = 0.0,
    language: str = "en",
    fallback_summary: str = "",
    confidence: float | None = None,
) -> PredocListing:
    """Turn a wire result into a validated listing.

    Raises ``CoercionError`` when the model declined the item or omitted the two
    fields a listing cannot exist without. Everything else is repaired here
    rather than bounced back to the model.
    """
    if not result.is_vacancy:
        raise CoercionError(f"not a vacancy: {result.rejection_reason or 'unspecified'}")

    title = squish(result.title)
    institution = squish(result.institution)
    if not title or not institution:
        raise CoercionError("missing title or institution")

    # A tweet reading "we're hiring a predoc, DM me" has no application URL.
    # Requiring one, as the reviewed schema did, forces the model to invent a
    # link while the same prompt forbids inventing anything. Fall back to the
    # place the signal was found and let the card label the button honestly.
    apply_url = clean_url(result.application_url or "") or clean_url(source_url)
    if not apply_url:
        raise CoercionError("no usable application or source URL")

    visa = result.visa_sponsorship_status.strip().lower()
    if visa not in {v.value for v in VisaStatus}:
        visa = VisaStatus.UNKNOWN.value

    summary = sanitize_summary(
        squish(result.summary) or squish(fallback_summary),
        title=title,
        institution=institution,
        pi=squish(result.principal_investigator or "") or None,
        disciplines=result.disciplines,
        deadline=result.deadline,
    )

    # Salary normalization
    s_raw = squish(result.salary_raw or "") or None
    s_min = result.salary_min
    s_max = result.salary_max
    s_curr = result.salary_currency
    s_per = result.salary_period
    if s_raw and (s_min is None or s_max is None or s_curr is None):
        p_min, p_max, p_curr, p_per = parse_salary(s_raw)
        s_min = s_min if s_min is not None else p_min
        s_max = s_max if s_max is not None else p_max
        s_curr = s_curr or p_curr
        s_per = s_per or p_per

    # Tools normalization
    req_tools = list(result.tools_required)
    pref_tools = list(result.tools_preferred)
    if result.tools or not (req_tools or pref_tools):
        t_req, t_pref = normalize_tools(result.tools, text_context=f"{title} {summary}")
        for t in t_req:
            if t not in req_tools:
                req_tools.append(t)
        for t in t_pref:
            if t not in pref_tools and t not in req_tools:
                pref_tools.append(t)

    # Degree normalization
    m_deg, deg_note = normalize_degree(result.min_degree)
    if result.degree_note:
        deg_note = result.degree_note

    # Start date normalization
    s_term, s_date = normalize_start_date(result.start_date)
    if result.start_term:
        s_term = result.start_term

    return PredocListing(
        title=title,
        institution=institution,
        principal_investigator=squish(result.principal_investigator or "") or None,
        location=Location(
            country=squish(result.country or ""),
            city=squish(result.city or "") or None,
            is_remote=bool(result.is_remote),
        ),
        duration_years=result.duration_years,
        deadline=parse_datetime(result.deadline),
        disciplines=_disciplines(result.disciplines),
        visa_sponsorship_status=VisaStatus(visa),
        summary=truncate(summary, 600),
        language=language,
        apply_url=apply_url,
        source_url=clean_url(source_url) or source_url,
        model_confidence=result.confidence,
        rule_score=rule_score,
        confidence=result.confidence if confidence is None else confidence,
        deadline_note=squish(result.deadline_note or "") or None,
        visa_note=squish(result.visa_note or "") or None,
        salary_min=s_min,
        salary_max=s_max,
        salary_currency=s_curr,
        salary_period=s_per,
        salary_raw=s_raw,
        tools_required=req_tools,
        tools_preferred=pref_tools,
        min_degree=m_deg,
        degree_note=deg_note,
        start_term=s_term,
        start_date=s_date,
    )
