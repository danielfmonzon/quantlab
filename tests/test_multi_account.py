"""Multi-account: account registry, legacy migration, run-all orchestration."""

from __future__ import annotations

import pytest

from quantlab.config import ConfigError, Settings, account_for
from quantlab.paper.runner import migrate_legacy_state, run_all_strategies


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "ALPACA_API_KEY": "vol-key", "ALPACA_SECRET_KEY": "vol-secret",
        "ALPACA_TREND_API_KEY": None, "ALPACA_TREND_SECRET_KEY": None,
    }
    base.update(overrides)
    # _env_file=None isolates the test from the on-disk .env.
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# account_for                                                                 #
# --------------------------------------------------------------------------- #

def test_voltarget_maps_to_primary_keys() -> None:
    creds = account_for("voltarget", _settings())
    assert creds.api_key == "vol-key"
    assert creds.secret_key == "vol-secret"
    assert creds.label == "voltarget"
    assert creds.base_url.endswith("paper-api.alpaca.markets")  # paper-gated


def test_trend_without_keys_raises_naming_missing_vars() -> None:
    with pytest.raises(ConfigError) as ei:
        account_for("trend", _settings())
    msg = str(ei.value)
    assert "ALPACA_TREND_API_KEY" in msg
    assert "ALPACA_TREND_SECRET_KEY" in msg
    assert "trend" in msg


def test_trend_with_keys_returns_trend_account() -> None:
    creds = account_for(
        "trend", _settings(ALPACA_TREND_API_KEY="tr-key", ALPACA_TREND_SECRET_KEY="tr-secret")
    )
    assert creds.api_key == "tr-key"
    assert creds.secret_key == "tr-secret"
    assert creds.label == "trend"


def test_trend_never_falls_back_to_voltarget_keys() -> None:
    # Only the primary keys are set; trend must NOT borrow them.
    with pytest.raises(ConfigError):
        account_for("trend", _settings())


def test_unknown_strategy_raises() -> None:
    with pytest.raises(ConfigError, match="no paper account"):
        account_for("dualmom", _settings())


# --------------------------------------------------------------------------- #
# Legacy state migration                                                      #
# --------------------------------------------------------------------------- #

def test_migration_renames_legacy_files_once(tmp_path) -> None:
    (tmp_path / "equity_history.parquet").write_text("legacy-eq", encoding="utf-8")
    (tmp_path / "risk_state.json").write_text("{}", encoding="utf-8")

    migrated = migrate_legacy_state(tmp_path)
    assert set(migrated) == {"equity_history_voltarget.parquet", "risk_state_voltarget.json"}
    assert (tmp_path / "equity_history_voltarget.parquet").exists()
    assert (tmp_path / "risk_state_voltarget.json").exists()
    assert not (tmp_path / "equity_history.parquet").exists()
    assert not (tmp_path / "risk_state.json").exists()

    # Second run is a no-op (files already migrated).
    assert migrate_legacy_state(tmp_path) == []


def test_migration_does_not_overwrite_existing_target(tmp_path) -> None:
    (tmp_path / "risk_state.json").write_text("legacy", encoding="utf-8")
    (tmp_path / "risk_state_voltarget.json").write_text("current", encoding="utf-8")
    migrated = migrate_legacy_state(tmp_path)
    assert "risk_state_voltarget.json" not in migrated
    assert (tmp_path / "risk_state_voltarget.json").read_text(encoding="utf-8") == "current"


def test_migration_absent_is_noop(tmp_path) -> None:
    assert migrate_legacy_state(tmp_path) == []


# --------------------------------------------------------------------------- #
# run-all orchestration                                                       #
# --------------------------------------------------------------------------- #

def test_run_all_continues_after_a_strategy_raises() -> None:
    attempted: list[str] = []

    def run_one(strategy: str) -> int:
        attempted.append(strategy)
        if strategy == "voltarget":
            raise RuntimeError("voltarget blew up")
        return 0

    rc = run_all_strategies(["voltarget", "trend"], run_one, printer=lambda _m: None)
    assert attempted == ["voltarget", "trend"]  # second ran despite first raising
    assert rc == 1  # nonzero because one failed


def test_run_all_nonzero_if_any_aborts() -> None:
    attempted: list[str] = []

    def run_one(strategy: str) -> int:
        attempted.append(strategy)
        return 1 if strategy == "trend" else 0

    rc = run_all_strategies(["voltarget", "trend"], run_one, printer=lambda _m: None)
    assert attempted == ["voltarget", "trend"]
    assert rc == 1


def test_run_all_zero_when_all_succeed() -> None:
    rc = run_all_strategies(["voltarget", "trend"], lambda _s: 0, printer=lambda _m: None)
    assert rc == 0
