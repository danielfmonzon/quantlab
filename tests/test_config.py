"""Tests for quantlab.config."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from quantlab.config import (
    ConfigError,
    Settings,
    Universe,
    load_settings,
    load_universe,
)


def test_settings_yaml_loads_and_validates() -> None:
    settings = load_settings()
    assert settings.project_name == "quantlab"
    assert settings.timezone == "America/New_York"
    assert settings.data_dir == "data"
    assert settings.reports_dir == "reports"
    assert settings.log_level == "INFO"


def test_universe_yaml_loads_twelve_symbols() -> None:
    universe = load_universe()
    assert len(universe.etfs) == 12
    expected = {
        "SPY", "QQQ", "IWM", "EFA", "EEM", "VNQ",
        "TLT", "IEF", "LQD", "GLD", "DBC", "BIL",
    }
    assert set(universe.symbols) == expected


def test_universe_rejects_duplicate_symbols(tmp_path: Path) -> None:
    dup_yaml = tmp_path / "universe.yaml"
    dup_yaml.write_text(
        textwrap.dedent(
            """\
            - symbol: SPY
              asset_class: us_equity
              description: first
            - symbol: SPY
              asset_class: us_equity
              description: duplicate
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="Duplicate symbol"):
        load_universe(dup_yaml)


def test_universe_model_direct_duplicate() -> None:
    from quantlab.config import ETF

    with pytest.raises(ConfigError, match="SPY"):
        Universe(
            etfs=[
                ETF(symbol="SPY", asset_class="us_equity", description="a"),
                ETF(symbol="SPY", asset_class="us_equity", description="b"),
            ]
        )


def test_require_keys_raises_naming_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    # env_file="" so no .env is read during the test.
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    with pytest.raises(ConfigError, match="TIINGO_API_KEY"):
        settings.require_keys("TIINGO_API_KEY", "ALPACA_API_KEY")


def test_require_keys_passes_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIINGO_API_KEY", "fake-not-real")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    settings.require_keys("TIINGO_API_KEY")  # should not raise


def test_alpaca_base_url_defaults_to_paper() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.ALPACA_BASE_URL == "https://paper-api.alpaca.markets"


def test_alpaca_base_url_safety_gate_rejects_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_BASE_URL", "https://api.alpaca.markets")
    with pytest.raises(ConfigError, match="live trading"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_alpaca_base_url_paper_variant_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.ALPACA_BASE_URL == "https://paper-api.alpaca.markets"
