#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _resolve_default_root() -> Path:
    # Assumes a dev/private checkout depth (src/nogra_mcp/transport_runtime.py
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
TRANSPORT_DIR = ROOT / "manager" / "state" / "transport"
RUNS_STATE_DIR = TRANSPORT_DIR / "runs"
ARCHIVE_DIR = TRANSPORT_DIR / "archive"
LOCKS_DIR = TRANSPORT_DIR / "locks"
WATCHERS_DIR = TRANSPORT_DIR / "watchers"
EVENTS_FILE = TRANSPORT_DIR / "events.jsonl"
INBOX_MANAGER_FILE = TRANSPORT_DIR / "inbox-manager.jsonl"

TERMINAL_STATUSES = {
    "ok",
    "partial",
    "failed",
    "failed_no_report",
    "failed_scope_drift",
    "failed_completion_validation",
    "failed_preflight",
    "timeout",
    "cancelled",
    "orphaned",
    "unavailable",
}
RETURNABLE_STATUSES = TERMINAL_STATUSES | {"returned", "acknowledged"}
ACTIVE_STATUSES = {"queued", "running", "stale", "returning"}
DEFAULT_STALE_SECONDS = int(os.environ.get("NOGRA_TRANSPORT_STALE_SECONDS") or os.environ.get("Y26_TRANSPORT_STALE_SECONDS", "120"))
DEFAULT_POLL_SECONDS = float(os.environ.get("NOGRA_TRANSPORT_POLL_SECONDS") or os.environ.get("Y26_TRANSPORT_POLL_SECONDS", "2"))
DEFAULT_HEARTBEAT_SECONDS = float(
    os.environ.get("NOGRA_TRANSPORT_HEARTBEAT_SECONDS") or os.environ.get("Y26_TRANSPORT_HEARTBEAT_SECONDS", "30")
)
RELEASE_VERSION = "v1.0.0"
TRANSPORT_RUN_SCHEMA = "nogra.transport.run.v1"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def ensure_dirs() -> None:
    for path in (TRANSPORT_DIR, RUNS_STATE_DIR, ARCHIVE_DIR, LOCKS_DIR, WATCHERS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    ensure_dirs()
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    ensure_dirs()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=json_default) + "\n")


def append_event(run_id: str, event_type: str, **fields: Any) -> dict[str, Any]:
    event = {"generatedAt": now(), "runId": run_id, "type": event_type, **fields}
    append_jsonl(EVENTS_FILE, event)
    return event


def append_manager_inbox(payload: dict[str, Any]) -> dict[str, Any]:
    generated_at = now()
    item = {
        "schema": "nogra.manager.inbox.item.v1",
        "eventId": f"manager-inbox-{generated_at.replace(':', '').replace('-', '').replace('.', '')}-{uuid.uuid4().hex[:8]}",
        "generatedAt": generated_at,
        "recipient": "Manager",
        "status": "unread",
        **payload,
    }
    append_jsonl(INBOX_MANAGER_FILE, item)
    return item


def run_state_path(run_id: str) -> Path:
    return RUNS_STATE_DIR / f"{run_id}.json"


def archive_state_path(run_id: str) -> Path:
    return ARCHIVE_DIR / f"{run_id}.json"


def lock_path(run_id: str) -> Path:
    return LOCKS_DIR / f"{run_id}.lock.json"


def load_run(run_id: str, include_archive: bool = True) -> dict[str, Any]:
    ensure_dirs()
    payload = read_json(run_state_path(run_id), {})
    if payload or not include_archive:
        return payload
    return read_json(archive_state_path(run_id), {})


def save_run(record: dict[str, Any]) -> dict[str, Any]:
    record["updatedAt"] = now()
    write_json_atomic(run_state_path(str(record["runId"])), record)
    return record


