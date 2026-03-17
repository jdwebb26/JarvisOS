#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import shutil
import sys


DEFAULT_BUNDLE = Path.home() / ".npm-global/lib/node_modules/openclaw/dist/auth-profiles-iXW75sRj.js"
DEFAULT_BOOTSTRAP_HANDLER = Path.home() / ".npm-global/lib/node_modules/openclaw/dist/bundled/bootstrap-extra-files/handler.js"
# SearXNG patches must be applied to ALL bundles that contain createWebSearchTool,
# not just auth-profiles. The gateway loads different bundles for different code paths
# (reply-*.js for WebSocket agent turns, discord-*.js for Discord turns, etc.).
SEARXNG_EXTRA_BUNDLES = [
    "reply-BEN3KNDZ.js",
    "discord-BGqJ05Bl.js",
    "config-CmS8VEM4.js",
    "model-selection-_2UcLVem.js",
    "model-selection-7OCRoBDT.js",
]
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
NETWORK_GUARD_LABEL = "runtime_network_interface_guard"


REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (
        # DEFAULT_TOOL_ALLOW is the sandbox tool allowlist. web_search/web_fetch are omitted
        # from the default, so sandboxed agents (Scout) never receive them in toolsRaw.
        # Adding them here lets Scout's Python-side allowlist gate them correctly while
        # agents that don't have web tools in their AGENT_TOOL_ALLOWLIST still get nothing.
        'const DEFAULT_TOOL_ALLOW = [\n\t"exec",\n\t"process",\n\t"read",\n\t"write",\n\t"edit",\n\t"apply_patch",\n\t"image",\n\t"sessions_list",\n\t"sessions_history",\n\t"sessions_send",\n\t"sessions_spawn",\n\t"sessions_yield",\n\t"subagents",\n\t"session_status"\n];',
        'const DEFAULT_TOOL_ALLOW = [\n\t"exec",\n\t"process",\n\t"read",\n\t"write",\n\t"edit",\n\t"apply_patch",\n\t"image",\n\t"sessions_list",\n\t"sessions_history",\n\t"sessions_send",\n\t"sessions_spawn",\n\t"sessions_yield",\n\t"subagents",\n\t"session_status",\n\t"web_search",\n\t"web_fetch"\n];',
    ),
    (
        'const candidate = path.resolve(workspaceDir, "scripts", "source_owned_context_engine_cli.py");\n\tif (existsSync(candidate)) return candidate;\n\tthrow new Error(`Source-owned context engine CLI not found: ${candidate}`);',
        'const candidates = [\n\t\tpath.resolve(workspaceDir, "scripts", "source_owned_context_engine_cli.py"),\n\t\tpath.resolve(workspaceDir, "jarvis-v5", "scripts", "source_owned_context_engine_cli.py"),\n\t\tpath.resolve(process.cwd(), "scripts", "source_owned_context_engine_cli.py"),\n\t\tpath.resolve(process.env.HOME || "", ".openclaw", "workspace", "jarvis-v5", "scripts", "source_owned_context_engine_cli.py")\n\t];\n\tfor (const candidate of candidates) {\n\t\tif (existsSync(candidate)) return candidate;\n\t}\n\tthrow new Error(`Source-owned context engine CLI not found: ${candidates[0]}`);',
    ),
    (
        "\t\tconst skillsPrompt = resolveSkillsPromptForRun({",
        "\t\tlet skillsPrompt = resolveSkillsPromptForRun({",
    ),
    (
        "function shouldStripJarvisSkills(sessionKey) {\n        return true;\n}",
        "function shouldStripJarvisSkills(sessionKey) {\n        return false;\n}",
    ),
    (
        "\tconst ifaces = os.networkInterfaces();\n",
        "\tlet ifaces;\n\ttry {\n\t\tifaces = os.networkInterfaces();\n\t}\n\tcatch {\n\t\treturn {\n\t\t\tipv4: [],\n\t\t\tipv6: []\n\t\t};\n\t}\n",
    ),
    (
        "\tconst nets = os.networkInterfaces();\n",
        "\tlet nets;\n\ttry {\n\t\tnets = os.networkInterfaces();\n\t}\n\tcatch {\n\t\treturn;\n\t}\n",
    ),
    (
        "function listTailnetAddresses() {\n\tconst ipv4 = [];\n\tconst ipv6 = [];\n\tconst ifaces = os.networkInterfaces();\n\tfor (const entries of Object.values(ifaces)) {\n\t\tif (!entries) continue;\n\t\tfor (const e of entries) {\n\t\t\tif (!e || e.internal) continue;\n\t\t\tconst address = e.address?.trim();\n\t\t\tif (!address) continue;\n\t\t\tif (isTailnetIPv4(address)) ipv4.push(address);\n\t\t\tif (isTailnetIPv6(address)) ipv6.push(address);\n\t\t}\n\t}\n\treturn {\n\t\tipv4: [...new Set(ipv4)],\n\t\tipv6: [...new Set(ipv6)]\n\t};\n}\n",
        "function listTailnetAddresses() {\n\tconst ipv4 = [];\n\tconst ipv6 = [];\n\tlet ifaces;\n\ttry {\n\t\tifaces = os.networkInterfaces();\n\t}\n\tcatch {\n\t\treturn {\n\t\t\tipv4: [],\n\t\t\tipv6: []\n\t\t};\n\t}\n\tfor (const entries of Object.values(ifaces)) {\n\t\tif (!entries) continue;\n\t\tfor (const e of entries) {\n\t\t\tif (!e || e.internal) continue;\n\t\t\tconst address = e.address?.trim();\n\t\t\tif (!address) continue;\n\t\t\tif (isTailnetIPv4(address)) ipv4.push(address);\n\t\t\tif (isTailnetIPv6(address)) ipv6.push(address);\n\t\t}\n\t}\n\treturn {\n\t\tipv4: [...new Set(ipv4)],\n\t\tipv6: [...new Set(ipv6)]\n\t};\n}\n",
    ),
    (
        "function pickPrimaryLanIPv4() {\n\tconst nets = os.networkInterfaces();\n\tfor (const name of [\"en0\", \"eth0\"]) {\n\t\tconst entry = nets[name]?.find((n) => n.family === \"IPv4\" && !n.internal);\n\t\tif (entry?.address) return entry.address;\n\t}\n\tfor (const list of Object.values(nets)) {\n\t\tconst entry = list?.find((n) => n.family === \"IPv4\" && !n.internal);\n\t\tif (entry?.address) return entry.address;\n\t}\n}\n",
        "function pickPrimaryLanIPv4() {\n\tlet nets;\n\ttry {\n\t\tnets = os.networkInterfaces();\n\t}\n\tcatch {\n\t\treturn;\n\t}\n\tfor (const name of [\"en0\", \"eth0\"]) {\n\t\tconst entry = nets[name]?.find((n) => n.family === \"IPv4\" && !n.internal);\n\t\tif (entry?.address) return entry.address;\n\t}\n\tfor (const list of Object.values(nets)) {\n\t\tconst entry = list?.find((n) => n.family === \"IPv4\" && !n.internal);\n\t\tif (entry?.address) return entry.address;\n\t}\n}\n",
    ),
    # --- SearXNG web_search provider patches ---
    # Patch 1: WEB_SEARCH_PROVIDERS list (config-time validation)
    (
        'const WEB_SEARCH_PROVIDERS = [\n\t"brave",\n\t"gemini",\n\t"grok",\n\t"kimi",\n\t"perplexity"\n];',
        'const WEB_SEARCH_PROVIDERS = [\n\t"brave",\n\t"gemini",\n\t"grok",\n\t"kimi",\n\t"perplexity",\n\t"searxng"\n];',
    ),
    # Patch 2: normalizeProvider$1 — accepts "searxng" as a valid configured provider
    (
        'if (normalized === "brave" || normalized === "gemini" || normalized === "grok" || normalized === "kimi" || normalized === "perplexity") return normalized;',
        'if (normalized === "brave" || normalized === "gemini" || normalized === "grok" || normalized === "kimi" || normalized === "perplexity" || normalized === "searxng") return normalized;',
    ),
    # Patch 3: envVarsForProvider — maps "searxng" to JARVIS_SEARXNG_URL for config diagnostics
    (
        '\tif (provider === "brave") return ["BRAVE_API_KEY"];\n\tif (provider === "gemini") return ["GEMINI_API_KEY"];\n\tif (provider === "grok") return ["XAI_API_KEY"];\n\tif (provider === "kimi") return ["KIMI_API_KEY", "MOONSHOT_API_KEY"];\n\treturn ["PERPLEXITY_API_KEY", "OPENROUTER_API_KEY"];',
        '\tif (provider === "brave") return ["BRAVE_API_KEY"];\n\tif (provider === "gemini") return ["GEMINI_API_KEY"];\n\tif (provider === "grok") return ["XAI_API_KEY"];\n\tif (provider === "kimi") return ["KIMI_API_KEY", "MOONSHOT_API_KEY"];\n\tif (provider === "searxng") return ["JARVIS_SEARXNG_URL"];\n\treturn ["PERPLEXITY_API_KEY", "OPENROUTER_API_KEY"];',
    ),
    # Patch 4: resolveSearchProvider — returns "searxng" when configured or auto-detected from JARVIS_SEARXNG_URL env
    (
        '\tif (raw === "perplexity") return "perplexity";\n\tif (raw === "") {\n\t\tif (resolveSearchApiKey(search)) {',
        '\tif (raw === "perplexity") return "perplexity";\n\tif (raw === "searxng") return "searxng";\n\tif (raw === "") {\n\t\tif (process.env.JARVIS_SEARXNG_URL) {\n\t\t\tlogVerbose("web_search: no provider configured, auto-detected \\"searxng\\" from JARVIS_SEARXNG_URL");\n\t\t\treturn "searxng";\n\t\t}\n\t\tif (resolveSearchApiKey(search)) {',
    ),
    # Patch 5: missingSearchKeyPayload — error message when JARVIS_SEARXNG_URL not set
    (
        '\treturn {\n\t\terror: "missing_perplexity_api_key",\n\t\tmessage: "web_search (perplexity) needs an API key. Set PERPLEXITY_API_KEY or OPENROUTER_API_KEY in the Gateway environment, or configure tools.web.search.perplexity.apiKey.",\n\t\tdocs: "https://docs.openclaw.ai/tools/web"\n\t};\n}',
        '\tif (provider === "searxng") return {\n\t\terror: "missing_searxng_url",\n\t\tmessage: "web_search (searxng) requires JARVIS_SEARXNG_URL to be set in the Gateway environment (e.g. http://localhost:8888).",\n\t\tdocs: "https://docs.openclaw.ai/tools/web"\n\t};\n\treturn {\n\t\terror: "missing_perplexity_api_key",\n\t\tmessage: "web_search (perplexity) needs an API key. Set PERPLEXITY_API_KEY or OPENROUTER_API_KEY in the Gateway environment, or configure tools.web.search.perplexity.apiKey.",\n\t\tdocs: "https://docs.openclaw.ai/tools/web"\n\t};\n}',
    ),
    # Patch 6: apiKey resolution in execute — reuses the apiKey slot to carry the SearXNG URL
    (
        'const apiKey = provider === "perplexity" ? perplexityRuntime?.apiKey : provider === "grok" ? resolveGrokApiKey(grokConfig) : provider === "kimi" ? resolveKimiApiKey(kimiConfig) : provider === "gemini" ? resolveGeminiApiKey(geminiConfig) : resolveSearchApiKey(search);\n\t\t\tif (!apiKey) return jsonResult(missingSearchKeyPayload(provider));',
        'const apiKey = provider === "perplexity" ? perplexityRuntime?.apiKey : provider === "grok" ? resolveGrokApiKey(grokConfig) : provider === "kimi" ? resolveKimiApiKey(kimiConfig) : provider === "gemini" ? resolveGeminiApiKey(geminiConfig) : provider === "searxng" ? (process.env.JARVIS_SEARXNG_URL || (search && typeof search === "object" && search.searxng && typeof search.searxng === "object" ? String(search.searxng.url || "") : "") || "") : resolveSearchApiKey(search);\n\t\t\tif (!apiKey) return jsonResult(missingSearchKeyPayload(provider));',
    ),
    # Patch 7: tool description — adds SearXNG description before brave/llm-context fallback
    (
        ': braveMode === "llm-context" ? "Search the web using Brave Search LLM Context API. Returns pre-extracted page content (text chunks, tables, code blocks) optimized for LLM grounding." : "Search the web using Brave Search API. Supports region-specific and localized search via country and language parameters. Returns titles, URLs, and snippets for fast research.",',
        ': provider === "searxng" ? "Search the web using SearXNG (local self-hosted meta-search). Returns titles, URLs, and snippets from the configured SearXNG instance." : braveMode === "llm-context" ? "Search the web using Brave Search LLM Context API. Returns pre-extracted page content (text chunks, tables, code blocks) optimized for LLM grounding." : "Search the web using Brave Search API. Supports region-specific and localized search via country and language parameters. Returns titles, URLs, and snippets for fast research.",',
    ),
    # Patch 8: runWebSearch dispatch — SearXNG HTTP handler inserted before the "not brave" throw
    (
        '\tif (params.provider !== "brave") throw new Error("Unsupported web search provider.");\n\tif (effective',
        '\tif (params.provider === "searxng") {\n'
        '\t\tconst searxngBaseUrl = params.apiKey.replace(/\\/$/, "");\n'
        '\t\tconst searchUrl = new URL(searxngBaseUrl + "/search");\n'
        '\t\tsearchUrl.searchParams.set("q", params.query);\n'
        '\t\tsearchUrl.searchParams.set("format", "json");\n'
        '\t\tconst count = params.count ?? DEFAULT_SEARCH_COUNT;\n'
        '\t\tconst mapped = await withTrustedWebSearchEndpoint({\n'
        '\t\t\turl: searchUrl.toString(),\n'
        '\t\t\ttimeoutSeconds: params.timeoutSeconds,\n'
        '\t\t\tinit: { method: "GET", headers: { "Accept": "application/json" } }\n'
        '\t\t}, async (res) => {\n'
        '\t\t\tif (!res.ok) {\n'
        '\t\t\t\tconst detail = (await readResponseText(res, { maxBytes: 64e3 })).text;\n'
        '\t\t\t\tthrow new Error(`SearXNG search error (${res.status}): ${detail || res.statusText}`);\n'
        '\t\t\t}\n'
        '\t\t\tconst data = await res.json();\n'
        '\t\t\treturn (Array.isArray(data.results) ? data.results : []).slice(0, count).map((entry) => ({\n'
        '\t\t\t\ttitle: entry.title ? wrapWebContent(entry.title, "web_search") : "",\n'
        '\t\t\t\turl: entry.url ?? "",\n'
        '\t\t\t\tdescription: entry.content ? wrapWebContent(entry.content, "web_search") : "",\n'
        '\t\t\t\tpublished: entry.publishedDate || void 0,\n'
        '\t\t\t\tsiteName: entry.engine || void 0\n'
        '\t\t\t}));\n'
        '\t\t});\n'
        '\t\tconst payload = {\n'
        '\t\t\tquery: params.query,\n'
        '\t\t\tprovider: params.provider,\n'
        '\t\t\tcount: mapped.length,\n'
        '\t\t\ttookMs: Date.now() - start,\n'
        '\t\t\texternalContent: { untrusted: true, source: "web_search", provider: params.provider, wrapped: true },\n'
        '\t\t\tresults: mapped\n'
        '\t\t};\n'
        '\t\twriteCache(SEARCH_CACHE, cacheKey, payload, params.cacheTtlMs);\n'
        '\t\treturn payload;\n'
        '\t}\n'
        '\tif (params.provider !== "brave") throw new Error("Unsupported web search provider.");\n'
        '\tif (effective',
    ),
    # --- end SearXNG patches ---
    (
        'async function applyBootstrapHookOverrides(params) {\n\tconst sessionKey = params.sessionKey ?? params.sessionId ?? "unknown";\n\tconst agentId = params.agentId ?? (params.sessionKey ? resolveAgentIdFromSessionKey(params.sessionKey) : void 0);\n\tconst event = createInternalHookEvent("agent", "bootstrap", sessionKey, {\n\t\tworkspaceDir: params.workspaceDir,\n\t\tbootstrapFiles: params.files,\n\t\tcfg: params.config,\n\t\tsessionKey: params.sessionKey,\n\t\tsessionId: params.sessionId,\n\t\tagentId\n\t});\n\tawait triggerInternalHook(event);\n\tconst updated = event.context.bootstrapFiles;\n\treturn Array.isArray(updated) ? updated : params.files;\n}',
        'async function applyBootstrapHookOverrides(params) {\n\tconst sessionKey = params.sessionKey ?? params.sessionId ?? "unknown";\n\tconst agentId = params.agentId ?? (params.sessionKey ? resolveAgentIdFromSessionKey(params.sessionKey) : void 0);\n\tconst event = createInternalHookEvent("agent", "bootstrap", sessionKey, {\n\t\tworkspaceDir: params.workspaceDir,\n\t\tbootstrapFiles: params.files,\n\t\tcfg: params.config,\n\t\tsessionKey: params.sessionKey,\n\t\tsessionId: params.sessionId,\n\t\tagentId\n\t});\n\tconst originalFiles = event.context.bootstrapFiles;\n\tawait triggerInternalHook(event);\n\tif (event.context.bootstrapFiles === originalFiles) try {\n\t\tconst bootstrapExtraFilesModule = await import("./bundled/bootstrap-extra-files/handler.js");\n\t\tconst bootstrapExtraFilesHook = typeof bootstrapExtraFilesModule?.default === "function" ? bootstrapExtraFilesModule.default : null;\n\t\tif (bootstrapExtraFilesHook) await bootstrapExtraFilesHook(event);\n\t} catch {}\n\tconst updated = event.context.bootstrapFiles;\n\treturn Array.isArray(updated) ? updated : params.files;\n}',
    ),
)

