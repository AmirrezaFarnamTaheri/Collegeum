"""AI cannot bypass bounded read-only queries or supply the answer's facts."""

import json
from datetime import timedelta

import httpx
import pytest

from predoc_pipeline.core.timeparse import format_ts, utcnow
from predoc_pipeline.publish.assistant import (
    NOT_CONFIGURED,
    REFUSAL,
    UNAVAILABLE,
    DatabaseQuery,
    ask_database,
    query_records,
    render_result,
    reserve_public_request,
)
from predoc_pipeline.publish.feedback import FeedbackStore
from predoc_pipeline.settings import Settings


def row(**extra):
    return {'id': 42, 'url_hash': 'a' * 64, 'title': 'Economics RA',
            'institution': 'Example University', 'country': 'Canada', 'kind': 'predoc',
            'visa': 'unknown', 'apply_url': 'https://example.org/job',
            'deadline': '2099-12-01T00:00:00Z', 'first_seen_at': format_ts(), **extra}


def response(arguments=None, content=None, name='query_database'):
    message = {'content': content}
    if arguments is not None:
        message['tool_calls'] = [{'function': {'name': name, 'arguments': json.dumps(arguments)}}]
    return httpx.Response(200, json={'choices': [{'message': message}]})


def ask(tmp_path, provider_response, *, owner=True):
    store = FeedbackStore(tmp_path / 'feedback.json')
    settings = Settings(_env_file=None, openrouter_api_key='offline-test-key')
    with httpx.Client(transport=httpx.MockTransport(lambda request: provider_response)) as client:
        answer = ask_database('Which roles offer visas?', [row()], store, settings,
                              user_id=42, owner=owner, client=client)
    return answer


def test_provider_prose_is_never_shown_as_a_database_answer(tmp_path):
    assert ask(tmp_path, response(content='Here is unrelated weather advice')) == REFUSAL


def test_refusal_and_arbitrary_sql_never_execute_or_return_provider_text(tmp_path):
    assert ask(tmp_path, response({'action': 'refuse'}, content='invented facts')) == REFUSAL
    assert ask(tmp_path, response({'action': 'list', 'sql': 'DROP TABLE listings'})) == REFUSAL
    assert ask(tmp_path, response({'action': 'list'}, name='shell')) == REFUSAL


def test_answer_uses_exact_stored_facts_and_source_links(tmp_path):
    answer = ask(tmp_path, response({'action': 'list', 'fields': ['visa', 'salary']},
                                    content='All visas guaranteed, salary $100000'))
    assert 'unknown' in answer and 'Unstated' in answer
    assert 'https://example.org/job' in answer and '#42' in answer
    assert 'guaranteed' not in answer and '100000' not in answer


def test_public_users_cannot_query_owner_application_marks(tmp_path):
    assert ask(tmp_path, response({'action': 'list', 'personal_status': 'applied'}),
               owner=False) == REFUSAL


def test_missing_deadline_never_matches_known_deadline_filter():
    query = DatabaseQuery(action='list', deadline_before='2099-12-31')
    assert query_records(query, [row(deadline=None)], {}, owner=True) == []
    with pytest.raises(ValueError):
        query_records(DatabaseQuery(action='list', deadline_before='2026-02-30'),
                      [row()], {}, owner=True)


def test_public_limit_is_three_per_rolling_minute_and_shared_per_hour(tmp_path):
    store = FeedbackStore(tmp_path / 'feedback.json')
    for _ in range(3):
        assert reserve_public_request(store, 1, owner=False, hourly_cap=4) is None
    assert '3 questions' in reserve_public_request(store, 1, owner=False, hourly_cap=4)
    assert reserve_public_request(store, 2, owner=False, hourly_cap=4) is None
    assert 'hourly' in reserve_public_request(store, 3, owner=False, hourly_cap=4)
    # Owners are exempt from both public limits, including after exhaustion.
    for _ in range(10):
        assert reserve_public_request(store, 1, owner=True, hourly_cap=4) is None
    assert len(store.data['assistant_usage']['public']) == 4
    store.data['assistant_usage']['public'] = [format_ts(utcnow() - timedelta(hours=2))]
    assert reserve_public_request(store, 3, owner=False, hourly_cap=4) is None


