# nogra-mcp standalone binary — packaging notes (Phase A PoC + Phase B hardening, macOS-arm64)

Status: PASSED — onefile binary serves the full MCP handshake with exactly the
32 public tools, in a hostile environment (no uv/uvx/pipx on PATH, no repo
.venv, cwd = throwaway fixture workspace).

Phase B (2026-07-04) added: explicit `nogra_mcp.y26_private` exclusion with a
structural build-time assert, bundled package data (resource-reading tools now
return real content), and the `packaging/npm/` esbuild-style npm layout —
all proven locally end-to-end. See the "Phase B" sections below.

This file is the CI-matrix input for Phase C. Everything below was measured on
2026-07-04 on this stack; re-verify on dep bumps.

## Build stack (exact versions)

| component        | version                                   |
| ---------------- | ----------------------------------------- |
| OS / arch        | macOS (Darwin 25.6.0), arm64              |
| PyInstaller      | 6.21.0 (+ pyinstaller-hooks-contrib)      |
| Python (via uv)  | 3.12 (uv-managed cpython-3.12 aarch64)    |
| mcp              | 1.27.0 (FastMCP)                          |
| pydantic         | 2.13.3                                    |
| pydantic-core    | 2.46.3                                    |
| uvicorn          | 0.46.0                                    |
| httpx            | 0.28.1                                    |
| jsonschema       | 4.26.0                                    |
| deps resolution  | uv.lock via `uv run` project env          |

## How to build

    ./packaging/build-macos-arm64.sh

End-to-end: cleans old artifacts, resolves locked deps with uv, layers
PyInstaller via `uv run --with pyinstaller`, builds from
`packaging/nogra-mcp.spec`, smoke-tests `--self-test`.

- Output binary: `packaging/dist/nogra-mcp` (single file, Mach-O arm64)
- Intermediates: `packaging/build/` — safe to `rm -rf` after every build.
- Requirements on the build machine: `uv` + Xcode CLT. Nothing on the user
  machine — the binary is self-contained.

## Why entry_point.py exists

PyInstaller needs a script (not a console-script entry point) as its analysis
root. `packaging/entry_point.py` is a 4-line wrapper importing
`nogra_mcp.server.main` — the same target as pyproject's
`[project.scripts] nogra-mcp`. It is a packaging asset, NOT a server-source
change; `src/nogra_mcp/` is untouched.

## Hidden imports / hooks / quirks — the actual findings

**NONE REQUIRED.** First `--onefile` build worked with empty `hiddenimports`,
no custom hooks, no `datas`. This was expected to be the hard part; it wasn't,
because:

- `pyinstaller-hooks-contrib` stdhooks fired automatically for: `anyio`,
  `pydantic` (bundles the `pydantic_core` native lib), `uvicorn`, `jsonschema`,
  `jsonschema_specifications`, `rich`, `certifi`, `zoneinfo`.
- FastMCP's server-side stdio path (`mcp.server.fastmcp` -> `mcp.server.stdio`)
  has no lazy dynamic imports that escape PyInstaller's graph on mcp 1.27.0.
- `nogra_mcp` itself reads package data via `package_root()`-relative paths
  only for optional resources (schemas/templates/examples); the 32-tool
  handshake does not require them. NOT bundled as datas in this PoC.

Quirks that DID show up (benign, but CI should know):

1. **SDK version rewrite**: PyInstaller rewrites the exe's macOS SDK version
   (26.2.0 -> 14.2.0) to match the Python library, then ad-hoc re-signs.
   Harmless locally; real Developer-ID signing + notarization is a Phase C/D
   item for distribution (Gatekeeper will quarantine downloaded binaries).
2. **setuptools vendored aliases**: analysis aliases `tomli`, `jaraco`,
   `more_itertools`, `importlib_metadata`, `zipp`, `wheel`, `backports` to
   `setuptools._vendor.*`. Informational only.
