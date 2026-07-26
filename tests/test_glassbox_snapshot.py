"""Snapshot pipeline and the sanitization gate.

The gate tests are the important ones: a sanitizer that fails open is worse than no
sanitizer, because it produces a report that says PASS. Each forbidden pattern gets a
test that plants a match and asserts the whole snapshot aborts, and a test that the
report never echoes the thing it found.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from starlette.testclient import TestClient

from quantlab.glassbox.paths import GlassboxPaths
from quantlab.glassbox.sanitize import (
    ENV_SECRET_PATTERN_PREFIX,
    SanitizationError,
    load_env_secret_prefixes,
    redact,
    sanitize,
)
from quantlab.glassbox.snapshot import (
    MANIFEST_NAME,
    REPORT_NAME,
    canonical_key,
    capture,
    plan_requests,
    write_snapshot,
)

# --------------------------------------------------------------------------- #
# Fixture artifact tree                                                       #
# --------------------------------------------------------------------------- #

RUN: dict[str, Any] = {
    "strategy": "voltarget",
    "dry_run": False,
    "timestamp": "2026-07-24T14:00:07.519467Z",
    "aborted": False,
    "equity": 98821.82,
    "target_weights": {"SPY": 0.857},
    "plan": {
        "equity": 98821.82, "cash": 14116.04,
        "current_weights": {"SPY": 0.9371}, "target_weights": {"SPY": 0.857},
        "intents": [{"symbol": "SPY", "side": "sell", "notional": 7897.07,
                     "current_w": 0.9371, "target_w": 0.857}],
        "skipped": [], "est_turnover": 0.0799, "buy_scale": 1.0, "min_trade_frac": 0.01,
    },
    "submitted_orders": [], "no_trades": False,
    "stages": [{"stage": "submit", "ok": True, "detail": "ok"}],
}


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    paper = root / "reports" / "paper"
    paper.mkdir(parents=True)
    (paper / "run_voltarget_20260724T140007Z.json").write_text(
        json.dumps(RUN), encoding="utf-8")

    weekly = root / "reports" / "weekly"
    weekly.mkdir(parents=True)
    (weekly / "week_20260724.json").write_text(json.dumps({
        "generated_at": "2026-07-24T21:00:03Z", "week_ending": "2026-07-24",
        "divergence_threshold_bps": 50.0,
        "accounts": [{"label": "voltarget", "available": True,
                      "asset_class": "us_equity", "verdict": "TRACKING",
                      "divergence_bps": -6.06, "excluded_tail_days": [],
                      "window": {"start": "2026-07-20", "end": "2026-07-24",
                                 "n_snapshots": 5, "insufficient": False},
                      "cumulative": {"cumulative_divergence_bps": 27.3,
                                     "structural_drift_note": "note"}}],
        "readiness": {"clocks": [{"asset_class": "us_equity",
                                  "paper_start_date": "2026-07-09",
                                  "calendar_days_elapsed": 15, "target_days": 90,
                                  "pct_complete": 16.7, "start_note": None}],
                      "blockers": []},
    }), encoding="utf-8")

    data = root / "data"
    data.mkdir(parents=True)
    pd.DataFrame({"timestamp": pd.to_datetime(["2026-07-24 14:00:07"]),
                  "equity": [98821.82]}).to_parquet(
        data / "equity_history_voltarget.parquet", index=False)

    cfg = root / "config"
    cfg.mkdir(parents=True)
    (cfg / "risk.yaml").write_text("max_drawdown_kill: 0.25\n", encoding="utf-8")
    docs = root / "docs"
    docs.mkdir(parents=True)
    (docs / "decisions.md").write_text(
        "# Log\n\n---\n\n## 2026-07-25 — Entry\n\nbody\n", encoding="utf-8")
    return root


def _no_env(tmp_path: Path) -> Path:
    """A path guaranteed not to exist, so the env check is skipped explicitly."""
    return tmp_path / "absent.env"


# --------------------------------------------------------------------------- #
# canonical_key — the contract the frontend mirrors                           #
# --------------------------------------------------------------------------- #

def test_canonical_key_sorts_params_and_drops_limit() -> None:
    assert canonical_key("/api/overview") == "/api/overview"
    assert canonical_key("/api/overview", {}) == "/api/overview"
    # limit is excluded: snapshots are captured at full depth.
    assert canonical_key("/api/runs", {"limit": "5000"}) == "/api/runs"
    assert canonical_key("/api/runs", {"label": "trend", "limit": "50"}) == (
        "/api/runs?label=trend"
    )
    # Order-independent.
    assert canonical_key("/api/x", {"b": "2", "a": "1"}) == canonical_key(
        "/api/x", {"a": "1", "b": "2"}
    )
    assert canonical_key("/api/x", {"a": "1", "b": "2"}) == "/api/x?a=1&b=2"
    # Empty values are dropped rather than producing a dangling `=`.
    assert canonical_key("/api/x", {"label": ""}) == "/api/x"


# --------------------------------------------------------------------------- #
# Route enumeration                                                           #
# --------------------------------------------------------------------------- #

def test_plan_requests_enumerates_routes_from_the_app(tree: Path) -> None:
    from quantlab.glassbox.app import create_app

    paths = GlassboxPaths.from_root(tree)
    app = create_app(paths)
    requests = plan_requests(paths, app)
    keys = {r.key for r in requests}

    # Every non-parameterised endpoint is present.
    for expected in ("/api/overview", "/api/risk", "/api/decisions",
                     "/api/ignored-inputs", "/api/runs", "/api/timeline",
                     "/api/divergence", "/api/equity"):
        assert expected in keys, expected

    # Label variants for the label-filtered endpoints.
    assert "/api/divergence?label=trend" in keys
    assert "/api/equity?label=crypto_voltarget" in keys
    assert "/api/runs?label=voltarget" in keys

    # Parameterised narration expanded over the run ids actually on disk.
    assert "/api/runs/run_voltarget_20260724T140007Z/narrate" in keys
    assert not any("{" in r.path for r in requests)

    # No duplicate keys: each snapshot file is written once.
    assert len(keys) == len(requests)


def test_plan_requests_is_empty_of_narrations_when_no_runs_exist(tmp_path: Path) -> None:
    from quantlab.glassbox.app import create_app

    empty = tmp_path / "empty"
    empty.mkdir()
    paths = GlassboxPaths.from_root(empty)
    requests = plan_requests(paths, create_app(paths))
    assert not any("narrate" in r.path for r in requests)
    # The fixed endpoints are still captured.
    assert "/api/overview" in {r.key for r in requests}


# --------------------------------------------------------------------------- #
# Capture + write                                                             #
# --------------------------------------------------------------------------- #

def test_capture_produces_a_document_per_endpoint_plus_a_manifest(tree: Path) -> None:
    documents, manifest, report = capture(
        GlassboxPaths.from_root(tree), env_path=_no_env(tree))

    assert report.passed
    assert MANIFEST_NAME in documents
    assert manifest.endpoint_count == len(manifest.endpoints)
    assert len(documents) == manifest.endpoint_count + 1  # + manifest itself
    assert manifest.quantlab_version
    assert manifest.generated_at.endswith("Z")
    # Every captured document is valid JSON.
    for name, text in documents.items():
        json.loads(text)
        assert name.endswith(".json")
    # Every manifest entry points at a document that exists, and succeeded.
    for entry in manifest.endpoints:
        assert entry.file in documents
        assert entry.status == 200


def test_write_snapshot_writes_files_and_a_report(tree: Path) -> None:
    out = tree / "out"
    result = write_snapshot(GlassboxPaths.from_root(tree), env_path=_no_env(tree)) \
        if False else write_snapshot(out, GlassboxPaths.from_root(tree),
                                     env_path=_no_env(tree))
    assert result.report.passed
    assert (out / MANIFEST_NAME).is_file()
    # The report is an operator artifact and must NOT land in the published tree: it
    # would be served publicly, and it lists the pattern names the gate searches for
    # (including "authorization_header"), which made verify-dist fail on its own report.
    assert not (out / REPORT_NAME).exists()
    written_report = Path(result.report_path)
    assert written_report.is_file()
    assert "SANITIZATION REPORT" in written_report.read_text(encoding="utf-8")

    manifest = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    for entry in manifest["endpoints"]:
        assert (out / entry["file"]).is_file()


def test_write_snapshot_removes_stale_captures(tree: Path) -> None:
    """A dropped endpoint must not linger and be served as if it were current."""
    out = tree / "out"
    out.mkdir()
    stale = out / "api-endpoint-that-no-longer-exists.json"
    stale.write_text('{"stale": true}', encoding="utf-8")

    write_snapshot(out, GlassboxPaths.from_root(tree), env_path=_no_env(tree),
                   report_dir=tree / "reports")
    assert not stale.exists()


def test_snapshot_of_an_empty_tree_still_succeeds(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    out = tmp_path / "out"
    result = write_snapshot(out, GlassboxPaths.from_root(empty),
                            env_path=_no_env(tmp_path), report_dir=tmp_path / "reports")
    assert result.report.passed
    assert (out / MANIFEST_NAME).is_file()
    overview = json.loads((out / "api-overview.json").read_text(encoding="utf-8"))
    assert overview["accounts"]  # roster still enumerated


def test_capture_depth_never_exceeds_each_endpoints_declared_ceiling(tree: Path) -> None:
    """Regression: a limit above the endpoint's `le` yields 422, and a 422 body
    serialises to JSON that sits in the snapshot looking like data. The first run of
    this pipeline captured five such bodies."""
    from quantlab.glassbox.app import create_app

    paths = GlassboxPaths.from_root(tree)
    app = create_app(paths)
    requests = plan_requests(paths, app)

    with TestClient(app) as client:
        for request in requests:
            response = client.get(request.url)
            assert response.status_code == 200, f"{request.url} -> {response.status_code}"


def test_a_non_200_response_aborts_the_capture(tree: Path) -> None:
    """The guard, not just the constants, is what keeps a bad depth out of a snapshot."""
    import quantlab.glassbox.snapshot as snap

    original = dict(snap.DEPTH_BY_PATH)
    snap.DEPTH_BY_PATH["/api/runs"] = 999_999  # above the declared ceiling
    try:
        with pytest.raises(snap.SnapshotCaptureError) as excinfo:
            capture(GlassboxPaths.from_root(tree), env_path=_no_env(tree))
        assert "/api/runs" in str(excinfo.value)
        assert "422" in str(excinfo.value)
    finally:
        snap.DEPTH_BY_PATH.clear()
        snap.DEPTH_BY_PATH.update(original)


# --------------------------------------------------------------------------- #
# Redaction                                                                   #
# --------------------------------------------------------------------------- #

def test_windows_user_path_is_redacted_in_every_encoding() -> None:
    for original, expected in [
        (r"C:\Users\danmo\Dev\quantlab", r"<path>\Dev\quantlab"),
        (r"C:\\Users\\danmo\\Dev", r"<path>\\Dev"),          # JSON-escaped
        ("C:/Users/danmo/Dev", "<path>/Dev"),
        (r"D:\Users\someone\x", r"<path>\x"),
    ]:
        cleaned, performed = redact(original)
        assert cleaned == expected, original
        assert performed and performed[0][0] == "windows_user_path"


def test_posix_home_path_is_redacted() -> None:
    cleaned, performed = redact("/home/danmo/dev/quantlab")
    assert cleaned == "<path>/dev/quantlab"
    assert performed[0][0] == "posix_home_path"


def test_planted_path_is_redacted_and_reported(tmp_path: Path) -> None:
    documents = {"api-x.json": json.dumps({"note": r"failed at C:\\Users\\danmo\\x.log"})}
    clean, report = sanitize(documents, env_path=_no_env(tmp_path))

    assert report.passed
    assert "danmo" not in clean["api-x.json"]
    assert "<path>" in clean["api-x.json"]
    assert report.redaction_count == 1
    entry = report.redactions[0]
    assert entry.pattern == "windows_user_path"
    assert entry.location == "api-x.json"
    assert entry.replacement == "<path>"
    # The report records the replacement, never the original.
    assert "danmo" not in report.render()


def test_clean_fixture_passes_byte_identical(tmp_path: Path) -> None:
    documents = {
        "api-overview.json": json.dumps({"accounts": [{"label": "voltarget"}]}, indent=2),
        "api-risk.json": json.dumps({"accounts": []}, indent=2),
    }
    clean, report = sanitize(documents, env_path=_no_env(tmp_path))

    assert report.passed
    assert report.redactions == []
    assert clean == documents  # byte-identical: nothing was touched
    assert report.files_scanned == 2


# --------------------------------------------------------------------------- #
# Forbidden patterns — each one must abort the whole snapshot                  #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("pattern_name", "planted"),
    [
        ("alpaca_account_id", "account PA3XKLM99Q1 rebalanced"),
        ("email_address", "notify quant.lead@example.com on halt"),
        ("apca_api_header", "APCA-API-KEY-ID: PKLIVEKEY123"),
        ("authorization_header", "Authorization: Bearer abc.def.ghi"),
    ],
)
def test_planted_forbidden_pattern_fails_the_snapshot(
    tmp_path: Path, pattern_name: str, planted: str
) -> None:
    documents = {"api-x.json": json.dumps({"note": planted})}
    with pytest.raises(SanitizationError) as excinfo:
        sanitize(documents, env_path=_no_env(tmp_path))

    report = excinfo.value.report
    assert report.passed is False
    failing = {f.pattern for f in report.failures}
    assert pattern_name in failing
    record = next(f for f in report.forbidden if f.pattern == pattern_name)
    assert record.count >= 1
    assert record.locations == ["api-x.json"]
    assert "FAIL" in report.render()
    assert "Nothing was written" in report.render()


def test_a_planted_account_id_blocks_the_write_entirely(tree: Path) -> None:
    """The gate is a gate: a failure writes nothing, not even the clean files."""
    paper = tree / "reports" / "paper"
    poisoned = dict(RUN)
    poisoned["abort_reason"] = "account PA9ZZZZ0001 blocked"
    (paper / "run_trend_20260723T140016Z.json").write_text(
        json.dumps({**poisoned, "strategy": "trend"}), encoding="utf-8")

    out = tree / "out"
    with pytest.raises(SanitizationError):
        write_snapshot(out, GlassboxPaths.from_root(tree), env_path=_no_env(tree),
                       report_dir=tree / "reports")

    # Nothing at all was created.
    assert not out.exists() or list(out.iterdir()) == []


def test_prose_about_the_gate_does_not_trip_the_gate(tmp_path: Path) -> None:
    """This project documents its own security design, and that documentation is
    published through /api/decisions. Matching the bare header NAMES made the gate fail
    the build over its own decision log — so the patterns require a header with a value.
    """
    documents = {
        "api-decisions.json": json.dumps({
            "entries": [{
                "title": "Sanitization gate",
                "body": "FAILS on Alpaca account ids, any email address, "
                        "`APCA-API` / `Authorization` header names, and env prefixes.",
            }],
        }),
    }
    _clean, report = sanitize(documents, env_path=_no_env(tmp_path))
    assert report.passed, report.render()


def test_a_real_auth_header_with_a_value_still_fails(tmp_path: Path) -> None:
    for planted in (
        "APCA-API-KEY-ID: PKREALKEY0001",
        "APCA-API-SECRET-KEY=abcdef123456",
        "Authorization: Bearer eyJhbGciOi",
        'headers={"Authorization": "Basic dXNlcjpwYXNz"}',
    ):
        with pytest.raises(SanitizationError):
            sanitize({"api-x.json": planted}, env_path=_no_env(tmp_path))


def test_report_names_every_declared_check_even_when_it_passes(tmp_path: Path) -> None:
    """A reader must see WHICH checks ran, not only which ones fired."""
    _clean, report = sanitize({"api-x.json": "{}"}, env_path=_no_env(tmp_path))
    names = {f.pattern for f in report.forbidden}
    for expected in ("alpaca_account_id", "email_address", "apca_api_header",
                     "authorization_header"):
        assert expected in names
    rendered = report.render()
    assert "FORBIDDEN PATTERNS (zero matches required to pass)" in rendered
    assert "0  ok" in rendered


# --------------------------------------------------------------------------- #
# Env-secret check                                                            #
# --------------------------------------------------------------------------- #

def test_env_prefix_leak_fails_and_the_prefix_is_never_printed(tmp_path: Path) -> None:
    secret = "sk_live_ABCDEFGH1234567890"
    env = tmp_path / ".env"
    env.write_text(f"TIINGO_API_KEY={secret}\n", encoding="utf-8")

    documents = {"api-x.json": json.dumps({"leak": secret[:8] + "..."})}
    with pytest.raises(SanitizationError) as excinfo:
        sanitize(documents, env_path=env)

    report = excinfo.value.report
    assert f"{ENV_SECRET_PATTERN_PREFIX}:TIINGO_API_KEY" in {
        f.pattern for f in report.failures
    }
    rendered = report.render()
    # The KEY NAME is reportable; the secret and its prefix are not.
    assert "TIINGO_API_KEY" in rendered
    assert secret not in rendered
    assert secret[:8] not in rendered


def test_absent_env_is_reported_as_not_checked_not_as_a_pass(tmp_path: Path) -> None:
    """"0 matches" and "not checked" are different claims."""
    _clean, report = sanitize({"api-x.json": "{}"}, env_path=_no_env(tmp_path))
    assert report.env_checked is False
    assert report.env_note and "no .env" in report.env_note
    rendered = report.render()
    assert "NOT CHECKED" in rendered
    # Still an overall pass — nothing forbidden was found — but the gap is visible.
    assert report.passed


def test_short_env_values_are_skipped_to_avoid_false_positives(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("DEBUG=true\nMODE=x\nREAL_KEY=abcdefghij\n", encoding="utf-8")
    secrets = load_env_secret_prefixes(env)
    assert "REAL_KEY" in secrets.prefixes
    # "true" and "x" are too short to be searched for without matching prose.
    assert "DEBUG" not in secrets.prefixes
    assert "MODE" not in secrets.prefixes


def test_env_values_never_appear_on_the_report_object(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("ALPACA_API_KEY=PKTESTKEY123456\n", encoding="utf-8")
    _clean, report = sanitize({"api-x.json": "{}"}, env_path=env)
    dumped = report.model_dump_json()
    assert "PKTESTKEY" not in dumped
    assert "ALPACA_API_KEY" in dumped  # the name is fine
    assert report.env_checked


def test_redaction_runs_before_vetting(tmp_path: Path) -> None:
    """The text that would ship is the text that gets vetted."""
    documents = {"api-x.json": r"C:\\Users\\PA12345678\\file"}
    # The account-id pattern is inside the path segment that gets redacted away, so
    # after redaction there is nothing forbidden left to find.
    clean, report = sanitize(documents, env_path=_no_env(tmp_path))
    assert report.passed
    assert "PA12345678" not in clean["api-x.json"]


# --------------------------------------------------------------------------- #
# Real repo shape                                                             #
# --------------------------------------------------------------------------- #

def test_manifest_records_commit_version_and_iso_utc(tree: Path) -> None:
    _documents, manifest, _report = capture(
        GlassboxPaths.from_root(tree), env_path=_no_env(tree))
    assert manifest.git_commit
    # Parseable as an instant, and explicitly UTC.
    assert manifest.generated_at.endswith("Z")
    from datetime import datetime

    parsed = datetime.fromisoformat(manifest.generated_at.replace("Z", "+00:00"))
    assert parsed.date() >= date(2026, 1, 1)
