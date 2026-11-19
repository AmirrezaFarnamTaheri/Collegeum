"""The official funding publisher must actually be enabled by the live workflow."""
from pathlib import Path


def test_production_workflow_injects_official_calls_activation_and_limit():
    workflow = Path(".github/workflows/pipeline.yml").read_text(encoding="utf-8")
    assert "TELEGRAM_OFFICIAL_CALLS_ENABLED:" in workflow
    assert "TELEGRAM_OFFICIAL_CALLS_MAX_PER_RUN:" in workflow
    assert "vars.TELEGRAM_OFFICIAL_CALLS_ENABLED || 'true'" in workflow
    assert "vars.TELEGRAM_OFFICIAL_CALLS_MAX_PER_RUN || '2'" in workflow


def test_official_calls_are_a_separately_enabled_public_delivery_path():
    workflow = Path(".github/workflows/pipeline.yml").read_text(encoding="utf-8")
    publisher = Path("src/predoc_pipeline/pipeline.py").read_text(encoding="utf-8")
    settings = Path("src/predoc_pipeline/settings.py").read_text(encoding="utf-8")
    assert "publish_official_calls(" in publisher
    assert "enabled=settings.telegram_official_calls_enabled" in publisher
    assert "telegram_official_calls_enabled: bool = False" in settings
    assert "data/official_phd_calls_telegram.json" in workflow
