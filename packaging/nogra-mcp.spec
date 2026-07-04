# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the standalone nogra-mcp binary (Phase B hardened).

Build from the package root via packaging/build-macos-arm64.sh, or directly:

    uv run --with pyinstaller -- pyinstaller packaging/nogra-mcp.spec

Paths are anchored on SPECPATH (this file's directory = packaging/), so the
spec is location-independent as long as the repo layout (src/nogra_mcp,
packaging/entry_point.py) is intact.

Result (macOS-arm64, PyInstaller 6.21.0, Python 3.12, mcp 1.27.0,
pydantic 2.13.3): NO extra hiddenimports or hooks were required. The bundled
_pyinstaller_hooks_contrib stdhooks for anyio, pydantic, uvicorn, jsonschema
and rich covered everything. See packaging/NOTES.md for the full build log
evidence and measurements.

Phase B hardening (locked decision, see packaging/NOTES.md "Phase B" section
for the full investigation trail):

- excludes: `nogra_mcp.y26_private` is Y26-internal private doctrine/legacy
  Codex-adapter surface (host-only per BOUNDARY.md; gated off by default via
  NOGRA_ENABLE_PRIVATE and never reachable from this distributed binary's
  default env). It is explicitly excluded from Analysis so its code is not
  merely inert, but physically absent from the built artifact.
- datas: package-data directories actually read via package_root()-relative
  paths in src/nogra_mcp/server.py (read_package_text/read_package_json/
  default_nogra_dir) are bundled so resource-reading tools (e.g. the `init`
  tool) return real content instead of PUBLIC_RESOURCE_MISSING fallbacks.
  `roles.json` at the package root is NOT bundled: it is referenced only by
  runtime_server.py's Y26-private control-plane path resolution
  (`ROOT / "manager" / "nogra-mcp" / "roles.json"`), a different, host-only
  path unrelated to package_root() — verified by source read, not needed by
  the public standalone binary.
"""

import os

PACKAGING_DIR = SPECPATH  # PyInstaller injects SPECPATH = dir of this spec
PACKAGE_ROOT = os.path.dirname(PACKAGING_DIR)
SRC_DIR = os.path.join(PACKAGE_ROOT, "src")


def _pkg_data(relative: str) -> tuple[str, str]:
    """(source dir under PACKAGE_ROOT, dest dir under sys._MEIPASS at runtime).

    Dest mirrors the same relative path so package_root()-relative reads
    (once package_root() resolves to sys._MEIPASS via the NOGRA_MCP_ROOT
    bridge set in packaging/entry_point.py) find the files exactly where the
    unfrozen source tree would have them.
    """
    return (os.path.join(PACKAGE_ROOT, relative), relative)


a = Analysis(
    [os.path.join(PACKAGING_DIR, "entry_point.py")],
    pathex=[SRC_DIR],
    binaries=[],
    datas=[
        _pkg_data("schemas"),
        _pkg_data("templates"),
        _pkg_data(os.path.join("examples", "objects")),
        _pkg_data("toolbank"),
        _pkg_data("init-bundle"),
        _pkg_data("defaults"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Y26-private doctrine/legacy-Codex-adapter module: never ship it, see
    # docstring above and packaging/NOTES.md "Phase B" for the full trail.
    excludes=["nogra_mcp.y26_private"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="nogra-mcp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # native arch of the build host (arm64 here)
    codesign_identity=None,  # ad-hoc re-sign by PyInstaller; real signing is a Phase C concern
    entitlements_file=None,
)
