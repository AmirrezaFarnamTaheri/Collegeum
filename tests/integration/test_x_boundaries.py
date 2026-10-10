"""X documented weights, full-field budgets and preflight request validation."""

from unittest.mock import MagicMock

import pytest
from twitter_text import extract_emojis_with_indices, parse_tweet

from predoc_pipeline.models import Discipline, Location, PredocListing, VisaStatus
from predoc_pipeline.publish.x import (
    XClient,
    XError,
    _truncate_weighted,
    format_thread,
    format_tweet,
    tweet_length,
)


def example(**overrides):
    data = dict(
        title='Research Assistant', institution='University of Oxford',
        location=Location(country='United Kingdom', city='Oxford'),
        summary='Empirical economics research.', disciplines=[Discipline.APPLIED_MICRO],
        apply_url='https://example.org/job?a=1&b=2', source_url='https://example.org/jobs',
        visa_sponsorship_status=VisaStatus.EXPLICIT,
        confidence=0.99, model_confidence=0.99, rule_score=0.99,
    )
    data.update(overrides)
    return PredocListing(**data)


@pytest.mark.parametrize(('text', 'weight'), [
    ('Hello', 5), ('漢字', 4), ('😀', 2), ('🙋🏽', 2), ('👨‍👩‍👧‍👦', 2),
    ('cafe\u0301', 4), ('https://example.org/a/long/path', 23),
    ('https://example.org/a).', 25), ('https://', 8),
])
def test_documented_character_weights(text, weight):
    assert tweet_length(text) == weight


@pytest.mark.parametrize('text', ['漢字' * 1000, '😀' * 1000, 'é\u0301' * 1000,
                                      '👨‍👩‍👧‍👦' * 1000, 'x' * 4000],
                         ids=['cjk', 'emoji', 'combining', 'family', 'latin'])
def test_every_listing_field_and_both_thread_posts_fit(text):
    listing = example(title=text, institution=text, summary=text,
                      location=Location(country=text, city=text),
                      deadline_note=text, visa_note=text)
    for post in [format_tweet(listing), *format_thread(listing)]:
        assert parse_tweet(post).valid
    assert listing.apply_url in format_tweet(listing)


@pytest.mark.parametrize(('title', 'label', 'tag'), [
    ('Predoctoral Research Assistant', 'Pre-Doctoral', '#Predoc'),
    ('PhD Studentship in Economics', 'PhD', '#PhD'),
    ('Postdoctoral Fellow in Economics', 'Postdoctoral', '#Postdoc'),
])
def test_role_heading_and_hashtag_follow_shared_classifier(title, label, tag):
    post = format_tweet(example(title=title))
    assert f'New {label} Opening' in post
    assert tag in post
    if label != 'Pre-Doctoral':
        assert '#Predoc' not in post


def test_truncation_preserves_complete_emoji_sequences():
    family = '👨‍👩‍👧‍👦'
    text = _truncate_weighted(family * 200, 40)
    assert text.endswith('…')
    assert tweet_length(text) <= 40
    assert text[:-1] == family * len(extract_emojis_with_indices(text))


@pytest.mark.parametrize('budget', [0, -1, 1, 281])
def test_impossible_or_unsupported_custom_budget_rejected(budget):
    with pytest.raises(ValueError):
        format_tweet(example(), max_chars=budget)


@pytest.mark.parametrize('text', ['', '  ', '漢' * 141, '\ufeffbad', '\ud800'])
def test_invalid_direct_posts_rejected_before_network(text):
    session = MagicMock()
    client = XClient(session=session)
    with pytest.raises(XError) as error:
        client.post_tweet(text)
    assert error.value.permanent
    session.post.assert_not_called()


def test_real_oauth_session():
    from requests_oauthlib import OAuth1Session

    session = XClient(consumer_key='test', consumer_secret='test')._get_oauth_session()
    assert isinstance(session, OAuth1Session)
    session.close()
