from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import runtime as nogra_runtime, runtime_server


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


def reference_file(name: str) -> Path:
    return repo_root() / "manager" / "reference" / name


def read_reference(name: str) -> str:
    path = reference_file(name)
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def codex_tool_names() -> list[str]:
    return [
        "codex_fresh_eyes_packet",
        "codex_fresh_eyes",
        "codex_dispatch_packet",
        "codex_dispatch",
    ]


def private_tool_names() -> list[str]:
    return [
        "y26_private_registry",
        "y26_role_graph",
        "y26_brief_template",
        "y26_manager_output_shapes",
        "y26_workflow_spine",
        *codex_tool_names(),
    ]


def extension_metadata() -> dict[str, Any]:
    return {
        "name": "y26-private-module",
        "version": "0.1.0",
        "visibility": "private",
        "status": "ready",
        "tools": private_tool_names(),
        "resources": [
            "nogra://workspace/y26-private/private/role-graph",
            "nogra://workspace/y26-private/private/brief-template",
            "nogra://workspace/y26-private/private/manager-output-shapes",
            "nogra://workspace/y26-private/private/workflow-spine",
        ],
        "boundary": "Y26-private doctrine readers and Patti-local Codex tools.",
        "module": "nogra_mcp.y26_private",
    }


def load_runtime_module() -> Any:
    root = repo_root()
    os.environ.setdefault("NOGRA_ROOT", str(root))
    os.environ.setdefault("Y26_ROOT", str(root))
    return runtime_server


def role_graph_payload(runtime: Any) -> dict[str, Any]:
    return {
        "schema": "y26.role_graph.v0",
        "workspaceId": runtime.workspace_id,
        "visibility": "private",
        "sourceRefs": [
            "manager/reference/role-boundaries.md",
            "manager/reference/codex-is-the-bridge.md",
            "manager/reference/manager-boot-context.md",
            "manager/reference/direct-mode-safety.md",
        ],
        "flow": [
            "CEO",
            "Chat Manager",
            "Transport/Orchestrator",
            "Codex PM",
            "Scribe/Agent",
            "Verify/Return",
            "CEO",
        ],
        "roles": [
            {
                "id": "ceo",
                "tier": 1,
                "title": "CEO",
                "authority": "intent, priority, GO/NO-GO, interrupt, final trust",
            },
            {
                "id": "chat_manager",
                "tier": 2,
                "title": "Chat Manager",
                "authority": "dialogue, scope, judgment, evidence-preserving surface upward; direct-mode hands-on only after explicit CEO approval",
            },
            {
                "id": "transport_orchestrator",
                "tier": 3,
                "title": "Transport / Orchestrator",
                "authority": "routing, packet preservation, run pointers, no judgment theft",
            },
            {
                "id": "codex_pm",
                "tier": 4,
                "title": "Codex PM",
                "authority": "implementation shape, brief gate, technical verification",
            },
            {
                "id": "scribe",
                "tier": "5a",
                "title": "Scribe / Transport Writer",
                "authority": "brief/report artifact writing from PM spec",
            },
            {
                "id": "agent",
                "tier": "5b",
                "title": "Agent",
                "authority": "bounded execution inside approved brief and file scope",
            },
            {
                "id": "canvas",
                "tier": 6,
                "title": "Canvas / Observability",
                "authority": "read-only flow, capacity, health and evidence-level visibility",
            },
            {
                "id": "return_path",
                "tier": 7,
                "title": "Return Path",
                "authority": "compress without upgrading evidence",
            },
        ],
    }


def brief_template_payload(runtime: Any) -> dict[str, Any]:
    return {
        "schema": "y26.brief_template.v0",
        "workspaceId": runtime.workspace_id,
        "visibility": "private",
        "sourceRef": "manager/reference/BRIEF-template.md",
        "requiredSections": [
            "intent",
            "context_handoff",
            "decisions",
            "rejected",
            "known_gaps",
            "scope",
            "files",
            "stop_criteria",
            "success_criteria",
            "max_output",
        ],
        "fieldContract": [
            {"field": "intent", "markdown": "## Intent", "shape": "non-empty text"},
            {"field": "contextHandoff", "markdown": "## Context handoff", "shape": "non-empty text"},
            {"field": "scope.in", "markdown": "## Scope", "shape": "list or prose"},
            {"field": "scope.files", "markdown": "## Filer", "shape": "optional list of paths"},
            {"field": "successCriteria", "markdown": "## Success criteria", "shape": "non-empty list"},
            {"field": "stopCriteria", "markdown": "## Stop-kriterier", "shape": "non-empty list"},
            {"field": "maxOutput.format", "markdown": "## Max output / Format:", "shape": "non-empty text"},
            {"field": "maxOutput.limit", "markdown": "## Max output / Limit:", "shape": "non-empty text"},
        ],
        "frontmatterFields": [
            "zone",
            "owner",
            "agent",
            "project_dir",
            "scope_files",
        ],
        "markdown": read_reference("BRIEF-template.md"),
    }


