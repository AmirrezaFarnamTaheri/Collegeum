"""Structured extraction against the Gemini API, over plain HTTP.

Why not the SDK, or `instructor`
--------------------------------
The provider is mid-migration. Current documentation leads with an
``/v1beta/interactions`` endpoint taking ``response_format``, alongside a
published "breaking changes" note for that same API, while the older
``:generateContent`` endpoint with ``generationConfig.responseSchema`` remains
widely deployed. A wrapper library sits between us and that churn and adds its
own release cadence on top.

So: two thin backends over ``httpx``, an automatic one-time probe that records
which endpoint this key can reach, and the answer cached in the database so
subsequent runs skip the probe. ``instructor`` remains available as an opt-in
third backend for anyone who prefers it. The request body is small enough to
read in full, which is the point -- when the vendor changes shape again, the
fix is fifteen lines here rather than a dependency bump and a prayer.

Quota discipline
----------------
Every call passes through the shared ``RateLimiter`` first. A 429 is treated as
authoritative: the server's ``RetryInfo.retryDelay`` (or ``Retry-After``) wins
over any local estimate, and the limiter is penalised accordingly.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..core.ratelimit import QuotaExceeded, RateLimiter
from ..logging_setup import get_logger
from ..models import EXTRACTION_JSON_SCHEMA, ExtractionResult
from .prompt import SYSTEM_PROMPT, build_user_prompt

log = get_logger(__name__)

__all__ = [
    "ExtractionError",
    "RateLimited",
    "KeyRotator",
    "Extractor",
    "build_extractor",
    "NullExtractor",
]

_BACKEND_META_KEY = "extraction_backend_resolved"
_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_FENCE_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


@dataclass
class KeyState:
    key: str
    cooldown_until: float = 0.0
    calls: int = 0
    tokens: int = 0
    errors: int = 0


class KeyRotator:
    """Thread-safe round-robin API key rotator with automatic per-key cooldowns."""

    def __init__(self, keys: Any) -> None:
        clean: list[str] = []
        if isinstance(keys, str):
            raw = re.split(r"[,;\s]+", keys.strip())
        elif isinstance(keys, (list, tuple, set)):
            raw = list(keys)
        else:
            raw = [keys]

        for k in raw:
            if not k:
                continue
            for item in re.split(r"[,;\s]+", str(k).strip()):
                if item and item not in clean:
                    clean.append(item)

        if not clean:
            raise ValueError("KeyRotator requires at least one API key")

        self._states = [KeyState(key=k) for k in clean]
        self._lock = threading.Lock()
        self._index = 0

    @property
    def keys(self) -> list[str]:
        return [s.key for s in self._states]

    @property
    def primary_key(self) -> str:
        return self._states[0].key

    def __len__(self) -> int:
        return len(self._states)

    def get_key(self) -> str:
        """Return the next available healthy key in round-robin order."""
        with self._lock:
            now = time.monotonic()
            n = len(self._states)
            for i in range(n):
                idx = (self._index + i) % n
                state = self._states[idx]
                if state.cooldown_until <= now:
                    self._index = (idx + 1) % n
                    return state.key
            # All keys in cooldown: return the one that becomes free earliest
            earliest = min(self._states, key=lambda s: s.cooldown_until)
            wait = max(0.0, earliest.cooldown_until - now)
            key = earliest.key
        if wait > 60.0:
            raise RateLimited(
                f"all API keys cooling; next available in {wait:.1f}s", retry_after=wait
            )
        if wait > 0.0:
            time.sleep(wait)
        return key

    def mark_rate_limited(self, key: str, retry_after: float = 30.0) -> None:
        """Mark a specific key as rate-limited / on cooldown."""
        with self._lock:
            now = time.monotonic()
            for s in self._states:
                if s.key == key:
                    s.cooldown_until = now + max(10.0, retry_after)
                    s.errors += 1
                    break

    def mark_success(self, key: str, tokens: int = 0) -> None:
        """Record a successful call for this key."""
        with self._lock:
            for s in self._states:
                if s.key == key:
                    s.calls += 1
                    s.tokens += tokens
                    s.errors = 0
                    break

    def mark_error(self, key: str) -> None:
        """Record a transport or non-429 error for this key."""
        with self._lock:
            for s in self._states:
                if s.key == key:
                    s.errors += 1
                    if s.errors >= 3:
                        s.cooldown_until = time.monotonic() + 15.0
                    break


class ExtractionError(RuntimeError):
    """The provider could not be used, or returned something unusable."""


class RateLimited(ExtractionError):
    """The provider refused the request for quota reasons."""

    def __init__(self, message: str, retry_after: float = 0.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _strip_fence(text: str) -> str:
    """Extract JSON from raw text, removing markdown fences or surrounding commentary."""
    s = (text or "").strip()
    fence_match = _FENCE_BLOCK_RE.search(s)
    if fence_match:
        return fence_match.group(1).strip()
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return s[start:end + 1]
    return s


def _parse_retry_delay(response: httpx.Response) -> float:
    """Seconds to wait, preferring the provider's own instruction."""
    header = response.headers.get("retry-after")
    if header:
        try:
            delay = float(header)
            if math.isfinite(delay) and delay >= 0:
                return delay
        except ValueError:
            pass
    try:
        payload = response.json()
    except Exception:
        return 0.0
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        return 0.0
    details = payload["error"].get("details") or []
    if not isinstance(details, list):
        return 0.0
    for detail in details:
        if not isinstance(detail, dict):
            continue
        retry_delay = detail.get("retryDelay")
        if isinstance(retry_delay, str) and retry_delay.endswith("s"):
            try:
                parsed = float(retry_delay[:-1])
                if math.isfinite(parsed) and parsed >= 0:
                    return parsed
            except ValueError:
                continue
    return 0.0


