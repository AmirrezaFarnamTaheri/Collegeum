"""X (Twitter) broadcasting and API client.

Implements publishing of newly discovered listings to X/Twitter via official
X API v2 using OAuth 1.0a (User Context), with 280-character budget accounting
(URLs count as 23 characters per Twitter specifications) and thread formatting.
"""

from __future__ import annotations

import json
import os
import unicodedata
from hashlib import sha256
from pathlib import Path
from typing import Any

from twitter_text import (  # type: ignore[import-untyped]
    extract_emojis_with_indices,
    extract_urls_with_indices,
    parse_tweet,
)

from ..core.textproc import squish
from ..core.urls import url_hash
from ..models import PredocListing
from ..routing import Router
from .telegram import deadline_label
from .x_state import ThreadStateError, XThreadJournal, valid_post_id

__all__ = [
    "XError",
    "XClient",
    "format_tweet",
    "format_thread",
    "tweet_length",
]

MAX_TWEET_CHARS = 280


class XError(RuntimeError):
    """The X API rejected the request, or was unreachable."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        permanent: bool = False,
        reset_ts: int | None = None,
        uncertain: bool = False,
        created_ids: tuple[str, ...] = (),
        next_index: int | None = None,
        thread_key: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.permanent = permanent
        self.reset_ts = reset_ts
        self.uncertain = uncertain
        self.created_ids = created_ids
        self.next_index = next_index
        self.thread_key = thread_key


def tweet_length(text: str) -> int:
    """Measure the character count according to X/Twitter rules.

    On X, any HTTP/HTTPS URL counts as exactly 23 characters (t.co wrap)
    regardless of its actual string length.
    """
    return int(parse_tweet(text).weightedLength)


def _clean_text(text: str) -> str:
    text = ''.join(c for c in text if not 0xD800 <= ord(c) <= 0xDFFF
                   and ord(c) not in (0xFEFF, 0xFFFE, 0xFFFF))
    return unicodedata.normalize('NFC', squish(text))


def _truncate_weighted(text: str, budget: int) -> str:
    """Keep complete detected URLs, emoji sequences and combining characters."""
    text = _clean_text(text)
    if budget <= 0:
        return ''
    if tweet_length(text) <= budget:
        return text
    spans = sorted(extract_urls_with_indices(text) + extract_emojis_with_indices(text),
                   key=lambda item: item['indices'][0])
    ends = {}
    covered = 0
    for span in spans:
        start, end = span['indices']
        if start >= covered:
            ends[start] = end
            covered = end
    result = ''
    index = 0
    while index < len(text):
        end = ends.get(index, index + 1)
        while end < len(text) and unicodedata.combining(text[end]):
            end += 1
        candidate = result + text[index:end]
        if tweet_length(candidate.rstrip() + '…') > budget:
            break
        result = candidate
        index = end
    return result.rstrip() + '…'


def format_tweet(listing: PredocListing, max_chars: int = MAX_TWEET_CHARS) -> str:
    """Format a single high-signal tweet for an academic job listing.

    Ensures the resulting tweet strictly respects Twitter's 280-character budget.
    """
    if not 1 <= max_chars <= MAX_TWEET_CHARS:
        raise ValueError('X post budget must be between 1 and 280')
    loc_parts = [p for p in (listing.location.city, listing.location.country) if p]
    if loc_parts:
        loc_str = ", ".join(loc_parts)
    elif listing.location.is_remote:
        loc_str = "Remote"
    else:
        loc_str = ""

    kind = Router.position_kind(listing.title, listing.summary)
    label, tag = {'predoc': ('Pre-Doctoral', '#Predoc'),
                  'phd': ('PhD', '#PhD'), 'postdoc': ('Postdoctoral', '#Postdoc')}[kind]
    link = listing.apply_url or listing.source_url
    fields = [
        ('🏛 ', _truncate_weighted(listing.institution, max_chars)),
        ('💼 ', _truncate_weighted(listing.title, max_chars)),
        ('📍 ', _truncate_weighted(loc_str, max_chars)),
        ('⏳ Deadline: ', _truncate_weighted(
            deadline_label(listing.deadline, listing.deadline_note, relative=False), max_chars)),
    ]

    def assemble() -> str:
        lines = [f'🎓 New {label} Opening', '']
        lines.extend(prefix + text for prefix, text in fields if text)
        lines.extend([f'🔗 {link}', '', f'#EconTwitter {tag}'])
        return '\n'.join(lines)

    while tweet_length(assemble()) > max_chars:
        index = max(range(len(fields)), key=lambda i: tweet_length(fields[i][1]))
        prefix, text = fields[index]
        if not text:
            raise ValueError('X post budget cannot hold the role heading, link and hashtags')
        excess = tweet_length(assemble()) - max_chars
        budget = max(0, tweet_length(text) - max(excess, 1))
        fields[index] = (prefix, _truncate_weighted(text, budget))
    tweet = assemble()
    if not parse_tweet(tweet).valid:
        raise ValueError('Listing cannot produce a valid X post')
    return tweet


def format_thread(listing: PredocListing) -> list[str]:
    """Format a 2-tweet thread: Tweet 1 with essentials, Tweet 2 with details."""
    tweet1 = format_tweet(listing)
    extra_parts = []
    if listing.summary:
        extra_parts.append(_truncate_weighted(listing.summary, 200))
    if listing.visa_sponsorship_status.value != "unknown":
        visa_desc = f"Visa: {listing.visa_sponsorship_status.value}"
        if listing.visa_note:
            visa_desc += f" ({_truncate_weighted(listing.visa_note, 200)})"
        extra_parts.append(visa_desc)
    if listing.disciplines:
        extra_parts.append("Fields: " + ", ".join(d.value for d in listing.disciplines[:3]))

    if not extra_parts:
        return [tweet1]

    tweet2 = "📌 Details:\n\n" + "\n\n".join(extra_parts)
    if tweet_length(tweet2) > MAX_TWEET_CHARS:
        tweet2 = _truncate_weighted(tweet2, MAX_TWEET_CHARS)
    return [tweet1, tweet2]


class XClient:
    """Client for X API v2 posting and search."""

    API_BASE = "https://api.x.com/2"

    def __init__(
        self,
        *,
        consumer_key: str = "",
        consumer_secret: str = "",
        access_token: str = "",
        access_token_secret: str = "",
        bearer_token: str = "",
        session: Any = None,
        thread_journal_path: str | Path = 'data/x_threads.sqlite3',
        publication_scope: str = '',
    ) -> None:
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.access_token = access_token
        self.access_token_secret = access_token_secret
        self.bearer_token = bearer_token
        self._session = session
        self._owns_session = False
        self.thread_journal = XThreadJournal(thread_journal_path)
        self.publication_scope = publication_scope or sha256(
            f'{consumer_key}\0{access_token}'.encode()
        ).hexdigest()

    @classmethod
    def from_settings(cls, settings: Any) -> XClient:
        return cls(
            consumer_key=(
                getattr(settings, "x_consumer_key", "")
                or os.environ.get("X_CONSUMER_KEY", "")
            ),
            consumer_secret=(
                getattr(settings, "x_consumer_secret", "")
                or os.environ.get("X_CONSUMER_SECRET", "")
            ),
            access_token=(
                getattr(settings, "x_access_token", "")
                or os.environ.get("X_ACCESS_TOKEN", "")
            ),
            access_token_secret=(
                getattr(settings, "x_access_token_secret", "")
                or os.environ.get("X_ACCESS_TOKEN_SECRET", "")
            ),
            bearer_token=(
                getattr(settings, "x_bearer_token", "")
                or os.environ.get("X_BEARER_TOKEN", "")
            ),
            thread_journal_path=getattr(
                settings, 'x_thread_journal_path', 'data/x_threads.sqlite3'),
            publication_scope=getattr(settings, 'x_publication_scope', ''),
        )

    def _get_oauth_session(self) -> Any:
        if self._session is not None:
            return self._session
        try:
            from requests_oauthlib import OAuth1Session  # type: ignore[import-untyped]

            self._session = OAuth1Session(
                client_key=self.consumer_key,
                client_secret=self.consumer_secret,
                resource_owner_key=self.access_token,
                resource_owner_secret=self.access_token_secret,
            )
            self._owns_session = True
            return self._session
        except ImportError as exc:
            raise XError(
                "requests_oauthlib is required for posting to X: pip install requests-oauthlib"
            ) from exc

    def close(self) -> None:
        if self._owns_session and self._session is not None:
            self._session.close()
            self._session = None
            self._owns_session = False

    def __enter__(self) -> XClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def post_tweet(self, text: str, in_reply_to_tweet_id: str | None = None) -> str:
        """Post a single tweet to X and return the created tweet ID."""
        if (not text.strip() or any(0xD800 <= ord(c) <= 0xDFFF for c in text)
                or not parse_tweet(text).valid):
            raise XError('X post text is empty, invalid or exceeds the weighted limit',
                         permanent=True)
        if in_reply_to_tweet_id is not None and not valid_post_id(in_reply_to_tweet_id):
            raise XError('Invalid X reply post identifier', permanent=True)
        session = self._get_oauth_session()
        url = f"{self.API_BASE}/tweets"
        payload: dict[str, Any] = {"text": text}
        if in_reply_to_tweet_id:
            payload["reply"] = {"in_reply_to_tweet_id": in_reply_to_tweet_id}

        try:
            resp = session.post(url, json=payload, timeout=20.0)
        except Exception as exc:
            raise XError('X submission outcome unknown after a transport failure',
                         uncertain=True) from exc

        if resp.status_code == 201:
            try:
                body = resp.json() if hasattr(resp, "json") else {}
            except (ValueError, TypeError) as exc:
                raise XError('X API 201 response missing valid tweet id in malformed JSON',
                             status=201, uncertain=True) from exc
            data = body.get("data", {}) if isinstance(body, dict) else {}
            tweet_id = data.get('id') if isinstance(data, dict) else None
            if not valid_post_id(tweet_id):
                raise XError("X API 201 response missing valid tweet id in 'data.id'",
                             status=201, uncertain=True)
            return tweet_id

        status = resp.status_code
        reset_ts = None
        if "x-rate-limit-reset" in resp.headers:
            try:
                reset_ts = int(resp.headers["x-rate-limit-reset"])
            except (ValueError, TypeError):
                pass

        if status == 429:
            raise XError(
                f"Rate limited by X API. Reset at {reset_ts}",
                status=429,
                reset_ts=reset_ts,
            )
        if status in (401, 403):
            detail = ""
            try:
                body = resp.json()
                detail = body.get('detail', '') if isinstance(body, dict) else ''
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                pass
            raise XError(
                f"X authentication/permission error ({status}): {detail or resp.text}",
                status=status,
                permanent=True,
            )

        raise XError(f'X API error {status}', status=status,
                     permanent=400 <= status < 500, uncertain=status >= 500 or status < 400)

    def post_thread(self, tweets: list[str], *, thread_key: str | None = None) -> list[str]:
        """Resume acknowledged segments; require reconciliation of unknown outcomes.

        Persist the journal across runs. Reusing a logical key with changed
        content fails instead of silently starting another copy of a thread.
        """
        if not tweets:
            return []
        for text in tweets:
            if (not text.strip() or any(0xD800 <= ord(c) <= 0xDFFF for c in text)
                    or not parse_tweet(text).valid):
                raise XError('Thread contains invalid post text', permanent=True)
        tweets = [unicodedata.normalize('NFC', text) for text in tweets]
        fingerprint = sha256(json.dumps(tweets, ensure_ascii=False).encode('utf-8')).hexdigest()
        key = sha256(f'{self.publication_scope}\0{thread_key or fingerprint}'.encode()).hexdigest()
        state = None
        try:
            state = self.thread_journal.prepare(key, fingerprint, len(tweets))
            if state.pending:
                raise XError('Reconcile the pending X submission before resuming', uncertain=True)
            while len(state.ids) < len(tweets):
                state = self.thread_journal.claim(state)
                try:
                    new_id = self.post_tweet(
                        tweets[len(state.ids)],
                        in_reply_to_tweet_id=state.ids[-1] if state.ids else None)
                except Exception as error:
                    if (isinstance(error, XError) and not error.uncertain
                            and (error.permanent or error.status in range(400, 500))):
                        state = self.thread_journal.reject(state)
                    raise
                try:
                    state = self.thread_journal.acknowledge(state, new_id)
                except Exception as error:
                    raise XError('X post created but acknowledgement could not be saved',
                                 uncertain=True, created_ids=(*state.ids, new_id)) from error
            return list(state.ids)
        except Exception as error:
            state = getattr(error, 'state', None) or state
            ids = getattr(error, 'created_ids', ()) or (state.ids if state else ())
            uncertain = (state.pending if state else False) or getattr(error, 'uncertain', False)
            raise XError(str(error), status=getattr(error, 'status', None),
                         permanent=getattr(error, 'permanent', isinstance(error, ThreadStateError)),
                         reset_ts=getattr(error, 'reset_ts', None), uncertain=uncertain,
                         created_ids=ids, next_index=len(ids), thread_key=key) from error

    def post_listing(self, listing: PredocListing, as_thread: bool = False) -> str:
        """Format and post an academic listing to X. Returns the primary tweet ID."""
        if as_thread:
            thread = format_thread(listing)
            ids = self.post_thread(
                thread, thread_key=f'listing:{url_hash(listing.apply_url or listing.source_url)}')
            return ids[0] if ids else ""
        tweet = format_tweet(listing)
        key = f'single-listing:{url_hash(listing.apply_url or listing.source_url)}'
        ids = self.post_thread(
            [tweet], thread_key=key
        )
        return ids[0]

    def search_recent(
        self,
        query: str,
        max_results: int = 10,
        http_client: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Search recent public tweets using Bearer Token (X API v2)."""
        bearer = self.bearer_token or os.environ.get("X_BEARER_TOKEN", "")
        if not bearer:
            raise XError("X_BEARER_TOKEN is required for searching X via API v2")

        url = f"{self.API_BASE}/tweets/search/recent"
        headers = {"Authorization": f"Bearer {bearer}"}
        params: dict[str, Any] = {
            "query": query,
            "max_results": min(max(10, max_results), 100),
            "tweet.fields": "created_at,entities,author_id,text",
            "expansions": "author_id",
            "user.fields": "username,name",
        }

        if http_client is not None:
            resp = http_client.get(url, headers=headers, params=params)
        else:
            import httpx

            with httpx.Client(timeout=20.0) as client:
                resp = client.get(url, headers=headers, params=params)

        if resp.status_code != 200:
            raise XError(
                f"X search failed ({resp.status_code}): {resp.text[:300]}",
                status=resp.status_code,
            )

        try:
            payload = resp.json()
        except (ValueError, TypeError) as error:
            raise XError('Malformed X search response') from error
        if not isinstance(payload, dict):
            raise XError('Malformed X search response')
        if 'data' not in payload:
            metadata = payload.get('meta')
            if (not isinstance(metadata, dict) or type(metadata.get('result_count')) is not int
                    or metadata['result_count'] != 0 or payload.get('errors')):
                raise XError('X search response has no confirmed results or empty-result metadata')
        includes = payload.get('includes', {})
        if not isinstance(includes, dict):
            raise XError('Malformed X search user data')
        users = includes.get('users', [])
        tweets = payload.get('data', [])
        if (not isinstance(users, list) or not isinstance(tweets, list)
                or any(not isinstance(user, dict) or not valid_post_id(user.get('id'))
                       for user in users)
                or any(not isinstance(tweet, dict) or not valid_post_id(tweet.get('id'))
                       or not isinstance(tweet.get('text'), str) for tweet in tweets)):
            raise XError('Malformed X search results')
        users_by_id = {u['id']: u for u in users}
        for t in tweets:
            author_id = t.get("author_id")
            if author_id in users_by_id:
                t["author"] = users_by_id[author_id]
        return [dict(tweet) for tweet in tweets]
