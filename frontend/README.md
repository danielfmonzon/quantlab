# Glass Box frontend

One codebase, **two products**:

| | Operational dashboard | Public site |
|---|---|---|
| audience | the operator, on this machine | anyone |
| data | live `/api/*` from `quantlab glassbox serve` | static JSON captured by `quantlab glassbox snapshot` |
| host | `127.0.0.1` only | Netlify (static) |
| build | `npm run build` | `npm run build:public` |
| mode | `VITE_DATA_MODE` unset → `live` | `VITE_DATA_MODE=snapshot` |
| freshness | current as of the request | as of the capture instant, shown in a banner on every screen |

The public site never reaches the machine that trades. It reads flat files, so there
is no route from the internet back to the broker credentials, the artifacts, or the
API — which is the whole reason for the split.

Vite + React + TypeScript + Tailwind + Recharts, on the MonzonAutomation brand system
(warm cream, deep green, honey; Fraunces + Hanken Grotesk, self-hosted). See
`docs/brand.md` for the token extraction and the measured contrast ratios. No
credentials, no writes: neither build can place, cancel, or halt anything.

---

## Operational dashboard (localhost)

```bash
cd frontend
npm install
npm run build          # tsc -b && vite build  ->  frontend/dist/
cd ..
quantlab glassbox serve            # http://127.0.0.1:8600
```

`serve` mounts `frontend/dist` at `/` **when the build exists**. With no build the API
keeps serving normally and `/` returns a plain-text message explaining how to produce
one — a missing view never takes the data down with it.

Localhost only. The bind host is hardcoded in `glassbox/serve.py`; exposing it beyond
loopback, and the authentication that would have to come with it, is a later explicit
decision.

### Develop

```bash
quantlab glassbox serve            # terminal 1 — the API on :8600
npm run dev                        # terminal 2 — Vite on :5173, /api proxied to :8600
```

---

## Public site — the deploy ritual

Three steps, in this order. **Step 2 is a human gate, not a formality.**

### 1. Capture a snapshot

```bash
cd ..
quantlab glassbox snapshot --out frontend/public/snapshot/
```

Enumerates every `/api` GET route from the app itself (so a new endpoint is captured
automatically), expands the parameterised narration route over every run on disk,
captures each at full depth, and writes one JSON file per endpoint plus
`manifest.json`. Runs in-process through `TestClient` — no server, no port, no network.

### 2. Read the sanitization report — and get it reviewed

Every byte is redacted and vetted **in memory before anything is written**. If a
forbidden pattern is found, *nothing* is written — not even the files that were clean,
because a partially-written snapshot looks finished.

The report prints to stdout and is saved to `reports/glassbox/sanitization-report.txt`
— **outside** the published tree. It used to be written into the snapshot directory,
which meant it shipped to the public site; it is an internal review document, and it
lists the pattern names the gate searches for, so publishing it was doubly wrong. It
lists, per pattern, a match count that must be zero:

* Alpaca account ids (`PA[A-Z0-9]{8,}`)
* any email address
* Alpaca / broker auth headers **with a value** (`APCA-API-KEY-ID: …`,
  `Authorization: Bearer …`) — the bare header names are prose and no longer trip the
  gate, because this project documents its own security design and that documentation is
  published
* the first 8 characters of every SECRET-BEARING value in your local `.env` — public URLs
  and documented endpoints are excluded by an allowlist and the exclusions are printed,
  because a gate that fires falsely trains its operator to ignore it

plus every redaction performed (Windows user paths and POSIX home directories →
`<path>`).

The report is safe to share: it records pattern names, counts and file locations, never
the matched text. If `.env` is missing it says **NOT CHECKED** rather than reporting a
vacuous pass.

> **Deploy is gated on the Quant Lead reading this report.** A PASS from the tool is
> necessary, not sufficient — the tool only knows the patterns it was told about.

### 3. Build, verify the published bytes, deploy

```bash
cd frontend
npm run build:public                              # tsc -b && vite build --mode public
cd ..
quantlab glassbox verify-dist --dir frontend/dist # gate over EVERY published file
cd frontend
# The site ID is pinned deliberately — see below.
netlify deploy --prod --dir=dist --site=be63f48c-4949-4603-b8dd-a6ccfdd996e7
```

