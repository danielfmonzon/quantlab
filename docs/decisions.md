# Decision log

Major design decisions made during the quantlab build, with rationale. Each
entry is dated to the build phase in which the decision was made; the log was
compiled on 2026-07-10 (v1.0.0). Newest entries first.

---

## 2026-08-10 — Divergence diagnosis #2, and six re-rulings

**Scope.** The two weekly reviews on file since 2026-07-31: `week_20260802` (generated
2026-08-02T22:53:50.959572Z) and `week_20260807` (generated 2026-08-07T21:00:04.381541Z).
Read-only. Unlike the 2026-07-24 study, **every published figure reproduced exactly**
through the aligned code path — all six divergences to the tenth of a basis point — so
nothing here is a non-reproducible artifact of the kind that voided the earlier headline.

**Finding 1 — `trend` is measurement geometry, provably and completely.** `trend` held a
constant **133.028241898** SPY across 2026-07-24..2026-08-10 with zero orders, zero
`est_turnover`, and cash inside ±$12 on a ~$100k book, so `(equity − cash) / qty` *is* the
SPY price at the mark instant; every implied price lands inside its session's low-high
range. For a position held without trading, paper interval `[10:00 t−1, 10:00 t]` minus
shadow session `t` telescopes to `rem[t−1] − rem[t]` where `rem[t] = close[t]/implied[t] −
1`, so a week depends **only on its two endpoint remainders** and every interior mark
cancels. Week 2026-08-07: `rem[07-31]` **+68.20** less `rem[08-06]` **−31.52** predicts
**+99.71 bps** against the published **+101.39** — residual **+1.68 bps (1.7%)**. Week
2026-08-02 predicts **+21.31** against **+21.10**, residual **−0.21 bps**. Per-day
predictions match observed gaps to **0.1–2.8 bps** across eight sessions. No SPY dividend
ex-date falls in either window (last 2026-06-18, quarterly).

A corollary worth keeping: the 2026-08-05 mark was a catch-up **3h01m late** and drove the
week's largest single-day gap (**+130.3 bps**), yet contributed **exactly zero** to the week
aggregate, because it is interior to the window and cancels. Off-schedule marks move days,
not weeks, whenever the window's two edges are on schedule.

**Finding 2 — the crypto gap was a comparator dating defect, not mark-window length.** A
crypto mark fires at 00:30 UTC, **thirty minutes into** UTC day `d`, so the interval ending
there covers day `d−1` for 23.5 of its 24 hours. The review paired it with session `d`,
shifting every crypto comparison by a full session. Tested against BTC's own bars over
twelve intervals, mean absolute error was **81.0 bps** pairing with `d` and **33.0 bps**
pairing with `d−1`; across the clean 24.00h on-schedule stretch of 2026-08-05..09 the `d`
pairing missed by up to **116 bps** while `d−1` matched to **0.1–9.1 bps**. Re-pairing cut
week 2026-08-02's **+208.08 bps** to **−1.03 bps** (that week's cadence was intact — all
seven UTC days marked — which is why it isolates the defect so cleanly) and week
2026-08-07's **+132.05 bps** to **+10.67 bps**.

This **supersedes the mechanism named in `_CRYPTO_STRUCTURAL_NOTE`** for these weeks.
Variable mark-window length and mark-phase straddle were the right story for week
2026-07-24, when three *leaked* 14:00Z marks genuinely scrambled the spacing to 10.49–32.72h.
With the leak fixed and marks landing at 00:30Z, that noise cleared and exposed a constant
one-session shift underneath it — larger than the mechanism it was hiding behind.

**Finding 3 — a missed run, and what it does to the arithmetic.** No crypto run fired on
**2026-08-01** (no run report, no equity mark, no alert, for both crypto accounts), leaving a
**70.40h** interval followed by a **6.92h** one. In week 2026-08-07 the compared window then
holds seven shadow sessions against six paper intervals: session **2026-07-31**
(**−185.91 bps**) has no paper counterpart at all. Paired daily gaps sum to **−176.0 bps**
and that orphan session contributes **+185.91**, netting the **+10.67**. The small net is
arithmetic coincidence, not structure — a different BTC path across 07-31/08-01 leaves a
large residual with identical cadence.

**Finding 4 — the store was stale at both generation instants.** At the 2026-08-02 review
the last stored SPY/IEF bar was **2026-07-30** while the NYSE calendar had completed
**2026-07-31**; `digest_20260802`, generated in the same second, records
`staleness_sessions: 1`, so the health check saw it. At the 2026-08-07 review the calendar
had completed **2026-08-07** — the review ran at 21:00:04.381Z, **4.4 seconds past** the
21:00:00Z session-completion cutoff — while the store still held **2026-08-06**, with no
ingest in the intervening fifteen minutes. Both reviews therefore measured a week ending one
session earlier than the calendar allowed. The alignment fix behaved correctly in all six
cases (no orphan day landed whole in a divergence, the 2026-07-24 defect); the exclusions
were **store staleness**, not calendar truncation.

**Run audit, 2026-07-28..2026-08-07.** `voltarget` 9/9 attempted/completed, 0 aborted, 0
missed. `trend` 9/9, 0 aborted, 0 missed, 9 in-band no-trade. `crypto_voltarget` and
`crypto_trend` 10 of 11 expected days, 0 aborted, **2026-08-01 missed**. **`voltarget` DID
run on 2026-08-06**: `run_voltarget_20260806T140006Z.json`, all nine stages `ok`, plan
detail `in-band, no trades`, `current_w` 0.6876 vs `target_w` 0.6898 → `diff` 0.0022 below
`min_trade_frac` 0.01, and its equity 102,490.84 was written to the history. An
**in-band-no-trade completion, not a missed run** — the distinction the run audit now states
explicitly, because the two look identical in a run count.

**Six re-rulings. All six account-weeks are MARK-TIMING-STRUCTURAL.** No account-week shows
tracking error, execution slippage beyond one day's fill effect, risk-path interference (0
of 38 runs aborted, no halts), or strategy misbehaviour. Unexplained residual never exceeds
**+4.24 bps** anywhere.

| account | week | published | verdict as published | re-ruling |
|---|---|---|---|---|
| voltarget | 2026-08-02 | +12.72 | TRACKING | TRACKING — stands |
| trend | 2026-08-02 | +21.10 | TRACKING | TRACKING — stands |
| crypto_voltarget | 2026-08-02 | +208.08 | DIVERGING | **VOIDED** — comparator dating |
| voltarget | 2026-08-07 | +77.86 | DIVERGING | **TRACKING** — mark phase |
| trend | 2026-08-07 | +101.39 | DIVERGING | **TRACKING** — mark phase |
| crypto_voltarget | 2026-08-07 | +132.05 | DIVERGING | **VOIDED** — comparator dating |

**Both crypto blockers are VOIDED as a comparator dating defect**, not as a partial-bar
artifact — the inputs were complete and the computation reproducible; the *pairing* was
wrong. The two equity DIVERGING blockers from week 2026-08-07 are **withdrawn**: their
residuals after decomposition are **+2.63** and **+1.88 bps**.

**The published reports stand unmodified.** `week_20260802.*` and `week_20260807.*` are the
record of what was reported and are not rewritten; this entry is the correction, and the
demonstration that produced these figures wrote nothing. Precedent: the 2026-07-25 entry.

---

## 2026-08-10 — Residual thresholding: fix the instrument, not the threshold

**Decision.** Three measurement-correctness fixes on the reporting path, and a change in
what the 50 bps threshold is applied *to*. **The threshold value is unchanged at 50 bps.**

**(A) Per-asset-class mark-to-session dating.** `weekly.session_for_mark` maps a paper mark's
date to the shadow session whose period the interval ending at that mark actually covers:
offset **0** for `us_equity` (a 14:00Z mark sits mid-session, and pairing with its own
session is exact up to the endpoint remainders the decomposition prices) and **−1** for
`crypto` (a 00:30Z mark closes the previous UTC day). The offset is applied in three places
that must agree or the comparison is incoherent: the weekly pairing, the cumulative pairing,
and the **coverage-exclusion test** — a mark is comparable when its *paired* session is
covered, not when its own date is. Equity behaviour is unchanged, pinned by regression.

*Documented limitation.* The offset is per asset class, **not per mark**. A `leaked` crypto
mark from the pre-2026-07-22 14:00Z equity task sits mid-day and is mis-paired by one session
under this rule; so is an off-schedule crypto catch-up such as the 2026-08-02 **22:54Z** mark,
which sits at the *end* of its UTC day. Those marks predate the crypto readiness clock's
restart or are flagged `catch_up`, and a clock-time-aware rule is a later decision rather
than a silent guess here — the same posture `glassbox.constants` takes on its EDT-era
provenance windows.

