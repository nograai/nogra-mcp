---
schema: nogra.brief.v1
releaseVersion: v1.0.0
briefId: brief-demo-contract-check
workspaceId: local
title: Validate public contract resources
createdAt: 2026-05-04T00:00:00Z
status: ready
owner: local-user
targetRole: implementer
targetModel: anthropic:sonnet
evidenceRequired: verified
---

# Validate Public Contract Resources

## Intent

Confirm that the public MCP package exposes stable contract resources for a clean workspace.

## Context Handoff

The public core should expose schemas and templates without reading private workflow context or local machine state.

## Decisions

- Keep this validation structural.
- Do not add dispatch, locking or provider calls.

## Rejected

- Do not expose private transcripts or repo state.

## Known Gaps

- Runtime behavior will be designed after the contract layer is validated.

## Scope

In:

- Inspect public registry output.
- Read the public Brief, Run and RunEvent resources.

Out:

- Executing work from the brief.
- Assigning ownership automatically.

Files:

- nogra://public/schemas/brief-v1
- nogra://public/templates/brief-v1

## Success Criteria

- The registry lists the public contract resources.
- The public package boundary scan returns no private-context hits.

## Stop Criteria

- Any public resource exposes private context.

## Execution Shape

Tool families:

- read-only

Tool needs:

- read-only file inspection

Notes:

No writes or provider web research are needed for this structural contract check.

## Max Output

Format: concise validation report
Limit: no hard word limit; include command evidence and any blockers needed to verify the result
