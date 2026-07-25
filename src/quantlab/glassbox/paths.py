"""Where the Glass Box reads from — and nothing it writes to.

Every artifact location the service touches is named here, on one injectable
object, so the read-only surface is auditable in a single place and the test suite
can point the whole app at a fixture tree in ``tmp_path``.

Nothing in this package opens a file for writing. The service is a window onto
artifacts the trading and reporting paths produce; it never produces them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quantlab.constants import PROJECT_ROOT


@dataclass(frozen=True)
class GlassboxPaths:
    """Read-only artifact locations, all derived from one repo root."""

    project_root: Path

    @classmethod
    def from_root(cls, root: Path | None = None) -> GlassboxPaths:
        return cls(project_root=Path(root) if root is not None else PROJECT_ROOT)

    # -- reports -----------------------------------------------------------
    @property
    def reports_dir(self) -> Path:
        return self.project_root / "reports"

    @property
    def paper_dir(self) -> Path:
        return self.reports_dir / "paper"

    @property
    def weekly_dir(self) -> Path:
        return self.reports_dir / "weekly"

    @property
    def digests_dir(self) -> Path:
        return self.reports_dir / "digests"

    @property
    def alerts_path(self) -> Path:
        return self.reports_dir / "alerts" / "alerts.jsonl"

    @property
    def backtests_dir(self) -> Path:
        return self.reports_dir / "backtests"

    @property
    def validation_dir(self) -> Path:
        return self.reports_dir / "validation"

    # -- data --------------------------------------------------------------
    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    def equity_history_path(self, label: str) -> Path:
        return self.data_dir / f"equity_history_{label}.parquet"

    def risk_state_path(self, label: str) -> Path:
        return self.data_dir / f"risk_state_{label}.json"

    # -- config / docs -----------------------------------------------------
    @property
    def config_dir(self) -> Path:
        return self.project_root / "config"

    @property
    def risk_yaml(self) -> Path:
        return self.config_dir / "risk.yaml"

    @property
    def crypto_risk_yaml(self) -> Path:
        return self.config_dir / "crypto_risk.yaml"

    @property
    def decisions_path(self) -> Path:
        return self.project_root / "docs" / "decisions.md"

    # -- frontend ----------------------------------------------------------
    @property
    def frontend_dist(self) -> Path:
        """Built single-page app, mounted at ``/`` when present (``npm run build``)."""
        return self.project_root / "frontend" / "dist"

    @property
    def frontend_built(self) -> bool:
        return (self.frontend_dist / "index.html").is_file()


__all__ = ["GlassboxPaths"]
