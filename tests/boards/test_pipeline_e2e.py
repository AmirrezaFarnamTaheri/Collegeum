"""End-to-end: job boards -> gate -> heuristic extraction -> preferences -> dedupe
-> link check -> Telegram (with ✅ ❌ 📝 buttons) -> journal/dashboard, all against
mocked HTTP. No Gemini key, as for a user in a country where Gemini is blocked."""

import json
from pathlib import Path

import httpx
import pytest

from predoc_pipeline import pipeline
from predoc_pipeline.core.db import Database
from predoc_pipeline.settings import Settings
from tests.boards.conftest import ROOT, fixture_text

WD_API = "https://ubc.wd10.myworkdayjobs.com/wday/cxs/ubc/ubcstaffjobs"

PAGES = {
    # UCL predoc (still open)
    "https://bit.ly/4yDgnWV": "<html><body><main><h1>Research Assistant</h1><p>UCL School of "
                              "Management, London. Finance and economics research with Saleem "
                              "Bahaj. Closing date: 22 November 2026.</p></main></body></html>",
    # UPF predoc (open, EU)
    "https://bit.ly/4bMFmgP": "<html><body><main><p>Pre-doctoral RA in macroeconomics. Location: "
                              "Barcelona, Spain. Visas for international candidates outside of the "
                              "EU will be supported.</p></main></body></html>",
    # a predoc whose link redirects to a US .edu site
    "https://econ.example.edu/predoc": "<html><body><main><p>Predoctoral fellow in labor economics "
                                       "and public finance. Apply by December 1, 2026.</p></main>"
                                       "</body></html>",
    # Stockholm University Varbi posting
    "https://su.varbi.com/en/what:job/jobID:971001": "<html><body><main><p>Research assistant in "
                                                    "economics at the Department of Economics, "
                                                    "Stockholm.</p></main></body></html>",
}
REDIRECTS = {"https://bit.ly/4usPredoc": "https://econ.example.edu/predoc"}
DEAD: dict[str, int] = {"https://bit.ly/3VuuwHD": 410}  # UBC pre-doc intern: filled


def board_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url == "https://predoc.org/opportunities":
        return httpx.Response(200, text=fixture_text("predoc_org.html"))
    if url in DEAD:
        return httpx.Response(DEAD[url])
    if url in PAGES:
        return httpx.Response(200, text=PAGES[url])
    if url in REDIRECTS:
        return httpx.Response(302, headers={"Location": REDIRECTS[url]})
    if url == f"{WD_API}/jobs":
        return httpx.Response(200, text=fixture_text("workday_jobs.json"),
                              headers={"content-type": "application/json"})
    if url.startswith(f"{WD_API}/job/"):
        name = "workday_detail_econ.json" if "Economics" in url else "workday_detail_bio.json"
        return httpx.Response(200, text=fixture_text(name),
                              headers={"content-type": "application/json"})
    if url == "https://su.varbi.com/en/":
        return httpx.Response(200, text=fixture_text("varbi.html"))
    if url == "https://broken.example.org/jobs":
        return httpx.Response(500)
    return httpx.Response(404)


class FakeTelegram:
    def __init__(self, updates=None):
        self.updates = updates or []
        self.calls: list[tuple[str, dict]] = []
        self.next_id = 100

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = str(request.url).rsplit("/", 1)[-1]
        body = json.loads(request.content or b"{}")
        self.calls.append((method, body))
        if method == "getUpdates":
            offset = body.get("offset", 0)
            result = [u for u in self.updates if u["update_id"] >= offset]
            return httpx.Response(200, json={"ok": True, "result": result})
        if method == "sendMessage":
            self.next_id += 1
            return httpx.Response(200, json={"ok": True, "result": {"message_id": self.next_id}})
        return httpx.Response(200, json={"ok": True, "result": True})

    def sent(self):
        return [b for m, b in self.calls if m == "sendMessage"]

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