**(B) Mark-phase decomposition, and the verdict moves onto the residual.** `AccountWeekly`
now carries `raw_divergence_bps`, `predicted_mark_phase_bps`, `residual_bps` and a
`decomposition_note`, all three numbers rendered in the markdown with one line saying which
one decides. `reporting.markphase` sums per-session contributions
`w_post × (r_mark − r_session)`, which is the telescoped form of finding 1's endpoint
remainders. It is implemented in the summed form deliberately: it needs **no share count**
(only price ratios, recovered from `equity − cash` and the signed order notional), and it
carries a **distinct `w_post` per session**, so `voltarget`'s daily weight changes decompose
correctly instead of assuming one weight for the week. The two forms agree to **0.11 bps** on
`trend`'s static week; a test pins <0.5 bps.

**Verdict is `|residual| ≤ threshold`.** When inputs are incomplete — a missing run report,
an aborted run, or a holding that is not exactly one symbol, in which case `equity − cash` is
a basket and no implied price exists — the prediction is `None`, the verdict falls back to
the raw divergence, and the note says `decomposition unavailable` so a fallback pass can
never be mistaken for an explained one. The DIVERGING alert and the readiness blocker both
quote the figure that actually decided, labelled `residual` or `raw`.

**(C) Unpaired sessions.** `unpaired_sessions` lists sessions inside the compared window that
no paper interval closes on, rendered in the markdown. The 2026-08-01 miss surfaces as
session **2026-07-31** for both crypto accounts in both weeks, instead of being folded
silently into a 70.40h interval's comparison.

**Rationale.** The 50 bps threshold is a policy statement about how far an account may drift
from its own model before a human looks. It was being applied to a number that was mostly
arithmetic: `trend` tripped it at +101 bps in a week it did not place a single order.
Loosening the threshold would have hidden real drift along with the geometry; leaving it
meant four false blockers in two weeks and a gate that cries wolf. The defect was never the
number — it was that the instrument measured mark timing and the threshold was being read as
though it measured behaviour. So the instrument was fixed and the threshold left alone.

**Freeze compliance.** Report-only. No strategy parameter, risk limit, threshold value, alert
threshold, run cadence, `broker/` module, order-submission path, or sanitizer pattern is
touched. (A) changes which shadow session a paper interval is compared against; (B) and (C)
add fields and rendering. `divergence_bps` is retained alongside `raw_divergence_bps` because
the published week files and the Glass Box reader key on it. Precedent: the 2026-07-25 aligned
windows and completed-session bars, and the 2026-07-22 scheduler-leak fix.

**Demonstration.** Both weeks recomputed read-only at their published generation instants,
with the store frontier pinned to what it held at publication so the equity windows reproduce
exactly. Nothing written.

| account | week | raw | predicted | residual | verdict |
|---|---|---|---|---|---|
| voltarget | 08-02 | +12.72 | +9.80 | **+2.92** | TRACKING |
| trend | 08-02 | +21.10 | +19.18 | **+1.92** | TRACKING |
| crypto_voltarget | 08-02 | +55.44 | +38.01 | **+17.43** | TRACKING |
| voltarget | 08-07 | +77.86 | +75.23 | **+2.63** | TRACKING |
| trend | 08-07 | +101.39 | +99.51 | **+1.88** | TRACKING |
| crypto_voltarget | 08-07 | +15.50 | −38.97 | **+54.47** | DIVERGING |

Five of six clear the threshold. **`crypto_voltarget` week 2026-08-07 does not, at +54.47
bps, and that is reported rather than tuned away.** Its cause is localised: on the subset of
that same week where every mark is `on_schedule` and every interval is exactly 24.00h
(2026-08-05..08-07) the residual is **−0.54 bps**, and it degrades monotonically as
off-cadence intervals are added back — +43.98 including the 18.68h window, +49.73 including
the 6.92h and 70.40h windows, +54.47 including the orphan session. A **6.92h mark window
straddling midnight has no single-session counterpart at daily resolution**, so this is the
limitation named in (A) and the irreducible cost of the 2026-08-01 miss, not account
behaviour. The crypto windows also slide one mark forward of the published ones, because
under (A) a mark whose paired session is covered is no longer excluded — which is the fix
working, and why these raw figures are not the published ones.

---

## 2026-08-10 — Turnover: 33.79% in one week, and what it actually costs

**Finding.** `voltarget`'s realized turnover was **33.79%** over 2026-07-28..2026-08-01 —
**2.3× the top of the 10–15%/week heuristic** — and **13.50%** over 2026-08-03..08-07, inside
it at the upper end. Realized equals planned: every intent was submitted, and order notional
÷ equity reproduces `plan.est_turnover` on every run. The breach is concentrated in two
single-day rebalances, **11.61%** on 07-29 pushing to `target_w = 1.0` and **13.18%** on
07-31 reversing to 0.8048 — a whipsaw, against the following week's monotonic de-risking
glide (0.8048 → 0.6878).

**Modeled cost quantified.** At the shadow's 5 bps one-way rate the drag is **1.690 bps** for
the 33.79% week and **0.675 bps** for the 13.50% week (**1.031** and **0.618 bps** over the
review windows themselves). **This is the converge-vs-backtest cost, and it is not paid
symmetrically.** The shadow models it; Alpaca paper charges no commission, so paper keeps
what the shadow spends and the modeled drag shows up as *positive* divergence. Against
divergences of 78–101 bps it is **under 2%** of the gap — which is the point worth recording:
turnover was investigated as a divergence suspect and **exonerated**. It cannot account for
these weeks, and the decomposition above shows what does.

**No action now, and why.** The 5 bps assumption is the live exposure, not the turnover
figure: it is a *modeled* rate, never validated against a fill. On SPY at this size real
one-way cost is plausibly below 5 bps, in which case the shadow over-charges and the
divergence is flattered; the sign of that error is unknown until fills are examined. Two
weeks is also too short to call 33.79% a regime rather than one whipsaw — the strategy
parameters that produced it are frozen, and re-tuning them to hit a turnover heuristic would
be a strategy change dressed as a measurement fix.

**Revisit at day 90**, alongside the live-readiness decision, with (a) realized turnover
distribution over the full track rather than two weeks, (b) the 5 bps assumption tested
against actual paper fill prices versus the marks, and (c) whether the heuristic itself is
the right band for a daily-converge vol-target account. Recorded here so the day-90 review
inherits the question instead of rediscovering it.

---

## 2026-07-27 — DKIM key published, and why that is not the same as DKIM working

The G5 entry recorded DKIM as out of reach because it needs Google Workspace Admin. Half of
that was right. Generating the key is an Admin action and activating it is an Admin action,
but **publishing it is a DNS action**, and the zone is ours — so Part B was executable after
all. `TXT google._domainkey` is live: additive create, `MX` verified before and after, zone
diffed to prove exactly one record was added and nothing pre-existing moved.

**The verification is the part worth recording.** A DKIM value is 410 characters of base64
that no human can proofread, and DNS splits it across two 255-byte character-strings, so the
published form does not even look like the input. Eyeballing it would be theatre. Instead the
record was reassembled from its chunks and compared to the source by SHA-256, then decoded to
confirm it is a 294-byte SPKI carrying a 2048-bit RSA key with exponent 65537 — checked
against what the authoritative nameservers actually serve, and against what a public resolver
reassembles, not against what was sent. **For a value this shape, "identical" has to be an
assertion, not an impression.**

**DKIM is published and still not on.** Until *Start authentication* is clicked, outbound mail
carries no signature, and the only symptom is an absence — the same failure mode that let this
domain run unauthenticated for as long as it did. So the README now names four parts with
owners rather than one checklist: a published key reads as "done" to anyone skimming, and that
misreading is the whole risk. It also warns against re-clicking *Generate new record*, which
would silently invalidate the key just published.

---

## 2026-07-26 — One apex, a real domain, and mail that can finally be authenticated

**The two-apex question is closed.** Quant Lead ruling: `monzonautomation.com` is not owned and
will not be acquired. There is one apex, `danielmonzonautomation.com`, and Glass Box lives at
`glassbox.danielmonzonautomation.com`. The discrepancy tracked in `docs/brand.md` §6.1 was
resolved by a decision, not by DNS.

**DNS changes on a domain that carries live mail, done additively.** The zone is Netlify-hosted,
so this was executable rather than a handover document. `MX` was re-verified before and after
every individual change — five checkpoints — and never differed from `1 smtp.google.com`. Two
structural safeguards were worth more than the care: the Netlify API offers `createDnsRecord`
and `deleteDnsRecord` but **no update method**, so a record cannot be silently mutated; and a
full record inventory was captured before the first change and diffed after the last, proving
every pre-existing record was byte-identical afterwards.