@dataclass(slots=True)
class _Backend:
    name: str

    def headers(self, api_key: str) -> dict[str, str]:
        return {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }

    def request(self, model: str, system: str, user: str) -> dict[str, Any]:
        raise NotImplementedError

    def path(self, model: str) -> str:
        raise NotImplementedError

    def extract_text(self, payload: dict[str, Any]) -> str:
        raise NotImplementedError


class _InteractionsBackend(_Backend):
    """POST /v1beta/interactions with response_format. The documented path."""

    def __init__(self) -> None:
        super().__init__("interactions")

    def path(self, model: str) -> str:
        return "/v1beta/interactions"

    def request(self, model: str, system: str, user: str) -> dict[str, Any]:
        return {
            "model": model,
            "input": f"{system}\n\n---\n\n{user}",
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": EXTRACTION_JSON_SCHEMA,
            },
        }

    def extract_text(self, payload: dict[str, Any]) -> str:
        text = payload.get("output_text")
        if isinstance(text, str) and text.strip():
            return text
        # Fall back to walking the output items if the convenience field moves.
        chunks: list[str] = []
        for item in payload.get("output", []) or []:
            if isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    chunks.append(item["text"])
                for part in item.get("content", []) or []:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        chunks.append(part["text"])
        if chunks:
            return "\n".join(chunks)
        raise ExtractionError("no text in interactions response")


