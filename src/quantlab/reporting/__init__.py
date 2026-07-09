"""Daily digest and alerting for the paper-trading loop (report-only side channel).

Kept import-light on purpose: ``reporting.digest`` imports from ``paper.runner``
and ``paper.runner`` imports from ``reporting.alerts``, so this package's
``__init__`` avoids re-exporting either to prevent an import cycle.
"""

from __future__ import annotations