HANDLER_OLD = """import "../../paths-hfkBoC7i.js";
import { t as createSubsystemLogger } from "../../subsystem-2phE7Tdr.js";
import { d as loadExtraBootstrapFilesWithDiagnostics, u as filterBootstrapFilesForSession } from "../../workspace-B3nm_eCU.js";
import "../../logger-BYA-BLD7.js";
import "../../boolean-Cuaw_-7j.js";
import { g as isAgentBootstrapEvent } from "../../frontmatter-CEejIjxx.js";
import { t as resolveHookConfig } from "../../config-BYkzFD4a.js";
//#region src/hooks/bundled/bootstrap-extra-files/handler.ts
const HOOK_KEY = "bootstrap-extra-files";
const log = createSubsystemLogger("bootstrap-extra-files");
function normalizeStringArray(value) {
\tif (!Array.isArray(value)) return [];
\treturn value.map((v) => typeof v === "string" ? v.trim() : "").filter(Boolean);
}
function resolveExtraBootstrapPatterns(hookConfig) {
\tconst fromPaths = normalizeStringArray(hookConfig.paths);
\tif (fromPaths.length > 0) return fromPaths;
\tconst fromPatterns = normalizeStringArray(hookConfig.patterns);
\tif (fromPatterns.length > 0) return fromPatterns;
\treturn normalizeStringArray(hookConfig.files);
}
const bootstrapExtraFilesHook = async (event) => {
\tif (!isAgentBootstrapEvent(event)) return;
\tconst context = event.context;
\tconst hookConfig = resolveHookConfig(context.cfg, HOOK_KEY);
\tif (!hookConfig || hookConfig.enabled === false) return;
\tconst patterns = resolveExtraBootstrapPatterns(hookConfig);
\tif (patterns.length === 0) return;
\ttry {
\t\tconst { files: extras, diagnostics } = await loadExtraBootstrapFilesWithDiagnostics(context.workspaceDir, patterns);
\t\tif (diagnostics.length > 0) log.debug("skipped extra bootstrap candidates", {
\t\t\tskipped: diagnostics.length,
\t\t\treasons: diagnostics.reduce((counts, item) => {
\t\t\t\tcounts[item.reason] = (counts[item.reason] ?? 0) + 1;
\t\t\t\treturn counts;
\t\t\t}, {})
\t\t});
\t\tif (extras.length === 0) return;
\t\tcontext.bootstrapFiles = filterBootstrapFilesForSession([...context.bootstrapFiles, ...extras], context.sessionKey);
\t} catch (err) {
\t\tlog.warn(`failed: ${String(err)}`);
\t}
};
//#endregion
export { bootstrapExtraFilesHook as default };
"""

