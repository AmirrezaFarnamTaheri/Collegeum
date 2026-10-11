"""Rendered size, structural validity and delivery membership at output boundaries."""

import html
import re
from xml.etree import ElementTree as ET

import pytest

from predoc_pipeline import pipeline, state
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.output_quality import (
    application_url_issue,
    authentication_page_text,
)
from predoc_pipeline.core.textproc import telegram_visible_length
from predoc_pipeline.core.urls import url_hash
from predoc_pipeline.models import Discipline, Location, PredocListing, VisaStatus
from predoc_pipeline.publish.bot import build_pages
from predoc_pipeline.publish.feedback import FeedbackStore
from predoc_pipeline.publish.telegram import (
    TelegramError,
    render_card,
    render_digest,
    render_digest_pages,
)
from predoc_pipeline.settings import Settings


def listing(index=0, **overrides):
    values = dict(
        title=f"Research Assistant in Economics {index}", institution="University of Oxford",
        location=Location(country="United Kingdom", city="Oxford"),
        summary="Paid economics research using administrative data and causal inference.",
        disciplines=[Discipline.APPLIED_MICRO], visa_sponsorship_status=VisaStatus.UNKNOWN,
        apply_url=f"https://example.org/job/{index}?a=1&b=2",
        source_url=f"https://example.org/source/{index}",
        confidence=0.99, rule_score=0.99, model_confidence=0.99,
    )
    values.update(overrides)
    return PredocListing(**values)


def assert_valid_message(body):
    parsed = ET.fromstring(f"<message>{body}</message>")
    plain = "".join(parsed.itertext())
    assert len(plain.encode("utf-16-le")) // 2 <= 4096
    assert telegram_visible_length(body) <= 4096
    return parsed


def test_single_digest_preview_preserves_link_and_reports_omissions():
    items = [listing(i, location=Location(country="😀" * 6000)) for i in range(100)]
    destination = 'https://example.org/?q="quoted"&page=1'
    body = render_digest(items, site_url=destination)
    parsed = assert_valid_message(body)
    assert "omitted from this preview" in "".join(parsed.itertext())
    assert parsed.findall("a")[-1].attrib["href"] == destination
    shown = len(parsed.findall("a")) - 1
    assert f"{100 - shown} more listings" in body


@pytest.mark.parametrize("text", ["<&>" * 3000, "😀" * 6000, "é\u0301漢字&" * 2000],
                         ids=["entities", "emoji", "mixed-unicode"])
def test_all_variable_card_fields_are_bounded_before_escaping(text):
    item = listing(
        location=Location(country=text, city=text), salary_raw=text, start_term=text,
        deadline_note=text, visa_note=text, degree_note=text,
        tools_required=[text], tools_preferred=[text], min_degree=text,
    )
    card = render_card(item)
    assert_valid_message(card)
    assert "Research Assistant" in card and "Compensation:" in card
    assert not card.endswith("&lt")


@pytest.mark.parametrize("page_size", [0, -1, 1, 6, 30])
@pytest.mark.parametrize("feedback", [False, True])
def test_digest_pages_fit_and_preserve_all_items_and_button_numbers(page_size, feedback):
    items = [(url_hash(item.apply_url), item) for item in [
        listing(i, title=f"Research Assistant {i} " + "a" * 85,
                institution="University " + "b" * 70,
                location=Location(country="😀" * 6000, city="<&>" * 2000),
                deadline_note="&<deadline> " * 800)
        for i in range(30)
    ]]
    pages = render_digest_pages(items, page_size=page_size, feedback=feedback,
                                site_url='https://example.org/?q="<&>')
    seen_numbers, button_numbers = [], []
    for body, keyboard in pages:
        parsed = assert_valid_message(body)
        plain = "".join(parsed.itertext())
        seen_numbers.extend(int(n) for n in re.findall(r"(\d+)\. Research Assistant", plain))
        if feedback:
            button_numbers.extend(int(row[0]["text"].rsplit(" ", 1)[1])
                                  for row in keyboard["inline_keyboard"])
        else:
            assert keyboard is None
    assert seen_numbers == list(range(1, 31))
    if feedback:
        assert button_numbers == seen_numbers
    assert "Browse and filter" in pages[-1][0]


