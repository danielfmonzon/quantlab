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

Vite + React + TypeScript + Tailwind + Recharts. Dark-first. No credentials, no
writes: neither build can place, cancel, or halt anything.

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

The report prints to stdout and is saved to
`frontend/public/snapshot/sanitization-report.txt`. It lists, per pattern, a match
count that must be zero:

* Alpaca account ids (`PA[A-Z0-9]{8,}`)
* any email address
* `APCA-API` / `Authorization` header names
* the first 8 characters of every value in your local `.env`, per key

plus every redaction performed (Windows user paths and POSIX home directories →
`<path>`).

The report is safe to share: it records pattern names, counts and file locations, never
the matched text. If `.env` is missing it says **NOT CHECKED** rather than reporting a
vacuous pass.

> **Deploy is gated on the Quant Lead reading this report.** A PASS from the tool is
> necessary, not sufficient — the tool only knows the patterns it was told about.

### 3. Build and deploy

```bash
cd frontend
npm run build:public               # tsc -b && vite build --mode public
netlify deploy --prod              # publish dist/
```

`--mode public` loads `.env.public`, which sets `VITE_DATA_MODE=snapshot`. `netlify.toml`
sets the same variable, so a Netlify-triggered build cannot accidentally ship live mode
(which on a static host would render every screen as a fetch error).

`public/snapshot/` is copied verbatim into `dist/` by Vite, so the captured JSON ships
with the bundle.

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
| `/` | Story | What this is, in plain language |
| `/live` | Live State | What each account holds right now |
| `/decisions` | Every Decision | Each rebalance, and the rule behind it |
| `/tracking` | Paper vs Shadow | Did it do what its rules said? |
| `/limits` | Risk Limits | How far from the brakes |
| `/equity` | Equity Curve | The curve, and how each point was taken |
| `/ledger` | Full Ledger | Everything, in order |
| `/ignores` | What It Ignores | The inputs it deliberately refuses |

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

**Placeholder copy.** `src/content/copy.ts` holds every user-facing sentence on the
Story screen, the nav labels/subtitles, and the footer disclaimer. The G1 brief
specified these by reference to documents (F4 / F2 / F15) that are not in this
repository, so the current text is **authored placeholder**, flagged in the UI and
gated behind `PLACEHOLDER_*` flags. Replace the constants and clear the flags before
any public deploy; the tests assert structure and the `{N}` substitution, not exact
wording, so canonical text drops in without touching a component.

**`og:image` is a placeholder slot.** `index.html` points at `/og-image.png`, which does
not exist yet — share cards degrade to text until a 1200×630 image is added at
`public/og-image.png`.
