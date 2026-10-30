"""Life-sciences archive should preserve official vacancy application dates.

These assertions reproduce data loss at classify_post() -> journal -> CSV.
They do not alter subscriber delivery records or historical job identities.
"""
from __future__ import annotations

import csv
from datetime import date

from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.ingest.career import load_career, save_career
from predoc_pipeline.ingest.life_sciences import classify_post
from tools.export_life_sciences import write_csv

TODAY = date(2026, 10, 30)


def vacancy(*, deadline=None, deadline_text="", closed=None):
    extra = {"closed": closed} if closed else {}
    return JobPostSchema(
        title="Doctoral researcher in computational genomics",
        url="https://jobs.helsinki.fi/job/Helsinki-Doctoral-researcher-in-"
            "computational-genomics-for-predictive-medicine/1374865757/",
        institution="University of Helsinki",
        source="life_nordic_helsinki_main",
        country="Finland",
        location="Helsinki, Finland",
        fields_of_research="Computational genomics and bioinformatics",
        description_snippet="PhD researcher in molecular medicine",
        deadline=deadline,
        deadline_text=deadline_text,
        date_posted=date(2026, 10, 14),
        extra=extra,
    )


def test_deadline_and_original_posting_date_survive_classification_and_export(tmp_path):
    match = classify_post(
        vacancy(
            deadline=date(2026, 11, 19),
            deadline_text="Apply by November 19, 2026",
        ), today=TODAY,
    )
    assert match is not None
    assert match["deadline"] == "2026-11-19"
    assert match["deadline_note"] == "Apply by November 19, 2026"
    assert match["date_posted"] == "2026-10-14"
    assert match["research_fields"] == "Computational genomics and bioinformatics"
    assert match["funding_status"] == "unverified"
    assert match.get("availability") != "active"

    journal = tmp_path / "careers.ndjson"
    assert save_career(journal, [], [match]) == 1
    stored = load_career(journal)
    assert stored[0]["deadline"] == "2026-11-19"
    csvfile = tmp_path / "positions.csv"
    assert write_csv(csvfile, stored) == 1
    with csvfile.open(encoding="utf-8-sig", newline="") as f:
        row = next(csv.DictReader(f))
    assert row["deadline"] == "2026-11-19"
    assert row["deadline_note"] == "Apply by November 19, 2026"
    assert row["research_fields"] == "Computational genomics and bioinformatics"


def test_missing_deadline_remains_unknown_and_does_not_become_fabricated():
    match = classify_post(vacancy(), today=TODAY)
    assert match is not None
    assert not match.get("deadline")
    assert not match.get("deadline_note")


def test_explicitly_closed_position_is_not_published_even_before_deadline():
    job = vacancy(deadline=date(2026, 11, 19), closed="Applications closed")
    assert classify_post(job, today=TODAY) is None


def test_updated_deadline_preserves_identity_and_does_not_realert(tmp_path):
    old = classify_post(vacancy(), today=TODAY)
    updated = classify_post(
        vacancy(deadline=date(2026, 11, 19)), today=TODAY,
    )
    assert old is not None and updated is not None
    assert old["key"] == updated["key"]
    path = tmp_path / "careers.ndjson"
    assert save_career(path, [], [old]) == 1
    first = load_career(path)[0]["first_seen_at"]
    assert save_career(path, load_career(path), [updated]) == 0
    final = load_career(path)
    assert len(final) == 1
    assert final[0]["first_seen_at"] == first
    assert final[0]["deadline"] == "2026-11-19"
