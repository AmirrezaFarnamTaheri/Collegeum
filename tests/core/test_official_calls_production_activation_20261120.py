"""Live official PhD call delivery must not silently inherit the local opt-out."""
from pathlib import Path


def test_reviewed_main_ingestion_explicitly_enables_official_funding_calls():
    workflow = Path(".github/workflows/pipeline.yml").read_text(encoding="utf-8")
    # Missing an env key makes Settings silently default to False.
    assert "TELEGRAM_OFFICIAL_CALLS_ENABLED:" in workflow
    assert (
        "TELEGRAM_OFFICIAL_CALLS_ENABLED: "
        "${{ vars.TELEGRAM_OFFICIAL_CALLS_ENABLED || 'true' }}"
    ) in workflow
    assert (
        "TELEGRAM_OFFICIAL_CALLS_MAX_PER_RUN: "
        "${{ vars.TELEGRAM_OFFICIAL_CALLS_MAX_PER_RUN || '2' }}"
    ) in workflow
    assert "TELEGRAM_OFFICIAL_CALLS_ENABLED: ${{ secrets." not in workflow
    assert "data/official_phd_calls_telegram.json" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow


def test_local_default_remains_no_send_without_opt_in():
    settings = Path("src/predoc_pipeline/settings.py").read_text(encoding="utf-8")
    assert "telegram_official_calls_enabled: bool = False" in settings
    assert "telegram_official_calls_max_per_run: int = Field(2, ge=1, le=10)" in settings


def test_pipeline_uses_the_live_flag_and_independent_receipts():
    code = Path("src/predoc_pipeline/pipeline.py").read_text(encoding="utf-8")
    assert "publish_official_calls(" in code
    assert "enabled=settings.telegram_official_calls_enabled" in code
    assert "settings.official_calls_delivery_path" in code
