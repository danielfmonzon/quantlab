/**
 * Glossary — fourteen terms this site cannot avoid using.
 *
 * Each entry is exactly two sentences: what the term MEANS, then why it MATTERS here.
 * Written for a reader with no finance background, which means no jargon inside a
 * definition of jargon — and never talking down. The test for each of these was: would
 * this sentence embarrass a reader who already knew the term? If yes, rewrite.
 */

export interface GlossaryEntry {
  /** Canonical term, matched case-insensitively by <Term>. */
  term: string
  /** One sentence: what it is. */
  meaning: string
  /** One sentence: why it matters on this site. */
  matters: string
}

export const GLOSSARY: readonly GlossaryEntry[] = [
  {
    term: 'paper trading',
    meaning:
      'Trading with simulated money in a brokerage account that behaves like a real one ' +
      'but settles nothing.',
    matters:
      'Every figure on this site comes from paper accounts, so the results are a test of ' +
      'the rules rather than a claim about anyone’s returns.',
  },
  {
    term: 'shadow',
    meaning:
      'A recomputation of what an account should have earned if its own rules had been ' +
      'followed perfectly, rebuilt from settled prices after the fact.',
    matters:
      'Comparing the real account against its shadow is how this system catches its own ' +
      'mistakes without waiting for a loss to reveal them.',
  },
  {
    term: 'drawdown',
    meaning:
      'How far an account has fallen from its own highest point, measured as a percentage ' +
      'of that peak.',
    matters:
      'It is the number the kill switch watches, because it describes the loss an owner ' +
      'would actually have lived through rather than an average.',
  },
  {
    term: 'bps',
    meaning:
      'Basis points — hundredths of a percent, so 50 bps is 0.50% and 100 bps is one ' +
      'percent.',
    matters:
      'Differences between an account and its shadow are small by design, and percent ' +
      'figures with three decimals are harder to compare at a glance than whole bps.',
  },
  {
    term: 'kill switch',
    meaning:
      'An automatic stop that halts all trading for an account when its drawdown crosses a ' +
      'preset limit, and stays halted until a person clears it.',
    matters:
      'It is the one control here that a human must release by hand, so a bad week cannot ' +
      'quietly become a worse month.',
  },
  {
    term: 'realized volatility',
    meaning:
      'How much a price actually moved over a recent window, measured from the price ' +
      'history rather than predicted.',
    matters:
      'Two of the four rules size their positions from this number, holding less when ' +
      'recent movement has been large.',
  },
  {
    term: 'rebalance',
    meaning:
      'Buying or selling to bring holdings back to the weights a rule currently calls for.',
    matters:
      'It is the only action this system ever takes, and each one is published with the ' +
      'rule and the numbers that produced it.',
  },
  {
    term: 'drift band',
    meaning:
      'A tolerance — one percent here — inside which holdings are left alone rather than ' +
      'traded back to target.',
    matters:
      'Without it the system would trade constantly on meaningless movement and pay fees ' +
      'for the privilege.',
  },
  {
    term: 'month-end signal',
    meaning:
      'The rule’s decision, computed once using the last completed trading day of the ' +
      'month and then held until the next one.',
    matters:
      'Fixing the decision date in advance removes the temptation to act on a day that ' +
      'happens to look favourable.',
  },
  {
    term: 'backtest',
    meaning:
      'Running a rule over historical prices to see what it would have done in the past.',
    matters:
      'A backtest is the weakest evidence on this site, because the past is the one dataset ' +
      'a rule can be quietly tuned against.',
  },
  {
    term: 'walk-forward',
    meaning:
      'A stricter test that decides using only data available at each point in time, then ' +
      'steps forward and repeats.',
    matters:
      'It catches rules that only work because they were built with knowledge of what came ' +
      'next.',
  },
  {
    term: 'bootstrap',
    meaning:
      'Reshuffling historical returns thousands of times to see the range of outcomes a ' +
      'rule could plausibly have produced.',
    matters:
      'It answers "was this luck?" with a distribution instead of a single flattering ' +
      'number.',
  },
  {
    term: 'provenance',
    meaning:
      'The record of how a particular figure came to exist — which run wrote it, and when.',
    matters:
      'Marks taken late or by the wrong scheduled task look identical to clean ones on a ' +
      'chart, so this site labels each one rather than letting them blend.',
  },
  {
    term: 'tracking error',
    meaning:
      'The gap between what an account did and what it was supposed to do.',
    matters:
      'Most of the gap here turns out to be measurement timing rather than trading, which ' +
      'is exactly the distinction this site exists to make visible.',
  },
]

const BY_TERM = new Map(GLOSSARY.map((entry) => [entry.term.toLowerCase(), entry]))

export const lookupTerm = (term: string): GlossaryEntry | undefined =>
  BY_TERM.get(term.trim().toLowerCase())
