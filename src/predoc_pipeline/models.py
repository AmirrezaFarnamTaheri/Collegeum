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

from datetime import datetime
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
                "celebration", "admissions", "paper_or_discourse", "postdoc",
                "phd_studentship", "faculty", "student_job", "unrelated_field",
                "not_a_vacancy", "already_closed", None,
            ],
            "description": "Why this is not a predoctoral vacancy. Null if it is one.",
        },
        "title": {"type": "string", "description": "Position title, in English."},
        "institution": {
            "type": "string",
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
            "type": "array",
            "items": {"type": "string", "enum": _DISCIPLINE_VALUES},
            "description": "One to three fields. Use 'Other' when unclear.",
        },
        "visa_sponsorship_status": {
            "type": "string",
            "enum": ["explicit", "inferred", "unknown", "not_offered"],
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
            "type": "string",
            "description": (
                "Two neutral sentences in English: what the role is and who it "
                "suits. No marketing language, no invented detail."
            ),
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Calibrated probability that is_vacancy is correct.",
        },
    },
    "required": ["is_vacancy", "title", "institution", "disciplines", "confidence"],
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

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, value: Any) -> float:
        try:
            return min(max(float(value), 0.0), 1.0)
        except (TypeError, ValueError):
            return 0.0

    @field_validator("disciplines", mode="before")
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

    summary = squish(result.summary) or squish(fallback_summary)

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
    )
