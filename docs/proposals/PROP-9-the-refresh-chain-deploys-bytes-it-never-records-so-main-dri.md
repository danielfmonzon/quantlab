# PROP-9 — The refresh chain deploys bytes it never records, so main drifts from the live site

_proposed 2026-08-30T23:30:54.249703Z  |  risk class: **infrastructure**  |  status: **IMPLEMENTED — awaiting human merge**_

## Observation

The published Glass Box is deployed from frontend/dist by Netlify, not from git, so the repository has no mechanism that ties what is on main to what the site is serving. On 2026-08-28 the chain wrote its captures and then died before building them, and on 2026-08-30 a manual re-run deployed a set that existed only in the working tree; between the two, anyone reading main to answer what does the site currently say got the 2026-08-22 answer while the site served 08-30. That gap was closed by hand in PR 15, which committed 46 files and verified them against the deployed manifest, and the commit message for it says plainly that it makes main truthful as of now and not self-maintaining. Nothing prevents the same drift reopening on the very next publish, because the chain still has no step that records what it published. The captures are the only artifact in the system with this property: every other thing the chain touches is either already in git or is not published at all.

### Evidence

- `reports/alerts/alerts.jsonl`
- `docs/decisions.md`
- `reports/digests/digest_20260828.md`

## Proposed change

The chain gains a final step that runs only after deploy has PASSED. It commits the snapshot files it just published to a new branch named for the day, pushes that branch, and opens a pull request titled for the refresh date, leaving the merge to a human exactly as every other change in this repository does. It never writes to the trunk and has no path that could: the branch name is generated from the date, the branch is asserted not to exist before it is created, and the create carries no force argument, so a second run on the same day refuses rather than moving a reference. A failure anywhere in this step does NOT retroactively fail the publish that already succeeded -- the bytes are live and saying otherwise would be false. It downgrades the outcome to a warning, records why in the chain report, and leaves every earlier step reading exactly as it did. The Friday routine gains one merge click, and frontend README gains the paragraph that says so.

## Affected files

- `src/quantlab/glassbox/refresh.py`
- `tests/test_glassbox_refresh.py`
- `frontend/README.md`

## Risk class

**infrastructure**

## Test plan

A recording runner captures every git and gh invocation without executing any. A fixture with a clean deploy asserts the branch is created with no force argument in the recorded argv, that the push targets the generated branch and never the trunk, and that the pull request title carries the refresh date. A collision fixture asserts that when the branch already exists the step raises before a single git command is recorded, so nothing is committed, pushed or opened. A failure fixture makes the push fail and asserts the deploy step still reads PASS, the report still carries the deploy URL, and the overall outcome is a warning rather than an abort. A dry-run fixture asserts the step does not run at all. A regression fixture asserts a chain that aborts before deploy never reaches the step. Full pytest, ruff and mypy locally, and CI green before human review.

## Firewall

```
FIREWALL PASS — no forbidden path or change class touched.
```

## Merge gate

`implement` stops after pushing the branch. **Merge is human-only:** Daniel merges via pull request after Quant Lead review. No automated path to `main` exists in this pipeline.

---

<!-- IMPLEMENTATION REPORT ANCHOR -->

## Implementation report

_implemented 2026-08-30T23:36:11.823934Z  |  branch `prop/9`  |  status: **GATES PASSED**_

### Diff stat

```
frontend/README.md               |  23 +++++
 src/quantlab/glassbox/refresh.py | 214 ++++++++++++++++++++++++++++++++++++++-
 tests/test_glassbox_refresh.py   | 184 ++++++++++++++++++++++++++++++++-
 3 files changed, 415 insertions(+), 6 deletions(-)
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
| `pytest` | PASS | 747 passed, 1 warning in 81.31s (0:01:21) |
| `frontend` | PASS | [2m   Duration [22m 8.09s[2m (transform 975ms, setup 4.17s, collect 5.90s, tests 6.61s, environment 13.04s, prepare 2.14s)[22m |
| `frontend-lint` | PASS | > tsc -b --noEmit |
| `verify-dist` | PASS | {"files": 212, "event": "verify_dist_passed", "logger": "quantlab.cli", "level": "info", "timestamp": "2026-08-30T23:37:53.368095Z"} |

### Branch

- branch: `prop/9`
- commit and push: performed immediately after this report was written into the proposal, since the report is part of what gets committed. The resulting SHA and push result are in the run output, and the commit itself is the one carrying this file.

### Merge gate — STOPPED HERE

This pipeline does not merge. The change sits on `prop/9` and `main` is untouched. **Daniel merges via pull request after Quant Lead review.** There is no automated path to `main` in `quantlab implement` — verified by test, not by convention.
