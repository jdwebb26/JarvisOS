#!/usr/bin/env python3
"""Tests for Kitt/NVIDIA routing.

Proves:
- Kitt agent policy resolves preferred_provider=nvidia, preferred_model=kimi
- route_task_intent for agent_id=kitt selects kimi/nvidia_executor (not qwen)
- When NVIDIA_LANE_DOWN degradation is active, kimi candidate is blocked
  and routing falls back to Qwen3.5-35B (allowed_fallbacks in policy)
- Validate passes (no agent:kitt policy failure)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _seed_routing_policy(tmp_path: Path) -> None:
    """Copy live routing policy config into tmp_path so kitt agent policy is available."""
    import shutil
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    shutil.copy2(ROOT / "config" / "runtime_routing_policy.json", config_dir / "runtime_routing_policy.json")


def test_kitt_routing_resolves_to_kimi_nvidia(tmp_path: Path) -> None:
    from runtime.core.routing import route_task_intent, ensure_default_routing_contracts

    _seed_routing_policy(tmp_path)
    ensure_default_routing_contracts(tmp_path)
    result = route_task_intent(
        task_id="task_kitt_routing_001",
        normalized_request="research the latest NQ futures volatility patterns",
        task_type="research",
        risk_level="normal",
        priority="normal",
        actor="kitt",
        lane="kitt",
        agent_id="kitt",
        channel=None,
        workload_type="research",
        root=tmp_path,
    )
    decision = result["decision"]
    assert decision["selected_provider_id"] == "nvidia", \
        f"Kitt should route to nvidia, got: {decision['selected_provider_id']}"
    assert decision["selected_model_name"] == "moonshotai/kimi-k2.5", \
        f"Kitt should route to kimi-k2.5, got: {decision['selected_model_name']}"
    assert decision["selected_execution_backend"] == "nvidia_executor", \
        f"Kitt should use nvidia_executor, got: {decision['selected_execution_backend']}"
    print(f"  ✓ Kitt routes to {decision['selected_model_name']} via {decision['selected_provider_id']}")


def test_kitt_routing_falls_back_to_qwen_when_nvidia_lane_down(tmp_path: Path) -> None:
    """When NVIDIA_LANE_DOWN degradation is active, kitt should fall back to Qwen3.5-35B."""
    from runtime.core.routing import route_task_intent, ensure_default_routing_contracts
    from runtime.core.degradation_policy import record_degradation_event

    _seed_routing_policy(tmp_path)
    ensure_default_routing_contracts(tmp_path)

    # Activate NVIDIA_LANE_DOWN
    record_degradation_event(
        subsystem="nvidia_lane",
        failure_category="provider_unreachable",
        reason="NVIDIA API unreachable during preflight",
        actor="preflight",
        lane="system",
        root=tmp_path,
    )

    result = route_task_intent(
        task_id="task_kitt_routing_002",
        normalized_request="research the latest NQ futures volatility patterns",
        task_type="research",
        risk_level="normal",
        priority="normal",
        actor="kitt",
        lane="kitt",
        agent_id="kitt",
        channel=None,
        workload_type="research",
        root=tmp_path,
    )
    decision = result["decision"]
    # Should fall back to qwen (allowed_fallbacks includes Qwen3.5-35B)
    assert decision["selected_provider_id"] == "qwen", \
        f"With NVIDIA_LANE_DOWN, kitt should fallback to qwen, got: {decision['selected_provider_id']}"
    assert "Qwen3.5" in decision["selected_model_name"], \
        f"With NVIDIA_LANE_DOWN, kitt should fallback to Qwen3.5, got: {decision['selected_model_name']}"
    print(f"  ✓ Kitt falls back to {decision['selected_model_name']} when NVIDIA_LANE_DOWN active")


def test_kitt_policy_candidate_pool(tmp_path: Path) -> None:
    """Verify candidate pool for kitt has kimi preferred and qwen fallback."""
    from runtime.core.routing import (
        ensure_default_routing_contracts,
        legal_candidate_pool_for_runtime_policy_block,
        resolve_runtime_route_policy,
    )

    _seed_routing_policy(tmp_path)
    ensure_default_routing_contracts(tmp_path)
    resolved = resolve_runtime_route_policy(
        agent_id="kitt",
        channel=None,
        workload_type="general",
        root=tmp_path,
    )
    assert resolved["preferred_provider"] == "nvidia"
    assert resolved["preferred_model"] == "moonshotai/kimi-k2.5"
    assert "kimi" in resolved.get("allowed_families", [])
    assert "qwen3.5" in resolved.get("allowed_families", [])

    pool = legal_candidate_pool_for_runtime_policy_block(
        runtime_route_policy=resolved,
        allowed_families=resolved["allowed_families"],
        root=tmp_path,
    )
    assert pool["preferred_provider_entries"], \
        f"Expected nvidia candidate in pool, got: {pool['legal_provider_ids']}"
    assert "nvidia" in pool["legal_provider_ids"]
    assert "qwen" in pool["legal_provider_ids"], "Fallback qwen candidates should be present"
    print(f"  ✓ Kitt pool: {pool['legal_provider_ids']} providers, "
          f"preferred={[r.model_name for r in pool['preferred_provider_entries']]}, "
          f"fallback={[r.model_name for r in pool['fallback_entries']]}")


def test_kitt_quant_highstakes_routes_to_kimi(tmp_path: Path) -> None:
    """Quant tasks with high_stakes risk for Kitt must NOT exclude kimi."""
    from runtime.core.routing import route_task_intent, ensure_default_routing_contracts

    _seed_routing_policy(tmp_path)
    ensure_default_routing_contracts(tmp_path)
    result = route_task_intent(
        task_id="task_kitt_quant_001",
        normalized_request="Summarize the current NQ futures regime based on recent volatility patterns",
        task_type="quant",
        risk_level="high_stakes",
        priority="normal",
        actor="kitt",
        lane="kitt",
        agent_id="kitt",
        channel=None,
        workload_type="quant",
        root=tmp_path,
    )
    decision = result["decision"]
    assert decision["selected_provider_id"] == "nvidia", \
        f"Kitt quant/high_stakes should route to nvidia, got: {decision['selected_provider_id']}"
    assert decision["selected_model_name"] == "moonshotai/kimi-k2.5", \
        f"Kitt quant/high_stakes should route to kimi, got: {decision['selected_model_name']}"
    assert decision["selected_execution_backend"] == "nvidia_executor"
    print(f"  ✓ Kitt quant/high_stakes routes to {decision['selected_model_name']}")


def test_kitt_preferred_provider_wins_over_latency_heuristic(tmp_path: Path) -> None:
    """Kitt's preferred_provider=nvidia must outrank latency/context heuristics."""
    from runtime.core.routing import route_task_intent, ensure_default_routing_contracts

    _seed_routing_policy(tmp_path)
    ensure_default_routing_contracts(tmp_path)
    result = route_task_intent(
        task_id="task_kitt_scoring_001",
        normalized_request="brief analysis of market structure",
        task_type="general",
        risk_level="normal",
        priority="normal",
        actor="kitt",
        lane="kitt",
        agent_id="kitt",
        channel=None,
        workload_type="general",
        root=tmp_path,
    )
    decision = result["decision"]
    # Before fix, Qwen3.5-9B won on latency_fit despite kimi being preferred.
    # After fix, preferred_model/provider outranks latency_fit.
    assert decision["selected_provider_id"] == "nvidia", \
        f"Kitt preferred_provider=nvidia should win, got: {decision['selected_provider_id']}"
    assert decision["selected_model_name"] == "moonshotai/kimi-k2.5", \
        f"Kitt preferred_model should win over latency heuristic, got: {decision['selected_model_name']}"
    print(f"  ✓ Kitt preferred provider wins: {decision['selected_model_name']}")


