"""Build gate: FAIL if Y26-private material is present in the frozen binary.

Usage (run under the same env as the build, PyInstaller importable):

    uv run --with pyinstaller -- python packaging/assert_no_private.py packaging/dist/nogra-mcp

Exit 0 = clean. Exit 1 = private material found (build must fail).
Exit 2 = could not inspect the artifact (also a build failure — never ship
uninspected).

WHY NOT `strings | grep`: PyInstaller onefile stores all pure-Python modules
zlib-compressed inside the embedded PYZ archive. Plain `strings` on the
executable finds almost nothing — empirically, even identifiers that are
definitely present (e.g. `transport_dispatch`, `pydantic`, `nogra_mcp`)
return ZERO hits on this artifact. A strings-grep "proof of absence" is
therefore vacuous, not evidence. This gate instead inspects the archive
structurally, which is both sound (checks what the import system can actually
load) and demonstrably falsifiable (run it against a binary built without the
spec's `excludes=["nogra_mcp.y26_private"]` — it fails; see packaging/NOTES.md
for the recorded demo).

Two checks:

1. MODULE TOC: list every module name in the CArchive top level and in the
   embedded PYZ archive's table of contents. Any module matching
   `y26_private` (e.g. `nogra_mcp.y26_private`) => FAIL.
2. DECOMPRESSED PAYLOAD: walk every module's code object (names, varnames,
   consts, filenames, qualnames — recursively into nested code objects) for
   the three tool-name strings that exist ONLY in the private module:
   `y26_role_graph`, `y26_workflow_spine`, `y26_brief_template` => any hit
   FAILS and is attributed to the module it came from.

Deliberately NOT asserted: `codex_dispatch` / `codex_fresh_eyes` substrings.
Those names legitimately occur in required PUBLIC modules (the static
capability catalog in nogra_mcp/registry.py and the transport_dispatch
`codex_pm` target implementation in nogra_mcp/runtime.py /
nogra_mcp/runtime_server.py), so asserting on them would fail every build
forever regardless of the private module's absence. The private module's
*registration* of those tools is covered by check 1 (the module itself is
absent) and by the 32-tool handshake gate (no y26_*/codex_* tool names are
served).
"""
from __future__ import annotations

import re
import sys

from PyInstaller.archive.readers import CArchiveReader

FORBIDDEN_MODULE_RE = re.compile(r"y26_private")
FORBIDDEN_STRINGS = ("y26_role_graph", "y26_workflow_spine", "y26_brief_template")


def walk_code(code, acc: set) -> None:
    acc.update(n for n in code.co_names if isinstance(n, str))
    acc.update(v for v in code.co_varnames if isinstance(v, str))
    if code.co_filename:
        acc.add(code.co_filename)
    qualname = getattr(code, "co_qualname", None)
    if qualname:
        acc.add(qualname)
    acc.add(code.co_name)
    for const in code.co_consts:
        if isinstance(const, str):
            acc.add(const)
        elif type(const).__name__ == "code":
            walk_code(const, acc)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: assert_no_private.py <frozen-binary>", file=sys.stderr)
        return 2

    exe_path = argv[0]
    try:
        car = CArchiveReader(exe_path)
    except Exception as exc:  # noqa: BLE001
        print(f"ASSERT ERROR: cannot open CArchive in {exe_path}: {exc}", file=sys.stderr)
        return 2

    failures: list[str] = []

    # Check 1a: CArchive top-level entries (covers modules placed outside PYZ).
    top_bad = sorted(n for n in car.toc if FORBIDDEN_MODULE_RE.search(n))
    for name in top_bad:
        failures.append(f"CArchive top-level entry matches y26_private: {name}")

    # Check 1b + 2: embedded PYZ module TOC + decompressed payload scan.
    pyz_names = [n for n, entry in car.toc.items() if entry[-1] == "z"]
    if not pyz_names:
        print("ASSERT ERROR: no embedded PYZ archive found — cannot verify", file=sys.stderr)
        return 2

    scanned = 0
    for pyz_name in pyz_names:
        try:
            za = car.open_embedded_archive(pyz_name)
        except Exception as exc:  # noqa: BLE001
            print(f"ASSERT ERROR: cannot open {pyz_name}: {exc}", file=sys.stderr)
            return 2

        module_names = list(za.toc.keys())
        toc_bad = sorted(n for n in module_names if FORBIDDEN_MODULE_RE.search(n))
        for name in toc_bad:
            failures.append(f"PYZ module TOC contains private module: {name}")

        for name in module_names:
            try:
                code = za.extract(name)
            except Exception as exc:  # noqa: BLE001
                print(f"ASSERT ERROR: cannot extract module {name}: {exc}", file=sys.stderr)
                return 2
            if code is None:
                continue
            scanned += 1
            strs: set = set()
            walk_code(code, strs)
            blob = "\n".join(strs)
            for pat in FORBIDDEN_STRINGS:
                if pat in blob:
                    failures.append(f"decompressed payload of module {name} contains: {pat}")

    if failures:
        print(f"PRIVATE-MODULE ASSERT: FAIL ({len(failures)} finding(s), {scanned} modules scanned)")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"PRIVATE-MODULE ASSERT: PASS ({scanned} modules scanned, 0 y26_private modules, 0 private tool-name strings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
