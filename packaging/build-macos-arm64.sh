#!/bin/bash
# Back-compat wrapper for the portable build driver (Phase C1).
#
# All the real logic (uv-resolved deps, PyInstaller build from
# packaging/nogra-mcp.spec, private-module assert) now lives in
# packaging/build.py so the exact same driver runs unmodified on macOS,
# Linux and Windows CI runners. This script is kept only so existing
# invocations/docs (`./packaging/build-macos-arm64.sh`) keep working
# unchanged on this machine.
#
# Requirements on the BUILD machine (dev/CI only — never the user machine):
#   - uv (https://docs.astral.sh/uv/)
#   - Xcode CLT (for codesign; PyInstaller ad-hoc re-signs the binary)
#
# Output: packaging/dist/nogra-mcp   (single-file executable, ~17-18 MB)
# Intermediates: packaging/build/    (safe to delete; recreated every build)
#
# Usage: ./packaging/build-macos-arm64.sh   (from anywhere; paths self-anchor)

set -euo pipefail

PACKAGING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec uv run python "$PACKAGING_DIR/build.py" "$@"
