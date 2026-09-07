# PROP-14 — The watchdog reports an in-flight catch-up firing as a missed one

_proposed 2026-09-07T14:12:16.167325Z  |  risk class: **infrastructure**  |  status: **IMPLEMENTED — awaiting human merge**_

## Observation

On 2026-09-04 at 05:35:39Z the digest dispatched a WARNING naming both crypto paper runs as missed firings for 2026-09-04. Both had in fact completed. Their run reports were written at 05:35:35.437Z and 05:35:37.867Z, and one of them submitted an order two seconds before the WARNING was written. The same watchdog, over the identical window and the identical eight expected firings, ran again at 20:45:04Z that day and reported MISSED RUNS none: digest_20260904.json records window 2026-09-03 to 2026-09-04, firings_checked 8, missed empty. Nothing but elapsed time separates the two answers, which is what makes this a race rather than a judgement. The host left Modern Standby at 01:32:40 local and Windows released two catch-up firings together, the missed 2026-09-03 digest and the missed crypto paper job. check_schedule globs the paper reports directory once at its top, and between that glob and the alert it reads the weekly directory, scans a 186KB alert stream, and shells out to a scheduler query; the two reports landed inside that gap. The watchdog premise is that an absent artifact means the job never fired, and that premise is false while the job is still in progress. A WARNING that names a completed job as missed teaches its reader to discount the next one, and the next one is the one it exists for.

### Evidence

- `reports/alerts/alerts.jsonl`
- `reports/digests/digest_20260904.json`

## Proposed change

audit_task_deaths already recognises a scheduler row that describes a job in progress rather than one that ended: _is_own_in_flight_result excludes the digest's own record because SCHED_S_TASK_RUNNING is a state and not an ending. That recognition is scoped to one task name. Generalise it to any task. The scheduler is read before the missed-firing loop, and a job whose recorded state is SCHED_S_TASK_RUNNING is treated as in flight. A firing whose owning job is in flight is not reported as missed. It is DEFERRED rather than dropped, reusing the PROP-6 principle that skipping a check today is only honest if something checks it later: deferred firings are recorded in the digest artifact, and the next digest reads them back and re-checks them, so a firing that really was absent is named by the following digest instead of never. The report renders deferred firings explicitly, so a deferral is visible rather than silent. When the scheduler cannot be read the behaviour is unchanged, which keeps the failure direction toward alerting.

## Affected files

- `src/quantlab/reporting/watchdog.py`
- `tests/test_watchdog.py`

## Risk class

**infrastructure**

## Test plan

The 2026-09-04 race is replayed as a fixture: two expected firings with no artifact on disk, their owning task reading SCHED_S_TASK_RUNNING, must produce ZERO missed firings, zero dispatched WARNING, and two deferred entries rendered in the report. The same fixture with the task reading a settled state must still produce two missed firings and exactly one WARNING, so the exclusion is not a blanket mute. A deferred firing recorded in one digest and still absent at the next must be reported as missed by that next digest; the same firing whose artifact has since appeared must not be. Regression fixtures assert the PROP-6 deferral window, the single-WARNING rule, and the PROP-8 explained/unexplained distinction are unchanged. Full pytest, ruff and mypy locally, and CI green before human review.

## Firewall

```
FIREWALL PASS — no forbidden path or change class touched.
```

## Merge gate

`implement` stops after pushing the branch. **Merge is human-only:** Daniel merges via pull request after Quant Lead review. No automated path to `main` exists in this pipeline.

---

<!-- IMPLEMENTATION REPORT ANCHOR -->

## Implementation report

_implemented 2026-09-07T14:19:39.457157Z  |  branch `prop/14`  |  status: **GATES PASSED**_

### Diff stat

_`main..prop/14` — the whole series, not only this run's commit._

```
src/quantlab/reporting/watchdog.py | 164 +++++++++++++++++++++---
 tests/test_watchdog.py             | 253 +++++++++++++++++++++++++++++++++++++
 2 files changed, 397 insertions(+), 20 deletions(-)
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
| `pytest` | PASS | 850 passed, 1 warning in 202.83s (0:03:22) |
| `frontend` | SKIP | no frontend/ path in the diff |
| `verify-dist` | SKIP | site not touched |

### Branch

- branch: `prop/14`
- commit and push: performed immediately after this report was written into the proposal, since the report is part of what gets committed. The resulting SHA and push result are in the run output, and the commit itself is the one carrying this file.

### Merge gate — STOPPED HERE

This pipeline does not merge. The change sits on `prop/14` and `main` is untouched. **Daniel merges via pull request after Quant Lead review.** There is no automated path to `main` in `quantlab implement` — verified by test, not by convention.