**A `CNAME` was the wrong instrument, and the wrong-ness was invisible.** Generic DNS advice —
and this project's own G4 runbook — says a subdomain takes a `CNAME`. On a Netlify-hosted zone,
attaching the domain to the site makes Netlify create its own `NETLIFY`-type record, the same
mechanism already serving the apex and `www`. Doing both left **two records for one hostname**,
which RFC 1034 forbids: a `CNAME` may not coexist with other data at a name. Nothing failed —
the resolver silently preferred the managed record and all eight routes returned 200 — which is
precisely why it was worth finding. The redundant `CNAME` was deleted and the runbook now says
to let Netlify write the record.

**Mail authentication: two of three, and the third is honestly out of reach.** SPF and DMARC are
live. SPF was created only after re-confirming zero existing `v=spf1` records, because two is a
permanent failure rather than a merge. `~all` not `-all`, and DMARC at `p=none`: **observation
before enforcement.** A domain that has never published SPF does not yet know every service
legitimately sending on its behalf, and enforcing first is how a business blackholes its own
invoicing. DKIM requires Google Workspace Admin and cannot be done from here — so it is written
as click-by-click instructions rather than half-attempted, including the step people miss
(clicking *Start authentication*, without which the published key does nothing and fails
silently).

**"Security headers matching the Glass Box standard" stayed refused, and the refusal was
tested.** The marketing site received four headers — `X-Frame-Options`,
`X-Content-Type-Options`, `Referrer-Policy`, and a `Permissions-Policy` that denies camera,
microphone and geolocation but **leaves `payment` enabled because Stripe needs it**. No CSP: all
22 of that site's scripts are inline and five third parties are load-bearing. Verification
drove real Chrome before and after and compared: identical third-party load counts, all widget
globals present, zero blocked resources, zero console errors. The probe had to *trigger* each
integration — consent-accept for Clarity and Chatbase, booking-intent scroll for Calendly —
because a plain page load reports zero requests for all five and would have read as "everything
is broken" when the truth was "everything is correctly deferred". **A verification that cannot
distinguish deferred from broken is not a verification.**

**Canonical host wired in code, not in a command.** `SITE_URL_DEFAULT` in `vite.config.ts` and
`VITE_SITE_URL` in `netlify.toml` both name the custom domain. Making it a required env var
would have meant a forgotten export produced a successful build that quietly declared the wrong
host canonical, with nothing downstream failing. The `.netlify.app` host still answers 200 but
declares the custom domain canonical, so it is an alias rather than a competitor.

**A footnote on a number that was being carried forward.** `/decisions` mobile CLS was recorded
as 0.187 and still-open since G3. Re-measured on the new domain across four runs: **0**. The G3
work fixed it; the open figure was stale, not the problem. Numbers taken on trust go stale the
same way code does.

---

## 2026-07-26 — The marketing site was already live, and the CTA pointed at nothing

**Three findings, none of them what the batch was scoped around.** G4 was written to deploy
the MonzonAutomation marketing site to a new Netlify project and to park the Story CTA on a
placeholder link until an apex went live. Measuring first changed all three items.

**The site is already in production.** `github.com/danielfmonzon/dma-website` builds clean
(Astro, `npm run build`, 8 pages, no placeholder markers) and is already deployed at
`https://danielmonzonautomation.com` — Netlify project `danielmonzon`, custom domain
attached, live HTML byte-identical in its headline and title to a fresh local build, plus a
`dmonzon-staging` site on the same repo. Creating a third deployment named
`monzonautomation` would have published a competing copy of a live business site: two URLs
to keep in sync, and two hostnames competing for the same search ranking. **The site was
not unfinished, so the instruction's own guard — assess before forcing a deploy — resolved
to "do not deploy."** No new site was created. What ITEM 2 actually wanted, a
production-hosted marketing site, already existed.

**"Security headers matching the Glass Box standard" would have broken it.** Glass Box runs
`default-src 'self'` because it is self-contained: no third-party script, no inline script,
no embed. The marketing site is the opposite — 22 inline `<script>` blocks, zero external JS
bundles, and functional dependencies on Calendly, Stripe, Tally, Chatbase and Microsoft
Clarity. Copying that CSP across would have silently disabled booking, checkout and chat on
a live lead-generation site. **A security standard is a property of a threat model, not a
file to copy between projects.** The headers it can safely take, and the report-only CSP
path to a real policy, are recorded in the G4 report; none were applied, because pushing an
untested CSP to a live revenue path is not a change to make without its owner watching.

**The CTA pointed at an unregistered domain.** `monzonautomation.com` returns `NXDOMAIN` —
not an empty site, an unowned name. The most important link on the landing page, the one
asking a reader to become a client, produced a browser error, and two more references in
the footer did the same. The brief anticipated substituting a personal profile URL; the
better answer was the live marketing site, which returns 200 and *is* MonzonAutomation, so
the link is now correct rather than merely non-broken. `MONZONAUTOMATION_URL` in
`src/content/copy.ts` is the single point of change, and a test asserts the string appears
exactly once in that file so the three call sites cannot drift apart again.

**The DNS warning was aimed at a risk already taken.** The brief asked for a loud warning
never to move the nameservers, because the domain carries live email. The nameservers have
already been moved — the zone is on Netlify DNS (`dns1–dns4.p08.nsone.net`) and the Google
Workspace `MX` record survived the migration intact. The warning that still applies is a
different one, so the runbook states that one instead: the mail records now live in the same
Netlify panel as the web records, so bulk edits there are what breaks mail. And the premise
turned out to overstate the protection in place — the domain publishes **no SPF, no DMARC
and no DKIM**, so it is currently unauthenticated and spoofable. Documented as a mail task
rather than fixed, because it is outside this project and its own change window.

---

## 2026-07-26 — A gate that checks for presence, and a page readable without JavaScript

**The completeness gate.** `verify-dist` only ever asserted the ABSENCE of forbidden
content, and on 2026-07-26 it passed a build with no snapshot in it at all — because with
no data there was nothing forbidden to find. The deploy that followed served a working
shell with zero figures. **A gate that only looks for poison cannot notice an empty plate.**

`glassbox/completeness.py` adds five positive assertions, each a claim the published site
makes implicitly by existing, restated as something falsifiable: the manifest exists and
parses; its `endpoint_count` clears a floor of 20 AND matches both its own `endpoints` list
and the files on disk; the capture is within `--max-age-days` (default 14); at least one
account carries a non-null equity figure; and `index.html` references an entry bundle that
is actually present. They render as their own CONTENT section with the same loud PASS/FAIL,
and `verify_dist.passed` now requires both.

Deliberately a **separate module**: content completeness and secret detection fail for
different causes and should be readable independently — and the sanitization patterns are
frozen by ruling, so the new work had to sit beside them rather than inside them.

**Prerendering.** The site served an empty shell to anything that did not run JavaScript:
head tags and `<div id="root"></div>`, under 100 characters of readable content. For a page
whose entire argument is "you can check this", that was the wrong first impression.

`scripts/prerender.mjs` builds an SSR bundle, renders Story against the snapshot JSON
already in `dist/`, and injects the markup plus a `<script type="application/json">` data
block carrying the same overview payload — that type is not executed, so the strict
`script-src 'self'` CSP does not block it, where an inline assignment would have needed a
nonce. `main.tsx` hydrates only when `data-prerendered` matches the current path. The live
page now serves 6.9 kB of readable text and the day count is real, not an em dash.

Non-Story routes get flat `dist/<route>.html` shells with correct per-route head tags and a
`<noscript>` block, but no prerendered body: those screens are `React.lazy`, so
`renderToString` would emit the Suspense fallback. Flat files rather than
`<route>/index.html` because Netlify 301s a directory path to its trailing-slash form,
adding a redirect hop to every internal link.

**Two mistakes worth recording.** First, the server entry originally composed nav + main +
footer by hand rather than rendering `<App />`, on the reasoning that App's drawer state and
banner fetch had no meaningful server form. Hydration compares the WHOLE tree, so the
missing skip link and mobile bar produced React #418/#423 on every load and the prerendered
markup was discarded — crawlers still got the HTML, but every real visitor paid for a full
re-render and saw six console errors. Rendering App is both correct and simpler. Second, a
`cd` that failed silently meant that fix was not applied to the first redeploy, and it took
an empirical server-vs-client markup diff to notice; guessing at the cause had already cost
two wrong attempts.

**Reading experience on /decisions.** Sixty-five run cards at once was a comprehension
problem before it was a metrics problem. Ten most recent, "Show more" appends ten, filter
change resets the page. The newest run renders EXPANDED: the narration is the thing this
site exists to demonstrate, and requiring a click meant the most important feature was
invisible on arrival. Mobile CLS moved 0.223 → 0.187, which is progress and not a fix — see
below.

