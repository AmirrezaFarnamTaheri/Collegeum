"""Bounded read-only audit of previously registered economics source candidates.

No HTTP discovered link is fetched, so this cannot ingest a vacancy, bypass an
ATS or modify public/subscriber outputs. Access is robots-aware.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.ingest.http import PoliteClient

CANDIDATES = (
    "esri_ireland_jobs", "liser_luxembourg_jobs", "iab_germany_labour",
    "vatt_finland_jobs", "bank_finland_jobs", "smu_financial_econ",
    "anu_australia_jobs", "unu_wider_opportunities",
    "seo_amsterdam_economics", "cepr_uk_internal_jobs",
    "ifau_sweden_labour",
)
TITLE_RE = re.compile(
    r"research|associate|assistant|analyst|econom|job|vacanc|career|"
    r"wissenschaft|mitarbeiter|stelle|bewerb|ty[oö]paik|ty[oö]teht|"
    r"tutkim|rekrytoin|open.position", re.I,
)
NO_OPENINGS = re.compile(
    r"no open positions|no current vacanc|no jobs|ei avoimia|"
    r"ei avoinna|keine offenen stellen|pas d.offres", re.I,
)


def inspect_html(url: str, html: str) -> dict:
    soup = BeautifulSoup(html[:600000], "lxml")
    seen: set[str] = set()
    matches = []
    for a in soup.select("a[href]")[:1600]:
        href = urljoin(url, str(a.get("href") or ""))
        parsed = urlsplit(href)
        if parsed.scheme != "https" or not parsed.hostname:
            continue
        if href in seen:
            continue
        label = a.get_text(" ", strip=True)[:125]
        if not (TITLE_RE.search(label) or TITLE_RE.search(parsed.path)):
            continue
        seen.add(href)
        matches.append({"title": label, "url": href.split("?")[0][:260]})
        if len(matches) >= 18:
            break
    rendered = soup.get_text(" ", strip=True)[:60000]
    return {
        "anchors": len(soup.select("a[href]")),
        "candidate_links": matches,
        "candidate_link_count_sample": len(matches),
        "official_no_openings_notice": bool(NO_OPENINGS.search(rendered)),
        "visible_content_chars": len(rendered),
        "jobposting_metadata": '"@type":"JobPosting"' in html,
    }


def main() -> None:
    sources = {s.name: s for s in load_board_sources("config/sources.toml")}
    data = {"checked_at": datetime.now(UTC).isoformat(), "sources": {}}
    with PoliteClient(
        user_agent="Collegeum-SourceReview/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)",
        timeout=14, per_host_delay=2, respect_robots=True,
    ) as client:
        for name in CANDIDATES:
            cfg = sources[name]
            url = cfg.opt("url")
            row = {"enabled": cfg.enabled, "type": cfg.type, "url": url}
            if not isinstance(url, str) or not url.startswith("https://"):
                row["result"] = "invalid_source"
            else:
                try:
                    response = client.get(url, use_cache=False)
                    row["status"] = response.status
                    row["error"] = response.error[:120]
                    if response.ok:
                        row.update(inspect_html(url, response.text))
                except Exception as exc:
                    row["result"] = type(exc).__name__
            data["sources"][name] = row
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
