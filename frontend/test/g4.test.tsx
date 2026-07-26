/**
 * G4: the MonzonAutomation link target is a single configurable constant.
 *
 * WHY THESE TESTS EXIST. The landing page's primary call to action — the one link that asks
 * a reader to become a client — pointed at `https://monzonautomation.com`, which is not a
 * registered domain. Every visitor who clicked the most important button on the site got a
 * browser error. Nothing caught it, because no test asserted that a link's destination was
 * reachable, only that the attribute matched a hardcoded string; the string and the assertion
 * were wrong in exactly the same way.
 *
 * The fix is one constant. These tests enforce that it stays one constant: a second hardcoded
 * URL somewhere in the copy would drift the moment the apex changes, and the drift would be
 * invisible until someone clicked a stale footer link.
 *
 * Reachability itself is checked in the batch's verification step, not here — a unit test
 * that makes a network call is a unit test that fails on a plane.
 */

import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import { BUILT_BY, MONZONAUTOMATION_URL, STORY_CTA } from '../src/content/copy'

const COPY_SRC = fs.readFileSync(
  path.resolve(__dirname, '..', 'src', 'content', 'copy.ts'),
  'utf8',
)

describe('MonzonAutomation link target', () => {
  it('is a single absolute https URL with no trailing slash', () => {
    expect(MONZONAUTOMATION_URL).toMatch(/^https:\/\/[a-z0-9.-]+$/)
  })

  it('is not the unregistered apex', () => {
    /**
     * `monzonautomation.com` returned NXDOMAIN on 2026-07-26 — not an empty site, an
     * unregistered name. This is the assertion whose absence let the dead link ship. It is
     * written as an inequality against that specific host rather than a reachability check
     * so it keeps holding after the apex is registered and this constant moves to it: at
     * that point the host is live, and a maintainer who flips the constant will delete this
     * expectation deliberately, as part of the same change that makes it false.
     */
    expect(MONZONAUTOMATION_URL).not.toBe('https://monzonautomation.com')
  })

  it('is the destination of the Story CTA', () => {
    expect(STORY_CTA.ctas[0]?.href).toBe(MONZONAUTOMATION_URL)
  })

  it('is the destination of both footer references', () => {
    expect(BUILT_BY.orgHref).toBe(MONZONAUTOMATION_URL)
    const org = BUILT_BY.links.find((l) => l.label === 'MonzonAutomation')
    expect(org?.href).toBe(MONZONAUTOMATION_URL)
  })

  it('appears as a literal exactly once in copy.ts — at its definition', () => {
    // The "one constant" requirement, made mechanical. Three call sites reference the
    // identifier; only the declaration may contain the string.
    const literals = COPY_SRC.match(/'https:\/\/[a-z0-9.-]*monzonautomation\.com'/g) ?? []
    expect(literals).toEqual([`'${MONZONAUTOMATION_URL}'`])
  })

  it('carries the instruction for switching to the apex', () => {
    // A comment is the only thing that will tell a future reader why this indirection
    // exists. If it is deleted, the constant looks like arbitrary ceremony.
    expect(COPY_SRC).toMatch(/SWITCH TO `https:\/\/monzonautomation\.com` ONCE THAT APEX IS LIVE/)
  })
})
