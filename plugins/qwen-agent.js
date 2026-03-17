const { spawn } = require("node:child_process");
const fs = require("node:fs").promises;
const os = require("node:os");
const path = require("node:path");

// Resolve registerAcpRuntimeBackend from the installed openclaw package.
// The path @openclaw/plugin-sdk/acp/runtime/registry does not exist as a package export;
// the function is available from openclaw/plugin-sdk/acpx (ACP-specific sub-bundle) or
// from the main openclaw/plugin-sdk index. Both resolve through the jiti-backed root-alias.cjs
// when loaded inside the openclaw gateway plugin loader.
let registerAcpRuntimeBackend;
(function resolveAcpRegistry() {
    const candidates = [
        "openclaw/plugin-sdk/acpx",
        "openclaw/plugin-sdk",
        "/home/rollan/.npm-global/lib/node_modules/openclaw/dist/plugin-sdk/root-alias.cjs",
    ];
    for (const candidate of candidates) {
        try {
            const mod = require(candidate);
            if (typeof mod.registerAcpRuntimeBackend === "function") {
                registerAcpRuntimeBackend = mod.registerAcpRuntimeBackend;
                return;
            }
        } catch (_) {
            // try next candidate
        }
    }
    throw new Error(
        "qwen-agent: could not resolve registerAcpRuntimeBackend from any of: " + candidates.join(", ")
    );
})();

const PLUGIN_ID = "qwen-agent";
const BACKEND_ID = "qwen_agent";
const DEFAULT_COMMAND = "python3 scripts/qwen_agent_bridge.py";
const COMMAND_RAW = (process.env.JARVIS_QWEN_BRIDGE_COMMAND || DEFAULT_COMMAND).trim();
const COMMAND_CWD = process.env.JARVIS_QWEN_BRIDGE_CWD || process.cwd();
const LOG_PATH = process.env.JARVIS_QWEN_BRIDGE_LOG || "/tmp/qwen_acp_bridge.log";

if (!COMMAND_RAW) {
    throw new Error("JARVIS_QWEN_BRIDGE_COMMAND must not be empty");
}

const BASE_COMMAND_PARTS = _splitShellTokens(COMMAND_RAW);
if (BASE_COMMAND_PARTS.length === 0) {
    throw new Error(`Unable to parse qwen bridge command: ${COMMAND_RAW}`);
}

function _splitShellTokens(command) {
    const matches = command.match(/(?:[^\s"']+|"[^"]*"|'[^']*')+/g);
    if (!matches) return [];
    return matches.map((token) => {
        if ((token.startsWith('"') && token.endsWith('"')) || (token.startsWith("'") && token.endsWith("'"))) {
            return token.slice(1, -1);
        }
        return token;
    });
}

function _buildRequestPayload({ text, requestId, handle }) {
    const prompt = String(text || "").trim();
    const normalizedMessages = prompt ? [{ role: "user", content: prompt }] : [];
    return {
        requestId: String(requestId || `qwen-${Date.now()}`),
        taskId: handle?.sessionKey || `qwen-${Date.now()}`,
        objective: prompt,
        prompt,
        lane: handle?.backend || BACKEND_ID,
        agent: handle?.sessionKey ? handle.sessionKey.split(":")[1] : "qwen",
        mode: "turn",
        messages: normalizedMessages,
    };
}

async function _writeJson(filePath, payload) {
    await fs.writeFile(filePath, JSON.stringify(payload, null, 2) + "\n", "utf8");
}

async function _appendLog(entry) {
    const line = `[${new Date().toISOString()}] ${entry}\n`;
    try {
        await fs.appendFile(LOG_PATH, line, "utf8");
    } catch (err) {
        // Swallow logging failures so the runtime still works.
    }
}

async function _runBridge(requestPath, resultPath) {
    const commandArgs = [
        ...BASE_COMMAND_PARTS.slice(1),
        "--request-file",
        requestPath,
        "--result-file",
        resultPath,
    ];
    return new Promise((resolve, reject) => {
        const child = spawn(BASE_COMMAND_PARTS[0], commandArgs, {
            cwd: COMMAND_CWD,
            env: {
                ...process.env,
                JARVIS_QWEN_BRIDGE_MODE: "turn",
            },
            stdio: ["ignore", "pipe", "pipe"],
        });

        let stderr = "";
        child.stderr.on("data", (chunk) => {
            stderr += chunk.toString();
        });

        child.on("error", (err) => reject(err));
        child.on("close", (code) => {
            if (code === 0) {
                resolve({ stderr });
            } else {
                const error = new Error(`qwen bridge exited ${code}: ${stderr.trim()}`);
                error.code = `bridge_exit_${code}`;
                reject(error);
            }
        });
    });
}

async function _runTurn({ handle, text, requestId }) {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), "qwen_acp_"));
    const requestPath = path.join(dir, "request.json");
    const resultPath = path.join(dir, "result.json");
    const payload = _buildRequestPayload({ text, requestId, handle });
    await _writeJson(requestPath, payload);
    const preview = String(payload.objective || "").replace(/\s+/g, " ").slice(0, 120);
    try {
        await _runBridge(requestPath, resultPath);
        const resultText = (await fs.readFile(resultPath, "utf8")).trim();
        const resultPayload = resultText ? JSON.parse(resultText) : {};
        const contentPreview = String(resultPayload.content || "").replace(/\s+/g, " ").slice(0, 200);
        await _appendLog(
            `session=${handle?.sessionKey || "unknown"} status=${resultPayload.status || "?"} content_len=${String(resultPayload.content || "").length} content_preview=${contentPreview}`
        );
        return resultPayload;
    } catch (error) {
        await _appendLog(
            `session=${handle?.sessionKey || "unknown"} request=${requestPath} result=${resultPath} preview=${preview} error=${error.message}`
        );
        throw error;
    } finally {
        await fs.rm(dir, { recursive: true, force: true });
    }
}

