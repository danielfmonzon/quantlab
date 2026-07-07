"""Project-wide constants."""

from __future__ import annotations

from pathlib import Path

# Repository root (…/quantlab), resolved from this file's location:
# src/quantlab/constants.py -> parents[2] == repo root.
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

CONFIG_DIR: Path = PROJECT_ROOT / "config"
SETTINGS_YAML: Path = CONFIG_DIR / "settings.yaml"
UNIVERSE_YAML: Path = CONFIG_DIR / "universe.yaml"

# Alpaca endpoints. Only the paper endpoint is permitted in this codebase.
ALPACA_PAPER_BASE_URL: str = "https://paper-api.alpaca.markets"
# Substring that marks a live-trading endpoint. Any base URL containing this
# host without the "paper-" prefix is rejected as a hard safety gate.
ALPACA_LIVE_HOST: str = "api.alpaca.markets"

ENV_KEY_NAMES: tuple[str, ...] = (
    "TIINGO_API_KEY",
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "ALPACA_BASE_URL",
)
