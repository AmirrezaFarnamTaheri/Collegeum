"""Official-page parser contracts captured on 10 October 2026.

Each institution retains its discovery/metadata contract. Transport rejection
is shared adapter behavior, so it is exercised once per adapter.
"""

import asyncio
from datetime import date

import httpx
import pytest

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources, load_preferences
from predoc_pipeline.boards.filter import RelevanceFilter
from predoc_pipeline.boards.http import HttpClient
from predoc_pipeline.boards.scrapers import SCRAPERS
from tests.boards.conftest import ROOT, fixture_text

# Fixture, advert count, representative URL fragment, expected advert facts.
SOURCES = {
    'nuffield_jobs': ('source_expansion/nuffield', 1, '', {'deadline': date(2026, 10, 18)}),
    'crest_jobs': ('source_expansion/crest', 3, '', {}),
    'essec_jobs': ('source_expansion/essec', 14, '', {}),
    'nhh_jobs': ('source_expansion/nhh', 2, '', {}),
    'warwick_jobs': ('source_expansion_batch2/warwick', 48, '1443391233', {
        'title': 'Research Assistant',
    }),
    'bank_canada_jobs': ('source_expansion_batch2/bankcanada', 16, '606922517', {
        'location': 'Ottawa or Calgary, CA', 'deadline': date(2026, 10, 25),
    }),
    'sciencespo_jobs': ('source_expansion_batch2/sciencespo', 3, '', {}),
    'aarhus_jobs': ('institutions/aarhus_jobs', 60, 'research-assistant-at-the-mapp', {
        'deadline': date(2026, 10, 12), 'department': 'Department of Management',
    }),
    'gothenburg_jobs': ('institutions/gothenburg_jobs', 62, 'rmjob=41465', {
        'title': 'Postdoctoral Fellow in Political Science', 'deadline': date(2026, 10, 15),
    }),
    'umea_usbe_jobs': ('institutions/umea_usbe_jobs', 3, '965375', {
        'title': 'PhD students in Statistics', 'deadline': date(2026, 11, 4),
    }),
    'linkoping_jobs': ('institutions/linkoping_jobs', 19, '/29854', {
        'deadline': date(2026, 11, 9), 'location': 'Norrkoping',
        'department': 'ITN - Department of Science and Technology', 'date_posted': None,
    }),
    'duke_jobs': ('institutions/duke_jobs', 24, '1438184700', {
        'date_posted': date(2026, 10, 8), 'deadline': None,
    }),
    'trinity_cambridge_jobs': ('institutions/trinity_cambridge_jobs', 2, '', {}),
    'bruegel_jobs': ('institutions/bruegel_jobs', 1, '/about/careers/visiting-fellowships', {
        'title': 'Visiting Fellowships',
    }),
}


def config(name):
    return next(c for c in load_board_sources(ROOT / 'config/sources.toml') if c.name == name)


def collect(cfg, *, payload='', status=200):
    def respond(request):
        assert str(request.url) == cfg.opt('url')
        return httpx.Response(status, text=payload)

    async def run():
        async with HttpClient(max_retries=0, transport=httpx.MockTransport(respond)) as http:
            return (await _scrape_all([SCRAPERS[cfg.type](cfg, http)], 1, 5))[0]

    return asyncio.run(run())


@pytest.mark.parametrize('name', SOURCES)
def test_official_discovery_identity_and_metadata(name):
    fixture, count, needle, expected = SOURCES[name]
    cfg = config(name)
    result = collect(cfg, payload=fixture_text(f'{fixture}.html'))
    assert cfg.enabled == (name != 'nhh_jobs') and not cfg.field_implied
    assert result.ok
    assert len(result.posts) == len({p.job_id for p in result.posts}) == count
    assert all((p.institution, p.field_implied) == (cfg.institution, False) for p in result.posts)
    assert all(p.title != 'Careers' for p in result.posts)
    post = next(p for p in result.posts if needle in p.url)
    for field, value in expected.items():
        assert getattr(post, field) == value, field

    if name == 'nuffield_jobs':
        assert 'View more' not in post.title
    elif name == 'crest_jobs':
        assert all('/wp-content/uploads/' in p.url for p in result.posts)
        assert not any('job-market-candidate' in p.url or 'Shchapov' in p.title
                       for p in result.posts)
    elif name == 'essec_jobs':
        assert all(p.country is None for p in result.posts)
    elif name == 'nhh_jobs':
        assert all('/stilling/' in p.url for p in result.posts)
    elif name == 'warwick_jobs':
        assert not any('Select with space bar' in p.title for p in result.posts)
    elif name == 'bank_canada_jobs':
        assert '23:59 EST' in post.deadline_text
        assert any('PhD Job Market' in p.title for p in result.posts)
    elif name == 'sciencespo_jobs':
        assert all('/actualites/' in p.url for p in result.posts)
        assert not any('drive.google' in p.url or 'past-only' in p.url for p in result.posts)
        assert any('post-doctoral' in p.title for p in result.posts)
    elif name == 'aarhus_jobs':
        assert post.date_posted != post.deadline
    elif name == 'umea_usbe_jobs':
        assert any('scholarship' in p.title and 'Economics' in p.title for p in result.posts)
    elif name == 'trinity_cambridge_jobs':
        assert {p.title for p in result.posts} == {'Trinity Plus Coordinator', 'Functions Supervisor'}


@pytest.mark.parametrize('name', ['nuffield_jobs', 'linkoping_jobs', 'aarhus_jobs'])
def test_adapter_fetch_failure_is_not_seasonal_emptiness(name):
    result = collect(config(name), status=503)
    assert not result.ok and result.failure_stage == 'fetch'


def test_wide_boards_keep_role_and_field_policy():
    flt = RelevanceFilter(load_preferences(ROOT / 'config/preferences.toml').filters)
    for name, title in [
        ('essec_jobs', 'Assistant administratif F/H/X+'),
        ('nhh_jobs', 'Assistant Professor in Financial Accounting'),
        ('warwick_jobs', 'Campus Cleaning Services Supervisor'),
        ('bank_canada_jobs', 'Solutions Architect'),
        ('sciencespo_jobs', 'Communication Officer'),
    ]:
        cfg = config(name)
        post = SCRAPERS[cfg.type](cfg, None).make(title=title, url='https://example.org/jobs/1')
        assert not flt.evaluate(post).keep, name
    for text in ['Scientific machine learning in computer science',
                 'Nursing research and clinical medicine in hospital patients']:
        assert flt.field_verdict_long(text) == 'unwanted'
