"""Changed recurring adverts must reach classification again."""

import asyncio
from unittest.mock import Mock

import pytest

from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.dedupe import Deduplicator
from predoc_pipeline.core.urls import content_hash, url_hash
from predoc_pipeline.models import ExtractionResult, RawItem
from predoc_pipeline.pipeline import RunStats, _pre_extract, _process
from predoc_pipeline.settings import Settings


@pytest.mark.parametrize('change', ['text', 'hints'])
def test_rejected_board_advert_is_reconsidered_after_evidence_change(tmp_path, change):
    path = tmp_path / 'state.db'
    init(path)
    extractor = Mock()
    extractor.extract.return_value = ExtractionResult(
        is_vacancy=True, title='Predoctoral Fellow in Economics',
        institution='University of Oxford', country='United Kingdom',
        application_url='https://example.org/job/1',
        summary='Paid applied microeconomics research using Stata.', confidence=0.99,
    )
    item = RawItem(source='board:test', source_url='https://example.org/job/1',
                   title='Predoctoral Fellow in Economics',
                   text='We are hiring a paid predoctoral economics research fellow using Stata.',
                   hints={'board': 'test', 'reject': 'closed'})
    settings = Settings(_env_file=None, confidence_threshold=0.5)
    deduper = Deduplicator()
    with Database(path) as db:
        first = RunStats()
        assert _process(item, db=db, extractor=extractor, deduper=deduper,
                        settings=settings, stats=first) is None
        assert first.not_wanted == 1 and extractor.extract.call_count == 0

        unchanged = RunStats()
        assert _process(item, db=db, extractor=extractor, deduper=deduper,
                        settings=settings, stats=unchanged) is None
        assert unchanged.already_seen == 1 and extractor.extract.call_count == 0

        updates = {'hints': {'board': 'test'}}
        if change == 'text':
            updates['text'] = item.text + ' Applications have reopened for the next cohort.'
        reopened = item.model_copy(update=updates)
        second = RunStats()
        listing = _process(reopened, db=db, extractor=extractor, deduper=deduper,
                           settings=settings, stats=second)
        assert listing is not None and second.already_seen == 0
        assert extractor.extract.call_count == 1 and db.counts()['listings'] == 1


@pytest.mark.parametrize('update', [
    {'title': 'Predoctoral Fellow in Finance'},
    {'apply_url_hint': 'https://example.org/application/2'},
    {'hints': {'board': 'test', 'deadline': '2099-12-31'}},
])
def test_changed_candidate_metadata_invalidates_seen_verdict(tmp_path, update):
    path = tmp_path / 'state.db'
    init(path)
    item = RawItem(source='board:test', source_url='https://example.org/job/1',
                   title='Predoctoral Fellow in Economics',
                   text='We are hiring a paid predoctoral economics research fellow using Stata.',
                   hints={'board': 'test'})
    with Database(path) as db:
        gate, key, digest = _pre_extract(item, db=db, stats=RunStats())
        db.mark_seen(key, source=item.source, decision='rejected', content_hash=digest)
        assert _pre_extract(item, db=db, stats=RunStats()) is None
        assert _pre_extract(item.model_copy(update=update), db=db, stats=RunStats()) is not None


def test_legacy_text_verdict_rechecks_once_and_hint_order_is_stable(tmp_path):
    path = tmp_path / 'state.db'
    init(path)
    item = RawItem(source='board:test', source_url='https://example.org/job/1',
                   title='Predoctoral Fellow in Economics',
                   text='We are hiring a paid predoctoral economics research fellow using Stata.',
                   hints={'board': 'test', 'country': 'United Kingdom'})
    with Database(path) as db:
        db.mark_seen(url_hash(item.source_url), source=item.source, decision='rejected',
                     content_hash=content_hash(item.text))
        gate, key, digest = _pre_extract(item, db=db, stats=RunStats())
        db.mark_seen(key, source=item.source, decision='rejected', content_hash=digest)
        reordered = item.model_copy(update={
            'hints': {'country': 'United Kingdom', 'board': 'test'},
        })
        assert _pre_extract(reordered, db=db, stats=RunStats()) is None


def test_case_sensitive_application_identifier_changes_seen_verdict(tmp_path):
    path = tmp_path / 'state.db'
    init(path)
    item = RawItem(source='board:test', source_url='https://example.org/job/1',
                   title='Predoctoral Fellow in Economics',
                   text='We are hiring a paid predoctoral economics research fellow using Stata.',
                   apply_url_hint='https://example.org/apply/AbC', hints={'board': 'test'})
    with Database(path) as db:
        gate, key, digest = _pre_extract(item, db=db, stats=RunStats())
        db.mark_seen(key, source=item.source, decision='rejected', content_hash=digest)
        changed = item.model_copy(update={'apply_url_hint': 'https://example.org/apply/abc'})
        assert _pre_extract(changed, db=db, stats=RunStats()) is not None


def test_board_collector_emits_known_adverts_for_reconsideration(monkeypatch):
    from predoc_pipeline.boards import collector
    from predoc_pipeline.boards.config import SourceConfig, load_preferences
    from predoc_pipeline.boards.models import JobPostSchema
    from predoc_pipeline.boards.scrapers.rss import RSSScraper

    config = SourceConfig(name='test', type='rss', url='https://example.org/feed')
    scraper = RSSScraper(config, None)
    post = JobPostSchema(title='Predoctoral Fellow in Economics',
                        url='https://example.org/job/1', source='test',
                        institution='University of Oxford', country='United Kingdom',
                        description_snippet='Paid applied microeconomics research using Stata.')

    async def discovered(*args):
        return [collector.SourceResult(scraper, posts=[post])]

    monkeypatch.setattr(collector, '_scrape_all', discovered)
    prefs = load_preferences('config/preferences.toml')
    prefs.enrich.fetch_details = False
    result = asyncio.run(collector._collect([config], prefs, lambda _: True, None))
    assert result.known == 1
    assert len(result.items) == 1 and result.items[0].source_url == post.url
