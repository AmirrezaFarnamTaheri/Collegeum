"""Evidence-constrained LinkedIn quality corrections (2026-11-03).

These are *public projection* and historical provenance checks: do not
rewrite durable job IDs, LinkedIn source URLs or Telegram delivery receipts.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from predoc_pipeline import state
from predoc_pipeline.core.output_quality import suppressed_public_alias

ROOT = Path(__file__).resolve().parents[2]


def _journal():
    return {
        entry["id"]: entry
        for line in (ROOT / "data/listings.ndjson").read_text(encoding="utf-8").splitlines()
        if (entry := json.loads(line))
    }


def _public():
    data = json.loads((ROOT / "docs/data/listings.json").read_text(encoding="utf-8"))
    assert data["count"] == len(data["listings"])
    return {entry["id"]: entry for entry in data["listings"]}


def test_verified_cross_source_aliases_hide_only_reviewed_mirror_rows():
    rows = _journal()
    expected = {
        49: (304, "JR00124462"),
        46: (297, "JR00127654-1"),
        211: (301, "R-0000033280-2"),
    }
    public = _public()
    for alias, (canonical, requisition) in expected.items():
        original = rows[alias]
        target = rows[canonical]
        assert requisition in original["apply_url"]
        assert requisition in target["apply_url"]
        assert suppressed_public_alias(original["url_hash"])
        assert not suppressed_public_alias(target["url_hash"])
        assert alias not in public
        # A reviewed canonical record can subsequently be closed by ingestion.
        # Alias suppression must not resurrect that closed vacancy, nor hide
        # an otherwise eligible canonical record from the public projection.
        if target.get("closed_at") or target.get("expired_at"):
            assert canonical not in public
        else:
            assert canonical in public
        # The suppressed row remains a historical publication, never erased.
        assert original["status"] == "published"
        assert original["published_at"]
    for distinct in (247, 248, 222, 233, 235, 291, 327):
        assert not suppressed_public_alias(rows[distinct]["url_hash"])


def test_web_projection_retains_identity_and_receipts_for_reviewed_aliases():
    rows = _journal()
    alias = {
        "url_hash": rows[49]["url_hash"],
        "apply_url": rows[49]["apply_url"],
        "source_url": rows[49]["source_url"],
        "telegram_message_id": 99,
        "summary": "Research assistant role",
    }
    retained = {
        **alias,
        "url_hash": rows[304]["url_hash"],
        "source_url": rows[304]["source_url"],
        "apply_url": rows[304]["apply_url"],
        "telegram_message_id": 100,
    }

    class Database:
        def active_listings(self):
            return [alias, retained]

    assert state._web_rows(Database(), set(), None) == [retained]
    assert alias["telegram_message_id"] == 99
    assert alias["url_hash"] == rows[49]["url_hash"]


def test_kings_distinct_official_requisitions_have_verified_deadlines():
    rows, public = _journal(), _public()
    first, second = rows[247], rows[248]
    assert first["source_url"].endswith("4482079977")
    assert second["source_url"].endswith("4482067905")
    assert first["deadline"].startswith("2026-11-09")
    assert second["deadline"].startswith("2026-10-28")
    assert "160868" in first["deadline_note"]
    assert "160625" in second["deadline_note"]
    assert "kcl.ac.uk/jobs/160868-" in first["apply_url"]
    assert first["url_hash"] != second["url_hash"]
    # Both verified application deadlines have now elapsed in the committed
    # November 10 production projection. Identity remains distinct in the
    # journal, but expired vacancies must not be resurrected publicly.
    assert 247 not in public
    assert 248 not in public


def test_two_historically_unlinked_decisions_use_only_exact_journal_hashes():
    rows = _journal()
    by_hash = {value["url_hash"]: value for value in rows.values()}
    decisions = [
        json.loads(line)
        for line in (ROOT / "data/seen.ndjson").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    checked = [x for x in decisions if x["source"] == "linkedin" and
               x["decision"] == "accepted"]
    # This is a growing append-only provenance ledger. Production ingestion
    # added accepted decisions after the historical 41-row baseline; its exact
    # total is not a fixed fixture. Do not weaken the two known null links or
    # the journal crosswalk checks below.
    assert len(checked) >= 41
    assert len({x["url_hash"] for x in checked}) == len(checked)
    assert len([x for x in checked if x["listing_url_hash"] is None]) == 2
    for source_hash, expected_id in (
        ("a5629362e65e59c4ec0f467ce3287b6422dc1fcdb50a8f85e428e19b970d707f", 3),
        ("2929d88ab5ae7b76597d5de381f514292913074962787f994a34047d6021accb", 51),
    ):
        row = next(item for item in checked if item["url_hash"] == source_hash)
        assert row["listing_url_hash"] == source_hash
        assert by_hash[source_hash]["id"] == expected_id
    assert all(x["listing_url_hash"] in by_hash for x in checked
               if x["listing_url_hash"])


def test_rss_does_not_claim_rolling_when_deadline_is_unknown(tmp_path: Path):
    record = {
        "title": "Research role", "institution": "University",
        "city": None, "country": "Norway", "summary": "A genuine vacancy.",
        "first_seen_at": "2026-10-20T10:00:00Z",
        "source_url": "https://example.org/jobs/123",
        "apply_url": "https://example.org/jobs/123",
        "deadline": None, "deadline_note": None, "disciplines": [],
    }
    with (patch.object(state, "_web_rows", return_value=[{}]),
          patch.object(state, "_public_record", return_value=record)):
        state.export_feed(object(), tmp_path / "feed.xml")
    feed = (tmp_path / "feed.xml").read_text(encoding="utf-8")
    assert "Deadline: not recorded (availability unverified)" in feed
    assert "Deadline: rolling" not in feed


def test_rss_can_use_explicit_rolling_evidence(tmp_path: Path):
    record = {
        "title": "Research role", "institution": "University",
        "city": None, "country": "Norway", "summary": "A genuine vacancy.",
        "first_seen_at": "2026-10-20T10:00:00Z",
        "source_url": "https://example.org/jobs/123",
        "apply_url": "https://example.org/jobs/123",
        "deadline": None, "deadline_note": "Rolling until filled",
        "disciplines": [],
    }
    with (patch.object(state, "_web_rows", return_value=[{}]),
          patch.object(state, "_public_record", return_value=record)):
        state.export_feed(object(), tmp_path / "feed.xml")
    feed = (tmp_path / "feed.xml").read_text(encoding="utf-8")
    assert "Deadline: Rolling until filled" in feed


def test_opt_in_subscription_preview_does_not_repeat_verified_requisition_aliases():
    from predoc_pipeline.publish.subscriptions import matching

    rows = _journal()
    member = {"topics": {"predoc": "2026-10-01T00:00:00Z"}, "scopes": {}}
    results = matching(member, [rows[49], rows[304]], [],
                       preview=True, lookback_days=60)
    assert [entry["key"] for entry in results] == [
        "academic:" + rows[304]["url_hash"]
    ]


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js required")
def test_dashboard_does_not_mislabel_linkedin_source_advert_as_direct_application():
    page = (ROOT / "docs/index.html").read_text(encoding="utf-8")
    source = "function applicationLinkLabel" + page.split(
        "function applicationLinkLabel", 1
    )[1].split("function deadlineBadge", 1)[0]
    script = source + """
const tests = [
 {apply_url:'https://www.linkedin.com/jobs/view/4482079977'},
 {apply_url:'https://www.kcl.ac.uk/jobs/160868-research-associate-evaluation'},
 {apply_url:'https://example.edu/role.pdf'},
];
console.log(JSON.stringify(tests.map(applicationLinkLabel)));
"""
    output = subprocess.run(["node", "-e", script], check=True,
                            capture_output=True, text=True)
    assert json.loads(output.stdout) == [
        "View on LinkedIn ↗",
        "View application page ↗",
        "View job description ↗",
    ]
    assert "applicationLinkLabel(r)" in page
    assert "Direct link ↗" not in page
