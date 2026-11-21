"""Banco de Espana's officially advertised zero-result state is not a fetch failure.

The bank's Spanish 'Convocatorias con plazo abierto' page explicitly
reports zero rows for an empty season; only that exact source-managed
statement may permit a verified-empty status. A missing notice, changed
layout or unexpected job link must remain degraded for operator review.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS


class Page:
    def __init__(self, html: str) -> None:
        self.html = html

    async def get_text(self, url: str) -> str:
        assert url == "https://www.bde.es/wbe/es/sobre-banco/trabajar-banco/convocatorias-plazo-abierto/"
        return self.html


def _collect(html: str):
    cfg = next(s for s in load_board_sources(Path("config/sources.toml"))
               if s.name == "bde_spain")
    result = asyncio.run(_scrape_all([SCRAPERS[cfg.type](cfg, Page(html))], 1, 5))[0]
    return cfg, result


def test_approved_official_zero_result_notice_is_verified_empty() -> None:
    cfg, result = _collect(
        '<h1>Convocatorias con plazo abierto</h1>'
        '<p>0 resultados encontrados para los filtros seleccionados.</p>'
    )
    assert cfg.may_be_empty is True
    assert cfg.opt("verified_empty_marker") == (
        "0 resultados encontrados para los filtros seleccionados"
    )
    assert result.ok, result.as_stats()
    assert result.posts == []


def test_missing_or_changed_empty_notice_does_not_hide_source_drift() -> None:
    for html in (
        '<h1>Convocatorias con plazo abierto</h1><p>1 resultado encontrado</p>',
        '<h1>Maintenance in progress</h1>',
        '<html><body>403 Forbidden</body></html>',
    ):
        _, result = _collect(html)
        assert not result.ok, result.as_stats()
        assert result.posts == []


def test_official_zero_result_notice_with_conflicting_job_link_fails_closed() -> None:
    # The zero-count line is not proof of emptiness if the page also exposes
    # a plausible new application link that the current parser cannot match.
    html = (
        '<h1>Convocatorias con plazo abierto</h1>'
        '<p>0 resultados encontrados para los filtros seleccionados.</p>'
        '<a href="/wbe/es/sobre-banco/trabajar-banco/trabajar-bde/'
        'convocatorias/personal-tecnico-economia.html">Puesto de trabajo</a>'
    )
    _, result = _collect(html)
    assert not result.ok, result.as_stats()
    # Keep the raw role for review while marking the contradictory page
    # partial; do not silently suppress job identities or label zero verified.
    assert result.posts
