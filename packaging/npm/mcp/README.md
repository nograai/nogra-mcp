# @nograai/mcp

Nogra MCP server for npm/npx installs — no Python, uv or pipx required on the
user machine.

This package ships a tiny Node selector (`bin/nogra-mcp.js`). The actual
server is a self-contained native binary delivered through per-platform
packages declared as optionalDependencies (esbuild-style layout):

| package                    | os     | cpu   |
| -------------------------- | ------ | ----- |
| `@nograai/mcp-darwin-arm64` | darwin | arm64 |
| `@nograai/mcp-darwin-x64`   | darwin | x64   |
| `@nograai/mcp-linux-x64`    | linux  | x64   |
| `@nograai/mcp-linux-arm64`  | linux  | arm64 |
| `@nograai/mcp-win32-x64`    | win32  | x64   |

npm installs only the package matching the current machine. The selector
resolves the binary with `require.resolve`, spawns it with stdio passthrough,
forwards SIGTERM/SIGINT and passes the exit code through. It never installs
anything and never makes network calls. On an unsupported platform or a
missing platform package it prints one explanatory stderr line and exits
non-zero.

Usage with an MCP client (e.g. Claude Code `.mcp.json`):

```json
{
  "mcpServers": {
    "nogra": { "command": "npx", "args": ["-y", "@nograai/mcp"] }
  }
}
```

Versioning: all packages here version in lockstep with the `nogra-mcp` PyPI
package (1.0.0).
