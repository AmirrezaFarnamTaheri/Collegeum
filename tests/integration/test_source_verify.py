from types import SimpleNamespace

import httpx
import pytest
from typer.testing import CliRunner

from predoc_pipeline.boards.collector import verify_boards
from predoc_pipeline.boards.config import Preferences
from predoc_pipeline.cli import app


def test_verifier_includes_boards_excludes_disabled_denominator(monkeypatch):
    boards = [SimpleNamespace(name=name, enabled=enabled) for name, enabled in
              [('good', True), ('seasonal', True), ('broken', True), ('off', False)]]
    monkeypatch.setattr('predoc_pipeline.cli.load_sources', lambda _: [])
    monkeypatch.setattr('predoc_pipeline.boards.config.load_board_sources', lambda _: boards)
    calls = []

    def probe(config, prefs):
        calls.append((config, prefs.http.source_timeout))
        return {'good': {'ok': True, 'items': 2},
                'seasonal': {'ok': True, 'items': 0, 'may_be_empty': True},
                'broken': {'ok': False, 'items': 0, 'errors': 1}}

    monkeypatch.setattr('predoc_pipeline.boards.collector.verify_boards', probe)
    result = CliRunner().invoke(app, ['sources', 'verify', '--timeout', '3'])
    assert result.exit_code == 1, result.output
    assert '2/3 enabled sources passed' in result.output
    assert 'EMPTY' in result.output and 'FAIL' in result.output
    assert 'off (disabled)' in result.output
    assert calls == [('config/sources.toml', 3)]


def test_verifier_flags_unexpected_empty_board(monkeypatch):
    monkeypatch.setattr('predoc_pipeline.cli.load_sources', lambda _: [])
    monkeypatch.setattr('predoc_pipeline.boards.config.load_board_sources',
                        lambda _: [SimpleNamespace(name='empty', enabled=True)])
    monkeypatch.setattr('predoc_pipeline.boards.collector.verify_boards',
                        lambda *_: {'empty': {'ok': True, 'items': 0}})
    result = CliRunner().invoke(app, ['sources', 'verify'])
    assert result.exit_code == 1
    assert 'unexpected empty discovery' in result.output


def test_real_rss_discovery_distinguishes_transport_parser_and_empty(tmp_path):
    config = tmp_path / 'sources.toml'
    config.write_text('\n'.join(
        f'[[board]]\nname="{name}"\ntype="rss"\nurl="https://example.org/{name}"\n'
        f'enabled={str(name != "disabled").lower()}\nmay_be_empty=true\n'
        for name in ['good', 'empty', 'broken', 'html', 'disabled']
    ), encoding='utf-8')
    seen = []
    rss = '<rss version="2.0"><channel><title>Jobs</title>{}</channel></rss>'

    def respond(request):
        seen.append(request.url.path)
        if request.url.path == '/broken':
            return httpx.Response(503)
        if request.url.path == '/html':
            return httpx.Response(200, text='<html><body>Sign in to view jobs</body></html>')
        item = ('<item><title>Research Assistant</title>'
                '<link>https://example.org/job/1</link></item>')
        return httpx.Response(200, text=rss.format(item if request.url.path == '/good' else ''))

    prefs = Preferences()
    prefs.http.max_retries = 0
    prefs.http.default_min_interval = 0
    stats = verify_boards(str(config), prefs, transport=httpx.MockTransport(respond))
    assert stats['good']['ok'] and stats['good']['items'] == 1
    assert stats['empty']['ok'] and stats['empty']['items'] == 0
    assert stats['empty']['may_be_empty']
    assert not stats['broken']['ok'] and stats['broken']['errors'] == 1
    assert stats['broken']['failure_stage'] == 'fetch'
    assert not stats['html']['ok'] and stats['html']['errors'] == 1
    assert stats['html']['items'] == 0
    assert stats['html']['failure_stage'] == 'parse'
    assert 'disabled' not in stats and '/disabled' not in seen


