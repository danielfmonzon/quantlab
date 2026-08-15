"""The firewall must refuse, structurally, the things the iron rule freezes.

The load-bearing test in this file is `test_widen_the_threshold_proposal_is_refused`.
The pipeline's entire safety claim is that an automated loop cannot relax the constraints
it is measured against — and the most plausible way that claim fails is not malice but
reasonableness: a loop reads a week of DIVERGING alerts, correctly observes that the
threshold produces alerts nobody acts on, and proposes widening it. That proposal would
be well-evidenced and wrong, and it is exactly what 2026-08-10 ("Residual thresholding:
fix the instrument, not the threshold") ruled against. So it is tested by name.
"""

from __future__ import annotations

import pytest

from quantlab.improve import firewall
from quantlab.improve.propose import Proposal, ProposalRefused, write_proposal


def test_widen_the_threshold_proposal_is_refused() -> None:
    """THE test. A synthetic, well-argued 'widen the threshold' proposal must not pass."""
    proposal = Proposal(
        title="Widen the DIVERGING threshold from 50 bps to 120 bps",
        observation=(
            "Four of the last six weekly reviews fired DIVERGING on crypto_voltarget. "
            "Every one was later attributed to mark-phase geometry rather than tracking "
            "error, so the alerts produced no action."
        ),
        change=(
            "Raise weekly_divergence_alert_bps from 50 to 120 so the alert fires only on "
            "residuals that survive the geometry decomposition."
        ),
        affected_paths=["config/risk.yaml"],
        risk_class="operational",
        test_plan="Re-run the weekly over the last six weeks and confirm zero alerts.",
    )

    verdict = firewall.check(
        affected_paths=proposal.affected_paths, text=proposal.firewall_text
    )
    assert not verdict.allowed, "the firewall let a threshold-widening proposal through"

    kinds = {r.kind for r in verdict.refusals}
    assert "path" in kinds, "config/risk.yaml should have been refused on its path"
    assert "class" in kinds, "the stated intent should have been refused on its class"

    classes = {r.identifier for r in verdict.refusals if r.kind == "class"}
    assert "threshold_constants" in classes


def test_widen_the_threshold_proposal_writes_nothing(tmp_path) -> None:
    """A refusal must leave no file behind — the gate is before the write, not after."""
    proposal = Proposal(
        title="Widen the DIVERGING threshold to 120 bps",
        observation="Alerts nobody acts on.",
        change="Raise the divergence threshold.",
        affected_paths=["config/risk.yaml"],
        risk_class="operational",
        test_plan="Re-run the weekly.",
    )
    with pytest.raises(ProposalRefused) as caught:
        write_proposal(proposal, proposals_dir=tmp_path)

    assert list(tmp_path.iterdir()) == [], "a refused proposal left a file on disk"
    assert "IRON RULE" in caught.value.verdict.render()


def test_refusal_text_cites_the_iron_rule() -> None:
    """The refusal has to explain itself to someone who does not know the history."""
    verdict = firewall.check(affected_paths=["src/quantlab/broker/alpaca.py"])
    rendered = verdict.render()
    assert not verdict.allowed
    assert "IRON RULE" in rendered
    assert "2026-07-06" in rendered
    assert "docs/decisions.md" in rendered
    assert "no flag that overrides it" in rendered


@pytest.mark.parametrize(
    "path",
    [
        "src/quantlab/backtest/strategies/trend.py",
        "src/quantlab/broker/alpaca.py",
        "src/quantlab/risk/limits.py",
        "config/risk.yaml",
        "config/crypto_risk.yaml",
        "src/quantlab/glassbox/sanitize.py",
        "src/quantlab/scheduling/tasks.py",
    ],
)
def test_every_frozen_path_is_refused(path: str) -> None:
    assert not firewall.check(affected_paths=[path]).allowed, f"{path} was not refused"


