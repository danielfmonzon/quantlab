# PROP-7 — Proposal numbering is branch-local and publish force-moves an existing prop ref

_proposed 2026-08-30T21:05:38.756858Z  |  risk class: **infrastructure**  |  status: **IMPLEMENTED — awaiting human merge**_

## Observation

improve.propose.next_number reads only the docs/proposals directory present in the current working tree, and improve.propose.publish_proposal then points prop/{number} at HEAD with git branch --force. Neither step consults what already exists elsewhere in the repository. On 2026-08-30 this destroyed work: PROP-5 had been written, implemented and pushed on prop/5, and a later propose invocation run from main -- where docs/proposals holds only PROP-1 through PROP-4, because PROP-5 lives on its own branch -- numbered the new proposal 5 and then force-moved the local prop/5 pointer onto it. The PROP-5 commit survived only because it had already been pushed and could be restored from origin/prop/5. Had propose been run before that push, the branch pointer would have been the only reference to the commit and the work would have been recoverable from the reflog alone, or not at all. The comment above the force call states that force is safe because the ref is one this command owns. That is the defect stated as a justification: the ref is not owned by the invocation, it may already name another proposal's in-flight work, and nothing checks. Both halves are needed for the failure, and either alone is still wrong: branch-local numbering silently reuses a number that is in use, and an unconditional force write discards whatever the reused number already pointed at.

### Evidence

- `docs/proposals/PROP-5-persist-fill-evidence-in-run-reports-and-attribute-fill-vs-m.md`
- `docs/proposals/PROP-6-the-watchdog-cannot-verify-any-task-due-after-the-digest-tha.md`
- `docs/decisions.md`

## Proposed change

Numbering becomes global: the next number is one above the highest seen either in docs/proposals on disk or among the prop/N references that already exist locally and on the remote, so a number in use anywhere is never handed out again. Publishing then asserts before it creates: if prop/N already exists, propose raises and writes nothing, and the git branch invocation drops --force so that even a defeated assertion cannot overwrite a reference. The assertion is evaluated from a set of taken numbers supplied by the caller, so on a collision it raises before publish_proposal issues a single git command. Nothing else about propose moves: what it writes, where it commits, the prop-namespace guard and the bounded push are all unchanged.

## Affected files

- `src/quantlab/improve/propose.py`
- `tests/test_improve_pipeline.py`

## Risk class

**infrastructure**

## Test plan

A recording runner that captures every git invocation without executing any is injected into publish_proposal, which is called with a number already present in the supplied taken set; the test asserts a collision error is raised and that the recorder captured zero commands, proving nothing was committed, pointed or pushed. A companion test with a free number asserts the branch is created without a force argument anywhere in the recorded argv. A numbering test seeds a proposals directory holding PROP-1 and a reference set holding 5 and asserts the next number is 6, reproducing the exact shape of the 2026-08-30 collision. A regression test asserts a clean repository with no prop references numbers exactly as it does today. Full pytest, ruff and mypy locally, and CI green before human review.

## Firewall

```
FIREWALL PASS — no forbidden path or change class touched.
```

## Merge gate

`implement` stops after pushing the branch. **Merge is human-only:** Daniel merges via pull request after Quant Lead review. No automated path to `main` exists in this pipeline.

---

<!-- IMPLEMENTATION REPORT ANCHOR -->

## Implementation report

_implemented 2026-08-30T21:10:06.650564Z  |  branch `prop/7`  |  status: **GATES PASSED**_

### Diff stat

```
src/quantlab/improve/propose.py | 103 ++++++++++++++++++++++++++++++++++------
 tests/test_improve_pipeline.py  | 102 ++++++++++++++++++++++++++++++++++++++-
 2 files changed, 189 insertions(+), 16 deletions(-)
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
| `pytest` | PASS | 717 passed, 1 warning in 88.32s (0:01:28) |
| `frontend` | SKIP | no frontend/ path in the diff |
| `verify-dist` | SKIP | site not touched |

### Branch

- branch: `prop/7`
- commit and push: performed immediately after this report was written into the proposal, since the report is part of what gets committed. The resulting SHA and push result are in the run output, and the commit itself is the one carrying this file.

### Merge gate — STOPPED HERE

This pipeline does not merge. The change sits on `prop/7` and `main` is untouched. **Daniel merges via pull request after Quant Lead review.** There is no automated path to `main` in `quantlab implement` — verified by test, not by convention.
