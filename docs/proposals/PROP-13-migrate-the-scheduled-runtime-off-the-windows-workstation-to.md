# PROP-13 — Migrate the scheduled runtime off the Windows workstation to an always-on VPS

_proposed 2026-09-07  |  risk class: **infrastructure**  |  status: **AWAITING QUANT LEAD RULING — not written by `quantlab propose`**_

> **This proposal is hand-authored, and that is not an irregularity — it is the pipeline
> working.** `quantlab propose` was invoked with these affected paths and **REFUSED
> (exit 3)**:
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
> The refusal is correct. This change relocates the entire scheduling layer, and
> `scheduling/tasks.py` is frozen precisely because a changed mark interval silently
> redefines every divergence figure computed against it. The refusal text names the
> remedy itself: *"If the change is genuinely warranted, it is a HUMAN decision: take it
> to the Quant Lead, and if it is approved it is recorded as a dated ruling in
> `docs/decisions.md` and applied by hand."*
>
> This is the second time the firewall has blocked a warranted change; the first was
> PROP-5 (broker path, 2026-08-30 ruling), and this document follows that precedent
> exactly. **Nothing here has been implemented.**

## Observation

The Friday **2026-09-04 17:30** Glass Box refresh fired, wrote its snapshot and its
sanitization report, and was then killed before the deploy step. Windows recorded
`0xC000013A` (`STATUS_CONTROL_C_EXIT`). **It dispatched no alert of any kind** — neither
the success INFO nor the abort WARNING the chain emits on either outcome, so the absence
of both is the signature. The published site stayed on its 2026-08-30 bytes and went
**eight days stale**. Nothing reported it; it was found by hand on 2026-09-07.

The host was in **Modern Standby** for the whole window: Kernel-Power 506 (enter) at
2026-09-04 15:04:23, no matching 507 (exit) until 2026-09-05 19:21:36. Both Friday jobs
fired inside that period. The 17:00 weekly is short (~90s) and completed. The refresh is
long — `npm run build:public`, then `verify-dist`, then `netlify deploy`; the successful
2026-08-30 run took 101 seconds with the host awake — and was terminated part-way.

This is the **second silent outage of the refresh specifically** (2026-08-28,
`0x8007042B` `ERROR_PROCESS_ABORTED`, same step boundary, site stale eight days) and at
least the fourth of the class overall (2026-08-01 host off; 2026-08-17 runtime orphaned).

The **2026-08-30 early-move trigger** governs, and it was written to remove exactly this
deliberation:

> **RULING — the early-move trigger.** … **A second silent outage before day-90 ends the
> deferral immediately: migrate to an always-on host at that point rather than carrying
> the exposure to the review.** No further deliberation is required and none should be
> sought — the argument has been had here, and the trigger exists so that the decision
> does not have to be re-litigated at the worst possible moment.

The trigger's own definition of *silent* — "the scheduled tasks stop producing artifacts
and no local alert reaches Daniel, regardless of the cause, and specifically regardless of
whether the cause is one already seen" — is satisfied without argument. **The trigger has
fired. This proposal is the execution of a decision already taken, not a request to take
one.** What remains for the Quant Lead is the *shape* of the move, not whether to move.

Two further facts sharpen the case beyond publishing:

* **Missed and late marks.** Across 2026-08-31 → 2026-09-06 every one of the 24 due paper
  runs completed, but **four of seven crypto marks were struck 4–7 hours late**, each one
  gated on a Kernel-Power 507 wake (e.g. wake 2026-09-03 03:08:31 → run 03:11:41, due
  2026-09-02 20:30). That is the "variable mark-window LENGTH" mechanism the weekly's own
  crypto note describes, running continuously.
* **Unarmed risk limits.** Per the 2026-08-17 entry, the risk engine "provides no
  protection during the intervals when the loop is not running", and those are exactly the
  intervals nobody is watching. An always-on host does not make the limits better — it
  makes them *armed*.

