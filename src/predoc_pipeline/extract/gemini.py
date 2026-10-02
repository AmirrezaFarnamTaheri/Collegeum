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
import re
from dataclasses import dataclass
from typing import Any

import httpx

from ..core.ratelimit import QuotaExceeded, RateLimiter, quota_day
from ..models import EXTRACTION_JSON_SCHEMA, ExtractionResult
from .prompt import SYSTEM_PROMPT, build_user_prompt

__all__ = [
    "ExtractionError",
    "RateLimited",
    "Extractor",
    "build_extractor",
    "NullExtractor",
]

_BACKEND_META_KEY = "extraction_backend_resolved"
_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class ExtractionError(RuntimeError):
    """The provider could not be used, or returned something unusable."""


class RateLimited(ExtractionError):
    """The provider refused the request for quota reasons."""

    def __init__(self, message: str, retry_after: float = 0.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _strip_fence(text: str) -> str:
    """Remove ```json fences some models still emit around structured output."""
    return _JSON_FENCE.sub("", text or "").strip()


def _parse_retry_delay(response: httpx.Response) -> float:
    """Seconds to wait, preferring the provider's own instruction."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    try:
        payload = response.json()
    except Exception:
        return 0.0
    for detail in (payload.get("error", {}) or {}).get("details", []) or []:
        delay = detail.get("retryDelay")
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return float(delay[:-1])
            except ValueError:
                continue
    return 0.0


@dataclass(slots=True)
class _Backend:
    name: str

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


class Extractor:
    """Calls the provider and returns a validated ``ExtractionResult``."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        limiter: RateLimiter,
        backend: str = "auto",
        timeout: float = 45.0,
        max_input_chars: int = 12_000,
        client: httpx.Client | None = None,
        store: Any | None = None,
    ) -> None:
        if not api_key:
            raise ExtractionError("GEMINI_API_KEY is required for extraction")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.limiter = limiter
        self.timeout = timeout
        self.max_input_chars = max_input_chars
        self.store = store
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)
        self._candidates = self._resolve_candidates(backend)
        self.calls = 0

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
        return [_InteractionsBackend(), _GenerateContentBackend()]

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Extractor:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _post(self, backend: _Backend, body: dict[str, Any]) -> httpx.Response:
        return self._client.post(
            f"{self.base_url}{backend.path(self.model)}",
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
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
        day = quota_day()
        self.limiter.acquire(day=day)

        user = build_user_prompt(
            text=text[: self.max_input_chars], source_url=source_url, title=title
        )
        last_error: Exception | None = None

        for index, backend in enumerate(self._candidates):
            try:
                response = self._post(backend, backend.request(self.model, SYSTEM_PROMPT, user))
            except httpx.RequestError as exc:
                last_error = ExtractionError(f"{backend.name}: transport error: {exc}")
                continue

            if response.status_code == 429:
                delay = _parse_retry_delay(response)
                self.limiter.penalise(delay or 30.0)
                self.limiter.record(error=True, day=day)
                raise RateLimited(f"provider rate limit ({backend.name})", delay)

            if response.status_code in (400, 404) and index + 1 < len(self._candidates):
                # Unknown endpoint or unsupported field: try the other shape
                # once rather than failing the whole run on a vendor change.
                last_error = ExtractionError(
                    f"{backend.name}: HTTP {response.status_code}: {response.text[:200]}"
                )
                continue

            if response.status_code >= 400:
                self.limiter.record(error=True, day=day)
                raise ExtractionError(
                    f"{backend.name}: HTTP {response.status_code}: {response.text[:300]}"
                )

            payload = response.json()
            raw = _strip_fence(backend.extract_text(payload))
            tokens = int(
                (payload.get("usageMetadata") or {}).get("totalTokenCount", 0) or 0
            )
            self.limiter.record(tokens=tokens, day=day)
            self.calls += 1
            self._remember_backend(backend.name)

            try:
                return ExtractionResult.model_validate(json.loads(raw))
            except json.JSONDecodeError as exc:
                raise ExtractionError(f"model returned non-JSON: {exc}") from exc
            except Exception as exc:
                raise ExtractionError(f"schema validation failed: {exc}") from exc

        raise last_error or ExtractionError("no extraction backend succeeded")

    def _remember_backend(self, name: str) -> None:
        if self.store is None or len(self._candidates) == 1:
            return
        try:
            if self.store.get_meta(_BACKEND_META_KEY) != name:
                self.store.set_meta(_BACKEND_META_KEY, name)
        except Exception:  # pragma: no cover - advisory only
            pass


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
    """Construct the configured extractor.

    ``instructor`` is imported lazily and only when explicitly requested, so
    the default install does not pay for it.

    With no Gemini key (the default, and the only option where Gemini is not
    reachable) ``auto`` means the rule-based heuristic backend, not the null
    backend -- the null backend rejects every item, so the pipeline would run
    daily and publish nothing.
    """
    if settings.extraction_backend == "null":
        return NullExtractor()
    if settings.extraction_backend == "heuristic" or (
        settings.extraction_backend == "auto" and not settings.gemini_api_key
    ):
        from ..boards.config import load_preferences
        from .heuristic import HeuristicExtractor

        return HeuristicExtractor(prefs or load_preferences(settings.preferences_config))

    limiter = RateLimiter(
        requests_per_minute=settings.llm_requests_per_minute,
        requests_per_day=settings.llm_requests_per_day,
        safety_margin=settings.llm_daily_safety_margin,
        store=store,
    )

    if settings.extraction_backend == "instructor":
        from .instructor_backend import InstructorExtractor

        return InstructorExtractor(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            limiter=limiter,
            max_input_chars=settings.llm_max_input_chars,
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
    )


__all__ += ["QuotaExceeded"]