HANDLER_NEW = """import "../../paths-hfkBoC7i.js";
import path from "path";
import { promises as fs } from "fs";
import { t as createSubsystemLogger } from "../../subsystem-2phE7Tdr.js";
import { d as loadExtraBootstrapFilesWithDiagnostics, u as filterBootstrapFilesForSession } from "../../workspace-B3nm_eCU.js";
import "../../logger-BYA-BLD7.js";
import "../../boolean-Cuaw_-7j.js";
import { g as isAgentBootstrapEvent } from "../../frontmatter-CEejIjxx.js";
import { t as resolveHookConfig } from "../../config-BYkzFD4a.js";
//#region src/hooks/bundled/bootstrap-extra-files/handler.ts
const HOOK_KEY = "bootstrap-extra-files";
const log = createSubsystemLogger("bootstrap-extra-files");
const AGENT_BOOTSTRAP_FILE_NAMES = [
\t"AGENTS.md",
\t"SOUL.md",
\t"TOOLS.md",
\t"IDENTITY.md",
\t"USER.md",
\t"HEARTBEAT.md",
\t"BOOTSTRAP.md",
\t"MEMORY.md",
\t"memory.md"
];
function normalizeStringArray(value) {
\tif (!Array.isArray(value)) return [];
\treturn value.map((v) => typeof v === "string" ? v.trim() : "").filter(Boolean);
}
function resolveExtraBootstrapPatterns(hookConfig) {
\tconst fromPaths = normalizeStringArray(hookConfig?.paths);
\tif (fromPaths.length > 0) return fromPaths;
\tconst fromPatterns = normalizeStringArray(hookConfig?.patterns);
\tif (fromPatterns.length > 0) return fromPatterns;
\treturn normalizeStringArray(hookConfig?.files);
}
function normalizeAgentId(value) {
\treturn typeof value === "string" ? value.trim().toLowerCase() : "";
}
async function readBootstrapFile(name, filePath) {
\ttry {
\t\tconst content = await fs.readFile(filePath, "utf-8");
\t\treturn {
\t\t\tname,
\t\t\tpath: filePath,
\t\t\tcontent,
\t\t\tmissing: false
\t\t};
\t} catch {
\t\treturn null;
\t}
}
async function resolveAgentBootstrapOverlayFiles(context) {
\tconst agentId = normalizeAgentId(context.agentId);
\tif (!agentId) return [];
\tconst agents = Array.isArray(context.cfg?.agents?.list) ? context.cfg.agents.list : [];
\tconst agentEntry = agents.find((entry) => normalizeAgentId(entry?.id) === agentId);
\tconst rawAgentDir = typeof agentEntry?.agentDir === "string" ? agentEntry.agentDir.trim() : "";
\tif (!rawAgentDir) return [];
\tconst agentDir = path.resolve(rawAgentDir);
\tconst agentRoot = path.dirname(agentDir);
\tconst overlays = [];
\tfor (const name of AGENT_BOOTSTRAP_FILE_NAMES) {
\t\tconst candidates = [
\t\t\tpath.join(agentRoot, name),
\t\t\tpath.join(agentDir, name)
\t\t];
\t\tfor (const candidate of candidates) {
\t\t\tconst loaded = await readBootstrapFile(name, candidate);
\t\t\tif (!loaded) continue;
\t\t\toverlays.push(loaded);
\t\t\tbreak;
\t\t}
\t}
\treturn overlays;
}
function mergeAgentBootstrapFiles(baseFiles, overlayFiles) {
\tif (overlayFiles.length === 0) return baseFiles;
\tconst overlayByName = new Map(overlayFiles.map((file) => [file.name, file]));
\tconst merged = baseFiles.map((file) => overlayByName.get(file.name) ?? file);
\tfor (const file of overlayFiles) {
\t\tif (merged.some((entry) => entry.name === file.name)) continue;
\t\tmerged.push(file);
\t}
\treturn merged;
}
const bootstrapExtraFilesHook = async (event) => {
\tif (!isAgentBootstrapEvent(event)) return;
\tconst context = event.context;
\tconst hookConfig = resolveHookConfig(context.cfg, HOOK_KEY);
\tif (hookConfig?.enabled === false) return;
\tconst patterns = resolveExtraBootstrapPatterns(hookConfig);
\ttry {
\t\tconst overlayFiles = await resolveAgentBootstrapOverlayFiles(context);
\t\tlet mergedFiles = mergeAgentBootstrapFiles(context.bootstrapFiles, overlayFiles);
\t\tif (overlayFiles.length > 0) log.debug("applied agent bootstrap overlay", {
\t\t\tagentId: context.agentId,
\t\t\toverlayFiles: overlayFiles.map((file) => file.path)
\t\t});
\t\tif (patterns.length > 0) {
\t\t\tconst { files: extras, diagnostics } = await loadExtraBootstrapFilesWithDiagnostics(context.workspaceDir, patterns);
\t\t\tif (diagnostics.length > 0) log.debug("skipped extra bootstrap candidates", {
\t\t\t\tskipped: diagnostics.length,
\t\t\t\treasons: diagnostics.reduce((counts, item) => {
\t\t\t\t\tcounts[item.reason] = (counts[item.reason] ?? 0) + 1;
\t\t\t\t\treturn counts;
\t\t\t\t}, {})
\t\t\t});
\t\t\tif (extras.length > 0) mergedFiles = [...mergedFiles, ...extras];
\t\t}
\t\tcontext.bootstrapFiles = filterBootstrapFilesForSession(mergedFiles, context.sessionKey);
\t} catch (err) {
\t\tlog.warn(`failed: ${String(err)}`);
\t}
};
//#endregion
export { bootstrapExtraFilesHook as default };
"""


