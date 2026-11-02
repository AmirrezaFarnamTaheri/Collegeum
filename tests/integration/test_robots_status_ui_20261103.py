"""A policy-blocked career source must not be shown as healthy in Telegram."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from predoc_pipeline.publish.ui import sources_panel


def test_provider_policy_block_is_visible_in_both_languages_without_raw_errors(tmp_path):
    now = datetime.now(UTC)
    health = tmp_path / "health.json"
    health.write_text(json.dumps({
        "checked_at": now.isoformat(),
        "sources": {
            "jobicy": {"requested": True, "fetched": 2, "accepted": 1, "status": "ok"},
            "jobinja": {
                "requested": True, "fetched": 1, "accepted": 0,
                "status": "blocked_robots",
                "last_robots_denial_at": (now - timedelta(hours=30)).isoformat(),
                "next_robots_check_at": (now + timedelta(days=5)).isoformat(),
            },
            "irantalent": {"requested": True, "fetched": 1, "accepted": 0, "status": "empty"},
        },
        "errors": ["PRIVATE_TOKEN_NEVER_ECHO"],
    }), encoding="utf-8")

    english, _ = sources_panel(health, lang="en")
    persian, _ = sources_panel(health, lang="fa")
    jobinja_en = next(line for line in english.splitlines() if "Jobinja" in line)
    jobinja_fa = next(line for line in persian.splitlines() if "Jobinja" in line)
    assert "Blocked by site policy" in jobinja_en
    assert "Healthy" not in jobinja_en
    assert "No matching roles" not in jobinja_en
    assert "مسدود" in jobinja_fa
    assert "Next policy recheck:" in english
    assert "PRIVATE_TOKEN_NEVER_ECHO" not in english
    assert "PRIVATE_TOKEN_NEVER_ECHO" not in persian


def test_stale_report_does_not_override_explicit_policy_denial(tmp_path):
    old = datetime.now(UTC) - timedelta(days=2)
    health = tmp_path / "health.json"
    health.write_text(json.dumps({
        "checked_at": old.isoformat(),
        "sources": {"jobinja": {
            "requested": True, "fetched": 1, "accepted": 0,
            "status": "blocked_robots",
            "last_robots_denial_at": old.isoformat(),
        }},
    }), encoding="utf-8")
    english, _ = sources_panel(health)
    source = next(line for line in english.splitlines() if "Jobinja" in line)
    assert "Blocked by site policy" in source
    assert "Healthy" not in source
