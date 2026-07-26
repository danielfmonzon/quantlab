"""`verify-dist`: the sanitization gate over an entire published site.

The snapshot gate vets the JSON it writes. This one vets what actually ships — compiled
JS, CSS, HTML, SVG, and anything a build tool or a human dropped into `public/`. A secret
can reach the public through an inlined constant or a stray file without ever passing
through the snapshot writer, so the two gates are not interchangeable and both are tested.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quantlab.glassbox.sanitize import (
    _ENV_NON_SECRET_KEYS,
    ENV_SECRET_PATTERN_PREFIX,
    is_secret_bearing,
    load_env_secret_prefixes,
)
from quantlab.glassbox.verify_dist import verify_dist


def _dist(tmp_path: Path, files: dict[str, str], binaries: tuple[str, ...] = ()) -> Path:
    root = tmp_path / "dist"
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for name in binaries:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    return root


CLEAN = {
    "index.html": "<!doctype html><title>Glass Box</title><div id=root></div>",
    "assets/index-abc123.js": 'const s="/snapshot";export{s};',
    "assets/index-abc123.css": ":root{--cream:#f7f2e9}",
    "snapshot/manifest.json": json.dumps({"generated_at": "2026-07-26T00:00:00Z"}),
    "snapshot/api-overview.json": json.dumps({"accounts": [{"label": "voltarget"}]}),
    "robots.txt": "User-agent: *\nAllow: /\n",
    "favicon.svg": '<svg xmlns="http://www.w3.org/2000/svg"><title>GB</title></svg>',
}


def _no_env(tmp_path: Path) -> Path:
    return tmp_path / "absent.env"


# --------------------------------------------------------------------------- #
# Clean dist passes                                                           #
# --------------------------------------------------------------------------- #

def test_clean_dist_passes(tmp_path: Path) -> None:
    dist = _dist(tmp_path, CLEAN)
    result = verify_dist(dist, env_path=_no_env(tmp_path))

    assert result.passed
    assert result.report.passed
    assert result.files_text == len(CLEAN)
    assert result.redactable_findings == []
    assert "DIST PASS" in result.render()


def test_binary_assets_are_skipped_and_counted(tmp_path: Path) -> None:
    """Coverage is stated rather than assumed: a skipped file is reported as skipped."""
    dist = _dist(tmp_path, CLEAN, binaries=("og-image.png", "favicon.ico"))
    result = verify_dist(dist, env_path=_no_env(tmp_path))

    assert result.passed
    assert result.files_binary_skipped == 2
    assert sorted(result.binary_names) == ["favicon.ico", "og-image.png"]
    rendered = result.render()
    assert "2 skipped" in rendered
    assert "og-image.png" in rendered


# --------------------------------------------------------------------------- #
# A planted secret in a bundle fails                                          #
# --------------------------------------------------------------------------- #

def test_planted_account_id_in_a_js_bundle_fails(tmp_path: Path) -> None:
    """The case the snapshot gate cannot catch: a secret inlined into compiled JS."""
    files = dict(CLEAN)
    files["assets/index-abc123.js"] = 'const acct="PA3XKLM99Q1";export{acct};'
    dist = _dist(tmp_path, files)

    result = verify_dist(dist, env_path=_no_env(tmp_path))

    assert result.passed is False
    failing = {f.pattern for f in result.report.failures}
    assert "alpaca_account_id" in failing
    record = next(f for f in result.report.forbidden if f.pattern == "alpaca_account_id")
    assert record.count == 1
    assert record.locations == ["assets/index-abc123.js"]
    rendered = result.render()
    assert "DIST FAIL" in rendered
    assert "do not deploy" in rendered.lower()


@pytest.mark.parametrize(
    ("pattern", "planted", "filename"),
    [
        ("email_address", "contact quant.lead@example.com", "index.html"),
        ("apca_api_header", 'APCA-API-KEY-ID: PKREAL01', "assets/index-abc123.js"),
        ("authorization_header", "Authorization: Bearer abc.def", "assets/index-abc123.css"),
        ("alpaca_account_id", "PA99887766", "snapshot/api-overview.json"),
        # An SVG is text and ships to the public like anything else.
        ("email_address", "<desc>me@example.org</desc>", "favicon.svg"),
    ],
)
def test_every_forbidden_pattern_fails_wherever_it_hides(
    tmp_path: Path, pattern: str, planted: str, filename: str
) -> None:
    files = dict(CLEAN)
    files[filename] = files.get(filename, "") + planted
    dist = _dist(tmp_path, files)

    result = verify_dist(dist, env_path=_no_env(tmp_path))
    assert result.passed is False
    assert pattern in {f.pattern for f in result.report.failures}


def test_documentation_of_the_gate_does_not_fail_the_build(tmp_path: Path) -> None:
    """The published decisions log describes the gate's own patterns by name."""
    files = dict(CLEAN)
    files["snapshot/api-decisions.json"] = json.dumps(
        {"body": "FAILS on `APCA-API` / `Authorization` header names."}
    )
    dist = _dist(tmp_path, files)
    result = verify_dist(dist, env_path=_no_env(tmp_path))
    assert result.passed, result.render()