async function* _runTurnIterator(input) {
    const prompt = String(input.text || "").trim();
    if (!prompt) {
        yield { type: "error", message: "Qwen bridge received empty prompt", code: "empty_prompt" };
        yield { type: "done", stopReason: "error" };
        return;
    }
    const TOOL_CALL_PATTERN = /<tool_call\b/i;
    try {
        const result = await _runTurn({ handle: input.handle, text: prompt, requestId: input.requestId });
        const content = String(result.content || "").trim();
        if (TOOL_CALL_PATTERN.test(content)) {
            await _appendLog(
                `session=${input.handle?.sessionKey || "unknown"} EMIT=tool_markup_filtered raw_preview=${content.slice(0, 200)}`
            );
            yield {
                type: "text_delta",
                text: "(Qwen is processing your request.)",
                stream: "output",
                tag: "agent_message_chunk",
            };
            yield { type: "done", stopReason: "tool_markup_filtered" };
            return;
        }
        if (content) {
            await _appendLog(
                `session=${input.handle?.sessionKey || "unknown"} EMIT=text_delta stream=output len=${content.length} preview=${content.slice(0, 120).replace(/\s+/g, " ")}`
            );
            yield {
                type: "text_delta",
                text: content,
                stream: "output",
                tag: "agent_message_chunk",
            };
        } else {
            await _appendLog(
                `session=${input.handle?.sessionKey || "unknown"} EMIT=done_only content_empty=true`
            );
        }
        yield {
            type: "done",
            stopReason: result.status || "completed",
        };
    } catch (error) {
        yield {
            type: "error",
            message: `Qwen backend failure: ${error.message}`,
            code: error.code || "bridge_error",
        };
        yield {
            type: "done",
            stopReason: "error",
        };
    }
}

const runtime = {
    async ensureSession(input) {
        return {
            sessionKey: input.sessionKey,
            backend: BACKEND_ID,
            runtimeSessionName: `${input.agent}:${input.mode}:${input.sessionKey}`.replace(/::+/g, ":"),
        };
    },
    async *runTurn(input) {
        yield* _runTurnIterator(input);
    },
    async cancel() {
        // Stateless bridge – nothing to cancel.
    },
    async close() {
        // No-op.
    },
};

function register(_api) {
    registerAcpRuntimeBackend({
        id: BACKEND_ID,
        runtime,
        healthy: () => true,
    });
}

module.exports = {
    id: PLUGIN_ID,
    register,
};
