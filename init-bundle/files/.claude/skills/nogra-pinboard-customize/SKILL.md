---
name: nogra-pinboard-customize
description: Inspect local Nogra records or install/customize the optional pinboard renderer. Use when the user asks for status, wants to view briefs or runs, or wants to adapt the optional visual surface.
---

# Nogra Pinboard Customize

The pinboard is an optional local browser surface owned by the customer
workspace. It is not part of core init. It is a viewer, not a service, alarm or
enforcement layer. It shows what happened when the user installs the local
renderer; it does not tell the user they should use Nogra.

## Data Contract

Core Nogra does not install a pinboard file. `.nogra/` records are the trust
source:

- `.nogra/briefs/drafts/`
- `.nogra/briefs/`
- `.nogra/runs/`
- `.nogra/events/`
- `.nogra/transport/`
- transport reports and outputs under `.nogra/transport/artifacts/`

## Refresh Workflow

1. Read `.nogra/config.json` for workspace metadata.
2. Read brief records from `.nogra/briefs/`.
3. Read run and event records from `.nogra/runs/`, `.nogra/events/` and
   `.nogra/transport/`.
4. Pick the latest brief and latest relevant run evidence.
5. If the local renderer is installed, use it to render from `.nogra/` records.
6. If no renderer is installed, summarize status from `.nogra/` records in chat
   and offer the optional renderer only when useful.

## Optional Renderer

The local renderer is optional. Install it only after the user asks for it.

- `nogra_init` advertises the feature as metadata only.
- Source files come from `nogra_optional_feature_bundle` with
  `feature_id: local-pinboard-renderer`, after the user opts in.
- The optional bundle includes the visible pinboard HTML, server, README and
  local `.gitignore`. Write those files with their writePolicy; preserve
  existing customized files by default.
- Do not auto-start a background process.
- Start manually from the workspace root:

```bash
node nogra/pinboard/server.mjs --port 7777
```

If the current directory does not contain `.nogra/config.json`, ask for the
workspace root or start with `--root /path/to/workspace`.

The renderer serves:

- the printed local URL for the live pinboard
- `/api/state` for `nogra.pinboard.state.v0`

## Customization Rules

- Do not add hidden sync, hooks, watchers or enforcement.
- Do not make pinboard state more authoritative than `.nogra/` records.
- If adding a live surface, keep it optional and local to the workspace.
- Keep the file readable and editable by the customer's Claude.
- Prefer direct status, brief, run and evidence views over decorative content.

## Safe Design Changes

Safe changes include layout, colors, labels, columns, density, filters, and
which fields are emphasized.

Risky changes include hiding verification status, inventing a second state
store, or making the pinboard depend on a service outside the workspace.
