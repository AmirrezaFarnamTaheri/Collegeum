"""Durable at-most-once Telegram send reservations for ephemeral GitHub runners.

Telegram sendMessage has no caller-supplied idempotency key. An in-process
ledger checkpoint is lost if the GitHub Actions runner dies before its final
git push. Reserve a *new*, immutable content object on trusted main via the
GitHub Contents API before every admission/scholarship send. An existing
reservation (HTTP 422) or unknown API outcome must stop the send, never retry
blindly. Confirmed message IDs still belong in the normal receipt journals.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

_REPOSITORY = re.compile(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
_KEY = re.compile(r"[0-9a-f]{32}\Z")
_NAMESPACES = frozenset({"admissions", "calls"})
_API = "https://api.github.com"


class GitHubIntentReserver:
    """Atomic create-only reservation; never overwrite a potentially used key."""

    def __init__(self, *, repository: str, token: str) -> None:
        if (not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository)
                or repository.split("/")[0].endswith("-") or ".." in repository):
            raise ValueError("Invalid GitHub owner/repository")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("A nonempty token is required for durable reservations")
        self._repository = repository
        self._token = token

    @classmethod
    def from_environment(cls) -> GitHubIntentReserver:
        """Only trusted production-main ingestion may commit durable send intents."""
        if (
            os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_WORKFLOW") != "predoc-pipeline"
        ):
            raise OSError("Durable Telegram reservations require trusted main ingestion")
        try:
            return cls(
                repository=os.environ.get("GITHUB_REPOSITORY", ""),
                token=os.environ.get("GITHUB_TOKEN", ""),
            )
        except ValueError:
            raise OSError("Durable Telegram reservation credentials unavailable") from None

    def reserve(self, namespace: str, key: str, operation: str) -> None:
        """Persist a permanent send-intent in main before calling Telegram.

        A create-only PUT is atomic at GitHub's Contents API endpoint: a
        second attempt for the same call and operation receives HTTP 422.
        A transport timeout may mean the intent WAS persisted. It is never
        safe to retry or to call Telegram after that uncertainty.
        """
        if namespace not in _NAMESPACES:
            raise ValueError("Unknown Telegram reservation namespace")
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise ValueError("Invalid Telegram opportunity key")
        if not isinstance(operation, str) or not 1 <= len(operation) <= 120:
            raise ValueError("Invalid Telegram reservation operation")
        digest = hashlib.sha256(operation.encode("utf-8")).hexdigest()[:24]
        path = f"data/telegram_delivery_intents/{namespace}/{key}-{digest}.json"
        document: dict[str, Any] = {
            "schema_version": 1,
            "namespace": namespace,
            "opportunity_key": key,
            "operation_hash": digest,
            "reserved_at": datetime.now(UTC).isoformat(
                timespec="seconds"
            ).replace("+00:00", "Z"),
        }
        payload = json.dumps({
            "message": f"chore: reserve {namespace} Telegram delivery [skip ci]",
            "branch": "main",
            # No sha: GitHub rejects update attempts for existing files.
            "content": base64.b64encode(
                (json.dumps(document, sort_keys=True) + "\n").encode("utf-8")
            ).decode("ascii"),
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{_API}/repos/{self._repository}/contents/{path}",
            data=payload,
            method="PUT",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "Collegeum-Durable-Telegram-Intents",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                if response.status != 201:
                    raise OSError("GitHub did not confirm a new Telegram send reservation")
        except urllib.error.HTTPError as exc:
            if exc.code in (409, 422):
                raise OSError("Existing or conflicting Telegram reservation; no send") from None
            raise OSError("GitHub refused durable Telegram reservation; no send") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise OSError("Durable Telegram reservation outcome uncertain; no send") from None


def enforce_production_reservation(reserve_intent: Any) -> None:
    """Main GitHub ingestion must not silently publish with local-only intents."""
    if (
        os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("GITHUB_REF") == "refs/heads/main"
        and os.environ.get("GITHUB_WORKFLOW") == "predoc-pipeline"
        and reserve_intent is None
    ):
        raise OSError("Missing durable Telegram send reservation on production main")