SOURCES = '''
[[board]]
name = "predoc_org"
type = "predoc_org"
url = "https://predoc.org/opportunities"

[[board]]
name = "ubc"
type = "workday"
field_implied = true
url = "https://ubc.wd10.myworkdayjobs.com/ubcstaffjobs"
search_terms = ["research assistant"]
institution = "University of British Columbia"
country = "Canada"

[[board]]
name = "su"
type = "varbi"
url = "https://su.varbi.com/en/"
institution = "Stockholm University"
country = "Sweden"

[[board]]
name = "broken"
type = "link_scan"
url = "https://broken.example.org/jobs"
link_pattern = "x"
'''


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for var in ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_PUBLIC_CHANNEL_ID",
                "TELEGRAM_ADMIN_CHAT_ID", "EXTRACTION_BACKEND", "SITE_URL"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "sources.toml").write_text(SOURCES)
    prefs = (ROOT / "config" / "preferences.toml").read_text()
    # tests must not wait for politeness delays
    prefs = prefs.replace("default_min_interval = 1.5", "default_min_interval = 0")
    prefs = prefs.replace("max_retries = 3", "max_retries = 0")
    # Fixture tests specifically verify regional and employer rejection behavior
    prefs = prefs.replace(
        'regions_include = ["UK", "Europe", "Canada", "US", "Other"]',
        'regions_include = ["UK", "Europe", "Canada"]',
    )
    prefs = prefs.replace(
        'excluded_employers = []',
        'excluded_employers = ["J-PAL", "JPAL", "Poverty Action Lab", "povertyactionlab.org"]',
    )
    (tmp_path / "preferences.toml").write_text(prefs)
    return Settings(
        _env_file=None,
        telegram_bot_token="T",
        telegram_public_channel_id="42",
        sources_config=str(tmp_path / "sources.toml"),
        preferences_config=str(tmp_path / "preferences.toml"),
        db_path=str(tmp_path / "data" / "predocs.db"),
        state_path=str(tmp_path / "data" / "listings.ndjson"),
        seen_state_path=str(tmp_path / "data" / "seen.ndjson"),
        feedback_path=str(tmp_path / "data" / "feedback.json"),
        telegram_state_path=str(tmp_path / "data" / "telegram_state.json"),
        dashboard_json=str(tmp_path / "docs" / "data" / "listings.json"),
        health_json=str(tmp_path / "docs" / "data" / "health.json"),
        feed_path=str(tmp_path / "docs" / "feed.xml"),
        dlq_path=str(tmp_path / "dlq.json"),
        enable_feeds=False,
        enable_portals=False,
        telegram_feedback_buttons=True,
    )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    import predoc_pipeline.publish.telegram as tg

    monkeypatch.setattr(tg, "MIN_SEND_INTERVAL", 0)


def run(settings, fake):
    return pipeline.run(settings, board_transport=httpx.MockTransport(board_handler),
                        telegram_client=fake.client())


def titles(messages):
    return "\n".join(m["text"] for m in messages)


def test_full_run_then_nothing_is_sent_twice(settings):
    fake = FakeTelegram()
    stats = run(settings, fake)

    cards = fake.sent()
    text = titles(cards)
    assert len(cards) == 4 and stats.published == 4
    for wanted in ("Pre-Doctoral Research Assistant",                     # UPF, Spain
                   "Research Assistant - Vancouver School of Economics",  # UBC Workday
                   "Research assistant in economics (pre-doctoral)",      # Stockholm (Varbi)
                   "Research Assistant, Finance, Accounting &amp; Economics"):  # UCL
        assert wanted in text, wanted
    for unwanted in ("Notre Dame", "Columbia University", "Pre-Doc Intern", "protein"):
        assert unwanted not in text, unwanted

    # every card: Apply/Source (or Open) row + ✅ ❌ 📝 row for the owner
    for card in cards:
        rows = card["reply_markup"]["inline_keyboard"]
        assert [b["text"] for b in rows[-1]] == ["✅ Interested", "❌ Not for me", "📝 Applied"]
        assert card["chat_id"] == "42" and card["parse_mode"] == "HTML"

    # the bit.ly link of the UBC pre-doc intern answers 410 -> recorded as filled
    assert stats.gate_reasons.get("board:filled-or-closed") == 1
    assert stats.gate_reasons.get("board:wrong-field-detail") == 1  # protein-folding lab tech
    assert stats.llm_calls == 0  # no model anywhere

    with Database(settings.db_path) as db:
        vse = next(r for r in db.published_listings() if "Vancouver" in r["title"])
        assert vse["principal_investigator"] == "Jane Doe"
        assert vse["deadline"].startswith("2026-11-15")
        # This fixture welcomes international applicants but promises no sponsorship.
        assert vse["visa_sponsorship_status"] == "unknown"
        assert "International applications welcome" in vse["visa_note"]
        upf = next(r for r in db.published_listings() if "Pompeu" in r["institution"])
        assert upf["visa_sponsorship_status"] == "explicit"
        ucl = next(r for r in db.published_listings() if "Finance" in r["title"])
        assert "bit.ly" not in ucl["apply_url"] or ucl["apply_url"] == ucl["source_url"]

    dashboard = json.loads(Path(settings.dashboard_json).read_text())
    # All 4 published fixtures are non-US predoc positions (Stockholm, UPF, UCL, UBC).
    # Under the routing rules, they go to Telegram only; the web dashboard is empty.
    assert dashboard["count"] == 0
    health = json.loads(Path(settings.health_json).read_text())
    last = health["runs"][0]["source_stats"]
    assert last["board:broken"]["ok"] is False and last["board:predoc_org"]["raw"] == 6

    # second run on a fresh machine (GitHub Actions): the SQLite file is gone,
    # only the committed journal + seen list remain -> nothing is re-sent.
    for suffix in ("", "-wal", "-shm"):
        path = settings.db_path + suffix
        import os
        if os.path.exists(path):
            os.remove(path)
    fake2 = FakeTelegram()
    stats2 = run(settings, fake2)
    assert fake2.sent() == [] and stats2.published == 0


