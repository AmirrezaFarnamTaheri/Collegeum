"""Parse already obtained LinkedIn Jobs HTML without borrowing unrelated evidence.

This module performs no network access. A valid advert ID or description does
not establish provider permission, employer verification or current eligibility.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, TypeGuard
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

from ..utils.text import clean_ws

_JOB_ID = re.compile(r"[0-9]{6,30}\Z")
_JOB_URN = re.compile(r"urn:li:jobPosting:([0-9]{6,30})\Z")
_JOB_PATH = re.compile(r"/jobs/view/(?:[^/?#]+-)?([0-9]{6,30})/?\Z")
_CARDS = "div.base-card, div.job-search-card, li > div[data-entity-urn]"
_CHALLENGE_HEADING = re.compile(
    r"^(?:sign[ -]?in (?:is )?required(?: to continue)?|sign[ -]?in to continue|"
    r"join LinkedIn to continue|security verification|verify (?:that )?you are human|"
    r"let['’]s do a quick security check)[.!]?\Z", re.I,
)
_CLOSED = re.compile(
    r"(?:no longer accepting applications|this job is no longer available|"
    r"applications are closed)[.!]?\Z", re.I,
)
MAX_ADVERT_TEXT_CHARS = 20000


def _unrendered(node: Tag) -> bool:
    """Recognize explicit hidden/template markup without inferring CSS layout."""
    return bool(
        node.name in {"script", "style", "noscript", "template"}
        or node.has_attr("hidden")
        or str(node.get("aria-hidden", "")).casefold() == "true"
        or re.search(
            r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\s*(?:!important\s*)?(?:;|$)",
            str(node.get("style", "")), re.I,
        )
    )


def _hidden(node: Tag) -> bool:
    return any(_unrendered(parent) for parent in [node, *node.parents] if isinstance(parent, Tag))


def _discard_unrendered(soup: BeautifulSoup) -> None:
    # Removing a hidden parent also removes its nested challenge headings and
    # descriptions. A child of a decomposed parent must not be inspected again.
    for node in soup.find_all(True):
        if not node.decomposed and _unrendered(node):
            node.decompose()


def valid_job_id(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and _JOB_ID.fullmatch(value) is not None


def job_id_from_url(value: object) -> str | None:
    """Accept actual LinkedIn job paths, including regional and relative links."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"", "https", "http"} or parsed.username or parsed.password:
            return None
        if parsed.netloc:
            host = (parsed.hostname or "").lower()
            if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
                return None
            if parsed.port not in {None, 443 if parsed.scheme != "http" else 80}:
                return None
        elif parsed.scheme or not parsed.path.startswith("/jobs/view/"):
            return None
    except ValueError:
        return None
    match = _JOB_PATH.fullmatch(parsed.path)
    return match.group(1) if match else None


def _unrelated_container(node: Tag) -> bool:
    if node.name in {"aside", "nav", "footer"}:
        return True
    raw_classes = node.get("class")
    classes = raw_classes.split() if isinstance(raw_classes, str) else (raw_classes or [])
    # A CSS class token can continue with BEM underscores, which are word
    # characters to regex \b. Require a token end or naming delimiter,
    # without treating names such as "base-cardinality" as a job card.
    return any(re.match(
        r"(?:similar-jobs|related-jobs|recommended-jobs|base-card)(?=$|[-_])", str(c),
    ) for c in classes)


def _outside_advert(node: Tag) -> bool:
    """Sidebars and related-job cards must not provide the primary description."""
    return any(
        _unrelated_container(parent)
        for parent in [node, *node.parents] if isinstance(parent, Tag)
    )


def _access_challenge(soup: BeautifulSoup) -> bool:
    # The words "sign in" and "captcha" can occur in a real job description.
    # Require a security/authwall element or a dedicated challenge heading.
    for element in soup.select(
        ".authwall, #authwall, .challenge-page, #captcha-internal, "
        "iframe[src*='captcha'], form[action*='/checkpoint/']",
    ):
        if element.has_attr("hidden") or element.get("aria-hidden") == "true":
            continue
        if re.search(r"display\s*:\s*none", str(element.get("style", "")), re.I):
            continue
        return True
    if any(_CHALLENGE_HEADING.fullmatch(clean_ws(node.get_text(" ")))
           for node in soup.select("title, h1, h2")):
        return True
    if not soup.select(_CARDS + ", .show-more-less-html__markup, .description__text"):
        text = clean_ws(soup.get_text(" "))
        if len(text) <= 500 and re.search(
            r"captcha|sign[ -]?in.*(?:required|continue)|verify (?:that )?you are human",
            text, re.I,
        ):
            return True
    return False