### Evidence

- `reports/alerts/alerts.jsonl` (no `glassbox.refresh` record on 2026-09-04)
- `reports/weekly/week_20260904.json`
- `reports/digests/digest_20260904.json`
- `reports/paper/` (run report write timestamps across the window)
- `docs/decisions.md` (2026-08-10, amended 2026-08-22; 2026-08-17; 2026-08-30)
- Windows Task Scheduler: `quantlab-glassbox-refresh` last run 2026-09-04 17:30:00, result `0xC000013A`
- Windows System log, Microsoft-Windows-Kernel-Power events 506/507

---

## 1. Target host

**Recommendation: Hetzner Cloud CX22 — 2 vCPU, 4 GB RAM, 40 GB NVMe — in `us-east`
(Ashburn, VA), running Ubuntu 24.04 LTS.** Roughly €4.5–5.5/month depending on VAT,
inside the ~$5–7 budget. *Prices move; verify at provision time rather than trusting this
line.*

**Why 4 GB and not 1 GB.** This is the one spec decision that is not cosmetic. Two
workloads on this host are memory-hungry and both are on the critical path:

* `npm run build:public` — a Vite production build. Node build steps are the classic OOM
  victim on 1 GB instances, and an OOM here reproduces *the exact failure this migration
  exists to eliminate*: a refresh that dies mid-chain after writing its snapshot.
* `uv run pytest -q` — 824 tests importing pandas, pyarrow and duckdb.

A $6/month 1 GB droplet (DigitalOcean Basic, Vultr, Akamai Nanode) would need swap to
survive the Vite build, and a swapping build is a slow build that a systemd
`TimeoutStartSec=` would then have to be widened for. Paying the same money for 4 GB
removes the whole class.

**Alternatives considered.** DigitalOcean Basic 2 GB (~$12/mo) — over budget, and the 1 GB
tier at ~$6 is the memory trap above. Vultr / Akamai at ~$5–6 for 1 GB — same trap.
Hetzner is recommended on RAM-per-dollar alone; if the Quant Lead prefers a US-headquartered
provider for the account relationship, DigitalOcean 2 GB at ~$12/mo is the fallback and the
budget line should move rather than the RAM.

**Region: US East.** Nearest to Alpaca, Tiingo and Coinbase endpoints, and it keeps the
host's wall clock in the same zone as the schedule (below).

**Host timezone: `America/New_York`, deliberately — not UTC.** The firing instants in
`scheduling/tasks.py` are expressed as local wall-clock times (`_RUN_TIME`, `_DIGEST_TIME`,
`_WEEKLY_TIME`, `_GLASSBOX_REFRESH_TIME`) and re-expressed as EDT-era UTC minutes in
`SCHEDULE`. Setting the VPS to `America/New_York` reproduces today's firing instants
*exactly*, including the DST behaviour the code already documents as a known limitation.
Setting it to UTC would shift every firing by 4–5 hours, which **is a cadence change** —
forbidden by the firewall, and forbidden in substance by the 2026-08-22 amendment's
insistence that a migration changes "the host, not the record". The DST wart is inherited
unchanged and stays a separate decision.

---

## 2. The scheduler layer: systemd timers, not cron

**Recommendation: systemd timers.** Four reasons, in descending order of weight. The first
is close to decisive on its own.

**(a) `Persistent=true` is the only faithful replacement for `StartWhenAvailable`.** The
existing schedule depends on catch-up: a `PowerShell` post-step sets
`StartWhenAvailable = $true` on all five tasks, and the record is full of catch-up runs
that exist because of it. A systemd timer with `Persistent=true` stores the last trigger
and fires immediately on boot if the window was missed — the same semantics. **cron has no
equivalent at all.** `anacron` exists but only at daily/weekly/monthly granularity and is
not usable for a 00:30 crypto firing. Choosing cron would mean *silently deleting* a
behaviour the record depends on, which is the same class of change as a cadence edit.