**Copy.** `STORY_CTA` is first person singular. The brand voice is "I", and a page arguing
against overclaiming should not inflate one builder into a "we".

**The path to the builder.** A recruiter's only route to who made this was one footer line
five sections down. "How this was built" now sits before the CTA: twelve reviewed batches,
the human approval gate on money/credentials/claims, the two self-caught incidents, and
errors caught in both directions — with links to the ledger and the GitHub profile. Facts
only; every claim is checkable from the ledger.

**Still open.** `/decisions` mobile CLS is 0.187, above the 0.1 "good" threshold. Pagination
and a reserved narration placeholder brought it down from 0.96, but the remaining shift is
ten cards mounting into a lazy route on a throttled connection. Fixing it properly means
virtualising the list or server-rendering that route, and both are larger than this batch.
It is recorded rather than rounded away.

---

## 2026-07-26 — Glass Box is a MonzonAutomation property: brand, canonical copy, and a public deploy

**Brand adoption, not brand invention.** `docs/brand.md` records the extraction from
`danielfmonzon/dma-website`: the full cream/ink/green/honey/clay token block, Fraunces +
Hanken Grotesk on their variable axes, the typographic wordmark with its honey dot, and
the voice. The brand is coherent and well-tokenised, so Glass Box adopts it rather than
proposing a replacement. `monzonautomation.com` did not resolve from this machine, so the
findings come from the repository — which is upstream of the site anyway.

**The dark theme is gone.** Glass Box was near-black by deliberate choice in F2
("Bloomberg-meets-Linear"). The brand is unambiguously warm-light, and a black dashboard
hanging off a cream marketing site reads as two companies. Brand coherence beats an
aesthetic preference. Density, typographic hierarchy, motion-only-on-state-change, and the
three-layer chart contract all survived the port.

Three additions were needed and are documented as such: semantic status colours (derived
from existing brand hues and darkened until each measures AA on cream), a system mono
stack for tabular figures, and nothing else.

**Contrast is measured.** `scripts/contrast.mjs` computes exact WCAG ratios for all 23
foreground/background pairs the UI renders: 23 AA, 15 AAA, zero failures. The script exits
non-zero, so it can gate a build. Its blind spot is documented and cost us a real failure:
it measures TOKEN pairs, and `text-clay/70` rendered at 3.1:1 where `text-clay` measures
5.61:1. Opacity is no longer applied to text anywhere.

**Copy is canonical.** Every `PLACEHOLDER_*` flag and its UI warning is deleted. The Story
hero, five sections, nav labels with teaching subtitles, and the footer disclaimer are the
approved wording, reproduced verbatim in `src/content/copy.ts`. One divergence from the
brand voice is retained as supplied and flagged in `docs/brand.md` §6.2: the CTA block uses
"We", where the rest of the brand is emphatically first-person singular.

**Accessibility is a requirement, not a score.** WCAG 2.2 AA, verified by axe-core over
every screen in both populated and empty states — zero violations, 40 a11y tests. The parts
axe cannot judge are pinned by hand:

* **Provenance is encoded three ways** — shape (● ◐ ▲), colour, and text. Roughly one man
  in twelve cannot separate the green from the clay, and provenance is precisely the field
  where that matters, so any one of the three carries the meaning alone.
* **Glossary terms open on click/focus, never hover.** A hover-only disclosure is invisible
  on touch and unreachable by keyboard — it would show the definitions only to mouse users,
  the group least likely to need them.
* **Charts are `role="img"` with the takeaway as the accessible name.** Recharts emits
  hundreds of path nodes a screen reader would read as fragments; naming the figure gives a
  non-visual reader the same one-sentence conclusion a sighted reader gets.
* **The mobile drawer traps focus** and hides BOTH the content column and the footer. Marking
  only the content left the disclaimer reachable from inside a modal.

**Sanitizer hardening, and two lessons about gates.** `verify-dist` now scans the entire
published directory — compiled JS, CSS, HTML, SVG, JSON — because the snapshot gate only
vets what the snapshot writer wrote, and a secret can reach the public through an inlined
constant or a stray file in `public/`. Two false positives were fixed on the principle that
**a gate which fires falsely trains its operator to ignore it**:

1. `ALPACA_BASE_URL` is a public documented endpoint; secret-prefix checking it could fail
   the build over a URL that is meant to be greppable. Non-secret keys are now excluded by
   an allowlist plus a public-URL test, and the exclusions are **printed**, so a reader can
   see which checks did not run.
2. The bare header names `APCA-API` and `Authorization` matched this very decision log,
   which is published through `/api/decisions` — the gate failed the build over its own
   documentation. The patterns now require a header WITH a value, which is what a captured
   request envelope always has.

The sanitization report also moved OUT of the published tree to
`reports/glassbox/sanitization-report.txt`. It was being served publicly, it is an internal
review document, and it lists the patterns the gate searches for.

**Deployed.** https://monzonautomation-glassbox.netlify.app — HTTPS with HSTS, the
`netlify.toml` CSP (`default-src 'self'`, `frame-ancestors 'none'`), nosniff,
referrer-policy, immutable asset caching, real 301s for every pre-G1 path. Lighthouse on
the live site: **100/100/100/100** on `/` (mobile and desktop) and 97/100/100/100 on
`/decisions` mobile.

**No custom domain, deliberately.** DNS belongs to the domain owner; `frontend/README.md`
carries the exact CNAME record and the two follow-ups (rebuild with `VITE_SITE_URL`, and
decide which apex is canonical — the marketing repo says `danielmonzonautomation.com` while
this project links to `monzonautomation.com`, and two apexes for one brand split SEO
authority).

**The deploy gate still stands.** The tool's PASS is necessary, not sufficient: it only
knows the patterns it was told about. This deploy was authorised explicitly, and the
sanitization report is in the G2 report for review.

---

## 2026-07-26 — Two products from one codebase, and a gate between them

**Decision.** The Glass Box is now **two products** built from one codebase:

* the **operational dashboard**, served by `quantlab glassbox serve` on `127.0.0.1`,
  reading the live API — unchanged in behaviour;
* the **public site**, a static build that reads flat JSON captured by
  `quantlab glassbox snapshot` and hosted on Netlify.

The public build has **no route back to the machine that trades**. It fetches
`/snapshot/*.json` and never `/api/*`, so there is no path from the internet to the
broker credentials, the artifacts, or the API — not a firewall rule that could be
misconfigured, but an absence of the capability. That is the whole reason for the
split, and it is why the public site is a snapshot rather than a read-only proxy:
a proxy would still be a door.

**Snapshot architecture.** `quantlab glassbox snapshot` enumerates every `/api` GET
route **from the app itself** rather than from a hand-kept list, so a new endpoint is
captured automatically and cannot be silently omitted; the parameterised narration
route is expanded over every run on disk. Capture runs in-process through
`TestClient` — no server, no port, no network. Files are addressed by a
`canonical_key` mirrored verbatim in the frontend, with `limit` excluded because
captures are full-depth. `manifest.json` records the capture instant, git commit and
version, and the banner on every public screen reads its timestamp from there, so a
stale snapshot is visible rather than quietly out of date.

Two guards earned their place on the first run:

* **Depth vs declared ceiling.** `/api/runs` declares `le=1000`; the pipeline asked
  for 5000 and FastAPI answered **422**, so the first snapshot contained five
  validation-error bodies that serialise to JSON and sit in a capture looking like
  data. Depth is now per-endpoint, and `capture` **refuses any non-200** rather than
  trusting those constants to stay correct.
* **All-or-nothing writes.** A forbidden pattern aborts before any file is created —
  not even the clean ones. A partially-written snapshot is worse than none, because
  it looks finished.

**Sanitization is a gate, not a step.** Every byte is redacted and vetted in memory
before anything is written. Redactions rewrite what is merely *local* (Windows user
paths, POSIX home directories → `<path>`). Forbidden patterns **abort**: Alpaca
account ids, any email address, `APCA-API` / `Authorization` header names, and the
first eight characters of every value in the local `.env`. Redaction runs first, so
the text that would actually ship is the text that gets vetted.

The report is built to be **safe to share**: pattern names, match counts, and file
locations, never the matched text — a report that echoed the secret it found in order
to prove it found one would be the leak it exists to prevent. Secret prefixes are
searched for and never printed, logged, or attached to the report object. And when
`.env` is absent the report says **NOT CHECKED** rather than reporting a vacuous pass:
"0 matches" and "the check did not run" are different claims, and conflating them is
how a gate fails open.

**Deploy is gated on a human.** A PASS from the tool is **necessary, not sufficient** —
it only knows the patterns it was told about. The ritual is snapshot → *Quant Lead
reads the sanitization report* → `build:public` → deploy, and the report is written to
`frontend/public/snapshot/sanitization-report.txt` for exactly that review. There is
no automatic refresh by design: each publication is a deliberate act.

