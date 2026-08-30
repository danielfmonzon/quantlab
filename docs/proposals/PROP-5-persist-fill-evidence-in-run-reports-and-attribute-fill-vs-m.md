# PROP-5 — Persist fill evidence in run reports and attribute fill-vs-mark from actual fills

_proposed 2026-08-30  |  risk class: **infrastructure**  |  status: **IMPLEMENTED — awaiting human merge**_

> **This proposal was written by hand, and that is itself part of the record.**
> `quantlab propose` **REFUSED** it (exit 3) on `FORBIDDEN PATH src/quantlab/broker/alpaca_trading.py`
> — "the broker order path, frozen under human review since the first paper account". The
> refusal was correct and was not routed around: the change genuinely needs three fields on
> `OrderInfo`, and a second orders client living outside `broker/` would have been the same
> change wearing a disguise. The refusal names the process, and it was followed —
> **Quant Lead ruling, 2026-08-30, recorded in `docs/decisions.md`**, authorising an
> additive, read-only extension to the broker response model and nothing else. `implement`
> was likewise bypassed, since it will not run on a proposal `propose` never wrote; the
> gates it would have run were run by hand and are reported below in the same shape.

## Observation

Divergence diagnosis #3 attributed **+100.79 of `crypto_voltarget`'s +115.60 bps** week-20260828
residual to the gap between the notional a repair converge submitted and the cash it actually
raised. That figure could not be read from any artifact.

`run_crypto_voltarget_20260822T162421Z.json` records `submitted_orders` with
`status: "pending_new"` and nothing else — no filled quantity, no average fill price, no fill
timestamp. Every run report in `reports/paper/` has this shape, because the runner writes the
order as it was *submitted* and only ever polls sells, whose resolved status it then discards.

So the number had to be inferred from the difference between two equity-history marks
(`$71,430.49` raised against `$70,218.29` submitted) and corroborated indirectly, by backing an
implied BTC price out of position value and testing it against that session's own high-low bar.
That test was decisive — under the model's assumption the implied mark lands 0.60%–1.02% above
2026-08-22's high, which is impossible — but it was decisive **only because the account happened
to hold one asset and to trade once**. On a basket, or on a window with several trades, the
inference is not available at all.

`reporting.markphase` states in its own docstring that it leaves this effect in the residual
deliberately. That is a defensible choice, but its consequence is that the residual the verdict
is taken on carries an unmeasured component whenever the compared window contains turnover, and
week 2026-08-28 is the first week where that component decided a verdict.

`docs/decisions.md` already queues "the 5 bps assumption tested against actual paper fill prices
versus the marks" as day-90 revisit item (b). Week 2026-08-28 forced that question early and the
artifacts could not answer it.

### Evidence

- `reports/weekly/week_20260828.md`
- `reports/paper/run_crypto_voltarget_20260822T162421Z.json`
- `docs/decisions.md`

## Proposed change

After orders are submitted, poll **every** order to a terminal state within the same bounded
window the runner already applies to sells, and record `filled_qty`, `filled_avg_price`,
`filled_at` and the terminal `status` per order in the run report alongside the submitted
notional.

The weekly residual attribution then gains a **fill-vs-mark component computed from those
recorded fills** whenever the compared window contains turnover, replacing the
inferred-from-account-deltas method diagnosis #3 had to fall back on. When a window has no
turnover, or when its reports predate this change, the component is **absent rather than zero**
and the existing output is unchanged.

**Attribution only.** The component does not move `predicted_mark_phase_bps`, the residual, or
the verdict; it names a part of the residual that was previously unnamed. Which figure the
threshold is applied to is a dated ruling (2026-08-10) and is deliberately untouched here.

**No trading-decision change.** What is ordered, when, at what size, and every decision behind it
are untouched. Sells are still submitted, awaited, and only then are buys submitted. The new poll
runs strictly *after* every order is placed, so it cannot move, resize, or delay one of them, and
no recorded value is read by any decision path.

## Affected files

- `src/quantlab/broker/alpaca_trading.py` *(forbidden path; see the ruling above)*
- `src/quantlab/paper/runner.py`
- `src/quantlab/reporting/markphase.py`
- `src/quantlab/reporting/weekly.py`
- `tests/test_markphase.py`
- `tests/test_paper_runner.py`

## Risk class

**infrastructure**

## Test plan

A fixture builds a mark window carrying one order whose recorded average fill price sits 1% away
from the implied mark price, and asserts the new component equals the expected basis points for
that notional and equity. A companion fixture with zero turnover asserts the component is absent
and the mark-phase prediction is unchanged. A runner fixture asserts the recorded fields are
written for a terminal order, that a poll timing out leaves them null rather than guessing, and
that the submitted notional already recorded is unchanged. Full pytest, ruff and mypy locally,
and CI green before human review.

## Firewall

```
========================================================================
FIREWALL REFUSAL — this proposal will not be written.
========================================================================

  FORBIDDEN PATH   src/quantlab/broker/alpaca_trading.py
                   the broker order path, frozen under human review since the first paper account
    triggered by:  src/quantlab/broker/alpaca_trading.py
```

Refused, then authorised by dated Quant Lead ruling (2026-08-30) and applied by hand — the exact
path the refusal text prescribes. **The firewall was not modified, weakened, or bypassed in code**:
`propose` and `implement` still refuse this proposal today, and re-running `quantlab propose` with
the same `--affects` list reproduces the refusal above verbatim.

## Merge gate

**Merge is human-only.** Daniel merges via pull request after Quant Lead review. The hand-applied
path grants no automated route to `main`: the branch is pushed and stops there, exactly as
`implement` would have left it.

