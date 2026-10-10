"""Optional `instructor` + google-genai backend.

Not the default. It exists so that anyone already standardised on instructor
can keep their tooling, and so the REST backends have something to be compared
against. Imports are local to the constructor: `pip install predoc-pipeline`
must not pull instructor in for users who never select it.
"""

from __future__ import annotations

import threading
from typing import Any

from ..models import ExtractionResult
from .prompt import SYSTEM_PROMPT, build_user_prompt


class InstructorExtractor:
    """Thin adapter presenting the same surface as `Extractor`."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        limiter: Any,
        max_input_chars: int = 12_000,
    ) -> None:
        try:
            import instructor  # noqa: F401
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - optional path
            raise RuntimeError(
                "extraction_backend='instructor' needs the 'llm-instructor' extra: "
                "pip install 'predoc-pipeline[llm-instructor]'"
            ) from exc

        import instructor as _instructor

        self.model = model
        self.limiter = limiter
        self.max_input_chars = max_input_chars
        self.calls = 0
        self._calls_lock = threading.Lock()
        self._genai = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
        )
        self._client = _instructor.from_genai(self._genai)

    def extract(
        self,
        *,
        text: str,
        source_url: str,
        title: str = "",
        hints: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        from tenacity import Retrying, stop_after_attempt

        day = self.limiter.acquire()
        with self._calls_lock:
            self.calls += 1
        try:
            result = self._client.chat.completions.create(
                model=self.model,
                response_model=ExtractionResult,
                # Explicit total-attempt bound, independent of the SDK's
                # integer retry-count conventions. Every call is reserved.
                max_retries=Retrying(stop=stop_after_attempt(1), reraise=True),
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": build_user_prompt(
                            text=text[: self.max_input_chars],
                            source_url=source_url,
                            title=title,
                        ),
                    },
                ],
            )
            result = ExtractionResult.model_validate(result)
        except Exception:
            self.limiter.record(error=True, day=day)
            raise
        self.limiter.record(day=day)
        return result

    def close(self) -> None:
        self._genai.close()

    def __enter__(self) -> InstructorExtractor:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
