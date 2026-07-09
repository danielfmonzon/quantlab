"""Daily paper-trading digest across ALL paper accounts (one section per label).

Report-only. ``build_digest`` snapshots each approved strategy's dedicated
account (equity, positions with unrealized P&L, orders, that label's risk state,
staleness, target weights, per-label track record) plus a combined total. A label
whose keys are absent is skipped cleanly with a note. ``render_markdown`` formats
it; ``write_digest`` writes ``.md`` + ``.json`` under ``reports/digests/``
(same-day reruns overwrite).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from quantlab.backtest.panel import build_price_panel
from quantlab.broker.alpaca_trading import AlpacaTradingClient
from quantlab.config import APPROVED_STRATEGIES
from quantlab.constants import PROJECT_ROOT
from quantlab.data.alpaca_client import ClockInfo
from quantlab.data.calendar import TradingCalendar
from quantlab.data.health import preflight
from quantlab.data.store import ParquetStore
from quantlab.paper.runner import (
    DATA_DIR,
    PAPER_REPORTS_DIR,
    current_target_weights,
    equity_history_path_for,
    make_paper_strategy,
)
from quantlab.risk.state import RiskState, load_risk_state, risk_state_path_for

DIGESTS_DIR: Path = PROJECT_ROOT / "reports" / "digests"


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


class AccountDigest(BaseModel):
    """One paper account's slice of the digest."""

    label: str
    available: bool
    note: str | None = None  # why unavailable, when available is False
    account: DigestAccount | None = None
    positions: list[DigestPosition] = []
    orders: list[DigestOrder] = []
    risk_state: RiskState | None = None
    staleness: list[DigestStaleness] = []
    target_weights: dict[str, float] = {}
    track_record: TrackRecord | None = None
    latest_run_note: str | None = None


class Digest(BaseModel):
    generated_at: datetime
    accounts: list[AccountDigest]
    combined_equity: float
    combined_cash: float


