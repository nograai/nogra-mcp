# Nogra MCP

The MCP server behind [Nogra](https://nogra.ai) — brief, GO, dispatch,
evidence, verify for AI-assisted work. This package is the protocol bridge:
32 public tools for briefs, dispatch transport, run events, registry and
redaction, served over MCP stdio against the current workspace's local
`.nogra/` records.

## Install

Usually nothing to install: the Nogra Claude Code plugin starts this server
automatically through its bundled launcher (`npx` first, `uvx`/`pipx` as
fallbacks). Standalone:

```bash
npx -y @nograai/mcp   # npm path — standalone platform binaries, no Python needed
uvx nogra-mcp         # PyPI path — needs uv on PATH
```

Run it from a workspace folder; it reads and writes that workspace's
`.nogra/` records.

## What it serves

Public mode only: 32 tools covering brief save/validate/promote, dispatch
handoffs, transport lifecycle (dispatch, status, events, return), run
records, the contract registry and text redaction. Everything stays in local
markdown/JSON files the user owns — the server does zero model inference,
makes no network calls of its own, and never touches credentials.

## Naming

The `nogra` MCP server name is reserved for the public plugin path. If you
develop against a local checkout, register it under a different name (for
example `nogra-dev`) so the two never collide.

<!-- mcp-name: io.github.nograai/nogra-mcp -->

