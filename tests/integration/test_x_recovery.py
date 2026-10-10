"""Exercise durable X progress, uncertain submissions and concurrent publishers."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from unittest.mock import MagicMock

import pytest

from predoc_pipeline.models import Location, PredocListing
from predoc_pipeline.publish.x import XClient, XError


def response(status=201, post_id='101'):
    result = MagicMock()
    result.status_code = status
    result.headers = {}
    result.text = 'Test response'
    result.json.return_value = {'data': {'id': post_id}}
    return result


def client(path, responses):
    session = MagicMock()
    session.post.side_effect = responses
    return XClient(session=session, thread_journal_path=path, publication_scope='account-1')


@pytest.mark.parametrize('failure', [None, response(429), TimeoutError('timeout')],
                         ids=['acknowledged', 'rejected', 'uncertain'])
def test_single_listing_recovery_survives_cache_loss(tmp_path, failure):
    listing = PredocListing(
        title='Research Assistant', institution='University of Oxford',
        location=Location(country='United Kingdom'), summary='Empirical economics research.',
        apply_url='https://example.org/job', source_url='https://example.org/jobs',
        confidence=0.99, model_confidence=0.99, rule_score=0.99,
    )
    path = tmp_path / 'single.sqlite3'
    first = client(path, [response() if failure is None else failure])
    if failure is None:
        assert first.post_listing(listing) == '101'
    else:
        with pytest.raises(XError):
            first.post_listing(listing)
    path.unlink()
    second = client(path, [response(post_id='102')])
    if isinstance(failure, TimeoutError):
        with pytest.raises(XError) as caught:
            second.post_listing(listing)
        assert caught.value.uncertain
        second._session.post.assert_not_called()
    else:
        assert second.post_listing(listing) == ('101' if failure is None else '102')
        assert second._session.post.call_count == (0 if failure is None else 1)


@pytest.mark.parametrize('failed_index', range(4))
def test_retry_restores_acknowledged_ids_after_database_cache_loss(tmp_path, failed_index):
    path = tmp_path / 'threads.sqlite3'
    posts = ['Root', 'Details', 'Eligibility', 'Apply']
    first = client(path, [*[response(post_id=str(101 + i)) for i in range(failed_index)],
                          response(429)])
    with pytest.raises(XError) as caught:
        first.post_thread(posts)
    error = caught.value
    assert error.created_ids == tuple(str(101 + i) for i in range(failed_index))
    assert error.next_index == failed_index and not error.uncertain and error.status == 429
    journal = json.loads(path.with_suffix('.ndjson').read_text())
    assert journal['ids'] == list(error.created_ids) and journal['pending'] == 0
    path.unlink()  # The durable text journal must suffice on a fresh runner.
    second = client(path, [response(post_id=str(101 + i)) for i in range(failed_index, 4)])
    assert second.post_thread(posts) == ['101', '102', '103', '104']
    assert second._session.post.call_count == 4 - failed_index
    payload = second._session.post.call_args_list[0].kwargs['json']
    if failed_index:
        assert payload['reply']['in_reply_to_tweet_id'] == str(100 + failed_index)
    else:
        assert 'reply' not in payload
    third = client(path, [])
    assert third.post_thread(posts) == ['101', '102', '103', '104']
    third._session.post.assert_not_called()


@pytest.mark.parametrize('failure', [TimeoutError('timeout'), response(500), response(201, None)],
                         ids=['transport', 'server-error', 'malformed-success'])
def test_unknown_submission_blocks_replay_until_verified_resolution(tmp_path, failure):
    path = tmp_path / 'threads.sqlite3'
    posts = ['Root', 'Details', 'Eligibility']
    first = client(path, [response(), failure])
    with pytest.raises(XError) as caught:
        first.post_thread(posts)
    error = caught.value
    assert error.created_ids == ('101',) and error.next_index == 1 and error.uncertain
    second = client(path, [response(post_id='103')])
    with pytest.raises(XError) as retry:
        second.post_thread(posts)
    assert retry.value.created_ids == ('101',) and retry.value.uncertain
    second._session.post.assert_not_called()
    second.thread_journal.resolve(error.thread_key, post_id='102')
    assert second.post_thread(posts) == ['101', '102', '103']
    assert second._session.post.call_args.kwargs['json']['reply'] == {
        'in_reply_to_tweet_id': '102',
    }


def test_process_interruption_leaves_submission_intent(tmp_path):
    path = tmp_path / 'threads.sqlite3'
    first = client(path, [response(), KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        first.post_thread(['Root', 'Details'])
    path.unlink()
    second = client(path, [response(post_id='102')])
    with pytest.raises(XError) as caught:
        second.post_thread(['Root', 'Details'])
    assert caught.value.created_ids == ('101',) and caught.value.uncertain
    second._session.post.assert_not_called()
    second.thread_journal.resolve(caught.value.thread_key, confirmed_not_created=True)
    assert second.post_thread(['Root', 'Details']) == ['101', '102']


def test_acknowledgement_write_failure_returns_observed_id_and_blocks_replay(tmp_path, monkeypatch):
    path = tmp_path / 'threads.sqlite3'
    first = client(path, [response()])
    original = first.thread_journal._export
    calls = 0

    def fail_ack(connection):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError('disk full')
        original(connection)

    monkeypatch.setattr(first.thread_journal, '_export', fail_ack)
    with pytest.raises(XError) as caught:
        first.post_thread(['Root', 'Details'])
    assert caught.value.created_ids == ('101',) and caught.value.uncertain
    stored = json.loads(path.with_suffix('.ndjson').read_text())
    assert stored['ids'] == [] and stored['pending'] == 1
    second = client(path, [response(post_id='102')])
    with pytest.raises(XError):
        second.post_thread(['Root', 'Details'])
    second._session.post.assert_not_called()
    second.thread_journal.resolve(caught.value.thread_key, post_id='101')
    assert second.post_thread(['Root', 'Details']) == ['101', '102']


def test_intent_write_failure_prevents_network_submission(tmp_path, monkeypatch):
    path = tmp_path / 'threads.sqlite3'
    first = client(path, [response()])
    original = first.thread_journal._export
    calls = 0

    def fail_intent(connection):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('disk full')
        original(connection)

    monkeypatch.setattr(first.thread_journal, '_export', fail_intent)
    with pytest.raises(XError):
        first.post_thread(['Root'])
    first._session.post.assert_not_called()
    assert json.loads(path.with_suffix('.ndjson').read_text())['pending'] == 0


@pytest.mark.parametrize('contents', ['', '{broken', '[]',
                                       '{"version":true}', '{"version":99}'])
def test_corrupt_journal_preserved_and_never_replayed(tmp_path, contents):
    path = tmp_path / 'threads.sqlite3'
    journal = path.with_suffix('.ndjson')
    journal.write_text(contents)
    publisher = client(path, [response()])
    with pytest.raises(XError):
        publisher.post_thread(['Root'])
    assert journal.read_text() == contents
    publisher._session.post.assert_not_called()


def test_changed_logical_thread_preserves_existing_progress(tmp_path):
    publisher = client(tmp_path / 'threads.sqlite3', [response(), response(429)])
    with pytest.raises(XError):
        publisher.post_thread(['Root', 'Details'], thread_key='listing:1')
    with pytest.raises(XError) as caught:
        publisher.post_thread(['Changed root', 'Details'], thread_key='listing:1')
    assert caught.value.created_ids == ('101',) and caught.value.permanent
    assert publisher._session.post.call_count == 2


def test_concurrent_publishers_do_not_repeat_claimed_segment(tmp_path):
    path = tmp_path / 'threads.sqlite3'
    entered, release = Event(), Event()
    first = client(path, [])

    def delayed_post(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return response()

    first._session.post.side_effect = delayed_post
    second = client(path, [])
    with ThreadPoolExecutor(max_workers=1) as executor:
        work = executor.submit(first.post_thread, ['Root'])
        try:
            assert entered.wait(10)
            with pytest.raises(XError) as caught:
                second.post_thread(['Root'])
            assert caught.value.uncertain
            second._session.post.assert_not_called()
        finally:
            release.set()
        assert work.result(timeout=10) == ['101']
    first._session.post.assert_called_once()


def test_all_thread_segments_preflighted_before_root_is_sent(tmp_path):
    path = tmp_path / 'threads.sqlite3'
    publisher = client(path, [response()])
    with pytest.raises(XError):
        publisher.post_thread(['Root', '漢' * 141])
    publisher._session.post.assert_not_called()
    assert not path.exists()


@pytest.mark.parametrize('post_id', [None, True, 123, '', '0', '0001', '１２３',
                                    'x', '1' * 5000, str(2**64)])
def test_invalid_success_identifiers_are_unknown_outcomes(tmp_path, post_id):
    publisher = client(tmp_path / 'threads.sqlite3', [response(201, post_id)])
    with pytest.raises(XError) as caught:
        publisher.post_tweet('Root')
    assert caught.value.uncertain and caught.value.status == 201


def test_owned_oauth_session_reused_and_closed_once(monkeypatch):
    constructor = MagicMock()
    monkeypatch.setattr('requests_oauthlib.OAuth1Session', constructor)
    with XClient() as publisher:
        assert publisher._get_oauth_session() is publisher._get_oauth_session()
    constructor.assert_called_once()
    constructor.return_value.close.assert_called_once()
    publisher.close()
    constructor.return_value.close.assert_called_once()
    external = MagicMock()
    with XClient(session=external):
        pass
    external.close.assert_not_called()


def test_stable_account_scope_survives_credential_rotation_without_reposting(tmp_path):
    path = tmp_path / 'threads.sqlite3'
    first = client(path, [response()])
    first.consumer_key, first.access_token = 'original-consumer', 'original-token'
    assert first.post_thread(['Root']) == ['101']
    second = client(path, [])
    second.consumer_key, second.access_token = 'rotated-consumer', 'rotated-token'
    assert second.post_thread(['Root']) == ['101']
    second._session.post.assert_not_called()
    raw = path.with_suffix('.ndjson').read_text()
    assert 'original-token' not in raw and 'rotated-token' not in raw and 'Root' not in raw
    other = client(path, [response(post_id='201')])
    other.publication_scope = 'account-2'
    assert other.post_thread(['Root']) == ['201']


@pytest.mark.parametrize('post_id', ['x', '0', '0001', '１２３', str(2**64)])
def test_invalid_reply_id_never_sent(tmp_path, post_id):
    publisher = client(tmp_path / 'threads.sqlite3', [response()])
    with pytest.raises(XError) as caught:
        publisher.post_tweet('Reply', in_reply_to_tweet_id=post_id)
    assert caught.value.permanent
    publisher._session.post.assert_not_called()


@pytest.mark.parametrize('payload', [None, [], {}, {'errors': [{'title': 'Forbidden'}]},
                                   {'includes': []}, {'data': {}}, {'data': [{}]},
                                   {'data': [None]}, {'includes': {'users': [None]}},
                                   {'includes': {'users': [{'id': 'bad'}]}}])
def test_malformed_search_payload_fails_explicitly(tmp_path, payload):
    publisher = client(tmp_path / 'threads.sqlite3', [])
    publisher.bearer_token = 'test'
    search = MagicMock()
    search.get.return_value.status_code = 200
    search.get.return_value.json.return_value = payload
    with pytest.raises(XError):
        publisher.search_recent('economics', http_client=search)


def test_malformed_success_json_is_an_unknown_submission(tmp_path):
    malformed = response()
    malformed.json.side_effect = ValueError('Invalid JSON')
    publisher = client(tmp_path / 'threads.sqlite3', [malformed])
    with pytest.raises(XError) as caught:
        publisher.post_thread(['Root'])
    assert caught.value.uncertain and caught.value.status == 201


def test_invalid_resolution_choices_do_not_change_pending_journal(tmp_path):
    path = tmp_path / 'threads.sqlite3'
    publisher = client(path, [TimeoutError('timeout')])
    with pytest.raises(XError) as caught:
        publisher.post_thread(['Root'])
    original = path.with_suffix('.ndjson').read_bytes()
    for choices in [{}, {'post_id': '101', 'confirmed_not_created': True}, {'post_id': '0'}]:
        with pytest.raises((ValueError, RuntimeError)):
            publisher.thread_journal.resolve(caught.value.thread_key, **choices)
        assert path.with_suffix('.ndjson').read_bytes() == original


def test_listing_thread_can_resume_next_day_without_countdown_content_drift(tmp_path, monkeypatch):
    listing = PredocListing(
        title='Research Assistant', institution='University of Oxford',
        location=Location(country='United Kingdom'), summary='Empirical economics research.',
        apply_url='https://example.org/job', source_url='https://example.org/jobs',
        deadline=datetime(2026, 10, 8, tzinfo=UTC),
        confidence=0.99, model_confidence=0.99, rule_score=0.99,
    )
    monkeypatch.setattr('predoc_pipeline.core.timeparse.utcnow',
                        lambda: datetime(2026, 10, 5, tzinfo=UTC))
    path = tmp_path / 'threads.sqlite3'
    first = client(path, [response(), response(429)])
    with pytest.raises(XError) as caught:
        first.post_listing(listing, as_thread=True)
    assert caught.value.created_ids == ('101',)
    monkeypatch.setattr('predoc_pipeline.core.timeparse.utcnow',
                        lambda: datetime(2026, 10, 6, tzinfo=UTC))
    second = client(path, [response(post_id='102')])
    assert second.post_listing(listing, as_thread=True) == '101'
    second._session.post.assert_called_once()
    assert second._session.post.call_args.kwargs['json']['reply'] == {
        'in_reply_to_tweet_id': '101',
    }


@pytest.mark.parametrize(('field', 'value'), [
    ('count', True), ('count', 0), ('ids', '["101"]'), ('ids', ['101', '101']),
    ('pending', True), ('fingerprint', 'bad'),
])
def test_invalid_nested_journal_fields_preserved(tmp_path, field, value):
    path = tmp_path / 'threads.sqlite3'
    first = client(path, [response(), response(429)])
    with pytest.raises(XError):
        first.post_thread(['Root', 'Details'])
    journal = path.with_suffix('.ndjson')
    record = json.loads(journal.read_text())
    record[field] = value
    damaged = json.dumps(record)
    journal.write_text(damaged)
    second = client(path, [])
    with pytest.raises(XError):
        second.post_thread(['Root', 'Details'])
    second._session.post.assert_not_called()
    assert journal.read_text() == damaged


def test_older_text_snapshot_cannot_erase_newer_cache_acknowledgements(tmp_path):
    path = tmp_path / 'threads.sqlite3'
    first = client(path, [response(429)])
    with pytest.raises(XError):
        first.post_thread(['Root', 'Details'])
    journal = path.with_suffix('.ndjson')
    older = journal.read_bytes()
    second = client(path, [response(), response(post_id='102')])
    assert second.post_thread(['Root', 'Details']) == ['101', '102']
    journal.write_bytes(older)
    third = client(path, [])
    assert third.post_thread(['Root', 'Details']) == ['101', '102']
    third._session.post.assert_not_called()
    assert json.loads(journal.read_text())['ids'] == ['101', '102']


def test_older_cache_restores_more_advanced_text_acknowledgements(tmp_path):
    path = tmp_path / 'threads.sqlite3'
    first = client(path, [response(429)])
    with pytest.raises(XError):
        first.post_thread(['Root', 'Details'])
    older_cache = path.read_bytes()
    second = client(path, [response(), response(post_id='102')])
    assert second.post_thread(['Root', 'Details']) == ['101', '102']
    path.write_bytes(older_cache)
    third = client(path, [])
    assert third.post_thread(['Root', 'Details']) == ['101', '102']
    third._session.post.assert_not_called()


def test_pending_cache_intent_is_preserved_when_text_snapshot_says_ready(tmp_path):
    path = tmp_path / 'threads.sqlite3'
    first = client(path, [TimeoutError('timeout')])
    with pytest.raises(XError):
        first.post_thread(['Root'])
    journal = path.with_suffix('.ndjson')
    older = json.loads(journal.read_text())
    older['pending'] = 0
    journal.write_text(json.dumps(older))
    second = client(path, [])
    with pytest.raises(XError) as caught:
        second.post_thread(['Root'])
    assert caught.value.uncertain
    second._session.post.assert_not_called()
    assert json.loads(journal.read_text())['pending'] == 1


def test_conflicting_acknowledgement_sequences_fail_without_overwriting_either(tmp_path):
    path = tmp_path / 'threads.sqlite3'
    first = client(path, [response()])
    assert first.post_thread(['Root']) == ['101']
    journal = path.with_suffix('.ndjson')
    other = json.loads(journal.read_text())
    other['ids'] = ['999']
    damaged = json.dumps(other)
    journal.write_text(damaged)
    second = client(path, [])
    with pytest.raises(XError) as caught:
        second.post_thread(['Root'])
    assert caught.value.created_ids == ('101',)
    second._session.post.assert_not_called()
    assert journal.read_text() == damaged


def test_confirmed_empty_search_metadata_returns_no_results(tmp_path):
    publisher = client(tmp_path / 'threads.sqlite3', [])
    publisher.bearer_token = 'test'
    search = MagicMock()
    search.get.return_value.status_code = 200
    search.get.return_value.json.return_value = {'meta': {'result_count': 0}}
    assert publisher.search_recent('economics', http_client=search) == []
