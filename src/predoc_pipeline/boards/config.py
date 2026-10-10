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

from ..ingest.registry import read_registry

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
    # When true, employers outside academia (banks, firms, consultancies) pass the
    # employer check; only employer_block_patterns still reject them.
    allow_private_sector: bool = False
    excluded_employers: list[str] = Field(default_factory=list)
    regions_include: list[str] = Field(default_factory=lambda: ["UK", "Europe", "Canada"])
    keep_unknown_region: bool = True
    drop_expired: bool = True
    max_age_days: int = 120


class EnrichConfig(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    fetch_details: bool = True
    max_details_per_run: int = Field(500, ge=0)
    detail_concurrency: int = Field(6, gt=0)
    recheck_open_jobs: bool = True
    recheck_every_days: float = Field(3, ge=0, allow_inf_nan=False)
    recheck_max_per_run: int = Field(40, ge=0)


class HttpConfig(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    timeout: float = Field(30.0, gt=0, allow_inf_nan=False)
    max_retries: int = Field(3, ge=0)
    backoff_base: float = Field(2.0, ge=0, allow_inf_nan=False)
    default_min_interval: float = Field(1.5, ge=0, allow_inf_nan=False)
    max_concurrent_sources: int = Field(6, gt=0)
    source_timeout: float = Field(300.0, gt=0, allow_inf_nan=False)
    user_agents: list[str] = Field(default_factory=list)


class TelegramPrefs(BaseModel):
    list_page_size: int = 5  # positions per message for /positions etc.
    list_max: int = 60  # most positions one command shows
    digest_page_size: int = 6  # positions per message when many are new at once
    alert_on_source_failures: int = 3  # warn when a source failed N runs in a row (0 = off)


class RoutingConfig(BaseModel):
    """Which listings go to the website (and X) and which go to Telegram only."""

    web_regions: list[str] = Field(default_factory=lambda: ["US"])
    web_position_kinds: list[str] = Field(default_factory=lambda: ["phd", "postdoc"])
    web_employer_patterns: list[str] = Field(default_factory=list)
    web_employer_names: list[str] = Field(default_factory=list)


class Preferences(BaseModel):
    filters: FilterConfig = Field(default_factory=FilterConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
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
    raw = read_registry(path)
    # Registry identities are already resolved and validated across collector kinds.
    # Do not interpolate them twice if an environment value contains another template.
    return [SourceConfig.model_validate({**_interpolate(entry), "name": entry["name"]})
            for entry in raw.get("board", [])]
