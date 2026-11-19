"""Officially evidenced institutional scholarship calls cannot vanish between feed and Telegram."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from predoc_pipeline.publish.official_calls import (
    call_key,
    eligible_calls,
    publish_official_calls,
)
from tools.update_official_calls import (
    discover_links,
    extract_call,
    refresh_sources,
)
from predoc_pipeline.publish.telegram import TelegramError

NOW = datetime(2026, 11, 20, 8, tzinfo=UTC)
IEB = "https://ieb.ub.edu/en/phd-scholarship-in-economics-2027/"
CLIMATE = "https://ieb.ub.edu/call-for-expressions-of-interest-phd-fellowship-in-energy-and-climate-economics/"
HENLEY = "https://www.henley.ac.uk/study/phds/accounting-and-financial-management"

IEB_HTML = """<html><h1>PhD Scholarship in Economics 2027</h1>
<p>We offer one full-time scholarship to pursue a PhD in Economics at
the University of Barcelona, starting September 2027.</p>
<p>Interested candidates must complete both of the following steps by
11 December 2026.</p><footer>C/ John M. Keynes, 1-11, 08034 Barcelona.
Tel. +34 93 403 46 46</footer></html>"""

CLIMATE_HTML = """<h1>Call for expressions of interest - PhD Fellowship in
Energy and Climate Economics</h1>
<p>University of Barcelona offers a three-year, full-time PhD Fellowship
starting September 2027.</p>
<p>Interested candidates must complete both of the following steps before
11 December 2026 at 23:59 CET.</p>
<footer>C/ John M. Keynes 1-11, 08034 Barcelona; Tel. +34 93 403 46 46.</footer>"""

HENLEY_HTML = """<h1>Accounting PhD Opportunities</h1>
<p>Our PhD in Accounting offered within the Finance and Accounting department.</p>
<h2>PhD funding</h2><p>We offer postgraduate studentships covering course fees and a stipend.</p>
<p>Studentship applications for the 2026/27 academic year are now closed.</p>
<p>Studentship applications for the 2027/28 academic year are now open
and will close on 21 February 2027. Scholarships are available exclusively
to applicants who have received an offer to study for a PhD.
We strongly advise submitting your application no later than 10 January 2027.</p>
<h2>Entry requirements</h2>
<p>PhD applications for the 2027/28 academic year are due to close on
30 June 2027.</p>"""

SOURCES = {
    "kind": "official_phd_call_sources", "version": 1,
    "sources": [
        {"id": "ieb", "institution": "Barcelona Institute of Economics (IEB)",
         "country_code": "ES", "mode": "index",
         "url": "https://ieb.ub.edu/en/news/"},
        {"id": "henley-accounting", "institution": "Henley Business School",
         "country_code": "UK", "mode": "detail", "url": HENLEY,
         "title": "Finance and Accounting PhD Studentships"},
    ],
}
INDEX_HTML = f"""<h1>News</h1>
<a href="{IEB}">PhD Scholarship in Economics 2027</a>
<a href="{CLIMATE}">Call for expressions of interest - PhD Fellowship in Energy and Climate Economics</a>
<a href="/en/research-news/">New university research programme</a>
<a href="/en/postdoctoral-position/">Postdoctoral position in Environmental Economics</a>
<a href="https://linkedin.com/posts/fake">PhD Scholarship in Economics</a>
<a href="/wp-content/uploads/call.pdf">PhD Scholarship PDF</a>"""


def _source(url=IEB):
    return {"id": "ieb", "institution": "Barcelona Institute of Economics (IEB)",
            "country_code": "ES", "url": url, "mode": "detail"}


def _catalog(*rows):
    return {"kind": "official_phd_call_observations", "version": 1, "calls": list(rows)}


def test_index_discovers_multiple_distinct_official_calls_without_social_or_postdocs():
    assert discover_links(INDEX_HTML, SOURCES["sources"][0]) == [IEB, CLIMATE]


def test_ieb_direct_scholarship_deadline_not_intake_or_stipend():
    row = extract_call(IEB_HTML, url=IEB, source=_source(), now=NOW)
    assert row["status"] == "verified"
    assert row["kind"] == "phd_scholarship"
    assert row["deadline_iso"] == "2026-12-11"
    assert row["deadline_kind"] == "scholarship"
    assert row["intake_year"] == 2027
    assert row["location_evidence"]


def test_distinct_ieb_fellowship_is_not_deduplicated_into_scholarship():
    a = extract_call(IEB_HTML, url=IEB, source=_source(), now=NOW)
    b = extract_call(CLIMATE_HTML, url=CLIMATE, source=_source(CLIMATE), now=NOW)
    assert b["status"] == "verified"
    assert b["deadline_iso"] == "2026-12-11"
    assert b["kind"] == "phd_fellowship"
    assert call_key(a) != call_key(b)


def test_henley_funding_cutoff_is_not_general_phd_admission_or_suggested_date():
    row = extract_call(HENLEY_HTML, url=HENLEY, source=SOURCES["sources"][1], now=NOW)
    assert row["status"] == "verified"
    assert row["kind"] == "phd_studentship"
    assert row["deadline_iso"] == "2027-02-21"
    assert row["deadline_kind"] == "funding"
    assert row["recommended_admission_iso"] == "2027-01-10"
    assert "30 June" not in row["evidence_excerpt"]


def test_social_claims_and_cemfi_general_admission_cannot_be_scholarship_evidence():
    cemfi = """<h1>Doctoral Program Admission</h1>
    <p>Applications are open until 15 April 2027. The deadline to be
    eligible for funding is 31 January 2027.</p>"""
    row = extract_call(cemfi, url="https://www.cemfi.es/programs/phd/admissions.asp",
                       source={"id": "cemfi", "institution": "CEMFI",
                               "country_code": "ES", "mode": "detail"}, now=NOW)
    assert row["status"] != "verified"
    assert eligible_calls(_catalog(row), now=NOW) == []


def test_multiple_deadlines_or_wrong_country_remain_unpublishable():
    bad = extract_call(IEB_HTML.replace("11 December 2026",
                                        "11 December 2026 or 15 January 2027"),
                       url=IEB, source=_source(), now=NOW)
    assert bad["status"] != "verified"
    good = extract_call(IEB_HTML, url=IEB, source=_source(), now=NOW)
    good["country_code"] = "FR"
    assert eligible_calls(_catalog(good), now=NOW) == []


def test_fresh_official_index_is_checked_without_scraping_feed_posts():
    responses = {
        "https://ieb.ub.edu/en/news/": {"status": "ok", "html": INDEX_HTML},
        IEB: {"status": "ok", "html": IEB_HTML},
        CLIMATE: {"status": "ok", "html": CLIMATE_HTML},
        HENLEY: {"status": "ok", "html": HENLEY_HTML},
    }
    result = refresh_sources(SOURCES, _catalog(), now=NOW,
                             fetcher=lambda url: responses[url])
    assert {row["deadline_iso"] for row in result["calls"]} == {
        "2026-12-11", "2027-02-21",
    }
    assert len(eligible_calls(result, now=NOW)) == 3


def test_inaccessible_official_source_fails_closed_even_after_prior_success():
    old = extract_call(IEB_HTML, url=IEB, source=_source(), now=NOW)
    old["checked_at"] = (NOW - timedelta(days=16)).isoformat()
    result = refresh_sources(SOURCES, _catalog(old), now=NOW,
                             fetcher=lambda url: {"status": "robots_unavailable"})
    assert eligible_calls(result, now=NOW) == []
    assert all(s["status"] == "robots_unavailable" for s in result["sources"])


def test_multiple_posts_with_independent_receipts_and_no_duplicate_on_rerun(tmp_path):
    rows = [extract_call(html, url=url, source=_source(url), now=NOW)
            for html, url in ((IEB_HTML, IEB), (CLIMATE_HTML, CLIMATE))]
    catalog = tmp_path / "calls.json"
    ledger = tmp_path / "receipts.json"
    catalog.write_text(json.dumps(_catalog(*rows)), encoding="utf-8")
    telegram = Mock()
    telegram.send_message.side_effect = [231, 232]
    assert publish_official_calls(catalog, ledger, telegram, chat_id="@channel",
                                  enabled=True, now=NOW) == 2
    receipts = json.loads(ledger.read_text())["deliveries"]
    assert set(receipt["message_id"] for receipt in receipts.values()) == {231, 232}
    assert telegram.send_message.call_count == 2
    assert publish_official_calls(catalog, ledger, telegram, chat_id="@channel",
                                  enabled=True, now=NOW) == 0


def test_uncertain_delivery_remains_held_in_ledger(tmp_path):
    row = extract_call(IEB_HTML, url=IEB, source=_source(), now=NOW)
    catalog = tmp_path / "calls.json"
    ledger = tmp_path / "receipts.json"
    catalog.write_text(json.dumps(_catalog(row)), encoding="utf-8")
    telegram = Mock()
    telegram.send_message.side_effect = TelegramError("timeout", uncertain=True)
    assert publish_official_calls(catalog, ledger, telegram, chat_id="@channel",
                                  enabled=True, now=NOW) == 0
    telegram.send_message.side_effect = None
    assert publish_official_calls(catalog, ledger, telegram, chat_id="@channel",
                                  enabled=True, now=NOW) == 0
    assert next(iter(json.loads(ledger.read_text())["deliveries"].values()))[
        "state"] == "uncertain"