**Landing page.** `/` is now the Story screen and the operational Overview moved to
`/live`. Pre-G1 paths redirect — client-side in the app and as real 301s in
`netlify.toml` — so existing links do not rot. This is the one intentional behaviour
change to the operational dashboard; every screen is otherwise identical, which the
60 pre-existing frontend tests still assert.

**Copy is placeholder, and says so.** The brief specified the Story prose, the nav
renames, and the footer disclaimer by reference to documents (F4, F2, F15) that are not
in this repository or its history. Text cannot be reproduced verbatim from an absent
source, and a public-facing legal disclaimer is the last place to invent
plausible-looking wording — so every user-facing sentence lives in
`frontend/src/content/copy.ts`, is flagged in the UI behind `PLACEHOLDER_*` constants,
and must be replaced before deploy. **The copy review joins the sanitization report at
the same human gate.**

---

## 2026-07-25 — Tier correction: Proven is earned at day 90, not before

**Correction (Quant Lead ruling).** The equity accounts were prematurely labelled
**Proven** in the Glass Box tier map. All four accounts are now **Probable**.

`voltarget` and `trend` were given Proven on the strength of their validation
battery plus a 15-day paper track. That inverts the gate: the battery is the ENTRY
condition for paper tracking, not a substitute for it. Proven is earned by passing a
clean day-90 readiness review on live paper tracking — no DIVERGING weeks, no KILL,
at least four completed runs per week sustained to the gate — and by that standard
nothing here qualifies yet. Day 15 of 90 is not a track record.

The tier payload now carries an `upgrade_condition` per asset class, naming the gate
and projecting the date from each class's ACTUAL clock start (equity 2026-07-09 →
~2026-10-07; crypto, restarted 2026-07-22 → ~2026-10-20). Deriving the projection
from the live clock rather than hardcoding it means a future restart moves the date
instead of leaving a stale promise on the screen. The `Proven` rationale string now
names the day-90 gate explicitly, and a test asserts no account carries Proven, so
the tier cannot be re-awarded on battery evidence alone.

---

## 2026-07-25 — Glass Box frontend: seven screens, and two conventions that constrain them

**Decision.** `frontend/` is a Vite + React + TypeScript + Tailwind + Recharts SPA
over the nine read-only endpoints. `quantlab glassbox serve` mounts `frontend/dist`
at `/` when the build exists; with no build the API is untouched and `/` explains how
to produce one. A missing view must never take the data down with it, so the static
mount is registered last and cannot shadow `/api/*`.

**No chart without a takeaway.** `<Chart>` requires `takeaway`, `mechanics`, and
`rawHref` as non-optional props, so a chart with no stated conclusion is a **compile**
error — `tsc -b` runs before Vite in `npm run build`, meaning such a chart cannot
ship. The type system cannot see an empty string, so `assertChartContract` also
throws at render time; both halves are needed and the suite pins each. The reason is
that an unlabelled chart delegates the conclusion to the reader, who will reach one
anyway — better that the system state its own and be checkable than imply one and be
deniable.

**DIVERGING is amber, never red.** Red is reserved for a live kill switch, the only
state that actually stops trading. A diverging week is a question to investigate, and
the one case on record turned out to be a measurement artifact rather than a trading
fault. The divergence caption says this in words, because a colour convention alone
can be misread by someone seeing the screen for the first time.

**Three-layer disclosure on narration.** The prose is primary; every number in it is
hoverable and reveals the JSON path it came from; the raw report sits behind a
collapsed `<details>`. The client splits the narration on the exact `rendered`
strings the API returned, so the number→source mapping is the API's, not a
client-side re-derivation — a number the API did not declare as a fact renders as
plain text and cannot acquire a source path it was never given. A test asserts that
directly.

**Week 2026-07-24 shows both figures.** The divergence screen renders the published
−54.33 bps DIVERGING beside the corrected −6.06 bps TRACKING, with a connecting
annotation pointing at the ruling. Quietly replacing a published number with a better
one would erase the audit trail that makes the correction credible.

**Provenance colouring is not decoration.** A series of marks spaced 10 to 33 hours
apart looks exactly like clean daily data on a chart, and that resemblance is what
produced the false DIVERGING verdict. Each equity point is coloured by how it was
produced, and the legend carries the one-sentence reason it matters.

**Empty is a designed state.** Every screen is tested twice — against fixture
responses and against the empty responses a repo with no artifacts returns — because
a blank panel is the failure mode this app exists to avoid. Unknown equity reads "no
marks yet", never `$0.00`; an absent drawdown reads "Unknown", never "No".

`GLASS` — what the system reads against what it deliberately refuses to read — gets
the same design weight as `OVERVIEW`, since the refusal list is the load-bearing half
of the trust claim.

---

## 2026-07-25 — Glass Box: narration is template-bound, and ignorance is published

**Decision.** `src/quantlab/glassbox` serves a read-only HTTP API over the
artifacts this system already writes — run reports, weekly reviews, digests,
alerts, equity history, risk state, config, and this log. It trades nothing, holds
no credentials, imports nothing from `broker/`, makes no network calls of its own,
and opens no file for writing. It binds `127.0.0.1` only, with the host hardcoded
rather than exposed as a flag; **exposure and authentication are a later, explicit
decision**, and until it is recorded the only supported reach is a browser on this
host or a tunnel a human sets up knowingly.

**The no-fabrication rule, as an architectural constraint.** `/api/runs/{id}/narrate`
explains a run in English. Every token it emits must be derivable from exactly
three declared sources: the run report's own structured fields, the account's
pre-registered rule parameters, and the run id being narrated. Nothing else — no
market commentary, no news, no inferred motive, no model judgement about why a
price moved.

This is enforced, not asserted. Each rendered figure is returned as a
`NarrationFact` carrying its source path (`report.plan.intents[0].current_w`,
`rule_constant.voltarget.target_vol`,
`derived.abs(...target_w - ...current_w)`), and the suite extracts every numeric
token from the prose and checks membership in an allowed set rebuilt
independently from the raw JSON plus those constants. Canary tests plant an
`analyst_note`, a `news_headline`, a `model_confidence`, and an unreferenced
number, and assert none of them ever surfaces; a vocabulary test rejects
"rally", "sentiment", "Fed", "outlook", and their neighbours outright. The rule
constants are read off the LIVE strategy objects rather than typed into a map, and
a test pins them against `VolTarget`, `TrendSMA10`, `CryptoVolTargetBTC`, and
`CryptoTrendBTC` — so the parameters a narration quotes cannot drift into fiction
while still passing.

The reason to constrain it this hard is that a plausible explanation is more
dangerous than no explanation. A narrator free to say "trimmed SPY as momentum
faded" would be inventing a causal story from a system whose only inputs are
settled daily closes. Narration also states the branch the rule did **not** take
("traded because drift was 7.99%, above the 1.00% minimum-trade band; had drift
been at or below that band the runner would have left the position to drift
untouched") — a rule you only ever see fire is a rule you cannot audit.

**News and AI-confidence surfaces are deliberately replaced.** Two features that
would be conventional here are refused, and the refusal is itself an endpoint:

* `/api/ignored-inputs` names the five inputs the system reads — Tiingo EOD,
  Alpaca IEX as an independent cross-check, Coinbase daily candles, Alpaca paper
  account state, and the session calendars — and the seven it deliberately does
  not: news, earnings, analyst ratings, sentiment, intraday/quote/order-book data,
  macro releases, and any LLM opinion about the market. A reader can then judge
  what the strategies *cannot* know instead of inferring capability from a feature
  list. A confidence score would imply a probabilistic belief no strategy holds.
* **Distance-to-flip honesty** replaces it. `/api/risk` reports each account's
  current drawdown against the kill threshold that actually governs it, and the
  headroom between them; `/api/equity` flags every mark `on_schedule`,
  `catch_up`, or `leaked` using the 2026-07-24 diagnosis heuristics as documented
  constants, because a chart of marks spaced 10–33h apart looks like clean daily
  data and is not; and `/api/divergence` surfaces the published and corrected
  figures for week 2026-07-24 side by side, quoted from the ruling below and
  never recomputed.

**Interpretation is labelled where it occurs.** Validation tiers
(Proven/Probable) and mark provenance are editorial positions, not measurements;
both live in one reviewable constants module, ship their rationale in the payload,
and the provenance constants carry an explicit DST limitation rather than a silent
guess.

**Absence is a state, not an error.** Every endpoint answers 200 with an explicit
empty model on a repo with no artifacts at all, and skips a corrupt report or a
truncated parquet rather than returning 500 — tested against both a populated
fixture tree and a bare directory. A read-only proof walks every file's size and
mtime before and after exercising the whole endpoint surface and asserts nothing
changed.

**Freeze note.** The service reads; it does not participate in the trading path.
The only pre-existing modules touched are `cli.py` (one lazily-imported
`glassbox serve` subcommand — the import is lazy and tested to be, so a broken web
dependency can never block a paper run) and `pyproject.toml` (fastapi, uvicorn,
and httpx for the test client).

---

## 2026-07-25 — Week 2026-07-24 divergence diagnosis, and two re-rulings

**Finding.** Both DIVERGING verdicts in `week_20260724` were artifacts of the
measurement, not tracking error in the accounts.

`trend`, published **−54.33 bps**. Fully decomposed, with no residual:

* **−32.2 bps** — the 2026-07-24 14:00Z paper snapshot was compared against
  *nothing*. SPY's and IEF's stored history ended 2026-07-23 (that day's digest
  records `last_date: "2026-07-23"`, `staleness_sessions: 0`), so the paper week
  carried four snapshot-to-snapshot returns while the shadow week carried three.
  The orphan day landed whole in the divergence.
* **−22.2 bps** — mark-phase: paper marks at 10:00 ET, the shadow close-to-close.
  `trend` held a constant 133.028241898 SPY with ~zero cash and no trades all
  week, so paper equity ÷ qty *is* the SPY mark price; the implied 10:00 ET prices
  (745.77, 745.46, 748.79, 740.17) predict each daily gap from SPY's own bars to
  within **0.1–0.9 bps**. The −87.78 bps on 07-21 is the 10:00-to-close remainder
  swinging +49.59 → −37.69 across two intraday-reversal days. Notably 07-23 was
  the week's largest move (−123.5 bps close-to-close) yet produced only +8.95 bps
  of gap: the gap tracks intraday *position change*, not move size.

No snapshot in `trend`'s window was off-schedule (all five at 14:00:11–14:00:28
UTC), and **no SPY dividend ex-date falls in the window** — the last was
2026-06-18, on a quarterly cadence.

