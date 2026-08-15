# PROP-3 — Durable-at-propose via a bounded push to prop refs only

_proposed 2026-08-15T20:05:22.575750Z  |  risk class: **infrastructure**  |  status: **IMPLEMENTED — awaiting human merge**_

## Observation

PROP-2 made the proposal durable by committing it at propose time, but only on the machine it ran from. With the protect-main ruleset in force a direct push to main is rejected, so a proposal committed on main can never reach origin: the record survives a branch switch and a branch deletion, which were the observed PROP-1 failures, but it does not survive the loss of this checkout and is invisible to any other clone. A proposal that is written and never implemented therefore still has no off-machine trace, which is the gap PROP-2 set out to close and only half closed. The remaining risk is asymmetric - the analysis is exactly the artifact that is cheap to produce and expensive to reconstruct, because it carries the dated reasoning and the evidence paths that were true at the time.

### Evidence

- `docs/proposals`
- `docs/decisions.md`

## Proposed change

propose seeds a branch for the proposal and pushes it, so the record is durable on the remote the moment the analysis is made. The push target is bounded IN CODE: a guard validates the ref name and raises UnsafePushTarget for anything that is not a prop ref, and it raises BEFORE any git subprocess is constructed, so a bad target cannot reach the network even transiently. No pull request is opened at propose time - a proposal is not a request to merge anything, and opening one would put unreviewed analysis into the review queue. implement opens the pull request once every gate has passed, which is the first moment a request to merge is meaningful. The human merge gate is unchanged and implement still never merges.

## Affected files

- `src/quantlab/improve/propose.py`
- `src/quantlab/improve/implement.py`
- `tests/test_improve_pipeline.py`

## Risk class

**infrastructure**

## Test plan

A recording runner is injected that captures every git invocation and executes none. The guard test asserts that a non-prop ref raises UnsafePushTarget AND that the recorder captured exactly zero invocations, so before any git call is an observable property rather than an ordering claim. Parametrised over main, origin/main, an empty string, a bare prefix, and a traversal attempt. Further tests assert propose pushes only its own ref, that no pull request is opened at propose time, that implement opens one when gates pass and does not when they fail, and that the existing proofs that implement never touches main stay green. Full pytest, ruff, mypy, and CI must be green before human review.

## Firewall

```
FIREWALL PASS — no forbidden path or change class touched.
```

## Merge gate

`implement` stops after pushing the branch. **Merge is human-only:** Daniel merges via pull request after Quant Lead review. No automated path to `main` exists in this pipeline.

---

<!-- IMPLEMENTATION REPORT ANCHOR -->

## Implementation report

_implemented 2026-08-15T20:15:27.865319Z  |  branch `prop/3`  |  status: **GATES PASSED**_

### Diff stat

```
src/quantlab/improve/implement.py |  63 ++++++++++++++++-
 src/quantlab/improve/propose.py   | 145 ++++++++++++++++++++++++++++++++++++--
 tests/test_improve_pipeline.py    | 132 ++++++++++++++++++++++++++++++++--
 3 files changed, 328 insertions(+), 12 deletions(-)
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
| `pytest` | PASS | 691 passed, 1 warning in 84.84s (0:01:24) |
| `frontend` | SKIP | no frontend/ path in the diff |
| `verify-dist` | SKIP | site not touched |

### Branch

- branch: `prop/3`
- commit and push: performed immediately after this report was written into the proposal, since the report is part of what gets committed. The resulting SHA and push result are in the run output, and the commit itself is the one carrying this file.

### Merge gate — STOPPED HERE

This pipeline does not merge. The change sits on `prop/3` and `main` is untouched. **Daniel merges via pull request after Quant Lead review.** There is no automated path to `main` in `quantlab implement` — verified by test, not by convention.
