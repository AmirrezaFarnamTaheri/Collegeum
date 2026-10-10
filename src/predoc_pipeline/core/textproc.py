"""Text normalisation. Stdlib only.

Feed ``<description>`` payloads are HTML, social posts are entity-encoded, and
Telegram's HTML parse mode cares about exactly three characters. Getting this
layer wrong shows up as garbled channel posts and as model calls spent on
markup, so it is small, explicit and fully covered by tests.
"""

from __future__ import annotations

import re
import unicodedata
from html import escape as _escape
from html import unescape as _unescape
from html.parser import HTMLParser

__all__ = [
    "html_to_text",
    "squish",
    "squish_lines",
    "truncate",
    "truncate_utf16",
    "escape_telegram_html",
    "telegram_visible_length",
    "hashtag",
    "language_hint",
    "word_shingles",
    "char_ngrams",
]

_INLINE_WS = re.compile(r"[ \t\r\f\v]+")
_BLANKS = re.compile(r"\n{3,}")
_HTML_TAG_STRIP = re.compile(r"<[^>]+>")
_ASCII_ALPHANUM = re.compile(r"[A-Za-z0-9]+")
_LATIN_TOKENS = re.compile(r"[a-zà-öø-ÿ]+")
# Layout artifacts, not ZWJ/ZWNJ: those carry emoji and linguistic meaning.
_LAYOUT_ARTIFACTS = str.maketrans("", "", "\u200b\ufeff\u2060\u00ad")
_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "blockquote", "table", "ul", "ol",
}
_DROP_TAGS = {"script", "style", "noscript", "template", "svg", "head"}


class _TextExtractor(HTMLParser):
    """Minimal, dependency-free HTML to text. Tolerant of broken markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self._out.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._out.append(data)

    def text(self) -> str:
        return "".join(self._out)


def squish_lines(text: str) -> str:
    """Collapse intra-line whitespace, cap consecutive blank lines at one."""
    lines = [
        _INLINE_WS.sub(" ", line).strip()
        for line in (text or "").translate(_LAYOUT_ARTIFACTS).splitlines()
    ]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


def html_to_text(html: str) -> str:
    """Strip markup, keeping block structure as newlines."""
    if not html:
        return ""
    if "<" not in html:
        return squish_lines(html)
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # pragma: no cover - HTMLParser is very tolerant
        return squish_lines(_HTML_TAG_STRIP.sub(" ", html))
    return squish_lines(parser.text())


def squish(text: str) -> str:
    """Collapse all whitespace, newlines included, into single spaces."""
    return " ".join((text or "").translate(_LAYOUT_ARTIFACTS).split())


def truncate(text: str, limit: int, *, ellipsis: str = "\u2026") -> str:
    """Truncate on a word boundary when one is reasonably close to the limit."""
    text = text or ""
    if len(text) <= limit:
        return text
    if limit <= len(ellipsis):
        return text[:limit]
    cut = text[: limit - len(ellipsis)]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:.-") + ellipsis


def escape_telegram_html(text: str) -> str:
    """Telegram's HTML parse mode requires escaping exactly &, < and >."""
    text = "".join(c for c in (text or "") if not 0xD800 <= ord(c) <= 0xDFFF)
    return _escape(text, quote=False)


def truncate_utf16(text: str, limit: int) -> str:
    """Bound plain text in UTF-16 units without splitting a code point."""
    text = text or ""
    if limit <= 0:
        return ""
    if sum(2 if ord(c) > 0xFFFF else 1 for c in text) <= limit:
        return text
    used = 0
    cut = []
    for c in text:
        units = 2 if ord(c) > 0xFFFF else 1
        if used + units > limit - 1:
            break
        cut.append(c)
        used += units
    return "".join(cut).rstrip() + "…"


_TAG = re.compile(r"</?[a-zA-Z][^>]*>")


def telegram_visible_length(html: str) -> int:
    """Conservative UTF-16 budget after HTML entity parsing.

    The documented limit applies *after entity parsing*, so ``&amp;`` costs one
    character rather than five and tags cost nothing. Measuring raw HTML (the
    usual shortcut) truncates messages far earlier than necessary while still
    failing to guarantee the real limit is respected. UTF-16 units also cover
    supplementary characters safely and match Telegram's entity offsets.
    """
    without_tags = _TAG.sub("", html or "")
    return sum(2 if ord(c) > 0xFFFF else 1 for c in _unescape(without_tags))


def hashtag(value: str) -> str:
    """Build a Telegram-safe hashtag body from arbitrary text.

    Telegram terminates a hashtag at the first non-word character, so
    "Côte d'Ivoire" has to become "CoteDIvoire" rather than "Côted'Ivoire".
    Returns '' when nothing usable survives; callers then omit the tag.
    """
    folded = unicodedata.normalize("NFKD", value or "")
    ascii_only = "".join(c for c in folded if not unicodedata.combining(c))
    parts = _ASCII_ALPHANUM.findall(ascii_only)
    tag = "".join(p[:1].upper() + p[1:] for p in parts)
    if tag and tag[0].isdigit():
        tag = "_" + tag
    return tag[:60]


# Cheap script and language hinting -- not a language detector, just enough to
# pick a lexicon and record a hint on the listing.
_LANG_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("de", ("wissenschaftliche", "mitarbeiter", "bewerbung", "stelle", "universität",
            "befristet", "vergütung", "und", "für", "eine", "gesucht")),
    ("fr", ("recherche", "poste", "candidature", "candidatures", "université",
            "contrat", "ingénieur", "études", "pour", "avec", "sont")),
    ("es", ("investigación", "contrato", "universidad", "convocatoria",
            "solicitud", "para", "investigador")),
    ("it", ("ricerca", "concorso", "università", "assegno", "candidatura", "per")),
    ("nl", ("onderzoek", "universiteit", "sollicitatie", "vacature", "voor")),
    ("pt", ("investigação", "pesquisa", "universidade", "candidatura", "para")),
)


def language_hint(text: str) -> str:
    """Return a two-letter hint, defaulting to 'en'.

    Deliberately biased towards 'en': a wrong 'de' costs a lexicon choice,
    while a wrong 'en' on a German advert would drop it at the gate.
    """
    lowered = (text or "").lower()
    if not lowered:
        return "en"
    tokens = set(_LATIN_TOKENS.findall(lowered))
    best, best_score = "en", 1  # 'en' starts with a one-point handicap
    for lang, markers in _LANG_MARKERS:
        score = sum(1 for m in markers if m in tokens)
        if score > best_score:
            best, best_score = lang, score
    return best


_TOKEN = re.compile(r"\w+", re.UNICODE)


def word_shingles(text: str, size: int = 5) -> set[str]:
    """w-shingles over normalised word tokens.

    Word 5-shingles are the standard near-duplicate primitive. Character
    n-grams saturate on long documents -- two *unrelated* English job adverts
    routinely share most of their character trigrams -- which is why this is the
    default and char n-grams are only a short-text fallback.
    """
    tokens = _TOKEN.findall((text or "").lower())
    if len(tokens) < size:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)}


def char_ngrams(text: str, size: int = 3) -> set[str]:
    """Character n-grams. Fallback for text too short to shingle by word."""
    compact = squish(text).lower()
    if len(compact) < size:
        return {compact} if compact else set()
    return {compact[i : i + size] for i in range(len(compact) - size + 1)}
