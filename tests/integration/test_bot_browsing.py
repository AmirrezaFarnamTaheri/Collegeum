"""Interactive navigation stays private, bounded, and useful across sync runs."""

from datetime import timedelta

from predoc_pipeline.core.db import Database
from predoc_pipeline.core.timeparse import format_ts, utcnow
from predoc_pipeline.publish.feedback import FeedbackStore
from tests.integration.test_bot import (
    OWNER,
    FakeTelegram,
    add_listings,
    msg,
    rows_of,
    run_sync,
    tap,
)
from tests.integration.test_bot import settings as bot_settings

settings = bot_settings


def test_home_menu_has_navigation_and_open_count(settings):
    add_listings(settings)
    fake = FakeTelegram([msg(1, '/menu')])
    run_sync(settings, fake)
    message = fake.sent()[0]
    assert 'Collegeum' in message['text'] and '3 open' in message['text']
    labels = [b['text'] for r in message['reply_markup']['inline_keyboard'] for b in r]
    assert any('Saved' in label for label in labels)
    assert any('Closing' in label for label in labels)


def test_position_navigation_edits_one_message_instead_of_flooding_chat(settings):
    add_listings(settings)
    first = FakeTelegram([msg(1, '/positions')])
    run_sync(settings, first, page_size=2)
    assert len(first.sent()) == 1
    markup = first.sent()[0]['reply_markup']
    next_button = next(b for row in markup['inline_keyboard'] for b in row if 'Next' in b['text'])
    fake = FakeTelegram([tap(2, next_button['callback_data'], markup)])
    run_sync(settings, fake, page_size=2)
    edits = [body for method, body in fake.calls if method == 'editMessageText']
    assert len(edits) == 1 and 'Pre-doctoral Fellow' in edits[0]['text']
    assert 'Research Assistant in Finance' not in edits[0]['text']


def test_search_and_its_pagination_survive_fresh_bot_sync(settings):
    add_listings(settings)
    fake = FakeTelegram([msg(1, '/search finance')])
    run_sync(settings, fake)
    text = fake.sent()[0]['text']
    assert 'Research Assistant in Finance' in text and 'Predoc in Macroeconomics' not in text
    assert 'finance' in text.lower()
    empty = FakeTelegram([msg(2, '/search no-such-job')])
    run_sync(settings, empty)
    assert 'No matches' in empty.sent()[0]['text']


def test_search_without_query_explains_usage(settings):
    fake = FakeTelegram([msg(1, '/search')])
    run_sync(settings, fake)
    assert '/search' in fake.sent()[0]['text'] and 'economics' in fake.sent()[0]['text']


def test_closing_soon_and_recent_views_use_actual_dates(settings):
    add_listings(settings)
    with Database(settings.db_path) as db:
        db.conn.execute('UPDATE listings SET deadline=?, first_seen_at=? WHERE id=1',
                        (format_ts(utcnow() + timedelta(days=3)), format_ts()))
        db.conn.execute('UPDATE listings SET first_seen_at=? WHERE id<>1',
                        (format_ts(utcnow() - timedelta(days=30)),))
        db.conn.commit()
    for update, command in ((1, '/closing'), (2, '/new')):
        fake = FakeTelegram([msg(update, command)])
        run_sync(settings, fake)
        assert 'Predoc in Macroeconomics' in fake.sent()[0]['text']
        assert 'Research Assistant in Finance' not in fake.sent()[0]['text']


def test_navigation_callback_from_stranger_cannot_read_positions(settings):
    add_listings(settings)
    fake = FakeTelegram([tap(1, 'view|positions|0', {}, who=OWNER + 1)])
    summary = run_sync(settings, fake)
    assert summary['ignored'] == 1
    assert not any(method in ('sendMessage', 'editMessageText') for method, _ in fake.calls)


def test_saved_shortcut_and_details_preserve_feedback(settings):
    ids = add_listings(settings)
    store = FeedbackStore(settings.feedback_path)
    key = ids['Research Assistant in Finance']
    store.set(key, 'valid')
    store.save()
    fake = FakeTelegram([msg(1, '/saved')])
    run_sync(settings, fake)
    message = fake.sent()[0]
    assert 'Research Assistant in Finance' in message['text']
    button = next(b for r in message['reply_markup']['inline_keyboard'] for b in r
                  if b['callback_data'].startswith('detail|'))
    detail = FakeTelegram([tap(2, button['callback_data'], message['reply_markup'])])
    run_sync(settings, detail)
    assert any(m == 'editMessageText' and 'Research Assistant in Finance' in body['text']
               for m, body in detail.calls)
    assert FeedbackStore(settings.feedback_path).status(key) == 'valid'


def test_export_retry_restores_journal_on_fresh_runner(settings):
    import json
    from pathlib import Path

    from predoc_pipeline import state

    add_listings(settings)
    with Database(settings.db_path) as db:
        state.write_journal(db, settings.state_path)
    Path(settings.db_path).unlink()
    Path(settings.telegram_state_path).write_text(json.dumps({'exports_pending': True}))
    fake = FakeTelegram([])
    summary = run_sync(settings, fake)
    assert summary['failed'] == 0
    assert json.loads(Path(settings.telegram_state_path).read_text())['exports_pending'] is False
    assert len(rows_of(settings)) == 5
