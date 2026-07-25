"""CLI wiring for ``quantlab glassbox serve``, including the localhost binding.

The bind host is the security property worth a test: the API has no auth and
exposes account equity, positions, and orders, so binding anything but loopback
would publish holdings to the local network. No server is started — the uvicorn
runner is injected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from quantlab.cli import build_parser, cmd_glassbox_serve
from quantlab.glassbox.serve import DEFAULT_PORT, HOST, serve


class _FakeRunner:
    """Stands in for ``uvicorn.run``; records how it was called."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


def test_host_constant_is_loopback_only() -> None:
    assert HOST == "127.0.0.1"
    assert DEFAULT_PORT == 8600


def test_serve_binds_loopback_and_the_requested_port(tmp_path: Path) -> None:
    runner = _FakeRunner()
    rc = serve(port=9123, root=tmp_path, runner=runner)

    assert rc == 0
    assert len(runner.calls) == 1
    _args, kwargs = runner.calls[0]
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 9123


def test_serve_never_binds_a_wildcard_address(tmp_path: Path) -> None:
    """The host is not parameterised, so no caller can widen it."""
    runner = _FakeRunner()
    serve(port=DEFAULT_PORT, root=tmp_path, runner=runner)
    host = runner.calls[0][1]["host"]
    assert host not in {"0.0.0.0", "::", "", "*"}  # noqa: S104 - asserting the negative
    with pytest.raises(TypeError):
        serve(port=DEFAULT_PORT, root=tmp_path, runner=runner, host="0.0.0.0")  # type: ignore[call-arg]


def test_serve_mounts_the_app_over_the_requested_root(tmp_path: Path) -> None:
    runner = _FakeRunner()
    serve(port=DEFAULT_PORT, root=tmp_path, runner=runner)
    app = runner.calls[0][0][0]
    assert app.state.glassbox_paths.project_root == tmp_path


def test_parser_wires_glassbox_serve_with_a_port_default() -> None:
    args = build_parser().parse_args(["glassbox", "serve"])
    assert args.func is cmd_glassbox_serve
    assert args.port == DEFAULT_PORT

    args = build_parser().parse_args(["glassbox", "serve", "--port", "9999"])
    assert args.port == 9999


def test_parser_exposes_no_host_flag() -> None:
    """A --host flag would be the obvious way to accidentally publish this."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["glassbox", "serve", "--host", "0.0.0.0"])


def test_glassbox_subcommand_requires_an_action() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["glassbox"])


def test_cmd_glassbox_serve_delegates_to_serve(monkeypatch: pytest.MonkeyPatch) -> None:
    import quantlab.glassbox.serve as serve_module

    seen: dict[str, Any] = {}

    def _fake_serve(port: int = DEFAULT_PORT, **kwargs: Any) -> int:
        seen["port"] = port
        return 0

    monkeypatch.setattr(serve_module, "serve", _fake_serve)
    args = build_parser().parse_args(["glassbox", "serve", "--port", "8777"])
    assert cmd_glassbox_serve(args) == 0
    assert seen["port"] == 8777


def test_cli_import_does_not_pull_in_fastapi() -> None:
    """A broken web dependency must never be able to block a paper run."""
    import subprocess
    import sys

    code = (
        "import sys, quantlab.cli;"
        "assert 'fastapi' not in sys.modules, 'cli imported fastapi';"
        "print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