def test_env_secret_leaked_into_a_bundle_fails_without_printing_it(tmp_path: Path) -> None:
    secret = "sk_live_ABCDEF1234567890"
    env = tmp_path / ".env"
    env.write_text(f"TIINGO_API_KEY={secret}\n", encoding="utf-8")

    files = dict(CLEAN)
    files["assets/index-abc123.js"] = f'const k="{secret[:8]}";export{{k}};'
    dist = _dist(tmp_path, files)

    result = verify_dist(dist, env_path=env)
    assert result.passed is False
    assert f"{ENV_SECRET_PATTERN_PREFIX}:TIINGO_API_KEY" in {
        f.pattern for f in result.report.failures
    }
    rendered = result.render()
    assert "TIINGO_API_KEY" in rendered  # the name is safe
    assert secret not in rendered
    assert secret[:8] not in rendered


# --------------------------------------------------------------------------- #
# Redactable content is a finding, not a silent fix                           #
# --------------------------------------------------------------------------- #

def test_a_leaked_local_path_is_reported_not_rewritten(tmp_path: Path) -> None:
    """These bytes are already written; the gate can only report, so it says so."""
    files = dict(CLEAN)
    files["assets/index-abc123.js"] = (
        'const p="C:' + chr(92) + chr(92) + 'Users' + chr(92) + chr(92) + 'danmo'
        + chr(92) + chr(92) + 'build";export{p};'
    )
    dist = _dist(tmp_path, files)
    before = (dist / "assets" / "index-abc123.js").read_text(encoding="utf-8")

    result = verify_dist(dist, env_path=_no_env(tmp_path))

    # Not a hard failure — embarrassing, not dangerous — but visible.
    assert result.passed
    assert any("windows_user_path" in f for f in result.redactable_findings)
    assert "REDACTABLE CONTENT IN PUBLISHED BYTES (1)" in result.render()
    assert "Fix the source and rebuild" in result.render()
    # And nothing was modified: this gate is read-only.
    assert (dist / "assets" / "index-abc123.js").read_text(encoding="utf-8") == before


def test_verify_dist_never_writes(tmp_path: Path) -> None:
    dist = _dist(tmp_path, CLEAN, binaries=("og-image.png",))
    before = {
        p.relative_to(dist).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(dist.rglob("*")) if p.is_file()
    }
    verify_dist(dist, env_path=_no_env(tmp_path))
    after = {
        p.relative_to(dist).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(dist.rglob("*")) if p.is_file()
    }
    assert after == before


def test_missing_directory_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="no such directory"):
        verify_dist(tmp_path / "nope", env_path=_no_env(tmp_path))


def test_unknown_extension_is_still_scanned(tmp_path: Path) -> None:
    """An unrecognised text file that the gate skipped is the hole this closes."""
    files = dict(CLEAN)
    files["_headers.custom"] = "PA12345678ABC"
    dist = _dist(tmp_path, files)
    result = verify_dist(dist, env_path=_no_env(tmp_path))
    assert result.passed is False
    assert "alpaca_account_id" in {f.pattern for f in result.report.failures}


