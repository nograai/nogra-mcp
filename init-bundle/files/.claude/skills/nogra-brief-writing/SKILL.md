---
name: nogra-brief-writing
description: Turn user intent into a Nogra brief before execution. Use when work needs scope, success criteria, stop criteria, or user approval before dispatch.
---

# Nogra Brief Writing

Use this skill to convert intent into a brief that can be validated, saved and
approved before execution starts. Nogra invites; it does not enforce. Suggest a
brief when the work has scope, stakes or ambiguity, then wait for the user's GO.
Never insist, nag, count turns or auto-escalate direct work into Nogra flow.

## Brief Standard

A Nogra brief should make the work executable without making the result
pre-decided. Build from the public brief contract, not from trial-and-error.
Include:

- `title`: concrete work name
- `intent`: what the user wants and why it matters
- `contextHandoff`: relevant facts, constraints, prior decisions and rejected
  paths
- `scope`: what may be changed or inspected
- `files`: file or resource patterns when known
- `successCriteria`: checks that prove the work is done
- `stopCriteria`: conditions that require returning to the user
- `maxOutput`: return policy for the executor's final response; this is not a
  limit on how long the brief may be
- `evidenceRequired`: the expected evidence level
- `target` and `targetModel` when execution routing matters

The brief itself has no default word limit. Use as much detail as needed for a
bounded executor to work safely and for the Manager to verify the return. If the
workspace has `.nogra/config.json`, use its `returnPolicy` as the default
`maxOutput` value unless the user gives a different return policy.

## Workflow

1. Inspect enough context to avoid guessing.
2. Ask one concrete question if a missing decision would change scope.
3. Read the public brief contract before drafting when it is available: call
   `nogra_brief_contract`, or read `nogra://public/schemas/brief-v0` and
   `nogra://public/templates/brief-v0`.
4. Draft a complete `nogra.brief.v0` shape. Prefer structured JSON for
   validate/save so field names and nested values are explicit.
5. Validate it once with `nogra_brief_validate`.
6. If validation fails after using the contract, stop and report the contract
   mismatch or missing decision. Do not use repeated validation failures as a
   discovery mechanism.
7. Save it with `nogra_brief_save`.
8. If the response includes `localWrites`, apply them to `.nogra/` with path
   validation before saying the brief is locally recorded.
9. Promote it only when it is ready for user approval.
10. If promote returns `localWrites`, apply them with the same validation.
11. Stop after the brief unless the user gave explicit execution approval after
   seeing the brief.

## Writing Rules

- Keep scope testable. "Improve the app" is not a dispatchable scope.
- If a success criterion requires an evidence artifact written to disk, include
  that artifact path or pattern in `scope.files`. Do not add screenshot or
  browser artifacts unless they are actually part of the requested result.
- List no-go areas when they are known.
- Write success criteria that evidence can prove, not vibes.
- Do not hide uncertainty. Put known gaps in the brief.
- Do not impose a word count on the brief unless the user asks for one.
- Do not turn the brief into a long manual. It should be enough context for a
  bounded agent to do the work and for the Manager to verify the return.
- Do not call non-public workspace doctrine tools for customer brief writing.
- Do not fall back from hosted/public Nogra to a local or private Nogra server
  in public demo, init, brief or test flows. If hosted Nogra fails, stop and
  report the failure.
- Do not write memory during Nogra demo, init, test or diagnosis work unless
  the user explicitly asks you to save memory.
- If the user chooses direct work instead of Nogra, respect that choice.
- Treat localWrites as artifact persistence only. Reject paths that escape
  `<workspace>/.nogra/`, and deduplicate JSONL appends by their idempotency key.

## Approval Boundary

Demo and preview language is not GO. If the user asks to "show a demo", "show
what this would look like", "build something through a brief", or similar, draft
and present the brief, then ask for approval. Do not dispatch, write files, run
commands or spawn execution until the user approves with clear language such as
`GO`, `kør det`, `byg det`, `execute`, `run it`, or `approved`.

## Stop Conditions

Stop and ask before dispatch if:

- the user has not approved execution
- success criteria cannot be checked
- file scope is unknown and could affect unrelated work
- credentials, payment, production traffic or irreversible actions are involved
- the brief needs private context the customer workspace does not own
