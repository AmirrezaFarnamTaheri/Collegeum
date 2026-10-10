"""Read-only official-link discovery for the institution coverage investigation."""

import asyncio
import json
from pathlib import Path

from bs4 import BeautifulSoup

from predoc_pipeline.boards.http import HttpClient

PAGES = {
    "penn": "https://www.hr.upenn.edu/PennHR/careers-at-penn/how-to-apply",
    "rand": "https://www.rand.org/jobs.html",
    "duke": "https://careers.duke.edu/search/?q=economics",
    "gothenburg": "https://www.gu.se/en/work-at-the-university-of-gothenburg/vacancies",
    "umea": "https://www.umu.se/en/usbe/about-us/open-positions/",
    "linkoping": "https://liu.se/en/work-at-liu/vacancies",
    "aarhus": "https://international.au.dk/about/profile/vacant-positions",
    "trinity": "https://www.trin.cam.ac.uk/vacancies/",
    "kings": "https://www.kings.cam.ac.uk/about/working-at-kings",
    "urban": "https://www.urban.org/careers",
}
ROOT = Path(__file__).parent / "institutions"


async def main():
    ROOT.mkdir(exist_ok=True)
    async with HttpClient(timeout=20, max_retries=0) as http:

        async def inspect(name, url):
            try:
                resp = await http.request("GET", url)
                soup = BeautifulSoup(resp.text, "lxml")
                links = [
                    dict(title=a.get_text(" ", strip=True), href=a["href"])
                    for a in soup.select("a[href]")
                    if any(
                        s in a["href"].lower()
                        for s in [
                            "varbi",
                            "myworkday",
                            "/job/",
                            "jobid",
                            "vacan",
                            "recruit",
                            ".pdf",
                        ]
                    )
                ]
                (ROOT / f"{name}.html").write_text(resp.text, encoding="utf-8")
                return dict(
                    name=name,
                    url=url,
                    final_url=str(resp.url),
                    status=resp.status_code,
                    links=links,
                    text_sample=soup.get_text(" ", strip=True)[-1600:],
                )
            except Exception as exc:
                return dict(name=name, url=url, error=str(exc), error_type=type(exc).__name__)

        results = await asyncio.gather(*(inspect(n, u) for n, u in PAGES.items()))
    (ROOT / "candidates.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for result in results:
        print(
            result["name"], result.get("error", result.get("status")), result.get("links", [])[:8]
        )


if __name__ == "__main__":
    asyncio.run(main())
