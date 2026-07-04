#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .registry import registry_payload
from .transport_runtime import (
    ack_run as transport_ack_run,
    append_event as transport_append_event,
    cleanup as transport_cleanup_state,
    merge_receipt_context as transport_merge_receipt_context,
    mirror_output_to_report as transport_mirror_output_to_report,
    read_events as transport_read_events,
    recent_runs as transport_recent_runs,
    register_run as transport_register_run,
    return_payload as transport_return_payload,
    spawn_watcher as transport_spawn_watcher,
    submit_report as transport_submit_report_runtime,
    wait_for_run as transport_wait_for_run,
    load_run as transport_load_run,
    public_run as transport_public_run,
)


def _resolve_default_root() -> Path:
    # Assumes a dev/private checkout depth (src/nogra_mcp/runtime_server.py
    # -> parents[4] is the workspace root). A frozen PyInstaller onefile binary
    # self-extracts to a shallow throwaway dir per run (e.g. Linux /tmp/_MEIxxxx
    # has only 4 ancestors, indices 0-3) where this walk is out of range --
    # and there is no real host control-plane to find there anyway, since this
    # module is host-only machinery (see BOUNDARY.md). Fall back to the
    # shallowest available ancestor instead of raising: on a real deep
    # checkout this branch never triggers (index 4 is always present), so
    # host/dev behavior is unchanged.
    parents = Path(__file__).resolve().parents
    index = 4
    return parents[index] if index < len(parents) else parents[-1]


DEFAULT_ROOT = _resolve_default_root()
ROOT = Path(os.environ.get("NOGRA_ROOT") or os.environ.get("Y26_ROOT") or str(DEFAULT_ROOT)).resolve()
PRODUCT_NAME = os.environ.get("NOGRA_PRODUCT_NAME") or os.environ.get("Y26_PRODUCT_NAME", "Nogra")
CALLER_LABEL = os.environ.get("NOGRA_CALLER_LABEL") or os.environ.get("Y26_CALLER_LABEL", "CEO")
CHAT_DIR = ROOT / "manager" / "chat"
CLAUDE_PROJECTS_DIR = Path(
    os.environ.get("NOGRA_CLAUDE_PROJECTS_DIR")
    or os.environ.get("Y26_CLAUDE_PROJECTS_DIR")
    or str(Path.home() / ".claude" / "projects")
).expanduser()
REFERENCE_DIR = ROOT / "manager" / "reference"
RUNS_DIR = ROOT / "manager" / "agent-runs"
CHAIN_STATE_DIR = ROOT / "manager" / "state" / "transport" / "chains"
PROMOTED_BRIEFS_DIR = ROOT / "manager" / "docs" / "briefs"
BRIEF_DRAFTS_DIR = ROOT / "manager" / "state" / "pinboard" / "brief-drafts"
BRIEF_DISPATCH_FLOW_REF = "manager/reference/brief-dispatch-flow.md"
BRIEF_PROMOTE_ERROR = (
    "Brief skal promoves før chain dispatch. Quickest path: "
    f"manager/bin/brief from-file <markdown_path> --promote. Detaljeret flow: {BRIEF_DISPATCH_FLOW_REF}."
)
BRIEF_FRONTMATTER_FIX = (
    "Brief mangler påkrævet frontmatter (scope_files, project_dir). Quickest fix: "
    "re-run via manager/bin/brief from-file <path> --promote for at autopopulere fra markdown-struktur."
)
TRANSCRIPT_LIMIT = int(os.environ.get("NOGRA_MCP_TRANSCRIPT_LIMIT") or os.environ.get("Y26_MCP_TRANSCRIPT_LIMIT", "220000"))
CODEX_BIN = os.environ.get("CODEX_BIN") or shutil.which("codex") or str(Path.home() / ".npm-global" / "bin" / "codex")
CODEX_MODEL = os.environ.get("NOGRA_CODEX_MODEL") or os.environ.get("Y26_CODEX_MODEL", "gpt-5.4")
CODEX_MCP_NAME = os.environ.get("NOGRA_CODEX_MCP_NAME") or os.environ.get("Y26_CODEX_MCP_NAME", "nogra-dev")
NOGRA_MCP_BIN = os.environ.get("NOGRA_MCP_BIN") or os.environ.get("Y26_MCP_BIN") or str(ROOT / "manager" / "bin" / "nogra-mcp")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
GEMINI_BIN = os.environ.get("GEMINI_BIN") or shutil.which("gemini") or str(Path.home() / ".npm-global" / "bin" / "gemini")
ROLE_CONFIG_FILE = Path(
    os.environ.get("NOGRA_ROLE_CONFIG")
    or os.environ.get("Y26_ROLE_CONFIG")
    or str(ROOT / "manager" / "nogra-mcp" / "roles.json")
).expanduser()
SETTINGS_FILE = Path(
    os.environ.get("NOGRA_SETTINGS_PATH")
    or os.environ.get("Y26_SETTINGS_PATH")
    or str(Path.home() / ".config" / "nogra" / "settings.json")
).expanduser()
BRIEF_META_BIN = ROOT / ".claude" / "hooks" / "brief_meta.py"
SETTINGS_MERGE_BIN = ROOT / "manager" / "bin" / "merge-claude-settings.py"
ROOT_CLAUDE_SETTINGS = ROOT / ".claude" / "settings.json"
ADAPTER_RUNNER_BIN = ROOT / "manager" / "nogra-mcp" / "src" / "nogra_mcp" / "adapter_runner.py"
SUPPORTED_ROLE_ADAPTERS = {"claude_cli", "codex_cli", "gemini_cli"}
SUPPORTED_AGENT_ADAPTERS = SUPPORTED_ROLE_ADAPTERS


DEFAULT_ROLE_CONFIG: dict[str, Any] = {
    "version": 1,
    "principle": "Roles are workflow functions. Models are user-selected adapters behind those functions.",
    "roles": {
        "manager": {
            "role": "manager",
            "title": "Manager",
            "layer": "T2",
            "adapter": "claude_cli",
            "model": os.environ.get("NOGRA_MANAGER_MODEL") or os.environ.get("Y26_MANAGER_MODEL", "opus"),
            "sandboxDefault": "read-only",
            "authority": "meaning, judgment, routing and CEO-facing surface",
        },
        "orchestrator": {
            "role": "orchestrator",
            "title": "Orchestrator",
            "layer": "T3",
            "adapter": "claude_cli",
            "model": os.environ.get("NOGRA_ORCHESTRATOR_MODEL") or os.environ.get("Y26_ORCHESTRATOR_MODEL", "opus"),
            "sandboxDefault": "read-only",
            "authority": "transport routing, packets, run pointers and return-path preservation",
        },
        "project_manager": {
            "role": "project_manager",
            "title": "Project Manager",
            "layer": "T4",
            "adapter": "codex_cli",
            "model": CODEX_MODEL,
            "reasoning": "medium",
            "sandboxDefault": "workspace-write",
            "authority": "implementation shape, scoped code changes, verification, evidence return",
        },
        "agent": {
            "role": "agent",
            "title": "Agent Exec",
            "layer": "T5",
            "adapter": "claude_cli",
            "model": "sonnet",
            "effort": "low",
            "sandboxDefault": "workspace-write",
            "authority": "bounded execution inside an approved brief and write boundary",
        },
    },
}

BASELINE_ROLE_SLOTS = ["manager", "orchestrator", "project_manager", "agent"]
ROLE_ALIASES = {"pm": "project_manager", "codex_pm": "project_manager", "agent_exec": "agent"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def read_text(path: Path, limit: int | None = None) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"path": str(path), "exists": False, "error": str(exc), "text": ""}
    truncated = False
    if limit is not None and len(text) > limit:
        text = text[-limit:]
        truncated = True
    return {"path": str(path), "exists": True, "truncated": truncated, "text": text}


def read_json_file(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return json.loads(json.dumps(fallback))
    return payload if isinstance(payload, dict) else json.loads(json.dumps(fallback))


def file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def deep_merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(left))
    for key, value in right.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def canonical_role_key(role: str) -> str:
    cleaned = str(role or "").strip().lower().replace("-", "_")
    return ROLE_ALIASES.get(cleaned, cleaned)


def read_settings_payload() -> dict[str, Any]:
    if not SETTINGS_FILE.is_file():
        return {}
    return read_json_file(SETTINGS_FILE, {})


def settings_role_overrides(settings: dict[str, Any]) -> dict[str, Any]:
    for key in ("roles", "roleGrants", "role_grants", "slots"):
        value = settings.get(key)
        if isinstance(value, dict):
            return value
    return {}


def default_model_for_adapter(adapter: str) -> str:
    if adapter == "codex_cli":
        return CODEX_MODEL
    if adapter == "gemini_cli":
        return os.environ.get("NOGRA_GEMINI_MODEL") or os.environ.get("Y26_GEMINI_MODEL", "gemini-default")
    return "sonnet"


def adapter_binary(adapter: str) -> str:
    if adapter == "codex_cli":
        return CODEX_BIN
    if adapter == "gemini_cli":
        return GEMINI_BIN
    if adapter == "claude_cli":
        return CLAUDE_BIN
    return ""


def command_available(command: str) -> bool:
    if not command:
        return False
    return Path(command).exists() or shutil.which(command) is not None


def role_config_payload() -> dict[str, Any]:
    legacy_payload = read_json_file(ROLE_CONFIG_FILE, DEFAULT_ROLE_CONFIG)
    payload = deep_merge(DEFAULT_ROLE_CONFIG, legacy_payload)
    settings_payload = read_settings_payload()
    roles = payload.setdefault("roles", {})
    if isinstance(roles.get("pm"), dict):
        roles["project_manager"] = deep_merge(roles.get("project_manager", {}), roles["pm"])
        roles["project_manager"]["role"] = "project_manager"

    for raw_key, override in settings_role_overrides(settings_payload).items():
        if not isinstance(override, dict):
            continue
        key = canonical_role_key(raw_key)
        roles[key] = deep_merge(roles.get(key, {}), override)

    for slot in BASELINE_ROLE_SLOTS:
        default_role = DEFAULT_ROLE_CONFIG["roles"].get(slot, {})
        roles[slot] = deep_merge(default_role, roles.get(slot, {}))

    manager = roles.setdefault("manager", {})
    orchestrator = roles.setdefault("orchestrator", {})
    pm = roles.setdefault("project_manager", {})
    agent = roles.setdefault("agent", {})

    manager.setdefault("role", "manager")
    manager.setdefault("title", "Manager")
    manager.setdefault("layer", "T2")
    manager.setdefault("adapter", "claude_cli")
    manager["model"] = os.environ.get("NOGRA_MANAGER_MODEL") or os.environ.get("Y26_MANAGER_MODEL", str(manager.get("model") or "opus"))
    manager.setdefault("sandboxDefault", "read-only")
    manager["supportedAdapters"] = sorted(SUPPORTED_ROLE_ADAPTERS)

    orchestrator.setdefault("role", "orchestrator")
    orchestrator.setdefault("title", "Orchestrator")
    orchestrator.setdefault("layer", "T3")
    orchestrator.setdefault("adapter", "claude_cli")
    orchestrator["model"] = os.environ.get("NOGRA_ORCHESTRATOR_MODEL") or os.environ.get("Y26_ORCHESTRATOR_MODEL", str(orchestrator.get("model") or "opus"))
    orchestrator.setdefault("sandboxDefault", "read-only")
    orchestrator["supportedAdapters"] = sorted(SUPPORTED_ROLE_ADAPTERS)

    pm.setdefault("role", "project_manager")
    pm.setdefault("title", "Project Manager")
    pm.setdefault("layer", "T4")
    configured_pm_adapter = str(pm.get("adapter") or "codex_cli")
    pm["adapter"] = (
        os.environ.get("NOGRA_PROJECT_MANAGER_ADAPTER")
        or os.environ.get("Y26_PROJECT_MANAGER_ADAPTER")
        or os.environ.get("NOGRA_PM_ADAPTER")
        or os.environ.get("Y26_PM_ADAPTER")
        or configured_pm_adapter
    )
    if "NOGRA_PROJECT_MANAGER_MODEL" in os.environ:
        pm["model"] = os.environ["NOGRA_PROJECT_MANAGER_MODEL"]
    elif "Y26_PROJECT_MANAGER_MODEL" in os.environ:
        pm["model"] = os.environ["Y26_PROJECT_MANAGER_MODEL"]
    elif "NOGRA_PM_MODEL" in os.environ:
        pm["model"] = os.environ["NOGRA_PM_MODEL"]
    elif "Y26_PM_MODEL" in os.environ:
        pm["model"] = os.environ["Y26_PM_MODEL"]
    elif str(pm["adapter"]) == "codex_cli":
        pm["model"] = os.environ.get("NOGRA_CODEX_MODEL") or os.environ.get("Y26_CODEX_MODEL", str(pm.get("model") or CODEX_MODEL))
    elif pm["adapter"] != configured_pm_adapter:
        pm["model"] = default_model_for_adapter(str(pm["adapter"]))
    else:
        pm["model"] = str(pm.get("model") or default_model_for_adapter(str(pm["adapter"])))
    pm["reasoning"] = os.environ.get("NOGRA_CODEX_DISPATCH_REASONING") or os.environ.get("Y26_CODEX_DISPATCH_REASONING", str(pm.get("reasoning") or "medium"))
    pm.setdefault("sandboxDefault", "workspace-write")
    pm["supportedAdapters"] = sorted(SUPPORTED_ROLE_ADAPTERS)

    agent.setdefault("role", "agent")
    agent.setdefault("title", "Agent Exec")
    agent.setdefault("layer", "T5")
    configured_adapter = str(agent.get("adapter") or "claude_cli")
    agent["adapter"] = os.environ.get("NOGRA_AGENT_ADAPTER") or os.environ.get("Y26_AGENT_ADAPTER", configured_adapter)
    if "NOGRA_AGENT_MODEL" in os.environ:
        agent["model"] = os.environ["NOGRA_AGENT_MODEL"]
    elif "Y26_AGENT_MODEL" in os.environ:
        agent["model"] = os.environ["Y26_AGENT_MODEL"]
    elif agent["adapter"] != configured_adapter:
        agent["model"] = default_model_for_adapter(str(agent["adapter"]))
    else:
        agent["model"] = str(agent.get("model") or default_model_for_adapter(str(agent["adapter"])))
    agent["effort"] = os.environ.get("NOGRA_AGENT_EFFORT") or os.environ.get("Y26_AGENT_EFFORT", str(agent.get("effort") or "low"))
    agent.setdefault("sandboxDefault", "workspace-write")
    agent["supportedAdapters"] = sorted(SUPPORTED_ROLE_ADAPTERS)

    roles["pm"] = {**pm, "role": "pm", "aliasOf": "project_manager"}

    payload.update(
        {
            "generatedAt": now(),
            "configPath": str(SETTINGS_FILE),
            "settingsPath": str(SETTINGS_FILE),
            "settingsExists": SETTINGS_FILE.is_file(),
            "legacyConfigPath": str(ROLE_CONFIG_FILE),
            "settingsAuthority": "User/host settings outside dispatch project roots; runtime snapshots resolved grants into runs.",
            "authModel": "Roles do not own credentials. Each adapter uses the user's local logged-in client/OAuth.",
            "v1Scope": ["pm", "agent"],
            "v2Slots": BASELINE_ROLE_SLOTS,
            "supportedAdapters": sorted(SUPPORTED_ROLE_ADAPTERS),
            "supportedAgentAdapters": sorted(SUPPORTED_ROLE_ADAPTERS),
        }
    )
    return payload


