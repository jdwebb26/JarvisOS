# Feature Prompts — Large Feature Request Intake

Capture large feature ideas here before they become tasks.
Each entry is a prompt, not a commitment. Promote to CURRENT_TRUTH.md backlog when scoped and prioritized.

> See also: [CURRENT_TRUTH.md](CURRENT_TRUTH.md) (status/backlog), [SPEC_VERIFICATION_MATRIX.md](SPEC_VERIFICATION_MATRIX.md) (spec verification)

---

## Format

```
### <short name>
- **What**: one-line description
- **Why**: user impact
- **Scope**: small / medium / large
- **Blocked by**: dependencies if any
```

---

## Intake Queue

### Hermes deep research pipeline
- **What**: Activate external Hermes daemon for multi-step web research campaigns
- **Why**: Unblocks autonomous research hypothesis generation
- **Scope**: medium (adapter exists, needs external service + activation)
- **Blocked by**: External Hermes runtime not started

### Strategy factory operator walkthrough
- **What**: End-to-end guided run: IDEA → candidate → backtest → promotion gate review
- **Why**: Proves the core mission pipeline with operator in the loop
- **Scope**: medium (pipeline code exists, needs operator-guided first run)
- **Blocked by**: Nothing — ready to attempt

### Ralph cron integration
- **What**: Wire Ralph v1 loop to systemd timer for scheduled memory compaction and queue draining
- **Why**: Automated housekeeping without operator intervention
- **Scope**: small (loop proven, just needs cron entry + service file)
- **Blocked by**: Nothing

### Cadence mic passthrough (WSL2)
- **What**: Get microphone input working through WSL2 for voice interaction
- **Why**: Unblocks full voice stack (ingress → TTS → call)
- **Scope**: medium (investigate PulseAudio/pipewire WSL passthrough)
- **Blocked by**: WSL2 RDPSource limitation

### Session size monitoring
- **What**: Dashboard or alert for session file sizes, turn counts, stale sessions
- **Why**: Prevent context overflow incidents like the 83KB Jarvis session
- **Scope**: small

### Multi-node burst routing
- **What**: Activate NIMO/Koolkidclub nodes for elastic task execution
- **Why**: Scale beyond single-node for batch factory runs
- **Scope**: large (scaffold exists, needs node registration + heartbeat wiring)
- **Blocked by**: NIMO/Koolkidclub hardware setup
