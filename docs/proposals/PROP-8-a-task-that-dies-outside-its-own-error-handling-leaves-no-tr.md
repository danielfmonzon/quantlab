# PROP-8 — A task that dies outside its own error handling leaves no trace anywhere

_proposed 2026-08-30T23:19:42.009683Z  |  risk class: **infrastructure**  |  status: **AWAITING IMPLEMENTATION**_

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

