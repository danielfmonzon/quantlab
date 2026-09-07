"""Configuration for quantlab.

Loads secret keys from the environment (via a local ``.env`` in development) and
structured configuration from ``config/settings.yaml`` and ``config/universe.yaml``.

Safety gate: ``ALPACA_BASE_URL`` may only point at the Alpaca *paper* trading
endpoint. Any attempt to configure a live endpoint raises :class:`ConfigError`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from quantlab.constants import (
    ALPACA_LIVE_HOST,
    ALPACA_PAPER_BASE_URL,
    CRYPTO_UNIVERSE_YAML,
    PROJECT_ROOT,
    SETTINGS_YAML,
    UNIVERSE_YAML,
)
from quantlab.logging_setup import get_logger

log = get_logger("quantlab.config")


class ConfigError(Exception):
    """Raised when configuration is missing or violates a safety constraint."""


def _is_live_alpaca_url(url: str) -> bool:
    """Return True if ``url`` targets the Alpaca live-trading host.

    The live host is ``api.alpaca.markets``; the permitted paper host is
    ``paper-api.alpaca.markets``. We reject any URL containing the live host
    substring unless it is actually the ``paper-`` prefixed variant.
    """
    return ALPACA_LIVE_HOST in url and f"paper-{ALPACA_LIVE_HOST}" not in url


# Overrides where the env file is read from (PROP-13). It must be a REAL environment
# variable -- systemd sets it with `Environment=`, a shell with `export` -- because it is
# what tells the process where to find the env file, so it cannot itself live in one.
ENV_FILE_VAR = "QUANTLAB_ENV_FILE"


def env_file_path() -> Path:
    """Where this process reads its ``.env`` from.

    ANCHORED TO THE REPO ROOT BY DEFAULT, and that default is load-bearing rather than
    incidental: a RELATIVE path here never resolves under a scheduler that supplies no
    working directory, and the failure is silent in the worst direction. The env-secret
    half of the published-bytes gate treats a missing file as "nothing to search for" and
    PASSES, so a gate that should be looking for secret prefixes quietly looks for none.
    See `glassbox.verify_dist.DEFAULT_ENV_PATH` for the incident that established the
    anchoring rule and `glassbox.snapshot.DEFAULT_REPORT_DIR` for the one that preceded it.

    The override exists for the migration (PROP-13). On the VPS the env file is deployed
    outside the checkout on some layouts and inside it on others, and pinning the path to
    `PROJECT_ROOT` in two separate modules made that a code change rather than a
    deployment one. Resolved at CALL time, never captured at import, so a test or a unit
    file can set it without reloading the module.
    """
    override = os.environ.get(ENV_FILE_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    return PROJECT_ROOT / ".env"


def env_file_is_group_or_world_readable(path: Path | None = None) -> bool:
    """Whether the env file's POSIX mode lets anyone but its owner read it (PROP-13).

    Reported, never enforced: refusing to start because of a file mode would take the
    trading path down over a permissions nit, and the failure this guards against is
    disclosure, not corruption. Always False on Windows, where the mode bits do not carry
    this meaning and reading them would produce a warning nobody can act on.
    """
    target = path if path is not None else env_file_path()
    if os.name == "nt":
        return False
    try:
        return bool(target.stat().st_mode & 0o077)
    except OSError:
        return False


class Settings(BaseSettings):
    """Secret keys and endpoints loaded from the environment / ``.env``.

    All fields are optional at load time so the package can be imported without
    credentials present. Use :meth:`require_keys` to assert presence at the point
    of use.
    """

    # ABSOLUTE, not ".env". A relative path is resolved against the CWD, and under a
    # scheduler that supplies none the CWD is not the checkout -- so this silently read
    # nothing and only `load_env_file` (called explicitly at CLI startup) was doing the
    # work. Resolved once at import: `QUANTLAB_ENV_FILE` is a real environment variable
    # and is therefore already set by the time this module loads.
    model_config = SettingsConfigDict(
        env_file=str(env_file_path()),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    TIINGO_API_KEY: str | None = None
    ALPACA_API_KEY: str | None = None
    ALPACA_SECRET_KEY: str | None = None
    # Dedicated paper account for the trend strategy (fully isolated from
    # voltarget's ALPACA_API_KEY/SECRET). Optional until trend is traded.
    ALPACA_TREND_API_KEY: str | None = None
    ALPACA_TREND_SECRET_KEY: str | None = None
    # Dedicated, isolated paper accounts for the two crypto strategies. Optional
    # until crypto is traded; the same paper endpoint serves crypto and equities.
    ALPACA_CRYPTO_TREND_API_KEY: str | None = None
    ALPACA_CRYPTO_TREND_SECRET_KEY: str | None = None
    ALPACA_CRYPTO_VOLTARGET_API_KEY: str | None = None
    ALPACA_CRYPTO_VOLTARGET_SECRET_KEY: str | None = None
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


def load_crypto_universe(path: Path = CRYPTO_UNIVERSE_YAML) -> Universe:
    """Load and validate ``config/crypto_universe.yaml`` (same schema as equities).

    Kept separate from :func:`load_universe` so crypto symbols never enter the
    equity ingest/validate/paper default symbol set.
    """
    raw = _read_yaml(path)
    if not isinstance(raw, list):
        raise ConfigError(f"crypto_universe.yaml must be a list, got {type(raw).__name__}")
    return Universe(etfs=[ETF(**entry) for entry in raw])


def get_settings() -> Settings:
    """Return the environment-backed :class:`Settings`."""
    return Settings()


@dataclass(frozen=True)
class AccountCreds:
    """Resolved credentials for one strategy's dedicated paper account."""

    api_key: str
    secret_key: str
    label: str
    base_url: str