**(b) systemd records a structured, queryable ending; cron records nothing.** This is what
PROP-8's death tripwire reads, and it is why cron is not merely worse but unusable.
`systemctl show quantlab-digest.service` yields `Result=`, `ExecMainStatus=`,
`ExecMainCode=`, `ExecMainExitTimestamp=`, `ActiveState=`, `SubState=` — machine-readable,
per-unit, and durable across the run. cron gives you an exit status delivered by local
mail, with no queryable history, so the tripwire would have to be deleted rather than
ported.

**(c) `Result=` is strictly better evidence than `Last Result` ever was.** The whole of
PROP-11 exists because Windows' `Last Result` is two fields wearing one name — sometimes an
exit code, sometimes a `SCHED_S_*` *state* code — and the tripwire read a state as a death.
systemd separates them structurally: `ActiveState`/`SubState` answer "what is it doing",
`Result`/`ExecMainStatus` answer "how did it end". More: `Result` *names the cause* —
`exit-code`, `signal`, `oom-kill`, `timeout`, `core-dump`. The 2026-09-04 death would have
been reported as `Result=signal` rather than as an opaque HRESULT a human had to look up.

**(d) Units are declarative files that live in git.** Five `.service` + five `.timer` files
under `deploy/systemd/` are reviewable in a PR and reproducible on a rebuild. A crontab is
one opaque table on one host, and the current install path already had to bolt a PowerShell
post-step onto `schtasks` because the CLI could not express a setting it needed.

**Additional hardening systemd gives for free**, each aimed at a failure already on the
record: `TimeoutStartSec=` (a hung deploy is killed and *reported*, instead of running
forever), `MemoryMax=` (an OOM becomes `Result=oom-kill`, a named cause), and
`WorkingDirectory=` — which structurally removes the `C:\Windows\System32` CWD hazard
documented at `glassbox/snapshot.py:73`, where `schtasks` supplied no working directory and
a relative `Path("reports")` resolved into System32.

**Sketch (illustrative — not to be installed from this document):**

```ini
# quantlab-crypto-paper-run.timer
[Timer]
OnCalendar=*-*-* 20:30:00 America/New_York
Persistent=true
Unit=quantlab-crypto-paper-run.service

# quantlab-crypto-paper-run.service
[Service]
Type=oneshot
User=quantlab
WorkingDirectory=/opt/quantlab
EnvironmentFile=/opt/quantlab/.env
ExecStart=/opt/quantlab/.venv/bin/quantlab paper run-all --asset-class crypto --submit
TimeoutStartSec=20min
MemoryMax=2G
```

---

## 3. The PROP-8 death tripwire on Linux

**This is the highest-risk item in the migration, and it is a silent one.**
`watchdog.py:262` is:

```python
return platform.system() == "Windows"
```

Move to Linux with nothing else changed and `schtasks_available()` returns `False`,
`task_results_available` goes `False`, and the tripwire **switches itself off** — rendering
"task-death tripwire: **unavailable on this host**" once a day, forever, while reporting no
deaths. The report line is honest, which is the only reason this is recoverable; but the
migration would otherwise trade a silent-outage failure mode for a silent-*monitoring*
one. **The Linux reader must land in the same change as the cutover, not after it.**

The port is mechanical, because PROP-8/11 already put the right seams in:
`check_schedule` takes `task_reader` and `task_results_available` injectables, and
`audit_task_deaths` consumes a plain `list[TaskResult]`. Only the reader and the
classifier change.