@pytest.mark.parametrize(
    "text",
    [
        "Retune the trend lookback from 10 months to 12.",
        "Lower the max drawdown limit so the kill switch fires later.",
        "Relax the sanitizer forbidden pattern for email_address.",
        "Change the crypto run cadence to hourly.",
        "Adjust the order submission logic to use marketable limits.",
        "Increase the volatility target to 12%.",
    ],
)
def test_forbidden_change_classes_are_refused_from_prose_alone(text: str) -> None:
    """Path rules are not enough — a constant can be edited from an innocuous file."""
    verdict = firewall.check(affected_paths=["src/quantlab/reporting/weekly.py"], text=text)
    assert not verdict.allowed, f"not refused: {text!r}"
    assert any(r.kind == "class" for r in verdict.refusals)


def test_legitimate_infrastructure_proposal_passes() -> None:
    """The firewall must not refuse everything, or it would just be an off switch."""
    verdict = firewall.check(
        affected_paths=[
            "src/quantlab/reporting/weekly.py",
            "tests/test_weekly_completion_signal.py",
        ],
        text=(
            "The weekly emits no completion signal on an all-TRACKING week, so a clean "
            "week and a week the task never ran are indistinguishable from the alert "
            "stream. Emit one INFO alert recording the week ending and the four verdicts."
        ),
    )
    assert verdict.allowed, verdict.render()
    assert "FIREWALL PASS" in verdict.render()


def test_discussing_a_threshold_without_proposing_to_move_it_is_allowed() -> None:
    """Both halves must fire: a target alone is discussion, a verb alone is English."""
    verdict = firewall.check(
        affected_paths=["src/quantlab/reporting/weekly.py"],
        text=(
            "The report should state which threshold the verdict was taken against, so "
            "a reader does not have to infer it. The threshold value itself is unchanged."
        ),
    )
    assert verdict.allowed, verdict.render()


def test_strategy_performance_data_may_inform_an_infrastructure_proposal() -> None:
    """The rule is enforced on EFFECT, not on what the analysis read.

    Reading the divergence figures to improve the reporting machinery is the intended
    use. The same figures used to argue for a parameter change are refused above.
    """
    verdict = firewall.check(
        affected_paths=["src/quantlab/glassbox/app.py"],
        text=(
            "crypto_voltarget's cumulative divergence of -76 bps is dominated by mark "
            "timing, but the Glass Box surfaces only the raw figure, so a reader cannot "
            "see the decomposition the verdict was actually taken on. Expose the "
            "residual alongside the raw divergence in the divergence endpoint."
        ),
    )
    assert verdict.allowed, verdict.render()


def test_absolute_paths_are_normalised_before_matching() -> None:
    """An absolute path must not sneak past a prefix match."""
    from quantlab.constants import PROJECT_ROOT

    absolute = str(PROJECT_ROOT / "config" / "risk.yaml")
    assert not firewall.check(affected_paths=[absolute]).allowed


def test_windows_separators_are_normalised_before_matching() -> None:
    """A backslash is a separator on every platform, not only where `Path` says so.

    This failed on CI (ubuntu-latest, 2026-08-15) while passing on the Windows dev
    machine: POSIX `Path` treats `config\\risk.yaml` as one filename containing a
    backslash, so it never matched `config/risk.yaml` and the firewall ALLOWED a frozen
    path. The gate's verdict must not depend on the OS evaluating it.
    """
    assert not firewall.check(affected_paths=[r"config\risk.yaml"]).allowed
    assert not firewall.check(
        affected_paths=[r"src\quantlab\broker\alpaca.py"]
    ).allowed
    # Mixed separators, as a copy-paste from a Windows shell into a POSIX tool produces.
    assert not firewall.check(
        affected_paths=[r"src/quantlab\backtest/strategies\trend.py"]
    ).allowed


@pytest.mark.parametrize(
    "raw,expected",
    [
        (r"config\risk.yaml", "config/risk.yaml"),
        ("config/risk.yaml", "config/risk.yaml"),
        (r"src\quantlab\broker\alpaca.py", "src/quantlab/broker/alpaca.py"),
        (r"src/quantlab\broker/alpaca.py", "src/quantlab/broker/alpaca.py"),
    ],
)
def test_normalise_is_platform_independent(raw: str, expected: str) -> None:
    """Pinned directly, so the property is asserted rather than inferred from a verdict."""
    assert firewall._normalise(raw) == expected
