"""X (Twitter) broadcasting and API client.

Implements publishing of newly discovered listings to X/Twitter via official
X API v2 using OAuth 1.0a (User Context), with 280-character budget accounting
(URLs count as 23 characters per Twitter specifications) and thread formatting.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from ..core.textproc import squish, truncate
from ..models import PredocListing
from .telegram import deadline_label

__all__ = [
    "XError",
    "XClient",
    "format_tweet",
    "format_thread",
    "tweet_length",
]

_URL_RE = re.compile(r"https?://\S+")
T_CO_LENGTH = 23
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
    ) -> None:
        super().__init__(message)
        self.status = status
        self.permanent = permanent
        self.reset_ts = reset_ts


def tweet_length(text: str) -> int:
    """Measure the character count according to X/Twitter rules.

    On X, any HTTP/HTTPS URL counts as exactly 23 characters (t.co wrap)
    regardless of its actual string length.
    """
    urls = _URL_RE.findall(text)
    text_no_urls = _URL_RE.sub("", text)
    return len(text_no_urls) + (len(urls) * T_CO_LENGTH)


def format_tweet(listing: PredocListing, max_chars: int = MAX_TWEET_CHARS) -> str:
    """Format a single high-signal tweet for an academic job listing.

    Ensures the resulting tweet strictly respects Twitter's 280-character budget.
    """
    loc_parts = [p for p in (listing.location.city, listing.location.country) if p]
    if loc_parts:
        loc_str = ", ".join(loc_parts)
    elif listing.location.is_remote:
        loc_str = "Remote"
    else:
        loc_str = ""

    deadline_str = deadline_label(listing.deadline, listing.deadline_note)
    link = listing.apply_url or listing.source_url

    hashtags = "#EconTwitter #Predoc"
    lines = [
        "🎓 New Pre-Doctoral Opening",
        "",
        f"🏛 {squish(listing.institution)}",
        f"💼 {squish(listing.title)}",
    ]
    if loc_str:
        lines.append(f"📍 {loc_str}")
    if deadline_str:
        lines.append(f"⏳ Deadline: {deadline_str}")
    lines.extend([
        f"🔗 {link}",
        "",
        hashtags,
    ])

    tweet = "\n".join(lines)
    if tweet_length(tweet) <= max_chars:
        return tweet

    # Need to truncate title or institution to fit
    avail = max_chars - (tweet_length(tweet) - len(listing.title))
    if avail > 20:
        short_title = truncate(listing.title, avail - 3) + "..."
        lines[3] = f"💼 {short_title}"
        tweet = "\n".join(lines)
        if tweet_length(tweet) <= max_chars:
            return tweet

    # Fallback to minimal essential post
    minimal_lines = [
        f"🎓 {squish(listing.institution)}: {truncate(listing.title, 80)}",
        f"⏳ {deadline_str}" if deadline_str else "",
        f"🔗 {link}",
        hashtags,
    ]
    return "\n".join([line for line in minimal_lines if line])


def format_thread(listing: PredocListing) -> list[str]:
    """Format a 2-tweet thread: Tweet 1 with essentials, Tweet 2 with details."""
    tweet1 = format_tweet(listing)
    extra_parts = []
    if listing.summary:
        extra_parts.append(truncate(squish(listing.summary), 200))
    if listing.visa_sponsorship_status.value != "unknown":
        visa_desc = f"Visa: {listing.visa_sponsorship_status.value}"
        if listing.visa_note:
            visa_desc += f" ({listing.visa_note})"
        extra_parts.append(visa_desc)
    if listing.disciplines:
        extra_parts.append("Fields: " + ", ".join(d.value for d in listing.disciplines[:3]))

    if not extra_parts:
        return [tweet1]

    tweet2 = "📌 Details:\n\n" + "\n\n".join(extra_parts)
    if tweet_length(tweet2) > MAX_TWEET_CHARS:
        tweet2 = truncate(tweet2, MAX_TWEET_CHARS - 3) + "..."
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
    ) -> None:
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.access_token = access_token
        self.access_token_secret = access_token_secret
        self.bearer_token = bearer_token
        self._session = session

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
        )

    def _get_oauth_session(self) -> Any:
        if self._session is not None:
            return self._session
        try:
            from requests_oauthlib import OAuth1Session

            return OAuth1Session(
                client_key=self.consumer_key,
                client_secret=self.consumer_secret,
                resource_owner_key=self.access_token,
                resource_owner_secret=self.access_token_secret,
            )
        except ImportError as exc:
            raise XError(
                "requests_oauthlib is required for posting to X: pip install requests-oauthlib"
            ) from exc

    def post_tweet(self, text: str, in_reply_to_tweet_id: str | None = None) -> str:
        """Post a single tweet to X and return the created tweet ID."""
        session = self._get_oauth_session()
        url = f"{self.API_BASE}/tweets"
        payload: dict[str, Any] = {"text": text}
        if in_reply_to_tweet_id:
            payload["reply"] = {"in_reply_to_tweet_id": in_reply_to_tweet_id}

        try:
            resp = session.post(url, json=payload, timeout=20.0)
        except Exception as exc:
            raise XError(f"Network error connecting to X API: {exc}") from exc

        if resp.status_code == 201:
            body = resp.json() if hasattr(resp, "json") else {}
            data = body.get("data", {}) if isinstance(body, dict) else {}
            tweet_id = str(data.get("id", "")).strip() if isinstance(data, dict) else ""
            if not tweet_id:
                raise XError("X API 201 response missing valid tweet id in 'data.id'")
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
                detail = resp.json().get("detail", "")
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                pass
            raise XError(
                f"X authentication/permission error ({status}): {detail or resp.text}",
                status=status,
                permanent=True,
            )

        raise XError(f"X API error {status}: {resp.text[:300]}", status=status)

    def post_thread(self, tweets: list[str]) -> list[str]:
        """Post a sequence of tweets as a thread."""
        tweet_ids: list[str] = []
        last_id: str | None = None
        for text in tweets:
            new_id = self.post_tweet(text, in_reply_to_tweet_id=last_id)
            tweet_ids.append(new_id)
            last_id = new_id
        return tweet_ids

    def post_listing(self, listing: PredocListing, as_thread: bool = False) -> str:
        """Format and post an academic listing to X. Returns the primary tweet ID."""
        if as_thread:
            thread = format_thread(listing)
            ids = self.post_thread(thread)
            return ids[0] if ids else ""
        tweet = format_tweet(listing)
        return self.post_tweet(tweet)

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

        payload = resp.json()
        users_by_id = {u["id"]: u for u in payload.get("includes", {}).get("users", [])}
        tweets = payload.get("data", [])
        for t in tweets:
            author_id = t.get("author_id")
            if author_id in users_by_id:
                t["author"] = users_by_id[author_id]
        return tweets
