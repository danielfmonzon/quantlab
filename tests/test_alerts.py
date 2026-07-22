"""Alerting tests: channel activation, dispatch isolation, no secret leakage."""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import MagicMock, patch

from quantlab.reporting.alerts import (
    Alert,
    ConsoleChannel,
    EmailChannel,
    FileChannel,
    default_channels,
    dispatch,
)

_ALERT = Alert(level="CRITICAL", title="t", body="b", source="test")

_EMAIL_ENV = {
    "SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587",
    "SMTP_USER": "alerts@example.com", "SMTP_PASS": "s3cr3t-pw",
    "ALERT_EMAIL_TO": "you@example.com",
}


def test_console_and_file_always_active(monkeypatch) -> None:
    monkeypatch.delenv("SMTP_HOST", raising=False)
    channels = default_channels()
    names = [c.name for c in channels]
    assert names == ["console", "file"]  # no email without env


def test_email_channel_inactive_without_env(monkeypatch) -> None:
    for key in _EMAIL_ENV:
        monkeypatch.delenv(key, raising=False)
    assert EmailChannel.from_env() is None


def test_email_channel_active_with_all_env(monkeypatch) -> None:
    for key, val in _EMAIL_ENV.items():
        monkeypatch.setenv(key, val)
    assert EmailChannel.from_env() is not None
    assert "email" in [c.name for c in default_channels()]


def test_dispatch_writes_jsonl_to_file_channel(tmp_path) -> None:
    path = tmp_path / "alerts.jsonl"
    results = dispatch(_ALERT, channels=[FileChannel(path)])
    assert results[0].ok
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["level"] == "CRITICAL" and record["title"] == "t"


def test_email_uses_starttls_and_never_logs_password(monkeypatch, caplog) -> None:
    for key, val in _EMAIL_ENV.items():
        monkeypatch.setenv(key, val)
    channel = EmailChannel.from_env()
    assert channel is not None

    smtp_instance = MagicMock()
    smtp_ctx = MagicMock()
    smtp_ctx.__enter__.return_value = smtp_instance
    with patch("quantlab.reporting.alerts.smtplib.SMTP", return_value=smtp_ctx) as smtp_cls:
        with caplog.at_level(logging.DEBUG):
            dispatch(_ALERT, channels=[channel])

    smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=30)
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("alerts@example.com", "s3cr3t-pw")
    smtp_instance.send_message.assert_called_once()
    # The password must never appear in any log record.
    assert "s3cr3t-pw" not in caplog.text


def test_one_channel_failing_does_not_block_the_others(tmp_path) -> None:
    path = tmp_path / "alerts.jsonl"

    class BoomChannel:
        name = "boom"

        def send(self, alert: Any) -> None:
            raise RuntimeError("channel exploded")

    results = dispatch(_ALERT, channels=[BoomChannel(), FileChannel(path)])
    by_name = {r.channel: r for r in results}
    assert by_name["boom"].ok is False
    assert by_name["file"].ok is True
    # The file channel still wrote despite the boom channel raising first.
    assert path.exists() and path.read_text(encoding="utf-8").strip()


def test_console_channel_send_does_not_raise(capsys) -> None:
    ConsoleChannel().send(_ALERT)
    assert "ALERT/CRITICAL" in capsys.readouterr().out


# --------------------------------------------------------------------------
# Alert-log isolation (2026-07-22 test-pollution incident)
# --------------------------------------------------------------------------


def test_dispatch_never_touches_the_production_alert_log(tmp_path) -> None:
    """The autouse conftest fixture must keep the real alerts.jsonl untouched.

    This is the regression guard for the incident where the suite appended ~50
    fixture alerts to reports/alerts/alerts.jsonl, inflating the weekly review's
    ops stats. It reads the TRUE production path from PROJECT_ROOT rather than
    the (redirected) module constant, so it fails if the redirect ever breaks.
    """
    from quantlab.constants import PROJECT_ROOT

    production = PROJECT_ROOT / "reports" / "alerts" / "alerts.jsonl"
    before = (
        (production.stat().st_size, production.stat().st_mtime_ns)
        if production.exists() else None
    )

    dispatch(Alert(level="WARNING", title="isolation probe",
                   body="must not reach production", source="tests"))

    after = (
        (production.stat().st_size, production.stat().st_mtime_ns)
        if production.exists() else None
    )
    assert after == before, "a test wrote to the production alerts.jsonl"


def test_redirected_channel_actually_received_the_alert(isolate_alert_log) -> None:
    # The flip side: isolation must not silently swallow alerts.
    dispatch(Alert(level="INFO", title="redirect probe", body="b", source="tests"))
    assert isolate_alert_log.exists()
    records = [json.loads(line) for line in
               isolate_alert_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [r["title"] for r in records] == ["redirect probe"]


def test_file_channel_persists_the_strategy_field(tmp_path) -> None:
    path = tmp_path / "alerts.jsonl"
    FileChannel(path).send(
        Alert(level="INFO", title="paper trend: ok", body="b",
              source="paper.runner", strategy="trend")
    )
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert record["strategy"] == "trend"


def test_file_channel_defaults_to_the_live_constant_at_send_time(
    tmp_path, monkeypatch
) -> None:
    # Resolution must be late-bound, or the conftest redirect cannot work.
    from quantlab.reporting import alerts as alerts_module

    target = tmp_path / "late" / "alerts.jsonl"
    monkeypatch.setattr(alerts_module, "ALERTS_JSONL", target)
    channel = FileChannel()  # constructed BEFORE... nothing; path resolves on send
    channel.send(Alert(level="INFO", title="t", body="b", source="s"))
    assert target.exists()
