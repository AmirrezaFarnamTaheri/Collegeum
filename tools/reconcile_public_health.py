"""Reconcile published component snapshots after the production Git rebase.

The application writes health before the final source-data pull. Independent
refreshes may publish a newer institutional catalogue in the meantime, making
a newly persisted health.json contain misleading *older* nested metrics.
This bounded, no-network command updates health.json only, never delivery
journals or outgoing messages. The check mode runs after durable checkpointing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

MAX_INPUT_BYTES = 8 * 1024 * 1024
FUTURE_SKEW = timedelta(minutes=5)
SNAPSHOT_AGES = {
    "official_calls": timedelta(hours=8),
    "phd_admissions": timedelta(hours=8),
    "life_sciences": timedelta(hours=24),
    "career": timedelta(hours=24),
    "listings": timedelta(hours=8),
}
SNAPSHOT_FILES = {
    "official_calls": ("docs/data/official_phd_calls.json", "generated_at"),
    "phd_admissions": ("docs/data/phd_admissions.json", "generated_at"),
    "life_sciences": ("data/life_sources_health.json", "checked_at"),
    "career": ("data/career_health.json", "checked_at"),
    "listings": ("docs/data/listings.json", "generated_at"),
}
DELIVERY_JOURNALS = {
    "official_calls": "data/official_phd_calls_telegram.json",
    "phd_admissions": "data/phd_admissions_telegram.json",
}
COUNTS = ("successful", "empty", "failed", "partial", "skipped")


def _parse_aware(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 45 or "T" not in value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.astimezone(UTC) if stamp.tzinfo is not None else None


def classify_snapshot(
    stamp: Any, *, now: datetime, max_age: timedelta,
) -> dict[str, Any]:
    """Classify source age independently of the outer pipeline CI status."""
    if now.tzinfo is None or max_age <= timedelta(0):
        raise ValueError("Snapshot checks need aware clock and positive max age")
    moment = _parse_aware(stamp)
    if moment is None:
        return {
            "state": "missing" if stamp is None else "invalid",
            "generated_at": stamp if isinstance(stamp, str) else None,
            "age_seconds": None,
        }
    age = now.astimezone(UTC) - moment
    state = ("future" if age < -FUTURE_SKEW else
             "stale" if age > max_age else "current")
    return {
        "state": state, "generated_at": stamp,
        "age_seconds": max(0, int(age.total_seconds())),
    }


def _validate_run(health: Any, expected_run_id: str, now: datetime) -> None:
    if not isinstance(health, dict):
        raise ValueError("Invalid health document")
    last = health.get("last_run")
    if (not isinstance(last, dict) or not expected_run_id
            or str(last.get("run_id", "")) != expected_run_id):
        raise ValueError("Health run identity mismatch")
    status = classify_snapshot(
        health.get("generated_at"), now=now, max_age=timedelta(days=3),
    )["state"]
    if status in {"missing", "invalid", "future"}:
        raise ValueError("Invalid pipeline health timestamp")
    summary = last.get("sources")
    if summary is None and last.get("outcome") in {"fatal", "dry-run"}:
        return
    if not isinstance(summary, dict):
        raise ValueError("Invalid source summary")
    if (type(summary.get("total")) is not int or summary["total"] < 0
            or any(type(summary.get(k)) is not int or summary[k] < 0
                   for k in COUNTS)
            or summary["total"] != sum(summary[k] for k in COUNTS)):
        raise ValueError("Inconsistent source summary")
    if (health.get("status") == "ok"
            and (last.get("outcome") != "ok"
                 or bool(summary["failed"] or summary["partial"])
                 or bool(last.get("errors") or last.get("source_errors")))):
        raise ValueError("False-green application outcome")


def reconcile_health(
    health: dict[str, Any], official_summary: dict[str, Any],
    observed: dict[str, Any], *, expected_run_id: str, now: datetime,
) -> dict[str, Any]:
    """Repair source metadata without changing production outcome or receipts."""
    _validate_run(health, expected_run_id, now)
    if not isinstance(official_summary, dict) or not isinstance(observed, dict):
        raise ValueError("Invalid source summary")
    previous = health.get("official_calls")
    previous_at = previous.get("generated_at") if isinstance(previous, dict) else None
    pipeline_at = _parse_aware(health["generated_at"])
    snapshots: dict[str, dict[str, Any]] = {}
    for name, max_age in SNAPSHOT_AGES.items():
        record = classify_snapshot(observed.get(name), now=now, max_age=max_age)
        source_at = _parse_aware(record["generated_at"])
        record["updated_after_pipeline"] = bool(
            source_at is not None and pipeline_at is not None
            and source_at > pipeline_at
        )
        if name == "official_calls":
            record["previous_summary_generated_at"] = previous_at
            record["reconciled"] = previous_at != observed.get(name)
            if observed.get(name) != official_summary.get("generated_at"):
                record["state"] = "mismatched"
        snapshots[name] = record
    official = dict(official_summary)
    state = snapshots["official_calls"]["state"]
    if state in {"missing", "invalid", "future", "mismatched"}:
        official = {
            "status": "unavailable", "generated_at": observed.get("official_calls"),
            "eligible": None, "unpublished": None,
        }
    elif state == "stale":
        official.update(
            status="degraded", snapshot_freshness="stale",
            eligible=None, unpublished=None,
        )
    result = dict(health)
    result["official_calls"] = official
    result["component_snapshots"] = snapshots
    result["component_snapshots_observed_at"] = now.astimezone(UTC).isoformat(
        timespec="seconds",
    ).replace("+00:00", "Z")
    return result


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("Untrusted or unbounded health component")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Health component must be a JSON object")
    return data


def _bounded_json_with_hash(
    path: Path, *, label: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Read and hash a bounded, non-symlink JSON document exactly once."""
    if not path.exists():
        return None, None
    if path.is_symlink() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"Untrusted or unbounded {label}")
    raw = path.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError(f"Unbounded {label} content")
    try:
        data = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ValueError(f"Invalid {label} JSON") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Invalid {label} format")
    return data, hashlib.sha256(raw).hexdigest()