| Windows today | Linux equivalent |
|---|---|
| `schtasks_available()` → `platform.system() == "Windows"` | probe for a usable `systemctl` (units present on the system bus) |
| `schtasks /query /fo LIST /v` | `systemctl show 'quantlab-*.service' --property=Id,Result,ExecMainStatus,ExecMainCode,ExecMainExitTimestamp,ActiveState,SubState` |
| `parse_schtasks_list` | `parse_systemctl_show` — blank-line-separated blocks, one per unit; the existing `_field` helper generalises |
| `Last Result` (HRESULT) | `Result` + `ExecMainStatus` (two fields, correctly separated) |
| `SCHED_S_*` status family (PROP-11 exclusion) | not needed — state lives in `ActiveState`/`SubState`, never in `Result` |
| `SCHED_S_TASK_RUNNING` self-exclusion | `SubState=running` (see PROP-14, which needs the same signal) |
| `_SCHTASKS_STAMP_FORMATS` (US local, AM/PM) | `ExecMainExitTimestamp`, which systemd renders with an explicit zone |
| `_local_naive()` | keeps working; prefer the zoned stamp and stop discarding the offset |

Classification maps cleanly, and improves:

* `Result=success` → not a death.
* `Result=exit-code`, `ExecMainStatus != 0`, **with** an in-code failure record → explained,
  no second alert. The PROP-8 distinction is unchanged.
* `Result=exit-code`, non-zero, **without** one → a death. Same as today.
* `Result=signal` / `oom-kill` / `timeout` / `core-dump` → a death **with a named cause**.
  This is the class that produced `0xC000013A`, and on Linux it arrives self-describing.

**Two ledger consequences that must not be skipped:**

1. `BATTERY_HARDENING_APPLIED_AT = datetime(2026, 8, 30)` is a Windows-laptop concept and
   becomes meaningless on the new host. It must **not** be deleted — it still correctly
   classifies pre-migration deaths in the historical record. The recommendation is to add a
   `MIGRATED_AT` instant beside it and treat the two as bounds on which host a recorded
   death belongs to. A death from the old host must keep reading as it reads today.
2. `config/acknowledged_task_deaths.json` keys on `(task, result_code, recorded_at)`, and
   the task names change (`quantlab-digest` → `quantlab-digest.service`) as does the code
   space (HRESULT → exit status / signal). The shipped 2026-08-28 entry must be preserved
   verbatim as history. **The 2026-09-04 `0xC000013A` death must be entered too — but only
   after this ruling is recorded, per item 7 of the session brief, because the acknowledgement
   text has to cite the ruling that closed it.**

---

## 4. Secrets

**`.env` — 15 keys, 1096 bytes, already gitignored, and it must stay that way.**

The constraint that decides the layout: `config.py:258` sets
`_DOTENV_PATH = PROJECT_ROOT / ".env"`, and `verify_dist.py:47` independently sets
`DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"`. **So `.env` must live at the repo root on the
VPS** — `/opt/quantlab/.env` — or both constants have to change. Recommend keeping it at
the repo root and pointing systemd's `EnvironmentFile=` at that same file, so the env-secret
gate keeps working with **zero code changes**. Ownership `quantlab:quantlab`, mode `0600`.

**Transfer.** `scp` over SSH directly from the workstation to `/opt/quantlab/.env`. It never
touches git, a paste buffer, or a third-party service. Verify afterwards with a byte count
and a key-name diff — never by printing values.

**Netlify is the one genuinely new credential, and it is easy to miss.** There is **no
Netlify token in `.env` today**. `build_deploy_command()` runs `npx netlify deploy --prod`,
which authenticates from a *machine-local CLI login* stored in
`%APPDATA%\netlify\Config` on the workstation. That file is not a secret the migration can
copy — it must be replaced by a **`NETLIFY_AUTH_TOKEN`** (a Netlify user personal access
token) added to `.env` on the VPS, which is what `netlify deploy` reads in a headless
environment. Without it the refresh chain fails at the deploy step on the very first Friday.

**Verified: the sanitizer does not need to change, and therefore no second firewall
refusal is incurred.** Two things were checked rather than assumed:

* `is_secret_bearing()` (`sanitize.py:268`) excludes only `_ENV_NON_SECRET_KEYS`
  (`ALPACA_BASE_URL`, `SMTP_HOST`, `SMTP_PORT`), public URLs, email values, and values
  shorter than 6 characters. `NETLIFY_AUTH_TOKEN` is none of those, so it is picked up as
  secret-bearing **automatically** and its prefix is searched for in every published byte.
  No edit to the frozen `sanitize.py` is required.
* `REDACTION_PATTERNS` already contains `posix_home_path`
  (`/(?:home|Users)/[^/"\s,;:*?<>|]+`, `sanitize.py:63`) alongside `windows_user_path`. A
  snapshot generated on Linux has its host paths redacted today. The module's own comment
  anticipated this: *"a gate that only guards the current developer's OS is a gate with a
  hole in it."*

**SMTP.** Gmail app password, unchanged. Confirm outbound **587** is open — many providers
block 25 but not 587 — and send one real alert as an explicit burn-in item, because a
migrated alert path that silently stops delivering would recreate the exact condition this
migration exists to end.

**Host access.** SSH keys only (`PasswordAuthentication no`, `PermitRootLogin no`), `ufw`
default-deny inbound with 22/tcp only, unattended-upgrades on, `fail2ban`. The Glass Box API
binds `127.0.0.1` by design (`glassbox/serve.py`) and **must not** be exposed; the public
site is Netlify-hosted and is not served from this box.

---

## 5. Cutover: staged parallel run, then a hard switch

**Recommendation: run the two hosts in parallel but with only ONE of them submitting, then
hard-switch on a Saturday.** A true parallel run is not available here and the reason is
worth stating plainly.

> **The binding constraint: exactly one host may submit orders, and exactly one host may
> write `data/` and `reports/`, at any instant.** Both hosts submitting would double-trade
> the same four Alpaca paper accounts and corrupt the 90-day record the migration is
> supposed to carry across intact. Both hosts writing the reports tree would fork the
> record itself.
>
> There is a partial safety net — `client_order_id` is deterministic per day
> (`ql-{label}-{YYYYMMDD}-{symbol}-{side}`) and Alpaca rejects a duplicate, which is what
> `was_duplicate` in the run report records. **It must not be relied on as the plan.** It
> is a backstop for an operator error, not a design.

**Phase 0 — provision and prove (no schedule armed).**
Provision; `apt` baseline and hardening; create the `quantlab` service user; install `uv`
and Node; `git clone`; `uv sync`; `scp` the `.env`; mint and add `NETLIFY_AUTH_TOKEN`; set
the host timezone to `America/New_York`. Then, by hand: `uv run pytest -q` (expect 824
passed), `quantlab health`, `quantlab paper status` (read-only — must show the same four
accounts and equities as the workstation), and `quantlab glassbox refresh --dry-run`
(exercises snapshot → build → verify-dist with the deploy withheld). **No timer is enabled
in this phase.**

**Phase 1 — timers armed, nothing submitted (2–3 days).**
Enable the timers with the paper-run units running **without `--submit`**, and the digest,
weekly and refresh units masked. The workstation continues to be the only submitting host
and the only writer of record. What this proves is precisely what the 2026-08-22 amendment
says needs proving — "that its schedule fires, its alerts deliver and its runtime survives
a reboot" — without touching the trading path. Include one **deliberate reboot** and
confirm `Persistent=true` catch-up fires.

**Phase 2 — cutover (a Saturday).**
Saturday is chosen because it is crypto-only: no equity firing is due, and the switch gets a
full weekend of margin before Monday's open.

1. Let the workstation's Saturday 20:30 crypto run complete and verify its report.
2. `schtasks /Change /TN <name> /DISABLE` on all five Windows tasks — **disable, never
   delete.** The disabled tasks *are* the rollback.
3. `rsync` `data/` and `reports/` workstation → VPS. From this moment the VPS is the sole
   authoritative writer; the workstation copy is frozen as the rollback snapshot.
