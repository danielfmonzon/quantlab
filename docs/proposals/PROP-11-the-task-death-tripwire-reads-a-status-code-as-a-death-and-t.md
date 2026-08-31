# PROP-11 — The task-death tripwire reads a status code as a death and the known Aug 28 death as a recurrence

_proposed 2026-08-31T22:46:30.569083Z  |  risk class: **infrastructure**  |  status: **IMPLEMENTED — awaiting human merge**_

## Observation

The 2026-08-31 digest reported TASK DEATHS (2) and dispatched one CRITICAL headed "post-battery-hardening recurrence, escalate to Quant Lead". Neither entry is a recurrence, and neither warranted that alert. The tripwire's first two live firings were both false.

The first entry is `quantlab-digest` itself, result 267009 -- 0x00041301, SCHED_S_TASK_RUNNING. That is not an exit code at all. It is the scheduler answering "what is this task doing" with "it is running", and what it was running was the very digest that read it. Two independent defects produce it. `unexplained_task_deaths` treats every non-zero result as an ending, but the SCHED_S_* family (0x00041300 through 0x00041306) are success-severity HRESULTs describing a task's state rather than the outcome of one. And the digest audits its own task while that task is in flight, so its own record is guaranteed to read as in-progress on every run -- a CRITICAL at 16:45 every single day, forever, for as long as the check exists.

The second entry is `quantlab-glassbox-refresh`, result -2147023829 at 2026-08-28T17:30:00. That is the known 2026-08-28 non-publish: diagnosed in the dated ruling of 2026-08-30, and the incident this tripwire was built for. It PREDATES the battery hardening applied the same day. The CRITICAL's own body explains that the battery settings "were disarmed on all five tasks on 2026-08-30, so a recurrence is a new fact and not the known one" -- and then fires on the known one anyway, because nothing in the code compares the recorded instant against that date. The distinction is asserted in the alert body and enforced nowhere.

Precision is the only thing a CRITICAL has. This one names the Quant Lead, fires on a permanent daily false positive and on an incident that was closed the day before it shipped, and a CRITICAL that was wrong twice out of two is one nobody reads the third time -- and the third is the one it exists for.

### Evidence

- `reports/digests/digest_20260831.md`
- `reports/digests/digest_20260831.json`
- `reports/alerts/alerts.jsonl`
- `docs/decisions.md`

## Proposed change

Three narrowings in `reporting.watchdog`. Every one of them makes the tripwire fire on strictly less; none widens it, and the missed-firing half of the watchdog is not touched.

1. A result in the SCHED_S_* status family (0x00041300 through 0x00041306) is never a failure, and is skipped before any other test. The seven codes are listed by name so a reader can see which is which. Separately and independently, the audit skips its own task's in-flight record: a result recorded for `quantlab-digest` on the day the audit is itself running describes that run, and a task that fires once a day has no other record on that day for the rule to hide. A death of yesterday's digest still carries yesterday's date and is audited exactly as before.

2. Every death is classified against the instant the battery hardening was applied, recorded as a single named constant with its derivation in the docstring and compared in the scheduler's own local frame. A death recorded after it is a recurrence and keeps today's CRITICAL verbatim. A death recorded before it is reported as known and pre-hardening at WARNING, pointing at the ruling that already covers it. A death whose instant cannot be read is treated as a recurrence: when the instant is unknown, the louder of the two is the safe direction.

3. An acknowledged-deaths ledger at `config/acknowledged_task_deaths.json`, holding the task, the result, the instant the death was recorded, and the ruling that closed it. A death matching all three fields is rendered in the report as acknowledged and dispatches nothing, so a death that has been diagnosed and ruled on stops re-firing without the check going blind to it. It ships seeded with the 2026-08-28 refresh death. An absent or malformed ledger acknowledges nothing at all, so its failure direction is toward alerting.