def _equity_history(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame({"timestamp": pd.Series(dtype="datetime64[ns]"),
                             "equity": pd.Series(dtype="float64")})
    return pd.read_parquet(path)


def _latest_run_note(paper_reports_dir: Path, label: str) -> str | None:
    if not paper_reports_dir.exists():
        return None
    runs = sorted(paper_reports_dir.glob(f"run_{label}_*.json"))
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


def _account_digest(
    label: str,
    broker: AlpacaTradingClient | None,
    store: ParquetStore,
    calendar: TradingCalendar,
    now: datetime,
    clock: ClockInfo | None,
    data_dir: Path,
    paper_reports_dir: Path,
) -> AccountDigest:
    if broker is None:
        return AccountDigest(label=label, available=False,
                             note="account keys not configured")

    strat = make_paper_strategy(label)
    account_raw = broker.get_account()
    positions_raw = broker.get_positions()
    orders_raw = broker.get_orders(status="all", after=now.date())

    history = _equity_history(equity_history_path_for(label, data_dir))
    prev_equity = float(history["equity"].iloc[-1]) if len(history) else None
    day_change = (
        account_raw.equity / prev_equity - 1.0
        if prev_equity is not None and prev_equity > 0.0 else None
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

    health = preflight(strat.all_symbols, store, calendar, clock, now)
    staleness = [
        DigestStaleness(symbol=sh.symbol, has_data=sh.has_data,
                        last_date=sh.last_date, staleness_sessions=sh.staleness_sessions)
        for sh in health.symbols
    ]

    panel = build_price_panel(store, strat.all_symbols)
    usable = panel[strat.required_symbols].dropna()
    if usable.empty:
        target_weights: dict[str, float] = {}
    else:
        panel = panel.loc[usable.index.min():]
        target_weights, _ = current_target_weights(strat, panel)

    start_date = pd.Timestamp(history["timestamp"].iloc[0]).date() if len(history) else None
    first_equity = float(history["equity"].iloc[0]) if len(history) else None
    total_return = (
        account_raw.equity / first_equity - 1.0
        if first_equity is not None and first_equity > 0.0 else None
    )

    return AccountDigest(
        label=label,
        available=True,
        account=DigestAccount(
            equity=account_raw.equity, cash=account_raw.cash,
            currency=account_raw.currency, day_change_pct=day_change,
        ),
        positions=positions,
        orders=orders,
        risk_state=load_risk_state(risk_state_path_for(label, data_dir)),
        staleness=staleness,
        target_weights=target_weights,
        track_record=TrackRecord(
            start_date=start_date, n_run_days=int(len(history)),
            total_return_since_start=total_return,
        ),
        latest_run_note=_latest_run_note(paper_reports_dir, label),
    )


def build_digest(
    brokers: dict[str, AlpacaTradingClient | None],
    store: ParquetStore,
    calendar: TradingCalendar,
    now: datetime,
    *,
    clock: ClockInfo | None = None,
    data_dir: Path = DATA_DIR,
    paper_reports_dir: Path = PAPER_REPORTS_DIR,
) -> Digest:
    """Assemble the digest across every approved account (missing keys -> skipped)."""
    accounts: list[AccountDigest] = []
    combined_equity = 0.0
    combined_cash = 0.0
    for label in APPROVED_STRATEGIES:
        acct = _account_digest(
            label, brokers.get(label), store, calendar, now, clock, data_dir, paper_reports_dir
        )
        accounts.append(acct)
        if acct.available and acct.account is not None:
            combined_equity += acct.account.equity
            combined_cash += acct.account.cash
    return Digest(
        generated_at=now, accounts=accounts,
        combined_equity=combined_equity, combined_cash=combined_cash,
    )


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.2%}"


def _render_account(acct: AccountDigest) -> list[str]:
    lines: list[str] = [f"## Account: {acct.label}"]
    if not acct.available:
        lines.append(f"- _skipped: {acct.note}_")
        lines.append("")
        return lines

    a = acct.account
    assert a is not None
    lines.append(
        f"- equity: **{a.equity:,.2f} {a.currency}**  (day change {_pct(a.day_change_pct)})"
    )
    lines.append(f"- cash: {a.cash:,.2f} {a.currency}")

    if acct.positions:
        lines.append("")
        lines.append("| symbol | qty | market value | avg entry | unrealized P&L |")
        lines.append("|---|---:|---:|---:|---:|")
        for p in acct.positions:
            lines.append(
                f"| {p.symbol} | {p.qty:g} | {p.market_value:,.2f} | "
                f"{p.avg_entry_price:,.2f} | {p.unrealized_pl:+,.2f} "
                f"({_pct(p.unrealized_pl_pct)}) |"
            )
    else:
        lines.append("- positions: (none)")

    if acct.orders:
        lines.append("")
        lines.append("- orders today:")
        for o in acct.orders:
            note = f" ${o.notional:,.2f}" if o.notional is not None else ""
            lines.append(f"  - {o.side} {o.symbol}{note} - {o.status}  (`{o.client_order_id}`)")

    rs = acct.risk_state
    halted = rs.halted if rs is not None else False
    lines.append(f"- risk: halted **{halted}**"
                 + (f" - {rs.reason}" if rs is not None and rs.halted else ""))

    weights = ", ".join(f"{k}={v:.3f}" for k, v in acct.target_weights.items()) or "cash"
    lines.append(f"- target weights: {weights}")

    tr = acct.track_record
    if tr is not None:
        start = tr.start_date.isoformat() if tr.start_date else "-"
        lines.append(f"- track record: since {start} over {tr.n_run_days} run-day(s), "
                     f"total return {_pct(tr.total_return_since_start)}")
    if acct.latest_run_note:
        lines.append(f"- latest run: {acct.latest_run_note}")
    lines.append("")
    return lines


def render_markdown(digest: Digest) -> str:
    """Render the multi-account daily report."""
    lines: list[str] = [
        f"# quantlab paper digest - {digest.generated_at.date().isoformat()}",
        "",
        f"_generated {digest.generated_at.isoformat()}_",
        "",
    ]
    for acct in digest.accounts:
        lines.extend(_render_account(acct))

    lines.append("## Combined")
    lines.append(f"- total equity across accounts: **{digest.combined_equity:,.2f}**")
    lines.append(f"- total cash across accounts: {digest.combined_cash:,.2f}")
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
    "AccountDigest",
    "DigestAccount",
    "DigestPosition",
    "DigestOrder",
    "DigestStaleness",
    "TrackRecord",
    "DIGESTS_DIR",
]
