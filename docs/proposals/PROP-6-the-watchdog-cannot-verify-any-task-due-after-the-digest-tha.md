# PROP-6 — The watchdog cannot verify any task due after the digest that checks for it

_proposed 2026-08-30T20:44:23.096000Z  |  risk class: **infrastructure**  |  status: **IMPLEMENTED — awaiting human merge**_

## Observation

reporting.watchdog.check_schedule opens its comparison window at previous_digest_date plus one day, on the premise that the previous digest already reported on its own day. It separately skips any expected firing whose due instant is later than the moment the digest fires, which is correct on its own: silence before a job is due is not absence. Those two rules interact badly for every task due later in the day than the digest itself. The digest fires at 20:45 UTC on weekdays. quantlab-weekly is due at 21:00 UTC on Fridays and quantlab-glassbox-refresh at 21:30 UTC on Fridays. Each is therefore skipped as not yet due on the Friday it fires, and then falls outside every later window, because the next window opens on the Saturday. Neither Friday task can ever be verified by this watchdog, which is the one thing it exists to do. On 2026-08-28 the glassbox refresh process died after writing its snapshot and dispatched no alert at all, so alerts.jsonl carries no glassbox.refresh record for that day and the published site served a capture from 2026-08-22 for eight days. digest_20260828.md reports MISSED RUNS none over expected firings checked 4, which was true by construction rather than verified. Replaying the window arithmetic for digests dated 08-29, 08-31, 09-01 and 09-04 puts 2026-08-28 outside all of them, so no future digest reports it either.

### Evidence

- `reports/digests/digest_20260828.md`
- `reports/alerts/alerts.jsonl`
- `docs/decisions.md`

## Proposed change

The comparison window reaches back one further day whenever the previous digest fired before that day's expected firings were due, so a firing skipped as not-yet-due is picked up by the next digest instead of falling into a gap between two windows. The not-yet-due rule itself is untouched, and an expectation already satisfied by an artifact is still reported clean, so a healthy Friday produces exactly the output it produces today. Nothing about when any task fires is affected: this is the watchdog's own read-back window and nothing else.

## Affected files

- `src/quantlab/reporting/watchdog.py`
- `tests/test_watchdog.py`

## Risk class

**infrastructure**

## Test plan

A fixture places a Friday digest at 20:45 UTC with no glassbox.refresh alert for that Friday and asserts the following Monday's digest names it as missed. A companion fixture with the alert present asserts the same window reports clean, so a wider window cannot invent a miss. A third asserts a firing that is genuinely not yet due is still skipped on the day it fires. A regression fixture asserts an ordinary weekday window with every artifact present is unchanged. Full pytest, ruff and mypy locally, and CI green before human review.

## Firewall

```
FIREWALL PASS — no forbidden path or change class touched.
```

## Merge gate

`implement` stops after pushing the branch. **Merge is human-only:** Daniel merges via pull request after Quant Lead review. No automated path to `main` exists in this pipeline.

---

<!-- IMPLEMENTATION REPORT ANCHOR -->

## Implementation report

_implemented 2026-08-30T20:49:41.373638Z  |  branch `prop/6`  |  status: **GATES PASSED**_

### Diff stat

```
src/quantlab/reporting/watchdog.py | 117 ++++++++++++++++++++++++++++--------
 tests/test_watchdog.py             | 120 ++++++++++++++++++++++++++++++++++---
 2 files changed, 204 insertions(+), 33 deletions(-)
```

### Firewall re-check (against the actual diff)

```
FIREWALL PASS — no forbidden path or change class touched.
```

### Gates

| gate | result | detail |
|---|---|---|
| `ruff` | PASS | All checks passed! |
| `mypy` | PASS | Success: no issues found in 71 source files |
| `pytest` | PASS | 711 passed, 1 warning in 89.79s (0:01:29) |
| `frontend` | SKIP | no frontend/ path in the diff |
| `verify-dist` | SKIP | site not touched |

### Branch

- branch: `prop/6`
- commit and push: performed immediately after this report was written into the proposal, since the report is part of what gets committed. The resulting SHA and push result are in the run output, and the commit itself is the one carrying this file.

### Merge gate — STOPPED HERE

This pipeline does not merge. The change sits on `prop/6` and `main` is untouched. **Daniel merges via pull request after Quant Lead review.** There is no automated path to `main` in `quantlab implement` — verified by test, not by convention.
