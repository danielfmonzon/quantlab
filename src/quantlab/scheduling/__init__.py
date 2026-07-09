"""Scheduled paper-trading via Windows Task Scheduler (schtasks).

The scheduled entry point is exactly ``quantlab paper run --strategy voltarget
--submit`` — the full gated pipeline. Scheduling adds NO new trading authority
and cannot weaken any risk gate; it only invokes the same command a human would.
"""

from __future__ import annotations
