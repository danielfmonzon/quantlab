"""The AI improvement pipeline: propose -> firewall -> implement -> human merge.

Three modules, one rule each:

* :mod:`quantlab.improve.sources` — what the analysis may READ (an allowlist of
  artifacts this system published about itself, plus the dated decision log).
* :mod:`quantlab.improve.firewall` — what a proposal may CHANGE (a denylist of frozen
  paths and change classes, enforced structurally at both propose and implement time).
* :mod:`quantlab.improve.propose` / :mod:`quantlab.improve.implement` — the two halves,
  kept separate so that analysis can run freely while anything that touches the tree
  stays on a branch behind a human merge gate.

Nothing here merges. That is checked by a test, not asserted by a comment.
"""

from __future__ import annotations

__all__ = ["firewall", "implement", "propose", "sources"]