`verify-dist` runs **after** the build, because its scope is the built output: compiled
JS, CSS, HTML, SVG, the copied snapshot, and anything a human dropped into `public/`. A
secret can reach the public through an inlined constant or a stray file without ever
passing through the snapshot writer, so the two gates are not interchangeable. Non-zero
exit means do not deploy.

`--mode public` loads `.env.public`, which sets `VITE_DATA_MODE=snapshot`. `netlify.toml`
sets the same variable, so a Netlify-triggered build cannot accidentally ship live mode
(which on a static host would render every screen as a fetch error).

`public/snapshot/` is copied verbatim into `dist/` by Vite, so the captured JSON ships
with the bundle.

**Why `--site` is pinned.** `.netlify/state.json` holds the site link, and the build
recreates that directory — so the link disappears, and `netlify deploy` responds by opening
an interactive "Link this directory to an existing site?" prompt. In a `&&`-chained deploy
that is worse than an error: the chain stalls on a prompt instead of failing, and in a
non-interactive context it can exit having deployed nothing while looking like it ran.
Passing the ID makes the command independent of local link state.

### Live site

**https://glassbox.danielmonzonautomation.com** — the canonical host.

Also served at `monzonautomation-glassbox.netlify.app`, which is the same deploy. Every
crawler-facing declaration (`<link rel="canonical">`, `og:image`, `robots.txt`,
`sitemap.xml`) names the custom domain, so the `.netlify.app` host is a working alias rather
than a competing URL.

Netlify project `monzonautomation-glassbox` (site id `be63f48c-4949-4603-b8dd-a6ccfdd996e7`).
Force HTTPS is on, so `http://` 301s to `https://`. The TLS certificate is the
Netlify-managed Let's Encrypt **wildcard** for the zone (`*.danielmonzonautomation.com` +
apex) — adding this subdomain needed no new issuance, which is why it was serving HTTPS
within seconds rather than the usual few minutes. HSTS and the `netlify.toml` security
headers are active; asset compression and immutable caching of `/assets/*` come from
Netlify's CDN.

### Refreshing

Repeat all three steps. The banner's timestamp comes from `manifest.json`, so a stale
snapshot is visible on every screen rather than silently out of date. There is no
automatic refresh, by design: each publication is a deliberate act with a human
reading the sanitization report first.

## DNS runbook — both sites

**Applied on 2026-07-26.** The zone is Netlify-hosted, so this was done via the Netlify API
rather than handed over as instructions. `MX` was re-verified before and after every single
change and never differed. Current state:

| What | Record | Status |
| --- | --- | --- |
| Glass Box subdomain | `NETLIFY glassbox → monzonautomation-glassbox.netlify.app` | live, HTTPS forced |
| SPF | `TXT @ v=spf1 include:_spf.google.com ~all` | live |
| DMARC | `TXT _dmarc v=DMARC1; p=none; …` | live, **observe mode** |
| DKIM | `TXT google._domainkey` | **record published 2026-07-27; not yet activated — see below** |
| Mail | `MX 1 smtp.google.com` | **unchanged throughout** |

The DKIM **record is published**; DKIM is not yet **active**. Publishing the key and
switching authentication on are two different actions in two different systems, and only the
first is a DNS task. See the DKIM section below for the one remaining step.

### ⚠️ READ THIS BEFORE TOUCHING THE ZONE — THE DOMAIN CARRIES LIVE EMAIL

`danielmonzonautomation.com` receives real mail through Google Workspace
(`MX 1 smtp.google.com`). **Mail delivery and web hosting share one zone.** A DNS change
made carelessly does not produce a broken page you notice in a browser — it produces mail
that silently stops arriving, and you find out when a client says they never heard back.

Two specific rules:

1. **Do not move the nameservers.** They are already `dns1–dns4.p08.nsone.net` (Netlify
   DNS), and the MX record has been migrated into that zone correctly. Repointing them at
   another provider — a registrar's default set, a new host's "we'll manage DNS for you"
   offer — hands the zone to a nameserver that has never heard of the MX record, and mail
   stops at the moment of the switch. **Add records; never re-delegate.**
