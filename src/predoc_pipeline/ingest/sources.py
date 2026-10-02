"""Declarative source registry, loaded from config/sources.toml.

Hard-coding feed URLs in Python, as both reviewed documents did, has two
problems. Feed URLs rot -- portals redesign, query parameters change, whole
services move -- and an unverified URL committed as code looks authoritative
while silently returning zero items for months. And adding a source should not
require a code change.

So sources live in TOML (parsed by stdlib `tomllib`, no dependency), each
carries a `verified` flag stating whether a human has actually seen it return
data, and two CLI commands operate on the file:

    predoc-pipeline sources verify     fetch every source, report status/counts
    predoc-pipeline sources discover   find feeds advertised by a site

`verify` is the first thing to run after cloning. It turns "the defaults are
probably wrong" from a hidden liability into a thirty-second checklist.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Source", "load_sources", "DEFAULT_SOURCES_TOML"]


@dataclass(slots=True)
class Source:
    name: str
    kind: str                       # feed | portal
    url: str
    enabled: bool = True
    verified: bool = False
    country: str = ""
    note: str = ""
    max_items: int | None = None
    follow_links: bool = False      # portals only: fetch linked detail pages
    link_pattern: str = ""
    tags: list[str] = field(default_factory=list)


def load_sources(path: str | Path) -> list[Source]:
    """Read the registry. A missing file yields an empty list, not a crash."""
    file = Path(path)
    if not file.exists():
        return []
    data = tomllib.loads(file.read_text(encoding="utf-8"))
    out: list[Source] = []
    for kind in ("feed", "portal"):
        for entry in data.get(kind, []) or []:
            if not entry.get("url") or not entry.get("name"):
                continue
            out.append(
                Source(
                    name=str(entry["name"]),
                    kind=kind,
                    url=str(entry["url"]),
                    enabled=bool(entry.get("enabled", True)),
                    verified=bool(entry.get("verified", False)),
                    country=str(entry.get("country", "")),
                    note=str(entry.get("note", "")),
                    max_items=entry.get("max_items"),
                    follow_links=bool(entry.get("follow_links", False)),
                    link_pattern=str(entry.get("link_pattern", "")),
                    tags=[str(t) for t in entry.get("tags", []) or []],
                )
            )
    return out


DEFAULT_SOURCES_TOML = "config/sources.toml"
