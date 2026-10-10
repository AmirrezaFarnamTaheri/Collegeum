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

import re

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
        0,
        description="Above this many new listings in one run, post a compact "
                    "digest instead of one card each. Set to 0 (default) to disable "
                    "digest mode and always post individual cards regardless of count.",
    )
    telegram_feedback_buttons: bool = Field(
        False,
        description="Whether to include personal feedback buttons (Interested/Not for me/Applied) "
                    "on broadcast channel posts.",
    )

    # -- Model provider ---------------------------------------------------
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-lite-latest"
    gemini_base_url: str = "https://generativelanguage.googleapis.com"

    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    nvidia_api_key: str = ""
    nvidia_model: str = "meta/llama-3.3-70b-instruct"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-haiku-20241022"
    anthropic_base_url: str = "https://api.anthropic.com"

    openrouter_api_key: str = ""
    openrouter_api_keys: list[str] = Field(default_factory=list)
    openrouter_model: str = "openrouter/free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    mistral_api_key: str = ""
    mistral_model: str = "mistral-small-latest"
    mistral_base_url: str = "https://api.mistral.ai/v1"

    memo_api_key: str = ""
    memo_model: str = ""
    memo_base_url: str = ""

    custom_llm_api_key: str = ""
    custom_llm_model: str = "default"
    custom_llm_base_url: str = "http://localhost:8000/v1"

    extraction_backend: str = Field(
        "auto",
        description=(
            "auto | heuristic | gemini | groq | nvidia | nim | openai | anthropic | "
            "claude | openrouter | mistral | custom | null. "
            "auto detects configured key in priority order, falling back to heuristic."
        ),
    )
    extraction_concurrency: int = Field(
        12,
        ge=1,
        le=32,
        description="Parallel workers for LLM candidate digestion and key rotation.",
    )
    llm_requests_per_minute: int = 200
    llm_requests_per_day: int = 10000
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
    # Fernet key (``predoc-pipeline feedback-key``). When set, marks are stored only
    # as data/feedback.enc, which is safe to commit; without it they stay local.
    feedback_encryption_key: str = ""
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
    max_items_per_source: int = 400
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

    # -- X (Twitter) Integration ------------------------------------------
    x_broadcast_enabled: bool = True
    x_retry_limit: int = Field(20, ge=0, description="Existing web listings retried on X per run")
    x_bearer_token: str = ""
    xquik_api_key: str = ""
    x_consumer_key: str = ""
    x_consumer_secret: str = ""
    x_access_token: str = ""
    x_access_token_secret: str = ""
    x_thread_journal_path: str = 'data/x_threads.sqlite3'
    x_publication_scope: str = Field(
        '', description='Stable X account identifier for recovery across credential rotation',
    )
    twitter_search_accounts: list[str] = Field(
        default_factory=lambda: ["econ_RA", "predoc_org"]
    )
    twitter_search_queries: list[str] = Field(
        default_factory=lambda: [
            (
                '(from:econ_RA OR "predoc" OR "pre-doc" OR "predoctoral") '
                "(economics OR finance) -is:retweet -is:reply"
            ),
            (
                '"research assistant" (economics OR finance) '
                '("hiring" OR "now accepting" OR "apply") -is:retweet -is:reply'
            ),
        ]
    )

    # -- Operations -------------------------------------------------------
    empty_run_alert_threshold: int = Field(
        3, description="Consecutive zero-publish runs before alerting the maintainer."
    )
    expiry_grace_days: int = 1
    dry_run: bool = False

    @field_validator("extraction_backend")
    @classmethod
    def _known_backend(cls, value: str) -> str:
        allowed = {
            "auto",
            "heuristic",
            "gemini",
            "interactions",
            "generate_content",
            "instructor",
            "null",
            "groq",
            "nvidia",
            "nim",
            "openai",
            "anthropic",
            "claude",
            "openrouter",
            "mistral",
            "memo",
            "custom",
            "openai_compatible",
        }
        if value not in allowed:
            raise ValueError(f"extraction_backend must be one of {sorted(allowed)}")
        return value

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_public_channel_id)

    @property
    def x_broadcast_configured(self) -> bool:
        return bool(
            self.x_broadcast_enabled
            and self.x_consumer_key
            and self.x_consumer_secret
            and self.x_access_token
            and self.x_access_token_secret
        )

    @property
    def x_search_configured(self) -> bool:
        return bool(self.x_bearer_token or self.xquik_api_key)

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

    def get_openrouter_keys(self) -> list[str]:
        keys: list[str] = []
        if self.openrouter_api_keys:
            keys.extend(self.openrouter_api_keys)
        if self.openrouter_api_key:
            for part in re.split(r"[,;\s]+", self.openrouter_api_key.strip()):
                if part and part not in keys:
                    keys.append(part)
        return keys