def test_partial_endpoint_failure_retains_posts_and_degrades_health(tmp_path):
    from predoc_pipeline.core.health import source_status

    config = tmp_path / 'sources.toml'
    config.write_text(
        '[[board]]\nname="multi"\ntype="rss"\n'
        'urls=["https://example.org/good", "https://example.org/fail1", '
        '"https://example.org/fail2"]\n', encoding='utf-8',
    )
    seen = []

    def respond(request):
        seen.append(request.url.path)
        if request.url.path != '/good':
            return httpx.Response(503)
        return httpx.Response(200, text='<rss version="2.0"><channel><title>Jobs</title>'
                              '<item><title>Research Assistant</title>'
                              '<link>https://example.org/job/1</link></item></channel></rss>')

    prefs = Preferences()
    prefs.http.max_retries = 0
    prefs.http.default_min_interval = 0
    stats = verify_boards(str(config), prefs, transport=httpx.MockTransport(respond))['multi']
    assert stats['items'] == 1  # Good endpoint output survives failures elsewhere.
    assert not stats['ok'] and stats['errors'] == 2
    assert stats['failure_stage'] == 'fetch'
    assert source_status(stats) == 'partial'
    assert seen == ['/good', '/fail1', '/fail2']
    assert stats['messages'] == ['2 discovery endpoint(s) failed']


def test_malformed_feed_preserves_recoverable_entries_as_partial(tmp_path):
    from predoc_pipeline.core.health import source_status

    config = tmp_path / 'sources.toml'
    config.write_text('[[board]]\nname="malformed"\ntype="rss"\n'
                      'url="https://example.org/feed"\n', encoding='utf-8')
    xml = ('<rss version="2.0"><channel><title>Jobs</title><item>'
           '<title>Research Assistant</title><link>https://example.org/job/1</link>'
           '</item>')  # Missing closing channel/rss; feedparser recovers the entry.
    prefs = Preferences()
    prefs.http.max_retries = 0
    prefs.http.default_min_interval = 0
    transport = httpx.MockTransport(lambda _: httpx.Response(200, text=xml))
    stats = verify_boards(str(config), prefs, transport=transport)['malformed']
    assert stats['items'] == 1
    assert stats['errors'] == 1 and not stats['ok']
    assert stats['failure_stage'] == 'parse'
    assert source_status(stats) == 'partial'


@pytest.mark.parametrize('order', [('bad', 'good'), ('good', 'bad')])
def test_unparseable_sibling_payload_does_not_discard_valid_feed(tmp_path, order):
    from predoc_pipeline.core.health import source_status

    config = tmp_path / 'sources.toml'
    config.write_text('[[board]]\nname="mixed"\ntype="rss"\n'
                      f'urls=["https://example.org/{order[0]}", '
                      f'"https://example.org/{order[1]}"]\n',
                      encoding='utf-8')

    def respond(request):
        text = ('<html><body>Sign in</body></html>' if request.url.path == '/bad' else
                '<rss version="2.0"><channel><title>Jobs</title><item>'
                '<title>Research Assistant</title><link>https://example.org/job/1</link>'
                '</item></channel></rss>')
        return httpx.Response(200, text=text)

    prefs = Preferences()
    prefs.http.default_min_interval = 0
    stats = verify_boards(str(config), prefs, transport=httpx.MockTransport(respond))['mixed']
    assert stats['items'] == 1 and stats['errors'] == 1
    assert stats['failure_stage'] == 'parse' and not stats['ok']
    assert source_status(stats) == 'partial'


@pytest.mark.parametrize('bad_entry', [
    '<item><title>Missing link</title></item>',
    '<item><link>https://example.org/bad</link></item>',
])
def test_invalid_feed_entry_does_not_discard_valid_siblings(tmp_path, bad_entry):
    from predoc_pipeline.core.health import source_status

    config = tmp_path / 'sources.toml'
    config.write_text('[[board]]\nname="entries"\ntype="rss"\n'
                      'url="https://example.org/feed"\n', encoding='utf-8')
    good = ('<item><title>Research Assistant</title>'
            '<link>https://example.org/job/1</link></item>')
    xml = '<rss version="2.0"><channel><title>Jobs</title>' + bad_entry + good + '</channel></rss>'
    prefs = Preferences()
    prefs.http.default_min_interval = 0
    transport = httpx.MockTransport(lambda _: httpx.Response(200, text=xml))
    stats = verify_boards(str(config), prefs, transport=transport)['entries']
    assert stats['items'] == 1 and stats['errors'] == 1
    assert source_status(stats) == 'partial' and stats['failure_stage'] == 'parse'