`crypto_voltarget`, published **+91.24 bps**: **not reproducible**. Re-running the
same code on the same store today yields **+211.46 bps**, and the cumulative
figure flips sign, **−54.46 → +67.12 bps**. The sole changed input is BTC's
2026-07-24 daily bar, which was **partial when the review ran** at 21:00Z — the
last ingest before it was the 05:43:03Z run. Inverting the shadow for the close
that reproduces the published numbers gives **65,230.06** against a final
**64,083.32** (+179 bps), and reproduces `shadow_week` +28.25 vs the stored +28.24
bps and `shadow_total` +141.75 vs +141.74 bps. Independently, chaining the paper
account's own equity × weight across runs puts its 05:43Z BTC mark at
**65,304.02** — within **11 bps** of the inverted figure. Two unrelated
derivations agree the shadow read a mid-morning price as a daily close.

Beneath that artifact the account's day-to-day gaps are mark-timing. Only **1 of
7** window marks was on schedule (00:30 UTC); three were catch-up runs and three
were the leaked 14:00 UTC equity task, giving mark windows of **10.49h to
32.72h** against uniform 24h UTC days. Scaling each window's BTC move against its
UTC-day move by the account's BTC weight matches the observed gap in sign and
magnitude on all six days, leaving a **+38.6 bps** residual across the week
(~82% explained) attributable to fill-vs-mark prices, fees and the shadow's cost
model. The largest positive contributors were **07-23 (+142.59 bps**, Thursday, a
10.49h window) and **07-21 (+139.14 bps**, Tuesday, a 14h phase offset) — neither
a weekend day; the weekend case (07-19 Sunday, +74.68 bps) ranked third.

**Re-ruling 1.** `trend` is **TRACKING** for week 2026-07-24. Recomputed through
the aligned code path at the instant the published review ran, its week divergence
is **−6.06 bps** over 2026-07-16 → 2026-07-23 — a **+48.27 bps** correction, and
comfortably inside the 50 bps threshold. (The aligned window slides back to
2026-07-16 to keep a full five snapshots; over the published window's own
2026-07-20 → 2026-07-23 span the figure is the ~−22 bps of mark-phase drift
itemised above. Both readings are inside the threshold; the −6.06 bps is the one
the fixed code reports.) Cumulative divergence moves −5.09 → **+26.90 bps**.

**Re-ruling 2.** `crypto_voltarget`'s **+91 bps headline is VOIDED** as a
partial-bar artifact. No verdict is recorded for that week: the underlying
divergence is structural mark-timing, but it cannot be quantified from a corrupted
input, and the honest recomputation (+211 bps) measures marks 10–33h apart against
24h sessions rather than any account behaviour. The **next clean Friday decides** —
the first week whose crypto marks are all on-schedule and whose bars are all
complete at review time.

**The published reports stand unmodified.** `reports/weekly/week_20260724.md` and
`.json` are the record of what was reported on 2026-07-24 and are not rewritten;
this entry is the correction. Re-deriving the corrected figure is a read-only
exercise, never an overwrite.

---

## 2026-07-25 — Aligned comparison windows and completed-session bar reads

**Decision.** Two correctness fixes arising from the diagnosis above.

**(1) Like-for-like weekly windows.** The weekly review now truncates the paper
snapshot window to the last session the shadow can cover, read from the shadow
series itself. Snapshots beyond it are excluded from **both** the weekly and the
cumulative divergence and reported in a new `excluded_tail_days` field, rendered
as `- excluded from comparison (no shadow data yet): 2026-07-24`. Deriving
coverage from the returned series rather than the store means an injected
`shadow_fn` defines its own coverage, so the alignment stays honest for any
alternative reconstruction.

**(2) Completed sessions only on every read path.** `completed_sessions_only`
truncates a price panel to `calendar.last_completed_session(now)` on the account's
own calendar, and is applied in `current_target_weights` (the runner threads its
existing `run_now` through) and in `shadow_returns`. Ingestion may still *write* a
partial current-day bar — the Coinbase upsert does, on every run — and that stays
harmless, because the next run overwrites it and it settles when the session
closes. Reading it is the defect.

**Rationale.** Both defects share a shape: a number that changes when you compute
it again. A signal or shadow return taken off an in-progress price is not
reproducible, and a paper mark compared against a shadow session that does not
exist yet measures the calendar rather than the strategy. Between them they
produced two false DIVERGING verdicts in one week and a cumulative figure whose
sign depended on the hour of the query. Fix (2) also brings the paper signal into
line with the backtest and the shadow, which have always read settled bars — the
three now agree on what a session is.

**Freeze compliance.** Precedent: the 2026-07-22 scheduler-leak fix, where a
correctness defect in *when* the pipeline ran was repaired under freeze without
touching what it decided. No strategy parameter, risk limit, alert threshold, run
cadence, `broker/` module, or order-submission path is modified here. Fix (1) is
report-only. Fix (2) does touch the trading path, and deliberately so: it changes
only *which bars are eligible to be read*, never the signal computed from them.
On the equity path it is provably inert — an EOD bar only exists after its session
closes — which the suite asserts by comparing a run's `target_weights` with the
filter on against the unfiltered signal on the same fixture. On the crypto path it
removes a bar that should never have been eligible. The panel is truncated before
the usable-history guard so that guard's abort reason stays accurate, and
`current_target_weights` re-applies it for direct callers.

A week stays "the last N snapshots", now applied to the *aligned* history: the
window slides back rather than shrinking, so a truncated tail does not silently
turn a five-snapshot comparison into a four-snapshot one.

**Tests.** 22 added (344 → 366). `tests/test_partial_bar.py` pins both read paths
against a synthetic BTC panel carrying a partial current-UTC-day bar, including
teeth checks that the bar *would* move both the signal and the shadow if read, and
that the vol-target weight sits strictly between 0 and 1 so "unchanged" cannot
pass vacuously. `tests/test_weekly.py` adds the alignment cases: the 2026-07-24
`trend` window in isolation (aligned −22.1 bps and TRACKING, ragged −54.3 bps and
beyond threshold), the window-slide behaviour on a production-shaped history, and
the degenerate cases (no coverage at all, no snapshots inside coverage).

---

## 2026-07-25 — Correcting the crypto structural-drift note

**Decision.** `_CRYPTO_STRUCTURAL_NOTE` is rewritten to name the mechanisms the
diagnosis actually measured: **variable mark-window length** (catch-up runs
produced windows from 10h to 33h in week 2026-07-24, against the shadow's uniform
24h UTC days) and **mark-phase offset** (a full 24h window struck mid-day still
straddles two UTC sessions, so a trending stretch is split between them and both
show a gap). Weekend and overnight gaps are retained as an explicitly **secondary**
case. The pinned note tests are updated to assert the new mechanisms and to
reject the retired premise.

