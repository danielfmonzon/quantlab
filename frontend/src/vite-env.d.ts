/// <reference types="vite/client" />

/**
 * The one build-time variable this app reads. Declared explicitly so a typo in the
 * name is a compile error rather than a silent fall back to live mode — which, on a
 * static host, would render every screen as a fetch failure.
 */
interface ImportMetaEnv {
  readonly VITE_DATA_MODE?: 'live' | 'snapshot'
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
