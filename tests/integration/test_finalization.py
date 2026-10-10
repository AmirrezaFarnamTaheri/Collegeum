"""Production-path regressions for vacancy refresh and independent X recovery."""

from unittest.mock import Mock

import pytest

from predoc_pipeline import pipeline
from predoc_pipeline.boards.config import load_preferences
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.dedupe import Deduplicator
from predoc_pipeline.models import ExtractionResult, RawItem
from predoc_pipeline.pipeline import RunStats, _process, _retry_x_publications
from predoc_pipeline.publish.feedback import FeedbackStore, StateCorruptError, generate_key
from predoc_pipeline.routing import Router
from predoc_pipeline.settings import Settings

from .test_listing_refresh import insert
from .test_operational_regressions import isolated_run  # noqa: F401


def test_pipeline_refresh_updates_facts_without_republishing(tmp_path):
    path = tmp_path / 'state.db'
    init(path)
    item = RawItem(source='board:test', source_url='https://example.org/job/1',
                   title='Predoctoral Fellow in Economics',
                   text='We are hiring a paid predoctoral economics research fellow using Stata.',
                   hints={'board': 'test'})
    result = ExtractionResult(
        is_vacancy=True, title=item.title, institution='University of Oxford',
        country='United Kingdom', application_url=item.source_url,
        summary='Paid applied microeconomics research using Stata.', confidence=0.99,
    )
    extractor = Mock()
    extractor.extract.return_value = result
    settings = Settings(_env_file=None, confidence_threshold=0.5)
    with Database(path) as db:
        listing = _process(item, db=db, extractor=extractor, deduper=Deduplicator(),
                           settings=settings, stats=RunStats())
        lid = listing.__dict__['_listing_id']
        db.mark_published(lid, 123, x_post_id='101')
        before = dict(db.listing(lid))
        extractor.extract.return_value = result.model_copy(update={
            'deadline': '2099-12-31', 'salary_min': 43250,
        })
        stats = RunStats()
        changed = item.model_copy(update={'text': item.text + ' Updated salary and deadline.'})
        assert _process(changed, db=db, extractor=extractor, deduper=Deduplicator(),
                        settings=settings, stats=stats) is None
        after = dict(db.listing(lid))
        assert stats.refreshed == 1 and stats.duplicates == 1
        assert after['salary_min'] == 43250 and after['deadline'].startswith('2099-12-31')
        for field in ('id', 'url_hash', 'published_at', 'telegram_message_id', 'x_post_id'):
            assert after[field] == before[field]
        assert db.counts()['listings'] == 1


def test_x_recovery_retries_failure_and_preserves_web_history(tmp_path):
    path = tmp_path / 'state.db'
    init(path)
    settings = Settings(_env_file=None, x_retry_limit=1)
    prefs = load_preferences('config/preferences.toml')
    prefs.enrich.fetch_details = False
    policy = Mock()
    policy.check_stored.return_value = None
    feedback = FeedbackStore(tmp_path / 'feedback.json')
    router = Router(prefs)
    publisher = Mock()
    publisher.post_listing.side_effect = [RuntimeError('rejected'), '101']
    with Database(path) as db:
        lid = insert(db)
        db.refresh_listing_facts(lid, {'country': 'United States'})
        db.mark_published(lid, None)
        before = dict(db.listing(lid))
        stats = RunStats()
        for _ in range(2):
            _retry_x_publications(publisher, settings, db, stats, prefs, policy,
                                  feedback, router, skip=set())
        assert db.listing(lid)['x_post_id'] == '101'
        assert stats.errors == 1 and stats.published == 0
        assert db.listing(lid)['published_at'] == before['published_at']
        _retry_x_publications(publisher, settings, db, stats, prefs, policy,
                              feedback, router, skip=set())
        assert publisher.post_listing.call_count == 2


def test_x_recovery_excludes_hidden_skipped_and_closed_rows(tmp_path):
    path = tmp_path / 'state.db'
    init(path)
    settings = Settings(_env_file=None)
    prefs = load_preferences('config/preferences.toml')
    prefs.enrich.fetch_details = False
    policy = Mock()
    policy.check_stored.return_value = None
    feedback = FeedbackStore(tmp_path / 'feedback.json')
    publisher = Mock()
    with Database(path) as db:
        lid = insert(db)
        db.refresh_listing_facts(lid, {'country': 'United States'})
        db.mark_published(lid, None)
        _retry_x_publications(publisher, settings, db, RunStats(), prefs, policy,
                              feedback, Router(prefs), skip={lid})
        feedback.set('stable', 'invalid', title='Hidden')
        _retry_x_publications(publisher, settings, db, RunStats(), prefs, policy,
                              feedback, Router(prefs), skip=set())
        feedback.set('stable', 'valid', title='Visible')
        db.mark_closed(lid, 'filled')
        _retry_x_publications(publisher, settings, db, RunStats(), prefs, policy,
                              feedback, Router(prefs), skip=set())
        publisher.post_listing.assert_not_called()


def test_pipeline_recovers_x_when_collection_has_no_new_items(isolated_run, monkeypatch):  # noqa: F811
    settings = isolated_run.model_copy(update={
        'x_consumer_key': 'test', 'x_consumer_secret': 'test',
        'x_access_token': 'test', 'x_access_token_secret': 'test',
    })
    init(settings.db_path)
    with Database(settings.db_path) as db:
        lid = insert(db)
        db.refresh_listing_facts(lid, {
            'country': 'United States', 'institution': 'University of Oxford',
            'summary': 'Paid predoctoral research in applied microeconomics using Stata.',
            'disciplines': '["Applied Microeconomics"]',
        })
        db.mark_published(lid, None)
    publisher = Mock()
    publisher.post_listing.return_value = '101'
    monkeypatch.setattr('predoc_pipeline.publish.x.XClient.from_settings', lambda _: publisher)
    monkeypatch.setattr(pipeline, 'gather', lambda *args, **kwargs: ([], {}))
    stats = pipeline.run(settings, sync_telegram=False)
    assert stats.published == 0
    with Database(settings.db_path) as db:
        assert db.listing(lid)['x_post_id'] == '101'
    publisher.post_listing.assert_called_once()
    publisher.close.assert_called_once()


def test_pipeline_missing_feedback_key_stops_before_collection(isolated_run, monkeypatch):  # noqa: F811
    store = FeedbackStore(isolated_run.feedback_path, key=generate_key())
    store.set('hidden', 'invalid', title='Saved hidden listing')
    store.save()
    collect = Mock()
    monkeypatch.setattr(pipeline, 'gather', collect)
    settings = isolated_run.model_copy(update={'feedback_encryption_key': ''})
    with pytest.raises(StateCorruptError, match='FEEDBACK_ENCRYPTION_KEY'):
        pipeline.run(settings, sync_telegram=False)
    collect.assert_not_called()
