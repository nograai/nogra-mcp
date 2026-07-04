#!/usr/bin/env python3
"""Portable cross-platform build driver for the standalone nogra-mcp binary.

Identical invocation on macOS / Linux / Windows CI runners:

    uv run python packaging/build.py [--smoke]

Steps (same on every platform):

  1. Resolve the package's locked deps (uv.lock) into an ephemeral env and
     layer PyInstaller on top via `uv run --with pyinstaller`.
  2. Build from packaging/nogra-mcp.spec (native arch of the host; the matrix
     covers all 5 platforms by running this same driver on 5 runners).
  3. Run packaging/assert_no_private.py against the built binary — the
     structural PYZ-TOC gate that fails the build if nogra_mcp.y26_private
     leaked in (see packaging/NOTES.md "Phase B").
  4. Optionally (--smoke) chain packaging/ci_smoke.py against the freshly
     built binary — the full JSON-RPC handshake + 32-tool boundary gate.

This script has no third-party imports itself (stdlib only): it only shells
out to `uv`. packaging/build-macos-arm64.sh is now a thin back-compat wrapper
that calls this driver; CI calls this driver directly on all 5 platforms.

Windows note: PyInstaller's `name="nogra-mcp"` in the spec produces
`nogra-mcp.exe` automatically on win32 — BINARY_NAME below accounts for that
so --smoke (and any caller) can find the right output file without any
bash-isms or platform-specific shell logic.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = PACKAGING_DIR.parent
BUILD_DIR = PACKAGING_DIR / "build"
DIST_DIR = PACKAGING_DIR / "dist"
SPEC_FILE = PACKAGING_DIR / "nogra-mcp.spec"
ASSERT_SCRIPT = PACKAGING_DIR / "assert_no_private.py"
SMOKE_SCRIPT = PACKAGING_DIR / "ci_smoke.py"

BINARY_NAME = "nogra-mcp.exe" if sys.platform == "win32" else "nogra-mcp"
BINARY_PATH = DIST_DIR / BINARY_NAME


def run(cmd: list[str]) -> None:
    print(f"==> {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True, cwd=str(PACKAGE_ROOT))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="chain packaging/ci_smoke.py against the built binary after the assert passes",
    )
    args = parser.parse_args(argv)

    uv = shutil.which("uv")
    if uv is None:
        print("ERROR: uv not found on PATH (install: https://docs.astral.sh/uv/)", file=sys.stderr)
        return 1

    print(f"==> package root: {PACKAGE_ROOT}")
    try:
        run([uv, "--version"])

        # Clean previous build artifacts so every run is from scratch (same
        # behavior as the original build-macos-arm64.sh).
        for d in (BUILD_DIR, DIST_DIR):
            if d.exists():
                shutil.rmtree(d)

        # uv run: project env from pyproject.toml/uv.lock; --with pyinstaller
        # layers the build tool on top without touching the lockfile. This
        # exact invocation is identical on macOS, Linux and Windows.
        run(
            [
                uv,
                "run",
                "--with",
                "pyinstaller",
                "--",
                "pyinstaller",
                "--workpath",
                str(BUILD_DIR),
                "--distpath",
                str(DIST_DIR),
                "--noconfirm",
                str(SPEC_FILE),
            ]
        )

        if not BINARY_PATH.exists():
            print(f"ERROR: expected built binary not found: {BINARY_PATH}", file=sys.stderr)
            return 1

        size = BINARY_PATH.stat().st_size
        print()
        print("==> built:")
        print(f"{BINARY_PATH} ({size:,} bytes)")

        print()
        print("==> private-module assert (PYZ TOC + decompressed payload):")
        # Structural gate: the frozen archive must contain no
        # nogra_mcp.y26_private module and none of the y26-only tool-name
        # strings. Non-zero exit here fails the whole build. See
        # packaging/assert_no_private.py and packaging/NOTES.md for why plain
        # `strings | grep` is not valid evidence on onefile artifacts.
        run(
            [
                uv,
                "run",
                "--with",
                "pyinstaller",
                "--",
                "python",
                str(ASSERT_SCRIPT),
                str(BINARY_PATH),
            ]
        )

        if args.smoke:
            print()
            print("==> smoke test (packaging/ci_smoke.py):")
            run([sys.executable, str(SMOKE_SCRIPT), str(BINARY_PATH)])

    except subprocess.CalledProcessError as exc:
        print(f"\nBUILD FAILED: {' '.join(exc.cmd)} exited {exc.returncode}", file=sys.stderr)
        return exc.returncode if exc.returncode else 1

    print()
    print(f"Done. Binary: {BINARY_PATH}")
    print(f"Intermediates in {BUILD_DIR} can be removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