@pytest.mark.parametrize('bad_entry', [
    '<item><title>Missing link</title></item>',
    '<item><link>https://example.org/bad</link></item>',
    '<item><title>Non-web ID</title><guid>urn:uuid:abc</guid></item>',
    '<item><title>Invalid port</title><link>https://example.org:bad/job</link></item>',
])
def test_ingestion_feed_reports_invalid_entries_and_retains_siblings(bad_entry):
    from predoc_pipeline.ingest.collectors import collect_feeds
    from predoc_pipeline.ingest.sources import Source

    good = ('<item><title>Research Assistant</title>'
            '<link>/job/1</link></item>')
    xml = '<rss version="2.0"><channel><title>Jobs</title>' + bad_entry + good + '</channel></rss>'

    class Client:
        def get(self, url):
            return SimpleNamespace(ok=True, skipped=False, text=xml, content=xml.encode(),
                                   url='https://example.org/redirected/feed')

    items, stats = collect_feeds([Source('test', 'feed', 'https://original.org/feed')],
                                Client(), max_items=5)
    assert len(items) == 1 and items[0].source_url == 'https://example.org/job/1'
    assert stats[0].items == 1 and stats[0].errors == 1
    assert stats[0].messages[0].startswith('feed entry ')


def test_command_checks_feed_and_portal_parsing_not_only_http_success(monkeypatch):
    from predoc_pipeline.ingest.sources import Source

    sources = [Source('feed-good', 'feed', 'https://example.org/good'),
               Source('feed-html', 'feed', 'https://example.org/html'),
               Source('portal-empty', 'portal', 'https://example.org/portal')]
    monkeypatch.setattr('predoc_pipeline.cli.load_sources', lambda _: sources)
    monkeypatch.setattr('predoc_pipeline.boards.config.load_board_sources', lambda _: [])
    monkeypatch.setattr('predoc_pipeline.boards.collector.verify_boards', lambda *_: {})

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            text = ('<rss version="2.0"><channel><title>Jobs</title><item>'
                    '<title>Research Assistant</title><link>https://example.org/job/1</link>'
                    '</item></channel></rss>' if url.endswith('/good') else
                    '<html><body>Sign in</body></html>')
            return SimpleNamespace(ok=True, skipped=False, text=text, content=text.encode(),
                                   status=200, error=None, url=url)

    monkeypatch.setattr('predoc_pipeline.cli.PoliteClient', Client)
    result = CliRunner().invoke(app, ['sources', 'verify'])
    assert result.exit_code == 1, result.output
    assert '1/3 enabled sources passed' in result.output
    assert '1 collector errors' in result.output
    assert 'no postings discovered' in result.output


@pytest.mark.parametrize('backend', ['absent', 'failed'])
def test_portal_retains_valid_jsonld_and_reports_neighboring_parse_failures(monkeypatch, backend):
    import sys

    from predoc_pipeline.ingest.collectors import collect_portals
    from predoc_pipeline.ingest.sources import Source

    def fail(*args, **kwargs):
        raise RuntimeError('private parser detail')

    monkeypatch.setitem(sys.modules, 'extruct',
                        None if backend == 'absent' else SimpleNamespace(extract=fail))
    monkeypatch.setitem(sys.modules, 'w3lib.html',
                        SimpleNamespace(get_base_url=lambda html, url: url))
    html = ('<script type="application/ld+json">{broken</script>'
            '<script type="application/ld+json">{"@type":"JobPosting",'
            '"title":"Research Assistant","url":"https://example.org/job/1"}</script>')

    class Client:
        def get(self, url):
            return SimpleNamespace(ok=True, skipped=False, text=html, url=url)

    items, stats = collect_portals([Source('test', 'portal', 'https://example.org/jobs')],
                                  Client(), max_items=5)
    assert len(items) == 1 and items[0].title == 'Research Assistant'
    assert stats[0].errors == (1 if backend == 'absent' else 2)
    assert 'invalid JSON-LD block' in stats[0].messages
    assert 'private parser detail' not in str(stats[0].messages)


