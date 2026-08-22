# PROP-4 — Weekly verdict is INSUFFICIENT when the comparison window predates the requested week

_proposed 2026-08-22T20:11:23.298677Z  |  risk class: **infrastructure**  |  status: **IMPLEMENTED — awaiting human merge**_

## Observation

week_20260821.md reports verdict TRACKING for all four accounts. The comparison window it describes is 2026-08-10 -> 2026-08-14 for both equity accounts and 2026-08-11 -> 2026-08-17 for both crypto accounts. The requested week began 2026-08-15, so none of those windows lie inside the week that was asked for. That week held one usable mark day for the equity accounts: the interpreter the scheduled tasks launch was uninstalled on 2026-08-17 and no task produced an artifact again until 2026-08-22. The weekly builds its window from the last N snapshots on or before the requested week end, so when the requested week is empty the window reaches back into earlier weeks and the verdict then describes days the reader did not ask about. The sparsity is stated plainly elsewhere in the same document, in 'runs this week: 1 attempted, 1 completed' and in the readiness blockers, but the verdict line is the line a reader skims and it says TRACKING. A reader scanning the four verdicts sees a clean week over a period in which the system produced almost no marks at all, and this document is the record the 90-day readiness review reads back. Separately, the missed-firing warning in the daily digest tells the reader that a missed firing means the task never ran, most often because the host was off. digest_20260822.md carries that sentence above 20 missed firings whose cause was different: the host was on and awake for every one of them, and the runtime beneath the tasks was gone. The sentence sends the first diagnostic step to the wrong place.

### Evidence

- `reports/weekly/week_20260821.md`
- `reports/digests/digest_20260822.md`
- `docs/decisions.md`

## Proposed change

An account whose comparison window begins before the requested week start reports verdict INSUFFICIENT rather than TRACKING or DIVERGING, and carries a one-line note naming the fallback week it actually describes. A return needs two marks, so a window that reaches into earlier weeks to find them is reporting on a different period than the one requested and should name that period rather than let the verdict speak for it. Readiness blockers are untouched. The divergence figures, the mark-phase decomposition, the alerting rule and the existing account notes are all untouched: what changes is which word the verdict line prints and the note printed beside it. The digest missed-firing sentence becomes '(host off, or the runtime itself broken)' so the first diagnostic step covers both causes the record now shows.

## Affected files

- `src/quantlab/reporting/weekly.py`
- `src/quantlab/reporting/digest.py`
- `tests/test_weekly.py`
- `tests/test_watchdog.py`

## Risk class

**infrastructure**

## Test plan

A fixture builds an equity account whose history holds a full prior week plus a single mark inside the requested week, which is the shape week_20260821 had. It asserts the verdict is INSUFFICIENT, that the note names the fallback week actually described, and that the readiness blockers are byte-identical to the pre-change output. A companion fixture with a fully populated requested week asserts the verdict is still TRACKING and no note is added, so the change cannot fire on a healthy week. A digest test asserts the missed-firing body contains the new wording. Full pytest, ruff and mypy locally, and CI green before human review.

## Firewall

```
FIREWALL PASS — no forbidden path or change class touched.
```

## Merge gate

`implement` stops after pushing the branch. **Merge is human-only:** Daniel merges via pull request after Quant Lead review. No automated path to `main` exists in this pipeline.

---

<!-- IMPLEMENTATION REPORT ANCHOR -->

## Implementation report

_implemented 2026-08-22T20:24:24.776960Z  |  branch `prop/4`  |  status: **GATES PASSED**_

### Diff stat

```
src/quantlab/reporting/digest.py |  5 ++-
 src/quantlab/reporting/weekly.py | 35 +++++++++++++++++-
 tests/test_watchdog.py           |  6 +++
 tests/test_weekly.py             | 80 ++++++++++++++++++++++++++++++++++++++++
 4 files changed, 123 insertions(+), 3 deletions(-)
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
| `pytest` | PASS | 695 passed, 1 warning in 70.12s (0:01:10) |
| `frontend` | SKIP | no frontend/ path in the diff |
| `verify-dist` | SKIP | site not touched |

### Branch

- branch: `prop/4`
- commit and push: performed immediately after this report was written into the proposal, since the report is part of what gets committed. The resulting SHA and push result are in the run output, and the commit itself is the one carrying this file.

### Merge gate — STOPPED HERE

This pipeline does not merge. The change sits on `prop/4` and `main` is untouched. **Daniel merges via pull request after Quant Lead review.** There is no automated path to `main` in `quantlab implement` — verified by test, not by convention.