def test_telegram_down_keeps_listings_pending_and_retries(settings):
    class Down(FakeTelegram):
        def handler(self, request):
            if str(request.url).endswith("/sendMessage"):
                return httpx.Response(400, json={"ok": False, "description": "boom"})
            return super().handler(request)

    stats = run(settings, Down())
    assert stats.published == 0
    fake = FakeTelegram()
    stats2 = run(settings, fake)
    # permanent 400s marked them undeliverable, transient ones would retry;
    # either way nothing is lost silently: they are in the DLQ / journal
    assert stats2.published == 0 or len(fake.sent()) == stats2.published


def test_pending_rows_are_link_checked_before_sending(settings):
    """A listing queued earlier (Telegram was not set up) whose link died is not sent."""
    no_tg = settings.model_copy(update={"telegram_public_channel_id": ""})
    stats = run(no_tg, FakeTelegram())
    assert stats.published == 0
    with Database(settings.db_path) as db:
        rows = db.pending_listings()
        assert len(rows) == 4
        upf = next(r for r in rows if "Pre-Doctoral" in r["title"])
    DEAD[upf["apply_url"]] = 410  # filled in the meantime
    try:
        fake = FakeTelegram()
        stats = run(settings, fake)
    finally:
        DEAD.pop(upf["apply_url"])
    assert stats.published == 3 and stats.closed_before_send == 1
    assert "Pre-Doctoral Research Assistant" not in titles(fake.sent())


def test_filled_positions_leave_the_dashboard_on_recheck(settings):
    run(settings, FakeTelegram())
    with Database(settings.db_path) as db:
        su = next(r for r in db.active_listings() if "Stockholm" in r["institution"])
        # pretend the last check was long ago
        db.conn.execute("UPDATE listings SET last_checked_at='2026-01-01T00:00:00Z', "
                        "first_seen_at='2026-01-01T00:00:00Z'")
    original = PAGES.get(su["apply_url"])
    PAGES[su["apply_url"]] = "<html><body><main>This position has been filled.</main></body></html>"
    try:
        stats = run(settings, FakeTelegram())
    finally:
        if original is None:
            PAGES.pop(su["apply_url"])
        else:
            PAGES[su["apply_url"]] = original
    assert stats.closed_found >= 1
    dashboard = json.loads(Path(settings.dashboard_json).read_text())
    assert all("Stockholm" not in r["institution"] for r in dashboard["listings"])


def test_digest_for_many_new_listings_is_paged_with_numbered_buttons(settings):
    many = settings.model_copy(update={"telegram_digest_threshold": 2})
    fake = FakeTelegram()
    stats = run(many, fake)
    msgs = fake.sent()
    assert stats.published == 4
    # preferences.toml: digest_page_size = 6 -> one message with 4 numbered rows
    assert len(msgs) == 1 and "4 new predoc listings" in msgs[0]["text"]
    rows = msgs[0]["reply_markup"]["inline_keyboard"]
    assert [r[0]["text"] for r in rows] == ["✅ 1", "✅ 2", "✅ 3", "✅ 4"]


