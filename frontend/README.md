# Glass Box frontend

A read-only view over the nine `/api/*` endpoints in `src/quantlab/glassbox`. It
holds no credentials, sends no writes, and cannot place, cancel, or halt anything —
every screen is a rendering of a file that the trading and reporting paths wrote.

Vite + React + TypeScript + Tailwind + Recharts. Dark-first.

## Build

```bash
cd frontend
npm install
npm run build      # tsc -b && vite build  ->  frontend/dist/
```

Then start the API:

```bash
quantlab glassbox serve            # http://127.0.0.1:8600
```

`quantlab glassbox serve` mounts `frontend/dist` at `/` **when the build exists**.
With no build, the API keeps serving normally and `/` returns a plain-text message
explaining how to produce one — a missing view never takes the data down with it.

Localhost only. The bind host is hardcoded in `glassbox/serve.py`; exposing this
beyond loopback, and the authentication that would have to come with it, is a later
explicit decision.

## Develop

```bash
quantlab glassbox serve            # terminal 1 — the API on :8600
npm run dev                        # terminal 2 — Vite on :5173, /api proxied to :8600
```

## Test

```bash
npm test           # vitest, jsdom, testing-library
npm run lint       # tsc -b --noEmit
```

Every screen is tested twice: against fixture API responses, and against the empty
responses a repo with no artifacts returns. The empty pass is the one that matters —
a blank panel is the failure mode this app exists to avoid.

## Screens

| Route         | What it answers |
| ------------- | --------------- |
| `/`           | Overview — equity, mark provenance, risk state, tier, readiness clock, what changed today |
| `/runs`       | Every rebalance, with a template-bound narration whose numbers are hoverable to their JSON source path |
| `/divergence` | Paper vs shadow per week, thresholds, excluded days, and published-vs-corrected pairs |
| `/risk`       | Distance to the kill threshold, captioned with the literal answer to "should I be worried?" |
| `/equity`     | The curve, coloured by whether each mark fired on schedule |
| `/ledger`     | Orders, alerts, verdicts, and decisions in one filterable stream |
| `/glass`      | What the system reads, and what it deliberately refuses to read |

## Two conventions worth knowing

**No chart without a takeaway.** `<Chart>` requires `takeaway`, `mechanics`, and
`rawHref` as non-optional props, so a chart with no stated conclusion fails
`tsc -b` and cannot ship. Emptiness is caught at render time by
`assertChartContract`, since the type system cannot see an empty string.

**DIVERGING is amber, not red.** A diverging week is a question — the one case on
record turned out to be a measurement artifact, not a trading fault. Red is reserved
for a live kill switch, which is the only state that actually stops trading.
