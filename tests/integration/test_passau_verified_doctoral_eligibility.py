"""Evidence-based correction for Passau Development Economics PhD #407."""
import json
from pathlib import Path

from predoc_pipeline.boards.config import Preferences
from predoc_pipeline.models import Discipline, Location, PredocListing
from predoc_pipeline.routing import Channel, Router


def test_passau_phd_degree_from_employer_advert_not_scraped_phd_marker():
    journal = Path(__file__).resolve().parents[2] / "data/listings.ndjson"
    rows = {record["id"]: record for record in (
        json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()
    )}
    row = rows[407]
    # University of Passau's Nov. 2026 PDF says M.A./M.Sc. Economics or
    # Development Studies (or near-completion), not a completed doctorate.
    # Source: www.uni-passau.de/fileadmin/dokumente/beschaeftigte/Stellenangebote/
    # 2026_11_WM_Prof_Grimm_engl__002__Ri_MG.pdf
    assert row["min_degree"] == "masters"
    assert row["deadline"].startswith("2026-11-22T")
    assert "University of Passau" in row["degree_note"]
    assert row["telegram_delivery_state"] == "not_attempted"
    assert row["telegram_message_id"] is None

    listing = PredocListing(
        title=row["title"],
        institution=row["institution"],
        location=Location(country=row["country"], city=row["city"]),
        summary=row["summary"],
        disciplines=[Discipline.DEVELOPMENT],
        min_degree=row["min_degree"],
        degree_note=row["degree_note"],
        apply_url=row["apply_url"],
        source_url=row["source_url"],
    )
    assert Channel.TELEGRAM in Router(Preferences()).destinations(listing)

    # Never clear or replay any prior confirmed historical digest.
    ids = {id for id, entry in rows.items() if entry["telegram_message_id"] in (117, 118, 119)}
    assert len(ids) == 16
    assert all(rows[id]["telegram_delivery_state"] == "confirmed" for id in ids)
