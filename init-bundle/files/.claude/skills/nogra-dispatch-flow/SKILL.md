---
name: nogra-dispatch-flow
description: Start approved Nogra work from a validated brief. Use when the user gives GO and you need a dispatch receipt, run id, execution handoff, and return path.
---

# Nogra Dispatch Flow

Use this skill after a brief exists and the user has approved execution. Nogra
invites; it does not enforce. Dispatch is only for user-chosen Nogra work, never
an automatic escalation from direct work.

## Preflight

- Confirm the brief is the one the user approved.
- Confirm the user gave explicit execution approval after seeing the brief.
  Demo, preview or "can we build something" language is not approval.
- Confirm the execution mode. GO approves the route that was presented.
- Confirm scope files, success criteria and stop criteria are present.
- Confirm the target and targetModel are appropriate. V1 defaults are
  Anthropic-first, but the provider label remains customer-owned.
- If a material choice is missing, ask before dispatch.
- If the public/hosted Nogra control plane is unavailable in a public demo or
  customer flow, stop and report that failure. Do not continue by falling back
  to a local or private Nogra server.

## Dispatch

1. Create or select the ready brief record.
2. Request a Nogra dispatch receipt and run id with the appropriate MCP tool.
3. If the response includes `localWrites`, apply them to `.nogra/` with path
   validation before saying the local run record exists.
4. Fetch the ephemeral executor contract with `nogra_role_contract(role:
   executor)`.
5. Spawn Claude Code's built-in `general-purpose` subagent as a disposable run
   agent. Include the returned executor role contract, full brief, run id,
   scope, stop criteria and required evidence in the handoff.
6. Tell the run agent to use `nogra-completion-evidence` before packaging its
   final report when the client exposes the Skill tool; otherwise the role
   contract's return shape is the fallback evidence contract.
7. Give the run agent the full brief, not a loose summary. The Manager must not
   implement dispatched scope itself.
8. Keep the Manager conversation focused on state and decisions while the work
   runs.

The hosted Nogra MCP returns control-plane artifacts. It does not perform local
file edits for the customer. Local commands, file writes and subagent execution
remain customer-side Claude Code work.

Hosted Nogra is not the runtime ledger. After dispatch, do not call hosted
Nogra to log lifecycle steps, read ordinary status, persist reports/outputs or
hold run state. Use hosted Nogra at event boundaries only: route guidance,
security checks, mismatch diagnosis and optional stateless completion
validation. Local `.nogra/` records are the trust source.

Manager is not Executor. Do not install or depend on persistent
`.claude/agents/` files for Nogra runtime roles. Nogra runtime agents are
ephemeral: Manager fetches a role contract from hosted Nogra at the dispatch or
verification boundary, spawns Claude Code's built-in `general-purpose`
subagent with that contract and run-specific inputs, receives a report, then
the run agent is done.

If Claude Code cannot spawn a subagent at all, stop and surface the missing
primitive. Do not offer synchronous fallback, inline Manager execution or a
bypass path. The user may explicitly override, but Manager must not propose
bypass paths.

`localWrites` are the bridge from hosted control-plane state to customer-local
`.nogra/` records. They are not permission to write outside `.nogra/`. Reject
absolute paths, `~`, control characters, `..` escapes and any resolved path
outside `<workspace>/.nogra/`. For JSONL appends, skip duplicates using the
provided idempotency key.

Nogra protocol localWrites are not customer scope changes. Keep them out of
customer `filesChanged` evidence unless the brief explicitly asks to customize
Nogra files.

If a dispatch receipt or run id cannot be obtained, stop. Do not "continue
pragmatically" by editing files outside the approved Nogra run.

## Optional `/goal`

Use `/goal` only when the execution has a measurable completion condition and
the user approved that style. Render the brief's success criteria into a
condition that can be proven by surfaced evidence, such as a check exit code or
completed acceptance list.

Do not treat `/goal` as the Nogra completion gate. Completion still requires
evidence submitted to Nogra and verified against the brief.

## Return Path

After execution returns:

1. Gather reportText, customer filesChanged, commandsRun and acceptance results
   from the executor. Keep `.nogra/` protocol artifacts separate.
2. Persist report/output and run state locally under `.nogra/transport/`.
3. For a normal single-run dispatch, Manager compares the executor report and
   evidence against the approved brief's intent, scope and success criteria and
   forms the verdict.
4. Spawn a disposable verifier only when verification would create noisy
   browser, network, console, test or log work, when independent verification is
   explicitly required, or when the run is part of a larger multi-agent flow.
   In those cases, fetch `nogra_role_contract(role: verifier)` and spawn a
   `general-purpose` verifier with the role contract, brief, run id and
   executor report.
5. Call `transport_validate_completion` when hosted stateless validation is
   needed for protocol checks or completion verdict support.
6. Return the verdict and the supporting evidence.
7. If the verdict is `afvigelse`, `blocked` or `beslutning_kraeves`, ask for a
   decision before continuing.

Local report persistence is a Manager responsibility:

- write `.nogra/transport/artifacts/<runId>/report.md`
- write `.nogra/transport/artifacts/<runId>/output.md`
- read-modify-write `.nogra/transport/runs/<runId>.json`, preserving all
  existing dispatch metadata and merging only these fields:
  - `updatedAt`: current ISO timestamp
  - `phase`: `returning`
  - `reportSubmittedAt`: current ISO timestamp
  - `status`: executor status normalized to Nogra transport status
  - `summary`: executor summary
  - `completedAt`: current ISO timestamp only when status is terminal
- append `transport_report_submitted` to `.nogra/transport/events.jsonl` with a
  stable `eventId`

Never replace the whole run record with a thin stub. Preserve `paths`,
`metadata`, `briefId`, target fields and scope metadata from the dispatch
receipt.

## Stop Conditions

Stop and ask if:

- the executor needs to touch work outside approved scope
- the user has not given clear execution approval after reviewing the brief
- the run id or receipt is missing
- evidence is incomplete
- the user asks to change target, model or scope mid-run
- the work reaches a stop criterion
