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

### Custom domain — DNS records Daniel needs to add

**Not configured by this batch, deliberately.** DNS belongs to the domain owner. To serve
Glass Box at `glassbox.monzonautomation.com`, add ONE of the following at whichever
provider hosts `monzonautomation.com`:

**Option A — CNAME (recommended for a subdomain)**

| Type | Name | Value | TTL |
| --- | --- | --- | --- |
| `CNAME` | `glassbox` | `monzonautomation-glassbox.netlify.app.` | 3600 |

**Option B — Netlify DNS** (only if you want Netlify to run the whole zone): point the
apex nameservers at Netlify and add the subdomain in the Netlify UI. This moves *all* DNS
for the domain, including the marketing site's records, so Option A is the smaller change.

After the record resolves:

```bash
netlify domains:add glassbox.monzonautomation.com          # or add it in the UI
```

Netlify then provisions a Let's Encrypt certificate automatically (usually minutes; it
needs the CNAME to resolve first). Two follow-ups once the domain is live:

1. Set `VITE_SITE_URL=https://glassbox.monzonautomation.com` and rebuild, so
   `<link rel="canonical">`, `og:image`, `robots.txt` and `sitemap.xml` all carry the real
   host instead of the `.netlify.app` one.
2. Decide which apex is canonical — the marketing repo's canonical tag currently says
   `danielmonzonautomation.com` while this project links to `monzonautomation.com`. Two
   apexes for one brand split SEO authority. See `docs/brand.md` §6.1.

### Refreshing

Repeat all three steps. The banner's timestamp comes from `manifest.json`, so a stale
snapshot is visible on every screen rather than silently out of date. There is no
automatic refresh, by design: each publication is a deliberate act with a human
reading the sanitization report first.

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
