#!/usr/bin/env python3
"""Validate the closed Baseline A canonical hybrid half-wing CFD release policy.

This checker is deliberately a route guardrail, not a mesher. It prevents the
WO-006 R-series forensic probes from being promoted back into the active CFD
delivery route after the R27/R28/R29/R30 evidence showed that all-tet BL/core
handoff and closure-marker repair can pass primal audits while failing SU2 dual
control-volume quality.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
    / "cfd_release_v0"
    / "manifest.yaml"
)

CANONICAL_ACTIVE_ROUTE = "canonical_hybrid_halfwing_v0"
ALLOWED_RELEASE_STATUSES = frozenset(
    {
        "TOOLCHAIN_PASS",
        "PRESSURE_SANITY_PASS",
        "ROUTE_SMOKE_PASS",
        "GRID_LADDER_PASS",
    }
)
EXPECTED_PHASE_GATE_ORDER = (
    "TOOLCHAIN_PASS",
    "PRESSURE_SANITY_PASS",
    "ROUTE_SMOKE_PASS",
    "GRID_LADDER_PASS",
)
RETIRED_R_ROUTES = frozenset(
    {
        "WO-006R25",
        "WO-006R26",
        "WO-006R27",
        "WO-006R28",
        "WO-006R29",
        "WO-006R30",
    }
)
REQUIRED_SURFACE_MARKERS = frozenset(
    {
        "wing_upper",
        "wing_lower",
        "tip_wall",
        "te_wall",
        "closure_wall",
        "root_symmetry",
        "farfield",
    }
)
PRIMARY_FORCE_MARKERS = ("wing_upper", "wing_lower")
REQUIRED_BANNED_METHODS = frozenset(
    {
        "all_tet_global_star_bl_handoff",
        "split_bl_cells_into_star_tets",
        "owner_pyramid_as_active_method",
        "closure_face_silent_merge_into_wing_wall",
        "single_case_face_id_marker_patch",
        "conservative_numerics_as_success",
    }
)
ALLOWED_WRITERS = frozenset(
    {
        "gmsh_su2_export_preserving_physical_groups_and_cell_types",
        "msh_to_su2_preserving_cell_types_only",
    }
)


def load_manifest(path: Path | str = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    manifest_path = Path(path)
    with manifest_path.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"manifest must be a YAML mapping: {manifest_path}")
    return dict(loaded)


def validate_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []

    active_route = str(manifest.get("active_cfd_route") or "")
    forensic_routes = _string_set(manifest.get("forensic_routes"))
    passed_statuses = _string_set(manifest.get("passed_gate_statuses"))
    phase_gate_order = tuple(str(item) for item in manifest.get("phase_gate_order") or ())
    mesh_policy = _mapping(manifest.get("mesh_topology_policy"))
    marker_policy = _mapping(manifest.get("marker_policy"))
    solver_policy = _mapping(manifest.get("solver_policy"))
    writer_policy = _mapping(manifest.get("writer_policy"))

    if active_route != CANONICAL_ACTIVE_ROUTE:
        blockers.append("active_route_must_be_canonical_hybrid_halfwing_v0")
    if active_route in RETIRED_R_ROUTES or active_route.startswith("WO-006R"):
        blockers.append("retired_r_route_cannot_be_active_cfd_delivery")
    if not {"WO-006R27", "WO-006R28", "WO-006R29"}.issubset(forensic_routes):
        blockers.append("forensic_routes_must_include_r27_r28_r29_evidence")
    if "WO-006R30" not in forensic_routes:
        blockers.append("forensic_routes_must_include_existing_r30_forensic_evidence")

    non_release_statuses = sorted(passed_statuses - ALLOWED_RELEASE_STATUSES)
    if non_release_statuses:
        blockers.append("manifest_contains_non_release_status")
    if phase_gate_order != EXPECTED_PHASE_GATE_ORDER:
        blockers.append("canonical_phase_gate_order_required")

    bl_cell_types = _string_set(mesh_policy.get("boundary_layer_cell_types"))
    core_cell_types = _string_set(mesh_policy.get("core_cell_types"))
    if not ({"prism", "hexa"} & bl_cell_types):
        blockers.append("boundary_layer_must_preserve_prism_or_hexa_cells")
    if "tetra" not in core_cell_types:
        blockers.append("core_must_use_tetra_cells")
    if not bool(mesh_policy.get("preserve_hybrid_cell_types")):
        blockers.append("hybrid_cell_types_must_be_preserved")
    if not bool(mesh_policy.get("interface_conformal_required")):
        blockers.append("bl_core_interface_must_be_conformal")
    missing_bans = REQUIRED_BANNED_METHODS - _string_set(mesh_policy.get("banned_methods"))
    if missing_bans:
        blockers.append("route_must_ban_old_patch_methods")

    required_markers = _string_set(marker_policy.get("required_surface_markers"))
    if not REQUIRED_SURFACE_MARKERS.issubset(required_markers):
        blockers.append("required_surface_marker_policy_incomplete")
    force_markers = tuple(str(item) for item in marker_policy.get("force_monitoring_markers") or ())
    if force_markers != PRIMARY_FORCE_MARKERS:
        blockers.append("primary_force_markers_must_be_wing_upper_lower")
    if "closure_wall" in force_markers:
        blockers.append("closure_wall_must_not_be_primary_force_marker")
    if not bool(marker_policy.get("closure_markers_reported_separately")):
        blockers.append("closure_markers_must_be_reported_separately")

    initial_3d_case = _mapping(solver_policy.get("initial_3d_viscous_case"))
    if float(initial_3d_case.get("aoa_deg") or 0.0) != 0.0:
        blockers.append("initial_3d_viscous_case_must_use_alpha_zero")
    if not bool(initial_3d_case.get("geometry_carries_incidence")):
        blockers.append("geometry_incidence_must_not_be_double_counted_with_aoa")
    if str(initial_3d_case.get("ref_area_basis") or "") != "half_physical_area":
        blockers.append("half_wing_ref_area_basis_required")
    if bool(solver_policy.get("conservative_numerics_counts_as_success")):
        blockers.append("conservative_numerics_cannot_count_as_success")
    if float(solver_policy.get("route_smoke_cd_max") or 0.0) > 0.15:
        blockers.append("route_smoke_cd_gate_must_not_exceed_0p15")

    allowed_writers = _string_set(writer_policy.get("allowed_writers"))
    if not allowed_writers.issubset(ALLOWED_WRITERS) or not allowed_writers:
        blockers.append("writer_policy_must_preserve_hybrid_cell_types_only")
    if REQUIRED_BANNED_METHODS - _string_set(writer_policy.get("forbidden_converter_behaviors")):
        blockers.append("writer_policy_must_ban_repair_and_split_converters")

    return {
        "status": "pass" if not blockers else "fail",
        "blockers": sorted(set(blockers)),
        "active_cfd_route": active_route,
        "forensic_routes": sorted(forensic_routes),
        "passed_gate_statuses": sorted(passed_statuses),
        "allowed_release_statuses": sorted(ALLOWED_RELEASE_STATUSES),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Path to cfd_release_v0 manifest.yaml.",
    )
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    result = validate_manifest(manifest)
    if result["status"] == "pass":
        print(
            "canonical hybrid CFD release policy passed: "
            f"active_cfd_route={result['active_cfd_route']}"
        )
        return 0
    print("canonical hybrid CFD release policy failed:")
    for blocker in result["blockers"]:
        print(f"- {blocker}")
    return 1


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, Sequence):
        return {str(item) for item in value}
    return set()


if __name__ == "__main__":
    raise SystemExit(main())
