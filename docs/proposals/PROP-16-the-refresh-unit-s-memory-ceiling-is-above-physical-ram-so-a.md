# PROP-16 — The refresh unit's memory ceiling is above physical RAM so an OOM cannot be reported as one

_proposed 2026-09-07T16:25:16.397712Z  |  risk class: **infrastructure**  |  status: **IMPLEMENTED — awaiting human merge**_

## Observation

The Glass Box refresh unit declares MemoryMax=3G. The provisioned host has 1,919 MiB of physical memory, so that ceiling is above everything the machine has and can never be reached by an in-memory allocation; the host swaps first, and a job that swaps into a 4 GB swapfile degrades quietly instead of ending. The value was chosen on 2026-09-07 against a 4 GB machine that was recommended and not the CPX11 that was provisioned, so it is a number that no longer describes anything. Phase 0 measured the public build at 705 MiB of whole-machine committed memory at peak, with 258 MiB and 327 MiB of resident set across its two steps, so a ceiling under physical memory still leaves ample room above the real figure. The point of having a ceiling at all is that systemd reports Result=oom-kill, which the ported death tripwire reads as a NAMED cause; a ceiling nothing can reach converts that named ending back into the silent degradation this migration exists to remove, and does it on the one job that has already died twice. Separately, every timer carries AccuracySec=1s. It asks systemd for a tighter wake-up than anything here needs and buys nothing: what protects the mark is the absence of RandomizedDelaySec, not accuracy, and a value that looks protective while protecting nothing is worth removing before anyone relies on it.

### Evidence

- `docs/decisions.md`
- `docs/proposals`

## Proposed change

MemoryMax on the refresh service becomes 1500M, below the host's physical memory, so an allocation that runs away is killed and reported as Result=oom-kill instead of swapping. AccuracySec is dropped from every timer, restoring the systemd default. The rendered files under deploy/systemd are regenerated from the same functions so the reviewed artifacts and the generator stay identical. A test asserts no unit declares a ceiling that a small host cannot enforce, so the value cannot drift back above physical memory unnoticed. Neither edit moves a firing instant and no OnCalendar changes.

## Affected files

- `src/quantlab/scheduling/systemd.py`
- `deploy/systemd/quantlab-glassbox-refresh.service`
- `tests/test_systemd_migration.py`

## Risk class

**infrastructure**

## Test plan

A unit test asserts every rendered MemoryMax parses to at most 2G, and that the refresh unit specifically is at most 1500M, so a future edit above plausible host memory fails rather than silently disarming the oom-kill report. Another asserts no timer declares AccuracySec. The existing test that the committed deploy/systemd files match render_units() byte-for-byte covers the regeneration. Full pytest, ruff and mypy locally, and CI green before human review.

## Firewall

```
FIREWALL PASS — no forbidden path or change class touched.
```

## Merge gate

`implement` stops after pushing the branch. **Merge is human-only:** Daniel merges via pull request after Quant Lead review. No automated path to `main` exists in this pipeline.

---

<!-- IMPLEMENTATION REPORT ANCHOR -->

## Implementation report

_implemented 2026-09-07T16:26:06.068131Z  |  branch `prop/16`  |  status: **GATES PASSED**_

### Diff stat

_`main..prop/16` — the whole series, not only this run's commit._

```
deploy/systemd/quantlab-crypto-paper-run.timer   |  1 -
 deploy/systemd/quantlab-digest.timer             |  1 -
 deploy/systemd/quantlab-glassbox-refresh.service |  2 +-
 deploy/systemd/quantlab-glassbox-refresh.timer   |  1 -
 deploy/systemd/quantlab-paper-run.timer          |  1 -
 deploy/systemd/quantlab-weekly.timer             |  1 -
 src/quantlab/scheduling/systemd.py               | 19 +++++++---
 tests/test_systemd_migration.py                  | 46 ++++++++++++++++++++++++
 8 files changed, 62 insertions(+), 10 deletions(-)
```

### Firewall re-check (against the actual diff)

```
FIREWALL PASS — no forbidden path or change class touched.
```

### Gates

| gate | result | detail |
|---|---|---|
| `ruff` | PASS | All checks passed! |
| `mypy` | PASS | Success: no issues found in 73 source files |
| `pytest` | PASS | 906 passed, 1 skipped, 1 warning in 221.61s (0:03:41) |
| `frontend` | SKIP | no frontend/ path in the diff |
| `verify-dist` | SKIP | site not touched |

### Branch

- branch: `prop/16`
- commit and push: performed immediately after this report was written into the proposal, since the report is part of what gets committed. The resulting SHA and push result are in the run output, and the commit itself is the one carrying this file.

### Merge gate — STOPPED HERE

This pipeline does not merge. The change sits on `prop/16` and `main` is untouched. **Daniel merges via pull request after Quant Lead review.** There is no automated path to `main` in `quantlab implement` — verified by test, not by convention.
