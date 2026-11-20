"""GitHub Pages artifact metadata can lag the completed artifact upload."""
from pathlib import Path


def test_pages_deploy_retries_a_failed_metadata_lookup_once_after_delay():
    workflow = Path(".github/workflows/pages.yml").read_text(encoding="utf-8")
    assert "id: deployment" in workflow
    assert "continue-on-error: true" in workflow
    assert "steps.deployment.outcome == 'failure'" in workflow
    assert "sleep 20" in workflow
    assert "id: deployment_retry" in workflow
    assert workflow.count("uses: actions/deploy-pages@v5") == 2


def test_pages_retry_preserves_successful_deployment_url_and_security_guards():
    workflow = Path(".github/workflows/pages.yml").read_text(encoding="utf-8")
    assert "steps.deployment_retry.outputs.page_url" in workflow
    assert "steps.deployment.outputs.page_url" in workflow
    assert "vars.ENABLE_PAGES == 'true'" in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
    assert "contents: read" in workflow
    assert "pages: write" in workflow
    assert "id-token: write" in workflow
