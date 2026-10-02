"""Feed autodiscovery.

Given any page, find the feeds it advertises via `<link rel="alternate">`, plus
a few conventional paths. Turns "I need to find this university's RSS URL" from
a browsing task into one command, which is what makes a config-driven source
registry maintainable rather than aspirational.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin

__all__ = ["DiscoveredFeed", "discover_in_html", "CONVENTIONAL_PATHS"]

_FEED_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
    "application/json",  # JSON Feed
}

CONVENTIONAL_PATHS = (
    "/feed", "/feed/", "/rss", "/rss.xml", "/atom.xml", "/index.xml",
    "/jobs/feed", "/jobs/rss", "/vacancies/rss", "/rss/rss.aspx",
)


@dataclass(slots=True)
class DiscoveredFeed:
    url: str
    title: str = ""
    mime: str = ""
    method: str = "autodiscovery"


class _LinkFinder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[DiscoveredFeed] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ("link", "a"):
            return
        attributes = {k.lower(): (v or "") for k, v in attrs}
        rel = attributes.get("rel", "").lower()
        mime = attributes.get("type", "").lower()
        href = attributes.get("href", "")
        if not href:
            return
        if tag == "link" and "alternate" in rel and mime in _FEED_TYPES:
            self.found.append(
                DiscoveredFeed(url=href, title=attributes.get("title", ""), mime=mime)
            )
        elif tag == "a" and re.search(r"(rss|atom|feed)", href, re.IGNORECASE):
            self.found.append(DiscoveredFeed(url=href, title="", mime="", method="anchor"))


def discover_in_html(html: str, base_url: str) -> list[DiscoveredFeed]:
    """Feeds advertised by a page, absolutised and de-duplicated."""
    parser = _LinkFinder()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:  # pragma: no cover - HTMLParser is tolerant
        return []
    seen: set[str] = set()
    out: list[DiscoveredFeed] = []
    for item in parser.found:
        absolute = urljoin(base_url, item.url)
        if absolute in seen:
            continue
        seen.add(absolute)
        out.append(DiscoveredFeed(absolute, item.title, item.mime, item.method))
    # Declared feeds first: an <a href> guess is far weaker evidence.
    out.sort(key=lambda f: 0 if f.method == "autodiscovery" else 1)
    return out
