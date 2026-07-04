# @nograai/mcp-darwin-arm64

Native `nogra-mcp` binary for macOS arm64 (Apple Silicon).

Do not install this package directly — install `@nograai/mcp`, which declares
all platform packages as optionalDependencies and selects the right one at
runtime via its `nogra-mcp` bin selector.

The `nogra-mcp` file in this package is the self-contained PyInstaller onefile
build produced by `packaging/build-macos-arm64.sh` (build-hardened: private
modules excluded and asserted absent, package data bundled).
