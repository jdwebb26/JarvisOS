# TOOLS.md — Vizor

Vizor is a vision-first analytical agent. Reads images, returns structured analysis.

## Vision Endpoints (on NIMO via Tailscale)

- **EyeNet-Personal**: http://100.70.114.34:8801/v1 (operator's trained model — sacred data only)
- **EyeNet-Swarm**: http://100.70.114.34:8802/v1 (research-trained model — broad intelligence)
- Both serve OpenAI-compatible /v1/chat/completions with image_url support
- Base model: Qwen3-VL-8B-Instruct (Q8_0 quantization)
- NIMO is Windows 11, 64GB RAM, AMD Radeon 8060S (Strix Halo iGPU)
- Servers run via NSSM Windows services, auto-start on reboot
- Model files: C:\models\vizor-personal\active\ and C:\models\vizor-swarm\active\ on NIMO
- Junction points (mklink /J) allow hot-swapping between base and fine-tuned model versions

## Tool Posture

- **read**: inspect chart images, screenshots, visual data
- **vision**: call NIMO vision endpoints for image analysis
- **memory_search**: retrieve prior chart analyses and patterns
- **message**: report analysis back to requesting channel

## What Vizor Does

- Analyze trading charts (any platform: TradingView, Sierra Chart, NinjaTrader, etc.)
- Identify ICT/SMC patterns visually (FVG, OB, breaker, BOS, CHoCH, displacement, liquidity)
- OCR/read screenshots, dashboards, terminal output
- Compare analyses between personal and swarm models (dual-model conviction)
- Rate setup quality (A+ through C)
- Output structured visual_analysis_packet format

## What Vizor Does Not Do

- No trade execution or order placement
- No file writes to personal training data (quarantine system only — operator approves via emoji)
- No autonomous model retraining
- No direct market data pulls (that is Kitt's job)

## Training Data Pipeline

Training data flows: Workstation → NIMO via scp over Tailscale

**Personal model training data:**
- Source: Operator-approved screenshots from Discord #vizor channel
- Collector script: C:\Users\jdweb\Documents\vizor_screenshot_collector.py (on workstation)
- Quarantine: D:\vizor_training\quarantine\ (on workstation)
- Approved: D:\vizor_training\personal\ (on workstation)
- Training JSONL: D:\vizor_training\personal\training_personal.jsonl (on workstation)
- Synced to: C:\training_data\vizor-personal\ (on NIMO)
- Approval flow: image posted to #vizor → bot quarantines → adds emoji reactions → operator clicks checkmark or X

**Swarm model training data:**
- Source: Discord Backtesters Anon server screenshots (10,437+ images collected)
- Scraped by: discord_targeted_scraper.py targeting ~80 high-value channels
- Raw images: D:\discord_screenshots\ (on workstation, organized by channel name)
- Per-image metadata: JSON sidecar files with author, timestamp, channel, message content
- Training JSONL: D:\discord_screenshots\training_dataset.jsonl (on workstation)
- Synced to: C:\training_data\vizor-swarm\ (on NIMO)
- NOTE: PNL screenshots need to be filtered out (identified as useless noise)

**Sync script:** C:\Users\jdweb\Documents\nimo_training_sync.py
- One-shot: `python nimo_training_sync.py`
- Watch mode: `python nimo_training_sync.py --watch` (checks every 2 min)
- Uses scp over Tailscale (NIMO IP: 100.70.114.34)
