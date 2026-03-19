# Rejection Intelligence Runtime Consumption Plan — 2026-03-19

## Current State

Rejection intelligence v1 is fully implemented as a library:
- `runtime/quant/rejection_types.py` — Canonical data models
- `runtime/quant/rejection_normalizer.py` — Deterministic rule-based normalizer (Factory, Sigma, Executor sources)
- `runtime/quant/rejection_ledger.py` — Durable append-only ledger at `state/quant/rejections/`
- `runtime/quant/rejection_scoreboard.py` — Family, regime, and learning scoreboards
- `runtime/quant/rejection_feedback.py` — Structured feedback exports for Atlas, Fish, Kitt

**Only active consumer**: Governor reads `rejection_feedback.json` → `atlas.cooldown_families` to gate Atlas intensity.

**All other outputs are unused by runtime.**

---

## Gap Analysis

| Artifact | Producer | Consumer | Gap |
|----------|----------|----------|-----|
| `rejection_feedback.json` → `atlas.cooldown_families` | `rejection_ingest.py` | Governor | Partial — manual ingest only |
| `rejection_feedback.json` → `fish.regimes` | `rejection_ingest.py` | None | **UNUSED** |
| `rejection_feedback.json` → `kitt.brief_data` | `rejection_ingest.py` | None | **UNUSED** |
| `family_scoreboard.json` | `build_rejection_scoreboard.py` | None | **UNUSED** |
| `regime_scoreboard.json` | `build_rejection_scoreboard.py` | None | **UNUSED** |
| `learning_summary.json` | `build_rejection_scoreboard.py` | None | **UNUSED** |
| Ingest automation | N/A | N/A | **NO CRON/HOOK** |

---

## Consumption Steps (Ordered by Safety)

### Step 1: Automated Ingest via Quant Handshake

**What**: Hook `rejection_ingest.run_full()` into the existing quant handshake path trigger.

**Where**: `workspace/quant_infra/handshake.py` — already fires when Kitt/Salmon/Sigma emit packets.

**Implementation**:
```python
# In handshake.py, after existing processing
from workspace.quant_infra.rejection_ingest import run_full as ingest_rejections

def on_handshake_complete(root):
    # Existing handshake logic...
    # Then ingest any new rejections
    result = ingest_rejections(root)
    if result.get("new_records"):
        print(f"[handshake] Ingested {result['new_records']} new rejection(s)")
```

**Why safe**:
- Append-only ledger — cannot corrupt existing data
- Idempotent — duplicate rejection_ids skipped
- Bounded scope — only reads Sigma/Executor packet dirs that already exist
- Governor already expects the feedback file to exist

**Risk**: Near-zero. Worst case: ingest fails silently, governor continues using stale feedback.

---

### Step 2: Feed Scoreboards into Kitt Brief

**What**: Read `family_scoreboard.json` and `learning_summary.json` in Kitt's `_write_cycle_brief()`.

**Where**: `workspace/quant_infra/kitt/run_kitt_cycle.py` — the brief already has a SYSTEM HEALTH section.

**Implementation**: Add a REJECTION INTELLIGENCE section to the brief:
```python
def _get_rejection_summary() -> dict:
    """Read rejection scoreboards for brief enrichment."""
    scoreboard_dir = REPO_ROOT / "state" / "quant" / "rejections"
    result = {"top_reasons": [], "cooldown_families": [], "near_misses": [], "exploration_shifts": []}

    learning_path = scoreboard_dir / "learning_summary.json"
    if learning_path.exists():
        data = json.loads(learning_path.read_text())
        result["top_reasons"] = data.get("top_reasons", [])[:3]
        result["near_misses"] = data.get("near_misses", [])[:3]
        result["exploration_shifts"] = data.get("exploration_shifts", [])[:3]

    family_path = scoreboard_dir / "family_scoreboard.json"
    if family_path.exists():
        data = json.loads(family_path.read_text())
        result["cooldown_families"] = [f for f in data.get("families", {})
                                        if data["families"][f].get("cooldown")]
    return result
```

**Why safe**: Read-only. Brief content changes only; no runtime behavior change.

---

### Step 3: Fish Regime Guidance

**What**: Fish reads `rejection_feedback.json` → `fish.regimes` to bias scenario generation toward regimes with high rejection rates.

**Where**: `workspace/quant_infra/salmon/adapter.py` — Salmon (Fish backend) generates scenarios.

**Implementation**:
```python
def _load_regime_guidance() -> dict:
    """Read rejection regime feedback for scenario prioritization."""
    path = ROOT / "workspace" / "quant" / "shared" / "latest" / "rejection_feedback.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return data.get("fish", {}).get("regimes", {})
```

Scenario generation can then weight regime scenarios proportionally to rejection frequency.

**Why safe**: Scenarios are already generated; this biases which scenarios are prioritized. No execution impact.

---

### Step 4: Scoreboard Auto-Rebuild

**What**: Rebuild scoreboards after each ingest cycle (piggyback on Step 1).

**Where**: Extend the handshake hook from Step 1.

**Implementation**:
```python
from runtime.quant.rejection_ledger import RejectionLedger
from runtime.quant.rejection_scoreboard import write_scoreboards

def on_handshake_complete(root):
    result = ingest_rejections(root)
    if result.get("new_records"):
        ledger = RejectionLedger(root=root)
        write_scoreboards(ledger, output_dir=root / "state" / "quant" / "rejections")
```

**Why safe**: Write-only to scoreboard JSONs in state dir. No runtime consumers until Step 2 is landed.

---

### Step 5: Atlas Proposal Biasing

**What**: Atlas reads family-level rejection guidance to avoid over-exploring failed families.

**Where**: `workspace/quant_infra/atlas/proposal_generator.py` (just landed).

**Implementation**: Before generating proposals, check cooldown list:
```python
def generate_proposal(submit_top=False):
    # Load rejection guidance
    feedback = _load_rejection_feedback()
    cooldown_families = feedback.get("atlas", {}).get("cooldown_families", [])

    # Filter/deprioritize candidates from cooled-down families
    # ...existing proposal logic with family bias...
```

**Why safe**: Only affects experiment proposal ranking; does not affect validation, execution, or live trading.

---

## Implementation Order

| Step | What | Files Changed | Risk | Prereqs |
|------|------|---------------|------|---------|
| 1 | Automated ingest in handshake | `handshake.py` | Near-zero | None |
| 2 | Scoreboards in Kitt brief | `run_kitt_cycle.py` | Near-zero | Step 1 |
| 3 | Fish regime guidance | `salmon/adapter.py` | Low | Step 1 |
| 4 | Scoreboard auto-rebuild | `handshake.py` | Near-zero | Step 1 |
| 5 | Atlas proposal biasing | `proposal_generator.py` | Low | Steps 1, 4 |

Steps 1+4 can be done together. Steps 2 and 3 are independent of each other.

---

## What NOT To Do

- Do not make rejection intelligence block any lane cycle
- Do not make scoreboards a gate for strategy promotion
- Do not add new rejection sources until existing sources are reliably ingested
- Do not redesign the ledger format (it's working and tested)
- Do not merge rejection consumption with the Atlas↔Sigma feedback loop (they serve different purposes)