2. **Because the zone lives at Netlify, every record edit happens in the Netlify UI**
   (Domains → `danielmonzonautomation.com` → DNS panel), alongside the mail records. Do not
   use a "replace all records" or bulk-import flow. Change one record at a time and leave
   `MX`, `TXT` and anything named `_dmarc` or `*._domainkey` untouched.

Verify mail records are intact **before and after** any change — same output both times:

```bash
nslookup -type=MX  danielmonzonautomation.com 8.8.8.8   # expect: 1 smtp.google.com
nslookup -type=TXT danielmonzonautomation.com 8.8.8.8   # expect: the google-site-verification string
```

### Mail authentication

Before 2026-07-26 this domain published **no SPF, no DMARC and no DKIM** — mail delivered
fine, so nothing looked broken, but the domain was unauthenticated and anyone could send
mail appearing to come from it. Two of the three are now fixed.

**SPF** — `TXT` at the apex:

```
v=spf1 include:_spf.google.com ~all
```

A domain must have **exactly one** `v=spf1` record; two is a permanent error that fails SPF
outright rather than merging. This was checked immediately before creating it. `~all`
(softfail) rather than `-all` (hardfail) is deliberate: until DKIM and DMARC reports confirm
every legitimate sender is covered, a hardfail can bounce real mail from a service nobody
remembered was sending on the domain's behalf.

Note the apex now holds **two** `TXT` records — SPF and the Google site-verification string.
That is correct and normal; multiple `TXT` records at one name are fine, and only one of them
may contain `v=spf1`.

**DMARC** — `TXT` at `_dmarc`:

```
v=DMARC1; p=none; rua=mailto:danielmonzonautomation@gmail.com; fo=1
```

`p=none` is **observe mode and must stay that way for now.** It changes nothing about
delivery; it only asks receivers to send aggregate reports to `rua`. `fo=1` requests failure
reports on any authentication problem. Do **not** move to `p=quarantine` or `p=reject` until
the reports have arrived and been read: enforcement before observation is how a domain
blackholes its own newsletters, invoicing, or form notifications. Reports begin arriving
within ~24–72 hours as XML attachments.

#### DKIM — four parts, two done

DKIM spans two systems, and it is worth naming the parts so nobody assumes a published key
means a working signature:

| Part | What | Who | Status |
| --- | --- | --- | --- |
| A | Generate the 2048-bit key in Workspace Admin | Daniel | done |
| B | Publish the `TXT` at `google._domainkey` in Netlify DNS | this repo | **done 2026-07-27** |
| C | Click **Start authentication** in Workspace Admin | **Daniel** | **outstanding** |
| D | Confirm signatures appear on outbound mail | Daniel | after C |

**Part B, for the record.** `TXT google._domainkey.danielmonzonautomation.com`, TTL 3600,
created additively via `createDnsRecord`. The published value was verified
character-for-character against the key from Workspace — reassembled from its two DNS
character-strings and compared by SHA-256, not by eye — and parsed to confirm it decodes to a
294-byte SPKI holding a 2048-bit RSA key with exponent 65537. All four authoritative
nameservers serve it and it has propagated to public resolvers. `MX` was verified before and
after and did not change.

**Part C is the step that actually turns DKIM on, and it is still not done.**

1. Sign in to **https://admin.google.com** as a Workspace **super administrator**.
2. Left menu → **Apps** → **Google Workspace** → **Gmail**.
3. Open **Authenticate email** (on some versions: *Settings* → *Authenticate email*).
4. In the domain selector, choose **danielmonzonautomation.com**.
5. Click **Start authentication**. The status must then read *Authenticating email*.

Do **not** click *Generate new record* again. A second generation replaces the key Google
will sign with, and the record published in Part B would instantly become the wrong one —
silently, since mail keeps flowing unsigned. If the page offers only *Generate new record*
and no *Start authentication*, stop and re-read the DNS record first rather than regenerating.

Why this ordering matters: publishing a key does nothing on its own. Until Part C, outbound
mail carries no DKIM signature at all, and the only visible symptom is an absence — which is
exactly the failure mode that let this domain run without SPF, DKIM or DMARC for as long as
it did.

