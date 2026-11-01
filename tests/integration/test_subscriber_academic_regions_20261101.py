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
    member['academic_regions'] = {'all': _ts(2)}
    assert not eligible(member, 'predoc', '', _ts(3), country='Canada')
    assert eligible(member, 'predoc', '', _ts(1), country='Canada')


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


def test_legacy_python_menu_has_unified_career_and_academic_region_controls() -> None:
    from predoc_pipeline.publish.ui import menu

    member = {'topics': {'predoc': _ts(2), 'data_analyst': _ts(2)},
              'scopes': {'iran': _ts(2)}, 'academic_regions': {'europe': _ts(2)}}
    overview, overview_keyboard = menu(member, "subscriptions")
    codes = [button['callback_data'] for row in overview_keyboard['inline_keyboard']
             for button in row]
    assert "Edit subscriptions" in overview
    assert "sub:p:academic" in codes and "sub:p:careers" in codes
    assert "sub:p:markets" not in codes
    careers, careers_keyboard = menu(member, "careers")
    actions = [button['callback_data'] for row in careers_keyboard['inline_keyboard']
               for button in row]
    assert "sub:g:iran" in actions and "sub:g:remote" in actions
    assert "sub:t:data_analyst" in actions
    assert "sub:p:markets" not in actions
    academic, academics_keyboard = menu(member, "academic")
    assert "sub:p:academic_regions" in {
        button['callback_data'] for row in academics_keyboard['inline_keyboard']
        for button in row
    }
    regions, regions_keyboard = menu(member, "academic_regions")
    region_actions = {b["callback_data"] for row in regions_keyboard["inline_keyboard"]
                      for b in row}
    assert "Academic regions" in regions
    assert "sub:r:europe" in region_actions
    assert "sub:r:all" in region_actions


def test_encrypted_store_reset_to_worldwide_keeps_fresh_opt_in_timestamp(settings) -> None:
    from predoc_pipeline.publish.feedback import FeedbackStore

    store = FeedbackStore.from_settings(settings)
    store.toggle_subscription(202, "topics", "predoc")
    # Simulate an established subscription: only the new region reset may
    # disqualify an older advert; the original topic opt-in is five days old.
    store.subscriber(202)["topics"]["predoc"] = _ts(5)
    store.toggle_academic_region(202, "europe")
    store.toggle_academic_region(202, "europe")
    current = store.subscriber(202)
    assert current is not None
    assert set(current['academic_regions']) == {'all'}
    assert not eligible(current, "predoc", "", _ts(1), country="Germany")
    assert not current['deliveries']  # Regional toggles never create delivery receipts.