def pid_alive(pid: Any) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    try:
        os.kill(value, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def file_info(path_value: str | None) -> dict[str, Any]:
    if not path_value:
        return {"exists": False, "path": ""}
    path = Path(path_value)
    try:
        stat = path.stat()
    except OSError:
        return {"exists": False, "path": str(path)}
    return {
        "exists": True,
        "path": str(path),
        "size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def artifacts_for(record: dict[str, Any]) -> dict[str, Any]:
    paths = record.get("paths") if isinstance(record.get("paths"), dict) else {}
    return {
        "output": file_info(paths.get("output")),
        "report": file_info(paths.get("report")),
        "log": file_info(paths.get("log")),
        "receipt": file_info(paths.get("receipt")),
        "packet": file_info(paths.get("packet")),
        "prompt": file_info(paths.get("prompt")),
    }


def refresh_record(record: dict[str, Any]) -> dict[str, Any]:
    if not record:
        return {}
    record["artifacts"] = artifacts_for(record)
    status = str(record.get("status") or "")
    if status in ACTIVE_STATUSES:
        watcher_alive = pid_alive(record.get("watcherPid"))
        target_alive = pid_alive(record.get("targetPid"))
        record["watcherAlive"] = watcher_alive
        record["targetAlive"] = target_alive
        if not watcher_alive and not target_alive and record.get("startedAt"):
            age = time.time() - (parse_time(record.get("updatedAt")) or time.time())
            if age > 15:
                record["status"] = "orphaned"
                record["phase"] = "returned"
                record["resultStatus"] = "orphaned"
                record["nextOwner"] = "Manager"
                record["error"] = "transport watcher and target process are not alive"
                append_event(str(record["runId"]), "transport_orphaned", nextOwner="Manager")
                append_manager_inbox(
                    {
                        "runId": record["runId"],
                        "type": "transport_return",
                        "summary": "Transport run orphaned; Manager review required.",
                        "resultStatus": "orphaned",
                        "report": record.get("paths", {}).get("report", ""),
                    }
                )
                save_run(record)
    elif status in RETURNABLE_STATUSES:
        record["watcherAlive"] = False
        record["targetAlive"] = False
    return record


def public_run(record: dict[str, Any]) -> dict[str, Any]:
    record = refresh_record(dict(record))
    return {
        "runId": record.get("runId"),
        "target": record.get("target"),
        "targetRole": record.get("targetRole"),
        "status": record.get("status"),
        "phase": record.get("phase"),
        "resultStatus": record.get("resultStatus"),
        "nextOwner": record.get("nextOwner"),
        "createdAt": record.get("createdAt"),
        "startedAt": record.get("startedAt"),
        "completedAt": record.get("completedAt"),
        "acknowledgedAt": record.get("acknowledgedAt"),
        "durationSeconds": record.get("durationSeconds"),
        "staleSeconds": record.get("staleSeconds"),
        "heartbeatSeconds": record.get("heartbeatSeconds"),
        "lastHeartbeatAt": record.get("lastHeartbeatAt"),
        "lastLogAt": record.get("lastLogAt"),
        "idleSeconds": record.get("idleSeconds"),
        "quietSeconds": record.get("quietSeconds"),
        "scopeBaseline": record.get("scopeBaseline"),
        "scopeBaselineCapturedAt": record.get("scopeBaselineCapturedAt"),
        "scopeBaselineError": record.get("scopeBaselineError"),
        "watcherPid": record.get("watcherPid"),
        "targetPid": record.get("targetPid"),
        "watcherAlive": record.get("watcherAlive"),
        "targetAlive": record.get("targetAlive"),
        "model": record.get("model"),
        "adapter": record.get("adapter"),
        "effort": record.get("effort"),
        "sandbox": record.get("sandbox"),
        "projectDir": record.get("projectDir"),
        "briefPath": record.get("briefPath"),
        "parentRunId": record.get("parentRunId"),
        "intentId": record.get("intentId"),
        "sharedDoctrineRefs": record.get("sharedDoctrineRefs", []),
        "paths": record.get("paths", {}),
        "artifacts": record.get("artifacts", {}),
        "error": record.get("error", ""),
    }


def recent_runs(limit: int = 20, include_archive: bool = False) -> list[dict[str, Any]]:
    ensure_dirs()
    paths = list(RUNS_STATE_DIR.glob("*.json"))
    if include_archive:
        paths.extend(ARCHIVE_DIR.glob("*.json"))
    records = [read_json(path, {}) for path in paths]
    records = [record for record in records if isinstance(record, dict) and record.get("runId")]
    records.sort(key=lambda record: str(record.get("updatedAt") or record.get("createdAt") or ""), reverse=True)
    return [public_run(record) for record in records[:limit]]


def latest_run_id() -> str:
    runs = recent_runs(limit=1, include_archive=False)
    return str(runs[0].get("runId") or "") if runs else ""


def read_events(limit: int = 80, run_id: str = "") -> list[dict[str, Any]]:
    ensure_dirs()
    try:
        lines = EVENTS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if run_id and event.get("runId") != run_id:
            continue
        out.append(event)
        if len(out) >= limit:
            break
    out.reverse()
    return out


def register_run(record: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    record.setdefault("schema", TRANSPORT_RUN_SCHEMA)
    record.setdefault("releaseVersion", RELEASE_VERSION)
    record.setdefault("kind", "transport_run")
    record.setdefault("createdAt", now())
    record.setdefault("status", "queued")
    record.setdefault("phase", "queued")
    record.setdefault("nextOwner", "Transport")
    record.setdefault("staleSeconds", DEFAULT_STALE_SECONDS)
    record.setdefault("heartbeatSeconds", DEFAULT_HEARTBEAT_SECONDS)
    record["artifacts"] = artifacts_for(record)
    save_run(record)
    append_event(
        str(record["runId"]),
        "transport_run_created",
        target=record.get("target"),
        targetRole=record.get("targetRole"),
        parentRunId=record.get("parentRunId"),
        intentId=record.get("intentId"),
        nextOwner="Transport",
    )
    return public_run(record)


def spawn_watcher(run_id: str) -> dict[str, Any]:
    ensure_dirs()
    record = load_run(run_id, include_archive=False)
    if not record:
        return {"status": "missing", "runId": run_id, "error": "transport run not found"}
    if pid_alive(record.get("watcherPid")):
        return public_run(record)

    watcher_bin = ROOT / "manager" / "bin" / "transport-watch"
    watcher_log = WATCHERS_DIR / f"{run_id}.log"
    paths = record.setdefault("paths", {})
    paths["watcherLog"] = str(watcher_log)
    save_run(record)

    env = os.environ.copy()
    env["NOGRA_ROOT"] = str(ROOT)
    env["Y26_ROOT"] = str(ROOT)
    with watcher_log.open("a", encoding="utf-8") as log_handle:
        proc = subprocess.Popen(
            [str(watcher_bin), "run", run_id],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )

    record["watcherPid"] = proc.pid
    record["watcherStartedAt"] = now()
    save_run(record)
    append_event(run_id, "transport_watcher_spawned", watcherPid=proc.pid)
    return public_run(record)


def kill_process_group(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        return
    except PermissionError:
        raise


def canonical_receipt_context(record: dict[str, Any]) -> dict[str, Any]:
    paths = record.get("paths") if isinstance(record.get("paths"), dict) else {}
    return {
        "runId": record.get("runId", ""),
        "target": record.get("target", ""),
        "targetRole": record.get("targetRole", ""),
        "projectDir": record.get("projectDir", ""),
        "briefPath": record.get("briefPath", ""),
        "runDir": paths.get("runDir", ""),
        "packet": paths.get("packet", ""),
        "prompt": paths.get("prompt", ""),
        "output": paths.get("output", ""),
        "log": paths.get("log", ""),
        "report": paths.get("report", ""),
        "receipt": paths.get("receipt", ""),
        "settings": paths.get("settings", ""),
        "adapter": record.get("adapter", ""),
        "model": record.get("model", ""),
        "effort": record.get("effort", ""),
        "sandbox": record.get("sandbox", ""),
        "parentRunId": record.get("parentRunId", ""),
        "intentId": record.get("intentId", ""),
        "sharedDoctrineRefs": record.get("sharedDoctrineRefs", []),
        "transportMode": record.get("transportMode", "detached-watch"),
        "nextOwner": record.get("nextOwner", ""),
    }


def merge_receipt_context(record: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    canonical = canonical_receipt_context(record)
    merged = {**canonical, **receipt}
    for key, value in canonical.items():
        if key == "sharedDoctrineRefs":
            if not isinstance(merged.get(key), list):
                merged[key] = value
            continue
        current = merged.get(key)
        if (current is None or current == "") and value is not None and value != "":
            merged[key] = value
    return merged


def write_receipt(record: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    paths = record.get("paths", {})
    receipt_value = str(paths.get("receipt") or "")
    receipt_path = Path(receipt_value) if receipt_value else None
    receipt = read_json(receipt_path, {}) if receipt_path else {}
    if not isinstance(receipt, dict):
        receipt = {}
    receipt = merge_receipt_context(record, receipt)
    receipt.update(updates)
    if receipt_path:
        write_json_atomic(receipt_path, receipt)
    return receipt


def read_text_if_exists(path_value: str | None, limit: int | None = None) -> str:
    if not path_value:
        return ""
    try:
        text = Path(path_value).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if limit is not None and len(text) > limit:
        return text[-limit:]
    return text


def should_mirror_output_to_report(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    head = stripped[:700].lower()
    if head.startswith("blocked:") and "report" in head and any(token in head for token in ("sandbox", "writable", "write")):
        return False
    return True


def mirror_output_to_report(output_path: Path, report_path: Path, run_id: str = "") -> bool:
    if report_path.exists() or not output_path.exists():
        return False
    text = read_text_if_exists(str(output_path))
    if not should_mirror_output_to_report(text):
        return False
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text.rstrip() + "\n", encoding="utf-8")
    except OSError as exc:
        if run_id:
            append_event(run_id, "transport_report_mirror_failed", output=str(output_path), report=str(report_path), error=str(exc))
        return False
    if run_id:
        append_event(run_id, "transport_report_mirrored", source="output", output=str(output_path), report=str(report_path))
    return True


def append_agent_log(log_path: Path, event_type: str, **fields: Any) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"generatedAt": now(), "type": event_type, **fields}
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=json_default) + "\n")
    except OSError:
        return


def validate_report_present(report_path: Path) -> bool:
    return report_path.is_file()


def brief_meta_payload(brief_path: Path) -> dict[str, Any]:
    helper = ROOT / ".claude" / "hooks" / "brief_meta.py"
    if not helper.is_file():
        return {"error": f"brief metadata helper not found: {helper}"}
    result = subprocess.run(
        [sys.executable, str(helper), str(brief_path)],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return {"error": result.stdout.strip() or "invalid brief metadata"}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": "brief metadata helper returned non-json"}
    return payload if isinstance(payload, dict) else {"error": "brief metadata helper returned non-object"}


def git_diff_names(project_dir: Path) -> tuple[list[str], str]:
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=str(project_dir),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        return [], result.stdout.strip() or f"git diff failed with exit code {result.returncode}"
    return [line.strip() for line in result.stdout.splitlines() if line.strip()], ""


def capture_scope_baseline(record: dict[str, Any], project_dir: Path) -> dict[str, Any]:
    if isinstance(record.get("scopeBaseline"), list):
        return record
    baseline, error = git_diff_names(project_dir)
    record["scopeBaseline"] = baseline
    record["scopeBaselineCapturedAt"] = now()
    if error:
        record["scopeBaselineError"] = error
        append_event(str(record.get("runId") or ""), "transport_scope_baseline_failed", error=error)
    else:
        record.pop("scopeBaselineError", None)
        append_event(str(record.get("runId") or ""), "transport_scope_baseline_captured", baselineCount=len(baseline))
    return record


def validate_diff_in_scope(project_dir: Path, scope_files: list[str], baseline: list[str] | None) -> dict[str, Any]:
    if baseline is None:
        return {
            "scopeCheckSkipped": True,
            "scopeCheckSkipReason": "scopeBaseline missing",
            "currentDiff": [],
            "scopeDelta": [],
            "outOfScope": [],
        }
    current_diff, error = git_diff_names(project_dir)
    if error:
        return {
            "scopeCheckSkipped": True,
            "scopeCheckSkipReason": error,
            "currentDiff": [],
            "scopeDelta": [],
            "outOfScope": [],
        }
    scope = {str(path).strip() for path in scope_files if str(path).strip()}
    delta = sorted(set(current_diff) - set(baseline))
    out_of_scope = sorted(set(delta) - scope)
    return {
        "scopeCheckSkipped": False,
        "currentDiff": current_diff,
        "scopeDelta": delta,
        "outOfScope": out_of_scope,
    }


def validate_completion_record(record: dict[str, Any], emit: bool = True) -> dict[str, Any]:
    run_id = str(record.get("runId") or "")
    paths = record.get("paths") if isinstance(record.get("paths"), dict) else {}
    report_path = Path(str(paths.get("report") or ""))
    log_path = Path(str(paths.get("log") or ""))
    brief_path = Path(str(record.get("briefPath") or ""))
    project_dir = Path(str(record.get("projectDir") or ""))

    validation: dict[str, Any] = {
        "generatedAt": now(),
        "runId": run_id,
        "status": "ok",
        "reportPresent": validate_report_present(report_path),
        "report": str(report_path),
        "outOfScope": [],
    }
    if not validation["reportPresent"]:
        validation.update(
            {
                "status": "failed_no_report",
                "error": f"completion report missing: {report_path}",
            }
        )
    elif not str(record.get("briefPath") or "").strip():
        validation.update(
            {
                "briefPath": "",
                "scopeCheckSkipped": True,
                "scopeCheckSkipReason": "no brief path; read-only/message dispatch has no scope contract",
                "currentDiff": [],
                "scopeDelta": [],
                "scopeFiles": [],
            }
        )
    else:
        meta = brief_meta_payload(brief_path)
        if "error" in meta:
            validation.update(
                {
                    "status": "failed_brief_contract",
                    "error": str(meta["error"]),
                }
            )
        else:
            scope_files = [str(value) for value in meta.get("scope_files", []) if str(value).strip()]
            baseline = None if record.get("scopeBaselineError") else record.get("scopeBaseline")
            scope_validation = validate_diff_in_scope(
                project_dir=project_dir,
                scope_files=scope_files,
                baseline=baseline if isinstance(baseline, list) else None,
            )
            validation.update(
                {
                    "projectDir": str(project_dir),
                    "briefPath": str(brief_path),
                    "scopeFiles": scope_files,
                    "scopeBaseline": record.get("scopeBaseline") if isinstance(record.get("scopeBaseline"), list) else [],
                    "scopeBaselineCapturedAt": record.get("scopeBaselineCapturedAt", ""),
                    "scopeBaselineError": record.get("scopeBaselineError", ""),
                    **scope_validation,
                }
            )
            if scope_validation.get("outOfScope"):
                validation.update(
                    {
                        "status": "failed_scope_drift",
                        "error": "out-of-scope diff detected: " + ", ".join(scope_validation["outOfScope"][:12]),
                    }
                )

    if emit and validation["status"] != "ok":
        append_agent_log(log_path, "transport_completion_validation_failed", **validation)
        append_event(run_id, "transport_completion_validation_failed", **validation)
    elif emit:
        append_event(run_id, "transport_completion_validated", report=str(report_path), outOfScope=[])
    return validation


def validate_completion(run_id: str) -> dict[str, Any]:
    record = load_run(run_id, include_archive=True)
    if not record:
        return {"generatedAt": now(), "status": "missing", "runId": run_id, "error": "transport run not found"}
    return validate_completion_record(record, emit=True)


def submit_report(
    run_id: str = "",
    report_text: str = "",
    status: str = "",
    summary: str = "",
    output_text: str = "",
    allow_overwrite: bool = False,
    source: str = "mcp",
) -> dict[str, Any]:
    resolved_run_id = (
        run_id.strip()
        or os.environ.get("NOGRA_TRANSPORT_RUN_ID", "").strip()
        or os.environ.get("Y26_TRANSPORT_RUN_ID", "").strip()
    )
    if not resolved_run_id:
        return {
            "generatedAt": now(),
            "status": "invalid",
            "error": "transport run id required; dispatch must allocate NOGRA_TRANSPORT_RUN_ID or caller must pass run_id",
        }

    text = report_text.rstrip()
    if not text:
        return {"generatedAt": now(), "status": "invalid", "runId": resolved_run_id, "error": "report_text required"}

    record = load_run(resolved_run_id, include_archive=False)
    if not record:
        return {"generatedAt": now(), "status": "missing", "runId": resolved_run_id, "error": "transport run not found"}

    paths = record.get("paths") if isinstance(record.get("paths"), dict) else {}
    report_value = str(paths.get("report") or "")
    output_value = str(paths.get("output") or "")
    if not report_value:
        return {"generatedAt": now(), "status": "invalid", "runId": resolved_run_id, "error": "transport run has no report path"}
    report_path = Path(report_value)
    output_path = Path(output_value) if output_value else Path()

    try:
        if report_path.exists() and not allow_overwrite:
            existing_size = report_path.stat().st_size
            if existing_size > 0:
                return {
                    "generatedAt": now(),
                    "status": "exists",
                    "runId": resolved_run_id,
                    "report": str(report_path),
                    "error": "report already exists; pass allow_overwrite=true to replace it",
                }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text + "\n", encoding="utf-8")

        output_payload = (output_text.rstrip() if output_text.strip() else text)
        if output_value and (allow_overwrite or not output_path.exists()):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(output_payload + "\n", encoding="utf-8")
    except OSError as exc:
        append_event(resolved_run_id, "transport_report_submit_failed", source=source, error=str(exc), report=str(report_path))
        return {"generatedAt": now(), "status": "failed", "runId": resolved_run_id, "error": str(exc)}

    submitted_at = now()
    normalized_status = status.strip().lower()
    receipt_updates: dict[str, Any] = {
        "reportText": text + "\n",
        "answer": (output_text.rstrip() if output_text.strip() else text) + "\n",
        "reportSubmittedAt": submitted_at,
        "reportSubmissionSource": source,
    }
    if normalized_status:
        receipt_updates["submittedStatus"] = normalized_status
    if summary.strip():
        receipt_updates["summary"] = summary.strip()
    receipt = write_receipt(record, receipt_updates)

    record["phase"] = "returning"
    record["reportSubmittedAt"] = submitted_at
    record["artifacts"] = artifacts_for(record)
    save_run(record)
    append_event(
        resolved_run_id,
        "transport_report_submitted",
        source=source,
        submittedStatus=normalized_status,
        summary=summary.strip(),
        report=str(report_path),
        output=str(output_path) if output_value else "",
    )

    public = public_run(record)
    return {
        "generatedAt": submitted_at,
        "status": "ok",
        "runId": resolved_run_id,
        "report": str(report_path),
        "output": str(output_path) if output_value else "",
        "receipt": receipt,
        "run": public,
    }


def acquire_lock(run_id: str) -> bool:
    ensure_dirs()
    path = lock_path(run_id)
    existing = read_json(path, {})
    if existing and pid_alive(existing.get("pid")) and int(existing.get("pid")) != os.getpid():
        return False
    write_json_atomic(path, {"runId": run_id, "pid": os.getpid(), "createdAt": now()})
    return True


def release_lock(run_id: str) -> None:
    path = lock_path(run_id)
    existing = read_json(path, {})
    if int(existing.get("pid") or 0) == os.getpid():
        try:
            path.unlink()
        except OSError:
            pass


def watch_run(run_id: str, poll_seconds: float = DEFAULT_POLL_SECONDS) -> dict[str, Any]:
    if not acquire_lock(run_id):
        return {"status": "already-watched", "runId": run_id}

    record = load_run(run_id, include_archive=False)
    if not record:
        release_lock(run_id)
        return {"status": "missing", "runId": run_id, "error": "transport run not found"}

    try:
        command = record.get("command")
        if not isinstance(command, list) or not command:
            record["status"] = "failed"
            record["phase"] = "returned"
            record["resultStatus"] = "failed"
            record["nextOwner"] = "Manager"
            record["error"] = "transport run has no command"
            save_run(record)
            append_event(run_id, "transport_run_failed", error=record["error"], nextOwner="Manager")
            return public_run(record)

        paths = record.get("paths", {})
        prompt_path = Path(str(paths.get("prompt", "")))
        log_path = Path(str(paths.get("log", "")))
        output_path = Path(str(paths.get("output", "")))
        report_path = Path(str(paths.get("report", "")))

        if not prompt_path.is_file():
            record["status"] = "failed"
            record["phase"] = "returned"
            record["resultStatus"] = "failed"
            record["nextOwner"] = "Manager"
            record["error"] = f"prompt file missing: {prompt_path}"
            save_run(record)
            append_event(run_id, "transport_run_failed", error=record["error"], nextOwner="Manager")
            return public_run(record)

        timeout_seconds = int(record.get("timeoutSeconds") or 600)
        stale_seconds = int(record.get("staleSeconds") or DEFAULT_STALE_SECONDS)
        heartbeat_seconds = float(record.get("heartbeatSeconds") or DEFAULT_HEARTBEAT_SECONDS)
        started = time.time()
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in dict(record.get("env") or {}).items()})
        env.pop("OPENAI_API_KEY", None)
        env.pop("ANTHROPIC_API_KEY", None)
        env.setdefault("PYTHONUNBUFFERED", "1")

        project_dir = Path(str(record.get("projectDir") or ROOT))
        record = capture_scope_baseline(record, project_dir)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record.update(
            {
                "status": "running",
                "phase": "running",
                "startedAt": now(),
                "watcherPid": os.getpid(),
                "watcherAlive": True,
                "nextOwner": "Transport",
            }
        )
        save_run(record)
        append_event(run_id, "transport_run_started", target=record.get("target"), timeoutSeconds=timeout_seconds)

        with prompt_path.open("r", encoding="utf-8") as prompt_handle, log_path.open("a", encoding="utf-8") as log_handle:
            proc = subprocess.Popen(
                [str(part) for part in command],
                cwd=str(record.get("projectDir") or ROOT),
                text=True,
                stdin=prompt_handle,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )

            record["targetPid"] = proc.pid
            save_run(record)
            append_event(run_id, "transport_target_started", targetPid=proc.pid)

            last_log_size = file_info(str(log_path)).get("size") or 0
            last_change = time.time()
            last_heartbeat = 0.0
            quiet_emitted = False
            returning_emitted = False
            result_status = ""
            exit_code: int | None = None

            while True:
                exit_code = proc.poll()
                log_snapshot = file_info(str(log_path))
                log_size = int(log_snapshot.get("size") or 0)
                if log_size != last_log_size:
                    last_log_size = log_size
                    last_change = time.time()
                    record["lastLogAt"] = now()
                    record["quietSeconds"] = 0
                    if record.get("status") == "stale":
                        record["status"] = "running"
                        record["phase"] = "running"
                        append_event(run_id, "transport_resumed", logSize=log_size)
                    quiet_emitted = False

                if (output_path.exists() or report_path.exists()) and not returning_emitted:
                    record["phase"] = "returning"
                    returning_emitted = True
                    append_event(
                        run_id,
                        "transport_artifact_seen",
                        outputExists=output_path.exists(),
                        reportExists=report_path.exists(),
                    )

                if exit_code is not None:
                    break

                elapsed = time.time() - started
                if elapsed >= timeout_seconds:
                    result_status = "timeout"
                    append_event(run_id, "transport_timeout", timeoutSeconds=timeout_seconds)
                    try:
                        kill_process_group(proc.pid, signal.SIGTERM)
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        kill_process_group(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=5)
                    except ProcessLookupError:
                        pass
                    exit_code = proc.returncode
                    break

                heartbeat_due = time.time() - last_heartbeat >= heartbeat_seconds
                idle_seconds = time.time() - last_change
                if heartbeat_due:
                    last_heartbeat = time.time()
                    record["lastHeartbeatAt"] = now()
                    record["idleSeconds"] = round(idle_seconds, 3)
                    record["watcherAlive"] = True
                    record["targetAlive"] = True

                if idle_seconds >= stale_seconds and not quiet_emitted:
                    record["quietSeconds"] = round(idle_seconds, 3)
                    record["lastHeartbeatAt"] = now()
                    record["artifacts"] = artifacts_for(record)
                    save_run(record)
                    append_event(run_id, "transport_quiet", quietSeconds=round(idle_seconds, 3), thresholdSeconds=stale_seconds, logSize=log_size)
                    quiet_emitted = True

                record["artifacts"] = artifacts_for(record)
                record["durationSeconds"] = round(elapsed, 3)
                save_run(record)
                time.sleep(max(0.2, poll_seconds))

        duration = round(time.time() - started, 3)
        report_mirrored = mirror_output_to_report(output_path, report_path, run_id)
        completion_validation = validate_completion_record(record, emit=True)
        output_exists = output_path.exists()
        report_exists = report_path.exists()
        if exit_code == 78:
            result_status = "failed_preflight"
        elif completion_validation.get("status") != "ok":
            result_status = str(completion_validation.get("status") or "failed_completion_validation")
        elif not result_status:
            if exit_code == 0 and output_exists and report_exists:
                result_status = "ok"
            elif output_exists or report_exists:
                result_status = "partial"
            else:
                result_status = "failed"

        receipt_updates: dict[str, Any] = {
            "status": result_status,
            "exitCode": exit_code,
            "durationSeconds": duration,
            "completedAt": now(),
            "nextOwner": "Manager",
            "transport": {
                "runId": run_id,
                "watcherPid": os.getpid(),
                "targetPid": record.get("targetPid"),
                "nextOwner": "Manager",
                "reportMirroredFromOutput": report_mirrored,
            },
            "completionValidation": completion_validation,
        }
        if output_exists:
            receipt_updates["answer"] = read_text_if_exists(str(output_path))
        if report_exists:
            receipt_updates["reportText"] = read_text_if_exists(str(report_path))
        target_label = str(record.get("targetRole") or record.get("target") or "target")
        if completion_validation.get("error"):
            receipt_updates["error"] = str(completion_validation["error"])
        if result_status == "failed_preflight":
            receipt_updates["error"] = f"{target_label} preflight failed; see agent log and report artifact"
        if result_status == "failed":
            receipt_updates["error"] = f"{target_label} finished without output/report artifacts"
        if result_status == "timeout":
            receipt_updates["error"] = f"{target_label} timed out after {timeout_seconds}s"

        receipt = write_receipt(record, receipt_updates)
        record.update(
            {
                "status": result_status,
                "phase": "returned",
                "resultStatus": result_status,
                "exitCode": exit_code,
                "durationSeconds": duration,
                "completedAt": receipt_updates["completedAt"],
                "nextOwner": "Manager",
                "watcherAlive": False,
                "targetAlive": False,
                "artifacts": artifacts_for(record),
            }
        )
        if receipt.get("error"):
            record["error"] = receipt["error"]
        save_run(record)
        append_event(
            run_id,
            "transport_return_ready",
            resultStatus=result_status,
            exitCode=exit_code,
            nextOwner="Manager",
            target=record.get("target"),
            targetRole=record.get("targetRole"),
            parentRunId=record.get("parentRunId"),
            intentId=record.get("intentId"),
            report=str(report_path) if report_exists else "",
            reportMirroredFromOutput=report_mirrored,
        )
        append_manager_inbox(
            {
                "runId": run_id,
                "type": "transport_return",
                "target": record.get("target"),
                "targetRole": record.get("targetRole"),
                "parentRunId": record.get("parentRunId"),
                "intentId": record.get("intentId"),
                "summary": f"{record.get('targetRole') or record.get('target')} returned {result_status}.",
                "resultStatus": result_status,
                "report": str(report_path) if report_exists else "",
                "receipt": str(paths.get("receipt", "")),
                "nextOwner": "Manager",
            }
        )
        return public_run(record)
    finally:
        release_lock(run_id)


def wait_for_run(run_id: str, wait_seconds: int = 900, poll_seconds: float = DEFAULT_POLL_SECONDS) -> dict[str, Any]:
    deadline = time.time() + max(0, wait_seconds)
    while True:
        record = load_run(run_id, include_archive=True)
        if not record:
            return {"status": "missing", "runId": run_id, "error": "transport run not found"}
        public = public_run(record)
        status = str(public.get("status") or "")
        phase = str(public.get("phase") or "")
        if status in RETURNABLE_STATUSES or phase == "returned":
            return public
        if time.time() >= deadline:
            public["watchStatus"] = "wait-timeout"
            return public
        time.sleep(max(0.2, poll_seconds))


def return_payload(run_id: str, include_text: bool = True, text_limit: int = 120_000) -> dict[str, Any]:
    record = load_run(run_id or latest_run_id(), include_archive=True)
    if not record:
        return {"status": "missing", "runId": run_id, "error": "transport run not found"}
    public = public_run(record)
    paths = public.get("paths", {})
    payload = {"status": public.get("status"), "run": public}
    if include_text:
        payload["reportText"] = read_text_if_exists(paths.get("report"), limit=text_limit)
        payload["outputText"] = read_text_if_exists(paths.get("output"), limit=text_limit)
    payload["receipt"] = read_json(Path(str(paths.get("receipt", ""))), {})
    return payload


def ack_run(run_id: str, note: str = "") -> dict[str, Any]:
    record = load_run(run_id or latest_run_id(), include_archive=False)
    if not record:
        return {"status": "missing", "runId": run_id, "error": "transport run not found"}
    record["acknowledgedAt"] = now()
    record["acknowledgedBy"] = "Manager"
    if note:
        record["acknowledgementNote"] = note
    if record.get("status") in TERMINAL_STATUSES:
        record["phase"] = "acknowledged"
    record["nextOwner"] = "Archive"
    save_run(record)
    append_event(str(record["runId"]), "transport_acknowledged", nextOwner="Archive", note=note)
    return public_run(record)


def maybe_compact_log(record: dict[str, Any], max_log_bytes: int) -> dict[str, Any] | None:
    if max_log_bytes <= 0:
        return None
    log_path = Path(str(record.get("paths", {}).get("log", "")))
    try:
        stat = log_path.stat()
    except OSError:
        return None
    if stat.st_size <= max_log_bytes:
        return None
    gz_path = log_path.with_suffix(log_path.suffix + ".gz")
    if not gz_path.exists():
        with log_path.open("rb") as src, gzip.open(gz_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
    tail_bytes = max(32_000, min(250_000, max_log_bytes // 4))
    with log_path.open("rb") as src:
        src.seek(max(0, stat.st_size - tail_bytes))
        tail = src.read()
    note = f"[transport cleanup compacted full log to {gz_path} at {now()}]\n".encode()
    log_path.write_bytes(note + tail)
    return {"log": str(log_path), "gz": str(gz_path), "originalBytes": stat.st_size, "tailBytes": len(tail)}


def cleanup(
    archive_after_hours: float = 24,
    orphan_after_seconds: int = 900,
    max_events: int = 5000,
    max_log_bytes: int = 0,
    dry_run: bool = False,
) -> dict[str, Any]:
    ensure_dirs()
    actions: list[dict[str, Any]] = []
    cutoff = time.time() - max(0, archive_after_hours) * 3600
    orphan_cutoff = time.time() - max(0, orphan_after_seconds)

    for path in sorted(RUNS_STATE_DIR.glob("*.json")):
        record = read_json(path, {})
        if not record:
            continue
        record = refresh_record(record)
        run_id = str(record.get("runId") or path.stem)
        status = str(record.get("status") or "")
        updated_ts = parse_time(record.get("updatedAt")) or path.stat().st_mtime

        if status in ACTIVE_STATUSES and updated_ts < orphan_cutoff:
            if not pid_alive(record.get("watcherPid")) and not pid_alive(record.get("targetPid")):
                action = {"action": "mark-orphaned", "runId": run_id}
                actions.append(action)
                if not dry_run:
                    record["status"] = "orphaned"
                    record["phase"] = "returned"
                    record["resultStatus"] = "orphaned"
                    record["nextOwner"] = "Manager"
                    record["error"] = "cleanup found no alive watcher or target process"
                    save_run(record)
                    append_event(run_id, "transport_cleanup_orphaned", nextOwner="Manager")
                continue

        if max_log_bytes > 0 and status in RETURNABLE_STATUSES:
            compacted = None if dry_run else maybe_compact_log(record, max_log_bytes=max_log_bytes)
            if compacted:
                actions.append({"action": "compact-log", "runId": run_id, **compacted})

        if status in RETURNABLE_STATUSES and (record.get("acknowledgedAt") or updated_ts < cutoff):
            action = {"action": "archive-state", "runId": run_id, "from": str(path), "to": str(archive_state_path(run_id))}
            actions.append(action)
            if not dry_run:
                record["archivedAt"] = now()
                write_json_atomic(archive_state_path(run_id), record)
                try:
                    path.unlink()
                except OSError:
                    pass
                append_event(run_id, "transport_archived", archive=str(archive_state_path(run_id)))

    event_actions = rotate_events(max_events=max_events, dry_run=dry_run)
    actions.extend(event_actions)
    return {"generatedAt": now(), "status": "ok", "dryRun": dry_run, "actions": actions, "stateDir": str(TRANSPORT_DIR)}


def rotate_events(max_events: int, dry_run: bool) -> list[dict[str, Any]]:
    if max_events <= 0 or not EVENTS_FILE.exists():
        return []
    lines = EVENTS_FILE.read_text(encoding="utf-8").splitlines()
    if len(lines) <= max_events:
        return []
    archive_name = f"events-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
    archive_path = ARCHIVE_DIR / archive_name
    keep = lines[-max_events:]
    drop = lines[:-max_events]
    action = {"action": "rotate-events", "archivedLines": len(drop), "keptLines": len(keep), "archive": str(archive_path)}
    if not dry_run:
        archive_path.write_text("\n".join(drop) + "\n", encoding="utf-8")
        EVENTS_FILE.write_text("\n".join(keep) + "\n", encoding="utf-8")
    return [action]


def cli() -> int:
    parser = argparse.ArgumentParser(description="Nogra transport watcher/runtime")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the watcher for one transport run.")
    run.add_argument("run_id")
    run.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)

    status = sub.add_parser("status", help="Return transport status JSON.")
    status.add_argument("run_id", nargs="?", default="")
    status.add_argument("--limit", type=int, default=20)
    status.add_argument("--include-archive", action="store_true")

    watch = sub.add_parser("watch", help="Wait for a run to return.")
    watch.add_argument("run_id")
    watch.add_argument("--wait-seconds", type=int, default=900)

    ret = sub.add_parser("return", help="Return report/output payload for a run.")
    ret.add_argument("run_id", nargs="?", default="")

    ack = sub.add_parser("ack", help="Acknowledge a returned run.")
    ack.add_argument("run_id", nargs="?", default="")
    ack.add_argument("--note", default="")

    clean = sub.add_parser("cleanup", help="Clean transport state.")
    clean.add_argument("--archive-after-hours", type=float, default=24)
    clean.add_argument("--orphan-after-seconds", type=int, default=900)
    clean.add_argument("--max-events", type=int, default=5000)
    clean.add_argument("--max-log-bytes", type=int, default=0)
    clean.add_argument("--dry-run", action="store_true")

    events = sub.add_parser("events", help="Read transport events.")
    events.add_argument("--run-id", default="")
    events.add_argument("--limit", type=int, default=80)

    args = parser.parse_args()
    if args.command == "run":
        payload = watch_run(args.run_id, poll_seconds=args.poll_seconds)
    elif args.command == "status":
        if args.run_id:
            record = load_run(args.run_id, include_archive=args.include_archive)
            payload = public_run(record) if record else {"status": "missing", "runId": args.run_id}
        else:
            payload = {"status": "ok", "runs": recent_runs(limit=args.limit, include_archive=args.include_archive)}
    elif args.command == "watch":
        payload = wait_for_run(args.run_id, wait_seconds=args.wait_seconds)
    elif args.command == "return":
        payload = return_payload(args.run_id)
    elif args.command == "ack":
        payload = ack_run(args.run_id, note=args.note)
    elif args.command == "cleanup":
        payload = cleanup(
            archive_after_hours=args.archive_after_hours,
            orphan_after_seconds=args.orphan_after_seconds,
            max_events=args.max_events,
            max_log_bytes=args.max_log_bytes,
            dry_run=args.dry_run,
        )
    elif args.command == "events":
        payload = {"status": "ok", "events": read_events(limit=args.limit, run_id=args.run_id)}
    else:
        payload = {"status": "invalid", "error": args.command}

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") not in {"missing", "failed"} else 1


if __name__ == "__main__":
    raise SystemExit(cli())