**Verify after Part C** — DNS says the key is published; only a real message proves it signs:

```bash
# The published key (should already pass — this is Part B, done):
nslookup -type=TXT google._domainkey.danielmonzonautomation.com 8.8.8.8
```

Then send a message to a Gmail address, open it, **Show original**, and confirm
`DKIM: 'PASS' with domain danielmonzonautomation.com`. That line, not the DNS lookup, is
what closes Part D.

Once DKIM has been live and passing for a couple of weeks and the DMARC reports show only
expected senders, `p=none` can be raised to `p=quarantine`. That is a separate, deliberate
decision, not a follow-up to this batch.

### Site 1 — Glass Box (this project) at `glassbox.<apex>`

**Done — live at https://glassbox.danielmonzonautomation.com.** Netlify project
`monzonautomation-glassbox`.

| Type | Name | Value | Managed by |
| --- | --- | --- | --- |
| `NETLIFY` | `glassbox` | `monzonautomation-glassbox.netlify.app` | Netlify (auto-created) |

**A note on the record type, because it is a trap.** The obvious instrument for a subdomain
is a `CNAME`, and that is what a runbook written against generic DNS advice would tell you to
add. On a *Netlify-hosted* zone it is the wrong one. Attaching the domain to the site makes
Netlify create its own `NETLIFY`-type record — the same mechanism already serving the apex and
`www` — so adding a `CNAME` first leaves **two records for one hostname**. That is not merely
untidy: RFC 1034 forbids a `CNAME` coexisting with other data at the same name, and the
resolver silently ignored the `CNAME` in favour of the managed record. The redundant `CNAME`
was deleted; only the managed record remains.

So the correct procedure on this zone is **attach the domain and let Netlify write the
record**:

```bash
# Site configuration → Domain management → Add a domain, or:
netlify api updateSite --data '{"site_id":"be63f48c-4949-4603-b8dd-a6ccfdd996e7",
  "body":{"custom_domain":"glassbox.danielmonzonautomation.com"}}'
```

Add a `CNAME` by hand **only** if the zone is ever moved off Netlify DNS.

HTTPS was serving within seconds, not the usual few minutes, because the zone already has a
Netlify-managed Let's Encrypt **wildcard** certificate (`*.danielmonzonautomation.com` +
apex) — a new subdomain needs no new issuance. Force HTTPS is enabled, so `http://` 301s.

Canonical host is wired in code, not left to a per-deploy env var: `SITE_URL_DEFAULT` in
`vite.config.ts` and `VITE_SITE_URL` in `netlify.toml` both name
`https://glassbox.danielmonzonautomation.com`. A build that forgot an env var would otherwise
succeed while declaring the `.netlify.app` host canonical, and nothing downstream would fail.

### Site 2 — the marketing site

**Already live and needs nothing.** `https://danielmonzonautomation.com` is served by
Netlify project `danielmonzon` from `github.com/danielfmonzon/dma-website`, with the apex
and `www` both resolving and `www` 301-ing to the apex. There is also a
`dmonzon-staging` site building from the same repo.

The records are in place already, recorded here so a future reader can recognise them
rather than "fix" them:

| Type | Name | Value | Note |
| --- | --- | --- | --- |
| `NETLIFY` | `@` | `danielmonzon.netlify.app` | Netlify-managed apex alias |
| `NETLIFY` | `www` | `danielmonzon.netlify.app` | 301s to the apex |
| `MX` | `@` | `1 smtp.google.com` | **live mail — do not touch** |
| `CNAME` | `72184824` | `google.com` | Google Workspace domain verification — leave it |

`NETLIFY` is a provider-specific pseudo-record, not a standard type: it resolves to Netlify's
load-balancer addresses and is how Netlify aliases an apex, which plain DNS cannot do with a
`CNAME`. It resolves to `A` records when queried (currently `18.208.88.157` /
`98.84.224.111`) — **do not copy those IPs anywhere.** They are infrastructure and can change
without notice.

