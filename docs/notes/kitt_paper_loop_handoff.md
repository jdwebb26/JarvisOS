# Kitt Paper Trading Loop — Handoff Note

## What was built

A bounded autonomous paper-trading cycle for Kitt that runs every 10 minutes via systemd timer.

## Files

| File | Purpose |
|------|---------|
| `workspace/quant_infra/kitt/run_kitt_cycle.py` | Cycle runner — fetch price, compute signal, decide, execute paper trade, write artifacts |
| `systemd/user/openclaw-kitt-paper.service` | Systemd oneshot service |
| `systemd/user/openclaw-kitt-paper.timer` | 10-minute timer |

## How it works

Each cycle:
1. Fetches 60 recent 15-minute NQ bars from yfinance
2. Checks open positions for stop/TP hits, marks to market
3. Computes mean-reversion signal: EMA(8)/EMA(21) crossover with ATR(14) threshold
4. Decides: open_long / open_short / hold / no_trade / skip
5. Executes paper action via DuckDB warehouse
6. Writes: decision record (DuckDB), packet (packets/kitt/latest.json), brief (research/kitt_briefs/latest.md)

## Constraints (by design)

- PAPER ONLY — no live trading hooks exist
- Max 1 open position at a time
- No pyramiding or martingale
- Conservative entry: 1.8 * ATR deviation from EMA(21)
- Stop: 2.5 * ATR, Take-profit: 1.5 * ATR
- Minimum ATR of 20 NQ points to trade

## To enable the live timer

```bash
# Copy units from repo (or use sync script)
cp systemd/user/openclaw-kitt-paper.service ~/.config/systemd/user/
cp systemd/user/openclaw-kitt-paper.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now openclaw-kitt-paper.timer
```

## To run manually

```bash
cd ~/.openclaw/workspace/jarvis-v5
.venv/bin/python3 workspace/quant_infra/kitt/run_kitt_cycle.py           # real cycle
.venv/bin/python3 workspace/quant_infra/kitt/run_kitt_cycle.py --dry-run # signal only
.venv/bin/python3 workspace/quant_infra/kitt/run_kitt_cycle.py --status  # show positions
```

## Artifacts per cycle

- `workspace/quant_infra/packets/kitt/latest.json` — structured packet
- `workspace/quant_infra/research/kitt_briefs/latest.md` — human-readable brief
- `workspace/quant_infra/warehouse/quant.duckdb` → `kitt_trade_decisions` table
