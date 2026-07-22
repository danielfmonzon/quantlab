"""Asset-class registry and symbol-format conversion for the trading client.

quantlab's canonical symbol form is dash-separated (``BTC-USD``), matching the
universe files and the parquet store. Alpaca's crypto *trading* API expects the
slash form (``BTC/USD`` — verified against Alpaca's crypto-orders docs), while
positions may echo either the slash or a bare concatenated form (``BTCUSD``).

The crypto set is an EXPLICIT registry (mirroring ``config/crypto_universe.yaml``
— a test pins them equal), never inferred by string heuristics like "ends with
USD". Equity symbols pass through every helper unchanged, so equity order and
position handling is byte-for-byte identical to before.
"""

from __future__ import annotations

CRYPTO = "crypto"
US_EQUITY = "us_equity"

# Canonical (dash) crypto symbols. Kept in lockstep with crypto_universe.yaml.
CRYPTO_SYMBOLS: frozenset[str] = frozenset({"BTC-USD", "ETH-USD"})

# Reverse map: every Alpaca-facing spelling of a crypto symbol -> canonical form.
_ALPACA_TO_CANONICAL: dict[str, str] = {}
for _canon in CRYPTO_SYMBOLS:
    _ALPACA_TO_CANONICAL[_canon] = _canon  # BTC-USD
    _ALPACA_TO_CANONICAL[_canon.replace("-", "/")] = _canon  # BTC/USD
    _ALPACA_TO_CANONICAL[_canon.replace("-", "")] = _canon  # BTCUSD


def asset_class(symbol: str) -> str:
    """Return ``crypto`` for a registered crypto symbol (any spelling), else ``us_equity``."""
    return CRYPTO if to_canonical_symbol(symbol) in CRYPTO_SYMBOLS else US_EQUITY


def to_alpaca_symbol(symbol: str) -> str:
    """Canonical symbol -> the form Alpaca's trading API expects.

    Crypto uses the slash form (``BTC-USD`` -> ``BTC/USD``); equities are unchanged.
    """
    canon = to_canonical_symbol(symbol)
    if canon in CRYPTO_SYMBOLS:
        return canon.replace("-", "/")
    return symbol


def to_canonical_symbol(symbol: str) -> str:
    """Any Alpaca crypto spelling (``BTC/USD`` / ``BTCUSD``) -> canonical ``BTC-USD``.

    Equity symbols (not in the registry) are returned unchanged.
    """
    return _ALPACA_TO_CANONICAL.get(symbol, symbol)


__all__ = [
    "CRYPTO",
    "US_EQUITY",
    "CRYPTO_SYMBOLS",
    "asset_class",
    "to_alpaca_symbol",
    "to_canonical_symbol",
]
