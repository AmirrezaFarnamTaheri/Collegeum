"""Durably store encrypted Telegram state in a separate PRIVATE Git repository.

The main repository's public state may not be used as a fallback when the
private backend is configured: doing so could resurrect deleted subscribers.
The private repository is checked out by the workflow after an API visibility
gate verifies it is private. No unencrypted subscriber data is ever persisted.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

PRIVATE_STATE_FILES = ("data/feedback.enc", "data/telegram_state.json")
MAX_STATE_BYTES = 16_000_000


def restore(repository: Path, root: Path) -> None:
    """Copy authoritative remote state into the ephemeral runner.

    Fails closed on incomplete migration. The private repository must contain
    all existing tracked state before enabling this backend in production.
    """
    for relative in PRIVATE_STATE_FILES:
        source = repository / relative
        destination = root / relative
        if not source.exists():
            if destination.exists():
                raise RuntimeError(
                    f"Private state missing {relative}; migrate existing data first"
                )
            continue
        if source.stat().st_size > MAX_STATE_BYTES or not source.is_file():
            raise ValueError(f"Invalid private state size: {relative}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_name(destination.name + ".private-tmp")
        try:
            shutil.copyfile(source, temp)
            os.chmod(temp, 0o600)
            temp.replace(destination)
        finally:
            temp.unlink(missing_ok=True)


def checkpoint(repository: Path, root: Path) -> bool:
    """Persist encrypted files; abort on a conflicting writer, never force-push."""
    if not (repository / ".git").exists():
        raise ValueError("Private state checkout is not a Git working tree")
    changed_paths: list[str] = []
    for relative in PRIVATE_STATE_FILES:
        source = root / relative
        if not source.is_file():
            continue
        if source.stat().st_size > MAX_STATE_BYTES:
            raise ValueError(f"Private state file exceeds bound: {relative}")
        target = repository / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        content = source.read_bytes()
        if target.is_file() and target.read_bytes() == content:
            continue
        temp = target.with_name(target.name + ".tmp")
        try:
            with temp.open("wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp, 0o600)
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
        changed_paths.append(relative)
    if not changed_paths:
        return False
    git = ["git", "-C", str(repository)]
    subprocess.run([*git, "config", "user.name", "collegeum-state-bot"], check=True)
    subprocess.run(
        [*git, "config", "user.email", "actions@users.noreply.github.com"],
        check=True,
    )
    # Initial migration can have feedback.enc before the update cursor exists.
    # Git would reject a pathspec for a missing file.
    subprocess.run([*git, "add", "--", *changed_paths], check=True)
    subprocess.run(
        [*git, "commit", "-m", "checkpoint: private Telegram state"],
        check=True,
    )
    # Never rebase divergent Fernet ciphertext or overwrite the remote.
    # Failure is authoritative: sending must not start if intents were not pushed.
    subprocess.run([*git, "push"], check=True)
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("restore", "checkpoint"))
    parser.add_argument("--repo", type=Path, default=Path(".private-state"))
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    if args.operation == "restore":
        restore(args.repo, args.root)
    else:
        checkpoint(args.repo, args.root)


if __name__ == "__main__":
    main()
