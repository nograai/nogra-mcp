# Nogra MCP

Canonical full Nogra MCP server for the Y26 workspace.

Nogra MCP is a separate primitive from the Nogra plugin. The plugin is the
user-facing surface; MCP is the thin bridge/control-plane interface that lets
Nogra and Code/tools/other surfaces talk both ways. MCP is not Pro, and Pro is
not required for the bridge.

Current public plugin defaults can work without this server by using bundled
contracts, `scripts/nogra-local.mjs` and workspace-local `.nogra/` records. A
plugin or workspace can connect Nogra MCP when it needs a real protocol bridge
instead of only local filesystem state.

Local/private development should be registered as `nogra-dev`. The `nogra`
MCP name is reserved for the public hosted/plugin path.

Run:

```bash
manager/bin/nogra-mcp --self-test
manager/bin/nogra-mcp --inventory
```
