"""Glass Box API: schemas, empty states, provenance, parsing, and read-only proof.

Everything runs against a fixture artifact tree in ``tmp_path`` via ``TestClient``
— no network, no real repo writes. The one exception is the decisions-parser test,
which reads the REAL ``docs/decisions.md`` on purpose: a parser for a file format
should be tested against the file it has to parse.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from quantlab.constants import PROJECT_ROOT
from quantlab.glassbox.app import create_app
from quantlab.glassbox.constants import (
    PROVENANCE_CATCH_UP,
    PROVENANCE_LEAKED,
    PROVENANCE_ON_SCHEDULE,
)
from quantlab.glassbox.decisions import parse_decisions, read_decisions
from quantlab.glassbox.models import (
    DecisionsResponse,
    DivergenceResponse,
    EquityResponse,
    IgnoredInputsResponse,
    OverviewResponse,
    RiskResponse,
    RunsResponse,
    TimelineResponse,
)
from quantlab.glassbox.paths import GlassboxPaths
from quantlab.glassbox.provenance import classify_mark

ALL_ENDPOINTS = (
    "/api/overview",
    "/api/runs",
    "/api/divergence",
    "/api/equity",
    "/api/risk",
    "/api/timeline",
    "/api/decisions",
    "/api/ignored-inputs",
)

RESPONSE_MODELS = {
    "/api/overview": OverviewResponse,
    "/api/runs": RunsResponse,
    "/api/divergence": DivergenceResponse,
    "/api/equity": EquityResponse,
    "/api/risk": RiskResponse,
    "/api/timeline": TimelineResponse,
    "/api/decisions": DecisionsResponse,
    "/api/ignored-inputs": IgnoredInputsResponse,
}


# --------------------------------------------------------------------------- #
# Fixture artifact tree                                                       #
# --------------------------------------------------------------------------- #

VOLTARGET_SUBMIT_RUN: dict[str, Any] = {
    "strategy": "voltarget",
    "dry_run": False,
    "timestamp": "2026-07-24T14:00:07.519467Z",
    "aborted": False,
    "abort_stage": None,
    "abort_reason": None,
    "equity": 98821.82,
    "target_weights": {"SPY": 0.85715659109397},
    "plan": {
        "equity": 98821.82,
        "cash": 14116.04,
        "current_weights": {"SPY": 0.9371},
        "target_weights": {"SPY": 0.85715659109397},
        "intents": [{"symbol": "SPY", "side": "sell", "notional": 7897.07,
                     "current_w": 0.9371, "target_w": 0.85715659109397}],
        "skipped": [{"symbol": "IEF", "current_w": 0.004, "target_w": 0.0,
                     "diff": 0.004}],
        "est_turnover": 0.0799,
        "buy_scale": 1.0,
        "min_trade_frac": 0.01,
    },
    "submitted_orders": [{"id": "oid-SPY", "client_order_id": "ql-voltarget-20260724-SPY-sell",
                          "symbol": "SPY", "side": "sell", "notional": 7897.07,
                          "status": "filled", "submitted_at": "2026-07-24T14:00:08Z",
                          "was_duplicate": False}],
    "no_trades": False,
    "stages": [{"stage": "risk_state", "ok": True, "detail": "not halted"},
               {"stage": "submit", "ok": True, "detail": "submitted 1 order(s)"}],
}

TREND_NOTRADE_RUN: dict[str, Any] = {
    "strategy": "trend",
    "dry_run": False,
    "timestamp": "2026-07-23T14:00:16.183102Z",
    "aborted": False,
    "equity": 98467.50,
    "target_weights": {"SPY": 1.0},
    "plan": {"equity": 98467.50, "cash": 3.98, "current_weights": {"SPY": 0.99996},
             "target_weights": {"SPY": 1.0}, "intents": [], "skipped": [],
             "est_turnover": 0.0, "buy_scale": 1.0, "min_trade_frac": 0.01},
    "submitted_orders": [],
    "no_trades": True,
    "stages": [{"stage": "plan", "ok": True, "detail": "in-band, no trades"}],
}

TREND_ABORTED_RUN: dict[str, Any] = {
    "strategy": "trend",
    "dry_run": True,
    "timestamp": "2026-07-22T14:00:28.578414Z",
    "aborted": True,
    "abort_stage": "health",
    "abort_reason": "FREEZE_STALE_DATA: SPY is 2 sessions stale",
    "equity": None,
    "target_weights": {},
    "plan": None,
    "submitted_orders": [],
    "no_trades": False,
    "stages": [{"stage": "health", "ok": False, "detail": "stale"}],
}

CRYPTO_RUN: dict[str, Any] = {
    "strategy": "crypto_voltarget",
    "dry_run": False,
    "timestamp": "2026-07-24T05:43:03.688286Z",
    "aborted": False,
    "equity": 100872.81,
    "target_weights": {"BTC-USD": 0.6741382252011294},
    "plan": {"equity": 100872.81, "cash": 31844.32,
             "current_weights": {"BTC-USD": 0.6843121599665957},
             "target_weights": {"BTC-USD": 0.6741382252011294},
             "intents": [{"symbol": "BTC-USD", "side": "sell", "notional": 1026.27,
                          "current_w": 0.6843121599665957,
                          "target_w": 0.6741382252011294}],
             "skipped": [], "est_turnover": 0.0102, "buy_scale": 1.0,
             "min_trade_frac": 0.01},
    "submitted_orders": [{"id": "oid-BTC", "client_order_id": "ql-cv-20260724-BTC-USD-sell",
                          "symbol": "BTC-USD", "side": "sell", "notional": 1026.27,
                          "status": "pending_new", "submitted_at": None,
                          "was_duplicate": False}],
    "no_trades": False,
    "stages": [{"stage": "submit", "ok": True, "detail": "submitted 1 order(s)"}],
}

WEEKLY_REVIEW: dict[str, Any] = {
    "generated_at": "2026-07-24T21:00:03.939687Z",
    "week_ending": "2026-07-24",
    "divergence_threshold_bps": 50.0,
    "accounts": [
        {"label": "voltarget", "available": True, "asset_class": "us_equity",
         "window": {"start": "2026-07-20", "end": "2026-07-24", "n_snapshots": 5,
                    "insufficient": False, "note": None},
         "paper_week_return": -0.0094, "shadow_week_return": -0.0046,
         "divergence_bps": -47.66, "excluded_tail_days": [],
         "cumulative": {"paper_total_return": -0.0118, "shadow_total_return": -0.0145,
                        "cumulative_divergence_bps": 27.32,
                        "structural_drift_note": "dividend drag note"},
         "verdict": "TRACKING"},
        {"label": "trend", "available": True, "asset_class": "us_equity",
         "window": {"start": "2026-07-16", "end": "2026-07-23", "n_snapshots": 5,
                    "insufficient": False, "note": None},
         "paper_week_return": -0.0173, "shadow_week_return": -0.0167,
         "divergence_bps": -6.06, "excluded_tail_days": ["2026-07-24"],
         "cumulative": {"paper_total_return": -0.0153, "shadow_total_return": -0.0180,
                        "cumulative_divergence_bps": 26.90,
                        "structural_drift_note": "dividend drag note"},
         "verdict": "TRACKING"},
    ],
    "readiness": {
        "clocks": [
            {"asset_class": "us_equity", "paper_start_date": "2026-07-09",
             "calendar_days_elapsed": 15, "target_days": 90, "pct_complete": 16.67,
             "start_note": None},
            {"asset_class": "crypto", "paper_start_date": "2026-07-22",
             "calendar_days_elapsed": 2, "target_days": 90, "pct_complete": 2.22,
             "start_note": "clock restarted 2026-07-22 by ruling"},
        ],
        "blockers": ["crypto_voltarget: DIVERGING week (+91 bps)",
                     "trend: only 3 completed run(s) this week (< 4)"],
    },
}

DECISIONS_FIXTURE = """# Decision log

