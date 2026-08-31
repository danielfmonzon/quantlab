# PROP-12 — implement cannot gate itself when it is driven through its own console script

_proposed 2026-08-31T23:07:16.062723Z  |  risk class: **infrastructure**  |  status: **IMPLEMENTED — awaiting human merge**_

## Observation

PROP-11 was implemented twice. The first attempt, commit 256d3b9, reported every gate as FAILED with an identical detail on all three:

    error: failed to remove file `...\.venv\Lib\site-packages\../../Scripts/quantlab.exe`:
    The process cannot access the file because it is being used by another process.

Nothing was wrong with the code. `implement` had been invoked as `.venv/Scripts/quantlab.exe implement 11`, and its gates shell out through `uv run`, which resynchronises the project before executing anything -- including reinstalling the editable package, which means replacing `Scripts/quantlab.exe`. On Windows that file is held open by the process that is running it, which was `implement` itself. The gates did not fail; they never executed.

The pipeline then behaved exactly as designed, which is the only reason this was cheap. It refused to open a pull request on a red report, pushed the branch as evidence, and stopped. The same invocation re-run as `python -m quantlab.cli implement 11` passed all three gates and opened the PR. But it left a wrong record on the branch, and one that is quiet rather than loud: a report claiming a full gate failure over a diff that was in fact green.

The second attempt left a second defect in the record. `implement` computes its diff stat from the staged diff, which is the work of THAT invocation alone. Because the code had already been committed by the first attempt, the surviving report -- the durable artifact a reviewer reads -- shows `1 file changed, 1 insertion(+), 40 deletions(-)` for a change that was 6 files and 786 insertions. The gates themselves ran over the whole tree, so GATES PASSED is true; the diff stat beside it understates what was gated by two orders of magnitude. Any re-run of `implement` on an existing branch produces the same understatement, not just this one.

### Evidence

Both are on `main`: the proposal document carrying the surviving report, and the decision log entry for the day.

### Evidence

- `docs/proposals/PROP-11-the-task-death-tripwire-reads-a-status-code-as-a-death-and-t.md`
- `docs/decisions.md`

## Proposed change

Three fixes in `improve.implement`, two of them for the same fault because one of them is only true while nobody edits it.

1. The three `uv run` gates pass `--no-sync`. They exist to verify a checkout, not to provision one; resynchronising the environment underneath them is a side effect nobody asked for, and the specific side effect here is replacing the binary that is executing the gates.

2. `implement` refuses to start when its own argv[0] resolves to the `quantlab` console script, raising before the branch is created and long before any gate is invoked. The refusal names `python -m quantlab.cli implement N` as the way to run it. This is deliberate belt and braces: fix 1 holds only until someone re-adds a sync for a good reason, and this one holds regardless, because it removes the collision rather than the symptom. The program name is matched by splitting argv[0] on BOTH separators and stripping a `.exe`/`.cmd`/`.bat` suffix, which is the same normalisation the remote-call guard uses and for the same reason: a comparison whose verdict depends on which operating system evaluates it is not a comparison. `propose`'s closing hint stops advertising an invocation that would now be refused.

3. The implementation report's diff stat covers the whole series -- from the point the branch left the trunk to the index about to be committed -- instead of the staged diff of the current invocation. The base is read with `git merge-base`, which computes a commit id and joins nothing; the source-level test that forbids an automated merge path is untouched and still passes. When no base can be found the report falls back to the staged diff and says which of the two it is showing, because a stat that does not say what it covers is how this defect started.

What does NOT change: the firewall re-check and the frontend/verify-dist selection still read the staged diff of this invocation, since those govern what THIS run applies. Nothing else about the gates, the branch guard, the push guard or the human merge gate is touched.

## Affected files

- `src/quantlab/improve/implement.py`
- `src/quantlab/cli.py`
- `tests/test_improve_pipeline.py`
- `docs/decisions.md`

## Risk class

**infrastructure**

## Test plan

One fixture per fix, each asserting the observable rather than the intent. First: the gate command lines are collected from a run driven by a recording double, and every `uv run` gate must carry `--no-sync`; the double executes nothing, so the assertion is about the argv that would have been issued. Second: a synthetic argv[0] ending in `quantlab.exe` -- and its bare and `.cmd` spellings, and a Windows-style path evaluated on the Linux runner -- must raise, with a recording double observing ZERO git invocations, so the proof is that the guard ran before anything else did rather than that something later rejected it; a plain interpreter argv[0] must not raise. Third: a real two-commit branch in a temporary repository, where the first commit carries a file the second does not touch, must report a diff stat naming BOTH files, which the staged-only stat cannot do.

Regression cover: the existing structural test that reads this module's source and refuses any merge verb must still pass with `git merge-base` present, and the existing behavioural test that `main` is byte-identical after a run is unchanged. Full pytest, ruff and mypy locally, and CI green before human review.

## Firewall

```
FIREWALL PASS — no forbidden path or change class touched.
```

## Merge gate

`implement` stops after pushing the branch. **Merge is human-only:** Daniel merges via pull request after Quant Lead review. No automated path to `main` exists in this pipeline.

---

<!-- IMPLEMENTATION REPORT ANCHOR -->

## Implementation report

_implemented 2026-08-31T23:13:26.884223Z  |  branch `prop/12`  |  status: **GATES PASSED**_

### Diff stat

_`main..prop/12` — the whole series, not only this run's commit._

```
docs/decisions.md                 |  62 +++++++++++++++++
 src/quantlab/cli.py               |  14 +++-
 src/quantlab/improve/implement.py | 119 +++++++++++++++++++++++++++++++--
 tests/test_improve_pipeline.py    | 135 ++++++++++++++++++++++++++++++++++++++
 4 files changed, 322 insertions(+), 8 deletions(-)
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
| `pytest` | PASS | 837 passed, 1 warning in 157.39s (0:02:37) |
| `frontend` | SKIP | no frontend/ path in the diff |
| `verify-dist` | SKIP | site not touched |

### Branch

- branch: `prop/12`
- commit and push: performed immediately after this report was written into the proposal, since the report is part of what gets committed. The resulting SHA and push result are in the run output, and the commit itself is the one carrying this file.

### Merge gate — STOPPED HERE

This pipeline does not merge. The change sits on `prop/12` and `main` is untouched. **Daniel merges via pull request after Quant Lead review.** There is no automated path to `main` in `quantlab implement` — verified by test, not by convention.
