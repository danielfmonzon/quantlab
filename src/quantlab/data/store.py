"""Parquet-backed EOD store with a DuckDB read view.

One parquet file per symbol at ``data/eod/{SYMBOL}.parquet``. Symbol metadata
(inception date and the start date requested at ingest) is persisted alongside
as ``{SYMBOL}.meta.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from quantlab.constants import PROJECT_ROOT
from quantlab.data import CANONICAL_COLUMNS, DataError

_DEFAULT_EOD_DIR = PROJECT_ROOT / "data" / "eod"


@dataclass(frozen=True)
class SymbolMeta:
    """Persisted per-symbol metadata."""

    inception_date: date | None
    requested_start: date | None


class ParquetStore:
    """Per-symbol parquet storage with upsert semantics."""

    def __init__(self, eod_dir: Path = _DEFAULT_EOD_DIR):
        self.eod_dir = Path(eod_dir)
        self.eod_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, symbol: str) -> Path:
        return self.eod_dir / f"{symbol.upper()}.parquet"

    def _meta_path_for(self, symbol: str) -> Path:
        return self.eod_dir / f"{symbol.upper()}.meta.json"

    def exists(self, symbol: str) -> bool:
        return self.path_for(symbol).exists()

    # -- Read / write --------------------------------------------------------

    def load(
        self,
        symbol: str,
        start: date | str | None = None,
        end: date | str | None = None,
    ) -> pd.DataFrame:
        """Load a symbol's frame, optionally filtered to [start, end] inclusive."""
        path = self.path_for(symbol)
        if not path.exists():
            empty = pd.DataFrame({c: pd.Series(dtype="float64") for c in CANONICAL_COLUMNS})
            empty["date"] = pd.Series(dtype="datetime64[ns]")
            return empty[list(CANONICAL_COLUMNS)]

        df = pd.read_parquet(path)
        df = df[list(CANONICAL_COLUMNS)].copy()
        df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
        if start is not None:
            df = df[df["date"] >= pd.Timestamp(start)]
        if end is not None:
            df = df[df["date"] <= pd.Timestamp(end)]
        return df.sort_values("date").reset_index(drop=True)

    def upsert(self, symbol: str, df: pd.DataFrame) -> pd.DataFrame:
        """Merge ``df`` into the symbol's store on ``date`` (new rows win).

        Idempotent: upserting identical data twice leaves the file unchanged.
        Returns the merged frame.
        """
        missing = [c for c in CANONICAL_COLUMNS if c not in df.columns]
        if missing:
            raise DataError(f"Cannot upsert {symbol}: missing columns {missing}")

        incoming = df[list(CANONICAL_COLUMNS)].copy()
        # Pin dtype so parquet round-trips and concats stay byte-identical (idempotency).
        incoming["date"] = pd.to_datetime(incoming["date"]).dt.normalize().astype("datetime64[ns]")

        if self.exists(symbol):
            existing = self.load(symbol)
            # Existing first, incoming second -> keep='last' lets new rows win.
            combined = pd.concat([existing, incoming], ignore_index=True)
        else:
            combined = incoming

        combined = (
            combined.drop_duplicates(subset="date", keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )

        if combined["date"].duplicated().any():  # pragma: no cover - defensive
            raise DataError(f"Non-unique dates after upsert for {symbol}")

        # Drop any transient frame-level attrs (e.g. the client's inception_date);
        # pandas>=3 would otherwise fail to JSON-serialize them into parquet metadata.
        combined.attrs = {}
        combined.to_parquet(self.path_for(symbol), index=False)
        return combined

    # -- Metadata ------------------------------------------------------------

    def save_metadata(
        self,
        symbol: str,
        inception_date: date | None,
        requested_start: date | None = None,
    ) -> None:
        payload = {
            "symbol": symbol.upper(),
            "inception_date": inception_date.isoformat() if inception_date else None,
            "requested_start": requested_start.isoformat() if requested_start else None,
        }
        self._meta_path_for(symbol).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_metadata(self, symbol: str) -> SymbolMeta | None:
        path = self._meta_path_for(symbol)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        inception = payload.get("inception_date")
        requested = payload.get("requested_start")
        return SymbolMeta(
            inception_date=date.fromisoformat(inception) if inception else None,
            requested_start=date.fromisoformat(requested) if requested else None,
        )

    def symbols(self) -> list[str]:
        return sorted(p.stem for p in self.eod_dir.glob("*.parquet"))

    # -- DuckDB view ---------------------------------------------------------

    def duckdb_connection(self) -> duckdb.DuckDBPyConnection:
        """Return an in-memory DuckDB connection exposing a read-only view
        ``eod_prices`` (columns: symbol + canonical schema) over all parquet
        files. The underlying parquet files are only ever read, never written.
        """
        con = duckdb.connect(database=":memory:")
        cols = ", ".join(CANONICAL_COLUMNS)
        files = sorted(self.eod_dir.glob("*.parquet"))
        if files:
            pattern = str(self.eod_dir / "*.parquet").replace("\\", "/")
            con.execute(
                f"""
                CREATE VIEW eod_prices AS
                SELECT parse_filename(filename, true) AS symbol, {cols}
                FROM read_parquet('{pattern}', filename=true)
                """
            )
        else:
            # No data yet: an empty view with the correct column names.
            typed = ["CAST(NULL AS VARCHAR) AS symbol", "CAST(NULL AS TIMESTAMP) AS date"]
            typed += [f"CAST(NULL AS DOUBLE) AS {c}" for c in CANONICAL_COLUMNS[1:]]
            con.execute(f"CREATE VIEW eod_prices AS SELECT {', '.join(typed)} WHERE 1=0")
        return con


__all__ = ["ParquetStore", "SymbolMeta"]
