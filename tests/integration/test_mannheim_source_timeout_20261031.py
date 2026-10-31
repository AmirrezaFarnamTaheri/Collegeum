"""Known slow departmental providers must not monopolize a pipeline worker."""
from __future__ import annotations

from pathlib import Path

from predoc_pipeline.boards.config import load_board_sources


def test_mannheim_economics_request_has_bounded_source_timeout():
    root = Path(__file__).resolve().parents[2]
    sources = load_board_sources(root / "config/sources.toml")
    mannheim = next(source for source in sources if source.name == "mannheim_econ")
    assert not mannheim.enabled  # The runner proved robots denial, not healthy emptiness.
    assert "robots.txt" in str(mannheim.opt("note"))
    assert mannheim.type == "link_scan"
    assert mannheim.source_timeout_seconds is not None
    assert 0 < mannheim.source_timeout_seconds <= 50
    assert mannheim.may_be_empty is True