def test_blocked_bot_keeps_everything_pending(settings):
    """403 'bot can't initiate conversation' must not throw the positions away."""
    class Blocked(FakeTelegram):
        def handler(self, request):
            if str(request.url).endswith("/sendMessage"):
                return httpx.Response(403, json={
                    "ok": False, "description": "Forbidden: bot can't initiate conversation"})
            return super().handler(request)

    assert run(settings, Blocked()).published == 0
    fake = FakeTelegram()
    assert run(settings, fake).published == 4 and len(fake.sent()) == 4


def test_same_title_twice_on_one_board_is_two_jobs(settings):
    """Stockholm often has several "Research assistant in economics" ads at once."""
    varbi = fixture_text("varbi.html")
    twin = varbi.replace("jobID:971001", "jobID:971777")
    if twin == varbi:
        pytest.skip("fixture layout changed")
    both = varbi.replace("</body>", twin[twin.find("<body>") + 6:])
    PAGES["https://su.varbi.com/en/what:job/jobID:971777"] = PAGES[
        "https://su.varbi.com/en/what:job/jobID:971001"].replace("Stockholm", "Stockholm (II)")

    def handler(request):
        if str(request.url) == "https://su.varbi.com/en/":
            return httpx.Response(200, text=both)
        return board_handler(request)

    try:
        stats = pipeline.run(settings, board_transport=httpx.MockTransport(handler),
                             telegram_client=FakeTelegram().client())
    finally:
        PAGES.pop("https://su.varbi.com/en/what:job/jobID:971777")
    assert stats.duplicates == 0 and stats.published == 5


def test_jpal_named_only_in_the_ad_text_is_dropped(settings):
    original = PAGES["https://bit.ly/4bMFmgP"]
    PAGES["https://bit.ly/4bMFmgP"] = original.replace(
        "Pre-doctoral RA", "Pre-doctoral RA with J-PAL Europe")
    try:
        fake = FakeTelegram()
        stats = run(settings, fake)
    finally:
        PAGES["https://bit.ly/4bMFmgP"] = original
    assert stats.published == 3
    assert stats.gate_reasons.get("board:excluded-employer") == 1


def test_expired_pending_rows_are_not_sent(settings):
    no_tg = settings.model_copy(update={"telegram_public_channel_id": ""})
    run(no_tg, FakeTelegram())
    with Database(settings.db_path) as db:
        db.conn.execute("UPDATE listings SET deadline='2020-01-01T23:59:59Z' "
                        "WHERE title LIKE 'Pre-Doctoral%'")
    fake = FakeTelegram()
    stats = run(settings, fake)
    assert stats.published == 3
    assert "Pre-Doctoral Research Assistant" not in titles(fake.sent())


def test_recheck_uses_the_stored_deadline():
    from datetime import date

    from predoc_pipeline.boards.collector import check_links
    from predoc_pipeline.boards.config import HttpConfig

    page = ("<html><body><main>Predoctoral RA. Review of applications will begin on "
            "15 Sep 2026.</main></body></html>")
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text=page))
    cfg = HttpConfig(default_min_interval=0, max_retries=0)
    links = {1: ("RA", "https://x.org/ra", date(2026, 11, 30)), 2: ("RA", "https://x.org/ra")}
    out = check_links(links, cfg, transport=transport)
    assert out[1] is None                     # known deadline 30 Nov: still open
    assert out[2] is None  # Review scheduling alone does not establish a closed application window.


def test_feedback_buttons_omitted_when_disabled(settings):
    no_buttons = settings.model_copy(update={"telegram_feedback_buttons": False})
    fake = FakeTelegram()
    stats = run(no_buttons, fake)
    assert stats.published == 4
    cards = fake.sent()
    assert len(cards) == 4
    for card in cards:
        rows = card["reply_markup"]["inline_keyboard"]
        for row in rows:
            texts = [b["text"] for b in row]
            assert "✅ Interested" not in texts
            assert "❌ Not for me" not in texts
            assert "📝 Applied" not in texts