def _check_bundle_state(text: str) -> dict[str, bool]:
    return {
        "sandbox_default_tool_allow_web_tools": '\t"web_search",\n\t"web_fetch"\n];\nconst DEFAULT_TOOL_DENY' in text,
        NETWORK_GUARD_LABEL: "function listTailnetAddresses() {\n\tconst ipv4 = [];\n\tconst ipv6 = [];\n\tlet ifaces;\n\ttry {\n\t\tifaces = os.networkInterfaces();\n\t}\n\tcatch {\n\t\treturn {\n\t\t\tipv4: [],\n\t\t\tipv6: []\n\t\t};\n\t}\n" in text
        and "function pickPrimaryLanIPv4() {\n\tlet nets;\n\ttry {\n\t\tnets = os.networkInterfaces();\n\t}\n\tcatch {\n\t\treturn;\n\t}\n" in text,
        "bridge_payload_fields": 'skills_prompt: typeof params.skillsPrompt === "string" ? params.skillsPrompt : ""' in text
        and 'agent_id: typeof params.agentId === "string" ? params.agentId : ""' in text
        and 'provider_id: typeof params.providerId === "string" ? params.providerId : ""' in text
        and 'model_id: typeof params.modelId === "string" ? params.modelId : ""' in text,
        "filtered_skills_applied": 'if (typeof sourceOwnedContextSeed?.filteredSkillsPrompt === "string") skillsPrompt = sourceOwnedContextSeed.filteredSkillsPrompt;' in text,
        "jarvis_skill_strip_disabled": "function shouldStripJarvisSkills(sessionKey) {\n        return false;\n}" in text,
        "skills_prompt_mutable": text.count("\t\tlet skillsPrompt = resolveSkillsPromptForRun({") >= 2,
        "cli_path_fallbacks_present": 'path.resolve(process.env.HOME || "", ".openclaw", "workspace", "jarvis-v5", "scripts", "source_owned_context_engine_cli.py")' in text,
        "local_bootstrap_fallback_present": 'const bootstrapExtraFilesModule = await import("./bundled/bootstrap-extra-files/handler.js");' in text
        and "if (event.context.bootstrapFiles === originalFiles) try {" in text,
        "session_report_bindings": "async function syncSessionReportToBindings" in text
        and "sessionId: queued.run.sessionId" in text
        and "sessionId: followupRun.run.sessionId" in text,
        "searxng_web_search_provider": '"searxng"\n];' in text
        and 'if (raw === "searxng") return "searxng";' in text
        and 'if (params.provider === "searxng") {\n\t\tconst searxngBaseUrl' in text
        and 'provider === "searxng" ? (process.env.JARVIS_SEARXNG_URL' in text,
    }


