from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import runtime as nogra_runtime


NAME = "nogra-mcp"
RELEASE_VERSION = "v1.0.0"
VERSION = RELEASE_VERSION


def _truthy_value(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


HOSTED_AT_IMPORT = _truthy_value(os.environ.get("NOGRA_HOSTED", ""))

_WORKSPACE_LABEL_CACHE: str | None = None


def workspace_label() -> str:
    """Resolve and cache the workspace label used in public payloads.

    This is the LABEL only (top-level workspaceId, serverWorkspaceId, resource
    URIs) -- never the data path, which already resolves against the caller's
    cwd via workspace_root().

    Hosted branch is untouched: same env-based lookup as before, still eager
    in spirit (no filesystem read either way).

    Non-hosted precedence:
      1. Explicit NOGRA_WORKSPACE_ID env override wins (dev/private wrapper).
      2. Else the resolved workspace's .nogra/config.json "workspaceId".
      3. Else "local".

    Resolution never runs at import time -- only on first call -- and the
    result is cached for the life of the process.
    """
    global _WORKSPACE_LABEL_CACHE
    if _WORKSPACE_LABEL_CACHE is not None:
        return _WORKSPACE_LABEL_CACHE
    if HOSTED_AT_IMPORT:
        _WORKSPACE_LABEL_CACHE = os.environ.get("NOGRA_HOSTED_WORKSPACE_ID", "nogra-hosted")
        return _WORKSPACE_LABEL_CACHE
    explicit = os.environ.get("NOGRA_WORKSPACE_ID", "").strip()
    if explicit:
        _WORKSPACE_LABEL_CACHE = explicit
        return _WORKSPACE_LABEL_CACHE
    _WORKSPACE_LABEL_CACHE = clean_inline(workspace_config().get("workspaceId")) or "local"
    return _WORKSPACE_LABEL_CACHE

TOOLS = [
    "init",
    "optional_feature_bundle",
    "registry",
    "brief_contract",
    "provider_handoff",
    "provider_handoff_read",
    "redact_text",
    "post_event",
    "update_run",
    "recent_events",
    "recent_runs",
    "brief_save",
    "brief_validate",
    "brief_promote",
    "brief_read",
    "recent_briefs",
    "transport_register",
    "transport_update",
    "transport_abort",
    "dispatch_handoff",
]

PROMPTS = [
    {
        "name": "init",
        "description": "Bootstrap Nogra in this Claude Code workspace from the connected MCP server.",
    },
]

PUBLIC_PACKAGE_JSON_RESOURCES = {
    "nogra://public/toolbank/claude-tools": "toolbank/claude-tools.json",
    "nogra://public/schemas/init-bundle-v1": "schemas/init-bundle-v1.schema.json",
    "nogra://public/schemas/dispatch-handoff-v1": "schemas/dispatch-handoff-v1.schema.json",
    "nogra://public/schemas/brief-v1": "schemas/brief-v1.schema.json",
    "nogra://public/schemas/run-v1": "schemas/run-v1.schema.json",
    "nogra://public/schemas/run-event-v1": "schemas/run-event-v1.schema.json",
    "nogra://public/templates/dispatch-handoff-v1": "templates/dispatch-handoff-v1.json",
    "nogra://public/templates/run-v1": "templates/run-v1.json",
    "nogra://public/templates/run-event-v1": "templates/run-event-v1.json",
    "nogra://public/examples/dispatch-handoff-v1": "examples/objects/dispatch-handoff-v1.json",
    "nogra://public/examples/run-v1": "examples/objects/run-v1.json",
    "nogra://public/examples/run-event-v1": "examples/objects/run-event-v1.json",
}

PUBLIC_PACKAGE_TEXT_RESOURCES = {
    "nogra://public/templates/brief-v1": "templates/brief-v1.md",
    "nogra://public/examples/brief-v1": "examples/objects/brief-v1.md",
}

PUBLIC_RESOURCES = [
    "nogra://public/registry",
    "nogra://public/toolbank/claude-tools",
    "nogra://public/schemas/provider-handoff-v1",
    "nogra://public/schemas/init-bundle-v1",
    "nogra://public/schemas/dispatch-handoff-v1",
    "nogra://public/schemas/brief-v1",
    "nogra://public/schemas/run-v1",
    "nogra://public/schemas/run-event-v1",
    "nogra://public/templates/brief-v1",
    "nogra://public/templates/dispatch-handoff-v1",
    "nogra://public/templates/run-v1",
    "nogra://public/templates/run-event-v1",
    "nogra://public/examples/brief-v1",
    "nogra://public/examples/dispatch-handoff-v1",
    "nogra://public/examples/run-v1",
    "nogra://public/examples/run-event-v1",
]

MODES = {"neutral", "fresh-eyes", "critique", "ideation"}
PROVIDER_INTENTS = {"consult", "review", "delegate", "gate"}
PROVIDER_SURFACES = {"pass-through", "manager-summary", "conditional-loud"}
BRIEF_SCHEMA = "nogra.brief.v1"
DEFAULT_TARGET_MODEL = "anthropic:sonnet"
DEFAULT_BRIEF_POLICY = {
    "defaultDepth": "thorough",
    "hardLimit": None,
    "guidance": "Use as much detail as needed to make the work executable and verifiable.",
}
DEFAULT_RETURN_POLICY = {
    "format": "evidence-first state brief",
    "limit": "no hard word limit; keep the opening summary concise and include all evidence needed to verify the result",
}
DEFAULT_RUNTIME_POLICY = {
    "profile": "balanced",
    "roles": {
        "manager": {
            "model": "inherit",
            "effort": "auto",
            "context": "session",
            "enforcement": "advisory-main-session",
        },
        "agent": {
            "model": "sonnet",
            "effort": "high",
            "context": "default",
            "maxTurns": None,
        },
        "verifier": {
            "model": "sonnet",
            "effort": "medium",
            "context": "default",
            "maxTurns": None,
        },
    },
    "budget": {
        "mode": "balanced",
        "maxUsdPerRun": None,
        "warnUsdPerRun": None,
    },
}
DEFAULT_ROUTING_POLICY = {
    "autoOfferEnabled": True,
    "sensitivityPercent": 50,
    "sensitivityStepPercent": 5,
    "autoOfferThreshold": 60,
    "strongOfferThreshold": 80,
    "offerOncePerIntent": True,
    "topicGate": True,
    "defaultLanguage": "en",
    "translationFallback": "claude-current-prompt",
    "scoring": {
        "createIntent": 25,
        "productSurface": 20,
        "evidenceNeed": 20,
        "completionClaim": 20,
        "qualityCritical": 15,
        "riskyDomain": 15,
        "ambiguity": 10,
        "lowRiskEdit": -30,
        "singleFileLowScope": -15,
        "directOverride": -40,
        "pureQuestion": -50,
    },
    "dictionary": {
        "createIntent": ["build", "create", "make", "scaffold", "implement", "write", "edit", "change", "design", "fix", "debug", "refactor", "deploy", "verify", "test", "check"],
        "productSurface": ["app", "site", "website", "page", "landing page", "dashboard", "ui", "ux", "frontend", "component", "view", "screen", "hero", "full viewport", "viewport", "react", "tailwind", "html", "css", "browser", "screenshot", "inspiration"],
        "evidenceNeed": ["test", "build check", "screenshot", "browser", "evidence", "verify", "verification", "check", "qa"],
        "completionClaim": ["done", "finished", "complete", "actually done", "claim checked"],
        "qualityCritical": ["visual", "polished", "beautiful", "design", "brand", "animation", "motion", "inspiration"],
        "riskyDomain": ["auth", "database", "db", "schema", "migration", "payment", "security", "deploy", "production", "prod", "api", "backend", "permission", "permissions"],
        "ambiguity": ["unclear", "risky", "hard to revert"],
        "lowRiskEdit": ["readme", "one sentence", "single sentence", "hello nogra"],
        "singleFileLowScope": ["single file", "one file"],
        "directOverride": ["direct", "skip brief", "skip nogra", "no nogra", "without nogra", "no ceremony", "just build"],
        "toggleOn": ["nogra on", "enable nogra", "turn on nogra", "use nogra here", "use nogra for this"],
        "toggleOff": ["nogra off", "disable nogra", "turn off nogra"],
    },
}
BRIEF_STATUSES = {"draft", "ready", "approved", "in_progress", "returned", "accepted", "archived"}
BRIEF_EVIDENCE = {"reported", "edited", "tested", "verified"}
BRIEF_EVIDENCE_GUIDANCE = {
    "reported": "Use when completion is asserted in the report but no diff, command or external check proves it.",
    "edited": "Use when changed files or a diff prove the workspace was mutated as intended.",
    "tested": "Use when a command, test or check was run and its exit/result is part of the evidence.",
    "verified": "Use when evidence includes an observation beyond the executor's own claim, such as browser, HTTP, screenshot, verifier or human review. Screenshots and browser checks are evidence methods for relevant outcomes, not success criteria by themselves. This is an evidence level, not an automatic requirement to spawn a verifier agent.",
}
TRANSPORT_RUN_SCHEMA = "nogra.transport.run.v1"
TRANSPORT_EVENT_SCHEMA = "nogra.transport.event.v1"
DISPATCH_HANDOFF_SCHEMA = "nogra.dispatch.handoff.v1"
INIT_BUNDLE_SCHEMA = "nogra.init.bundle.v1"
INIT_BUNDLE_VERSION = RELEASE_VERSION
INIT_BUNDLE_MANIFEST = "init-bundle/manifest.json"
INIT_BUNDLE_MODES = {"standalone", "plugin"}
TRANSPORT_STATUSES = {
    "queued",
    "running",
    "stale",
    "returning",
    "returned",
    "ok",
    "partial",
    "blocked",
    "failed",
    "timeout",
    "cancelled",
    "orphaned",
    "acknowledged",
}
TRANSPORT_PHASES = {"queued", "running", "returning", "returned", "acknowledged", "archived"}
TRANSPORT_TERMINAL_STATUSES = {"ok", "partial", "blocked", "failed", "timeout", "cancelled", "orphaned"}
TRANSPORT_RETURNABLE_STATUSES = TRANSPORT_TERMINAL_STATUSES | {"returned", "acknowledged"}
TRANSPORT_ACTIVE_STATUSES = {"queued", "running", "stale", "returning"}
TRANSPORT_STATUS_ALIASES = {
    "complete": "ok",
    "completed": "ok",
    "success": "ok",
    "succeeded": "ok",
    "ship": "ok",
    "done": "ok",
}
BRIEF_REQUIRED = [
    "schema",
    "releaseVersion",
    "briefId",
    "workspaceId",
    "title",
    "createdAt",
    "intent",
    "contextHandoff",
    "scope",
    "successCriteria",
    "stopCriteria",
    "maxOutput",
]

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "api-key-shape",
        re.compile(r"\b(?:sk|pk|rk|xoxb|ghp|gho|ghu|ghs)_[A-Za-z0-9_\-]{16,}\b"),
    ),
    (
        "assignment-secret",
        re.compile(
            r"(?i)\b(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*"
            r"['\"]?([A-Za-z0-9_\-./+=]{12,})['\"]?"
        ),
    ),
    ("bearer-token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_\-./+=]{12,}")),
]


class Runtime:
    @property
    def workspace_id(self) -> str:
        return workspace_label()

    @property
    def workspace_root(self) -> Path:
        return workspace_root()

    @property
    def nogra_dir(self) -> Path:
        return nogra_dir()

    @property
    def package_root(self) -> Path:
        return package_root()

    def now(self) -> str:
        return now()

    def registry(self) -> dict[str, Any]:
        return registry_payload()


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def package_root() -> Path:
    configured = os.environ.get("NOGRA_MCP_ROOT", "").strip() or os.environ.get("NOGRA_PUBLIC_MCP_ROOT", "").strip()
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[2]


def workspace_root() -> Path:
    configured = os.environ.get("NOGRA_WORKSPACE", "").strip()
    if configured:
        return Path(configured).resolve()
    if HOSTED_AT_IMPORT:
        return Path(os.environ.get("NOGRA_HOSTED_WORKSPACE") or os.environ.get("TMPDIR", "/tmp")) / "nogra-hosted-workspace"
    # Public/plugin mode with no explicit NOGRA_WORKSPACE: resolve against the
    # launching process's current working directory (the caller's project
    # root) instead of the package's bundled example fixture. This is what
    # lets a plugin-bundled `uvx nogra-mcp` registration (no env vars) operate
    # against the user's actual workspace. Dev/private and hosted paths are
    # unaffected because they always set NOGRA_WORKSPACE explicitly.
    try:
        return Path.cwd().resolve()
    except OSError:
        return package_root() / "examples" / "workspaces" / "y26-private"


def nogra_dir() -> Path:
    return workspace_root() / ".nogra"


def default_nogra_dir() -> Path:
    return package_root() / "defaults" / ".nogra"


def safe_id(value: str, prefix: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())[:80].strip(".-")
    if cleaned:
        return cleaned
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def clean_text(value: Any) -> str:
    return str(value if value is not None else "").replace("\r\n", "\n").strip()


def clean_inline(value: Any) -> str:
    return re.sub(r"\s+", " ", clean_text(value)).strip()


def normalize_transport_status(value: Any) -> str:
    status = clean_inline(value).lower()
    return TRANSPORT_STATUS_ALIASES.get(status, status)


def transport_status_invalid(run_id: str, status: str) -> dict[str, Any]:
    return {
        "status": "invalid",
        "runId": run_id,
        "error": f"transport status is not valid: {status}",
        "validValues": sorted(TRANSPORT_STATUSES),
        "acceptedAliases": TRANSPORT_STATUS_ALIASES,
    }


def env_truthy(name: str) -> bool:
    return _truthy_value(os.environ.get(name, ""))


def hosted_mode() -> bool:
    return env_truthy("NOGRA_HOSTED")


def private_modules_enabled() -> bool:
    return env_truthy("NOGRA_ENABLE_PRIVATE")


def private_module() -> Any:
    from . import y26_private

    return y26_private


def default_target_model() -> str:
    return clean_inline(os.environ.get("NOGRA_DEFAULT_TARGET_MODEL") or DEFAULT_TARGET_MODEL)


def workspace_config() -> dict[str, Any]:
    path = nogra_dir() / "config.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def default_brief_policy() -> dict[str, Any]:
    config = workspace_config()
    candidate = config.get("briefPolicy") if isinstance(config.get("briefPolicy"), dict) else {}
    return {
        "defaultDepth": clean_inline(candidate.get("defaultDepth") or DEFAULT_BRIEF_POLICY["defaultDepth"]),
        "hardLimit": candidate.get("hardLimit") if "hardLimit" in candidate else DEFAULT_BRIEF_POLICY["hardLimit"],
        "guidance": clean_inline(candidate.get("guidance") or DEFAULT_BRIEF_POLICY["guidance"]),
    }


def default_return_policy() -> dict[str, str]:
    config = workspace_config()
    candidate = config.get("returnPolicy") if isinstance(config.get("returnPolicy"), dict) else {}
    return {
        "format": clean_inline(candidate.get("format") or DEFAULT_RETURN_POLICY["format"]),
        "limit": clean_inline(candidate.get("limit") or DEFAULT_RETURN_POLICY["limit"]),
    }


def bounded_int(value: Any, fallback: int, minimum: int = 0, maximum: int = 100) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


def bounded_float_or_none(value: Any, minimum: float = 0.0, maximum: float = 10_000.0) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not (minimum <= parsed <= maximum):
        return None
    return parsed


def default_runtime_policy() -> dict[str, Any]:
    config = workspace_config()
    candidate = config.get("runtimePolicy") if isinstance(config.get("runtimePolicy"), dict) else {}
    candidate_roles = candidate.get("roles") if isinstance(candidate.get("roles"), dict) else {}
    default_roles = DEFAULT_RUNTIME_POLICY["roles"] if isinstance(DEFAULT_RUNTIME_POLICY.get("roles"), dict) else {}
    roles: dict[str, Any] = {}
    for role_name, default_role in default_roles.items():
        configured = candidate_roles.get(role_name) if isinstance(candidate_roles.get(role_name), dict) else {}
        roles[role_name] = {
            **default_role,
            **{
                key: configured[key]
                for key in configured
                if key not in {"model", "effort", "context", "enforcement", "maxTurns"}
            },
            "model": clean_inline(configured.get("model")) or str(default_role.get("model", "")),
            "effort": clean_inline(configured.get("effort")) or str(default_role.get("effort", "")),
            "context": clean_inline(configured.get("context")) or str(default_role.get("context", "")),
        }
        if "enforcement" in default_role or "enforcement" in configured:
            roles[role_name]["enforcement"] = clean_inline(configured.get("enforcement")) or str(default_role.get("enforcement", ""))
        max_turns = configured.get("maxTurns", default_role.get("maxTurns"))
        roles[role_name]["maxTurns"] = bounded_int(max_turns, 0, minimum=1, maximum=1_000) if max_turns is not None else None

    candidate_budget = candidate.get("budget") if isinstance(candidate.get("budget"), dict) else {}
    default_budget = DEFAULT_RUNTIME_POLICY["budget"] if isinstance(DEFAULT_RUNTIME_POLICY.get("budget"), dict) else {}
    budget = {
        **default_budget,
        **{key: candidate_budget[key] for key in candidate_budget if key not in {"mode", "maxUsdPerRun", "warnUsdPerRun"}},
        "mode": clean_inline(candidate_budget.get("mode")) or str(default_budget.get("mode", "balanced")),
        "maxUsdPerRun": bounded_float_or_none(candidate_budget.get("maxUsdPerRun", default_budget.get("maxUsdPerRun"))),
        "warnUsdPerRun": bounded_float_or_none(candidate_budget.get("warnUsdPerRun", default_budget.get("warnUsdPerRun"))),
    }
    return {
        **candidate,
        "profile": clean_inline(candidate.get("profile")) or str(DEFAULT_RUNTIME_POLICY["profile"]),
        "roles": roles,
        "budget": budget,
    }


def snap_percent(value: Any, fallback: int, step: int) -> int:
    bounded = bounded_int(value, fallback)
    safe_step = max(1, min(100, step))
    return max(0, min(100, round(bounded / safe_step) * safe_step))


def thresholds_from_sensitivity(value: Any, step: int = int(DEFAULT_ROUTING_POLICY["sensitivityStepPercent"])) -> tuple[int, int, int]:
    sensitivity_percent = snap_percent(value, int(DEFAULT_ROUTING_POLICY["sensitivityPercent"]), step)
    auto_threshold = round(95 - sensitivity_percent * 0.7)
    return sensitivity_percent, auto_threshold, min(100, auto_threshold + 20)


def sensitivity_from_auto_threshold(value: Any, step: int = int(DEFAULT_ROUTING_POLICY["sensitivityStepPercent"])) -> int:
    auto_threshold = bounded_int(value, int(DEFAULT_ROUTING_POLICY["autoOfferThreshold"]))
    return snap_percent(round((95 - auto_threshold) / 0.7), int(DEFAULT_ROUTING_POLICY["sensitivityPercent"]), step)


def routing_dictionary(candidate: dict[str, Any]) -> dict[str, list[str]]:
    configured = candidate.get("dictionary") if isinstance(candidate.get("dictionary"), dict) else {}
    out: dict[str, list[str]] = {}
    defaults = DEFAULT_ROUTING_POLICY["dictionary"]
    if not isinstance(defaults, dict):
        return out
    for key, values in defaults.items():
        merged: list[str] = []
        raw_values = list(values) if isinstance(values, list) else []
        extra_values = configured.get(key) if isinstance(configured.get(key), list) else []
        for value in [*raw_values, *extra_values]:
            cleaned = clean_inline(value)
            if cleaned and cleaned not in merged:
                merged.append(cleaned)
        out[key] = merged[:50]
    return out


def default_routing_policy() -> dict[str, Any]:
    config = workspace_config()
    candidate = config.get("routingPolicy") if isinstance(config.get("routingPolicy"), dict) else {}
    candidate_scoring = candidate.get("scoring") if isinstance(candidate.get("scoring"), dict) else {}
    sensitivity_step = bounded_int(candidate.get("sensitivityStepPercent"), int(DEFAULT_ROUTING_POLICY["sensitivityStepPercent"]), minimum=1, maximum=100)
    if isinstance(candidate.get("sensitivityPercent"), (int, float, str)):
        sensitivity_percent, auto_threshold, strong_threshold = thresholds_from_sensitivity(candidate.get("sensitivityPercent"), sensitivity_step)
    else:
        auto_threshold = bounded_int(
            candidate.get("autoOfferThreshold"),
            int(DEFAULT_ROUTING_POLICY["autoOfferThreshold"]),
        )
        strong_threshold = bounded_int(
            candidate.get("strongOfferThreshold"),
            int(DEFAULT_ROUTING_POLICY["strongOfferThreshold"]),
        )
        sensitivity_percent = sensitivity_from_auto_threshold(auto_threshold, sensitivity_step)
    return {
        "autoOfferEnabled": bool(candidate.get("autoOfferEnabled", candidate.get("enabled", DEFAULT_ROUTING_POLICY["autoOfferEnabled"]))),
        "sensitivityPercent": sensitivity_percent,
        "sensitivityStepPercent": sensitivity_step,
        "autoOfferThreshold": auto_threshold,
        "strongOfferThreshold": max(auto_threshold, strong_threshold),
        "offerOncePerIntent": bool(candidate.get("offerOncePerIntent", DEFAULT_ROUTING_POLICY["offerOncePerIntent"])),
        "topicGate": bool(candidate.get("topicGate", DEFAULT_ROUTING_POLICY["topicGate"])),
        "defaultLanguage": clean_inline(candidate.get("defaultLanguage")) or str(DEFAULT_ROUTING_POLICY["defaultLanguage"]),
        "translationFallback": clean_inline(candidate.get("translationFallback")) or str(DEFAULT_ROUTING_POLICY["translationFallback"]),
        "scoring": {
            key: bounded_int(candidate_scoring.get(key), int(value), minimum=-100, maximum=100)
            for key, value in DEFAULT_ROUTING_POLICY["scoring"].items()
        },
        "dictionary": routing_dictionary(candidate),
    }


