/**
 * Canonical copy. Every user-facing sentence on the site lives here.
 *
 * This text is the Quant Lead's approved wording, supplied verbatim in the G2 brief and
 * reproduced without alteration. The G1 `PLACEHOLDER_*` flags and their UI warnings are
 * gone — the copy is canonical now.
 *
 * `{N}` is substituted at render with the paper-tracking day count from the us_equity
 * readiness clock; see `withDayCount`. It renders as an em dash when unknown, never as a
 * zero, because "unknown" and "zero days" are different claims.
 *
 * VOICE. Matches MonzonAutomation (see docs/brand.md §4): first person SINGULAR, concrete
 * over abstract, names the failure mode before the mechanism, no hype. The G2 CTA block
 * used "We"; the 2026-07-26 ruling replaced it with "I", which is both the brand voice and
 * the honest number of people involved — on a page arguing against overclaiming, an
 * inflated pronoun is the wrong first impression.
 */

/** Token replaced with the paper-tracking day count from the equity clock. */
export const DAY_COUNT_TOKEN = '{N}'

// --------------------------------------------------------------------------- //
// Story — hero                                                                //
// --------------------------------------------------------------------------- //

export const STORY_HERO = {
  eyebrow: 'A MonzonAutomation project',
  headline: 'Every decision this system makes is arithmetic you can check.',
  paragraphs: [
    'Glass Box is the public window into quantlab — an autonomous trading-research ' +
      'system that trades simulated money using rules written down before it ever saw a ' +
      'result, then publishes every decision it makes, every mistake it catches, and ' +
      'everything it deliberately refuses to know.',
    `It has been running unattended for ${DAY_COUNT_TOKEN} days. Nothing here is ` +
      'investment advice, and no real money is at risk.',
  ],
  ctas: [
    { label: 'See what it decided today →', to: '/decisions', primary: true },
    { label: 'How it works', to: '#how-it-works', primary: false },
  ],
} as const

// --------------------------------------------------------------------------- //
// Story — sections                                                            //
// --------------------------------------------------------------------------- //

export interface StoryBullet {
  term: string
  rest: string
}

export interface StorySection {
  id: string
  title: string
  body: readonly string[]
  bullets?: readonly StoryBullet[]
  /** Paragraphs rendered after the bullet list. */
  after?: readonly string[]
}

export const STORY_SECTIONS: readonly StorySection[] = [
  {
    id: 'trusting-a-machine',
    title: 'The problem with trusting a machine',
    body: [
      'Most automated systems ask for trust they cannot earn. You are shown a result — a ' +
        'return, a score, a recommendation — and invited to believe the reasoning behind ' +
        'it was sound. When the reasoning is hidden, a good outcome and a lucky one look ' +
        'identical, and so do a bug and a strategy.',
      'Glass Box inverts that. Every number on this site is traceable to a file the ' +
        'system wrote at the moment it acted. Hover any figure in a decision and it will ' +
        'tell you the exact field it came from. Nothing is estimated, nothing is narrated ' +
        'by a language model guessing at motive, and anything that cannot be traced is ' +
        'not displayed at all.',
    ],
  },
  {
    id: 'how-it-works',
    title: 'How it works, in one screen',
    body: [
      'Four accounts run four rules. Each rule is one sentence, fixed in advance from ' +
        'published research, and never adjusted to make a backtest look better:',
    ],
    bullets: [
      {
        term: 'Volatility targeting',
        rest:
          'hold less when the market is turbulent and more when it is calm, sized so the ' +
          "portfolio's expected swing stays near a fixed target.",
      },
      {
        term: 'Trend following',
        rest:
          'hold the market while its price sits above its own ten-month average; step ' +
          'aside into bonds or cash when it falls below.',
      },
      {
        term: 'The same two rules',
        rest: 'applied to Bitcoin, on a 24-hour clock.',
      },
    ],
    after: [
      'Once a day the system wakes up, checks that its data is fresh and its losses are ' +
        'within limits, computes what each rule now says, and trades the difference — but ' +
        'only if the gap is bigger than one percent, so it isn’t churning fees over noise. ' +
        'If any check fails, it stops and does nothing. That “does nothing” path is the ' +
        'most-used feature in the system.',
    ],
  },
  {
    id: 'refuses-to-know',
    title: 'What it refuses to know',
    body: [
      'This system reads settled daily prices and its own account balance. It does not ' +
        'read news, earnings, analyst ratings, social sentiment, minute-by-minute quotes, ' +
        'or any opinion — including its own. Those refusals are published rather than ' +
        'hidden, because knowing what a system *cannot* see is the only way to judge what ' +
        'its decisions actually mean. A position here is never a view on a headline. It ' +
        'cannot be.',
    ],
  },
  {
    id: 'mistakes',
    title: 'The mistakes are on the site too',
    body: [
      'In its first two weeks this system flagged itself as misbehaving twice. Both times ' +
        'the investigation found the fault in the measurement, not the strategy: once a ' +
        'scheduler ran the crypto accounts twice a day, once a price was read before the ' +
        'day had finished settling. Both are written up here in full, with the original ' +
        'wrong numbers still displayed beside the corrected ones.',
      'That is deliberate. A track record you have never seen fail is a track record you ' +
        'cannot evaluate. Published reports are never edited after the fact — corrections ' +
        'are added beside them, and the reasoning is dated and signed.',
    ],
  },
] as const

