Static assets for the LIVE (localhost) build.

Deliberately excludes public/snapshot/: the operational dashboard reads the live API and
never requests a capture, so shipping ~800 kB of snapshot JSON with it served no purpose.
`vite.config.ts` selects this directory unless `--mode public` is set.

Anything added to public/ that BOTH builds need must be added here too.
