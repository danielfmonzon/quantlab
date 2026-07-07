# quantlab

quantlab is an algorithmic trading **research** system for exploring systematic
strategies across a fixed universe of liquid ETFs. This repository (Batch 1)
provides the foundational scaffold: a uv-managed Python project, a validated
configuration system built on pydantic / pydantic-settings, and structured JSON
logging via structlog. Trading, data ingestion, and backtesting logic are
intentionally **not** part of this batch.

## Setup

Requires Python >= 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                 # create .venv and install all dependencies (incl. dev)
cp .env.example .env    # then fill in your API keys (never commit .env)
```

Configuration lives in `config/settings.yaml` (structured, non-secret settings)
and `config/universe.yaml` (the tradable ETF universe). Secret API keys are read
from the environment / `.env`.

## Running tests

```bash
uv run ruff check .            # lint
uv run mypy src/               # type check
uv run pytest -v               # tests with coverage
```

## Project layout

```
config/            settings.yaml, universe.yaml
src/quantlab/      config, logging, constants
tests/             unit tests
data/ reports/     generated artifacts (gitignored)
notebooks/         exploratory notebooks
```

## ⚠️ SAFETY

- **Research / paper-trading only.** quantlab is intended solely for research
  and paper trading. It does not place live orders.
- **Live trading is architecturally disabled.** The configuration layer enforces
  a hard safety gate: `ALPACA_BASE_URL` must point at the Alpaca *paper* endpoint
  (`https://paper-api.alpaca.markets`). Any attempt to configure a live trading
  endpoint (`api.alpaca.markets` without the `paper-` prefix) raises a
  `ConfigError` at load time and the program will not start.
- **Not financial advice.** No part of this project constitutes financial,
  investment, or trading advice. Use it at your own risk.