The report renders all three outcomes -- recurrence, known pre-hardening, acknowledged -- and still renders "TASK DEATHS: none" when there are none, so a check that has stopped working stays as visible as it is today.

## Affected files

- `src/quantlab/reporting/watchdog.py`
- `src/quantlab/reporting/digest.py`
- `config/acknowledged_task_deaths.json`
- `tests/test_watchdog.py`
- `docs/decisions.md`

## Risk class

**infrastructure**

## Test plan

The two records from the 2026-08-31 digest, verbatim -- `quantlab-digest` 267009 at 2026-08-31T16:45:00 and `quantlab-glassbox-refresh` -2147023829 at 2026-08-28T17:30:00 -- are driven through `build_digest` against an empty ledger and must produce ZERO CRITICAL and exactly one WARNING, naming the refresh as the known pre-hardening death. The same two records against the shipped ledger must dispatch nothing at all and render the refresh as acknowledged. A synthetic death of the same task after the hardening instant must produce exactly one CRITICAL carrying the recurrence wording.

Unit fixtures cover each half: all seven SCHED_S_* codes yield no death for any task; a real non-zero result on the same task in the same call still yields one, so the family test is not a blanket mute; the digest's own record on the audit's own day is skipped while a digest record from a previous day is still named; an acknowledgement must match task, result and instant together, with a differing instant still firing; and a malformed ledger acknowledges nothing. A regression fixture asserts the PROP-6 missed-firing window, its single WARNING and the PROP-8 explained/unexplained distinction are unchanged. Full pytest, ruff and mypy locally, and CI green before human review.

## Firewall

```
FIREWALL PASS — no forbidden path or change class touched.
```

## Merge gate

`implement` stops after pushing the branch. **Merge is human-only:** Daniel merges via pull request after Quant Lead review. No automated path to `main` exists in this pipeline.

---

<!-- IMPLEMENTATION REPORT ANCHOR -->

## Implementation report

_implemented 2026-08-31T22:57:01.705152Z  |  branch `prop/11`  |  status: **NEEDS ATTENTION**_

### Diff stat

```
config/acknowledged_task_deaths.json |  13 ++
 docs/decisions.md                    |  83 +++++++++
 src/quantlab/reporting/digest.py     |  63 +++++--
 src/quantlab/reporting/watchdog.py   | 314 ++++++++++++++++++++++++++++++++---
 tests/test_watchdog.py               | 311 ++++++++++++++++++++++++++++++++++
 5 files changed, 750 insertions(+), 34 deletions(-)
```

### Firewall re-check (against the actual diff)

```
FIREWALL PASS — no forbidden path or change class touched.
```

### Gates

| gate | result | detail |
|---|---|---|
| `ruff` | FAIL | error: failed to remove file `C:\Users\danmo\Dev\quantlab\.venv\Lib\site-packages\../../Scripts/quantlab.exe`: The process cannot access the file because it is being used by another process. (os error |
| `mypy` | FAIL | error: failed to remove file `C:\Users\danmo\Dev\quantlab\.venv\Lib\site-packages\../../Scripts/quantlab.exe`: The process cannot access the file because it is being used by another process. (os error |
| `pytest` | FAIL | error: failed to remove file `C:\Users\danmo\Dev\quantlab\.venv\Lib\site-packages\../../Scripts/quantlab.exe`: The process cannot access the file because it is being used by another process. (os error |
| `frontend` | SKIP | no frontend/ path in the diff |
| `verify-dist` | SKIP | site not touched |

### Branch

- branch: `prop/11`
- commit and push: performed immediately after this report was written into the proposal, since the report is part of what gets committed. The resulting SHA and push result are in the run output, and the commit itself is the one carrying this file.

### Merge gate — STOPPED HERE

This pipeline does not merge. The change sits on `prop/11` and `main` is untouched. **Daniel merges via pull request after Quant Lead review.** There is no automated path to `main` in `quantlab implement` — verified by test, not by convention.
