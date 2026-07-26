/**
 * The transport layer: one function that both data modes flow through.
 *
 * **live** — the default. Fetches `/api/*` from the localhost API. This is the
 * operational dashboard's behaviour and it is unchanged.
 *
 * **snapshot** — selected at build time by `VITE_DATA_MODE=snapshot`. Reads flat
 * JSON captured by `quantlab glassbox snapshot` from `/snapshot/`, addressed through
 * `manifest.json`. Nothing public ever reaches the machine that trades.
 *
 * WHY A MANIFEST rather than a URL-to-filename convention: the mapping lives in one
 * generated file, so a filename scheme change on the Python side cannot silently
 * desynchronise the client. The only thing both sides must agree on is
 * `canonicalKey`, which is deliberately tiny and mirrored verbatim from
 * `glassbox/snapshot.py`.
 */

export type DataMode = 'live' | 'snapshot'

export const SNAPSHOT_BASE = '/snapshot'
export const MANIFEST_URL = `${SNAPSHOT_BASE}/manifest.json`

/** Query parameters excluded from snapshot addressing. Mirrors the Python constant. */
const KEY_EXCLUDED_PARAMS = new Set(['limit'])

/**
 * Resolve the mode from the build-time environment.
 *
 * NOTE, because it is easy to assume otherwise: this is a RUNTIME read of Vite's
 * `import.meta.env` object, not a statically eliminated constant — accessing it
 * through optional chaining defeats the literal substitution. Both transports are
 * therefore present in both bundles, and which one runs depends entirely on the
 * `VITE_DATA_MODE` value baked in at build time. The safety property does not rest on
 * dead-code elimination; it rests on `.env.public` and `netlify.toml` both setting
 * the variable, so a public build cannot come out in live mode.
 */
export function resolveDataMode(): DataMode {
  const declared = (import.meta.env?.VITE_DATA_MODE as string | undefined)?.toLowerCase()
  return declared === 'snapshot' ? 'snapshot' : 'live'
}

export const DATA_MODE: DataMode = resolveDataMode()

/**
 * The snapshot lookup key for a request URL.
 *
 * Mirrors `glassbox.snapshot.canonical_key`: parameters are sorted by name so key
 * construction is order-independent, and `limit` is dropped because snapshots are
 * captured at full depth — a request for 50 rows is answered with the whole capture
 * rather than missing the file.
 */
export function canonicalKey(url: string): string {
  const [path, query] = url.split('?', 2)
  if (!query) return path ?? url
  const params = new URLSearchParams(query)
  const kept: Array<[string, string]> = []
  params.forEach((value, key) => {
    if (!KEY_EXCLUDED_PARAMS.has(key) && value !== '') kept.push([key, value])
  })
  if (kept.length === 0) return path ?? url
  kept.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
  return `${path}?${kept.map(([k, v]) => `${k}=${v}`).join('&')}`
}

export interface SnapshotManifestEntry {
  key: string
  file: string
  path: string
  params: Record<string, string>
  status: number
  bytes: number
}

export interface SnapshotManifest {
  generated_at: string
  git_commit: string
  quantlab_version: string
  endpoints: SnapshotManifestEntry[]
  endpoint_count: number
  note: string
}

export class TransportError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'TransportError'
  }
}

let manifestPromise: Promise<SnapshotManifest> | null = null

/** Load (and memoise) the snapshot manifest. Rejects in live mode. */
export function loadManifest(): Promise<SnapshotManifest> {
  if (!manifestPromise) {
    manifestPromise = fetch(MANIFEST_URL, { headers: { accept: 'application/json' } })
      .then((response) => {
        if (!response.ok) {
          throw new TransportError(
            `snapshot manifest unavailable (${response.status})`,
            response.status,
          )
        }
        return response.json() as Promise<SnapshotManifest>
      })
      .catch((error: unknown) => {
        // Reset so a transient failure can be retried rather than cached forever.
        manifestPromise = null
        throw error
      })
  }
  return manifestPromise
}

/** Test seam: forget the memoised manifest. */
export function resetManifestCache(): void {
  manifestPromise = null
}

async function getSnapshot<T>(url: string): Promise<T> {
  const manifest = await loadManifest()
  const key = canonicalKey(url)
  const entry = manifest.endpoints.find((e) => e.key === key)
  if (!entry) {
    throw new TransportError(
      `no snapshot capture for ${key}. This build is a static snapshot; only ` +
        'endpoints captured at snapshot time are available.',
      404,
    )
  }
  const response = await fetch(`${SNAPSHOT_BASE}/${entry.file}`, {
    headers: { accept: 'application/json' },
  })
  if (!response.ok) {
    throw new TransportError(
      `snapshot file ${entry.file} missing (${response.status})`,
      response.status,
    )
  }
  return (await response.json()) as T
}

async function getLive<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { accept: 'application/json' } })
  if (!response.ok) {
    throw new TransportError(`${url} returned ${response.status}`, response.status)
  }
  return (await response.json()) as T
}

/** Fetch an `/api/*` URL through whichever mode this build is in. */
export function getJson<T>(url: string, mode: DataMode = DATA_MODE): Promise<T> {
  return mode === 'snapshot' ? getSnapshot<T>(url) : getLive<T>(url)
}
