# Quant Infrastructure Spine

Local quant data pipeline and storage backbone for OpenClaw/Jarvis.

## Quick Start

```bash
# 1. Bootstrap DuckDB warehouse (loads existing CSV data)
cd /path/to/jarvis-v5
.venv/bin/python3 workspace/quant_infra/warehouse/bootstrap.py

# 2. Pull fresh market context via OpenBB
workspace/quant_infra/env/.venv-openbb/bin/python3 workspace/quant_infra/openbb/fetch_market_context.py

# 3. Check Kitt paper trading status
.venv/bin/python3 workspace/quant_infra/kitt/paper_trader.py --status

# 4. Generate Fish scenarios from latest Kitt state
.venv/bin/python3 workspace/quant_infra/fish/scenario_engine.py

# 5. Operator summary
.venv/bin/python3 workspace/quant_infra/jarvis/observability.py
```

## Directory Layout

```
quant_infra/
├── specs/quant_spine_v1.md    # Versioned infrastructure spec
├── env/                        # OpenBB venv (Python 3.12)
├── openbb/                     # OpenBB adapter layer
│   ├── adapter.py              # Core data fetching
│   ├── config.py               # Provider config
│   └── fetch_market_context.py # CLI entry point
├── warehouse/                  # DuckDB analytical warehouse
│   ├── bootstrap.py            # Schema init + CSV loader
│   ├── loader.py               # Data loading utilities
│   ├── sql/schema.sql          # Table definitions
│   ├── sql/views.sql           # Analytical views
│   └── quant.duckdb            # Database file (created by bootstrap)
├── packets/                    # Lane output packets (JSON)
│   ├── writer.py               # Packet write utility
│   └── {scout,hermes,kitt,fish,atlas,sigma}/latest.json
├── research/                   # Human-readable artifacts
│   ├── kitt_briefs/
│   └── fish_scenarios/
├── kitt/paper_trader.py        # Paper trading state machine
├── fish/scenario_engine.py     # Scenario generation
├── atlas/experiment_surface.py # Experiment ingestion interface
├── sigma/validation_surface.py # Validation ingestion interface
├── jarvis/
│   ├── token_ledger.py         # LLM token usage tracking
│   └── observability.py        # Operator summary surface
└── logs/                       # Runtime logs
```

## Lane Packet Flow

```
Scout → Hermes → Kitt → Fish → Atlas/Sigma → Jarvis (operator)
```

Each lane reads upstream packets and writes its own `packets/<lane>/latest.json`.

## Data Sources

- **OpenBB** (via `openbb/adapter.py`): Market indices, VIX, economic data, news
- **Cron CSV** (existing): `~/.openclaw/workspace/data/NQ_*.csv` loaded into DuckDB
- **DuckDB** (`warehouse/quant.duckdb`): Unified analytical store

## Paper Trading (Kitt)

Kitt owns autonomous paper trading. Positions and decisions are tracked in DuckDB
and are fully auditable. NO live trades. See `kitt/paper_trader.py`.

## Spec

Full spec: `specs/quant_spine_v1.md`
