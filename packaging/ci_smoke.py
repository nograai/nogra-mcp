#!/usr/bin/env python3
"""Portable, stdlib-ONLY CI smoke test for the standalone nogra-mcp binary.

Spawns the frozen binary from a throwaway fixture workspace, drives the raw
JSON-RPC stdio handshake (initialize -> notifications/initialized ->
tools/list, newline-delimited per mcp/server/stdio.py), and asserts the
public boundary: EXACTLY 32 tools, none named y26_* or codex_* (per
BOUNDARY.md / packaging/NOTES.md "Handshake / boundary proof").

Usage:
    python packaging/ci_smoke.py [path-to-binary]

If [path-to-binary] is omitted, defaults to packaging/dist/nogra-mcp (or
packaging/dist/nogra-mcp.exe on win32) — the same path packaging/build.py
just built.

Exit 0 = handshake OK and boundary holds.
Exit 1 = handshake or boundary mismatch (CI must fail the build).
Exit 2 = could not run the smoke at all (binary missing / would not spawn).

stdlib-ONLY (no third-party imports) so this runs unmodified on every matrix
runner with zero extra dependency step. Windows-safe: pathlib throughout,
explicit UTF-8 text encoding on the child's stdio, the .exe suffix handled via
sys.platform, and response collection uses a background reader thread instead
of select() on pipes (select() on file objects is POSIX-only and does not
work on Windows).
"""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

TIMEOUT_SECONDS = 30
EXPECTED_TOOL_COUNT = 32
FORBIDDEN_PREFIXES = ("y26_", "codex_")


def default_binary_path() -> Path:
    packaging_dir = Path(__file__).resolve().parent
    name = "nogra-mcp.exe" if sys.platform == "win32" else "nogra-mcp"
    return packaging_dir / "dist" / name


def make_fixture_workspace() -> Path:
    """Throwaway workspace: only .nogra/config.json, matching the hostile-env
    fixture technique already proven in packaging/NOTES.md (Phase A/B)."""
    workspace = Path(tempfile.mkdtemp(prefix="nogra-ci-smoke-"))
    nogra_dir = workspace / ".nogra"
    nogra_dir.mkdir(parents=True, exist_ok=True)
    config_path = nogra_dir / "config.json"
    config_path.write_text(json.dumps({"workspaceId": "ci-smoke"}) + "\n", encoding="utf-8")
    return workspace


def _pump_stdout(stream, out_queue: "queue.Queue[str | None]") -> None:
    try:
        for line in stream:
            out_queue.put(line)
    except Exception:  # noqa: BLE001 - best-effort reader thread
        pass
    finally:
        out_queue.put(None)  # EOF sentinel


def _pump_stderr(stream, acc: list[str]) -> None:
    try:
        for line in stream:
            acc.append(line)
    except Exception:  # noqa: BLE001 - best-effort reader thread
        pass


def run_handshake(binary: Path, workspace: Path) -> tuple[dict[int, dict], str]:
    """Raw JSON-RPC over stdio: initialize -> notifications/initialized ->
    tools/list. Returns ({id: response}, stderr_text).

    Uses background reader threads (not select()) so this is identical on
    macOS, Linux and Windows. stdin is kept open while collecting responses
    (closing it immediately can race the child's own flush of its last
    response on some stdio implementations); the process is explicitly
    terminated once every expected response id has arrived or on timeout.
    """
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "nogra-ci-smoke", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    payload = "".join(json.dumps(m) + "\n" for m in messages)

    proc = subprocess.Popen(
        [str(binary)],
        cwd=str(workspace),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None

    stdout_q: "queue.Queue[str | None]" = queue.Queue()
    stderr_acc: list[str] = []
    stdout_thread = threading.Thread(target=_pump_stdout, args=(proc.stdout, stdout_q), daemon=True)
    stderr_thread = threading.Thread(target=_pump_stderr, args=(proc.stderr, stderr_acc), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    responses: dict[int, dict] = {}
    wanted = {1, 2}
    try:
        proc.stdin.write(payload)
        proc.stdin.flush()
    except (BrokenPipeError, OSError) as exc:
        print(f"SMOKE ERROR: writing request to binary stdin failed: {exc}", file=sys.stderr)

    deadline = time.monotonic() + TIMEOUT_SECONDS
    try:
        while wanted - responses.keys():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                line = stdout_q.get(timeout=remaining)
            except queue.Empty:
                break
            if line is None:  # child closed stdout / exited
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and isinstance(msg.get("id"), int):
                responses[msg["id"]] = msg
    finally:
        try:
            proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            pass
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

    return responses, "".join(stderr_acc)


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        print("usage: ci_smoke.py [path-to-binary]", file=sys.stderr)
        return 2

    binary = Path(argv[0]).resolve() if argv else default_binary_path()
    if not binary.exists():
        print(f"SMOKE ERROR: binary not found: {binary}", file=sys.stderr)
        return 2

    workspace = make_fixture_workspace()
    print(f"==> binary: {binary}")
    print(f"==> fixture workspace: {workspace}")

    try:
        responses, stderr_text = run_handshake(binary, workspace)
    except FileNotFoundError as exc:
        print(f"SMOKE ERROR: could not spawn binary: {exc}", file=sys.stderr)
        return 2

    if stderr_text.strip():
        print("---- binary stderr ----", file=sys.stderr)
        print(stderr_text, file=sys.stderr)

    failures: list[str] = []

    init = responses.get(1)
    if init is None or "result" not in init:
        failures.append(f"initialize did not return a result: {init!r}")

    tools_resp = responses.get(2)
    tools: list[dict] = []
    if tools_resp is None or "result" not in tools_resp:
        failures.append(f"tools/list did not return a result: {tools_resp!r}")
    else:
        tools = tools_resp["result"].get("tools", [])

    names = [t.get("name", "") for t in tools]
    count = len(names)
    if count != EXPECTED_TOOL_COUNT:
        failures.append(f"tool count {count} != expected {EXPECTED_TOOL_COUNT}")

    forbidden = sorted(n for n in names if any(n.startswith(p) for p in FORBIDDEN_PREFIXES))
    if forbidden:
        failures.append(f"forbidden private tool name(s) served: {forbidden}")

    if failures:
        print(f"CI SMOKE: FAIL ({len(failures)} finding(s))")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"CI SMOKE: PASS ({count}/{EXPECTED_TOOL_COUNT} tools, 0 forbidden y26_*/codex_* names)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
