"""Cross-repository private state checks with real local Git repositories."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.private_state import checkpoint, restore


def _git(*args: str) -> None:
    subprocess.run(
        ["git", *args], check=True, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_private_state_refuses_missing_migration(tmp_path: Path) -> None:
    root = tmp_path / "public"
    private = tmp_path / "private"
    (root / "data").mkdir(parents=True)
    private.mkdir()
    (root / "data/feedback.enc").write_bytes(b"encrypted-old")
    with pytest.raises(RuntimeError, match="migrate existing data"):
        restore(private, root)
    assert (root / "data/feedback.enc").read_bytes() == b"encrypted-old"


def test_private_state_restore_prefers_authoritative_private_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "public"
    private = tmp_path / "private"
    (root / "data").mkdir(parents=True)
    (private / "data").mkdir(parents=True)
    (root / "data/feedback.enc").write_bytes(b"old-public-ciphertext")
    (private / "data/feedback.enc").write_bytes(b"new-private-ciphertext")
    (private / "data/telegram_state.json").write_text('{"offset":9}', encoding="utf-8")
    restore(private, root)
    assert (root / "data/feedback.enc").read_bytes() == b"new-private-ciphertext"
    assert (root / "data/telegram_state.json").read_text("utf-8") == '{"offset":9}'


def test_private_state_checkpoint_is_remote_only_and_idempotent(tmp_path: Path) -> None:
    bare = tmp_path / "bare.git"
    private = tmp_path / "private"
    root = tmp_path / "public"
    _git("init", "--bare", "--initial-branch=main", str(bare))
    _git("clone", str(bare), str(private))
    (private / "README.md").write_text("private state\n", encoding="utf-8")
    _git("-C", str(private), "config", "user.name", "test")
    _git("-C", str(private), "config", "user.email", "test@example.com")
    _git("-C", str(private), "add", "README.md")
    _git("-C", str(private), "commit", "-m", "bootstrap")
    _git("-C", str(private), "push", "-u", "origin", "main")
    (root / "data").mkdir(parents=True)
    (root / "data/feedback.enc").write_bytes(b"opaque-encrypted-state")
    (root / "data/telegram_state.json").write_text('{"offset":10}', encoding="utf-8")
    assert checkpoint(private, root)
    assert (private / "data/feedback.enc").read_bytes() == b"opaque-encrypted-state"
    assert not checkpoint(private, root)
    clone = tmp_path / "verify"
    _git("clone", str(bare), str(clone))
    assert (clone / "data/feedback.enc").read_bytes() == b"opaque-encrypted-state"
    assert (clone / "data/telegram_state.json").read_text("utf-8") == '{"offset":10}'
