# Quant Infrastructure — Runtime Integration

How the live OpenClaw runtime consumes and uses the quant infra spine.

## Paths the Runtime Reads

| What | Path | Format |
|------|------|--------|
| Scout packet | `workspace/quant_infra/packets/scout/latest.json` | JSON |
| Hermes packet | `workspace/quant_infra/packets/hermes/latest.json` | JSON |
| Kitt packet | `workspace/quant_infra/packets/kitt/latest.json` | JSON |
| Fish packet | `workspace/quant_infra/packets/fish/latest.json` | JSON |
| Atlas packet | `workspace/quant_infra/packets/atlas/latest.json` | JSON |
| Sigma packet | `workspace/quant_infra/packets/sigma/latest.json` | JSON |
| DuckDB warehouse | `workspace/quant_infra/warehouse/quant.duckdb` | DuckDB |
| Kitt briefs | `workspace/quant_infra/research/kitt_briefs/latest.md` | Markdown |
| Fish scenarios | `workspace/quant_infra/research/fish_scenarios/latest.md` | Markdown |
| Market environment | `workspace/quant_infra/research/environment/latest.md` | Markdown |
| Operator report | `workspace/quant_infra/logs/latest_operator_report.txt` | Text |

## Paths the Runtime Writes

| What | Module | Writes to |
|------|--------|-----------|
| OpenBB market data | `openbb/fetch_market_context.py` | DuckDB + hermes packet |
| Paper positions | `kitt/paper_trader.py` | DuckDB + kitt packet + briefs |
| Scenarios | `fish/scenario_engine.py` | DuckDB + fish packet + scenario artifacts |
| Experiments | `atlas/experiment_surface.py` | DuckDB + atlas packet |
| Validations | `sigma/validation_surface.py` | DuckDB + sigma packet |
| Token usage | `jarvis/token_ledger.py` | DuckDB |
| Operator reports | `jarvis/observability.py` | logs/ |

## How to Run from the Live Runtime

### From existing quant lane code (Python 3.14 runtime)
```python
# Read a lane packet
import json
from pathlib import Path
qi = Path.home() / ".openclaw/workspace/jarvis-v5/workspace/quant_infra"
kitt_packet = json.loads((qi / "packets/kitt/latest.json").read_text())

# Query DuckDB warehouse
import duckdb
con = duckdb.connect(str(qi / "warehouse/quant.duckdb"), read_only=True)
latest_bars = con.execute("SELECT * FROM v_nq_daily_enriched ORDER BY bar_date DESC LIMIT 5").fetchall()
con.close()
```

### From a lane timer or cron job
```bash
# Refresh market data via OpenBB (uses 3.12 venv)
workspace/quant_infra/env/.venv-openbb/bin/python3 \
    workspace/quant_infra/openbb/fetch_market_context.py

# Run scenario generation
.venv/bin/python3 workspace/quant_infra/fish/scenario_engine.py

# Check paper trading status
.venv/bin/python3 workspace/quant_infra/kitt/paper_trader.py --status

# Generate operator report
.venv/bin/python3 workspace/quant_infra/jarvis/observability.py
```

### Subprocess pattern for OpenBB from main runtime
Since the main runtime uses Python 3.14 and OpenBB requires 3.12, use subprocess:
```python
import subprocess, json
result = subprocess.run(
    ["workspace/quant_infra/env/.venv-openbb/bin/python3",
     "workspace/quant_infra/openbb/fetch_market_context.py"],
    capture_output=True, text=True, cwd=PROJECT_ROOT,
)
# After the script runs, the latest packets and DuckDB are updated
# Read them normally from the 3.14 runtime
```

## Python Version Compatibility

| Component | Python Version | Reason |
|-----------|---------------|--------|
| DuckDB warehouse | 3.14 (main .venv) | DuckDB supports 3.14 |
| OpenBB adapter | 3.12 (quant_infra/env/.venv-openbb) | OpenBB requires <3.14 |
| Kitt paper_trader | 3.14 (main .venv) | Uses DuckDB only |
| Fish scenario_engine | 3.14 (main .venv) | Uses DuckDB only |
| Atlas/Sigma surfaces | 3.14 (main .venv) | Uses DuckDB only |
| Jarvis observability | 3.14 (main .venv) | Uses DuckDB only |

## Integration with Existing workspace/quant/ Runtime

The quant_infra spine is **complementary** to the existing `workspace/quant/` live runtime.
The existing runtime handles real-time lane coordination, packet routing via shared/latest,
and live governor/executor control. The quant_infra spine adds:

1. **DuckDB warehouse** — persistent analytical store not available in the file-based runtime
2. **OpenBB data** — structured market data backend beyond cron-ingested CSVs
3. **Paper trading state machine** — bounded, auditable position tracking in DuckDB
4. **Scenario generation** — systematic scenario analysis with DuckDB-backed persistence
5. **Experiment/validation surfaces** — structured interfaces for Atlas and Sigma

The two systems can coexist. Lanes can read from both `workspace/quant/shared/latest/`
(live runtime packets) and `workspace/quant_infra/packets/` (infrastructure packets).
