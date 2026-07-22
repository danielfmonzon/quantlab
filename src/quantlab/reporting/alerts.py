"""Multi-channel alerting.

Channels:
* ConsoleChannel - always active; prints to stdout.
* FileChannel    - always active; appends one JSON object per line to
  ``reports/alerts/alerts.jsonl``.
* EmailChannel   - active ONLY when all of SMTP_HOST, SMTP_PORT, SMTP_USER,
  SMTP_PASS, ALERT_EMAIL_TO are set in the environment. TLS via
  ``smtplib.SMTP`` + ``starttls``. ``SMTP_PASS`` is never logged.

``dispatch`` delivers an alert to every channel and isolates failures: one
channel raising never blocks the others; each failure is logged (without
secrets) and reported back in the delivery results.
"""

from __future__ import annotations

import json
import os
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from quantlab.constants import PROJECT_ROOT
from quantlab.logging_setup import get_logger

log = get_logger("quantlab.alerts")

ALERTS_JSONL: Path = PROJECT_ROOT / "reports" / "alerts" / "alerts.jsonl"

_EMAIL_ENV_VARS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "ALERT_EMAIL_TO")


class Alert(BaseModel):
    """A single alert. ``level`` is one of INFO / WARNING / CRITICAL."""

    level: str
    title: str
    body: str
    source: str
    # The account/strategy label this alert belongs to, when it is account-scoped.
    # Persisted as a structured field so consumers attribute EXACTLY rather than
    # by substring-matching the title (where 'trend' also matches 'crypto_trend').
    strategy: str | None = None


class DeliveryResult(BaseModel):
    """Outcome of delivering one alert to one channel."""

    channel: str
    ok: bool
    error: str | None = None


class Channel(Protocol):
    name: str

    def send(self, alert: Alert) -> None: ...


class ConsoleChannel:
    """Print the alert to stdout."""

    name = "console"

    def send(self, alert: Alert) -> None:
        print(f"[ALERT/{alert.level}] {alert.title}\n  {alert.body}  (source: {alert.source})")


class FileChannel:
    """Append the alert as a JSON line to ``alerts.jsonl``.

    ``path`` is resolved at SEND time (not bound at import) so the test suite can
    redirect the whole alert log by monkeypatching :data:`ALERTS_JSONL`. Binding
    the module default into the signature would have made that redirect silently
    ineffective — which is how the 2026-07-22 test-pollution incident happened.
    """

    name = "file"

    def __init__(self, path: Path | None = None):
        self._path = path

    @property
    def path(self) -> Path:
        """The explicit path if one was injected, else the current production default."""
        return self._path if self._path is not None else ALERTS_JSONL

    def send(self, alert: Alert) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": alert.level,
            "title": alert.title,
            "body": alert.body,
            "source": alert.source,
            # Exact-attribution key: the account this alert belongs to (None for
            # alerts that are not account-scoped). Consumers MUST prefer this over
            # substring-matching the title.
            "strategy": alert.strategy,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


class EmailChannel:
    """Send the alert over SMTP+STARTTLS. Never logs the password."""

    name = "email"

    def __init__(self, host: str, port: int, user: str, password: str, to_addr: str):
        self._host = host
        self._port = port
        self._user = user
        self._password = password  # never logged
        self._to = to_addr

    @classmethod
    def from_env(cls) -> EmailChannel | None:
        """Build from the environment, or return None if not fully configured."""
        values = {name: os.environ.get(name) for name in _EMAIL_ENV_VARS}
        if not all(values.values()):
            return None
        return cls(
            host=str(values["SMTP_HOST"]),
            port=int(str(values["SMTP_PORT"])),
            user=str(values["SMTP_USER"]),
            password=str(values["SMTP_PASS"]),
            to_addr=str(values["ALERT_EMAIL_TO"]),
        )

    def send(self, alert: Alert) -> None:
        message = EmailMessage()
        message["Subject"] = f"[quantlab {alert.level}] {alert.title}"
        message["From"] = self._user
        message["To"] = self._to
        message.set_content(f"{alert.body}\n\nsource: {alert.source}")
        with smtplib.SMTP(self._host, self._port, timeout=30) as server:
            server.starttls()
            server.login(self._user, self._password)
            server.send_message(message)


def default_channels() -> list[Channel]:
    """Console + File always; Email only when fully configured via env."""
    channels: list[Channel] = [ConsoleChannel(), FileChannel()]
    email = EmailChannel.from_env()
    if email is not None:
        channels.append(email)
    return channels


def dispatch(alert: Alert, channels: list[Channel] | None = None) -> list[DeliveryResult]:
    """Deliver ``alert`` to every channel; isolate and log per-channel failures."""
    targets = channels if channels is not None else default_channels()
    results: list[DeliveryResult] = []
    for channel in targets:
        try:
            channel.send(alert)
            results.append(DeliveryResult(channel=channel.name, ok=True))
        except Exception as exc:  # noqa: BLE001 - one channel must not sink the rest
            log.warning("alert_channel_failed", channel=channel.name, error=str(exc))
            results.append(DeliveryResult(channel=channel.name, ok=False, error=str(exc)))
    return results


def send_test_alert() -> list[DeliveryResult]:
    """Dispatch a benign test alert through all active channels (for the CLI)."""
    alert = Alert(
        level="INFO",
        title="quantlab test alert",
        body="If you can see this, the alert channel is wired up correctly.",
        source="alerts.send_test_alert",
    )
    return dispatch(alert)


__all__ = [
    "Alert",
    "DeliveryResult",
    "Channel",
    "ConsoleChannel",
    "FileChannel",
    "EmailChannel",
    "default_channels",
    "dispatch",
    "send_test_alert",
    "ALERTS_JSONL",
]
