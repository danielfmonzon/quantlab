"""Tests for quantlab.logging_setup."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

from quantlab.logging_setup import configure_logging, get_logger


def test_get_logger_returns_logger(tmp_path: Path) -> None:
    configure_logging(log_file=tmp_path / "logs" / "quantlab.jsonl")
    logger = get_logger("quantlab.test")
    assert hasattr(logger, "info")
    assert hasattr(logger, "bind")


def test_log_call_produces_valid_json(tmp_path: Path) -> None:
    configure_logging(level="INFO", log_file=tmp_path / "logs" / "quantlab.jsonl")

    # Capture the stdout stream handler's output.
    buffer = io.StringIO()
    root = logging.getLogger()
    capture = logging.StreamHandler(buffer)
    # Reuse the JSON formatter already installed on an existing handler.
    capture.setFormatter(root.handlers[0].formatter)
    root.addHandler(capture)
    try:
        logger = get_logger("quantlab.test")
        logger.info("unit_test_event", extra_field=42)
    finally:
        root.removeHandler(capture)

    line = buffer.getvalue().strip().splitlines()[-1]
    payload = json.loads(line)  # raises if not valid JSON

    assert payload["event"] == "unit_test_event"
    assert payload["level"] == "info"
    assert payload["logger"] == "quantlab.test"
    assert "timestamp" in payload
    # ISO UTC timestamps end with 'Z' when rendered by structlog.
    assert payload["timestamp"].endswith("Z")
    assert payload["extra_field"] == 42


def test_log_written_to_file(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "quantlab.jsonl"
    configure_logging(log_file=log_file)
    logger = get_logger("quantlab.filetest")
    logger.info("file_event")

    for handler in logging.getLogger().handlers:
        handler.flush()

    assert log_file.exists()
    lines = [ln for ln in log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    payloads = [json.loads(ln) for ln in lines]
    assert any(p["event"] == "file_event" for p in payloads)
