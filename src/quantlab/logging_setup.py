"""structlog configuration for quantlab.

Emits JSON log lines to stdout and to a rotating file at
``reports/logs/quantlab.jsonl``. Every entry carries a UTC ISO ``timestamp``,
``level``, logger ``name`` (the ``logger`` key), and ``event``.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Any

import structlog

from quantlab.constants import PROJECT_ROOT

_DEFAULT_LOG_PATH: Path = PROJECT_ROOT / "reports" / "logs" / "quantlab.jsonl"
_configured: bool = False


def _shared_processors() -> list[structlog.typing.Processor]:
    """Processors shared by the stdlib formatter and structlog itself."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def configure_logging(
    level: str = "INFO",
    log_file: Path = _DEFAULT_LOG_PATH,
) -> None:
    """Configure structlog + stdlib logging. Idempotent.

    Routes structlog records through the stdlib logging machinery so a single
    ``ProcessorFormatter`` renders JSON for both the stdout stream handler and
    the rotating file handler.
    """
    global _configured

    log_file.parent.mkdir(parents=True, exist_ok=True)

    shared = _shared_processors()

    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        # ``foreign_pre_chain`` runs on records that did NOT originate from
        # structlog (e.g. plain stdlib logging), so they gain the same keys.
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    # Replace any handlers we installed on a prior call to keep this idempotent.
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)
    root.setLevel(level.upper())

    _configured = True


def get_logger(name: str, **initial_values: Any) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger, configuring logging on first use."""
    if not _configured:
        configure_logging()
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    if initial_values:
        logger = logger.bind(**initial_values)
    return logger


__all__ = ["configure_logging", "get_logger"]
