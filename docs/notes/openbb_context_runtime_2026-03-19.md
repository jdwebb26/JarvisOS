# OpenBB Market Context — Runtime Operationalization

**Date**: 2026-03-19
**Branch**: feat/openbb-context merged → main

## What was done

Merged the hardened OpenBB market-context pipeline from `feat/openbb-context` into
`main` and operationalized it as a systemd user timer.

### Merge

Two commits landed from `feat/openbb-context`:
- `9e7bd64` feat(openbb): harden market context fetch and improve scout/hermes packets
- `c3358c3` fix(openbb): round prices to 2dp and sort news by date descending

Changes: `adapter.py` (+269/-68 lines), `fetch_market_context.py` (+456/-68 lines).

Key improvements over the pre-merge version:
- Direct yfinance fallback when OpenBB endpoints fail (bypasses SDK entirely)
- Scout packet generation (`packets/scout/latest.json`)
- Hermes packet with regime classification
- News sorted newest-first
- Prices rounded to 2dp
- Every output section fails independently — no single-point-of-failure
- Source provenance field on every data section

### Systemd units

| File | Purpose |
|------|---------|
| `systemd/user/openclaw-openbb-context.service` | Oneshot service using OpenBB venv Python 3.12 |
| `systemd/user/openclaw-openbb-context.timer` | Fires every 60 minutes on the hour |

**Cadence**: Every 60 minutes, all day. Persistent=true ensures missed ticks fire on wake.
RandomizedDelaySec=30 prevents exact-second thundering herd with other timers.

**Venv**: `/home/rollan/.openclaw/workspace/jarvis-v5/workspace/quant_infra/env/.venv-openbb/bin/python3`
(Python 3.12 — required because OpenBB does not support 3.14).

**WorkingDirectory**: Set to the `openbb/` dir so `from adapter import ...` resolves.

### Outputs written per run

| Output | Path |
|--------|------|
| Scout packet | `workspace/quant_infra/packets/scout/latest.json` |
| Hermes packet | `workspace/quant_infra/packets/hermes/latest.json` |
| Environment research | `workspace/quant_infra/research/environment/latest.md` |
| News research | `workspace/quant_infra/research/news/latest.md` |
| Risk stub | `workspace/quant_infra/research/risk/latest.md` |
| Options stub | `workspace/quant_infra/research/options/latest.md` |
| DuckDB snapshot | `workspace/quant_infra/warehouse/quant.duckdb` |
| Raw debug JSON | `workspace/quant_infra/warehouse/snapshots/latest_openbb.json` |

### First live run results

- **Status**: SUCCESS (exit 0)
- **Sections**: 3/4 succeeded (quotes, vix, news via yfinance-direct; calendar failed — no free provider)
- **NQ**: 24465.75 | **VIX**: 25.3 | **SPY**: 656.26 | **QQQ**: 589.28
- **Regime**: high_vol
- **News**: 15 headlines, sorted newest-first
- **CPU time**: 10.6s
- **No crash loop** — oneshot exits cleanly

### What was NOT touched

- Strategy Factory
- Kitt paper trading loop
- Fish/Salmon adapter
- OpenBB internal imports (the `OBBject_EquityInfo` import failure is upstream — yfinance fallback handles it)

## Preflight / Postdeploy

- `scripts/preflight.sh` — CLEAR (0 failures, 2 pre-existing warnings)
- `scripts/postdeploy.sh` — CLEAN (0 failures, 1 pre-existing warning)

## Next steps

- Monitor journal for crash loops over 24h: `journalctl --user -u openclaw-openbb-context -f`
- Consider market-hours-only schedule if cost/noise matters later
- Economic calendar will auto-recover if OpenBB upstream fixes the import or a free provider is configured
