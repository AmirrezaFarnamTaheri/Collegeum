"""Three-tier deduplication engine. Stdlib only.

Tier 1  canonical URL equality          exact, O(1), enforced by a UNIQUE index
Tier 2  MinHash LSH over word 5-shingles near-duplicate full texts across portals
Tier 3  token-sort ratio over a composite key + deadline proximity, for short
        social posts that carry no description to shingle

Each tier is strictly cheaper than the one after it and the search stops at the
first hit. Tier 3 is blocked on a normalised institution token, so it compares
an incoming item against the handful of records from the same employer rather
than the whole corpus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .fuzzy import token_sort_ratio
from .identity import normalize_institution
from .minhash import MinHash, MinHashLSH
from .textproc import char_ngrams, word_shingles
from .timeparse import days_between, parse_datetime
from .urls import composite_key

__all__ = ["Duplicate", "Deduplicator"]

_SHINGLE_MIN_WORDS = 24  # below this, word 5-shingles are too sparse to be useful
_STOP_TOKENS = {
    "the", "of", "at", "for", "and", "university", "universite", "universitat",
    "universidad", "universita", "school", "institute", "college", "de", "di", "du",
}
_WORD_RE = re.compile(r"\w+")


def _blocking_key(institution: str) -> str:
    """Most distinctive token of an institution name, used to block tier 3."""
    tokens = [
        t for t in _WORD_RE.findall(normalize_institution(institution)) if t not in _STOP_TOKENS
    ]
    return max(tokens, key=len) if tokens else ""


@dataclass(slots=True)
class Duplicate:
    listing_id: int
    tier: str
    score: float

    def __str__(self) -> str:  # pragma: no cover - logging convenience
        return f"{self.tier}:{self.listing_id}@{self.score:.3f}"


@dataclass(slots=True)
class _Record:
    listing_id: int
    institution: str
    title: str
    principal_investigator: str | None
    deadline: datetime | None
    composite: str


class Deduplicator:
    """In-memory index over the recent corpus, rebuilt at the start of each run."""

    def __init__(
        self,
        *,
        jaccard_threshold: float = 0.82,
        fuzzy_threshold: float = 88.0,
        deadline_window_days: int = 14,
        num_perm: int = 128,
    ) -> None:
        self.jaccard_threshold = jaccard_threshold
        self.fuzzy_threshold = fuzzy_threshold
        self.deadline_window_days = deadline_window_days
        self.num_perm = num_perm
        self._lsh = MinHashLSH(threshold=jaccard_threshold, num_perm=num_perm)
        self._by_block: dict[str, list[_Record]] = {}
        self._records: dict[int, _Record] = {}

    def __len__(self) -> int:
        return len(self._records)

    @property
    def banding(self) -> tuple[int, int]:
        return self._lsh.bands, self._lsh.rows

    @staticmethod
    def text_for(title: str, summary: str) -> str:
        """The reproducible identity text available both live and after recovery."""
        return f"{title or ''}. {summary or ''}"

    @staticmethod
    def signature(text: str, num_perm: int = 128) -> MinHash | None:
        """Word 5-shingles for real descriptions, char trigrams for stubs."""
        words = (text or "").split()
        tokens = (
            word_shingles(text, 5) if len(words) >= _SHINGLE_MIN_WORDS else char_ngrams(text, 3)
        )
        return MinHash.from_tokens(tokens, num_perm=num_perm)

    def add(
        self,
        listing_id: int,
        *,
        text: str,
        institution: str,
        title: str,
        principal_investigator: str | None = None,
        deadline: str | datetime | None = None,
        signature: MinHash | None = None,
    ) -> None:
        sig = signature or self.signature(text, self.num_perm)
        if sig is not None:
            self._lsh.insert(listing_id, sig)
        record = _Record(
            listing_id=listing_id,
            institution=institution or "",
            title=title or "",
            principal_investigator=principal_investigator,
            deadline=parse_datetime(deadline),
            composite=composite_key(institution, title, principal_investigator),
        )
        self._records[listing_id] = record
        self._by_block.setdefault(_blocking_key(institution), []).append(record)

    def seed(self, rows: Any) -> None:
        """Populate from database rows (sqlite3.Row or dict-like)."""
        for row in rows:
            get = row.__getitem__ if hasattr(row, "keys") else row.get
            blob = None
            try:
                blob = get("signature")
            except (KeyError, IndexError):
                blob = None
            sig = MinHash.from_bytes(blob) if blob else None
            if sig is not None and len(sig.values) != self.num_perm:
                sig = None
            self.add(
                int(get("id")),
                text=self.text_for(get("title"), get("summary")),
                institution=get("institution") or "",
                title=get("title") or "",
                principal_investigator=get("principal_investigator"),
                deadline=get("deadline"),
                signature=sig,
            )

    def _deadlines_compatible(self, a: datetime | None, b: datetime | None) -> bool:
        gap = days_between(a, b)
        if gap is None:
            return True  # unknown deadline is not evidence of difference
        return gap <= self.deadline_window_days

    def _compatible(
        self, record: _Record, institution: str, title: str,
        principal_investigator: str | None, deadline: datetime | None,
    ) -> bool:
        employer = normalize_institution(institution)
        if not employer or employer != normalize_institution(record.institution):
            return False
        if not self._deadlines_compatible(deadline, record.deadline):
            return False
        mine = " ".join(_WORD_RE.findall((title or "").lower()))
        theirs = " ".join(_WORD_RE.findall(record.title.lower()))
        if not mine or not theirs:
            return False
        if not (mine.startswith(theirs + " ") or theirs.startswith(mine + " ")) and (
            token_sort_ratio(mine, theirs) < self.fuzzy_threshold
        ):
            return False
        if principal_investigator and record.principal_investigator:
            def surnames(value: str) -> set[str]:
                parts = re.split(r"[,;&]|\band\b", value, flags=re.I)
                return {tokens[-1] for part in parts if (tokens := _WORD_RE.findall(part.lower()))}

            if not surnames(principal_investigator) & surnames(record.principal_investigator):
                return False
        return True

    def find(
        self,
        *,
        text: str,
        institution: str,
        title: str,
        principal_investigator: str | None = None,
        deadline: str | datetime | None = None,
        signature: MinHash | None = None,
    ) -> Duplicate | None:
        """First duplicate found, or None. Tiers run cheapest-first."""
        want = parse_datetime(deadline)
        sig = signature if signature is not None else self.signature(text, self.num_perm)
        if sig is not None and len(self._lsh):
            best_key, best_score = None, 0.0
            for key in sorted(self._lsh.query(sig)):
                record = self._records[key]
                if not self._compatible(record, institution, title, principal_investigator, want):
                    continue
                other_signature = self._lsh.signature(key)
                score = sig.jaccard(other_signature) if other_signature is not None else 0.0
                if score >= self.jaccard_threshold and score > best_score:
                    best_key, best_score = key, score
            if best_key is not None:
                return Duplicate(best_key, "minhash", best_score)

        incoming = composite_key(institution, title, principal_investigator)
        if not incoming.strip(" |"):
            return None
        block = self._by_block.get(_blocking_key(institution), [])
        best_id, best_score = None, 0.0
        for record in block:
            if not self._compatible(record, institution, title, principal_investigator, want):
                continue
            score = token_sort_ratio(incoming, record.composite)
            if score > best_score:
                best_id, best_score = record.listing_id, score
        if best_id is not None and best_score >= self.fuzzy_threshold:
            return Duplicate(best_id, "fuzzy", best_score)
        return None
