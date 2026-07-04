"""PyInstaller entry point for the standalone nogra-mcp binary.

Thin wrapper around the real console-script target (`nogra_mcp.server:main`,
per pyproject.toml `[project.scripts]`). Kept as a separate file (rather than
pointing PyInstaller at src/nogra_mcp/server.py directly) so the frozen
executable's `__main__` module name stays stable regardless of source layout.

Frozen package-data bridge (Phase B): in the onefile binary, bundled datas
(schemas/, templates/, examples/objects/, toolbank/, init-bundle/, defaults/)
are extracted under `sys._MEIPASS`, but `nogra_mcp.server.package_root()`
falls back to a source-layout-relative path when no env override is set.
Pointing the existing `NOGRA_MCP_ROOT` override at `sys._MEIPASS` (only when
frozen, and only when the caller has not set it) makes package_root()-relative
resource reads resolve to the bundled datas. This is a packaging asset — no
server-source change; an explicit user-provided NOGRA_MCP_ROOT still wins.
"""
from __future__ import annotations

import os
import sys

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    os.environ.setdefault("NOGRA_MCP_ROOT", sys._MEIPASS)

from nogra_mcp.server import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
