"""Official Opportunity Insights research hiring PDFs must be discovered safely."""

import asyncio
from pathlib import Path

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS


CAREERS = "https://opportunityinsights.org/joinourteam/"
DATA_SCIENTIST_PDF = (
    "https://opportunityinsights.org/wp-content/uploads/2026/07/"
    "OI-Associate-Data-Scientist-JD-Website-.pdf"
)


class FixtureHttp:
    def __init__(self, html):
        self.html = html

    async def get_text(self, url):
        assert url == CAREERS
        return self.html


def scrape(html):
    source = next(s for s in load_board_sources(Path("config/sources.toml"))
                  if s.name == "opportunity_insights")
    return asyncio.run(_scrape_all([SCRAPERS[source.type](source, FixtureHttp(html))], 1, 5))[0]


def test_opportunity_insights_official_job_description_pdf_is_discovered():
    html = (
        '<h1>Join Our Team</h1><ul><li>'
        f'<a href="{DATA_SCIENTIST_PDF}">Associate Data Scientist</a>'
        '</li></ul>'
    )
    result = scrape(html)
    assert result.ok
    assert len(result.posts) == 1
    assert result.posts[0].title == "Associate Data Scientist"
    assert result.posts[0].url == DATA_SCIENTIST_PDF
    assert result.posts[0].institution == "Opportunity Insights (Harvard University)"


def test_opportunity_insights_rejects_unrelated_or_offsite_pdfs():
    html = (
        '<a href="/wp-content/uploads/2026/07/economic-mobility-research-data.pdf">'
        'Economic mobility research paper</a>'
        '<a href="https://opportunityinsights.org.evil.invalid/wp-content/uploads/'
        '2026/07/OI-Associate-Data-Scientist-JD-Website-.pdf">Fake job</a>'
        '<a href="https://evil.invalid/?next=https://opportunityinsights.org/'
        'wp-content/uploads/2026/07/OI-Associate-Data-Scientist-JD-Website-.pdf">'
        'Fake redirect</a>'
    )
    result = scrape(html)
    assert result.ok
    assert result.posts == []


def test_opportunity_insights_preserves_employer_application_links():
    html = (
        '<a href="https://harvardcareers.harvard.edu/job/99999">'
        'Predoctoral Research Fellow</a>'
    )
    result = scrape(html)
    assert result.ok
    assert [post.title for post in result.posts] == ["Predoctoral Research Fellow"]
