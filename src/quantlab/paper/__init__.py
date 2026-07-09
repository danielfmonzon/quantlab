"""Paper-trading orchestration: rebalance planning and the gated runner.

Every order path in this package flows through the risk engine and kill-switch
state, and real submission is opt-in (DRY-RUN is the default). See
``paper.runner`` for the ordered, abort-on-first-failure pipeline.
"""

from __future__ import annotations

from quantlab.paper.rebalance import (
    OrderIntent,
    RebalancePlan,
    SkippedDiff,
    plan_rebalance,
)

__all__ = ["plan_rebalance", "RebalancePlan", "OrderIntent", "SkippedDiff"]
