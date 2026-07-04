# @nograai/mcp-linux-arm64

Native `nogra-mcp` binary for Linux arm64.

SCAFFOLD — CI-populated. This directory intentionally contains NO binary in
the source tree. The release CI matrix (Phase C) builds `nogra-mcp` on a
native Linux arm64 runner via the platform build script and places it here
before `npm publish`. Publishing this package without the binary is a
release-pipeline error.

Do not install this package directly — install `@nograai/mcp`.