# Strategy -> (key env field, secret env field, account label). The account label
# is also the state-isolation namespace (equity_history_{label}, risk_state_{label}).
_STRATEGY_ACCOUNTS: dict[str, tuple[str, str, str]] = {
    "voltarget": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY", "voltarget"),
    "trend": ("ALPACA_TREND_API_KEY", "ALPACA_TREND_SECRET_KEY", "trend"),
    "crypto_trend": (
        "ALPACA_CRYPTO_TREND_API_KEY", "ALPACA_CRYPTO_TREND_SECRET_KEY", "crypto_trend",
    ),
    "crypto_voltarget": (
        "ALPACA_CRYPTO_VOLTARGET_API_KEY", "ALPACA_CRYPTO_VOLTARGET_SECRET_KEY", "crypto_voltarget",
    ),
}

# Accounts whose session/staleness logic, risk limits, and data feed are crypto
# (24/7 UTC calendar, crypto_risk.yaml, Coinbase). Explicit — never inferred from
# the strategy name by string matching.
CRYPTO_ACCOUNTS: frozenset[str] = frozenset({"crypto_trend", "crypto_voltarget"})

# Approved strategies, in the order run-all iterates them. The crypto strategies
# passed the walk-forward + perturbation + bootstrap battery on 2026-07-11.
APPROVED_STRATEGIES: tuple[str, ...] = ("voltarget", "trend", "crypto_trend", "crypto_voltarget")

# The equity paper roster. The DAILY DIGEST is still an equity-shaped report
# (NYSE session marks) and covers only these accounts. The weekly review no
# longer uses this roster: as of 2026-07-22 it covers every APPROVED_STRATEGIES
# entry and selects its window length and structural-drift note per asset class.
EQUITY_APPROVED_STRATEGIES: tuple[str, ...] = ("voltarget", "trend")


def account_asset_class(strategy_name: str) -> str:
    """Asset class for an account: ``crypto`` for crypto accounts, else ``us_equity``."""
    return "crypto" if strategy_name in CRYPTO_ACCOUNTS else "us_equity"


def account_label(strategy_name: str) -> str:
    """The state-isolation label for ``strategy_name`` (no credentials required)."""
    mapping = _STRATEGY_ACCOUNTS.get(strategy_name)
    if mapping is None:
        raise ConfigError(f"no paper account is mapped for strategy {strategy_name!r}")
    return mapping[2]


def account_for(strategy_name: str, settings: Settings | None = None) -> AccountCreds:
    """Resolve the dedicated paper account for ``strategy_name``.

    Every strategy trades in its OWN Alpaca paper account (one paper-gated URL,
    N key pairs). Raises :class:`ConfigError` naming the missing env vars if the
    account is not configured. NEVER falls back to another strategy's account.
    """
    mapping = _STRATEGY_ACCOUNTS.get(strategy_name)
    if mapping is None:
        raise ConfigError(f"no paper account is mapped for strategy {strategy_name!r}")
    key_var, secret_var, label = mapping
    settings = settings if settings is not None else get_settings()
    api_key = getattr(settings, key_var)
    secret_key = getattr(settings, secret_var)
    missing = [name for name, val in ((key_var, api_key), (secret_var, secret_key)) if not val]
    if missing:
        raise ConfigError(
            f"paper account '{label}' (strategy {strategy_name!r}) is not configured; "
            f"set the missing env var(s): {', '.join(missing)}"
        )
    return AccountCreds(
        api_key=api_key, secret_key=secret_key, label=label,
        base_url=settings.ALPACA_BASE_URL,
    )


# The un-overridden default, kept as a name because `test_path_anchoring` asserts every
# default path in the package is anchored to the repo root.
_DOTENV_PATH: Path = PROJECT_ROOT / ".env"


def load_env_file(path: Path | None = None) -> list[str]:
    """Inject ``.env`` keys into ``os.environ`` (without overriding real env vars).

    pydantic-settings reads ``.env`` for the :class:`Settings` fields, but code
    that reads ``os.environ`` directly (e.g. the alerting SMTP config) would
    otherwise never see ``.env`` values. Call this once at CLI startup. Existing
    environment variables always win. Returns the names loaded (never values).
    """
    target = path if path is not None else env_file_path()
    if not target.exists():
        return []
    if env_file_is_group_or_world_readable(target):
        log.warning(
            "env_file_permissive",
            path=str(target),
            detail="env file is readable beyond its owner; chmod 600 it",
        )
    loaded: list[str] = []
    for raw in target.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


__all__ = [
    "PROJECT_ROOT",
    "AccountCreds",
    "APPROVED_STRATEGIES",
    "EQUITY_APPROVED_STRATEGIES",
    "CRYPTO_ACCOUNTS",
    "ConfigError",
    "ETF",
    "ProjectSettings",
    "Settings",
    "Universe",
    "account_asset_class",
    "account_for",
    "account_label",
    "get_settings",
    "load_env_file",
    "env_file_path",
    "env_file_is_group_or_world_readable",
    "ENV_FILE_VAR",
    "load_settings",
    "load_universe",
    "load_crypto_universe",
]
