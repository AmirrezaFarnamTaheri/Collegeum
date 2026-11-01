"""Current documented public Jobicy API contract, without live provider requests."""
from urllib.parse import parse_qs, urlsplit

from predoc_pipeline.ingest.career import (
    REMOTE_API,
    REMOTE_STATUS_API,
    parse_remote_jobs,
)


def test_jobicy_public_feed_uses_documented_current_api_and_safe_page_size() -> None:
    feed = urlsplit(REMOTE_API)
    assert (feed.scheme, feed.hostname, feed.path) == (
        "https", "jobicy.com", "/api/jobs",
    )
    assert parse_qs(feed.query) == {"count": ["100"], "geo": ["anywhere"]}
    status = urlsplit(REMOTE_STATUS_API)
    assert (status.scheme, status.hostname, status.path) == (
        "https", "jobicy.com", "/api/jobs/status",
    )


def test_current_public_feed_schema_respects_worldwide_and_role_filters() -> None:
    payload = {
        "apiVersion": "2.2.19", "success": True, "nextCursor": None,
        "jobs": [
            {
                "id": 123456, "jobTitle": "Senior Data Analyst",
                "companyName": "Example", "jobGeo": "Anywhere",
                "url": "https://jobicy.com/jobs/example-analyst",
            },
            {
                "id": 123457, "jobTitle": "Data Analyst",
                "companyName": "Example", "jobGeo": "USA",
                "url": "https://jobicy.com/jobs/us-only-analyst",
            },
            {
                "id": 123458, "jobTitle": "Accountant",
                "companyName": "Example", "jobGeo": "Anywhere",
                "url": "https://jobicy.com/jobs/example-accountant",
            },
        ],
    }
    jobs = parse_remote_jobs(payload)
    assert len(jobs) == 1
    assert jobs[0]["category"] == "data_analyst"
    assert jobs[0]["scope"] == "remote"
    assert jobs[0]["source"] == "Jobicy"
