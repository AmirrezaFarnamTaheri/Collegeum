"""Public vacancy and historical PhD Telegram sends need pre-send durable identities."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from predoc_pipeline import pipeline
from predoc_pipeline.boards.config import load_preferences
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.urls import url_hash
from predoc_pipeline.models import Discipline, Location, PredocListing
from predoc_pipeline.publish.telegram import TelegramError
from predoc_pipeline.publish.telegram_intents import GitHubIntentReserver
from predoc_pipeline.routing import Router
from predoc_pipeline.settings import Settings


def _item(suffix: str, *, source: str = "shared", phd: bool = False) -> PredocListing:
    return PredocListing(
        title="PhD Researcher in Economics" if phd else "Research Assistant in Economics",
        institution="Example University",
        location=Location(country="Germany", city="Berlin"),
        disciplines=[Discipline.APPLIED_MICRO],
        apply_url=f"https://example.org/jobs/{suffix}",
        source_url=f"https://example.org/adverts/{source}",
        summary="Quantitative research and applied economics",
    )


def _add(db: Database, listing: PredocListing) -> int:
    return db.insert_listing(pipeline._listing_row(listing, source="test", signature=None))


def _config(*, phd: bool = False) -> Settings:
    return Settings(
        _env_file=None, telegram_bot_token="offline-test",
        telegram_public_channel_id="@existing",
        telegram_non_us_econ_phd_enabled=phd,
    )


def test_every_url_in_connected_alias_group_reserved_before_single_channel_post(tmp_path):
    path = tmp_path / "db.sqlite"
    init(path)
    a = _item("first")
    b = _item("second")
    keys = {url_hash(url)[:32] for url in (a.apply_url, b.apply_url, a.source_url)}
    observed: set[str] = set()

    def reserve(namespace, key, operation):
        assert namespace == "vacancies" and operation == "initial"
        observed.add(key)

    telegram = Mock()

    def send(**kwargs):
        assert observed == keys
        return 901

    telegram.send_message.side_effect = send
    with Database(path) as db:
        ids = [_add(db, a), _add(db, b)]
        stats = pipeline.RunStats()
        pipeline._broadcast(
            list(zip(ids, (a, b), strict=True)), telegram, _config(), db, stats,
            reserve_intent=reserve,
        )
        assert stats.published == 1
        assert telegram.send_message.call_count == 1
        assert [db.listing(i)["telegram_message_id"] for i in ids] == [901, 901]


def test_failed_alias_reservation_holds_entire_group_without_telegram_send(tmp_path):
    path = tmp_path / "db.sqlite"
    init(path)
    listings = [_item("first"), _item("second")]
    telegram = Mock()
    seen = []

    def reserve(namespace, key, operation):
        seen.append(key)
        if len(seen) == 2:
            raise OSError("GitHub reservation collision or timeout")

    with Database(path) as db:
        ids = [_add(db, item) for item in listings]
        stats = pipeline.RunStats()
        pipeline._broadcast(
            list(zip(ids, listings, strict=True)), telegram, _config(), db, stats,
            reserve_intent=reserve,
        )
        telegram.send_message.assert_not_called()
        assert stats.errors == 1
        assert all(db.listing(i)["status"] == "delivery-uncertain" for i in ids)


def test_crash_after_telegram_acceptance_cannot_replay_fresh_runner(tmp_path):
    # Remote reservations survive; runner-local SQLite and journal do not.
    reserved = set()
    item = _item("original", source="stable")
    confirmed = Mock()
    confirmed.send_message.side_effect = RuntimeError("crash after Telegram accepted")

    def reserve(namespace, key, operation):
        token = (namespace, key, operation)
        if token in reserved:
            raise OSError("GitHub reservation already exists")
        reserved.add(token)

    before = tmp_path / "before.db"
    init(before)
    with Database(before) as db:
        lid = _add(db, item)
        with pytest.raises(RuntimeError, match="crash"):
            pipeline._broadcast(
                [(lid, item)], confirmed, _config(), db, pipeline.RunStats(),
                reserve_intent=reserve,
            )
    recovered = tmp_path / "recovered.db"
    init(recovered)
    with Database(recovered) as db:
        lid = _add(db, item)
        telegram = Mock()
        pipeline._broadcast(
            [(lid, item)], telegram, _config(), db, pipeline.RunStats(),
            reserve_intent=reserve,
        )
        telegram.send_message.assert_not_called()
        assert db.listing(lid)["status"] == "delivery-uncertain"
    confirmed.send_message.assert_called_once()


def test_explicit_telegram_absence_reconciliation_unlocks_distinct_revision(tmp_path):
    path = tmp_path / "db.sqlite"
    init(path)
    item = _item("reissue")
    calls: list[str] = []

    def reserve(namespace, key, operation):
        calls.append(operation)

    with Database(path) as db:
        lid = _add(db, item)
        telegram = Mock()
        telegram.send_message.side_effect = TelegramError("response lost", uncertain=True)
        pipeline._broadcast(
            [(lid, item)], telegram, _config(), db, pipeline.RunStats(),
            reserve_intent=reserve,
        )
        assert db.listing(lid)["status"] == "delivery-uncertain"
        db.resolve_telegram_delivery(lid, confirmed_not_delivered=True)
        assert db.listing(lid)["status"] == "pending"
        revision = db.listing(lid)["telegram_delivery_revision"]
        assert revision > 0
        telegram.send_message.side_effect = None
        telegram.send_message.return_value = 902
        pipeline._broadcast(
            [(lid, item)], telegram, _config(), db, pipeline.RunStats(),
            reserve_intent=reserve,
        )
        assert db.listing(lid)["telegram_message_id"] == 902
    # Each attempt reserves *both* source and application URLs. All aliases
    # within the operator-reviewed retry use the same new generation.
    assert set(calls) == {"initial", f"verified_absent:{revision}"}


def test_trusted_main_without_durable_callback_must_not_send_vacancy(tmp_path):
    path = tmp_path / "db.sqlite"
    init(path)
    item = _item("production")
    with Database(path) as db:
        lid = _add(db, item)
        telegram = Mock()
        with patch.dict("os.environ", {
            "GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main",
            "GITHUB_WORKFLOW": "predoc-pipeline",
        }), pytest.raises(OSError, match="durable"):
            pipeline._broadcast(
                [(lid, item)], telegram, _config(), db, pipeline.RunStats(),
            )
        telegram.send_message.assert_not_called()


def test_historical_phd_uses_reservation_and_preserves_web_post(tmp_path):
    path = tmp_path / "db.sqlite"
    init(path)
    prefs = load_preferences(Path(__file__).resolve().parents[2] / "config/preferences.toml")
    router = Router(prefs)
    item = _item("doctoral", phd=True)
    telegram = Mock()
    reserved = []

    def reserve(namespace, key, operation):
        assert namespace == "vacancies"
        reserved.append((key, operation))

    def send(**kwargs):
        assert reserved
        return 903

    telegram.send_message.side_effect = send
    with Database(path) as db:
        lid = _add(db, item)
        db.mark_published(lid, None, x_post_id="web-prior")
        old = db.listing(lid)["published_at"]
        pipeline._publish_non_us_econ_phds(
            db, telegram, _config(phd=True), pipeline.RunStats(), router, prefs,
            fresh_ids=set(), verify=False, reserve_intent=reserve,
        )
        assert telegram.send_message.call_count == 1
        row = db.listing(lid)
        assert row["x_post_id"] == "web-prior"
        assert row["published_at"] == old
        assert row["telegram_message_id"] == 903
    assert all(operation == "initial" for _, operation in reserved)


def test_historical_phd_reservation_collision_is_held_without_send(tmp_path):
    path = tmp_path / "db.sqlite"
    init(path)
    prefs = load_preferences(Path(__file__).resolve().parents[2] / "config/preferences.toml")
    item = _item("doctoral-held", phd=True)
    telegram = Mock()

    def conflict(namespace, key, operation):
        raise OSError("prior send reservation or uncertain response")

    with Database(path) as db:
        lid = _add(db, item)
        db.mark_published(lid, None, x_post_id="prior-web")
        pipeline._publish_non_us_econ_phds(
            db, telegram, _config(phd=True), pipeline.RunStats(),
            Router(prefs), prefs, fresh_ids=set(), verify=False,
            reserve_intent=conflict,
        )
        telegram.send_message.assert_not_called()
        assert db.telegram_state(lid) == "uncertain"
        assert db.listing(lid)["x_post_id"] == "prior-web"


def test_production_wires_durable_callback_to_both_vacancy_publishers():
    source = Path("src/predoc_pipeline/pipeline.py").read_text(encoding="utf-8")
    assert "reserve_intent=durable_reserve" in source
    assert source.count("reserve_intent=durable_reserve") >= 4
    assert "GitHubIntentReserver.from_environment().reserve" in source


def test_reserver_accepts_vacancies_namespace_with_create_only_semantics():
    responder = Mock(status=201)
    responder.__enter__ = Mock(return_value=responder)
    responder.__exit__ = Mock(return_value=None)
    with patch("urllib.request.urlopen", return_value=responder) as transport:
        GitHubIntentReserver(repository="Owner/Repo", token="fake").reserve(
            "vacancies", "a" * 32, "initial",
        )
    request = transport.call_args.args[0]
    assert "/contents/data/telegram_delivery_intents/vacancies/" in request.full_url
    assert request.get_method() == "PUT"
