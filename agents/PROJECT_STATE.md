# OpenClaw — Vizor & ICT Agents: Project State
# Last updated: 2026-03-19

This document is the single source of truth for the Vizor and ICT agent subsystem.
Any Claude instance reading this should be able to fully understand, audit, and continue development.

## Architecture Overview

```
WORKSTATION (Koolkid)                      NIMO (Windows 11, 64GB RAM)
Tailscale: 100.84.23.108                   Tailscale: 100.70.114.34
WSL Ubuntu: /home/rollan/.openclaw/
                                           LM Studio: port 1234 (existing)
  openclaw.json (master config)            llama-server: port 8801 (Vizor Personal)
  agents/vizor/ (agent definition)         llama-server: port 8802 (Vizor Swarm)
  agents/ict/   (agent definition)         llama-server: port 8803 (ICT Expert)

D:\discord_screenshots\ (swarm data)       C:\models\ (model files)
D:\vizor_training\ (personal data)         C:\training_data\ (synced from workstation)
D:\ict_training\ (transcript data)
                                           All 3 models: Qwen3-VL-8B-Instruct Q8_0
C:\Users\jdweb\Documents\ (scripts)        with mmproj-F16 for vision capability
```

## Agents

### Vizor — Visual Quant Analyst
- **What**: Reads trading charts, identifies ICT/SMC patterns visually, rates setups
- **Dual model**: EyeNet-Personal (sacred, operator-approved data only) + EyeNet-Swarm (research data)
- **Discord channel**: #vizor (1484324994552172544)
- **Models**: ports 8801 (personal) and 8802 (swarm) on NIMO
- **Config**: openclaw.json agent id "vizor", providers "vizor_personal" and "vizor_swarm"
- **Agent dir**: /home/rollan/.openclaw/agents/vizor/
- **Quant Lanes role**: Visual analysis service for Kitt, Atlas, Sigma, Fish, TradeFloor

### ICT — Methodology Expert (Multimodal)
- **What**: Definitive authority on ICT (Inner Circle Trader / Michael J. Huddleston) methodology
- **Multimodal**: Vision + text because ICT teaches by pointing at charts while talking
- **Discord channel**: #ict (1484325009391489064)
- **Model**: port 8803 on NIMO
- **Config**: openclaw.json agent id "ict", provider "ict_expert"
- **Agent dir**: /home/rollan/.openclaw/agents/ict/
- **Quant Lanes role**: Methodology validation oracle for all lanes

## NIMO Infrastructure

- **OS**: Windows 11 (NOT Linux — instructions adapted accordingly)
- **RAM**: 64GB (tight with LM Studio + 3 servers; may need Q4_K_M quantization)
- **GPU**: AMD Radeon 8060S (Strix Halo iGPU) — Vulkan for GPU accel, no CUDA
- **Services**: NSSM (not systemd) for auto-start Windows services
- **Model dirs**: C:\models\{vizor-personal,vizor-swarm,ict-expert}\active\ (junction points)
- **Setup instructions**: C:\Users\jdweb\Documents\NIMO_CLAUDE_CODE_INSTRUCTIONS.md

## Training Data Status

### Vizor Personal (EyeNet-Personal, port 8801)
- **Source**: Operator-approved screenshots from Discord #vizor channel
- **Collection method**: vizor_screenshot_collector.py (emoji-based approval: checkmark/X reactions)
- **Status**: Collector script ready, NOT YET RUNNING
- **Data location**: D:\vizor_training\personal\ (approved), D:\vizor_training\quarantine\ (pending)

### Vizor Swarm (EyeNet-Swarm, port 8802)
- **Source**: Backtesters Anon Discord server — chart screenshots
- **Collection method**: discord_targeted_scraper.py (~80 high-value channels)
- **Status**: Original scraper got 10,437 images (2.1 GB). Targeted scraper ready but not yet run.
- **Data location**: D:\discord_screenshots\ (organized by channel subdirectory)
- **Known issue**: PNL screenshots are useless noise — need filter/classifier to remove them
- **Channels scraped**: #rules, #the-floor (original). Targeted scraper covers dogwatch, concept channels, mentorship episodes, backtesting, model/setup channels, live trade channels