4. Unmask and enable the full VPS schedule, paper-run units now **with `--submit`**.
5. Watch the Sunday 20:30 crypto firing land, then Monday's 10:00 equity firing, by hand.

**Phase 3 — the 14-day burn-in** (below), per the 2026-08-22 amendment.

**Why not a hard switch with no parallel phase.** It would put the first proof that timers
fire at all on a day when the workstation is already disabled, with money armed.
**Why not a longer parallel run.** With only one host permitted to submit, extra parallel
days buy nothing except schedule-firing evidence, which 2–3 days and one reboot already
supply.

---

## 6. Rollback

Rollback is cheap by construction, and the design choices above exist to keep it cheap.

| Trigger | Action | Cost |
|---|---|---|
| Phase 0/1 failure | Nothing to undo — the workstation never stopped. Destroy the VPS. | zero |
| Phase 2, same day | Re-enable the five Windows tasks (`schtasks /Change /ENABLE`); mask the VPS timers. | minutes |
| During the 14-day burn-in | Mask VPS timers; `rsync` `data/` + `reports/` VPS → workstation; re-enable the Windows tasks. | one run interval |

Preconditions, each of which is a decision made above rather than an afterthought: the
Windows tasks are **disabled, not deleted**; `.env` **stays on the workstation**; the repo
is unchanged on both hosts; and the reports/data snapshot taken at Phase 2 step 3 is
retained untouched for the full burn-in.

**Rollback is bounded, not open-ended.** A rollback ends the burn-in and restarts it —
`review date = max(day-90, migration + 14)` re-anchors to the *successful* migration. It does
not reset the readiness clocks; per the 2026-08-22 amendment those "continue uninterrupted
across a migration", and that applies to a reverted one too.

---

## 7. The 14-day burn-in checklist

Mandated by the 2026-08-22 amendment: **`review date = max(day-90, migration + 14)`.**
Fourteen days covers two full weekly cycles, so both Friday jobs and both weekend boundaries
are exercised twice. Current clocks: us_equity **60/90** (day-90 ≈ 2026-10-07), crypto
**47/90** (day-90 ≈ 2026-10-20). A migration in mid-September puts `migration + 14` well
inside day-90 for both, so **the burn-in costs nothing** — which is the point of the trigger
being cheap enough to pull.

*Daily*

- [ ] Every due crypto firing (00:30Z) left a run report. **Target: 14/14, zero catch-ups.**
- [ ] Mark interval between consecutive crypto runs is **24.00h ± 2 min**. This is the
      headline number: the Windows record for 2026-08-31 → 2026-09-06 has four of seven
      marks 4–7 hours late. A clean interval here is the migration's primary measurable win.
- [ ] Every due equity firing (14:00Z, NYSE sessions only) left two run reports.
- [ ] The digest ran and wrote `reports/digests/digest_YYYYMMDD.json`.
- [ ] `MISSED RUNS: none`, and the task-death section reads as **available** — not
      "unavailable on this host" (§3).
- [ ] No CRITICAL other than the deliberately injected one below.

*Weekly (×2)*

- [ ] Friday 17:00 weekly wrote `week_YYYYMMDD.{md,json}`; all four accounts carry a verdict.
- [ ] Friday 17:30 refresh **deployed AND recorded** — a `glassbox.refresh` INFO alert *and*
      a PROP-9 snapshot PR. Both halves: the 2026-09-04 failure produced neither.
- [ ] One end-to-end **SMTP alert actually delivered** to the inbox.
- [ ] CI green on `main`.

*Once, deliberately injected — a burn-in that only observes proves only that nothing went
wrong, not that failures are still caught*

