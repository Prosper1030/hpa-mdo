from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_canonical_hybrid_phase2_pressure_sanity.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "run_canonical_hybrid_phase2_pressure_sanity",
        SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_pressure_surface_uses_half_wing_marker_split() -> None:
    module = _load_module()

    surface = module.build_phase2_pressure_surface(
        module.DEFAULT_SECTION_TABLE_PATH,
        points_per_side=8,
        spanwise_subdivisions=1,
    )
    counts = surface.marker_counts()

    assert counts["wing_upper"] > 0
    assert counts["wing_lower"] > 0
    assert counts["te_wall"] > 0
    assert counts["closure_wall"] > 0
    assert counts["tip_wall"] > 0
    assert "root_symmetry" not in counts
    assert surface.metadata["side"] == "half"
    assert surface.metadata["root_symmetry_plane"] == "y=0"
    assert surface.metadata["force_monitoring_markers"] == ["wing_upper", "wing_lower"]


def test_pressure_runtime_config_separates_euler_symmetry_farfield_and_force_markers() -> None:
    module = _load_module()

    cfg = module.pressure_sanity_cfg_text(
        ref_area=16.710029799,
        ref_length=1.003721543,
        ref_origin=(0.246276512, 0.0, 0.0),
        velocity_mps=6.5,
        alpha_deg=0.0,
        max_iterations=100,
    )

    assert "SOLVER= INC_EULER" in cfg
    assert "MARKER_EULER= ( wing_upper, wing_lower, tip_wall, te_wall, closure_wall )" in cfg
    assert "MARKER_SYM= ( root_symmetry )" in cfg
    assert "MARKER_FAR= ( farfield )" in cfg
    assert "MARKER_MONITORING= ( wing_upper, wing_lower )" in cfg
    assert "AOA= 0.000000" in cfg
    assert "WRT_FORCES_BREAKDOWN= YES" in cfg
    assert "BREAKDOWN_FILENAME= forces_breakdown.dat" in cfg


def test_pressure_gate_passes_only_completed_stable_low_pressure_cd_with_force_breakdown() -> None:
    module = _load_module()

    pass_gate = module.evaluate_phase2_pressure_gate(
        {
            "solver": {
                "run_status": "completed",
                "dual_control_volume_quality": {
                    "status": "available",
                    "min_orthogonality_deg": 19.4,
                    "max_cv_face_area_aspect_ratio": 7487.0,
                    "max_cv_sub_volume_ratio": 186725.0,
                },
                "history": {
                    "row_count": 250,
                    "final_coefficients": {"cd": 0.018, "cl": 0.52, "cmy": -0.02},
                    "tail_stability": {
                        "cl_relative_span": 0.004,
                        "cd_relative_span": 0.003,
                    },
                },
            },
            "mesh": {
                "marker_audit": {"status": "pass"},
                "mesh_quality_gate": {"status": "pass"},
                "required_markers_present": True,
                "max_farfield_vertex_incident_volume_cells": 12,
            },
            "forces_breakdown": {"status": "available"},
        }
    )
    fail_gate = module.evaluate_phase2_pressure_gate(
        {
            "solver": {
                "run_status": "completed",
                "dual_control_volume_quality": {
                    "status": "available",
                    "min_orthogonality_deg": 19.4,
                    "max_cv_face_area_aspect_ratio": 7487.0,
                    "max_cv_sub_volume_ratio": 186725.0,
                },
                "history": {
                    "row_count": 250,
                    "final_coefficients": {"cd": 0.22, "cl": 0.52, "cmy": -0.02},
                    "tail_stability": {
                        "cl_relative_span": 0.004,
                        "cd_relative_span": 0.003,
                    },
                },
            },
            "mesh": {
                "marker_audit": {"status": "pass"},
                "mesh_quality_gate": {"status": "pass"},
                "required_markers_present": True,
                "max_farfield_vertex_incident_volume_cells": 12,
            },
            "forces_breakdown": {"status": "available"},
        }
    )

    assert pass_gate["status"] == "pass"
    assert pass_gate["release_status"] == "PRESSURE_SANITY_PASS"
    assert fail_gate["status"] == "fail"
    assert "pressure_cd_exceeds_0p15" in fail_gate["blockers"]


def test_pressure_gate_rejects_pathological_su2_dual_quality() -> None:
    module = _load_module()

    gate = module.evaluate_phase2_pressure_gate(
        {
            "solver": {
                "run_status": "completed",
                "dual_control_volume_quality": {
                    "status": "available",
                    "min_orthogonality_deg": 0.001,
                    "max_cv_face_area_aspect_ratio": 5.0e8,
                    "max_cv_sub_volume_ratio": 2.0e11,
                },
                "history": {
                    "row_count": 250,
                    "final_coefficients": {"cd": 0.018, "cl": 0.52, "cmy": -0.02},
                    "tail_stability": {
                        "cl_relative_span": 0.004,
                        "cd_relative_span": 0.003,
                    },
                },
            },
            "mesh": {
                "marker_audit": {"status": "pass"},
                "mesh_quality_gate": {"status": "pass"},
                "required_markers_present": True,
                "max_farfield_vertex_incident_volume_cells": 12,
            },
            "forces_breakdown": {"status": "available"},
        }
    )

    assert gate["status"] == "fail"
    assert "pressure_su2_dual_min_orthogonality_pathological" in gate["blockers"]
    assert "pressure_su2_dual_face_area_aspect_ratio_pathological" in gate["blockers"]
    assert "pressure_su2_dual_sub_volume_ratio_pathological" in gate["blockers"]


def test_su2_dual_quality_parser_reads_solver_table() -> None:
    module = _load_module()
    parsed = module.parse_su2_dual_control_volume_quality(
        "\n".join(
            [
                "|    Orthogonality Angle (deg.)|        19.4086|        80.4176|",
                "|     CV Face Area Aspect Ratio|        1.26909|        7487.37|",
                "|           CV Sub-Volume Ratio|        1.01625|         186725|",
            ]
        )
    )

    assert parsed["status"] == "available"
    assert parsed["min_orthogonality_deg"] == 19.4086
    assert parsed["max_cv_face_area_aspect_ratio"] == 7487.37
    assert parsed["max_cv_sub_volume_ratio"] == 186725


def test_pressure_manifest_update_records_report_path(tmp_path: Path) -> None:
    module = _load_module()
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "passed_gate_statuses:",
                "- TOOLCHAIN_PASS",
                "next_required_gate_status: PRESSURE_SANITY_PASS",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    summary = {
        "report_path": "output/cfd_release_v0/pressure_sanity/pressure_sanity_report.json",
        "case_dir": "output/cfd_release_v0/pressure_sanity",
    }

    module.mark_manifest_pressure_sanity_pass(manifest_path, summary)

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest["passed_gate_statuses"] == ["TOOLCHAIN_PASS", "PRESSURE_SANITY_PASS"]
    assert manifest["next_required_gate_status"] == "ROUTE_SMOKE_PASS"
    assert manifest["phase2_pressure_sanity"]["status"] == "PRESSURE_SANITY_PASS"
    assert manifest["phase2_pressure_sanity"]["report_path"] == summary["report_path"]
