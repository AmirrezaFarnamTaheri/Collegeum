"""Importing this package registers every scraper type in ``SCRAPERS``."""

from . import (  # noqa: F401
    bite_jobs,
    dzne_sitemap,
    emply_embedded,
    eth_softfactors,
    link_scan,
    linkedin_scraper,
    predoc_org,
    rss,
    text_table,
    university_ats,
)
from .base import SCRAPERS, BaseScraper, SourceSkipped

__all__ = ["SCRAPERS", "BaseScraper", "SourceSkipped"]
