"""The completeness gate: does a built site actually contain the data it claims?

This exists because of a specific failure. On 2026-07-26 `verify-dist` passed a build with
no snapshot in it, because a gate that only searches for forbidden content finds nothing
wrong with an empty directory — and the deploy that followed served a working shell with
zero figures. Every test here is a restatement of that lesson: absence of poison is not
presence of food.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from quantlab.glassbox.completeness import (
    DEFAULT_MAX_AGE_DAYS,
    MIN_ENDPOINTS,
    check_content,
)
from quantlab.glassbox.verify_dist import verify_dist

NOW = datetime(2026, 7, 26, 18, 0, 0, tzinfo=UTC)


def _good_manifest(endpoints: int = 85, generated: datetime | None = None) -> dict[str, object]:
    stamp = (generated or NOW - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    return {
        "generated_at": stamp,
        "git_commit": "abc1234",
        "quantlab_version": "1.0.0",
        "endpoint_count": endpoints,
        "endpoints": [
            {"key": f"/api/e{i}", "file": f"api-e{i}.json", "path": f"/api/e{i}",
             "params": {}, "status": 200, "bytes": 10}
            for i in range(endpoints)
        ],
    }


def _build_dist(
    tmp_path: Path,
    *,
    manifest: dict[str, object] | None | str = "default",
    endpoint_files: int | None = None,
    accounts: list[dict[str, object]] | None = None,
    entry_js: bool = True,
    entry_ref: bool = True,
) -> Path:
    """Assemble a dist tree. Every knob corresponds to one way a build can be wrong."""
    dist = tmp_path / "dist"
    snap = dist / "snapshot"
    snap.mkdir(parents=True)
    (dist / "assets").mkdir(parents=True)

    resolved = _good_manifest() if manifest == "default" else manifest
    if resolved is not None:
        text = resolved if isinstance(resolved, str) else json.dumps(resolved)
        (snap / "manifest.json").write_text(text, encoding="utf-8")

    n_files = endpoint_files if endpoint_files is not None else (
        resolved.get("endpoint_count", 0) if isinstance(resolved, dict) else 0
    )
    # api-overview.json counts toward the total, so emit it plus n-1 filler captures.
    if isinstance(n_files, int) and n_files > 0:
        default_accounts = [
            {"label": "voltarget", "latest_equity": 98821.82},
            {"label": "trend", "latest_equity": 98147.57},
        ]
        (snap / "api-overview.json").write_text(
            json.dumps({"accounts": default_accounts if accounts is None else accounts}),
            encoding="utf-8",
        )
        for i in range(n_files - 1):
            (snap / f"api-e{i}.json").write_text("{}", encoding="utf-8")
    elif accounts is not None:
        (snap / "api-overview.json").write_text(
            json.dumps({"accounts": accounts}), encoding="utf-8"
        )

    if entry_js:
        (dist / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    ref = '<script type="module" src="/assets/index-abc123.js"></script>' if entry_ref else ""
    (dist / "index.html").write_text(
        f"<!doctype html><title>Glass Box</title>{ref}<div id=root></div>",
        encoding="utf-8",
    )
    return dist


def _named(report: object, name: str) -> object:
    return next(c for c in report.checks if c.name == name)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# The good case                                                               #
# --------------------------------------------------------------------------- #

def test_a_complete_dist_passes(tmp_path: Path) -> None:
    report = check_content(_build_dist(tmp_path), now=NOW)
    assert report.passed, report.render()
    assert len(report.checks) == 5
    assert all(c.passed for c in report.checks)
    assert "CONTENT PASS" in report.render()


def test_every_assertion_is_named_in_the_report(tmp_path: Path) -> None:
    """A reader must be able to see WHICH assertions ran, not only which failed."""
    report = check_content(_build_dist(tmp_path), now=NOW)
    names = {c.name for c in report.checks}
    assert names == {
        "manifest_present", "endpoint_count", "manifest_freshness",
        "overview_has_data", "entry_bundle",
    }
    rendered = report.render()
    for name in names:
        assert name in rendered
    # Each check states its evidence, not just a verdict.
    assert all(c.detail for c in report.checks)


# --------------------------------------------------------------------------- #
# The failure that caused this module to exist                                #
# --------------------------------------------------------------------------- #

def test_a_dist_with_no_snapshot_fails(tmp_path: Path) -> None:
    """THE regression. This exact build passed the old gate and was deployed."""
    dist = _build_dist(tmp_path, manifest=None, endpoint_files=0)
    report = check_content(dist, now=NOW)

    assert report.passed is False
    failed = {c.name for c in report.failures}
    assert "manifest_present" in failed
    assert "overview_has_data" in failed
    rendered = report.render()
    assert "CONTENT FAIL" in rendered
    assert "Re-run the snapshot" in rendered


def test_the_whole_gate_fails_on_a_data_less_dist(tmp_path: Path) -> None:
    """End-to-end: verify_dist must now refuse it, not just the content sub-report."""
    dist = _build_dist(tmp_path, manifest=None, endpoint_files=0)
    result = verify_dist(dist, env_path=tmp_path / "absent.env", now=NOW)

    # No forbidden content — an empty build has nothing to find. That is the point.
    assert result.report.passed is True
    assert result.content.passed is False
    assert result.passed is False
    rendered = result.render()
    assert "DIST FAIL (missing content)" in rendered
    assert "do not deploy" in rendered.lower()


# --------------------------------------------------------------------------- #
# Individual assertions                                                       #
# --------------------------------------------------------------------------- #

def test_empty_accounts_fail(tmp_path: Path) -> None:
    dist = _build_dist(tmp_path, accounts=[])
    report = check_content(dist, now=NOW)
    assert report.passed is False
    check = _named(report, "overview_has_data")
    assert check.passed is False  # type: ignore[attr-defined]
    assert "no accounts" in check.detail  # type: ignore[attr-defined]


def test_accounts_with_only_null_equity_fail(tmp_path: Path) -> None:
    """A roster with no figures is the shape an empty artifact tree produces."""
    dist = _build_dist(
        tmp_path,
        accounts=[{"label": "voltarget", "latest_equity": None},
                  {"label": "trend", "latest_equity": None}],
    )
    report = check_content(dist, now=NOW)
    assert report.passed is False
    assert _named(report, "overview_has_data").passed is False  # type: ignore[attr-defined]


def test_one_real_equity_figure_is_enough(tmp_path: Path) -> None:
    dist = _build_dist(
        tmp_path,
        accounts=[{"label": "voltarget", "latest_equity": 100.0},
                  {"label": "trend", "latest_equity": None}],
    )
    report = check_content(dist, now=NOW)
    assert _named(report, "overview_has_data").passed is True  # type: ignore[attr-defined]


def test_a_thirty_day_old_manifest_fails(tmp_path: Path) -> None:
    dist = _build_dist(tmp_path, manifest=_good_manifest(generated=NOW - timedelta(days=30)))
    report = check_content(dist, now=NOW)
    assert report.passed is False
    check = _named(report, "manifest_freshness")
    assert check.passed is False  # type: ignore[attr-defined]
    assert "limit 14d" in check.detail  # type: ignore[attr-defined]


def test_max_age_days_is_configurable(tmp_path: Path) -> None:
    dist = _build_dist(tmp_path, manifest=_good_manifest(generated=NOW - timedelta(days=30)))
    assert check_content(dist, now=NOW, max_age_days=60).passed is True
    assert check_content(dist, now=NOW, max_age_days=14).passed is False
    assert DEFAULT_MAX_AGE_DAYS == 14


def test_a_manifest_just_inside_the_window_passes(tmp_path: Path) -> None:
    dist = _build_dist(
        tmp_path, manifest=_good_manifest(generated=NOW - timedelta(days=13, hours=23))
    )
    assert _named(check_content(dist, now=NOW), "manifest_freshness").passed is True  # type: ignore[attr-defined]


def test_too_few_endpoints_fails(tmp_path: Path) -> None:
    dist = _build_dist(tmp_path, manifest=_good_manifest(endpoints=5))
    report = check_content(dist, now=NOW)
    assert report.passed is False
    check = _named(report, "endpoint_count")
    assert check.passed is False  # type: ignore[attr-defined]
    assert f"minimum {MIN_ENDPOINTS}" in check.detail  # type: ignore[attr-defined]


def test_declared_count_must_match_the_files_on_disk(tmp_path: Path) -> None:
    """A truncated write leaves a manifest promising more than it delivered."""
    dist = _build_dist(tmp_path, manifest=_good_manifest(85), endpoint_files=40)
    report = check_content(dist, now=NOW)
    assert report.passed is False
    check = _named(report, "endpoint_count")
    assert check.passed is False  # type: ignore[attr-defined]
    assert "on disk" in check.detail  # type: ignore[attr-defined]


def test_declared_count_must_match_the_endpoints_list(tmp_path: Path) -> None:
    manifest = _good_manifest(85)
    manifest["endpoint_count"] = 90  # disagrees with len(endpoints)
    dist = _build_dist(tmp_path, manifest=manifest, endpoint_files=85)
    report = check_content(dist, now=NOW)
    assert _named(report, "endpoint_count").passed is False  # type: ignore[attr-defined]


def test_unparseable_manifest_fails_without_crashing(tmp_path: Path) -> None:
    dist = _build_dist(tmp_path, manifest="{not json", endpoint_files=85)
    report = check_content(dist, now=NOW)
    assert report.passed is False
    assert _named(report, "manifest_present").passed is False  # type: ignore[attr-defined]
    # Downstream checks are reported as unmet rather than crashing, so one run of the
    # gate lists every problem at once.
    assert "not checked" in _named(report, "endpoint_count").detail  # type: ignore[attr-defined]


def test_unparseable_timestamp_fails(tmp_path: Path) -> None:
    manifest = _good_manifest()
    manifest["generated_at"] = "not-a-date"
    dist = _build_dist(tmp_path, manifest=manifest)
    report = check_content(dist, now=NOW)
    assert _named(report, "manifest_freshness").passed is False  # type: ignore[attr-defined]


def test_missing_entry_bundle_fails(tmp_path: Path) -> None:
    """index.html referencing a script that is not there is a broken deploy."""
    dist = _build_dist(tmp_path, entry_js=False)
    report = check_content(dist, now=NOW)
    assert report.passed is False
    check = _named(report, "entry_bundle")
    assert check.passed is False  # type: ignore[attr-defined]
    assert "absent" in check.detail  # type: ignore[attr-defined]


def test_html_with_no_entry_script_fails(tmp_path: Path) -> None:
    dist = _build_dist(tmp_path, entry_ref=False)
    report = check_content(dist, now=NOW)
    assert _named(report, "entry_bundle").passed is False  # type: ignore[attr-defined]


def test_missing_index_html_fails(tmp_path: Path) -> None:
    dist = _build_dist(tmp_path)
    (dist / "index.html").unlink()
    report = check_content(dist, now=NOW)
    check = _named(report, "entry_bundle")
    assert check.passed is False  # type: ignore[attr-defined]
    assert "index.html missing" in check.detail  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# The two gates stay independent                                              #
# --------------------------------------------------------------------------- #

def test_content_and_pattern_failures_are_reported_separately(tmp_path: Path) -> None:
    """They fail for different causes and must be readable independently."""
    dist = _build_dist(tmp_path, accounts=[])
    (dist / "assets" / "leak.js").write_text('const a="PA3XKLM99Q1";', encoding="utf-8")

    result = verify_dist(dist, env_path=tmp_path / "absent.env", now=NOW)
    assert result.content.passed is False
    assert result.report.passed is False
    rendered = result.render()
    assert "DIST FAIL (missing content, forbidden pattern)" in rendered
    # Both sections appear, each with its own heading.
    assert "CONTENT COMPLETENESS" in rendered
    assert "FORBIDDEN PATTERNS" in rendered


def test_a_complete_and_clean_dist_passes_the_whole_gate(tmp_path: Path) -> None:
    result = verify_dist(_build_dist(tmp_path), env_path=tmp_path / "absent.env", now=NOW)
    assert result.passed
    assert "DIST PASS" in result.render()
    assert "CONTENT PASS" in result.render()


def test_verify_dist_freshness_follows_the_injected_clock(tmp_path: Path) -> None:
    """``verify_dist`` must gate freshness against the instant it is GIVEN, not the wall clock.

    Regression for a defect that turned the suite red with no code change on 2026-08-09:
    ``verify_dist`` had no ``now``, so the fixture manifest below (stamped two hours before
    the hardcoded ``NOW`` of 2026-07-26) silently aged past ``DEFAULT_MAX_AGE_DAYS`` and the
    only failing assertion was a clock. Both directions are pinned here, so neither an
    unplumbed clock nor a disabled freshness gate can pass.
    """
    dist = _build_dist(tmp_path)
    fresh = verify_dist(dist, env_path=tmp_path / "absent.env", now=NOW)
    assert fresh.content.passed is True
    assert fresh.passed is True

    # One second past the limit, the same bytes must fail -- and fail on freshness alone.
    stale_at = NOW + timedelta(days=DEFAULT_MAX_AGE_DAYS, seconds=1)
    stale = verify_dist(dist, env_path=tmp_path / "absent.env", now=stale_at)
    assert stale.passed is False
    assert stale.report.passed is True  # nothing forbidden; only the age changed
    failed = [c.name for c in stale.content.checks if not c.passed]
    assert failed == ["manifest_freshness"]


def test_the_gate_still_writes_nothing(tmp_path: Path) -> None:
    dist = _build_dist(tmp_path)
    before = {
        p.relative_to(dist).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(dist.rglob("*")) if p.is_file()
    }
    verify_dist(dist, env_path=tmp_path / "absent.env", now=NOW)
    after = {
        p.relative_to(dist).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(dist.rglob("*")) if p.is_file()
    }
    assert after == before


def test_freshness_uses_a_real_clock_by_default(tmp_path: Path) -> None:
    """Passing no `now` must use the current time, not a fixture default."""
    fresh = _build_dist(tmp_path, manifest=_good_manifest(generated=datetime.now(UTC)))
    assert _named(check_content(fresh), "manifest_freshness").passed is True  # type: ignore[attr-defined]


@pytest.mark.parametrize("equity", [0, 0.0, -1.5, 100])
def test_zero_and_negative_equity_still_count_as_data(tmp_path: Path, equity: float) -> None:
    """A halted account at zero is real data; only null means unknown."""
    dist = _build_dist(tmp_path, accounts=[{"label": "x", "latest_equity": equity}])
    assert _named(check_content(dist, now=NOW), "overview_has_data").passed is True  # type: ignore[attr-defined]


def test_a_boolean_is_not_an_equity_figure(tmp_path: Path) -> None:
    """`True` is an int in Python; a JSON bool must not satisfy the check."""
    dist = _build_dist(tmp_path, accounts=[{"label": "x", "latest_equity": True}])
    assert _named(check_content(dist, now=NOW), "overview_has_data").passed is False  # type: ignore[attr-defined]
