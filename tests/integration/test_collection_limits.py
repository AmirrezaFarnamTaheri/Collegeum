"""Invalid limits fail before creating a zero-worker collection queue."""

import asyncio

import pytest
from pydantic import ValidationError

from predoc_pipeline.boards.collector import _scrape_all, check_links
from predoc_pipeline.boards.config import EnrichConfig, HttpConfig


@pytest.mark.parametrize('model,field,value', [
    (HttpConfig, 'max_concurrent_sources', 0),
    (HttpConfig, 'max_concurrent_sources', -1),
    (HttpConfig, 'timeout', 0),
    (HttpConfig, 'source_timeout', float('inf')),
    (HttpConfig, 'backoff_base', float('nan')),
    (HttpConfig, 'default_min_interval', -1),
    (HttpConfig, 'max_retries', -1),
    (EnrichConfig, 'detail_concurrency', 0),
    (EnrichConfig, 'max_details_per_run', -1),
    (EnrichConfig, 'recheck_every_days', float('nan')),
    (EnrichConfig, 'recheck_max_per_run', -1),
])
def test_invalid_collection_settings_rejected_on_load_and_assignment(model, field, value):
    with pytest.raises(ValidationError):
        model(**{field: value})
    config = model()
    original = getattr(config, field)
    with pytest.raises(ValidationError):
        setattr(config, field, value)
    assert getattr(config, field) == original


def test_zero_optional_budgets_remain_supported():
    HttpConfig(max_retries=0, backoff_base=0, default_min_interval=0)
    EnrichConfig(max_details_per_run=0, recheck_max_per_run=0, recheck_every_days=0)


def test_direct_collectors_reject_invalid_limits_without_network():
    with pytest.raises(ValueError, match='concurrency must be positive'):
        asyncio.run(_scrape_all([], 0, 30))
    with pytest.raises(ValueError, match='finite and positive'):
        asyncio.run(_scrape_all([], 1, float('nan')))
    with pytest.raises(ValueError, match='concurrency must be positive'):
        check_links({}, HttpConfig(), concurrency=0)