def _check_handler_state(text: str) -> dict[str, bool]:
    return {
        "agent_bootstrap_overlay_present": "resolveAgentBootstrapOverlayFiles" in text,
        "agent_bootstrap_overlay_uses_agent_dir": 'const rawAgentDir = typeof agentEntry?.agentDir === "string" ? agentEntry.agentDir.trim() : "";' in text,
        "agent_bootstrap_overlay_replaces_by_name": "mergeAgentBootstrapFiles" in text,
        "agent_bootstrap_overlay_without_patterns": 'if (hookConfig?.enabled === false) return;' in text
        and "const overlayFiles = await resolveAgentBootstrapOverlayFiles(context);" in text,
    }


def _apply_bundle_replacements(text: str) -> tuple[str, bool]:
    updated = text
    changed = False
    for old, new in REPLACEMENTS:
        if new in updated:
            continue
        if old not in updated:
            continue
        updated = updated.replace(old, new)
        changed = True
    helper_text, helper_changed = _apply_session_report_binding_patch(updated)
    if helper_changed:
        updated = helper_text
        changed = True
    return updated, changed


def _apply_session_report_binding_patch(text: str) -> tuple[str, bool]:
    changed = False
    helper_old = "\treturn patch;\n}\nasync function persistSessionUsageUpdate("
    helper_new = (
        "\treturn patch;\n}\n\nasync function syncSessionReportToBindings(params) {\n"
        "\t\tconst { storePath, sessionKey, sessionId, systemPromptReport } = params;\n"
        "\t\tif (!storePath || !sessionKey || !sessionId || !systemPromptReport) return;\n"
        "\t\treturn updateSessionStore(storePath, (store) => {\n"
        "\t\t\tlet mutated = false;\n"
        "\t\t\tconst now = Date.now();\n"
        "\t\t\tfor (const [key, entry] of Object.entries(store)) {\n"
        "\t\t\t\tif (!entry || key === sessionKey) continue;\n"
        "\t\t\t\tif (entry.sessionId !== sessionId) continue;\n"
        "\t\t\t\tstore[key] = {\n"
        "\t\t\t\t\t...entry,\n"
        "\t\t\t\t\tsystemPromptReport,\n"
        "\t\t\t\t\tupdatedAt: now\n"
        "\t\t\t\t};\n"
        "\t\t\t\tmutated = true;\n"
        "\t\t\t}\n"
        "\t\t\treturn mutated ? true : null;\n"
        "\t\t}, { activeSessionKey: sessionKey });\n"
        "\t}\n\nasync function persistSessionUsageUpdate("
    )
    if helper_old in text and "syncSessionReportToBindings" not in text:
        text = text.replace(helper_old, helper_new, 1)
        changed = True

    replacements = [
        ("\t\t\t});\n\t\t} catch (err)", "\t\t\t});\n\t\t\tawait syncSessionReportToBindings(params);\n\t\t} catch (err)"),
        ("\t\t});\n\t} catch (err)", "\t\t});\n\t\tawait syncSessionReportToBindings(params);\n\t} catch (err)"),
    ]
    for old, new in replacements:
        if new in text:
            continue
        if old not in text:
            continue
        text = text.replace(old, new, 1)
        changed = True

    call_replacements = [
        ("\t\t\t\tsessionKey,\n\t\t\t\tusage,", "\t\t\t\tsessionKey,\n\t\t\t\tsessionId: queued.run.sessionId,\n\t\t\t\tusage,"),
        ("\t\t\tstorePath,\n\t\t\tsessionKey,\n\t\t\tusage,", "\t\t\tstorePath,\n\t\t\tsessionKey,\n\t\t\tsessionId: followupRun.run.sessionId,\n\t\t\tusage,"),
    ]
    for old, new in call_replacements:
        if new in text:
            continue
        if old not in text:
            continue
        text = text.replace(old, new, 1)
        changed = True

    return text, changed


