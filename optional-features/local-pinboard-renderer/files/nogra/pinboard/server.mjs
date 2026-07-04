#!/usr/bin/env node
import { createServer } from "node:http";
import { readFile, readdir, stat } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const STATE_SCHEMA = "nogra.pinboard.state.v1";
const DEFAULT_PORT = 7777;

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function parseArgs(argv) {
  const args = {
    port: Number(process.env.NOGRA_PINBOARD_PORT || DEFAULT_PORT),
    host: process.env.NOGRA_PINBOARD_HOST || "127.0.0.1",
    root: process.env.NOGRA_WORKSPACE || process.cwd(),
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--help" || arg === "-h") {
      args.help = true;
    } else if (arg === "--port" || arg === "-p") {
      args.port = Number(argv[index + 1]);
      index += 1;
    } else if (arg === "--host") {
      args.host = argv[index + 1] || args.host;
      index += 1;
    } else if (arg === "--root" || arg === "-r") {
      args.root = argv[index + 1] || args.root;
      index += 1;
    }
  }
  return args;
}

function printHelp() {
  console.log(`Nogra local pinboard renderer

Usage:
  node nogra/pinboard/server.mjs [--port 7777] [--root /path/to/workspace]

Options:
  --port, -p   Local port. Default: 7777
  --host       Bind host. Default: 127.0.0.1
  --root, -r   Workspace root containing .nogra/config.json. Default: cwd

Routes:
  /            Live pinboard HTML rendered from .nogra/
  /api/state   Versioned JSON state (${STATE_SCHEMA})
  /health      Renderer health
`);
}

function clean(value, fallback = "") {
  if (value === null || value === undefined) return fallback;
  return String(value).trim() || fallback;
}

function asArray(value) {
  if (Array.isArray(value)) return value;
  return value ? [value] : [];
}

function timestamp(value) {
  const raw = clean(value);
  if (!raw) return 0;
  const parsed = Date.parse(raw);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function normalizeWorkspaceRoot(rawRoot) {
  return path.resolve(clean(rawRoot, process.cwd()));
}

function assertWorkspaceRoot(root) {
  const configPath = path.join(root, ".nogra", "config.json");
  if (!existsSync(configPath)) {
    throw new Error(
      `Nogra workspace not found at ${root}. Start from the workspace root or pass --root /path/to/workspace.`
    );
  }
}

function safeJoin(root, ...parts) {
  const resolved = path.resolve(root, ...parts);
  if (resolved !== root && !resolved.startsWith(root + path.sep)) {
    throw new Error(`Path escaped workspace root: ${parts.join("/")}`);
  }
  return resolved;
}

async function readText(filePath, fallback = "") {
  try {
    return await readFile(filePath, "utf8");
  } catch {
    return fallback;
  }
}

async function readJson(filePath, fallback = null) {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch {
    return fallback;
  }
}

async function listFiles(dirPath, predicate = () => true) {
  try {
    const names = await readdir(dirPath);
    const files = [];
    for (const name of names) {
      const filePath = path.join(dirPath, name);
      try {
        const info = await stat(filePath);
        if (info.isFile() && predicate(name)) files.push(filePath);
      } catch {
        // Ignore files that disappear while reading.
      }
    }
    return files.sort();
  } catch {
    return [];
  }
}

async function readJsonObjects(dirPath, predicate = (name) => name.endsWith(".json")) {
  const files = await listFiles(dirPath, predicate);
  const objects = [];
  for (const filePath of files) {
    const payload = await readJson(filePath);
    if (payload && typeof payload === "object" && !Array.isArray(payload)) {
      objects.push({ ...payload, path: path.relative(process.cwd(), filePath) });
    }
  }
  return objects;
}

async function readJsonl(filePath) {
  const text = await readText(filePath);
  const rows = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim()) continue;
    try {
      const payload = JSON.parse(line);
      if (payload && typeof payload === "object" && !Array.isArray(payload)) rows.push(payload);
    } catch {
      // Keep the renderer tolerant. Broken rows should not blank the pinboard.
    }
  }
  return rows;
}