def test_digest_delivery_marks_only_the_members_of_successful_pages(tmp_path):
    path = tmp_path / "output.db"
    init(path)
    items = [listing(i, title=f"Research Assistant {i} " + "a" * 85,
                     institution="University " + "b" * 70) for i in range(30)]

    class Telegram:
        sent = []

        def send_message(self, *, html, **kwargs):
            self.sent.append(html)
            assert_valid_message(html)
            if len(self.sent) == 2:
                raise TelegramError("bad message", status=400, permanent=True)
            return len(self.sent) + 100

    telegram = Telegram()
    settings = Settings(_env_file=None, telegram_bot_token="test",
                        telegram_public_channel_id="42", telegram_digest_threshold=1)
    with Database(path) as db:
        accepted = []
        for item in items:
            row = pipeline._listing_row(item, source="test", signature=None)
            accepted.append((db.insert_listing(row), item))
        stats = pipeline.RunStats()
        pipeline._broadcast(accepted, telegram, settings, db, stats, digest_page_size=30)
        assert len(telegram.sent) >= 2
        failed_indices = {int(n) for n in re.findall(r"(\d+)\. Research Assistant",
                                                   html.unescape(telegram.sent[1]))}
        for i, (lid, _) in enumerate(accepted, 1):
            assert (db.listing(lid)["status"] == "published") is (i not in failed_indices)
        assert stats.published == 30 - len(failed_indices)


@pytest.mark.parametrize("page_size", [0, 1, 30])
def test_bot_command_pages_fit_with_unbounded_location_and_deadline_notes(tmp_path, page_size):
    path = tmp_path / "output.db"
    init(path)
    with Database(path) as db:
        for i in range(30):
            item = listing(i, location=Location(country="😀" * 6000, city="<&>" * 2000),
                           deadline_note="unknown " * 1000)
            row = pipeline._listing_row(item, source="test", signature=None)
            row["status"] = "published"
            db.insert_listing(row)
        rows = list(db.published_listings())
    store = FeedbackStore(tmp_path / "feedback.json")
    pages = build_pages("positions", rows, store, page_size=page_size)
    count = 0
    for body, keyboard in pages:
        assert_valid_message(body)
        count += len(keyboard["inline_keyboard"])
    assert count == 30


@pytest.mark.parametrize("bad_character", ["\x00", "\x01", "\x0b", "\ud800", "\ufffe", "\uffff"])
def test_forbidden_xml_characters_cannot_corrupt_the_entire_feed(tmp_path, bad_character):
    path = tmp_path / "output.db"
    init(path)
    with Database(path) as db:
        row = pipeline._listing_row(listing(), source="test", signature=None)
        # SQLite cannot store a lone surrogate; exercise that directly below.
        row["summary"] = "Paid research " + (bad_character if bad_character != "\ud800" else "\x01")
        row["status"] = "published"
        db.insert_listing(row)
        output = tmp_path / "feed.xml"
        assert state.export_feed(db, output, title="Research " + bad_character) == 1
    root = ET.parse(output).getroot()
    assert len(root.findall("channel/item")) == 1
    assert "Paid research" in root.findtext("channel/item/description")
    assert bad_character not in output.read_text(encoding="utf-8")


@pytest.mark.parametrize("url,expected", [
    ("https://www.europeanjobmarketofeconomists.org/job-listing/role/%5Bnid%5D",
     "unresolved-url-template"),
    ("https://www.europeanjobmarketofeconomists.org/job-listing/role/{nid}",
     "unresolved-url-template"),
    ("https://accounts.google.com/v3/signin/identifier?continue=https://docs.google.com",
     "authentication-redirect"),
    ("https://login.microsoftonline.com/common/oauth2/authorize", "authentication-redirect"),
    ("http://www.econjobmarket.org/", "generic-job-board-homepage"),
    ("http://jobs.hhs.se/en/job/stockholm/position-123.html", None),
    ("https://www.uni-hannover.de/en/jobs/8794/", None),
    ("https://jobs.ac.uk/job/ABC123?jobID=42", None),
])
def test_audited_historical_link_types_are_classified_conservatively(url, expected):
    assert application_url_issue(url) == expected