@pytest.mark.parametrize('bad', [
    {'@type': 42},
    {'@type': 'JobPosting', 'title': {'text': 'not a title'}},
    {'@type': 'JobPosting', 'title': 'Bad URL', 'url': 'javascript:alert(1)'},
    {'@type': 'JobPosting', 'title': 'Bad URL', 'url': {'id': 'job'}},
])
@pytest.mark.parametrize('first', [True, False])
def test_portal_malformed_node_preserves_valid_sibling(monkeypatch, bad, first):
    import json
    import sys

    from predoc_pipeline.ingest.collectors import _jobposting_items

    monkeypatch.setitem(sys.modules, 'extruct', None)
    good = {'@type': 'JobPosting', 'title': 'Research Assistant', 'url': '/job/1'}
    payload = {'@graph': [bad, good] if first else [good, bad]}
    html = '<script type="application/ld+json">' + json.dumps(payload) + '</script>'
    issues = []
    items = _jobposting_items(html, 'https://example.org/jobs', 'test', issues=issues)
    assert len(items) == 1 and items[0].source_url == 'https://example.org/job/1'
    assert len(issues) == 1


def test_deep_portal_metadata_does_not_abort_later_blocks(monkeypatch):
    import sys

    from predoc_pipeline.ingest.collectors import _iter_jobpostings, _jobposting_items

    monkeypatch.setitem(sys.modules, 'extruct', None)
    good = {'@type': 'JobPosting', 'title': 'Research Assistant'}
    nested = good
    for _ in range(2000):
        nested = [nested]
    assert list(_iter_jobpostings(nested)) == [good]

    html = ('<script type="application/ld+json">' + '[' * 2000 + '0' + ']' * 2000
            + '</script><script type="application/ld+json">'
            '{"@type":"JobPosting","title":"Research Assistant"}</script>')
    issues = []
    items = _jobposting_items(html, 'https://example.org/job/1', 'test', issues=issues)
    assert len(items) == 1
    assert issues == ['invalid JSON-LD block']


def test_portal_duplicates_do_not_consume_vacancy_capacity(monkeypatch):
    import json
    import sys

    from predoc_pipeline.ingest.collectors import collect_portals
    from predoc_pipeline.ingest.sources import Source

    monkeypatch.setitem(sys.modules, 'extruct', None)

    def markup(postings):
        return '<script type="application/ld+json">' + json.dumps(postings) + '</script>'

    first = {'@type': 'JobPosting', 'title': 'Research Assistant', 'url': '/job/1'}
    second = {'@type': 'JobPosting', 'title': 'Predoc Fellow', 'url': '/job/2'}
    index = markup([first, first]) + '<a href="/job/1">First</a><a href="/job/2">Second</a>'
    seen = []

    class Client:
        def get(self, url):
            seen.append(url)
            html = index if url.endswith('/jobs') else markup(
                first if url.endswith('/1') else second)
            return SimpleNamespace(ok=True, skipped=False, text=html, url=url)

    source = Source('test', 'portal', 'https://example.org/jobs',
                    follow_links=True, link_pattern=r'/job/\d+')
    items, stats = collect_portals([source], Client(), max_items=2)
    assert [item.title for item in items] == ['Research Assistant', 'Predoc Fellow']
    assert stats[0].items == 2 and stats[0].fetched == 3 and stats[0].errors == 0
    assert seen == ['https://example.org/jobs', 'https://example.org/job/1',
                    'https://example.org/job/2']


def test_empty_portal_details_keep_request_limit(monkeypatch):
    import sys

    from predoc_pipeline.ingest.collectors import collect_portals
    from predoc_pipeline.ingest.sources import Source

    monkeypatch.setitem(sys.modules, 'extruct', None)
    index = ''.join(f'<a href="/job/{i}">Job</a>' for i in range(10))
    requested = []

    class Client:
        def get(self, url):
            requested.append(url)
            return SimpleNamespace(ok=True, skipped=False,
                                   text=index if url.endswith('/jobs') else '<html></html>',
                                   url=url)

    source = Source('test', 'portal', 'https://example.org/jobs',
                    follow_links=True, link_pattern=r'/job/\d+')
    items, stats = collect_portals([source], Client(), max_items=2)
    assert items == [] and stats[0].fetched == 3
    assert len(requested) == 3  # One index and at most two detail requests.