export const STORY_CTA = {
  id: 'why-this-exists',
  title: 'Why this exists',
  body: [
    // First person SINGULAR, per the 2026-07-26 ruling. The brand voice is "I", and a
    // page whose argument is against overclaiming should not inflate one builder into a
    // "we". This replaced the G2 wording and resolves the inconsistency flagged in
    // docs/brand.md §6.2.
    'Glass Box is a MonzonAutomation project. I build automation for businesses that ' +
      'need to trust what a system did while nobody was watching — and this is the ' +
      'standard I hold my own work to: every action logged, every claim traceable, every ' +
      'failure published.',
    'It was built in collaboration with an AI engineering partner across twelve reviewed ' +
      'batches, with a human approval gate at every step that touched money, credentials, ' +
      'or a published claim. The AI caught errors a human would have missed. The human ' +
      'caught errors the AI would have shipped. The record of both is in the ledger.',
  ],
  ctas: [
    {
      label: 'Work with MonzonAutomation →',
      href: 'https://monzonautomation.com',
      external: true,
      primary: true,
    },
    { label: 'Read the build log →', href: '/ledger', external: false, primary: false },
  ],
} as const

// --------------------------------------------------------------------------- //
// How this was built                                                          //
// --------------------------------------------------------------------------- //

/**
 * The section a recruiter or hiring manager actually needs.
 *
 * Before this existed, the only route from the landing page to *who made this* was one
 * line in the footer, five sections down. Facts and numbers only — no résumé voice, no
 * adjectives about the work. Every claim here is checkable from the ledger or the repo,
 * which is the same standard the rest of the site holds itself to.
 */
export const BUILD_PROCESS = {
  id: 'how-this-was-built',
  eyebrow: 'How this was built',
  title: 'Twelve reviewed batches, and a human gate on anything that mattered.',
  lede:
    'Glass Box and the system behind it were built in collaboration with an AI ' +
    'engineering partner. The process is part of the record, not a footnote to it.',
  facts: [
    {
      label: 'Twelve reviewed batches',
      detail:
        'Each batch shipped with its own verification: linting, type checking, and a test ' +
        'suite that had to pass in isolation against the previous batch before the new ' +
        'work counted.',
    },
    {
      label: 'A human gate on money, credentials, and claims',
      detail:
        'No batch that touched an order path, a secret, or a published number merged ' +
        'without explicit human approval. The trading path has been frozen under review ' +
        'since the first paper account went live.',
    },
    {
      label: 'Two self-caught incidents, both published',
      detail:
        'A scheduler that ran the crypto accounts twice a day, and a price read before ' +
        'the day had settled. Both were found by the system measuring itself, and both ' +
        'write-ups sit beside the original wrong numbers.',
    },
    {
      label: 'Errors caught in both directions',
      detail:
        'The AI found faults a human review would have passed over — a partial bar read as ' +
        'final, a signed value compared against an absolute threshold. The human caught ' +
        'work the AI would have shipped, including a gate that failed the build on its own ' +
        'documentation.',
    },
  ],
  ctas: [
    { label: 'The full dated ledger →', href: '/ledger', external: false },
    { label: 'GitHub ↗', href: 'https://github.com/danielfmonzon', external: true },
  ],
} as const

