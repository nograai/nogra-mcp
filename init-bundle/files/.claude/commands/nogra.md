---
description: Run Nogra workspace actions
argument-hint: init | status | config | brief | demo | dispatch | verify | pinboard
---

Handle this Nogra request: $ARGUMENTS

Use the smallest safe Nogra workflow that fits the request.

## Product Stance

Nogra invites; it does not enforce. Suggest Nogra when work has scope, stakes
or ambiguity, then wait for the user's GO. Never pressure, nag, count turns or
auto-escalate the user into Nogra. If the user chooses direct work, continue
directly.

## Tool Boundary

Use the public Nogra MCP server for `/nogra` event-boundary actions. If more
than one Nogra MCP server is available, prefer the hosted/public server for
init, brief contract/validation, route guidance, security checks, mismatch
diagnosis and optional completion validation. In this workspace, do not use
non-public doctrine tools to infer the public brief shape; use the public brief
contract instead.

Hosted Nogra is the living guide and stateless judge, not the runtime ledger.
Do not call hosted Nogra to log lifecycle steps, persist reports/outputs, read
ordinary status or hold run state. Local `.nogra/` records are the trust source.
Version/playbook freshness piggybacks on normal Nogra responses; do not add
session-start pings or polling.

If the hosted/public Nogra MCP call fails during a public init, demo, brief or
test flow, stop and report the hosted failure. Do not fall back to a local or
private Nogra server. A fallback can make the test look successful while writing
to the wrong workspace.

Do not write memory during Nogra demo, init, test or diagnosis work unless the
user explicitly asks you to save something to memory.

## Routing

- `init`: call `nogra_init`, then write each returned file according to its
  writePolicy. Use the returned `installPlan` when present: do a preflight for
  existing files, write in phase groups, and keep chat narration at the phase
  level rather than listing every file. If an `ask_before_overwrite` file
  already exists, skip it by default and report it as preserved. Only overwrite
  those files when the user explicitly asks to overwrite Nogra files. If Claude
  Code stores a large tool result in a file, use the Write tool or the client's
  built-in JSON parsing rather than `jq`, `wc` or shell loops that can be
  brittle in sandboxed PATHs. Render install progress as a short phase tasklist,
  not a file-by-file transcript. Track final counts as written, updated,
  preserved and failed. Do not hide or suppress Claude Code's normal Write
  transparency; the quieting is chat narration only, not opaque bundling. If a
  phase fails because of path validation, permissions, disk or another local
  write error, mark that phase failed with the reason, stop remaining phases,
  and report which prior phases completed. After successful writes, show the
  returned `postInstallMessage`, tell the user that core init does not install
  persistent Nogra project agents, and that approved runs use disposable
  `general-purpose` run agents with role contracts fetched from Nogra at
  dispatch or verification boundaries. If obsolete
  `.claude/agents/nogra-executor.md` or `.claude/agents/nogra-verifier.md`
  files exist from an older Nogra init, explain that they are no longer used and
  ask before deleting them. Mention that the optional local pinboard renderer
  can be installed later with `/nogra pinboard install`, and ask what brief the
  user wants to create first. Do not install optional features unless the user
  asks.
- `status`: read recent briefs, runs, transport state and events; return a
  concise current-state summary.
- `config`: inspect local Nogra configuration and render a numbered menu with a
  conversational escape. Read `.nogra/config.json`, `.nogra/providers.md`,
  `.nogra/presets/`, `.nogra/consult-templates/` and `.claude/skills/` when
  present. Include pinboard state: if the optional
  renderer is not installed, choosing pinboard offers install; if it is
  installed, choosing pinboard offers customize, repair or uninstall guidance.
  Skills should show the installed list and offer to view or edit one. Runtime
  roles are not installed as agents; fetch them with `nogra_role_contract` when
  dispatch or verification needs them.
  End every menu level with: `Type a number to change, or describe what you want
  to change.` If the user requests an edit, preview the exact file and change,
  then wait for explicit GO before writing. Do not silently edit config,
  providers, presets, templates or skills. Call hosted Nogra only for
  schema, mismatch, refresh or security guidance; ordinary config navigation is
  local file reading and editing.
- `brief`: use the `nogra-brief-writing` skill. Draft, validate and save the
  brief; do not dispatch unless the user also gave execution GO.
- `demo`: use a known-good demo brief shape from the public brief contract.
  Prefer the contract's `demoBrief` payload. Do not intentionally trigger
  validation failures as part of the demo. A demo request is not execution GO:
  show the brief and ask for approval before dispatching or writing files.
- `dispatch`: use the `nogra-dispatch-flow` skill. Require an approved brief
  and explicit GO before getting a dispatch receipt or run id. After receipt,
  fetch `nogra_role_contract(role: executor)` and spawn Claude Code's built-in
  `general-purpose` subagent as a disposable run agent with the returned role
  contract, full brief, run id, scope, stop criteria and evidence contract. The
  Manager must not implement dispatched scope itself. If Claude Code cannot
  spawn a subagent at all, stop and surface the missing primitive; do not offer
  synchronous fallback, inline execution or bypass paths. The user may
  explicitly override, but Manager must not propose bypass paths.