class _GenerateContentBackend(_Backend):
    """POST /v1beta/models/{model}:generateContent. The long-lived path."""

    def __init__(self) -> None:
        super().__init__("generate_content")

    def path(self, model: str) -> str:
        return f"/v1beta/models/{model}:generateContent"

    def request(self, model: str, system: str, user: str) -> dict[str, Any]:
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": EXTRACTION_JSON_SCHEMA,
                "temperature": 0.0,
                "candidateCount": 1,
            },
        }

    def extract_text(self, payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates") or []
        if not candidates:
            blocked = (payload.get("promptFeedback") or {}).get("blockReason")
            raise ExtractionError(f"no candidates returned (blockReason={blocked})")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        chunks = [p["text"] for p in parts if isinstance(p, dict) and "text" in p]
        if not chunks:
            finish = candidates[0].get("finishReason")
            raise ExtractionError(f"no text parts (finishReason={finish})")
        return "\n".join(chunks)


class _OpenAICompatibleBackend(_Backend):
    """POST /chat/completions (OpenAI, Groq, NVIDIA NIM, OpenRouter, Mistral, Ollama)."""

    def __init__(
        self, name: str = "openai_compatible", endpoint: str = "/chat/completions"
    ) -> None:
        super().__init__(name)
        self._endpoint = endpoint

    def headers(self, api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def path(self, model: str) -> str:
        return self._endpoint

    def request(self, model: str, system: str, user: str) -> dict[str, Any]:
        return {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }

    def extract_text(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            error = payload.get("error")
            raise ExtractionError(f"no choices returned ({error})")
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        text = choice.get("text")
        if isinstance(text, str) and text.strip():
            return text
        for r_key in ("reasoning_content", "reasoning"):
            r_val = message.get(r_key)
            if isinstance(r_val, str) and r_val.strip():
                return r_val
        refusal = message.get("refusal")
        if refusal:
            raise ExtractionError(f"model refusal: {refusal}")
        raise ExtractionError("no text content in model response message")


class _AnthropicBackend(_Backend):
    """POST /v1/messages (Anthropic Claude)."""

    def __init__(self) -> None:
        super().__init__("anthropic")

    def headers(self, api_key: str) -> dict[str, str]:
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def path(self, model: str) -> str:
        return "/v1/messages"

    def request(self, model: str, system: str, user: str) -> dict[str, Any]:
        return {
            "model": model,
            "max_tokens": 2048,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "temperature": 0.0,
        }

    def extract_text(self, payload: dict[str, Any]) -> str:
        content = payload.get("content") or []
        chunks = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        if chunks:
            return "\n".join(chunks)
        error = payload.get("error")
        raise ExtractionError(f"no text blocks in anthropic response ({error})")


class Extractor:
    """Calls the provider and returns a validated ``ExtractionResult``."""

    def __init__(
        self,
        *,
        api_key: str = "",
        api_keys: Any = None,
        model: str,
        base_url: str,
        limiter: RateLimiter,
        backend: str = "auto",
        timeout: float = 45.0,
        max_input_chars: int = 12_000,
        client: httpx.Client | None = None,
        store: Any | None = None,
        fallback_extractor: Any | None = None,
    ) -> None:
        raw_keys: list[str] = []
        if api_keys:
            if isinstance(api_keys, str):
                raw_keys.extend(re.split(r"[,;\s]+", api_keys.strip()))
            elif isinstance(api_keys, (list, tuple, set)):
                raw_keys.extend(list(api_keys))
            else:
                raw_keys.append(str(api_keys))
        if api_key:
            for part in re.split(r"[,;\s]+", api_key.strip()):
                if part and part not in raw_keys:
                    raw_keys.append(part)
        if not raw_keys:
            raise ExtractionError("An API key is required for model extraction")

        self.rotator = KeyRotator(raw_keys)
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.limiter = limiter
        self.timeout = timeout
        self.max_input_chars = max_input_chars
        self.store = store
        self.fallback_extractor = fallback_extractor
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)
        self._candidates = self._resolve_candidates(backend)
        self.calls = 0
        self._calls_lock = threading.Lock()

    @property
    def api_key(self) -> str:
        """Primary active key, for backward compatibility."""
        return self.rotator.primary_key

    def _resolve_candidates(self, backend: str) -> list[_Backend]:
        cached = None
        if backend == "auto" and self.store is not None:
            try:
                cached = self.store.get_meta(_BACKEND_META_KEY)
            except Exception:  # pragma: no cover - meta lookup is advisory
                cached = None
        chosen = cached if backend == "auto" and cached else backend
        if chosen == "interactions":
            return [_InteractionsBackend()]
        if chosen == "generate_content":
            return [_GenerateContentBackend()]
        _compat = (
            "openai", "groq", "nvidia", "nim", "openrouter",
            "mistral", "custom", "openai_compatible", "memo",
        )
        if chosen in _compat:
            return [_OpenAICompatibleBackend(name=chosen)]
        if chosen in ("anthropic", "claude"):
            return [_AnthropicBackend()]
        return [_InteractionsBackend(), _GenerateContentBackend()]

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Extractor:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _post(
        self, backend: _Backend, body: dict[str, Any], key: str | None = None
    ) -> httpx.Response:
        endpoint = backend.path(self.model)
        base = self.base_url.rstrip("/")
        if endpoint.startswith("/"):
            if base.endswith("/v1") and endpoint.startswith("/v1/"):
                url = f"{base}{endpoint[3:]}"
            elif base.endswith("/v1beta") and endpoint.startswith("/v1beta/"):
                url = f"{base}{endpoint[7:]}"
            elif (
                not base.endswith("/v1")
                and not base.endswith("/v1beta")
                and endpoint == "/chat/completions"
            ):
                url = f"{base}/v1{endpoint}"
            else:
                url = f"{base}{endpoint}"
        else:
            url = f"{base}/{endpoint}"
        active_key = key or self.rotator.get_key()
        return self._client.post(
            url,
            headers=backend.headers(active_key),
            json=body,
            timeout=self.timeout,
        )

    def extract(
        self,
        *,
        text: str,
        source_url: str,
        title: str = "",
        hints: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """One extraction. Raises on quota exhaustion or unusable output."""
        user = build_user_prompt(
            text=text[: self.max_input_chars], source_url=source_url, title=title
        )
        last_error: Exception | None = None
        max_key_attempts = min(len(self.rotator), 5) if len(self.rotator) > 1 else 1

        for key_attempt in range(max_key_attempts):
            current_key = self.rotator.get_key()
            key_had_rate_limit = False
            for index, backend in enumerate(self._candidates):
                req_body = backend.request(self.model, SYSTEM_PROMPT, user)
                day = self.limiter.acquire()
                with self._calls_lock:
                    self.calls += 1
                try:
                    response = self._post(backend, req_body, key=current_key)
                except httpx.RequestError as exc:
                    self.limiter.record(error=True, day=day)
                    last_error = ExtractionError(f"{backend.name}: transport error: {exc}")
                    self.rotator.mark_error(current_key)
                    continue

                if response.status_code == 429:
                    self.limiter.record(error=True, day=day)
                    delay = _parse_retry_delay(response)
                    self.rotator.mark_rate_limited(current_key, delay or 30.0)
                    key_had_rate_limit = True
                    log.warning(
                        "key_rate_limited",
                        key=f"...{current_key[-4:]}" if len(current_key) > 8 else "***",
                        attempt=key_attempt + 1,
                        of=max_key_attempts,
                        delay=delay,
                    )
                    if key_attempt + 1 < max_key_attempts:
                        break  # rotate to next key
                    self.limiter.penalise(delay or 30.0)
                    raise RateLimited(f"provider rate limit ({backend.name})", delay)

                if response.status_code in (400, 404) and index + 1 < len(self._candidates):
                    self.limiter.record(error=True, day=day)
                    # Unknown endpoint or unsupported field: try the other shape
                    # once rather than failing the whole run on a vendor change.
                    last_error = ExtractionError(
                        f"{backend.name}: HTTP {response.status_code}: {response.text[:200]}"
                    )
                    continue

                if response.status_code >= 400:
                    self.rotator.mark_error(current_key)
                    self.limiter.record(error=True, day=day)
                    last_error = ExtractionError(
                        f"{backend.name}: HTTP {response.status_code}: {response.text[:300]}"
                    )
                    continue

                raw = ""
                tokens = 0
                try:
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ExtractionError("provider response must be a JSON object")
                    raw = _strip_fence(backend.extract_text(payload))
                    tokens = int(
                        (payload.get("usageMetadata") or {}).get("totalTokenCount", 0)
                        or (payload.get("usage") or {}).get("total_tokens", 0)
                        or (
                            (payload.get("usage") or {}).get("input_tokens", 0)
                            + (payload.get("usage") or {}).get("output_tokens", 0)
                        )
                        or 0
                    )
                    decoded = json.loads(raw)
                    if not isinstance(decoded, dict) or any(
                        key not in decoded for key in EXTRACTION_JSON_SCHEMA["required"]
                    ):
                        raise ExtractionError(
                            "model JSON is missing required classification fields"
                        )
                    result = ExtractionResult.model_validate(decoded)
                    if result.is_vacancy and (not result.title or not result.institution):
                        raise ExtractionError("accepted vacancy is missing title or institution")
                    self.limiter.record(tokens=tokens, day=day)
                    self.rotator.mark_success(current_key, tokens=tokens)
                    self._remember_backend(backend.name)
                    return result
                except (QuotaExceeded, RateLimited):
                    raise
                except Exception as exc:
                    self.limiter.record(tokens=tokens, error=True, day=day)
                    if self.fallback_extractor is not None:
                        log.warning(
                            "model_extraction_failed_fallback_heuristic",
                            error=str(exc),
                            raw=raw[:200] if "raw" in locals() and isinstance(raw, str) else "",
                        )
                        fallback_hints = dict(hints or {})
                        fallback_hints["is_heuristic_fallback"] = True
                        res = self.fallback_extractor.extract(
                            text=text, source_url=source_url, title=title, hints=fallback_hints
                        )
                        res.is_heuristic_fallback = True
                        return ExtractionResult.model_validate(res)
                    if isinstance(exc, json.JSONDecodeError):
                        raise ExtractionError(f"model returned non-JSON: {exc}") from exc
                    if isinstance(exc, ExtractionError):
                        raise
                    raise ExtractionError(f"schema validation failed: {exc}") from exc

            if not key_had_rate_limit and last_error is None:
                break

        if self.fallback_extractor is not None:
            log.warning(
                "model_all_candidates_failed_fallback_heuristic",
                error=str(last_error or "no extraction backend succeeded"),
            )
            fallback_hints = dict(hints or {})
            fallback_hints["is_heuristic_fallback"] = True
            res = self.fallback_extractor.extract(
                text=text, source_url=source_url, title=title, hints=fallback_hints
            )
            res.is_heuristic_fallback = True
            return ExtractionResult.model_validate(res)

        raise last_error or ExtractionError("no extraction backend succeeded")

    def _remember_backend(self, name: str) -> None:
        if self.store is None or len(self._candidates) == 1:
            return
        try:
            if self.store.get_meta(_BACKEND_META_KEY) != name:
                self.store.set_meta(_BACKEND_META_KEY, name)
        except Exception as exc:  # pragma: no cover - advisory only
            log.debug("Failed to persist backend preference %s: %s", name, exc)


class NullExtractor:
    """Stand-in used by --dry-run and by tests. Never touches the network."""

    calls = 0

    def extract(
        self,
        *,
        text: str,
        source_url: str,
        title: str = "",
        hints: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        raise ExtractionError("extraction disabled (null backend)")

    def close(self) -> None:
        return None

    def __enter__(self) -> NullExtractor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def build_extractor(settings: Any, *, store: Any | None = None, prefs: Any | None = None) -> Any:
    """Construct the configured extractor across multiple LLM providers or rule-based heuristics."""
    backend = (getattr(settings, "extraction_backend", "auto") or "auto").lower()
    if backend == "null":
        return NullExtractor()

    provider = backend
    if backend == "auto":
        if getattr(settings, "groq_api_key", None):
            provider = "groq"
        elif getattr(settings, "nvidia_api_key", None):
            provider = "nvidia"
        elif getattr(settings, "openai_api_key", None):
            provider = "openai"
        elif getattr(settings, "anthropic_api_key", None):
            provider = "anthropic"
        elif getattr(settings, "openrouter_api_key", None):
            provider = "openrouter"
        elif getattr(settings, "mistral_api_key", None):
            provider = "mistral"
        elif getattr(settings, "gemini_api_key", None):
            provider = "gemini"
        elif getattr(settings, "memo_api_key", None):
            provider = "memo"
        elif getattr(settings, "custom_llm_api_key", None):
            provider = "custom"
        else:
            provider = "heuristic"

    if provider == "heuristic":
        from ..boards.config import load_preferences
        from .heuristic import HeuristicExtractor

        return HeuristicExtractor(prefs or load_preferences(settings.preferences_config))

    from ..boards.config import load_preferences
    from .heuristic import HeuristicExtractor

    pref_obj = prefs or (
        load_preferences(settings.preferences_config)
        if hasattr(settings, "preferences_config")
        else None
    )
    fallback_extractor = HeuristicExtractor(pref_obj)

    limiter = RateLimiter(
        requests_per_minute=settings.llm_requests_per_minute,
        requests_per_day=settings.llm_requests_per_day,
        safety_margin=settings.llm_daily_safety_margin,
        store=store,
    )

    if provider == "instructor":
        from .instructor_backend import InstructorExtractor

        return InstructorExtractor(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            limiter=limiter,
            max_input_chars=settings.llm_max_input_chars,
        )

    if provider == "groq":
        return Extractor(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            base_url=settings.groq_base_url,
            limiter=limiter,
            backend="groq",
            timeout=settings.llm_timeout_seconds,
            max_input_chars=settings.llm_max_input_chars,
            store=store,
            fallback_extractor=fallback_extractor,
        )

    if provider in ("nvidia", "nim"):
        return Extractor(
            api_key=settings.nvidia_api_key,
            model=settings.nvidia_model,
            base_url=settings.nvidia_base_url,
            limiter=limiter,
            backend="nvidia",
            timeout=settings.llm_timeout_seconds,
            max_input_chars=settings.llm_max_input_chars,
            store=store,
            fallback_extractor=fallback_extractor,
        )

    if provider == "openai":
        return Extractor(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            base_url=settings.openai_base_url,
            limiter=limiter,
            backend="openai",
            timeout=settings.llm_timeout_seconds,
            max_input_chars=settings.llm_max_input_chars,
            store=store,
            fallback_extractor=fallback_extractor,
        )

    if provider in ("anthropic", "claude"):
        return Extractor(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            base_url=settings.anthropic_base_url,
            limiter=limiter,
            backend="anthropic",
            timeout=settings.llm_timeout_seconds,
            max_input_chars=settings.llm_max_input_chars,
            store=store,
            fallback_extractor=fallback_extractor,
        )

    if provider == "openrouter":
        keys = (
            settings.get_openrouter_keys()
            if hasattr(settings, "get_openrouter_keys")
            else []
        )
        primary_key = keys[0] if keys else settings.openrouter_api_key
        return Extractor(
            api_key=primary_key,
            api_keys=keys or None,
            model=settings.openrouter_model,
            base_url=settings.openrouter_base_url,
            limiter=limiter,
            backend="openrouter",
            timeout=settings.llm_timeout_seconds,
            max_input_chars=settings.llm_max_input_chars,
            store=store,
            fallback_extractor=fallback_extractor,
        )

    if provider == "mistral":
        return Extractor(
            api_key=settings.mistral_api_key,
            model=settings.mistral_model,
            base_url=settings.mistral_base_url,
            limiter=limiter,
            backend="mistral",
            timeout=settings.llm_timeout_seconds,
            max_input_chars=settings.llm_max_input_chars,
            store=store,
            fallback_extractor=fallback_extractor,
        )

    if provider == "memo":
        if not settings.memo_base_url.strip() or not settings.memo_model.strip():
            raise ExtractionError(
                "memo requires explicit MEMO_BASE_URL and MEMO_MODEL for an "
                "OpenAI-compatible chat endpoint; custom/local defaults are not inherited"
            )
        return Extractor(
            api_key=settings.memo_api_key,
            model=settings.memo_model.strip(),
            base_url=settings.memo_base_url.strip(),
            limiter=limiter,
            backend="memo",
            timeout=settings.llm_timeout_seconds,
            max_input_chars=settings.llm_max_input_chars,
            store=store,
            fallback_extractor=fallback_extractor,
        )

    if provider == "custom":
        return Extractor(
            api_key=settings.custom_llm_api_key,
            model=settings.custom_llm_model,
            base_url=settings.custom_llm_base_url,
            limiter=limiter,
            backend="custom",
            timeout=settings.llm_timeout_seconds,
            max_input_chars=settings.llm_max_input_chars,
            store=store,
            fallback_extractor=fallback_extractor,
        )

    return Extractor(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        base_url=settings.gemini_base_url,
        limiter=limiter,
        backend=settings.extraction_backend,
        timeout=settings.llm_timeout_seconds,
        max_input_chars=settings.llm_max_input_chars,
        store=store,
        fallback_extractor=fallback_extractor,
    )


__all__ += ["QuotaExceeded"]