def _observed_components(
    root: Path,
) -> tuple[dict[str, Any], dict[str, str | None]]:
    """Bind every catalogue timestamp to its exact bounded JSON bytes."""
    stamps: dict[str, Any] = {}
    digests: dict[str, str | None] = {}
    for name, (filename, field) in SNAPSHOT_FILES.items():
        data, digest = _bounded_json_with_hash(
            root / filename, label=f"{name} snapshot",
        )
        stamps[name] = data.get(field) if data is not None else None
        digests[name] = digest
    return stamps, digests


def _observed_delivery_journals(root: Path) -> dict[str, str | None]:
    """Fingerprint durable receipt dependencies without changing their state."""
    digests: dict[str, str | None] = {}
    for name, filename in DELIVERY_JOURNALS.items():
        data, digest = _bounded_json_with_hash(
            root / filename, label=f"delivery journal {name}",
        )
        if data is not None and (
            data.get("version") != 1
            or not isinstance(data.get("deliveries"), dict)
        ):
            raise ValueError(f"Invalid delivery journal {name} schema")
        digests[name] = digest
    return digests


def checkpoint(
    root: Path, *, expected_run_id: str, now: datetime, write: bool,
) -> dict[str, Any]:
    """Update only health metadata, or check persisted metadata after a push."""
    path = root / "docs/data/health.json"
    health = _read_json(path)
    _validate_run(health, expected_run_id, now)
    assert health is not None
    observed, digests = _observed_components(root)
    journal_hashes = _observed_delivery_journals(root)
    if not write:
        current = health.get("official_calls")
        recorded = health.get("component_snapshots")
        if (not isinstance(current, dict)
                or current.get("generated_at") != observed["official_calls"]
                or not isinstance(recorded, dict)):
            raise ValueError("Persisted official calls not reconciled")
        for name, stamp in observed.items():
            item = recorded.get(name)
            if not isinstance(item, dict) or item.get("generated_at") != stamp:
                raise ValueError(f"Unreconciled {name} snapshot")
            if item.get("content_sha256") != digests[name]:
                raise ValueError(f"Unreconciled {name} fingerprint")
        if health.get("delivery_journal_sha256") != journal_hashes:
            raise ValueError("Unreconciled delivery journal fingerprint")
        return {"status": "checked", "run_id": expected_run_id}

    # Pure read-only health report: no publish/dispatch method is invoked.
    from predoc_pipeline.publish.official_calls import official_calls_health

    summary = official_calls_health(
        root / SNAPSHOT_FILES["official_calls"][0],
        root / "data/official_phd_calls_telegram.json", now=now,
    )
    summary.setdefault("generated_at", observed["official_calls"])
    data = reconcile_health(
        health, summary, observed, expected_run_id=expected_run_id, now=now,
    )
    for name, digest in digests.items():
        data["component_snapshots"][name]["content_sha256"] = digest
    data["delivery_journal_sha256"] = journal_hashes
    payload = (json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode()
    if len(payload) > MAX_INPUT_BYTES:
        raise ValueError("Reconciled health too large")
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".health-checkpoint-", suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
    return {
        "status": "reconciled", "run_id": expected_run_id,
        "official_calls": data["component_snapshots"]["official_calls"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--expected-run-id", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    result = checkpoint(
        args.root, expected_run_id=args.expected_run_id,
        now=datetime.now(UTC), write=args.write,
    )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
