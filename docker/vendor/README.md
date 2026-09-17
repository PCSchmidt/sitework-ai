# docker/vendor/

Holds the vendored `prime-agent` npm tarball that `Dockerfile.agent` installs from.
Gitignored — never commit the `.tgz` itself.

## Why this directory exists

`prime-agent` (github.com/PCSchmidt/prime-agent) is not published to the public npm
registry — its `package.json` has `"private": true`. `npm install -g prime-agent@x.y.z`
inside a Docker build only works on a machine that happens to have it installed
globally already; it fails everywhere else, including CI. Found and documented in
`docs/spikes/spike-01-prime-agent-headless.md` (2026-09-17) — see that spike report
for the full context, and risk F9 in `docs/prime-agent-feasibility.md`.

## Regenerating the tarball

From a machine with a working `prime-agent` install (`npm list -g prime-agent`):

```bash
npm pack --pack-destination /path/to/sitework-ai/docker/vendor \
  "$(npm root -g)/prime-agent"
```

This packs the already-built `dist/` from the global install (no separate build step
needed). Match the resulting filename's version to `PRIME_AGENT_VERSION` in
`Dockerfile.agent` (default `0.9.3`, the version this was verified against).

## The real fix

This vendoring approach is a stopgap, not a destination. Before this image needs to be
reproducible by anyone other than the person who built it (a second contributor, CI,
a fresh machine), set up either:

- A private npm registry (GitHub Packages is the natural fit given the repo already
  lives on GitHub) with build-time auth (`NPM_TOKEN` build secret), or
- A CI job in the `prime-agent` repo that publishes a tagged, versioned artifact
  somewhere `Dockerfile.agent` can fetch with credentials.

Either way, `Dockerfile.agent`'s install step changes from `COPY .../prime-agent.tgz`
+ `npm install -g` to a registry install with an auth token, and this directory (and
the vendoring instructions above) go away.