// --------------------------------------------------------------------------- //
// Footer                                                                      //
// --------------------------------------------------------------------------- //

export const DISCLAIMER =
  'quantlab trades simulated money in brokerage paper accounts. Nothing on this site is ' +
  'investment advice, a recommendation, or an offer to buy or sell any security. ' +
  'Simulated results do not indicate future performance and do not reflect the costs, ' +
  'liquidity, or pressures of live trading. No real capital is at risk.'

export const BUILT_BY = {
  name: 'Daniel Monzon',
  prefix: 'Built by',
  org: 'MonzonAutomation',
  orgHref: 'https://monzonautomation.com',
  links: [
    { label: 'GitHub', href: 'https://github.com/danielfmonzon' },
    { label: 'MonzonAutomation', href: 'https://monzonautomation.com' },
  ],
} as const

// --------------------------------------------------------------------------- //
// Navigation                                                                  //
// --------------------------------------------------------------------------- //

export interface NavCopy {
  label: string
  /** Teaching subtitle — one line, plain language, no jargon. */
  subtitle: string
  title: string
  description: string
}

export const NAV_COPY: Record<string, NavCopy> = {
  '/': {
    label: 'Story',
    subtitle: 'what this is',
    title: 'Glass Box — every decision is arithmetic you can check',
    description:
      'The public window into quantlab: an autonomous trading-research system that ' +
      'trades simulated money by pre-registered rules and publishes every decision, ' +
      'mistake, and deliberate refusal. Not investment advice.',
  },
  '/live': {
    label: 'Live State',
    subtitle: 'the accounts now',
    title: 'Live State — Glass Box',
    description:
      'Current simulated equity, how each mark was taken, risk state, evidence tier, and ' +
      'the 90-day readiness clock for all four paper accounts.',
  },
  '/decisions': {
    label: 'Decisions',
    subtitle: 'every trade, explained',
    title: 'Decisions — Glass Box',
    description:
      'Every rebalance with its stage checklist, the one-sentence rule behind it, and the ' +
      'branch the rule did not take. Every figure traces to the field it came from.',
  },
  '/tracking': {
    label: 'Tracking',
    subtitle: 'does reality match the math',
    title: 'Tracking — Glass Box',
    description:
      'Weekly divergence between what each paper account earned and what its own rules ' +
      'should have earned, against a fixed threshold, with corrections shown beside the ' +
      'figures they replaced.',
  },
  '/limits': {
    label: 'Limits',
    subtitle: 'the brakes',
    title: 'Limits — Glass Box',
    description:
      'How far each account sits from the drawdown limit that would stop it trading, read ' +
      'from the same configuration the risk engine uses.',
  },
  '/equity': {
    label: 'Equity',
    subtitle: 'the curve, point by point',
    title: 'Equity — Glass Box',
    description:
      'Simulated equity per account, with every mark labelled by whether it was taken on ' +
      'schedule, late, or by a task that should not have run.',
  },
  '/ledger': {
    label: 'Ledger',
    subtitle: 'everything, dated',
    title: 'Ledger — Glass Box',
    description:
      'Orders, alerts, weekly verdicts, and dated design rulings merged into one ' +
      'chronological record — including the build log for the system itself.',
  },
  '/ignores': {
    label: 'Refusals',
    subtitle: "what it won't look at",
    title: 'Refusals — Glass Box',
    description:
      'The complete list of what this system reads, and the inputs it deliberately does ' +
      'not: news, earnings, ratings, sentiment, intraday quotes, and any model opinion.',
  },
}

/** Substitute the day-count token. */
export const withDayCount = (text: string, days: number | null): string =>
  text.split(DAY_COUNT_TOKEN).join(days === null ? '—' : String(days))