- `verify`: use the `nogra-completion-evidence` skill. Package evidence, use
  `nogra_role_contract(role: verifier)` plus a disposable `general-purpose`
  verifier for noisy browser/log/test checks when useful, call completion
  validation, and report the verdict. Do not verify inline as a
  Manager-proposed bypass.
- `pinboard`: use the `nogra-pinboard-customize` skill. Inspect status from
  local Nogra records, install the optional renderer when asked, show renderer
  help, or adapt the optional visual surface.

## Pinboard State

Treat `.nogra/` records as the trust source. Core init does not install
pinboard files or create a visible `nogra/` folder. Do not create hidden sync,
sidecar state, hooks, watchers or enforcement to keep a visual surface fresh.

For status, read local Nogra records directly: brief drafts and promoted briefs,
runs, events, transport runs, reports and outputs. If the user asks for a live
pinboard, explain that the local renderer is an optional feature and is not
required for Nogra core.

If the user asks to install the local pinboard renderer, call
`nogra_optional_feature_bundle` with `feature_id: local-pinboard-renderer`, then
write the returned pinboard files while preserving each file writePolicy. Do not
download or write those files during normal `/nogra init`. Do not auto-start it.
Show:

```bash
node nogra/pinboard/server.mjs --port 7777
```

If the user asks to start it, run that command only after confirming the current
directory is the Nogra workspace root containing `.nogra/config.json`. If not,
ask for the workspace root or use `--root /path/to/workspace`. The renderer
prints the live URL when it starts. Its versioned data contract is `/api/state`
with schema `nogra.pinboard.state.v0`.

## Config Menu

For `/nogra config`, keep the surface predictable but conversational. Show the
current state before asking for action:

```text
Nogra config

1. Workspace          name, id, paths
2. Model defaults     target model and provider labels
3. Brief policy       depth and limits
4. Return policy      final answer shape
5. Providers          .nogra/providers.md
6. Presets            neutral, critique, ideation, fresh-eyes
7. Consult template   consult-default.md
8. Pinboard           installed or not installed
9. Skills & roles     skills installed, runtime roles fetched on demand

Type a number to change, or describe what you want to change.
```

If the user chooses a number, drill into that local file or feature state. If
they describe a change in normal language, map it to the relevant local file and
preview the edit. Editing configuration is never implicit GO: show the proposed
diff or replacement snippet and wait for explicit approval before writing.

## Local Artifact Writes

Some Nogra MCP responses include `localWrites`. These are customer-local
artifact instructions, not execution approval. Apply them before saying the
local `.nogra/` trust source is current.

Validate each write path before writing:

- resolve it against the current workspace root
- reject absolute paths, `~` paths, null bytes and control characters
- normalize `.`, `..`, duplicate slashes and symlinks
- reject the write unless the resolved target stays under
  `<workspace>/.nogra/`

For `append_jsonl`, skip the append if the target file already contains the
same `idempotencyField` value. If a local write fails, report the hosted control
plane result and the local persistence failure separately. If you are not
standing in the workspace that ran `/nogra init`, stop and ask before applying
local writes. Do not include Nogra protocol localWrites under `.nogra/briefs`,
`.nogra/events`, `.nogra/runs`, `.nogra/receipts` or `.nogra/transport` in
customer `filesChanged` evidence; report them separately as control-plane
artifacts when relevant.

If the argument is empty or ambiguous, inspect current Nogra state and offer the
next useful action rather than guessing.

## Local Report Persistence

After an executor returns, persist report/output locally before validation:

- write `.nogra/transport/artifacts/<runId>/report.md`
- write `.nogra/transport/artifacts/<runId>/output.md`
- read-modify-write `.nogra/transport/runs/<runId>.json`, preserving dispatch
  metadata and merging only `updatedAt`, `phase: "returning"`,
  `reportSubmittedAt`, `status`, `summary` and `completedAt` when status is
  terminal
- append `transport_report_submitted` to `.nogra/transport/events.jsonl` with a
  stable `eventId`

If hosted transport lifecycle tools say local records are required, treat that
as updated playbook guidance: read/write local `.nogra/` records and recommend
re-running `/nogra init` after preserving customer changes.

Explicit GO means the user approves execution after seeing the brief, using
clear language such as `GO`, `kør det`, `byg det`, `execute`, `run it`,
`approved`, or an equivalent direct approval. Phrases like "show me a demo",
"can we build something", "what would this look like", or "vis mig noget fedt"
are not GO.

Never expose access tokens or secrets. Never treat this command as permission to
change files, run commands or dispatch work unless the user explicitly asked for
that action.
