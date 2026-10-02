"""Pydantic schema every scraper normalises into."""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .utils.text import canonical_url, clean_ws, normalize_institution, normalize_title, sha256


class JobPostSchema(BaseModel):
    title: str
    url: str
    source: str
    institution: str = ""
    department: str | None = None
    location: str | None = None
    country: str | None = None
    region: str | None = None  # UK | Europe | Canada | US | Other
    date_posted: date | None = None
    deadline: date | None = None
    deadline_text: str | None = None
    description_snippet: str = ""
    fields_of_research: str | None = None
    pi_name: str | None = None
    visa_note: str | None = None
    # True when the source only lists economics/finance jobs, so the field check can be skipped.
    field_implied: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", "institution", "description_snippet", mode="before")
    @classmethod
    def _clean(cls, v: Any) -> str:
        return clean_ws(v) if v else ""

    @field_validator("url", mode="before")
    @classmethod
    def _url(cls, v: Any) -> str:
        return canonical_url(str(v)) if v else ""

    @property
    def job_id(self) -> str:
        """Deterministic id: SHA-256 of normalised title + institution + canonical URL."""
        return sha256(normalize_title(self.title), normalize_institution(self.institution), self.url)

    @property
    def fingerprint(self) -> str:
        """URL-independent key used to spot the same job cross-posted on several boards."""
        return sha256(normalize_title(self.title), normalize_institution(self.institution))

    def haystack(self) -> str:
        """All text fields concatenated, for keyword matching."""
        return " \n ".join(
            x for x in (self.title, self.department or "", self.fields_of_research or "",
                        self.institution, self.description_snippet) if x
        )