def _searxng_only_replacements() -> list[tuple[str, str]]:
    """Return only the SearXNG-specific REPLACEMENTS (patches 1-8)."""
    # These are the replacements from REPLACEMENTS that contain "searxng" in their new text.
    return [(old, new) for old, new in REPLACEMENTS if "searxng" in new.lower()]


def _apply_searxng_to_extra_bundles(dist_dir: Path, *, apply: bool) -> dict[str, dict[str, bool]]:
    """Apply SearXNG patches to all extra bundles that contain createWebSearchTool.

    Result keys per bundle:
      bundle_found          – file exists on disk
      has_web_search_tool   – bundle contains createWebSearchTool (only patched if True)
      searxng_patched       – SearXNG provider patch is present in the bundle
    """
    results: dict[str, dict[str, bool]] = {}
    searxng_patches = _searxng_only_replacements()
    for bname in SEARXNG_EXTRA_BUNDLES:
        bpath = dist_dir / bname
        if not bpath.exists():
            results[bname] = {"bundle_found": False, "has_web_search_tool": False, "searxng_patched": False}
            continue
        text = bpath.read_text(encoding="utf-8")
        has_wst = "createWebSearchTool" in text
        if not has_wst:
            results[bname] = {"bundle_found": True, "has_web_search_tool": False, "searxng_patched": False}
            continue
        is_patched = 'if (raw === "searxng") return "searxng";' in text and "JARVIS_SEARXNG_URL" in text
        if is_patched or not apply:
            results[bname] = {"bundle_found": True, "has_web_search_tool": True, "searxng_patched": is_patched}
            continue
        changed = False
        for old, new in searxng_patches:
            if new in text:
                continue
            if old in text:
                text = text.replace(old, new, 1)
                changed = True
        if changed:
            bpath.write_text(text, encoding="utf-8")
        results[bname] = {
            "bundle_found": True,
            "has_web_search_tool": True,
            "searxng_patched": 'if (raw === "searxng") return "searxng";' in text and "JARVIS_SEARXNG_URL" in text,
        }
    return results


