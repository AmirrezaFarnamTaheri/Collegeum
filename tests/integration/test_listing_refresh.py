"""Fact refresh must preserve durable identity and publication history."""

import pytest

from predoc_pipeline.core.db import Database, init


def insert(db):
    return db.insert_listing({
        'url_hash': 'stable', 'apply_url': 'https://example.org/apply',
        'source_url': 'https://example.org/job', 'source': 'test',
        'title': 'Research Assistant', 'institution': 'University', 'country': '',
        'is_remote': 0, 'disciplines': '[]', 'summary': '', 'language': 'en',
        'visa_sponsorship_status': 'unknown', 'model_confidence': 0.9,
        'rule_score': 0.9, 'confidence': 0.9,
    })


def test_refresh_preserves_identity_delivery_and_closure(tmp_path):
    path = tmp_path / 'state.db'
    init(path)
    with Database(path) as db:
        listing_id = insert(db)
        db.mark_published(listing_id, 123)
        db.mark_closed(listing_id, 'explicitly filled')
        before = dict(db.listing(listing_id))
        db.refresh_listing_facts(listing_id, {
            'deadline': '2099-12-31T18:00:00Z', 'salary_min': 43250,
            'summary': 'Updated research responsibilities.',
        })
        after = dict(db.listing(listing_id))
        assert after['salary_min'] == 43250
        assert after['deadline'] == '2099-12-31T18:00:00Z'
        for field in ('id', 'url_hash', 'apply_url', 'source_url', 'source', 'status',
                      'first_seen_at', 'published_at', 'closed_at', 'closed_reason',
                      'telegram_message_id', 'x_post_id'):
            assert after[field] == before[field]


@pytest.mark.parametrize('field', ['url_hash', 'status', 'published_at', 'closed_at',
                                  'telegram_message_id', 'title=1;DROP TABLE listings'])
def test_refresh_rejects_identity_lifecycle_and_unknown_fields(tmp_path, field):
    path = tmp_path / 'state.db'
    init(path)
    with Database(path) as db:
        listing_id = insert(db)
        before = dict(db.listing(listing_id))
        with pytest.raises(ValueError, match='non-fact'):
            db.refresh_listing_facts(listing_id, {'summary': 'must not persist', field: 'bad'})
        assert dict(db.listing(listing_id)) == before
        with pytest.raises(ValueError, match='does not exist'):
            db.refresh_listing_facts(999, {'summary': 'missing'})
