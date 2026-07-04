#!/usr/bin/env node

// @nograai/mcp — platform binary selector (esbuild-style layout).
//
// The real nogra-mcp server is a self-contained native binary shipped in
// per-platform packages (@nograai/mcp-<platform>-<arch>), declared as
// optionalDependencies of this package so npm installs exactly the one that
// matches the current machine.
//
// Contract (mirrors the Nogra plugin's scripts/mcp-launcher.mjs):
//   1. Map process.platform + process.arch to the platform package and
//      require.resolve the binary inside it.
//   2. Spawn it with full stdio passthrough (stdin/stdout/stderr "inherit")
//      and forward its exit code.
//   3. Unsupported platform, or platform package not installed: write
//      exactly ONE explanatory line to stderr and exit non-zero.
//   4. This selector NEVER installs anything and NEVER makes a network
//      call — it only executes a binary that npm already placed on disk.
//   5. SIGTERM/SIGINT received by this selector are forwarded to the child
//      so MCP clients can stop the server cleanly.
//
// Testing hook: NOGRA_MCP_PLATFORM_OVERRIDE="<platform>-<arch>" overrides
// the detected platform/arch pair. Used by packaging E2E tests to prove the
// unsupported-platform path; harmless in production (unset = real values).

import process from "node:process";
import { createRequire } from "node:module";
import { spawn } from "node:child_process";

const require = createRequire(import.meta.url);

const SIGNAL_EXIT_CODE = { SIGINT: 130, SIGTERM: 143 };

const SUPPORTED = {
  "darwin-arm64": { pkg: "@nograai/mcp-darwin-arm64", bin: "nogra-mcp" },
  "darwin-x64": { pkg: "@nograai/mcp-darwin-x64", bin: "nogra-mcp" },
  "linux-x64": { pkg: "@nograai/mcp-linux-x64", bin: "nogra-mcp" },
  "linux-arm64": { pkg: "@nograai/mcp-linux-arm64", bin: "nogra-mcp" },
  "win32-x64": { pkg: "@nograai/mcp-win32-x64", bin: "nogra-mcp.exe" },
};

const key =
  process.env.NOGRA_MCP_PLATFORM_OVERRIDE || `${process.platform}-${process.arch}`;

const target = SUPPORTED[key];
if (!target) {
  process.stderr.write(
    `nogra-mcp: unsupported platform ${key} (supported: ${Object.keys(SUPPORTED).join(", ")})\n`,
  );
  process.exit(1);
}

let binaryPath;
try {
  binaryPath = require.resolve(`${target.pkg}/${target.bin}`);
} catch {
  process.stderr.write(
    `nogra-mcp: platform package ${target.pkg} is not installed (reinstall @nograai/mcp so npm can fetch the matching binary for ${key})\n`,
  );
  process.exit(1);
}

const child = spawn(binaryPath, process.argv.slice(2), { stdio: "inherit" });

const forwardSignal = (signal) => {
  if (!child.killed) child.kill(signal);
};
process.on("SIGTERM", () => forwardSignal("SIGTERM"));
process.on("SIGINT", () => forwardSignal("SIGINT"));

child.on("exit", (code, signal) => {
  if (signal) {
    process.exit(SIGNAL_EXIT_CODE[signal] || 1);
  }
  process.exit(code === null ? 1 : code);
});

child.on("error", (err) => {
  process.stderr.write(`nogra-mcp: failed to start ${binaryPath}: ${err.message}\n`);
  process.exit(1);
});
