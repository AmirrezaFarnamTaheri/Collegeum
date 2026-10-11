"""Distinguish healthy zero matches from provider markup changes."""

import json
from types import SimpleNamespace

from tools.probe_career_sources import probe_sources


def _probe(*, remote, jobinja, irantalent):
    class Client:
        def get(self, url, **_kwargs):
            if "jobicy.com" in url:
                text = json.dumps(remote)
            elif "jobinja.ir" in url:
                text = jobinja
            else:
                text = irantalent
            return SimpleNamespace(ok=True, status=200, text=text)

    return probe_sources(Client())


def test_renamed_jobicy_fields_fail_visible():
    result = _probe(
        remote={"jobs": [{
            "headline": "Data Analyst", "geo": "Anywhere",
            "link": "https://jobicy.com/jobs/100",
        }]},
        jobinja='<a href="/companies/acme/jobs/12/accountant">Accountant</a>',
        irantalent='<a href="/en/job/accountant/12345">Accountant</a>',
    )
    assert result["sources"]["jobicy"]["status"] == "schema_changed"
    assert not result["healthy"]


def test_script_only_job_urls_are_not_job_cards():
    result = _probe(
        remote={"jobs": []},
        jobinja='<script>"/companies/acme/jobs/12/accountant"</script>',
        irantalent='<script>"/en/job/accountant/12345"</script>',
    )
    assert result["sources"]["jobinja"]["status"] == "schema_changed"
    assert result["sources"]["irantalent"]["status"] == "schema_changed"
    assert not result["healthy"]


def test_ineligible_well_formed_jobs_are_healthy_empty():
    result = _probe(
        remote={"jobs": [{
            "jobTitle": "Accountant",
            "jobGeo": "United States",
            "url": "https://jobicy.com/jobs/100",
        }]},
        jobinja="<div>No jobs found</div>",
        irantalent="<p>No matching jobs</p>",
    )
    assert result["healthy"]
    assert all(
        row["status"] == "healthy_empty"
        for row in result["sources"].values()
    )
