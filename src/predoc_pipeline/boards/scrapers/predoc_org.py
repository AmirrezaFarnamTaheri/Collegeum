"""PREDOC.org opportunities board (server-rendered HTML).

Each listing looks like:
    <h2><a href="https://bit.ly/...">Pre-Doctoral Research Assistant</a></h2>
    <p><strong>Sponsoring Researcher(s):</strong> Jan Eeckhout</p>
    <p><strong>Sponsoring Institution:</strong> Universitat Pompeu Fabra, Barcelona, Spain</p>
    <p><strong>Fields of Research:</strong> Macroeconomics and Labour Economics</p>
    <p><strong>Deadline:</strong> 20th April 2026</p>
    <p><strong>Visa:</strong> Visas for international candidates ... will be supported.</p>
The parser keys on the labels rather than CSS classes so it survives theme changes.
"""
from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString

from ..models import JobPostSchema
from ..utils.dates import extract_deadline
from ..utils.text import absolutize, clean_ws
from .base import BaseScraper, register

LABELS = {
    "sponsoring researcher": "pi_name", "sponsoring researchers": "pi_name",
    "sponsoring researcher(s)": "pi_name", "principal investigator": "pi_name",
    "sponsoring institution": "institution", "sponsoring institutions": "institution",
    "institution": "institution", "fields of research": "fields", "field of research": "fields",
    "field": "fields", "deadline": "deadline", "application deadline": "deadline",
    "closing date": "deadline", "application closing date": "deadline",
    "final deadline": "deadline", "final application deadline": "deadline",
    "deadline/first review date": "review", "first review date": "review", "review date": "review",
    "priority deadline": "review", "priority application deadline": "review",
    "visa": "visa", "location": "location",
    # labels we don't use, listed so they end the previous value instead of leaking into it
    "start date": "_start", "start": "_start", "duration": "_other", "salary": "_other", "term": "_other",
    "contact": "_other", "eligibility": "_other", "requirements": "_other", "how to apply": "_other",
    "to apply": "_other", "job description": "_other", "description": "_other", "position": "_other",
}
_LABEL_RX = re.compile(
    r"(?P<qualifier>\b(?:for\s+(?:full|priority)\s+consideration|(?:first|initial)\s+review)"
    r"\s*[,;:\-–]?\s*)?"
    r"(?P<label>" + "|".join(re.escape(k) for k in sorted(LABELS, key=len, reverse=True)) + r")\s*:",
    re.IGNORECASE,
)
_HEADINGS = ("h1", "h2", "h3", "h4")


def parse_labeled_block(text: str) -> dict[str, str]:
    """'Sponsoring Institution: X Fields of Research: Y' -> {'institution': 'X', 'fields': 'Y'}."""
    out: dict[str, str] = {}
    date_fields: list[str] = []
    cutoff_fields: list[str] = []
    review_fields: list[str] = []
    matches = list(_LABEL_RX.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        key = LABELS[m.group("label").lower()]
        qualifier = m.group("qualifier") or ""
        if qualifier and key == "deadline":
            key = "review"
        val = clean_ws(text[m.end():end]).strip(" *:-–")
        if val and key in {"deadline", "review"}:
            field = f"{qualifier}{m.group('label')}: {val}"
            date_fields.append(field)
            (cutoff_fields if key == "deadline" else review_fields).append(field)
        if val and key not in out:
            out[key] = val
            if key in {"deadline", "review"}:
                out[f"{key}_label"] = m.group("label")
    if date_fields:
        # Repeated labels may carry different applicant groups or conflicting
        # dates. Retain them all for both extraction and later enrichment.
        out["date_fields"] = "\n".join(date_fields)
        out["cutoff_fields"] = "\n".join(cutoff_fields)
        out["review_fields"] = "\n".join(review_fields)
    return {k: v for k, v in out.items() if not k.startswith("_")}


def _block_text(heading: Tag) -> str:
    parts: list[str] = []
    for sib in heading.next_siblings:
        if isinstance(sib, NavigableString):
            if sib.strip():
                parts.append(str(sib))
            continue
        if not isinstance(sib, Tag):
            continue
        if sib.name in _HEADINGS or sib.find(_HEADINGS):
            break
        parts.append(sib.get_text(" ", strip=True))
    text = " \n ".join(parts)
    if not _LABEL_RX.search(text) and heading.parent is not None:
        text = heading.parent.get_text(" ", strip=True)
    return text


@register
class PredocOrgScraper(BaseScraper):
    type_name = "predoc_org"

    async def fetch_raw_postings(self) -> list[Any]:
        async def get(u: str) -> tuple[str, str]:
            return u, await self.http.get_text(u)
        return await self.fetch_each(get)

    def parse_postings(self, raw_data: list[Any]) -> list[JobPostSchema]:
        posts: list[JobPostSchema] = []
        for base, html in raw_data:
            soup = BeautifulSoup(html, "lxml")
            for h in soup.find_all(_HEADINGS):
                a = h.find("a", href=True)
                if not a:
                    continue
                title = clean_ws(a.get_text(" "))
                href = str(a["href"])
                if len(title) < 5 or href.startswith(("#", "mailto:", "javascript:")):
                    continue
                # Cards repeat the title as an "apply" button; drop it so it doesn't leak into values.
                info = parse_labeled_block(_block_text(h).replace(title, " "))
                if not ({"institution", "deadline", "review", "fields"} & info.keys()):
                    continue  # not a listing (nav heading, blog post, ...)
                deadline_raw = info.get("deadline")
                date_fields = info.get("date_fields", "").splitlines()
                cutoff_fields = info.get("cutoff_fields", "").splitlines()
                deadline, note = extract_deadline("\n".join(date_fields))
                review_note = (
                    info["review_fields"] if info.get("review_fields") else
                    note if not deadline and note and re.search(r"review|priority|consideration", note, re.I)
                    else None
                )
                deadline_text = (
                    "\n".join(cutoff_fields) if len(cutoff_fields) > 1
                    else deadline_raw or review_note or note
                )
                desc_parts: list[str] = []
                inst = info.get("institution")
                pi = info.get("pi_name")
                fields = info.get("fields")
                visa = info.get("visa")
                if inst and pi:
                    desc_parts.append(
                        f"Full-time predoctoral research role at {inst}, working with {pi}."
                    )
                elif inst:
                    desc_parts.append(f"Full-time predoctoral research role at {inst}.")
                elif pi:
                    desc_parts.append(f"Full-time predoctoral research role working with {pi}.")
                if fields:
                    desc_parts.append(f"Research focus: {fields}.")
                # Keep the source's role labels. Rephrasing review timing as an
                # application deadline would let later enrichment promote it.
                desc_parts.extend(f"{field}." for field in date_fields)
                if visa:
                    desc_parts.append(f"Visa note: {visa}.")
                snippet = " ".join(desc_parts)
                posts.append(self.make(
                    title=title, url=absolutize(base, href),
                    institution=info.get("institution", ""), location=info.get("location"),
                    fields_of_research=info.get("fields"), pi_name=info.get("pi_name"),
                    deadline=deadline, deadline_text=deadline_text, visa_note=info.get("visa"),
                    description_snippet=snippet,
                    extra={"predoc_review_note": review_note} if review_note else {},
                ))
        return posts
