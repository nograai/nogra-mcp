---
schema: nogra.brief.v1
releaseVersion: v1.0.0
briefId: brief-slug
workspaceId: local
title: Brief title
createdAt: 2026-05-04T00:00:00Z
status: draft
owner: ""
targetRole: ""
targetModel: anthropic:sonnet
evidenceRequired: reported
---

# Brief Title

## Intent

State the outcome in one or two concrete sentences.

## Context Handoff

Capture the context needed to act without reading private history.

## Decisions

- Decision already made.

## Rejected

- Path that should not be taken.

## Known Gaps

- Open uncertainty or missing input.

## Scope

In:

- Work that belongs in this brief.

Out:

- Work that must not be done in this brief.

Files:

- Optional file or resource pointer.

## Success Criteria

- Brief-specific condition, derived from the intent and scope, that would show
  the result matches what the user asked for.

## Stop Criteria

- Condition that should stop execution and return for clarification.

## Execution Shape

Tool needs:

- None

Notes:

None

## Max Output

Format: evidence-first state brief
Limit: no hard word limit; keep the opening summary concise and include all evidence needed to verify the result
