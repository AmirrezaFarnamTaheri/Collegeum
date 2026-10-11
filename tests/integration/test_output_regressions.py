"""Rendered size, structural validity and delivery membership at output boundaries."""

import html
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from predoc_pipeline import pipeline, state
from predoc_pipeline.core.db import Database, init
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


def test_rss_defaults_to_collegeum_not_invalid_or_legacy_host(tmp_path):
    path = tmp_path / "output.db"
    init(path)
    with Database(path) as db:
        item = listing()
        row = pipeline._listing_row(item, source="test", signature=None)
        row["status"] = "published"
        db.insert_listing(row)
        output = tmp_path / "feed.xml"
        assert state.export_feed(db, output) == 1
    channel = ET.parse(output).getroot().find("channel")
    assert channel is not None
    assert channel.findtext("link") == (
        "https://amirrezafarnamtaheri.github.io/Collegeum/"
    )
    atom = channel.find("{http://www.w3.org/2005/Atom}link")
    assert atom is not None
    assert atom.attrib["href"].endswith("/Collegeum/feed.xml")


def test_publication_holds_auth_and_error_pages_and_unwraps_valid_forms(tmp_path):
    path = tmp_path / "output.db"
    init(path)
    with Database(path) as db:
        rows = [
            ("https://example.org/vacancy/1", "Research methods position."),
            ("https://accounts.google.com/v3/signin/identifier?"
             "continue=https%3A%2F%2Fdocs.google.com%2Fforms%2Fd%2Fe%2Fabc%2Fviewform",
             "Research assistant position."),
            ("https://accounts.google.com/v3/signin/identifier?"
             "continue=https%3A%2F%2Fevil.example%2Fsteal",
             "Sign in to continue to Google Forms Email or phone."),
            ("https://job-boards.greenhouse.io/bfiprep?error=true", "Research role."),
        ]
        for i, (link, summary) in enumerate(rows):
            row = pipeline._listing_row(listing(i), source="test", signature=None)
            row.update(status="published", summary=summary, apply_url=link)
            db.insert_listing(row)
        output = tmp_path / "listings.json"
        assert state.export_dashboard(db, output) == 2
    payload = __import__("json").loads(output.read_text(encoding="utf-8"))
    assert len(payload["listings"]) == 2
    assert payload["listings"][1]["apply_url"] == (
        "https://docs.google.com/forms/d/e/abc/viewform"
    )


def test_published_salary_projection_rechecks_ad_text_instead_of_model_numbers():
    item = listing(salary_raw="salary scale 13 TV-L, 100%", salary_min=13,
                   salary_max=13, salary_period="year")
    record = state._public_record({"id": 1, "alternate_sources": "[]",
                                   **pipeline._listing_row(
        item, source="test", signature=None,
    )})
    assert record["salary_raw"] == item.salary_raw
    assert record["salary_min"] is None
    assert record["salary_max"] is None
    assert record["salary_period"] is None


def test_cutoff_is_enforced_in_active_search_and_pending_retries(tmp_path):
    from datetime import timedelta

    from predoc_pipeline.core.timeparse import format_ts, utcnow

    path = tmp_path / "cutoffs.db"
    init(path)
    old = format_ts(utcnow() - timedelta(minutes=15))
    future = format_ts(utcnow() + timedelta(days=3))
    with Database(path) as db:
        ids = []
        for i, (deadline, status) in enumerate([
            (old, "published"), (future, "published"),
            (None, "published"), (old, "pending"), (future, "pending"),
        ]):
            row = pipeline._listing_row(listing(i), source="test", signature=None)
            row.update(deadline=deadline, status=status)
            ids.append(db.insert_listing(row))
        assert {r["id"] for r in db.active_listings()} == set(ids[1:3])
        assert {r["id"] for r in db.search_listings("research", active_only=True)} == (
            set(ids[1:3])
        )
        assert {r["id"] for r in db.pending_listings()} == {ids[4]}
        # The raw audit trail preserves historical/expired rows.
        assert len(db.search_listings("research", active_only=False)) == 5
        target = tmp_path / "listings.json"
        assert state.export_dashboard(db, target) == 2


def test_pipeline_rejects_same_day_cutoff_that_passed_before_extraction(
    tmp_path, monkeypatch,
):
    from datetime import UTC, datetime
    from unittest.mock import Mock

    from predoc_pipeline.core.dedupe import Deduplicator
    from predoc_pipeline.models import ExtractionResult, RawItem

    monkeypatch.setattr(
        pipeline, "utcnow", lambda: datetime(2030, 1, 2, 12, 0, tzinfo=UTC)
    )
    path = tmp_path / "cutoff-extraction.db"
    init(path)
    item = RawItem(
        source="test", source_url="https://example.org/job/expired",
        title="Research Assistant in Economics",
        text="We are hiring a paid research assistant in economics now.",
        hints={"board": True},
    )
    extracted = ExtractionResult(
        is_vacancy=True, title=item.title, institution="University of Oxford",
        country="United Kingdom", application_url=item.source_url,
        summary="Paid predoctoral research in applied microeconomics.",
        deadline="2030-01-02T11:59:59Z", confidence=0.99,
    )
    extractor = Mock()
    extractor.extract.return_value = extracted
    stats = pipeline.RunStats()
    with Database(path) as db:
        result = pipeline._process(
            item, db=db, extractor=extractor, deduper=Deduplicator(),
            settings=Settings(_env_file=None, confidence_threshold=0.5),
            stats=stats,
        )
        assert result is None
        assert db.counts()["listings"] == 0
        assert stats.gate_reasons == {"expired-at-extraction": 1}


def test_dashboard_snapshot_preserved_when_atomic_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "atomic.db"
    init(path)
    target = tmp_path / "listings.json"
    saved = '{"count": 3, "listings": []}'
    target.write_text(saved, encoding="utf-8")

    def fails_replace(*args):
        raise OSError("blocked")

    monkeypatch.setattr(state.Path, "replace", fails_replace)
    with Database(path) as db, pytest.raises(OSError, match="blocked"):
        state.export_dashboard(db, target)
    assert target.read_text(encoding="utf-8") == saved


def test_all_actual_state_journal_records_render_valid_telegram_cards(tmp_path):
    """Check the complete committed real dataset, not only synthetic fixtures."""
    target = tmp_path / "real-output.db"
    init(target)
    with Database(target) as db:
        restored = state.restore_if_needed(
            db, Path("data/listings.ndjson"), Path("data/seen.ndjson")
        )
        assert restored >= 100
        all_rows = db.conn.execute("SELECT * FROM listings ORDER BY id").fetchall()
        assert len(all_rows) >= 100
        for row in all_rows:
            item = pipeline._listing_from_row(row)
            card = render_card(item)
            parsed = assert_valid_message(card)
            assert "Research" in " ".join(parsed.itertext()) or item.title
            assert "\x00" not in card