@dataclass(frozen=True)
class SearchPage:
    cards: list[dict[str, Any]]
    invalid_cards: int = 0
    access_challenge: bool = False


def parse_search_page(html: str) -> SearchPage:
    soup = BeautifulSoup(html, "lxml")
    # Hidden cards cannot supply jobs or make a full response appear complete
    # after removal. Preserve that uncertainty in the existing partial-page path.
    hidden_cards = sum(_hidden(node) for node in soup.select(_CARDS))
    _discard_unrendered(soup)
    if _access_challenge(soup):
        return SearchPage([], access_challenge=True)
    nodes = soup.select(_CARDS)
    containers = {id(node) for node in nodes}
    cards: list[dict[str, Any]] = []
    invalid = hidden_cards
    for card in nodes:
        if any(id(parent) in containers for parent in card.parents):
            continue  # Nested markup is one card, not another pagination offset.
        title_el = card.select_one(".base-search-card__title, h3")
        link_el = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
        urn = str(card.get("data-entity-urn") or "")
        urn_match = _JOB_URN.fullmatch(urn) if urn else None
        urn_id = urn_match.group(1) if urn_match else None
        href = str(link_el.get("href") or "") if link_el else ""
        link_id = job_id_from_url(href) if href else None
        title = clean_ws(title_el.get_text(" ")) if title_el else ""
        if not title or (urn and not urn_id) or (href and not link_id) or (
            urn_id and link_id and urn_id != link_id
        ) or not (urn_id or link_id):
            invalid += 1
            continue
        company = card.select_one(".base-search-card__subtitle, h4")
        location = card.select_one(".job-search-card__location")
        posted = card.select_one("time")
        cards.append({
            "id": urn_id or link_id,
            "title": title,
            "company": clean_ws(company.get_text(" ")) if company else "",
            "location": clean_ws(location.get_text(" ")) if location else "",
            "datetime": posted.get("datetime") if posted else None,
            "posted_text": clean_ws(posted.get_text(" ")) if posted else None,
        })
    return SearchPage(cards, invalid_cards=invalid)


@dataclass(frozen=True)
class DetailPage:
    text: str | None
    status: str


def parse_detail_page(html: str, job_id: str) -> DetailPage:
    soup = BeautifulSoup(html, "lxml")
    _discard_unrendered(soup)
    if _access_challenge(soup):
        return DetailPage(None, "access_challenge")
    if not valid_job_id(job_id):
        return DetailPage(None, "invalid_job_identity")
    for node in soup.select("link[rel='canonical'], meta[property='og:url']"):
        source = node.get("href") if node.name == "link" else node.get("content")
        if source and job_id_from_url(source) != job_id:
            return DetailPage(None, "job_identity_mismatch")
    bodies = soup.select(".show-more-less-html__markup")
    if not bodies:
        bodies = soup.select(".description__text")
    texts = []
    for body in bodies:
        if body.decomposed or _outside_advert(body):
            continue
        # Related material can also be nested *inside* a primary wrapper. Its
        # dates, eligibility and closure text belong to a different advert.
        for child in body.find_all(True):
            if not child.decomposed and _unrelated_container(child):
                child.decompose()
        text = clean_ws(body.get_text(" "))
        if text and text not in texts:
            texts.append(text)
    if len(texts) != 1:
        return DetailPage(None, "ambiguous_advert_body" if texts else "missing_advert_body")
    # LinkedIn can retain the description after applications close. Only its
    # dedicated primary-job status element can supplement that description.
    closed = [clean_ws(node.get_text(" ")) for node in soup.select(
        ".closed-job__flavor-text, .topcard__flavor--closed",
    ) if not _outside_advert(node)]
    status = next((value for value in closed if _CLOSED.fullmatch(value)), None)
    text = (status + "\n" if status else "") + texts[0]
    if len(text) > MAX_ADVERT_TEXT_CHARS:
        # Truncation can remove a late requirement, cutoff qualifier or closure.
        # An incomplete advert must not certify successful detail enrichment.
        if status:
            # The separate primary-job banner is complete closure evidence even
            # when the description exceeds the supported extraction limit.
            return DetailPage(status, "advert_closed")
        return DetailPage(None, "advert_body_too_large")
    return DetailPage(text, "advert_body_received")
