# Qwen-v5 Integration Plan

## Phase 1: Smoke Runner
Deploy `runtime/core/qwen_agent_smoke.py` as the initial runtime entry point. Validate workspace file I/O tools (`workspace_list_files`, `read_file`, `write_file`) with path validation and size filtering. Use existing environment variables (`JARVIS_WORKSPACE`, `QWEN_AGENT_MODEL_SERVER`). Target: confirm agent can safely read/write within allowed directory boundaries without escaping.

## Phase 2: Task/Artifact Adapter
Bridge Qwen-agent outputs to the tasks layer. Parse task classifications from `local_executor.py` (strategy_factory, ops_report, infra_fix, notification_feature). Route artifacts to `results/*.md` format matching existing templates. Integrate with `live_config.py` channel mappings for Discord notifications via `notify_task_event()`.

## Phase 3: Controlled Task Execution
Implement task lifecycle management using SQLite `tasks.db`. Status transitions: pending → running → completed/blocked. Use `ralph_worker.py` webhook dispatch pattern for lane routing (review/anton/builder). Add execution timeouts, retry logic, and artifact validation before marking tasks complete.

## Phase 4: Optional Jarvis Integration
Connect to full Qwen-agent orchestration with state persistence. Populate empty configs (`config/*.yaml`) and docs (`docs/*.md`). Enable multi-step task chains via `jarvis-v5/` runtime. Requires production deployment infrastructure beyond current smoke test scope.