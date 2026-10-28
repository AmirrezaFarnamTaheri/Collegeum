"""Career alerts must not imply a job is verified open when status is unknown."""
from __future__ import annotations

import pytest

from predoc_pipeline.publish.subscriptions import render_alert


def career(**changes: str) -> dict[str, str]:
    job = {
        "key": "career:unverified", "category": "life_sciences_phd",
        "title": "PhD Researcher in Genetics", "employer": "Example University",
        "location": "Finland", "scope": "", "source": "official university",
        "url": "https://example.edu/jobs/123",
    }
    job.update(changes)
    return job


@pytest.mark.parametrize("status", [None, "", "unknown"])
def test_unverified_life_sciences_career_alert_explains_unknown_open_status(
    status: str | None,
) -> None:
    job = career()
    if status is not None:
        job["availability"] = status
    rendered = render_alert(job, "en")
    assert "Availability has not been verified" in rendered
    assert "Funding, salary and tuition are not verified" in rendered
    assert "View opportunity" in rendered


def test_unverified_remote_career_alert_explains_unknown_status_in_both_languages() -> None:
    job = career(category="data_analyst", scope="remote", availability="unknown")
    assert "Availability has not been verified" in render_alert(job, "en")
    assert "فعال بودن این فرصت تأیید نشده" in render_alert(job, "fa")


def test_verified_active_career_and_published_academic_do_not_get_unknown_notice() -> None:
    active = career(availability="active")
    assert "Availability has not been verified" not in render_alert(active, "en")
    academic = career(key="academic:published", category="predoc")
    assert "Availability has not been verified" not in render_alert(academic, "en")
