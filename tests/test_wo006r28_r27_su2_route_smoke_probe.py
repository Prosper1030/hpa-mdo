from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r28_r27_su2_route_smoke.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r28_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_config_uses_wall_resolved_r27_markers_and_baseline_references() -> None:
    module = _load_module()

    cfg = module.build_r27_route_smoke_config(
        ref_area_m2=33.420059598,
        ref_length_m=1.003721543,
        moment_origin_m=(0.314193, 0.0, 0.0),
        iterations=180,
        alpha_deg=5.0,
    )

    assert "SOLVER= INC_RANS" in cfg
    assert "KIND_TURB_MODEL= SA" in cfg
    assert "INC_NONDIM= INITIAL_VALUES" in cfg
    assert "MARKER_HEATFLUX= ( wing_wall, 0.0 )" in cfg
    assert "MARKER_FAR= ( farfield )" in cfg
    assert "MARKER_MONITORING= ( wing_wall )" in cfg
    assert "MESH_FILENAME= mesh.su2" in cfg
    assert "REF_AREA= 33.420060" in cfg
    assert "REF_LENGTH= 1.003722" in cfg
    assert "REF_ORIGIN_MOMENT_X= 0.314193" in cfg
    assert "ITER= 180" in cfg

    marker_audit = module.audit_config_markers(
        {
            "markers": {
                "wing_wall": {"element_count": 1992},
                "farfield": {"element_count": 2366},
            }
        },
        cfg,
    )

    assert marker_audit["status"] == "pass"
    assert marker_audit["mesh_markers"] == ["farfield", "wing_wall"]


def test_config_marker_audit_rejects_missing_or_unassigned_markers() -> None:
    module = _load_module()
    cfg = module.build_r27_route_smoke_config(
        ref_area_m2=33.420059598,
        ref_length_m=1.003721543,
        moment_origin_m=(0.0, 0.0, 0.0),
    )

    result = module.audit_config_markers(
        {
            "markers": {
                "wing_wall": {"element_count": 1992},
                "unused_patch": {"element_count": 3},
            }
        },
        cfg,
    )

    assert result["status"] == "fail"
    assert result["missing_from_mesh"] == ["farfield"]
    assert result["unassigned_mesh_markers"] == ["unused_patch"]


def test_config_can_use_conservative_first_order_jst_numerics() -> None:
    module = _load_module()

    cfg = module.build_r27_route_smoke_config(
        ref_area_m2=33.420059598,
        ref_length_m=1.003721543,
        moment_origin_m=(0.0, 0.0, 0.0),
        cfl_number=0.02,
        conv_num_method_flow="JST",
        muscl_flow=False,
    )

    assert "CONV_NUM_METHOD_FLOW= JST" in cfg
    assert "CFL_NUMBER= 0.02" in cfg
    assert "MUSCL_FLOW= NO" in cfg
    assert "SLOPE_LIMITER_FLOW" not in cfg


def test_history_summary_reports_force_and_residual_stability(tmp_path: Path) -> None:
    module = _load_module()
    history_path = tmp_path / "history.csv"
    with history_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Inner_Iter", "CL", "CD", "CMy", "rms[P]"])
        for iteration in range(1, 121):
            writer.writerow(
                [
                    iteration,
                    0.8200 + iteration * 1.0e-6,
                    0.0340 + iteration * 1.0e-7,
                    -0.0210 + iteration * 1.0e-8,
                    -2.0 - iteration * 1.0e-3,
                ]
            )

    summary = module.summarize_history(history_path, window_rows=100)

    assert summary["row_count"] == 120
    assert summary["final_iteration"] == 120
    assert summary["final_coefficients"]["cl"] > 0.82
    assert summary["final_coefficients"]["cd"] < 0.035
    assert summary["force_stability"]["status"] == "pass"
    assert summary["residual_stability"]["status"] == "pass"
    assert summary["force_stability"]["window_rows"] == 100


def test_solver_log_quality_parser_blocks_pathological_dual_metrics(tmp_path: Path) -> None:
    module = _load_module()
    log_path = tmp_path / "solver.log"
    log_path.write_text(
        "\n".join(
            [
                "|    Orthogonality Angle (deg.)|     0.00108069|        81.0243|",
                "|     CV Face Area Aspect Ratio|        1.87185|    5.15199e+08|",
                "|           CV Sub-Volume Ratio|              1|    2.07841e+11|",
            ]
        ),
        encoding="utf-8",
    )

    quality = module.parse_solver_mesh_quality_from_log(log_path)

    assert quality["status"] == "fail"
    assert quality["minimum_orthogonality_angle_deg"] == 0.00108069
    assert quality["maximum_cv_face_area_aspect_ratio"] == 5.15199e8
    assert quality["maximum_cv_sub_volume_ratio"] == 2.07841e11
    assert "su2_dual_cv_face_area_aspect_ratio_extreme" in quality["blockers"]
    assert "su2_dual_cv_sub_volume_ratio_extreme" in quality["blockers"]


def test_route_smoke_summary_blocks_high_cd_and_never_promotes_completion() -> None:
    module = _load_module()

    summary = module.build_route_smoke_summary(
        output_dir=Path("/tmp/wo006r28"),
        r27_summary={
            "geometry_source": "/tmp/section_table.csv",
            "mixed_su2_handoff": {
                "mesh_path": "/tmp/r27.su2",
                "node_count": 56873,
                "volume_element_count": 332221,
                "marker_counts": {"wing_wall": 1992, "farfield": 2366},
            },
            "near_wall_yplus": {"status": "estimate_ready_not_solver_postprocessed"},
        },
        authority={
            "design_gross_mass_kg": 98.5,
            "pipeline_full_span_m": 34.332286,
            "pipeline_half_span_m": 17.166143,
            "sref_m2": 33.420059598,
            "cref_m": 1.003721543,
            "bref_m": 34.332286,
            "moment_origin_m": [0.0, 0.0, 0.0],
        },
        marker_audit={"status": "pass", "blockers": []},
        solver_report={
            "run_requested": True,
            "run_status": "completed",
            "returncode": 0,
            "elapsed_s": 12.0,
            "history_path": "/tmp/history.csv",
        },
        solver_mesh_quality={
            "status": "pass",
            "blockers": [],
        },
        history={
            "row_count": 120,
            "final_iteration": 120,
            "final_coefficients": {"cl": 0.74, "cd": 0.52, "cm": -0.04},
            "force_stability": {"status": "pass", "window_rows": 100},
            "residual_stability": {"status": "pass", "window_rows": 100},
        },
    )

    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert summary["coefficient_plausibility_gate"]["status"] == "fail"
    assert "route_smoke_cd_implausibly_high_for_hpa_main_wing" in summary["blockers"]
    assert "coarse_medium_fine_solver_ladder_not_run" in summary["blockers"]
    assert summary["coefficient_interpretable_for_grid_convergence"] is False
