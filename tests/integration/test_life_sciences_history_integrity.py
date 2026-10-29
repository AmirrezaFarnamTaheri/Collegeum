"""Prevent one provably off-field historical PhD from leaking into exports and alerts.

Keep the raw journal intact, and preserve ambiguous records for manual review.
"""
import json
from datetime import UTC, datetime
from pathlib import Path

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.publish.subscriptions import matching
from tools.export_life_sciences import stored_positions

CLIMATE = "PhD Researcher (m/f/d): Economic Impacts from Complex Climate Risks"
BIOLOGY = "PhD Student in Molecular Biology and Economic Analysis of Biomanufacturing"
AMBIGUOUS = "Doctoral fellow"


def _rows():
    now = datetime.now(UTC).isoformat()
    return [
        {
            "key": f"career:historical-{i}", "category": "life_sciences_phd",
            "scope": "", "first_seen_at": now, "location": "Germany",
            "source": "life_max_planck", "funding_status": "unverified",
            "title": title, "url": f"https://example.org/jobs/{i}",
        }
        for i, title in enumerate((CLIMATE, BIOLOGY, AMBIGUOUS))
    ]


def test_stored_export_excludes_explicitly_off_field_phd_without_rewriting_journal(tmp_path):
    path = tmp_path / "career_jobs.ndjson"
    original = "".join(json.dumps(x) + "\n" for x in _rows())
    path.write_text(original, encoding="utf-8")
    included = stored_positions(path)
    assert {x["title"] for x in included} == {BIOLOGY, AMBIGUOUS}
    assert path.read_text(encoding="utf-8") == original


def test_private_life_sciences_preview_does_not_offer_known_off_field_history():
    member = {"topics": {"life_sciences_phd": "2026-10-29T00:00:00Z"}, "scopes": {}}
    included = matching(member, [], _rows(), preview=True)
    assert {x["title"] for x in included} == {BIOLOGY, AMBIGUOUS}


def test_robots_blocked_copenhagen_is_not_in_scheduled_life_sciences_rotation():
    sources = {
        x.name: x for x in load_board_sources(Path("config/life_sciences.toml"))
    }
    assert sources["life_copenhagen"].enabled is False
    assert sources["life_vienna_doctoral"].enabled is True
