# PROP-15 — `quantlab-digest` is absent from `SCHEDULE`, so a missed digest can never be reported

_proposed 2026-09-07  |  risk class: **infrastructure**  |  status: **AWAITING QUANT LEAD RULING — refused by `quantlab propose`**_

> **Hand-authored because the pipeline refused it, and the refusal is correct.**
> `quantlab propose` was invoked with the affected paths below and returned **exit 3**:
>
> ```
> ========================================================================
> FIREWALL REFUSAL — this proposal will not be written.
> ========================================================================
>
>   FORBIDDEN PATH   src/quantlab/scheduling/tasks.py
>                    schedule cadences, which define what the paper mark interval means
> ```
>
> **Nothing has been implemented.** There is a variant of this change that the firewall
> *would* allow (§4), and it was deliberately not taken — see §5. Precedent: PROP-5
> (2026-08-30 ruling) and PROP-13.

## Observation

**There is no `reports/digests/digest_20260903.json`.** The 2026-09-03 digest never ran.
The host was in Modern Standby across its 16:45 ET firing, and Windows released it as a
catch-up at 01:35 the following morning — where it collided with the crypto paper run and
produced the false WARNING that PROP-14 addresses. Its output was then overwritten by the
regular 2026-09-04 digest at 16:45, which is why no trace of it survives on disk.

**Nothing reported the absence. Nothing ever could.**

`scheduling.tasks.SCHEDULE` carries exactly four entries:

```python
SCHEDULE: tuple[ScheduledTask, ...] = (
    ScheduledTask(TASK_PAPER_RUN,        14 * 60,      DAYS_WEEKDAYS, PRODUCES_RUN_REPORT, ...),
    ScheduledTask(TASK_CRYPTO_PAPER_RUN, 30,           DAYS_DAILY,    PRODUCES_RUN_REPORT, ...),
    ScheduledTask(TASK_WEEKLY,           21 * 60,      DAYS_FRIDAY,   PRODUCES_WEEKLY_REVIEW),
    ScheduledTask(TASK_GLASSBOX_REFRESH, 21 * 60 + 30, DAYS_FRIDAY,   PRODUCES_REFRESH_ALERT),
)
```

`TASK_DIGEST` is not among them — **although `build_install_commands` installs it beside
the other four**, and `_FAILURE_SOURCES_BY_TASK` in the watchdog already names it, and
`SELF_TASK = "quantlab-digest"` already exists there too. The digest is present everywhere
in this subsystem *except* in the list of things whose absence is checked. The watchdog
therefore holds no expectation for it, `firings_checked` never counts it, and a digest that
does not run is indistinguishable from a day on which none was due.

The scale of the blind spot is worth stating precisely: **the digest fires on every weekday,
which is more often than any other task except the crypto run**, and it is the task that
carries the watchdog itself. Every other silence in this system is now audible. This one is
not, and it is the silence that mutes all the others — a digest that does not run does not
merely fail to report itself, it fails to report the *other four* tasks for that day as well.

This is the PROP-6 lesson one layer up. That proposal established that *"skipping a firing
today is only honest if something checks it later"*, and rebuilt the window so a deferred
check is a postponed one rather than a cancelled one. For `quantlab-digest` there is no
later check to postpone to, because no check exists at all. **The watchdog watches four
tasks; the fifth is the one doing the watching.**

A note on why this is not self-referential nonsense: a digest genuinely cannot observe its
own absence, and nothing here asks it to. A *later* digest observes it, exactly as a later
digest observes a missed crypto run. The machinery for that already exists and is already
correct — `previous_digest_date` and `previous_digest_instant` are how the window anchors,
and `_is_own_in_flight_result` already prevents the digest from indicting itself. The only
missing piece is the expectation.

### Evidence

