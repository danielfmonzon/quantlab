# PROP-1 — Story page undercounts the self-caught incidents: it says twice, there have been three

_proposed 2026-08-15T16:36:07.230314Z  |  risk class: **content**  |  status: **AWAITING IMPLEMENTATION**_

## Observation

The Story page section 'The mistakes are on the site too' (frontend/src/content/copy.ts) states that in its first two weeks the system flagged itself as misbehaving twice, and names two faults, both in the measurement rather than the strategy: a scheduler that ran the crypto accounts twice a day, and a price read before the day had finished settling. A third self-caught measurement fault has since been ruled and published. The 2026-08-10 comparator dating defect paired a paper interval against the wrong shadow session; the ruling voided two crypto blockers as a dating defect rather than a partial-bar artifact, and withdrew two equity blockers whose residuals after decomposition were +2.63 and +1.88 bps. The decision log therefore records three self-caught measurement incidents while the public Story page still says two. The same undercount appears a second time on the ledger highlight card, labelled 'Two self-caught incidents, both published'. A page whose argument is that published failures are what make a record evaluable is currently understating its own evidence.

### Evidence

- `docs/decisions.md`
- `reports/weekly/week_20260807.md`
- `reports/weekly/week_20260814.md`

## Proposed change

Update both places in frontend/src/content/copy.ts to say three, naming the third fault alongside the existing two and keeping the section's voice: plain, specific, no inflation. The section already argues that a track record you have never seen fail is one you cannot evaluate; a third published instance strengthens that argument and costs nothing to state. The prose stays first-person-singular per the 2026-07-26 ruling and the incident is described in the same register as the other two - what broke, in one clause, without jargon.

## Affected files

- `frontend/src/content/copy.ts`

## Risk class

**content**

## Test plan

Run the frontend vitest suite (165 tests, 6 files) and the tsc lint; both must stay green, since the Story page copy is rendered by the a11y and content tests. Assert by grep that no self-caught-incident count of two survives in copy.ts. Read the section aloud against the two neighbouring paragraphs to confirm the voice is unchanged. No Python path is touched, so the backend suites are expected to be unaffected and are run only as a regression check.

## Firewall

```
FIREWALL PASS — no forbidden path or change class touched.
```

## Merge gate

`implement` stops after pushing the branch. **Merge is human-only:** Daniel merges via pull request after Quant Lead review. No automated path to `main` exists in this pipeline.

---

<!-- IMPLEMENTATION REPORT ANCHOR -->

## Implementation report

_implemented 2026-08-15T16:42:18.470293Z  |  branch `prop/1`  |  status: **GATES PASSED**_

### Diff stat

```
frontend/src/content/copy.ts | 18 ++++++++++--------
 1 file changed, 10 insertions(+), 8 deletions(-)
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
| `pytest` | PASS | 662 passed, 1 warning in 55.79s |
| `frontend` | PASS | [2m   Duration [22m 6.55s[2m (transform 793ms, setup 3.21s, collect 4.33s, tests 7.03s, environment 8.55s, prepare 1.39s)[22m |
| `frontend-lint` | PASS | > tsc -b --noEmit |
| `verify-dist` | PASS | {"files": 178, "event": "verify_dist_passed", "logger": "quantlab.cli", "level": "info", "timestamp": "2026-08-15T16:43:31.669767Z"} |

### Branch

- branch: `prop/1`
- commit and push: performed immediately after this report was written into the proposal, since the report is part of what gets committed. The resulting SHA and push result are in the run output, and the commit itself is the one carrying this file.

### Merge gate — STOPPED HERE

This pipeline does not merge. The change sits on `prop/1` and `main` is untouched. **Daniel merges via pull request after Quant Lead review.** There is no automated path to `main` in `quantlab implement` — verified by test, not by convention.
