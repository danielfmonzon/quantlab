# PROP-10 — Fill evidence is recorded but nothing reads it, so the cost model is still an assumption

_proposed 2026-08-30T23:38:36.807780Z  |  risk class: **infrastructure**  |  status: **IMPLEMENTED — awaiting human merge**_

## Observation

The three fill fields landed on main and the runner now records what every order actually did, but no report reads them. The shadow charges a flat five basis points one way and the 2026-08-10 turnover entry says plainly that this rate is a modeled figure never validated against a fill, that the sign of its error is unknown, and that the day-90 review must test it against actual paper fill prices versus the marks. That item cannot be answered by looking at anything the system currently prints. Divergence diagnosis #3 needed exactly this number for one order and had to derive it from the difference between two equity-history marks, then corroborate it by backing an implied price out of position value and testing it against a daily bar -- an inference that worked only because the account held one asset and traded once. The figure it produced, a hundred and seventy-two point six basis points in the account's favour on a seventy thousand dollar sell, is large enough that it will not reproduce live and is recorded as an open live-readiness exposure. One order is not a distribution, and a single favourable outlier tells you almost nothing about the rate that should replace the assumption.

### Evidence

- `reports/paper/run_crypto_voltarget_20260822T162421Z.json`
- `docs/decisions.md`
- `reports/weekly/week_20260828.md`

## Proposed change

A new reporting module reads the recorded fills and nothing else -- never equity deltas, never an implied price, never an inference. For every order it prints the notional the run submitted, the value that actually filled as quantity times average price, the price the mark implied, and the difference expressed in basis points and signed so that positive always means favourable to the account regardless of side. Beneath the rows it prints the distribution over every order recorded since the instrumentation began: count, mean, median, and the fifth and ninety-fifth percentiles. A new command prints it on demand and the weekly review gains the same section. An order whose report predates the instrumentation prints that no fill data was captured rather than a zero, because zero would assert that the order filled exactly at its mark, which is the claim diagnosis #3 had to disprove by hand. The 2026-08-22 order stays annotated as unexplained in the decision log and is not retrofitted -- its fill was never recorded and no amount of reporting can invent it.

## Affected files

- `src/quantlab/reporting/fills.py`
- `src/quantlab/reporting/weekly.py`
- `src/quantlab/cli.py`
- `tests/test_fills.py`

## Risk class

**infrastructure**

## Test plan

A fixture writes three synthetic orders whose recorded fills land one percent above, exactly at, and one percent below the price their notional implied, and asserts the three rows carry plus one hundred, zero and minus one hundred basis points with the favourable sign convention applied per side, and that the distribution reports a count of three, a mean and median of zero, and the expected outer percentiles. A companion fixture with a report that carries no fill fields asserts the row reads as not captured and is excluded from the distribution rather than counted as zero. A sign fixture asserts a buy that filled above its mark reads adverse while a sell that filled above its mark reads favourable. An empty fixture asserts the section renders with an explicit nothing-recorded line rather than being absent. Full pytest, ruff and mypy locally, and CI green before human review.

## Firewall

```
FIREWALL PASS — no forbidden path or change class touched.
```

## Merge gate

`implement` stops after pushing the branch. **Merge is human-only:** Daniel merges via pull request after Quant Lead review. No automated path to `main` exists in this pipeline.

---

<!-- IMPLEMENTATION REPORT ANCHOR -->

## Implementation report

_implemented 2026-08-30T23:42:30.029226Z  |  branch `prop/10`  |  status: **GATES PASSED**_

### Diff stat

```
src/quantlab/cli.py              |  23 +++
 src/quantlab/reporting/fills.py  | 299 +++++++++++++++++++++++++++++++++++++++
 src/quantlab/reporting/weekly.py |   7 +
 tests/test_fills.py              | 227 +++++++++++++++++++++++++++++
 4 files changed, 556 insertions(+)
```

### Firewall re-check (against the actual diff)

```
FIREWALL PASS — no forbidden path or change class touched.
```

### Gates

| gate | result | detail |
|---|---|---|
| `ruff` | PASS | All checks passed! |
| `mypy` | PASS | Success: no issues found in 72 source files |
| `pytest` | PASS | 750 passed, 1 warning in 78.56s (0:01:18) |
| `frontend` | SKIP | no frontend/ path in the diff |
| `verify-dist` | SKIP | site not touched |

### Branch

- branch: `prop/10`
- commit and push: performed immediately after this report was written into the proposal, since the report is part of what gets committed. The resulting SHA and push result are in the run output, and the commit itself is the one carrying this file.

### Merge gate — STOPPED HERE

This pipeline does not merge. The change sits on `prop/10` and `main` is untouched. **Daniel merges via pull request after Quant Lead review.** There is no automated path to `main` in `quantlab implement` — verified by test, not by convention.
