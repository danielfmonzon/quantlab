"""Daily paper-trading digest: account, positions, orders, risk, track record.

Report-only. ``build_digest`` snapshots current broker/store/risk state into a
pydantic :class:`Digest`; ``render_markdown`` formats it; ``write_digest`` writes
both a ``.md`` and ``.json`` under ``reports/digests/`` (same-day reruns
overwrite).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from quantlab.backtest.panel import build_price_panel
from quantlab.broker.alpaca_trading import AlpacaTradingClient
from quantlab.constants import PROJECT_ROOT
from quantlab.data.alpaca_client import ClockInfo
from quantlab.data.calendar import TradingCalendar
from quantlab.data.health import preflight
from quantlab.data.store import ParquetStore
from quantlab.paper.runner import (
    DEFAULT_EQUITY_HISTORY,
    PAPER_REPORTS_DIR,
    current_target_weights,
    make_paper_strategy,
)
from quantlab.risk.state import DEFAULT_STATE_PATH, RiskState, load_risk_state

DIGESTS_DIR: Path = PROJECT_ROOT / "reports" / "digests"

# Strategies whose current target we surface in the digest (paper-approved only).
APPROVED_STRATEGIES = ("voltarget",)


class DigestAccount(BaseModel):
    equity: float
    cash: float
    currency: str
    day_change_pct: float | None  # vs the previous equity snapshot


class DigestPosition(BaseModel):
    symbol: str
    qty: float
    market_value: float
    avg_entry_price: float
    unrealized_pl: float
    unrealized_pl_pct: float | None


class DigestOrder(BaseModel):
    symbol: str
    side: str
    status: str
    client_order_id: str
    notional: float | None


class DigestStaleness(BaseModel):
    symbol: str
    has_data: bool
    last_date: date | None
    staleness_sessions: int


class TrackRecord(BaseModel):
    start_date: date | None
    n_run_days: int
    total_return_since_start: float | None


class Digest(BaseModel):
    generated_at: datetime
    account: DigestAccount
    positions: list[DigestPosition]
    orders: list[DigestOrder]
    risk_state: RiskState
    staleness: list[DigestStaleness]
    target_weights: dict[str, dict[str, float]]
    track_record: TrackRecord
    latest_run_note: str | None


def _equity_history(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame({"timestamp": pd.Series(dtype="datetime64[ns]"),
                             "equity": pd.Series(dtype="float64")})
    return pd.read_parquet(path)


def _latest_run_note(paper_reports_dir: Path) -> str | None:
    if not paper_reports_dir.exists():
        return None
    runs = sorted(paper_reports_dir.glob("run_*.json"))
    if not runs:
        return None
    payload = json.loads(runs[-1].read_text(encoding="utf-8"))
    if payload.get("aborted"):
        return (f"{runs[-1].name}: ABORTED at {payload.get('abort_stage')} "
                f"- {payload.get('abort_reason')}")
    if payload.get("no_trades"):
        return f"{runs[-1].name}: in-band, no trades"
    n = len(payload.get("submitted_orders") or [])
    return f"{runs[-1].name}: {'DRY-RUN' if payload.get('dry_run') else 'SUBMIT'}, {n} order(s)"


def build_digest(
    broker: AlpacaTradingClient,
    store: ParquetStore,
    calendar: TradingCalendar,
    now: datetime,
    *,
    clock: ClockInfo | None = None,
    equity_history_path: Path = DEFAULT_EQUITY_HISTORY,
    paper_reports_dir: Path = PAPER_REPORTS_DIR,
    risk_state_path: Path = DEFAULT_STATE_PATH,
) -> Digest:
    """Assemble the daily digest from live broker/store/risk state."""
    account_raw = broker.get_account()
    positions_raw = broker.get_positions()
    orders_raw = broker.get_orders(status="all", after=now.date())

    history = _equity_history(equity_history_path)
    prev_equity = float(history["equity"].iloc[-1]) if len(history) else None
    day_change = (
        account_raw.equity / prev_equity - 1.0
        if prev_equity is not None and prev_equity > 0.0
        else None
    )

    positions: list[DigestPosition] = []
    for p in positions_raw:
        cost = p.qty * p.avg_entry_price
        upl = p.market_value - cost
        positions.append(DigestPosition(
            symbol=p.symbol, qty=p.qty, market_value=p.market_value,
            avg_entry_price=p.avg_entry_price, unrealized_pl=upl,
            unrealized_pl_pct=(upl / cost) if cost > 0.0 else None,
        ))

    orders = [
        DigestOrder(symbol=o.symbol, side=o.side, status=o.status,
                    client_order_id=o.client_order_id, notional=o.notional)
        for o in orders_raw
    ]

    # Union of approved strategies' symbols for the staleness view.
    strategies = {name: make_paper_strategy(name) for name in APPROVED_STRATEGIES}
    symbols = sorted({s for strat in strategies.values() for s in strat.all_symbols})
    health = preflight(symbols, store, calendar, clock, now)
    staleness = [
        DigestStaleness(symbol=sh.symbol, has_data=sh.has_data,
                        last_date=sh.last_date, staleness_sessions=sh.staleness_sessions)
        for sh in health.symbols
    ]

    target_weights: dict[str, dict[str, float]] = {}
    for name, strat in strategies.items():
        panel = build_price_panel(store, strat.all_symbols)
        usable = panel[strat.required_symbols].dropna()
        if usable.empty:
            target_weights[name] = {}
            continue
        panel = panel.loc[usable.index.min():]
        weights, _ = current_target_weights(strat, panel)
        target_weights[name] = weights

    start_date = (
        pd.Timestamp(history["timestamp"].iloc[0]).date() if len(history) else None
    )
    first_equity = float(history["equity"].iloc[0]) if len(history) else None
    total_return = (
        account_raw.equity / first_equity - 1.0
        if first_equity is not None and first_equity > 0.0
        else None
    )
    track_record = TrackRecord(
        start_date=start_date, n_run_days=int(len(history)),
        total_return_since_start=total_return,
    )

    return Digest(
        generated_at=now,
        account=DigestAccount(
            equity=account_raw.equity, cash=account_raw.cash,
            currency=account_raw.currency, day_change_pct=day_change,
        ),
        positions=positions,
        orders=orders,
        risk_state=load_risk_state(risk_state_path),
        staleness=staleness,
        target_weights=target_weights,
        track_record=track_record,
        latest_run_note=_latest_run_note(paper_reports_dir),
    )


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.2%}"


def render_markdown(digest: Digest) -> str:
    """Render a compact, readable daily report."""
    a = digest.account
    lines: list[str] = []
    lines.append(f"# quantlab paper digest - {digest.generated_at.date().isoformat()}")
    lines.append("")
    lines.append(f"_generated {digest.generated_at.isoformat()}_")
    lines.append("")

    lines.append("## Account")
    lines.append(
        f"- equity: **{a.equity:,.2f} {a.currency}**  (day change {_pct(a.day_change_pct)})"
    )
    lines.append(f"- cash: {a.cash:,.2f} {a.currency}")
    lines.append("")

    lines.append("## Positions")
    if not digest.positions:
        lines.append("- (none)")
    else:
        lines.append("| symbol | qty | market value | avg entry | unrealized P&L |")
        lines.append("|---|---:|---:|---:|---:|")
        for p in digest.positions:
            lines.append(
                f"| {p.symbol} | {p.qty:g} | {p.market_value:,.2f} | "
                f"{p.avg_entry_price:,.2f} | {p.unrealized_pl:+,.2f} "
                f"({_pct(p.unrealized_pl_pct)}) |"
            )
    lines.append("")

    lines.append(f"## Today's orders ({digest.generated_at.date().isoformat()})")
    if not digest.orders:
        lines.append("- (none)")
    else:
        for o in digest.orders:
            note = f" ${o.notional:,.2f}" if o.notional is not None else ""
            lines.append(f"- {o.side} {o.symbol}{note} - {o.status}  (`{o.client_order_id}`)")
    lines.append("")

    rs = digest.risk_state
    lines.append("## Risk state")
    halted_detail = (
        f" - {rs.reason} (manual reset required: {rs.requires_manual_reset})"
        if rs.halted else ""
    )
    lines.append(f"- halted: **{rs.halted}**{halted_detail}")
    lines.append("")

    lines.append("## Data staleness")
    for s in digest.staleness:
        last = s.last_date.isoformat() if s.last_date else "-"
        lines.append(f"- {s.symbol}: last {last}, {s.staleness_sessions} session(s) behind"
                     + ("" if s.has_data else " (NO DATA)"))
    lines.append("")

    lines.append("## Current target weights")
    for name, weights in digest.target_weights.items():
        pretty = ", ".join(f"{k}={v:.3f}" for k, v in weights.items()) or "cash"
        lines.append(f"- {name}: {pretty}")
    lines.append("")

    tr = digest.track_record
    lines.append("## Paper track record")
    start = tr.start_date.isoformat() if tr.start_date else "-"
    lines.append(f"- since {start} over {tr.n_run_days} run-day(s): "
                 f"total return {_pct(tr.total_return_since_start)}")
    lines.append("")

    if digest.latest_run_note:
        lines.append("## Latest run")
        lines.append(f"- {digest.latest_run_note}")
        lines.append("")

    return "\n".join(lines)


def write_digest(digest: Digest, digests_dir: Path = DIGESTS_DIR) -> tuple[Path, Path]:
    """Write ``digest_{YYYYMMDD}.md`` and ``.json`` (overwriting same-day reruns)."""
    digests_dir.mkdir(parents=True, exist_ok=True)
    stamp = digest.generated_at.strftime("%Y%m%d")
    md_path = digests_dir / f"digest_{stamp}.md"
    json_path = digests_dir / f"digest_{stamp}.json"
    md_path.write_text(render_markdown(digest), encoding="utf-8")
    json_path.write_text(json.dumps(digest.model_dump(mode="json"), indent=2), encoding="utf-8")
    return md_path, json_path


__all__ = [
    "build_digest",
    "render_markdown",
    "write_digest",
    "Digest",
    "DigestAccount",
    "DigestPosition",
    "DigestOrder",
    "DigestStaleness",
    "TrackRecord",
    "DIGESTS_DIR",
    "APPROVED_STRATEGIES",
]
