"""Unit tests for the dependency-free core.

Written against `unittest` rather than pytest fixtures so the whole suite runs
with `python -m unittest` on a bare interpreter -- useful when diagnosing a
broken environment, and it still collects cleanly under pytest in CI.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from predoc_pipeline.core import gating
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.dedupe import Deduplicator
from predoc_pipeline.core.fuzzy import token_sort_ratio
from predoc_pipeline.core.minhash import MinHash, MinHashLSH, jaccard
from predoc_pipeline.core.ratelimit import QuotaExceeded, RateLimiter, quota_day
from predoc_pipeline.core.textproc import (
    escape_telegram_html,
    hashtag,
    html_to_text,
    language_hint,
    telegram_visible_length,
    truncate,
    word_shingles,
)
from predoc_pipeline.core.timeparse import days_between, format_ts, parse_datetime
from predoc_pipeline.core.urls import (
    canonicalize_url,
    composite_key,
    content_hash,
    url_hash,
)

UTC = UTC


class TestUrls(unittest.TestCase):
    def test_tracking_params_removed(self):
        self.assertEqual(
            url_hash("https://example.org/job?id=1&utm_source=x&fbclid=abc"),
            url_hash("https://example.org/job?id=1"),
        )

    def test_query_order_and_fragment_irrelevant(self):
        self.assertEqual(
            url_hash("https://example.org/j?b=2&a=1#apply"),
            url_hash("https://example.org/j?a=1&b=2"),
        )

    def test_host_case_www_and_default_port(self):
        self.assertEqual(
            url_hash("HTTPS://WWW.Example.ORG:443/Job/"),
            url_hash("https://example.org/Job"),
        )

    def test_www_kept_for_bare_two_label_host(self):
        # www.co.uk-style edge: only strip www when a real subdomain remains.
        self.assertEqual(canonicalize_url("https://www.jobs.ac.uk/x"), "https://jobs.ac.uk/x")

    def test_path_case_is_significant(self):
        self.assertNotEqual(url_hash("https://example.org/A"), url_hash("https://example.org/a"))

    def test_percent_encoding_normalised(self):
        self.assertEqual(
            canonicalize_url("https://example.org/a%2Db"),
            canonicalize_url("https://example.org/a-b"),
        )

    def test_scheme_relative_and_bare_host(self):
        self.assertEqual(canonicalize_url("example.org/x"), "https://example.org/x")

    def test_empty_and_garbage_do_not_raise(self):
        self.assertEqual(canonicalize_url(""), "")
        self.assertIsInstance(canonicalize_url("http://[bad"), str)

    def test_content_hash_ignores_whitespace_and_case(self):
        self.assertEqual(content_hash("Hello   World\n"), content_hash("hello world"))

    def test_composite_key_strips_punctuation(self):
        self.assertEqual(
            composite_key("LSE", "Predoc", "Prof. Ada Lovelace"),
            composite_key("lse", "predoc", "Prof Ada Lovelace"),
        )


class TestTextProc(unittest.TestCase):
    def test_html_to_text_drops_script_and_keeps_structure(self):
        html = "<div><p>One</p><script>evil()</script><ul><li>Two</li></ul></div>"
        text = html_to_text(html)
        self.assertIn("One", text)
        self.assertIn("Two", text)
        self.assertNotIn("evil", text)

    def test_html_entities_decoded(self):
        self.assertIn("R&D", html_to_text("<p>R&amp;D</p>"))

    def test_telegram_escape_is_exactly_three_entities(self):
        self.assertEqual(escape_telegram_html('a<b>&"c'), 'a&lt;b&gt;&amp;"c')

    def test_visible_length_counts_parsed_characters(self):
        html = "<b>A&amp;B</b>"
        # Telegram counts "A&B" = 3, not the 14 raw characters.
        self.assertEqual(telegram_visible_length(html), 3)

    def test_hashtag_strips_accents_and_punctuation(self):
        self.assertEqual(hashtag("Côte d'Ivoire"), "CoteDIvoire")
        self.assertEqual(hashtag("Behavioral/Experimental Economics"),
                         "BehavioralExperimentalEconomics")
        self.assertEqual(hashtag("!!!"), "")

    def test_truncate_prefers_word_boundary(self):
        out = truncate("alpha beta gamma delta", 14)
        self.assertLessEqual(len(out), 14)
        self.assertTrue(out.endswith("\u2026"))

    def test_language_hint(self):
        self.assertEqual(language_hint("We are hiring a research assistant"), "en")
        self.assertEqual(
            language_hint("Wissenschaftliche Mitarbeiterin gesucht, Bewerbung bis Juni, "
                          "Universität Bonn, befristet und Vergütung nach TV-L"),
            "de",
        )

    def test_word_shingles_short_text(self):
        self.assertEqual(word_shingles("a b", 5), {"a b"})


class TestMinHash(unittest.TestCase):
    def test_estimator_is_close_to_true_jaccard(self):
        a = {f"token{i}" for i in range(200)}
        b = {f"token{i}" for i in range(50, 250)}
        exact = jaccard(a, b)
        est = MinHash.from_tokens(a, 128).jaccard(MinHash.from_tokens(b, 128))
        # 128 permutations => standard error ~0.088; allow 3 sigma.
        self.assertLess(abs(est - exact), 0.27)

    def test_identical_sets_are_one(self):
        a = {"x", "y", "z"}
        self.assertEqual(MinHash.from_tokens(a, 64).jaccard(MinHash.from_tokens(a, 64)), 1.0)

    def test_empty_token_set_returns_none(self):
        # Critical: two empty signatures would otherwise report Jaccard 1.0.
        self.assertIsNone(MinHash.from_tokens([], 128))

    def test_signature_is_stable_across_instances(self):
        first = MinHash.from_tokens(["alpha", "beta"], 32)
        second = MinHash.from_tokens(["beta", "alpha"], 32)
        self.assertEqual(first.values, second.values)

    def test_bytes_roundtrip(self):
        sig = MinHash.from_tokens(["a", "b", "c"], 32)
        self.assertEqual(MinHash.from_bytes(sig.to_bytes()).values, sig.values)

    def test_banding_probability_curve(self):
        lsh = MinHashLSH(threshold=0.85, num_perm=128)
        self.assertEqual(lsh.bands * lsh.rows, 128)
        self.assertLess(lsh.probability(0.4), 0.1)
        self.assertGreater(lsh.probability(0.95), 0.9)

    def test_lsh_retrieves_near_duplicate(self):
        lsh = MinHashLSH(threshold=0.6, num_perm=128)
        base = {f"w{i}" for i in range(100)}
        lsh.insert(1, MinHash.from_tokens(base, 128))
        near = MinHash.from_tokens(base | {"w100", "w101"}, 128)
        key, score = lsh.best_match(near)
        self.assertEqual(key, 1)
        self.assertGreater(score, 0.9)


class TestFuzzy(unittest.TestCase):
    def test_identical_is_hundred(self):
        self.assertEqual(token_sort_ratio("a b c", "a b c"), 100.0)

    def test_token_order_ignored(self):
        self.assertEqual(token_sort_ratio("lse predoc", "predoc lse"), 100.0)

    def test_unrelated_is_low(self):
        self.assertLess(token_sort_ratio("lse predoc economics", "acme senior devops"), 60.0)


class TestDeduplicator(unittest.TestCase):
    LONG = (
        "We are hiring a predoctoral research fellow in applied microeconomics at the "
        "London School of Economics. The post is a two year full time appointment "
        "starting in September and is suitable for candidates preparing to apply for "
        "doctoral study. Applicants should have strong quantitative skills and "
        "experience with Stata or R. Applications close on the first of March."
    )

    def _seeded(self, **kwargs):
        dedup = Deduplicator(**kwargs)
        dedup.add(
            1,
            text=self.LONG,
            institution="London School of Economics",
            title="Predoctoral Research Fellow in Applied Microeconomics",
            principal_investigator="Prof. Ada Lovelace",
            deadline="2027-03-01T23:59:00Z",
        )
        return dedup

    def test_minhash_catches_reworded_crosspost(self):
        dedup = self._seeded(jaccard_threshold=0.6)
        variant = self.LONG.replace("We are hiring", "The department is hiring")
        hit = dedup.find(
            text=variant,
            institution="London School of Economics",
            title="Predoctoral Research Fellow",
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit.tier, "minhash")

    def test_fuzzy_catches_short_social_post(self):
        dedup = self._seeded(jaccard_threshold=0.99, fuzzy_threshold=80.0)
        hit = dedup.find(
            text="hiring a predoc, DM me",
            institution="London School of Economics",
            title="Predoctoral Research Fellow in Applied Microeconomics",
            principal_investigator="Prof Ada Lovelace",
            deadline="2027-03-05T00:00:00Z",
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit.tier, "fuzzy")

    def test_distant_deadline_blocks_fuzzy_match(self):
        dedup = self._seeded(jaccard_threshold=0.99, fuzzy_threshold=80.0)
        hit = dedup.find(
            text="hiring a predoc",
            institution="London School of Economics",
            title="Predoctoral Research Fellow in Applied Microeconomics",
            principal_investigator="Prof Ada Lovelace",
            deadline="2028-11-01T00:00:00Z",
        )
        self.assertIsNone(hit)

    def test_unrelated_listing_is_not_a_duplicate(self):
        dedup = self._seeded()
        hit = dedup.find(
            text="Senior machine learning engineer at a fintech, equity offered.",
            institution="Acme Capital",
            title="Senior ML Engineer",
        )
        self.assertIsNone(hit)

    def test_two_empty_texts_do_not_match(self):
        dedup = Deduplicator()
        dedup.add(1, text="", institution="A", title="")
        self.assertIsNone(dedup.find(text="", institution="B", title=""))


class TestGating(unittest.TestCase):
    REAL = (
        "The Department of Economics is hiring a full-time predoctoral research "
        "assistant to work with Prof. Smith on applied microeconomics projects. "
        "Applications are invited from candidates with strong Stata and R skills. "
        "Closing date: 2027-03-01."
    )

    def test_accepts_real_advert(self):
        result = gating.evaluate(self.REAL)
        self.assertTrue(result.passed)
        self.assertGreater(result.score, 0.7)
        self.assertIn("deadline", result.signals)

    def test_rejects_completion_post(self):
        text = ("I just finished my predoc at the Federal Reserve and I am so grateful "
                "to everyone who supported me over the last two years of this journey.")
        self.assertFalse(gating.evaluate(text).passed)

    def test_rejects_phd_studentship(self):
        # The dominant false positive on European research portals.
        text = ("Applications are invited for a fully funded PhD studentship in "
                "economics at the University of Bonn. The doctoral candidate will "
                "work on macroeconomic modelling. Closing date 2027-01-15.")
        result = gating.evaluate(text)
        self.assertFalse(result.passed)
        self.assertIn("phd-studentship", result.reason)

    def test_rejects_postdoc(self):
        text = ("We are recruiting a postdoctoral research fellow in econometrics. "
                "Applications are invited. A PhD is required. Closing date 2027-02-01.")
        self.assertFalse(gating.evaluate(text).passed)

    def test_rejects_faculty(self):
        text = ("The School of Economics invites applications for a tenure-track "
                "assistant professor position. Applications are invited by March.")
        self.assertFalse(gating.evaluate(text).passed)

    def test_rejects_paper_promotion(self):
        text = ("Our new working paper on the returns to predoctoral experience is "
                "out today, joint with several coauthors. Comments are welcome.")
        self.assertFalse(gating.evaluate(text).passed)

    def test_requires_positive_role_term(self):
        text = ("We are hiring a marketing coordinator for our growing team. "
                "Applications are invited before the closing date of March.")
        result = gating.evaluate(text)
        self.assertFalse(result.passed)
        self.assertEqual(result.reason, "no-role-term")

    def test_requires_hiring_intent(self):
        text = ("A predoctoral research assistant typically spends two years working "
                "with faculty before applying to doctoral programmes in economics.")
        self.assertEqual(gating.evaluate(text).reason, "no-hiring-intent")

    def test_accepts_german_advert(self):
        text = ("Die Universität Bonn sucht eine wissenschaftliche Mitarbeiterin "
                "(TV-L E13, ohne Promotion) für ein volkswirtschaftliches "
                "Forschungsprojekt. Bewerbungsfrist ist der 01.03.2027.")
        result = gating.evaluate(text)
        self.assertTrue(result.passed)
        self.assertEqual(result.language, "de")

    def test_accepts_french_advert(self):
        text = ("L'université recrute un ingénieur d'études en recherche économique. "
                "Les candidatures sont ouvertes, date limite le 01/03/2027. "
                "Le poste est à temps plein au sein du laboratoire.")
        self.assertTrue(gating.evaluate(text).passed)

    def test_too_short_is_rejected(self):
        self.assertEqual(gating.evaluate("hiring a predoc").reason, "too-short")

    def test_blend_lets_rule_score_veto(self):
        confident_but_unsupported = gating.blend_confidence(0.99, 0.05)
        confident_and_supported = gating.blend_confidence(0.99, 0.95)
        self.assertLess(confident_but_unsupported, 0.7)
        self.assertGreater(confident_and_supported, 0.9)


class TestGateScoping(unittest.TestCase):
    """Real predoc adverts mention PhD students, PhD programs and professors."""

    ADS = {
        "phd students": ("Predoctoral Research Assistant",
                         "The centre invites applications for a full-time predoctoral research "
                         "assistant. The RA will work closely with faculty and PhD students. "
                         "Applications are invited until 15 January 2027."),
        "phd program": ("Pre-doctoral Fellow",
                        "The fellow will work with Assistant Professor Jane Doe. The position is "
                        "ideal preparation for a PhD program in economics. Apply by 1 March 2027."),
        "german chair": ("Research Assistant (Predoc)",
                         "The Chair of Public Economics is hiring a research assistant for two "
                         "years. Application deadline: 30 November 2026."),
        "lecturers": ("Predoc Research Fellow",
                      "The university is recruiting predoctoral research fellows who will "
                      "collaborate with a lecturer in finance. Deadline 10/12/2026."),
    }

    def test_passing_mentions_do_not_reject(self):
        for name, (title, text) in self.ADS.items():
            with self.subTest(name):
                result = gating.evaluate(text, title=title)
                self.assertTrue(result.passed, result.reason)

    def test_the_subject_still_rejects(self):
        cases = [
            ("Postdoctoral Research Fellow", "We are hiring. Closing date 1 May 2027.", "postdoc"),
            ("Assistant Professor of Economics", "Applications are invited.", "faculty"),
            ("Research position", "Applications are invited for a fully funded PhD studentship "
                                  "in economics.", "phd-studentship"),
        ]
        for title, text, label in cases:
            with self.subTest(title):
                self.assertEqual(gating.evaluate(text, title=title).reason, f"reject:{label}")

    def test_pre_doctoral_titles_are_not_phd_jobs(self):
        for title in ("Pre-doctoral Researcher in Economics", "Pre-doctoral position in finance",
                      "Pre-doctoral Fellowship", "Pre-PhD position (economics)",
                      "Pre doctoral fellowship, labour economics"):
            with self.subTest(title):
                result = gating.evaluate("We are hiring. Closing date 1 March 2027.", title=title)
                self.assertTrue(result.passed, result.reason)
        self.assertFalse(gating.evaluate("Apply now.", title="Doctoral position in economics",
                                         known_vacancy=True).passed)

    def test_board_page_navigation_does_not_reject(self):
        page = ("Jobs | PhD positions | Postdoc positions | Contact. Predoctoral research "
                "assistant in economics, two years, Barcelona.")
        self.assertFalse(gating.evaluate(page, title="Predoctoral Research Assistant").passed)
        self.assertTrue(gating.evaluate(page, title="Predoctoral Research Assistant",
                                        known_vacancy=True).passed)
        self.assertFalse(gating.evaluate(page, title="Postdoctoral Researcher",
                                         known_vacancy=True).passed)

    def test_known_vacancy_needs_no_hiring_verb(self):
        self.assertFalse(gating.evaluate("Junior economist, macro team.",
                                         title="Junior Economist").passed)
        result = gating.evaluate("Junior economist, macro team.", title="Junior Economist",
                                 known_vacancy=True)
        self.assertTrue(result.passed)
        self.assertGreaterEqual(result.score, 0.55)


class TestTimeParse(unittest.TestCase):
    def test_iso_with_z(self):
        parsed = parse_datetime("2027-03-01T23:59:00Z")
        self.assertEqual(parsed.tzinfo, UTC)
        self.assertEqual(parsed.year, 2027)

    def test_naive_becomes_utc(self):
        self.assertEqual(parse_datetime("2027-03-01").tzinfo, UTC)

    def test_european_formats(self):
        for value in ("01/03/2027", "01.03.2027", "1 March 2027"):
            with self.subTest(value=value):
                self.assertEqual(parse_datetime(value).month, 3)

    def test_unparseable_returns_none(self):
        self.assertIsNone(parse_datetime("rolling basis"))
        self.assertIsNone(parse_datetime(None))

    def test_days_between_mixed_awareness_does_not_raise(self):
        naive = datetime(2027, 3, 1)
        aware = datetime(2027, 3, 15, tzinfo=UTC)
        self.assertEqual(days_between(naive, aware), 14)

    def test_format_is_sortable(self):
        early = format_ts(datetime(2027, 1, 1, tzinfo=UTC))
        late = format_ts(datetime(2027, 1, 2, tzinfo=UTC))
        self.assertLess(early, late)
        self.assertTrue(late.endswith("Z"))


class TestRateLimiter(unittest.TestCase):
    def test_daily_budget_applies_safety_margin(self):
        limiter = RateLimiter(requests_per_day=100, safety_margin=0.9)
        self.assertEqual(limiter.daily_budget, 90)

    def test_budget_exhaustion_raises(self):
        limiter = RateLimiter(requests_per_minute=600, requests_per_day=2, safety_margin=1.0)
        slept: list[float] = []
        limiter.acquire(sleep=slept.append)
        limiter.record()
        limiter.acquire(sleep=slept.append)
        limiter.record()
        with self.assertRaises(QuotaExceeded):
            limiter.acquire(sleep=slept.append)

    def test_token_bucket_sleeps_when_drained(self):
        limiter = RateLimiter(requests_per_minute=1, requests_per_day=1000)
        slept: list[float] = []
        limiter.acquire(sleep=slept.append)   # first call uses the initial allowance
        limiter.acquire(sleep=slept.append)
        self.assertTrue(any(s > 0 for s in slept))

    def test_concurrent_waiters_reserve_slots(self):
        limiter = RateLimiter(requests_per_minute=60, requests_per_day=1000)
        # Drain allowance
        limiter._allowance = 0.0
        slept: list[float] = []
        limiter.acquire(sleep=slept.append)
        limiter.acquire(sleep=slept.append)
        limiter.acquire(sleep=slept.append)
        # Each consecutive waiter reserves another slot and sleeps proportionally longer
        self.assertEqual(len(slept), 3)
        self.assertAlmostEqual(slept[0], 1.0, places=1)
        self.assertAlmostEqual(slept[1], 2.0, places=1)
        self.assertAlmostEqual(slept[2], 3.0, places=1)

    def test_penalise_preserves_future_wait(self):
        limiter = RateLimiter(requests_per_minute=60, requests_per_day=1000)
        limiter.penalise(3.0)
        slept: list[float] = []
        limiter.acquire(sleep=slept.append)
        self.assertTrue(len(slept) == 1 and slept[0] >= 3.0)

    def test_quota_day_uses_pacific_reset(self):
        # 03:00 UTC on 2 June is still 1 June in Los Angeles.
        moment = datetime(2027, 6, 2, 3, 0, tzinfo=UTC)
        self.assertEqual(quota_day(moment), "2027-06-01")
        self.assertEqual(quota_day(datetime(2027, 6, 2, 18, 0, tzinfo=UTC)), "2027-06-02")


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self._tmp.name) / "test.db")
        init(self.path)
        self.db = Database(self.path)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _listing(self, **overrides):
        values = {
            "url_hash": url_hash("https://example.org/apply"),
            "apply_url": "https://example.org/apply",
            "source_url": "https://example.org/source",
            "source": "feeds",
            "title": "Predoctoral Research Fellow",
            "institution": "London School of Economics",
            "principal_investigator": "Prof. Ada Lovelace",
            "country": "United Kingdom",
            "city": "London",
            "is_remote": 0,
            "duration_years": 2.0,
            "deadline": "2027-03-01T23:59:00Z",
            "disciplines": '["Applied Microeconomics"]',
            "visa_sponsorship_status": "inferred",
            "summary": "A two-year predoctoral appointment.",
            "language": "en",
            "model_confidence": 0.9,
            "rule_score": 0.8,
            "confidence": 0.87,
            "signature": None,
            "first_seen_at": None,
            "last_seen_at": None,
            "status": "pending",
        }
        values.update(overrides)
        return values

    def test_insert_and_publish_lifecycle(self):
        listing_id = self.db.insert_listing(self._listing())
        self.assertEqual(len(self.db.pending_listings()), 1)
        self.db.mark_published(listing_id, 4242)
        self.assertEqual(len(self.db.pending_listings()), 0)
        row = self.db.listing(listing_id)
        self.assertEqual(row["telegram_message_id"], 4242)
        self.assertEqual(row["status"], "published")

    def test_url_hash_is_unique(self):
        self.db.insert_listing(self._listing())
        import sqlite3

        with self.assertRaises(sqlite3.IntegrityError):
            self.db.insert_listing(self._listing())

    def test_web_publication_is_not_pending_without_telegram_id(self):
        listing_id = self.db.insert_listing(self._listing(deadline=None))
        self.db.mark_published(listing_id, None)
        self.assertEqual(self.db.pending_listings(), [])
        self.assertIsNone(self.db.listing(listing_id)["telegram_message_id"])

    def test_unpublished_remains_pending_without_credentials(self):
        listing_id = self.db.insert_listing(self._listing(status="unpublished", deadline=None))
        self.assertEqual([r["id"] for r in self.db.pending_listings()], [listing_id])

    def test_alternate_sources_are_deduplicated(self):
        listing_id = self.db.insert_listing(self._listing())
        for url in ("https://a/1", "https://a/1", "https://a/2"):
            self.db.add_alternate_source(listing_id, url)
        import json

        stored = json.loads(self.db.listing(listing_id)["alternate_sources"])
        self.assertEqual(stored, ["https://a/1", "https://a/2"])

    def test_seen_items_gate(self):
        h = url_hash("https://example.org/x")
        self.assertIsNone(self.db.seen(h))
        self.db.mark_seen(h, source="feeds", decision="rejected", reason="no-role-term")
        row = self.db.seen(h)
        self.assertEqual(row["decision"], "rejected")
        self.db.mark_seen(h, source="feeds", decision="published", listing_id=7)
        self.assertEqual(self.db.seen(h)["listing_id"], 7)

    def test_recent_listings_uses_comparable_timestamp_format(self):
        """Regression guard for mixed timestamp formats.

        The interesting case is two rows on the *same calendar day*: a naive
        lexicographic comparison of "2027-03-01T08:00:00+00:00" against
        SQLite's "2027-03-01 08:00:00" appears to work whenever the dates
        differ, and fails silently when they do not.
        """
        self.db.insert_listing(self._listing())
        old = format_ts(datetime.now(UTC) - timedelta(days=45))
        self.db.conn.execute("UPDATE listings SET first_seen_at=?", (old,))

        recent = format_ts(datetime.now(UTC) - timedelta(hours=2))
        self.db.insert_listing(
            self._listing(
                url_hash=url_hash("https://example.org/apply-2"),
                apply_url="https://example.org/apply-2",
                first_seen_at=recent,
                last_seen_at=recent,
            )
        )
        self.assertEqual(len(self.db.recent_listings(30)), 1)
        self.assertEqual(len(self.db.recent_listings(60)), 2)

    def test_expiry_sweep(self):
        past = format_ts(datetime.now(UTC) - timedelta(days=30))
        self.db.insert_listing(self._listing(deadline=past))
        self.assertEqual(self.db.expire_past_deadline(grace_days=1), 1)
        self.assertEqual(self.db.counts()["expired"], 1)

    def test_llm_usage_accumulates(self):
        day = quota_day()
        self.assertEqual(self.db.llm_usage(day), (0, 0))
        self.db.record_llm_call(day, tokens=1200)
        self.db.record_llm_call(day, tokens=800)
        self.assertEqual(self.db.llm_usage(day), (2, 2000))

    def test_consecutive_empty_runs(self):
        for _ in range(3):
            row = self.db.start_run("r")
            self.db.finish_run(row, {"published": 0}, {})
        self.assertEqual(self.db.consecutive_empty_runs(), 3)
        row = self.db.start_run("r")
        self.db.finish_run(row, {"published": 2}, {})
        self.assertEqual(self.db.consecutive_empty_runs(), 0)

    def test_export_import_roundtrip(self):
        self.db.insert_listing(self._listing())
        records = self.db.export_rows()
        self.assertEqual(records[0]["disciplines"], ["Applied Microeconomics"])

        other = str(Path(self._tmp.name) / "restored.db")
        init(other)
        with Database(other) as restored:
            self.assertEqual(restored.import_rows(records), 1)
            self.assertEqual(restored.counts()["listings"], 1)

    def test_prune_keeps_seen_items_linked_to_listings(self):
        listing_id = self.db.insert_listing(self._listing())
        self.db.mark_seen("h1", source="s", decision="published", listing_id=listing_id)
        self.db.mark_seen("h2", source="s", decision="rejected")
        stale = format_ts(datetime.now(UTC) - timedelta(days=500))
        self.db.conn.execute("UPDATE seen_items SET last_seen_at=?", (stale,))
        self.db.prune(dlq_days=0, seen_days=400)
        self.assertIsNotNone(self.db.seen("h1"))
        self.assertIsNone(self.db.seen("h2"))

    def test_transaction_rolls_back(self):
        from predoc_pipeline.core.db import transaction

        with self.assertRaises(ValueError), transaction(self.db.conn):
            self.db.conn.execute(
                "INSERT INTO meta(key, value) VALUES('x','1')"
            )
            raise ValueError("boom")
        self.assertIsNone(self.db.get_meta("x"))

    def test_multithreaded_database_access(self):
        from concurrent.futures import ThreadPoolExecutor

        def worker(i: int):
            self.db.record_llm_call("2026-10-03", tokens=10 * i)
            return self.db.llm_usage("2026-10-03")

        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(worker, range(10)))

        self.assertEqual(len(results), 10)
        reqs, tokens = self.db.llm_usage("2026-10-03")
        self.assertEqual(reqs, 10)
        self.assertEqual(tokens, 450)

    def test_search_listings(self):
        lid1 = self.db.insert_listing(self._listing(
            url_hash="h_srch1",
            title="Pre-Doctoral Fellow in Econometrics",
            institution="University of Oxford",
            summary="Working on causal inference and microeconometrics.",
        ))
        lid2 = self.db.insert_listing(self._listing(
            url_hash="h_srch2",
            title="Research Assistant",
            institution="Bocconi University",
            summary="Financial economics project.",
        ))
        self.db.mark_published(lid1, 101)
        self.db.mark_published(lid2, 102)

        # Keyword in title
        res = self.db.search_listings("econometrics")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["id"], lid1)

        # Keyword in institution
        res = self.db.search_listings("Bocconi")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["id"], lid2)

        # Keyword in summary
        res = self.db.search_listings("causal inference")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["id"], lid1)

        # Empty search
        self.assertEqual(self.db.search_listings(""), [])

        # Active-only filtering
        self.db.mark_closed(lid1, "Filled")
        self.assertEqual(len(self.db.search_listings("econometrics", active_only=True)), 0)
        self.assertEqual(len(self.db.search_listings("econometrics", active_only=False)), 1)

    def test_optimize_and_indexes(self):
        self.db.optimize()
        indexes = {
            row["name"]
            for row in self.db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        self.assertIn("ix_listings_apply_url", indexes)
        self.assertIn("ix_listings_source_url", indexes)
        self.assertIn("ix_listings_active", indexes)
        self.assertIn("ix_listings_identity", indexes)
        self.assertIn("ix_listings_pending", indexes)

    def test_migrate_plain_tuple_connection(self):
        import sqlite3

        from predoc_pipeline.core.db import _migrate

        raw_conn = sqlite3.connect(":memory:")
        raw_conn.execute("CREATE TABLE listings (id INT, url_hash TEXT)")
        _migrate(raw_conn)
        cols = {r[1] for r in raw_conn.execute("PRAGMA table_info(listings)")}
        self.assertIn("deadline_note", cols)
        self.assertIn("x_post_id", cols)
        raw_conn.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
