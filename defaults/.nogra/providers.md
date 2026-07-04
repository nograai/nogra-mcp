# Providers

V1 public MCP validation does not call providers. The customer-owned Claude Code client executes work with its own auth.

## Defaults

- manager: anthropic:opus
- agent: anthropic:sonnet
- targetModel: anthropic:sonnet

## Contract

- target is the workflow role, for example agent.
- targetModel is the wildcard provider:model label, for example anthropic:sonnet.
- OpenAI, Gemini and local adapters are future-provider slots, not V1 hosted defaults.