**If the zone is ever moved to a provider that is not Netlify**, the apex cannot be a `CNAME`
(RFC forbids `CNAME` at a zone apex), so it needs that provider's `ALIAS`/`ANAME`/
flattened-`CNAME` type pointed at `<site>.netlify.app`; if the provider offers none, use
Netlify's documented apex `A` target from their current docs rather than whatever the zone
happens to resolve to today. And re-read the mail warning above before doing any of it.

### `monzonautomation.com` — settled, and not being used

**There is one apex, and it is `danielmonzonautomation.com`.** Quant Lead ruling,
2026-07-26: `monzonautomation.com` is not owned and will not be acquired. It was never a
configuration gap — the name returned `NXDOMAIN` because nobody had registered it — and
earlier drafts of this project treated it as a future home, which is why `copy.ts` once
linked there and produced a dead primary CTA.

Nothing further is needed. `MONZONAUTOMATION_URL` in `src/content/copy.ts` already points at
the live apex, and the two-apex discrepancy recorded in `docs/brand.md` §6.1 is closed by
this decision rather than by any DNS work. If some future reader finds a reference to
`monzonautomation.com` anywhere in this repo, it is a leftover and should be deleted, not
implemented.

---

## Test

```bash
npm test           # vitest, jsdom, testing-library
npm run lint       # tsc -b --noEmit
```

Every screen is tested three ways: against fixture API responses, against the *empty*
responses a repo with no artifacts returns, and — for the mode-sensitive paths — through
both transports against the same payloads. The empty pass is the one that matters: a
blank panel is the failure mode this app exists to avoid.

---

## Screens

| Route | Nav name | What it answers |
| --- | --- | --- |
| `/` | Story · what this is | The thesis, in plain language, for a first-time reader |
| `/live` | Live State · the accounts now | What each account holds right now |
| `/decisions` | Decisions · every trade, explained | Each rebalance, and the rule behind it |
| `/tracking` | Tracking · does reality match the math | Paper against its own shadow |
| `/limits` | Limits · the brakes | How far from the kill threshold |
| `/equity` | Equity · the curve, point by point | The curve, with each mark's provenance |
| `/ledger` | Ledger · everything, dated | Orders, alerts, verdicts, and rulings |
| `/ignores` | Refusals · what it won't look at | The inputs it deliberately refuses |

Pre-G1 paths (`/runs`, `/divergence`, `/risk`, `/glass`, `/overview`) redirect to their
new homes — client-side in the app, and as real 301s in `netlify.toml`.

---

## Conventions worth knowing

**No chart without a takeaway.** `<Chart>` requires `takeaway`, `mechanics`, and
`rawHref` as non-optional props, so a chart with no stated conclusion fails `tsc -b`
and cannot ship. Emptiness is caught at render time by `assertChartContract`, since the
type system cannot see an empty string.

**DIVERGING is amber, not red.** A diverging week is a question — the one case on record
turned out to be a measurement artifact, not a trading fault. Red is reserved for a live
kill switch, which is the only state that actually stops trading.

**Copy is canonical.** `src/content/copy.ts` holds every user-facing sentence — the Story
hero and five sections, the nav labels and teaching subtitles, and the footer disclaimer.
The text is the Quant Lead's approved wording, reproduced verbatim; the G1
`PLACEHOLDER_*` flags are gone. `{N}` is substituted from the us_equity readiness clock and
renders an em dash, never a zero, when unknown.

**Glossary terms open on click/focus, never hover.** `<Term>` is a real `<button>` with
`aria-expanded` and `aria-describedby`. Hover-only would make the definitions invisible on
touch and unreachable by keyboard — to the group least likely to need them.

**Contrast is measured, not eyeballed.** `node scripts/contrast.mjs` computes exact WCAG
ratios for every foreground/background pair the UI renders and exits non-zero on an AA
failure. It measures TOKEN pairs, so it cannot see opacity modifiers: `text-clay` is
5.61:1 but `text-clay/70` rendered at 3.1:1 and failed. Opacity is not used on text
anywhere for that reason.

**`og:image` is a placeholder slot.** `index.html` points at `/og-image.png`, which does
not exist yet — share cards degrade to text until a 1200×630 image is added at
`public/og-image.png`.
