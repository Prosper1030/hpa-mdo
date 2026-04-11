from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.ansys_dual_beam_production_check import (  # noqa: E402
    ModeSnapshot,
    build_robustness_report,
    build_specimen_result_from_crossval_report,
)


def test_build_specimen_result_from_crossval_report_reconstructs_segment_design(tmp_path: Path) -> None:
    report_path = tmp_path / "crossval_report.txt"
    report_path.write_text(
        "\n".join(
            [
                "Spar tube mass (full-span)             9.454 kg",
                "Total optimized mass (full)           11.954 kg",
                "Tip deflection (uz, y=16.5m)        2500.000 mm",
                "Max Von Mises (main spar)             530.823 MPa",
                "Max Von Mises (rear spar)             257.210 MPa",
                "Max twist angle                         0.213 deg",
                "  Main spar:",
                "    Seg 1: OD=61.27mm, t=0.80mm",
                "    Seg 2: OD=45.95mm, t=0.90mm",
                "  Rear spar:",
                "    Seg 1: OD=20.00mm, t=0.80mm",
                "    Seg 2: OD=21.00mm, t=0.85mm",
            ]
        ),
        encoding="utf-8",
    )

    result = build_specimen_result_from_crossval_report(report_path)

    assert result.success is True
    assert result.main_r_seg_mm.tolist() == [30.635, 22.975]
    assert result.main_t_seg_mm.tolist() == [0.8, 0.9]
    assert result.rear_r_seg_mm.tolist() == [10.0, 10.5]
    assert result.rear_t_seg_mm.tolist() == [0.8, 0.85]
    assert result.spar_mass_full_kg == 9.454
    assert result.total_mass_full_kg == 11.954


def test_build_robustness_report_lists_mode_deltas() -> None:
    report = build_robustness_report(
        snapshots=[
            ModeSnapshot(
                label="parity",
                mode="dual_spar_ansys_parity",
                link_mode="joint_only_equal_dof_parity",
                main_tip_mm=2800.0,
                rear_tip_mm=3350.0,
                max_uz_mm=3350.0,
                max_uz_location="rear node 60",
                spar_mass_full_kg=9.45,
                root_main_fz_n=-5.0,
                root_rear_fz_n=-23.0,
                wire_fz_n=-882.0,
                support_total_abs_fz_n=910.0,
                link_force_max_n=5500.0,
                reaction_balance_residual_n=1.0e-9,
                hottest_link_nodes=(17, 28, 39),
            ),
            ModeSnapshot(
                label="production_default",
                mode="dual_beam_production",
                link_mode="joint_only_offset_rigid",
                main_tip_mm=2390.0,
                rear_tip_mm=3228.0,
                max_uz_mm=3228.0,
                max_uz_location="rear node 60",
                spar_mass_full_kg=9.45,
                root_main_fz_n=87.0,
                root_rear_fz_n=-116.0,
                wire_fz_n=-789.0,
                support_total_abs_fz_n=818.0,
                link_force_max_n=5797.0,
                reaction_balance_residual_n=1.0e-9,
                hottest_link_nodes=(28, 39, 49),
            ),
        ]
    )

    assert "Dual-Beam Production Robustness Summary" in report
    assert "production_default" in report
    assert "Delta vs parity -> production_default" in report
    assert "hottest link nodes=(28, 39, 49)" in report


def test_build_specimen_result_from_production_crossval_report_supports_new_format(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "crossval_report.txt"
    report_path.write_text(
        "\n".join(
            [
                "Spar tube mass (full-span)             9.454 kg",
                "Total optimized mass (full)           11.954 kg",
                "  Main tip deflection (uz, y=tip)    2393.720 mm   inspection / compare directly",
                "  Rear tip deflection (uz, y=tip)    3228.426 mm   inspection / compare directly",
                "  Max twist angle                      0.000 deg  informative / non-gating",
                "  Main spar:",
                "    Seg 1: OD=61.27mm, t=0.80mm",
                "    Seg 2: OD=45.95mm, t=0.90mm",
                "  Rear spar:",
                "    Seg 1: OD=20.00mm, t=0.80mm",
                "    Seg 2: OD=21.00mm, t=0.85mm",
            ]
        ),
        encoding="utf-8",
    )

    result = build_specimen_result_from_crossval_report(report_path)

    assert result.tip_deflection_m == 2.39372
    assert result.max_stress_main_Pa == 0.0
    assert result.max_stress_rear_Pa == 0.0
