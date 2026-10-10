"""Elapsed expected start dates are suspicion, not evidence of closure."""

import asyncio
from datetime import date

import pytest

from predoc_pipeline.boards.heuristics import apply_heuristics, check_still_open
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.boards.utils import dates


@pytest.mark.parametrize('suffix', ['Applications accepted until filled.',
                                    'The start date is flexible.', ''])
def test_old_start_is_a_note_not_closure(monkeypatch, suffix):
    monkeypatch.setattr(dates, 'today', lambda: date(2026, 10, 5))
    text = f'Expected start: July 2026. {suffix}'
    post = JobPostSchema(title='Research Assistant', url='https://example.org/job', source='test')
    apply_heuristics(post, text)
    assert not post.extra.get('closed')
    assert post.extra['stale_start_note']

    class Scraper:
        async def fetch_detail(self, post):
            return text

    assert asyncio.run(check_still_open(Scraper(), post)) is None


@pytest.mark.parametrize('closure', ['This position is filled.',
                                    'Application deadline: September 1, 2026.'])
def test_explicit_closure_or_deadline_still_closes(monkeypatch, closure):
    monkeypatch.setattr(dates, 'today', lambda: date(2026, 10, 5))
    post = JobPostSchema(title='Research Assistant', url='https://example.org/job', source='test')

    class Scraper:
        async def fetch_detail(self, post):
            return f'Expected start: July 2026. Start date flexible. {closure}'

    assert asyncio.run(check_still_open(Scraper(), post))


def test_updated_start_clears_obsolete_suspicion(monkeypatch):
    monkeypatch.setattr(dates, 'today', lambda: date(2026, 10, 5))
    post = JobPostSchema(title='Research Assistant', url='https://example.org/job', source='test')
    apply_heuristics(post, 'Expected start: July 2026.')
    assert post.extra.get('stale_start_note')
    apply_heuristics(post, 'Expected start: December 2026.')
    assert 'stale_start_note' not in post.extra
    post.extra['stale_start_note'] = 'old suspicion'

    class Scraper:
        async def fetch_detail(self, post):
            return 'Expected start: December 2026.'

    assert asyncio.run(check_still_open(Scraper(), post)) is None
    assert 'stale_start_note' not in post.extra
