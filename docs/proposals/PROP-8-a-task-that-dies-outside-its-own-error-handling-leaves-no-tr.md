# PROP-8 — A task that dies outside its own error handling leaves no trace anywhere

_proposed 2026-08-30T23:19:42.009683Z  |  risk class: **infrastructure**  |  status: **IMPLEMENTED — awaiting human merge**_

## Observation

On 2026-08-28 the Glass Box refresh process was terminated after it had written its snapshot and before its build step returned. Nothing recorded it. reports/logs/quantlab.jsonl carries no record from that chain for the day, alerts.jsonl carries none between the weekly WARNING at 21:01:30 and the next paper INFO after midnight, and the only evidence that anything went wrong is the Windows Task Scheduler field Last Result, which reads -2147023829 -- ERROR_PROCESS_ABORTED, the process terminated unexpectedly. The chain's own abort path is intact and is not what failed: it logs at error level and then dispatches, on every in-code failure path, and the absence of both proves it never executed. A killed process cannot alert about being killed. The daily digest reads only artifacts the system itself produced, so a firing that produced no artifact because it died is indistinguishable to it from one that produced no artifact because it never started, and PROP-6's deferred check names it as a missed firing with the wrong explanation attached. Meanwhile the scheduler recorded the truth in a field nothing reads. The battery settings that were the leading suspect are now disarmed on all five tasks, so a recurrence would be a genuinely new fact and needs to be visible as one rather than rediscovered by hand.

### Evidence

- `reports/digests/digest_20260828.md`
- `reports/alerts/alerts.jsonl`
- `docs/decisions.md`

## Proposed change

The digest watchdog gains a second check alongside the artifact one. For every quantlab task it reads the scheduler's recorded Last Result and the instant that result was recorded, through an injectable reader so the parsing is testable without a scheduler present, and guarded by platform so the check reports itself unavailable rather than failing on a host that has no such scheduler. A non-zero result whose day carries no in-code failure record attributable to that task -- no alert from its own source, no error-level log entry from its own logger -- fires exactly one CRITICAL naming the task, the numeric result and the instant it was recorded. A non-zero result that does have such a record raises nothing extra, because the task already alerted for itself and a second alert for one failure trains its reader to ignore both. A zero result is silent. The existing missed-firing check, its window and its single WARNING are untouched.

## Affected files

- `src/quantlab/reporting/watchdog.py`
- `src/quantlab/reporting/digest.py`
- `tests/test_watchdog.py`

## Risk class

**infrastructure**

## Test plan

A fixture supplies a recorded result of -2147023829 for the refresh task with no matching failure record and asserts exactly one CRITICAL is dispatched, naming the task, the numeric result and the recorded instant. A companion supplies a non-zero result of 3 together with a matching in-code failure record and asserts nothing additional is dispatched. A third supplies zero for every task and asserts silence. A fourth asserts that on a host with no such scheduler the check reports unavailable and dispatches nothing, so the suite is meaningful on the Linux runner as well as the workstation. A regression fixture asserts the missed-firing section and its single WARNING are byte-identical to today's output. Full pytest, ruff and mypy locally, and CI green before human review.

## Firewall

```
FIREWALL PASS — no forbidden path or change class touched.
```

## Merge gate

`implement` stops after pushing the branch. **Merge is human-only:** Daniel merges via pull request after Quant Lead review. No automated path to `main` exists in this pipeline.

---

<!-- IMPLEMENTATION REPORT ANCHOR -->

## Implementation report

_implemented 2026-08-30T23:28:04.246982Z  |  branch `prop/8`  |  status: **GATES PASSED**_

### Diff stat

```
src/quantlab/reporting/digest.py   |  43 +++++-
 src/quantlab/reporting/watchdog.py | 294 ++++++++++++++++++++++++++++++++++++-
 tests/test_watchdog.py             | 217 +++++++++++++++++++++++++++
 3 files changed, 548 insertions(+), 6 deletions(-)
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
| `pytest` | PASS | 749 passed, 1 warning in 129.54s (0:02:09) |
| `frontend` | SKIP | no frontend/ path in the diff |
| `verify-dist` | SKIP | site not touched |

### Branch

- branch: `prop/8`
- commit and push: performed immediately after this report was written into the proposal, since the report is part of what gets committed. The resulting SHA and push result are in the run output, and the commit itself is the one carrying this file.

### Merge gate — STOPPED HERE

This pipeline does not merge. The change sits on `prop/8` and `main` is untouched. **Daniel merges via pull request after Quant Lead review.** There is no automated path to `main` in `quantlab implement` — verified by test, not by convention.