def test_result_rendering_is_bounded_and_html_escaped():
    query = DatabaseQuery(action='list', fields=['deadline', 'visa', 'salary', 'degree',
                                                'tools', 'start', 'summary'], limit=5)
    rows = [row(id=i, title='<b>Fake title</b>', summary='x' * 600, salary_raw='x' * 400,
                visa_note='x' * 400, degree_note='x' * 400, start_term='x' * 400,
                tools_required=['x' * 400]) for i in range(1, 6)]
    answer = render_result(query, rows, snapshot='2026-10-12')
    from predoc_pipeline.publish.telegram import telegram_visible_length

    assert telegram_visible_length(answer) <= 4096
    assert '&lt;b&gt;Fake title&lt;/b&gt;' in answer


def test_raw_questions_and_keys_are_not_saved_in_follow_up_state(tmp_path):
    store = FeedbackStore(tmp_path / 'feedback.json')
    settings = Settings(_env_file=None, openrouter_api_key='offline-test-key')
    with httpx.Client(transport=httpx.MockTransport(
            lambda r: response({'action': 'count'}))) as client:
        ask_database('private question text', [row()], store, settings,
                     user_id=42, owner=True, client=client)
    saved = (tmp_path / 'feedback.json').read_text()
    assert 'private question text' not in saved and 'offline-test-key' not in saved


def test_replayed_polling_request_reuses_prepared_result_without_spending_again(tmp_path):
    store = FeedbackStore(tmp_path / 'feedback.json')
    settings = Settings(_env_file=None, openrouter_api_key='offline-test-key')
    calls = []

    def handler(request):
        calls.append(request)
        return response({'action': 'count'})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = ask_database('Count roles', [row()], store, settings,
                             user_id=101, owner=False, request_id=7, client=client)
        second = ask_database('Count roles', [row()], store, settings,
                              user_id=101, owner=False, request_id=7, client=client)
    assert first == second and len(calls) == 1
    assert len(store.data['assistant_usage']['public']) == 1


@pytest.mark.parametrize('contents', [
    None, '{bad json', '[]', '{}', '{"system": 42, "tool": {}}',
    '{"system": "Rules", "tool": {"type": "function", "function": null}}',
    '{"system": "Rules", "tool": {"type": "function", "function": '
    '{"name": "query_database", "parameters": {}}}}',
])
def test_unavailable_protocol_is_cached_without_quota_or_provider_work(tmp_path, contents):
    protocol = tmp_path / 'custom-protocol.json'
    if contents is not None:
        protocol.write_text(contents, encoding='utf-8')
    store = FeedbackStore(tmp_path / 'feedback.json')
    settings = Settings(_env_file=None, openrouter_api_key='offline-test-key',
                        telegram_ai_protocol_path=str(protocol))

    def handler(request):
        pytest.fail('An unusable protocol must not invoke OpenRouter')

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        answer = ask_database('Count roles', [row()], store, settings,
                              user_id=101, owner=False, request_id=7, client=client)
        assert answer == NOT_CONFIGURED
        persisted = FeedbackStore(tmp_path / 'feedback.json')
        assert 'assistant_usage' not in persisted.data
        assert persisted.data['assistant_replies']['101:7']['answer'] == answer
        # A polling replay reuses the prepared response even if configuration changes.
        protocol.write_text('{}', encoding='utf-8')
        assert ask_database('Count roles', [row()], persisted, settings,
                            user_id=101, owner=False, request_id=7, client=client) == answer


