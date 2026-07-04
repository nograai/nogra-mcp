# Nogra Local Pinboard Renderer

This optional renderer serves a live pinboard from the workspace's `.nogra/`
records. It is a viewer only: no hooks, no watchers, no enforcement and no
background process unless you start it.

The optional bundle installs the visible pinboard HTML plus this renderer. Core
`/nogra init` works without these files.

## Start

From the workspace root:

```bash
node nogra/pinboard/server.mjs --port 7777
```

Open:

```text
http://127.0.0.1:7777
```

The renderer also exposes a versioned JSON contract for custom UIs:

```text
http://127.0.0.1:7777/api/state
```

The response schema is `nogra.pinboard.state.v1`.

## Options

Use another port:

```bash
node nogra/pinboard/server.mjs --port 7778
```

Serve another workspace explicitly:

```bash
node nogra/pinboard/server.mjs --root /path/to/workspace --port 7777
```

## Stop

Use `Ctrl-C` in the terminal running the renderer.

## Troubleshooting

- `Nogra workspace not found`: start from the workspace root, or pass
  `--root /path/to/workspace`.
- `Port 7777 is already in use`: run with another port, for example
  `--port 7778`.
- Empty pinboard: Nogra is installed, but no local `.nogra/` records have been
  written yet. Create a brief or dispatch a run first.
