# RELEASING.md — nogra-mcp npm distribution (Phase C2 runbook)

Phase C1 authored the complete GitHub repo skeleton in-tree: the 5-platform
CI build matrix (`.github/workflows/build.yml`), the tag-triggered publish
pipeline (`.github/workflows/publish.yml`), the portable build driver
(`packaging/build.py`) and the stdlib-only CI smoke gate
(`packaging/ci_smoke.py`). Everything below was validated as far as possible
on this machine (YAML parse-clean, build+assert+smoke green on
macOS-arm64) — see `packaging/NOTES.md` "Phase C1" for the local-proof
evidence. **Nothing in this file has been executed. No repo exists yet, no
tag has been pushed, no package has been published.**

Repo decision (locked): `github.com/nograai/nogra-mcp`, PUBLIC. The repo root
IS this package directory (`nogra-mcp/`) — `.github/` already sits at the
directory root you are pushing, no path rewriting needed.

## The three Patti actions

### 1. Create the repo and push

```
gh repo create nograai/nogra-mcp --public --source=. --remote=origin
git push -u origin main
```

(Or create empty on github.com and `git remote add origin ... && git push -u
origin main` — either way, push this exact directory as the repo root.)

This alone triggers `build.yml` (its `on: push` trigger) — the 5-platform
matrix will run and upload artifacts, but `publish.yml` does NOT run yet (it
only triggers on `v*` tags). This is a free, safe way to confirm the matrix
schedules and goes green on all 5 runners before ever tagging.

### 2. Add the NPM_TOKEN secret

npm side: on npmjs.com, generate a **Granular Access Token** scoped to the
`@nograai` org packages, with **publish** permission only (not "automation"
tokens, not classic tokens with full account access). Reasonable expiration
(e.g., 1 year) is fine; org 2FA/IP-allowlist as your account policy requires.

Repo side: Settings -> Secrets and variables -> Actions -> New repository
secret -> name it exactly `NPM_TOKEN`, paste the token value. This is the
only secret `publish.yml` reads (`secrets.NPM_TOKEN`, wired to
`NODE_AUTH_TOKEN` via `actions/setup-node`'s registry-url auth path — never
echoed in any workflow step).

### 3. Tag and push

```
git tag v1.0.0
git push origin v1.0.0
```

This triggers `publish.yml`: job 1 reuses `build.yml` via `workflow_call`
(same 5-platform build -> assert -> smoke gate, not duplicated logic); job 2
downloads all 5 artifacts, places each binary into its
`packaging/npm/mcp-<plat>-<arch>/` package (restoring the executable bit that
`upload-artifact`/`download-artifact` strip on unix binaries), verifies every
`package.json` version equals the tag (**fails fast, before any `npm publish`
call, on any mismatch** — proven locally, see `packaging/NOTES.md`), then
publishes the 5 platform packages and finally `@nograai/mcp` itself.

## Post-verify checklist (after the tag push)

- [ ] GitHub Actions tab: the `publish.yml` run shows the reused build job
      green on all 5 matrix legs (5 artifacts: `nogra-mcp-darwin-arm64`,
      `nogra-mcp-darwin-x64`, `nogra-mcp-linux-x64`, `nogra-mcp-linux-arm64`,
      `nogra-mcp-win32-x64`), then the `publish` job green.
- [ ] `https://www.npmjs.com/package/@nograai/mcp` and all 5
      `@nograai/mcp-<plat>-<arch>` package pages show version `1.0.0`.
- [ ] `npx --yes @nograai/mcp` in a throwaway directory spawns the server and
      serves the MCP handshake (32 tools) — same proof shape as
      `packaging/ci_smoke.py`, now over the published registry instead of a
      local binary.
- [ ] `uvx nogra-mcp` (the existing PyPI distribution path) still works
      unchanged — this npm work is a separate, additive distribution channel;
      Phase C1 touched nothing in the PyPI/`pyproject.toml` path.

## Known gaps — flagged, not silently dropped

Verified live against `github.com/actions/runner-images` (main branch
README) on 2026-07-04, the day this was authored. Re-check before relying on
this if a long time has passed.

**1. `ubuntu-24.04-arm` (linux-arm64) — CONFIRMED GA, low risk.** It appears
in the current runner-images table with no "preview" badge (unlike
`ubuntu-26.04-arm`, which IS marked preview). This resolves the brief's
"availability uncertain" flag positively. Residual risk: hosted Linux ARM64
runner access/billing can still differ by org plan tier in ways this
read-only check can't confirm from this machine. If the `ubuntu-24.04-arm`
leg fails to schedule on the first real push: fallback is either a
self-hosted arm64 runner, or shipping `@nograai/mcp-linux-arm64` as an
unpublished scaffold for v1 (same treatment as the darwin-x64 fallback
below) and revisiting once confirmed.

**2. `macos-13` (darwin-x64) — WORSE than "deprecation risk": already fully
retired.** The brief flagged this as a possible upcoming deprecation; live
verification shows `macos-13` is not merely deprecated, it is **absent
entirely** from the current runner-images list (only macOS 14/15/26 remain).
Using the literal `macos-13` label in the matrix would fail to schedule
immediately. I authored the matrix using the brief's own anticipated
fallback, `macos-15-intel`, which is confirmed to be the current x64 macOS
label — **but** it is listed alongside `macos-15-large`/`macos-14-large`
under GitHub's "larger runner" naming convention, not as a plain standard
runner the way the ARM macOS labels (`macos-14`, `macos-15`) are. This means
**standard hosted x64 macOS runners may no longer be available on the same
terms as ARM macOS runners**, and whether `nograai`'s actual GitHub plan can
schedule `macos-15-intel` at all is **unverified from this machine** — it can
only be confirmed by the first real push in step 1 above.

  - If `macos-15-intel` schedules and goes green: no action needed.
  - If it fails to schedule (org/plan lacks larger-runner access): two
    fallback options, neither implemented here (would need their own
    brief/decision):
    (a) drop `@nograai/mcp-darwin-x64` from the v1 publish — ship
        darwin-arm64 only initially (Apple Silicon is the dominant Mac
        install base by 2026; `mcp-darwin-x64` stays an unpublished scaffold,
        same shape as the pre-C1 state), or
    (b) a Rosetta-2 cross-build of the x64 binary from an arm64 runner
        (PyInstaller `--target-arch x86_64` against an x86_64 Python under
        Rosetta) — genuinely unverified, higher-risk, needs its own
        investigation before attempting.

**3. `npm --provenance` — deliberately skipped for v1.** Enabling it later
needs two additions to `publish.yml`'s `publish` job: `permissions:
id-token: write`, and `--provenance` appended to each `npm publish` call.
No other changes needed (npm provenance does not require anything from the
platform packages themselves beyond being published from a GitHub Actions
run, which is already the case here).

## Rollback note

npm does not allow republishing the same version number once published. If a
publish run fails partway (e.g. 3 of 6 packages succeed, then a registry
hiccup), do not try to "fix forward" `v1.0.0` — bump to a patch tag (e.g.
`v1.0.1`) and re-run the full tag-push flow. All 6 packages stay in lockstep
versioning by construction (the version-match gate would otherwise refuse to
publish a partial set against a new tag anyway).
