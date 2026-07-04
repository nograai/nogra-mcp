---
name: nogra-completion-evidence
description: Package completion evidence for Nogra verification. Use before reporting work as done, after an executor returns, or when evidence is partial or blocked.
---

# Nogra Completion Evidence

Use this skill before presenting Nogra-selected work as complete. Nogra invites;
it does not enforce. Package and verify evidence when the user chose Nogra flow;
do not use verification as pressure to convert direct work into Nogra.

## Evidence Packet

Prepare an evidence object with:

- `reportText`: concise summary of what changed and what remains
- `filesChanged`: customer artifact paths changed by the executor, normalized
  to workspace scope
- `scopeFiles`: required in hosted validation unless the full brief is embedded
- `protocolFilesChanged`: optional Nogra bookkeeping paths such as
  `.nogra/briefs`, `.nogra/events`, `.nogra/runs`, `.nogra/receipts` or
  `.nogra/transport`; these are not customer scope changes
- `commandsRun`: commands or checks actually run, with result status
- `acceptance`: one item per success criterion with `status` and `criterion`
- `briefId` or embedded `brief` when needed for validation
- `decisionRequired`: true when the user must choose before completion

Useful acceptance statuses:

- `met`: criterion satisfied
- `partial`: criterion partly satisfied or needs review
- `blocked`: criterion cannot be satisfied
- `decision_required`: user decision needed

## Rules

- Evidence must describe what happened, not what should have happened.
- Never claim a check passed unless it was actually run or otherwise proven.
- If no check was run, say that directly in `commandsRun` or reportText.
- If files outside scope changed, include them in `filesChanged` and let
  validation flag the drift.
- Do not put Nogra protocol localWrites in customer `filesChanged`. Report
  them as `protocolFilesChanged` when relevant.
- If the return is incomplete, use `blocked`, `partial` or
  `decision_required`; do not soften it into a ship verdict.

## Verification

For an ordinary single-run dispatch, Manager verifies completion by comparing
the executor's report and evidence against the approved brief's intent, scope
and success criteria. Spawn a separate verifier only when verification work
itself should be isolated from the Manager conversation.

When independent checks would keep browser, network, console, test or log noise
out of the Manager conversation, fetch `nogra_role_contract(role: verifier)`
and spawn a disposable `general-purpose` verifier with the returned role
contract, the brief, run id, executor report and evidence packet. Nogra does
not install a persistent `nogra-verifier` project agent. Then call
`transport_validate_completion` with the run id and evidence object. Use the
returned verdict as the completion authority:

- `ship`: work matched the brief
- `afvigelse`: partial or review needed
- `blocked`: completion failed or evidence is invalid
- `beslutning_kraeves`: user decision is needed

Hosted validation is stateless. It must receive the evidence needed to judge
the run inline; do not rely on hosted Nogra to read the customer run record.
Minimum hosted evidence is `runId`, `briefId`, `reportText`, `scopeFiles` or an
embedded `brief`, `filesChanged`, `commandsRun` and `acceptance`. Include
`protocolFilesChanged` separately when `.nogra/` bookkeeping changed.

If submit or validation responses include `localWrites`, apply them to
`.nogra/` before reporting that local records are current. Validate paths
against `<workspace>/.nogra/` and deduplicate JSONL appends by the provided
idempotency key.

After verification, report the verdict, evidence highlights and next owner. Do
not continue fixing after a blocked or decision-required verdict without new
user approval.