function parseFrontmatter(markdown) {
  const match = markdown.match(/^---\n([\s\S]*?)\n---\n?/);
  if (!match) return {};
  const meta = {};
  for (const line of match[1].split(/\r?\n/)) {
    const index = line.indexOf(":");
    if (index === -1) continue;
    const key = line.slice(0, index).trim();
    let value = line.slice(index + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    meta[key] = value;
  }
  return meta;
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function markdownSection(markdown, title) {
  const pattern = new RegExp(`(?:^|\\n)##\\s+${escapeRegExp(title)}\\s*\\n([\\s\\S]*?)(?=\\n##\\s+|$)`, "i");
  const match = markdown.match(pattern);
  return match ? match[1].trim() : "";
}

function markdownList(markdown, title) {
  return markdownSection(markdown, title)
    .split(/\r?\n/)
    .map((line) => line.replace(/^\s*-\s*/, "").trim())
    .filter(Boolean);
}

async function readPromotedBriefs(root) {
  const dirPath = safeJoin(root, ".nogra", "briefs");
  const files = await listFiles(dirPath, (name) => name.endsWith(".md"));
  const briefs = [];
  for (const filePath of files) {
    const markdown = await readText(filePath);
    const meta = parseFrontmatter(markdown);
    const titleMatch = markdown.match(/^#\s+(.+)$/m);
    const scopeFiles = markdownSection(markdown, "Scope")
      .split(/\r?\n/)
      .map((line) => line.replace(/^\s*-\s*/, "").trim())
      .filter((line) => line && !["In:", "Out:", "Files:"].includes(line));
    briefs.push({
      briefId: clean(meta.briefId || meta.brief_id),
      status: clean(meta.status, "ready"),
      title: clean(meta.title || titleMatch?.[1], "Untitled brief"),
      intent: markdownSection(markdown, "Intent"),
      successCriteria: markdownList(markdown, "Success Criteria"),
      scopeFiles,
      updatedAt: clean(meta.updatedAt || meta.createdAt),
      path: path.relative(root, filePath),
    });
  }
  return briefs;
}

function briefView(brief) {
  const scope = brief.scope && typeof brief.scope === "object" ? brief.scope : {};
  return {
    briefId: clean(brief.briefId || brief.id),
    status: clean(brief.status, "draft"),
    title: clean(brief.title, "Untitled brief"),
    intent: clean(brief.intent || brief.summary),
    summary: clean(brief.summary || brief.intent),
    files: asArray(scope.files || brief.files || brief.scopeFiles).map((item) => clean(item)).filter(Boolean),
    scopeFiles: asArray(scope.files || brief.scopeFiles).map((item) => clean(item)).filter(Boolean),
    successCriteria: asArray(brief.successCriteria || brief.acceptance).filter(Boolean),
    updatedAt: clean(brief.updatedAt || brief.createdAt || brief.modifiedAt),
    path: clean(brief.path),
  };
}

function runView(run) {
  return {
    runId: clean(run.runId || run.id),
    status: clean(run.status || run.phase, "unknown"),
    phase: clean(run.phase),
    verification: clean(run.verification || run.verdict),
    briefId: clean(run.briefId),
    target: clean(run.target),
    summary: clean(run.summary || run.notes),
    notes: clean(run.notes),
    createdAt: clean(run.createdAt || run.generatedAt),
    updatedAt: clean(run.updatedAt || run.completedAt || run.createdAt || run.generatedAt),
    reportSubmittedAt: clean(run.reportSubmittedAt),
    artifacts: run.artifacts && typeof run.artifacts === "object" ? run.artifacts : {},
    evidence: run.evidence && typeof run.evidence === "object" ? run.evidence : {},
  };
}

function eventView(event) {
  return {
    eventId: clean(event.eventId || event.id),
    eventType: clean(event.eventType || event.type || event.status, "event"),
    type: clean(event.type || event.eventType || event.status, "event"),
    message: clean(event.message || event.summary || event.notes || event.error),
    summary: clean(event.summary),
    runId: clean(event.runId),
    briefId: clean(event.briefId),
    createdAt: clean(event.createdAt || event.generatedAt || event.timestamp),
    generatedAt: clean(event.generatedAt || event.createdAt || event.timestamp),
  };
}

async function collectState(root) {
  const config = (await readJson(safeJoin(root, ".nogra", "config.json"), {})) || {};
  const drafts = await readJsonObjects(safeJoin(root, ".nogra", "briefs", "drafts"));
  const promoted = await readPromotedBriefs(root);
  const draftIds = new Set(drafts.map((brief) => clean(brief.briefId || brief.id)).filter(Boolean));
  const briefs = [
    ...drafts.map(briefView),
    ...promoted.filter((brief) => !draftIds.has(brief.briefId)).map(briefView),
  ].sort((a, b) => timestamp(a.updatedAt) - timestamp(b.updatedAt));

  const transportRuns = (await readJsonObjects(safeJoin(root, ".nogra", "transport", "runs"))).map(runView);
  const runUpdates = [];
  for (const filePath of await listFiles(safeJoin(root, ".nogra", "runs"), (name) => name.endsWith(".jsonl"))) {
    runUpdates.push(...(await readJsonl(filePath)).map(runView));
  }
  const runs = [...transportRuns, ...runUpdates]
    .filter((run) => run.runId)
    .sort((a, b) => timestamp(a.updatedAt || a.createdAt) - timestamp(b.updatedAt || b.createdAt));

  const events = [
    ...(await readJsonl(safeJoin(root, ".nogra", "events", "events.jsonl"))),
    ...(await readJsonl(safeJoin(root, ".nogra", "transport", "events.jsonl"))),
  ].map(eventView).sort((a, b) => timestamp(a.createdAt || a.generatedAt) - timestamp(b.createdAt || b.generatedAt));

  const latestRun = runs.at(-1) || {};
  const validation = latestRun.runId
    ? await readJson(safeJoin(root, ".nogra", "transport", "artifacts", latestRun.runId, "validation.json"), {})
    : {};
  const evidence = {
    runId: clean(validation?.runId || latestRun.runId),
    filesChanged: asArray(validation?.filesChanged || latestRun.filesChanged),
    commandsRun: asArray(validation?.commandsRun || latestRun.commandsRun),
    acceptance: asArray(validation?.acceptance || latestRun.acceptance),
  };
  if ((validation?.verification || validation?.verdict) && latestRun.runId) {
    latestRun.verification = validation.verification || validation.verdict;
  }

  const now = new Date().toISOString();
  return {
    schema: STATE_SCHEMA,
    updatedAt: now,
    source: "local-renderer",
    sequence: Date.now(),
    workspace: {
      name: clean(config.workspaceName || config.name, path.basename(root)),
      id: clean(config.workspaceId || config.id, "local"),
      version: clean(config.version, ""),
      updatedAt: now,
    },
    briefs,
    latestBrief: briefs.at(-1) || null,
    runs,
    events,
    agents: [],
    evidence,
  };
}

async function renderPinboard(root) {
  const state = await collectState(root);
  const templatePath = safeJoin(root, "nogra", "pinboard.html");
  const template = await readText(templatePath);
  if (!template) {
    throw new Error(`Missing pinboard template: ${templatePath}`);
  }
  const json = JSON.stringify(state, null, 2).replace(/</g, "\\u003c");
  const rendered = template.replace(
    /<script id="nogra-pinboard-data" type="application\/json">[\s\S]*?<\/script>/,
    `<script id="nogra-pinboard-data" type="application/json">\n${json}\n    </script>`
  );
  return { rendered, state };
}

function sendJson(response, status, payload) {
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  });
  response.end(JSON.stringify(payload, null, 2) + "\n");
}

function sendText(response, status, body, contentType = "text/plain; charset=utf-8") {
  response.writeHead(status, {
    "content-type": contentType,
    "cache-control": "no-store",
  });
  response.end(body);
}

async function handleRequest(request, response, root) {
  const url = new URL(request.url || "/", "http://localhost");
  try {
    if (url.pathname === "/health") {
      sendJson(response, 200, { status: "ok", schema: STATE_SCHEMA, root });
      return;
    }
    if (url.pathname === "/api/state") {
      sendJson(response, 200, await collectState(root));
      return;
    }
    if (url.pathname === "/" || url.pathname === "/pinboard" || url.pathname === "/pinboard.html") {
      const { rendered } = await renderPinboard(root);
      sendText(response, 200, rendered, "text/html; charset=utf-8");
      return;
    }
    if (url.pathname === "/favicon.ico") {
      response.writeHead(204);
      response.end();
      return;
    }
    sendJson(response, 404, { status: "missing", error: "route not found" });
  } catch (error) {
    sendJson(response, 500, {
      status: "error",
      error: error instanceof Error ? error.message : String(error),
    });
  }
}

const args = parseArgs(process.argv.slice(2));
if (args.help) {
  printHelp();
  process.exit(0);
}
if (!Number.isInteger(args.port) || args.port <= 0 || args.port > 65535) {
  console.error("Invalid --port. Use a number between 1 and 65535.");
  process.exit(1);
}

const root = normalizeWorkspaceRoot(args.root);
try {
  assertWorkspaceRoot(root);
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}

const server = createServer((request, response) => {
  handleRequest(request, response, root);
});

server.on("error", (error) => {
  if (error && error.code === "EADDRINUSE") {
    console.error(`Port ${args.port} is already in use. Try --port ${args.port + 1}.`);
  } else {
    console.error(error instanceof Error ? error.message : String(error));
  }
  process.exit(1);
});

server.listen(args.port, args.host, () => {
  console.log(`Nogra pinboard renderer running at http://${args.host}:${args.port}`);
  console.log(`Root: ${root}`);
  console.log(`State: http://${args.host}:${args.port}/api/state`);
});