### ICT Expert (port 8803)
- **Source**: ICT YouTube channel transcripts (752 videos indexed, 621 transcripts downloaded)
- **Scraper**: ict_transcript_scraper.py (priority playlists first, then remaining channel)
- **Status**: COMPLETE — 24,947 raw training pairs generated
- **Filter**: ict_training_filter.py (transition detection: chart-teaching vs chitchat)
- **Status**: Filter runs but needs tuning — currently keeps ~86%, target ~30-40%
- **Data location**: D:\ict_training\training_pairs.jsonl (raw), training_filtered.jsonl (filtered)
- **Future**: Video frame extraction with transcript alignment for multimodal training
- **Key insight**: ICT's mouse position indicates teaching mode (moving = pointing at chart = teaching)

## Scripts (all on workstation at C:\Users\jdweb\Documents\)

| Script | Purpose | Status |
|--------|---------|--------|
| vizor_screenshot_collector.py | Collects operator screenshots from #vizor, emoji approval flow | Ready, not running |
| discord_targeted_scraper.py | Scrapes ~80 channels from Backtesters Anon for chart images | Ready, not yet run |
| ict_transcript_scraper.py | Scrapes ICT YouTube transcripts, generates training pairs | COMPLETE (24,947 pairs) |
| ict_training_filter.py | Filters ICT training data: chart-teaching vs chitchat | Working, needs threshold tuning |
| nimo_training_sync.py | Syncs training data to NIMO via scp over Tailscale | Ready, needs SSH key setup |
| NIMO_CLAUDE_CODE_INSTRUCTIONS.md | Full Windows-adapted setup guide for NIMO's Claude Code | Updated for Windows |

## OpenClaw Config (openclaw.json in WSL)

**Location**: /home/rollan/.openclaw/openclaw.json

**Providers added:**
- vizor_personal: baseUrl http://100.70.114.34:8801/v1 (input: text, image)
- vizor_swarm: baseUrl http://100.70.114.34:8802/v1 (input: text, image)
- ict_expert: baseUrl http://100.70.114.34:8803/v1 (input: text, image)

**Agents added:**
- vizor: primary model vizor_personal/vizor-personal, fallbacks vizor_swarm, lmstudio/qwen3.5-35b-a3b
- ict: primary model ict_expert/ict-expert-v1, fallbacks lmstudio/qwen3.5-35b-a3b, lmstudio/qwen3.5-122b-a10b

**Discord bindings:**
- vizor bound to channel 1484324994552172544
- ict bound to channel 1484325009391489064
- Both channel IDs added to guild channels allowlist

## Quant Lanes Integration (v3.5.1)

Vizor and ICT are defined as support services within the Quant Lanes framework:

- **Vizor** outputs `visual_analysis_packet` with: instrument, timeframe, structure, key levels, patterns, bias, setup quality, confluence score, model agreement
- **ICT** outputs `ict_validation_packet` with: concept, validation status, confidence, ICT source, explanation, related concepts, chart reference, caveats
- Both respond to the Adaptive Runtime Governor's intensity scaling
- Full integration details in each agent's SOUL.md

## Pending / TODO

1. NIMO setup — Claude Code on NIMO needs to run the Windows-adapted instructions
2. Run targeted Discord scraper for remaining ~80 channels
3. PNL screenshot filter/classifier for Vizor swarm training data
4. ICT training filter threshold tuning (target ~30-40% keep rate, currently ~86%)
5. ICT video frame extraction pipeline (for multimodal training)
6. Vizor screenshot collector deployment (standalone Discord bot process)
7. SSH key setup between workstation and NIMO for training sync
8. Fine-tuning pipeline setup on NIMO (Unsloth + ShareGPT format)
9. Regenerate Discord bot token (exposed in prior session)