def test_validate_passes_no_kitt_failure() -> None:
    """Validate.py should report 0 failures (Kitt policy failure is resolved)."""
    import subprocess
    result = subprocess.run(
        ["python3", "scripts/validate.py"],
        capture_output=True, text=True,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, \
        f"validate.py should pass, got:\n{result.stdout}\n{result.stderr}"
    assert "PASS" in result.stdout
    assert "agent:kitt" not in result.stdout, \
        f"No kitt failure expected in validate output, got: {result.stdout}"
    print(f"  ✓ validate passes: {result.stdout.strip()}")


if __name__ == "__main__":
    import tempfile
    import shutil

    tests_with_tmp = [
        test_kitt_routing_resolves_to_kimi_nvidia,
        test_kitt_routing_falls_back_to_qwen_when_nvidia_lane_down,
        test_kitt_policy_candidate_pool,
        test_kitt_quant_highstakes_routes_to_kimi,
        test_kitt_preferred_provider_wins_over_latency_heuristic,
    ]
    tests_no_tmp = [test_validate_passes_no_kitt_failure]
    failures = 0

    for test_fn in tests_with_tmp:
        tmp = Path(tempfile.mkdtemp(prefix="openclaw_kitt_test_"))
        try:
            test_fn(tmp)
            print(f"PASS {test_fn.__name__}")
        except Exception as exc:
            print(f"FAIL {test_fn.__name__}: {exc}")
            import traceback; traceback.print_exc()
            failures += 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    for test_fn in tests_no_tmp:
        try:
            test_fn()
            print(f"PASS {test_fn.__name__}")
        except Exception as exc:
            print(f"FAIL {test_fn.__name__}: {exc}")
            import traceback; traceback.print_exc()
            failures += 1

    total = len(tests_with_tmp) + len(tests_no_tmp)
    print(f"\n{total - failures}/{total} passed")
    raise SystemExit(0 if failures == 0 else 1)
