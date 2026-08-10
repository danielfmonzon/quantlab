"""Late-run guard: no SUBMITTING equity run may fire after 15:30 ET.

The guard is the safety pair to StartWhenAvailable catch-up on
``quantlab-paper-run``: catch-up makes a missed 10:00 run fire whenever the host
comes back, and this cutoff stops that recovery from converging a
morning-intended signal minutes before the close.

Nothing here touches a broker, the vendor, or the data store: the gated pipeline
itself is replaced by a sentinel that proves whether the guard let execution
through (see the ``no_broker`` fixture for why that, and not the broker factory,
is the observable).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from quantlab import cli
from quantlab.data.calendar import TradingCalendar
from quantlab.reporting.alerts import Alert

ET = ZoneInfo("America/New_York")
# 2026-07-22 is a Wednesday and a regular NYSE session.
SESSION = (2026, 7, 22)


def _et(hour: int, minute: int) -> datetime:
    """A UTC instant corresponding to the given ET wall-clock time on SESSION."""
    return datetime(*SESSION, hour, minute, tzinfo=ET).astimezone(ZoneInfo("UTC"))


class _BrokerReached(Exception):
    """Raised by the stub pipeline to prove the guard let the run through."""


@pytest.fixture
def no_broker(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace the whole gated pipeline; invoking it at all is the observable.

    What these tests are really about is whether the cutoff guard let execution THROUGH,
    so the honest observable is the pipeline entry point, and stubbing it makes the tests
    independent of credentials, of the network, and of the data store.

    They used to stub ``_trading_client_for`` instead and rely on the broker being built at
    the top of ``_run_one_paper``, which made "reached the broker" a usable proxy for
    "passed the guard". That proxy died when the retry wrapper (2026-08-10) moved broker
    construction to pipeline stage (e) — deliberately, so a halted account never builds a
    client. Stages (b)–(d) then really ran, with two consequences CI found and one it
    could not:

    * ``_clock_for`` became the first credentialed call, so the tests failed on a keyless
      runner;
    * with the clock stubbed, ``validate`` then failed because a CI checkout has no
      ``data/eod`` store at all, and the run never reached stage (e);
    * and on a machine that HAS both, the ingest ran for real and upserted into the
      production store — a partial same-day SPY bar with no matching IEF bar, whose
      internal gap broke ``build_price_panel`` for the digest and for every later
      ``trend`` run. A guard test must never write to the production store.

    Stubbing the pipeline removes all three at once.
    """
    pipeline = MagicMock(side_effect=_BrokerReached())
    monkeypatch.setattr(cli, "run_paper_with_retry", pipeline)
    # Belt and braces: neither should be reachable now, and if a refactor makes one
    # reachable again the test must still not touch credentials, the vendor, or the store.
    monkeypatch.setattr(cli, "_trading_client_for", MagicMock(side_effect=_BrokerReached()))
    monkeypatch.setattr(cli, "_clock_for", lambda _label: None)
    monkeypatch.setattr(cli, "_ingest_fn_for", lambda _strategy: None)
    return pipeline


# -- the pure predicate -----------------------------------------------------


def test_cutoff_reason_is_none_at_1529_et() -> None:
    assert cli.equity_submit_cutoff_reason(_et(15, 29), TradingCalendar()) is None


def test_cutoff_reason_fires_at_1531_et() -> None:
    reason = cli.equity_submit_cutoff_reason(_et(15, 31), TradingCalendar())
    assert reason is not None
    assert "after 15:30 ET cutoff" in reason
    assert "morning signal near the close" in reason


def test_cutoff_boundary_1530_et_exactly_is_still_allowed() -> None:
    assert cli.equity_submit_cutoff_reason(_et(15, 30), TradingCalendar()) is None


def test_cutoff_does_not_apply_off_session() -> None:
    # 2026-07-25 is a Saturday: no session, so the cutoff has nothing to guard.
    saturday = datetime(2026, 7, 25, 18, 0, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    assert cli.equity_submit_cutoff_reason(saturday, TradingCalendar()) is None


# -- the guard inside _run_one_paper ----------------------------------------


def test_guarded_run_aborts_and_never_enters_the_pipeline(no_broker: MagicMock) -> None:
    sent: list[Alert] = []
    rc = cli._run_one_paper(
        "voltarget", submit=True, now_utc=_et(15, 31), alert_fn=sent.append
    )
    assert rc == 1
    no_broker.assert_not_called()  # the pipeline was never entered at all

    assert len(sent) == 1
    alert = sent[0]
    assert alert.level == "WARNING"
    assert alert.strategy == "voltarget"  # exact attribution, not title matching
    assert "after 15:30 ET cutoff" in alert.body
    assert alert.source == "cli.paper_run"


def test_before_cutoff_proceeds_to_the_pipeline(no_broker: MagicMock) -> None:
    sent: list[Alert] = []
    with pytest.raises(_BrokerReached):
        cli._run_one_paper(
            "voltarget", submit=True, now_utc=_et(15, 29), alert_fn=sent.append
        )
    no_broker.assert_called_once()
    assert sent == []  # no guard alert when the run is in time


def test_dry_run_is_unaffected_by_the_cutoff(no_broker: MagicMock) -> None:
    # submit=False: a dry run places no orders, so the near-close hazard is absent.
    sent: list[Alert] = []
    with pytest.raises(_BrokerReached):
        cli._run_one_paper(
            "voltarget", submit=False, now_utc=_et(23, 0), alert_fn=sent.append
        )
    no_broker.assert_called_once()
    assert sent == []


def test_crypto_is_unaffected_by_the_cutoff(no_broker: MagicMock) -> None:
    # 24/7 market: no close to be near, so no cutoff at any hour.
    sent: list[Alert] = []
    with pytest.raises(_BrokerReached):
        cli._run_one_paper(
            "crypto_trend", submit=True, now_utc=_et(23, 30), alert_fn=sent.append
        )
    no_broker.assert_called_once()
    assert sent == []


def test_run_all_equity_guards_every_account(no_broker: MagicMock) -> None:
    sent: list[Alert] = []
    rcs = [
        cli._run_one_paper(label, submit=True, now_utc=_et(16, 0), alert_fn=sent.append)
        for label in ("voltarget", "trend")
    ]
    assert rcs == [1, 1]
    no_broker.assert_not_called()
    assert [a.strategy for a in sent] == ["voltarget", "trend"]