- `reports/digests/` — 2026-08-31, 09-01, 09-02 and 09-04 present; **09-03 absent**
- `reports/alerts/alerts.jsonl` — five records between 08-31 and 09-06; none names a missed digest
- `reports/digests/digest_20260904.json` — `"firings_checked": 8`, over a two-day window in which the digest itself fired twice and was counted zero times
- `docs/decisions.md` — 2026-08-10 (the watchdog's purpose), PROP-6

## Proposed change (the design this proposal asks to be approved)

1. A `PRODUCES_DIGEST` artifact class, and a fifth `SCHEDULE` entry:
   `ScheduledTask(TASK_DIGEST, 20 * 60 + 45, DAYS_WEEKDAYS, PRODUCES_DIGEST)`. The instant
   is **read off the existing `_DIGEST_TIME` constant in the same file** — 16:45 ET, which
   is 20:45 UTC on the EDT-era offsets every other entry already uses. **No cadence is
   introduced, chosen, or altered.** The firing time is not new information; it is
   re-expressed in the second of the two forms that file already maintains, which is what
   every other task in `SCHEDULE` does.
2. A `_digest_days(digests_dir)` reader in `reporting.watchdog`, alongside the existing
   `_run_report_days`, `_weekly_review_days` and `_refresh_alert_days`, returning the days
   for which `digest_YYYYMMDD.json` exists — the same glob `previous_digest_date` already
   performs.
3. One branch in `check_schedule`'s classification loop for `PRODUCES_DIGEST`, identical in
   shape to the three beside it.

Nothing else changes. No new alert kind, no new severity, no change to the single-WARNING
rule: a missed digest joins the existing WARNING alongside any other miss in the window,
which is what that rule was written for.

## Affected files

- `src/quantlab/scheduling/tasks.py` — **FIREWALL-FORBIDDEN; human edit only**
- `src/quantlab/reporting/watchdog.py`
- `tests/test_watchdog.py`

## Risk class

**infrastructure**

## Test plan

The 2026-09-03 gap, replayed: digests present for 09-02 and 09-04 and absent for 09-03,
checked from 09-04, must name `quantlab-digest` for 09-03 exactly once and dispatch exactly
one WARNING. The same window with 09-03 present must stay silent.

Three exclusions get their own fixtures, because each is a way this check could become the
daily false alarm PROP-11 spent a whole proposal removing: a digest running *now* must not
name its own day (it has not written its artifact yet, and `_due_at <= now` is true from
20:45 onward); a weekend and a market holiday must produce no digest expectation; and a
window with no previous digest at all must fall to the bounded lookback rather than
indicting every day in history.

Regression fixtures assert `firings_checked` rises by exactly one per weekday in the window
and that the PROP-6 deferral, the PROP-8 explained/unexplained distinction and the PROP-14
in-flight deferral are all unchanged. Full `pytest`, `ruff` and `mypy` locally, and CI green
before human review.

## Firewall

```
FIREWALL REFUSAL — this proposal will not be written.

  FORBIDDEN PATH   src/quantlab/scheduling/tasks.py
                   schedule cadences, which define what the paper mark interval means
```

Refused by `quantlab propose` (exit 3) on 2026-09-07.

### §4 — There is a variant that the firewall would allow

`_FAILURE_SOURCES_BY_TASK` in `reporting/watchdog.py` is task-keyed schedule-adjacent
knowledge that lives in the watchdog **specifically because** `tasks.py` is forbidden; its
comment says so outright: *"`scheduling.tasks` is a firewall-forbidden path and is not
touched."* PROP-8 set that precedent. The same move is available here: hold the digest's
expectation in `watchdog.py` and never touch `tasks.py`. This was checked, and it passes:

```
affected_paths = ['src/quantlab/reporting/watchdog.py', 'tests/test_watchdog.py']
FIREWALL PASS — no forbidden path or change class touched.
```

### §5 — Why that variant was not taken

Because `tasks.py` says not to, in the docstring directly above `SCHEDULE`:

> The watchdog has to know when each task was SUPPOSED to fire, and **that knowledge must
> not be duplicated**: a schedule change here has to move the expectation too, or the
> watchdog starts either crying wolf or going quiet.

The PROP-8 precedent does not extend to this. `_FAILURE_SOURCES_BY_TASK` maps a task to the
*alert sources it speaks through* — that is not cadence, and no edit to `tasks.py` can
falsify it. A firing instant **is** cadence, and a copy of it in a second file is the exact
duplication that comment forbids, with the exact failure it predicts: change `_DIGEST_TIME`
later and the watchdog's private copy silently disagrees.

More to the point: **deciding to duplicate cadence knowledge into an ungated file, on the
grounds that the correct file is gated, is the reasoning the firewall exists to stop an
automated agent making on its own.** The refusal text is explicit that the remedy is a human
ruling, not a different file. Taking the allowed variant would have satisfied the letter of
the gate while defeating it, and would have been much harder for a reviewer to notice than
this paragraph is.

So the choice is put here rather than made:

| | Option A — `SCHEDULE` entry *(recommended)* | Option B — watchdog-local expectation |
|---|---|---|
| Firewall | Refused; needs a dated ruling | Passes |
| Source of truth | Single, as designed | Duplicated across two files |
| Failure mode | none | `_DIGEST_TIME` and the expectation drift apart silently |
| Cost | one human edit + a ruling | none up front, a latent defect after |

**Recommendation: Option A.** The edit is three lines in a frozen file, it introduces no
cadence, and the ruling costs one entry in `docs/decisions.md`.

## Merge gate

No branch, no commit of code, no PR — the refusal came before anything was written.
**This document is a request for a dated ruling.** If Option A is approved, the `tasks.py`
edit is applied by hand and items 2–3 can then go through `implement` normally, since the
remaining paths are not forbidden.

### Relationship to PROP-13 and PROP-14

- **PROP-14** fixes the watchdog reporting a firing that *did* happen as missed. **PROP-15**
  fixes it never reporting one that *did not*. Opposite errors, same check; neither
  supersedes the other and they do not conflict.
- **PROP-13** (VPS migration) rewrites this same `SCHEDULE` for systemd. If both are
  approved, **this entry should land as part of that rewrite rather than twice** — one human
  edit to `tasks.py`, not two. If PROP-13 is deferred or declined, PROP-15 stands alone and
  is still worth ruling on: the blind spot is on the current host today.
