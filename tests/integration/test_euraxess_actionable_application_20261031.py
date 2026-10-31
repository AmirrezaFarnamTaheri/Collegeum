"""Reject a generic EURAXESS search landing page as a direct vacancy application."""
from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree as ET

from predoc_pipeline.core.output_quality import application_url_issue

ROOT = Path(__file__).resolve().parents[2]
GENERIC = "https://euraxess.ec.europa.eu/jobs/search"
DETAIL = "https://euraxess.ec.europa.eu/jobs/476523"


def test_euraxess_search_is_not_a_position_specific_application_url():
    assert application_url_issue(GENERIC) == "generic-job-search-page"
    assert application_url_issue(GENERIC + "?keywords=postdoc") == "generic-job-search-page"
    assert application_url_issue(DETAIL) is None
    assert application_url_issue("https://euraxess.ec.europa.eu/jobs/476519") is None


def test_published_snapshots_never_offer_generic_euraxess_search_as_apply_link():
    dashboard = json.loads((ROOT / "docs/data/listings.json").read_text("utf-8"))
    assert all(
        application_url_issue(row["apply_url"]) is None
        for row in dashboard["listings"]
    )
    assert all(
        application_url_issue(item.findtext("link")) is None
        for item in ET.parse(ROOT / "docs/feed.xml").getroot().findall("channel/item")
    )


def test_historical_posting_identity_and_delivery_receipts_survive_public_link_repair():
    journal = [
        json.loads(line)
        for line in (ROOT / "data/listings.ndjson").read_text("utf-8").splitlines()
        if line.strip()
    ]
    original = [row for row in journal if row.get("id") == 322]
    assert len(original) == 1
    record = original[0]
    assert record["source_url"] == DETAIL
    assert record["url_hash"] == "9d4062e918a5789799d8f2a2d7815f7d86bae86c26ba6cab404a2f79157da8b1"
    assert record["published_at"] == "2026-10-30T15:10:50Z"
    assert "telegram_delivery_revision" in record
