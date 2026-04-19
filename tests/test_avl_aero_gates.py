# ruff: noqa: E402
from __future__ import annotations

import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.aero import AvlAeroGateSettings, build_avl_aero_gate_settings, evaluate_aero_performance
from hpa_mdo.core import load_config


def _minimal_avl_text(*, sref: float) -> str:
    return "\n".join(
        [
            "unit-test",
            "#Mach",
            "0.0",
            "#Sref Cref Bref",
            f"{float(sref):.6f} 1.130200 33.000000",
            "#Xref Yref Zref",
            "0.282540 0.000000 0.000000",
            "SURFACE",
            "Wing",
            "SECTION",
            "0.000000 0.000000 0.000000 1.300000 0.000000",
            "AFILE",
            "fx76mp140.dat",
        ]
    ) + "\n"


class AvlAeroGateTests(unittest.TestCase):
    def test_build_avl_aero_gate_settings_uses_candidate_avl_sref(self) -> None:
        cfg = load_config(REPO_ROOT / "configs" / "blackcat_004.yaml")
        with tempfile.TemporaryDirectory() as tmp:
            avl_path = Path(tmp) / "case.avl"
            avl_path.write_text(_minimal_avl_text(sref=35.175), encoding="utf-8")

            gate = build_avl_aero_gate_settings(cfg=cfg, case_avl_path=avl_path)

        dynamic_pressure = 0.5 * float(cfg.flight.air_density) * float(cfg.flight.velocity) ** 2
        expected_cl = float(cfg.weight.max_takeoff_kg) * 9.81 / (dynamic_pressure * 35.175)
        self.assertAlmostEqual(gate.reference_area_m2, 35.175, places=6)
        self.assertAlmostEqual(gate.cl_required, expected_cl, places=9)
        self.assertAlmostEqual(gate.cl_required, 1.0777105, places=6)

    def test_evaluate_aero_performance_uses_gate_reference_area_for_lift(self) -> None:
        gate = AvlAeroGateSettings(
            reference_area_source="generated_avl_sref",
            reference_area_m2=35.175,
            reference_area_case_path="/tmp/case.avl",
            air_density_kgpm3=1.225,
            cruise_velocity_mps=6.5,
            dynamic_pressure_pa=25.878125,
            trim_target_weight_kg=100.0,
            trim_target_weight_n=981.0,
            cl_required=981.0 / (25.878125 * 35.175),
            min_lift_kg=100.0,
            min_lift_n=981.0,
            min_ld_ratio=25.0,
            cd_profile_estimate=0.010,
            max_trim_aoa_deg=12.0,
            soft_trim_aoa_deg=10.0,
            stall_alpha_deg=13.5,
            min_stall_margin_deg=2.0,
        )
        trim_eval = mock.Mock(
            trim_converged=True,
            trim_status="trim_converged",
            cl_trim=gate.cl_required,
            cd_induced=0.018,
            aoa_trim_deg=10.2,
            span_efficiency=0.72,
        )

        perf = evaluate_aero_performance(trim_eval=trim_eval, gate_settings=gate)

        self.assertTrue(perf.aero_performance_feasible)
        assert perf.lift_total_n is not None
        self.assertTrue(math.isclose(perf.lift_total_n, 981.0, rel_tol=1.0e-9, abs_tol=1.0e-6))

    def test_evaluate_aero_performance_tolerates_trim_roundoff_at_lift_gate(self) -> None:
        gate = AvlAeroGateSettings(
            reference_area_source="generated_avl_sref",
            reference_area_m2=35.175,
            reference_area_case_path="/tmp/case.avl",
            air_density_kgpm3=1.225,
            cruise_velocity_mps=6.5,
            dynamic_pressure_pa=25.878125,
            trim_target_weight_kg=100.0,
            trim_target_weight_n=981.0,
            cl_required=1.0777104523443473,
            min_lift_kg=100.0,
            min_lift_n=981.0,
            min_ld_ratio=25.0,
            cd_profile_estimate=0.010,
            max_trim_aoa_deg=12.0,
            soft_trim_aoa_deg=10.0,
            stall_alpha_deg=13.5,
            min_stall_margin_deg=2.0,
        )
        trim_eval = mock.Mock(
            trim_converged=True,
            trim_status="trim_converged",
            cl_trim=1.07771,
            cd_induced=0.0144779,
            aoa_trim_deg=10.16612,
            span_efficiency=0.8038,
        )

        perf = evaluate_aero_performance(trim_eval=trim_eval, gate_settings=gate)

        self.assertTrue(perf.aero_performance_feasible)
        self.assertEqual(perf.aero_performance_reason, "ok")
        assert perf.lift_total_n is not None
        self.assertLess(981.0 - perf.lift_total_n, 1.0e-3)

    def test_gate_metadata_records_reference_area_source_and_path(self) -> None:
        gate = AvlAeroGateSettings(
            reference_area_source="generated_avl_sref",
            reference_area_m2=35.175,
            reference_area_case_path="/tmp/case.avl",
            air_density_kgpm3=1.225,
            cruise_velocity_mps=6.5,
            dynamic_pressure_pa=25.878125,
            trim_target_weight_kg=100.0,
            trim_target_weight_n=981.0,
            cl_required=1.0777105,
            min_lift_kg=100.0,
            min_lift_n=981.0,
            min_ld_ratio=25.0,
            cd_profile_estimate=0.010,
            max_trim_aoa_deg=12.0,
            soft_trim_aoa_deg=10.0,
            stall_alpha_deg=13.5,
            min_stall_margin_deg=2.0,
        )

        payload = gate.to_metadata(
            skip_aero_gates=False,
            skip_beta_sweep=False,
            max_sideslip_deg=12.0,
            min_spiral_time_to_double_s=10.0,
            beta_sweep_values_deg=(0.0, 5.0, 10.0, 12.0),
        )

        self.assertEqual(payload["reference_area_source"], "generated_avl_sref")
        self.assertEqual(payload["reference_area_case_path"], "/tmp/case.avl")
        self.assertAlmostEqual(float(payload["reference_area_m2"]), 35.175, places=6)
        self.assertAlmostEqual(float(payload["cl_required"]), 1.0777105, places=6)


if __name__ == "__main__":
    unittest.main()
