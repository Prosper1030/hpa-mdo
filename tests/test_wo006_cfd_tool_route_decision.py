from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_wo006_cfd_tool_route_decision.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "run_wo006_cfd_tool_route_decision",
        SCRIPT_PATH,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_fullwing_pressure_surface_preserves_split_markers_without_symmetry() -> None:
    module = _load_module()

    surface = module.build_fullwing_pressure_surface(
        points_per_side=6,
        spanwise_subdivisions=1,
    )
    counts = surface.marker_counts()

    for marker in module.SPLIT_WING_MARKERS:
        assert counts[marker] > 0
    assert "root_symmetry" not in counts
    assert "tip_wall" not in counts
    assert surface.metadata["side"] == "full"
    assert surface.metadata["force_primary_markers"] == ["wing_upper", "wing_lower"]
    assert min(vertex[1] for vertex in surface.vertices) < 0.0
    assert max(vertex[1] for vertex in surface.vertices) > 0.0


def test_fullwing_pressure_config_uses_split_markers_and_no_symmetry() -> None:
    module = _load_module()

    cfg = module.fullwing_pressure_cfg_text(
        ref_area=33.420059598,
        ref_length=1.003721543,
        ref_origin=(0.246276512, 0.0, 0.0),
        velocity_mps=6.5,
        alpha_deg=0.0,
        max_iterations=100,
    )

    assert "SOLVER= INC_EULER" in cfg
    assert (
        "MARKER_EULER= ( wing_upper, wing_lower, tip_left, tip_right, "
        "te_wall, closure_wall )"
    ) in cfg
    assert "MARKER_FAR= ( farfield )" in cfg
    assert (
        "MARKER_MONITORING= ( wing_upper, wing_lower, tip_left, tip_right, "
        "te_wall, closure_wall )"
    ) in cfg
    assert "MARKER_SYM" not in cfg
    assert "AOA= 0.000000" in cfg
    assert "WRT_FORCES_BREAKDOWN= YES" in cfg


def test_openfoam_track_hard_stops_after_0_and_3_when_tools_missing() -> None:
    module = _load_module()

    summary = module.plan_openfoam_track_attempts(
        {
            "blockMesh": None,
            "snappyHexMesh": None,
            "checkMesh": None,
            "simpleFoam": None,
        }
    )

    attempted_layers = [attempt["nSurfaceLayers"] for attempt in summary["attempts"]]
    assert attempted_layers == [0, 3]
    assert summary["status"] == "blocked_tool_unavailable"
    assert summary["hard_stop_triggered"] is True
    assert summary["skipped_layers"] == [8]
    assert "openfoam_executables_missing" in summary["blockers"]


def test_force_breakdown_sums_primary_and_diagnostic_markers() -> None:
    module = _load_module()
    parsed = {
        "surface_coefficients": {
            "wing_upper": {"cd": {"total": 0.012}, "cl": {"total": 0.31}},
            "wing_lower": {"cd": {"total": 0.006}, "cl": {"total": 0.07}},
            "tip_left": {"cd": {"total": 0.001}, "cl": {"total": 0.0}},
            "tip_right": {"cd": {"total": 0.0015}, "cl": {"total": 0.0}},
            "te_wall": {"cd": {"total": 0.0004}, "cl": {"total": 0.0}},
            "closure_wall": {"cd": {"total": 0.0002}, "cl": {"total": 0.0}},
        }
    }

    summary = module.summarize_split_marker_forces(parsed)

    assert summary["primary"]["cd"] == 0.018
    assert summary["primary"]["cl"] == 0.38
    assert summary["diagnostics"]["tip_left"]["cd"] == 0.001
    assert summary["diagnostics"]["tip_right"]["cd"] == 0.0015
    assert summary["diagnostics"]["te_wall"]["cd"] == 0.0004
    assert summary["diagnostics"]["closure_wall"]["cd"] == 0.0002
    assert summary["total"]["cd"] == 0.0211


def test_decision_recommends_external_mesher_when_su2_markers_pass_but_dual_fails() -> None:
    module = _load_module()

    decision = module.build_tool_route_decision(
        {
            "status": "blocked_tool_unavailable",
            "blockers": ["openfoam_executables_missing"],
            "engineering_assessment": {"status": "not_run_locally"},
        },
        {
            "mesh": {
                "marker_audit": {"status": "pass"},
                "required_markers_present": True,
            },
            "gate": {
                "status": "fail",
                "blockers": [
                    "track_b_dual_sub_volume_ratio_pathological",
                    "track_b_solver_not_completed",
                ],
            },
        },
    )

    assert decision["recommendation"] == "B_mature_external_mesher_to_su2"