def slugify(value: Any, fallback: str = "brief") -> str:
    normalized = unicodedata.normalize("NFKD", clean_inline(value))
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", ascii_text).strip("-")[:72]
    return slug or fallback


def new_brief_id(title: str) -> str:
    stamp = now()[:10]
    return f"brief-{slugify(title or 'untitled').lower()}-{stamp}-{uuid.uuid4().hex[:6]}"


def safe_brief_id(value: str) -> str:
    brief_id = clean_inline(value)
    if not re.fullmatch(r"brief-[A-Za-z0-9_.-]+", brief_id):
        raise ValueError(f"invalid brief id: {brief_id or '(empty)'}")
    return brief_id


def briefs_dir() -> Path:
    return nogra_dir() / "briefs"


def briefs_drafts_dir() -> Path:
    return briefs_dir() / "drafts"


def transport_dir() -> Path:
    return nogra_dir() / "transport"


def transport_runs_dir() -> Path:
    return transport_dir() / "runs"


def transport_archive_dir() -> Path:
    return transport_dir() / "archive"


def transport_events_path() -> Path:
    return transport_dir() / "events.jsonl"


def transport_artifacts_dir(run_id: str) -> Path:
    return transport_dir() / "artifacts" / transport_safe_run_id(run_id)


def workspace_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def workspace_file(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return workspace_root() / path


def read_markdown(relative: str, fallback_relative: str = "") -> str:
    workspace_file = nogra_dir() / relative
    if workspace_file.is_file():
        return workspace_file.read_text(encoding="utf-8")
    default_file = default_nogra_dir() / relative
    if default_file.is_file():
        return default_file.read_text(encoding="utf-8")
    if fallback_relative:
        fallback_workspace_file = nogra_dir() / fallback_relative
        if fallback_workspace_file.is_file():
            return fallback_workspace_file.read_text(encoding="utf-8")
        fallback_default_file = default_nogra_dir() / fallback_relative
        if fallback_default_file.is_file():
            return fallback_default_file.read_text(encoding="utf-8")
    return ""


def read_package_text(relative: str) -> str:
    return (package_root() / relative).read_text(encoding="utf-8")


def read_package_json(relative: str) -> dict[str, Any]:
    try:
        return json.loads(read_package_text(relative))
    except OSError:
        return {"status": "error", "code": "PUBLIC_RESOURCE_MISSING"}
    except json.JSONDecodeError:
        return {"status": "error", "code": "PUBLIC_RESOURCE_INVALID_JSON"}


def public_toolbank_summary() -> dict[str, Any]:
    toolbank = read_package_json(PUBLIC_PACKAGE_JSON_RESOURCES["nogra://public/toolbank/claude-tools"])
    families = toolbank.get("families") if isinstance(toolbank.get("families"), dict) else {}
    return {
        "resource": "nogra://public/toolbank/claude-tools",
        "defaultFamily": toolbank.get("defaultFamily", "default-code"),
        "families": [
            {
                "id": key,
                "description": value.get("description", "") if isinstance(value, dict) else "",
                "replacesDefault": bool(value.get("replacesDefault")) if isinstance(value, dict) else False,
            }
            for key, value in families.items()
        ],
    }


def safe_init_path(value: Any) -> str:
    raw = clean_inline(value).replace("\\", "/")
    if not raw or raw.startswith("/") or raw.startswith("~") or "\x00" in raw:
        raise ValueError(f"invalid init bundle path: {raw or '(empty)'}")
    parts = [part for part in raw.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        raise ValueError(f"init bundle path escapes workspace: {raw}")
    if not parts:
        raise ValueError("invalid init bundle path: (empty)")
    return "/".join(parts)


def render_init_template(text: str, context: dict[str, str]) -> str:
    rendered = text
    for key, value in context.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def server_mode() -> str:
    if hosted_mode():
        return "hosted-public"
    if private_modules_enabled():
        return "local-private"
    return "local-public"


def init_phase_for_path(path: str) -> str:
    if path == ".nogra/config.json":
        return "configuration"
    if path.startswith(".nogra/presets/") or path.startswith(".nogra/provider-handoff-templates/") or path == ".nogra/providers.md":
        return "provider-handoff-defaults"
    if path == "CLAUDE.md" or path.startswith(".claude/"):
        return "workspace-method"
    return "local-records"


def init_install_plan(files: list[dict[str, Any]], init_mode: str = "standalone") -> dict[str, Any]:
    if init_mode == "plugin":
        workspace_method_description = "Create root CLAUDE.md only when missing. Plugin-owned commands and skills stay in the plugin."
        workspace_method_narration = "Creating root CLAUDE.md only if the workspace does not already have one."
        configuration_description = "Write the folder-local Nogra workspace config."
        configuration_narration = "Writing the folder-local Nogra config."
    else:
        workspace_method_description = "Write CLAUDE.md, the /nogra command and Nogra skills."
        workspace_method_narration = "Writing the Nogra workspace method and skills."
        configuration_description = "Write workspace config and visible provider defaults."
        configuration_narration = "Writing workspace configuration and provider defaults."
    definitions = [
        {
            "id": "preflight",
            "name": "preflight",
            "title": "Preflight",
            "description": "Check whether the workspace is empty and whether customized ask-before-overwrite files already exist.",
            "narration": "Checking for existing Nogra files before writing the core skeleton.",
        },
        {
            "id": "configuration",
            "name": "configuration",
            "title": "Configuration",
            "description": configuration_description,
            "narration": configuration_narration,
        },
        {
            "id": "provider-handoff-defaults",
            "name": "provider-handoff-defaults",
            "title": "Provider handoff defaults",
            "description": "Write customer-editable presets and provider handoff templates.",
            "narration": "Writing provider handoff presets and templates.",
        },
        {
            "id": "workspace-method",
            "name": "workspace-method",
            "title": "Workspace method",
            "description": workspace_method_description,
            "narration": workspace_method_narration,
        },
        {
            "id": "local-records",
            "name": "local-records",
            "title": "Local records",
            "description": "Create local Nogra record directories without overwriting customer data.",
            "narration": "Creating local .nogra/ record directories.",
        },
    ]
    by_phase: dict[str, list[dict[str, Any]]] = {definition["id"]: [] for definition in definitions}
    for file in files:
        path = clean_inline(file.get("path"))
        if not path:
            continue
        phase_id = init_phase_for_path(path)
        by_phase.setdefault(phase_id, []).append(
            {
                "path": path,
                "writePolicy": clean_inline(file.get("writePolicy")),
                "purpose": clean_inline(file.get("purpose")),
            }
        )

    phases = []
    for definition in definitions:
        phase_id = definition["id"]
        phase_files = by_phase.get(phase_id, [])
        if init_mode == "plugin" and phase_id != "preflight" and not phase_files:
            continue
        phases.append(
            {
                "id": phase_id,
                "name": definition["name"],
                "title": definition["title"],
                "description": definition["description"],
                "summary": definition["description"],
                "narration": definition["narration"],
                "fileCount": len(phase_files),
                "files": phase_files,
            }
        )
    return {
        "schema": "nogra.init.install_plan.v1",
        "mode": "phase-grouped-client-writes",
        "initMode": init_mode,
        "compatibility": "Additive field. Existing clients may ignore installPlan and use files directly.",
        "defaultExistingFileBehavior": "skip ask_before_overwrite files that already exist and report them as preserved",
        "overwriteOverride": "Only overwrite ask_before_overwrite files when the user explicitly asks to overwrite Nogra files.",
        "configMergePolicy": {
            "path": ".nogra/config.json",
            "mode": "merge_preserve_existing",
            "rule": "If .nogra/config.json already exists, preserve user-set values and unknown keys, add missing default keys from the returned config, and report preserved settings. If existing JSON is invalid, stop and ask before replacing it.",
        },
        "chatGuidance": "Narrate phases and final written/updated/preserved/failed counts, not every individual file write.",
        "transparencyGuidance": "Do not hide or suppress Claude Code Write transparency. Quiet the chat narration only; do not use opaque archive, wrapper or daemon installs.",
        "failureGuidance": "If a phase fails because of path validation, permissions, disk or another local write error, mark that phase failed with the reason, stop remaining phases and report completed phases plus final counts.",
        "summaryCounts": ["written", "updated", "preserved", "failed"],
        "phases": phases,
    }


def init_file_from_manifest_item(item: dict[str, Any], context: dict[str, str]) -> dict[str, Any]:
    source = safe_init_path(item.get("source", ""))
    target_path = safe_init_path(item.get("path", ""))
    content = render_init_template(read_package_text(source), context)
    return {
        "path": target_path,
        "content": content,
        "mimeType": clean_inline(item.get("mimeType")) or "text/plain",
        "contentEncoding": "utf-8",
        "contentDelivery": "inline-json-string",
        "writePolicy": clean_inline(item.get("writePolicy")) or "create_if_missing",
        "purpose": clean_inline(item.get("purpose")),
    }


def normalize_init_mode(value: Any) -> str:
    mode = slugify(clean_inline(value), fallback="standalone").lower()
    return mode if mode in INIT_BUNDLE_MODES else "standalone"


def manifest_item_supports_mode(item: dict[str, Any], init_mode: str) -> bool:
    raw_modes = item.get("modes")
    if not raw_modes:
        return True
    if not isinstance(raw_modes, list):
        return True
    modes = {normalize_init_mode(mode) for mode in raw_modes}
    return init_mode in modes


EXECUTOR_ROLE_PROMPT = """You are the ephemeral Nogra Executor for one approved run.

You were spawned as a disposable Claude Code subagent for this run only. Do not
assume persistent memory and do not save an agent definition. Do not call any
Nogra MCP tools, including mcp__nogra-hosted__* or nogra_* tools. The Manager
owns all Nogra control-plane calls: brief validation, dispatch, local .nogra/
bookkeeping, hosted completion validation, completion verification and final
handoff. You own implementation inside the approved scope only.

Inputs the Manager must provide:
- full nogra.brief.v1 brief or equivalent complete brief text
- Nogra run id
- approved scope.files, scope.in and scope.out
- success criteria and stop criteria
- evidenceRequired and expected return shape
- repo, browser or command verification instructions when relevant

If any material input is missing, stop and return blocked with the missing
input. Do not infer permission from vague context.

Execution rules:
- Work only inside the approved customer scope.
- Do not edit CLAUDE.md, .claude/, .nogra/ or optional pinboard files unless
  those paths are explicitly in approved customer scope.
- Treat .nogra/ writes as Manager/control-plane bookkeeping unless the brief
  explicitly asks you to customize Nogra files.
- If the work needs a file outside scope, stop and return for Manager approval.
- If a stop criterion is reached, stop and return for Manager approval.
- Preserve existing user changes. Do not clean unrelated files.
- Do not claim completion without evidence for every success criterion.
- Treat screenshots, browser checks and opening files as evidence methods, not
  success criteria by themselves. Prove the behavior, content or artifact
  condition the criterion names.
- Before packaging your final report, use the local nogra-completion-evidence
  skill if the client exposes a Skill tool and the skill is available. If it is
  not available, follow the return shape below directly and include concrete
  evidence for every success criterion. Do not create screenshots or visual
  artifacts unless the brief or Manager handoff explicitly asks for them.

Return a concise executor report for the Manager:
- status: ok, partial, blocked or decision_required
- summary: what changed
- filesChanged: customer artifact paths only, excluding Nogra protocol
  bookkeeping under .nogra/briefs, .nogra/events, .nogra/runs,
  .nogra/receipts and .nogra/transport
- commandsRun: commands/checks actually run and their result
- acceptance: one item per success criterion with met, partial, blocked or
  decision_required
- briefDeviations: any unapproved mismatch between the brief and the delivered
  result, including dependency/version substitutions, skipped evidence,
  changed scope, or "functionally equivalent" choices the Manager did not
  approve first
- evidence: proof required by the brief, such as diff notes, command results,
  browser observations or screenshots only when explicitly requested
- nextOwner: Manager

After returning your report, stop. The Manager persists your report into local
.nogra/ records and runs final validation when needed."""


VERIFIER_ROLE_PROMPT = """You are the ephemeral Nogra Verifier for one run.

You were spawned as a disposable Claude Code subagent for this verification
only. Do not assume persistent memory, do not save an agent definition, and do
not call any Nogra MCP tools, including mcp__nogra-hosted__* or nogra_* tools.
The Manager owns the user conversation, final verification, local .nogra/
bookkeeping and hosted validation call. The Executor owns implementation. You
independently inspect returned evidence and, when needed, run read-first checks
that prove or disprove the brief's success criteria.

Inputs the Manager must provide:
- full brief or complete brief summary with success criteria and scope files
- run id
- executor report
- files, URLs or rendered output to inspect
- required evidence level

If material inputs are missing, return blocked with the missing input.

Verification rules:
- Be read-first. Do not mutate customer project files.
- You may run non-mutating commands, read files, inspect rendered output, start
  a temporary local server when needed for browser verification, and stop that
  server afterwards.
- Do not edit .nogra/ records or call any Nogra MCP tools.
- Separate customer artifacts from Nogra protocol artifacts.
- Never treat the Executor's claim as proof. Verify each criterion from
  observable evidence when possible.
- Do not treat a screenshot or opened file as proof by itself. It only matters
  when it demonstrates the actual behavior or artifact condition in the brief.
- If verification is impossible, return blocked or decision_required instead of
  guessing.

Return a concise verification report:
- status: met, partial, blocked or decision_required
- summary: high-signal result
- criteria: one item per success criterion with status and evidence
- filesInspected: files read or rendered
- commandsRun: commands/checks actually run and their result
- observations: browser, network, console, screenshot or test findings
- risks: any remaining doubt
- nextOwner: Manager

Keep raw logs out of the Manager conversation unless they are needed to explain
a failure. After returning your report, stop."""


def handoff_contract_payload(kind: str) -> dict[str, Any]:
    wanted = slugify(kind or "", fallback="").lower()
    contracts = {
        "executor": {
            "title": "Nogra ephemeral executor",
            "purpose": "Implement one approved Nogra run inside the brief scope and return evidence.",
            "prompt": EXECUTOR_ROLE_PROMPT,
            "modelHint": "sonnet",
            "effortHint": "high",
        },
        "verifier": {
            "title": "Nogra ephemeral verifier",
            "purpose": "Independently verify one executor report against the approved brief.",
            "prompt": VERIFIER_ROLE_PROMPT,
            "modelHint": "sonnet",
            "effortHint": "medium",
        },
    }
    contract = contracts.get(wanted)
    if contract is None:
        return {
            "schema": "nogra.handoff.contract.v1",
            "releaseVersion": RELEASE_VERSION,
            "status": "invalid",
            "kind": clean_inline(kind),
            "availableKinds": sorted(contracts),
            "error": "unknown handoff kind",
        }
    return {
        "schema": "nogra.handoff.contract.v1",
        "releaseVersion": RELEASE_VERSION,
        "status": "ready",
        "kind": wanted,
        "title": contract["title"],
        "purpose": contract["purpose"],
        "executionModel": "ephemeral-run-agent",
        "targetSubagent": {
            "type": "general-purpose",
            "background": True,
            "modelHint": contract["modelHint"],
            "effortHint": contract["effortHint"],
        },
        "prompt": contract["prompt"],
        "managerInstructions": [
            "Fetch this contract at dispatch or verification boundaries only.",
            "Spawn Claude Code's built-in general-purpose subagent with this prompt plus the full brief, run id, scope, stop criteria and evidence contract.",
            "Manager is not the executor. If the subagent primitive is unavailable, stop and surface the missing primitive; do not execute inline or offer a synchronous fallback.",
            "Do not install or persist .claude/agents files for Nogra execution handoffs.",
            "Do not let the spawned subagent call hosted Nogra MCP tools; Manager owns Nogra control-plane calls.",
            "For executor runs, make the local nogra-completion-evidence skill available to the subagent when the client supports skills; otherwise the prompt's return shape is the fallback evidence contract.",
            "For ordinary single-run completion, Manager compares the executor report against the approved brief. Fetch role=verifier only for noisy browser/log/test work, explicit independent verification, or larger multi-agent flows.",
            "Treat the subagent as disposable. After it returns its report, the run agent is done.",
        ],
    }


def optional_feature_manifest_items(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in manifest.get("optionalFeatures", []) if isinstance(item, dict)]


def optional_feature_file_plan(files: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "nogra.optional_feature.install_plan.v1",
        "mode": "manual-opt-in-client-writes",
        "defaultExistingFileBehavior": "skip ask_before_overwrite files that already exist and report them as preserved",
        "fileCount": len(files),
        "files": [
            {
                "path": safe_init_path(file.get("path", "")),
                "writePolicy": clean_inline(file.get("writePolicy")) or "create_if_missing",
                "purpose": clean_inline(file.get("purpose")),
            }
            for file in files
            if isinstance(file, dict)
        ],
    }


def init_optional_features(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for item in optional_feature_manifest_items(manifest):
        feature_files = [file_item for file_item in item.get("files", []) if isinstance(file_item, dict)]
        feature_id = clean_inline(item.get("id"))
        if not feature_id or not feature_files:
            continue
        features.append(
            {
                "id": feature_id,
                "title": clean_inline(item.get("title")),
                "default": clean_inline(item.get("default") or "off"),
                "requires": clean_inline(item.get("requires")),
                "description": clean_inline(item.get("description")),
                "installPrompt": clean_inline(item.get("installPrompt")),
                "startCommand": clean_inline(item.get("startCommand")),
                "stateEndpoint": clean_inline(item.get("stateEndpoint")),
                "schema": clean_inline(item.get("schema")),
                "downloadTool": "optional_feature_bundle",
                "installPlan": optional_feature_file_plan(feature_files),
            }
        )
    return features


def optional_feature_bundle(feature_id: str, workspace_name: str = "") -> dict[str, Any]:
    manifest = read_package_json(INIT_BUNDLE_MANIFEST)
    wanted = clean_inline(feature_id)
    workspace_name_clean = clean_inline(workspace_name) or "local"
    context = {
        "workspaceName": workspace_name_clean,
        "workspaceId": slugify(workspace_name_clean, fallback="local").lower(),
        "generatedAt": now(),
        "version": INIT_BUNDLE_VERSION,
    }
    for item in optional_feature_manifest_items(manifest):
        if clean_inline(item.get("id")) != wanted:
            continue
        files = [
            init_file_from_manifest_item(file_item, context)
            for file_item in item.get("files", [])
            if isinstance(file_item, dict)
        ]
        if not files:
            return {
                "schema": "nogra.optional_feature.bundle.v1",
                "status": "invalid",
                "featureId": wanted,
                "error": "optional feature has no files",
            }
        return {
            "schema": "nogra.optional_feature.bundle.v1",
            "status": "ready",
            "featureId": wanted,
            "title": clean_inline(item.get("title")),
            "version": INIT_BUNDLE_VERSION,
            "generatedAt": context["generatedAt"],
            "requires": clean_inline(item.get("requires")),
            "description": clean_inline(item.get("description")),
            "startCommand": clean_inline(item.get("startCommand")),
            "stateEndpoint": clean_inline(item.get("stateEndpoint")),
            "stateSchema": clean_inline(item.get("schema")),
            "writeMode": "client_writes_files",
            "installPlan": optional_feature_file_plan([file_item for file_item in item.get("files", []) if isinstance(file_item, dict)]),
            "files": files,
            "nextSteps": [
                "Write these files only after explicit user opt-in.",
                "Preserve each file writePolicy; skip ask_before_overwrite files by default if they already exist.",
                "Do not auto-start the renderer. Show the startCommand and let the user choose when to run it.",
            ],
        }
    return {
        "schema": "nogra.optional_feature.bundle.v1",
        "status": "missing",
        "featureId": wanted,
        "availableFeatures": [clean_inline(item.get("id")) for item in optional_feature_manifest_items(manifest) if clean_inline(item.get("id"))],
    }


def post_install_message(init_mode: str = "standalone") -> str:
    if init_mode == "plugin":
        return (
            "Nogra is installed in this folder. The plugin provides the Nogra commands, skills and MCP connection; "
            "this init wrote folder-local .nogra/ config, continuity notes, trust-source record directories and CLAUDE.md only if it was missing. "
            "Use /nogra:brief to start a Nogra brief, or ask Claude to write one for the work. "
            "For existing projects, use /nogra:adapt next to let Claude write Nogra's project map under .nogra/ without changing app files. "
            "When the brief looks right, say GO to dispatch it. "
            "Use /nogra:verify when you want Nogra to check whether work is actually done. "
            "No app code, .claude/ files, Claude Code config, skills, commands, presets, templates or pinboard files were changed. "
            "For demo requests, ask Claude for 2-3 bounded ideas that fit this folder, then choose one to brief."
        )
    return (
        "Nogra is installed. Use /nogra:brief to start a Nogra brief, or ask Claude to write one for the work. "
        "When the brief looks right, say GO to dispatch it. "
        "Use /nogra:verify when you want Nogra to check whether work is actually done. "
        "Standard init installed the Nogra workspace compass and .nogra/ trust-source records; no pinboard files are installed by default. "
        "If you want the optional live pinboard later, ask for /nogra pinboard install; it requires Node.js and starts manually. "
        "Standard init does not install persistent Nogra project agents. For approved runs, Manager fetches a fresh executor or verifier "
        "handoff contract from Nogra at the dispatch boundary and spawns a disposable general-purpose run agent. "
        "If this workspace previously installed Nogra, old .claude/agents/nogra-executor.md and .claude/agents/nogra-verifier.md "
        "files are obsolete and should be removed only after the user approves cleanup. "
        "For demo requests, ask Claude for 2-3 bounded ideas that fit this folder, then choose one to brief."
    )


def init_migration_guidance(init_mode: str) -> dict[str, Any]:
    if init_mode != "plugin":
        return {
            "schema": "nogra.init.migration_guidance.v1",
            "mode": init_mode,
            "required": False,
            "clientScanTargets": [],
            "directives": [],
        }
    stale_workspace_paths = [
        ".claude/commands/nogra.md",
        ".claude/skills/nogra-brief-writing/SKILL.md",
        ".claude/skills/nogra-dispatch-flow/SKILL.md",
        ".claude/skills/nogra-completion-evidence/SKILL.md",
        ".claude/skills/nogra-pinboard-customize/SKILL.md",
        ".claude/agents/nogra-executor.md",
        ".claude/agents/nogra-verifier.md",
    ]
    return {
        "schema": "nogra.init.migration_guidance.v1",
        "mode": init_mode,
        "required": False,
        "clientScanTargets": stale_workspace_paths + ["CLAUDE.md"],
        "directives": [
            {
                "id": "remove-pre-plugin-workspace-behavior",
                "action": "delete_after_user_approval",
                "paths": stale_workspace_paths,
                "reason": "The Nogra plugin now manages commands, skills and execution handoffs. Old workspace copies can drift and should not remain active beside the plugin.",
            },
            {
                "id": "review-old-root-claude-md",
                "action": "ask_before_editing",
                "paths": ["CLAUDE.md"],
                "reason": "Older standalone Nogra installs wrote a full root CLAUDE.md. Plugin-mode init creates root guidance only when missing and should not overwrite customer project memory.",
            },
        ],
        "userPrompt": "I found old Nogra workspace files from the pre-plugin install. The plugin manages this behavior now. May I remove the old workspace copies?",
        "mcpConflictNote": "MCP server entries live in Claude Code config, outside this workspace init bundle. If plugin installation reports an existing MCP server named 'nogra', stop and surface the conflict; do not overwrite, remove or rename MCP config from init guidance.",
    }


def init_bundle(workspace_name: str = "", mode: str = "standalone") -> dict[str, Any]:
    generated_at = now()
    init_mode = normalize_init_mode(mode)
    if init_mode == "plugin" and not hosted_mode():
        return {
            "schema": INIT_BUNDLE_SCHEMA,
            "releaseVersion": RELEASE_VERSION,
            "status": "invalid",
            "code": "PLUGIN_MODE_REQUIRES_HOSTED_MCP",
            "message": "Plugin-mode init must be served by the hosted Nogra MCP. This session is calling a local/non-hosted Nogra server because a local/private MCP server is still registered as 'nogra' and is winning over the plugin-managed hosted MCP.",
            "resolution": "Reserve 'nogra' for the public hosted/plugin MCP. Move local/private development to 'nogra-dev', restart Claude Code with the Nogra plugin loaded, then run /nogra:init again.",
            "serverMode": server_mode(),
            "initMode": init_mode,
            "generatedAt": generated_at,
        }
    workspace_name_clean = clean_inline(workspace_name) or "local"
    workspace_id = slugify(workspace_name_clean, fallback="local").lower()
    manifest = read_package_json(INIT_BUNDLE_MANIFEST)
    if manifest.get("schema") != "nogra.init.manifest.v1":
        return {
            "schema": INIT_BUNDLE_SCHEMA,
            "releaseVersion": RELEASE_VERSION,
            "status": "error",
            "code": "INIT_MANIFEST_INVALID",
            "message": "Nogra init bundle manifest is missing or invalid.",
        }

    context = {
        "workspaceName": workspace_name_clean,
        "workspaceId": workspace_id,
        "generatedAt": generated_at,
        "version": INIT_BUNDLE_VERSION,
        "releaseVersion": RELEASE_VERSION,
        "initMode": init_mode,
    }
    files: list[dict[str, Any]] = []
    for item in manifest.get("files", []):
        if not isinstance(item, dict):
            continue
        if not manifest_item_supports_mode(item, init_mode):
            continue
        files.append(init_file_from_manifest_item(item, context))

    optional_features = [] if init_mode == "plugin" else init_optional_features(manifest)
    migration = init_migration_guidance(init_mode)
    mode_guidance = (
        "Plugin mode: do not write any .claude/ files; the plugin owns Nogra behavior and the workspace owns .nogra/ records plus root CLAUDE.md only when missing."
        if init_mode == "plugin"
        else "Standalone mode: write the full local Nogra workspace method because no Nogra plugin is assumed."
    )
    next_steps = [
        mode_guidance,
        "Use installPlan to write files in phase groups while preserving each file writePolicy and showing a short phase tasklist.",
        "For .nogra/config.json, merge missing defaults into an existing config while preserving user-set values and unknown keys; if the existing JSON is invalid, stop and ask before replacing it.",
        "Skip existing ask_before_overwrite files by default and report them as preserved; report final written, updated, preserved and failed counts.",
        "If a phase fails, stop remaining phases and show the failed phase, reason and completed phases.",
        "Do not hide Claude Code Write transparency or use opaque archive, wrapper or daemon installs; quiet chat narration only.",
        "After writing, show postInstallMessage and ask what brief the user wants to create first.",
        "If migration.clientScanTargets exist in the workspace, explain migration.userPrompt and wait for explicit user approval before deleting or editing old Nogra files.",
        "Treat .nogra/ records as the trust source.",
        "For brief work, read the public brief contract before validation and save.",
    ]
    if init_mode == "plugin":
        next_steps.extend(
            [
                "Do not install providers, presets, provider handoff templates, skills, commands, pinboard files, wrappers or runtime agents from plugin-mode init.",
                "The plugin owns behavior files and updates them through the Claude Code plugin update path.",
                "Create CLAUDE.md only if it is returned by this bundle and missing locally; never overwrite an existing CLAUDE.md from plugin-mode init.",
            ]
        )
    else:
        next_steps.extend(
            [
                "Tell the user that init does not install persistent Nogra project agents; dispatch and verification use disposable general-purpose run agents with handoff contracts fetched from Nogra at event boundaries.",
                "If obsolete .claude/agents/nogra-executor.md or .claude/agents/nogra-verifier.md files exist from an older Nogra init, explain that they are no longer used and ask before deleting them.",
                "Pinboard files are not installed unless the user opts in.",
                "If the user wants a live pinboard, offer optionalFeatures.local-pinboard-renderer and download it with optional_feature_bundle only after opt-in.",
            ]
        )

    return {
        "schema": INIT_BUNDLE_SCHEMA,
        "releaseVersion": RELEASE_VERSION,
        "status": "ready",
        "bundleId": "init-bundle-v1",
        "version": INIT_BUNDLE_VERSION,
        "initMode": init_mode,
        "generatedAt": generated_at,
        "serverMode": server_mode(),
        "workspaceId": workspace_id,
        "workspaceName": workspace_name_clean,
        "writeMode": "client_writes_files",
        "installPlan": init_install_plan(files, init_mode),
        "postInstallMessage": post_install_message(init_mode),
        "migration": migration,
        "files": files,
        "optionalFeatures": optional_features,
        "nextSteps": next_steps,
    }


def redact(text: str) -> tuple[str, list[str]]:
    out = text
    redactions: list[str] = []
    for label, pattern in SECRET_PATTERNS:
        replaced = pattern.sub("[REDACTED]", out)
        if replaced != out:
            redactions.append(label)
            out = replaced
    return out, sorted(set(redactions))


def scan_for_secrets(text: Any) -> list[str]:
    """Return sorted unique secret-pattern labels detected in text."""
    if not isinstance(text, str) or not text:
        return []
    _, labels = redact(text)
    return labels


def secrets_in_payload(payload: Any, _depth: int = 0) -> list[str]:
    """Recursively scan top-level + 1-level nested string values for secrets."""
    if _depth > 2:
        return []
    found: set[str] = set()
    if isinstance(payload, str):
        found.update(scan_for_secrets(payload))
    elif isinstance(payload, list) and _depth < 2:
        for item in payload:
            found.update(secrets_in_payload(item, _depth + 1))
    elif isinstance(payload, dict) and _depth < 2:
        for value in payload.values():
            found.update(secrets_in_payload(value, _depth + 1))
    return sorted(found)


def merge_redactions(existing: Any, *payloads: Any) -> list[str]:
    found = {str(label) for label in existing if isinstance(label, str)} if isinstance(existing, list) else set()
    for payload in payloads:
        found.update(secrets_in_payload(payload))
    return sorted(found)


def brief_secret_payload(brief: dict[str, Any]) -> dict[str, Any]:
    scope = brief.get("scope") if isinstance(brief.get("scope"), dict) else {}
    max_output = brief.get("maxOutput") if isinstance(brief.get("maxOutput"), dict) else {}
    return {
        "title": brief.get("title", ""),
        "intent": brief.get("intent", ""),
        "contextHandoff": brief.get("contextHandoff", ""),
        "decisions": brief.get("decisions", []),
        "rejected": brief.get("rejected", []),
        "knownGaps": brief.get("knownGaps", []),
        "scope": [
            *as_string_array(scope.get("in")),
            *as_string_array(scope.get("out")),
            *as_string_array(scope.get("files")),
        ],
        "successCriteria": brief.get("successCriteria", []),
        "stopCriteria": brief.get("stopCriteria", []),
        "maxOutput": [max_output.get("format", ""), max_output.get("limit", "")],
        "owner": brief.get("owner", ""),
        "targetRole": brief.get("targetRole", ""),
        "targetModel": brief.get("targetModel", ""),
        "executionShape": brief.get("executionShape", {}),
        "evidenceRequired": brief.get("evidenceRequired", ""),
    }


def render_provider_handoff_prompt(provider: str, prompt: str, context: str, intent: str) -> tuple[str, list[str]]:
    selected_intent = clean_inline(intent) or "consult"
    preset_mode = selected_intent if selected_intent in MODES else "neutral"
    preset = read_markdown(f"presets/{preset_mode}.md").strip()
    handoff_template = read_markdown("provider-handoff-templates/default.md", "provider-handoff-templates/provider-handoff-default.md").strip()
    if not handoff_template:
        handoff_template = (
            "# Nogra provider handoff\n\n"
            "Provider: {{provider}}\n\n"
            "Preset:\n{{preset}}\n\n"
            "Context:\n{{context}}\n\n"
            "Question:\n{{prompt}}\n"
        )
    rendered = (
        handoff_template.replace("{{provider}}", provider.strip())
        .replace("{{model}}", provider.strip())
        .replace("{{intent}}", selected_intent)
        .replace("{{mode}}", selected_intent)
        .replace("{{preset}}", preset)
        .replace("{{context}}", context.strip() or "(none)")
        .replace("{{prompt}}", prompt.strip())
    )
    return redact(rendered)


def ensure_runtime_dirs() -> None:
    (nogra_dir() / "receipts").mkdir(parents=True, exist_ok=True)
    (nogra_dir() / "events").mkdir(parents=True, exist_ok=True)
    (nogra_dir() / "runs").mkdir(parents=True, exist_ok=True)
    briefs_drafts_dir().mkdir(parents=True, exist_ok=True)
    transport_runs_dir().mkdir(parents=True, exist_ok=True)
    transport_archive_dir().mkdir(parents=True, exist_ok=True)
    (transport_dir() / "artifacts").mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def local_write_policy() -> dict[str, Any]:
    return {
        "schema": "nogra.local.write_policy.v1",
        "root": ".nogra/",
        "clientValidation": [
            "Resolve each localWrites path against the current workspace root before writing.",
            "Reject absolute paths, '~' paths, null bytes and control characters.",
            "Normalize '.', '..', duplicate slashes and symlinks.",
            "Reject the write if the resolved target is not under <workspace>/.nogra/.",
            "For append_jsonl writes, skip append when idempotencyField already has idempotencyKey in the target file.",
        ],
    }


def local_write_path(path_value: str) -> str:
    raw = str(path_value if path_value is not None else "").replace("\\", "/").strip()
    if not raw or raw.startswith("/") or raw.startswith("~") or "\x00" in raw:
        raise ValueError(f"invalid local write path: {raw or '(empty)'}")
    if any(ord(ch) < 32 for ch in raw):
        raise ValueError("invalid local write path: control character")
    parts = [part for part in raw.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        raise ValueError(f"local write path escapes .nogra: {raw}")
    normalized = "/".join(parts)
    if not normalized.startswith(".nogra/"):
        raise ValueError(f"local write path must stay under .nogra/: {raw}")
    return normalized


def local_write(
    path: str,
    operation: str,
    content: str,
    mime_type: str,
    purpose: str,
    write_policy: str = "create_or_update",
    **extra: Any,
) -> dict[str, Any]:
    item = {
        "path": local_write_path(path),
        "operation": operation,
        "content": content,
        "mimeType": mime_type,
        "writePolicy": write_policy,
        "purpose": clean_inline(purpose),
    }
    for key, value in extra.items():
        if value not in ("", None, [], {}):
            item[key] = value
    return item


def local_write_json(path: str, payload: dict[str, Any], purpose: str) -> dict[str, Any]:
    return local_write(
        path=path,
        operation="write_json",
        content=json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        mime_type="application/json",
        purpose=purpose,
    )


def local_write_text(path: str, text: str, purpose: str, mime_type: str = "text/plain") -> dict[str, Any]:
    return local_write(
        path=path,
        operation="write_text",
        content=text if text.endswith("\n") else text + "\n",
        mime_type=mime_type,
        purpose=purpose,
    )


def local_write_jsonl(path: str, payload: dict[str, Any], purpose: str, idempotency_key: str = "") -> dict[str, Any]:
    key = clean_inline(idempotency_key or payload.get("eventId") or payload.get("id") or "")
    return local_write(
        path=path,
        operation="append_jsonl",
        content=json.dumps(payload, ensure_ascii=False) + "\n",
        mime_type="application/jsonl",
        purpose=purpose,
        write_policy="append_if_missing",
        idempotencyField="eventId" if key else "",
        idempotencyKey=key,
    )


def attach_local_writes(payload: dict[str, Any], writes: list[dict[str, Any]]) -> dict[str, Any]:
    if writes:
        payload["localWritePolicy"] = local_write_policy()
        payload["localWrites"] = writes
    return payload


def local_brief_draft_path(brief_id: str) -> str:
    return f".nogra/briefs/drafts/{safe_brief_id(brief_id)}.json"


def local_promoted_brief_path(brief_id: str) -> str:
    return f".nogra/briefs/{safe_brief_id(brief_id)}.md"


def local_transport_run_path(run_id: str) -> str:
    return f".nogra/transport/runs/{transport_safe_run_id(run_id)}.json"


def local_transport_archive_path(run_id: str) -> str:
    return f".nogra/transport/archive/{transport_safe_run_id(run_id)}.json"


def local_transport_events_path() -> str:
    return ".nogra/transport/events.jsonl"


def local_transport_artifact_path(run_id: str, name: str) -> str:
    safe_name = clean_inline(name)
    if safe_name not in {"report.md", "output.md", "validation.json"}:
        raise ValueError(f"invalid local transport artifact: {safe_name or '(empty)'}")
    return f".nogra/transport/artifacts/{transport_safe_run_id(run_id)}/{safe_name}"


def local_provider_handoff_receipt_path(handoff_id: str) -> str:
    cleaned = safe_id(handoff_id, "provider-handoff")
    if not cleaned.startswith("provider-handoff-"):
        raise ValueError(f"invalid provider handoff id: {handoff_id or '(empty)'}")
    return f".nogra/receipts/{cleaned}.json"


def local_workspace_events_path() -> str:
    return ".nogra/events/events.jsonl"


def local_workspace_run_updates_path(run_id: str) -> str:
    return f".nogra/runs/{safe_id(run_id, 'run')}.jsonl"


def local_transport_run_write(run: dict[str, Any], purpose: str = "Persist transport run state locally.") -> dict[str, Any]:
    return local_write_json(local_transport_run_path(str(run.get("runId") or "")), run, purpose)


def local_transport_event_write(event: dict[str, Any], purpose: str = "Persist transport event locally.") -> dict[str, Any]:
    return local_write_jsonl(local_transport_events_path(), event, purpose, idempotency_key=str(event.get("eventId") or ""))


def module_metadata_payloads() -> list[dict[str, Any]]:
    modules = [nogra_runtime.extension_metadata()]
    if private_modules_enabled():
        modules.append(private_module().extension_metadata())
    return modules


def resource_uris() -> list[str]:
    return [
        *PUBLIC_RESOURCES,
        f"nogra://workspace/{workspace_label()}/provider-handoffs/recent",
        f"nogra://workspace/{workspace_label()}/pinboard/events",
        f"nogra://workspace/{workspace_label()}/runs/recent",
        f"nogra://workspace/{workspace_label()}/briefs/recent",
        f"nogra://workspace/{workspace_label()}/transport/runs/recent",
        f"nogra://workspace/{workspace_label()}/transport/events/recent",
    ]


def extension_metadata_payloads() -> list[dict[str, Any]]:
    return module_metadata_payloads()


def extended_tools() -> list[str]:
    tools = list(TOOLS)
    for metadata in extension_metadata_payloads():
        if metadata.get("status") != "ready":
            continue
        tools.extend(str(item) for item in metadata.get("tools", []) if item)
    return tools


def extended_resources() -> list[str]:
    resources = list(resource_uris())
    for metadata in extension_metadata_payloads():
        if metadata.get("status") != "ready":
            continue
        resources.extend(str(item) for item in metadata.get("resources", []) if item)
    return resources


def extended_prompts() -> list[dict[str, str]]:
    prompts = list(PROMPTS)
    for metadata in extension_metadata_payloads():
        if metadata.get("status") != "ready":
            continue
        prompts.extend(item for item in metadata.get("prompts", []) if isinstance(item, dict))
    return prompts


def register_extensions(mcp: Any, runtime: Runtime) -> None:
    nogra_runtime.register(mcp, runtime)
    if private_modules_enabled():
        private_module().register(mcp, runtime)


def registry_payload() -> dict[str, Any]:
    return {
        "name": NAME,
        "version": VERSION,
        "releaseVersion": RELEASE_VERSION,
        "initBundleVersion": INIT_BUNDLE_VERSION,
        "versions": {
            "mcp": VERSION,
            "initBundle": INIT_BUNDLE_VERSION,
            "plugin": "client-installed-ref",
        },
        "status": "v1-hosted-validation" if hosted_mode() else "v1-local-validation",
        "tools": extended_tools(),
        "resources": extended_resources(),
        "prompts": extended_prompts(),
        "boundary": {
            "canonicalServer": True,
            "publicResourcesOnly": not private_modules_enabled(),
            "workspaceScoped": True,
            "internalContext": private_modules_enabled(),
            "liveProviderCalls": False,
            "extensionsEnabled": True,
            "privateModulesEnabled": private_modules_enabled(),
            "hostedMode": hosted_mode(),
        },
        "extensions": extension_metadata_payloads(),
        "modules": module_metadata_payloads(),
        "workspace": {
            "id": workspace_label(),
            "substrate": [
                ".nogra/config.json",
                ".nogra/providers.md",
                ".nogra/presets/*.md",
                ".nogra/provider-handoff-templates/*.md",
                "nogra/",
            ],
            "installPaths": [".claude/skills/", ".claude/commands/"],
        },
    }


def brief_contract_payload(workspace_id: str = "") -> dict[str, Any]:
    return_policy = default_return_policy()
    client_workspace_id = clean_inline(workspace_id) or "local"
    return {
        "schema": "nogra.brief.contract.v1",
        "releaseVersion": RELEASE_VERSION,
        "briefSchema": BRIEF_SCHEMA,
        "serverMode": server_mode(),
        "workspaceId": client_workspace_id,
        "serverWorkspaceId": workspace_label(),
        "schemaResource": "nogra://public/schemas/brief-v1",
        "templateResource": "nogra://public/templates/brief-v1",
        "exampleResource": "nogra://public/examples/brief-v1",
        "workspaceIdPolicy": {
            "sourceOfTruth": ".nogra/config.json workspaceId after init",
            "fallback": "local",
            "note": "Hosted Nogra cannot infer the customer's local workspace id unless the caller supplies it.",
        },
        "evidenceRequiredGuidance": BRIEF_EVIDENCE_GUIDANCE,
        "briefPolicy": default_brief_policy(),
        "routingPolicy": default_routing_policy(),
        "runtimePolicy": default_runtime_policy(),
        "runtimePolicyGuidance": {
            "sourceOfTruth": ".nogra/config.json runtimePolicy after init",
            "effect": "Controls user-facing Nogra preferences for profile, role model/effort and advisory budget. It does not silently change Claude Code native /model or /effort.",
            "profile": "Simple preset label such as frugal, balanced or max. /nogra:settings can apply presets.",
            "roles.manager": "Advisory desired model/effort for the active Manager conversation. The user must use native /model and /effort to actually switch the current session.",
            "roles.agent": "Desired disposable executor model/effort/context/maxTurns when the client/runtime can honor them. Use this as the default targetModel guidance for briefs.",
            "roles.verifier": "Desired independent verifier model/effort when a verifier is needed.",
            "budget": "Advisory in interactive plugin mode. Hard maxUsdPerRun applies only to headless runtimes that support budget flags such as --max-budget-usd.",
        },
        "routingPolicyGuidance": {
            "sourceOfTruth": ".nogra/config.json routingPolicy after init",
            "effect": "Controls only local Nogra offers before work starts. It never authorizes MCP calls, dispatch, verification or subagents.",
            "autoOfferEnabled": "When false, Claude should not proactively offer Nogra for ordinary prompts. Explicit /nogra:* commands still work.",
            "sensitivityPercent": "User-facing heat control from 0 to 100. Higher sensitivity lowers effective offer thresholds; lower sensitivity raises them. Default 50 maps to effective thresholds 60/80.",
            "sensitivityStepPercent": "Granularity for user-facing heat. Default 5 means values snap to 0, 5, 10 ... 100. Use 10 for coarser calibration passes.",
            "autoOfferThreshold": "Derived from sensitivityPercent when present. Legacy override: lower values offer more often; higher values offer less often.",
            "strongOfferThreshold": "Derived from sensitivityPercent when present. At or above this score, recommend a Nogra brief strongly while still letting the user choose.",
            "topicGate": "If the request is not workspace/build/change/verify related, do not offer Nogra no matter the score.",
            "defaultLanguage": "Preferred workspace language for Nogra routing interpretation and user-facing guidance. Default en.",
            "translationFallback": "claude-current-prompt means Claude may use its own understanding of the current prompt when dictionary matching is insufficient. It is not an external translation call.",
            "dictionary": "Signal-specific local phrases checked after the English-first core. Add workspace language terms here instead of expanding hardcoded regex.",
        },
        "executionShapeGuidance": {
            **public_toolbank_summary(),
            "effect": "Optional Manager-authored evidence/tool need guidance for adapter tool scope. Blank means conservative default execution.",
            "rule": "Briefs declare evidence/tool needs once; the adapter derives toolbank families mechanically. Explicit toolFamilies remains a compatibility override, not the preferred authoring path.",
        },
        "defaultReturnPolicy": return_policy,
        "requiredFields": [
            {"field": "schema", "shape": "literal nogra.brief.v1", "source": "frontmatter or structured payload"},
            {"field": "releaseVersion", "shape": "literal v1.0.0 or later release tag", "source": "structured payload or generated by the tool"},
            {"field": "briefId", "shape": "brief-* id", "source": "frontmatter or generated by the tool"},
            {"field": "workspaceId", "shape": "non-empty string", "source": ".nogra/config.json workspaceId, frontmatter, or structured payload"},
            {"field": "title", "shape": "non-empty string", "source": "frontmatter title or first # heading"},
            {"field": "createdAt", "shape": "date-time string", "source": "frontmatter or generated by the tool"},
            {"field": "intent", "shape": "non-empty text", "source": "## Intent"},
            {"field": "contextHandoff", "shape": "non-empty text", "source": "## Context Handoff"},
            {"field": "scope.in", "shape": "array of strings", "source": "## Scope / In:"},
            {"field": "scope.out", "shape": "array of strings", "source": "## Scope / Out:"},
            {"field": "successCriteria", "shape": "non-empty array of brief-specific, intent-derived strings", "source": "## Success Criteria"},
            {"field": "stopCriteria", "shape": "non-empty array of strings", "source": "## Stop Criteria"},
            {"field": "maxOutput.format", "shape": "non-empty text", "source": "## Max Output / Format:"},
            {"field": "maxOutput.limit", "shape": "non-empty text", "source": "## Max Output / Limit:"},
        ],
        "optionalFields": [
            {"field": "decisions", "shape": "array of strings", "source": "## Decisions"},
            {"field": "rejected", "shape": "array of strings", "source": "## Rejected"},
            {"field": "knownGaps", "shape": "array of strings", "source": "## Known Gaps"},
            {"field": "scope.files", "shape": "array of strings", "source": "## Scope / Files: or ## Files"},
            {"field": "owner", "shape": "string", "source": "frontmatter or structured payload"},
            {"field": "targetRole", "shape": "string", "source": "frontmatter or structured payload"},
            {"field": "targetModel", "shape": "string", "source": "frontmatter or workspace default"},
            {
                "field": "executionShape",
                "shape": "optional object with freeform toolNeeds/notes guidance",
                "source": "structured payload or ## Execution Shape",
                "guidance": "Use only when the work needs a materially different execution/tool shape. Prefer toolNeeds/evidence method declarations; do not duplicate them as toolFamilies unless overriding compatibility behavior.",
            },
            {"field": "evidenceRequired", "shape": "reported | edited | tested | verified", "source": "frontmatter or structured payload", "guidance": BRIEF_EVIDENCE_GUIDANCE},
            {"field": "handoffRefs", "shape": "array of strings", "source": "structured payload"},
        ],
        "markdownSections": [
            {"heading": "## Intent", "field": "intent", "required": True},
            {"heading": "## Context Handoff", "field": "contextHandoff", "required": True},
            {"heading": "## Decisions", "field": "decisions", "required": False},
            {"heading": "## Rejected", "field": "rejected", "required": False},
            {"heading": "## Known Gaps", "field": "knownGaps", "required": False},
            {"heading": "## Scope", "field": "scope", "required": True, "labels": ["In:", "Out:", "Files:"]},
            {"heading": "## Success Criteria", "field": "successCriteria", "required": True},
            {"heading": "## Stop Criteria", "field": "stopCriteria", "required": True},
            {"heading": "## Execution Shape", "field": "executionShape", "required": False, "labels": ["Tool needs:", "Notes:"]},
            {"heading": "## Max Output", "field": "maxOutput", "required": True, "labels": ["Format:", "Limit:"]},
        ],
        "notes": [
            "Success criteria must be specific to the user's intent and approved scope. Do not add generic quality gates that were not implied by the intent.",
            "Success criteria describe outcomes or observable artifact behavior. Do not make evidence collection chores such as opening a file, taking a screenshot or showing a page into criteria unless the user's requested deliverable is literally that artifact.",
            "Screenshots, browser checks, console/network inspection and file opening belong in the evidence plan or executor/verifier handoff when they are needed to prove a criterion.",
            "Acceptance is judged by comparing the result evidence against the brief's intent, scope and success criteria.",
            "evidenceRequired describes evidence strength. It does not automatically require a separate verifier agent.",
            "Use a verifier agent only for noisy checks, explicit independent verification or larger multi-agent flows.",
            "executionShape is optional. It should guide tool/runtime shape when the brief genuinely needs it; blank means conservative default execution. Prefer toolNeeds/evidence methods and let the adapter derive families from the toolbank.",
            "maxOutput is the return policy for the executor's final response; it is not a limit on brief length.",
            "The brief itself has no default word limit.",
            "Prefer structured JSON for validate/save when available.",
            "Validation should be a gate, not the way to discover the contract.",
        ],
        "demoBrief": {
            "schema": BRIEF_SCHEMA,
            "briefId": new_brief_id("demo workspace readme"),
            "workspaceId": client_workspace_id,
            "title": "Add workspace README",
            "createdAt": now(),
            "status": "draft",
            "owner": "",
            "targetRole": "agent",
            "targetModel": default_target_model(),
            "intent": "Add a short README to the workspace root so a new visitor can understand the workspace purpose and find the Nogra records.",
            "contextHandoff": "The workspace has been initialized with Nogra. Keep the README small and point to the .nogra/ trust-source records plus the /nogra command.",
            "decisions": ["Place README.md at the workspace root.", "Use .nogra/ records as the status authority."],
            "rejected": ["Do not create a full documentation site.", "Do not install or change optional pinboard files in this brief."],
            "knownGaps": ["Tone can be neutral unless the user gives a preference."],
            "scope": {
                "in": ["Create README.md at the workspace root."],
                "out": ["Do not modify CLAUDE.md, .nogra/*, or optional pinboard files."],
                "files": ["README.md"],
            },
            "successCriteria": [
                "README.md exists at the workspace root.",
                "README.md mentions .nogra/ records and the /nogra command.",
                "No other files are changed.",
            ],
            "stopCriteria": [
                "If README.md already exists, stop and ask before overwriting.",
                "If the work requires changes outside README.md, stop and return for approval.",
            ],
            "maxOutput": return_policy,
            "evidenceRequired": "reported",
            "handoffRefs": [],
        },
    }


def inventory_payload() -> dict[str, Any]:
    modules = module_metadata_payloads()
    return {
        "tools": extended_tools(),
        "resources": extended_resources(),
        "prompts": extended_prompts(),
        "extensions": modules,
        "modules": modules,
    }


def init_prompt_text() -> str:
    return """Bootstrap Nogra in the current workspace from the connected Nogra MCP server.

This is first-install bootstrap. Do not use a local /nogra command, local Nogra skill, local Nogra agent, wrapper, daemon, archive installer, or repository checkout. Those may not exist yet, and they are not the authority for first install.

Do this:
1. Call the MCP tool `init` once. If the tool accepts `workspace_name`, leave it empty so the client uses the current workspace name. If the tool accepts `mode`, use `standalone`; plugin installs use their own plugin-provided `/nogra:init` skill and pass `mode=plugin`.
2. Treat the returned bundle as the server-side source of truth. The server does not write files; you write only the returned files into this workspace.
3. Use `installPlan.phases[]` to narrate progress as phase-level checklist items. Keep chat narration quiet; do not narrate every individual file unless a write fails.
4. Apply every returned file according to its `path`, `content`, and `writePolicy`.
5. For `.nogra/config.json`, merge missing defaults into an existing valid config while preserving user-set values and unknown keys. If the existing JSON is invalid, stop and ask before replacing it.
6. Create parent directories as needed. Preserve existing files marked `ask_before_overwrite`; show the exact path and wait for explicit user approval before overwriting.
7. Do not install optional features such as the pinboard unless the user explicitly asks for that optional feature after core init.
8. If any phase fails, stop remaining phases, mark the failed phase with the concrete reason, and summarize what was already written/updated/preserved.
9. When complete, report written/updated/preserved/failed counts and show the post-install message returned by the server. Tell the user whether they need to fully quit and reopen Claude Code for newly installed local commands/skills to be available.

Important boundary: first-install bootstrap is MCP-owned. After this install, the local `/nogra` command and Nogra skills may guide normal workspace use, but they must not be required to perform this first install."""


def as_string_array(value: Any) -> list[str]:
    if isinstance(value, list):
        return [clean_inline(item) for item in value if clean_inline(item)]
    if isinstance(value, tuple):
        return [clean_inline(item) for item in value if clean_inline(item)]
    return []


def lines_from(value: Any) -> list[str]:
    lines: list[str] = []
    for raw in clean_text(value).split("\n"):
        line = re.sub(r"^[-*]\s+", "", raw.strip()).strip()
        if line and line.lower() != "none":
            lines.append(line)
    return lines


def split_inline_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return as_string_array(value)
    text = clean_inline(value)
    if not text:
        return []
    return [clean_inline(item.strip().strip("\"'")) for item in re.split(r"[,;]+", text) if clean_inline(item.strip().strip("\"'"))]


def parse_yaml_value(value: str) -> Any:
    text = value.strip()
    if text == "[]":
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [clean_inline(item) for item in parsed if clean_inline(item)]
        except json.JSONDecodeError:
            return split_inline_list(text[1:-1])
    return text.strip("\"'")


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"), -1)
    if end < 0:
        return {}, text
    meta: dict[str, Any] = {}
    list_key = ""
    for raw in lines[1:end]:
        line = raw.rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- ") and list_key:
            current = meta.setdefault(list_key, [])
            if isinstance(current, list):
                current.append(clean_inline(stripped[2:]).strip("\"'"))
            continue
        list_key = ""
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", stripped)
        if not match:
            continue
        key = match.group(1).replace("-", "_")
        raw_value = match.group(2).strip()
        if raw_value == "":
            meta[key] = []
            list_key = key
        else:
            meta[key] = parse_yaml_value(raw_value)
    return meta, "\n".join(lines[end + 1 :])


def normalize_sections(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    sections: list[dict[str, str]] = []
    for section in value:
        if not isinstance(section, dict):
            continue
        heading = clean_inline(section.get("h") or section.get("heading") or "")
        body = clean_text(section.get("body") or section.get("text") or "")
        if heading or body:
            sections.append({"h": heading, "body": body})
    return sections


def markdown_sections(body: str) -> tuple[list[dict[str, str]], str]:
    sections: list[dict[str, Any]] = []
    preamble: list[str] = []
    current: dict[str, Any] | None = None
    for raw in body.splitlines():
        if re.match(r"^#\s+[^#]", raw):
            continue
        heading = re.match(r"^##\s+(.+)", raw)
        if heading:
            current = {"h": clean_inline(heading.group(1)), "lines": []}
            sections.append(current)
            continue
        if current is None:
            if raw.strip():
                preamble.append(raw)
        else:
            current["lines"].append(raw)
    normalized = [{"h": item["h"], "body": clean_text("\n".join(item["lines"]))} for item in sections]
    return [section for section in normalized if section["h"] or section["body"]], clean_text("\n".join(preamble))


def section_body(sections: list[dict[str, str]], pattern: str) -> str:
    regex = re.compile(pattern, re.IGNORECASE)
    for section in sections:
        if regex.search(section.get("h", "")):
            return clean_text(section.get("body", ""))
    return ""


def all_section_text(sections: list[dict[str, str]]) -> str:
    parts = []
    for section in sections:
        heading = section.get("h") or "Section"
        body = section.get("body") or "(empty)"
        parts.append(f"### {heading}\n\n{body}")
    return clean_text("\n\n".join(parts))


def parse_scope_body(body: str) -> dict[str, list[str]]:
    parsed = {"in": [], "out": [], "files": []}
    current = "in"
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        label = line.rstrip(":").lower()
        if label in {"in", "include", "included"}:
            current = "in"
            continue
        if label in {"out", "exclude", "excluded"}:
            current = "out"
            continue
        if label in {"files", "file", "paths", "resources"}:
            current = "files"
            continue
        item = re.sub(r"^[-*]\s+", "", line).strip()
        if item and item.lower() != "none":
            parsed[current].append(item)
    return parsed


def parse_max_output_body(body: str) -> dict[str, str]:
    result = {"format": "", "limit": ""}
    for raw in body.splitlines():
        line = re.sub(r"^\s*[-*]\s+", "", raw).strip()
        line = re.sub(r"^\*\*([^*]+)\*\*\s*:\s*", r"\1: ", line)
        line = re.sub(r"^`([^`]+)`\s*:\s*", r"\1: ", line)
        match = re.match(r"^\s*([A-Za-z ]+):\s*(.+?)\s*$", line)
        if not match:
            continue
        key = match.group(1).strip().lower()
        if key == "format":
            result["format"] = clean_inline(match.group(2))
        elif key == "limit":
            result["limit"] = clean_inline(match.group(2))
    inline = clean_inline(body)
    if inline and (not result["format"] or not result["limit"]):
        if not result["format"]:
            format_match = re.search(r"\b([A-Za-z][A-Za-z -]*(?:report|brief|summary|verification))\b", inline, flags=re.IGNORECASE)
            result["format"] = clean_inline(format_match.group(1)) if format_match else default_return_policy()["format"]
        if not result["limit"]:
            result["limit"] = inline
    return result


def parse_execution_shape_body(body: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    tool_families: list[str] = []
    tool_needs: list[str] = []
    notes: list[str] = []
    current = "notes"
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        label = line.rstrip(":").lower()
        if label in {"tool families", "tool family", "families", "family", "capability families"}:
            current = "toolFamilies"
            continue
        if label in {"tool needs", "tool need", "tools", "capabilities", "capability needs"}:
            current = "toolNeeds"
            continue
        if label in {"notes", "note", "manager notes"}:
            current = "notes"
            continue
        item = re.sub(r"^[-*]\s+", "", line).strip()
        if not item or item.lower() == "none":
            continue
        if current == "toolFamilies":
            tool_families.append(item)
        elif current == "toolNeeds":
            tool_needs.append(item)
        else:
            notes.append(item)
    if tool_families:
        result["toolFamilies"] = tool_families
    if tool_needs:
        result["toolNeeds"] = tool_needs
    if notes:
        result["notes"] = "\n".join(notes)
    return result


def parse_markdown_brief(text: str) -> dict[str, Any]:
    source = clean_text(text)
    meta, body = parse_frontmatter(source)
    title_match = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
    sections, preamble = markdown_sections(body)
    output: dict[str, Any] = {
        "title": clean_inline(meta.get("title") or (title_match.group(1) if title_match else "Untitled brief")),
        "sections": sections,
        "metadata": {"source": "markdown"},
    }
    if meta:
        output["metadata"]["sourceFrontmatter"] = meta
    frontmatter_map = {
        "schema": "schema",
        "releaseVersion": "releaseVersion",
        "release_version": "releaseVersion",
        "briefId": "briefId",
        "brief_id": "briefId",
        "workspaceId": "workspaceId",
        "workspace_id": "workspaceId",
        "createdAt": "createdAt",
        "created_at": "createdAt",
        "updatedAt": "updatedAt",
        "updated_at": "updatedAt",
        "status": "status",
        "owner": "owner",
        "targetRole": "targetRole",
        "target_role": "targetRole",
        "targetModel": "targetModel",
        "target_model": "targetModel",
        "evidenceRequired": "evidenceRequired",
        "evidence_required": "evidenceRequired",
    }
    for source_key, target_key in frontmatter_map.items():
        if source_key in meta:
            output[target_key] = meta[source_key]
    if "intent" in meta:
        output["intent"] = meta["intent"]
    if preamble and "intent" not in output:
        output["intent"] = preamble
    return output


def parse_draft_input(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if not isinstance(payload, str):
        return {}
    try:
        parsed = json.loads(payload)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return parse_markdown_brief(payload)


def first_non_empty(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def collect_brief_extras(input_payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    existing_meta = existing.get("metadata", {}) if isinstance(existing, dict) else {}
    input_meta = input_payload.get("metadata", {}) if isinstance(input_payload.get("metadata"), dict) else {}
    for source in (existing_meta, input_meta):
        for key in ("source", "sourceFrontmatter", "promotedAt", "promotedPath"):
            if key in source:
                metadata[key] = source[key]
    return metadata


def normalize_execution_shape(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, raw in value.items():
                if key == "toolFamilies":
                    families = as_string_array(raw)
                    if families:
                        result["toolFamilies"] = families
                    continue
                if key == "toolNeeds":
                    needs = as_string_array(raw)
                    if needs:
                        result["toolNeeds"] = needs
                    continue
                if isinstance(raw, str):
                    cleaned = clean_text(raw)
                    if cleaned:
                        result[key] = cleaned
                elif isinstance(raw, list):
                    cleaned_list = as_string_array(raw)
                    if cleaned_list:
                        result[key] = cleaned_list
                elif raw not in (None, "", [], {}):
                    result[key] = raw
            if result:
                return result
        elif isinstance(value, str):
            cleaned = clean_text(value)
            if cleaned:
                return {"notes": cleaned}
    return {}


def normalize_brief(input_payload: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    at = now()
    existing = existing or {}
    sections = normalize_sections(input_payload.get("sections"))
    title = clean_inline(input_payload.get("title") or existing.get("title") or "Untitled brief")
    brief_id = safe_brief_id(input_payload.get("briefId") or input_payload.get("brief_id") or input_payload.get("id") or existing.get("briefId") or existing.get("brief_id") or new_brief_id(title))
    scope_section = parse_scope_body(section_body(sections, r"^scope|omfang"))
    files_section = lines_from(section_body(sections, r"^files|^filer|^paths|^resources"))
    max_output_section = parse_max_output_body(section_body(sections, r"max output|output"))
    execution_shape_section = parse_execution_shape_body(section_body(sections, r"execution shape|tool needs|tool shape"))
    input_scope = input_payload.get("scope") if isinstance(input_payload.get("scope"), dict) else {}
    existing_scope = existing.get("scope") if isinstance(existing.get("scope"), dict) else {}
    input_max = input_payload.get("maxOutput") if isinstance(input_payload.get("maxOutput"), dict) else {}
    if not input_max and isinstance(input_payload.get("returnPolicy"), dict):
        input_max = input_payload.get("returnPolicy", {})
    existing_max = existing.get("maxOutput") if isinstance(existing.get("maxOutput"), dict) else {}
    return_policy = default_return_policy()
    metadata = collect_brief_extras(input_payload, existing)
    source_text = all_section_text(sections)
    brief = {
        "schema": clean_inline(input_payload.get("schema") or existing.get("schema") or BRIEF_SCHEMA),
        "releaseVersion": clean_inline(input_payload.get("releaseVersion") or existing.get("releaseVersion") or RELEASE_VERSION),
        "briefId": brief_id,
        "workspaceId": clean_inline(input_payload.get("workspaceId") or input_payload.get("workspace_id") or existing.get("workspaceId") or existing.get("workspace_id") or workspace_label()),
        "title": title,
        "createdAt": clean_inline(input_payload.get("createdAt") or existing.get("createdAt") or at),
        "updatedAt": clean_inline(input_payload.get("updatedAt") or existing.get("updatedAt") or at),
        "status": clean_inline(input_payload.get("status") or existing.get("status") or "draft") or "draft",
        "owner": clean_inline(input_payload.get("owner") or existing.get("owner") or os.environ.get("NOGRA_OWNER", "")),
        "targetRole": clean_inline(input_payload.get("targetRole") or input_payload.get("target_role") or existing.get("targetRole") or existing.get("target_role") or ""),
        "targetModel": clean_inline(input_payload.get("targetModel") or input_payload.get("target_model") or existing.get("targetModel") or existing.get("target_model") or default_target_model()),
        "intent": first_non_empty(input_payload.get("intent"), existing.get("intent"), section_body(sections, r"intent|goal|objective|outcome")),
        "contextHandoff": first_non_empty(input_payload.get("contextHandoff"), existing.get("contextHandoff"), section_body(sections, r"context|handoff|background"), source_text),
        "decisions": as_string_array(input_payload.get("decisions")) or as_string_array(existing.get("decisions")) or lines_from(section_body(sections, r"decisions?")),
        "rejected": as_string_array(input_payload.get("rejected")) or as_string_array(existing.get("rejected")) or lines_from(section_body(sections, r"rejected|not")),
        "knownGaps": as_string_array(input_payload.get("knownGaps")) or as_string_array(existing.get("knownGaps")) or lines_from(section_body(sections, r"known gaps|gaps|unknown")),
        "scope": {
            "in": as_string_array(input_scope.get("in")) or as_string_array(existing_scope.get("in")) or scope_section["in"],
            "out": as_string_array(input_scope.get("out")) or as_string_array(existing_scope.get("out")) or scope_section["out"],
            "files": as_string_array(input_scope.get("files")) or as_string_array(existing_scope.get("files")) or scope_section["files"] or files_section,
        },
        "successCriteria": as_string_array(input_payload.get("successCriteria")) or as_string_array(existing.get("successCriteria")) or lines_from(section_body(sections, r"success|acceptance")),
        "stopCriteria": as_string_array(input_payload.get("stopCriteria")) or as_string_array(existing.get("stopCriteria")) or lines_from(section_body(sections, r"stop")),
        "maxOutput": {
            "format": clean_inline(input_max.get("format") or existing_max.get("format") or max_output_section["format"] or return_policy["format"]),
            "limit": clean_inline(input_max.get("limit") or existing_max.get("limit") or max_output_section["limit"] or return_policy["limit"]),
        },
        "executionShape": normalize_execution_shape(
            input_payload.get("executionShape"),
            input_payload.get("execution_shape"),
            existing.get("executionShape"),
            existing.get("execution_shape"),
            execution_shape_section,
        ),
        "evidenceRequired": clean_inline(input_payload.get("evidenceRequired") or existing.get("evidenceRequired") or "reported"),
        "handoffRefs": as_string_array(input_payload.get("handoffRefs")) or as_string_array(existing.get("handoffRefs")),
        "metadata": metadata,
    }
    if not brief["executionShape"]:
        brief.pop("executionShape")
    if not brief["metadata"]:
        brief.pop("metadata")
    return brief


def validate_brief(brief: dict[str, Any]) -> None:
    for key in BRIEF_REQUIRED:
        value = brief.get(key)
        if value is None or value == "":
            raise ValueError(f"brief missing {key}")
    if brief.get("schema") != BRIEF_SCHEMA:
        raise ValueError(f"brief schema mismatch: {brief.get('schema')}")
    safe_brief_id(str(brief.get("briefId", "")))
    if brief.get("status") and brief["status"] not in BRIEF_STATUSES:
        raise ValueError(f"brief status is not valid: {brief['status']}")
    if brief.get("evidenceRequired") and brief["evidenceRequired"] not in BRIEF_EVIDENCE:
        raise ValueError(f"brief evidenceRequired is not valid: {brief['evidenceRequired']}")
    scope = brief.get("scope")
    if not isinstance(scope, dict) or not isinstance(scope.get("in"), list) or not isinstance(scope.get("out"), list):
        raise ValueError("brief scope missing in/out arrays")
    if not isinstance(brief.get("successCriteria"), list) or not [item for item in brief["successCriteria"] if clean_inline(item)]:
        raise ValueError("brief missing successCriteria")
    if not isinstance(brief.get("stopCriteria"), list) or not [item for item in brief["stopCriteria"] if clean_inline(item)]:
        raise ValueError("brief missing stopCriteria")
    max_output = brief.get("maxOutput")
    if not isinstance(max_output, dict) or not clean_inline(max_output.get("format")) or not clean_inline(max_output.get("limit")):
        raise ValueError("brief missing maxOutput format/limit")
    execution_shape = brief.get("executionShape")
    if execution_shape is not None and not isinstance(execution_shape, dict):
        raise ValueError("brief executionShape must be an object when present")


def brief_draft_path(brief_id: str) -> Path:
    return briefs_drafts_dir() / f"{safe_brief_id(brief_id)}.json"


def brief_with_path(brief: dict[str, Any], path: Path) -> dict[str, Any]:
    return {**brief, "id": brief.get("briefId", ""), "path": workspace_path(path)}


def brief_with_local_path(brief: dict[str, Any], path: str) -> dict[str, Any]:
    return {**brief, "id": brief.get("briefId", ""), "path": local_write_path(path)}


def read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def save_draft_brief(payload: Any) -> dict[str, Any]:
    is_hosted = hosted_mode()
    if not is_hosted:
        ensure_runtime_dirs()
    input_payload = parse_draft_input(payload)
    candidate_id = input_payload.get("briefId") or input_payload.get("id")
    existing = None
    if candidate_id and not is_hosted:
        try:
            existing = read_json_object(brief_draft_path(str(candidate_id)))
        except (OSError, ValueError, json.JSONDecodeError):
            existing = None
    draft = normalize_brief(input_payload, existing)
    draft["status"] = "draft"
    draft["updatedAt"] = now()
    validate_brief(draft)
    draft["redactions"] = secrets_in_payload(brief_secret_payload(draft))
    if is_hosted:
        saved = brief_with_local_path(draft, local_brief_draft_path(draft["briefId"]))
    else:
        path = brief_draft_path(draft["briefId"])
        write_json_atomic(path, draft)
        saved = brief_with_path(draft, path)
    return attach_local_writes(
        saved,
        [
            local_write_json(
                local_brief_draft_path(draft["briefId"]),
                draft,
                "Persist Nogra brief draft locally.",
            )
        ],
    )


def read_brief_draft(brief_id: str) -> dict[str, Any]:
    path = brief_draft_path(brief_id)
    draft = read_json_object(path)
    return brief_with_path(draft, path)


def list_brief_drafts(limit: int = 10) -> list[dict[str, Any]]:
    drafts_dir = briefs_drafts_dir()
    if not drafts_dir.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in drafts_dir.glob("*.json"):
        try:
            stat = path.stat()
            draft = read_json_object(path)
            item = brief_with_path(draft, path)
            item["modifiedAt"] = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")
            items.append(item)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    items.sort(key=lambda item: item.get("updatedAt") or item.get("modifiedAt") or "", reverse=True)
    return items[: max(0, limit)]


def yaml_scalar(value: Any) -> str:
    text = clean_inline(value)
    if not text:
        return "\"\""
    if re.fullmatch(r"[A-Za-z0-9_.:/@ -]+", text):
        return text
    return json.dumps(text, ensure_ascii=False)


def render_list(items: Any, fallback: str = "None") -> str:
    values = as_string_array(items)
    if not values:
        values = [fallback]
    return "\n".join(f"- {item}" for item in values)


def render_execution_shape(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return ""
    parts: list[str] = []
    tool_families = as_string_array(value.get("toolFamilies"))
    if tool_families:
        parts.append("Tool families:\n\n" + render_list(tool_families))
    tool_needs = as_string_array(value.get("toolNeeds"))
    if tool_needs:
        parts.append("Tool needs:\n\n" + render_list(tool_needs))
    notes = clean_text(value.get("notes"))
    if notes:
        parts.append("Notes:\n\n" + notes)
    extras = []
    for key, raw in value.items():
        if key in {"toolFamilies", "toolNeeds", "notes"}:
            continue
        cleaned = clean_text(raw) if isinstance(raw, str) else ""
        if cleaned:
            extras.append(f"{key}: {cleaned}")
        elif isinstance(raw, list):
            entries = as_string_array(raw)
            if entries:
                extras.append(f"{key}:\n{render_list(entries)}")
    if extras:
        parts.append("\n\n".join(extras))
    if not parts:
        return ""
    return "## Execution Shape\n\n" + "\n\n".join(parts) + "\n\n"


def render_brief_markdown(brief: dict[str, Any]) -> str:
    validate_brief(brief)
    frontmatter_fields = [
        ("schema", brief.get("schema")),
        ("releaseVersion", brief.get("releaseVersion", RELEASE_VERSION)),
        ("briefId", brief.get("briefId")),
        ("workspaceId", brief.get("workspaceId")),
        ("title", brief.get("title")),
        ("createdAt", brief.get("createdAt")),
        ("updatedAt", brief.get("updatedAt")),
        ("status", brief.get("status")),
        ("owner", brief.get("owner", "")),
        ("targetRole", brief.get("targetRole", "")),
        ("targetModel", brief.get("targetModel", default_target_model())),
        ("evidenceRequired", brief.get("evidenceRequired", "")),
    ]
    frontmatter = "\n".join(f"{key}: {yaml_scalar(value)}" for key, value in frontmatter_fields)
    scope = brief.get("scope", {})
    max_output = brief.get("maxOutput", {})
    execution_shape = render_execution_shape(brief.get("executionShape"))
    return (
        f"---\n{frontmatter}\n---\n\n"
        f"# {brief['title']}\n\n"
        f"## Intent\n\n{brief['intent']}\n\n"
        f"## Context Handoff\n\n{brief['contextHandoff']}\n\n"
        f"## Decisions\n\n{render_list(brief.get('decisions'))}\n\n"
        f"## Rejected\n\n{render_list(brief.get('rejected'))}\n\n"
        f"## Known Gaps\n\n{render_list(brief.get('knownGaps'))}\n\n"
        f"## Scope\n\nIn:\n\n{render_list(scope.get('in'))}\n\nOut:\n\n{render_list(scope.get('out'))}\n\nFiles:\n\n{render_list(scope.get('files'))}\n\n"
        f"## Success Criteria\n\n{render_list(brief.get('successCriteria'))}\n\n"
        f"## Stop Criteria\n\n{render_list(brief.get('stopCriteria'))}\n\n"
        f"{execution_shape}"
        f"## Max Output\n\nFormat: {max_output.get('format', '')}\nLimit: {max_output.get('limit', '')}\n"
    )


def next_brief_path(brief: dict[str, Any]) -> Path:
    briefs_dir().mkdir(parents=True, exist_ok=True)
    date = now()[:10]
    base = f"BRIEF-{slugify(brief.get('title')).lower()}-{date}"
    path = briefs_dir() / f"{base}.md"
    index = 2
    while path.exists():
        path = briefs_dir() / f"{base}-{index}.md"
        index += 1
    return path


def parse_brief_file(path: Path) -> dict[str, Any]:
    parsed = parse_markdown_brief(path.read_text(encoding="utf-8"))
    brief = normalize_brief(parsed)
    validate_brief(brief)
    return brief_with_path(brief, path)


def promoted_brief_files() -> list[Path]:
    directory = briefs_dir()
    if not directory.is_dir():
        return []
    return [path for path in directory.glob("*.md") if path.is_file()]


def find_promoted_brief_path(brief_id: str) -> Path | None:
    wanted = safe_brief_id(brief_id)
    for path in promoted_brief_files():
        try:
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if clean_inline(meta.get("briefId") or meta.get("brief_id")) == wanted:
            return path
    return None


def promote_brief_payload(payload: Any, brief_id: str = "") -> dict[str, Any]:
    input_payload = parse_draft_input(payload)
    requested_id = clean_inline(brief_id)
    if requested_id:
        requested_id = safe_brief_id(requested_id)
        inline_id = clean_inline(input_payload.get("briefId") or input_payload.get("id"))
        if inline_id and safe_brief_id(inline_id) != requested_id:
            raise ValueError("brief_id does not match inline brief payload")
        input_payload["briefId"] = requested_id
    ready = normalize_brief(input_payload, input_payload)
    ready["status"] = "ready"
    ready["updatedAt"] = now()
    validate_brief(ready)
    markdown = render_brief_markdown(ready)
    metadata = dict(ready.get("metadata") or {})
    metadata["promotedAt"] = now()
    metadata["promotedPath"] = local_promoted_brief_path(ready["briefId"])
    updated_draft = {**ready, "metadata": metadata}
    draft_with_path = brief_with_local_path(updated_draft, local_brief_draft_path(ready["briefId"]))
    promoted = brief_with_local_path(updated_draft, local_promoted_brief_path(ready["briefId"]))
    return attach_local_writes(
        {
            "draft": draft_with_path,
            "brief": promoted,
            "path": local_promoted_brief_path(ready["briefId"]),
            "mode": "hosted-stateless" if hosted_mode() else "inline",
        },
        [
            local_write_json(
                local_brief_draft_path(ready["briefId"]),
                updated_draft,
                "Persist promoted Nogra brief draft state locally.",
            ),
            local_write_text(
                local_promoted_brief_path(ready["briefId"]),
                markdown,
                "Persist promoted Nogra brief markdown locally.",
                mime_type="text/markdown",
            ),
        ],
    )


def promote_brief_draft(brief_id: str) -> dict[str, Any]:
    if hosted_mode():
        cleaned = safe_brief_id(brief_id)
        return {
            "status": "local_required",
            "mode": "hosted-stateless",
            "briefId": cleaned,
            "code": "HOSTED_BRIEF_STORAGE_IS_LOCAL",
            "error": "Hosted Nogra does not read server-side draft state. Read the local draft JSON and call brief_promote with the inline payload.",
            "localDraftPath": local_brief_draft_path(cleaned),
            "nextOwner": "ManagerClaude",
        }
    draft = read_brief_draft(brief_id)
    ready = normalize_brief({**draft, "status": "ready"}, draft)
    ready["status"] = "ready"
    ready["updatedAt"] = now()
    validate_brief(ready)
    path = next_brief_path(ready)
    markdown = render_brief_markdown(ready)
    path.write_text(markdown, encoding="utf-8")
    metadata = dict(ready.get("metadata") or {})
    metadata["promotedAt"] = now()
    metadata["promotedPath"] = workspace_path(path)
    updated_draft = {**ready, "metadata": metadata}
    write_json_atomic(brief_draft_path(ready["briefId"]), updated_draft)
    draft_with_path = brief_with_path(updated_draft, brief_draft_path(ready["briefId"]))
    promoted = parse_brief_file(path)
    return attach_local_writes(
        {
            "draft": draft_with_path,
            "brief": promoted,
            "path": workspace_path(path),
        },
        [
            local_write_json(
                local_brief_draft_path(ready["briefId"]),
                updated_draft,
                "Persist promoted Nogra brief draft state locally.",
            ),
            local_write_text(
                local_promoted_brief_path(ready["briefId"]),
                markdown,
                "Persist promoted Nogra brief markdown locally.",
                mime_type="text/markdown",
            ),
        ],
    )


def brief_read(brief_id: str) -> dict[str, Any]:
    if hosted_mode():
        cleaned = safe_brief_id(brief_id)
        return {
            "status": "local_required",
            "mode": "hosted-stateless",
            "briefId": cleaned,
            "code": "HOSTED_BRIEF_STORAGE_IS_LOCAL",
            "error": "Hosted Nogra cannot read customer-local brief files. Read the local .nogra/ brief artifact and pass it inline to the next hosted call.",
            "draftPath": local_brief_draft_path(cleaned),
            "promotedPath": local_promoted_brief_path(cleaned),
        }
    try:
        draft = read_brief_draft(brief_id)
        promoted_path = draft.get("metadata", {}).get("promotedPath") if isinstance(draft.get("metadata"), dict) else ""
        if draft.get("status") == "ready" and promoted_path:
            return {"status": "ok", "brief": draft, "path": promoted_path}
        return {"status": "ok", "brief": draft, "path": draft.get("path", "")}
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    path = find_promoted_brief_path(brief_id)
    if path is None:
        return {"status": "missing", "brief": {}, "path": ""}
    try:
        return {"status": "ok", "brief": parse_brief_file(path), "path": workspace_path(path)}
    except (OSError, ValueError, json.JSONDecodeError):
        return {"status": "missing", "brief": {}, "path": ""}


def recent_briefs(limit: int = 10) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for draft in list_brief_drafts(limit=1000):
        items.append(
            {
                "briefId": draft.get("briefId", ""),
                "status": draft.get("status", ""),
                "title": draft.get("title", ""),
                "path": draft.get("path", ""),
                "updatedAt": draft.get("updatedAt") or draft.get("modifiedAt", ""),
            }
        )
    for path in promoted_brief_files():
        try:
            stat = path.stat()
            brief = parse_brief_file(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        items.append(
            {
                "briefId": brief.get("briefId", ""),
                "status": brief.get("status", ""),
                "title": brief.get("title", ""),
                "path": workspace_path(path),
                "updatedAt": brief.get("updatedAt") or datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        )
    items.sort(key=lambda item: item.get("updatedAt", ""), reverse=True)
    return {"workspaceId": workspace_label(), "briefs": items[: max(0, limit)]}


def parse_iso_timestamp(value: Any) -> float | None:
    text = clean_inline(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def transport_run_id_new() -> str:
    return f"transport-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def transport_safe_run_id(value: str) -> str:
    run_id = clean_inline(value)
    if not re.fullmatch(r"transport-\d{14}-[a-f0-9]{8}", run_id):
        raise ValueError(f"invalid transport run id: {run_id or '(empty)'}")
    return run_id


def transport_run_path(run_id: str) -> Path:
    return transport_runs_dir() / f"{transport_safe_run_id(run_id)}.json"


def transport_archive_path(run_id: str) -> Path:
    return transport_archive_dir() / f"{transport_safe_run_id(run_id)}.json"


def transport_artifact_paths(run_id: str) -> dict[str, str]:
    artifact_dir = transport_artifacts_dir(run_id)
    return {
        "artifactsDir": workspace_path(artifact_dir),
        "report": workspace_path(artifact_dir / "report.md"),
        "output": workspace_path(artifact_dir / "output.md"),
        "log": workspace_path(artifact_dir / "log"),
    }


def transport_artifacts_for(record: dict[str, Any]) -> dict[str, bool]:
    paths = record.get("paths") if isinstance(record.get("paths"), dict) else {}
    return {
        "reportExists": workspace_file(str(paths.get("report", ""))).is_file() if paths.get("report") else False,
        "outputExists": workspace_file(str(paths.get("output", ""))).is_file() if paths.get("output") else False,
        "logExists": workspace_file(str(paths.get("log", ""))).is_file() if paths.get("log") else False,
    }


def transport_duration_seconds(record: dict[str, Any]) -> float | None:
    start = parse_iso_timestamp(record.get("createdAt"))
    end = parse_iso_timestamp(record.get("completedAt"))
    if start is None or end is None:
        return None
    return max(0.0, round(end - start, 3))


def transport_public_run(record: dict[str, Any]) -> dict[str, Any]:
    public = {
        "schema": record.get("schema", TRANSPORT_RUN_SCHEMA),
        "releaseVersion": record.get("releaseVersion", RELEASE_VERSION),
        "runId": record.get("runId", ""),
        "createdAt": record.get("createdAt", ""),
        "updatedAt": record.get("updatedAt", ""),
        "status": record.get("status", ""),
        "phase": record.get("phase", ""),
        "target": record.get("target", ""),
        "targetRole": record.get("targetRole", ""),
        "targetModel": record.get("targetModel", ""),
        "briefId": record.get("briefId", ""),
        "metadata": record.get("metadata") if isinstance(record.get("metadata"), dict) else {},
        "paths": record.get("paths") if isinstance(record.get("paths"), dict) else {},
        "artifacts": {},
        "notes": record.get("notes", ""),
        "error": record.get("error", ""),
        "summary": record.get("summary", ""),
        "completedAt": record.get("completedAt"),
        "acknowledgedAt": record.get("acknowledgedAt"),
        "durationSeconds": record.get("durationSeconds"),
        "redactions": record.get("redactions") if isinstance(record.get("redactions"), list) else [],
    }
    if record.get("reportSubmittedAt"):
        public["reportSubmittedAt"] = record.get("reportSubmittedAt")
    if record.get("cancelledAt"):
        public["cancelledAt"] = record.get("cancelledAt")
    if record.get("archivedAt"):
        public["archivedAt"] = record.get("archivedAt")
    public["artifacts"] = transport_artifacts_for(public)
    return public


def transport_event_record(run_id: str, event_type: str, **fields: Any) -> dict[str, Any]:
    event_id = clean_inline(fields.pop("eventId", "")) or f"transport-event-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    generated = now()
    return {
        "schema": TRANSPORT_EVENT_SCHEMA,
        "releaseVersion": RELEASE_VERSION,
        "eventId": event_id,
        "generatedAt": generated,
        "createdAt": generated,
        "workspaceId": workspace_label(),
        "runId": run_id,
        "type": event_type,
        **fields,
    }


def transport_append_event(run_id: str, event_type: str, **fields: Any) -> dict[str, Any]:
    ensure_runtime_dirs()
    event = transport_event_record(run_id, event_type, **fields)
    append_jsonl(transport_events_path(), event)
    return event


def transport_read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def transport_save_run(record: dict[str, Any], archived: bool = False) -> dict[str, Any]:
    ensure_runtime_dirs()
    run_id = transport_safe_run_id(str(record.get("runId", "")))
    record["updatedAt"] = now()
    if record.get("completedAt"):
        record["durationSeconds"] = transport_duration_seconds(record)
    record["artifacts"] = transport_artifacts_for(record)
    write_json_atomic(transport_archive_path(run_id) if archived else transport_run_path(run_id), record)
    return record


def transport_load_run(run_id: str, include_archive: bool = True) -> dict[str, Any]:
    try:
        cleaned = transport_safe_run_id(run_id)
    except ValueError:
        return {}
    ensure_runtime_dirs()
    record = transport_read_json(transport_run_path(cleaned))
    if not record and include_archive:
        record = transport_read_json(transport_archive_path(cleaned))
    if not record:
        return {}
    return transport_public_run(record)


def transport_register_run(target: str, brief_id: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    run_id = transport_run_id_new()
    artifacts = transport_artifact_paths(run_id)
    if not hosted_mode():
        ensure_runtime_dirs()
        transport_artifacts_dir(run_id).mkdir(parents=True, exist_ok=True)
    created = now()
    record = {
        "schema": TRANSPORT_RUN_SCHEMA,
        "releaseVersion": RELEASE_VERSION,
        "runId": run_id,
        "createdAt": created,
        "updatedAt": created,
        "status": "queued",
        "phase": "queued",
        "target": clean_inline(target),
        "targetRole": clean_inline((metadata or {}).get("targetRole", "")) if isinstance(metadata, dict) else "",
        "targetModel": clean_inline((metadata or {}).get("targetModel", "")) if isinstance(metadata, dict) else "",
        "briefId": clean_inline(brief_id),
        "metadata": metadata if isinstance(metadata, dict) else {},
        "paths": artifacts,
        "artifacts": {"reportExists": False, "outputExists": False, "logExists": False},
        "notes": "",
        "error": "",
        "summary": "",
        "completedAt": None,
        "acknowledgedAt": None,
        "durationSeconds": None,
    }
    record["redactions"] = merge_redactions([], record["target"], record["metadata"])
    if hosted_mode():
        event = transport_event_record(
            run_id,
            "transport_run_created",
            target=record["target"],
            targetRole=record["targetRole"],
            targetModel=record["targetModel"],
            briefId=record["briefId"],
        )
    else:
        transport_save_run(record)
        event = transport_append_event(
            run_id,
            "transport_run_created",
            target=record["target"],
            targetRole=record["targetRole"],
            targetModel=record["targetModel"],
            briefId=record["briefId"],
        )
    public = transport_public_run(record)
    return attach_local_writes(public, [local_transport_run_write(public), local_transport_event_write(event)])


def transport_recent_runs(limit: int = 20, include_archive: bool = False) -> dict[str, Any]:
    ensure_runtime_dirs()
    paths = list(transport_runs_dir().glob("*.json"))
    if include_archive:
        paths.extend(transport_archive_dir().glob("*.json"))
    records: list[dict[str, Any]] = []
    for path in paths:
        record = transport_read_json(path)
        if record.get("runId"):
            records.append(transport_public_run(record))
    records.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
    return {"workspaceId": workspace_label(), "runs": records[: max(0, limit)]}


def transport_latest_run_id() -> str:
    runs = transport_recent_runs(limit=1).get("runs", [])
    return str(runs[0].get("runId") or "") if runs else ""


def transport_update_run(
    run_id: str,
    status: str = "",
    phase: str = "",
    notes: str = "",
    error: str = "",
    summary: str = "",
    artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = run_id or transport_latest_run_id()
    record = transport_load_run(resolved, include_archive=False)
    if not record:
        return {"status": "missing", "runId": resolved, "error": "transport run not found"}
    changed: dict[str, Any] = {}
    normalized_status = normalize_transport_status(status)
    normalized_phase = clean_inline(phase).lower()
    if normalized_status:
        if normalized_status not in TRANSPORT_STATUSES:
            return transport_status_invalid(resolved, normalized_status)
        record["status"] = normalized_status
        changed["status"] = normalized_status
        if normalized_status in {"running", "queued", "returning"} and not normalized_phase:
            normalized_phase = normalized_status
        elif normalized_status in TRANSPORT_TERMINAL_STATUSES | {"returned"} and not normalized_phase:
            normalized_phase = "returned"
        if normalized_status in TRANSPORT_TERMINAL_STATUSES | {"returned"} and not record.get("completedAt"):
            record["completedAt"] = now()
            changed["completedAt"] = record["completedAt"]
    if normalized_phase:
        if normalized_phase not in TRANSPORT_PHASES:
            return {"status": "invalid", "runId": resolved, "error": f"transport phase is not valid: {normalized_phase}"}
        record["phase"] = normalized_phase
        changed["phase"] = normalized_phase
    if notes:
        record["notes"] = notes
        changed["notes"] = notes
    if error:
        record["error"] = error
        changed["error"] = error
    if summary:
        record["summary"] = summary
        changed["summary"] = summary
    if isinstance(artifacts, dict) and artifacts:
        existing_artifacts = record.get("artifacts") if isinstance(record.get("artifacts"), dict) else {}
        record["artifacts"] = {**existing_artifacts, **artifacts}
        changed["artifacts"] = artifacts
    record["redactions"] = merge_redactions(
        record.get("redactions"),
        {"status": normalized_status, "phase": normalized_phase, "notes": notes, "error": error, "summary": summary},
    )
    transport_save_run(record)
    event = transport_append_event(str(record["runId"]), "transport_run_updated", **changed)
    public = transport_public_run(record)
    return attach_local_writes(public, [local_transport_run_write(public), local_transport_event_write(event)])


def transport_abort_record(
    record: dict[str, Any],
    reason: str = "",
    summary: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    run_id = transport_safe_run_id(str(record.get("runId") or ""))
    cancelled_at = now()
    reason_clean = clean_inline(reason) or "User cancelled the run before completion."
    summary_clean = clean_inline(summary) or "Run cancelled by user before completion."
    updated = dict(record)
    updated["runId"] = run_id
    updated["updatedAt"] = cancelled_at
    updated["status"] = "cancelled"
    updated["phase"] = "returned"
    updated["cancelledAt"] = cancelled_at
    updated["completedAt"] = updated.get("completedAt") or cancelled_at
    updated["notes"] = reason_clean
    updated["summary"] = summary_clean
    updated["redactions"] = merge_redactions(
        updated.get("redactions"),
        {"reason": reason_clean, "summary": summary_clean},
    )
    public = transport_public_run(updated)
    if hosted_mode() and isinstance(updated.get("artifacts"), dict):
        public["artifacts"] = updated["artifacts"]
    event = transport_event_record(
        run_id,
        "transport_run_cancelled",
        status="cancelled",
        phase="returned",
        reason=reason_clean,
        summary=summary_clean,
        nextOwner="ManagerClaude",
    )
    return public, event


def transport_abort_run(run_id: str, reason: str = "", summary: str = "") -> dict[str, Any]:
    resolved = run_id or transport_latest_run_id()
    record = transport_load_run(resolved, include_archive=False)
    if not record:
        return {"status": "missing", "runId": resolved, "error": "transport run not found"}
    public, event = transport_abort_record(record, reason=reason, summary=summary)
    transport_save_run(public)
    append_jsonl(transport_events_path(), event)
    return attach_local_writes(
        public,
        [
            local_transport_run_write(public, "Mark transport run cancelled locally."),
            local_transport_event_write(event, "Record transport run cancellation locally."),
        ],
    )


def read_text_if_exists(path_value: str, limit: int = 120_000) -> str:
    if not path_value:
        return ""
    try:
        text = workspace_file(path_value).read_text(encoding="utf-8")
    except OSError:
        return ""
    return text[: max(0, limit)]


def transport_submit_report(
    run_id: str,
    report_text: str,
    status: str = "",
    summary: str = "",
    output_text: str = "",
    allow_overwrite: bool = False,
) -> dict[str, Any]:
    record = transport_load_run(run_id, include_archive=False)
    if not record:
        return {"status": "missing", "runId": run_id, "error": "transport run not found"}
    text = report_text.rstrip()
    if not text:
        return {"status": "invalid", "runId": run_id, "error": "report_text required"}
    normalized_status = normalize_transport_status(status)
    if normalized_status and normalized_status not in TRANSPORT_STATUSES:
        return transport_status_invalid(run_id, normalized_status)
    paths = record.get("paths") if isinstance(record.get("paths"), dict) else {}
    report_path = workspace_file(str(paths.get("report", "")))
    output_path = workspace_file(str(paths.get("output", "")))
    try:
        if report_path.exists() and report_path.stat().st_size > 0 and not allow_overwrite:
            return {"status": "exists", "runId": run_id, "report": workspace_path(report_path), "error": "report already exists; pass allow_overwrite=true to replace it"}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text + "\n", encoding="utf-8")
        output_payload = output_text.rstrip() if output_text.strip() else text
        if allow_overwrite or not output_path.exists() or output_path.stat().st_size == 0:
            output_path.write_text(output_payload + "\n", encoding="utf-8")
    except OSError as exc:
        event = transport_append_event(run_id, "transport_report_submit_failed", error=str(exc), report=workspace_path(report_path))
        return attach_local_writes(
            {"status": "failed", "runId": run_id, "error": str(exc)},
            [local_transport_event_write(event)],
        )
    submitted_at = now()
    record["phase"] = "returning"
    record["reportSubmittedAt"] = submitted_at
    if normalized_status:
        record["status"] = normalized_status
        if normalized_status in TRANSPORT_TERMINAL_STATUSES | {"returned"}:
            record["completedAt"] = record.get("completedAt") or submitted_at
    if summary.strip():
        record["summary"] = summary.strip()
    record["redactions"] = merge_redactions(
        record.get("redactions"),
        {"reportText": report_text, "outputText": output_text, "summary": summary},
    )
    transport_save_run(record)
    event = transport_append_event(
        run_id,
        "transport_report_submitted",
        submittedStatus=normalized_status,
        summary=summary.strip(),
        report=workspace_path(report_path),
        output=workspace_path(output_path),
    )
    public = transport_public_run(record)
    evidence = {
        "runId": run_id,
        "filesChanged": [],
        "commandsRun": [],
        "acceptance": [],
        "report": workspace_path(report_path),
        "output": workspace_path(output_path),
    }
    payload = {
        "status": "ok",
        "runId": run_id,
        "report": workspace_path(report_path),
        "output": workspace_path(output_path),
        "run": public,
        "evidence": evidence,
    }
    return attach_local_writes(
        payload,
        [
            local_write_text(
                local_transport_artifact_path(run_id, "report.md"),
                text,
                "Persist transport report locally.",
                mime_type="text/markdown",
            ),
            local_write_text(
                local_transport_artifact_path(run_id, "output.md"),
                output_payload,
                "Persist transport output locally.",
                mime_type="text/markdown",
            ),
            local_transport_run_write(public),
            local_transport_event_write(event),
        ],
    )


def transport_return_payload(run_id: str = "", include_text: bool = True, text_limit: int = 120_000) -> dict[str, Any]:
    resolved = run_id or transport_latest_run_id()
    record = transport_load_run(resolved, include_archive=True)
    if not record:
        return {"status": "missing", "runId": resolved, "error": "transport run not found"}
    payload: dict[str, Any] = {"status": record.get("status"), "run": record}
    if include_text:
        paths = record.get("paths") if isinstance(record.get("paths"), dict) else {}
        payload["reportText"] = read_text_if_exists(str(paths.get("report", "")), limit=text_limit)
        payload["outputText"] = read_text_if_exists(str(paths.get("output", "")), limit=text_limit)
    return payload


def transport_read_events(limit: int = 80, run_id: str = "") -> dict[str, Any]:
    ensure_runtime_dirs()
    try:
        lines = transport_events_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"workspaceId": workspace_label(), "events": []}
    events: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if run_id and event.get("runId") != run_id:
            continue
        events.append(event)
        if len(events) >= max(0, limit):
            break
    events.reverse()
    return {"workspaceId": workspace_label(), "events": events}


def transport_ack_run(run_id: str, note: str = "") -> dict[str, Any]:
    resolved = run_id or transport_latest_run_id()
    record = transport_load_run(resolved, include_archive=False)
    if not record:
        return {"status": "missing", "runId": resolved, "error": "transport run not found"}
    record["acknowledgedAt"] = now()
    if note:
        record["notes"] = note
    if record.get("status") in TRANSPORT_TERMINAL_STATUSES:
        record["phase"] = "acknowledged"
    transport_save_run(record)
    event = transport_append_event(str(record["runId"]), "transport_acknowledged", note=note)
    public = transport_public_run(record)
    return attach_local_writes(public, [local_transport_run_write(public), local_transport_event_write(event)])


def transport_rotate_events(max_events: int, dry_run: bool) -> list[dict[str, Any]]:
    if max_events <= 0 or not transport_events_path().is_file():
        return []
    lines = transport_events_path().read_text(encoding="utf-8").splitlines()
    if len(lines) <= max_events:
        return []
    keep = lines[-max_events:]
    drop = lines[:-max_events]
    archive_path = transport_archive_dir() / f"events-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.jsonl"
    action = {"action": "rotate-events", "archivedLines": len(drop), "keptLines": len(keep), "archive": workspace_path(archive_path)}
    if not dry_run:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_text("\n".join(drop) + "\n", encoding="utf-8")
        transport_events_path().write_text("\n".join(keep) + "\n", encoding="utf-8")
    return [action]


def transport_cleanup(archive_after_hours: float = 24, orphan_after_seconds: int = 900, max_events: int = 5000, dry_run: bool = False) -> dict[str, Any]:
    ensure_runtime_dirs()
    actions: list[dict[str, Any]] = []
    local_writes: list[dict[str, Any]] = []
    now_ts = datetime.now(timezone.utc).timestamp()
    archive_cutoff = now_ts - max(0.0, archive_after_hours) * 3600
    orphan_cutoff = now_ts - max(0, orphan_after_seconds)
    for path in sorted(transport_runs_dir().glob("*.json")):
        record = transport_read_json(path)
        if not record.get("runId"):
            continue
        run_id = str(record["runId"])
        updated_ts = parse_iso_timestamp(record.get("updatedAt")) or path.stat().st_mtime
        status = str(record.get("status") or "")
        if status in TRANSPORT_ACTIVE_STATUSES and updated_ts < orphan_cutoff:
            actions.append({"action": "mark-orphaned", "runId": run_id})
            if not dry_run:
                record["status"] = "orphaned"
                record["phase"] = "returned"
                record["completedAt"] = record.get("completedAt") or now()
                record["error"] = record.get("error") or "cleanup marked active run orphaned after inactivity cutoff"
                transport_save_run(record)
                event = transport_append_event(run_id, "transport_cleanup_orphaned")
                public = transport_public_run(record)
                local_writes.extend([local_transport_run_write(public), local_transport_event_write(event)])
            continue
        if status in TRANSPORT_RETURNABLE_STATUSES and (record.get("acknowledgedAt") or updated_ts < archive_cutoff):
            archive_path = transport_archive_path(run_id)
            actions.append({"action": "archive-state", "runId": run_id, "from": workspace_path(path), "to": workspace_path(archive_path)})
            if not dry_run:
                record["phase"] = "archived"
                record["archivedAt"] = now()
                transport_save_run(record, archived=True)
                try:
                    path.unlink()
                except OSError:
                    pass
                event = transport_append_event(run_id, "transport_archived", archive=workspace_path(archive_path))
                public = transport_public_run(record)
                local_writes.extend(
                    [
                        local_write_json(
                            local_transport_archive_path(run_id),
                            public,
                            "Persist archived transport run state locally.",
                        ),
                        local_transport_event_write(event),
                    ]
                )
    actions.extend(transport_rotate_events(max_events=max_events, dry_run=dry_run))
    return attach_local_writes(
        {"generatedAt": now(), "status": "ok", "dryRun": dry_run, "actions": actions, "stateDir": workspace_path(transport_dir())},
        local_writes,
    )


def normalize_doctrine_refs(value: list[str] | tuple[str, ...] | None) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    refs: list[str] = []
    for item in value:
        ref = clean_inline(item)
        if ref:
            refs.append(ref)
    return refs


def resolve_doctrine_ref(ref: str) -> dict[str, str]:
    root = workspace_root().resolve()
    candidate = (root / ref).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return {"ref": ref, "path": "", "text": "", "error": "not found"}
    if not candidate.is_file():
        return {"ref": ref, "path": "", "text": "", "error": "not found"}
    try:
        text = candidate.read_text(encoding="utf-8")[:40000]
    except OSError:
        return {"ref": ref, "path": workspace_path(candidate), "text": "", "error": "not readable"}
    return {"ref": ref, "path": workspace_path(candidate), "text": text}


def build_dispatch_handoff(
    brief_id: str,
    target: str,
    parent_run_id: str = "",
    intent_id: str = "",
    doctrine_refs: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        cleaned_brief_id = safe_brief_id(brief_id)
    except ValueError as exc:
        return {"status": "invalid", "error": str(exc)}
    cleaned_target = clean_inline(target)
    if not cleaned_target:
        return {"status": "invalid", "briefId": cleaned_brief_id, "error": "target required"}
    loaded = brief_read(cleaned_brief_id)
    if loaded.get("status") == "missing" or not loaded.get("brief"):
        return {"status": "missing", "briefId": cleaned_brief_id, "error": "brief not found"}
    refs = normalize_doctrine_refs(doctrine_refs)
    handoff = {
        "schema": DISPATCH_HANDOFF_SCHEMA,
        "releaseVersion": RELEASE_VERSION,
        "generatedAt": now(),
        "target": cleaned_target,
        "briefId": cleaned_brief_id,
        "brief": loaded["brief"],
        "parentRunId": clean_inline(parent_run_id),
        "intentId": clean_inline(intent_id),
        "doctrineRefs": refs,
        "doctrine": [resolve_doctrine_ref(ref) for ref in refs],
        "metadata": metadata if isinstance(metadata, dict) else {},
    }
    handoff["redactions"] = merge_redactions(
        [],
        brief_secret_payload(handoff["brief"]),
        [item.get("text", "") for item in handoff["doctrine"] if isinstance(item, dict)],
        handoff["metadata"],
    )
    return handoff


def provider_handoff(provider: str, prompt: str, context: str = "", intent: str = "consult", surface: str = "pass-through") -> dict[str, Any]:
    if not provider.strip():
        return {"status": "error", "code": "PROVIDER_REQUIRED"}
    if not prompt.strip():
        return {"status": "error", "code": "PROMPT_REQUIRED"}
    raw_intent = clean_inline(intent)
    raw_surface = clean_inline(surface)
    warnings: list[str] = []
    if raw_intent and raw_intent not in PROVIDER_INTENTS:
        warnings.append(f"unknown intent {raw_intent!r}; defaulted to 'consult'")
    if raw_surface and raw_surface not in PROVIDER_SURFACES:
        warnings.append(f"unknown surface {raw_surface!r}; defaulted to 'pass-through'")
    selected_intent = raw_intent if raw_intent in PROVIDER_INTENTS else "consult"
    selected_surface = raw_surface if raw_surface in PROVIDER_SURFACES else "pass-through"
    ensure_runtime_dirs()
    handoff_id = f"provider-handoff-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    rendered, redactions = render_provider_handoff_prompt(provider, prompt, context, selected_intent)
    receipt = {
        "schema": "nogra.provider.handoff.receipt.v1",
        "releaseVersion": RELEASE_VERSION,
        "handoffId": handoff_id,
        "createdAt": now(),
        "workspaceId": workspace_label(),
        "status": "dry_run",
        "provider": provider.strip(),
        "intent": selected_intent,
        "surface": selected_surface,
        "renderedPromptRedacted": rendered,
        "redactions": redactions,
        "providerCall": {"attempted": False, "reason": "v1 dry-run"},
    }
    if warnings:
        receipt["normalizationWarnings"] = warnings
    write_json(nogra_dir() / "receipts" / f"{handoff_id}.json", receipt)
    response = {
        "status": "dry_run",
        "handoffId": handoff_id,
        "provider": provider.strip(),
        "intent": selected_intent,
        "surface": selected_surface,
        "receiptUri": f"nogra://workspace/{workspace_label()}/provider-handoffs/{handoff_id}",
        "renderedPromptRedacted": rendered,
        "redactions": redactions,
    }
    if warnings:
        response["normalizationWarnings"] = warnings
    return attach_local_writes(
        response,
        [
            local_write_json(
                local_provider_handoff_receipt_path(handoff_id),
                receipt,
                "Persist Nogra provider handoff receipt locally.",
            )
        ],
    )


def provider_handoff_read(handoff_id: str) -> dict[str, Any]:
    cleaned = safe_id(handoff_id, "provider-handoff")
    if not cleaned.startswith("provider-handoff-"):
        return {"status": "error", "code": "HANDOFF_ID_INVALID"}
    receipt_file = nogra_dir() / "receipts" / f"{cleaned}.json"
    if not receipt_file.is_file():
        return {"status": "missing", "handoffId": cleaned}
    try:
        payload = json.loads(receipt_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "error", "code": "RECEIPT_INVALID", "handoffId": cleaned}
    return {
        "status": "ok",
        "handoffId": payload.get("handoffId", cleaned),
        "provider": payload.get("provider", payload.get("model", "")),
        "intent": payload.get("intent", payload.get("mode", "")),
        "renderedPromptRedacted": payload.get("renderedPromptRedacted", ""),
        "redactions": payload.get("redactions", []),
    }


def post_event(event_type: str, message: str, brief_id: str = "", run_id: str = "") -> dict[str, Any]:
    ensure_runtime_dirs()
    event_id = f"event-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    payload = {
        "schema": "nogra.event.v1",
        "releaseVersion": RELEASE_VERSION,
        "eventId": event_id,
        "createdAt": now(),
        "workspaceId": workspace_label(),
        "eventType": event_type.strip() or "note",
        "message": message.strip(),
        "briefId": safe_id(brief_id, "brief") if brief_id.strip() else "",
        "runId": safe_id(run_id, "run") if run_id.strip() else "",
    }
    payload["redactions"] = secrets_in_payload({"event_type": payload["eventType"], "message": payload["message"]})
    append_jsonl(nogra_dir() / "events" / "events.jsonl", payload)
    return attach_local_writes(
        {
            "status": "ok",
            "eventId": event_id,
            "resourceUri": f"nogra://workspace/{workspace_label()}/pinboard/events",
        },
        [
            local_write_jsonl(
                local_workspace_events_path(),
                payload,
                "Persist Nogra workspace event locally.",
                idempotency_key=event_id,
            )
        ],
    )


def update_run(run_id: str, status: str, notes: str = "", brief_id: str = "") -> dict[str, Any]:
    ensure_runtime_dirs()
    cleaned_run_id = safe_id(run_id, "run")
    payload = {
        "schema": "nogra.run.update.v1",
        "releaseVersion": RELEASE_VERSION,
        "createdAt": now(),
        "workspaceId": workspace_label(),
        "runId": cleaned_run_id,
        "status": status.strip() or "updated",
        "notes": notes.strip(),
        "briefId": safe_id(brief_id, "brief") if brief_id.strip() else "",
    }
    event_id = f"run-update-{cleaned_run_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    payload["eventId"] = event_id
    payload["redactions"] = secrets_in_payload({"status": payload["status"], "notes": payload["notes"]})
    append_jsonl(nogra_dir() / "runs" / f"{cleaned_run_id}.jsonl", payload)
    return attach_local_writes(
        {
            "status": "ok",
            "runId": cleaned_run_id,
            "resourceUri": f"nogra://workspace/{workspace_label()}/runs/{cleaned_run_id}",
        },
        [
            local_write_jsonl(
                local_workspace_run_updates_path(cleaned_run_id),
                payload,
                "Persist Nogra workspace run update locally.",
                idempotency_key=event_id,
            )
        ],
    )


def recent_provider_handoffs(limit: int = 10) -> dict[str, Any]:
    receipts = [
        *sorted((nogra_dir() / "receipts").glob("provider-handoff-*.json"), reverse=True),
    ][:limit]
    items: list[dict[str, Any]] = []
    for receipt in receipts:
        try:
            payload = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items.append(
            {
                "handoffId": payload.get("handoffId", ""),
                "createdAt": payload.get("createdAt", ""),
                "status": payload.get("status", ""),
                "provider": payload.get("provider", payload.get("model", "")),
                "intent": payload.get("intent", payload.get("mode", "")),
                "surface": payload.get("surface", ""),
            }
        )
    return {"workspaceId": workspace_label(), "providerHandoffs": items}


def recent_runs(limit: int = 10) -> dict[str, Any]:
    runs_dir = nogra_dir() / "runs"
    if not runs_dir.is_dir():
        return {"workspaceId": workspace_label(), "runs": []}

    def mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    run_files = sorted(runs_dir.glob("*.jsonl"), key=mtime, reverse=True)[: max(0, limit)]
    runs: list[dict[str, Any]] = []
    for run_file in run_files:
        try:
            lines = run_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            runs.append(
                {
                    "runId": payload.get("runId", run_file.stem),
                    "status": payload.get("status", ""),
                    "updatedAt": payload.get("updatedAt", payload.get("createdAt", "")),
                    "briefId": payload.get("briefId", ""),
                    "notes": payload.get("notes", ""),
                }
            )
            break
    return {"workspaceId": workspace_label(), "runs": runs}


def recent_events(limit: int = 50) -> dict[str, Any]:
    event_file = nogra_dir() / "events" / "events.jsonl"
    if not event_file.is_file():
        return {"workspaceId": workspace_label(), "events": []}
    lines = event_file.read_text(encoding="utf-8").splitlines()[-limit:]
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {"workspaceId": workspace_label(), "events": events}


def self_test_payload() -> dict[str, Any]:
    root = nogra_dir()
    return {
        "registry": registry_payload(),
        "workspace": {
            "id": workspace_label(),
            "configured": root.exists(),
            "providers": (root / "providers.md").is_file(),
            "presets": (root / "presets").is_dir(),
            "providerHandoffTemplates": (root / "provider-handoff-templates").is_dir(),
        },
        "status": "ok",
    }


def build_mcp() -> Any:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.prompts import base
    from pydantic import Field

    fastmcp_options = {"log_level": os.environ.get("NOGRA_MCP_LOG_LEVEL", "ERROR")}
    if hosted_mode():
        fastmcp_options["host"] = os.environ.get("NOGRA_MCP_HOST", "0.0.0.0")
        # Vercel serverless instances cannot share FastMCP's in-memory HTTP
        # session map. Stateless mode prevents cross-instance requests from
        # failing with "Session not found" after a successful prior tool call.
        fastmcp_options["stateless_http"] = True
    mcp = FastMCP("Nogra MCP", **fastmcp_options)
    runtime = Runtime()

    @mcp.prompt(name="init", description="Bootstrap Nogra in this Claude Code workspace from the connected MCP server.")
    def init_prompt() -> list[Any]:
        return [base.UserMessage(init_prompt_text())]

    @mcp.resource("nogra://public/registry", mime_type="application/json")
    def public_registry() -> dict[str, Any]:
        return registry_payload()

    @mcp.resource("nogra://public/toolbank/claude-tools", mime_type="application/json")
    def claude_toolbank() -> dict[str, Any]:
        return read_package_json(PUBLIC_PACKAGE_JSON_RESOURCES["nogra://public/toolbank/claude-tools"])

    @mcp.resource("nogra://public/schemas/provider-handoff-v1", mime_type="application/json")
    def provider_handoff_schema() -> dict[str, Any]:
        return {
            "schema": "nogra.provider.handoff.v1",
            "releaseVersion": RELEASE_VERSION,
            "required": ["provider", "prompt"],
            "properties": {
                "provider": "string",
                "prompt": "string",
                "context": "string",
                "intent": ["consult", "review", "delegate", "gate"],
                "surface": ["pass-through", "manager-summary", "conditional-loud"],
            },
        }

    @mcp.resource("nogra://public/schemas/init-bundle-v1", mime_type="application/json")
    def init_bundle_schema() -> dict[str, Any]:
        return read_package_json(PUBLIC_PACKAGE_JSON_RESOURCES["nogra://public/schemas/init-bundle-v1"])

    @mcp.resource("nogra://public/schemas/dispatch-handoff-v1", mime_type="application/json")
    def dispatch_handoff_schema() -> dict[str, Any]:
        return read_package_json(PUBLIC_PACKAGE_JSON_RESOURCES["nogra://public/schemas/dispatch-handoff-v1"])

    @mcp.resource("nogra://public/schemas/brief-v1", mime_type="application/json")
    def brief_schema() -> dict[str, Any]:
        return read_package_json(PUBLIC_PACKAGE_JSON_RESOURCES["nogra://public/schemas/brief-v1"])

    @mcp.resource("nogra://public/schemas/run-v1", mime_type="application/json")
    def run_schema() -> dict[str, Any]:
        return read_package_json(PUBLIC_PACKAGE_JSON_RESOURCES["nogra://public/schemas/run-v1"])

    @mcp.resource("nogra://public/schemas/run-event-v1", mime_type="application/json")
    def run_event_schema() -> dict[str, Any]:
        return read_package_json(PUBLIC_PACKAGE_JSON_RESOURCES["nogra://public/schemas/run-event-v1"])

    @mcp.resource("nogra://public/templates/brief-v1", mime_type="text/markdown")
    def brief_template() -> str:
        return read_package_text(PUBLIC_PACKAGE_TEXT_RESOURCES["nogra://public/templates/brief-v1"])

    @mcp.resource("nogra://public/templates/dispatch-handoff-v1", mime_type="application/json")
    def dispatch_handoff_template() -> dict[str, Any]:
        return read_package_json(PUBLIC_PACKAGE_JSON_RESOURCES["nogra://public/templates/dispatch-handoff-v1"])

    @mcp.resource("nogra://public/templates/run-v1", mime_type="application/json")
    def run_template() -> dict[str, Any]:
        return read_package_json(PUBLIC_PACKAGE_JSON_RESOURCES["nogra://public/templates/run-v1"])

    @mcp.resource("nogra://public/templates/run-event-v1", mime_type="application/json")
    def run_event_template() -> dict[str, Any]:
        return read_package_json(PUBLIC_PACKAGE_JSON_RESOURCES["nogra://public/templates/run-event-v1"])

    @mcp.resource("nogra://public/examples/brief-v1", mime_type="text/markdown")
    def brief_example() -> str:
        return read_package_text(PUBLIC_PACKAGE_TEXT_RESOURCES["nogra://public/examples/brief-v1"])

    @mcp.resource("nogra://public/examples/dispatch-handoff-v1", mime_type="application/json")
    def dispatch_handoff_example() -> dict[str, Any]:
        return read_package_json(PUBLIC_PACKAGE_JSON_RESOURCES["nogra://public/examples/dispatch-handoff-v1"])

    @mcp.resource("nogra://public/examples/run-v1", mime_type="application/json")
    def run_example() -> dict[str, Any]:
        return read_package_json(PUBLIC_PACKAGE_JSON_RESOURCES["nogra://public/examples/run-v1"])

    @mcp.resource("nogra://public/examples/run-event-v1", mime_type="application/json")
    def run_event_example() -> dict[str, Any]:
        return read_package_json(PUBLIC_PACKAGE_JSON_RESOURCES["nogra://public/examples/run-event-v1"])

    @mcp.resource(f"nogra://workspace/{workspace_label()}/provider-handoffs/recent", mime_type="application/json")
    def provider_handoffs_recent() -> dict[str, Any]:
        return recent_provider_handoffs()

    @mcp.resource(f"nogra://workspace/{workspace_label()}/pinboard/events", mime_type="application/json")
    def pinboard_events() -> dict[str, Any]:
        return recent_events()

    @mcp.resource(f"nogra://workspace/{workspace_label()}/runs/recent", mime_type="application/json")
    def runs_recent() -> dict[str, Any]:
        return recent_runs()

    @mcp.resource(f"nogra://workspace/{workspace_label()}/briefs/recent", mime_type="application/json")
    def briefs_recent() -> dict[str, Any]:
        return recent_briefs(limit=20)

    @mcp.resource(f"nogra://workspace/{workspace_label()}/transport/runs/recent", mime_type="application/json")
    def transport_runs_recent() -> dict[str, Any]:
        return transport_recent_runs(limit=20)

    @mcp.resource(f"nogra://workspace/{workspace_label()}/transport/events/recent", mime_type="application/json")
    def transport_events_recent() -> dict[str, Any]:
        return transport_read_events(limit=80)

    @mcp.tool(name="init")
    def tool_init(
        workspace_name: str = Field(
            default="",
            description="Optional local workspace display name. Empty uses local. The user may ask for this as 'run Nogra init' or '/nogra init'.",
        ),
        mode: str = Field(
            default="standalone",
            description="Init bundle mode. Use standalone for MCP-only installs; use plugin when the Nogra plugin already provides commands, skills and MCP configuration.",
        ),
    ) -> dict[str, Any]:
        """Return the public Nogra init bundle for Claude Code to write locally.

        This tool is the server-side source for Nogra workspace files. It does not write files and does not
        execute commands. The caller's Claude Code client should write each returned file into the user's chosen
        workspace path using the file writePolicy. Newer clients should use the returned installPlan
        for phase-grouped writes and a quieter installation summary.

        When to use:
        - Initialize Nogra in a customer workspace after the hosted MCP server has been added.
        - Respond to user requests such as "run Nogra init" or "/nogra init".
        - Retrieve the current public-safe Nogra workspace methodology bundle.
        - Use mode=plugin when the Nogra plugin is installed; plugin mode returns only workspace bootstrap files,
          not plugin-owned commands or skills.

        When NOT to use:
        - Do not treat this as an installer that can write to the user's filesystem.
        - Do not overwrite files marked ask_before_overwrite without asking the user.
        - Do not expect this to configure provider auth, run local commands, or perform workspace execution.

        Examples:
        >>> init(workspace_name="Acme App")
        {"schema": "nogra.init.bundle.v1", "releaseVersion": "v1.0.0", "status": "ready", "writeMode": "client_writes_files", "files": [...]}
        >>> init(workspace_name="Acme App", mode="plugin")
        {"schema": "nogra.init.bundle.v1", "releaseVersion": "v1.0.0", "initMode": "plugin", "files": [...]}
        """
        return init_bundle(workspace_name=workspace_name, mode=mode)

    @mcp.tool(name="handoff_contract")
    def tool_handoff_contract(
        kind: str = Field(default="", description="Ephemeral Nogra handoff kind to fetch. Supported values: executor or verifier."),
        role: str = Field(default="", description="Deprecated alias for kind. Kept only so older beta prompts fail softly during migration."),
    ) -> dict[str, Any]:
        """Return an ephemeral Nogra handoff contract.

        Nogra execution roles are not installed as persistent Claude Code project agents. The Manager fetches a
        handoff contract at a dispatch or verification boundary, then spawns Claude Code's built-in general-purpose
        subagent with the returned prompt plus the approved brief, run id, scope and evidence contract.
        Manager must not implement the approved scope inline. If the client cannot spawn the subagent, stop and
        surface the missing primitive instead of offering a fallback.

        When to use:
        - After a brief is approved and a dispatch receipt/run id exists, fetch kind=executor before spawning the run agent.
        - Before independent evidence checks, fetch kind=verifier before spawning a disposable verifier agent.

        When NOT to use:
        - Do not call repeatedly during normal lifecycle logging.
        - Do not persist the returned prompt as a .claude/agents file.
        - Do not use this as execution approval; the user-approved brief and dispatch receipt remain the authority.
        - Do not use this to justify inline Manager execution.

        Examples:
        >>> handoff_contract("executor")
        {"schema": "nogra.handoff.contract.v1", "status": "ready", "kind": "executor", "targetSubagent": {"type": "general-purpose", ...}}
        """
        return handoff_contract_payload(kind=kind or role)

    @mcp.tool(name="optional_feature_bundle")
    def tool_optional_feature_bundle(
        feature_id: str = Field(description="Optional Nogra feature id to download after user opt-in, such as local-pinboard-renderer."),
        workspace_name: str = Field(default="", description="Optional local workspace display name used for templated optional feature files."),
    ) -> dict[str, Any]:
        """Return an optional Nogra feature bundle for Claude Code to write locally after user opt-in.

        This tool is download-on-demand. It does not write files, start local processes or change the workspace.
        The caller's Claude Code client should write returned files only after the user explicitly asks for the
        optional feature, preserving each returned writePolicy.

        When to use:
        - Install an optional Nogra feature advertised by init, such as the local pinboard renderer.
        - Re-download an optional feature file after the user asks to repair or update it.

        When NOT to use:
        - Do not call during default /nogra init unless the user opted into that feature.
        - Do not auto-start any local process after writing optional files.

        Examples:
        >>> optional_feature_bundle("local-pinboard-renderer")
        {"schema": "nogra.optional_feature.bundle.v1", "status": "ready", "files": [...]}
        """
        return optional_feature_bundle(feature_id=feature_id, workspace_name=workspace_name)

    @mcp.tool(name="registry")
    def tool_registry() -> dict[str, Any]:
        """Read the public Nogra MCP V1 registry.

        Returns the public registry payload for the configured workspace, including public tool names, resource
        URIs, boundary flags, extension metadata, and the workspace substrate paths that a caller may inspect.

        When to use:
        - Discover what the public Nogra MCP exposes before choosing another tool.
        - Check whether extensions are enabled and which tools/resources are visible in this workspace.

        When NOT to use:
        - Do not use this to read the contents of resources; fetch the resource URI directly instead.
        - Do not use this to create provider handoff receipts, post events, or update runs.

        Examples:
        >>> registry()
        {"name": "nogra-mcp", "version": "v1.0.0", "status": "v1-local-validation", "tools": [...], ...}
        """
        return registry_payload()

    @mcp.tool(name="brief_contract")
    def tool_brief_contract(
        workspace_id: str = Field(default="", description="Optional local workspaceId from .nogra/config.json. Empty uses local."),
    ) -> dict[str, Any]:
        """Read the public Nogra brief contract.

        Returns the fields, markdown anchors, default return policy and public resources needed to draft a
        `nogra.brief.v1` brief before calling validation or save tools.

        When to use:
        - Draft a Nogra brief from user intent without guessing field names or required sections.
        - Check how markdown sections map into the structured brief object.
        - Confirm that response length policy is a return policy, not a brief length cap.

        When NOT to use:
        - Do not use this as execution approval.
        - Do not dispatch work from this contract alone; save/promote/dispatch gates still apply.

        Examples:
        >>> brief_contract(workspace_id="acme-app")
        {"schema": "nogra.brief.contract.v1", "briefSchema": "nogra.brief.v1", "requiredFields": [...]}
        """
        return brief_contract_payload(workspace_id=workspace_id)

    @mcp.tool(name="provider_handoff")
    def tool_provider_handoff(
        provider: str = Field(default="", description="Provider label to place in the handoff receipt, such as codex or gemini."),
        prompt: str = Field(default="", description="Question or task text to render into the provider handoff prompt."),
        context: str = Field(default="", description="Optional surrounding context rendered into the provider handoff prompt."),
        intent: str = Field(default="consult", description="Provider intent label such as consult, review, delegate or gate."),
        surface: str = Field(default="pass-through", description="Suggested surface mode: pass-through, manager-summary or conditional-loud."),
        model: str = Field(default="", description="Deprecated alias for provider. Kept only so older beta prompts fail softly during migration."),
        mode: str = Field(default="", description="Deprecated alias for intent. Kept only so older beta prompts fail softly during migration."),
    ) -> dict[str, Any]:
        """Create a dry-run provider handoff receipt.

        Renders the configured provider handoff template, redacts secret-shaped text, stores the
        hosted receipt, and returns the handoff id plus localWrites guidance for the caller-owned
        `.nogra/` receipt copy.
        This public V1 tool does not call a live provider.

        When to use:
        - Prepare a redacted provider handoff before handing work to another model or reviewer.
        - Validate how a prompt, context, and mode will render without making an external model call.

        When NOT to use:
        - Do not use this when you need an actual provider response; providerCall.attempted is always false.
        - Do not use this for run tracking or pinboard activity; use event/run tools for that.

        Examples:
        >>> provider_handoff(provider="codex", prompt="Review this brief", context="Scope: docs only", intent="review")
        {"status": "dry_run", "handoffId": "provider-handoff-...", "provider": "codex", "intent": "review", ...}
        """
        return provider_handoff(provider=provider or model, prompt=prompt, context=context, intent=intent or mode, surface=surface)

    @mcp.tool(name="provider_handoff_read")
    def tool_provider_handoff_read(
        handoff_id: str = Field(default="", description="Provider handoff id returned by provider_handoff, normally shaped like provider-handoff-YYYYMMDDHHMMSS-xxxxxxxx."),
        consult_id: str = Field(default="", description="Deprecated alias for handoff_id. Kept only so older beta prompts fail softly during migration."),
    ) -> dict[str, Any]:
        """Read the redacted rendered prompt for a stored provider handoff receipt.

        Looks up a previously written provider handoff receipt by id, validates the id shape, reads the receipt JSON from the
        workspace .nogra receipts directory, and returns the redacted rendered prompt plus any redaction labels.

        When to use:
        - Inspect the exact redacted prompt that was stored for a previous dry-run provider handoff.
        - Recover prompt text by handoff id without re-rendering or creating a new receipt.

        When NOT to use:
        - Do not use this before creating a provider handoff receipt; missing ids return a missing status.
        - Do not use this for unredacted secrets or raw provider prompts; the stored field is redacted.

        Examples:
        >>> provider_handoff_read("provider-handoff-20260504120000-abc123ef")
        {"status": "ok", "handoffId": "provider-handoff-20260504120000-abc123ef", "renderedPromptRedacted": "...", "redactions": []}
        """
        return provider_handoff_read(handoff_id or consult_id)

    @mcp.tool(name="redact_text")
    def tool_redact_text(
        text: str = Field(description="Text to scan and return with secret-shaped matches replaced by [REDACTED]."),
    ) -> dict[str, Any]:
        """Redact secret-shaped text without writing a record.

        Applies the public Nogra secret-pattern filter to caller-provided text and returns the redacted text plus
        category labels for every detected secret-shaped match.

        When to use:
        - Preview which secret-pattern labels Nogra would detect in text before writing it to workspace substrate.
        - Build caller-side masking or display logic from the same labels used by write-time annotations.

        When NOT to use:
        - Do not use this as destructive storage; write-tools annotate records and keep original text.
        - Do not use this for provider handoff receipts; provider_handoff already redacts rendered prompts.

        Examples:
        >>> redact_text("token=sk_test_abcdefghij1234567890")
        {"redacted": "token=[REDACTED]", "redactions": ["api-key-shape"]}
        """
        redacted, redactions = redact(text)
        return {"redacted": redacted, "redactions": redactions}

    @mcp.tool(name="post_event")
    def tool_post_event(
        event_type: str = Field(description="Short event category. Blank input is stored as note."),
        message: str = Field(description="Human-readable event message to append to the workspace event log."),
        brief_id: str = Field(default="", description="Optional brief id to associate with the event; sanitized before storage."),
        run_id: str = Field(default="", description="Optional run id to associate with the event; sanitized before storage."),
    ) -> dict[str, Any]:
        """Append a workspace activity event.

        Writes one JSONL event into the configured workspace .nogra events log with schema, id, timestamp,
        workspace id, event type, message, and optional brief/run links, then returns the event id and events
        resource URI.

        When to use:
        - Record a visible workspace activity note for pinboard or workflow surfaces.
        - Attach a lightweight event to a brief id, run id, or both.

        When NOT to use:
        - Do not use this for run status history; use update_run for run updates.
        - Do not use this to store large reports or artifacts; it appends a compact event message.

        Examples:
        >>> post_event("dispatch", "Queued analytics audit", brief_id="brief-123", run_id="run-456")
        {"status": "ok", "eventId": "event-...", "resourceUri": "nogra://workspace/local/pinboard/events"}
        """
        return post_event(event_type=event_type, message=message, brief_id=brief_id, run_id=run_id)

    @mcp.tool(name="recent_events")
    def tool_recent_events(
        limit: int = Field(default=50, description="Maximum number of recent workspace events to return."),
    ) -> dict[str, Any]:
        """Read recent workspace activity events.

        Returns recent JSONL event entries from the configured workspace .nogra events log.

        When to use:
        - Inspect recent public workspace activity recorded through post_event.
        - Build caller-driven views over the local event substrate without reading resources directly.

        When NOT to use:
        - Do not use this for run status history; use recent_runs for run updates.
        - Do not use this to append events; use post_event for writes.

        Examples:
        >>> recent_events(limit=20)
        {"workspaceId": "local", "events": [...]}
        """
        return recent_events(limit=limit)

    @mcp.tool(name="update_run")
    def tool_update_run(
        run_id: str = Field(description="Run id to update; sanitized before storage and used as the run JSONL filename."),
        status: str = Field(description="Run status text to append. Blank input is stored as updated."),
        notes: str = Field(default="", description="Optional human-readable notes for this run status update."),
        brief_id: str = Field(default="", description="Optional brief id to associate with the run update; sanitized before storage."),
    ) -> dict[str, Any]:
        """Append a workspace run status update.

        Writes one JSONL status entry under the configured workspace .nogra runs directory for the sanitized run id,
        including schema, timestamp, workspace id, status, notes, and optional brief id, then returns the run resource
        URI.

        When to use:
        - Record that a run moved to a new status such as queued, running, complete, blocked, or failed.
        - Attach notes to a run timeline without changing any external transport state.

        When NOT to use:
        - Do not use this for general activity notes; use post_event for non-run events.
        - Do not use this to dispatch work or submit report artifacts; this only appends a public run update.

        Examples:
        >>> update_run("run-456", "running", notes="Audit started", brief_id="brief-123")
        {"status": "ok", "runId": "run-456", "resourceUri": "nogra://workspace/local/runs/run-456"}
        """
        return update_run(run_id=run_id, status=status, notes=notes, brief_id=brief_id)

    @mcp.tool(name="recent_runs")
    def tool_recent_runs(
        limit: int = Field(default=10, description="Maximum number of recent run update files to inspect."),
    ) -> dict[str, Any]:
        """Read recent workspace run updates.

        Returns the latest valid JSONL update from recent run files under the configured workspace .nogra runs
        directory, including run id, status, timestamp, brief id, and notes.

        When to use:
        - Inspect recent run status updates recorded through update_run.
        - Build caller-driven views over the local run substrate without reading resources directly.

        When NOT to use:
        - Do not use this to append run status; use update_run for writes.
        - Do not use this for general activity events; use recent_events for event history.

        Examples:
        >>> recent_runs(limit=10)
        {"workspaceId": "local", "runs": [...]}
        """
        return recent_runs(limit=limit)

    @mcp.tool(name="brief_save")
    def tool_brief_save(
        payload: str | dict[str, Any] = Field(description="Brief payload as markdown, JSON string, or structured object."),
        brief_id: str = Field(default="", description="Optional existing or explicit brief id to save as a draft."),
        source: str = Field(default="", description="Optional source label stored in public brief metadata."),
    ) -> dict[str, Any]:
        """Save a public Nogra brief draft.

        Parses markdown or structured input, normalizes it to the public brief schema, validates it, and returns
        localWrites for the caller-owned `.nogra/` draft store. In hosted mode, this tool does not rely on persistent
        server-side draft storage.

        When to use:
        - Create or update a caller-owned brief draft through the MCP tool interface.
        - Convert a markdown brief into public structured brief JSON before promotion.

        When NOT to use:
        - Do not use this to mark a brief ready; use brief_promote for promotion.
        - Do not use this for run updates or events; use the run/event tools for those substrates.

        Examples:
        >>> brief_save({"title": "Import audit", ...}, source="cli")
        {"schema": "nogra.brief.v1", "releaseVersion": "v1.0.0", "briefId": "brief-...", "status": "draft", "path": ".nogra/briefs/drafts/brief-....json", ...}
        """
        input_payload = parse_draft_input(payload)
        if brief_id.strip():
            input_payload["briefId"] = brief_id
        if source.strip():
            metadata = input_payload.get("metadata") if isinstance(input_payload.get("metadata"), dict) else {}
            input_payload["metadata"] = {**metadata, "source": source.strip()}
        return save_draft_brief(input_payload)

    @mcp.tool(name="brief_validate")
    def tool_brief_validate(
        payload: str | dict[str, Any] = Field(description="Brief payload as markdown, JSON string, or structured object."),
    ) -> dict[str, Any]:
        """Validate a public Nogra brief payload without persisting it.

        Parses and normalizes the supplied payload, then runs the public brief schema checks. Invalid input is returned
        as structured errors rather than raised to the caller.

        When to use:
        - Check whether a draft can be saved or promoted before writing it.
        - Inspect the normalized public brief shape produced from markdown.

        When NOT to use:
        - Do not use this to persist a draft; use brief_save for writes.
        - Do not use this to read stored briefs; use brief_read or recent_briefs.

        Examples:
        >>> brief_validate({"title": "Import audit", ...})
        {"valid": true, "errors": [], "normalized": {...}}
        """
        normalized: dict[str, Any] | None = None
        try:
            normalized = normalize_brief(parse_draft_input(payload))
            validate_brief(normalized)
            return {"valid": True, "errors": [], "normalized": normalized}
        except Exception as exc:
            return {"valid": False, "errors": [str(exc)], "normalized": normalized}

    @mcp.tool(name="brief_promote")
    def tool_brief_promote(
        brief_id: str = Field(default="", description="Brief draft id to promote, normally shaped like brief-<slug>-<date>-<hex>."),
        payload: str | dict[str, Any] = Field(default="", description="Optional inline brief payload. Required in hosted/stateless mode when promoting customer-local drafts."),
    ) -> dict[str, Any]:
        """Promote a saved public Nogra brief draft.

        Marks a draft ready, validates it, renders markdown, and returns localWrites for the promoted brief artifact.
        Hosted/plugin mode should pass the inline brief payload because the customer's local `.nogra/` store is the
        authority.

        When to use:
        - Convert a valid draft payload into a ready markdown brief artifact.
        - Produce a stable promoted brief path while keeping draft JSON readable.

        When NOT to use:
        - In hosted/plugin mode, do not rely on server-side draft state; pass the local draft payload inline.
        - Do not use this to edit a draft; use brief_save for updates.

        Examples:
        >>> brief_promote("brief-import-audit-2026-05-06-a1b2c3", payload={...})
        {"draft": {...}, "brief": {...}, "path": ".nogra/briefs/BRIEF-import-audit-2026-05-06.md"}
        """
        has_payload = isinstance(payload, dict) and bool(payload) or isinstance(payload, str) and bool(payload.strip())
        if has_payload:
            try:
                return promote_brief_payload(payload, brief_id=brief_id)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return {
                    "status": "invalid",
                    "mode": "hosted-stateless" if hosted_mode() else "inline",
                    "briefId": clean_inline(brief_id),
                    "error": str(exc),
                    "nextOwner": "ManagerClaude",
                }
        if not brief_id.strip():
            return {
                "status": "invalid",
                "mode": "hosted-stateless" if hosted_mode() else "local",
                "error": "brief_id or inline payload required",
                "nextOwner": "ManagerClaude",
            }
        return promote_brief_draft(brief_id)

    @mcp.tool(name="brief_read")
    def tool_brief_read(
        brief_id: str = Field(description="Brief id to read from draft storage first, then promoted markdown fallback."),
    ) -> dict[str, Any]:
        """Read a public Nogra brief by id.

        Reads draft JSON first and falls back to matching promoted markdown when no draft exists.

        When to use:
        - Retrieve a saved or promoted public brief through tools.
        - Verify the current status and path for a known brief id.

        When NOT to use:
        - Do not use this to list recent briefs; use recent_briefs.
        - Do not use this to validate arbitrary unsaved input; use brief_validate.

        Examples:
        >>> brief_read("brief-import-audit-2026-05-06-a1b2c3")
        {"status": "ok", "brief": {...}, "path": ".nogra/briefs/BRIEF-import-audit-2026-05-06.md"}
        """
        return brief_read(brief_id)

    @mcp.tool(name="recent_briefs")
    def tool_recent_briefs(
        limit: int = Field(default=10, description="Maximum number of recent draft and promoted briefs to return."),
    ) -> dict[str, Any]:
        """List recent public Nogra briefs.

        Returns recent draft JSON and promoted markdown briefs from the configured workspace brief substrate.

        When to use:
        - Build caller-driven brief lists through tools.
        - Inspect recent draft and promoted brief activity without reading resource URIs.

        When NOT to use:
        - Do not use this to read a specific brief body; use brief_read.
        - Do not use this to create or promote briefs; use the write lifecycle tools.

        Examples:
        >>> recent_briefs(limit=10)
        {"workspaceId": "local", "briefs": [...]}
        """
        return recent_briefs(limit=limit)

    @mcp.tool(name="transport_register")
    def tool_transport_register(
        target: str = Field(description="Free-form runtime target label supplied by the caller."),
        brief_id: str = Field(default="", description="Optional public brief id this run is associated with."),
        metadata: dict[str, Any] = Field(default_factory=dict, description="Optional caller-owned metadata for this run."),
    ) -> dict[str, Any]:
        """Register a public transport run.

        Creates a state-only run record, allocates report/output/log artifact paths under the workspace transport
        substrate, persists state atomically, and appends a transport event.

        When to use:
        - Start tracking caller-owned work through public transport state.
        - Allocate artifact paths before an external runtime begins work.

        When NOT to use:
        - Do not use this to execute work; public transport is state-only.
        - Do not use this for lightweight event logging; use post_event for that.

        Examples:
        >>> transport_register("import-audit", brief_id="brief-123")
        {"schema": "nogra.transport.run.v1", "runId": "transport-...", "status": "queued", ...}
        """
        return transport_register_run(target=target, brief_id=brief_id, metadata=metadata)

    @mcp.tool(name="transport_update")
    def tool_transport_update(
        run_id: str = Field(description="Transport run id to update."),
        status: str = Field(default="", description="Optional status transition."),
        phase: str = Field(default="", description="Optional phase transition."),
        notes: str = Field(default="", description="Optional human-readable notes."),
        error: str = Field(default="", description="Optional error text."),
        summary: str = Field(default="", description="Optional short result summary."),
    ) -> dict[str, Any]:
        """Update a public transport run.

        Applies partial status, phase, notes, error, or summary updates to an existing run and appends an event with
        the changed fields.

        When to use:
        - Move a run from queued to running, returned, failed, or another public lifecycle state.
        - Attach status notes from an external runtime.

        When NOT to use:
        - Do not use this to write report artifacts; use transport_submit_report.
        - Do not use this for brief draft lifecycle changes.

        Examples:
        >>> transport_update("transport-20260506120000-a1b2c3d4", status="running")
        {"runId": "transport-...", "status": "running", "phase": "running", ...}
        """
        if hosted_mode():
            return nogra_runtime.hosted_local_ledger_guidance("transport_update", run_id)
        return transport_update_run(run_id=run_id, status=status, phase=phase, notes=notes, error=error, summary=summary)

    @mcp.tool(name="transport_abort")
    def tool_transport_abort(
        run_id: str = Field(description="Transport run id to cancel."),
        reason: str = Field(default="", description="Human-readable reason, such as user stopped the executor."),
        summary: str = Field(default="", description="Short cancellation summary for the run timeline."),
        current_run: dict[str, Any] = Field(default_factory=dict, description="Hosted/plugin mode only: current local run record so Nogra can return a complete replacement localWrite."),
    ) -> dict[str, Any]:
        """Abort or cancel a Transport run.

        Use when the user stops an executor, cancels a run, or a dispatched run
        must be marked cancelled without pretending verification completed.

        In hosted/plugin mode the customer's `.nogra/` ledger is local. Pass
        current_run when available so this tool can return exact localWrites for
        the run record and cancellation event.
        """
        resolved_run_id = clean_inline(run_id)
        if hosted_mode():
            try:
                transport_safe_run_id(resolved_run_id)
            except ValueError as exc:
                return {"generatedAt": now(), "status": "invalid", "mode": "hosted", "tool": "transport_abort", "runId": resolved_run_id, "error": str(exc)}
            reason_clean = clean_inline(reason) or "User cancelled the run before completion."
            summary_clean = clean_inline(summary) or "Run cancelled by user before completion."
            payload: dict[str, Any] = {
                "generatedAt": now(),
                "status": "local_required",
                "mode": "hosted",
                "tool": "transport_abort",
                "runId": resolved_run_id,
                "abortedStatus": "cancelled",
                "requiredLocalRunMerge": {
                    "status": "cancelled",
                    "phase": "returned",
                    "updatedAt": "current ISO timestamp",
                    "cancelledAt": "current ISO timestamp",
                    "completedAt": "current ISO timestamp",
                    "notes": reason_clean,
                    "summary": summary_clean,
                },
                "localPersistence": {
                    "run": f".nogra/transport/runs/{resolved_run_id}.json",
                    "events": ".nogra/transport/events.jsonl",
                },
                "managerInstruction": "After aborting, stop execution and return a short cancelled/partial report. Do not continue verification, screenshots, browser opening or implementation unless the user asks.",
                "nextOwner": "ManagerClaude",
            }
            base_record = current_run if isinstance(current_run, dict) and current_run else {}
            if base_record:
                base_run_id = clean_inline(base_record.get("runId"))
                if base_run_id and base_run_id != resolved_run_id:
                    return {"generatedAt": now(), "status": "invalid", "mode": "hosted", "tool": "transport_abort", "runId": resolved_run_id, "error": "current_run.runId does not match run_id"}
                record = {**base_record, "runId": resolved_run_id}
                public, event = transport_abort_record(record, reason=reason_clean, summary=summary_clean)
                payload.update({"status": "ready", "run": public})
                return attach_local_writes(
                    payload,
                    [
                        local_transport_run_write(public, "Mark hosted/plugin transport run cancelled locally."),
                        local_transport_event_write(event, "Record hosted/plugin transport run cancellation locally."),
                    ],
                )
            event = transport_event_record(
                resolved_run_id,
                "transport_run_cancelled",
                status="cancelled",
                phase="returned",
                reason=reason_clean,
                summary=summary_clean,
                nextOwner="ManagerClaude",
            )
            return attach_local_writes(
                payload,
                [local_transport_event_write(event, "Record hosted/plugin transport run cancellation locally.")],
            )
        return transport_abort_run(run_id=run_id, reason=reason, summary=summary)

    @mcp.tool(name="dispatch_handoff")
    def tool_dispatch_handoff(
        brief_id: str = Field(description="Public brief id to embed into the dispatch handoff."),
        target: str = Field(description="Free-form caller-defined runtime target."),
        parent_run_id: str = Field(default="", description="Optional parent transport run id for caller linkage."),
        intent_id: str = Field(default="", description="Optional caller-owned intent id."),
        doctrine_refs: list[str] = Field(default_factory=list, description="Optional workspace-relative doctrine file refs to embed."),
        metadata: dict[str, Any] = Field(default_factory=dict, description="Optional caller-owned handoff metadata."),
    ) -> dict[str, Any]:
        """Build a public dispatch handoff.

        Bundles an existing public brief, caller-defined target, optional linkage, optional doctrine text, and metadata
        into a self-contained handoff for a caller-owned runtime. In plugin mode, this handoff is material for
        a customer-side ephemeral subagent; it is not permission for Manager to execute the scope inline.

        When to use:
        - Prepare a saved public brief for handoff to a runtime without requiring another MCP read.
        - Include small workspace-local reference files beside the embedded brief content.
        - Support a plugin-mode Manager -> ephemeral executor crossing when dispatch handoff material is useful.

        When NOT to use:
        - Do not use this to execute work; it only builds a handoff.
        - Do not use this without a saved brief; use transport_register directly for brief-less tracking.
        - Do not use this as a fallback after subagent spawning fails.

        Examples:
        >>> dispatch_handoff("brief-import-audit-2026-05-06-a1b2c3", "audit-job")
        {"schema": "nogra.dispatch.handoff.v1", "target": "audit-job", "brief": {...}, ...}
        """
        return build_dispatch_handoff(
            brief_id=brief_id,
            target=target,
            parent_run_id=parent_run_id,
            intent_id=intent_id,
            doctrine_refs=doctrine_refs,
            metadata=metadata,
        )

    register_extensions(mcp, runtime)

    return mcp


def run_stdio() -> None:
    build_mcp().run(transport="stdio")


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Canonical Nogra MCP server")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--inventory", action="store_true")
    parser.add_argument("--dry-run-provider-handoff", default="")
    parser.add_argument("--provider", default="")
    parser.add_argument("--intent", default="consult")
    parser.add_argument("--context", default="")
    parser.add_argument("--show-provider-handoff", default="")
    args = parser.parse_args(argv)

    if args.self_test:
        print_json(self_test_payload())
        return 0
    if args.inventory:
        print_json(inventory_payload())
        return 0
    handoff_prompt = args.dry_run_provider_handoff
    if handoff_prompt:
        print_json(
            provider_handoff(
                provider=args.provider or "codex",
                prompt=handoff_prompt,
                context=args.context,
                intent=args.intent or "consult",
            )
        )
        return 0
    if args.show_provider_handoff:
        print_json(provider_handoff_read(args.show_provider_handoff))
        return 0

    run_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
