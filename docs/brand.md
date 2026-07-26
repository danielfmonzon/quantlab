# MonzonAutomation brand — extracted findings and the Glass Box token set

**Sources read (2026-07-26).**

* `danielfmonzon/dma-website` (private, cloned via authenticated `gh`) — the source of
  truth. `src/styles/global.css` carries the full token block; `src/layouts/BaseLayout.astro`
  the font loading; `src/pages/index.astro` and `src/components/Footer.astro` the voice.
* `https://monzonautomation.com` — **did not resolve** (`getaddrinfo ETIMEOUT`). Findings
  below therefore come from the repository, which is upstream of the site anyway. See
  *Discrepancies* for what that gap leaves unverified.

The brand is **not thin and not inconsistent**. It is a deliberate, coherent system with
named tokens, an optical-size-aware display face, and a distinctive voice. Glass Box
adopts it rather than proposing a replacement. Two narrow additions and one open question
are listed at the end.

---

## 1. Colour

A warm, light system: bone-cream grounds, espresso ink, deep forest green as the single
primary, honey/clay as warm accents.

| token | hex | role (verbatim from `global.css` where quoted) |
| --- | --- | --- |
| `--cream` | `#f7f2e9` | "page background, warm bone" |
| `--cream-2` | `#fffdf8` | "cards / raised" |
| `--cream-3` | `#efe7d6` | "alt sections" |
| `--cream-4` | `#e6dcc7` | "deeper panel edges" |
| `--ink` | `#221f18` | "primary text, warm espresso" |
| `--ink-2` | `#4f4a3e` | "secondary text" |
| `--muted` | `#645f4e` | "tertiary / captions — AA ≥4.5 on cream/cream-2/cream-3" |
| `--line` | `rgba(34,31,24,0.10)` | hairlines |
| `--line-2` | `rgba(34,31,24,0.16)` | stronger hairlines |
| `--green` | `#1e5141` | "primary brand" |
| `--green-2` | `#2c6b55` | "hover / gradient" |
| `--green-deep` | `#163b30` | "deep panels" |
| `--green-tint` | `rgba(30,81,65,0.07)` | wash |
| `--honey` | `#d49a4e` | "warm accent (decorative)" |
| `--honey-2` | `#e8bd7c` | lighter honey |
| `--clay` | `#8f5113` | "warm accent TEXT (readable)" |

**The honey/clay split is the most important thing in this table.** The brand already
separates a decorative warm accent (`--honey`, too light for text on cream) from a
readable one (`--clay`). Glass Box inherits that discipline exactly: honey for fills,
rules and dots; clay for any warm-accent *text*.

The site also layers two atmospheric effects on `body`: soft radial glows (honey at top
right, green at top left) and a faint multiply-blended SVG grain at 40% opacity.

## 2. Typography

```
--f-display: "Fraunces Variable", Georgia, serif
--f-body:    "Hanken Grotesk Variable", system-ui, -apple-system, sans-serif
```

* **Self-hosted via Fontsource** — `@fontsource-variable/fraunces` (standard + italic) and
  `@fontsource-variable/hanken-grotesk`. No Google Fonts request. This matters for Glass
  Box: its CSP is `default-src 'self'`, so a hosted-font brand would have forced either a
  CSP hole or a font substitution. It forces neither.
* Fraunces is loaded on its **`opsz` + `wght`** axes with `font-optical-sizing: auto`, so
  display sizes get the intended optical treatment.
* Headings: display serif, weight 600, `line-height: 1.05`, `letter-spacing: -0.02em`.
  `h1: clamp(2.55rem, 6.2vw, 4.6rem)`.
* Body: `line-height: 1.62`, `letter-spacing: -0.006em`.
* `.lead` is capped at **58ch** — a measure discipline Glass Box copies.
* `.eyebrow`: body face, 0.74rem, weight 700, `letter-spacing: .18em`, uppercase, coloured
  `--clay`, preceded by a 24×2px honey rule.

## 3. Logo and wordmark

No image asset — the mark is **typographic**:

* wordmark in the display serif, weight 600, ~1.2rem, `letter-spacing: -0.02em`;
* an 11px honey **dot** to its left with a `0 0 0 4px rgba(212,154,78,.22)` glow ring;
* an optional `<small>` beneath: body face, 0.6rem, weight 600, `letter-spacing: .16em`,
  uppercase, `--muted`.

Glass Box reproduces this as `<BrandMark />` — same dot, same ring, same serif wordmark,
with "GLASS BOX" as the tracked sub-line.

## 4. Voice

Read from the homepage and footer. Characteristics, with evidence:

* **First person singular, and proud of it.** "I fix both — pick whichever's costing you
  more right now." "Built, launched, and maintained by me." "I'm not that. I'm an engineer
  who builds each system by hand and runs it myself."