- [ ] **Reboot** mid-week: timers re-arm, `Persistent=true` catch-up fires, nothing missed.
- [ ] **`systemctl kill`** a long-running unit mid-flight: the Linux death tripwire reports
      it as `Result=signal`, at CRITICAL, in the next digest. This is the direct analogue of
      the 2026-09-04 death, and it is the single most important item in this checklist —
      it proves the monitoring survived the move.
- [ ] Confirm `.env` is `0600`, owned by the service user, and absent from `git status`.

*Exit criteria — all four, or the burn-in extends rather than the review advancing*

1. 14 consecutive days, ≥2 full Friday cycles.
2. Zero missed firings and zero silent failures.
3. Both injected failures detected and reported.
4. Every crypto mark interval inside 24.00h ± 2 min.

---

## 8. Windows-only assumptions that must change — found by grep, not memory

Every entry carries the command that found it. **CI already runs `ubuntu-latest`
(`.github/workflows/ci.yml:10`) and all 824 tests pass there**, so the library core is
already Linux-verified. Everything below is in the *operational* layer, which CI does not
exercise.

**Blocking — the migration is incorrect without these**

| # | Location | What breaks |
|---|---|---|
| 1 | `src/quantlab/scheduling/tasks.py` (whole module) | `schtasks /Create /Delete /Query` builders (149–216), the PowerShell `StartWhenAvailable` post-step (219–235), `resolve_quantlab_exe()` → `quantlab.exe` (132). **FIREWALL-FORBIDDEN.** |
| 2 | `src/quantlab/reporting/watchdog.py:262` | `platform.system() == "Windows"` — **the death tripwire silently disables itself on Linux** (§3). |
| 3 | `src/quantlab/reporting/watchdog.py:286–329` | `parse_schtasks_list`, `_default_task_reader` shelling to `schtasks /query /fo LIST /v`. |
| 4 | Netlify auth | Machine-local CLI login in `%APPDATA%\netlify\Config`; **no token in `.env`**. Needs `NETLIFY_AUTH_TOKEN` (§4). |

**Needs a decision, but not a blocker**

| # | Location | Note |
|---|---|---|
| 5 | `watchdog.py:96–106` | `SCHED_S_STATUS_CODES` — no Linux analogue needed; state moves to `ActiveState`/`SubState`. Keep for historical rows. |
| 6 | `watchdog.py:145` | `BATTERY_HARDENING_APPLIED_AT` — a laptop concept. Keep as a historical bound; add `MIGRATED_AT`. |
| 7 | `watchdog.py:152–156` | `_SCHTASKS_STAMP_FORMATS` — US local, AM/PM, no zone. systemd stamps carry a zone. |
| 8 | `watchdog.py:595–597` | `_local_naive()` — deliberately discards the offset to match schtasks' frame. Revisit once stamps are zoned. |
| 9 | `config/acknowledged_task_deaths.json` | Keyed on Windows task names + HRESULT. Preserve as history (§3). |
| 10 | `src/quantlab/config.py:258`, `glassbox/verify_dist.py:47` | `.env` pinned to `PROJECT_ROOT`. **Constrains where the env file may live** (§4). |
| 11 | `src/quantlab/glassbox/constants.py:104–112` | EDT-era UTC offsets. Inherited unchanged by keeping the host on `America/New_York`. |
| 12 | `src/quantlab/config.py:102` | `timezone: str = "America/New_York"` — consistent with the host setting. |

**Improves or becomes moot on Linux — verified, no action**

