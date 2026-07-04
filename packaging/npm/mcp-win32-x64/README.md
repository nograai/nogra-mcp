# @nograai/mcp-win32-x64

Native `nogra-mcp` binary for Windows x64.

SCAFFOLD — CI-populated. This directory intentionally contains NO binary in
the source tree. The release CI matrix (Phase C) builds `nogra-mcp.exe` on a
native Windows x64 runner via the platform build script and places it here
before `npm publish`. Publishing this package without the binary is a
release-pipeline error.

Do not install this package directly — install `@nograai/mcp`.