---

<!-- IMPLEMENTATION REPORT ANCHOR -->

## Implementation report

_implemented 2026-08-30  |  branch `prop/5`  |  status: **GATES PASSED**_

### What changed

**`broker/alpaca_trading.py`** — three optional read-only fields on `OrderInfo`
(`filled_qty`, `filled_avg_price`, `filled_at`), populated in `_order_from_payload` through a new
`_numeric` helper. Alpaca renders these as decimal *strings* and uses both `null` and `""` for
"no value yet", so a bare `float()` is unsafe; an unparseable value yields `None` rather than
raising, because fill evidence is reporting-only and must never break the order path it is read
from. `submit_order` is not touched.

**`paper/runner.py`** — `_await_terminal` now returns the full `OrderInfo` per resolved id instead
of its status alone, and `_submit_plan` polls every submitted order after the last one is placed,
merging the result via a new `_with_fill_evidence`. The submitted record stays authoritative for
what the run *asked for* (notional, side, `client_order_id`, `was_duplicate`); the polled record
is authoritative for what became of it. A poll that cannot resolve an order leaves the fill fields
`None` — unknown, not zero.

`_await_terminal` also gained a **poll-count bound** alongside its deadline. The deadline is the
real limit in production, but a monotonic clock that does not advance — a suspended host, a frozen
clock in a harness — could otherwise spin forever in a loop that sits between submitting sells and
submitting the buys they fund. At the shipped 120s/2s that is 61 polls, so the deadline is always
reached first and behaviour is unchanged. This was found by the widened poll, not invented for it.

**`reporting/markphase.py`** — `_signed_filled_notional` reads the signed value actually filled at
a mark, returning `None` when the run submitted no orders, when *any* order lacks fill evidence, or
when the report predates this change. `fill_vs_mark_bps` sums
`(traded_notional - filled) / equity` over the marks that OPEN an interval. The docstring carries
the derivation: the part of an interval's residual the mark-price assumption accounts for is
`(cash_b - cash_a + traded_notional) / equity_a`, and cash moves by the negative of what filled.

**`reporting/weekly.py`** — `AccountWeekly.fill_vs_mark_bps`, rendered as
`- of which fill-vs-mark: +X bps (measured from recorded fills)` with a note stating that it
attributes the residual and does not reduce it.

### Reproducing diagnosis #3's figure

Fed the real 2026-08-22 mark (equity 120,264.39, sell notional 70,218.29) with the fill this change
would have recorded (0.921208 BTC at 77,540.06 = $71,430.49), `fill_vs_mark_bps` returns
**+100.79 bps** — the figure diagnosis #3 reached by hand from equity deltas and an implied-price
bar test.

### Gates

| gate | result | detail |
|---|---|---|
| `ruff` | PASS | All checks passed! |
| `mypy` | PASS | Success: no issues found in 71 source files |
| `pytest` | PASS | 707 passed, 1 warning in 64.97s (0:01:04) |
| `frontend` | SKIP | no frontend/ path in the diff |
| `verify-dist` | SKIP | site not touched |

707 against PROP-4's 695: +12 new tests, no test removed or weakened.

### Merge gate — STOPPED HERE

This change sits on `prop/5`. `main` is untouched. **Daniel merges via pull request after Quant
Lead review.** Applying a firewall-refused proposal by hand removes the pipeline's automation, not
its human gate — the gate is the only reason this path exists at all.

---

## Post-review amendments (Quant Lead, 2026-08-30)

Approved with two amendments, applied on the same branch. Both narrow the blast radius of
the three new fields; neither changes what they mean or what reads them.

**1. `filled_at` gets the same tolerance as the numeric fields.** Two `mode="before"`
field validators on `OrderInfo` make it structurally impossible for any of the three new
fields to fail construction: `filled_qty` / `filled_avg_price` route through `_numeric`,
and `filled_at` parses through a module-level `TypeAdapter(datetime | None)` that yields
`None` where pydantic would have raised. Delegating to the adapter rather than
hand-rolling a parser means every value that parsed before still parses identically — the
tolerance can only widen what is accepted, never alter a good value.

The guarantee lives on the **model**, not only in `_order_from_payload`, so it holds for
every construction path. This matters because the poll that reads these fields stands
between submitting sells and submitting the buys those sells fund: a `ValidationError`
there does not lose a timestamp, it strands the account half-rebalanced.

**2. `_numeric` rejects non-finite results.** `float("nan")` and `float("inf")` both
succeed, so "unparseable → `None`" was not literally true. The consequence is downstream:
`markphase.fill_vs_mark_bps` sums `filled_qty × filled_avg_price` across a window, and a
single `nan` turns a whole week's attribution into `nan` while still type-checking as a
float. A missing figure now reads as missing, which the attribution already handles by
reporting the component absent.

**Tests.** `filled_at="garbage"` yields `None` and the order still parses with its other
fields intact; a parametrised case covers empty, whitespace, an impossible date, a list, a
dict, a bare object and `nan`. `"nan"`, `"NaN"`, `"inf"`, `"-inf"`, `"Infinity"` and the
float forms all return `None`; an end-to-end payload with `filled_qty="nan"` and
`filled_avg_price="inf"` lands both as `None`. A teeth test pins that ordinary decimal
strings still parse, and one more proves direct `OrderInfo(...)` construction cannot fail
on the three fields.

**Gates after amendment:** ruff PASS, mypy PASS (71 files), pytest **728 passed** (+21,
none removed or weakened).