# --------------------------------------------------------------------------- #
# Env allowlist (ITEM 0b)                                                     #
# --------------------------------------------------------------------------- #

def test_public_urls_are_not_treated_as_secrets() -> None:
    """A gate that fires falsely trains its operator to ignore it."""
    assert is_secret_bearing("TIINGO_API_KEY", "abcdefghij") is True
    # Explicitly listed non-secret.
    assert is_secret_bearing("ALPACA_BASE_URL", "https://paper-api.alpaca.markets") is False
    # Any public URL, so a future endpoint variable needs no list edit.
    assert is_secret_bearing("SOME_NEW_ENDPOINT", "https://example.com/v1") is False
    assert is_secret_bearing("SOME_NEW_ENDPOINT", "http://example.com") is False
    # Too short to search for without matching prose.
    assert is_secret_bearing("MODE", "x") is False
    assert "ALPACA_BASE_URL" in _ENV_NON_SECRET_KEYS


def test_email_valued_keys_are_excluded_from_prefix_matching() -> None:
    """Regression: prefix-matching an email is a NAME collision, not a secret check.

    `danielmonzonautomation@gmail.com` reduces to `danielmo`, which matched the phrase
    "danielmonzonautomation.com" in the project's own published decision log and failed an
    otherwise-clean snapshot. Emails keep their exact `email_address` check instead.
    """
    assert is_secret_bearing("ALERT_EMAIL_TO", "someone@example.com") is False
    assert is_secret_bearing("SMTP_USER", "ops@example.org") is False
    # A non-email secret of the same length is still checked.
    assert is_secret_bearing("SMTP_PASS", "hunter2hunter2") is True


def test_a_full_email_in_the_bundle_still_fails(tmp_path: Path) -> None:
    """Excluding emails from PREFIX matching must not weaken the exact check."""
    env = tmp_path / ".env"
    env.write_text("ALERT_EMAIL_TO=ops@example.com" + chr(10), encoding="utf-8")
    files = dict(CLEAN)
    files["index.html"] += "<p>ops@example.com</p>"
    dist = _dist(tmp_path, files)
    result = verify_dist(dist, env_path=env)
    assert result.passed is False
    assert "email_address" in {f.pattern for f in result.report.failures}


def test_excluded_keys_are_reported_so_the_gap_is_visible(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "ALPACA_BASE_URL=https://paper-api.alpaca.markets\n"
        "TIINGO_API_KEY=abcdefghijklmno\n"
        "SMTP_HOST=smtp.example.com\n",
        encoding="utf-8",
    )
    secrets = load_env_secret_prefixes(env)

    assert "TIINGO_API_KEY" in secrets.prefixes
    assert "ALPACA_BASE_URL" not in secrets.prefixes
    assert "SMTP_HOST" not in secrets.prefixes
    assert "ALPACA_BASE_URL" in secrets.excluded
    assert "SMTP_HOST" in secrets.excluded

    dist = _dist(tmp_path, CLEAN)
    result = verify_dist(dist, env_path=env)
    rendered = result.render()
    # The exclusion is stated, not hidden — a reader can see which checks did not run.
    assert "keys EXCLUDED as non-secret" in rendered
    assert "ALPACA_BASE_URL" in rendered


def test_the_base_url_no_longer_produces_a_false_failure(tmp_path: Path) -> None:
    """Regression for ITEM 0b: the real snapshot contains this URL legitimately."""
    env = tmp_path / ".env"
    env.write_text("ALPACA_BASE_URL=https://paper-api.alpaca.markets\n", encoding="utf-8")
    files = dict(CLEAN)
    # A perfectly legitimate mention of the documented paper endpoint.
    files["snapshot/api-overview.json"] = json.dumps(
        {"note": "orders route to https://paper-api.alpaca.markets"}
    )
    dist = _dist(tmp_path, files)

    result = verify_dist(dist, env_path=env)
    assert result.passed, result.render()