def test_portal_preserves_multiple_locations_and_structured_country(monkeypatch):
    import json
    import sys

    from predoc_pipeline.ingest.collectors import _jobposting_items

    monkeypatch.setitem(sys.modules, 'extruct', None)
    oxford = {'address': {'addressLocality': 'Oxford',
                          'addressCountry': {'@type': 'Country', 'name': 'United Kingdom'}}}
    posting = {'@type': 'JobPosting', 'title': 'Research Assistant',
               'hiringOrganization': {'name': 'University'},
               'jobLocation': [oxford, {'address': 'Paris, France'}, oxford]}
    html = '<script type="application/ld+json">' + json.dumps(posting) + '</script>'
    items = _jobposting_items(html, 'https://example.org/job/1', 'test')
    assert len(items) == 1
    assert 'Oxford United Kingdom; Paris, France' in items[0].text
    assert "'@type'" not in items[0].text and 'None' not in items[0].text


def test_portal_detail_links_validate_before_counting_limit():
    from predoc_pipeline.ingest.collectors import _detail_links

    html = ('<a href="javascript:job(1)">Invalid</a>'
            '<a href="https://example.org:bad/job/1">Invalid</a>'
            '<a href="https://[bad/job/1">Invalid</a>'
            '<a href="/job/1?a=1&amp;b=2#requirements">First</a>'
            '<a href="/job/1?a=1&amp;b=2#application">Duplicate</a>'
            '<a href="/job/2">Second</a>')
    assert _detail_links(html, 'https://example.org/jobs', 'job', 2) == [
        'https://example.org/job/1?a=1&b=2', 'https://example.org/job/2',
    ]
    assert _detail_links(html, 'https://example.org/jobs', 'job', 0) == []
    assert _detail_links(html, 'https://example.org/jobs', 'job', -1) == []
    routes = '<a href="/#/job/1">One</a><a href="/#!/job/2">Two</a>'
    assert _detail_links(routes, 'https://example.org/jobs', 'job', 2) == [
        'https://example.org/#/job/1', 'https://example.org/#!/job/2',
    ]


@pytest.mark.parametrize('total,truncated', [(100, True), (20, False), (None, True)])
def test_workday_pagination_cap_reports_partial_discovery(tmp_path, total, truncated):
    from predoc_pipeline.core.health import source_status

    config = tmp_path / 'sources.toml'
    config.write_text('[[board]]\nname="workday"\ntype="workday"\n'
                      'url="https://test.myworkdayjobs.com/careers"\nmax_pages=1\n',
                      encoding='utf-8')
    calls = []

    def respond(request):
        calls.append(request)
        data = {'jobPostings': [
            {'title': f'Research Assistant {i}', 'externalPath': f'/job/role/JR{i}'}
            for i in range(20)
        ]}
        if total is not None:
            data['total'] = total
        return httpx.Response(200, json=data)

    prefs = Preferences()
    prefs.http.default_min_interval = 0
    stats = verify_boards(str(config), prefs, transport=httpx.MockTransport(respond))['workday']
    assert len(calls) == 1 and stats['items'] == 20
    assert stats['ok'] is not truncated
    assert stats['errors'] == int(truncated)
    if truncated:
        assert stats['failure_stage'] == 'limit' and source_status(stats) == 'partial'


def test_workday_missing_total_continues_until_short_page(tmp_path):
    import json

    config = tmp_path / 'sources.toml'
    config.write_text('[[board]]\nname="workday"\ntype="workday"\n'
                      'url="https://test.myworkdayjobs.com/careers"\nmax_pages=2\n',
                      encoding='utf-8')
    offsets = []

    def respond(request):
        offset = json.loads(request.content)['offset']
        offsets.append(offset)
        return httpx.Response(200, json={'jobPostings': [
            {'title': f'Research Assistant {i}', 'externalPath': f'/job/role/JR{i}'}
            for i in range(20)
        ] if offset == 0 else []})

    prefs = Preferences()
    prefs.http.default_min_interval = 0
    stats = verify_boards(str(config), prefs, transport=httpx.MockTransport(respond))['workday']
    assert offsets == [0, 20]
    assert stats['items'] == 20 and stats['ok'] and stats['errors'] == 0