**Rationale.** The old note claimed paper snapshots and shadow bars were "both
once-daily" and attributed the gap to weekend and overnight moves. Both halves
were wrong. Paper marks are once-daily only *after* the review collapses them;
their spacing was 10.49h to 32.72h that week, which is the dominant effect. And
the two largest contributing days — 07-23 at +142.59 bps and 07-21 at +139.14 bps
— were a Thursday and a Tuesday. The weekend explanation ranked third at +74.68
bps. A structural note exists so a reader can tell expected drift from tracking
error; one that names the wrong mechanism invites exactly the misreading that
occurred, and it is worse than no note because it sounds authoritative.

---

## 2026-07-22 — Scheduler catch-up, paired with a 15:30 ET submit cutoff

**Decision.** Enable `StartWhenAvailable` (missed-start catch-up) on the
scheduled tasks, and pair it with a **hard 15:30 ET cutoff** on any *submitting*
equity paper run. A run invoked with `--submit` after 15:30 ET on a trading day
aborts **before any broker call**, emitting a WARNING alert. Dry runs are
unaffected; crypto is unaffected.

**Rationale.** Two equity trading days were lost in two weeks because the host
was off at 10:00 and `schtasks` simply skipped the run — a silent gap in the
track record that the 90-day readiness gate depends on. Catch-up is the right
fix because **converge-to-target** makes a late run safe by construction: the
runner pursues the current target rather than replaying a missed rebalance, so a
recovered run reaches the same allocation a punctual one would.

The cutoff exists because that argument stops holding near the close. A signal
intended for 10:00 fired at 15:55 converges into the closing auction, taking the
day's full intraday move as slippage against a target chosen from the prior
session's data — and the shadow, which models a single daily mark, would read the
difference as tracking error. 15:30 leaves 30 minutes of liquid session for a
DAY order to fill while keeping the run clear of the close. A skipped day is a
visible gap in the ledger; a late near-close fill is invisible contamination, and
between the two the visible failure is strictly preferable.

Chosen over the alternative of "machine-on discipline" — an operational
convention that the host stays awake at 10:00 — because that is an unenforceable
promise about human behaviour guarding an automated track record, and it had
already failed twice.

---

## 2026-07-22 — The test suite polluted the production alert log

**Incident.** `pytest` wrote **49 fixture alerts** into the production
`reports/alerts/alerts.jsonl` across 16 bursts between `2026-07-22T17:19:48Z`
and `2026-07-22T22:13:56Z` — one burst per test invocation. The pollution
surfaced in that evening's weekly review, where `trend` reported
`CRITICAL=7, INFO=21, WARNING=14` for a week in which it had aborted no runs at
all; the `$200,000.00 notional` figure repeated 21 times is a fixture constant.

**Cause.** `FileChannel.__init__` took `path: Path = ALERTS_JSONL`. A default
argument binds **at import time**, so monkeypatching the module constant could
never redirect it, and any test reaching real `dispatch` wrote to the live log.

**Decision.** Three changes, and one deliberate non-change:

* `FileChannel` resolves its path at **send** time, so the constant is patchable.
* An **autouse** `isolate_alert_log` fixture in `tests/conftest.py` redirects
  every test's alert output to `tmp_path`. It also strips the five SMTP env vars
  — a developer with a populated `.env` exported into their shell would
  otherwise have had the suite send **real alert emails**.
* A regression test asserts the production log's size and mtime are unchanged
  across a real `dispatch`, reading the true path from `PROJECT_ROOT` rather than
  the redirected constant so it fails if the redirect ever breaks.
* **The polluted entries are NOT deleted.** A single structured annotation record
  (`source: ops.annotation`) was appended instead, naming the count, the burst
  timestamps, the cause, and the remediation.

**Rationale.** An append-only operational log is evidence. Editing it to remove
inconvenient entries destroys the audit trail and sets a precedent that the log
may be rewritten when it embarrasses us — exactly the property that makes it
worthless for a live-readiness decision later. Annotating costs one line and
leaves both the contamination and its explanation permanently inspectable.

---

## 2026-07-22 — Alert attribution by structured field, not substring

**Decision.** Every account-scoped alert carries a structured `strategy` field,
and `_alerts_in_window` attributes on that field. Legacy records written before
the field existed fall back to a **word-boundary** title match.

**Rationale.** Attribution was `label.lower() in title.lower()`. `trend` is a
substring of `crypto_trend` and `voltarget` of `crypto_voltarget`, so each equity
account silently absorbed its crypto namesake's alerts — `trend`'s `WARNING=14`
was 7 of its own plus 7 belonging to `crypto_trend`. The defect was invisible
while the weekly review covered only the equity pair, and became wrong the moment
both namesake pairs appeared in one report. A structured field is exact and
cannot be defeated by a future label that happens to contain an existing one. The
word-boundary fallback is correct for the legacy rows specifically because `_` is
a regex word character, so `trend` does not match `crypto_trend`.

---

## 2026-07-22 — Weekly review covers every asset class

**Decision.** `build_weekly_review` iterates **`APPROVED_STRATEGIES`** rather than
`EQUITY_APPROVED_STRATEGIES`, so the weekly paper-vs-shadow review renders a
section for all four approved accounts (`voltarget`, `trend`, `crypto_trend`,
`crypto_voltarget`). Three things vary by asset class:

* **Window length.** An equity week is 5 sessions; a crypto week is **7** UTC
  days, because the crypto accounts trade and snapshot every calendar day.
* **Structural-drift note.** Equity sections keep the dividend-drag note. Crypto
  sections carry a crypto-specific caveat instead: crypto pays no dividends, so
  there is no drag — the structural gap is *timing*, since BTC trades 24/7 while
  both the paper equity snapshot and the shadow's bars are once-daily, so
  weekend and overnight moves land entirely between two marks.
* **Snapshot collapse.** Crypto history is collapsed to the **last snapshot per
  UTC day** before any return is computed (`_last_snapshot_per_day`).

The DIVERGING threshold stays a single portfolio-wide policy number (50 bps)
applied to every account's **weekly aggregate**, crypto included.

**Rationale.** Excluding crypto from the only report that compares paper equity
against expectation left half the paper roster untracked — the crypto accounts
were being traded daily with no divergence gate at all. The three per-class
adjustments are what make the comparison honest rather than merely present: a
5-snapshot window on a 7-day market would label a 5-day span a "week"; the
dividend note is simply false for BTC; and the once-daily collapse is required
because the pre-fix double-runs (see the entry below) left two marks on some
days, which would have compressed a 7-snapshot window into roughly three days
and compared that against a threshold calibrated for a full week.

The equity path is deliberately untouched — same 5-snapshot window, same
dividend note, same numbers — so this change cannot perturb the equity track
record that the readiness gate depends on.

---

## 2026-07-22 — Crypto track-record clock restarts (Quant Lead ruling)

**Decision.** The **crypto** live-readiness clock **restarts at 2026-07-22**.
The readiness ledger therefore carries one independent 90-day clock per asset
class: **`us_equity` from 2026-07-09**, **`crypto` from 2026-07-22**. Crypto
paper history from 2026-07-12 to 2026-07-21 is **retained as diagnostic data
only** — it is still on disk, still rendered in the weekly return series, but it
does **not** count toward the 90-day gate. **Equity records are unaffected** by
this ruling; the equity clock keeps its original 2026-07-09 start.

**Rationale.** The pre-fix crypto history is contaminated by the double-runs
described in the entry below. Those leaked 10:00 ET runs were **not** dry runs —
they submitted real paper orders (e.g. `crypto_voltarget` submitted an order on
both its 00:30 UTC and its 14:00 UTC run on 2026-07-21) — so the affected days
carry rebalances at a second daily timestamp that the once-daily shadow does not
model. A track record whose turnover and mark timing do not match the policy
being evaluated cannot support a live-readiness decision, and the honest remedy
for a contaminated window is to restart the clock rather than to quietly average
the contamination away. Retaining rather than deleting the old history keeps the
contamination auditable.

Implementation: `_TRACK_START_FLOOR` in `reporting/weekly.py` floors the crypto
clock at 2026-07-22. The floored clock renders a `start_note` recording that the
clock was restarted by ruling and that the earlier history does not count, so the
restart is visible in every weekly report rather than buried in code.

---

## 2026-07-22 — Equity scheduled task leaked into the crypto accounts

**Decision.** The `quantlab-paper-run` scheduled task runs
`paper run-all **--asset-class us_equity** --submit`. The flag is load-bearing
and must never be dropped.