def test_authentication_boilerplate_is_not_accepted_as_a_job_description():
    assert authentication_page_text(
        "Sign in to continue to Google Forms Email or phone Forgot email? "
        "Not your computer? Use Guest mode."
    )
    assert not authentication_page_text(
        "A paid research fellowship; applicants will sign in to continue "
        "through their university account."
    )


def test_invalid_historical_links_never_reappear_in_new_public_exports(tmp_path):
    database = tmp_path / "audit-output.db"
    init(database)
    valid = listing(1)
    broken = listing(
        2,
        apply_url="https://www.europeanjobmarketofeconomists.org/job-listing/a/%5Bnid%5D",
    )
    auth = listing(
        3, apply_url="https://accounts.google.com/v3/signin/identifier",
        summary="Sign in to continue. Email or phone. Forgot email?",
    )
    with Database(database) as db:
        for item in (valid, broken, auth):
            fields = pipeline._listing_row(item, source="test", signature=None)
            fields["status"] = "published"
            db.insert_listing(fields)
        dashboard = tmp_path / "listings.json"
        feed = tmp_path / "feed.xml"
        assert state.export_dashboard(db, dashboard) == 1
        assert state.export_feed(db, feed) == 1
    import json

    exported = json.loads(dashboard.read_text(encoding="utf-8"))
    assert exported["count"] == 1
    assert exported["listings"][0]["apply_url"] == valid.apply_url
    assert len(ET.parse(feed).getroot().findall("channel/item")) == 1


def test_link_scan_rejects_ejm_placeholders_before_model_extraction():
    from predoc_pipeline.boards.config import SourceConfig
    from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper

    source = SourceConfig(
        name="european_job_market", type="link_scan",
        url="https://www.europeanjobmarketofeconomists.org/job-listings",
        link_pattern=r"europeanjobmarketofeconomists\\.org/job-listing/",
    )

    class OfflineHttp:
        def set_host_interval(self, *_args):
            pass

    scraper = LinkScanScraper(source, OfflineHttp())
    html = (
        '<a href="/job-listing/role/%5Bnid%5D">Postdoctoral Fellow in Economics</a>'
        '<a href="/job-listing/role/98765">Postdoctoral Fellow in Economics</a>'
    )
    items = scraper.parse_postings([(source.url, html)])
    assert len(items) == 1
    assert items[0].url.endswith("/98765")
    assert scraper.discovery_parse_errors


def test_failed_source_discovery_is_recoverable_from_dlq_without_secret_leak():
    class Recorder:
        rows = []

        def log_dlq(self, **kwargs):
            self.rows.append(kwargs)

    db = Recorder()
    entries = {
        "board:ok": {"ok": True, "items": 2, "messages": []},
        "board:broken": {
            "ok": False, "items": 0, "errors": 1,
            "messages": ["HTTP 403 at https://private.example/?token=secret"],
        },
        "board:degraded": {
            "ok": False, "items": 1, "errors": 1,
            "messages": ["timed out at https://site.example/key=secret"],
        },
        "board:skipped": {"skipped": True, "errors": 1},
    }
    assert pipeline._record_discovery_failures(db, "run123", entries) == 2
    assert {entry["source"] for entry in db.rows} == {
        "board:broken", "board:degraded",
    }
    assert all(entry["stage"] == "discovery" for entry in db.rows)
    assert all("secret" not in entry["error"] for entry in db.rows)
    assert all(entry["source_url"] == "" and entry["payload"] == "" for entry in db.rows)
