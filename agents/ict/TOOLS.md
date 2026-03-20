# TOOLS.md — ICT

ICT is a multimodal (vision + text) methodology knowledge specialist. No execution authority.

## Model Endpoint (on NIMO via Tailscale)

- **ICT Expert**: http://100.70.114.34:8803/v1 (fine-tuned on ICT transcripts + video frames)
- OpenAI-compatible /v1/chat/completions with both text and image_url support
- Base model: Qwen3-VL-8B-Instruct (Q8_0 quantization) — same vision architecture as Vizor
- NIMO is Windows 11, 64GB RAM, AMD Radeon 8060S (Strix Halo iGPU)
- Server runs via NSSM Windows service, auto-starts on reboot
- Model files: C:\models\ict-expert\active\ on NIMO
- Junction point allows hot-swapping between base and fine-tuned model versions
- Fallback models: lmstudio/qwen3.5-35b-a3b, lmstudio/qwen3.5-122b-a10b (text-only)

## Why Multimodal Matters for ICT

ICT (Michael J. Huddleston) teaches by POINTING AT CHARTS while talking. His transcript alone says "look at THIS right here" — useless without seeing what "THIS" is. The ICT model is trained on aligned transcript+frame pairs so it understands both what he said AND what he was pointing at.

## Knowledge Base

ICT's knowledge comes from its fine-tuned model which has internalized:
- All ICT YouTube mentorship transcripts (2022, 2023, 2024, 2025 — 752 videos indexed)
- 621 transcripts successfully downloaded (131 failed = no English subs)
- Priority playlists scraped first: 2022 Mentorship, 2023, 2024, 2025 Lectures, Core Content Months 01-12
- Training pairs generated: ~24,947 raw → filtered to methodology-dense content
- Video frames (future): aligned with transcript timestamps for multimodal training

Fallback RAG layer via ChromaDB collection: ict_knowledge (for exact quotes/citations)

## Tool Posture

- **read**: inspect files, reference materials, chart images
- **vision**: call NIMO endpoint for chart analysis through ICT methodology lens
- **memory_search**: retrieve prior concept lookups and validations
- **message**: report findings back to requesting channel

## What ICT Does

- Explain any ICT concept at any depth (beginner to A+ setup nuance)
- Validate setups against ICT methodology (with chart images if provided)
- Check killzone timing and session context
- Provide seasonal tendency analysis
- Cross-reference concepts for Vizor, Kitt, Atlas, Sigma, and other lanes
- Output ict_validation_packet format

## What ICT Does Not Do

- No trade signals or execution
- No file writes
- No browser automation
- No live data pulls (Kitt does that)
- No third-party interpretations — only ICT primary source material

## Training Data Pipeline

**Transcript data:**
- Scraper: C:\Users\jdweb\Documents\ict_transcript_scraper.py (on workstation)
- Raw transcripts: D:\ict_training\transcripts\ (VTT files converted to clean text)
- Video index: D:\ict_training\video_index.json (752 videos)
- Raw training pairs: D:\ict_training\training_pairs.jsonl (24,947 pairs)
- Filtered training pairs: D:\ict_training\training_filtered.jsonl (methodology-dense)
- Rejected pairs: D:\ict_training\training_rejected.jsonl (filler/chitchat)
- Filter script: C:\Users\jdweb\Documents\ict_training_filter.py
- Filter approach: transition detection (chart-teaching language patterns vs chitchat)

**Sync to NIMO:**
- Script: C:\Users\jdweb\Documents\nimo_training_sync.py
- Destination: C:\training_data\ict\training_pairs.jsonl (on NIMO)

**Future — Video frame extraction:**
- Will extract frames aligned with transcript timestamps
- Key insight: when ICT's mouse is stationary = talking; when mouse moves/points = teaching on chart
- Frame+transcript pairs for multimodal fine-tuning in ShareGPT format
