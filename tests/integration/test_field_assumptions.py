"""Source field defaults cannot override explicit off-topic advert evidence."""

import pytest

from predoc_pipeline.boards.config import FilterConfig
from predoc_pipeline.boards.filter import RelevanceFilter
from predoc_pipeline.boards.models import JobPostSchema


@pytest.mark.parametrize('implied', [True, False])
def test_explicit_off_topic_context_wins(implied):
    flt = RelevanceFilter(FilterConfig(role_terms=['research assistant'],
                                     field_terms=['economics'],
                                     field_exclude_terms=['protein folding', 'microscopy']))
    post = JobPostSchema(title='Research Assistant', url='https://example.org/job',
                         source='test', field_implied=implied,
                         description_snippet='Protein folding and microscopy experiments.')
    verdict = flt.evaluate(post)
    assert not verdict.keep
    assert verdict.reason == 'wrong-field-context'


def test_implied_field_can_fill_missing_evidence():
    flt = RelevanceFilter(FilterConfig(role_terms=['research assistant'],
                                     field_terms=['economics'],
                                     field_exclude_terms=['microscopy']))
    post = JobPostSchema(title='Research Assistant', url='https://example.org/job',
                         source='test', field_implied=True)
    assert flt.evaluate(post).keep
