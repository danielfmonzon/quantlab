"""Phase 5 validation battery: walk-forward, perturbation, block bootstrap.

IRON RULE — everything in this package is REPORT-ONLY.

Perturbation results MUST NEVER feed back into parameter selection. The
literature-fixed parameters (Faber's 10-month SMA, Antonacci's 12-month
lookback, the 10%/20-day vol target) stand regardless of what the neighbor grid
shows. This battery exists to FLAG fragility — a parameter whose backtest edge
evaporates one notch away is a parameter we would have overfit had we tuned it —
NOT to optimize. Nothing here selects, ranks-for-selection, or mutates a live
parameter. It only measures and reports.
"""

from __future__ import annotations

from quantlab.validation.bootstrap import BootstrapReport, stationary_block_bootstrap
from quantlab.validation.perturb import PerturbReport, perturb
from quantlab.validation.walkforward import WalkForwardReport, walk_forward

__all__ = [
    "walk_forward",
    "WalkForwardReport",
    "perturb",
    "PerturbReport",
    "stationary_block_bootstrap",
    "BootstrapReport",
]
