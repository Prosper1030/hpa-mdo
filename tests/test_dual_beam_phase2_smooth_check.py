from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.dual_beam_phase2_smooth_check import build_phase2_report  # noqa: E402


def test_build_phase2_report_includes_optimizer_and_report_channels(tmp_path: Path) -> None:
    result = SimpleNamespace(
        report=SimpleNamespace(
            tip_deflection_main_m=-2.3,
            tip_deflection_rear_m=-3.1,
            max_vertical_displacement_m=3.1,
            max_vertical_spar="rear",
            max_vertical_node=60,
        ),
        recovery=SimpleNamespace(spar_tube_mass_full_kg=9.454),
        optimizer=SimpleNamespace(
            psi_u_all_m=3.12,
            psi_u_rear_m=3.11,
            psi_u_rear_outboard_m=3.10,
            dual_displacement_limit_m=3.20,
            equivalent_gates=SimpleNamespace(
                analysis_success=True,
                failure_passed=True,
                failure_index=-0.2,
                failure_margin=0.2,
                buckling_passed=True,
                buckling_index=-0.3,
                buckling_margin=0.3,
                tip_passed=True,
                tip_deflection_m=2.5,
                tip_limit_m=3.0,
                tip_margin_m=0.5,
                twist_passed=True,
                twist_max_deg=0.8,
                twist_limit_deg=2.0,
                twist_margin_deg=1.2,
            ),
        ),
        feasibility=SimpleNamespace(
            analysis_succeeded=True,
            geometry_validity_succeeded=True,
            dual_displacement_candidate_passed=True,
            overall_hard_feasible=True,
            overall_optimizer_candidate_feasible=True,
            hard_failures=(),
            candidate_constraint_failures=(),
            report_only_channels=("raw_max_vertical_displacement", "dual_stress_metrics"),
        ),
    )
    parity = SimpleNamespace(
        report=SimpleNamespace(
            tip_deflection_main_m=-2.8,
            tip_deflection_rear_m=-3.3,
            max_vertical_displacement_m=3.3,
        ),
        optimizer=SimpleNamespace(
            psi_u_all_m=3.35,
            psi_u_rear_m=3.34,
            psi_u_rear_outboard_m=3.32,
        ),
    )

    report = build_phase2_report(
        config_path=tmp_path / "cfg.yaml",
        design_report=tmp_path / "crossval_report.txt",
        cruise_aoa_deg=4.2,
        production_result=result,
        parity_result=parity,
    )

    assert "Dual-Beam Production Phase-2 Smooth Evaluator Baseline" in report
    assert "psi_u_all" in report
    assert "Equivalent validated gates (legacy retained)" in report
    assert "Report-only outputs:" in report
    assert "raw max |UZ|" in report
