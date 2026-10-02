"""Typed configuration, entirely from environment variables or a .env file.

Rate limits are configuration with conservative defaults rather than
hard-coded architectural constants. The provider's public documentation no
longer publishes a fixed free-tier table -- it states that limits depend on
account tier and are visible only in the console, and that "specified rate
limits are not guaranteed". Any number baked into the source is therefore a
guess with a short shelf life; making it a setting means a 429 storm is fixed
by editing one variable rather than shipping code.
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Telegram ---------------------------------------------------------
    telegram_bot_token: str = ""
    # Where new positions are posted. For a personal bot, put YOUR chat id here
    # (the number `predoc-pipeline telegram-chat-id` prints); a channel works too.
    telegram_public_channel_id: str = ""
    # Where warnings go (broken sources, quiet weeks). Defaults to the chat above
    # when that is a private chat.
    telegram_admin_chat_id: str = ""
    telegram_digest_threshold: int = Field(
        12,
        description="Above this many new listings in one run, post a compact "
                    "digest instead of one card each. Protects the channel from "
                    "a forty-message burst after a backfill.",
    )

    # -- Model provider ---------------------------------------------------
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-lite-latest"
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    extraction_backend: str = Field(
        "auto",
        description="auto | heuristic | interactions | generate_content | instructor | null. "
                    "auto = Gemini when GEMINI_API_KEY is set, otherwise heuristic.",
    )
    llm_requests_per_minute: int = 10
    llm_requests_per_day: int = 200
    llm_daily_safety_margin: float = Field(0.9, ge=0.1, le=1.0)
    llm_max_input_chars: int = 12_000
    llm_timeout_seconds: float = 45.0

    # -- Storage ----------------------------------------------------------
    db_path: str = "data/predocs.db"
    state_path: str = "data/listings.ndjson"
    dashboard_json: str = "docs/data/listings.json"
    health_json: str = "docs/data/health.json"
    feed_path: str = "docs/feed.xml"
    dlq_path: str = "dlq-failures.json"
    site_url: str = ""
    # Every posting ever judged (so its page is read once, not daily). Committed
    # next to listings.ndjson because the SQLite file is not.
    seen_state_path: str = "data/seen.ndjson"
    # Your ✅ ❌ 📝 marks from Telegram, and the bot's update offset.
    feedback_path: str = "data/feedback.json"
    telegram_state_path: str = "data/telegram_state.json"

    # -- Classification ---------------------------------------------------
    confidence_threshold: float = Field(0.70, ge=0.0, le=1.0)
    model_confidence_weight: float = Field(0.75, ge=0.0, le=1.0)

    # -- Deduplication ----------------------------------------------------
    dedupe_jaccard_threshold: float = Field(0.82, ge=0.0, le=1.0)
    dedupe_fuzzy_threshold: float = Field(88.0, ge=0.0, le=100.0)
    dedupe_deadline_window_days: int = 14
    dedupe_lookback_days: int = 120

    # -- Ingestion --------------------------------------------------------
    sources_config: str = "config/sources.toml"
    # Fields, region, employer type, excluded employers... (see the file).
    preferences_config: str = "config/preferences.toml"
    max_items_per_source: int = 120
    http_timeout_seconds: float = 25.0
    http_user_agent: str = (
        "predoc-pipeline/2.0 (+https://github.com/USER/predoc-pipeline; "
        "academic job aggregation; contact: MAINTAINER@example.org)"
    )
    respect_robots_txt: bool = True
    per_host_delay_seconds: float = 1.0

    # -- Source toggles ---------------------------------------------------
    # Feeds and portals read what publishers deliberately syndicate.
    # The other two carry terms-of-service risk and are opt-in. See
    # COMPLIANCE.md before turning them on.
    enable_boards: bool = True
    enable_feeds: bool = True
    enable_portals: bool = True
    enable_jobspy: bool = False
    enable_twitter: bool = False

    # -- Operations -------------------------------------------------------
    empty_run_alert_threshold: int = Field(
        3, description="Consecutive zero-publish runs before alerting the maintainer."
    )
    expiry_grace_days: int = 1
    dry_run: bool = False

    @field_validator("extraction_backend")
    @classmethod
    def _known_backend(cls, value: str) -> str:
        allowed = {"auto", "heuristic", "interactions", "generate_content", "instructor", "null"}
        if value not in allowed:
            raise ValueError(f"extraction_backend must be one of {sorted(allowed)}")
        return value

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_public_channel_id)

    @staticmethod
    def _is_private_chat(chat_id: str) -> bool:
        """Private chats (people) have positive numeric ids; groups/channels don't."""
        value = (chat_id or "").strip()
        return value.isdigit() and int(value) > 0

    @property
    def owner_ids(self) -> set[int]:
        """People allowed to use /positions and the ✅ ❌ 📝 buttons."""
        return {
            int(c.strip())
            for c in (self.telegram_admin_chat_id, self.telegram_public_channel_id)
            if self._is_private_chat(c)
        }

    @property
    def alert_chat_id(self) -> str:
        if self.telegram_admin_chat_id:
            return self.telegram_admin_chat_id
        if self._is_private_chat(self.telegram_public_channel_id):
            return self.telegram_public_channel_id
        return ""