Preamble prose that is not an entry.

---

## 2026-07-25 — Glass Box design ruling

**Decision.** Narration is template-bound.

---

## 2026-07-22 — Scheduler catch-up

**Decision.** Enable StartWhenAvailable.

---
"""


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_equity(path: Path, stamps: list[str], values: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"timestamp": pd.to_datetime(stamps), "equity": values}).to_parquet(
        path, index=False
    )


@pytest.fixture
def populated_tree(tmp_path: Path) -> Path:
    """A fixture repo carrying one artifact of every kind the API reads."""
    root = tmp_path / "repo"
    paper = root / "reports" / "paper"
    _write_json(paper / "run_voltarget_20260724T140007Z.json", VOLTARGET_SUBMIT_RUN)
    _write_json(paper / "run_trend_20260723T140016Z.json", TREND_NOTRADE_RUN)
    _write_json(paper / "run_trend_20260722T140028Z.json", TREND_ABORTED_RUN)
    _write_json(paper / "run_crypto_voltarget_20260724T054303Z.json", CRYPTO_RUN)
    # A corrupt report must be skipped, not 500.
    (paper / "run_trend_20260721T140011Z.json").write_text("{not json", encoding="utf-8")

    _write_json(root / "reports" / "weekly" / "week_20260724.json", WEEKLY_REVIEW)
    _write_json(root / "reports" / "digests" / "digest_20260724.json",
                {"generated_at": "2026-07-24T20:45:04Z", "accounts": []})

    alerts = root / "reports" / "alerts" / "alerts.jsonl"
    alerts.parent.mkdir(parents=True, exist_ok=True)
    alerts.write_text(
        json.dumps({"timestamp": "2026-07-24T21:01:32Z", "level": "WARNING",
                    "title": "weekly review: trend DIVERGING", "body": "b",
                    "source": "reporting.weekly", "strategy": "trend"}) + "\n"
        + "{ broken line\n"
        + json.dumps({"timestamp": "2026-07-24T14:00:09Z", "level": "INFO",
                      "title": "paper voltarget: 1 order(s) submitted", "body": "b",
                      "source": "paper.runner", "strategy": "voltarget"}) + "\n",
        encoding="utf-8",
    )

    _write_equity(root / "data" / "equity_history_voltarget.parquet",
                  ["2026-07-20 14:00:05", "2026-07-23 14:00:10", "2026-07-24 14:00:07"],
                  [99759.12, 99150.70, 98821.82])
    _write_equity(root / "data" / "equity_history_trend.parquet",
                  ["2026-07-23 14:00:16", "2026-07-24 14:00:18"],
                  [98467.50, 98147.57])
    _write_equity(root / "data" / "equity_history_crypto_voltarget.parquet",
                  ["2026-07-22 14:00:46", "2026-07-23 00:30:09", "2026-07-24 05:43:03"],
                  [101519.84, 101918.02, 100872.81])
    _write_json(root / "data" / "risk_state_trend.json",
                {"halted": True, "reason": "daily loss 4.1%",
                 "triggered_at": "2026-07-23T14:00:00Z", "requires_manual_reset": False})

    cfg = root / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "risk.yaml").write_text(
        "max_position_weight: 1.0\nmax_gross_exposure: 1.0\nmax_daily_loss: 0.03\n"
        "max_weekly_loss: 0.08\nmax_drawdown_kill: 0.25\nstaleness_max_sessions: 1\n"
        "weekly_divergence_alert_bps: 50\n", encoding="utf-8")
    (cfg / "crypto_risk.yaml").write_text(
        "max_position_weight: 1.0\nmax_gross_exposure: 1.0\nmax_daily_loss: 0.15\n"
        "max_weekly_loss: 0.25\nmax_drawdown_kill: 0.50\nstaleness_max_sessions: 1\n",
        encoding="utf-8")

    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "decisions.md").write_text(DECISIONS_FIXTURE, encoding="utf-8")
    return root


def _client(root: Path) -> TestClient:
    return TestClient(create_app(GlassboxPaths.from_root(root)))


# --------------------------------------------------------------------------- #
# Populated tree: every endpoint, valid schema                                #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("endpoint", ALL_ENDPOINTS)
def test_endpoint_returns_valid_schema_on_populated_tree(
    populated_tree: Path, endpoint: str
) -> None:
    response = _client(populated_tree).get(endpoint)
    assert response.status_code == 200, response.text
    # Re-validating against the declared model proves the payload round-trips.
    RESPONSE_MODELS[endpoint].model_validate(response.json())


def test_overview_reports_equity_risk_tier_and_clock(populated_tree: Path) -> None:
    body = _client(populated_tree).get("/api/overview").json()
    accounts = {a["label"]: a for a in body["accounts"]}
    assert set(accounts) == {"voltarget", "trend", "crypto_trend", "crypto_voltarget"}
    assert body["week_ending"] == "2026-07-24"

    vt = accounts["voltarget"]
    assert vt["asset_class"] == "us_equity"
    assert vt["latest_equity"] == pytest.approx(98821.82)
    assert vt["latest_snapshot_at"].startswith("2026-07-24T14:00:07")
    assert vt["latest_snapshot_provenance"] == PROVENANCE_ON_SCHEDULE
    assert vt["snapshot_count"] == 3
    assert vt["validation_tier"] == "Proven"
    assert vt["validation_tier_rationale"]
    assert vt["clock"]["asset_class"] == "us_equity"
    assert vt["clock"]["calendar_days_elapsed"] == 15
    assert vt["risk"]["halted"] is False

    # The halted account surfaces its kill-switch and only ITS OWN blockers.
    tr = accounts["trend"]
    assert tr["risk"]["halted"] is True
    assert "daily loss" in tr["risk"]["reason"]
    assert tr["clock"]["blockers"] == ["trend: only 3 completed run(s) this week (< 4)"]

    # Crypto accounts carry the restarted clock and the thinner tier.
    cv = accounts["crypto_voltarget"]
    assert cv["validation_tier"] == "Probable"
    assert cv["clock"]["paper_start_date"] == "2026-07-22"
    assert "restarted" in cv["clock"]["start_note"]
    # An account with no history reports None rather than a fabricated zero.
    assert accounts["crypto_trend"]["latest_equity"] is None
    assert accounts["crypto_trend"]["snapshot_count"] == 0


def test_runs_are_newest_first_with_stages_orders_and_aborts(populated_tree: Path) -> None:
    body = _client(populated_tree).get("/api/runs").json()
    stamps = [r["timestamp"] for r in body["runs"]]
    assert stamps == sorted(stamps, reverse=True)
    # The corrupt report is skipped rather than raising.
    assert body["count"] == 4

    by_id = {r["run_id"]: r for r in body["runs"]}
    vt = by_id["run_voltarget_20260724T140007Z"]
    assert vt["dry_run"] is False
    assert vt["equity"] == pytest.approx(98821.82)
    assert vt["target_weights"] == {"SPY": pytest.approx(0.85715659109397)}
    assert vt["est_turnover"] == pytest.approx(0.0799)
    assert vt["min_trade_frac"] == pytest.approx(0.01)
    assert [s["stage"] for s in vt["stages"]] == ["risk_state", "submit"]
    assert all(s["ok"] for s in vt["stages"])
    assert vt["submitted_orders"][0]["symbol"] == "SPY"
    assert vt["submitted_orders"][0]["status"] == "filled"
    assert vt["intents"][0]["side"] == "sell"

    aborted = by_id["run_trend_20260722T140028Z"]
    assert aborted["aborted"] is True
    assert aborted["abort_stage"] == "health"
    assert "FREEZE_STALE_DATA" in aborted["abort_reason"]
    assert aborted["stages"][0]["ok"] is False


def test_runs_label_filter_and_limit(populated_tree: Path) -> None:
    client = _client(populated_tree)
    trend = client.get("/api/runs?label=trend").json()
    assert {r["strategy"] for r in trend["runs"]} == {"trend"}
    # `run_trend_*` must not absorb `run_crypto_trend_*` (nor the reverse).
    assert all("crypto" not in r["run_id"] for r in trend["runs"])

    limited = client.get("/api/runs?limit=1").json()
    assert limited["count"] == 1


def test_unknown_label_is_an_empty_answer_not_an_error(populated_tree: Path) -> None:
    body = _client(populated_tree).get("/api/runs?label=nope").json()
    assert body["count"] == 0 and body["runs"] == []
    assert "unknown account" in body["note"]


def test_divergence_series_carries_verdicts_excluded_tail_and_corrections(
    populated_tree: Path,
) -> None:
    body = _client(populated_tree).get("/api/divergence?label=trend").json()
    assert [w["label"] for w in body["weeks"]] == ["trend"]
    week = body["weeks"][0]
    assert week["week_ending"] == "2026-07-24"
    assert week["divergence_bps"] == pytest.approx(-6.06)
    assert week["verdict"] == "TRACKING"
    assert week["threshold_bps"] == pytest.approx(50.0)
    assert week["excluded_tail_days"] == ["2026-07-24"]
    assert week["window_start"] == "2026-07-16"
    assert week["structural_note"] == "dividend drag note"

    # The published/corrected pair is quoted, with a pointer to the ruling.
    correction = next(c for c in body["corrections"] if c["label"] == "trend")
    assert correction["week_ending"] == "2026-07-24"
    assert correction["published_divergence_bps"] == pytest.approx(-54.33)
    assert correction["published_verdict"] == "DIVERGING"
    assert correction["corrected_divergence_bps"] == pytest.approx(-6.06)
    assert correction["corrected_verdict"] == "TRACKING"
    assert "decisions.md" in correction["reference"]


def test_divergence_correction_for_crypto_voltarget_is_voided_not_a_number(
    populated_tree: Path,
) -> None:
    body = _client(populated_tree).get("/api/divergence?label=crypto_voltarget").json()
    correction = next(c for c in body["corrections"] if c["label"] == "crypto_voltarget")
    assert correction["published_divergence_bps"] == pytest.approx(91.24)
    assert correction["corrected_verdict"] == "VOIDED"
    assert correction["corrected_divergence_bps"] is None
    assert "PARTIAL" in correction["cause"]


def test_equity_points_carry_provenance_and_counts(populated_tree: Path) -> None:
    body = _client(populated_tree).get("/api/equity?label=crypto_voltarget").json()
    series = body["series"][0]
    assert series["asset_class"] == "crypto"
    provenances = [p["provenance"] for p in series["points"]]
    # 14:00Z crypto mark == the leaked equity task; 00:30Z == on schedule; 05:43Z == catch-up.
    assert provenances == [PROVENANCE_LEAKED, PROVENANCE_ON_SCHEDULE, PROVENANCE_CATCH_UP]
    assert series["provenance_counts"] == {
        PROVENANCE_LEAKED: 1, PROVENANCE_ON_SCHEDULE: 1, PROVENANCE_CATCH_UP: 1,
    }
    assert all(p["provenance_rationale"] for p in series["points"])


def test_risk_reports_limits_per_asset_class_and_drawdown_headroom(
    populated_tree: Path,
) -> None:
    body = _client(populated_tree).get("/api/risk").json()
    accounts = {a["label"]: a for a in body["accounts"]}

    vt = accounts["voltarget"]
    assert vt["limits"]["max_drawdown_kill"] == pytest.approx(0.25)
    assert vt["limits"]["max_daily_loss"] == pytest.approx(0.03)
    assert vt["limits_source"] == "risk.yaml"
    assert vt["peak_equity"] == pytest.approx(99759.12)
    assert vt["latest_equity"] == pytest.approx(98821.82)
    expected_dd = 98821.82 / 99759.12 - 1.0
    assert vt["current_drawdown"] == pytest.approx(expected_dd)
    assert vt["drawdown_headroom"] == pytest.approx(0.25 - abs(expected_dd))

    # Crypto reads the wider crypto yaml.
    cv = accounts["crypto_voltarget"]
    assert cv["limits"]["max_drawdown_kill"] == pytest.approx(0.50)
    assert cv["limits_source"] == "crypto_risk.yaml"

    assert accounts["trend"]["kill_switch"]["halted"] is True
    # No history -> unknown, stated as such.
    assert accounts["crypto_trend"]["current_drawdown"] is None
    assert "unknown" in accounts["crypto_trend"]["note"]


def test_timeline_merges_all_sources_newest_first(populated_tree: Path) -> None:
    body = _client(populated_tree).get("/api/timeline").json()
    kinds = {e["kind"] for e in body["events"]}
    assert kinds == {"order", "alert", "weekly_verdict", "decision"}

    dated = [e["at"] for e in body["events"] if e["at"]]
    assert dated == sorted(dated, reverse=True)

    alert = next(e for e in body["events"] if e["kind"] == "alert" and e["level"] == "WARNING")
    assert alert["label"] == "trend"  # strategy attribution preserved
    order = next(e for e in body["events"] if e["kind"] == "order")
    assert order["label"] in {"voltarget", "crypto_voltarget"}
    verdict = next(e for e in body["events"] if e["kind"] == "weekly_verdict")
    assert "TRACKING" in verdict["title"]
    assert any(e["kind"] == "decision" and "Glass Box" in e["title"] for e in body["events"])


def test_ignored_inputs_names_feeds_read_and_refused(populated_tree: Path) -> None:
    body = _client(populated_tree).get("/api/ignored-inputs").json()
    assert body["statement"]
    read_names = " ".join(r["name"] for r in body["reads"]).lower()
    # Two cross-validated EOD feeds, named.
    assert "tiingo" in read_names and "alpaca" in read_names
    assert any("cross-check" in r["role"] or "cross" in r["rationale"].lower()
               for r in body["reads"])
    ignored = " ".join(i["name"] for i in body["ignores"]).lower()
    for refused in ("news", "earnings", "sentiment", "intraday"):
        assert refused in ignored
    assert all(i["rationale"] for i in body["ignores"])


# --------------------------------------------------------------------------- #
# Empty tree: no 500s anywhere                                                #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("endpoint", ALL_ENDPOINTS)
def test_endpoint_is_an_explicit_empty_model_on_an_empty_tree(
    tmp_path: Path, endpoint: str
) -> None:
    empty = tmp_path / "nothing"
    empty.mkdir()
    response = _client(empty).get(endpoint)
    assert response.status_code == 200, response.text
    RESPONSE_MODELS[endpoint].model_validate(response.json())


def test_empty_tree_reports_empty_collections_and_says_so(tmp_path: Path) -> None:
    empty = tmp_path / "nothing"
    empty.mkdir()
    client = _client(empty)

    runs = client.get("/api/runs").json()
    assert runs["runs"] == [] and runs["count"] == 0 and runs["note"]

    div = client.get("/api/divergence").json()
    assert div["weeks"] == [] and div["note"]

    eq = client.get("/api/equity").json()
    assert all(s["points"] == [] for s in eq["series"]) and eq["note"]

    tl = client.get("/api/timeline").json()
    assert tl["events"] == [] and tl["note"]

    dec = client.get("/api/decisions").json()
    assert dec["entries"] == [] and dec["note"]

    # Overview still enumerates the roster, with unknown values as None.
    ov = client.get("/api/overview").json()
    assert len(ov["accounts"]) == 4
    assert all(a["latest_equity"] is None for a in ov["accounts"])
    assert all(a["clock"] is None for a in ov["accounts"])
    assert all(a["risk"]["halted"] is False for a in ov["accounts"])

    # Risk still enumerates the roster; limits fall back to empty, not invented.
    risk = client.get("/api/risk").json()
    assert len(risk["accounts"]) == 4
    assert all(a["limits"]["max_drawdown_kill"] is None for a in risk["accounts"])
    assert all("absent" in a["limits_source"] for a in risk["accounts"])

    # Static content is available with no artifacts at all.
    assert client.get("/api/ignored-inputs").json()["ignores"]


def test_narrate_missing_run_is_404_not_500(tmp_path: Path) -> None:
    empty = tmp_path / "nothing"
    empty.mkdir()
    response = _client(empty).get("/api/runs/run_nope_1/narrate")
    assert response.status_code == 404


def test_run_id_cannot_traverse_out_of_the_reports_directory(populated_tree: Path) -> None:
    for hostile in ("../../../etc/passwd", "..%2F..%2Fsecrets", "run_x/../../y"):
        response = _client(populated_tree).get(f"/api/runs/{hostile}/narrate")
        assert response.status_code in {404, 400}
        assert response.status_code != 500


# --------------------------------------------------------------------------- #
# Provenance classification                                                   #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("stamp", "asset_class", "expected"),
    [
        # The spec's three anchor cases.
        ("2026-07-24 14:00:18", "us_equity", PROVENANCE_ON_SCHEDULE),
        ("2026-07-19 05:17:33", "crypto", PROVENANCE_CATCH_UP),
        ("2026-07-21 14:00:17", "crypto", PROVENANCE_LEAKED),
        # Boundaries and the real record's other shapes.
        ("2026-07-23 00:30:09", "crypto", PROVENANCE_ON_SCHEDULE),
        ("2026-07-16 15:09:32", "us_equity", PROVENANCE_CATCH_UP),
        ("2026-07-16 15:09:39", "crypto", PROVENANCE_LEAKED),
        ("2026-07-09 17:54:20", "us_equity", PROVENANCE_CATCH_UP),
        # Midnight wrap: 23:55 UTC is 35 minutes before the 00:30 crypto run.
        ("2026-07-23 23:55:00", "crypto", PROVENANCE_CATCH_UP),
        ("2026-07-23 00:05:00", "crypto", PROVENANCE_ON_SCHEDULE),
    ],
)
def test_classify_mark(stamp: str, asset_class: str, expected: str) -> None:
    assert classify_mark(datetime.fromisoformat(stamp), asset_class) == expected


def test_equity_mark_at_1400_is_on_schedule_but_crypto_mark_at_1400_is_leaked() -> None:
    """The same clock time means different things for the two schedules."""
    at_1400 = datetime(2026, 7, 24, 14, 0, 18, tzinfo=UTC)
    assert classify_mark(at_1400, "us_equity") == PROVENANCE_ON_SCHEDULE
    assert classify_mark(at_1400, "crypto") == PROVENANCE_LEAKED


# --------------------------------------------------------------------------- #
# decisions.md parsing                                                        #
# --------------------------------------------------------------------------- #

def test_decisions_parser_handles_the_real_file() -> None:
    """Parsed against the actual repo file, not a stand-in."""
    real = PROJECT_ROOT / "docs" / "decisions.md"
    assert real.exists(), "docs/decisions.md is expected in this repo"
    entries = read_decisions(real)

    assert len(entries) >= 8
    # Every entry has a title; the preamble is not an entry.
    assert all(e["title"] for e in entries)
    assert not any("Decision log" == e["title"] for e in entries)
    # The real file uses an em dash after an ISO date.
    dated = [e for e in entries if e["date"] is not None]
    assert len(dated) == len(entries)
    assert all(isinstance(e["date"], date) for e in dated)
    # Newest-first ordering in the file is preserved as document order.
    assert dated[0]["date"] >= dated[-1]["date"]
    # Bodies carry real prose and never keep the trailing separator.
    assert all(e["body"].strip() for e in entries)
    assert not any(e["body"].rstrip().endswith("---") for e in entries)
    # The scheduler entry is present and its body mentions its mechanism.
    sched = next(e for e in entries if "Scheduler catch-up" in e["title"])
    assert "StartWhenAvailable" in sched["body"]


def test_decisions_parser_tolerates_ascii_dash_and_missing_date() -> None:
    entries = parse_decisions(
        "# Log\n\npreamble\n\n---\n\n"
        "## 2026-07-25 - ASCII dash entry\n\nbody one\n\n---\n\n"
        "## Untitled with no date\n\nbody two\n"
    )
    assert [e["title"] for e in entries] == ["ASCII dash entry", "Untitled with no date"]
    assert entries[0]["date"] == date(2026, 7, 25)
    assert entries[1]["date"] is None
    assert entries[0]["body"] == "body one"


def test_decisions_parser_ignores_h3_subheadings() -> None:
    entries = parse_decisions(
        "## 2026-07-25 — Entry\n\n### Not an entry\n\nbody\n"
    )
    assert len(entries) == 1
    assert "### Not an entry" in entries[0]["body"]


def test_decisions_endpoint_exposes_dates_titles_bodies(populated_tree: Path) -> None:
    body = _client(populated_tree).get("/api/decisions").json()
    assert body["count"] == 2
    first = body["entries"][0]
    assert first["date"] == "2026-07-25"
    assert first["title"] == "Glass Box design ruling"
    assert "template-bound" in first["body"]


# --------------------------------------------------------------------------- #
# Read-only proof                                                             #
# --------------------------------------------------------------------------- #

def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """Every file's (size, mtime_ns) under ``root``."""
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_the_full_endpoint_suite_changes_no_file_on_disk(populated_tree: Path) -> None:
    before = _snapshot(populated_tree)
    assert before, "fixture tree should not be empty"

    client = _client(populated_tree)
    for endpoint in ALL_ENDPOINTS:
        assert client.get(endpoint).status_code == 200
    # Include the parameterised and per-run paths in the proof.
    for label in ("voltarget", "trend", "crypto_trend", "crypto_voltarget"):
        assert client.get(f"/api/runs?label={label}").status_code == 200
        assert client.get(f"/api/equity?label={label}").status_code == 200
        assert client.get(f"/api/divergence?label={label}").status_code == 200
    for run in client.get("/api/runs").json()["runs"]:
        assert client.get(f"/api/runs/{run['run_id']}/narrate").status_code == 200

    after = _snapshot(populated_tree)
    assert after == before, "the Glass Box must not create, delete, or modify any file"


def test_glassbox_package_does_not_import_the_broker(populated_tree: Path) -> None:
    """The read-only surface must not be able to reach the trading client."""
    import quantlab.glassbox.app as gb_app
    import quantlab.glassbox.narrate as gb_narrate
    import quantlab.glassbox.readers as gb_readers

    for module in (gb_app, gb_readers, gb_narrate):
        source = Path(module.__file__ or "").read_text(encoding="utf-8")
        assert "quantlab.broker" not in source
        assert "AlpacaTradingClient" not in source