@pytest.mark.parametrize('bad_first', [True, False])
def test_workday_failed_term_preserves_other_term_results(tmp_path, bad_first):
    import json

    from predoc_pipeline.core.health import source_status

    terms = ['bad', 'good'] if bad_first else ['good', 'bad']
    config = tmp_path / 'sources.toml'
    config.write_text('[[board]]\nname="workday"\ntype="workday"\n'
                      'url="https://test.myworkdayjobs.com/careers"\nmax_pages=2\n'
                      f'search_terms={json.dumps(terms)}\n', encoding='utf-8')
    called = []

    def respond(request):
        term = json.loads(request.content)['searchText']
        called.append(term)
        if term == 'bad':
            return httpx.Response(503)
        return httpx.Response(200, json={'total': 1, 'jobPostings': [
            {'title': 'Research Assistant', 'externalPath': '/job/role/JR1'}]})

    prefs = Preferences()
    prefs.http.default_min_interval = 0
    prefs.http.max_retries = 0
    stats = verify_boards(str(config), prefs, transport=httpx.MockTransport(respond))['workday']
    assert called == terms and stats['items'] == 1 and stats['errors'] == 1
    assert stats['failure_stage'] == 'fetch' and source_status(stats) == 'partial'


@pytest.mark.parametrize('total', ['100', -1, True, 0, 100])
def test_workday_invalid_or_incomplete_total_retains_postings(tmp_path, total):
    from predoc_pipeline.core.health import source_status

    config = tmp_path / 'sources.toml'
    config.write_text('[[board]]\nname="workday"\ntype="workday"\n'
                      'url="https://test.myworkdayjobs.com/careers"\nmax_pages=2\n',
                      encoding='utf-8')
    data = {'total': total, 'jobPostings': [
        {'title': 'Research Assistant', 'externalPath': '/job/role/JR1'}]}
    prefs = Preferences()
    prefs.http.default_min_interval = 0
    stats = verify_boards(str(config), prefs,
                          transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))
                          )['workday']
    assert stats['items'] == 1 and stats['errors'] == 1
    assert stats['failure_stage'] == 'parse' and source_status(stats) == 'partial'


@pytest.mark.parametrize('bad,expected', [
    (None, 1),
    ({'title': 'No path'}, 1),
    ({'title': {'name': 'Bad'}, 'externalPath': '/job/JR0'}, 1),
    ({'title': 'Bad', 'externalPath': 'https://other.example/job'}, 1),
    ({'title': 'Usable', 'externalPath': '/job/JR0', 'bulletFields': [42]}, 2),
    ({'title': 'Usable', 'externalPath': '/job/JR0', 'locationsText': {'city': 'London'}}, 2),
])
def test_workday_bad_entry_preserves_valid_neighbor(tmp_path, bad, expected):
    from predoc_pipeline.core.health import source_status

    config = tmp_path / 'sources.toml'
    config.write_text('[[board]]\nname="workday"\ntype="workday"\n'
                      'url="https://test.myworkdayjobs.com/careers"\n', encoding='utf-8')
    data = {'total': 2, 'jobPostings': [bad,
            {'title': 'Research Assistant', 'externalPath': '/job/role/JR1'}]}
    prefs = Preferences()
    prefs.http.default_min_interval = 0
    stats = verify_boards(str(config), prefs,
                          transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))
                          )['workday']
    assert stats['items'] == expected and stats['errors'] == 1
    assert stats['failure_stage'] == 'parse' and source_status(stats) == 'partial'


def test_workday_later_page_failure_preserves_full_first_page(tmp_path):
    import json

    from predoc_pipeline.core.health import source_status

    config = tmp_path / 'sources.toml'
    config.write_text('[[board]]\nname="workday"\ntype="workday"\n'
                      'url="https://test.myworkdayjobs.com/careers"\nmax_pages=2\n'
                      'search_terms=["first", "second"]\n', encoding='utf-8')
    calls = []

    def respond(request):
        payload = json.loads(request.content)
        term, offset = payload['searchText'], payload['offset']
        calls.append((term, offset))
        if offset:
            return httpx.Response(503)
        count = 20 if term == 'first' else 1
        return httpx.Response(200, json={'total': 100 if term == 'first' else 1,
            'jobPostings': [{'title': f'Research Assistant {term} {i}',
                             'externalPath': f'/job/{term}/JR{i}'} for i in range(count)]})

    prefs = Preferences()
    prefs.http.default_min_interval = 0
    prefs.http.max_retries = 0
    stats = verify_boards(str(config), prefs, transport=httpx.MockTransport(respond))['workday']
    assert calls == [('first', 0), ('first', 20), ('second', 0)]
    assert stats['items'] == 21 and stats['errors'] == 1
    assert stats['failure_stage'] == 'fetch' and source_status(stats) == 'partial'
