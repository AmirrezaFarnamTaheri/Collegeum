"""Life-sciences PhD collection is separate from economics/public job rules."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from predoc_pipeline.boards.config import HttpConfig, load_board_sources
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.ingest import life_sciences
from predoc_pipeline.ingest.career import load_career, save_career
from predoc_pipeline.publish.feedback import FeedbackStore, generate_key
from predoc_pipeline.publish.private_delivery import plan_batch
from predoc_pipeline.publish.subscriptions import matching, render_alert
from predoc_pipeline.settings import Settings

TODAY = date(2026, 10, 11)


def post(
    *, title: str = "PhD position in Epigenetics",
    field: str = "", country: str | None = "Netherlands",
    location: str | None = "Utrecht", description: str = "",
    deadline: date | None = None, date_posted: date | None = None,
) -> JobPostSchema:
    return JobPostSchema(
        title=title, url="https://www.academictransfer.com/en/12345/phd-epigenetics/",
        source="life_academictransfer", country=country, location=location,
        institution="Utrecht University", fields_of_research=field,
        description_snippet=description, deadline=deadline, date_posted=date_posted,
    )


@pytest.mark.parametrize("title", [
    "PhD position in Epigenetics",
    "Doctoral Researcher in Chromatin Remodeling",
    "Doctorant in Epigenetics and Gene Regulation",
    "Doktorand in Functional Genomics",
    "PhD Scholarship in Molecular Biology",
    "PhD candidate in Psychiatric Genetics",
    "Doctoral Student in RNA Biology",
])
def test_genuine_doctoral_life_sciences_roles_match(title: str) -> None:
    result = life_sciences.classify_post(post(title=title), today=TODAY)
    assert result is not None
    assert result["category"] == "life_sciences_phd"
    assert result["scope"] == ""
    assert result["funding_status"] == "unverified"


@pytest.mark.parametrize("title", [
    "Postdoctoral Fellow in Epigenetics",
    "Research Associate (PhD required) in Epigenetics",
    "PhD position in Economics",
    "Master of Science in Molecular Biology",
    "Professor in Chromatin Biology",
])
def test_unrelated_or_ineligible_positions_are_excluded(title: str) -> None:
    assert life_sciences.classify_post(post(title=title), today=TODAY) is None


@pytest.mark.parametrize("title", [
    "PhD position in Experimental Physics with a focus on photonics",
    "PhD students in Statistics",
    "PhD Position: Curiosity in the Classroom",
])
def test_unrelated_phd_titles_are_not_rescued_by_university_boilerplate(
    title: str,
) -> None:
    unrelated = post(title=title, description=(
        "The university is known for CRISPR-Cas9 and world-leading research."
    ))
    assert life_sciences.classify_post(unrelated, today=TODAY) is None


@pytest.mark.parametrize("country,location", [
    ("United Kingdom", "London"),
    ("United States", "Cambridge, MA"),
    ("Canada", "Toronto"),
    ("Japan", "Tokyo"),
    ("Europe", "Remote"),
    (None, None),
])
def test_explicit_european_geography_is_required(
    country: str | None, location: str | None,
) -> None:
    assert life_sciences.classify_post(
        post(country=country, location=location), today=TODAY,
    ) is None


def test_posting_date_and_funding_restrictions() -> None:
    assert life_sciences.classify_post(
        post(deadline=date(2026, 10, 10)), today=TODAY,
    ) is None
    assert life_sciences.classify_post(
        post(date_posted=date(2026, 6, 1)), today=TODAY,
    ) is None
    assert life_sciences.classify_post(
        post(description="This is an explicitly self-funded PhD."),
        today=TODAY,
    ) is None
    top = life_sciences.classify_post(
        post(title="PhD Candidate in Epigenetic Regulation"), today=TODAY,
    )
    assert top is not None and top["research_priority"] == "focus"
    related = life_sciences.classify_post(
        post(title="PhD Student in Computational Biology"), today=TODAY,
    )
    assert related is not None and related["research_priority"] == "related"


def test_separate_life_sciences_source_registry_keeps_economics_sources() -> None:
    repo = Path(__file__).resolve().parents[2]
    new_sources = load_board_sources(repo / "config/life_sciences.toml")
    default_sources = load_board_sources(repo / "config/sources.toml")
    enabled = {row.name for row in new_sources if row.enabled}
    assert enabled == {
        "life_euraxess", "life_academictransfer", "life_max_planck",
        "life_uppsala", "life_karolinska",
        "life_vib", "life_epfl", "life_crg_phd", "life_dkfz",
        "life_vienna_doctoral",
    }
    assert {
        "life_embl", "life_eth_bsse", "life_eth_jobs",
        "life_fmi_programme", "life_embl_phd_programme",
        "life_vienna_biocenter", "life_helsinki", "life_ista", "life_mdc",
        "life_copenhagen",
    }.issubset({row.name for row in new_sources if not row.enabled})
    assert "euraxess" in {row.name for row in default_sources}
    assert "academictransfer" in {row.name for row in default_sources}


def test_poll_persists_life_phd_without_damaging_existing_economics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = tmp_path / "career.ndjson"
    economics = {
        "key": "career:econ", "category": "data_analyst", "scope": "remote",
        "title": "Data Analyst", "url": "https://jobicy.com/jobs/data-analyst",
        "employer": "Example", "location": "Anywhere", "source": "Jobicy",
    }
    save_career(journal, [], [economics])

    sources = tmp_path / "life_sources.toml"
    sources.write_text(
        '[[board]]\nname="life_example"\ntype="link_scan"\n'
        'url="https://example.org/jobs"\nlink_pattern="example.org"\n',
        encoding="utf-8",
    )

    async def fake_discover(
        _sources: object, _http: object, *, selected_names: set[str] | None = None,
    ):
        assert selected_names == {"life_example"}
        return [post(title="PhD Position in Gene Regulation")], []

    monkeypatch.setattr(life_sciences, "discover", fake_discover)
    count, errors = life_sciences.poll_life_sciences(
        journal, sources_path=sources, http_config=HttpConfig(),
    )
    assert count == 1 and errors == []
    records = load_career(journal)
    assert len(records) == 2
    assert {r["category"] for r in records} == {
        "data_analyst", "life_sciences_phd",
    }
    life = next(r for r in records if r["category"] == "life_sciences_phd")
    assert life["scope"] == ""
    first_seen = life["first_seen_at"]
    assert life_sciences.poll_life_sciences(
        journal, sources_path=sources, http_config=HttpConfig(),
    )[0] == 0
    assert next(r for r in load_career(journal) if r["category"] == "life_sciences_phd")[
        "first_seen_at"
    ] == first_seen


def test_private_delivery_reaches_life_sciences_subscriber_without_markets(
    tmp_path: Path,
) -> None:
    cfg = Settings(
        _env_file=None, telegram_bot_token="test",
        telegram_public_channel_id="", telegram_admin_chat_id="",
        feedback_encryption_key=generate_key(),
        feedback_path=str(tmp_path / "feedback.json"),
        telegram_state_path=str(tmp_path / "updates.json"),
        state_path=str(tmp_path / "journal.ndjson"),
        seen_state_path=str(tmp_path / "seen.ndjson"),
        db_path=str(tmp_path / "db.sqlite"),
        career_state_path=str(tmp_path / "career.ndjson"),
        dashboard_json=str(tmp_path / "docs/listings.json"),
        feed_path=str(tmp_path / "docs/feed.xml"),
    )
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "life_sciences_phd")
    store.subscriber(101)["topics"]["life_sciences_phd"] = (
        datetime.now(UTC) - timedelta(hours=1)
    ).isoformat()
    store.save()
    job = life_sciences.classify_post(post(), today=TODAY)
    assert job is not None
    save_career(cfg.career_state_path, [], [job])
    member = store.subscriber(101)
    assert member is not None and member["scopes"] == {}
    assert len(matching(member, [], load_career(cfg.career_state_path))) == 1
    formatted = render_alert(job)
    assert "Life Sciences PhD" in formatted
    assert "Funding, salary and tuition are not verified" in formatted
    batch = tmp_path / "batch.json"
    assert plan_batch(cfg, path=batch) == 1
    rows = json.loads(batch.read_text("utf-8"))
    assert rows[0]["chat_id"] == "101"
    assert rows[0]["key"].startswith("career:")
    assert "Life Sciences PhD" in rows[0]["text"]


def test_other_users_do_not_receive_life_sciences_phds() -> None:
    job = {
        **life_sciences.classify_post(post(), today=TODAY),
        "first_seen_at": datetime.now(UTC).isoformat(),
    }
    before = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    economics_member = {"topics": {"phd": before}, "scopes": {}}
    life_member = {"topics": {"life_sciences_phd": before}, "scopes": {}}
    assert matching(economics_member, [], [job]) == []
    assert len(matching(life_member, [], [job])) == 1


def test_international_research_brand_does_not_imply_location() -> None:
    from predoc_pipeline.boards.models import JobPostSchema

    baseline = {
        "title": "PhD Position in Epigenetics",
        "url": "https://www.mpg.de/jobs/example",
        "source": "life_max_planck",
        "institution": "Max Planck Society",
    }
    ambiguous = JobPostSchema(
        **baseline, description_snippet="Collaborators at the University of Berlin.",
    )
    assert life_sciences.classify_post(ambiguous, today=TODAY) is None
    verified = JobPostSchema(
        **baseline, description_snippet="Location: Munich, Germany",
    )
    match = life_sciences.classify_post(verified, today=TODAY)
    assert match is not None
    assert match["location"] == "Germany"
    outside = JobPostSchema(
        **baseline, description_snippet="Work location: Cambridge, UK",
    )
    assert life_sciences.classify_post(outside, today=TODAY) is None


def test_primary_research_interests_rank_before_related_on_same_discovery() -> None:
    stamp = datetime.now(UTC).isoformat()
    related = life_sciences.classify_post(
        post(title="PhD Student in Computational Biology"), today=TODAY,
    )
    focus = life_sciences.classify_post(
        post(title="PhD Position in Epigenetic Regulation"), today=TODAY,
    )
    assert related is not None and focus is not None
    related = {**related, "key": "career:related", "first_seen_at": stamp}
    focus = {**focus, "key": "career:focus", "first_seen_at": stamp}
    member = {
        "topics": {"life_sciences_phd": (
            datetime.now(UTC) - timedelta(hours=1)
        ).isoformat()},
        "scopes": {},
    }
    ranked = matching(member, [], [related, focus])
    assert [job["key"] for job in ranked] == ["career:focus", "career:related"]



def test_vib_recruitment_calls_are_real_phd_roles_not_generic_programme_pages() -> None:
    call = post(
        title="2026-2027 International PhD Call VIB CNL",
        country="Belgium", location="Leuven",
        description="VIB-KU Leuven Center for Neuroscience",
        deadline=TODAY + timedelta(days=30),
    )
    match = life_sciences.classify_post(call, today=TODAY)
    assert match is not None
    assert match["research_priority"] == "related"
    call.deadline = None
    assert life_sciences.classify_post(call, today=TODAY) is None
    assert life_sciences.classify_post(
        post(title="PhD Programme", country="Belgium"), today=TODAY,
    ) is None


def test_new_official_portal_patterns_parse_actual_vacancy_url_shapes() -> None:
    from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper
    from predoc_pipeline.boards.utils.text import canonical_url

    sources = {
        item.name: item for item in load_board_sources(
            Path(__file__).resolve().parents[2] / "config/life_sciences.toml",
        )
    }
    samples = [
        ("life_uppsala",
         "https://www.uu.se/en/about-uu/join-us/jobs-and-vacancies/job-details"
         "?query=967249",
         "PhD-student in Evolutionary and Ecological Genetics"),
        ("life_karolinska",
         "https://kidoktorand.varbi.com/en/what:job/jobID:972393/type:job"
         "/where:4/apply:1",
         "Doctoral (PhD) student position in Epigenetics and Neuroimmunology"),
        ("life_copenhagen",
         "https://employment.ku.dk/phd/?show=169826",
         "PhD fellowship in stem cell immunoavoidance"),
        ("life_vib",
         "https://jobs.vib.be/j/137653/2026-2027-international-phd-call-vib-cnl",
         "2026-2027 International PhD Call VIB CNL"),
        ("life_epfl",
         "https://careers.epfl.ch/job/Lausanne-PhD-position/1165576555/",
         "PhD Student Position in Epigenomics"),
        ("life_crg_phd",
         "https://www.crg.eu/en/content/training-phd-students/"
         "crg-international-phd-fellowships-programme-2027",
         "CRG International PhD Call 2027"),
        ("life_vienna_doctoral",
         "https://jobs.univie.ac.at/job/Vienna-Doctoral-School-in-Cognition%2C-"
         "Behavior%2C-and-Neuroscience-Doctoral-Positions-%28AUTUMN-CALL-20/"
         "1431139533/",
         "Vienna Doctoral School in Cognition, Behavior, and Neuroscience "
         "- Doctoral Positions (AUTUMN CALL 2026)"),
    ]

    class StubHttp:
        def set_host_interval(self, _url: str, _interval: float) -> None:
            return None

    for name, url, title in samples:
        scraper = LinkScanScraper(sources[name], StubHttp())
        html = f"<li class='job-card'><a href='{url}'>{title}</a></li>"
        jobs = scraper.parse_postings([(scraper.urls()[0], html)])
        assert len(jobs) == 1, name
        assert jobs[0].url == canonical_url(url), name
        assert jobs[0].country == sources[name].country, name


def test_rotated_source_budget_covers_nineteen_feeds_in_three_runs(
    tmp_path: Path,
) -> None:
    from predoc_pipeline.ingest.rotation import save_rotation

    source_path = tmp_path / "expanded.toml"
    source_path.write_text(
        "".join(
            '[[board]]\n'
            f'name = "life_source_{index:02d}"\n'
            'type = "link_scan"\n'
            'url = "https://example.org/jobs"\n'
            'link_pattern = "example.org"\n'
            'enabled = true\n'
            for index in range(19)
        ), encoding="utf-8",
    )
    checkpoint = tmp_path / "life-rotation.json"
    all_sources = {f"life_source_{i:02d}" for i in range(19)}
    total: set[str] = set()
    for _ in range(3):
        remaining = all_sources - total
        selected = life_sciences.select_sources(source_path, checkpoint)
        assert len(selected) == life_sciences.MAX_SOURCES
        # Sources not yet checked come before prior visits. During the last
        # round, the remaining three share slots with five returning feeds.
        assert len(selected & remaining) == min(len(remaining), len(selected))
        total.update(selected)
        save_rotation(checkpoint, selected)
    assert total == all_sources


def test_detail_enrichment_is_reserved_for_incomplete_doctoral_cards() -> None:
    assert not life_sciences._needs_detail(
        post(title="PhD Position in Epigenetics")
    )
    assert life_sciences._needs_detail(
        post(title="PhD fellowship", description="")
    )
    assert life_sciences._needs_detail(
        post(
            title="2026-2027 International PhD Call VIB CNL",
            description="VIB Centre for Neuroscience",
            country="Belgium",
        )
    )
    assert life_sciences._needs_detail(
        post(title="PhD Position in Gene Regulation", country=None, location=None)
    )
    assert not life_sciences._needs_detail(post(title="Professor in Genomics"))


def test_detail_fetch_adds_missing_research_evidence_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    board = tmp_path / "one.toml"
    board.write_text(
        '[[board]]\nname="vib"\ntype="link_scan"\n'
        'url="https://example.org/jobs"\nlink_pattern="example.org"\n',
        encoding="utf-8",
    )

    class HttpContext:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class FakeScraper:
        discovery_fetch_errors: list[str] = []
        discovery_parse_errors: list[str] = []
        discovery_limits: list[str] = []

        def __init__(self, _config, _http):
            pass

        async def run(self):
            return [post(
                title="2026-2027 International PhD Call VIB CNL",
                country="Belgium", location="Leuven",
                description="International call to doctoral students",
            )], 1

        async def fetch_detail(self, _post):
            return ("Neurodevelopmental disorders, single-cell genomics, "
                    "chromatin architecture; Application deadline: 30 October 2026")

    monkeypatch.setattr(life_sciences, "build_http", lambda _cfg: HttpContext())
    monkeypatch.setattr(life_sciences, "SCRAPERS", {"link_scan": FakeScraper})
    jobs, errors = asyncio.run(
        life_sciences.discover(board, HttpConfig())
    )
    assert errors == []
    assert len(jobs) == 1
    assert "chromatin architecture" in jobs[0].description_snippet
    assert life_sciences.classify_post(jobs[0], today=TODAY) is not None


def test_discovery_errors_preserve_safe_cause_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from predoc_pipeline.boards.scrapers.base import DiscoveryFetchError

    board = tmp_path / "source.toml"
    board.write_text(
        '[[board]]\nname="life_aalto_university"\n'
        'type="link_scan"\nurl="https://example.org/jobs"\n'
        'link_pattern="example.org"\n', encoding="utf-8",
    )

    class HttpContext:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class FailingScraper:
        discovery_fetch_errors: list[str] = []
        discovery_parse_errors: list[str] = []
        discovery_limits: list[str] = []

        def __init__(self, _config, _http):
            pass

        async def run(self):
            raise DiscoveryFetchError(
                "https://example.org/jobs?api_key=secret: ConnectTimeout: timed out"
            )

    monkeypatch.setattr(life_sciences, "build_http", lambda _cfg: HttpContext())
    monkeypatch.setattr(life_sciences, "SCRAPERS", {"link_scan": FailingScraper})
    _, errors = asyncio.run(life_sciences.discover(board, HttpConfig()))

    assert len(errors) == 1
    assert "life_aalto_university: DiscoveryFetchError" in errors[0]
    assert "ConnectTimeout" in errors[0]
    assert "api_key" not in errors[0]
    assert "secret" not in errors[0]


def test_high_volume_sources_cannot_monopolize_discovery_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from collections import Counter

    board = tmp_path / "eight.toml"
    board.write_text(
        "".join(
            '[[board]]\n'
            f'name = "source_{i}"\n'
            'type = "link_scan"\n'
            'url = "https://example.org/jobs"\n'
            'link_pattern = "example.org"\n'
            for i in range(8)
        ), encoding="utf-8",
    )

    class HttpContext:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class FakeScraper:
        discovery_fetch_errors: list[str] = []
        discovery_parse_errors: list[str] = []
        discovery_limits: list[str] = []

        def __init__(self, config, _http):
            self.name = config.name

        async def run(self):
            return [
                JobPostSchema(
                    title="PhD Position in Epigenetics",
                    url=f"https://example.org/jobs/{self.name}-{j}",
                    source=self.name, country="Netherlands",
                ) for j in range(60)
            ], 60

        async def fetch_detail(self, _post):
            raise AssertionError("Complete listings must not fetch details")

    monkeypatch.setattr(life_sciences, "build_http", lambda _cfg: HttpContext())
    monkeypatch.setattr(life_sciences, "SCRAPERS", {"link_scan": FakeScraper})
    jobs, errors = asyncio.run(life_sciences.discover(board, HttpConfig()))
    assert errors == []
    assert len(jobs) == life_sciences.MAX_TOTAL
    assert set(Counter(job.source for job in jobs).values()) == {25}



def test_programme_and_university_autumn_calls_require_deadline_detail() -> None:
    """Doctoral calls with a field-labelled title still need closing date proof."""
    crg = post(
        title="CRG International PhD Call 2027", country="Spain",
        location="Barcelona",
        description="CRG PhD fellowship in gene regulation and chromatin",
    )
    vienna = post(
        title="Vienna Doctoral School in Cognition, Behavior, and Neuroscience "
        "- Doctoral Positions (AUTUMN CALL 2026)",
        country="Austria", location="Vienna",
    )
    assert life_sciences._needs_detail(crg)
    assert life_sciences._needs_detail(vienna)
    assert life_sciences.classify_post(vienna, today=TODAY) is None
    crg.deadline = date(2026, 11, 22)
    assert life_sciences.classify_post(crg, today=TODAY) is not None
    assert life_sciences.classify_post(crg, today=date(2026, 11, 23)) is None


def test_large_direct_poll_uses_bounded_selection_even_without_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = tmp_path / "sources.toml"
    sources.write_text(
        "".join(
            '[[board]]\n'
            f'name = "life_direct_{i:02d}"\n'
            'type = "link_scan"\n'
            'url = "https://example.org/jobs"\n'
            'link_pattern = "example.org"\n'
            for i in range(life_sciences.MAX_SOURCES + 5)
        ), encoding="utf-8",
    )
    selected: list[set[str]] = []

    async def fake_discover(
        _path: object, _http: object, *, selected_names: set[str] | None = None,
    ):
        assert selected_names is not None
        selected.append(selected_names)
        return [], []

    monkeypatch.setattr(life_sciences, "discover", fake_discover)
    result = life_sciences.poll_life_sciences(
        tmp_path / "jobs.ndjson", sources_path=sources, http_config=HttpConfig(),
    )
    assert result == (0, [])
    assert len(selected) == 1
    assert len(selected[0]) == life_sciences.MAX_SOURCES
    assert not (tmp_path / "life_rotation.json").exists()
