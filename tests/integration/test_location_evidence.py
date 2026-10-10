"""Advert locations can replace a source's headquarters default."""

import pytest

from predoc_pipeline.boards.heuristics import apply_heuristics
from predoc_pipeline.boards.models import JobPostSchema


@pytest.mark.parametrize('location,country,region', [
    ('Shanghai, China', 'China', 'Other'),
    ('Singapore', 'Singapore', 'Other'),
    ('Tokyo, Japan', 'Japan', 'Other'),
    ('Sydney, Australia', 'Australia', 'Other'),
    ('Auckland, New Zealand', 'New Zealand', 'Other'),
    ('Mumbai, India', 'India', 'Other'),
    ('Seoul, South Korea', 'South Korea', 'Other'),
    ('Dubai, United Arab Emirates', 'United Arab Emirates', 'Other'),
    ('Nairobi, Kenya', 'Kenya', 'Other'),
    ('São Paulo, Brazil', 'Brazil', 'Other'),
    ('Bogotá, Colombia', 'Colombia', 'Other'),
    ('Kuala Lumpur, Malaysia', 'Malaysia', 'Other'),
    ('Tehran, Iran', 'Iran', 'Other'),
    ('Zurich, Switzerland', 'Switzerland', 'Europe'),
    ('Toronto, Canada', 'Canada', 'Canada'),
    ('London, United Kingdom', 'United Kingdom', 'UK'),
    ('London, Canada', 'Canada', 'Canada'),
    ('Cambridge, United States', 'United States', 'US'),
    ('Santiago, Spain', 'Spain', 'Europe'),
])
def test_advert_replaces_source_country_default(location, country, region):
    post = JobPostSchema(title='Research Assistant', source='test',
                         url='https://example.edu/job', country='United States', region='US',
                         extra={'source_country_default': True})
    apply_heuristics(post, f'Location: {location}\nResearch assistant position.')
    assert post.country == country
    assert post.region == region
    assert post.extra['region_from_detail'] is True
    assert 'source_country_default' not in post.extra