3. **`uv run` project env**: the repo `.venv` was pip-less; all builds and
   drivers ran through `uv run` against uv.lock instead. The build never
   touches `.venv`.
4. **serverInfo.version reports 1.27.0** (the mcp SDK version, FastMCP
   default), not nogra-mcp 1.0.0 — same behavior as the unpackaged server,
   not a packaging regression.

## Package-data caveat (RESOLVED in Phase B)

Phase A shipped no `datas`; `tools/call` on resource-reading tools returned
fallback/error content (verified: `init` on the Phase A binary returns
`INIT_MANIFEST_INVALID`). Phase B resolution, proven 2026-07-04:

- `datas` in the spec now bundle exactly the directories the server reads via
  `package_root()`-relative paths (verified against source usage in
  `src/nogra_mcp/server.py`: `read_package_text` / `read_package_json` /
  `default_nogra_dir` + the `PUBLIC_PACKAGE_*_RESOURCES` maps and
  `INIT_BUNDLE_MANIFEST`): `schemas/`, `templates/`, `examples/objects/`,
  `toolbank/`, `init-bundle/`, `defaults/`.
- NOT bundled: `roles.json` (referenced only by `runtime_server.py`'s
  Y26-private control-plane resolution `ROOT / "manager" / "nogra-mcp" /
  "roles.json"` — a host-only path unrelated to `package_root()`), and
  `examples/workspaces/` (fixture workspaces, only referenced as a last-resort
  cwd fallback path, never read as resource content).
- `package_root()` resolution in the frozen app: `packaging/entry_point.py`
  now sets `NOGRA_MCP_ROOT=sys._MEIPASS` (setdefault, frozen-only) so the
  existing env-override path in `server.py`/`runtime.py` resolves to the
  extracted datas. Packaging asset only — zero server-source changes; a
  caller-provided NOGRA_MCP_ROOT still wins.
- Proof (rebuilt binary, hostile env, fixture workspace): `tools/call init`
  (`mode=standalone`, `workspace_name=pkgdata-proof`) returns
  `status=ready`, 23/23 files matching `init-bundle/manifest.json`, content
  byte-identical to source after template render (SKILL.md 4758/4758 chars,
  `workspaceId` correctly rendered). Same call against the preserved Phase A
  binary: `status=error, code=INIT_MANIFEST_INVALID`.
- Cost: +24,144 bytes on the binary (18,189,824 -> 18,213,968 B; +0.13%) —
  the ~460 KB of datas compress well. Far under the 100 MB stop threshold;
  handshake unaffected (32/32 verbatim, re-proven).

## Phase B: private-module exclusion + build assert

Enumeration (from source, 2026-07-04): `src/nogra_mcp/y26_private.py` is the
ONLY private module. It is imported lazily in exactly one place
(`server.py: private_module() -> from . import y26_private`), gated behind
`NOGRA_ENABLE_PRIVATE`. No other private/codex module files exist in `src/`.

Spec hardening: `excludes=["nogra_mcp.y26_private"]` in `nogra-mcp.spec` —
the module is physically absent from the artifact, not merely gated off.
PyInstaller handles the excluded lazy import gracefully (the module simply
raises ImportError if the gate were ever enabled in the frozen binary).

Build gate: `packaging/assert_no_private.py` runs inside
`build-macos-arm64.sh` after every build; non-zero exit fails the build.
It checks, structurally:

1. no module matching `y26_private` in the CArchive top level or the embedded
   PYZ archive's module table of contents;
2. none of the y26-only tool-name strings (`y26_role_graph`,
   `y26_workflow_spine`, `y26_brief_template`) anywhere in the DECOMPRESSED
   code objects (names/varnames/consts/filenames/qualnames, recursive), with
   hits attributed to the module they came from.

Deliberately NOT asserted: `codex_dispatch`/`codex_fresh_eyes` substrings.
Those occur in legitimate public modules (`registry.py`'s static capability
catalog; the `transport_dispatch` `codex_pm` target implementation in
`runtime.py`/`runtime_server.py`), so a substring assert on them would fail
every build forever. The private module's registration of those tools is
covered by check 1 plus the 32-tool handshake gate.

