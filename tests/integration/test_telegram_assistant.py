"""AI cannot bypass bounded read-only queries or supply the answer's facts."""

import json
from datetime import timedelta

import httpx
import pytest

from predoc_pipeline.core.timeparse import format_ts, utcnow
from predoc_pipeline.publish.assistant import (
    REFUSAL,
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
