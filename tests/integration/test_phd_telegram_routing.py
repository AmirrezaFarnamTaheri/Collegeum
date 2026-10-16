"""Regression: a completed PhD must never be advertised as a predoc.

The historic Telegram journal contains PhD-qualified Research Fellow, junior
economist and senior research roles whose titles did not say "postdoc".
Minimum degree must follow the record through publication and subscriber UI.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from predoc_pipeline.boards.config import Preferences
from predoc_pipeline.publish.subscriptions import matching
from predoc_pipeline.routing import Channel, Router


@pytest.mark.parametrize("field", ["summary", "degree_note"])
@pytest.mark.parametrize("text", [
    "No PhD in economics is required. A bachelor degree is sufficient.",
    "A PhD in economics is not required.",
    "A PhD in economics is preferred but not required.",
])
def test_negated_phd_field_requirement_remains_predoc(field, text):
    assert Router.position_kind("Research Assistant", **{field: text}) == "predoc"


@pytest.mark.parametrize(("title", "summary", "degree", "expected"), [
    ("Research Fellow", "Lead quantitative research in econometrics", "phd", "research"),
    ("Senior Research Fellow (Evaluation)", "Design rigorous RCTs", "phd", "research"),
    ("Junior Economist", "Empirical analysis in applied economics", "phd", "research"),
    ("Research Associate in Labor Economics", "A PhD in economics is required.", None, "research"),
    ("Research Assistant", "Applicants must hold a PhD in economics.", None, "research"),
    ("Postdoctoral Researcher", "Economic policy analysis", "phd", "postdoc"),
    ("Research Assistant",
     "This role suits recent graduates who plan to pursue a PhD.", None, "predoc"),
    ("Predoctoral Research Assistant",
     "A PhD is not required. This role prepares graduates for a PhD.", None, "predoc"),
    ("Research Analyst", "A PhD is preferred but not required.", None, "predoc"),
])
def test_qualification_aware_role_classification(title, summary, degree, expected):
    assert Router.position_kind(title, summary, min_degree=degree) == expected


@pytest.mark.parametrize("min_degree", ["phd", "doctoral", "Ph.D."])
def test_phd_min_degree_never_routes_to_public_predoc_telegram(min_degree):
    router = Router(Preferences())
    title = "Research Fellow"
    summary = "Open full-time appointment researching labor markets."
    assert router.channel(
        title=title, institution="University of Warwick", country="United Kingdom",
        summary=summary, min_degree=min_degree,
    ) is Channel.WEB
    listing = SimpleNamespace(
        title=title, institution="University of Warwick",
        location=SimpleNamespace(country="United Kingdom", city="Coventry"),
        summary=summary, min_degree=min_degree, degree_note=None,
    )
    assert router.channel_for(listing) is Channel.WEB
    stored = {"title": title, "institution": "University of Warwick",
              "country": "United Kingdom", "city": "Coventry",
              "summary": summary, "min_degree": min_degree, "degree_note": None}
    assert router.channel_for_row(stored) is Channel.WEB


def test_historical_row_without_degree_metadata_is_still_supported():
    router = Router(Preferences())
    row = {"title": "Predoctoral Research Assistant", "institution": "University of Bristol",
           "country": "United Kingdom", "city": "Bristol",
           "summary": "Preparing graduates for PhD applications."}
    assert router.channel_for_row(row) is Channel.TELEGRAM


def test_predoc_only_private_subscription_must_not_receive_phd_qualified_staff():
    now = datetime.now(UTC).isoformat()
    member = {"topics": {"predoc": "2020-01-01T00:00:00+00:00"},
              "scopes": {}}
    row = {
        "status": "published", "closed_at": None, "expired_at": None,
        "url_hash": "a" * 64, "apply_url": "https://example.org/position/123",
        "summary": "Quantitative research supporting applied economics projects.",
        "deadline": None, "published_at": now,
        "title": "Research Fellow", "institution": "University of Warwick",
        "city": "Coventry", "country": "United Kingdom", "min_degree": "phd",
        "degree_note": None,
    }
    assert matching(member, [row], [], preview=True) == []

def test_phd_requirement_still_excluded_when_config_omits_web_categories():
    """Misconfiguration must not publish a doctorate-required opening as a predoc."""
    from predoc_pipeline.boards.config import RoutingConfig

    router = Router(Preferences(routing=RoutingConfig(web_position_kinds=[])))
    assert router.channel(
        title="Research Fellow", institution="University of Warwick",
        country="United Kingdom", summary="The appointment requires a completed PhD.",
        min_degree="phd",
    ) is Channel.WEB
    assert router.channel(
        title="Doctoral Researcher", institution="University of Zurich",
        country="Switzerland", summary="The holder must pursue a PhD thesis.",
    ) is Channel.WEB
    assert router.channel(
        title="Predoctoral Research Assistant", institution="University of Warwick",
        country="United Kingdom", summary="Ideal preparation for a future PhD.",
    ) is Channel.TELEGRAM


def test_completed_phd_required_does_not_invent_postdoctoral_role():
    """A completed qualification is distinct from an explicitly postdoctoral job."""
    assert Router.position_kind(
        "Research Fellow", "A completed PhD is required for this appointment."
    ) == "research"
    assert Router.position_kind(
        "Postdoctoral Fellow", "A completed PhD is required for this appointment."
    ) == "postdoc"