def _extra_bundles_fully_patched(results: dict[str, dict[str, bool]]) -> bool:
    """True iff every found bundle that contains createWebSearchTool has the SearXNG patch."""
    for checks in results.values():
        if checks.get("bundle_found") and checks.get("has_web_search_tool") and not checks.get("searxng_patched"):
            return False
    return True


def _extra_bundle_status(checks: dict[str, bool]) -> str:
    """Single-word status label for operator output."""
    if not checks.get("bundle_found"):
        return "missing-file"
    if not checks.get("has_web_search_tool"):
        return "no-web-search-tool"
    return "ok" if checks.get("searxng_patched") else "unpatched"


def _discover_unregistered_web_search_bundles(dist_dir: Path, skip_names: set[str]) -> list[str]:
    """Scan dist_dir for JS bundles that contain createWebSearchTool but are not in skip_names.

    Used post-upgrade to detect newly hashed bundles that need to be added to
    SEARXNG_EXTRA_BUNDLES in this script.  Only reads files ≥10 KB to skip stubs.
    """
    found: list[str] = []
    try:
        for p in sorted(dist_dir.glob("*.js")):
            if p.name in skip_names:
                continue
            try:
                if p.stat().st_size < 10_000:
                    continue
                text = p.read_text(encoding="utf-8", errors="ignore")
                if "createWebSearchTool" in text:
                    found.append(p.name)
            except OSError:
                continue
    except OSError:
        pass
    return found


def _smoke_check_searxng(base_url: str | None = None) -> dict[str, object]:
    """Bounded SearXNG reachability check: GET /healthz then GET /search?q=test&format=json.

    Returns a dict with 'ok' (bool) and diagnostic fields.  Safe to call even if
    SearXNG is not configured (returns ok=False with an 'error' key).
    """
    import json as _json
    import os as _os
    import time as _time
    import urllib.error as _urlerr  # noqa: F401
    import urllib.parse as _urlparse
    import urllib.request as _urlreq

    url = (base_url or _os.environ.get("JARVIS_SEARXNG_URL", "")).rstrip("/")
    if not url:
        return {"ok": False, "error": "JARVIS_SEARXNG_URL not set and no base_url supplied"}

    result: dict[str, object] = {"base_url": url}

    try:
        t0 = _time.monotonic()
        with _urlreq.urlopen(f"{url}/healthz", timeout=3) as resp:
            result["healthz_status"] = resp.status
            result["healthz_ms"] = int((_time.monotonic() - t0) * 1000)
            result["healthz_ok"] = resp.status == 200
    except Exception as exc:
        result["healthz_ok"] = False
        result["healthz_error"] = str(exc)
        result["ok"] = False
        return result

    if not result.get("healthz_ok"):
        result["ok"] = False
        return result

    try:
        qs = _urlparse.urlencode({"q": "test", "format": "json"})
        t0 = _time.monotonic()
        with _urlreq.urlopen(f"{url}/search?{qs}", timeout=5) as resp:
            data = _json.loads(resp.read())
            result["search_status"] = resp.status
            result["search_ms"] = int((_time.monotonic() - t0) * 1000)
            result["search_result_count"] = len(data.get("results", []))
            result["search_ok"] = resp.status == 200
    except Exception as exc:
        result["search_ok"] = False
        result["search_error"] = str(exc)
        result["ok"] = False
        return result

    result["ok"] = bool(result.get("healthz_ok") and result.get("search_ok"))
    return result


def _apply_handler_replacement(text: str) -> tuple[str, bool]:
    if "resolveAgentBootstrapOverlayFiles" in text:
        return text, False
    if HANDLER_OLD in text:
        return text.replace(HANDLER_OLD, HANDLER_NEW), True
    return text, False


