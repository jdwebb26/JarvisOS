# Quant Infrastructure Spine v1

**Version**: 1.0.0
**Date**: 2026-03-19
**Status**: Live — initial pass

---

## Purpose

This spec defines the quant infrastructure backbone for OpenClaw/Jarvis.
It provides the data plumbing, storage layer, packet contracts, and lane
boundaries that let Kitt, Fish, Atlas, Sigma, Scout, and Hermes operate
as a coherent quant system instead of disconnected ideas.

The spine is implementation-oriented. Every section maps to real code,
real files, and real runtime paths.

---

## Lane Ownership

| Lane | Role | Owns | Does NOT own |
|------|------|------|--------------|
| **Scout** | Reconnaissance | Market news, catalysts, events, regime observations | Quant compute, trading |
| **Hermes** | Synthesis | Macro/environment/risk framing from Scout inputs | Direct data pulls, trading |
| **Kitt** | Quant brain | OpenBB access, DuckDB consumption, paper trading, risk metrics, options context | Live trading, execution |
| **Fish** | Scenario/simulation | "What if" scenarios around Kitt outputs, invalidation cases | Live trading, direct orders |
| **Atlas** | Experiment | vectorbt-style exploration, experiment design, candidate generation | Validation, trading |
| **Sigma** | Validation | Strategy validation, backtesting.py comparison, promotion gates | Live trading, experiment design |
| **Jarvis** | Operator/orchestrator | Token ledger, observability, operator surfaces | Raw quant compute |

---

## Packet Flow

```
Scout → Hermes → Kitt → Fish → Atlas/Sigma → Jarvis (operator visibility)
```

### Scout Packet
- **Type**: `scout_recon`
- **Contains**: news items, catalysts, events, regime-relevant observations
- **Source**: RSS/news feeds, market scanners, scheduled reconnaissance
- **Output**: `packets/scout/latest.json`

### Hermes Packet
- **Type**: `hermes_synthesis`
- **Contains**: synthesized macro environment, risk framing, volatility regime assessment
- **Upstream**: Scout packet + external research
- **Output**: `packets/hermes/latest.json`

### Kitt Packet
- **Type**: `kitt_quant`
- **Contains**: actionable quant context, current paper positions, candidate trade actions, risk summary, options context
- **Upstream**: Hermes packet + OpenBB data + DuckDB warehouse
- **Output**: `packets/kitt/latest.json`

### Fish Packet
- **Type**: `fish_scenario`
- **Contains**: scenario outcomes (bull/bear/neutral), invalidation cases, risk assessments
- **Upstream**: Kitt packet + DuckDB warehouse context
- **Output**: `packets/fish/latest.json`

### Atlas Packet
- **Type**: `atlas_experiment`
- **Contains**: experiment-ready inputs, parameter sweeps, candidate strategies for exploration
- **Upstream**: Fish scenarios + historical data
- **Output**: `packets/atlas/latest.json`

### Sigma Packet
- **Type**: `sigma_validation`
- **Contains**: validation results, backtest comparisons, promotion recommendations
- **Upstream**: Atlas experiments + Strategy Factory outputs
- **Output**: `packets/sigma/latest.json`

---

## Storage Model

### DuckDB Warehouse
- **Location**: `workspace/quant_infra/warehouse/quant.duckdb`
- **Purpose**: Local analytical warehouse for quant context and cross-lane data
- **Bootstrap**: `workspace/quant_infra/warehouse/bootstrap.py`

#### Core Tables

| Table | Purpose | Written by | Read by |
|-------|---------|-----------|---------|
| `market_environment_snapshots` | Periodic macro/VIX/regime snapshots | OpenBB adapter, cron | Kitt, Fish, Hermes |
| `market_news_items` | Structured news/catalyst items | Scout | Hermes, Kitt |
| `kitt_paper_positions` | Open and closed paper positions | Kitt paper trader | Kitt, Fish, Sigma, Jarvis |
| `kitt_trade_decisions` | Paper trade decision log with reasoning | Kitt paper trader | Kitt, Fish, Sigma, Jarvis |
| `fish_scenarios` | Scenario outputs and invalidation cases | Salmon Adapter (for Fish) | Atlas, Sigma, Jarvis |
| `sigma_validation_inputs` | Validation-ready strategy data | Sigma | Sigma |
| `atlas_experiment_inputs` | Experiment configurations and results | Atlas | Atlas, Sigma |
| `ohlcv_daily` | Daily OHLCV bars (loaded from CSV) | Loader | All lanes |

### File-based Packets
- **Location**: `workspace/quant_infra/packets/<lane>/latest.json`
- **Format**: JSON with standard envelope (see Packet Schema below)
- **Retention**: `latest.json` always current; historical in timestamped files

### Research Artifacts
- **Location**: `workspace/quant_infra/research/<category>/`
- **Categories**: `news/`, `environment/`, `risk/`, `options/`, `kitt_briefs/`, `fish_scenarios/`
- **Format**: Markdown summaries + JSON structured data

---

## Data Source Model

