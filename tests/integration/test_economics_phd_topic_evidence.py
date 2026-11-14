"""Doctoral Telegram routing requires economic research evidence, not tags alone."""
import pytest

from predoc_pipeline.boards.config import Preferences
from predoc_pipeline.models import Discipline, Location, PredocListing
from predoc_pipeline.routing import Channel, Router


def position(title, summary, disciplines):
    return PredocListing(
        title=title,
        institution="Example University",
        location=Location(country="Germany", city="Berlin"),
        disciplines=disciplines,
        summary=summary,
        apply_url="https://example.edu/jobs/doctoral-1",
        source_url="https://example.edu/jobs/doctoral-1",
    )


@pytest.mark.parametrize(("title", "summary", "disciplines"), [
    (
        "School of Law, Education and Society PhD Studentship 2026-27",
        "Doctoral research on criminal justice and rehabilitation.",
        [Discipline.LAW, Discipline.PUBLIC_POLICY],
    ),
    (
        "PhD Student in Biogas Solutions for a Flexible Energy System",
        "Doctoral work in biogas solutions, sustainable energy and systems engineering.",
        [Discipline.ENVIRONMENTAL],
    ),
    (
        "Doctoral Researcher: Russia's Role in Promoting Illiberal Governance",
        "The project investigates illiberal governance and political influence in Europe.",
        [Discipline.POLITICAL_ECONOMY],
    ),
    (
        "Doctoral Candidate and Assistant in Business Administration (Operations Research)",
        "Research and teaching in Business Administration. Applicants should have "
        "a degree in business or quantitative economics.",
        [Discipline.QUANT_SOCIAL],
    ),
    (
        "Doctoral Researcher in Ethnic Stratification of Housing",
        "Research on migration and urban inequality. Applicants need a Master's "
        "degree in social or economic sciences.",
        [Discipline.DEVELOPMENT],
    ),
    (
        "PhD Student in Agricultural Bioeconomy Systems",
        "Research on biomass production and GIS. The work includes "
        "environmental and economic assessments.",
        [Discipline.ENVIRONMENTAL],
    ),
    (
        "Doctoral Researcher in Migration and Disinformation",
        "Research on Russian influence on European migration narratives.",
        [Discipline.POLITICAL_ECONOMY],
    ),
    (
        "PhD Candidate in Hydrogen and Industrial Decarbonization",
        "Doctoral research in hydrogen value chains, CCS and electrification.",
        [Discipline.ENVIRONMENTAL, Discipline.IO],
    ),
    (
        "Doctoral Researcher in Assessment of Nature-Based Solutions",
        "Research on policy and evaluation of nature-based solutions.",
        [Discipline.ENVIRONMENTAL],
    ),
    (
        "Doctoral Candidate at the Chair of Accounting",
        "Research on capital market communication and accounting.",
        [Discipline.FINANCE, Discipline.APPLIED_MICRO],
    ),
])
def test_non_economics_vacancies_not_sent_due_to_noisy_discipline_tags(
    title, summary, disciplines,
):
    job = position(title, summary, disciplines)
    assert Router(Preferences()).destinations(job) == frozenset({Channel.WEB})


@pytest.mark.parametrize(("title", "summary", "disciplines"), [
    (
        "PhD Researcher in Monetary Economics",
        "Doctoral research in monetary policy and financial stability.",
        [Discipline.MACRO],
    ),
    (
        "PhD Researcher: Economic Impacts of Climate Risks",
        "The doctoral project focuses on economic impacts of climate change.",
        [Discipline.ENVIRONMENTAL],
    ),
    (
        "PhD Fellowship in the Economics of Health Care",
        "Research on market externalities and health care procurement.",
        [Discipline.HEALTH],
    ),
    (
        "PhD Candidate, Prae-Doc (30 hours/week)",
        "A PhD candidate in the Research Group for Environmental and "
        "Resource Economics, working on electricity market welfare.",
        [Discipline.ENVIRONMENTAL],
    ),
    (
        "Doctoral Researcher: Islamic Finance and Governance",
        "The role involves interdisciplinary research combining economics, "
        "law and public policy to study Islamic finance.",
        [Discipline.FINANCE, Discipline.LAW],
    ),
    (
        "Doctoral Candidate in Financial Inclusion",
        "The project focuses on research in political economy of credit markets.",
        [Discipline.DEVELOPMENT],
    ),
])
def test_economics_research_topics_remain_eligible(title, summary, disciplines):
    job = position(title, summary, disciplines)
    assert Channel.TELEGRAM in Router(Preferences()).destinations(job)
