"""Preserve immutable predoc identity while correcting one verified apply link.

Old PR #57 targeted an outdated journal snapshot; these assertions run against
the current durable journal and exports without requiring retired items to
remain forever among the newest 100 RSS items.
"""
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from predoc_pipeline.core.output_quality import application_url_issue

OLD = (
    "https://epic.uchicago.edu/about/jobs-fellowships/fellowships/"
    "predoctoral-fellows/predoctoral-fellowship-program/about/"
)
NEW = "https://job-boards.greenhouse.io/bfiprep/jobs/8011760003"
ORIGINAL_SOURCE = "https://bit.ly/4zbBa4E"
ORIGINAL_HASH = "659f7fcbd0779614e7c1287a1af22c63bd2e58b30f6ba07083a6ca52558549e2"
ROOT = Path(__file__).resolve().parents[2]


def test_generic_epic_programme_page_is_not_a_job_application():
    assert application_url_issue(OLD) == "generic-program-information-page"
    assert application_url_issue(NEW) is None
    assert application_url_issue(
        "https://epic.uchicago.edu/opportunities/"
        "research-professional-koichiro-ito-full-time-benefits-eligible-3/"
    ) is None


def test_ito_journal_preserves_published_identity_but_fixes_destination():
    rows = [
        json.loads(x) for x in (ROOT / "data/listings.ndjson").read_text("utf-8").splitlines()
        if x.strip()
    ]
    matching = [row for row in rows if row.get("id") == 268]
    assert len(matching) == 1
    job = matching[0]
    assert job["apply_url"] == NEW
    assert job["source_url"] == ORIGINAL_SOURCE
    assert job["url_hash"] == ORIGINAL_HASH
    # A future legitimate close/expiry must not break immutable identity checks.
    assert job["published_at"] is not None
    assert job["first_seen_at"] == "2026-10-23T23:12:27Z"
    assert job["published_at"] == "2026-10-23T23:17:08Z"
    assert "telegram_delivery_revision" in job


def test_public_exports_use_same_destination_when_listing_is_still_present():
    payload = json.loads((ROOT / "docs/data/listings.json").read_text("utf-8"))
    # The public dashboard and feed are sliding windows. Do not pin an older
    # vacancy to a feed forever just to make this test pass.
    listing = next((row for row in payload["listings"] if row.get("id") == 268), None)
    if listing:
        assert listing["apply_url"] == NEW
        assert listing["source_url"] == ORIGINAL_SOURCE
    root = ET.parse(ROOT / "docs/feed.xml").getroot()
    for item in root.findall(".//item"):
        if item.findtext("guid") == ORIGINAL_SOURCE:
            assert item.findtext("link") == NEW