| # | Location | Note |
|---|---|---|
| 13 | `glassbox/sanitize.py:56–67` | `windows_user_path` **and** `posix_home_path` both present. Linux paths already redacted. **No change to the frozen sanitizer.** |
| 14 | `glassbox/snapshot.py:73–81` | The `C:\Windows\System32` CWD hazard; systemd's `WorkingDirectory=` removes the class. Keep the `PROJECT_ROOT` anchoring regardless. |
| 15 | `improve/implement.py:64`, `89–110` | `_PROGRAM_SUFFIXES`; `assert_not_console_script` exists because Windows cannot replace a running `quantlab.exe`. POSIX can unlink a running file, so the guard stops being load-bearing — **do not remove it**, it is tested and still correct. |
| 16 | `glassbox/refresh.py:286–300` | `shutil.which` resolution for `.cmd` shims. Harmless on Linux; the comment narrows. |
| 17 | `logging_setup.py:75–78` | `RotatingFileHandler`, 5 MB × 5. Cross-process rotation is unsafe on both platforms but materially less bad without Windows file locking. Note only. |
| 18 | `tests/test_improve_pipeline.py:594` | `_WINDOWS_CONSOLE_ARGV` — a cross-platform regression fixture that already passes on ubuntu CI. Keep. |

Commands used:

```
grep -rn "schtasks" src/ --include=*.py
grep -rn "platform\.system\|sys\.platform\|os\.name" src/ --include=*.py
grep -rn "\.exe\|\.cmd\|\.bat\b" src/ --include=*.py
grep -rn "powershell\|StartWhenAvailable\|Set-Scheduled" src/ --include=*.py
grep -rn "Eastern\|America/New_York\|\bEDT\b\|\bEST\b\|ZoneInfo\|astimezone" src/ --include=*.py
grep -rn "\.env\b\|DOTENV" src/quantlab/config.py src/quantlab/glassbox/*.py
grep -rn "windows_user_path\|posix_home_path" src/ tests/
```

---

## Affected files

- `src/quantlab/scheduling/tasks.py` — **FIREWALL-FORBIDDEN; human edit only**
- `src/quantlab/scheduling/systemd.py` *(new)*
- `src/quantlab/reporting/watchdog.py`
- `src/quantlab/cli.py`
- `config/acknowledged_task_deaths.json`
- `deploy/systemd/*.service`, `deploy/systemd/*.timer` *(new)*
- `tests/test_watchdog.py`, `tests/test_scheduling.py`
- `docs/decisions.md` — the ruling this proposal asks for

## Risk class

**infrastructure**

## Test plan

Full `ruff` / `mypy` / `pytest` on the target host before any timer is enabled (Phase 0),
and CI green on `ubuntu-latest` for the code changes — which is the same platform the VPS
runs, so CI stops being a proxy and becomes a direct test.

The systemd reader is unit-tested exactly as the schtasks reader is: recorded
`systemctl show` output as fixtures, one per outcome — `success`, `exit-code` non-zero with
and without an in-code failure record, `signal`, `oom-kill`, `timeout` — asserting the same
explained/unexplained distinction PROP-8 established and the same
`state-is-not-an-ending` exclusion PROP-11 established. A regression fixture asserts that
historical Windows rows in `acknowledged_task_deaths.json` still classify exactly as they do
today.

Beyond the suite, the **14-day burn-in in §7 is the test plan**, and its injected-failure
items are the part that matters: they verify the monitoring survived the move, which is the
one thing a passing suite on a quiet host cannot show.

## Firewall

```
FIREWALL REFUSAL — this proposal will not be written.

  FORBIDDEN PATH   src/quantlab/scheduling/tasks.py
                   schedule cadences, which define what the paper mark interval means
```

Refused by `quantlab propose` (exit 3) on 2026-09-07. The refusal is **correct** and is not
being routed around: this document was written by hand, changes no code, and asks for a
dated human ruling. Precedent: PROP-5, refused on `broker/alpaca_trading.py` and resolved by
the Quant Lead ruling of 2026-08-30.

Note for the ruling: the firewall's concern is a **cadence** change, and this proposal
explicitly makes none. Keeping the host on `America/New_York` (§1) is chosen precisely so
every firing instant is preserved bit-for-bit; what moves is the machine, not the schedule.

## Merge gate

No branch, no commit of code, no PR. **This document is a request for a dated ruling in
`docs/decisions.md`.** Nothing in §1–§7 may be provisioned before that ruling exists.