def manager_output_shapes_payload(runtime: Any) -> dict[str, Any]:
    return {
        "schema": "y26.manager_output_shapes.v0",
        "workspaceId": runtime.workspace_id,
        "visibility": "private",
        "sourceRef": "manager/reference/manager-output-contract.md",
        "shapes": [
            "SHORTLIST",
            "NONE_OVER_THRESHOLD",
            "BATCH_FAIL",
            "VERIFY",
            "BLOCKED",
            "DECISION",
        ],
        "rule": "Manager must land in one explicit deliverable shape when surfacing upward.",
        "markdown": read_reference("manager-output-contract.md"),
    }


def workflow_spine_payload(runtime: Any) -> dict[str, Any]:
    return {
        "schema": "y26.workflow_spine.v0",
        "workspaceId": runtime.workspace_id,
        "visibility": "private",
        "sourceRefs": [
            "manager/reference/manager-boot-context.md",
            "manager/reference/codex-is-the-bridge.md",
            "manager/reference/direct-mode-safety.md",
            "memory/workflow-rules.md",
        ],
        "spine": [
            {
                "group": "CEO <-> Manager",
                "intent": "meaning, taste, doctrine, scope, GO/NO-GO",
                "output": "intent, constraints, decision surface",
            },
            {
                "group": "Transport / Orchestrator",
                "intent": "preserve packet and route work without judgment theft",
                "output": "pointers, run records, routing",
            },
            {
                "group": "Codex PM <-> Scribe",
                "intent": "turn intent into executable brief artifact",
                "output": "brief, scope files, acceptance criteria, verify plan",
            },
            {
                "group": "Codex PM <-> Agent",
                "intent": "execute bounded work and verify against brief",
                "output": "diff, evidence, return status",
            },
            {
                "group": "Manager <-> CEO",
                "intent": "surface decision-ready result",
                "output": "ship, afvigelse, blocked, beslutning kræves",
            },
        ],
        "directMode": {
            "status": "allowed_with_explicit_ceo_approval",
            "rule": "Native Claude Code Agent/Task tools and direct edits are direct/native mode, not Nogra orchestration.",
            "labeling": "If direct-mode is used, label it direct/native and never call it Transport, Codex PM, Agent Exec, Tier 4 or Nogra-run.",
            "goInheritance": "GO inherits the mode of the plan Manager presented. Nogra-plan GO routes through Nogra; direct-mode requires explicit approval.",
        },
        "hardRules": [
            "Questions are not commands.",
            "Phase before action.",
            "GO inherits the presented plan's mode.",
            "Native Agent/Task tools are direct-mode, not Nogra flow.",
            "State reads before project guesses.",
            "Return path may compress but never upgrade evidence.",
            "Brief-first for complex execution.",
            "Manager filters before CEO.",
        ],
    }


