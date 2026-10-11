"""Regional Life Sciences source catalogue contracts and real listing-link shapes.

The adapters are tested without remote HTTP requests. An enabled source is
a verified listing/link-shape candidate, not a guarantee of future availability.
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from predoc_pipeline.boards.config import HttpConfig, load_board_sources
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper
from predoc_pipeline.boards.utils.text import canonical_url
from predoc_pipeline.ingest import life_sciences
from predoc_pipeline.ingest.rotation import save_rotation

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "config/life_sciences.toml"

REGIONAL_EXAMPLES = [
    (
        "life_benelux_ghent",
        "https://www.ugent.be/en/work/scientific/doctoral-fellow-129",
        "Doctoral fellow",
    ),
    (
        "life_es_irb",
        "https://www.irbbarcelona.org/en/careers/young-scientists/"
        "irb-barcelona-international-phd-fellowships-extraordinary-call-2026",
        "IRB Barcelona International PhD Fellowships - Extraordinary call 2026",
    ),
    (
        "life_lund_university",
        "https://lu.varbi.com/en/what:job/jobID:965334/type:job/where:4/apply:1",
        "PhD student in chromatin remodeling",
    ),
    (
        "life_umea_university",
        "https://www.umu.se/en/work-with-us/open-positions/"
        "doctoral-phd-position-in-medical-science_931992/",
        "Doctoral PhD Position in Medical Science and Genomics",
    ),
    (
        "life_gothenburg_university",
        "https://web103.reachmee.com/ext/I005/1035/main"
        "?lang=UK&rmjob=40969&rmpage=job&site=7",
        "Doctoral student in Neuroscience",
    ),
    (
        "life_aalto_university",
        "https://www.aalto.fi/en/open-positions/"
        "doctoral-researcher-in-numerical-modeling-of-sea-ice",
        "Doctoral researcher in Computational Biology",
    ),
    (
        "life_basel_university",
        "https://jobs.unibas.ch/offene-stellen/"
        "phd-position-tcr-discovery-and-cellular-immunotherapy/"
        "8fde752e-fb44-44e6-a5e2-5db423d521eb",
        "PhD Position in Epigenetics",
    ),
    (
        "life_basel_biozentrum",
        "https://www.biozentrum.unibas.ch/open-positions/detail/"
        "phd-student-antibiotic-biosensor-protein-engineering",
        "PhD student in RNA Biology",
    ),
    (
        "life_utrecht_university",
        "https://www.uu.nl/en/organisation/working-at-utrecht-university/jobs/"
        "phd-position-on-predictive-plant-microbiome-pathogen-interactions",
        "PhD position in Functional Genomics",
    ),
    (
        "life_radboud_university",
        "https://www.ru.nl/en/working-at/job-opportunities/"
        "phd-position-curiosity-in-the-classroom",
        "PhD Student in Neurodevelopment",
    ),
    (
        "life_inria",
        "https://recrutement.inria.fr/public/classic/en/offres/2026-10352",
        "PhD student in Computational Biology",
    ),
    (
        "life_ibec_barcelona",
        "https://ibecbarcelona.eu/predoctoral-researcher-at-the-"
        "protein-phase-transitions-in-health-and-disease-research-group/",
        "Predoctoral researcher in Epigenetics",
    ),
]


def test_regional_catalogue_loads_with_distinct_stable_ids() -> None:
    regional = ROOT / "config/life_sciences_sources"
    assert {p.name for p in regional.glob("*.toml")} == {
        "nordics.toml", "dach.toml", "benelux.toml",
        "france_iberia.toml", "central_south.toml",
    }
    base = load_board_sources(CATALOG)
    assert len(base) == 20
    registered = life_sciences.load_life_sources(CATALOG)
    names = [source.name for source in registered]
    assert len(names) == len(set(names))
    assert len(registered) == 112
    active = [source for source in registered if source.enabled]
    assert len(active) == 22
    assert len(registered) - len(active) == 90
    assert len(active) <= life_sciences.MAX_REGISTERED
    assert len(registered) <= life_sciences.MAX_CATALOG
    assert all(source.type in {"rss", "link_scan"} for source in active)
    assert all(source.country != "United Kingdom" for source in active)
    for source in registered:
        assert source.name.startswith("life_")
        if source.name in {name for name, _, _ in REGIONAL_EXAMPLES}:
            assert source.enabled
            assert source.opt("verification") == "listing_and_vacancy_url"
        if source.opt("verification") == "candidate_unverified":
            assert not source.enabled
            assert source.opt("link_pattern") == "^$"


class StubHttp:
    def set_host_interval(self, _url: str, _interval: float) -> None:
        return None


@pytest.mark.parametrize(("name", "url", "title"), REGIONAL_EXAMPLES)
def test_regional_vacancy_patterns_match_real_page_link_shapes(
    name: str, url: str, title: str,
) -> None:
    registry = {s.name: s for s in life_sciences.load_life_sources(CATALOG)}
    source = registry[name]
    pattern = re.compile(source.opt("link_pattern"), re.I)
    assert pattern.search(url)
    scraper = LinkScanScraper(source, StubHttp())
    if name == "life_benelux_ghent":
        html = (
            "<table><tr><td>"
            f"<a href='{url}'>{title}</a></td>"
            "<td>Department of Biochemistry and Microbiology</td></tr></table>"
        )
    elif name == "life_ibec_barcelona":
        # IBEC's clickable code is not the actual role title.
        html = (
            f"<article class='job-card'><h3>{title}</h3>"
            f"<a href='{url}'>PhD-BM_2026/Deadline</a></article>"
        )
    else:
        html = f"<article class='job-card'><a href='{url}'>{title}</a></article>"
    posts = scraper.parse_postings([(scraper.urls()[0], html)])
    assert len(posts) == 1, name
    assert posts[0].url == canonical_url(url), name
    assert posts[0].country == source.country, name
    assert posts[0].title == title, name
    assert life_sciences._doctoral_title(posts[0].title), name
    if name == "life_benelux_ghent":
        assert "Biochemistry" in posts[0].description_snippet
        assert life_sciences.classify_post(posts[0]) is not None


@pytest.mark.parametrize("title", [
    "Predoctoral Researcher in Molecular Biology",
    "Pre-doctoral Fellow in Epigenetics",
    "Doctorando en Genómica",
    "Dottorando in Neuroscienze",
    "Doktorgradsstipendiat i Genomics",
    "Väitöskirjatutkija in Epigenetics",
    "Offre de thèse en Chromatin Biology",
    "Promotionsstelle in Genomics",
])
def test_multilingual_doctoral_titles_are_recognized(title: str) -> None:
    assert life_sciences._doctoral_title(title)
    row = JobPostSchema(
        title=title,
        url="https://example.org/jobs/123",
        source="life_umea_university",
        institution="Institute",
        country="Sweden",
        description_snippet="chromatin epigenetics gene regulation",
    )
    assert life_sciences.classify_post(row) is not None


def test_duplicate_provider_name_across_catalogues_is_rejected(tmp_path: Path) -> None:
    original = tmp_path / "life_sciences.toml"
    directory = tmp_path / "life_sciences_sources"
    directory.mkdir()
    original.write_text(
        '[[board]]\nname = "life_same"\ntype = "link_scan"\n'
        'url = "https://example.org/jobs"\nlink_pattern = "example.org"\n',
        encoding="utf-8",
    )
    (directory / "regional.toml").write_text(
        original.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Duplicate Life Sciences source"):
        life_sciences.load_life_sources(original)


def test_source_round_robin_with_twenty_enabled_providers(tmp_path: Path) -> None:
    journal = tmp_path / "life_rotation.json"
    enabled = {s.name for s in life_sciences.load_life_sources(CATALOG) if s.enabled}
    assert len(enabled) == 22
    seen: set[str] = set()
    for iteration in range(3):
        selected = life_sciences.select_sources(CATALOG, journal)
        assert len(selected) == 8
        if iteration <= 1:
            assert not (selected & seen)
        else:
            assert len(selected - seen) == 6
        seen.update(selected)
        save_rotation(
            journal, selected, timestamp=datetime.now(UTC) + timedelta(minutes=iteration),
        )
    assert seen == enabled
    assert all(
        name not in enabled
        for name in (
            "life_benelux_ku_leuven", "life_nordic_stockholm",
            "life_dach_mdc_jobs", "life_fr_cnrs",
        )
    )


def test_doctoral_posts_are_prioritized_when_a_board_has_many_staff_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    board = tmp_path / "feed.toml"
    board.write_text(
        '[[board]]\nname="life_test"\ntype="link_scan"\n'
        'url="https://example.org/jobs"\nlink_pattern="example.org"\n',
        encoding="utf-8",
    )

    class HttpContext:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class Scraper:
        discovery_fetch_errors: list[str] = []
        discovery_parse_errors: list[str] = []
        discovery_limits: list[str] = []

        def __init__(self, config, _http):
            self.name = config.name

        async def run(self):
            rows = [
                JobPostSchema(
                    title=f"Administrative and staff coordinator {i}",
                    url=f"https://example.org/staff/{i}",
                    source=self.name, country="Sweden",
                )
                for i in range(200)
            ]
            rows.extend(
                JobPostSchema(
                    title=f"PhD position {i} in Epigenetics",
                    url=f"https://example.org/phd/{i}",
                    source=self.name, country="Sweden",
                )
                for i in range(2)
            )
            return rows, len(rows)

        async def fetch_detail(self, _post):
            raise AssertionError("Should not fetch complete doctoral roles")

    monkeypatch.setattr(life_sciences, "build_http", lambda _prefs: HttpContext())
    monkeypatch.setattr(life_sciences, "SCRAPERS", {"link_scan": Scraper})
    jobs, errors = asyncio.run(life_sciences.discover(board, HttpConfig()))
    assert not errors
    assert len(jobs) == 60
    counts = Counter(life_sciences._doctoral_title(row.title) for row in jobs)
    assert counts[True] == 2
    assert counts[False] == 58



def test_aggregator_searches_cover_primary_and_related_biological_fields() -> None:
    all_sources = {
        s.name: s for s in life_sciences.load_life_sources(CATALOG)
    }
    euraxess = all_sources["life_euraxess"].opt("urls")
    dutch = all_sources["life_academictransfer"].opt("urls")
    assert len(euraxess) == 19
    assert len(dutch) == 15
    assert len(euraxess) == len(set(euraxess))
    assert len(dutch) == len(set(dutch))
    assert all("euraxess.ec.europa.eu/jobs/search?" in url for url in euraxess)
    assert all("academictransfer.com/en/jobs/" in url for url in dutch)
    for topic in ("epigenetics", "chromatin", "genomics", "neurodevelopment"):
        assert any(topic in url for url in [*euraxess, *dutch])
    for topic in ("RNA%20biology", "psychiatric%20genetics", "transcriptomics"):
        assert any(topic in url for url in [*euraxess, *dutch])