@pytest.mark.parametrize('failure', ['transport', 'json', 'envelope'])
def test_provider_failure_uses_next_key_and_reserves_only_once(tmp_path, failure):
    store = FeedbackStore(tmp_path / 'feedback.json')
    settings = Settings(_env_file=None, openrouter_api_key='first second')
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            if failure == 'transport':
                raise httpx.ReadTimeout('offline timeout', request=request)
            return httpx.Response(200, text='invalid' if failure == 'json' else '{}')
        return response({'action': 'count'})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        answer = ask_database('Count roles', [row()], store, settings,
                              user_id=101, owner=False, request_id=9, client=client)
    assert '1 matching record' in answer and len(calls) == 2
    assert len(store.data['assistant_usage']['public']) == 1


@pytest.mark.parametrize('responses,expected', [
    ([httpx.Response(200, text='invalid'), httpx.Response(429)], UNAVAILABLE),
    ([httpx.Response(429), httpx.Response(429)], 'The AI provider is busy.'),
    ([response({'action': 'list', 'sql': 'bad'})], REFUSAL),
])
def test_provider_outage_is_distinct_from_refused_tool_arguments(tmp_path, responses, expected):
    store = FeedbackStore(tmp_path / 'feedback.json')
    settings = Settings(_env_file=None, openrouter_api_key='first second')
    calls = []

    def handler(request):
        calls.append(request)
        return responses[len(calls) - 1]

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        answer = ask_database('Count roles', [row()], store, settings,
                              user_id=101, owner=False, client=client)
    assert answer.startswith(expected)
    assert len(calls) == len(responses)


def test_provider_retries_share_one_monotonic_budget(tmp_path, monkeypatch):
    from predoc_pipeline.publish import assistant

    clock = iter([100.0, 100.0, 120.0, 126.0])
    monkeypatch.setattr(assistant.time, 'monotonic', lambda: next(clock))
    store = FeedbackStore(tmp_path / 'feedback.json')
    settings = Settings(_env_file=None, openrouter_api_key='first second third')
    timeouts = []

    class Client:
        def post(self, url, *, headers, json, timeout):
            timeouts.append(timeout)
            raise httpx.ConnectError('offline failure')

    answer = ask_database('Count roles', [row()], store, settings,
                          user_id=101, owner=False, client=Client())
    assert answer == UNAVAILABLE
    assert timeouts == [20, 5]
    assert len(store.data['assistant_usage']['public']) == 1


def test_oversized_answer_keeps_snapshot_and_truncation_notice():
    from predoc_pipeline.publish.telegram import telegram_visible_length
    query = DatabaseQuery(action='list', fields=[
        'deadline', 'visa', 'salary', 'degree', 'tools', 'start', 'summary',
    ], limit=5)
    rows = [
        row(id=i, title='Very long vacancy ' + 'T' * 110,
            institution='Research center ' + 'I' * 95,
            summary='x' * 650, visa_note='v' * 600,
            salary_raw='s' * 600, degree_note='d' * 600,
            start_term='t' * 600, tools_required=['p' * 600])
        for i in range(1, 6)
    ]
    result = render_result(query, rows, snapshot='2026-10-13T11:02:03Z')
    assert telegram_visible_length(result) <= 4096
    assert 'Snapshot: 2026-10-13T11:02:03Z' in result
    assert 'Showing' in result and 'matching records' in result
    assert 'Ask for specific IDs' in result


def test_replay_after_crash_does_not_reserve_public_quota_twice(tmp_path):
    store = FeedbackStore(tmp_path / 'feedback.json')
    settings = Settings(_env_file=None, openrouter_api_key='offline-test-key')

    class CrashingClient:
        def post(self, url, *, headers, json, timeout):
            raise KeyboardInterrupt('simulated runner termination')

    with pytest.raises(KeyboardInterrupt):
        ask_database('Count roles', [row()], store, settings,
                     user_id=101, owner=False, request_id=77, client=CrashingClient())
    recovered = FeedbackStore(tmp_path / 'feedback.json')
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: response({'action': 'count'}))) as client:
        result = ask_database('Count roles', [row()], recovered, settings,
                              user_id=101, owner=False, request_id=77, client=client)
    assert '1 matching record' in result
    assert len(recovered.data['assistant_usage']['public']) == 1
