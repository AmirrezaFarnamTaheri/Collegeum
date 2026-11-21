"""An official numerical zero-result notice cannot coexist with parsed roles.

Banco de Espana already has an explicitly approved verified-empty notice on
main. This regression only guards contradictions between that notice and
new vacancy candidates, without changing seasonal sources using a generic
evergreen careers footer.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS

URL = "https://www.bde.es/wbe/es/sobre-banco/trabajar-banco/convocatorias-plazo-abierto/"
ROLE_URL = (
    "https://www.bde.es/wbe/es/sobre-banco/trabajar-banco/"
    "trabajar-bde/convocatorias/personal-tecnico-economia.html"
)


class Page:
    def __init__(self, content: str) -> None:
        self.content = content

    async def get_text(self, url: str) -> str:
        assert url == URL
        return self.content


def collect(html: str):
    cfg = next(item for item in load_board_sources(Path("config/sources.toml"))
               if item.name == "bde_spain")
    result = asyncio.run(_scrape_all([SCRAPERS[cfg.type](cfg, Page(html))], 1, 5))[0]
    return cfg, result


def test_bde_zero_notice_with_real_role_is_partial_and_preserves_candidate() -> None:
    html = (
        "<h1>Convocatorias con plazo abierto</h1>"
        "<p>0 resultados encontrados para los filtros seleccionados.</p>"
        f'<a href="{ROLE_URL}">Puesto de trabajo de economia</a>'
    )
    cfg, result = collect(html)
    assert cfg.may_be_empty
    assert {item.url for item in result.posts} == {ROLE_URL}
    assert not result.ok, result.as_stats()


def test_bde_valid_live_role_without_zero_notice_remains_collectable() -> None:
    html = (
        "<h1>Convocatorias con plazo abierto</h1>"
        "<p>1 resultado encontrado para los filtros seleccionados.</p>"
        f'<a href="{ROLE_URL}">Puesto de trabajo de economia</a>'
    )
    _, result = collect(html)
    assert result.ok, result.as_stats()
    assert {item.url for item in result.posts} == {ROLE_URL}


def test_bde_official_empty_notice_without_roles_remains_accepted() -> None:
    html = (
        "<h1>Convocatorias con plazo abierto</h1>"
        "<p>0 resultados encontrados para los filtros seleccionados.</p>"
    )
    _, result = collect(html)
    assert result.ok, result.as_stats()
    assert result.posts == []
