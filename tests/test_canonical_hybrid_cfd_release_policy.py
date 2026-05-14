from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_canonical_hybrid_cfd_release.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "check_canonical_hybrid_cfd_release",
        SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_default_manifest_retires_r_series_and_keeps_canonical_route_active() -> None:
    module = _load_module()

    manifest = module.load_manifest(module.DEFAULT_MANIFEST_PATH)
    result = module.validate_manifest(manifest)

    assert result["status"] == "pass"
    assert manifest["active_cfd_route"] == "canonical_hybrid_halfwing_v0"
    assert {
        "WO-006R27",
        "WO-006R28",
        "WO-006R29",
        "WO-006R30",
    }.issubset(set(manifest["forensic_routes"]))
    assert "TOOLCHAIN_PASS" in manifest["phase_gate_order"]
    assert "PRESSURE_SANITY_PASS" in manifest["phase_gate_order"]
    assert "ROUTE_SMOKE_PASS" in manifest["phase_gate_order"]
    assert "GRID_LADDER_PASS" in manifest["phase_gate_order"]
    assert set(manifest["passed_gate_statuses"]).issubset(module.ALLOWED_RELEASE_STATUSES)
    assert "diagnostic_success" not in manifest["passed_gate_statuses"]


def test_validator_rejects_retired_r_route_as_active() -> None:
    module = _load_module()

    manifest = {
        "active_cfd_route": "WO-006R28",
        "forensic_routes": ["WO-006R27", "WO-006R28", "WO-006R29"],
        "passed_gate_statuses": ["diagnostic_success"],
        "phase_gate_order": list(module.EXPECTED_PHASE_GATE_ORDER),
        "mesh_topology_policy": {
            "boundary_layer_cell_types": ["tetra"],
            "core_cell_types": ["tetra"],
            "preserve_hybrid_cell_types": False,
            "interface_conformal_required": False,
            "banned_methods": [],
        },
        "marker_policy": {
            "required_surface_markers": ["wing_wall", "farfield"],
            "force_monitoring_markers": ["wing_wall"],
            "closure_markers_reported_separately": False,
        },
        "solver_policy": {
            "initial_3d_viscous_case": {"aoa_deg": 5.0},
            "conservative_numerics_counts_as_success": True,
        },
    }

    result = module.validate_manifest(manifest)

    assert result["status"] == "fail"
    assert "active_route_must_be_canonical_hybrid_halfwing_v0" in result["blockers"]
    assert "retired_r_route_cannot_be_active_cfd_delivery" in result["blockers"]
    assert "manifest_contains_non_release_status" in result["blockers"]


def test_validator_requires_hybrid_bl_core_topology_and_split_force_markers() -> None:
    module = _load_module()

    manifest = {
        "active_cfd_route": "canonical_hybrid_halfwing_v0",
        "forensic_routes": ["WO-006R27", "WO-006R28", "WO-006R29"],
        "passed_gate_statuses": [],
        "phase_gate_order": list(module.EXPECTED_PHASE_GATE_ORDER),
        "mesh_topology_policy": {
            "boundary_layer_cell_types": ["tetra"],
            "core_cell_types": ["tetra"],
            "preserve_hybrid_cell_types": False,
            "interface_conformal_required": True,
            "banned_methods": ["global_star_tet_bl_handoff"],
        },
        "marker_policy": {
            "required_surface_markers": [
                "wing_upper",
                "wing_lower",
                "root_symmetry",
                "farfield",
            ],
            "force_monitoring_markers": ["wing_upper", "wing_lower", "closure_wall"],
            "closure_markers_reported_separately": False,
        },
        "solver_policy": {
            "initial_3d_viscous_case": {"aoa_deg": 0.0},
            "conservative_numerics_counts_as_success": False,
        },
    }

    result = module.validate_manifest(manifest)

    assert result["status"] == "fail"
    assert "boundary_layer_must_preserve_prism_or_hexa_cells" in result["blockers"]
    assert "hybrid_cell_types_must_be_preserved" in result["blockers"]
    assert "required_surface_marker_policy_incomplete" in result["blockers"]
    assert "closure_wall_must_not_be_primary_force_marker" in result["blockers"]
    assert "closure_markers_must_be_reported_separately" in result["blockers"]


def test_validator_rejects_double_counted_aoa_and_conservative_success() -> None:
    module = _load_module()

    manifest = {
        "active_cfd_route": "canonical_hybrid_halfwing_v0",
        "forensic_routes": ["WO-006R27", "WO-006R28", "WO-006R29"],
        "passed_gate_statuses": [],
        "phase_gate_order": list(module.EXPECTED_PHASE_GATE_ORDER),
        "mesh_topology_policy": {
            "boundary_layer_cell_types": ["prism", "hexa"],
            "core_cell_types": ["tetra"],
            "preserve_hybrid_cell_types": True,
            "interface_conformal_required": True,
            "banned_methods": ["global_star_tet_bl_handoff"],
        },
        "marker_policy": {
            "required_surface_markers": list(module.REQUIRED_SURFACE_MARKERS),
            "force_monitoring_markers": ["wing_upper", "wing_lower"],
            "closure_markers_reported_separately": True,
        },
        "solver_policy": {
            "initial_3d_viscous_case": {"aoa_deg": 5.0},
            "conservative_numerics_counts_as_success": True,
        },
    }

    result = module.validate_manifest(manifest)

    assert result["status"] == "fail"
    assert "initial_3d_viscous_case_must_use_alpha_zero" in result["blockers"]
    assert "conservative_numerics_cannot_count_as_success" in result["blockers"]
