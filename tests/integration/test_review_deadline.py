"""Review scheduling must not manufacture a hard application cutoff."""

from datetime import date

import pytest

from predoc_pipeline.boards.utils.dates import extract_deadline


@pytest.mark.parametrize('text', [
    'First review date October 7, 2026. Deadline November 1, 2026.',
    'Deadline: rolling. Final application deadline: November 1, 2026.',
    'Deadline for applications: 01/11/2026. Applications processed on a rolling basis.',
])
def test_fixed_deadline_wins_over_review_and_rolling(text):
    assert extract_deadline(text, date(2026, 10, 5))[0] == date(2026, 11, 1)


def test_review_only_preserves_note_without_expiring_job():
    value, note = extract_deadline('Deadline: First review date October 7, 2026, then rolling')
    assert value is None
    assert 'October 7, 2026' in note
    assert 'rolling' in note


@pytest.mark.parametrize('text', ['Start ASAP. Deadline not stated.',
                                  'Start as soon as possible; review timing unstated.'])
def test_start_urgency_is_not_rolling_recruitment(text):
    assert extract_deadline(text) == (None, None)


@pytest.mark.parametrize('label', ['Start date', 'Starting on', 'Expected start',
                                  'Commencement', 'Interview date', 'Posted on',
                                  'Publication date'])
def test_other_date_labels_do_not_fill_an_unknown_cutoff(label):
    assert extract_deadline(f'Deadline: not stated. {label}: November 1, 2026.')[0] is None


def test_actual_deadline_before_start_label_is_preserved():
    value, _ = extract_deadline('Deadline: November 1, 2026. Start date: December 1, 2026.')
    assert value == date(2026, 11, 1)