### OpenBB (Primary structured data backend)
- **Adapter**: `workspace/quant_infra/openbb/adapter.py`
- **Venv**: `workspace/quant_infra/env/.venv-openbb/` (Python 3.12, OpenBB requires <3.14)
- **Capabilities**:
  - Market indices and futures context via yfinance provider
  - Volatility data (VIX, term structure)
  - Economic calendar and macro indicators
  - News aggregation
  - Options data (when provider keys configured)
- **Config**: `workspace/quant_infra/openbb/config.py` reads from env

### Cron-ingested CSV (Existing pipeline)
- **Location**: `~/.openclaw/workspace/data/`
- **Files**: `NQ_daily.csv`, `NQ_hourly.csv`, `NQ_15m.csv`, `NQ_1min.csv`
- **Provider**: yfinance via `strategy_factory/scripts/cron_ingest.sh`
- **Schedule**: Daily 4:00 AM UTC
- **Integration**: DuckDB loader imports these into `ohlcv_daily` table

### Data Freshness
- Cron CSV: updated daily 4:00 AM, staleness tracked via `data_freshness_hours`
- OpenBB pulls: on-demand with caching, staleness in packet metadata
- DuckDB: materialized at load time, views always current against loaded data

---

## Live Paper Trading Boundaries

### What Kitt CAN do
- Consume Scout/Hermes market context
- Pull data via OpenBB adapter
- Query DuckDB warehouse for historical context
- Form paper trade candidates with reasoning
- Open/close paper positions (PAPER ONLY)
- Track P&L, mark-to-market, and position status
- Write auditable decision logs
- Produce quant packets for downstream lanes

### What Kitt CANNOT do
- Place live/real trades (NEVER)
- Access real broker accounts
- Execute orders without kill switch check
- Bypass the existing executor approval flow for any live activity

### Paper Trading State
- **Portfolio state**: `warehouse/quant.duckdb` → `kitt_paper_positions` table
- **Decision log**: `warehouse/quant.duckdb` → `kitt_trade_decisions` table
- **Latest brief**: `research/kitt_briefs/latest.md`
- **JSON state**: `packets/kitt/latest.json`

---

## Observability Model

### Jarvis Token Ledger
- **Module**: `workspace/quant_infra/jarvis/token_ledger.py`
- **Scope**: Jarvis operator surface ONLY
- **Tracks**: LLM token usage per lane/session, cost estimates, throughput
- **Storage**: DuckDB `token_usage` table + JSON summary

### Lane Health
- **Module**: `workspace/quant_infra/jarvis/observability.py`
- **Provides**: operator-facing summary of what each lane produced, when, and whether it succeeded
- **Reads**: all `packets/<lane>/latest.json` timestamps and status fields
- **Output**: operator summary suitable for Discord #flowstate or dashboard

---

## Scope: Now vs Later

### In scope (v1 — this pass)
- DuckDB warehouse with core tables and views
- OpenBB adapter with market context fetch
- Packet writers and schema for all 6 lanes
- Kitt paper trading state machine (open/close/track)
- Salmon Adapter (scenario feeder for Fish lane: consume Kitt → produce scenarios)
- Atlas experiment surface (receive structured inputs)
- Sigma validation surface (receive structured inputs)
- Jarvis token ledger and observability stubs
- CSV → DuckDB loader for existing cron data
- Spec and README

### Deferred (v2+)
- Live streaming market data
- Full vectorbt automation for Atlas
- Full backtesting.py harness for Sigma
- Options chain deep integration (requires API keys)
- Automated scenario timers for Fish (via Salmon Adapter)
- Multi-symbol support beyond NQ
- Vector/embedding store for Atlas experiments
- Real-time P&L streaming for Kitt paper positions

---

## Packet Schema (Standard Envelope)

Every packet JSON follows this envelope:

```json
{
  "packet_type": "<lane>_<type>",
  "lane": "<lane_name>",
  "timestamp": "ISO-8601",
  "version": "1.0.0",
  "summary": "Human-readable one-liner",
  "upstream": ["<packet_type that fed this>"],
  "data": { },
  "metadata": {
    "source_module": "<module path>",
    "data_freshness_hours": 0.0,
    "confidence": 0.0
  }
}
```

---

## Runtime Integration

The live OpenClaw runtime reads from:
1. `workspace/quant_infra/packets/<lane>/latest.json` — lane outputs
2. `workspace/quant_infra/warehouse/quant.duckdb` — analytical queries
3. `workspace/quant_infra/research/` — human-readable artifacts

The live runtime writes to:
1. DuckDB tables via `warehouse/loader.py` and `warehouse/bootstrap.py`
2. Packet files via `packets/writer.py`
3. Research artifacts via lane-specific modules

Scripts the operator can run today:
- `python3 workspace/quant_infra/warehouse/bootstrap.py` — initialize/reset DuckDB
- `workspace/quant_infra/openbb/fetch_market_context.py` — pull OpenBB data
- `python3 workspace/quant_infra/kitt/paper_trader.py --status` — check paper positions
- `python3 workspace/quant_infra/salmon/adapter.py` — Salmon Adapter: generate scenarios for Fish lane
- `python3 workspace/quant_infra/jarvis/observability.py` — operator summary

All scripts use the project venv at `.venv/` for DuckDB, and the OpenBB venv at
`workspace/quant_infra/env/.venv-openbb/` for OpenBB-specific operations.
