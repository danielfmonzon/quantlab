/**
 * GLASS — the trust thesis, and the reason the whole app is called a glass box.
 *
 * Given the same design weight as OVERVIEW on purpose. Most systems publish a
 * feature list, which invites a reader to infer capability. This screen publishes
 * the inverse: the complete set of inputs, and the deliberate refusals. A reader who
 * knows the system cannot see news will not read a position as a view on news.
 */

import { api } from '../lib/api'
import type { IgnoredInputsResponse } from '../lib/api'
import { useApi } from '../lib/useApi'
import { EmptyState } from '../components/primitives'

export function Glass() {
  const resource = useApi<IgnoredInputsResponse>(() => api.ignoredInputs())
  const data = resource.data

  return (
    <div>
      <header className="border-b border-ink-600 pb-8">
        <p className="text-2xs font-medium uppercase tracking-[0.2em] text-signal-idle">
          the glass box
        </p>
        <h1 className="mt-3 max-w-4xl text-3xl font-semibold leading-tight tracking-tight text-slate-50 sm:text-4xl">
          What it knows, and what it refuses to know.
        </h1>
        {data ? (
          <p className="mt-4 max-w-3xl text-sm leading-relaxed text-slate-400">
            {data.statement}
          </p>
        ) : null}
      </header>

      {resource.error ? (
        <div className="mt-8">
          <EmptyState title="Could not read /api/ignored-inputs." detail={resource.error} />
        </div>
      ) : resource.loading ? (
        <p className="mt-8 text-xs text-signal-idle">reading /api/ignored-inputs…</p>
      ) : !data ? null : (
        <>
          <div className="mt-8 grid gap-6 lg:grid-cols-2">
            {/* Reads. */}
            <section data-testid="inputs-read">
              <div className="mb-4 flex items-baseline gap-3">
                <h2 className="text-sm font-medium uppercase tracking-widest text-signal-ok">
                  What it reads
                </h2>
                <span className="font-mono text-2xs text-signal-idle">
                  {data.reads.length} inputs
                </span>
              </div>
              {data.reads.length === 0 ? (
                <EmptyState
                  title="No inputs declared."
                  detail="The service could not report what it reads."
                />
              ) : (
                <ul className="space-y-3">
                  {data.reads.map((input) => (
                    <li
                      key={input.name}
                      className="rounded-lg border border-ink-500 bg-ink-800 p-4"
                    >
                      <div className="flex items-start gap-3">
                        <span
                          className="mt-1.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-signal-ok"
                          aria-hidden
                        />
                        <div>
                          <h3 className="text-sm font-medium text-slate-100">{input.name}</h3>
                          <p className="mt-0.5 font-mono text-2xs uppercase tracking-wider text-signal-idle">
                            {input.role}
                          </p>
                          <p className="mt-2 text-xs leading-relaxed text-slate-400">
                            {input.rationale}
                          </p>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* Refusals. */}
            <section data-testid="inputs-ignored">
              <div className="mb-4 flex items-baseline gap-3">
                <h2 className="text-sm font-medium uppercase tracking-widest text-signal-warn">
                  What it deliberately ignores
                </h2>
                <span className="font-mono text-2xs text-signal-idle">
                  {data.ignores.length} refusals
                </span>
              </div>
              {data.ignores.length === 0 ? (
                <EmptyState
                  title="No refusals declared."
                  detail="The service could not report what it ignores."
                />
              ) : (
                <ul className="space-y-3">
                  {data.ignores.map((input) => (
                    <li
                      key={input.name}
                      className="rounded-lg border border-dashed border-ink-500 bg-ink-900/40 p-4"
                    >
                      <div className="flex items-start gap-3">
                        <span
                          className="mt-1 shrink-0 font-mono text-signal-warn/70"
                          aria-hidden
                        >
                          ✕
                        </span>
                        <div>
                          <h3 className="text-sm font-medium text-slate-300">{input.name}</h3>
                          <p className="mt-2 text-xs leading-relaxed text-slate-400">
                            {input.rationale}
                          </p>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>

          <section className="mt-10 border-t border-ink-600 pt-8">
            <h2 className="text-2xs font-medium uppercase tracking-widest text-signal-idle">
              Why publish the refusals
            </h2>
            <div className="mt-3 grid max-w-5xl gap-6 text-xs leading-relaxed text-slate-400 sm:grid-cols-2">
              <p>
                A feature list tells you what a system can do, and lets you assume the
                rest. The refusal list tells you what it structurally cannot do, which
                is the more useful half when you are deciding how much to trust a
                number. If this system trims a position, that decision came from a
                moving average or a volatility ratio — not from anything it read about
                the world that day.
              </p>
              <p>
                It is also the reason the run narrations are template-bound to
                structured fields. A narrator free to write "trimmed on weakening
                momentum" would be inventing a causal story from a system whose only
                inputs are settled daily closes. A plausible explanation is more
                dangerous than none, because it is harder to check.
              </p>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
