/**
 * ⚠ PLACEHOLDER COPY — NOT F4 / F2 / F15 CANONICAL TEXT.
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * The G1 brief specified this screen's prose by reference:
 *
 *   • the Story hero and its three sections "EXACTLY as the Quant Lead's audit
 *     copy specifies (F4)"
 *   • nav renames and teaching subtitles "per F2"
 *   • the footer disclaimer "F15 ... verbatim"
 *
 * None of those documents exists in this repository or its git history (searched
 * `docs/`, `reports/`, both READMEs, and every commit). Text cannot be reproduced
 * verbatim from a source that is not present, and a public-facing legal disclaimer
 * is the last place to invent plausible-looking wording — so everything below is
 * PLACEHOLDER, authored here and clearly marked as such.
 *
 * WHAT TO DO BEFORE ANY PUBLIC DEPLOY
 *   1. Replace the marked constants with the canonical F4 / F2 / F15 text.
 *   2. Delete the `PLACEHOLDER_*` flags below.
 *   3. `npm test` — the copy tests assert structure and the {N} substitution, not
 *      exact wording, so canonical text drops in without touching a component.
 *
 * Every consumer imports from this module only. Swapping the copy is a one-file
 * edit; no screen or component contains a hardcoded sentence.
 */

/** Set false once canonical text lands. Surfaced in the UI so it cannot ship unnoticed. */
export const PLACEHOLDER_STORY_COPY = true
export const PLACEHOLDER_DISCLAIMER = true
export const PLACEHOLDER_NAV_COPY = true

/** Token replaced with the paper-tracking day count from the equity clock. */
export const DAY_COUNT_TOKEN = '{N}'

// --------------------------------------------------------------------------- //
// Story — hero                                                                //
// --------------------------------------------------------------------------- //

export const STORY_HERO = {
  eyebrow: 'quantlab · paper trading only',
  // ⚠ PLACEHOLDER — awaiting F4 audit copy.
  headline: 'A trading system that shows its work.',
  // ⚠ PLACEHOLDER — awaiting F4 audit copy. {N} is substituted at render.
  subhead:
    `Every position, every order, and every rule that produced them — published for ` +
    `${DAY_COUNT_TOKEN} days of paper trading, with the arithmetic left in so you can ` +
    `check it.`,
  // ⚠ PLACEHOLDER — awaiting F4 audit copy.
  standfirst:
    'No capital is at risk. Nothing here is a recommendation. What follows is a record ' +
    'of what an automated system actually did, and the evidence for each claim it makes ' +
    'about itself.',
} as const

// --------------------------------------------------------------------------- //
// Story — the three sections                                                  //
// --------------------------------------------------------------------------- //

export interface StorySection {
  id: string
  eyebrow: string
  title: string
  body: readonly string[]
  /** Optional call-through to the screen that carries the underlying evidence. */
  link?: { to: string; label: string }
}

/** ⚠ PLACEHOLDER — three sections, awaiting F4 audit copy for exact wording. */
export const STORY_SECTIONS: readonly StorySection[] = [
  {
    id: 'what-it-does',
    eyebrow: 'one',
    title: 'What it does',
    body: [
      `Two pre-registered strategies trade a small set of broad-market ETFs, and two ` +
        `more trade Bitcoin. Each reads one thing: settled daily closing prices. A ` +
        `trend rule holds an asset while its price sits above a long moving average; a ` +
        `volatility rule sizes each position so its recent realised volatility lands on ` +
        `a fixed target.`,
      `The parameters come from published literature and are never tuned against ` +
        `results. Rebalances happen monthly, on a schedule, without discretion.`,
    ],
    link: { to: '/decisions', label: 'See every rebalance, and why' },
  },
  {
    id: 'what-it-knows',
    eyebrow: 'two',
    title: 'What it knows, and what it refuses to know',
    body: [
      `It reads two independently cross-checked end-of-day price feeds, its own broker ` +
        `account state, and a market calendar. That is the whole input list.`,
      `It reads no news, no earnings, no analyst ratings, no sentiment, no intraday ` +
        `prices, and no language-model opinion about the market. When this site explains ` +
        `a trade, the explanation is assembled from the numbers in that trade's own ` +
        `record — never from a story about why the market moved.`,
    ],
    link: { to: '/ignores', label: 'The full list of refusals' },
  },
  {
    id: 'what-it-has-not-proven',
    eyebrow: 'three',
    title: "What it hasn't proven yet",
    body: [
      `${DAY_COUNT_TOKEN} days of paper tracking is not a track record. Every account ` +
        `on this site is rated Probable, not Proven: the validation battery is on ` +
        `record, but the 90-day live-tracking gate has not been passed, and no account ` +
        `can be upgraded before it is.`,
      `Where a published figure later turned out to be wrong, both the original and the ` +
        `correction are shown side by side, with the ruling that connects them. That ` +
        `pairing is the point — a number you can only see after it was fixed is a number ` +
        `you cannot audit.`,
    ],
    link: { to: '/tracking', label: 'Paper against its shadow' },
  },
] as const

