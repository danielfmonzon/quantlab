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
netlify deploy --prod --dir=dist                  # publish
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

### Live site

**https://monzonautomation-glassbox.netlify.app**

Netlify project `monzonautomation-glassbox` (site id `be63f48c-4949-4603-b8dd-a6ccfdd996e7`).
HTTPS, HSTS, and the `netlify.toml` security headers are active; asset compression and
immutable caching of `/assets/*` are handled by Netlify's CDN.

### Refreshing

Repeat all three steps. The banner's timestamp comes from `manifest.json`, so a stale
snapshot is visible on every screen rather than silently out of date. There is no
automatic refresh, by design: each publication is a deliberate act with a human
reading the sanitization report first.

## DNS runbook — both sites

**Not configured by this batch, deliberately.** DNS belongs to the domain owner. This
section is the complete set of steps; nothing here has been applied.

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

> **Separate finding, worth acting on independently of any DNS work below.** As of
> 2026-07-26 this domain publishes **no SPF record, no DMARC record and no DKIM key**
> (`_dmarc` and `google._domainkey` both resolve to nothing). Mail is being *delivered*,
> so nothing looks broken, but the domain is currently unauthenticated: anyone can send
> mail that appears to come from it, and Gmail/Outlook may increasingly send legitimate
> mail from it to spam. Adding SPF, then DKIM from the Workspace admin console, then a
> `p=none` DMARC record to observe before enforcing, is the fix. That is a mail task, not
> a hosting task, and it is out of scope for this batch — but it is the reason the warning
> above says "MX/TXT" rather than the fuller record set you would expect to protect.

### Site 1 — Glass Box (this project) at `glassbox.<apex>`

Netlify project `monzonautomation-glassbox`. A subdomain, so a plain `CNAME` is all it
needs:

| Type | Name | Value | TTL |
| --- | --- | --- | --- |
| `CNAME` | `glassbox` | `monzonautomation-glassbox.netlify.app.` | 3600 |

Then, in the Netlify UI: **Site configuration → Domain management → Add a domain** →
`glassbox.danielmonzonautomation.com` → Verify. Or:

```bash
netlify domains:add glassbox.danielmonzonautomation.com
```

Netlify issues a Let's Encrypt certificate automatically once the CNAME resolves (usually
minutes). Because the zone is already on Netlify DNS, adding the domain in the UI may
create the record for you — check the DNS panel first and do not add a duplicate.

**One follow-up, required for correctness rather than cosmetics:** set
`VITE_SITE_URL=https://glassbox.danielmonzonautomation.com` and rebuild, so
`<link rel="canonical">`, `og:image`, `robots.txt` and `sitemap.xml` carry the real host.
Until that rebuild, the deployed pages declare the `.netlify.app` host as canonical, which
tells search engines to index the wrong hostname.

### Site 2 — the marketing site

**Already live and needs nothing.** `https://danielmonzonautomation.com` is served by
Netlify project `danielmonzon` from `github.com/danielfmonzon/dma-website`, with the apex
and `www` both resolving and `www` 301-ing to the apex. There is also a
`dmonzon-staging` site building from the same repo.

The records are in place already, recorded here so a future reader can recognise them
rather than "fix" them:

| Type | Name | Value | Note |
| --- | --- | --- | --- |
| `A` | `@` | `18.208.88.157`, `98.84.224.111` | Netlify load balancers, managed by Netlify DNS |
| `A` | `www` | same pair | 301s to the apex |
| `MX` | `@` | `1 smtp.google.com` | **live mail — do not touch** |

Netlify DNS handles the apex itself, which is why there are `A` records and no `ALIAS`.
**If the zone is ever moved to a provider that is not Netlify**, an apex cannot be a
`CNAME` (DNS forbids `CNAME` at a zone apex), so it would need that provider's
`ALIAS`/`ANAME`/flattened-`CNAME` record type pointed at `<site>.netlify.app` — and if the
provider offers none, Netlify's documented apex `A` target. Do not hardcode the two IPs
above into a new provider: they are Netlify infrastructure and can change.

### Moving to the `monzonautomation.com` apex

The shorter apex the copy used to link to **is not registered** — `monzonautomation.com`
returns `NXDOMAIN`, so it is not a configuration gap but an unowned name. Two apexes for
one brand also split SEO authority (`docs/brand.md` §6.1). If Daniel wants it, in order:

1. Register `monzonautomation.com`.
2. Add it to the **existing** `danielmonzon` Netlify site as a domain alias — not a new
   site. Two sites serving identical content from one repo compete with each other for
   search ranking and give two URLs to keep in sync.
3. Decide which apex is canonical and 301 the other to it. The repo's `<link
   rel="canonical">` currently names `danielmonzonautomation.com`; whichever apex loses
   must redirect, not merely coexist.
4. Flip `MONZONAUTOMATION_URL` in `src/content/copy.ts` — one line, and the CTA, the
   footer link and the attribution all follow.
5. Repeat step 1's mail check. Registering a second domain does not affect the first
   domain's mail, but step 2 involves the live site, so verify anyway.

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
