"""A mixed-subject PhD backfill must not be mislabelled Economics-only."""

from predoc_pipeline.models import Discipline, Location, PredocListing
from predoc_pipeline.publish.telegram import render_digest_batches


def test_historical_population_studies_digest_has_general_phd_heading():
    position = PredocListing(
        title="University of Hong Kong – Max Planck PhD Studentship in Population Studies",
        institution="University of Hong Kong and Max Planck Institute for Demographic Research",
        location=Location(country="Hong Kong", city="Hong Kong"),
        disciplines=[Discipline.QUANT_SOCIAL],
        summary="A four-year jointly funded Population Studies and demography PhD.",
        apply_url="https://www.mpg.de/27030733/hku-mpidr-phd-stundentship",
        source_url="https://www.mpg.de/27030733/hku-mpidr-phd-stundentship",
    )
    pages = render_digest_batches(
        [("a" * 64, position)], historical=True, feedback=False,
    )
    assert len(pages) == 1
    assert "Previously collected PhD positions" in pages[0].html
    assert "Economics PhD positions" not in pages[0].html
    assert "Stored vacancies; current availability is not" in pages[0].html
