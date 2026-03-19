#!/usr/bin/env python3
"""Tests for Lane B intelligence lanes.

Tests Atlas, Fish, Hermes, TradeFloor using frozen packet contracts.
Includes scheduler/host enforcement, governor, cadence, and missing packet tests.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from workspace.quant.shared.schemas.packets import make_packet, validate_packet, QuantPacket
from workspace.quant.shared.packet_store import store_packet, get_latest, get_all_latest
from workspace.quant.shared.registries.strategy_registry import (
    create_strategy, transition_strategy, load_all_strategies,
)


@pytest.fixture
def clean_root(tmp_path):
    """Provide a clean root directory for each test."""
    (tmp_path / "workspace" / "quant" / "shared" / "latest").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "registries").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "config").mkdir(parents=True)
    (tmp_path / "workspace" / "quant" / "shared" / "scheduler").mkdir(parents=True)
    for lane in ["atlas", "fish", "hermes", "sigma", "kitt", "tradefloor", "executor"]:
        (tmp_path / "workspace" / "quant" / lane).mkdir(parents=True)

    # Seed hosts.json
    hosts = {
        "hosts": {
            "NIMO": {"role": "primary", "specs": "128GB", "heavy_job_cap": 2, "ip": "127.0.0.1"},
            "SonLM": {"role": "secondary", "specs": "lighter", "heavy_job_cap": 1, "ip": None},
        },
        "global_heavy_job_cap": 3,
        "lane_placement": {
            "atlas": {"primary": "NIMO", "overflow": "SonLM"},
            "fish": {"primary": "SonLM", "overflow": "cloud"},
            "hermes": {"primary": "mixed", "overflow": "either"},
            "tradefloor": {"primary": "strongest_available", "overflow": "cloud"},
            "kitt": {"primary": "NIMO", "overflow": "cloud"},
            "sigma": {"primary": "NIMO", "overflow": "cloud"},
            "executor": {"primary": "NIMO", "overflow": None},
        },
    }
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "hosts.json").write_text(
        json.dumps(hosts, indent=2), encoding="utf-8"
    )

    # Seed governor_state.json
    gov = {lane: {
        "batch_size": 1, "max_iterations": 5, "cooldown_interval": 0,
        "cloud_burst_allowed": False, "escalation_threshold": 0.6,
        "cadence_multiplier": 1.0, "consecutive_backoff_cycles": 0, "paused": False,
    } for lane in ["atlas", "fish", "hermes", "tradefloor", "kitt", "sigma", "executor"]}
    (tmp_path / "workspace" / "quant" / "shared" / "config" / "governor_state.json").write_text(
        json.dumps(gov, indent=2), encoding="utf-8"
    )

    return tmp_path


# ---- Scheduler Tests ----

class TestScheduler:
    def test_resolve_host_primary(self, clean_root):
        from workspace.quant.shared.scheduler.scheduler import resolve_host
        assert resolve_host(clean_root, "atlas") == "NIMO"
        assert resolve_host(clean_root, "fish") == "SonLM"

    def test_check_capacity_empty(self, clean_root):
        from workspace.quant.shared.scheduler.scheduler import check_capacity
        can, host, reason = check_capacity(clean_root, "atlas")
        assert can is True
        assert "capacity_available" in reason

    def test_register_and_deregister(self, clean_root):
        from workspace.quant.shared.scheduler.scheduler import (
            register_heavy_job, deregister_heavy_job, get_active_jobs,
        )
        jid = register_heavy_job(clean_root, "atlas", "NIMO")
        jobs = get_active_jobs(clean_root)
        assert len(jobs) == 1
        assert jobs[0]["lane"] == "atlas"
        deregister_heavy_job(clean_root, jid)
        assert len(get_active_jobs(clean_root)) == 0

    def test_host_cap_enforcement(self, clean_root):
        from workspace.quant.shared.scheduler.scheduler import (
            register_heavy_job, check_capacity,
        )
        register_heavy_job(clean_root, "fish", "SonLM")
        can, _, reason = check_capacity(clean_root, "fish", "SonLM")
        assert can is False
        assert "host_cap_hit" in reason

    def test_global_cap_enforcement(self, clean_root):
        from workspace.quant.shared.scheduler.scheduler import (
            register_heavy_job, check_capacity,
        )
        register_heavy_job(clean_root, "atlas", "NIMO")
        register_heavy_job(clean_root, "fish", "SonLM")
        register_heavy_job(clean_root, "sigma", "NIMO")
        can, _, reason = check_capacity(clean_root, "hermes")
        assert can is False
        assert "global_cap_hit" in reason

    def test_heavy_job_slot_context_manager(self, clean_root):
        from workspace.quant.shared.scheduler.scheduler import heavy_job_slot, get_active_jobs
        with heavy_job_slot(clean_root, "atlas") as slot:
            assert slot.acquired is True
            assert slot.host == "NIMO"
            assert len(get_active_jobs(clean_root)) == 1
        assert len(get_active_jobs(clean_root)) == 0

    def test_heavy_job_slot_blocked(self, clean_root):
        from workspace.quant.shared.scheduler.scheduler import (
            register_heavy_job, heavy_job_slot,
        )
        register_heavy_job(clean_root, "a", "NIMO")
        register_heavy_job(clean_root, "b", "SonLM")
        register_heavy_job(clean_root, "c", "NIMO")
        with heavy_job_slot(clean_root, "atlas") as slot:
            assert slot.acquired is False
            assert slot.waited is True

    def test_overflow_to_secondary(self, clean_root):
        from workspace.quant.shared.scheduler.scheduler import (
            register_heavy_job, resolve_host,
        )
        register_heavy_job(clean_root, "a", "NIMO")
        register_heavy_job(clean_root, "b", "NIMO")
        host = resolve_host(clean_root, "atlas")
        assert host == "SonLM"


# ---- Governor Tests ----

class TestGovernor:
    def test_push_when_healthy(self, clean_root):
        from workspace.quant.shared.governor import evaluate_cycle, get_lane_params
        action, reason = evaluate_cycle(
            clean_root, "atlas",
            usefulness_score=0.7, efficiency_score=0.6,
            health_score=0.9, confidence_score=0.7,
        )
        assert action == "push"
        params = get_lane_params(clean_root, "atlas")
        assert params["batch_size"] == 2

    def test_backoff_when_useless(self, clean_root):
        from workspace.quant.shared.governor import evaluate_cycle
        action, _ = evaluate_cycle(
            clean_root, "atlas",
            usefulness_score=0.1, efficiency_score=0.5,
            health_score=0.8, confidence_score=0.5,
        )
        assert action == "backoff"

    def test_hold_when_moderate(self, clean_root):
        from workspace.quant.shared.governor import evaluate_cycle
        action, _ = evaluate_cycle(
            clean_root, "atlas",
            usefulness_score=0.4, efficiency_score=0.3,
            health_score=0.6, confidence_score=0.5,
        )
        assert action == "hold"

    def test_pause_when_critical(self, clean_root):
        from workspace.quant.shared.governor import evaluate_cycle, get_lane_params
        action, _ = evaluate_cycle(
            clean_root, "fish",
            usefulness_score=0.1, efficiency_score=0.1,
            health_score=0.1, confidence_score=0.1,
        )
        assert action == "pause"
        assert get_lane_params(clean_root, "fish")["paused"] is True

    def test_consecutive_backoffs_pause(self, clean_root):
        from workspace.quant.shared.governor import evaluate_cycle, get_lane_params
        for _ in range(3):
            evaluate_cycle(clean_root, "hermes",
                           usefulness_score=0.1, efficiency_score=0.5,
                           health_score=0.5, confidence_score=0.5)
        assert get_lane_params(clean_root, "hermes")["paused"] is True


# ---- Atlas Tests ----

class TestAtlas:
    def test_generate_candidate_creates_registry_entry(self, clean_root):
        from workspace.quant.atlas.exploration_lane import generate_candidate
        pkt, feedback = generate_candidate(clean_root, "atlas-test-001", "Test thesis")
        assert validate_packet(pkt) == []
        assert pkt.strategy_id == "atlas-test-001"
        strats = load_all_strategies(clean_root)
        assert "atlas-test-001" in strats
        assert strats["atlas-test-001"].lifecycle_state == "CANDIDATE"

    def test_generate_candidate_rejects_duplicate(self, clean_root):
        from workspace.quant.atlas.exploration_lane import generate_candidate
        generate_candidate(clean_root, "atlas-dup-001", "First")
        with pytest.raises(ValueError, match="already exists"):
            generate_candidate(clean_root, "atlas-dup-001", "Second")

    def test_ingest_rejections_empty(self, clean_root):
        from workspace.quant.atlas.exploration_lane import ingest_rejections
        feedback = ingest_rejections(clean_root)
        assert feedback["rejection_count"] == 0
        assert feedback["adapted"] is False

    def test_atlas_adapts_from_rejection(self, clean_root):
        """Core proof: Atlas consumes rejection and changes output."""
        from workspace.quant.atlas.exploration_lane import generate_candidate, ingest_rejections

        pkt1, fb1 = generate_candidate(clean_root, "atlas-a-001", "Simple gap fade")
        assert fb1["adapted"] is False

        transition_strategy(clean_root, "atlas-a-001", "VALIDATING", actor="sigma")
        rej = make_packet(
            "strategy_rejection_packet", "sigma", "Rejected: poor OOS",
            strategy_id="atlas-a-001", rejection_reason="poor_oos",
            rejection_detail="PF 0.8 < 1.3",
        )
        store_packet(clean_root, rej)
        transition_strategy(clean_root, "atlas-a-001", "REJECTED", actor="sigma")

        feedback = ingest_rejections(clean_root)
        assert feedback["rejection_count"] >= 1
        assert len(feedback["avoidance_patterns"]) > 0

        pkt2, fb2 = generate_candidate(
            clean_root, "atlas-a-002", "Improved gap fade with filter",
            parent_id="atlas-a-001",
        )
        assert "adapted:" in pkt2.thesis.lower() or "avoid" in (pkt2.notes or "").lower()
        assert pkt2.confidence != 0.5

    def test_failure_learning_packet(self, clean_root):
        from workspace.quant.atlas.exploration_lane import emit_failure_learning
        rej = make_packet(
            "strategy_rejection_packet", "sigma", "Rejected",
            strategy_id="test-001", rejection_reason="curve_fit",
            rejection_detail="Overfitted",
        )
        store_packet(clean_root, rej)
        learning = emit_failure_learning(clean_root, rej, "Need out-of-sample validation")
        assert validate_packet(learning) == []
        assert learning.packet_type == "failure_learning_packet"

    def test_atlas_health_summary_with_governor(self, clean_root):
        from workspace.quant.atlas.exploration_lane import emit_health_summary
        h = emit_health_summary(clean_root, "2026-01-01T00:00:00Z", "2026-01-01T06:00:00Z", 3)
        assert validate_packet(h) == []
        assert h.packet_type == "health_summary"
        assert h.lane == "atlas"
        assert h.governor_action_taken in ("push", "hold", "backoff", "pause")

    def test_generate_candidate_batch(self, clean_root):
        from workspace.quant.atlas.exploration_lane import generate_candidate_batch
        candidates = [
            {"strategy_id": "batch-001", "thesis": "Test batch 1"},
            {"strategy_id": "batch-002", "thesis": "Test batch 2"},
        ]
        batch_pkt, generated, sched = generate_candidate_batch(clean_root, candidates)
        assert validate_packet(batch_pkt) == []
        assert batch_pkt.packet_type == "experiment_batch_packet"
        assert sched["acquired"] is True
        assert sched["generated"] >= 1

    def test_batch_blocked_by_scheduler(self, clean_root):
        from workspace.quant.atlas.exploration_lane import generate_candidate_batch
        from workspace.quant.shared.scheduler.scheduler import register_heavy_job
        register_heavy_job(clean_root, "a", "NIMO")
        register_heavy_job(clean_root, "b", "SonLM")
        register_heavy_job(clean_root, "c", "NIMO")
        batch_pkt, generated, sched = generate_candidate_batch(
            clean_root, [{"strategy_id": "blocked-001", "thesis": "Blocked"}],
        )
        assert sched["acquired"] is False
        assert sched["skipped"] == 1
        assert len(generated) == 0


# ---- Fish Tests ----

class TestFish:
    def test_emit_scenario(self, clean_root):
        from workspace.quant.fish.scenario_lane import emit_scenario
        pkt = emit_scenario(clean_root, "NQ range-bound this week", confidence=0.6)
        assert validate_packet(pkt) == []
        assert pkt.packet_type == "scenario_packet"

    def test_emit_forecast_with_direction(self, clean_root):
        from workspace.quant.fish.scenario_lane import emit_forecast
        pkt = emit_forecast(
            clean_root, "NQ bullish into FOMC",
            forecast_value=18400.0, forecast_direction="bullish", confidence=0.55,
        )
        assert validate_packet(pkt) == []
        assert "direction=bullish" in pkt.notes
        assert "target=18400" in pkt.notes

    def test_calibrate_correct_direction(self, clean_root):
        from workspace.quant.fish.scenario_lane import emit_forecast, calibrate
        forecast = emit_forecast(
            clean_root, "NQ bullish", confidence=0.6,
            forecast_value=18400.0, forecast_direction="bullish",
        )
        cal_pkt, result = calibrate(clean_root, forecast, realized_value=18350.0, realized_direction="bullish")
        assert validate_packet(cal_pkt) == []
        assert result["direction_correct"] is True
        assert result["value_error"] == 50.0
        assert result["calibration_score"] > 0
        assert result["adjusted_confidence"] != forecast.confidence

    def test_calibrate_wrong_direction_lowers_confidence(self, clean_root):
        from workspace.quant.fish.scenario_lane import emit_forecast, calibrate
        forecast = emit_forecast(
            clean_root, "NQ bearish", confidence=0.6,
            forecast_value=17800.0, forecast_direction="bearish",
        )
        cal_pkt, result = calibrate(clean_root, forecast, realized_value=18500.0, realized_direction="bullish")
        assert result["direction_correct"] is False
        assert result["adjusted_confidence"] < forecast.confidence

    def test_calibration_trend(self, clean_root):
        from workspace.quant.fish.scenario_lane import emit_forecast, calibrate
        f1 = emit_forecast(clean_root, "f1", confidence=0.5, forecast_value=18000.0, forecast_direction="bullish")
        calibrate(clean_root, f1, 18050.0, "bullish")
        f2 = emit_forecast(clean_root, "f2", confidence=0.5, forecast_value=18100.0, forecast_direction="bullish")
        _, result2 = calibrate(clean_root, f2, 18120.0, "bullish")
        assert result2["trend"] in ("improving", "degrading", "insufficient_data")
        assert result2["history_depth"] >= 2

    def test_emit_risk_map(self, clean_root):
        from workspace.quant.fish.scenario_lane import emit_risk_map
        pkt = emit_risk_map(
            clean_root, "NQ risk map: VIX spike zone active",
            risk_zones={"vix_spike": {"level": "high", "trigger": "VIX > 30"}},
            confidence=0.6,
        )
        assert validate_packet(pkt) == []
        assert pkt.packet_type == "risk_map_packet"
        assert len(pkt.artifacts) == 1

    def test_scenario_batch_scheduler_aware(self, clean_root):
        from workspace.quant.fish.scenario_lane import run_scenario_batch
        pkts, sched = run_scenario_batch(clean_root, [
            {"thesis": "Scenario 1"}, {"thesis": "Scenario 2"},
        ])
        assert sched["acquired"] is True
        assert sched["emitted"] >= 1

    def test_fish_health_with_governor(self, clean_root):
        from workspace.quant.fish.scenario_lane import emit_health_summary
        h = emit_health_summary(clean_root, "2026-01-01T00:00:00Z", "2026-01-01T08:00:00Z", 5,
                                scenarios_emitted=1, calibrations_done=2)
        assert validate_packet(h) == []
        assert h.lane == "fish"
        assert h.governor_action_taken in ("push", "hold", "backoff", "pause")


# ---- Hermes Tests ----

class TestHermes:
    def test_emit_research(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_research
        pkt = emit_research(clean_root, "NQ research", source="test-source", source_type="web")
        assert pkt is not None
        assert validate_packet(pkt) == []
        assert "source=test-source" in pkt.notes

    def test_dedup_skips_recent(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_research
        emit_research(clean_root, "First", source="same-source", source_type="web")
        dup = emit_research(clean_root, "Second", source="same-source", source_type="web")
        assert dup is None

    def test_force_overrides_dedup(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_research
        emit_research(clean_root, "First", source="force-source", source_type="web")
        forced = emit_research(clean_root, "Forced", source="force-source", source_type="web", force=True)
        assert forced is not None

    def test_confidence_adjusted_by_source_type(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_research
        official = emit_research(clean_root, "Official", source="s1", source_type="official_doc", confidence=0.8)
        social = emit_research(clean_root, "Social", source="s2", source_type="social", confidence=0.8)
        assert official.confidence > social.confidence

    def test_research_request_packet(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_research_request
        pkt = emit_research_request(clean_root, "atlas", "Research vol surfaces", symbol_scope="NQ")
        assert validate_packet(pkt) == []
        assert pkt.lane == "atlas"
        assert pkt.packet_type == "research_request_packet"

    def test_emit_dataset_packet(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_dataset
        pkt = emit_dataset(clean_root, "OHLCV dataset for NQ", "nq_ohlcv_2025",
                           source="quandl-nq-daily", source_type="api", symbol_scope="NQ")
        assert pkt is not None
        assert validate_packet(pkt) == []
        assert pkt.packet_type == "dataset_packet"
        assert "dataset=nq_ohlcv_2025" in pkt.notes

    def test_emit_repo_packet(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_repo
        pkt = emit_repo(clean_root, "Useful NQ analysis repo",
                        repo_url="https://github.com/example/nq-analysis")
        assert pkt is not None
        assert validate_packet(pkt) == []
        assert pkt.packet_type == "repo_packet"

    def test_emit_theme_packet(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_theme
        pkt = emit_theme(clean_root, "FOMC dovish pivot emerging as macro theme",
                         theme_name="fomc_dovish_pivot", confidence=0.6)
        assert validate_packet(pkt) == []
        assert pkt.packet_type == "theme_packet"
        assert "theme=fomc_dovish_pivot" in pkt.notes

    def test_research_batch_scheduler_aware(self, clean_root):
        from workspace.quant.hermes.research_lane import run_research_batch
        pkts, sched = run_research_batch(clean_root, [
            {"thesis": "Research 1", "source": "src-1"},
            {"thesis": "Research 2", "source": "src-2"},
        ])
        assert sched["acquired"] is True
        assert sched["emitted"] >= 1

    def test_hermes_health_with_governor(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_health_summary
        h = emit_health_summary(clean_root, "2026-01-01T00:00:00Z", "2026-01-01T03:00:00Z", 2)
        assert validate_packet(h) == []
        assert h.lane == "hermes"
        assert h.governor_action_taken in ("push", "hold", "backoff", "pause")


# ---- TradeFloor Tests ----

class TestTradeFloor:
    def _seed_packets(self, root):
        store_packet(root, make_packet(
            "research_packet", "hermes", "NQ bullish momentum detected", confidence=0.6))
        store_packet(root, make_packet(
            "candidate_packet", "atlas", "NQ breakout strategy shows bullish edge",
            strategy_id="atlas-tf-001", confidence=0.55))
        store_packet(root, make_packet(
            "scenario_packet", "fish", "NQ bullish scenario: FOMC dovish", confidence=0.6))
        store_packet(root, make_packet(
            "validation_packet", "sigma", "atlas-tf-001 passes validation",
            strategy_id="atlas-tf-001", confidence=0.7))
        store_packet(root, make_packet(
            "brief_packet", "kitt", "Market bullish, considering NQ setups", confidence=0.65))

    def test_synthesize_produces_valid_packet(self, clean_root):
        self._seed_packets(clean_root)
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        pkt = synthesize(clean_root)
        assert validate_packet(pkt) == []
        assert pkt.packet_type == "tradefloor_packet"
        assert pkt.lane == "tradefloor"

    def test_synthesize_has_agreement_tier(self, clean_root):
        self._seed_packets(clean_root)
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        pkt = synthesize(clean_root)
        assert pkt.agreement_tier is not None
        assert 0 <= pkt.agreement_tier <= 4
        assert pkt.agreement_tier_reasoning

    def test_synthesize_routes_to_latest(self, clean_root):
        self._seed_packets(clean_root)
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        pkt = synthesize(clean_root)
        latest = get_latest(clean_root, "tradefloor", "tradefloor_packet")
        assert latest is not None
        assert latest.packet_id == pkt.packet_id

    def test_empty_latest_gives_tier_0(self, clean_root):
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        pkt = synthesize(clean_root)
        assert pkt.agreement_tier == 0

    def test_cadence_enforcement(self, clean_root):
        self._seed_packets(clean_root)
        from workspace.quant.tradefloor.synthesis_lane import synthesize, CadenceRefused
        synthesize(clean_root)
        with pytest.raises(CadenceRefused):
            synthesize(clean_root)

    def test_cadence_override(self, clean_root):
        self._seed_packets(clean_root)
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        synthesize(clean_root)
        pkt2 = synthesize(clean_root, override_reason="urgent regime shift")
        assert pkt2.agreement_tier is not None
        assert "override" in (pkt2.notes or "")

    def test_scheduler_blocked_emits_degraded(self, clean_root):
        self._seed_packets(clean_root)
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        from workspace.quant.shared.scheduler.scheduler import register_heavy_job
        register_heavy_job(clean_root, "a", "NIMO")
        register_heavy_job(clean_root, "b", "SonLM")
        register_heavy_job(clean_root, "c", "NIMO")
        pkt = synthesize(clean_root)
        assert pkt.degraded is True
        assert pkt.agreement_tier == 0


# ---- Restart/Recovery Tests ----

class TestRestart:
    def test_stale_scheduler_cleared_on_restart(self, clean_root):
        import time
        from workspace.quant.shared.scheduler.scheduler import _save_active_jobs, _load_active_jobs
        from workspace.quant.shared.restart import clear_stale_scheduler_jobs
        _save_active_jobs(clean_root, [
            {"job_id": "old-job", "lane": "atlas", "host": "NIMO",
             "registered_at": time.time() - 7200, "priority": 6},
        ])
        cleared = clear_stale_scheduler_jobs(clean_root)
        assert cleared == 1
        assert len(_load_active_jobs(clean_root)) == 0

    def test_latest_coherence_check(self, clean_root):
        from workspace.quant.shared.restart import check_latest_coherence
        store_packet(clean_root, make_packet("research_packet", "hermes", "test"))
        coherent, issues = check_latest_coherence(clean_root)
        assert coherent is True
        assert issues == []

    def test_latest_coherence_detects_corrupt(self, clean_root):
        from workspace.quant.shared.restart import check_latest_coherence
        corrupt_path = clean_root / "workspace" / "quant" / "shared" / "latest" / "bad.json"
        corrupt_path.write_text("{invalid json", encoding="utf-8")
        coherent, issues = check_latest_coherence(clean_root)
        assert coherent is False
        assert len(issues) >= 1

    def test_tradefloor_cadence_survives_restart(self, clean_root):
        store_packet(clean_root, make_packet("research_packet", "hermes", "test", confidence=0.5))
        store_packet(clean_root, make_packet("candidate_packet", "atlas", "test",
                                             strategy_id="tf-test", confidence=0.5))
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        from workspace.quant.shared.restart import check_tradefloor_cadence_after_restart
        synthesize(clean_root)
        can_run, remaining = check_tradefloor_cadence_after_restart(clean_root)
        assert can_run is False
        assert remaining > 0

    def test_hermes_dedup_survives_restart(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_research
        from workspace.quant.shared.restart import check_dedup_state_after_restart
        emit_research(clean_root, "Test", source="test-src", source_type="web")
        state = check_dedup_state_after_restart(clean_root)
        assert state["count"] >= 1
        assert "test-src" in state["recent_sources"]

    def test_atlas_duplicate_blocked_after_restart(self, clean_root):
        from workspace.quant.atlas.exploration_lane import generate_candidate
        from workspace.quant.shared.restart import check_atlas_registry_after_restart
        generate_candidate(clean_root, "restart-001", "First")
        reg = check_atlas_registry_after_restart(clean_root)
        assert "restart-001" in reg["active_ids"]
        with pytest.raises(ValueError, match="already exists"):
            generate_candidate(clean_root, "restart-001", "Duplicate")

    def test_recover_lane_state(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_research
        from workspace.quant.shared.restart import recover_lane_state
        emit_research(clean_root, "Recovery test", source="rec-src", source_type="web")
        rec = recover_lane_state(clean_root, "hermes")
        assert rec["latest_packet"] is not None
        assert rec["lane_packet_count"] >= 1
        assert len(rec["governor_params"]) > 0

    def test_governor_state_survives_restart(self, clean_root):
        from workspace.quant.shared.governor import evaluate_cycle, get_lane_params
        evaluate_cycle(clean_root, "atlas",
                       usefulness_score=0.7, efficiency_score=0.6,
                       health_score=0.9, confidence_score=0.7)
        params = get_lane_params(clean_root, "atlas")
        assert params["batch_size"] == 2


# ---- Integration ----

class TestLaneBIntegration:
    def test_full_loop_atlas_rejection_adaptation(self, clean_root):
        from workspace.quant.hermes.research_lane import emit_research
        from workspace.quant.atlas.exploration_lane import generate_candidate
        from workspace.quant.sigma.validation_lane import validate_candidate

        research = emit_research(clean_root, "Vol surface analysis", source="vol-api", source_type="api")
        c1, _ = generate_candidate(clean_root, "int-001", "Simple mean-rev",
                                   evidence_refs=[research.packet_id])
        transition_strategy(clean_root, "int-001", "VALIDATING", actor="sigma")
        validate_candidate(clean_root, c1, profit_factor=0.7, sharpe=0.3,
                           max_drawdown_pct=0.25, trade_count=8)
        c2, fb = generate_candidate(clean_root, "int-002", "Improved mean-rev with regime filter",
                                    parent_id="int-001")
        assert fb["adapted"]
        assert fb["rejection_count"] >= 1

    def test_full_loop_fish_calibration_to_brief(self, clean_root):
        from workspace.quant.fish.scenario_lane import emit_forecast, calibrate
        from workspace.quant.tradefloor.synthesis_lane import synthesize
        from workspace.quant.kitt.brief_producer import produce_brief

        forecast = emit_forecast(clean_root, "NQ bullish", confidence=0.6,
                                 forecast_value=18400.0, forecast_direction="bullish")
        calibrate(clean_root, forecast, 18350.0, "bullish")
        store_packet(clean_root, make_packet("brief_packet", "kitt", "Market read", confidence=0.5))
        store_packet(clean_root, make_packet("candidate_packet", "atlas", "NQ candidate",
                                             strategy_id="cal-001", confidence=0.5))
        tf = synthesize(clean_root)
        assert tf.agreement_tier is not None
        brief = produce_brief(clean_root)
        assert "TRADEFLOOR" in (brief.notes or "")

    def test_scheduler_limits_concurrent_heavy_work(self, clean_root):
        from workspace.quant.shared.scheduler.scheduler import register_heavy_job
        from workspace.quant.atlas.exploration_lane import generate_candidate_batch
        from workspace.quant.fish.scenario_lane import run_scenario_batch

        register_heavy_job(clean_root, "sigma", "NIMO")
        register_heavy_job(clean_root, "kitt", "NIMO")

        _, generated, sched_a = generate_candidate_batch(
            clean_root, [{"strategy_id": "sched-001", "thesis": "Test"}],
        )
        assert sched_a["acquired"] is True
        assert sched_a["host"] == "SonLM"

        pkts, sched_f = run_scenario_batch(clean_root, [{"thesis": "Fish scenario"}])
        assert sched_f["acquired"] is True
