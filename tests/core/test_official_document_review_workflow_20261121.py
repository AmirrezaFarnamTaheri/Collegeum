"""Document review must remain manually initiated, read-only and non-publishing."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/official-document-review.yml"


def test_document_review_workflow_is_explicit_and_never_scheduled():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in content
    assert "schedule:" not in content
    assert "workflow_run:" not in content
    assert "  push:" not in content
    assert "pull_request:" not in content
    assert "github.ref == 'refs/heads/main'" in content
    assert "contents: read" in content
    assert "contents: write" not in content


def test_document_review_requires_exact_approved_url_and_robots():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "--source-id" in content and "--url" in content
    assert "--fetch" in content and "--record" in content
    assert "uv run --locked" in content
    assert 'pdf|docx' in content
    assert 'tools.official_call_' in content
    assert "actions/upload-artifact@" in content


def test_document_review_workflow_cannot_publish_or_mutate_main():
    content = WORKFLOW.read_text(encoding="utf-8").lower()
    assert "telegram" not in content
    assert "git push" not in content
    assert "git commit" not in content
    assert "repository_dispatch" not in content
    assert "workflow_dispatch --" not in content
    assert "bot_token" not in content
    assert "api_secret" not in content
