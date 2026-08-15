# PROP-2 — Proposals should be committed at propose time, not created on the implementation branch

_proposed 2026-08-15T19:07:04.257703Z  |  risk class: **infrastructure**  |  status: **AWAITING IMPLEMENTATION**_

## Observation

propose writes docs/proposals/PROP-n as an UNTRACKED file in the working tree, and implement is what first commits it - onto prop/n. The analysis record therefore exists only on the implementation branch. Three consequences, one of them observed during the PROP-1 dogfood on 2026-08-15: switching back to main removes the proposal from the working tree, and deleting the branch destroys it outright. That happened - prop/1 was rebuilt after a defect was found in the report writer, and the proposal file had to be recovered from origin/prop/1 by hand before implement could find it again. Two further gaps follow from the same root: a proposal that is written and never implemented leaves no record anywhere, so there is no trace that the analysis was done and set aside; and a proposal refused by the firewall and then revised has no dated predecessor to compare against. The record of what was considered is as much a part of an auditable pipeline as the record of what was done.

### Evidence

- `docs/proposals`
- `docs/decisions.md`

## Proposed change

propose commits the new file on the branch it is run from, at propose time, with status AWAITING IMPLEMENTATION - so the analysis is recorded the moment it is made, independent of whether it is ever implemented. implement continues to write the implementation report, which lands on prop/n as part of that branch's commit, and additionally flips the status line to record that the proposal has been implemented and is awaiting human merge. A --no-commit escape hatch is kept for scripted or exploratory use. Note the bootstrap: PROP-2 is itself created under the old behaviour and is the last proposal that will be.

## Affected files

- `src/quantlab/improve/propose.py`
- `src/quantlab/improve/implement.py`
- `tests/test_improve_pipeline.py`

## Risk class

**infrastructure**

## Test plan

Assert propose leaves the proposal tracked and committed on the branch it ran from, with a clean working tree afterwards. Assert the file survives a checkout to another branch and back. Assert --no-commit leaves it untracked as before. Assert implement still appends the report and that the status line reads implemented on the branch while main keeps AWAITING until merge. The existing pipeline tests must stay green, including the two proving implement never touches main. Full pytest, ruff, mypy.

## Firewall

```
FIREWALL PASS — no forbidden path or change class touched.
```

## Merge gate

`implement` stops after pushing the branch. **Merge is human-only:** Daniel merges via pull request after Quant Lead review. No automated path to `main` exists in this pipeline.

---

<!-- IMPLEMENTATION REPORT ANCHOR -->

## Implementation report

_implemented 2026-08-15T19:12:38.006805Z  |  branch `prop/2`  |  status: **GATES PASSED**_

### Diff stat

```
src/quantlab/cli.py               | 11 +++++-
 src/quantlab/improve/implement.py | 13 ++++++-
 src/quantlab/improve/propose.py   | 65 ++++++++++++++++++++++++++++++++--
 tests/test_improve_pipeline.py    | 73 +++++++++++++++++++++++++++++++++++----
 4 files changed, 151 insertions(+), 11 deletions(-)
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
| `pytest` | PASS | 672 passed, 1 warning in 113.77s (0:01:53) |
| `frontend` | SKIP | no frontend/ path in the diff |
| `verify-dist` | SKIP | site not touched |

### Branch

- branch: `prop/2`
- commit and push: performed immediately after this report was written into the proposal, since the report is part of what gets committed. The resulting SHA and push result are in the run output, and the commit itself is the one carrying this file.

### Merge gate — STOPPED HERE

This pipeline does not merge. The change sits on `prop/2` and `main` is untouched. **Daniel merges via pull request after Quant Lead review.** There is no automated path to `main` in `quantlab implement` — verified by test, not by convention.
