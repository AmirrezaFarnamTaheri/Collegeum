"""Settings for the job-board scrapers and the preference rules.

Board sources live in ``config/sources.toml`` as ``[[board]]`` tables, the preference rules
(fields, region, employer type...) in ``config/preferences.toml``. Both are plain TOML so they
can be edited in the GitHub web editor.
"""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_ENV = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _interpolate(value: Any) -> Any:
    """``${VAR}`` / ``${VAR:-default}`` in TOML strings are read from the environment."""
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    return value


class SourceConfig(BaseModel):
    """One ``[[board]]`` entry. Unknown keys are kept and passed to the scraper as options."""

    model_config = ConfigDict(extra="allow")

    name: str
    type: str
    enabled: bool = True
    group: str = "other"  # aggregator | university | social -- informational
    institution: str | None = None
    country: str | None = None
    field_implied: bool = False
    min_interval: float | None = None  # seconds between requests to this host
    may_be_empty: bool = False  # small department pages: "no jobs right now" is normal

    def opt(self, key: str, default: Any = None) -> Any:
        return (self.model_extra or {}).get(key, default)


class FilterConfig(BaseModel):
    strong_terms: list[str] = Field(default_factory=list)
    role_terms: list[str] = Field(default_factory=list)
    field_terms: list[str] = Field(default_factory=list)
    field_terms_weak: list[str] = Field(default_factory=list)
    field_exclude_terms: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    exclude_phd_positions: bool = True
    employer_allow_patterns: list[str] = Field(default_factory=list)
    employer_allow_names: list[str] = Field(default_factory=list)
    employer_block_patterns: list[str] = Field(default_factory=list)
    excluded_employers: list[str] = Field(default_factory=list)
    regions_include: list[str] = Field(default_factory=lambda: ["UK", "Europe", "Canada"])
    keep_unknown_region: bool = True
    drop_expired: bool = True
    max_age_days: int = 120


class EnrichConfig(BaseModel):
    fetch_details: bool = True
    max_details_per_run: int = 150
    detail_concurrency: int = 6
    recheck_open_jobs: bool = True
    recheck_every_days: float = 3
    recheck_max_per_run: int = 40


class HttpConfig(BaseModel):
    timeout: float = 30.0
    max_retries: int = 3
    backoff_base: float = 2.0
    default_min_interval: float = 1.5
    max_concurrent_sources: int = 6
    source_timeout: float = 300.0
    user_agents: list[str] = Field(default_factory=list)


class TelegramPrefs(BaseModel):
    list_page_size: int = 5  # positions per message for /positions etc.
    list_max: int = 60  # most positions one command shows
    digest_page_size: int = 6  # positions per message when many are new at once
    alert_on_source_failures: int = 3  # warn when a source failed N runs in a row (0 = off)


class Preferences(BaseModel):
    filters: FilterConfig = Field(default_factory=FilterConfig)
    enrich: EnrichConfig = Field(default_factory=EnrichConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    telegram: TelegramPrefs = Field(default_factory=TelegramPrefs)


def load_preferences(path: str | Path) -> Preferences:
    """Read ``config/preferences.toml``; a missing file means "no filtering" defaults."""
    file = Path(path)
    if not file.exists():
        return Preferences()
    with file.open("rb") as handle:
        raw = tomllib.load(handle)
    return Preferences.model_validate(_interpolate(raw))


def load_board_sources(path: str | Path) -> list[SourceConfig]:
    """Read every ``[[board]]`` table from ``config/sources.toml``."""
    file = Path(path)
    if not file.exists():
        return []
    with file.open("rb") as handle:
        raw = tomllib.load(handle)
    return [SourceConfig.model_validate(_interpolate(entry)) for entry in raw.get("board", [])]
