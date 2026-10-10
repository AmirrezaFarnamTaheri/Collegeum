from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from predoc_pipeline.core.timeparse import parse_datetime
from predoc_pipeline.extract.heuristic import HeuristicExtractor, _deadline_iso
from predoc_pipeline.models import ExtractionResult
from predoc_pipeline.pipeline import _merge_hints


@pytest.mark.parametrize("value", [
    "2026-10-15T17:30:00+03:30",
    "2026-10-15T23:45:00-07:00",
    "2026-10-15T00:15:00Z",
    "2026-10-15T12:00:00",
    datetime(2026, 10, 15, 17, 30, tzinfo=timezone(timedelta(hours=3, minutes=30))),
])
def test_board_extraction_preserves_stated_deadline_time(value):
    result = HeuristicExtractor().extract(
        text="Research assistant in economics.", title="Research Assistant",
        source_url="https://example.org/job", hints={"board": True, "deadline": value},
    )
    parsed = datetime.fromisoformat(result.deadline)
    expected = (
        value if isinstance(value, datetime)
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    assert parsed == expected
    assert parsed.utcoffset() == expected.utcoffset()
    assert parsed.hour == expected.hour


@pytest.mark.parametrize("value", [
    None, "", "2026-02-30", "2026-10-15junk", "rolling", "2026-10-15T99:00:00Z",
])
def test_invalid_deadline_does_not_manufacture_a_cutoff(value):
    assert _deadline_iso(value) is None


@pytest.mark.parametrize("value", ["2026-10-15", date(2026, 10, 15)])
def test_legacy_date_only_deadline_remains_open_through_its_day(value):
    assert _deadline_iso(value) == "2026-10-15T23:59:59Z"


@pytest.mark.parametrize("value", [
    "2026-10-15", "2026-10-15T17:30:00+03:30", "2026-10-15T23:45:00-07:00",
    "2026-02-30", "2026-10-15junk",
])
def test_missing_model_deadline_uses_validated_board_evidence(value):
    result = ExtractionResult(is_vacancy=True, title="Research Assistant", institution="University")
    merged = _merge_hints(result, {"board": True, "deadline": value})
    assert merged.deadline == _deadline_iso(value)
    assert result.deadline is None


def test_board_hints_do_not_replace_existing_model_deadline():
    result = ExtractionResult(
        is_vacancy=True, title="Research Assistant", institution="University",
        deadline="2026-10-15T17:30:00+03:30",
    )
    merged = _merge_hints(result, {"board": True, "deadline": "2026-10-20"})
    assert merged.deadline == result.deadline


@pytest.mark.parametrize("value", [
    "2026-10-15T99:00:00Z", "2026-10-15T12:99:00Z", "2026-10-15T12:00:99Z",
    "2026-10-15T12:00:00+25:00", "2026-10-15junk", "2026-10-15T",
    "0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-12:00",
])
def test_persistence_parser_does_not_turn_invalid_instants_into_calendar_dates(value):
    assert parse_datetime(value) is None


@pytest.mark.parametrize(("value", "expected"), [
    ("2026-10-15T00:15:00+03:30", "2026-10-14T20:45:00+00:00"),
    ("2026-10-15T23:45:00-07:00", "2026-10-16T06:45:00+00:00"),
])
def test_valid_instants_keep_the_same_instant_during_utc_persistence(value, expected):
    assert parse_datetime(value).isoformat() == expected


@pytest.mark.parametrize("offset", ["+03:99", "-03:60", "+0360", "+03:30:99", "-033060"])
def test_invalid_offset_components_are_not_normalized_into_a_different_cutoff(offset):
    value = "2026-10-15T12:00:00" + offset
    assert _deadline_iso(value) is None
    assert parse_datetime(value) is None


@pytest.mark.parametrize("offset", ["+03:30", "-07:00", "+0330", "+03:30:15", "+00:00"])
def test_valid_offset_components_remain_supported(offset):
    value = "2026-10-15T12:00:00" + offset
    assert _deadline_iso(value) is not None
    assert parse_datetime(value) == datetime.fromisoformat(value).astimezone(UTC)


@pytest.mark.parametrize("value", ["01-03-2060", "01/03/2060", "2060-03-01"])
def test_calendar_date_suffix_is_not_mistaken_for_a_timezone_offset(value):
    assert parse_datetime(value) == datetime(2060, 3, 1, tzinfo=UTC)
