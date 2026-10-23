"""Regression coverage for the CLI's shared stdlib/structlog output."""

from __future__ import annotations

import io
import json
import logging
import sys

import pytest
import structlog

from predoc_pipeline import logging_setup


class _Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture(autouse=True)
def isolated_logging(monkeypatch):
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_structlog = structlog.get_config()
    root.handlers = []
    monkeypatch.setattr(logging_setup, "_CONFIGURED", False)
    monkeypatch.setattr(logging_setup, "_RENDERER", structlog.processors.JSONRenderer())
    try:
        yield
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
            handler.close()
        root.handlers = saved_handlers
        root.setLevel(saved_level)
        structlog.configure(**saved_structlog)


@pytest.mark.parametrize("logger_kind", ["stdlib", "structlog"])
@pytest.mark.parametrize("terminal", [False, True])
def test_exception_logs_retain_tracebacks(monkeypatch, logger_kind, terminal):
    stream = _Terminal() if terminal else io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    logging_setup.configure()
    logger = (
        logging.getLogger(__name__)
        if logger_kind == "stdlib"
        else logging_setup.get_logger(__name__)
    )

    try:
        raise ValueError("invalid listing")
    except ValueError:
        logger.exception("extraction failed")

    output = stream.getvalue()
    if terminal:
        assert "ValueError" in output
        assert "invalid listing" in output
        assert "test_exception_logs_retain_tracebacks" in output
    else:
        payload = json.loads(output)
        assert payload["event"] == "extraction failed"
        assert "exc_info" not in payload
        assert "Traceback (most recent call last)" in payload["exception"]
        assert "ValueError: invalid listing" in payload["exception"]


def test_deferred_stdlib_record_preserves_its_console_traceback(monkeypatch):
    monkeypatch.setattr(sys, "stderr", _Terminal())
    logging_setup.configure()
    try:
        raise ValueError("queued failure")
    except ValueError:
        record = logging.LogRecord(
            __name__, logging.ERROR, __file__, 1, "failed earlier", (), sys.exc_info()
        )

    # A queued record is rendered after leaving the exception handler.
    output = logging_setup.render_record(record)
    assert "ValueError" in output
    assert "queued failure" in output
    assert "test_deferred_stdlib_record_preserves_its_console_traceback" in output


@pytest.mark.parametrize("logger_kind", ["stdlib", "structlog"])
def test_stack_information_is_preserved_in_json(monkeypatch, logger_kind):
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    logging_setup.configure()
    logger = (
        logging.getLogger(__name__)
        if logger_kind == "stdlib"
        else logging_setup.get_logger(__name__)
    )
    logger.info("trace this call", stack_info=True)

    payload = json.loads(stream.getvalue())
    assert "Stack (most recent call last)" in payload["stack"]
    assert "test_stack_information_is_preserved_in_json" in payload["stack"]


@pytest.mark.parametrize("console_name", ["stdout", "stderr"])
def test_existing_console_handler_does_not_duplicate_output(monkeypatch, console_name):
    output = io.StringIO()
    errors = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr(sys, "stderr", errors)
    root = logging.getLogger()
    plain_handler = logging.StreamHandler(getattr(sys, console_name))
    root.addHandler(plain_handler)

    logging_setup.configure()
    logging_setup.configure()
    logging.getLogger(__name__).info("one record")

    assert plain_handler not in root.handlers
    assert output.getvalue() == ""
    lines = errors.getvalue().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "one record"
    assert sum(getattr(handler, "_predoc_rendered", False) for handler in root.handlers) == 1


def test_non_console_file_and_capture_handlers_are_preserved(monkeypatch, tmp_path):
    console = io.StringIO()
    capture = io.StringIO()
    monkeypatch.setattr(sys, "stderr", console)
    file_path = tmp_path / "application.log"
    file_handler = logging.FileHandler(file_path)
    capture_handler = logging.StreamHandler(capture)
    root = logging.getLogger()
    root.addHandler(file_handler)
    root.addHandler(capture_handler)

    logging_setup.configure()
    logging.getLogger(__name__).info("keep other destinations")

    assert file_handler in root.handlers
    assert capture_handler in root.handlers
    assert file_path.read_text() == "keep other destinations\n"
    assert capture.getvalue() == "keep other destinations\n"
    assert json.loads(console.getvalue())["event"] == "keep other destinations"
