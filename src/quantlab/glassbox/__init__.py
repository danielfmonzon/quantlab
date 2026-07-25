"""Glass Box — a read-only transparency API over quantlab's own artifacts.

The package answers one question: *what did this system actually do, and on what
basis?* It reads the files the trading and reporting paths already write — run
reports, weekly reviews, digests, alerts, equity history, risk state, config, and
the decisions log — and serves them as JSON on localhost.

What it deliberately is NOT:

* it does not trade, and imports nothing from ``quantlab.broker``;
* it writes no files, anywhere;
* it makes no network calls of its own;
* it never narrates beyond the structured fields it read (see ``narrate``), so no
  endpoint offers market commentary, a news feed, or a model's opinion. The
  ``/api/ignored-inputs`` endpoint publishes that boundary rather than hiding it.

Imports are LAZY (PEP 562). ``create_app`` pulls in FastAPI, and nothing outside
this package should pay that cost — least of all ``quantlab.cli``, where a broken
web dependency must never be able to block a paper run. ``from quantlab.glassbox
import create_app`` still works; it just resolves on first access.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - type-checking only, no runtime import
    from quantlab.glassbox.app import create_app
    from quantlab.glassbox.paths import GlassboxPaths
    from quantlab.glassbox.serve import DEFAULT_PORT, HOST, serve

_LAZY: dict[str, tuple[str, str]] = {
    "create_app": ("quantlab.glassbox.app", "create_app"),
    "GlassboxPaths": ("quantlab.glassbox.paths", "GlassboxPaths"),
    "serve": ("quantlab.glassbox.serve", "serve"),
    "HOST": ("quantlab.glassbox.serve", "HOST"),
    "DEFAULT_PORT": ("quantlab.glassbox.serve", "DEFAULT_PORT"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(target[0]), target[1])


def __dir__() -> list[str]:
    return sorted(_LAZY)


__all__ = ["create_app", "GlassboxPaths", "serve", "HOST", "DEFAULT_PORT"]
