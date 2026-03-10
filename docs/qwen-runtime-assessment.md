# Qwen Runtime Assessment: Real Code Present (2026-03-06)

## Discovery Summary

This document summarizes the **actual runtime code** currently present in three key directories based on file inspection. It distinguishes between working implementations, skeleton files, and empty placeholders.

---

## tasks/ — Task Orchestration Layer

### Active Runtime Code (Working)
- **`ralph_worker.py`** (5179 bytes) - **Task dispatcher**: Queries SQLite `tasks.db` for pending tasks ordered by priority DESC, routes them to Discord lanes via webhooks based on task kind/priority. Updates status to "running" after successful dispatch.

- **`local_executor.py`** (41117 bytes) - **Task classifier & executor**: Classifies incoming tasks into categories (strategy_factory, ops_report, infra_fix, notification_feature, publish_repo, loop_analysis, generic). Contains Discord bot notification system via `notify_task_event()`. Includes template code generators for NQ futures strategy framework.

- **`todo_intake.py`** (6948 bytes) - **Task intake handler**: Processes new tasks from Discord channels into the SQLite database. Maintains state files (`todo_state.json`, `updates_state.json`).

- **`live_config.py`** (783 bytes) - **Configuration constants**: Defines shared paths for database, secrets file, inbox/results directories. Maps named channels to Discord IDs.

### Supporting Infrastructure
- **SQLite database** (`tasks.db`) - Persistent task queue with status tracking (pending/running/completed/blocked)
- **Results directory** (`results/*.md`) - Markdown artifacts documenting task outcomes
- **Log files** (`local_executor.log`, `ralph_worker.log`) - Runtime execution logs

### Status: Production-ready orchestration layer with active task routing and notification system.

---

## strategy_factory/ — NQ Futures Strategy Framework (Skeleton)

### Active Implementation Files
- **`folds.py`** (2286 bytes) - **Fold builder**: Implements rolling/anchored fold generation with purge gap validation to prevent data leakage. Includes sentinel mode for testing.

- **`config.py`** (2985 bytes) - **Configuration schema**: Defines `TIMEFRAME_GATES`, `SESSION_SLIPPAGE`, `FILL_MODEL`, `REGIMES` dictionaries. Contains `DEFAULT_CONFIG` with instrument specs, feature lookbacks, and risk parameters.

- **`sim.py`** (2270 bytes) - **Simulation runner**: Basic candidate evaluation framework with soft saturation function for trade count normalization. Implements drawdown breach detection and insufficient trades rejection logic.

### Skeleton/Placeholder Files
- **`artifacts.py`**, **`cli.py`**, **`data.py`**, **`features.py`** (13-2461 bytes) - Partial implementations with basic structure but limited functionality
- **`gates.py`** (1004 bytes) - Gate validation logic present but untested in production
- **`regimes.py`** (379 bytes) - Regime labeling framework exists
- **Empty/minimal files**: `diversity.py`, `lambda_sweep.py`, `perturbation.py`, `scoring.py`, `stress.py` (<100 bytes each)

### Test Files
- **`test_folds.py`**, **`test_gates.py`**, **`test_sim.py`** - Unit tests present but coverage appears limited

### Configuration
- **`configs/default.yaml`** (188 bytes) - Minimal fold specification for NQ 5_60m intraday
- **`README.md`** (338 bytes) - Documents phased development roadmap (P1-P4)

### Status: **Phase 1 skeleton with core fold/config/sim infrastructure**. Missing full feature computation, strategy logic, and production testing. Not yet runnable end-to-end.

---

## jarvis-v5/ — Qwen Agent Runtime (Smoke Test Only)

### Active Runtime Code
- **`runtime/core/qwen_agent_smoke.py`** (11733 bytes) - **Qwen-Agent wrapper**: Thin wrapper around qwen-agent library providing three workspace tools:
  - `workspace_list_files`: Directory listing with path validation, size filtering, and binary exclusion
  - `workspace_read_file`: UTF-8 text file reading with character capping (default 16000)
  - `workspace_write_file`: Safe file writing with parent directory creation

### Configuration & Environment
- **Environment variables**: `JARVIS_WORKSPACE`, `QWEN_AGENT_MODEL_SERVER`, `MODEL_NAME`, `API_KEY`, `ENABLE_THINKING`, `USE_RAW_API`
- **System message**: Defines agent behavior constraints (stay in workspace, read before edit, don't invent missing pieces)
- **Path validation**: Prevents escape from allowed workspace via parent directory checks
- **File filtering**: Skips `.git`, `.venv`, virtualenvs, large files (>500KB), and binary formats

### Empty/Placeholder Files (0 bytes)
- `docs/channels.md` - Empty placeholder
- `docs/flowstate.md` - Empty placeholder  
- `config/app.example.yaml` - Empty template
- `config/channels.example.yaml` - Empty template
- `config/models.example.yaml` - Empty template
- `config/policies.example.yaml` - Empty template
- `scripts/doctor.py`, `install.sh`, `validate.py` - All empty scripts

### Preserved Artifacts (Not Active)
- **`.venv-qwen-agent/`** - Archived Python virtual environment with qwen-agent dependencies
- **`_cleanup_archive/2026-03-06/`** - Old v5 scripts being cleaned up (`apply_live_v5_patch.sh`, `create_task_direct.py`)

### Status: **Smoke test runner only**. Provides basic file I/O tools for Qwen agent but lacks full orchestration, state management, or production deployment. Empty config/docs indicate incomplete setup.

---

## Overall Assessment

| Component | Status | Production Ready? | Key Gaps |
|-----------|--------|-------------------|----------|
| **tasks/** | Active orchestration | ✅ Yes | None significant |
| **strategy_factory/** | Phase 1 skeleton | ❌ No | Missing feature computation, strategy logic, full testing |
| **jarvis-v5/** | Smoke test only | ❌ No | Empty configs/docs, no state management, no production deployment |

### Recommendations
1. **tasks/** is the most mature component and can be relied upon for task routing
2. **strategy_factory/** needs P2 features (gates, execution realism) before strategy evaluation
3. **jarvis-v5/** requires full config population and state management integration to become production-ready
4. Consider consolidating documentation into active files rather than empty placeholders

---
*Generated by Qwen agent during workspace inspection*