**Diagnosis.** `paper run-all` defaults to `--asset-class all`, which iterates
every entry in `APPROVED_STRATEGIES`. When the crypto sleeve added
`crypto_trend` and `crypto_voltarget` to that tuple, the pre-existing 10:00 ET
equity task silently widened to cover them as well — while the separate
`quantlab-crypto-paper-run` task at 20:30 local was already running them. The
crypto accounts were therefore run **twice a day** on weekdays. The evidence is
in the artifacts: `data/equity_history_crypto_*.parquet` carries two snapshots on
each affected weekday (one at ~00:30/05:00 UTC from the crypto task, one at
14:00 UTC = 10:00 ET from the equity task), and `reports/paper/` holds a matching
pair of non-dry-run reports per day, several with orders submitted on both.

**Rationale.** The default of `all` is right for an interactive
`paper run-all` — an operator asking to run everything means everything. The
defect was that a *scheduled* task inherited a default that changed meaning when
the roster grew. Pinning the asset class in the task definition makes each task's
scope explicit and immune to future roster additions; the crypto sleeve's own
task is likewise pinned to `--asset-class crypto`. The load-bearing nature of the
flag is documented in `scheduling/tasks.py` so it survives the next edit.

---

## 2026-07-11 — Crypto sleeve: strategies, accounts, and schedule

**Decision.** Add a crypto sleeve alongside the equity roster, kept structurally
separate at every layer rather than merged into the equity path:

* **Strategies.** `CryptoTrendBTC` (Faber 10-month SMA on BTC-USD, **no safe
  asset** — below the SMA is 100% cash) and `CryptoVolTargetBTC` (20% target vol,
  20-day realized window, weight capped at 1.0). Both annualize on a **365-day**
  grid. Parameters are literature/convention-fixed under the iron rule.
* **Accounts.** Two further dedicated, fully isolated Alpaca paper accounts,
  `crypto_trend` and `crypto_voltarget`, each with its own key pair and its own
  `equity_history_{label}.parquet` / `risk_state_{label}.json` namespace. Both
  were appended to `APPROVED_STRATEGIES` after passing the walk-forward +
  perturbation + bootstrap battery on 2026-07-11.
* **Calendar and data.** A `CryptoCalendar` emitting every UTC day (not NYSE
  sessions), Coinbase as the crypto price source, and a separate
  `config/crypto_universe.yaml` so crypto symbols can never leak into the equity
  ingest/validate/paper symbol set.
* **Risk.** A separate `config/crypto_risk.yaml` calibrated to crypto volatility
  (15% daily HALT, 25% weekly HALT, 50% drawdown KILL) — the equity
  `config/risk.yaml` is left untouched and the runner selects the file by the
  account's asset class.
* **Schedule.** A separate `quantlab-crypto-paper-run` task, `/SC DAILY` (all 7
  days) at 20:30 local, distinct from the three equity task definitions.

**Rationale.** Crypto differs from the equity sleeve in the three things that
drive nearly all of this codebase's logic — the calendar (24/7 vs NYSE), the
volatility regime (hence the risk limits), and the data source. Sharing one code
path and branching internally on asset class would have put crypto-shaped edge
cases inside the equity trading path, which is the one path with a real track
record. Separate config files, a separate calendar, separate accounts, and a
separate scheduled task mean a crypto change cannot regress equities. The cost of
that separation is that shared reports must be taught about asset classes one at
a time — the asset-class leak and the weekly-coverage gap above are both
instances of exactly that cost.

---

## 2026-07-10 — Version stamping on every report

**Decision.** Introduce a single `__version__` ("1.0.0") and embed
`version + git short hash` in every digest and weekly-review header.

**Rationale.** Generated reports drive operational decisions (including the
eventual live-readiness call). Every artifact must be traceable to the exact
commit that produced it, so a report can never be silently attributed to the
wrong code. The hash is computed at render time and degrades cleanly to the bare
version when git is unavailable.

---

## 2026-07-09 — Dividend-drag expectation in shadow tracking

**Decision.** The weekly review compares paper equity to a **shadow** return
series and *expects* paper to lag the shadow over time; the gap is annotated as
dividend drag rather than alarmed on.

**Rationale.** Alpaca paper does **not** credit cash dividends, while the shadow
uses dividend-adjusted (`adj_close`) returns, which include them. Over long
windows paper therefore trails the shadow by roughly the portfolio's dividend
yield — a *structural* difference, not tracking error. Two further structural
gaps are documented: paper equity is marked ~10:00 ET while the shadow is
close-to-close, and paper fills at ~10:00 vs the shadow's close price add
entry-day noise. The DIVERGING threshold (50 bps) and the dividend-drag note
exist so the review distinguishes expected drift from genuine divergence.

---

## 2026-07-09 — Per-account state isolation

**Decision.** Each approved strategy runs in its **own** Alpaca paper account with
fully isolated state: `data/equity_history_{label}.parquet` and
`data/risk_state_{label}.json`. The runner reads/writes only its own label.

**Rationale.** A KILL in one strategy must never halt another, and equity/risk
histories must not be co-mingled (that would corrupt drawdown and divergence
math). Isolation also mirrors how independent live sleeves would be operated and
keeps a single account's failure contained.

---

## 2026-07-08 — Risk thresholds are live-ops policy, never backtest-tuned

**Decision.** `RiskLimits` (3% daily HALT, 8% weekly HALT, 25% drawdown KILL,
etc.) are set as **operational policy**, chosen independently of any backtest
result, and never adjusted to improve historical performance.

**Rationale.** Tuning risk limits against the backtest would overfit the safety
system to the past and defeat its purpose. Limits express how much loss is
tolerable in live operation — a risk-appetite question, not an optimization
target. They are validated on load (`daily < weekly < kill`) and applied
identically in backtest overlay and paper trading.

---

## 2026-07-08 — Converge-to-target vs rebalance-date semantics

**Decision.** The **backtest** trades only on rebalance dates (month-end weights
take effect at t+1 and then drift). The **paper runner** instead converges toward
the *current* target whenever live drift exceeds `min_trade_frac` (1%), not only
on the rebalance day.

**Rationale.** A live process can miss its month-end run (host down, holiday, late
feed). Converge-to-target lets the next successful run still reach the intended
allocation. Because signals are monthly and only change at month-ends, the two
policies pursue the *same* target and differ only in *when* it is reached; the 1%
band prevents reconvergence churn. The shadow simulation mirrors these exact
semantics so paper-vs-shadow comparisons are apples-to-apples.

---

## 2026-07-07 — Exclude `dualmom` from paper trading

**Decision.** Dual Momentum (`dualmom`) remains available for backtesting and
research but is **excluded** from the paper-trading roster. Approved strategies
are `voltarget` and `trend` only.

**Rationale.** In the validation battery `dualmom` showed a Sharpe of ~**0.60**
and a bootstrap probability of a drawdown worse than −30% of **72.2%**. With a
25% max-drawdown **kill** policy, a strategy expected to breach the kill threshold
the majority of the time is not a viable candidate for capital — it would spend
much of its life in a manual-reset KILL state. This is a **risk** decision
grounded in the tail analysis, not a performance-ranking or data-mining one.

---

## 2026-07-06 — Literature-fixed parameters and the "iron rule"

**Decision.** Every strategy parameter is taken **directly from the source
literature** and never tuned to our data: Faber's 10-month SMA (`trend`),
Antonacci's 12-month lookback (`dualmom`), a conventional 10% target with a
20-day realized window (`voltarget`), 60/40 for the balanced baseline.

**Rationale.** The iron rule — no parameter is ever chosen or adjusted to improve
a backtest metric — is the project's primary defense against overfitting. Fixed,
citable parameters make results honest and reproducible, and make walk-forward /
perturbation analysis meaningful rather than circular.

---

## 2026-07-05 — Custom daily engine over vectorbt

**Decision.** Implement a custom NumPy/pandas daily backtest engine instead of
adopting `vectorbt`.

**Rationale.** `vectorbt`'s numba/numpy version pins conflicted with the rest of
the stack under the project's uv-locked environment, and the engine's needs are
narrow and specific: adj_close returns, a strict one-session signal lag (no
lookahead by construction), weight drift between rebalances, and a turnover cost
model. A ~250-line engine we fully control — and can mirror exactly with a test
oracle — is more maintainable and auditable than fighting a heavyweight
dependency for features we do not use.

---

## 2026-07-04 — 10:00 ET scheduled run time

**Decision.** The daily `paper run-all` fires at **10:00** local (intended ET),
30 minutes after the 09:30 open.

**Rationale.** Starting 30 minutes in sidesteps opening-auction noise and
first-print gaps; a monthly-signal strategy is insensitive to intraday timing, so
any post-open minute is acceptable; and a DAY order placed at 10:00 still has the
full session to fill. The digest runs at 16:45 (after marks settle) and the
weekly review at 17:00 Friday (after that day's digest). schtasks uses the host's
local clock, so the host is assumed to run on Eastern time.
