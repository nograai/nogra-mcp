#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_ROOT = Path(__file__).resolve().parents[4]
ROOT = Path(os.environ.get("NOGRA_ROOT") or os.environ.get("Y26_ROOT") or str(DEFAULT_ROOT)).resolve()
PREFLIGHT_MARKER = "NOGRA_PREFLIGHT_READY"
PREFLIGHT_TIMEOUT_SECONDS = 20
PREFLIGHT_EXIT_CODE = 78
TOOLBANK_FILE = ROOT / "manager" / "nogra-mcp" / "toolbank" / "claude-tools.json"
FALLBACK_TOOLBANK = {
    "defaultFamily": "default-code",
    "families": {
        "default-code": {"tools": ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]},
        "read-only": {"tools": ["Read", "Glob", "Grep", "Bash"], "replacesDefault": True},
    },
    "aliases": {},
}


def command_available(command: str) -> bool:
    return bool(command) and (Path(command).exists() or shutil.which(command) is not None)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def stream_command(cmd: list[str], cwd: Path, prompt: str, input_mode: str = "stdin") -> tuple[int, str]:
    stdin = subprocess.PIPE if input_mode == "stdin" else subprocess.DEVNULL
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        text=True,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=safe_env(),
    )
    if input_mode == "stdin" and proc.stdin:
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except BrokenPipeError:
            pass

    chunks: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        chunks.append(line)
        sys.stdout.write(line)
        sys.stdout.flush()
    return proc.wait(), "".join(chunks)


def safe_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.pop("ANTHROPIC_API_KEY", None)
    env["NOGRA_ROOT"] = str(ROOT)
    env["Y26_ROOT"] = str(ROOT)
    return env


def ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


def collect_strings(value: object) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(collect_strings(item))
        return strings
    if isinstance(value, dict):
        strings = []
        for item in value.values():
            strings.extend(collect_strings(item))
        return strings
    return []


def normalize_family_id(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned


def normalize_match_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.strip().lower()).strip()


def text_matches_marker(value: str, marker: str) -> bool:
    normalized_value = normalize_match_text(value)
    normalized_marker = normalize_match_text(marker)
    return bool(normalized_marker and normalized_marker in normalized_value)