def register(mcp: Any, runtime: Any) -> None:
    from pydantic import Field

    workspace_id = runtime.workspace_id
    runtime_mcp = load_runtime_module()

    @mcp.resource(f"nogra://workspace/{workspace_id}/private/role-graph", mime_type="application/json")
    def y26_role_graph_resource() -> dict[str, Any]:
        return role_graph_payload(runtime)

    @mcp.resource(f"nogra://workspace/{workspace_id}/private/brief-template", mime_type="application/json")
    def y26_brief_template_resource() -> dict[str, Any]:
        return brief_template_payload(runtime)

    @mcp.resource(f"nogra://workspace/{workspace_id}/private/manager-output-shapes", mime_type="application/json")
    def y26_manager_output_shapes_resource() -> dict[str, Any]:
        return manager_output_shapes_payload(runtime)

    @mcp.resource(f"nogra://workspace/{workspace_id}/private/workflow-spine", mime_type="application/json")
    def y26_workflow_spine_resource() -> dict[str, Any]:
        return workflow_spine_payload(runtime)

    @mcp.tool(name="y26_private_registry")
    def y26_private_registry() -> dict[str, Any]:
        """Read the Y26 private module status.

        Returns a small status payload confirming that the Y26 private module is registered inside the canonical
        Nogra MCP server, plus the active workspace id and runtime tool names.

        When to use:
        - Confirm that the private module is available before using y26 workspace doctrine tools.
        - Check the module name, workspace id, and runtime tools from inside a Nogra MCP session.

        When NOT to use:
        - Do not use this to read role doctrine, brief structure, output shapes, or workflow rules.
        - Do not use this as a public registry replacement; it only reports private module status.

        Examples:
        >>> y26_private_registry()
        {"status": "registered", "module": "y26-private-module", "visibility": "private", "server": "nogra-mcp", "workspaceId": "local", "internalContextExposed": False}
        """
        return {
            "status": "registered",
            "module": "y26-private-module",
            "visibility": "private",
            "server": runtime.registry().get("name", "nogra-mcp"),
            "workspaceId": runtime.workspace_id,
            "runtime_tools": nogra_runtime.runtime_tool_names(),
            "codex_tools": codex_tool_names(),
            "internalContextExposed": False,
        }

    @mcp.tool(name="y26_role_graph")
    def y26_role_graph() -> dict[str, Any]:
        """Read the private Y26 role graph as structured data.

        Returns the private role graph payload for the active workspace: schema, visibility, source reference paths,
        top-level flow, and structured role entries with tier, title, and authority text.

        When to use:
        - Understand which role owns intent, routing, execution, verification, and return-path responsibility.
        - Ground Manager or agent routing decisions in the private role graph without reading full reference files.

        When NOT to use:
        - Do not use this when you need the brief template or manager deliverable contract.
        - Do not use this to dispatch work; it only describes role boundaries.

        Examples:
        >>> y26_role_graph()
        {"schema": "y26.role_graph.v0", "workspaceId": "local", "visibility": "private", "sourceRefs": [...], "flow": [...], "roles": [...]}
        """
        return role_graph_payload(runtime)

    @mcp.tool(name="y26_brief_template")
    def y26_brief_template() -> dict[str, Any]:
        """Read the private Y26 brief template contract.

        Returns the private brief template payload for the active workspace, including required section names,
        frontmatter fields, the source reference path, and the template markdown loaded from manager reference docs.

        When to use:
        - Build or validate an executable brief against the private y26 brief contract.
        - Check required sections and frontmatter fields before routing work through Manager or Transport.

        When NOT to use:
        - Do not use this for role authority, workflow phase rules, or manager output shapes.
        - Do not use this to create or dispatch a run; it only returns the brief contract and template markdown.

        Examples:
        >>> y26_brief_template()
        {"schema": "y26.brief_template.v0", "workspaceId": "local", "visibility": "private", "sourceRef": "manager/reference/BRIEF-template.md", "requiredSections": [...], "frontmatterFields": [...], "markdown": "..."}
        """
        return brief_template_payload(runtime)

    @mcp.tool(name="y26_manager_output_shapes")
    def y26_manager_output_shapes() -> dict[str, Any]:
        """Read private Y26 manager deliverable shapes.

        Returns the private Manager output contract for the active workspace, including the allowed shape names,
        the governing rule, source reference path, and markdown loaded from the manager output contract doc.

        When to use:
        - Choose the correct Manager return shape before surfacing a result upward.
        - Validate that a Manager response lands in an explicit deliverable shape such as VERIFY, BLOCKED, or DECISION.

        When NOT to use:
        - Do not use this to understand role hierarchy or workflow routing.
        - Do not use this as a transport return payload; it only describes Manager output contracts.

        Examples:
        >>> y26_manager_output_shapes()
        {"schema": "y26.manager_output_shapes.v0", "workspaceId": "local", "visibility": "private", "sourceRef": "manager/reference/manager-output-contract.md", "shapes": [...], "rule": "...", "markdown": "..."}
        """
        return manager_output_shapes_payload(runtime)

    @mcp.tool(name="y26_workflow_spine")
    def y26_workflow_spine() -> dict[str, Any]:
        """Read the private Y26 workflow spine.

        Returns the private workflow spine payload for the active workspace, including source reference paths,
        group-by-group intent and output expectations, direct-mode rules, and hard workflow rules.

        When to use:
        - Decide whether work should remain in Manager planning, route through Transport, or be clearly labeled direct/native.
        - Check phase, GO inheritance, state-read, and return-path rules before moving from analysis to execution.

        When NOT to use:
        - Do not use this to read the brief template markdown or Manager output shape markdown.
        - Do not use this to mutate state, dispatch work, or submit reports; it is a read-only doctrine surface.

        Examples:
        >>> y26_workflow_spine()
        {"schema": "y26.workflow_spine.v0", "workspaceId": "local", "visibility": "private", "sourceRefs": [...], "spine": [...], "directMode": {...}, "hardRules": [...]}
        """
        return workflow_spine_payload(runtime)

    @mcp.tool(name="codex_fresh_eyes_packet")
    def codex_fresh_eyes_packet(
        question: str = Field(default="", description="CEO/Manager question or solution for Codex to inspect."),
        mode: str = Field(default="current", description="current, full, pm, or wildcard."),
    ) -> dict[str, Any]:
        """Build the legacy /codex fresh-eyes packet without invoking Codex."""
        return runtime_mcp.codex_packet_payload(question=question, mode=mode)

    @mcp.tool(name="codex_fresh_eyes")
    def codex_fresh_eyes(
        question: str = Field(default="", description="CEO/Manager question or solution for Codex to inspect."),
        mode: str = Field(default="current", description="current, full, or pm."),
        cwd: str = Field(default="", description="Working directory for Codex. Defaults to Nogra root."),
        dry_run: bool = Field(default=False, description="If true, write packet/prompt/receipt but do not invoke Codex."),
        timeout_seconds: int = Field(default=240, description="Timeout for local codex exec."),
    ) -> dict[str, Any]:
        """Run or dry-run the legacy /codex fresh-eyes adapter through the canonical server."""
        return runtime_mcp.run_codex_fresh_eyes(
            question=question,
            mode=mode,
            cwd=cwd,
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
        )

    @mcp.tool(name="codex_dispatch_packet")
    def codex_dispatch_packet(
        project_dir: str = Field(description="Project directory for Codex PM."),
        brief_path: str = Field(default="", description="Approved brief path. Enables implementation dispatch."),
        manager_message: str = Field(default="", description="Manager instruction when no brief is supplied."),
        sandbox: str = Field(default="", description="Optional Codex sandbox override."),
    ) -> dict[str, Any]:
        """Build a formal Codex PM dispatch packet without invoking execution."""
        return runtime_mcp.codex_dispatch_packet_payload(
            project_dir=project_dir,
            brief_path=brief_path,
            manager_message=manager_message,
            sandbox=sandbox,
        )

    @mcp.tool(name="codex_dispatch")
    def codex_dispatch(
        project_dir: str = Field(description="Existing project directory where Codex PM runs and where brief paths are resolved."),
        brief_path: str = Field(default="", description="Optional approved brief path. When supplied, Codex PM dispatch uses workspace-write by default; blank allows manager_message read-only PM mode."),
        manager_message: str = Field(default="", description="Optional read-only PM instruction used when no brief is supplied, or supplemental context beside a brief."),
        dry_run: bool = Field(default=False, description="If true, write Codex PM packet/prompt/receipt previews without invoking the codex binary."),
        timeout_seconds: int = Field(default=600, description="Maximum local codex exec runtime in seconds before Transport timeout handling."),
        sandbox: str = Field(default="", description="Optional sandbox mode passed to codex exec. Empty uses workspace-write when a brief exists, otherwise read-only."),
    ) -> dict[str, Any]:
        """Run formal Codex PM through private Nogra Transport and wait for return.

        Delegates to run_transport_codex_dispatch with wait enabled. The runtime resolves the project and optional
        brief, writes packet/prompt/output/log/report/receipt paths, registers a codex-dispatch Transport run, and
        returns a finalized receipt with transportRun and transportReturn context when the run comes back.

        When to use:
        - Ask Codex PM to turn a Manager instruction or approved brief into implementation-shaped work.
        - Run the Codex PM gate through Transport rather than direct/native CLI work.

        When NOT to use:
        - Do not use this for Agent Exec execution; use transport_dispatch with target agent_exec.
        - Do not use this to read or acknowledge a finished run; use transport_return or transport_ack.

        Examples:
        >>> codex_dispatch(project_dir="/repo", brief_path="/repo/docs/brief.md", timeout_seconds=600)
        {"generatedAt": "...", "status": "...", "runId": "codex-dispatch-...", "transportRun": {...}, "transportReturn": {...}, "nextOwner": "Manager", ...}
        """
        return runtime_mcp.run_transport_codex_dispatch(
            project_dir=project_dir,
            brief_path=brief_path,
            manager_message=manager_message,
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            sandbox=sandbox,
            wait=True,
        )
