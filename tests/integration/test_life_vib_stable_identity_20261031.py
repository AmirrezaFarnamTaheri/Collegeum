"""VIB Jobsoid URL migrations must not republish an existing doctoral vacancy."""

from __future__ import annotations

from predoc_pipeline.boards.config import HttpConfig
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.ingest import life_sciences
from predoc_pipeline.ingest.career import load_career, save_career


LEGACY = "https://jobs.vib.be/j/138253/phd-position-in-neuroimmunology"
CURRENT = (
    "https://jobs.vib.be/PortalJob/IntegratedJobDetails?"
    "dept=0&div=0&fun=0&group=3&id=138253&loc=0"
    "&slug=phd-position-in-neuroimmunology&source=website"
)
REORDERED = (
    "https://jobs.vib.be/PortalJob/IntegratedJobDetails?"
    "source=website&id=138253&slug=phd-position-in-neuroimmunology"
)


def _post(url: str) -> JobPostSchema:
    return JobPostSchema(
        source="life_vib", url=url, title="PhD Position in Neuroimmunology",
        institution="VIB", country="Belgium",
        description_snippet="Molecular neurobiology and neuroimmunology research",
    )


def _poll(tmp_path, monkeypatch, url: str):
    config = tmp_path / "life_sciences.toml"
    config.write_text(
        '[[board]]\nname="life_vib"\ntype="link_scan"\n'
        'url="https://jobs.vib.be/jobs"\nlink_pattern="jobs.vib.be"\n',
        encoding="utf-8",
    )

    async def discovered(_cfg, _http, *, selected_names):
        assert selected_names == {"life_vib"}
        return [_post(url)], []

    monkeypatch.setattr(life_sciences, "select_sources", lambda *_args: {"life_vib"})
    monkeypatch.setattr(life_sciences, "discover", discovered)
    return life_sciences.poll_life_sciences(
        tmp_path / "career.ndjson",
        sources_path=config, http_config=HttpConfig(),
    )


def test_new_vib_link_retains_legacy_identity_and_does_not_realert(
    tmp_path, monkeypatch,
):
    initial = life_sciences.classify_post(_post(LEGACY))
    assert initial is not None
    assert save_career(tmp_path / "career.ndjson", [], [initial]) == 1
    before = load_career(tmp_path / "career.ndjson")[0]
    old_key, old_first_seen = before["key"], before["first_seen_at"]

    added, errors = _poll(tmp_path, monkeypatch, CURRENT)
    after = load_career(tmp_path / "career.ndjson")
    assert errors == []
    assert added == 0
    assert len(after) == 1
    assert after[0]["key"] == old_key
    assert after[0]["url"] == CURRENT
    assert after[0]["first_seen_at"] == old_first_seen


def test_vib_query_parameter_order_does_not_create_new_alert(
    tmp_path, monkeypatch,
):
    assert _poll(tmp_path, monkeypatch, CURRENT)[0] == 1
    saved = load_career(tmp_path / "career.ndjson")[0]
    assert _poll(tmp_path, monkeypatch, REORDERED)[0] == 0
    updated = load_career(tmp_path / "career.ndjson")
    assert len(updated) == 1
    assert updated[0]["key"] == saved["key"]


def test_distinct_vib_job_ids_remain_distinct_positions(tmp_path, monkeypatch):
    assert _poll(tmp_path, monkeypatch, CURRENT)[0] == 1
    other = CURRENT.replace("id=138253", "id=138254")
    assert _poll(tmp_path, monkeypatch, other)[0] == 1
    rows = load_career(tmp_path / "career.ndjson")
    assert len(rows) == 2
    assert len({row["key"] for row in rows}) == 2