def load_toolbank() -> dict[str, object]:
    try:
        payload = json.loads(TOOLBANK_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(FALLBACK_TOOLBANK)
    if not isinstance(payload, dict) or not isinstance(payload.get("families"), dict):
        return dict(FALLBACK_TOOLBANK)
    return payload


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return {}, text
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, text
    meta: dict[str, str] = {}
    for raw in lines[1:end]:
        line = raw.strip()
        if not line or ":" not in line or line.startswith("- "):
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, "\n".join(lines[end + 1 :])


def markdown_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", flags=re.IGNORECASE | re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    next_heading = re.search(r"^##\s+", text[match.end() :], flags=re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end() : end].strip()


def execution_shape_from_markdown(text: str) -> dict[str, object]:
    _, body = parse_frontmatter(text)
    section = markdown_section(body, "Execution Shape")
    if not section:
        return {}
    shape: dict[str, object] = {}
    tool_families: list[str] = []
    tool_needs: list[str] = []
    notes: list[str] = []
    current = "notes"
    for raw in section.splitlines():
        line = raw.strip()
        if not line:
            continue
        label = line.rstrip(":").lower()
        if label in {"tool families", "tool family", "families", "family", "capability families"}:
            current = "toolFamilies"
            continue
        if label in {
            "tool needs",
            "tool need",
            "tools",
            "capabilities",
            "capability needs",
            "evidence needs",
            "evidence need",
            "evidence methods",
            "evidence method",
            "evidence plan",
        }:
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
        shape["toolFamilies"] = tool_families
    if tool_needs:
        shape["toolNeeds"] = tool_needs
    if notes:
        shape["notes"] = "\n".join(notes)
    return shape


def attach_brief_signals(shape: dict[str, object], payload: dict[str, object]) -> dict[str, object]:
    output = dict(shape)
    for key in ("evidenceRequired", "successCriteria"):
        value = payload.get(key)
        if value and f"_{key}" not in output:
            output[f"_{key}"] = value
    return output


def load_execution_shape(brief_path: str) -> dict[str, object]:
    if not brief_path:
        return {}
    path = Path(brief_path).expanduser()
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    try:
        payload = json.loads(text)
        if isinstance(payload, dict) and isinstance(payload.get("executionShape"), dict):
            return attach_brief_signals(payload["executionShape"], payload)
        if isinstance(payload, dict):
            return attach_brief_signals({}, payload)
    except json.JSONDecodeError:
        pass
    meta, body = parse_frontmatter(text)
    shape = execution_shape_from_markdown(text)
    payload: dict[str, object] = {}
    if meta.get("evidenceRequired"):
        payload["evidenceRequired"] = meta["evidenceRequired"]
    success_criteria = markdown_section(body, "Success Criteria")
    if success_criteria:
        payload["successCriteria"] = collect_strings(
            [re.sub(r"^[-*]\s+", "", line).strip() for line in success_criteria.splitlines()]
        )
    return attach_brief_signals(shape, payload)


def execution_shape_family_names(shape: dict[str, object]) -> list[str]:
    for key in ("toolFamilies", "toolFamily", "families", "family"):
        values = collect_strings(shape.get(key))
        if values:
            return values
    return []


def derived_family_names(shape: dict[str, object], toolbank: dict[str, object]) -> list[str]:
    families = toolbank.get("families") if isinstance(toolbank.get("families"), dict) else {}
    signals = {
        "toolNeeds": collect_strings(shape.get("toolNeeds")),
        "notes": collect_strings(shape.get("notes")),
        "evidenceRequired": collect_strings(shape.get("_evidenceRequired")),
        "successCriteria": collect_strings(shape.get("_successCriteria")),
    }
    derived: list[str] = []
    for family_id, family in families.items():
        if not isinstance(family, dict):
            continue
        derive_from = family.get("deriveFrom")
        if not isinstance(derive_from, dict):
            continue
        for source, markers in derive_from.items():
            haystacks = signals.get(str(source), [])
            if not haystacks:
                continue
            if any(
                text_matches_marker(haystack, marker)
                for haystack in haystacks
                for marker in collect_strings(markers)
            ):
                derived.append(str(family_id))
                break
    return ordered_unique([normalize_family_id(item) for item in derived])


def resolve_tool_families(shape: dict[str, object], toolbank: dict[str, object]) -> tuple[list[str], list[str]]:
    families = toolbank.get("families") if isinstance(toolbank.get("families"), dict) else {}
    aliases = toolbank.get("aliases") if isinstance(toolbank.get("aliases"), dict) else {}
    explicit = execution_shape_family_names(shape)
    requested = ordered_unique([*explicit, *derived_family_names(shape, toolbank)])
    if not requested:
        default_family = normalize_family_id(str(toolbank.get("defaultFamily") or "default-code"))
        return [default_family], []

    resolved: list[str] = []
    unknown: list[str] = []
    for item in requested:
        family_id = normalize_family_id(item)
        alias = aliases.get(family_id) if isinstance(aliases, dict) else None
        canonical = normalize_family_id(str(alias)) if alias else family_id
        if canonical in families:
            resolved.append(canonical)
        elif item in explicit:
            unknown.append(item)
    return ordered_unique(resolved), unknown


def claude_tool_scope_from_execution_shape(shape: dict[str, object]) -> dict[str, object]:
    toolbank = load_toolbank()
    families = toolbank.get("families") if isinstance(toolbank.get("families"), dict) else {}
    resolved, unknown = resolve_tool_families(shape, toolbank)
    default_family = normalize_family_id(str(toolbank.get("defaultFamily") or "default-code"))
    base_family = default_family
    for family_id in resolved:
        family = families.get(family_id)
        if isinstance(family, dict) and family.get("replacesDefault"):
            base_family = family_id
            break

    selected = ordered_unique([base_family, *[family_id for family_id in resolved if family_id != base_family]])
    tools: list[str] = []
    for family_id in selected:
        family = families.get(family_id)
        if not isinstance(family, dict):
            continue
        tools.extend(collect_strings(family.get("tools")))

    return {
        "families": selected,
        "unknownFamilies": unknown,
        "allowedTools": ordered_unique(tools),
        "toolbank": str(TOOLBANK_FILE),
    }


def claude_allowed_tools_from_execution_shape(shape: dict[str, object]) -> list[str]:
    scope = claude_tool_scope_from_execution_shape(shape)
    tools = scope.get("allowedTools")
    return tools if isinstance(tools, list) else []


def claude_allowed_tools(args: argparse.Namespace) -> list[str]:
    return claude_allowed_tools_from_execution_shape(load_execution_shape(getattr(args, "brief_path", "")))


def claude_tool_scope(args: argparse.Namespace) -> dict[str, object]:
    return claude_tool_scope_from_execution_shape(load_execution_shape(getattr(args, "brief_path", "")))


def codex_mcp_config_args(name: str, command: str, run_id: str = "", target: str = "") -> list[str]:
    args = [
        "-c",
        f"mcp_servers.{name}.command={json.dumps(command)}",
        "-c",
        f"mcp_servers.{name}.env.NOGRA_ROOT={json.dumps(str(ROOT))}",
    ]
    if run_id:
        args.extend(
            [
                "-c",
                f"mcp_servers.{name}.env.NOGRA_TRANSPORT_RUN_ID={json.dumps(run_id)}",
                "-c",
                f"mcp_servers.{name}.env.Y26_TRANSPORT_RUN_ID={json.dumps(run_id)}",
            ]
        )
    if target:
        args.extend(["-c", f"mcp_servers.{name}.env.NOGRA_TRANSPORT_TARGET={json.dumps(target)}"])
    return args


def build_claude_cmd(args: argparse.Namespace) -> list[str]:
    binary = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
    cmd = [
        binary,
        "--print",
        "--model",
        args.model or "sonnet",
        "--effort",
        args.effort or "low",
        "--input-format",
        "text",
        "--output-format",
        "text",
        "--verbose",
        "--permission-mode",
        "default",
        "--strict-mcp-config",
        "--setting-sources",
        "user,local",
        "--settings",
        args.settings,
        "--add-dir",
        args.project_dir,
    ]
    cmd.extend(f"--allowedTools={tool}" for tool in claude_allowed_tools(args))
    return cmd


def run_claude_preflight(args: argparse.Namespace, cwd: Path) -> tuple[bool, str, str]:
    prompt = f"Respond with exactly {PREFLIGHT_MARKER} and no other text."
    cmd = [*build_claude_cmd(args), "--", prompt]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            text=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=safe_env(),
            timeout=PREFLIGHT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        return False, f"claude preflight timed out after {PREFLIGHT_TIMEOUT_SECONDS}s", output

    output = result.stdout or ""
    if result.returncode != 0:
        return False, f"claude preflight exited {result.returncode}", output
    if PREFLIGHT_MARKER not in output:
        return False, f"claude preflight missing marker {PREFLIGHT_MARKER}", output
    return True, "", output


def write_preflight_failure(args: argparse.Namespace, reason: str, details: str) -> None:
    detail_block = details.strip()[:4000] or "(no preflight output)"
    text = f"""# Agent Exec Preflight Failed

## Status
failed_preflight

## Reason
{reason}

## Details
```text
{detail_block}
```
"""
    write_text(Path(args.output), text)
    write_text(Path(args.report), text)


def build_codex_cmd(args: argparse.Namespace) -> list[str]:
    binary = os.environ.get("CODEX_BIN") or shutil.which("codex") or str(Path.home() / ".npm-global" / "bin" / "codex")
    reasoning = os.environ.get("NOGRA_CODEX_DISPATCH_REASONING") or os.environ.get("Y26_CODEX_DISPATCH_REASONING", args.effort or "medium")
    return [
        binary,
        "exec",
        *codex_mcp_config_args(args.codex_mcp_name, args.nogra_mcp_bin, run_id=args.run_id, target=args.transport_target),
        "-m",
        args.model or os.environ.get("NOGRA_CODEX_MODEL") or os.environ.get("Y26_CODEX_MODEL", "gpt-5.4"),
        "-c",
        f"model_reasoning_effort={json.dumps(reasoning)}",
        "-c",
        'approval_policy="never"',
        "--sandbox",
        args.sandbox or "workspace-write",
        "--skip-git-repo-check",
        "--ephemeral",
        "--color",
        "never",
        "--json",
        "-C",
        args.project_dir,
        "-o",
        args.output,
        "-",
    ]


def build_gemini_cmd(args: argparse.Namespace, prompt: str) -> list[str]:
    binary = os.environ.get("GEMINI_BIN") or shutil.which("gemini") or str(Path.home() / ".npm-global" / "bin" / "gemini")
    cmd = [
        binary,
        "--prompt",
        prompt,
        "--approval-mode",
        os.environ.get("NOGRA_GEMINI_APPROVAL_MODE") or os.environ.get("Y26_GEMINI_APPROVAL_MODE", "auto_edit"),
        "--sandbox",
        "--skip-trust",
        "--output-format",
        "text",
        "--include-directories",
        args.project_dir,
    ]
    if args.model and args.model not in {"default", "gemini-default"}:
        cmd.extend(["--model", args.model])
    return cmd


def ensure_artifacts(args: argparse.Namespace, stdout_text: str) -> None:
    output = Path(args.output)
    report = Path(args.report)
    if not output.exists() and stdout_text.strip():
        write_text(output, stdout_text)
    if not report.exists():
        if output.exists():
            write_text(report, output.read_text(encoding="utf-8", errors="replace"))
        elif stdout_text.strip():
            write_text(report, stdout_text)


def run_agent_exec(args: argparse.Namespace) -> int:
    prompt = sys.stdin.read()
    project = Path(args.project_dir).resolve()
    adapter = args.adapter
    if args.run_id:
        os.environ["NOGRA_TRANSPORT_RUN_ID"] = args.run_id
        os.environ["Y26_TRANSPORT_RUN_ID"] = args.run_id
        os.environ["NOGRA_TRANSPORT_TARGET"] = args.transport_target
    if adapter == "claude_cli":
        cmd = [*build_claude_cmd(args), "--", prompt]
        input_mode = "none"
    elif adapter == "codex_cli":
        cmd = build_codex_cmd(args)
        input_mode = "stdin"
    elif adapter == "gemini_cli":
        cmd = build_gemini_cmd(args, prompt)
        input_mode = "none"
    else:
        write_text(Path(args.output), f"# Agent Exec adapter unsupported\n\nAdapter `{adapter}` is not supported.")
        write_text(Path(args.report), f"# Agent Exec adapter unsupported\n\nAdapter `{adapter}` is not supported.")
        print(f"agent-adapter: unsupported adapter {adapter}", file=sys.stderr)
        return 64

    if not command_available(cmd[0]):
        write_text(Path(args.output), f"# Agent Exec adapter unavailable\n\nBinary not found: `{cmd[0]}`.")
        write_text(Path(args.report), f"# Agent Exec adapter unavailable\n\nBinary not found: `{cmd[0]}`.")
        print(f"agent-adapter: binary not found: {cmd[0]}", file=sys.stderr)
        return 127

    print(
        json.dumps(
            {
                "type": "agent_adapter_start",
                "adapter": adapter,
                "model": args.model,
                "cwd": str(project),
                "toolScope": claude_tool_scope(args) if adapter == "claude_cli" else {},
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    if adapter == "claude_cli":
        print(json.dumps({"type": "agent_adapter_preflight_start", "timeoutSeconds": PREFLIGHT_TIMEOUT_SECONDS}, ensure_ascii=False), flush=True)
        ok, reason, details = run_claude_preflight(args, cwd=project)
        if not ok:
            write_preflight_failure(args, reason, details)
            print(json.dumps({"type": "agent_adapter_preflight_failed", "reason": reason}, ensure_ascii=False), flush=True)
            return PREFLIGHT_EXIT_CODE
        print(json.dumps({"type": "agent_adapter_preflight_ok", "marker": PREFLIGHT_MARKER}, ensure_ascii=False), flush=True)
    code, stdout_text = stream_command(cmd, cwd=project, prompt=prompt, input_mode=input_mode)
    ensure_artifacts(args, stdout_text)
    print(json.dumps({"type": "agent_adapter_exit", "adapter": adapter, "exitCode": code}, ensure_ascii=False), flush=True)
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="Nogra agent adapter runner")
    sub = parser.add_subparsers(dest="command", required=True)

    agent = sub.add_parser("agent-exec")
    agent.add_argument("--adapter", required=True)
    agent.add_argument("--project-dir", required=True)
    agent.add_argument("--output", required=True)
    agent.add_argument("--report", required=True)
    agent.add_argument("--run-id", default="")
    agent.add_argument("--model", default="")
    agent.add_argument("--effort", default="")
    agent.add_argument("--sandbox", default="workspace-write")
    agent.add_argument("--settings", default="")
    agent.add_argument("--brief-path", default="")
    agent.add_argument("--transport-target", default="agent_exec")
    agent.add_argument("--codex-mcp-name", default="nogra-dev")
    agent.add_argument("--nogra-mcp-bin", default=str(ROOT / "manager" / "bin" / "nogra-mcp"))

    args = parser.parse_args()
    if args.command == "agent-exec":
        return run_agent_exec(args)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