def role_payload(role: str) -> dict[str, Any]:
    roles = role_config_payload().get("roles", {})
    value = roles.get(canonical_role_key(role))
    return dict(value) if isinstance(value, dict) else {}


def normalize_shared_doctrine_refs(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
        for chunk in str(value).replace(",", "\n").splitlines():
            raw_items.append(chunk)
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        cleaned = str(item).strip()
        if not cleaned or cleaned in seen:
            continue
        out.append(cleaned)
        seen.add(cleaned)
    return out


def finalized_transport_receipt(
    *,
    receipt: dict[str, Any],
    transport_record: dict[str, Any],
    returned: dict[str, Any],
    waited: dict[str, Any],
    receipt_file: Path,
    report_file: Path,
    log_file: Path,
    output_file: Path | None = None,
) -> dict[str, Any]:
    returned_receipt = returned.get("receipt") if isinstance(returned.get("receipt"), dict) else {}
    final_receipt = dict(receipt)
    if returned_receipt:
        final_receipt.update(returned_receipt)

    final_receipt = transport_merge_receipt_context(transport_record, final_receipt)
    next_owner = waited.get("nextOwner") or returned.get("nextOwner") or final_receipt.get("nextOwner") or "Manager"
    final_receipt.update(
        {
            "transportRun": waited,
            "transportReturn": {
                "runId": transport_record.get("runId", ""),
                "status": returned.get("status"),
                "nextOwner": next_owner,
            },
            "nextOwner": next_owner,
        }
    )
    if returned.get("reportText") and not final_receipt.get("reportText"):
        final_receipt["reportText"] = returned["reportText"]
    if returned.get("outputText") and not final_receipt.get("answer"):
        final_receipt["answer"] = returned["outputText"]
    final_receipt.setdefault("runId", transport_record.get("runId", ""))
    final_receipt.setdefault("runDir", str(receipt_file.parent))
    final_receipt.setdefault("receipt", str(receipt_file))
    final_receipt.setdefault("report", str(report_file))
    final_receipt.setdefault("log", str(log_file))
    if output_file is not None:
        final_receipt.setdefault("output", str(output_file))

    final_receipt = transport_merge_receipt_context(transport_record, final_receipt)
    final_receipt["nextOwner"] = next_owner
    try:
        receipt_file.write_text(json.dumps(final_receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return final_receipt


def resolve_reference(project: Path, ref: str) -> dict[str, Any]:
    path = Path(ref).expanduser()
    candidates = [path] if path.is_absolute() else [project / path, ROOT / path]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists():
            return {"ref": ref, "path": str(resolved), "exists": True}
    fallback = candidates[-1].resolve() if candidates else path.resolve()
    return {"ref": ref, "path": str(fallback), "exists": False}


def run(cmd: list[str], timeout: int = 10) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return {"ok": proc.returncode == 0, "code": proc.returncode, "output": proc.stdout.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "code": 1, "output": str(exc)}


def codex_mcp_config_args(run_id: str = "", target: str = "") -> list[str]:
    args = [
        "-c",
        f"mcp_servers.{CODEX_MCP_NAME}.command={json.dumps(NOGRA_MCP_BIN)}",
        "-c",
        f"mcp_servers.{CODEX_MCP_NAME}.env.NOGRA_ROOT={json.dumps(str(ROOT))}",
    ]
    if run_id:
        args.extend(
            [
                "-c",
                f"mcp_servers.{CODEX_MCP_NAME}.env.NOGRA_TRANSPORT_RUN_ID={json.dumps(run_id)}",
                "-c",
                f"mcp_servers.{CODEX_MCP_NAME}.env.Y26_TRANSPORT_RUN_ID={json.dumps(run_id)}",
            ]
        )
    if target:
        args.extend(
            [
                "-c",
                f"mcp_servers.{CODEX_MCP_NAME}.env.NOGRA_TRANSPORT_TARGET={json.dumps(target)}",
            ]
        )
    return args


def codex_mcp_payload() -> dict[str, str]:
    return {
        "name": CODEX_MCP_NAME,
        "command": NOGRA_MCP_BIN,
        "env.NOGRA_ROOT": str(ROOT),
        "mode": "injected into codex exec and also expected in Codex global config",
    }


def latest_chat_file() -> Path | None:
    if not CHAT_DIR.exists():
        return None
    files = sorted(CHAT_DIR.glob("20*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    return files[0] if files else None


def claude_project_dirs() -> list[Path]:
    dirs: list[Path] = []
    env_dir = (os.environ.get("NOGRA_CLAUDE_PROJECT_DIR") or os.environ.get("Y26_CLAUDE_PROJECT_DIR", "")).strip()
    if env_dir:
        dirs.append(Path(env_dir).expanduser())
    if CLAUDE_PROJECTS_DIR.exists():
        derived = "-" + str(ROOT).strip(os.sep).replace(os.sep, "-")
        for candidate in CLAUDE_PROJECTS_DIR.iterdir():
            if candidate.is_dir() and candidate.name.lower() == derived.lower():
                dirs.append(candidate)
    out: list[Path] = []
    seen: set[str] = set()
    for directory in dirs:
        try:
            key = str(directory.resolve())
        except OSError:
            key = str(directory)
        if key not in seen and directory.exists():
            out.append(directory)
            seen.add(key)
    return out


def latest_claude_transcript_file() -> Path | None:
    files: list[Path] = []
    for directory in claude_project_dirs():
        files.extend(path for path in directory.glob("*.jsonl") if path.is_file())
    if not files:
        return None
    try:
        return max(files, key=lambda path: path.stat().st_mtime)
    except OSError:
        return None


def read_tail_text(path: Path, limit: int) -> tuple[str, bool]:
    try:
        size = path.stat().st_size
        start = max(0, size - limit)
        with path.open("rb") as handle:
            handle.seek(start)
            if start:
                handle.readline()
            data = handle.read()
    except OSError:
        return "", False
    return data.decode("utf-8", errors="replace"), start > 0


def claude_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = str(item.get("text") or "").strip()
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()


def read_claude_transcript(path: Path, limit: int) -> dict[str, Any]:
    raw, truncated = read_tail_text(path, limit)
    messages: list[str] = []
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("type") not in {"user", "assistant"}:
            continue
        message = item.get("message") if isinstance(item.get("message"), dict) else {}
        role = str(message.get("role") or item.get("type") or "message").upper()
        text = claude_content_text(message.get("content"))
        if not text or text.startswith("<local-command-caveat>"):
            continue
        if len(text) > 8000:
            text = text[:8000] + "\n[message truncated]"
        messages.append(f"{role}: {text}")
    return {
        "path": str(path),
        "exists": True,
        "truncated": truncated,
        "source": "claude-jsonl",
        "text": "\n\n".join(messages[-80:]),
    }


def repo_status_payload() -> dict[str, Any]:
    branch = run(["git", "branch", "--show-current"], timeout=5)
    head = run(["git", "rev-parse", "--short", "HEAD"], timeout=5)
    status = run(["git", "status", "--short"], timeout=5)
    dirty = status["output"].splitlines() if status["ok"] else []
    return {
        "generatedAt": now(),
        "root": str(ROOT),
        "branch": branch["output"] if branch["ok"] else "",
        "head": head["output"] if head["ok"] else "",
        "dirtyCount": len([line for line in dirty if line.strip()]),
        "dirtyPreview": dirty[:80],
        "note": "Read-only git snapshot for context. This does not mutate repo state.",
    }


def latest_work_payload() -> dict[str, Any]:
    command = [str(ROOT / "manager" / "bin" / "transport-state"), "latest-work", "--json"]
    result = run(command, timeout=12)
    if not result["ok"]:
        return {"status": "blocked", "command": command, "error": result["output"]}
    try:
        return json.loads(result["output"])
    except json.JSONDecodeError:
        return {"status": "blocked", "command": command, "error": "non-json output", "raw": result["output"][:4000]}


def workflow_roles_payload() -> dict[str, Any]:
    files = [
        "manager/reference/manager-boot-context.md",
        "manager/reference/role-boundaries.md",
        "manager/reference/codex-is-the-bridge.md",
        "manager/reference/orchestrator-manager.md",
    ]
    payload: dict[str, Any] = {
        "generatedAt": now(),
        "root": str(ROOT),
        "productName": PRODUCT_NAME,
        "principle": f"Roles guide ownership. {PRODUCT_NAME} MCP exposes capabilities; it does not become a role.",
        "roles": role_config_payload().get("roles", {}),
        "contracts": [
            {
                "layer": "CEO",
                "owner": CALLER_LABEL,
                "authority": "intent, taste, priority, GO/NO-GO and final trust",
                "boundary": "does not need to operate transport or receipts manually",
            },
            {
                "layer": "Manager",
                "owner": "Manager",
                "authority": "meaning, judgment, routing and CEO-facing synthesis",
                "boundary": "does not own target execution or transport polling",
            },
            {
                "layer": "Transport",
                "owner": "MCP runtime",
                "authority": "dispatch, run-state, timeout/stale handling, return pointers and cleanup",
                "boundary": "does not own meaning, product judgment or GO decisions",
            },
            {
                "layer": "PM",
                "owner": "Project Manager role",
                "authority": "implementation shape, scoped verification and evidence-preserving return",
                "boundary": "does not change product intent or final authority",
            },
            {
                "layer": "Agent Exec",
                "owner": "Agent role",
                "authority": "bounded execution inside an approved brief and write boundary",
                "boundary": "does not expand scope, mutate authority docs or make product decisions",
            },
        ],
        "localDoctrineRefs": files,
        "localDoctrineIncluded": False,
    }
    include_local = os.environ.get("NOGRA_MCP_INCLUDE_LOCAL_DOCTRINE", "").lower() in {"1", "true", "yes"}
    if include_local:
        payload["localDoctrineIncluded"] = True
        payload["files"] = [read_text(ROOT / file, limit=90000) for file in files]
    return payload


def latest_transcript_payload() -> dict[str, Any]:
    chat_path = latest_chat_file()
    claude_path = latest_claude_transcript_file()
    use_claude = False
    if claude_path is not None:
        if chat_path is None:
            use_claude = True
        else:
            try:
                use_claude = claude_path.stat().st_mtime >= chat_path.stat().st_mtime
            except OSError:
                use_claude = True
    if use_claude and claude_path is not None:
        payload = read_claude_transcript(claude_path, limit=TRANSCRIPT_LIMIT)
    elif chat_path is not None:
        payload = read_text(chat_path, limit=TRANSCRIPT_LIMIT)
        payload["source"] = "manager-chat"
    else:
        return {
            "generatedAt": now(),
            "status": "missing",
            "chatDir": str(CHAT_DIR),
            "claudeProjectsDir": str(CLAUDE_PROJECTS_DIR),
            "text": "",
        }
    payload.update({
        "generatedAt": now(),
        "status": "ok" if payload.get("exists") else "missing",
        "mode": "filtered latest transcript" if payload.get("source") == "claude-jsonl" else "raw latest transcript",
        "note": "This is raw context for fresh eyes, not a Manager summary.",
    })
    return payload


def normalize_codex_mode(mode: str) -> str:
    if mode in {"", "current", "wildcard"}:
        return "wildcard"
    return mode if mode in {"full", "pm"} else "wildcard"


def available_codex_resources() -> list[str]:
    return [
        "nogra://registry",
        "nogra://workflow/roles",
        "nogra://repo/status",
        "nogra://transcript/latest",
        "nogra://state/latest-work",
    ]


def codex_packet_payload(question: str = "", mode: str = "wildcard") -> dict[str, Any]:
    normalized_mode = normalize_codex_mode(mode)
    resources: list[str] = []
    if normalized_mode in {"full", "pm"}:
        resources.extend(available_codex_resources())
    return {
        "generatedAt": now(),
        "kind": "codex_fresh_eyes_packet",
        "mode": normalized_mode,
        "question": question,
        "stance": [
            "Come in as fresh eyes.",
            "No intellectual handcuffs: broaden scope, challenge premises, and name better paths.",
            "Do not act as Manager, CEO, Transport or PM unless explicitly invoked as that role.",
            "No state/code mutation from fresh-eyes mode. Ask for GO before execution.",
        ],
        "resourcePointers": resources,
        "availableResources": available_codex_resources(),
        "resourcePolicy": "wildcard pulls resources on request; full/pm preload listed resourcePointers.",
        "outputShape": output_shape_for_mode(normalized_mode),
        "authModel": f"Use local logged-in Codex/OAuth client. Do not require vendor API keys in {PRODUCT_NAME} MCP.",
        "codexMcpServer": codex_mcp_payload(),
    }


def output_shape_for_mode(mode: str) -> list[str]:
    if mode == "wildcard":
        return ["Answer the caller's exact request; choose format and context depth per call"]
    if mode == "pm":
        return [
            "What I verified",
            "Implementation risk",
            "Concrete next action",
            "Acceptance criteria",
        ]
    return [
        "What I see",
        "What is weak or missing",
        "The broader/better angle",
        "Concrete next options",
        "Context I still need, if any",
    ]


def prompt_text(
    question: str = "",
    mode: str = "wildcard",
    resources: dict[str, Any] | None = None,
    receipt_context: dict[str, str] | None = None,
) -> str:
    packet = codex_packet_payload(question=question, mode=mode)
    if packet["mode"] == "wildcard":
        lines = [
            f"You are Codex called directly inside the {PRODUCT_NAME} Manager conversation.",
            "",
            "This is wildcard mode: interpret this call on its own terms.",
            "Answer the caller's exact request. Do not force a review shape, role lecture, or workflow analysis unless the request asks for it.",
            "If the request is simple, answer simply.",
            f"If the request asks for {PRODUCT_NAME} state, repo facts, transcript context, latest work, or uses context-dependent wording that clearly points to the current conversation, pull the relevant MCP resource yourself.",
            "Do not preload or invent context. Pull only what the call needs.",
            "If pulled resources still do not identify the target, state the missing pointer plainly.",
            "Read-only: do not mutate repo/state or start execution without explicit GO.",
            "",
            f"Mode: {packet['mode']}",
            f"Caller message: {question or '(empty)'}",
            "",
            f"MCP server `{CODEX_MCP_NAME}` is available as the {PRODUCT_NAME} tool-plane.",
            "Available resources/tools to pull when needed:",
            *[f"- {uri}" for uri in packet["availableResources"]],
            "",
        ]
    else:
        lines = [
            f"You are Codex entering the {PRODUCT_NAME} workflow as FRESH EYES.",
            "",
            f"You are not the Manager and you are not Codex PM unless the {CALLER_LABEL}/Manager explicitly says so.",
            "Your job is to see the structure, challenge the current solution, and broaden scope when useful.",
            "No intellectual handcuffs: if the current framing is too narrow, say so and propose the better frame.",
            "Fresh-eyes mode is read-only. Do not mutate repo/state or start execution without explicit GO.",
            f"{CALLER_LABEL}/Manager own intent, priority and GO. You are here to widen sight, not to take the wheel.",
            "",
            "Output discipline:",
            "- The caller's explicit instruction about length and format overrides this default shape.",
            "- If the caller asks for a short/direct answer, answer short/direct and do not fill sections.",
            "- Do not mention repo status, dirty files, transcript facts or resources unless relevant to the caller's question.",
            "- Do not invent findings just to fill sections.",
            "- If the question is simple, answer simply.",
            "",
            f"Mode: {packet['mode']}",
            f"Question: {question or '(use current conversation intent)'}",
            "",
            "Read these MCP resources as needed:",
            *[f"- {uri}" for uri in packet["resourcePointers"]],
            "",
        ]
    if receipt_context:
        lines.extend([
            "This call writes receipts here:",
            *[f"- {key}: {value}" for key, value in receipt_context.items()],
            "",
        ])
    if resources:
        lines.extend([
            "MCP resource payloads are attached below as raw context.",
            "Use them directly. Do not treat Manager summaries as authoritative over raw evidence.",
            "",
        ])
        for uri, payload in resources.items():
            lines.extend([
                f"## MCP RESOURCE {uri}",
                "```json",
                json.dumps(payload, ensure_ascii=False, indent=2),
                "```",
                "",
            ])
    if packet["mode"] == "wildcard":
        lines.append("Answer now, using MCP only if this call asks for it.")
    else:
        lines.extend([
            "Default shape when a review/analysis is actually requested:",
            *[f"- {item}" for item in packet["outputShape"]],
        ])
    return "\n".join(lines)


def resource_payloads_for_mode(mode: str) -> dict[str, Any]:
    packet = codex_packet_payload(mode=mode)
    payloads: dict[str, Any] = {}
    for uri in packet["resourcePointers"]:
        if uri == "nogra://registry":
            payloads[uri] = registry_payload()
        elif uri == "nogra://workflow/roles":
            payloads[uri] = workflow_roles_payload()
        elif uri == "nogra://repo/status":
            payloads[uri] = repo_status_payload()
        elif uri == "nogra://transcript/latest":
            payloads[uri] = latest_transcript_payload()
        elif uri == "nogra://state/latest-work":
            payloads[uri] = latest_work_payload()
    return payloads


def run_codex_fresh_eyes(
    question: str = "",
    mode: str = "wildcard",
    cwd: str = "",
    dry_run: bool = False,
    timeout_seconds: int = 240,
) -> dict[str, Any]:
    normalized_mode = normalize_codex_mode(mode)
    workdir = Path(cwd).expanduser().resolve() if cwd else ROOT
    run_dir = RUNS_DIR / f"codex-fresh-{stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)

    packet_file = run_dir / "packet.json"
    prompt_file = run_dir / "prompt.md"
    output_file = run_dir / "output.md"
    log_file = run_dir / "codex.log"
    receipt_file = run_dir / "receipt.json"

    receipt_context = {
        "runDir": str(run_dir),
        "packet": str(packet_file),
        "prompt": str(prompt_file),
        "output": str(output_file),
        "log": str(log_file),
        "receipt": str(receipt_file),
    }

    resources = resource_payloads_for_mode(normalized_mode)
    packet = codex_packet_payload(question=question, mode=normalized_mode)
    prompt = prompt_text(
        question=question,
        mode=normalized_mode,
        resources=resources,
        receipt_context=receipt_context,
    )

    packet_file.write_text(json.dumps({"packet": packet, "resources": resources}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompt_file.write_text(prompt + "\n", encoding="utf-8")

    receipt: dict[str, Any] = {
        "generatedAt": now(),
        "status": "dry-run" if dry_run else "running",
        "mode": normalized_mode,
        "question": question,
        "cwd": str(workdir),
        "runDir": str(run_dir),
        "packet": str(packet_file),
        "prompt": str(prompt_file),
        "output": str(output_file),
        "log": str(log_file),
        "codexBin": CODEX_BIN,
        "codexModel": CODEX_MODEL,
        "authModel": f"local Codex OAuth/session; no vendor API key owned by {PRODUCT_NAME} MCP",
        "codexMcpServer": codex_mcp_payload(),
    }

    if dry_run:
        receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return receipt

    if not Path(CODEX_BIN).exists() and shutil.which(CODEX_BIN) is None:
        receipt.update({"status": "unavailable", "error": f"codex binary not found: {CODEX_BIN}"})
        receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return receipt

    cmd = [
        CODEX_BIN,
        "exec",
        *codex_mcp_config_args(),
        "-m",
        CODEX_MODEL,
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--ephemeral",
        "--color",
        "never",
        "-C",
        str(workdir),
        "-o",
        str(output_file),
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workdir),
            input=prompt,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds,
            check=False,
        )
        log_file.write_text(proc.stdout or "", encoding="utf-8")
        receipt.update({"status": "ok" if proc.returncode == 0 and output_file.exists() else "failed", "exitCode": proc.returncode})
        if output_file.exists():
            receipt["answer"] = output_file.read_text(encoding="utf-8", errors="replace")
        else:
            receipt["error"] = "codex finished without output file"
    except subprocess.TimeoutExpired as exc:
        log_file.write_text((exc.stdout or "") if isinstance(exc.stdout, str) else str(exc.stdout or ""), encoding="utf-8")
        receipt.update({"status": "timeout", "error": f"codex timed out after {timeout_seconds}s"})

    receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def is_claude_native_path(path: Path) -> bool:
    home_claude = (Path.home() / ".claude").resolve()
    try:
        path.resolve().relative_to(home_claude)
        return True
    except ValueError:
        return path.resolve() == home_claude


def resolve_existing_project(project_dir: str) -> Path:
    if not project_dir.strip():
        raise ValueError("project_dir required")
    path = Path(project_dir).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"project dir not found: {path}")
    if is_claude_native_path(path) and os.environ.get("STINSON_ALLOW_CLAUDE_NATIVE", "0") != "1":
        raise PermissionError(
            f"refusing .claude project scope by default: {path}. "
            "Set STINSON_ALLOW_CLAUDE_NATIVE=1 only for explicit Claude native memory/config work."
        )
    return path


def resolve_optional_brief(project_dir: Path, brief_path: str) -> Path | None:
    if not brief_path.strip():
        return None
    path = Path(brief_path).expanduser()
    candidates = [path] if path.is_absolute() else [project_dir / path, ROOT / path]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    raise FileNotFoundError(f"brief file not found: {brief_path}")


def brief_meta_payload(project: Path, brief: Path) -> dict[str, Any]:
    if not BRIEF_META_BIN.is_file():
        raise FileNotFoundError(f"brief metadata helper not found: {BRIEF_META_BIN}")
    result = subprocess.run(
        [sys.executable, str(BRIEF_META_BIN), str(brief)],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"invalid brief frontmatter: {brief}: {result.stdout.strip()}")
    try:
        meta = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"brief metadata helper returned non-json: {brief}") from exc
    meta_project = Path(str(meta.get("project_dir") or "")).expanduser().resolve()
    if meta_project != project:
        raise ValueError(f"brief project_dir mismatch: {meta_project} != {project}")
    return meta


def invalid_brief_contract_response(project: Path, brief: Path, exc: BaseException) -> dict[str, Any]:
    return {
        "generatedAt": now(),
        "status": "invalid_brief_contract",
        "phase": "pre_dispatch",
        "nextOwner": "Manager",
        "projectDir": str(project),
        "briefPath": str(brief),
        "error": str(exc),
        "fix": BRIEF_FRONTMATTER_FIX,
        "reference": BRIEF_DISPATCH_FLOW_REF,
    }


def validate_dispatch_brief_contract(project: Path, brief: Path | None) -> dict[str, Any]:
    if brief is None:
        return {}
    try:
        return brief_meta_payload(project, brief)
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ValueError(str(exc)) from exc


def claude_settings_file(project: Path, run_dir: Path) -> Path:
    settings_file = run_dir / "agent.settings.json"
    project_settings = project / ".claude" / "settings.json"
    if SETTINGS_MERGE_BIN.is_file():
        result = subprocess.run(
            [sys.executable, str(SETTINGS_MERGE_BIN), str(ROOT_CLAUDE_SETTINGS), str(project_settings)],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            settings_file.write_text(result.stdout, encoding="utf-8")
            return settings_file
    settings_file.write_text("{}\n", encoding="utf-8")
    return settings_file


def agent_exec_packet_payload(
    project_dir: str,
    brief_path: str,
    manager_message: str = "",
    sandbox: str = "",
    parent_run_id: str = "",
    intent_id: str = "",
    shared_doctrine_refs: str | list[str] | None = None,
) -> dict[str, Any]:
    project = resolve_existing_project(project_dir)
    brief = resolve_optional_brief(project, brief_path)
    if brief is None:
        raise ValueError("agent_exec requires an approved brief_path")
    meta = brief_meta_payload(project, brief)
    sandbox_mode = sandbox.strip() or str(role_payload("agent").get("sandboxDefault") or "workspace-write")
    refs = normalize_shared_doctrine_refs(shared_doctrine_refs)
    resolved_refs = [resolve_reference(project, ref) for ref in refs]
    agent_role = role_payload("agent")
    return {
        "generatedAt": now(),
        "kind": "agent_exec_dispatch_packet",
        "target": "agent_exec",
        "targetRole": "Agent Exec",
        "mode": "brief",
        "projectDir": str(project),
        "briefPath": str(brief),
        "briefMeta": meta,
        "role": agent_role,
        "modelAdapter": {
            "adapter": agent_role.get("adapter", "claude_cli"),
            "model": agent_role.get("model", "sonnet"),
            "effort": agent_role.get("effort", "low"),
            "userOwned": True,
        },
        "parentRunId": parent_run_id.strip(),
        "intentId": intent_id.strip(),
        "sharedDoctrineRefs": refs,
        "sharedDoctrine": resolved_refs,
        "managerMessage": manager_message,
        "freedomClause": [
            "Satisfy the approved brief's intent and acceptance criteria.",
            "Choose the implementation path freely inside the approved write boundary.",
            "Preserve nuance; do not narrow the brief by adding extra rules.",
            "If a better path requires changing authority/scope, report Proposed deviation instead of silently mutating.",
        ],
        "boundary": {
            "writeScope": meta.get("scope_files", []),
            "projectDir": str(project),
            "forbidden": [
                "commits or pushes — git is CEO/Manager only, never the agent",
                "DECISIONS.md or authority documents unless explicitly in scope",
                ".claude memory/config unless explicitly in scope",
                "unrelated dirty work",
            ],
        },
        "accessMode": {
            "sandbox": sandbox_mode,
            "mutation": "allowed inside approved brief scope only",
            "report": "return report content through MCP tool transport_submit_report; Transport owns artifact writes",
        },
        "authModel": f"Use the user's local logged-in adapter/OAuth client. {PRODUCT_NAME} MCP does not own vendor API keys.",
        "receiptRoot": str(RUNS_DIR),
    }


def agent_exec_prompt(
    project_dir: Path,
    brief_path: Path,
    manager_message: str,
    packet: dict[str, Any],
    report_file: Path,
    receipt_file: Path,
) -> str:
    project_name = project_dir.name
    refs = packet.get("sharedDoctrineRefs") if isinstance(packet.get("sharedDoctrineRefs"), list) else []
    refs_block = "\n".join(f"- {ref}" for ref in refs) if refs else "- None supplied"
    return f"""You are Agent Exec (T5) in the {PRODUCT_NAME} workflow for project `{project_name}`.

Role boundary:
- You are not the {CALLER_LABEL}/workflow owner.
- You are not Stinson Manager/Opus.
- You are not Transport/Orchestrator.
- You are not Codex PM.
- You execute bounded work from an approved PM/Manager packet and return evidence.

Task:
Read this approved brief:
{brief_path}

Your job is to satisfy the brief's intent and acceptance criteria. You are free to choose the implementation path inside the approved write boundary. This is constraint-based execution, not handcuffs.

Nuance rule:
- Preserve the brief's nuance and intent.
- Do not add stricter rules than the brief supplies.
- If the best path requires changing authority, scope, product taste, or write boundary, stop that part and document it under Proposed deviations.

Shared doctrine refs:
{refs_block}

Manager supplement:
{manager_message.strip() or "(none)"}

Parent linkage:
- parentRunId: {packet.get("parentRunId") or "(none)"}
- intentId: {packet.get("intentId") or "(none)"}

Write boundary:
{json.dumps(packet.get("boundary", {}), ensure_ascii=False, indent=2)}

Execution rules:
- Never commit, push, reset, revert, or touch `.claude`. Git is CEO/Manager only — the agent never performs git
operations, even if a brief asks for it.
- Preserve existing user/manager changes; do not clean unrelated dirty files.
- Prefer existing repo patterns and local helpers over new abstractions.
- Verify with the commands requested by the brief when feasible.
- If a verification command cannot run, record why.
- Do not write or overwrite the receipt file. Transport owns receipts and persisted artifacts; you own the report content.

Return your structured completion report through MCP tool `transport_submit_report`. Dispatch allocates `NOGRA_TRANSPORT_RUN_ID`, so pass `run_id` only if the tool asks for it. The Transport artifact path is:
{report_file}

If the return tool is unavailable, include the full structured report in the final answer; Transport captures that output as fallback.

Use this markdown structure:

# Agent Exec Report

## Status
COMPLETE | BLOCKED | PARTIAL

## Parent
- parentRunId:
- intentId:

## Scope
Brief handled in one sentence.

## Files changed
- path/to/file - description

## Commands run
- command - result

## Acceptance
- [x] criterion
- [ ] criterion (blocked: reason)

## Proposed deviations
None | concise deviation and why it needs PM/Manager authority

## Evidence / Not proven
- evidence

## Return to PM
ready for PM verify | blocked | decision required

Receipt pointer:
{receipt_file}

Canonical packet:
```json
{json.dumps(packet, ensure_ascii=False, indent=2)}
```

Final answer: include the structured report content. If your adapter can write files, write the report file first; the runtime will mirror final output into report.md only as fallback. Do not pretend PM/Manager/CEO decisions were made.
"""


def codex_dispatch_packet_payload(
    project_dir: str,
    brief_path: str = "",
    manager_message: str = "",
    sandbox: str = "",
) -> dict[str, Any]:
    project = resolve_existing_project(project_dir)
    brief = resolve_optional_brief(project, brief_path)
    mode = "brief" if brief else ("message" if manager_message.strip() else "boot")
    sandbox_mode = sandbox.strip() or ("workspace-write" if brief else "read-only")
    return {
        "generatedAt": now(),
        "kind": "codex_pm_dispatch_packet",
        "mode": mode,
        "projectDir": str(project),
        "briefPath": str(brief) if brief else "",
        "managerMessage": manager_message,
        "stance": [
            "Act as Codex PM, not CEO, not Manager, not Transport.",
            "CEO/Manager own intent, taste, priority and GO.",
            "Codex PM owns implementation shape, scoped code changes and verification.",
            "Inline /codex fresh-eyes is a separate read-only capability; this is formal PM dispatch.",
        ],
        "accessMode": {
            "sandbox": sandbox_mode,
            "mutation": "allowed only inside the project workspace when an approved brief is supplied",
            "commits": "forbidden — git is CEO/Manager only, never the agent",
        },
        "authModel": f"Use local logged-in Codex/OAuth client. Do not require vendor API keys in {PRODUCT_NAME} MCP.",
        "codexMcpServer": codex_mcp_payload(),
        "receiptRoot": str(RUNS_DIR),
    }


def codex_dispatch_prompt(
    project_dir: Path,
    brief_path: Path | None,
    manager_message: str,
    report_file: Path,
    receipt_file: Path,
) -> str:
    project_name = project_dir.name
    if brief_path:
        task_block = f"""Task: execute this approved brief exactly:
{brief_path}

First read the brief. Treat its intent, hard constraints, acceptance criteria and return path as binding.
You may edit only the files/surfaces named by the brief unless the brief itself proves a tiny supporting edit is required.
If the brief is ambiguous, would drift UI DNA, or needs a decision outside the brief, stop and report BLOCKED."""
        sandbox_note = "Workspace-write is enabled because an approved brief was supplied."
    elif manager_message.strip():
        task_block = f"""Task: handle this Manager instruction as a read-only Codex PM state check:
---
{manager_message.strip()}
---

Do not mutate files. Return implementation-shape, risks and the next bounded dispatch step."""
        sandbox_note = "Read-only sandbox is expected because no approved implementation brief was supplied."
    else:
        task_block = """Task: boot into this project as Codex PM and produce a read-only state report.
Read the minimal repo context needed to identify current technical state, risks and next dispatch step.
Do not mutate files."""
        sandbox_note = "Read-only sandbox is expected because this is a PM boot, not an implementation dispatch."

    return f"""You are Codex PM (T4) in the {PRODUCT_NAME} workflow for project `{project_name}`.

Role boundary:
- You are not the {CALLER_LABEL}/workflow owner.
- You are not Stinson Manager/Opus.
- You are not Transport/Orchestrator.
- You are the code-aware PM: implementation shape, scoped code changes, verification, evidence-preserving return.

{task_block}

Execution rules:
- {sandbox_note}
- {PRODUCT_NAME} MCP is attached inside this Codex session as server `{CODEX_MCP_NAME}`. Use it for registry, repo status, latest-work and workflow-role reads when useful.
- Do not recursively call `codex_dispatch` from inside a Codex PM dispatch unless Manager explicitly asks for nested dispatch.
- Never commit, push, reset, revert, or touch `.claude`. Git is CEO/Manager only — the agent never performs git
operations, even if a brief asks for it.
- Preserve existing user/manager changes; do not clean unrelated dirty files.
- Prefer existing repo patterns and local helpers over new abstractions.
- Timebox the work. For a small brief, ship a bounded patch quickly; if the scope cannot be completed inside the dispatch timeout, write PARTIAL or BLOCKED with exact next action.
- Verify with the commands requested by the brief when feasible.
- If a verification command cannot run, record why.

Return your structured completion report through MCP tool `transport_submit_report`. Dispatch allocates `NOGRA_TRANSPORT_RUN_ID`, so pass `run_id` only if the tool asks for it. The Transport artifact path is:
{report_file}

If the return tool is unavailable, include the full structured report in the final answer; Transport captures that output as fallback.

Use this markdown structure:

# Codex PM Dispatch Report

## Status
COMPLETE | BLOCKED | PARTIAL

## Scope
Brief/message handled in one sentence.

## Files changed
- path/to/file - description

## Commands run
- command - result

## Acceptance
- [x] criterion
- [ ] criterion (blocked: reason)

## Drift flags
None | concise flag for CEO/Manager

## Return
ship | afvigelse | blocked | beslutning kræves

Receipt pointer:
{receipt_file}

Final answer: include the full structured report content. Do not pretend Manager/CEO decisions were made.
"""


def run_codex_dispatch(
    project_dir: str,
    brief_path: str = "",
    manager_message: str = "",
    dry_run: bool = False,
    timeout_seconds: int = 600,
    sandbox: str = "",
) -> dict[str, Any]:
    try:
        project = resolve_existing_project(project_dir)
        brief = resolve_optional_brief(project, brief_path)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        return {"generatedAt": now(), "status": "invalid", "error": str(exc)}
    try:
        brief_meta = validate_dispatch_brief_contract(project, brief)
    except ValueError as exc:
        return invalid_brief_contract_response(project, brief or Path(brief_path), exc)
    pm_role = role_payload("project_manager")
    if str(pm_role.get("adapter") or "codex_cli") != "codex_cli":
        return {
            "generatedAt": now(),
            "status": "unsupported",
            "target": "codex_pm",
            "error": "run_codex_dispatch requires project_manager adapter codex_cli; use transport_dispatch for wildcard adapters",
            "adapter": str(pm_role.get("adapter") or ""),
            "nextOwner": "Manager",
        }
    pm_model = str(pm_role.get("model") or CODEX_MODEL)
    pm_reasoning = str(pm_role.get("reasoning") or "medium")

    run_dir = RUNS_DIR / f"codex-dispatch-{stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)

    packet_file = run_dir / "packet.json"
    prompt_file = run_dir / "prompt.md"
    output_file = run_dir / "output.md"
    log_file = run_dir / "codex.log"
    report_file = run_dir / "report.md"
    receipt_file = run_dir / "receipt.json"
    sandbox_mode = sandbox.strip() or ("workspace-write" if brief else "read-only")

    try:
        packet = codex_dispatch_packet_payload(
            project_dir=str(project),
            brief_path=str(brief) if brief else "",
            manager_message=manager_message,
            sandbox=sandbox_mode,
        )
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        return {"generatedAt": now(), "status": "invalid", "error": str(exc)}

    prompt = codex_dispatch_prompt(
        project_dir=project,
        brief_path=brief,
        manager_message=manager_message,
        report_file=report_file,
        receipt_file=receipt_file,
    )

    packet_file.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompt_file.write_text(prompt + "\n", encoding="utf-8")

    receipt: dict[str, Any] = {
        "generatedAt": now(),
        "status": "dry-run" if dry_run else "running",
        "mode": packet["mode"],
        "projectDir": str(project),
        "briefPath": str(brief) if brief else "",
        "runDir": str(run_dir),
        "packet": str(packet_file),
        "prompt": str(prompt_file),
        "output": str(output_file),
        "log": str(log_file),
        "report": str(report_file),
        "receipt": str(receipt_file),
        "briefMeta": brief_meta,
        "codexBin": CODEX_BIN,
        "codexModel": pm_model,
        "adapter": "codex_cli",
        "model": pm_model,
        "effort": pm_reasoning,
        "sandbox": sandbox_mode,
        "roleGrant": {
            "slot": "project_manager",
            "target": "codex_pm",
            "targetRole": "Codex PM",
            "adapter": "codex_cli",
            "model": pm_model,
            "effort": pm_reasoning,
            "sandbox": sandbox_mode,
            "settingsSource": "host-settings",
            "settingsHash": file_sha256(SETTINGS_FILE) if SETTINGS_FILE.is_file() else "",
        },
        "authModel": "local Codex OAuth/session; vendor API keys removed from dispatch environment",
        "codexMcpServer": codex_mcp_payload(),
    }
    receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if dry_run:
        return receipt

    if not Path(CODEX_BIN).exists() and shutil.which(CODEX_BIN) is None:
        receipt.update({"status": "unavailable", "error": f"codex binary not found: {CODEX_BIN}"})
        receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return receipt

    cmd = [
        CODEX_BIN,
        "exec",
        *codex_mcp_config_args(),
        "-m",
        pm_model,
        "-c",
        f"model_reasoning_effort={json.dumps(pm_reasoning)}",
        "-c",
        'approval_policy="never"',
        "--sandbox",
        sandbox_mode,
        "--skip-git-repo-check",
        "--ephemeral",
        "--color",
        "never",
        "--json",
        "-C",
        str(project),
        "-o",
        str(output_file),
        "-",
    ]

    env = os.environ.copy()
    env["NOGRA_ROOT"] = str(ROOT)
    env["Y26_ROOT"] = str(ROOT)
    env["NOGRA_CODEX_DISPATCH"] = "1"
    env["Y26_CODEX_DISPATCH"] = "1"
    env.pop("OPENAI_API_KEY", None)
    env.pop("ANTHROPIC_API_KEY", None)

    start = time.time()
    log_file.write_text(
        json.dumps(
            {
                "type": "nogra_dispatch_start",
                "generatedAt": now(),
                "cmd": cmd,
                "timeoutSeconds": timeout_seconds,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        with log_file.open("a", encoding="utf-8") as log_handle:
            proc = subprocess.Popen(
                cmd,
                cwd=str(project),
                text=True,
                stdin=subprocess.PIPE,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                env=env,
            )
            try:
                proc.communicate(prompt, timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                log_handle.write(
                    json.dumps(
                        {
                            "type": "nogra_dispatch_timeout",
                            "generatedAt": now(),
                            "timeoutSeconds": timeout_seconds,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                receipt.update(
                    {
                        "status": "timeout",
                        "exitCode": proc.returncode,
                        "durationSeconds": round(time.time() - start, 3),
                        "error": f"codex timed out after {timeout_seconds}s",
                    }
                )
                receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                return receipt

        receipt.update({"exitCode": proc.returncode, "durationSeconds": round(time.time() - start, 3)})
        report_mirrored = transport_mirror_output_to_report(output_file, report_file)
        receipt["reportMirroredFromOutput"] = report_mirrored
        if output_file.exists():
            receipt["answer"] = output_file.read_text(encoding="utf-8", errors="replace")
        if report_file.exists():
            receipt["reportText"] = report_file.read_text(encoding="utf-8", errors="replace")
        if proc.returncode == 0 and output_file.exists() and report_file.exists():
            receipt["status"] = "ok"
        else:
            receipt["status"] = "failed"
            if not output_file.exists():
                receipt["error"] = "codex finished without output file"
            elif not report_file.exists():
                receipt["error"] = "codex finished without dispatch report"
    except OSError as exc:
        receipt.update(
            {
                "status": "failed",
                "durationSeconds": round(time.time() - start, 3),
                "error": str(exc),
            }
        )
        with log_file.open("a", encoding="utf-8") as log_handle:
            log_handle.write(
                json.dumps(
                    {"type": "nogra_dispatch_error", "generatedAt": now(), "error": str(exc)},
                    ensure_ascii=False,
                )
                + "\n"
            )

    receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def role_dispatch_prompt(
    *,
    role_slot: str,
    target_role: str,
    project_dir: Path,
    brief_path: Path | None,
    manager_message: str,
    packet: dict[str, Any],
    report_file: Path,
) -> str:
    if brief_path:
        task_block = f"""Task: handle this approved brief:
{brief_path}

Read the brief first. Treat its intent, hard constraints, acceptance criteria and return path as binding.
If the best path requires changing authority, scope, product taste or write boundary, stop that part and report the deviation."""
    elif manager_message.strip():
        task_block = f"""Task: handle this Manager instruction as a read-only role dispatch:
---
{manager_message.strip()}
---

Do not mutate files. Return implementation shape, risks and the next bounded dispatch step."""
    else:
        task_block = """Task: produce a read-only state report for this project.
Read only the context needed to identify current technical state, risks and next dispatch step."""

    return f"""Nogra runtime grant

The following grant was resolved from user/host settings before dispatch. It is the runtime/audit envelope, not a model persona:

```json
{json.dumps(packet, ensure_ascii=False, indent=2)}
```

Project: {project_dir}
Role slot: {role_slot}
Target role label: {target_role}

{task_block}

Execution rules:
- The grant, brief metadata and sandbox are the authority. Do not claim a Manager/CEO decision was made unless the packet says so.
- Never commit, push, reset, revert, or touch `.claude` unless explicitly in scope.
- Preserve existing user/manager changes; do not clean unrelated dirty files.
- Verify with the commands requested by the brief when feasible.
- If a verification command cannot run, record why.

Return your structured completion report through MCP tool `transport_submit_report` when available. Transport allocated this artifact path:
{report_file}

If the return tool is unavailable, include the full structured report in the final answer; Transport captures that output as fallback.
"""


def run_transport_role_adapter_dispatch(
    *,
    role_slot: str,
    target: str,
    target_role: str,
    project_dir: str,
    brief_path: str = "",
    manager_message: str = "",
    dry_run: bool = False,
    timeout_seconds: int = 600,
    sandbox: str = "",
    wait: bool = False,
    wait_seconds: int = 0,
    parent_run_id: str = "",
    intent_id: str = "",
) -> dict[str, Any]:
    try:
        project = resolve_existing_project(project_dir)
        brief = resolve_optional_brief(project, brief_path)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        return {"generatedAt": now(), "status": "invalid", "target": target, "error": str(exc)}
    try:
        brief_meta = validate_dispatch_brief_contract(project, brief)
    except ValueError as exc:
        return invalid_brief_contract_response(project, brief or Path(brief_path), exc)

    role = role_payload(role_slot)
    adapter = str(role.get("adapter") or "")
    if adapter not in SUPPORTED_ROLE_ADAPTERS:
        return {
            "generatedAt": now(),
            "status": "unsupported",
            "target": target,
            "targetRole": target_role,
            "roleSlot": role_slot,
            "adapter": adapter,
            "supportedAdapters": sorted(SUPPORTED_ROLE_ADAPTERS),
            "nextOwner": "Manager",
        }

    run_id = f"role-dispatch-{stamp()}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    packet_file = run_dir / "packet.json"
    prompt_file = run_dir / "prompt.md"
    output_file = run_dir / "output.md"
    log_file = run_dir / "role.log"
    report_file = run_dir / "report.md"
    receipt_file = run_dir / "receipt.json"
    settings_file = claude_settings_file(project, run_dir)
    sandbox_mode = sandbox.strip() or str(role.get("sandboxDefault") or ("workspace-write" if brief else "read-only"))
    model = str(role.get("model") or default_model_for_adapter(adapter))
    effort = str(role.get("effort") or role.get("reasoning") or "medium")
    mode = "brief" if brief else ("message" if manager_message.strip() else "boot")
    role_grant = {
        "slot": role_slot,
        "target": target,
        "targetRole": target_role,
        "adapter": adapter,
        "model": model,
        "effort": effort,
        "sandbox": sandbox_mode,
        "settingsSource": "host-settings",
        "settingsHash": file_sha256(SETTINGS_FILE) if SETTINGS_FILE.is_file() else "",
        "authModel": "local adapter OAuth/session; vendor API keys removed from dispatch environment",
    }
    packet = {
        "generatedAt": now(),
        "kind": "role_dispatch_packet",
        "mode": mode,
        "roleSlot": role_slot,
        "target": target,
        "targetRole": target_role,
        "projectDir": str(project),
        "briefPath": str(brief) if brief else "",
        "briefMeta": brief_meta,
        "roleGrant": role_grant,
        "managerMessage": manager_message,
        "parentRunId": parent_run_id.strip(),
        "intentId": intent_id.strip(),
        "accessMode": {
            "sandbox": sandbox_mode,
            "mutation": "allowed only inside approved brief scope when a brief is supplied",
            "report": "Transport owns artifact writes; target returns report content",
        },
    }
    prompt = role_dispatch_prompt(
        role_slot=role_slot,
        target_role=target_role,
        project_dir=project,
        brief_path=brief,
        manager_message=manager_message,
        packet=packet,
        report_file=report_file,
    )

    packet_file.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompt_file.write_text(prompt + "\n", encoding="utf-8")

    cmd = [
        sys.executable,
        str(ADAPTER_RUNNER_BIN),
        "agent-exec",
        "--adapter",
        adapter,
        "--project-dir",
        str(project),
        "--output",
        str(output_file),
        "--report",
        str(report_file),
        "--run-id",
        run_id,
        "--model",
        model,
        "--effort",
        effort,
        "--sandbox",
        sandbox_mode,
        "--settings",
        str(settings_file),
        "--transport-target",
        target,
        "--codex-mcp-name",
        CODEX_MCP_NAME,
        "--nogra-mcp-bin",
        NOGRA_MCP_BIN,
    ]

    receipt: dict[str, Any] = {
        "generatedAt": now(),
        "status": "dry-run" if dry_run else "queued",
        "mode": mode,
        "target": target,
        "targetRole": target_role,
        "roleSlot": role_slot,
        "projectDir": str(project),
        "briefPath": str(brief) if brief else "",
        "briefMeta": brief_meta,
        "runDir": str(run_dir),
        "runId": run_id,
        "packet": str(packet_file),
        "prompt": str(prompt_file),
        "output": str(output_file),
        "log": str(log_file),
        "report": str(report_file),
        "receipt": str(receipt_file),
        "settings": str(settings_file),
        "adapter": adapter,
        "model": model,
        "effort": effort,
        "sandbox": sandbox_mode,
        "roleGrant": role_grant,
        "transportMode": "dry-run" if dry_run else "detached-watch",
        "nextOwner": "Manager" if dry_run else "Transport",
    }
    receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if dry_run:
        return receipt

    transport_record = {
        "runId": run_id,
        "target": target,
        "targetRole": target_role,
        "roleSlot": role_slot,
        "projectDir": str(project),
        "briefPath": str(brief) if brief else "",
        "briefMeta": brief_meta,
        "mode": mode,
        "model": model,
        "adapter": adapter,
        "effort": effort,
        "sandbox": sandbox_mode,
        "timeoutSeconds": timeout_seconds,
        "staleSeconds": int(os.environ.get("NOGRA_TRANSPORT_STALE_SECONDS") or os.environ.get("Y26_TRANSPORT_STALE_SECONDS", "120")),
        "parentRunId": parent_run_id.strip(),
        "intentId": intent_id.strip(),
        "roleGrant": role_grant,
        "paths": {
            "runDir": str(run_dir),
            "packet": str(packet_file),
            "prompt": str(prompt_file),
            "output": str(output_file),
            "log": str(log_file),
            "report": str(report_file),
            "receipt": str(receipt_file),
            "settings": str(settings_file),
        },
        "command": cmd,
        "env": {
            "NOGRA_ROOT": str(ROOT),
            "Y26_ROOT": str(ROOT),
            "NOGRA_TRANSPORT_RUN_ID": run_id,
            "Y26_TRANSPORT_RUN_ID": run_id,
            "NOGRA_TRANSPORT_TARGET": target,
            "NOGRA_ROLE_SLOT": role_slot,
        },
        "cleanup": {
            "archiveAfterHours": 24,
            "orphanAfterSeconds": 900,
        },
    }

    transport_cleanup_state(archive_after_hours=24, orphan_after_seconds=900, max_events=5000, dry_run=False)
    transport_state = transport_register_run(transport_record)
    transport_state = transport_spawn_watcher(run_id)

    if not wait:
        receipt.update({"status": "dispatched", "transportRun": transport_state, "nextOwner": "Transport"})
        receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return receipt

    waited = transport_wait_for_run(run_id, wait_seconds=wait_seconds or timeout_seconds + 30)
    returned = transport_return_payload(run_id, include_text=True)
    return finalized_transport_receipt(
        receipt=receipt,
        transport_record=transport_record,
        returned=returned,
        waited=waited,
        receipt_file=receipt_file,
        report_file=report_file,
        log_file=log_file,
        output_file=output_file,
    )


def run_transport_codex_dispatch(
    project_dir: str,
    brief_path: str = "",
    manager_message: str = "",
    dry_run: bool = False,
    timeout_seconds: int = 600,
    sandbox: str = "",
    wait: bool = False,
    wait_seconds: int = 0,
) -> dict[str, Any]:
    if dry_run:
        pm_role = role_payload("project_manager")
        if str(pm_role.get("adapter") or "codex_cli") != "codex_cli":
            return run_transport_role_adapter_dispatch(
                role_slot="project_manager",
                target="codex_pm",
                target_role=str(pm_role.get("title") or "Project Manager"),
                project_dir=project_dir,
                brief_path=brief_path,
                manager_message=manager_message,
                dry_run=True,
                timeout_seconds=timeout_seconds,
                sandbox=sandbox,
                wait=False,
                wait_seconds=0,
            )
        receipt = run_codex_dispatch(
            project_dir=project_dir,
            brief_path=brief_path,
            manager_message=manager_message,
            dry_run=True,
            timeout_seconds=timeout_seconds,
            sandbox=sandbox,
        )
        receipt["transportMode"] = "dry-run"
        return receipt

    try:
        project = resolve_existing_project(project_dir)
        brief = resolve_optional_brief(project, brief_path)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        return {"generatedAt": now(), "status": "invalid", "error": str(exc)}
    try:
        brief_meta = validate_dispatch_brief_contract(project, brief)
    except ValueError as exc:
        return invalid_brief_contract_response(project, brief or Path(brief_path), exc)
    pm_role = role_payload("project_manager")
    pm_adapter = str(pm_role.get("adapter") or "codex_cli")
    if pm_adapter != "codex_cli":
        return run_transport_role_adapter_dispatch(
            role_slot="project_manager",
            target="codex_pm",
            target_role=str(pm_role.get("title") or "Project Manager"),
            project_dir=str(project),
            brief_path=str(brief) if brief else "",
            manager_message=manager_message,
            dry_run=False,
            timeout_seconds=timeout_seconds,
            sandbox=sandbox,
            wait=wait,
            wait_seconds=wait_seconds,
        )
    pm_model = str(pm_role.get("model") or CODEX_MODEL)
    pm_reasoning = str(pm_role.get("reasoning") or "medium")

    run_id = f"codex-dispatch-{stamp()}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    packet_file = run_dir / "packet.json"
    prompt_file = run_dir / "prompt.md"
    output_file = run_dir / "output.md"
    log_file = run_dir / "codex.log"
    report_file = run_dir / "report.md"
    receipt_file = run_dir / "receipt.json"
    sandbox_mode = sandbox.strip() or ("workspace-write" if brief else "read-only")

    try:
        packet = codex_dispatch_packet_payload(
            project_dir=str(project),
            brief_path=str(brief) if brief else "",
            manager_message=manager_message,
            sandbox=sandbox_mode,
        )
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        return {"generatedAt": now(), "status": "invalid", "error": str(exc)}

    prompt = codex_dispatch_prompt(
        project_dir=project,
        brief_path=brief,
        manager_message=manager_message,
        report_file=report_file,
        receipt_file=receipt_file,
    )

    packet_file.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompt_file.write_text(prompt + "\n", encoding="utf-8")

    receipt: dict[str, Any] = {
        "generatedAt": now(),
        "status": "queued",
        "mode": packet["mode"],
        "projectDir": str(project),
        "briefPath": str(brief) if brief else "",
        "runDir": str(run_dir),
        "runId": run_id,
        "packet": str(packet_file),
        "prompt": str(prompt_file),
        "output": str(output_file),
        "log": str(log_file),
        "report": str(report_file),
        "receipt": str(receipt_file),
        "codexBin": CODEX_BIN,
        "codexModel": pm_model,
        "adapter": "codex_cli",
        "model": pm_model,
        "roleGrant": {
            "slot": "project_manager",
            "target": "codex_pm",
            "targetRole": "Codex PM",
            "adapter": "codex_cli",
            "model": pm_model,
            "effort": pm_reasoning,
            "sandbox": sandbox_mode,
            "settingsSource": "host-settings",
            "settingsHash": file_sha256(SETTINGS_FILE) if SETTINGS_FILE.is_file() else "",
        },
        "sandbox": sandbox_mode,
        "authModel": "local Codex OAuth/session; vendor API keys removed from dispatch environment",
        "codexMcpServer": codex_mcp_payload(),
        "transportMode": "detached-watch",
        "nextOwner": "Transport",
    }
    receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not Path(CODEX_BIN).exists() and shutil.which(CODEX_BIN) is None:
        receipt.update({"status": "unavailable", "error": f"codex binary not found: {CODEX_BIN}", "nextOwner": "Manager"})
        receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return receipt

    cmd = [
        CODEX_BIN,
        "exec",
        *codex_mcp_config_args(run_id=run_id, target="codex_pm"),
        "-m",
        pm_model,
        "-c",
        f"model_reasoning_effort={json.dumps(pm_reasoning)}",
        "-c",
        'approval_policy="never"',
        "--sandbox",
        sandbox_mode,
        "--skip-git-repo-check",
        "--ephemeral",
        "--color",
        "never",
        "--json",
        "-C",
        str(project),
        "-o",
        str(output_file),
        "-",
    ]

    transport_record = {
        "runId": run_id,
        "target": "codex_pm",
        "targetRole": "Codex PM",
        "projectDir": str(project),
        "briefPath": str(brief) if brief else "",
        "mode": packet["mode"],
        "model": pm_model,
        "adapter": "codex_cli",
        "effort": pm_reasoning,
        "sandbox": sandbox_mode,
        "briefMeta": brief_meta,
        "roleGrant": {
            "slot": "project_manager",
            "target": "codex_pm",
            "targetRole": "Codex PM",
            "adapter": "codex_cli",
            "model": pm_model,
            "effort": pm_reasoning,
            "sandbox": sandbox_mode,
            "settingsSource": "host-settings",
            "settingsHash": file_sha256(SETTINGS_FILE) if SETTINGS_FILE.is_file() else "",
        },
        "timeoutSeconds": timeout_seconds,
        "staleSeconds": int(os.environ.get("NOGRA_TRANSPORT_STALE_SECONDS") or os.environ.get("Y26_TRANSPORT_STALE_SECONDS", "120")),
        "paths": {
            "runDir": str(run_dir),
            "packet": str(packet_file),
            "prompt": str(prompt_file),
            "output": str(output_file),
            "log": str(log_file),
            "report": str(report_file),
            "receipt": str(receipt_file),
        },
        "command": cmd,
        "env": {
            "NOGRA_ROOT": str(ROOT),
            "Y26_ROOT": str(ROOT),
            "NOGRA_CODEX_DISPATCH": "1",
            "Y26_CODEX_DISPATCH": "1",
            "NOGRA_TRANSPORT_RUN_ID": run_id,
            "Y26_TRANSPORT_RUN_ID": run_id,
            "NOGRA_TRANSPORT_TARGET": "codex_pm",
        },
        "cleanup": {
            "archiveAfterHours": 24,
            "orphanAfterSeconds": 900,
        },
    }

    transport_cleanup_state(archive_after_hours=24, orphan_after_seconds=900, max_events=5000, dry_run=False)
    transport_state = transport_register_run(transport_record)
    transport_state = transport_spawn_watcher(run_id)

    if not wait:
        receipt.update(
            {
                "status": "dispatched",
                "transportRun": transport_state,
                "nextOwner": "Transport",
            }
        )
        receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return receipt

    waited = transport_wait_for_run(run_id, wait_seconds=wait_seconds or timeout_seconds + 30)
    returned = transport_return_payload(run_id, include_text=True)
    return finalized_transport_receipt(
        receipt=receipt,
        transport_record=transport_record,
        returned=returned,
        waited=waited,
        receipt_file=receipt_file,
        report_file=report_file,
        log_file=log_file,
        output_file=output_file,
    )


def run_transport_agent_exec_dispatch(
    project_dir: str,
    brief_path: str,
    manager_message: str = "",
    dry_run: bool = False,
    timeout_seconds: int = 900,
    sandbox: str = "",
    wait: bool = False,
    wait_seconds: int = 0,
    parent_run_id: str = "",
    intent_id: str = "",
    shared_doctrine_refs: str | list[str] | None = None,
) -> dict[str, Any]:
    try:
        project = resolve_existing_project(project_dir)
        brief = resolve_optional_brief(project, brief_path)
        if brief is None:
            raise ValueError("agent_exec requires an approved brief_path")
        packet = agent_exec_packet_payload(
            project_dir=str(project),
            brief_path=str(brief),
            manager_message=manager_message,
            sandbox=sandbox,
            parent_run_id=parent_run_id,
            intent_id=intent_id,
            shared_doctrine_refs=shared_doctrine_refs,
        )
    except (FileNotFoundError, PermissionError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"generatedAt": now(), "status": "invalid", "target": "agent_exec", "error": str(exc)}

    run_id = f"agent-exec-{stamp()}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    packet_file = run_dir / "packet.json"
    prompt_file = run_dir / "prompt.md"
    report_file = run_dir / "report.md"
    output_file = run_dir / "output.md"
    log_file = run_dir / "agent.log"
    receipt_file = run_dir / "receipt.json"
    settings_file = claude_settings_file(project, run_dir)

    sandbox_mode = str(packet.get("accessMode", {}).get("sandbox") or "workspace-write")
    prompt = agent_exec_prompt(
        project_dir=project,
        brief_path=brief,
        manager_message=manager_message,
        packet=packet,
        report_file=report_file,
        receipt_file=receipt_file,
    )

    packet_file.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompt_file.write_text(prompt + "\n", encoding="utf-8")

    agent_role = packet.get("role") if isinstance(packet.get("role"), dict) else {}
    adapter = str(agent_role.get("adapter") or "claude_cli")
    model = str(agent_role.get("model") or "sonnet")
    effort = str(agent_role.get("effort") or "low")
    receipt: dict[str, Any] = {
        "generatedAt": now(),
        "status": "dry-run" if dry_run else "queued",
        "mode": "brief",
        "target": "agent_exec",
        "targetRole": "Agent Exec",
        "projectDir": str(project),
        "briefPath": str(brief),
        "runDir": str(run_dir),
        "runId": run_id,
        "packet": str(packet_file),
        "prompt": str(prompt_file),
        "output": str(output_file),
        "log": str(log_file),
        "report": str(report_file),
        "receipt": str(receipt_file),
        "settings": str(settings_file),
        "adapter": adapter,
        "model": model,
        "effort": effort,
        "supportedAdapters": sorted(SUPPORTED_AGENT_ADAPTERS),
        "sandbox": sandbox_mode,
        "parentRunId": packet.get("parentRunId", ""),
        "intentId": packet.get("intentId", ""),
        "sharedDoctrineRefs": packet.get("sharedDoctrineRefs", []),
        "authModel": "local adapter OAuth/session; vendor API keys removed from dispatch environment",
        "transportMode": "dry-run" if dry_run else "detached-watch",
        "nextOwner": "Transport" if not dry_run else "Manager",
    }
    receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if adapter not in SUPPORTED_AGENT_ADAPTERS:
        receipt.update(
            {
                "status": "unsupported",
                "error": f"agent_exec adapter not supported in v1 runtime: {adapter}",
                "supportedAdapters": sorted(SUPPORTED_AGENT_ADAPTERS),
                "nextOwner": "Manager",
            }
        )
        receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return receipt

    binary = adapter_binary(adapter)
    binary_available = command_available(binary)
    if not dry_run and not binary_available:
        receipt.update({"status": "unavailable", "error": f"{adapter} binary not found: {binary}", "nextOwner": "Manager"})
        receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return receipt

    cmd = [
        sys.executable,
        str(ADAPTER_RUNNER_BIN),
        "agent-exec",
        "--adapter",
        adapter,
        "--project-dir",
        str(project),
        "--output",
        str(output_file),
        "--report",
        str(report_file),
        "--run-id",
        run_id,
        "--model",
        model,
        "--effort",
        effort,
        "--sandbox",
        sandbox_mode,
        "--settings",
        str(settings_file),
        "--brief-path",
        str(brief),
        "--codex-mcp-name",
        CODEX_MCP_NAME,
        "--nogra-mcp-bin",
        NOGRA_MCP_BIN,
    ]

    if dry_run:
        receipt.update(
            {
                "binary": binary,
                "binaryAvailable": binary_available,
                "commandPreview": cmd,
            }
        )
        receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return receipt

    transport_record = {
        "runId": run_id,
        "target": "agent_exec",
        "targetRole": "Agent Exec",
        "projectDir": str(project),
        "briefPath": str(brief),
        "mode": "brief",
        "model": model,
        "adapter": adapter,
        "effort": effort,
        "sandbox": sandbox_mode,
        "timeoutSeconds": timeout_seconds,
        "staleSeconds": int(os.environ.get("NOGRA_TRANSPORT_STALE_SECONDS") or os.environ.get("Y26_TRANSPORT_STALE_SECONDS", "120")),
        "parentRunId": packet.get("parentRunId", ""),
        "intentId": packet.get("intentId", ""),
        "sharedDoctrineRefs": packet.get("sharedDoctrineRefs", []),
        "transportMode": "detached-watch",
        "paths": {
            "runDir": str(run_dir),
            "packet": str(packet_file),
            "prompt": str(prompt_file),
            "output": str(output_file),
            "log": str(log_file),
            "report": str(report_file),
            "receipt": str(receipt_file),
            "settings": str(settings_file),
        },
        "command": cmd,
        "env": {
            "NOGRA_ROOT": str(ROOT),
            "Y26_ROOT": str(ROOT),
            "NOGRA_AGENT_EXEC": "1",
            "Y26_AGENT_EXEC": "1",
            "NOGRA_TRANSPORT_RUN_ID": run_id,
            "Y26_TRANSPORT_RUN_ID": run_id,
            "NOGRA_TRANSPORT_TARGET": "agent_exec",
            "NOGRA_AGENT_ADAPTER": adapter,
            "Y26_AGENT_ADAPTER": adapter,
            "NOGRA_AGENT_MODEL": model,
            "Y26_AGENT_MODEL": model,
            "NOGRA_AGENT_EFFORT": effort,
            "Y26_AGENT_EFFORT": effort,
            "STINSON_DISPATCH_ROLE": "agent",
            "STINSON_BRIEF_PATH": str(brief),
            "STINSON_REPORT_FILE": str(report_file),
            "NOGRA_PARENT_RUN_ID": str(packet.get("parentRunId") or ""),
            "Y26_PARENT_RUN_ID": str(packet.get("parentRunId") or ""),
            "NOGRA_INTENT_ID": str(packet.get("intentId") or ""),
            "Y26_INTENT_ID": str(packet.get("intentId") or ""),
            "CODEX_BIN": CODEX_BIN,
            "CLAUDE_BIN": CLAUDE_BIN,
            "GEMINI_BIN": GEMINI_BIN,
        },
        "cleanup": {
            "archiveAfterHours": 24,
            "orphanAfterSeconds": 900,
        },
    }

    transport_cleanup_state(archive_after_hours=24, orphan_after_seconds=900, max_events=5000, dry_run=False)
    transport_state = transport_register_run(transport_record)
    transport_state = transport_spawn_watcher(run_id)

    if not wait:
        receipt.update(
            {
                "status": "dispatched",
                "transportRun": transport_state,
                "nextOwner": "Transport",
            }
        )
        receipt_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return receipt

    waited = transport_wait_for_run(run_id, wait_seconds=wait_seconds or timeout_seconds + 30)
    returned = transport_return_payload(run_id, include_text=True)
    return finalized_transport_receipt(
        receipt=receipt,
        transport_record=transport_record,
        returned=returned,
        waited=waited,
        receipt_file=receipt_file,
        report_file=report_file,
        log_file=log_file,
        output_file=output_file,
    )


def chain_state_path(chain_id: str) -> Path:
    return CHAIN_STATE_DIR / f"{chain_id}.json"


def write_chain_state(state: dict[str, Any]) -> dict[str, Any]:
    CHAIN_STATE_DIR.mkdir(parents=True, exist_ok=True)
    state["updatedAt"] = now()
    path = chain_state_path(str(state["chainId"]))
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return state


def append_chain_event(state: dict[str, Any], event_type: str, **fields: Any) -> dict[str, Any]:
    chain_id = str(state.get("chainId") or "")
    payload = {
        "chainId": chain_id,
        "phase": fields.pop("phase", state.get("phase", "")),
        "pmRunId": fields.pop("pmRunId", state.get("pmRunId", "")),
        "agentRunId": fields.pop("agentRunId", state.get("agentRunId", "")),
        "verifyRunId": fields.pop("verifyRunId", state.get("verifyRunId", "")),
        "verifySignal": fields.pop("verifySignal", state.get("verifySignal", "")),
        "nextOwner": fields.pop("nextOwner", state.get("nextOwner", "")),
        **fields,
    }
    return transport_append_event(chain_id, event_type, **payload)


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate_chain_brief_path(brief: Path) -> None:
    if is_relative_to(brief, BRIEF_DRAFTS_DIR):
        raise ValueError(BRIEF_PROMOTE_ERROR)
    if not is_relative_to(brief, PROMOTED_BRIEFS_DIR):
        raise ValueError(BRIEF_PROMOTE_ERROR)


def is_brief_frontmatter_error(message: str) -> bool:
    lowered = message.lower()
    return "frontmatter" in lowered or "scope_files" in lowered or "project_dir" in lowered or "missing zone" in lowered


def chain_agent_error_message(receipt: dict[str, Any]) -> str:
    error = str(receipt.get("error") or "").strip()
    if is_brief_frontmatter_error(error):
        missing = []
        lowered = error.lower()
        if "scope_files" in lowered:
            missing.append("scope_files")
        if "project_dir" in lowered:
            missing.append("project_dir")
        if "zone" in lowered:
            missing.append("zone")
        detail = f" Missing: {', '.join(missing)}." if missing else ""
        return f"{BRIEF_FRONTMATTER_FIX}{detail} Original error: {error}"
    return error


def receipt_run_id(receipt: dict[str, Any]) -> str:
    run_id = str(receipt.get("runId") or receipt.get("run_id") or "").strip()
    if run_id:
        return run_id
    transport_run = receipt.get("transportRun") if isinstance(receipt.get("transportRun"), dict) else {}
    return str(transport_run.get("runId") or "").strip()


def receipt_status(receipt: dict[str, Any]) -> str:
    status = str(receipt.get("status") or receipt.get("resultStatus") or "").strip()
    if status:
        return status
    transport_run = receipt.get("transportRun") if isinstance(receipt.get("transportRun"), dict) else {}
    return str(transport_run.get("status") or transport_run.get("resultStatus") or "").strip()


def receipt_report_exists(receipt: dict[str, Any]) -> bool:
    if str(receipt.get("reportText") or "").strip():
        return True
    report_value = str(receipt.get("report") or "").strip()
    if not report_value:
        return False
    try:
        return Path(report_value).is_file() and Path(report_value).stat().st_size > 0
    except OSError:
        return False


def receipt_report_text(receipt: dict[str, Any]) -> str:
    text = str(receipt.get("reportText") or "").strip()
    if text:
        return text
    report_value = str(receipt.get("report") or "").strip()
    if not report_value:
        return ""
    try:
        return Path(report_value).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def child_receipt_pointer(receipt: dict[str, Any]) -> dict[str, Any]:
    transport_run = receipt.get("transportRun") if isinstance(receipt.get("transportRun"), dict) else {}
    paths = transport_run.get("paths") if isinstance(transport_run.get("paths"), dict) else {}
    pointer = {
        "runId": receipt_run_id(receipt),
        "status": receipt_status(receipt),
        "receipt": str(receipt.get("receipt") or paths.get("receipt") or ""),
        "report": str(receipt.get("report") or paths.get("report") or ""),
        "output": str(receipt.get("output") or paths.get("output") or ""),
        "runDir": str(receipt.get("runDir") or paths.get("runDir") or ""),
        "nextOwner": str(receipt.get("nextOwner") or transport_run.get("nextOwner") or ""),
        "parentRunId": str(receipt.get("parentRunId") or transport_run.get("parentRunId") or ""),
        "intentId": str(receipt.get("intentId") or transport_run.get("intentId") or ""),
    }
    return {key: value for key, value in pointer.items() if value != ""}


def build_pm_verify_message(*, brief: Path, agent_report_path: str, agent_run_id: str, chain_id: str) -> str:
    return f"""VERIFY MODE - Codex PM verify of Agent's execution.

You are not executing the brief. You are verifying that Agent's work matches it.

Brief: {brief}
Agent report: {agent_report_path}
Agent run id: {agent_run_id}
Chain id: {chain_id}

Verify the following, in this order:

1. Scope match: did Agent only touch files listed in brief's scope_files frontmatter?
   Check by reading Agent's "Files changed" section + grep'ing the listed paths against scope.
2. Acceptance criteria: each criterion in brief's success_criteria - is it marked done in Agent's report, with evidence?
   Acceptable evidence = file path + change description, command + output, or explicit BLOCKED with reason.
3. Runtime claims: if Agent reports "test passed", "build green", "endpoint returns 200" - re-run the command yourself if feasible. If not feasible, record "claim unverified".
4. Proposed deviations: if Agent's report has Proposed deviations, summarize what authority decision is needed.
5. Transport-owned-path conflicts: if the brief specifies report_path, log_path, output_path,
   run_dir, or receipt_path, and Agent writes to Transport's allocated path instead:
   CLASSIFY as afvigelse with reason "brief over-specified Transport-owned artifact path",
   NOT beslutning_kraeves. Existing doctrine (agent_exec_prompt + BRIEF-template) says
   Transport owns artifact paths. The conflict is a brief-template issue, not an authority question.

Return your verdict in this exact structure:

## Verify signal
ship | afvigelse | blocked | beslutning_kraeves

## Reasoning
<2-4 lines max - why this signal>

## Evidence
- scope: matched | drifted (paths)
- acceptance: N of M criteria met
- runtime claims: verified | unverified (which)
- deviations: none | <summary>

## Next step (recommendation, not authority)
<one line for Manager - e.g. "ship to CEO", "re-dispatch with narrowed scope", "request CEO call on deviation X">

You are read-only. Do not modify code. Do not write to brief or DECISIONS files.
"""


def markdown_section(text: str, heading: str) -> str:
    lines = text.splitlines()
    capture = False
    out: list[str] = []
    target = heading.strip().lower()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            current = stripped[3:].strip().lower()
            if capture and current != target:
                break
            capture = current == target
            continue
        if capture:
            out.append(line)
    return "\n".join(out).strip()


def normalize_verify_signal(value: str) -> str:
    cleaned = value.strip().lower()
    cleaned = cleaned.replace("æ", "ae").replace("ø", "oe").replace("å", "aa")
    cleaned = cleaned.replace("-", "_").replace(" ", "_")
    cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch == "_")
    if cleaned in {"ship", "afvigelse", "blocked", "beslutning_kraeves"}:
        return cleaned
    if cleaned.startswith("beslutning"):
        return "beslutning_kraeves"
    return ""


def parse_verify_signal(report_text: str) -> tuple[str, str]:
    signal_section = markdown_section(report_text, "Verify signal")
    signal = ""
    for line in signal_section.splitlines() or report_text.splitlines()[:20]:
        stripped = line.strip().strip("`").strip()
        if not stripped or "|" in stripped:
            continue
        signal = normalize_verify_signal(stripped)
        if signal:
            break
    if not signal:
        signal = "blocked"

    reasoning = markdown_section(report_text, "Reasoning")
    evidence = markdown_section(report_text, "Evidence")
    summary = "\n".join(part for part in (reasoning, evidence) if part).strip()
    if not summary:
        summary = report_text.strip()
    lines = [line.strip() for line in summary.splitlines() if line.strip()]
    return signal, "\n".join(lines[:8])[:1200]


def run_chain_pm_then_agent(
    project_dir: str,
    brief_path: str,
    manager_message: str = "",
    intent_id: str = "",
    timeout_per_phase_seconds: int = 900,
) -> dict[str, Any]:
    try:
        project = resolve_existing_project(project_dir)
        brief = resolve_optional_brief(project, brief_path)
        if brief is None:
            raise ValueError("brief_path required for pm_then_agent chain")
        validate_chain_brief_path(brief)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        return {"generatedAt": now(), "status": "invalid", "error": str(exc)}

    chain_id = f"chain-{stamp()}"
    created_at = now()
    phase_timeout = max(1, int(timeout_per_phase_seconds or 1))
    state: dict[str, Any] = {
        "chainId": chain_id,
        "intentId": intent_id.strip(),
        "phase": "pm_execute",
        "pmRunId": "",
        "agentRunId": "",
        "verifyRunId": "",
        "verifySignal": "",
        "verifyEvidence": "",
        "briefPath": str(brief),
        "projectDir": str(project),
        "createdAt": created_at,
        "updatedAt": created_at,
        "nextOwner": "Transport",
        "status": "running",
    }
    write_chain_state(state)
    append_chain_event(state, "chain_created")

    pm_receipt = run_transport_codex_dispatch(
        project_dir=str(project),
        brief_path=str(brief),
        manager_message=manager_message,
        timeout_seconds=phase_timeout,
        wait=True,
    )
    pm_run_id = receipt_run_id(pm_receipt)
    state["pmRunId"] = pm_run_id

    pm_status = receipt_status(pm_receipt)
    if pm_status != "ok" or not receipt_report_exists(pm_receipt):
        state.update({"phase": "blocked", "nextOwner": "Manager", "status": "failed"})
        write_chain_state(state)
        append_chain_event(
            state,
            "chain_blocked",
            reason="pm_execute_failed_or_missing_report",
            pmStatus=pm_status,
            pmReportExists=receipt_report_exists(pm_receipt),
        )
        return {
            "generatedAt": now(),
            "status": state["status"],
            "chain": state,
            "chainStatePath": str(chain_state_path(chain_id)),
            "pm": child_receipt_pointer(pm_receipt),
            "agent": {},
            "verify": {},
        }

    append_chain_event(state, "chain_phase_pm_execute_done", phase="pm_execute", pmRunId=pm_run_id, pmStatus=pm_status)
    state["phase"] = "agent_execute"
    write_chain_state(state)

    agent_receipt = run_transport_agent_exec_dispatch(
        project_dir=str(project),
        brief_path=str(brief),
        manager_message=manager_message,
        timeout_seconds=phase_timeout,
        wait=True,
        parent_run_id=chain_id,
        intent_id=intent_id,
    )
    agent_run_id = receipt_run_id(agent_receipt)
    agent_status = receipt_status(agent_receipt)
    state["agentRunId"] = agent_run_id
    append_chain_event(
        state,
        "chain_phase_agent_execute_done",
        phase="agent_execute",
        agentRunId=agent_run_id,
        agentStatus=agent_status,
    )

    if agent_status in {"ok", "partial"}:
        agent_pointer = child_receipt_pointer(agent_receipt)
        agent_report_path = str(agent_pointer.get("report") or "")
        state["phase"] = "pm_verify"
        write_chain_state(state)
        append_chain_event(state, "chain_phase_pm_verify_started", phase="pm_verify", agentStatus=agent_status)

        verify_message = build_pm_verify_message(
            brief=brief,
            agent_report_path=agent_report_path,
            agent_run_id=agent_run_id,
            chain_id=chain_id,
        )
        verify_receipt = run_transport_codex_dispatch(
            project_dir=str(project),
            brief_path="",
            manager_message=verify_message,
            timeout_seconds=phase_timeout,
            sandbox="read-only",
            wait=True,
        )
        verify_run_id = receipt_run_id(verify_receipt)
        verify_status = receipt_status(verify_receipt)
        state["verifyRunId"] = verify_run_id

        if verify_status not in {"ok", "partial"} or not receipt_report_exists(verify_receipt):
            state.update(
                {
                    "phase": "blocked",
                    "nextOwner": "Manager",
                    "status": "failed",
                    "verifySignal": "blocked",
                    "verifyEvidence": f"PM verify dispatch failed or returned no report. status={verify_status}",
                }
            )
            write_chain_state(state)
            append_chain_event(
                state,
                "chain_phase_pm_verify_done",
                phase="pm_verify",
                verifyRunId=verify_run_id,
                verifySignal=state["verifySignal"],
                verifyStatus=verify_status,
                verifyReportExists=receipt_report_exists(verify_receipt),
            )
            append_chain_event(state, "chain_blocked", reason="pm_verify_failed", verifyStatus=verify_status)
            return {
                "generatedAt": now(),
                "status": state["status"],
                "chain": state,
                "chainStatePath": str(chain_state_path(chain_id)),
                "pm": child_receipt_pointer(pm_receipt),
                "agent": agent_pointer,
                "verify": child_receipt_pointer(verify_receipt),
            }

        verify_signal, verify_evidence = parse_verify_signal(receipt_report_text(verify_receipt))
        state.update(
            {
                "phase": "complete",
                "nextOwner": "Manager",
                "status": "complete",
                "verifySignal": verify_signal,
                "verifyEvidence": verify_evidence,
            }
        )
        write_chain_state(state)
        append_chain_event(
            state,
            "chain_phase_pm_verify_done",
            phase="pm_verify",
            verifyRunId=verify_run_id,
            verifySignal=verify_signal,
            verifyStatus=verify_status,
        )
        append_chain_event(state, "chain_complete", agentStatus=agent_status, verifySignal=verify_signal)
    else:
        agent_error = chain_agent_error_message(agent_receipt)
        update = {"phase": "blocked", "nextOwner": "Manager", "status": "failed"}
        if agent_error:
            update["error"] = agent_error
        state.update(update)
        write_chain_state(state)
        append_chain_event(state, "chain_blocked", reason="agent_execute_failed", agentStatus=agent_status, error=agent_error)
        return {
            "generatedAt": now(),
            "status": state["status"],
            "error": agent_error,
            "chain": state,
            "chainStatePath": str(chain_state_path(chain_id)),
            "pm": child_receipt_pointer(pm_receipt),
            "agent": child_receipt_pointer(agent_receipt),
            "verify": {},
        }

    return {
        "generatedAt": now(),
        "status": state["status"],
        "chain": state,
        "chainStatePath": str(chain_state_path(chain_id)),
        "pm": child_receipt_pointer(pm_receipt),
        "agent": child_receipt_pointer(agent_receipt),
        "verify": child_receipt_pointer(verify_receipt),
    }


def self_test() -> int:
    payload = {
        "registry": registry_payload(),
        "roleConfig": role_config_payload(),
        "repoStatus": repo_status_payload(),
        "codexFullPacket": codex_packet_payload("Hvad ser du?", "full"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def run_mcp_server() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.server.fastmcp.prompts import base
        from pydantic import Field
    except ModuleNotFoundError as exc:
        print(
            "nogra-mcp: missing Python dependency. Run via manager/bin/nogra-mcp or install mcp[cli].",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    mcp = FastMCP(f"{PRODUCT_NAME} MCP", log_level=os.environ.get("NOGRA_MCP_LOG_LEVEL") or os.environ.get("Y26_MCP_LOG_LEVEL", "ERROR"))

    @mcp.resource("nogra://registry", mime_type="application/json")
    def registry_resource() -> dict[str, Any]:
        return registry_payload()

    @mcp.resource("nogra://workflow/roles", mime_type="application/json")
    def workflow_roles_resource() -> dict[str, Any]:
        return workflow_roles_payload()

    @mcp.resource("nogra://roles/config", mime_type="application/json")
    def role_config_resource() -> dict[str, Any]:
        return role_config_payload()

    @mcp.resource("nogra://transcript/latest", mime_type="application/json")
    def latest_transcript_resource() -> dict[str, Any]:
        return latest_transcript_payload()

    @mcp.resource("nogra://state/latest-work", mime_type="application/json")
    def latest_work_resource() -> dict[str, Any]:
        return latest_work_payload()

    @mcp.resource("nogra://transport/runs", mime_type="application/json")
    def transport_runs_resource() -> dict[str, Any]:
        return {"generatedAt": now(), "status": "ok", "runs": transport_recent_runs(limit=30)}

    @mcp.resource("nogra://transport/events", mime_type="application/json")
    def transport_events_resource() -> dict[str, Any]:
        return {"generatedAt": now(), "status": "ok", "events": transport_read_events(limit=120)}

    @mcp.resource("nogra://repo/status", mime_type="application/json")
    def repo_status_resource() -> dict[str, Any]:
        return repo_status_payload()

    @mcp.tool(name="nogra_registry", description=f"List {PRODUCT_NAME} MCP prompts, resources and tools with metadata.")
    def nogra_registry() -> dict[str, Any]:
        return registry_payload()

    @mcp.tool(name="nogra_repo_status", description="Read-only git status snapshot for the local workflow repo.")
    def nogra_repo_status() -> dict[str, Any]:
        return repo_status_payload()

    @mcp.tool(name="nogra_latest_work", description="Read-only latest-work snapshot through transport-state.")
    def nogra_latest_work() -> dict[str, Any]:
        return latest_work_payload()

    @mcp.tool(name="nogra_role_config", description="Read V1 role/model adapter config. Roles are functions; users choose models.")
    def nogra_role_config() -> dict[str, Any]:
        return role_config_payload()

    @mcp.tool(
        name="transport_dispatch",
        description=f"Dispatch a target through {PRODUCT_NAME} Transport and return a run id; Transport owns watch/return/cleanup.",
    )
    def transport_dispatch(
        target: str = Field(default="codex_pm", description="Dispatch target. Supported: codex_pm/codex, agent_exec/agent."),
        project_dir: str = Field(default=str(ROOT), description="Project directory for the dispatch."),
        brief_path: str = Field(default="", description="Approved brief path for implementation dispatch."),
        manager_message: str = Field(default="", description="Manager instruction when no brief is supplied."),
        timeout_seconds: int = Field(default=600, description="Total target timeout before Transport returns timeout."),
        sandbox: str = Field(default="", description="Optional target sandbox override."),
        wait: bool = Field(default=False, description="If true, wait for return using transport_watch semantics."),
        wait_seconds: int = Field(default=0, description="Optional wait timeout. Defaults to target timeout + 30s."),
        dry_run: bool = Field(default=False, description="If true, write packet/receipt without invoking the target."),
        parent_run_id: str = Field(default="", description="Parent PM/Transport run id for child graph linkage."),
        intent_id: str = Field(default="", description="Stable intent id for grouping child runs."),
        shared_doctrine_refs: str = Field(default="", description="Comma/newline separated shared doctrine refs for multi-agent cohesion."),
    ) -> dict[str, Any]:
        normalized_target = target.strip().lower().replace("-", "_")
        if normalized_target in {"codex", "codex_pm"}:
            return run_transport_codex_dispatch(
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
            return run_transport_agent_exec_dispatch(
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
            "generatedAt": now(),
            "status": "unsupported",
            "target": target,
            "supportedTargets": ["codex_pm", "agent_exec"],
        }

    @mcp.tool(
        name="agent_exec_packet",
        description="Build an Agent Exec dispatch packet without invoking execution.",
    )
    def agent_exec_packet(
        project_dir: str = Field(description="Project directory for Agent Exec."),
        brief_path: str = Field(description="Approved brief path. Required for Agent Exec."),
        manager_message: str = Field(default="", description="Manager/PM supplement; does not replace brief authority."),
        sandbox: str = Field(default="", description="Optional target sandbox override."),
        parent_run_id: str = Field(default="", description="Parent PM/Transport run id for child graph linkage."),
        intent_id: str = Field(default="", description="Stable intent id for grouping child runs."),
        shared_doctrine_refs: str = Field(default="", description="Comma/newline separated shared doctrine refs for multi-agent cohesion."),
    ) -> dict[str, Any]:
        try:
            return agent_exec_packet_payload(
                project_dir=project_dir,
                brief_path=brief_path,
                manager_message=manager_message,
                sandbox=sandbox,
                parent_run_id=parent_run_id,
                intent_id=intent_id,
                shared_doctrine_refs=shared_doctrine_refs,
            )
        except (FileNotFoundError, PermissionError, ValueError, subprocess.TimeoutExpired) as exc:
            return {
                "generatedAt": now(),
                "status": "invalid",
                "target": "agent_exec",
                "error": str(exc),
            }

    @mcp.tool(name="transport_status", description="Read live Transport run state without polling target tools directly.")
    def transport_status(
        run_id: str = Field(default="", description="Transport run id. Empty returns recent runs."),
        include_archive: bool = Field(default=False, description="Include archived transport state."),
        limit: int = Field(default=20, description="Recent run count when run_id is empty."),
    ) -> dict[str, Any]:
        if run_id.strip():
            record = transport_load_run(run_id.strip(), include_archive=include_archive)
            return transport_public_run(record) if record else {"generatedAt": now(), "status": "missing", "runId": run_id}
        return {"generatedAt": now(), "status": "ok", "runs": transport_recent_runs(limit=limit, include_archive=include_archive)}

    @mcp.tool(name="transport_watch", description="Await a Transport run until return/timeout without Manager-owned polling.")
    def transport_watch(
        run_id: str = Field(description="Transport run id."),
        wait_seconds: int = Field(default=900, description="How long this convenience call should wait."),
    ) -> dict[str, Any]:
        return transport_wait_for_run(run_id=run_id, wait_seconds=wait_seconds)

    @mcp.tool(name="transport_return", description="Return report/output payload and next owner for a Transport run.")
    def transport_return(
        run_id: str = Field(default="", description="Transport run id. Empty returns latest run."),
        include_text: bool = Field(default=True, description="Include report/output text in response."),
    ) -> dict[str, Any]:
        return transport_return_payload(run_id=run_id, include_text=include_text)

    @mcp.tool(name="transport_submit_report", description="Submit a Transport run report through MCP; Transport writes run artifacts and receipts.")
    def transport_submit_report(
        report_text: str = Field(description="Complete structured report content to persist for the current Transport run."),
        run_id: str = Field(default="", description="Transport run id. Empty uses NOGRA_TRANSPORT_RUN_ID allocated by dispatch."),
        status: str = Field(default="", description="Optional target status label such as ok, partial, blocked or failed. Aliases complete/completed/succeeded map to ok."),
        summary: str = Field(default="", description="Optional one-line summary for the Transport event/inbox trail."),
        output_text: str = Field(default="", description="Optional final output text. Defaults to report_text."),
        allow_overwrite: bool = Field(default=False, description="If true, replace an existing report artifact."),
    ) -> dict[str, Any]:
        return transport_submit_report_runtime(
            run_id=run_id,
            report_text=report_text,
            status=status,
            summary=summary,
            output_text=output_text,
            allow_overwrite=allow_overwrite,
            source="mcp",
        )

    @mcp.tool(name="transport_ack", description="Acknowledge a returned Transport run so cleanup can archive it.")
    def transport_ack(
        run_id: str = Field(default="", description="Transport run id. Empty acknowledges latest active returned run."),
        note: str = Field(default="", description="Optional Manager acknowledgement note."),
    ) -> dict[str, Any]:
        return transport_ack_run(run_id=run_id, note=note)

    @mcp.tool(name="transport_cleanup", description="Clean stale Transport state, archive acknowledged returns and rotate events.")
    def transport_cleanup(
        archive_after_hours: float = Field(default=24, description="Archive returned runs older than this or acknowledged runs."),
        orphan_after_seconds: int = Field(default=900, description="Mark dead active runs as orphaned after this age."),
        max_events: int = Field(default=5000, description="Keep this many recent events before rotation."),
        max_log_bytes: int = Field(default=0, description="If >0, gzip full completed logs above this size and keep a tail."),
        dry_run: bool = Field(default=False, description="If true, report cleanup actions without mutating state."),
    ) -> dict[str, Any]:
        return transport_cleanup_state(
            archive_after_hours=archive_after_hours,
            orphan_after_seconds=orphan_after_seconds,
            max_events=max_events,
            max_log_bytes=max_log_bytes,
            dry_run=dry_run,
        )

    @mcp.tool(name="transport_events", description="Read the Transport event ledger for pinboard/Manager visibility.")
    def transport_events(
        run_id: str = Field(default="", description="Optional run id filter."),
        limit: int = Field(default=80, description="Number of recent events to return."),
    ) -> dict[str, Any]:
        return {"generatedAt": now(), "status": "ok", "events": transport_read_events(limit=limit, run_id=run_id)}

    @mcp.tool(
        name="codex_fresh_eyes_packet",
        description="Build a raw-context packet for /codex or /codex full without invoking execution.",
    )
    def codex_fresh_eyes_packet(
        question: str = Field(default="", description="CEO/Manager question for Codex."),
        mode: str = Field(default="current", description="current, full, or pm."),
    ) -> dict[str, Any]:
        return codex_packet_payload(question=question, mode=mode)

    @mcp.tool(
        name="codex_fresh_eyes",
        description="Run /codex fresh-eyes through local Codex OAuth/session using MCP context resources.",
    )
    def codex_fresh_eyes(
        question: str = Field(default="", description="CEO/Manager question or solution for Codex to inspect."),
        mode: str = Field(default="current", description="current, full, or pm."),
        cwd: str = Field(default="", description=f"Working directory for Codex. Defaults to {PRODUCT_NAME} root."),
        dry_run: bool = Field(default=False, description="If true, write packet/prompt/receipt but do not invoke Codex."),
        timeout_seconds: int = Field(default=240, description="Timeout for local codex exec."),
    ) -> dict[str, Any]:
        return run_codex_fresh_eyes(
            question=question,
            mode=mode,
            cwd=cwd,
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
        )

    @mcp.tool(
        name="codex_dispatch_packet",
        description="Build a formal Codex PM dispatch packet without invoking execution.",
    )
    def codex_dispatch_packet(
        project_dir: str = Field(description="Project directory for Codex PM."),
        brief_path: str = Field(default="", description="Approved brief path. Enables implementation dispatch."),
        manager_message: str = Field(default="", description="Manager instruction when no brief is supplied."),
        sandbox: str = Field(default="", description="Optional Codex sandbox override."),
    ) -> dict[str, Any]:
        return codex_dispatch_packet_payload(
            project_dir=project_dir,
            brief_path=brief_path,
            manager_message=manager_message,
            sandbox=sandbox,
        )

    @mcp.tool(
        name="codex_dispatch",
        description="Run formal Codex PM through local Codex OAuth/session with bounded dispatch receipts.",
    )
    def codex_dispatch(
        project_dir: str = Field(description="Project directory for Codex PM."),
        brief_path: str = Field(default="", description="Approved brief path. Enables workspace-write dispatch."),
        manager_message: str = Field(default="", description="Read-only PM instruction when no brief is supplied."),
        dry_run: bool = Field(default=False, description="Write packet/prompt/receipt but do not invoke Codex."),
        timeout_seconds: int = Field(default=600, description="Timeout for local codex exec."),
        sandbox: str = Field(default="", description="Optional Codex sandbox override."),
    ) -> dict[str, Any]:
        return run_transport_codex_dispatch(
            project_dir=project_dir,
            brief_path=brief_path,
            manager_message=manager_message,
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            sandbox=sandbox,
            wait=True,
        )

    @mcp.prompt(name="codex", description=f"/codex fresh-eyes prompt for current {PRODUCT_NAME} conversation.")
    def codex_prompt(
        question: str = Field(default="", description="Question or solution to inspect."),
    ) -> list[Any]:
        return [base.UserMessage(prompt_text(question=question, mode="current"))]

    @mcp.prompt(name="codex_full", description=f"/codex full prompt with transcript and {PRODUCT_NAME} context resources.")
    def codex_full_prompt(
        question: str = Field(default="", description="Question or solution to inspect with full context."),
    ) -> list[Any]:
        return [base.UserMessage(prompt_text(question=question, mode="full"))]

    mcp.run(transport="stdio")


def main() -> int:
    parser = argparse.ArgumentParser(description=f"{PRODUCT_NAME} universal MCP server")
    parser.add_argument("--self-test", action="store_true", help="Print registry/context smoke payload without MCP runtime.")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    run_mcp_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
