"""Keep a verified employer application link instead of general fellowship information."""

import json
from pathlib import Path
from xml.etree import ElementTree as ET

from predoc_pipeline.core.output_quality import application_url_issue

OLD_PROGRAM_INFORMATION = (
    "https://epic.uchicago.edu/about/jobs-fellowships/fellowships/"
    "predoctoral-fellows/predoctoral-fellowship-program/about/"
)
CANONICAL_APPLICATION = "https://job-boards.greenhouse.io/bfiprep/jobs/8011760003"
SOURCE = "https://bit.ly/4zbBa4E"


def test_generic_fellowship_information_page_cannot_be_used_as_application_url():
    assert application_url_issue(OLD_PROGRAM_INFORMATION) == "generic-program-information-page"
    assert application_url_issue(CANONICAL_APPLICATION) is None
    assert application_url_issue(
        "https://epic.uchicago.edu/opportunities/"
        "research-professional-koichiro-ito-full-time-benefits-eligible-3/"
    ) is None


def test_verified_koichiro_application_is_consistent_in_journal_dashboard_and_rss():
    root = Path(__file__).resolve().parents[2]
    journal = {
        row["id"]: row
        for line in (root / "data/listings.ndjson").read_text("utf-8").splitlines()
        if (row := json.loads(line))
    }
    dashboard = json.loads((root / "docs/data/listings.json").read_text("utf-8"))
    public = {row["id"]: row for row in dashboard["listings"]}

    assert 268 in journal and 268 in public
    job = journal[268]
    assert job["status"] == "published"
    assert job["closed_at"] is None
    assert job["source_url"] == SOURCE
    assert job["url_hash"] == "659f7fcbd0779614e7c1287a1af22c63bd2e58b30f6ba07083a6ca52558549e2"
    assert job["apply_url"] == CANONICAL_APPLICATION
    assert public[268]["apply_url"] == CANONICAL_APPLICATION
    assert public[268]["source_url"] == SOURCE

    items = ET.parse(root / "docs/feed.xml").getroot().findall("channel/item")
    rss_match = [item for item in items if item.findtext("guid") == SOURCE]
    assert len(rss_match) == 1
    assert rss_match[0].findtext("link") == CANONICAL_APPLICATION
