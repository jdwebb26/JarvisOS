#!/usr/bin/env python3
"""Quant Lanes — Cold-Start / Bootstrap Proof.

Deterministic proof that quant lanes can start from empty state and
produce real, bounded, non-junk first packets. Re-runnable.

Usage:
    python3 workspace/quant/cold_start_proof.py
    python3 scripts/quant_lanes.py cold-start-proof

Exit 0 = all checks pass. Exit 1 = failure.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _setup_isolated_root() -> Path:
    """Create a clean, isolated test root with real configs."""
    tmp = Path(tempfile.mkdtemp(prefix="coldstart_proof_"))

    # Directory structure
    (tmp / "workspace" / "quant" / "shared" / "latest").mkdir(parents=True)
    (tmp / "workspace" / "quant" / "shared" / "registries").mkdir(parents=True)
    (tmp / "workspace" / "quant" / "shared" / "config").mkdir(parents=True)
    (tmp / "workspace" / "quant" / "shared" / "scheduler").mkdir(parents=True)
    for lane in ["atlas", "fish", "hermes", "sigma", "kitt", "tradefloor", "executor"]:
        (tmp / "workspace" / "quant" / lane).mkdir(parents=True)

    # Copy real config files from the repo
    config_src = ROOT / "workspace" / "quant" / "shared" / "config"
    config_dst = tmp / "workspace" / "quant" / "shared" / "config"
    for name in ["hosts.json", "watch_list.json", "fish_bootstrap.json",
                 "atlas_sources.json", "governor_state.json",
                 "review_thresholds.json", "risk_limits.json"]:
        src = config_src / name
        if src.exists():
            shutil.copy2(src, config_dst / name)

    # Ensure governor is not paused
    gov_path = config_dst / "governor_state.json"
    if gov_path.exists():
        gov = json.loads(gov_path.read_text(encoding="utf-8"))
        for lane in gov:
            gov[lane]["paused"] = False
        gov_path.write_text(json.dumps(gov, indent=2) + "\n", encoding="utf-8")

    return tmp


class Proof:
    def __init__(self):
        self.results: list[tuple[str, bool, str]] = []
        self.root: Path | None = None

    def check(self, name: str, passed: bool, detail: str = ""):
        tag = "PASS" if passed else "FAIL"
        print(f"  {tag}  {name:50s}  {detail}")
        self.results.append((name, passed, detail))

    def run(self) -> bool:
        print("COLD-START PROOF")
        print("=" * 70)

        self.root = _setup_isolated_root()
        print(f"Isolated root: {self.root}\n")

        try:
            self._prove_empty_state()
            self._prove_hermes_bootstrap()
            self._prove_fish_bootstrap()
            self._prove_atlas_bootstrap()
            self._prove_tradefloor_gate()
            self._prove_tradefloor_synthesis()
            self._prove_idempotent()
            self._prove_bootstrap_status()
            self._prove_brief_has_bootstrap()
            self._prove_lane_b_cycle()
        except Exception as e:
            self.check(f"UNEXPECTED ERROR: {e}", False, "proof aborted")
        finally:
            # Cleanup
            shutil.rmtree(self.root, ignore_errors=True)

        passed = sum(1 for _, ok, _ in self.results if ok)
        total = len(self.results)
        print(f"\n{'=' * 70}")
        print(f"COLD-START PROOF  {passed}/{total} pass")
        return passed == total

    def _prove_empty_state(self):
        """Verify isolated root starts truly empty."""
        from workspace.quant.shared.packet_store import get_all_latest, list_lane_packets
        from workspace.quant.bootstrap import get_all_bootstrap_status

        latest = get_all_latest(self.root)
        self.check("empty state: no latest packets", len(latest) == 0, f"got {len(latest)}")

        bs = get_all_bootstrap_status(self.root)
        all_not_started = all(s == "not_started" for s in bs.values())
        self.check("empty state: all lanes not_started", all_not_started, str(bs))

    def _prove_hermes_bootstrap(self):
        """Hermes cold-starts from watchlist, produces real packets."""
        from workspace.quant.bootstrap import bootstrap_hermes
        from workspace.quant.shared.packet_store import list_lane_packets
        from workspace.quant.shared.schemas.packets import validate_packet

        result = bootstrap_hermes(self.root)
        emitted = result.get("emitted", 0)
        self.check("hermes bootstrap: emitted > 0", emitted > 0, f"emitted={emitted}")
        self.check("hermes bootstrap: watchlist used",
                    result.get("watchlist_entries", 0) > 0,
                    f"entries={result.get('watchlist_entries', 0)}")

        packets = list_lane_packets(self.root, "hermes", "research_packet")
        self.check("hermes bootstrap: packets on disk",
                    len(packets) == emitted, f"disk={len(packets)} emitted={emitted}")

        # All packets valid
        all_valid = all(validate_packet(p) == [] for p in packets)
        self.check("hermes bootstrap: all packets valid", all_valid)

        # Each has a real source in notes
        all_sourced = all("source=" in (p.notes or "") for p in packets)
        self.check("hermes bootstrap: all have source", all_sourced)

    def _prove_fish_bootstrap(self):
        """Fish cold-starts with seed scenarios/regimes, no fake calibration."""
        from workspace.quant.bootstrap import bootstrap_fish
        from workspace.quant.shared.packet_store import list_lane_packets
        from workspace.quant.fish.scenario_lane import build_calibration_state

        result = bootstrap_fish(self.root)
        self.check("fish bootstrap: regimes emitted",
                    result.get("regimes_emitted", 0) > 0,
                    f"regimes={result.get('regimes_emitted', 0)}")
        self.check("fish bootstrap: scenarios emitted",
                    result.get("scenarios_emitted", 0) > 0,
                    f"scenarios={result.get('scenarios_emitted', 0)}")
        self.check("fish bootstrap: risk map emitted",
                    result.get("risk_maps_emitted", 0) > 0,
                    f"risk_maps={result.get('risk_maps_emitted', 0)}")

        # No fake calibration history
        cal = build_calibration_state(self.root)
        self.check("fish bootstrap: zero calibrations (honest)",
                    cal["total_calibrations"] == 0,
                    f"calibrations={cal['total_calibrations']}")
        self.check("fish bootstrap: trend is insufficient_data",
                    cal["trend"] == "insufficient_data",
                    f"trend={cal['trend']}")

        # Regime labels are real
        regimes = list_lane_packets(self.root, "fish", "regime_packet")
        labels = []
        for r in regimes:
            for part in (r.notes or "").split(";"):
                if part.strip().startswith("regime="):
                    labels.append(part.strip().split("=", 1)[1])
        all_real = all(len(l) > 3 and l != "unknown" for l in labels)
        self.check("fish bootstrap: regime labels are real",
                    all_real and len(labels) > 0, f"labels={labels}")

    def _prove_atlas_bootstrap(self):
        """Atlas cold-starts from seed themes, bounded, links Hermes evidence."""
        from workspace.quant.bootstrap import bootstrap_atlas
        from workspace.quant.shared.registries.strategy_registry import load_all_strategies
        from workspace.quant.shared.packet_store import list_lane_packets

        # Atlas requires Hermes evidence by default in the real config.
        # Our isolated root already has Hermes packets from the previous step.
        # Override require_hermes_evidence for determinism if needed.
        config_path = self.root / "workspace" / "quant" / "shared" / "config" / "atlas_sources.json"
        if config_path.exists():
            config = json.loads(config_path.read_text(encoding="utf-8"))
            had_hermes_req = config.get("require_hermes_evidence", False)
        else:
            had_hermes_req = False

        result = bootstrap_atlas(self.root)
        generated = result.get("candidates_generated", 0)
        self.check("atlas bootstrap: candidates generated",
                    generated > 0, f"generated={generated}")

        # Bounded
        max_allowed = 3  # from atlas_sources.json
        self.check("atlas bootstrap: bounded count",
                    generated <= max_allowed, f"{generated} <= {max_allowed}")

        # Strategies in registry
        strategies = load_all_strategies(self.root)
        real = {sid: s for sid, s in strategies.items()
                if not any(m in sid.lower() for m in ("proof", "smoke", "test-"))}
        self.check("atlas bootstrap: strategies in registry",
                    len(real) == generated, f"registry={len(real)} generated={generated}")

        # Evidence refs link to Hermes if required
        if had_hermes_req:
            candidates = list_lane_packets(self.root, "atlas", "candidate_packet")
            linked = all(
                any(r.startswith("hermes-") for r in c.evidence_refs)
                for c in candidates if c.evidence_refs
            )
            self.check("atlas bootstrap: linked to Hermes evidence", linked)

    def _prove_tradefloor_gate(self):
        """TradeFloor does NOT synthesize from empty upstream."""
        from workspace.quant.bootstrap import bootstrap_tradefloor

        # Use a fresh sub-root with nothing
        empty_root = Path(tempfile.mkdtemp(prefix="tf_empty_"))
        try:
            (empty_root / "workspace" / "quant" / "shared" / "latest").mkdir(parents=True)
            (empty_root / "workspace" / "quant" / "shared" / "config").mkdir(parents=True)
            (empty_root / "workspace" / "quant" / "shared" / "scheduler").mkdir(parents=True)
            for lane in ["atlas", "fish", "hermes", "sigma", "kitt", "tradefloor", "executor"]:
                (empty_root / "workspace" / "quant" / lane).mkdir(parents=True)

            # Copy hosts + governor
            config_src = ROOT / "workspace" / "quant" / "shared" / "config"
            for name in ["hosts.json", "governor_state.json"]:
                src = config_src / name
                if src.exists():
                    shutil.copy2(src, empty_root / "workspace" / "quant" / "shared" / "config" / name)

            result = bootstrap_tradefloor(empty_root)
            self.check("tradefloor gate: refuses empty upstream",
                        result["can_synthesize"] is False,
                        f"can_synthesize={result['can_synthesize']}, lanes={result['upstream_lanes']}")
        finally:
            shutil.rmtree(empty_root, ignore_errors=True)

    def _prove_tradefloor_synthesis(self):
        """TradeFloor synthesizes when sufficient upstream exists."""
        from workspace.quant.bootstrap import bootstrap_tradefloor

        # Our isolated root now has Hermes + Fish + Atlas packets
        result = bootstrap_tradefloor(self.root)
        self.check("tradefloor synthesis: can synthesize with upstream",
                    result["can_synthesize"] is True,
                    f"upstream={result['upstream_lanes']}")
        self.check("tradefloor synthesis: produced a tier",
                    result.get("synthesized") is True,
                    f"tier={result.get('tier')}")

    def _prove_idempotent(self):
        """Repeat bootstrap does not duplicate."""
        from workspace.quant.bootstrap import bootstrap_hermes, bootstrap_fish, bootstrap_atlas

        r_h = bootstrap_hermes(self.root)
        self.check("idempotent: hermes re-run emits 0",
                    r_h["emitted"] == 0, f"emitted={r_h['emitted']}")

        r_f = bootstrap_fish(self.root)
        self.check("idempotent: fish re-run already_bootstrapped",
                    r_f.get("already_bootstrapped") is True,
                    str({k: v for k, v in r_f.items() if k != "calibration_state"}))

        r_a = bootstrap_atlas(self.root)
        self.check("idempotent: atlas re-run already_bootstrapped",
                    r_a.get("already_bootstrapped") is True, str(r_a))

    def _prove_bootstrap_status(self):
        """Status reports truth about lane states."""
        from workspace.quant.bootstrap import get_all_bootstrap_status

        bs = get_all_bootstrap_status(self.root)
        # After bootstrap, lanes with recent packets should be 'active'
        for lane in ["hermes", "fish", "atlas"]:
            self.check(f"status: {lane} is active after bootstrap",
                        bs[lane] == "active", f"{lane}={bs[lane]}")
        # TradeFloor should be active after synthesis
        self.check("status: tradefloor is active after synthesis",
                    bs["tradefloor"] == "active", f"tradefloor={bs['tradefloor']}")

    def _prove_brief_has_bootstrap(self):
        """Kitt brief includes bootstrap status in HEALTH section."""
        from workspace.quant.kitt.brief_producer import produce_brief

        brief = produce_brief(self.root, market_read="Cold-start proof.")
        notes = brief.notes or ""
        self.check("brief: contains HEALTH section", "HEALTH" in notes)
        self.check("brief: contains bootstrap status",
                    "Bootstrap:" in notes, notes[notes.find("Bootstrap:"):notes.find("Bootstrap:") + 60] if "Bootstrap:" in notes else "not found")

    def _prove_lane_b_cycle(self):
        """Lane B cycle uses config-driven inputs for all lanes."""
        from workspace.quant.run_lane_b_cycle import (
            run_cycle, _build_atlas_cycle_input, _build_fish_cycle_input,
        )

        # Use a fresh root to prove cold-start path in cycle
        fresh = _setup_isolated_root()
        try:
            summary = run_cycle(fresh, verbose=False)

            from workspace.quant.shared.packet_store import list_lane_packets as _llp

            # --- Hermes: packets on disk from bootstrap or watchlist ---
            hermes_pkts = _llp(fresh, "hermes", "research_packet")
            self.check("cycle: hermes packets on disk",
                        len(hermes_pkts) > 0 or summary["hermes"]["emitted"] > 0,
                        f"packets={len(hermes_pkts)} emitted={summary['hermes']['emitted']}")

            # --- Atlas: config-driven, not hardcoded stub ---
            atlas_input = _build_atlas_cycle_input(fresh)
            if atlas_input:
                # Thesis must come from atlas_sources.json, not a hardcoded string
                config_path = fresh / "workspace" / "quant" / "shared" / "config" / "atlas_sources.json"
                config = json.loads(config_path.read_text(encoding="utf-8"))
                config_theses = {t["thesis"] for t in config.get("seed_themes", [])}
                input_thesis = atlas_input[0]["thesis"]
                self.check("cycle: atlas input from config",
                            input_thesis in config_theses,
                            f"thesis={input_thesis[:60]}")
                # Evidence refs should link to Hermes if available
                refs = atlas_input[0].get("evidence_refs") or []
                self.check("cycle: atlas links hermes evidence",
                            len(refs) > 0 and all(r.startswith("hermes-") for r in refs),
                            f"refs={len(refs)}")
            else:
                self.check("cycle: atlas input from config",
                            False, "no atlas input built (missing hermes evidence?)")
                self.check("cycle: atlas links hermes evidence", False, "skipped")

            atlas_pkts = _llp(fresh, "atlas", "candidate_packet")
            self.check("cycle: atlas candidates on disk",
                        len(atlas_pkts) > 0 or summary["atlas"]["generated"] > 0,
                        f"packets={len(atlas_pkts)} generated={summary['atlas']['generated']}")

            # --- Fish: config-driven, not hardcoded stub ---
            fish_input = _build_fish_cycle_input(fresh)
            self.check("cycle: fish input is non-empty",
                        len(fish_input) > 0, f"inputs={len(fish_input)}")
            if fish_input:
                config_path = fresh / "workspace" / "quant" / "shared" / "config" / "fish_bootstrap.json"
                config = json.loads(config_path.read_text(encoding="utf-8"))
                config_theses = {s["thesis"] for s in config.get("seed_scenarios", [])}
                input_thesis = fish_input[0]["thesis"]
                # The thesis may have a [regime: ...] suffix appended, so check prefix
                base_thesis = input_thesis.split(" [regime:")[0]
                self.check("cycle: fish input from config",
                            base_thesis in config_theses,
                            f"thesis={input_thesis[:60]}")

            fish_pkts = _llp(fresh, "fish", "scenario_packet")
            self.check("cycle: fish scenarios on disk",
                        len(fish_pkts) > 0 or summary["fish"]["emitted"] > 0,
                        f"packets={len(fish_pkts)} emitted={summary['fish']['emitted']}")

            # --- TradeFloor: synthesizes from real upstream ---
            tf_pkts = _llp(fresh, "tradefloor", "tradefloor_packet")
            if summary["tradefloor"]["ran"]:
                self.check("cycle: tradefloor synthesized",
                            len(tf_pkts) > 0, f"packets={len(tf_pkts)}")
                # Check evidence_refs link to real upstream packets
                tf = tf_pkts[-1]
                has_upstream_refs = any(
                    r.startswith(("hermes-", "atlas-", "fish-"))
                    for r in (tf.evidence_refs or [])
                )
                self.check("cycle: tradefloor refs real upstream",
                            has_upstream_refs,
                            f"refs={[r[:30] for r in (tf.evidence_refs or [])]}")
            else:
                # Cadence refused is OK — still check that it tried
                self.check("cycle: tradefloor ran or cadence-gated",
                            summary["tradefloor"]["cadence_refused"] or summary["tradefloor"]["ran"],
                            str(summary["tradefloor"]))

            # --- Brief produced ---
            self.check("cycle: brief produced",
                        summary["brief"] is True, f"brief={summary['brief']}")

            # --- No errors ---
            self.check("cycle: no errors",
                        len(summary["errors"]) == 0,
                        f"errors={summary['errors']}" if summary["errors"] else "clean")

        finally:
            shutil.rmtree(fresh, ignore_errors=True)


def main():
    proof = Proof()
    ok = proof.run()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