def _backup(target_path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = DEFAULT_REPO_ROOT / ".hotfix-openclaw" / f"specialization-bridge-{ts}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / target_path.name
    shutil.copy2(target_path, backup_path)
    return backup_dir


def _print_smoke_result(smoke: dict[str, object]) -> None:
    status = "ok" if smoke.get("ok") else "fail"
    print(f"smoke-check {status}: searxng")
    for key, value in smoke.items():
        print(f"  {key}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify or reapply the live OpenClaw specialization bridge patch.")
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE, help="Path to auth-profiles bundle")
    parser.add_argument("--bootstrap-handler", type=Path, default=DEFAULT_BOOTSTRAP_HANDLER, help="Path to bootstrap-extra-files handler")
    parser.add_argument("--apply", action="store_true", help="Apply the patch in place if missing")
    parser.add_argument("--smoke-check", action="store_true", dest="smoke_check", help="Run a bounded SearXNG reachability check (GET /healthz + /search) after verifying patches")
    args = parser.parse_args()

    bundle_path = args.bundle.expanduser().resolve()
    handler_path = args.bootstrap_handler.expanduser().resolve()
    if not bundle_path.exists():
        print(f"missing bundle: {bundle_path}", file=sys.stderr)
        return 2
    if not handler_path.exists():
        print(f"missing bootstrap handler: {handler_path}", file=sys.stderr)
        return 2

    original_bundle = bundle_path.read_text(encoding="utf-8")
    original_handler = handler_path.read_text(encoding="utf-8")
    bundle_checks = _check_bundle_state(original_bundle)
    handler_checks = _check_handler_state(original_handler)
    dist_dir = bundle_path.parent
    extra_results = _apply_searxng_to_extra_bundles(dist_dir, apply=args.apply)

    # Warn about bundles introduced by an npm upgrade that are not yet in SEARXNG_EXTRA_BUNDLES.
    skip_names: set[str] = {bundle_path.name} | set(SEARXNG_EXTRA_BUNDLES)
    unregistered = _discover_unregistered_web_search_bundles(dist_dir, skip_names)
    if unregistered:
        print(f"warn: {len(unregistered)} unregistered bundle(s) with createWebSearchTool found — add to SEARXNG_EXTRA_BUNDLES:", file=sys.stderr)
        for bname in unregistered:
            print(f"  {bname}", file=sys.stderr)

    all_main_ok = all(bundle_checks.values()) and all(handler_checks.values())
    all_extra_ok = _extra_bundles_fully_patched(extra_results)

    if all_main_ok and all_extra_ok:
        print(f"ok: {bundle_path}")
        for key, value in bundle_checks.items():
            print(f"  {key}: {value}")
        print(f"ok: {handler_path}")
        for key, value in handler_checks.items():
            print(f"  {key}: {value}")
        for bname, checks in extra_results.items():
            print(f"searxng-extra {_extra_bundle_status(checks)}: {dist_dir / bname}")
            for key, value in checks.items():
                print(f"  {key}: {value}")
        if args.smoke_check:
            smoke = _smoke_check_searxng()
            _print_smoke_result(smoke)
            return 0 if smoke.get("ok") else 5
        return 0

    if not args.apply:
        if not all_main_ok:
            print(f"missing patch bits: {bundle_path}", file=sys.stderr)
            for key, value in bundle_checks.items():
                print(f"  {key}: {value}", file=sys.stderr)
            print(f"missing patch bits: {handler_path}", file=sys.stderr)
            for key, value in handler_checks.items():
                print(f"  {key}: {value}", file=sys.stderr)
        if not all_extra_ok:
            for bname, checks in extra_results.items():
                if checks.get("bundle_found") and checks.get("has_web_search_tool") and not checks.get("searxng_patched"):
                    print(f"unpatched searxng-extra: {dist_dir / bname}", file=sys.stderr)
                    for key, value in checks.items():
                        print(f"  {key}: {value}", file=sys.stderr)
        return 1

    updated_bundle, bundle_changed = _apply_bundle_replacements(original_bundle)
    if not bundle_changed and not all(_check_bundle_state(updated_bundle).values()):
        print("unable to reapply all required patch bits automatically", file=sys.stderr)
        return 3
    updated_handler, handler_changed = _apply_handler_replacement(original_handler)
    if not handler_changed and not all(_check_handler_state(updated_handler).values()):
        print("unable to reapply bootstrap overlay patch automatically", file=sys.stderr)
        return 3

    backup_dir = _backup(bundle_path)
    shutil.copy2(handler_path, backup_dir / handler_path.name)
    bundle_path.write_text(updated_bundle, encoding="utf-8")
    handler_path.write_text(updated_handler, encoding="utf-8")
    bundle_checks = _check_bundle_state(updated_bundle)
    handler_checks = _check_handler_state(updated_handler)
    print(f"patched: {bundle_path}")
    print(f"patched: {handler_path}")
    print(f"backup_dir: {backup_dir}")
    print(f"network_guard_file: {bundle_path}")
    for key, value in bundle_checks.items():
        print(f"  {key}: {value}")
    for key, value in handler_checks.items():
        print(f"  {key}: {value}")
    for bname, checks in extra_results.items():
        print(f"searxng-extra {_extra_bundle_status(checks)}: {dist_dir / bname}")
        for key, value in checks.items():
            print(f"  {key}: {value}")
    if args.smoke_check:
        smoke = _smoke_check_searxng()
        _print_smoke_result(smoke)
        if not smoke.get("ok"):
            return 5
    return 0 if all(bundle_checks.values()) and all(handler_checks.values()) and _extra_bundles_fully_patched(extra_results) else 4


if __name__ == "__main__":
    raise SystemExit(main())