* **Concrete over abstract.** Not "increase conversion" but "turn a visitor into a booked
  job while you're out on the truck."
* **Anti-hype; honesty framed as the product.** The strongest line on the site is
  *"Yes, it's really an AI — ask it and it'll tell you. That honesty is the product."*
  Glass Box is that sentence generalised into a whole site.
* **Names the failure mode first.** "Most local businesses leak money in the same few
  spots — and none of it shows up on a report." Problem, then mechanism, then proof.
* **Em-dash heavy**, short declaratives, plain words. No exclamation marks. No "revolutionary",
  "cutting-edge", "seamless".

Glass Box's canonical copy matches this register: it opens on the failure mode ("Most
automated systems ask for trust they cannot earn"), stays concrete, and publishes its own
mistakes.

---

## 5. The Glass Box token set

Adopted **unchanged** from the brand: all cream/ink/green/honey/clay values, both
typefaces, the eyebrow treatment, the 58ch measure, the pill buttons, the focus-ring
pattern (`2px solid var(--ink)` + `4px` cream halo).

### 5a. Additions — semantic status colours

Glass Box needs something the marketing site does not: **status semantics on data**
(tracking/diverging/insufficient, on-schedule/catch-up/leaked, halted). The brand has no
tokens for these. Rather than invent a second palette, each is derived from an existing
brand hue and then **darkened until it measures AA on cream**:

| token | hex | derived from | used for |
| --- | --- | --- | --- |
| `signal-ok` | `#1e5141` | `--green` unchanged | TRACKING, on-schedule, not-halted |
| `signal-warn` | `#8f5113` | `--clay` unchanged | DIVERGING, catch-up, placeholder notices |
| `signal-info` | `#1d4e6b` | new — a teal-blue at green's value | leaked marks, links, active nav |
| `signal-danger` | `#8c2f1d` | new — a clay-adjacent red | live KILL only |
| `signal-idle` | `#645f4e` | `--muted` unchanged | captions, unknown values |

`signal-info` and `signal-danger` are the only genuinely new hues. Both are held to the
same rule as `--clay`: dark enough to be *text* on cream, not merely decorative. Measured
ratios for every pair are in the G2 report.

The **amber-not-red** convention survives the port: DIVERGING renders in `signal-warn`
(clay), and `signal-danger` is reserved for a live kill switch. Clay is a warmer, quieter
warning than the previous dark-mode amber, which suits the brand and still reads as
"look at this" rather than "panic".

### 5b. Addition — a mono face

Data tables and JSON source paths need a monospace, which the brand does not specify.
Glass Box uses the **system mono stack** (`ui-monospace, SFMono-Regular, Menlo, monospace`)
rather than shipping a fourth webfont — a tabular-numerals face for figures is worth the
bytes; a *branded* one is not.

### 5c. Deliberate divergence — light, not dark

**Glass Box was dark-first (`#0a0b0d`) before G2. It is now light.** The brand is
unambiguously a warm-light system, and the instruction is that Glass Box must read as a
MonzonAutomation property; a near-black dashboard hanging off a cream marketing site reads
as two companies. The dark theme's justification ("Bloomberg-meets-Linear") was an
aesthetic preference, not a requirement, and it loses to brand coherence.

What was kept from the dark design: density, typographic hierarchy over chrome, motion
only on state transitions, and the three-layer chart contract.

---

## 6. Discrepancies and open questions

These are flagged rather than silently resolved.

1. **Two domains.** The repo's canonical URL is `https://danielmonzonautomation.com/`;
   the G2 brief's CTA target is `https://monzonautomation.com`, and the requested Glass Box
   host is `glassbox.monzonautomation.com`. The brief's domain is used for the CTA as
   specified. **Which domain is canonical needs a decision** — the footer of one property
   linking to a different apex than the other property's canonical tag is the kind of thing
   that quietly splits SEO authority.
2. **"I" vs "we".** The brand voice is emphatically first-person *singular*. The canonical
   Section 5 copy supplied in the brief uses **"We build automation for businesses…"**. It
   is used verbatim as instructed, but it is the one sentence on the site that does not
   sound like the rest of the brand. Worth a second look.
3. **Live site unverified.** `monzonautomation.com` did not resolve from this machine, so
   the *rendered* brand — actual computed colours, any post-build overrides, favicon,
   OG image treatment — is inferred from source rather than observed. If the deployed site
   diverges from the repo, the repo won.
4. **No brand OG image to match.** `dma-website/public/og-image.png` exists but was not
   opened (binary, and its design language cannot be read from bytes). The Glass Box
   `og-image.png` is generated from the token set instead, so it will be *consistent* with
   the brand but not necessarily a *sibling* of the existing card.
5. **No logo file.** The mark is CSS-only in both properties. If a raster/vector logo is
   ever produced, `BrandMark` is the single place Glass Box needs updating.
