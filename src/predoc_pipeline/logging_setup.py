"""Structured logging. JSON in CI, human-readable on a terminal.

Both logging worlds render through the *same* renderer. structlog records and
plain ``logging.getLogger(__name__)`` records used to be written in two
different formats into the same file: structlog wrote JSON, stdlib wrote bare
text through ``basicConfig``. A CI log parser then saw half the lines without
a level or a timestamp. Both paths now go through one renderer, so a run log
has one shape.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, cast

import structlog
from structlog.typing import EventDict, FilteringBoundLogger

_CONFIGURED = False

#: The one renderer both logging worlds use. JSONRenderer in CI, the console
#: renderer on a terminal.
_RENDERER: Any = structlog.processors.JSONRenderer()

__all__ = ["configure", "get_logger", "render_record"]


def _timestamp(epoch: float) -> str:
    """The same ISO-UTC shape structlog's TimeStamper(fmt="iso") produces."""
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _render_event(logger: Any, method_name: str, event_dict: EventDict) -> str:
    # ConsoleRenderer needs the original exception tuple for its traceback
    # formatter. JSON needs a serializable traceback, not exc_info=True or a
    # tuple containing an opaque traceback object.
    if not isinstance(_RENDERER, structlog.dev.ConsoleRenderer):
        structlog.processors.format_exc_info(logger, method_name, event_dict)
    return cast(str, _RENDERER(logger, method_name, event_dict))


def render_record(record: logging.LogRecord) -> str:
    """Render one stdlib record exactly as a structlog record is rendered.

    Keeping this in one place is the point: the two paths differ only in how
    the event dict is built, not in how it is written out.
    """
    event_dict: dict[str, Any] = {
        "event": record.getMessage(),
        "level": record.levelname.lower(),
        "timestamp": _timestamp(record.created),
    }
    if record.exc_info:
        event_dict["exc_info"] = record.exc_info
    elif record.exc_text:
        event_dict["exception"] = record.exc_text
    if record.stack_info:
        event_dict["stack"] = record.stack_info
    try:
        return _render_event(None, record.levelname.lower(), event_dict.copy())
    except Exception:  # pragma: no cover - a renderer must never break logging
        # A renderer that insists on a real logger object still gets a
        # readable line, which is what a log reader needs.
        structlog.processors.format_exc_info(None, record.levelname.lower(), event_dict)
        return json.dumps(event_dict, default=str, ensure_ascii=False)


class _RenderedHandler(logging.Handler):
    """Send stdlib records through the shared renderer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # sys.stderr is resolved now, not at construction time: a test
            # harness may swap it between runs.
            stream = sys.stderr
            stream.write(render_record(record) + "\n")
            stream.flush()
        except Exception:  # pragma: no cover - logging must never raise
            self.handleError(record)


def configure(level: int = logging.INFO) -> None:
    """Idempotent. Safe to call from every CLI entry point."""
    global _CONFIGURED, _RENDERER
    if _CONFIGURED:
        return
    _RENDERER = (
        structlog.dev.ConsoleRenderer()
        if sys.stderr.isatty()
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            _render_event,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    root = logging.getLogger()
    # The CLI owns console output, but other destinations (files and test
    # harness capture handlers) must remain attached.
    console_streams = (sys.stderr, sys.stdout, sys.__stderr__, sys.__stdout__)
    for existing in root.handlers[:]:
        if (
            isinstance(existing, logging.StreamHandler)
            and not isinstance(existing, logging.FileHandler)
            and any(existing.stream is stream for stream in console_streams)
            and not getattr(existing, "_predoc_rendered", False)
        ):
            root.removeHandler(existing)
            existing.close()
    if not any(getattr(handler, "_predoc_rendered", False) for handler in root.handlers):
        handler = _RenderedHandler()
        handler._predoc_rendered = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    root.setLevel(level)
    _CONFIGURED = True


def get_logger(name: str) -> FilteringBoundLogger:
    return cast(FilteringBoundLogger, structlog.get_logger(name))
