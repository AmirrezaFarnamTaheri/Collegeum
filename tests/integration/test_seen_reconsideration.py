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


def test_legacy_phd_and_postdoc_rejections_are_reconsidered_once(tmp_path):
    import hashlib
    import json

    from predoc_pipeline.boards.config import load_preferences
    from predoc_pipeline.core.urls import url_hash
    from predoc_pipeline.pipeline import RunStats, _pre_extract
    from predoc_pipeline.policy import Policy

    preferences = load_preferences("config/preferences.toml")
    assert not preferences.filters.exclude_phd_positions
    policy = Policy(preferences)
    db_path = tmp_path / "reconsider.db"
    init(db_path)
    for i, reason in enumerate((
        "not a vacancy: phd_studentship", "not a vacancy: postdoc",
    )):
        item = RawItem(
            source="test", source_url=f"https://example.org/job/{i}",
            title="Research Assistant in Economics",
            text="Paid research assistant in economics, research and data analysis.",
            hints={"board": True},
        )
        evidence = json.dumps({
            "text": item.text, "title": item.title,
            "apply_url_hint": item.apply_url_hint, "hints": item.hints,
        }, sort_keys=True, ensure_ascii=False, default=str)
        legacy = "candidate-v3:" + hashlib.sha256(evidence.encode()).hexdigest()
        with Database(db_path) as db:
            db.mark_seen(url_hash(item.source_url), source="test", decision="rejected",
                         reason=reason, content_hash=legacy)
            first = _pre_extract(item, db=db, stats=RunStats(), policy=policy)
            assert first is not None
            _, key, new_digest = first
            assert new_digest.startswith("candidate-v4:")
            db.mark_seen(key, source="test", decision="rejected", reason=reason,
                         content_hash=new_digest)
            stats = RunStats()
            assert _pre_extract(item, db=db, stats=stats, policy=policy) is None
            assert stats.already_seen == 1


def test_filter_edit_reconsiders_rejected_but_not_accepted_decisions(tmp_path):
    from predoc_pipeline.boards.config import load_preferences
    from predoc_pipeline.core.urls import url_hash
    from predoc_pipeline.pipeline import RunStats, _pre_extract
    from predoc_pipeline.policy import Policy

    preferences = load_preferences("config/preferences.toml")
    item = RawItem(
        source="test", source_url="https://example.org/renewable-eligibility",
        title="Research Assistant in Economics", hints={"board": True},
        text="We are hiring a paid research assistant in applied economics.",
    )
    path = tmp_path / "policy.db"
    init(path)
    with Database(path) as db:
        old = _pre_extract(item, db=db, stats=RunStats(), policy=Policy(preferences))
        assert old is not None
        _, key, prior = old
        db.mark_seen(key, source="test", decision="rejected", reason="wrong-field",
                     content_hash=prior)
        changed = preferences.model_copy(deep=True)
        changed.filters.field_terms.append("genomics")
        reconsider = _pre_extract(item, db=db, stats=RunStats(), policy=Policy(changed))
        assert reconsider is not None and reconsider[2] != prior
        db.mark_seen(key, source="test", decision="accepted",
                     content_hash=prior)
        skipped = RunStats()
        assert _pre_extract(item, db=db, stats=skipped, policy=Policy(changed)) is None
        assert skipped.already_seen == 1
        assert db.seen(url_hash(item.source_url))["content_hash"] == reconsider[2]
