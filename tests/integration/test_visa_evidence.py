"""Eligibility and moving expenses do not establish visa sponsorship."""

import pytest

from predoc_pipeline.boards.heuristics import detect_visa
from predoc_pipeline.extract.heuristic import HeuristicExtractor, visa_status


@pytest.mark.parametrize('text,status', [
    ('International applicants are welcome. Relocation assistance provided.', 'unknown'),
    ('Priority given to citizens.', 'unknown'),
    ('Canadians and permanent residents will be given priority.', 'unknown'),
    ('This position is open to EU citizens.', 'unknown'),
    ('You should be a British citizen.', 'unknown'),
    ('This position is open only to EU citizens.', 'not_offered'),
    ('You must be a British citizen.', 'not_offered'),
    ('Visa sponsorship is available.', 'explicit'),
    ('We can sponsor a visa.', 'explicit'),
    ('We cannot sponsor a visa.', 'not_offered'),
    ('No visa sponsorship.', 'not_offered'),
    ('Visa sponsorship is not available.', 'not_offered'),
    ('We cannot confirm that visa sponsorship is available.', 'unknown'),
    ('Not eligible for sponsorship.', 'unknown'),
    ('Relocation assistance is not provided.', 'unknown'),
    ('You must have the right to work in the UK.', 'unknown'),
    ('Visa sponsorship is available. Canadians will be given priority.', 'explicit'),
    ('International applicants are welcome. No visa sponsorship.', 'not_offered'),
])
def test_sponsorship_requires_distinct_evidence(text, status):
    assert visa_status(detect_visa(text)) == status
    assert visa_status(text) == status


def test_board_and_text_extractors_preserve_unknown_context():
    text = ('Research assistant at Example University. International applicants are welcome. '
            'Relocation assistance provided.')
    extractor = HeuristicExtractor()
    for hints in [{}, {'board': True, 'institution': 'Example University'}]:
        result = extractor.extract(text=text, title='Research assistant',
                                   source_url='https://example.edu/job', hints=hints)
        assert result.visa_sponsorship_status == 'unknown'
        assert 'International applications welcome' in result.visa_note
        assert 'Relocation assistance' in result.visa_note


def test_positive_support_retains_preference_without_changing_status():
    note = detect_visa('Visa sponsorship is available. Citizens will be given priority.')
    assert visa_status(note) == 'explicit'
    assert 'Priority to citizens/residents' in note
