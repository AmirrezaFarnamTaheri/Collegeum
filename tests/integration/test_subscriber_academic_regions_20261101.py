"""Native Telegram academic geography and encrypted preference contract tests."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from predoc_pipeline.publish.cloud import _validate_subscribers
from predoc_pipeline.publish.subscriptions import academic_region, eligible, selected


def _ts(days: int = 1) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


@pytest.mark.parametrize(('country', 'expected'), [
    ('Germany', 'europe'), ('UK', 'europe'), ('United States', 'north_america'),
    ('Canada', 'north_america'), ('Mexico', 'latin_america'),
    ('Iran', 'middle_east'), ('India', 'asia'), ('Australia', 'oceania'),
    ('South Africa', 'africa'), ('', 'unknown'),
])
def test_academic_region_aliases_match_cloudflare(country: str, expected: str) -> None:
    assert academic_region(country) == expected


def test_academic_region_filter_is_worldwide_by_default_and_can_be_restricted() -> None:
    member = {'topics': {'predoc': _ts(3)}, 'scopes': {'remote': _ts(3)}}
    assert selected(member, 'predoc', '', country='Germany')
    assert selected(member, 'predoc', '', country='')
    member['academic_regions'] = {'europe': _ts(2)}
    assert selected(member, 'predoc', '', country='Germany')
    assert not selected(member, 'predoc', '', country='United States')
    assert not selected(member, 'predoc', '', country='')
    assert selected(member, 'data_analyst', 'remote', country='United States') is False
    member['topics']['data_analyst'] = _ts(3)
    assert selected(member, 'data_analyst', 'remote', country='United States')


def test_region_opt_in_date_never_backfills_old_notifications() -> None:
    member = {'topics': {'predoc': _ts(5)}, 'scopes': {},
              'academic_regions': {'europe': _ts(2)}}
    assert not eligible(member, 'predoc', '', _ts(3), country='Germany')
    assert eligible(member, 'predoc', '', _ts(1), country='Germany')
    assert not eligible(member, 'predoc', '', _ts(1), country='Canada')
    member['academic_regions'] = {}
    assert eligible(member, 'predoc', '', _ts(3), country='Canada')


def test_webhook_profile_accepts_legacy_regions_and_validates_new_selectors() -> None:
    member = {
        'topics': {'predoc': _ts(2)}, 'scopes': {}, 'paused': False,
        'language': 'en', 'delivery_mode': 'instant', 'daily_limit': 6,
        'quiet_hours': False, 'timezone': 'UTC',
    }
    restored = _validate_subscribers({'42': member})
    assert restored['42']['academic_regions'] == {}
    member_with = dict(member, academic_regions={'europe': _ts(1)})
    assert _validate_subscribers({'42': member_with})['42']['academic_regions']
    with pytest.raises(ValueError):
        _validate_subscribers({'42': dict(member, academic_regions={'fake': _ts(1)})})