**IMPORTANT — plain `strings | grep` is NOT valid evidence on onefile
artifacts.** The PYZ payload is zlib-compressed; empirically (2026-07-04,
this artifact), even identifiers that are certainly present return ZERO
`strings` hits: `transport_dispatch`, `pydantic`, `uvicorn`, `nogra_mcp`,
`FastMCP` -> all 0. A "0 hits for y26_*" strings-grep therefore proves
nothing (it also returns 0 for everything that IS in the binary). Any prior
strings-based absence proof (incl. Phase A's) must be read as vacuous and is
superseded by the structural assert above.

Falsifiability demo (the assert CAN fail — recorded run, 2026-07-04): the
same assert executed against the preserved Phase A binary (built WITHOUT the
exclude) exits 1 with:

    PRIVATE-MODULE ASSERT: FAIL (4 finding(s), 1376 modules scanned)
      - PYZ module TOC contains private module: nogra_mcp.y26_private
      - decompressed payload of module nogra_mcp.y26_private contains: y26_role_graph
      - decompressed payload of module nogra_mcp.y26_private contains: y26_workflow_spine
      - decompressed payload of module nogra_mcp.y26_private contains: y26_brief_template

Repeatable demo route: temporarily set `excludes=[]` in the spec, rebuild,
run `uv run --with pyinstaller -- python packaging/assert_no_private.py
packaging/dist/nogra-mcp` -> exit 1 with the same findings. (Restore the
exclude afterwards; the in-build gate makes shipping such a binary
impossible anyway.)

On the hardened binary the gate reports:
`PRIVATE-MODULE ASSERT: PASS (1375 modules scanned, 0 y26_private modules,
0 private tool-name strings)`.

## Phase B: npm distribution layout (`packaging/npm/`)

esbuild-style split, versions in lockstep with PyPI (all 1.0.0):

- `npm/mcp` = `@nograai/mcp` (main): `bin/nogra-mcp.js` selector +
  optionalDependencies on all five platform packages. The selector maps
  `process.platform`-`process.arch` -> `@nograai/mcp-<plat>-<arch>`,
  `require.resolve`s the binary inside it, spawns with `stdio: "inherit"`,
  forwards SIGTERM/SIGINT and passes the exit code through (same contract as
  the plugin's `scripts/mcp-launcher.mjs`). It never installs and never
  fetches. Test hook: `NOGRA_MCP_PLATFORM_OVERRIDE=<plat>-<arch>` overrides
  detection (E2E negative tests only; unset in production).
- `npm/mcp-darwin-arm64` = `@nograai/mcp-darwin-arm64`: `os:["darwin"]`,
  `cpu:["arm64"]`, contains the hardened binary as `./nogra-mcp`
  (18,213,968 B; tarball 18,022,037 B).
- `npm/mcp-darwin-x64`, `npm/mcp-linux-x64`, `npm/mcp-linux-arm64`,
  `npm/mcp-win32-x64`: scaffolds with correct os/cpu fields and README marked
  CI-populated; NO binary in the source tree (Phase C CI matrix builds and
  places them before publish; win32 binary name is `nogra-mcp.exe`).

Local E2E proof (2026-07-04, no publish): `npm pack` both real packages ->
install BOTH tarballs in one `npm install <darwin-arm64.tgz> <mcp.tgz>` into
a throwaway consumer project (giving npm the platform tarball on the command
line satisfies the optionalDependency locally; the four unpublished platform
packages are skipped without registry errors — "added 2 packages") ->
`node_modules/.bin/nogra-mcp` from a fixture workspace serves the full
handshake: 32 tools, byte-identical to the Phase A public list, spawn->tools
~1.8 s (npx/selector adds ~0.2 s over the bare binary).

Negative proofs (installed selector): `NOGRA_MCP_PLATFORM_OVERRIDE=linux-s390x`
-> exactly one stderr line ("unsupported platform ... (supported: ...)"),
exit 1. `NOGRA_MCP_PLATFORM_OVERRIDE=darwin-x64` (supported but not installed)
-> exactly one stderr line ("platform package @nograai/mcp-darwin-x64 is not
installed ..."), exit 1. No network activity in either path (the selector has
no fetch/install code at all).

## Measurements (macOS-arm64, M-series, 2026-07-04)

Phase A values below; Phase B (excludes + datas) binary = 18,213,968 B
(+24,144 B vs Phase A), hostile-env spawn->initialize 1602 ms (cold, fresh
copy), npm-installed selector spawn->tools/list 1825 ms.

| metric                                   | value            |
| ---------------------------------------- | ---------------- |
| binary size (`ls -lh`)                    | 17 MB (18,189,440 B) |
| cold start (fresh copy, first run, spawn->initialize resp) | 1383 ms |
| warm start, spawn->initialize resp (5 runs) | 984–1086 ms (median ~1023) |
| initialize->tools/list                    | 1.5–1.9 ms       |
| spawn->tools/list total, warm             | 985–1087 ms      |

"Cold" = first execution of a freshly copied binary (onefile bootloader
extracts the archive to a temp dir each run; `runtime_tmpdir=None`). Warm runs
re-extract too — the ~1s floor is dominated by extraction + CPython start +
FastMCP import, not by MCP itself. If ~1s spawn is too slow for MCP client UX,
the recorded fallback is `--onedir` (no per-run extraction; not needed for
this PoC since onefile worked and 1s is acceptable for a long-lived stdio
server that spawns once per session).

## Handshake / boundary proof (evidence summary)

- Driver: raw JSON-RPC over stdio (newline-delimited, per mcp/server/stdio.py):
  `initialize` -> `notifications/initialized` -> `tools/list`.
- Hostile env: `env -i PATH=<bindir>:/usr/bin:/bin`, cwd = fixture workspace
  containing only `.nogra/config.json` = `{"workspaceId": "binary-fixture"}`.
  `command -v uv uvx pipx` fails in that env (exit 1); only /usr/bin/python3
  (3.9) exists and is used ONLY as the driver process, never by the server.
- Result: `tool_count: 32`, tool list byte-identical to the unpackaged source
  baseline, zero `y26_*` / `codex_*` tools (public boundary per BOUNDARY.md:
  32 public vs 39 host tools — the 7 private tools are absent).

## CI reproduction checklist (Phase C input)

1. Install uv on the runner; checkout the package.
2. `./packaging/build-macos-arm64.sh` (same script; matrix over os/arch later —
   spec uses native arch, so each target builds on its own runner).
3. Handshake gate: spawn `packaging/dist/nogra-mcp` with a stripped env +
   fixture cwd, assert initialize OK and tools/list == the 32 public names.
4. Boundary gate: assert no tool name starts with `y26_` or `codex_`.
5. Record size + spawn->initialize timing as build metrics.

## Phase C1 (2026-07-04): CI matrix + publish pipeline authored, not pushed

The checklist above is now implemented as code instead of prose. Repo root
for the (not-yet-created) `github.com/nograai/nogra-mcp` public repo IS this
package directory, so `.github/` already sits where it needs to be.

**`packaging/build.py`** — portable build driver, the Python replacement for
the bash logic in `build-macos-arm64.sh`: cleans `build/`+`dist/`, resolves
deps via `uv run --with pyinstaller` against `uv.lock`, builds from
`packaging/nogra-mcp.spec`, runs `assert_no_private.py`, and optionally
(`--smoke`) chains `ci_smoke.py`. Identical invocation on every OS —
`uv run python packaging/build.py` — because it only shells out to `uv`
itself; no bash-isms, `pathlib` throughout, binary name resolved as
`nogra-mcp.exe` on `win32`. `build-macos-arm64.sh` is now a 10-line back-compat
wrapper (`exec uv run python "$PACKAGING_DIR/build.py" "$@"`) kept only so the
existing invocation keeps working unchanged on this machine.

**`packaging/ci_smoke.py`** — the portable CI gate the checklist's steps 3-4
describe, now stdlib-only (no PyInstaller/mcp import needed): writes a
throwaway fixture workspace (`.nogra/config.json` = `{"workspaceId":
"ci-smoke"}`), drives the raw JSON-RPC stdio handshake (`initialize` ->
`notifications/initialized` -> `tools/list`), and asserts exactly 32 tools
with zero `y26_*`/`codex_*` names. Windows-safe: reads the child's stdout via
a background thread + queue instead of `select()` on pipes (`select()` on
file objects is POSIX-only and silently doesn't work on Windows — this is why
it's a thread/queue design and not a straight port of
`acceptance/gate_boundary_test.py`'s `select()`-based session helper, which
inspired the JSON-RPC message shape but not the I/O plumbing).

**Local proof (2026-07-04, this machine, macOS-arm64) — the exact CI entry
points**:

```
$ python3 packaging/build.py
...
==> built:
.../packaging/dist/nogra-mcp (18,214,160 bytes)
==> private-module assert (PYZ TOC + decompressed payload):
PRIVATE-MODULE ASSERT: PASS (1375 modules scanned, 0 y26_private modules, 0 private tool-name strings)
Done. Binary: .../packaging/dist/nogra-mcp

$ python3 packaging/ci_smoke.py packaging/dist/nogra-mcp
CI SMOKE: PASS (32/32 tools, 0 forbidden y26_*/codex_* names)

$ ./packaging/build-macos-arm64.sh   # back-compat wrapper, full rebuild
... PRIVATE-MODULE ASSERT: PASS (1375 modules scanned, ...) ...
$ python3 packaging/ci_smoke.py packaging/dist/nogra-mcp
CI SMOKE: PASS (32/32 tools, 0 forbidden y26_*/codex_* names)
```

Negative proofs of `ci_smoke.py` itself (falsifiability, not just a pass):
`python3 packaging/ci_smoke.py` (no arg) correctly resolves the default
`packaging/dist/nogra-mcp` path; `python3 packaging/ci_smoke.py /bin/echo`
(a non-MCP binary) exits 1 with `initialize did not return a result`,
`tools/list did not return a result`, `tool count 0 != expected 32`.

Binary size drifted by a few hundred bytes build-to-build (18,214,160 B this
run vs. 18,213,968 B recorded in Phase B, 18,213,808 B on the wrapper
rebuild) — consistent with PyInstaller's per-build UUID/timestamp rewriting
noted above, not a functional change; the assert and smoke gates are the real
evidence, not the byte count.

**`.github/workflows/build.yml`** — 5-platform matrix (`macos-14`
darwin-arm64, `macos-15-intel` darwin-x64, `ubuntu-24.04` linux-x64,
`ubuntu-24.04-arm` linux-arm64, `windows-2022` win32-x64), triggers on
`push`/`pull_request`/`workflow_call`. Steps: `actions/checkout@v7` ->
`astral-sh/setup-uv@v8` -> `uv run python packaging/build.py` -> `uv run
python packaging/ci_smoke.py` -> `actions/upload-artifact@v7` with
deterministic names `nogra-mcp-<platform>-<arch>`.

**`.github/workflows/publish.yml`** — triggers on `v*` tags; job 1 calls
`build.yml` via `workflow_call` (reused, not duplicated); job 2 downloads all
5 artifacts, places binaries into `packaging/npm/mcp-<plat>-<arch>/`
(`chmod +x` restored on unix binaries — `upload-artifact`/`download-artifact`
strip the executable bit), verifies every platform + main `package.json`
version equals the tag (proven locally both ways: matching tag `v1.0.0`
against the current `1.0.0` package.jsons exits 0; a deliberately wrong tag
`v9.9.9` exits 1 with an explicit `VERSION MISMATCH` line per package,
**before** any `npm publish` call runs), then publishes the 5 platform
packages and `@nograai/mcp` last. `NODE_AUTH_TOKEN` comes from
`secrets.NPM_TOKEN` via `actions/setup-node@v6`'s `registry-url` auth path —
referenced only inside `env:` blocks, never echoed in any `run:` step.

**YAML validation**: `uv run --with pyyaml python -c yaml.safe_load(...)` on
both files parses clean. Both files' `on:` key loads as the Python boolean
`True` under `yaml.safe_load` — this is PyYAML's YAML-1.1 boolean-literal
behavior for bare `on`/`off`/`yes`/`no` keys, common to essentially every
GitHub Actions workflow file and harmless (GitHub's own workflow parser
handles it correctly); it is not a defect in these two files. Full structural
dump (`json.dumps` of the parsed tree) confirms the 5-entry matrix and both
jobs' step lists match what's described above; `bash -n` on every embedded
`run:` script in `publish.yml` parses clean; the version-match step was also
executed directly (not just `-n` checked) with both a matching and a
deliberately wrong tag, per the "Local proof" transcript above.

**Runner-label self-review (live-checked against
`github.com/actions/runner-images`, 2026-07-04)** — see `RELEASING.md`
"Known gaps" for the full detail and fallback options:

- `macos-13` (the brief's literal darwin-x64 label) is now **fully retired**,
  not merely deprecated — it's absent from the current image list entirely.
  Authored with the brief's own anticipated fallback, `macos-15-intel`,
  which IS the current x64 macOS label, but it's namespaced under GitHub's
  "larger runner" convention (`macos-15-intel`/`macos-15-large`/
  `macos-14-large`) rather than a plain standard label the way the ARM macOS
  images are — whether it schedules on the `nograai` org's actual plan is
  unverified from this machine and can only be confirmed by the first real
  push.
- `ubuntu-24.04-arm` is confirmed **GA** (no preview badge, unlike
  `ubuntu-26.04-arm` which is marked preview) — resolves that flag
  positively, residual risk only in per-org billing/access, not availability.
- `windows-2022` and `macos-14` (arm64) both confirmed current, unflagged.
- Action versions used reflect each action's current release as of
  2026-07-04 (`actions/checkout@v7`, `astral-sh/setup-uv@v8`,
  `actions/upload-artifact@v7`, `actions/download-artifact@v8`,
  `actions/setup-node@v6`) rather than the brief's illustrative `@v4` text —
  checked release notes confirm no breaking API changes relevant to this
  workflow's usage between those and v4 (mostly Node-runtime-version bumps).

**`RELEASING.md`** (package root) is the Phase C2 runbook: create the public
repo -> push -> add `NPM_TOKEN` (granular, `@nograai` scope, publish-only) ->
tag `v1.0.0` -> push tag -> post-verify checklist (Actions 5/5 green, npm
package pages, `npx @nograai/mcp` smoke, `uvx nogra-mcp` regression check) +
the gap-flags above + a rollback note (npm never allows republishing a
version; bump to a patch tag instead).

Nothing was pushed, tagged, or published in Phase C1 — the repo does not
exist yet. `packaging/build/` intermediates were removed after the final
local proof run; `packaging/dist/nogra-mcp` (the hardened binary) was kept.

## 1.0.1 frozen-path fix (2026-07-04): defensive ROOT resolution in transport_runtime

**Root cause.** CI Build #2 failed on BOTH Linux legs (linux-x64, linux-arm64)
with an identical traceback: `entry_point` -> `server.main` -> `run_stdio` ->
`build_mcp` -> `register_extensions` (server.py) -> `import
nogra_mcp.transport_runtime` -> module line 19 -> `IndexError: 4`. The
module-level default-ROOT computation was
`Path(__file__).resolve().parents[4]` — a walk that assumes the dev/private
checkout depth. A PyInstaller onefile binary on Linux self-extracts to
`/tmp/_MEIxxxxxx/`, so the module file is
`/tmp/_MEIxxxxxx/nogra_mcp/transport_runtime.py` with only **4** ancestors
(indices 0–3); `parents[4]` is out of range and the import — and therefore
the whole server — dies at startup.

**The macOS/Windows-passed-incidentally lesson.** The same binary passed CI
on macOS and Windows for depth reasons only: macOS runners extract under
`/var/folders/...` (deep, and even a literal `TMPDIR=/tmp` gains a level via
the `/tmp -> /private/tmp` symlink under `.resolve()`), Windows under a deep
`AppData\Local\Temp` path. PyPI/uvx (unfrozen, deep `site-packages`) is
unaffected. A green leg is only evidence for that leg's filesystem shape —
path-depth assumptions must be tested at the shallowest real extraction
point, which is Linux `/tmp/_MEIxxxxxx`.

**Repro recipe.** On Linux CI: any spawn of the frozen binary
(`packaging/ci_smoke.py`) hits it. On macOS the shallow layout is NOT
reproducible via `TMPDIR=/tmp` (verified empirically: the `/private/tmp`
symlink resolution adds the missing ancestor, and this build's spec sets
`runtime_tmpdir=None` — macOS extraction stayed under `/var/folders/...`).
Unit-level RED proof instead: exec the module source with a simulated
`__file__` of `/tmp/_MEIxxxxxx/nogra_mcp/transport_runtime.py` and `resolve()`
prevented from adding symlink levels -> `IndexError: 4` at line 19, verbatim
match with the CI traceback.

**The fix (transport_runtime.py only, no server.py change needed).** The
`parents[4]` walk moved into `_resolve_default_root()`, which checks depth
before indexing and falls back to the shallowest available ancestor
(`parents[-1]`) when index 4 does not exist. `transport_runtime` is host-only
control-plane machinery (BOUNDARY.md): in a frozen public binary there is no
control-plane at any path, so a harmless fallback ROOT is architecturally
correct — every consumer (`TRANSPORT_DIR` etc.) already tolerates a
nonexistent directory tree, and public mode simply serves its 32 tools as it
always did when the control-plane is absent. On a real deep checkout index 4
always exists, so the fallback branch never triggers and host/dev ROOT is
byte-for-byte unchanged (proven: pre-fix `parents[4]` value == post-fix
imported `ROOT` on this machine). `NOGRA_ROOT`/`Y26_ROOT` env overrides win
over the default exactly as before. `register_extensions`' import site in
server.py was read and needed no guard: the failure was module-level, not
call-level.

**Version lockstep 1.0.1.** `pyproject.toml` + `packaging/npm/mcp/package.json`
(version + all five optionalDependencies pins) + all five platform
package.jsons: 12 occurrences of `1.0.1`, zero remaining `1.0.0`.

**Green proofs (this machine, macOS-arm64, rebuilt binary).**
`python3 packaging/build.py` -> `PRIVATE-MODULE ASSERT: PASS (1375 modules
scanned, 0 y26_private modules, 0 private tool-name strings)`. Then:
(a) `TMPDIR=/tmp python3 packaging/ci_smoke.py` -> `CI SMOKE: PASS (32/32
tools, 0 forbidden y26_*/codex_* names)`; (b) default-TMPDIR run -> same PASS;
(c) unfrozen baseline (uv project env, this checkout's `src/` on `PYTHONPATH`,
`packaging/entry_point.py`) through the same ci_smoke handshake -> same PASS.
One trap worth recording: `uv run --project . nogra-mcp` is NOT a valid
unfrozen baseline on a dev machine — this project has no `[build-system]`, so
uv treats it as virtual (never installs the console script) and falls through
to whatever `nogra-mcp` wrapper is on PATH (here: a dev plugin wrapper serving
38 tools). Pin the source with `PYTHONPATH=src` + the explicit entry point.
Cross-platform verify is CI Build #3 after push; nothing was committed,
pushed, tagged, or published from this run.