// --------------------------------------------------------------------------- //
// Footer                                                                      //
// --------------------------------------------------------------------------- //

/** ⚠ PLACEHOLDER — NOT the F15 disclaimer. Replace with canonical text verbatim. */
export const DISCLAIMER =
  'This site documents a personal research project that trades a simulated (paper) ' +
  'brokerage account. No real capital is deployed and no real orders are placed. ' +
  'Nothing here is investment advice, a recommendation, an offer, or a solicitation ' +
  'to buy or sell any security. Past or simulated performance does not indicate future ' +
  'results, and simulated results carry inherent limitations — they benefit from ' +
  'hindsight and bear none of the execution risk, liquidity constraints, or emotional ' +
  'pressure of live trading. Figures are captured manually and may be out of date. ' +
  'The author is not a registered investment adviser or broker-dealer.'

export const BUILT_BY = {
  name: 'Daniel Monzon',
  prefix: 'Built by',
  // Placeholder hrefs. `#` deliberately, so a dead link is visible rather than
  // silently pointing somewhere wrong.
  links: [
    { label: 'GitHub', href: '#' },
    { label: 'LinkedIn', href: '#' },
    { label: 'Contact', href: '#' },
  ],
} as const

// --------------------------------------------------------------------------- //
// Navigation — labels and teaching subtitles                                  //
// --------------------------------------------------------------------------- //

export interface NavCopy {
  label: string
  /** ⚠ PLACEHOLDER teaching subtitle — awaiting F2. One line, plain language. */
  subtitle: string
  /** Per-route document title and meta description (ITEM 5 head manager). */
  title: string
  description: string
}

/** ⚠ PLACEHOLDER — nav names and subtitles, awaiting the F2 rename table. */
export const NAV_COPY: Record<string, NavCopy> = {
  '/': {
    label: 'Story',
    subtitle: 'What this is, in plain language',
    title: 'quantlab — a trading system that shows its work',
    description:
      'A paper-trading research system published with its arithmetic left in: every ' +
      'position, order, and rule, with the evidence for each claim.',
  },
  '/live': {
    label: 'Live State',
    subtitle: 'What each account holds right now',
    title: 'Live State — quantlab Glass Box',
    description:
      'Current paper equity, mark provenance, risk state, validation tier, and the ' +
      '90-day readiness clock for every account.',
  },
  '/decisions': {
    label: 'Every Decision',
    subtitle: 'Each rebalance, and the rule behind it',
    title: 'Every Decision — quantlab Glass Box',
    description:
      'Every paper rebalance with its stage checklist, the rule that produced it, and ' +
      'the branch the rule did not take. Each number traces to its source field.',
  },
  '/tracking': {
    label: 'Paper vs Shadow',
    subtitle: 'Did it do what its rules said?',
    title: 'Paper vs Shadow — quantlab Glass Box',
    description:
      'Weekly divergence between what the paper account earned and what its own rules ' +
      'should have earned, against a fixed threshold.',
  },
  '/limits': {
    label: 'Risk Limits',
    subtitle: 'How far from the brakes',
    title: 'Risk Limits — quantlab Glass Box',
    description:
      'Distance from each account’s current drawdown to the kill threshold that ' +
      'would stop it trading, read from the same config the risk engine uses.',
  },
  '/equity': {
    label: 'Equity Curve',
    subtitle: 'The curve, and how each point was taken',
    title: 'Equity Curve — quantlab Glass Box',
    description:
      'Paper equity per account, with every mark coloured by whether it fired on ' +
      'schedule, late, or from a leaked task.',
  },
  '/ledger': {
    label: 'Full Ledger',
    subtitle: 'Everything, in order',
    title: 'Full Ledger — quantlab Glass Box',
    description:
      'Orders, alerts, weekly verdicts, and design decisions merged into one ' +
      'chronological stream.',
  },
  '/ignores': {
    label: 'What It Ignores',
    subtitle: 'The inputs it deliberately refuses',
    title: 'What It Ignores — quantlab Glass Box',
    description:
      'The complete list of what this system reads, and the seven categories of input ' +
      'it deliberately does not — including any model opinion about the market.',
  },
}

/** Substitute the day-count token. Used by Story and by the hero subhead. */
export const withDayCount = (text: string, days: number | null): string =>
  text.split(DAY_COUNT_TOKEN).join(days === null ? '—' : String(days))
