"""The opt-in generic JobSpy flag cannot bypass LinkedIn provider policy."""
from __future__ import annotations

import sys
from types import SimpleNamespace

from predoc_pipeline.ingest.collectors import collect_jobspy


def test_generic_jobspy_keeps_indeed_and_never_invokes_linkedin(monkeypatch):
    calls = []

    def scrape_jobs(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(to_dict=lambda _orientation: [{
            "job_url": f"https://uk.indeed.com/viewjob?jk=job{len(calls)}",
            "title": "Predoctoral Research Assistant",
            "company": "Example University", "location": kwargs["location"],
            "description": "Economic research. Application deadline: January 15, 2027.",
        }])

    monkeypatch.setitem(sys.modules, "jobspy", SimpleNamespace(scrape_jobs=scrape_jobs))
    items, stats = collect_jobspy(SimpleNamespace(enable_jobspy=True, max_items_per_source=100))
    assert len(calls) == len(items) == 2
    assert all(call["site_name"] == ["indeed"] for call in calls)
    assert all("linkedin_fetch_description" not in call for call in calls)
    assert all(call["results_wanted"] == 25 for call in calls)
    assert {call["country_indeed"] for call in calls} == {"uk", "germany"}
    assert {item.source for item in items} == {"jobspy:indeed"}
    assert stats[0].errors == 0 and stats[0].fetched == 2
    assert any("LinkedIn is not supported" in message for message in stats[0].messages)
