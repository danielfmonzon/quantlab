"""Configuration for quantlab.

Loads secret keys from the environment (via a local ``.env`` in development) and
structured configuration from ``config/settings.yaml`` and ``config/universe.yaml``.

Safety gate: ``ALPACA_BASE_URL`` may only point at the Alpaca *paper* trading
endpoint. Any attempt to configure a live endpoint raises :class:`ConfigError`.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from quantlab.constants import (
    ALPACA_LIVE_HOST,
    ALPACA_PAPER_BASE_URL,
    PROJECT_ROOT,
    SETTINGS_YAML,
    UNIVERSE_YAML,
)


class ConfigError(Exception):
    """Raised when configuration is missing or violates a safety constraint."""


def _is_live_alpaca_url(url: str) -> bool:
    """Return True if ``url`` targets the Alpaca live-trading host.

    The live host is ``api.alpaca.markets``; the permitted paper host is
    ``paper-api.alpaca.markets``. We reject any URL containing the live host
    substring unless it is actually the ``paper-`` prefixed variant.
    """
    return ALPACA_LIVE_HOST in url and f"paper-{ALPACA_LIVE_HOST}" not in url


class Settings(BaseSettings):
    """Secret keys and endpoints loaded from the environment / ``.env``.

    All fields are optional at load time so the package can be imported without
    credentials present. Use :meth:`require_keys` to assert presence at the point
    of use.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    TIINGO_API_KEY: str | None = None
    ALPACA_API_KEY: str | None = None
    ALPACA_SECRET_KEY: str | None = None
    ALPACA_BASE_URL: str = ALPACA_PAPER_BASE_URL

    @field_validator("ALPACA_BASE_URL")
    @classmethod
    def _forbid_live_endpoint(cls, value: str) -> str:
        if _is_live_alpaca_url(value):
            raise ConfigError(
                "ALPACA_BASE_URL points at a live trading endpoint "
                f"({value!r}). Live trading is architecturally disabled in "
                f"quantlab; only the paper endpoint {ALPACA_PAPER_BASE_URL!r} "
                "is permitted."
            )
        return value

    def require_keys(self, *names: str) -> None:
        """Raise :class:`ConfigError` if any named key is unset/empty.

        Example: ``settings.require_keys("TIINGO_API_KEY", "ALPACA_API_KEY")``.
        """
        missing = [name for name in names if not getattr(self, name, None)]
        if missing:
            raise ConfigError(
                "Missing required configuration key(s): " + ", ".join(missing)
            )


class ProjectSettings(BaseModel):
    """Validated model of ``config/settings.yaml``."""

    project_name: str
    timezone: str = "America/New_York"
    data_dir: str
    reports_dir: str
    log_level: str = "INFO"


class ETF(BaseModel):
    """A single universe entry."""

    symbol: str
    asset_class: str
    description: str


class Universe(BaseModel):
    """Validated model of ``config/universe.yaml`` with duplicate detection."""

    etfs: list[ETF] = Field(default_factory=list)

    @model_validator(mode="after")
    def _reject_duplicate_symbols(self) -> Universe:
        seen: set[str] = set()
        dupes: list[str] = []
        for etf in self.etfs:
            if etf.symbol in seen:
                dupes.append(etf.symbol)
            seen.add(etf.symbol)
        if dupes:
            raise ConfigError(
                "Duplicate symbol(s) in universe.yaml: " + ", ".join(sorted(set(dupes)))
            )
        return self

    @property
    def symbols(self) -> list[str]:
        return [etf.symbol for etf in self.etfs]


def _read_yaml(path: Path) -> object:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_settings(path: Path = SETTINGS_YAML) -> ProjectSettings:
    """Load and validate ``config/settings.yaml``."""
    raw = _read_yaml(path)
    if not isinstance(raw, dict):
        raise ConfigError(f"settings.yaml must be a mapping, got {type(raw).__name__}")
    return ProjectSettings(**raw)


def load_universe(path: Path = UNIVERSE_YAML) -> Universe:
    """Load and validate ``config/universe.yaml``."""
    raw = _read_yaml(path)
    if not isinstance(raw, list):
        raise ConfigError(f"universe.yaml must be a list, got {type(raw).__name__}")
    return Universe(etfs=[ETF(**entry) for entry in raw])


def get_settings() -> Settings:
    """Return the environment-backed :class:`Settings`."""
    return Settings()


__all__ = [
    "PROJECT_ROOT",
    "ConfigError",
    "ETF",
    "ProjectSettings",
    "Settings",
    "Universe",
    "get_settings",
    "load_settings",
    "load_universe",
]
