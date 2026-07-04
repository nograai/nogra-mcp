from __future__ import annotations

import fnmatch
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any


def package_root() -> Path:
    configured = os.environ.get("NOGRA_MCP_ROOT", "").strip()
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    configured = os.environ.get("NOGRA_ROOT") or os.environ.get("Y26_ROOT")
    if configured:
        return Path(configured).resolve()
    return package_root().parents[1]


def load_runtime_module() -> Any:
    root = repo_root()
    os.environ.setdefault("NOGRA_ROOT", str(root))
    os.environ.setdefault("Y26_ROOT", str(root))
    from . import runtime_server

    return runtime_server


def load_transport_runtime_module() -> Any:
    from . import transport_runtime

    return transport_runtime


def runtime_tool_names() -> list[str]:
    return [
        "chain_pm_then_agent",
        "transport_dispatch",
        "agent_exec_packet",
        "transport_submit_report",
        "transport_validate_completion",
        "transport_status",
        "transport_events",
        "transport_return",
        "transport_watch",
        "transport_ack",
        "transport_cleanup",
    ]


def env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def hosted_mode() -> bool:
    return env_truthy("NOGRA_HOSTED")


def public_server() -> Any:
    from . import server

    return server


def generated_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def take_local_writes(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    writes = payload.pop("localWrites", []) if isinstance(payload.get("localWrites"), list) else []
    policy = payload.pop("localWritePolicy", None) if isinstance(payload.get("localWritePolicy"), dict) else None
    return writes, policy


def attach_local_writes(payload: dict[str, Any], writes: list[dict[str, Any]], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    if writes:
        payload["localWritePolicy"] = policy or public_server().local_write_policy()
        payload["localWrites"] = writes
    return payload


def clean_inline(value: Any) -> str:
    return " ".join(str(value if value is not None else "").strip().split())


def clean_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [clean_inline(item) for item in value if clean_inline(item)]
    text = clean_inline(value)
    return [text] if text else []


def parse_optional_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def first_list_value(*values: Any) -> list[Any]:
    for value in values:
        if isinstance(value, list):
            return value
    return []


def hosted_local_ledger_guidance(tool: str, run_id: str = "") -> dict[str, Any]:
    return {
        "generatedAt": generated_at(),
        "status": "local_required",
        "mode": "hosted",
        "tool": tool,
        "runId": clean_inline(run_id),
        "code": "HOSTED_RUNTIME_LEDGER_IS_LOCAL",
        "message": "Hosted Nogra is the living guide and stateless judge, not the runtime ledger. Read and write the customer workspace's local .nogra/ transport records instead.",
        "localLedger": {
            "run": ".nogra/transport/runs/<runId>.json",
            "report": ".nogra/transport/artifacts/<runId>/report.md",
            "output": ".nogra/transport/artifacts/<runId>/output.md",
            "events": ".nogra/transport/events.jsonl",
        },
        "playbookRefresh": "This installed Nogra playbook may be using the old hosted lifecycle-ledger pattern. Re-run /nogra init to refresh local guidance; preserve existing files unless the user explicitly approves overwrites.",
        "nextOwner": "ManagerClaude",
    }


def new_chain_id() -> str:
    return f"chain-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def hosted_supported_targets() -> list[str]:
    return ["agent"]


def normalize_hosted_target(target: str) -> tuple[str, dict[str, Any] | None]:
    normalized = clean_inline(target).lower().replace("-", "_")
    if not normalized:
        return "agent", None
    if normalized in {"agent", "agent_exec", "implementer"}:
        return "agent", None
    if normalized in {"codex", "codex_pm", "pm", "project_manager", "manager"}:
        return "", {
            "generatedAt": generated_at(),
            "status": "deferred_v1_5",
            "mode": "hosted",
            "receiptType": "dispatchReceipt",
            "code": "TARGET_NOT_IN_V1",
            "supportedTargets": hosted_supported_targets(),
            "error": "Hosted V1 dispatch targets the customer-owned agent role. Provider-specific PM adapters are deferred to v1.5.",
            "nextOwner": "ManagerClaude",
        }
    return "", {
        "generatedAt": generated_at(),
        "status": "unsupported",
        "mode": "hosted",
        "receiptType": "dispatchReceipt",
        "supportedTargets": hosted_supported_targets(),
        "error": f"unsupported hosted target: {target}",
        "nextOwner": "ManagerClaude",
    }


def resolve_hosted_brief(brief_id: str = "", brief: dict[str, Any] | None = None, brief_path: str = "") -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    server = public_server()
    cleaned_brief_id = clean_inline(brief_id)
    try:
        if isinstance(brief, dict) and brief:
            normalized = server.normalize_brief(brief, brief)
            inline_brief_id = str(normalized.get("briefId") or "")
            if cleaned_brief_id and inline_brief_id and cleaned_brief_id != inline_brief_id:
                return None, {
                    "generatedAt": generated_at(),
                    "status": "invalid",
                    "mode": "hosted",
                    "briefId": cleaned_brief_id,
                    "inlineBriefId": inline_brief_id,
                    "error": "brief_id does not match inline brief payload",
                }
            cleaned_brief_id = inline_brief_id or cleaned_brief_id
        elif cleaned_brief_id:
            return None, {
                "generatedAt": generated_at(),
                "status": "invalid",
                "mode": "hosted",
                "code": "INLINE_BRIEF_REQUIRED",
                "briefId": cleaned_brief_id,
                "error": "Hosted Nogra dispatch is stateless. Pass the full approved brief payload inline; brief_id is only a label for local records.",
                "localDraftPath": server.local_brief_draft_path(cleaned_brief_id),
                "localPromotedPath": server.local_promoted_brief_path(cleaned_brief_id),
                "nextOwner": "ManagerClaude",
            }
        else:
            hint = "brief_id or inline brief payload required in hosted mode"
            if clean_inline(brief_path):
                hint += "; brief_path is customer-local and cannot be read by hosted Nogra"
            return None, {"generatedAt": generated_at(), "status": "invalid", "mode": "hosted", "error": hint}
        server.validate_brief(normalized)
    except (ValueError, OSError, TypeError) as exc:
        return None, {"generatedAt": generated_at(), "status": "invalid", "mode": "hosted", "briefId": cleaned_brief_id, "error": str(exc)}
    return normalized, None


def hosted_target_model(brief: dict[str, Any], override: str = "") -> str:
    server = public_server()
    return clean_inline(override or brief.get("targetModel") or server.default_target_model())


def hosted_scope_files(brief: dict[str, Any]) -> list[str]:
    scope = brief.get("scope") if isinstance(brief.get("scope"), dict) else {}
    return [clean_inline(item) for item in scope.get("files", []) if clean_inline(item)] if isinstance(scope.get("files"), list) else []


def hosted_dispatch_receipt(
    *,
    receipt_type: str,
    target: str,
    brief_id: str = "",
    brief: dict[str, Any] | None = None,
    brief_path: str = "",
    manager_message: str = "",
    parent_run_id: str = "",
    intent_id: str = "",
    target_model: str = "",
    chain: bool = False,
) -> dict[str, Any]:
    normalized_target, target_error = normalize_hosted_target(target)
    if target_error:
        return target_error
    resolved_brief, brief_error = resolve_hosted_brief(brief_id=brief_id, brief=brief, brief_path=brief_path)
    if brief_error:
        brief_error.setdefault("receiptType", receipt_type)
        return brief_error
    assert resolved_brief is not None
    server = public_server()
    resolved_brief_id = str(resolved_brief.get("briefId") or "")
    model = hosted_target_model(resolved_brief, target_model)
    role = clean_inline(resolved_brief.get("targetRole")) or "Agent"
    chain_id = new_chain_id() if chain else ""
    metadata = {
        "mode": "hosted",
        "receiptType": receipt_type,
        "targetRole": role,
        "targetModel": model,
        "parentRunId": clean_inline(parent_run_id),
        "intentId": clean_inline(intent_id),
        "managerMessage": clean_inline(manager_message),
        "chainId": chain_id,
        "scopeFiles": hosted_scope_files(resolved_brief),
        "successCriteria": resolved_brief.get("successCriteria", []),
        "stopCriteria": resolved_brief.get("stopCriteria", []),
        "nextOwner": "ManagerSpawnsEphemeralExecutor",
    }
    run = server.transport_register_run(target=normalized_target, brief_id=resolved_brief_id, metadata=metadata)
    local_writes, local_write_policy = take_local_writes(run)
    run_id = str(run.get("runId") or "")
    event_type = "hosted_chain_started" if chain else "hosted_dispatch_receipt_created"
    event = server.transport_event_record(
        run_id,
        event_type,
        chainId=chain_id,
        target=normalized_target,
        targetRole=role,
        targetModel=model,
        briefId=resolved_brief_id,
        nextOwner="ManagerClaude",
    )
    local_writes.append(server.local_transport_event_write(event))
    receipt: dict[str, Any] = {
        "generatedAt": generated_at(),
        "status": "ready",
        "mode": "hosted",
        "receiptType": receipt_type,
        "runId": run_id,
        "briefId": resolved_brief_id,
        "target": normalized_target,
        "targetRole": role,
        "targetModel": model,
        "transport": {
            "armed": True,
            "validateCompletionTool": "transport_validate_completion",
            "ledger": "local .nogra/",
            "runtime": "customer-side ephemeral subagent",
            "reportPersistence": "Manager writes report/output/run/event records locally after the executor returns.",
            "localArtifacts": {
                "run": ".nogra/transport/runs/<runId>.json",
                "report": ".nogra/transport/artifacts/<runId>/report.md",
                "output": ".nogra/transport/artifacts/<runId>/output.md",
                "events": ".nogra/transport/events.jsonl",
            },
        },
        "executionCrossing": {
            "required": True,
            "managerMayImplement": False,
            "nextStep": "Fetch handoff_contract(kind='executor'), then spawn Claude Code's built-in general-purpose subagent with the returned handoff contract and the full approved brief.",
            "ifUnavailable": "Stop and surface the missing primitive. Do not execute inline, offer synchronous fallback, call private Agent Exec, or use a local/private Nogra runtime.",
        },
        "brief": resolved_brief,
        "run": run,
        "nextOwner": "ManagerSpawnsEphemeralExecutor",
    }
    if chain_id:
        receipt["chainId"] = chain_id
    if parent_run_id:
        receipt["parentRunId"] = clean_inline(parent_run_id)
    if intent_id:
        receipt["intentId"] = clean_inline(intent_id)
    return attach_local_writes(receipt, local_writes, local_write_policy)


def normalize_repo_path(value: Any, repo_root: str = "") -> tuple[str, str]:
    raw = str(value if value is not None else "").strip()
    if not raw:
        return "", "empty path"
    path = raw.replace("\\", "/")
    root = repo_root.replace("\\", "/").rstrip("/")
    if root and path.startswith(root + "/"):
        path = path[len(root) + 1 :]
    if len(path) > 1 and path[1] == ":":
        path = path[2:]
    path = path.lstrip("/")
    while path.startswith("./"):
        path = path[2:]
    parts = [part for part in path.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        return "", f"path escapes scope: {raw}"
    normalized = "/".join(parts)
    if not normalized:
        return "", "empty path"
    return normalized, ""


def normalize_path_list(values: Any, repo_root: str = "") -> tuple[list[str], list[dict[str, str]]]:
    if not isinstance(values, list):
        return [], [{"path": "", "error": "expected list"}]
    normalized: list[str] = []
    errors: list[dict[str, str]] = []
    for item in values:
        path, error = normalize_repo_path(item, repo_root=repo_root)
        if error:
            errors.append({"path": str(item), "error": error})
        elif path not in normalized:
            normalized.append(path)
    return normalized, errors


def scope_pattern_matches(path: str, pattern: str) -> bool:
    if path == pattern or path.endswith("/" + pattern):
        return True
    if fnmatch.fnmatchcase(path, pattern) or PurePosixPath(path).match(pattern):
        return True
    parts = path.split("/")
    for index in range(1, len(parts)):
        suffix = "/".join(parts[index:])
        if suffix == pattern or fnmatch.fnmatchcase(suffix, pattern) or PurePosixPath(suffix).match(pattern):
            return True
    return False


def is_nogra_protocol_artifact(path: str) -> bool:
    protocol_prefixes = (
        ".nogra/briefs/",
        ".nogra/events/",
        ".nogra/runs/",
        ".nogra/receipts/",
        ".nogra/transport/",
    )
    return any(path.startswith(prefix) for prefix in protocol_prefixes)


def normalize_optional_path_list(values: Any, repo_root: str = "") -> tuple[list[str], list[dict[str, str]]]:
    if values in (None, ""):
        return [], []
    if not isinstance(values, list):
        return [], [{"path": "", "error": "expected list"}]
    return normalize_path_list(values, repo_root=repo_root)


def acceptance_verification(acceptance: Any, success_criteria: Any) -> tuple[str, list[str]]:
    if not isinstance(acceptance, list) or not acceptance:
        return ("afvigelse", ["acceptance evidence missing"]) if isinstance(success_criteria, list) and success_criteria else ("ship", [])
    notes: list[str] = []
    verification = "ship"
    blocked = {"blocked", "failed", "fail", "not_met", "not met"}
    partial = {"partial", "unknown", "needs_review", "needs review", "afvigelse"}
    decision = {"decision_required", "beslutning_kraeves", "decision required"}
    for item in acceptance:
        status = clean_inline(item.get("status") if isinstance(item, dict) else item).lower()
        criterion = clean_inline(item.get("criterion") if isinstance(item, dict) else "")
        if status in decision:
            verification = "beslutning_kraeves"
            notes.append(criterion or "decision required")
        elif status in blocked:
            return "blocked", [criterion or "acceptance blocked"]
        elif status in partial and verification == "ship":
            verification = "afvigelse"
            notes.append(criterion or "partial acceptance")
    return verification, notes


def hosted_validate_completion(run_id: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    server = public_server()
    evidence = evidence if isinstance(evidence, dict) else {}
    run = parse_optional_json_object(evidence.get("run"))
    resolved_run_id = clean_inline(run_id or evidence.get("runId") or evidence.get("run_id") or run.get("runId") or run.get("run_id"))
    if not resolved_run_id:
        return {"generatedAt": generated_at(), "status": "invalid", "mode": "hosted", "error": "run_id required"}
    try:
        server.transport_safe_run_id(resolved_run_id)
    except ValueError as exc:
        return {"generatedAt": generated_at(), "status": "invalid", "mode": "hosted", "runId": resolved_run_id, "error": str(exc)}
    if not evidence:
        return {"generatedAt": generated_at(), "status": "invalid", "mode": "hosted", "runId": resolved_run_id, "error": "evidence object required in hosted mode"}
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    if isinstance(run.get("metadata"), str):
        metadata = {**metadata, **parse_optional_json_object(run["metadata"])}
    if isinstance(evidence.get("metadata"), dict):
        metadata = {**metadata, **evidence["metadata"]}
    if isinstance(evidence.get("metadata"), str):
        metadata = {**metadata, **parse_optional_json_object(evidence["metadata"])}
    brief = (
        parse_optional_json_object(evidence.get("brief"))
        or parse_optional_json_object(evidence.get("briefPayload"))
        or parse_optional_json_object(evidence.get("brief_payload"))
    )
    brief_id = clean_inline(
        evidence.get("briefId")
        or evidence.get("brief_id")
        or run.get("briefId")
        or run.get("brief_id")
        or brief.get("briefId")
        or brief.get("brief_id")
        or brief.get("id")
    )
    scope_files_raw = first_list_value(
        evidence.get("scopeFiles"),
        evidence.get("scope_files"),
        metadata.get("scopeFiles"),
        metadata.get("scope_files"),
    )
    if not scope_files_raw and isinstance(brief, dict):
        scope_files_raw = hosted_scope_files(brief)
    repo_root = clean_inline(evidence.get("repoRoot") or evidence.get("repo_root") or evidence.get("projectDir") or evidence.get("project_dir"))
    scope_files, scope_errors = normalize_path_list(scope_files_raw, repo_root=repo_root)
    changed_raw = evidence.get("filesChanged", evidence.get("files_changed"))
    files_changed_raw, changed_errors = normalize_path_list(changed_raw, repo_root=repo_root)
    protocol_raw = (
        evidence.get("protocolFilesChanged")
        or evidence.get("protocol_files_changed")
        or evidence.get("controlPlaneWrites")
        or evidence.get("control_plane_writes")
        or evidence.get("nograArtifacts")
        or evidence.get("nogra_artifacts")
    )
    protocol_files_explicit, protocol_errors = normalize_optional_path_list(protocol_raw, repo_root=repo_root)
    for path in list(protocol_files_explicit):
        if not is_nogra_protocol_artifact(path):
            protocol_errors.append({"path": path, "error": "not a Nogra protocol artifact"})
            protocol_files_explicit.remove(path)
    protocol_files = [path for path in files_changed_raw if is_nogra_protocol_artifact(path)]
    for path in protocol_files_explicit:
        if path not in protocol_files:
            protocol_files.append(path)
    files_changed = [path for path in files_changed_raw if not is_nogra_protocol_artifact(path)]
    report_text = clean_inline(evidence.get("reportText") or evidence.get("report_text") or evidence.get("report"))
    out_of_scope = [path for path in files_changed if not any(scope_pattern_matches(path, pattern) for pattern in scope_files)]
    success_criteria = evidence.get("successCriteria") if isinstance(evidence.get("successCriteria"), list) else metadata.get("successCriteria")
    if not isinstance(success_criteria, list) and isinstance(brief, dict):
        success_criteria = brief.get("successCriteria", [])
    verification, notes = acceptance_verification(evidence.get("acceptance"), success_criteria)
    deviations = (
        clean_text_list(evidence.get("briefDeviations"))
        or clean_text_list(evidence.get("deviations"))
        or clean_text_list(evidence.get("mismatches"))
    )
    errors = [*scope_errors, *changed_errors, *protocol_errors]
    if not report_text:
        verification = "blocked"
        notes.append("reportText missing")
    if not scope_files:
        verification = "blocked"
        notes.append("brief scope.files required for hosted validation")
    if errors:
        verification = "blocked"
        notes.append("invalid path evidence")
    if out_of_scope:
        verification = "blocked"
        notes.append("out-of-scope changes detected")
    if deviations and verification == "ship":
        verification = "afvigelse"
        notes.extend([f"brief deviation: {item}" for item in deviations])
    if evidence.get("decisionRequired") is True and verification != "blocked":
        verification = "beslutning_kraeves"
    status_by_verification = {
        "ship": "ok",
        "afvigelse": "partial",
        "beslutning_kraeves": "partial",
        "blocked": "blocked",
    }
    validation = {
        "generatedAt": generated_at(),
        "status": status_by_verification.get(verification, "partial"),
        "mode": "hosted",
        "runId": resolved_run_id,
        "briefId": brief_id,
        "verification": verification,
        "reportPresent": bool(report_text),
        "scopeFiles": scope_files,
        "filesChanged": files_changed,
        "evidenceFilesChanged": files_changed_raw,
        "protocolFilesChanged": protocol_files,
        "outOfScope": out_of_scope,
        "invalidPaths": errors,
        "commandsRun": evidence.get("commandsRun", evidence.get("commands_run", [])),
        "acceptance": evidence.get("acceptance", []),
        "deviations": deviations,
        "notes": notes,
        "localLedger": "run state is customer-local; hosted validation does not read or overwrite .nogra/transport/runs/<runId>.json",
        "nextOwner": "ManagerClaude",
    }
    event = {
        "schema": server.TRANSPORT_EVENT_SCHEMA,
        "releaseVersion": server.RELEASE_VERSION,
        "eventId": f"transport-event-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}",
        "generatedAt": validation["generatedAt"],
        "createdAt": validation["generatedAt"],
        "workspaceId": server.workspace_label(),
        "runId": resolved_run_id,
        "type": "transport_completion_validated",
        "verification": verification,
        "deviations": deviations,
        "outOfScope": out_of_scope,
        "invalidPaths": errors,
        "protocolFilesChanged": protocol_files,
    }
    validation["event"] = event
    validation_record = dict(validation)
    local_writes = [server.local_transport_event_write(event)]
    local_writes.append(
        server.local_write_json(
            server.local_transport_artifact_path(resolved_run_id, "validation.json"),
            validation_record,
            "Persist hosted completion validation locally.",
        )
    )
    return attach_local_writes(validation, local_writes)


def extension_metadata() -> dict[str, Any]:
    server = public_server()
    return {
        "name": "nogra-runtime-module",
        "version": server.RELEASE_VERSION,
        "releaseVersion": server.RELEASE_VERSION,
        "visibility": "public",
        "status": "ready",
        "tools": runtime_tool_names(),
        "resources": [],
        "boundary": "General Nogra dispatch and Transport runtime tools.",
        "module": "nogra_mcp.runtime",
    }


def register(mcp: Any, runtime: Any) -> None:
    from pydantic import Field

    runtime_mcp = None if hosted_mode() else load_runtime_module()

    @mcp.tool(name="chain_pm_then_agent")
    def chain_pm_then_agent(
        project_dir: str = Field(default=str(repo_root()), description="Existing project directory where the PM and Agent phases run."),
        brief_path: str = Field(default="", description="Approved brief path. Required for chain dispatch."),
        brief_id: str = Field(default="", description="Optional hosted brief id from the Nogra brief lifecycle. Inline brief payload is preferred when available."),
        brief: dict[str, Any] = Field(default_factory=dict, description="Approved inline brief payload for hosted/stateless dispatch. Preferred when available because hosted storage is not authority."),
        manager_message: str = Field(default="", description="Optional Manager instruction or supplement passed to both chain phases."),
        intent_id: str = Field(default="", description="Optional intent id forwarded to Agent for run-graph linkage."),
        targetModel: str = Field(default="", description="Optional targetModel override. Blank uses the brief value or anthropic:sonnet."),
        timeout_per_phase_seconds: int = Field(default=900, description="Maximum runtime per chain phase (PM execute, Agent execute) in seconds."),
    ) -> dict[str, Any]:
        """Chain PM -> Agent under a single chain id with persistent chain-state."""
        if hosted_mode():
            return hosted_dispatch_receipt(
                receipt_type="chainDispatchReceipt",
                target="agent",
                brief_id=brief_id,
                brief=brief,
                brief_path=brief_path,
                manager_message=manager_message,
                intent_id=intent_id,
                target_model=targetModel,
                chain=True,
            )
        try:
            return runtime_mcp.run_chain_pm_then_agent(
                project_dir=project_dir,
                brief_path=brief_path,
                manager_message=manager_message,
                intent_id=intent_id,
                timeout_per_phase_seconds=timeout_per_phase_seconds,
            )
        except (FileNotFoundError, PermissionError, ValueError) as exc:
            return {
                "generatedAt": runtime_mcp.now(),
                "status": "invalid",
                "tool": "chain_pm_then_agent",
                "error": str(exc),
            }

    @mcp.tool(name="transport_dispatch")
    def transport_dispatch(
        target: str = Field(default="", description="Workflow target role. Hosted V1 uses agent; blank uses the environment default."),
        project_dir: str = Field(default=str(repo_root()), description="Existing project directory used as the target working directory. Default is the y26 repo root."),
        brief_path: str = Field(default="", description="Approved local brief path for non-hosted/private dispatch."),
        brief_id: str = Field(default="", description="Optional hosted brief id from the Nogra brief lifecycle. Inline brief payload is preferred when available."),
        brief: dict[str, Any] = Field(default_factory=dict, description="Approved inline brief payload for hosted/stateless dispatch. Preferred when available because hosted storage is not authority."),
        manager_message: str = Field(default="", description="Optional Manager instruction or supplement."),
        timeout_seconds: int = Field(default=600, description="Maximum target runtime in seconds before Transport treats the run as timed out."),
        sandbox: str = Field(default="", description="Optional sandbox override passed to the selected local runtime in non-hosted/private mode."),
        wait: bool = Field(default=False, description="If true, block until Transport returns or times out in non-hosted/private mode."),
        wait_seconds: int = Field(default=0, description="Optional wait duration in seconds when wait is true. Zero uses timeout_seconds plus the runtime grace period."),
        dry_run: bool = Field(default=False, description="If true, write dispatch packet/receipt previews without invoking the target process."),
        parent_run_id: str = Field(default="", description="Optional parent Transport run id for child graph linkage."),
        intent_id: str = Field(default="", description="Optional stable intent id used to group related runs."),
        targetModel: str = Field(default="", description="Optional targetModel override. Blank uses the brief value or anthropic:sonnet."),
        shared_doctrine_refs: str = Field(default="", description="Optional comma- or newline-separated doctrine reference paths for local execution packets; blank supplies none."),
    ) -> dict[str, Any]:
        """Dispatch a workflow target through Nogra Transport."""
        if hosted_mode():
            return hosted_dispatch_receipt(
                receipt_type="dispatchReceipt",
                target=target,
                brief_id=brief_id,
                brief=brief,
                brief_path=brief_path,
                manager_message=manager_message,
                parent_run_id=parent_run_id,
                intent_id=intent_id,
                target_model=targetModel,
                chain=False,
            )
        if clean_inline(brief_id) or brief:
            return {
                "generatedAt": generated_at(),
                "status": "invalid",
                "mode": "local",
                "code": "HOSTED_DISPATCH_CALLED_ON_LOCAL_MCP",
                "error": "transport_dispatch received hosted/plugin-style inputs on a local/non-hosted Nogra server. A local/private MCP server is still registered as 'nogra' and is winning over the plugin-managed hosted MCP.",
                "resolution": "Reserve 'nogra' for the public hosted/plugin MCP. Move local/private development to 'nogra-dev', restart Claude Code with the Nogra plugin loaded, then retry dispatch.",
                "nextOwner": "ManagerClaude",
            }
        normalized_target = target.strip().lower().replace("-", "_") or "codex_pm"
        if normalized_target in {"codex", "codex_pm"}:
            return runtime_mcp.run_transport_codex_dispatch(
                project_dir=project_dir,
                brief_path=brief_path,
                manager_message=manager_message,
                dry_run=dry_run,
                timeout_seconds=timeout_seconds,
                sandbox=sandbox,
                wait=wait,
                wait_seconds=wait_seconds,
            )
        if normalized_target in {"agent", "agent_exec"}:
            return runtime_mcp.run_transport_agent_exec_dispatch(
                project_dir=project_dir,
                brief_path=brief_path,
                manager_message=manager_message,
                dry_run=dry_run,
                timeout_seconds=timeout_seconds,
                sandbox=sandbox,
                wait=wait,
                wait_seconds=wait_seconds,
                parent_run_id=parent_run_id,
                intent_id=intent_id,
                shared_doctrine_refs=shared_doctrine_refs,
            )
        return {
            "generatedAt": runtime_mcp.now(),
            "status": "unsupported",
            "target": target,
            "supportedTargets": ["codex_pm", "agent_exec"],
        }

    @mcp.tool(name="agent_exec_packet")
    def agent_exec_packet(
        project_dir: str = Field(description="Existing project directory used to resolve the approved brief and Agent Exec write boundary."),
        brief_path: str = Field(description="Approved brief path required for Agent Exec. The path is resolved against project_dir when relative."),
        manager_message: str = Field(default="", description="Optional Manager/PM supplement included in the packet; it does not replace brief authority."),
        sandbox: str = Field(default="", description="Optional sandbox mode recorded in the Agent Exec packet. Empty uses the agent role default sandbox."),
        parent_run_id: str = Field(default="", description="Optional parent PM/Transport run id embedded in the packet for run graph linkage."),
        intent_id: str = Field(default="", description="Optional stable intent id embedded in the packet for grouping related runs."),
        shared_doctrine_refs: str = Field(default="", description="Optional comma- or newline-separated doctrine reference paths resolved into sharedDoctrine; blank supplies none."),
    ) -> dict[str, Any]:
        """Build an Agent Exec dispatch packet without invoking execution."""
        if hosted_mode():
            return {
                "generatedAt": generated_at(),
                "status": "unsupported",
                "mode": "hosted",
                "code": "LOCAL_PACKET_ONLY",
                "error": "Hosted V1 uses dispatch receipts; local execution packets are customer-side.",
                "nextOwner": "ManagerClaude",
            }
        try:
            return runtime_mcp.agent_exec_packet_payload(
                project_dir=project_dir,
                brief_path=brief_path,
                manager_message=manager_message,
                sandbox=sandbox,
                parent_run_id=parent_run_id,
                intent_id=intent_id,
                shared_doctrine_refs=shared_doctrine_refs,
            )
        except (FileNotFoundError, PermissionError, ValueError) as exc:
            return {
                "generatedAt": runtime_mcp.now(),
                "status": "invalid",
                "target": "agent_exec",
                "error": str(exc),
            }

    @mcp.tool(name="transport_submit_report")
    def transport_submit_report(
        run_id: str = Field(default="", description="Transport run id. Hosted mode requires it so Manager can update local .nogra records."),
        report_text: str = Field(default="", description="Complete structured report markdown. Hosted mode returns local-ledger guidance instead of persisting it."),
        report: str = Field(default="", description="Alias for report_text. Use when the client naturally sends report instead of report_text."),
        status: str = Field(default="", description="Optional submitted run status such as ok, partial, blocked, or failed. Aliases complete/completed/succeeded map to ok."),
        summary: str = Field(default="", description="Optional one-line summary for the local transport event trail."),
        output_text: str = Field(default="", description="Optional final output text for output.md. Hosted mode returns the local output path to write."),
        allow_overwrite: bool = Field(default=False, description="Non-hosted only: replace an existing non-empty report artifact when true."),
    ) -> dict[str, Any]:
        """Submit a Transport report in non-hosted mode; hosted mode returns local-ledger guidance."""
        resolved_report_text = report_text if report_text.strip() else report
        if hosted_mode():
            server = public_server()
            resolved_run_id = clean_inline(run_id)
            if not resolved_run_id:
                return {"generatedAt": generated_at(), "status": "invalid", "mode": "hosted", "tool": "transport_submit_report", "error": "run_id required"}
            try:
                server.transport_safe_run_id(resolved_run_id)
            except ValueError as exc:
                return {"generatedAt": generated_at(), "status": "invalid", "mode": "hosted", "tool": "transport_submit_report", "runId": resolved_run_id, "error": str(exc)}
            if not resolved_report_text.strip():
                return {"generatedAt": generated_at(), "status": "invalid", "mode": "hosted", "tool": "transport_submit_report", "runId": resolved_run_id, "error": "report_text required"}
            normalized_status = server.normalize_transport_status(status)
            if normalized_status and normalized_status not in server.TRANSPORT_STATUSES:
                return {**server.transport_status_invalid(resolved_run_id, normalized_status), "generatedAt": generated_at(), "mode": "hosted", "tool": "transport_submit_report"}
            payload = hosted_local_ledger_guidance("transport_submit_report", resolved_run_id)
            payload.update(
                {
                    "status": "local_required",
                    "reportTextReceived": True,
                    "summary": clean_inline(summary),
                    "submittedStatus": normalized_status,
                    "localPersistence": {
                        "report": f".nogra/transport/artifacts/{resolved_run_id}/report.md",
                        "output": f".nogra/transport/artifacts/{resolved_run_id}/output.md",
                        "run": f".nogra/transport/runs/{resolved_run_id}.json",
                        "events": ".nogra/transport/events.jsonl",
                    },
                    "requiredLocalRunMerge": {
                        "updatedAt": "current ISO timestamp",
                        "phase": "returning",
                        "reportSubmittedAt": "current ISO timestamp",
                        "status": normalized_status or "executor status",
                        "summary": "executor summary",
                        "completedAt": "current ISO timestamp only when status is terminal",
                    },
                }
            )
            return payload
        return runtime_mcp.transport_submit_report_runtime(
            run_id=run_id,
            report_text=resolved_report_text,
            status=status,
            summary=summary,
            output_text=output_text,
            allow_overwrite=allow_overwrite,
            source="mcp",
        )

    @mcp.tool(name="transport_validate_completion")
    def transport_validate_completion(
        run_id: str = Field(description="Transport run id to validate after target exit."),
        evidence: dict[str, Any] = Field(default_factory=dict, description="Hosted completion evidence: reportText, scopeFiles or embedded brief, customer filesChanged, optional protocolFilesChanged, commandsRun, and acceptance results."),
    ) -> dict[str, Any]:
        """Validate completion from inline hosted evidence or non-hosted runtime records."""
        if hosted_mode():
            return hosted_validate_completion(run_id=run_id, evidence=evidence)
        return load_transport_runtime_module().validate_completion(run_id=run_id)

    @mcp.tool(name="transport_status")
    def transport_status(
        run_id: str = Field(default="", description="Optional Transport run id. Hosted mode returns local-ledger guidance."),
        include_archive: bool = Field(default=False, description="Non-hosted only: include archived run state when loading or listing runs."),
        limit: int = Field(default=20, description="Non-hosted only: maximum number of recent runs to return when run_id is blank."),
    ) -> dict[str, Any]:
        """Read non-hosted Transport run state; hosted mode returns local-ledger guidance."""
        if hosted_mode():
            return hosted_local_ledger_guidance("transport_status", run_id)
        if run_id.strip():
            record = runtime_mcp.transport_load_run(run_id.strip(), include_archive=include_archive)
            return runtime_mcp.transport_public_run(record) if record else {"generatedAt": runtime_mcp.now(), "status": "missing", "runId": run_id}
        return {
            "generatedAt": runtime_mcp.now(),
            "status": "ok",
            "runs": runtime_mcp.transport_recent_runs(limit=limit, include_archive=include_archive),
        }

    @mcp.tool(name="transport_events")
    def transport_events(
        run_id: str = Field(default="", description="Optional Transport run id filter. Hosted mode returns local-ledger guidance."),
        limit: int = Field(default=80, description="Non-hosted only: maximum number of recent ledger events to return after filtering."),
    ) -> dict[str, Any]:
        """Read non-hosted Transport events; hosted mode returns local-ledger guidance."""
        if hosted_mode():
            return hosted_local_ledger_guidance("transport_events", run_id)
        return {
            "generatedAt": runtime_mcp.now(),
            "status": "ok",
            "events": runtime_mcp.transport_read_events(limit=limit, run_id=run_id),
        }

    @mcp.tool(name="transport_return")
    def transport_return(
        run_id: str = Field(default="", description="Optional Transport run id. Hosted mode returns local-ledger guidance."),
        include_text: bool = Field(default=True, description="Non-hosted only: include reportText and outputText read from artifact files."),
    ) -> dict[str, Any]:
        """Return non-hosted report/output payload; hosted mode returns local-ledger guidance."""
        if hosted_mode():
            return hosted_local_ledger_guidance("transport_return", run_id)
        return runtime_mcp.transport_return_payload(run_id=run_id, include_text=include_text)

    @mcp.tool(name="transport_watch")
    def transport_watch(
        run_id: str = Field(description="Transport run id. Hosted mode returns local-ledger guidance."),
        wait_seconds: int = Field(default=900, description="Non-hosted only: maximum seconds to wait for a returnable status."),
    ) -> dict[str, Any]:
        """Wait for a non-hosted Transport run; hosted mode returns local-ledger guidance."""
        if hosted_mode():
            return hosted_local_ledger_guidance("transport_watch", run_id)
        return runtime_mcp.transport_wait_for_run(run_id=run_id, wait_seconds=wait_seconds)

    @mcp.tool(name="transport_ack")
    def transport_ack(
        run_id: str = Field(default="", description="Optional Transport run id. Hosted mode returns local-ledger guidance."),
        note: str = Field(default="", description="Non-hosted only: optional Manager acknowledgement note stored on the run."),
    ) -> dict[str, Any]:
        """Acknowledge a non-hosted Transport run; hosted mode returns local-ledger guidance."""
        if hosted_mode():
            return hosted_local_ledger_guidance("transport_ack", run_id)
        return runtime_mcp.transport_ack_run(run_id=run_id, note=note)

    @mcp.tool(name="transport_cleanup")
    def transport_cleanup(
        archive_after_hours: float = Field(default=24, description="Non-hosted only: archive returned runs older than this many hours."),
        orphan_after_seconds: int = Field(default=900, description="Non-hosted only: mark inactive runs orphaned after this many seconds."),
        max_events: int = Field(default=5000, description="Non-hosted only: keep this many recent Transport events before rotating."),
        max_log_bytes: int = Field(default=0, description="Non-hosted only: gzip completed run logs above this byte size."),
        dry_run: bool = Field(default=False, description="Non-hosted only: return planned cleanup actions without mutating state."),
    ) -> dict[str, Any]:
        """Clean non-hosted Transport state; hosted mode returns local-ledger guidance."""
        if hosted_mode():
            return hosted_local_ledger_guidance("transport_cleanup")
        return runtime_mcp.transport_cleanup_state(
            archive_after_hours=archive_after_hours,
            orphan_after_seconds=orphan_after_seconds,
            max_events=max_events,
            max_log_bytes=max_log_bytes,
            dry_run=dry_run,
        )
