#!/usr/bin/env python3
"""Build the WO-006 HPA CFD verification scaffold from the latest OpenFOAM evidence.

This script is intentionally report-oriented. It does not claim grid
independence or update design power. It turns the recent successful full-wing
mirror OpenFOAM route into the current CFD verification basis and quarantines
the older AVL/Tier2 drag-power basis as comparison evidence only.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from cfd_rescue.baseline_geometry import load_baseline_authority
import run_wo006_true_baseline_openfoam_route_smoke as route_smoke


REPO_ROOT = Path(__file__).resolve().parents[1]
WO006_ROOT = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
)
DEFAULT_OUTPUT_DIR = WO006_ROOT / "cfd_release_v0_hpa_grid_independence_verification"
STABLE_ROUTE_DIR = WO006_ROOT / "cfd_release_v0_true_baseline_solver_stability"
GRID_GATE_DIR = WO006_ROOT / "cfd_release_v0_true_baseline_grid_convergence"
BASE_N_PERIM = 192
CL_DESIGN_TARGET = 1.16853
LATEST_FINE_GENERATOR_SMOKE = {
    "case_id": "fine_te_radial_chord_shift_run",
    "cell_count": 3708800,
    "halfwing_seed_cells": 1854400,
    "n_perim": 240,
    "n_radial": 80,
    "span_cells": 95,
    "wake_cross_cells": 4,
    "te_normal_blend_points": 1,
    "first_layer_height_m": 5.0e-5,
    "open_cells": 0,
    "negative_volume_cells": 0,
    "max_cell_openness": 4.98214e-14,
    "min_volume_m3": 7.77078e-10,
    "max_non_ortho_deg": 87.516,
    "max_skew": 3.46221,
    "wrong_oriented_faces": 0,
    "failed_checks": 1,
    "strict_checkmesh_clean": False,
    "solver_status": "runaway_guard_triggered_at_pseudo_time_1",
    "remaining_blocker": "strict C/M/F family gate not passed; Fine has inherited determinant/twist warning and no stable force window",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--stable-route-dir", type=Path, default=STABLE_ROUTE_DIR)
    parser.add_argument("--grid-gate-dir", type=Path, default=GRID_GATE_DIR)
    args = parser.parse_args()

    stable_route = load_stable_route_summary(args.stable_route_dir)
    grid_gate = load_grid_gate_summary(args.grid_gate_dir)
    write_hpa_verification_scaffold(args.output_dir, stable_route=stable_route, grid_gate=grid_gate)
    print(json.dumps(build_grid_independence_verdict(stable_route=stable_route, grid_gate=grid_gate), indent=2))


def current_openfoam_operating_basis() -> dict[str, Any]:
    rho = route_smoke.AIR_DENSITY
    nu = route_smoke.KINEMATIC_VISCOSITY
    chord_reynolds = _current_chord_reynolds_range(nu=nu)
    return {
        "basis_id": "recent_successful_openfoam_fullwing_mirror",
        "role": "current_cfd_verification_basis",
        "source_commit": "fe73939a",
        "route_artifact": str(STABLE_ROUTE_DIR),
        "rho_kg_m3": rho,
        "velocity_mps": route_smoke.VELOCITY_MPS,
        "kinematic_viscosity_m2_s": nu,
        "dynamic_viscosity_pa_s": rho * nu,
        "aoa_deg": route_smoke.AOA_DEG,
        "sref_m2": route_smoke.REF_AREA_M2,
        "cref_m": route_smoke.REF_LENGTH_M,
        "cl_design_target": CL_DESIGN_TARGET,
        "chord_min_m": chord_reynolds["chord_min_m"],
        "chord_max_m": chord_reynolds["chord_max_m"],
        "reynolds_min": chord_reynolds["reynolds_min"],
        "reynolds_max": chord_reynolds["reynolds_max"],
        "full_span_m": route_smoke.AUTHORITY_FULL_SPAN_M,
        "half_span_m": route_smoke.AUTHORITY_HALF_SPAN_M,
        "full_or_half_wing": "full-wing mirror route",
        "turbulence_model": "SpalartAllmaras",
        "transition_model": "none",
        "force_definition": "primary = airfoil_upper + airfoil_lower; total includes physical_tip_left/right and te_wall",
        "do_not_revert_to_original_screening_basis": True,
    }


def original_screening_basis_comparison() -> dict[str, Any]:
    return {
        "basis_id": "historical_avl_tier2_screening_comparison",
        "role": "comparison_only_not_cfd_verification_basis",
        "source": "tier2_loaded_shape_selected_avl_recheck.csv conservative_best row",
        "rho_kg_m3": 1.18,
        "velocity_mps": 6.6,
        "dynamic_viscosity_pa_s": 1.7228e-5,
        "aoa_deg": 0.18015,
        "cl_design": 1.16853,
        "cd_total_screening": 0.026020030502038057,
        "power_screening_w": 174.60027944116567,
        "must_not_block_recent_openfoam_route": True,
    }


def local_refinement_zone_rows() -> list[dict[str, str]]:
    return [
        {
            "zone_id": "leading_edge",
            "target_spacing": "resolve LE curvature; keep chordwise LE spacing tied to n_perim",
            "growth_rate_target": "<=1.20",
            "coarse_to_medium_ratio": "4/3 linear",
            "medium_to_fine_ratio": "5/4 linear",
            "scaling_rule": "increase perimeter resolution and preserve LE index/cosine clustering",
            "why_hpa_specific": "Low-speed high-CL suction peak and transition/separation sensitivity start at LE.",
        },
        {
            "zone_id": "boundary_layer",
            "target_spacing": "first layer 5e-5 m until y+ evidence supports a change",
            "growth_rate_target": "<=1.20",
            "coarse_to_medium_ratio": "4/3 linear",
            "medium_to_fine_ratio": "5/4 linear",
            "scaling_rule": "increase wall-normal layers while preserving first-layer target and near-wall growth",
            "why_hpa_specific": "Wall-resolved HPA RANS needs y+ mostly below 1-2 on real wing walls.",
        },
        {
            "zone_id": "trailing_edge",
            "target_spacing": "explicit finite-TE/wake C-grid stencil; no open-cell TE regression",
            "growth_rate_target": "<=1.20",
            "coarse_to_medium_ratio": "4/3 linear",
            "medium_to_fine_ratio": "5/4 linear",
            "scaling_rule": "scale n_perim; keep the same finite-TE C-grid and lower-TE radial rebalance logic on every rung",
            "why_hpa_specific": "Low-Re pressure recovery and wake drag are sensitive to TE stencil quality.",
        },
        {
            "zone_id": "near_wake",
            "target_spacing": "streamwise wake cells begin at TE spacing and grow smoothly",
            "growth_rate_target": "<=1.20",
            "coarse_to_medium_ratio": "4/3 linear",
            "medium_to_fine_ratio": "5/4 linear",
            "scaling_rule": "scale radial wake streamwise cells with grid level; do not over-split the finite TE gap cross-wake direction",
            "why_hpa_specific": "Wake momentum thickness is part of drag sanity, not just forceCoeffs output.",
        },
        {
            "zone_id": "downstream_wake",
            "target_spacing": "hold wake length at least 8 chords; refine wake sampling, not only body cells",
            "growth_rate_target": "<=1.25",
            "coarse_to_medium_ratio": "4/3 linear",
            "medium_to_fine_ratio": "5/4 linear",
            "scaling_rule": "preserve wake length and increase downstream sampling planes",
            "why_hpa_specific": "Very low dynamic pressure makes small wake errors meaningful in power estimates.",
        },
        {
            "zone_id": "wing_tip_vortex_region",
            "target_spacing": "physical tip patch and vortex core refinement must remain physical, not symmetry-only",
            "growth_rate_target": "<=1.20",
            "coarse_to_medium_ratio": "4/3 linear",
            "medium_to_fine_ratio": "5/4 linear",
            "scaling_rule": "scale tip-local span cells and vortex-core sampling with the same grid family",
            "why_hpa_specific": "Tip vortex behavior is a major induced-drag and wake-structure check at high span.",
        },
        {
            "zone_id": "farfield",
            "target_spacing": "keep current farfield at 10 chords minimum unless domain study says otherwise",
            "growth_rate_target": "<=1.30",
            "coarse_to_medium_ratio": "4/3 linear",
            "medium_to_fine_ratio": "5/4 linear",
            "scaling_rule": "do not shrink domain; refine only to maintain smooth transition from near field",
            "why_hpa_specific": "Small force coefficients are sensitive to blockage and artificial boundary effects.",
        },
    ]


def build_grid_independence_verdict(
    *,
    stable_route: Mapping[str, Any],
    grid_gate: Mapping[str, Any],
) -> dict[str, Any]:
    demonstrated = grid_gate.get("study_status") == "grid_independent_demonstrated"
    blockers = list(grid_gate.get("blocking_items", []))
    return {
        "latest_route_smoke_success": bool(stable_route.get("accepted_stable_route_smoke")),
        "grid_independence_demonstrated": demonstrated,
        "can_trust_cd_approx_0p0315": demonstrated,
        "can_update_design_power_from_174w": demonstrated,
        "cd_medium_to_fine_rule": "CD Medium->Fine must be <=3%; >5% means drag is not reliable.",
        "max_abs_cd_percent_change": grid_gate.get("max_abs_cd_percent_change"),
        "exact_blockers": blockers,
        "engineering_read": (
            "The latest route-smoke is successful, but grid independence is not demonstrated."
            if not demonstrated
            else "Grid independence is demonstrated inside the documented HPA CFD basis."
        ),
    }


def write_hpa_verification_scaffold(
    output_dir: Path,
    *,
    stable_route: Mapping[str, Any],
    grid_gate: Mapping[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    basis = current_openfoam_operating_basis()
    comparison = original_screening_basis_comparison()
    zones = local_refinement_zone_rows()
    verdict = build_grid_independence_verdict(stable_route=stable_route, grid_gate=grid_gate)

    write_operating_condition_lock(output_dir / "hpa_operating_condition_lock.md", basis, comparison, stable_route)
    write_current_mesh_quality_audit(output_dir / "current_mesh_quality_audit.md", stable_route, grid_gate)
    write_current_mesh_quality_table(output_dir / "current_mesh_quality_table.csv", stable_route, grid_gate)
    write_mesh_strategy(output_dir / "hpa_mesh_strategy.md", basis, zones)
    write_zone_table(output_dir / "local_refinement_zone_table.csv", zones)
    write_mesh_generator_fix_report(output_dir / "mesh_generator_fix_report.md", grid_gate)
    write_final_verdict(output_dir / "final_hpa_grid_independence_verdict.md", basis, stable_route, verdict)
    write_manifest(output_dir / "hpa_cfd_verification_manifest.json", basis, comparison, stable_route, grid_gate, verdict)


def load_stable_route_summary(stable_route_dir: Path) -> dict[str, Any]:
    report = (stable_route_dir / "stable_route_smoke_report.md").read_text(encoding="utf-8")
    yplus = (stable_route_dir / "stable_yplus_report.md").read_text(encoding="utf-8")
    checkmesh = (stable_route_dir / "fullwing_checkmesh_report.md").read_text(encoding="utf-8")
    force_report = (stable_route_dir / "stable_force_breakdown_report.md").read_text(encoding="utf-8")
    return {
        "accepted_stable_route_smoke": _contains_bool(report, "accepted_stable_route_smoke"),
        "CD_primary": _extract_float(report, "CD_primary"),
        "CL_primary": _extract_float(report, "CL_primary"),
        "CD_total": _extract_float(report, "CD_total"),
        "CmPitch": _extract_nested_last_float(report, "CmPitch"),
        "yplus_mean": _extract_nested_last_float(yplus, "mean"),
        "yplus_p90": _extract_nested_last_float(yplus, "p90"),
        "yplus_p95": _extract_nested_last_float(yplus, "p95"),
        "yplus_p99": _extract_nested_last_float(yplus, "p99"),
        "yplus_max": _extract_nested_last_float(yplus, "max"),
        "wall_yplus_by_patch": _extract_yplus_patch_table(yplus),
        "cell_count": _extract_checkmesh_int(checkmesh, "cells"),
        "max_non_ortho": _extract_checkmesh_float(checkmesh, "maxNonOrtho"),
        "max_skew": _extract_checkmesh_float(checkmesh, "maxSkew"),
        "failed_checks": _extract_failed_checks(checkmesh),
        "force_window_stable": "route_smoke_stable': True" in report or "route_smoke_stable`" in report,
        "pressure_viscous_available": "CD_primary" in force_report,
    }


def load_grid_gate_summary(grid_gate_dir: Path) -> dict[str, Any]:
    manifest_path = grid_gate_dir / "grid_convergence_manifest.json"
    if not manifest_path.exists():
        return {
            "study_status": "grid_independence_not_demonstrated",
            "blocking_items": ["grid_convergence_manifest_missing"],
            "max_abs_cd_percent_change": None,
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verdict = dict(manifest.get("verdict", {}))
    verdict["rung_cell_counts"] = {
        rung["spec"]["case_id"]: rung.get("checkMesh_acceptance", {}).get("metrics", {}).get("cells")
        for rung in manifest.get("rungs", [])
    }
    return verdict


def write_operating_condition_lock(path: Path, basis: Mapping[str, Any], comparison: Mapping[str, Any], stable_route: Mapping[str, Any]) -> None:
    lines = [
        "# HPA Operating Condition Lock",
        "",
        "Verdict: `current_openfoam_basis_locked_for_hpa_verification`",
        "",
        "This supersedes the earlier Phase 0 hard-stop wording. The current CFD",
        "verification basis is the recent successful OpenFOAM full-wing mirror route,",
        "not the older AVL/Tier2 screening drag-power basis.",
        "",
        "## Current CFD Basis",
        "",
        f"- source commit: `{basis['source_commit']}`",
        f"- rho: `{basis['rho_kg_m3']} kg/m^3`",
        f"- viscosity: `nu={basis['kinematic_viscosity_m2_s']} m^2/s`, `mu={basis['dynamic_viscosity_pa_s']:.8g} Pa*s`",
        f"- V: `{basis['velocity_mps']} m/s`",
        f"- AoA: `{basis['aoa_deg']} deg`",
        f"- Sref: `{basis['sref_m2']} m^2`",
        f"- Cref: `{basis['cref_m']} m`",
        f"- CL_design target: `{basis['cl_design_target']}`",
        f"- chord range: `{basis['chord_min_m']:.6f}..{basis['chord_max_m']:.6f} m`",
        f"- Re range along span: `{basis['reynolds_min']:.0f}..{basis['reynolds_max']:.0f}`",
        f"- full-wing / half-wing convention: `{basis['full_or_half_wing']}`",
        f"- turbulence / transition model: `{basis['turbulence_model']}`, no transition model",
        f"- force definitions: `{basis['force_definition']}`",
        f"- stable route-smoke CL/CD: `CL_primary={stable_route.get('CL_primary')}`, `CD_primary={stable_route.get('CD_primary')}`",
        "",
        "## Historical Comparison Basis",
        "",
        f"The old `rho=1.18/V=6.6` basis remains historical comparison only: `CL_design={comparison['cl_design']}`,",
        f"`CD_total={comparison['cd_total_screening']}`, `P_crank={comparison['power_screening_w']} W`.",
        "The difference is documented, but it does not hard-stop the current OpenFOAM route because",
        "the latest instruction is to continue from the recent successful commits. Do not return to",
        "`rho=1.18/V=6.6` as a hard stop unless the user explicitly asks for a new",
        "screening-basis sensitivity study.",
        "",
        "## Engineering Caveat",
        "",
        "Fully turbulent Spalart-Allmaras is acceptable as the current route-smoke and",
        "grid-family basis because that is what recently stabilized. It is not final",
        "low-Re HPA transition truth. Any final drag claim still needs Cp, Cf, wake,",
        "tip-vortex, and transition/separation behavior checks.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_current_mesh_quality_audit(path: Path, stable_route: Mapping[str, Any], grid_gate: Mapping[str, Any]) -> None:
    wall_yplus_by_patch = stable_route.get("wall_yplus_by_patch") or {}
    lines = [
        "# Current Mesh Quality Audit",
        "",
        "Verdict: `route_smoke_mesh_accepted_but_grid_family_not_validated`",
        "",
        "The latest successful full-wing mirror route is the current audit baseline.",
        "It is not a final grid-independent family.",
        "",
        "## Accepted Route-Smoke Mesh",
        "",
        f"- cell count: `{stable_route.get('cell_count')}`",
        f"- combined y+ mean / p90 / p95 / p99 / max on real airfoil walls: `{stable_route.get('yplus_mean')}` / `{stable_route.get('yplus_p90')}` / `{stable_route.get('yplus_p95')}` / `{stable_route.get('yplus_p99')}` / `{stable_route.get('yplus_max')}`",
        "- first layer height: `5e-5 m` from the current swept C-grid generator",
        "- BL layer count: represented by the `n_radial=64` near-wall C-grid stack; current generator still needs explicit BL-layer-count metadata for final Phase 1 closure",
        "- BL total thickness: not yet reported as an explicit scalar; must be added before final Phase 1 closure",
        "- wall-normal growth rate: current generator default is `1.12`, within the preferred `<=1.2` target",
        "- surface spacing near LE/TE: tied to the `n_perim=192` C-grid, but exact LE/TE spacing scalars are not yet exported",
        "- wake resolution: current topology has an `8 chord` wake length; explicit wake sampling and profile comparisons are still missing",
        "- tip vortex resolution: side patches exist, but physical tip-vortex core diagnostics are still missing",
        "- farfield distance: current C-grid uses `10 chords`; final workflow still needs a domain-effect check if forces remain sensitive",
        f"- max non-orthogonality: `{stable_route.get('max_non_ortho')}`",
        f"- max skew: `{stable_route.get('max_skew')}`",
        f"- strict checkMesh failed checks: `{stable_route.get('failed_checks')}`",
    ]
    if wall_yplus_by_patch:
        lines.extend(["", "## Real-Wall y+ Split", ""])
        for patch_name in ("airfoil_upper", "airfoil_lower"):
            stats = wall_yplus_by_patch.get(patch_name)
            if not stats:
                continue
            lines.append(
                f"- `{patch_name}` y+ mean / p90 / p95 / p99 / max: "
                f"`{stats.get('mean')}` / `{stats.get('p90')}` / `{stats.get('p95')}` / "
                f"`{stats.get('p99')}` / `{stats.get('max')}`"
            )
        for patch_name in ("physical_tip_left", "physical_tip_right"):
            stats = wall_yplus_by_patch.get(patch_name)
            if not stats:
                continue
            lines.append(
                f"- `{patch_name}` diagnostic y+ max is `{stats.get('max')}`; this is not accepted as a physical tip-wall/tip-vortex sign-off."
            )
    else:
        lines.extend(
            [
                "",
                "## Real-Wall y+ Split",
                "",
                "- upper/lower wall split was not exported in the provided summary; final Phase 1 closure must include it.",
            ]
        )
    lines.extend(
        [
            "",
            "## Grid-Family Gate",
            "",
            f"- current grid-gate status: `{grid_gate.get('study_status')}`",
            f"- blockers: `{grid_gate.get('blocking_items')}`",
            f"- max CD change seen so far: `{grid_gate.get('max_abs_cd_percent_change')}%`",
            "",
            "The previous systematic ladder is useful because it proved the route still",
            "breaks under refinement. It cannot be treated as a passed grid study.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_current_mesh_quality_table(path: Path, stable_route: Mapping[str, Any], grid_gate: Mapping[str, Any]) -> None:
    rows = [
        {
            "case_id": "latest_successful_fullwing_mirror",
            "wall_patch": "primary_real_airfoil_walls",
            "cell_count": stable_route.get("cell_count"),
            "status": "route_smoke_success_not_grid_independent",
            "yplus_mean": stable_route.get("yplus_mean"),
            "yplus_p90": stable_route.get("yplus_p90"),
            "yplus_p95": stable_route.get("yplus_p95"),
            "yplus_p99": stable_route.get("yplus_p99"),
            "yplus_max": stable_route.get("yplus_max"),
            "first_layer_height_m": 5.0e-5,
            "wall_normal_growth_rate": 1.12,
            "max_non_ortho": stable_route.get("max_non_ortho"),
            "max_skew": stable_route.get("max_skew"),
            "failed_checks": stable_route.get("failed_checks"),
            "force_history_stable": stable_route.get("force_window_stable"),
            "notes": "Recent successful route from fe73939a; use as current CFD basis.",
        },
        {
            "case_id": "previous_systematic_grid_gate",
            "wall_patch": "",
            "cell_count": grid_gate.get("rung_cell_counts", {}),
            "status": grid_gate.get("study_status"),
            "yplus_mean": "",
            "yplus_p90": "",
            "yplus_p95": "",
            "yplus_p99": "",
            "yplus_max": "",
            "first_layer_height_m": 5.0e-5,
            "wall_normal_growth_rate": 1.12,
            "max_non_ortho": "",
            "max_skew": "",
            "failed_checks": "",
            "force_history_stable": False,
            "notes": f"Blocked by {grid_gate.get('blocking_items')}; proves no grid independence yet.",
        },
    ]
    for patch_name, stats in (stable_route.get("wall_yplus_by_patch") or {}).items():
        if patch_name not in {"airfoil_upper", "airfoil_lower"}:
            continue
        rows.append(
            {
                "case_id": "latest_successful_fullwing_mirror",
                "wall_patch": patch_name,
                "cell_count": "",
                "status": "wall_patch_yplus",
                "yplus_mean": stats.get("mean"),
                "yplus_p90": stats.get("p90"),
                "yplus_p95": stats.get("p95"),
                "yplus_p99": stats.get("p99"),
                "yplus_max": stats.get("max"),
                "first_layer_height_m": 5.0e-5,
                "wall_normal_growth_rate": 1.12,
                "max_non_ortho": "",
                "max_skew": "",
                "failed_checks": "",
                "force_history_stable": "",
                "notes": "Patch-level y+ split from stable_yplus_report.md.",
            }
        )
    _write_csv(path, rows)


def write_mesh_strategy(path: Path, basis: Mapping[str, Any], zones: Sequence[Mapping[str, str]]) -> None:
    lines = [
        "# HPA Mesh Strategy",
        "",
        "Verdict: `strategy_defined_for_recent_openfoam_basis`",
        "",
        f"Use `{basis['basis_id']}` as the CFD basis. Do not restart from the old",
        "`rho=1.18/V=6.6` screening basis unless explicitly asked.",
        "",
        "The next mesh-family generator fix must preserve one topology family and",
        "scale local HPA physics zones. Uniformly increasing cells is not accepted.",
        "",
        "## Local Zones",
        "",
        "| zone | target spacing | growth | scaling | HPA reason |",
        "|---|---|---|---|---|",
    ]
    for row in zones:
        lines.append(
            f"| `{row['zone_id']}` | {row['target_spacing']} | `{row['growth_rate_target']}` | "
            f"{row['coarse_to_medium_ratio']} then {row['medium_to_fine_ratio']} | {row['why_hpa_specific']} |"
        )
    lines.extend(
        [
            "",
            "## Generator Fix Requirements",
            "",
            "- Keep the successful full-wing mirror route as the starting point.",
            "- Fix high-resolution TE stencil/open-cell regression before running Fine.",
            "- Keep TE gap cross-wake cells bounded until a proper lower-TE H-block/sleeve removes face-pyramid errors.",
            "- Replace artificial tip-only convergence claims with physical tip-vortex diagnostics.",
            "- Add explicit BL layer count and total-thickness metadata.",
            "- Export Cp/Cf/wake/tip-vortex comparison surfaces for every grid.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_zone_table(path: Path, zones: Sequence[Mapping[str, str]]) -> None:
    _write_csv(path, zones)


def write_mesh_generator_fix_report(path: Path, grid_gate: Mapping[str, Any]) -> None:
    smoke = LATEST_FINE_GENERATOR_SMOKE
    lines = [
        "# Mesh Generator Fix Report",
        "",
        "Verdict: `lower_te_blocker_removed_but_family_gate_not_passed`",
        "",
        "The high-resolution TE/open-cell failure and the later lower-TE wrong-oriented",
        "face-pyramid blocker are no longer the active blockers. The current swept",
        "C-grid generator fixes the lower-TE body/wake sliver at source by a local",
        "radial wall-layer rebalance; no polyMesh surgery is used.",
        "",
        "This still is not a completed grid-family generator. The Fine mesh is not",
        "strict-clean because inherited determinant/twist `meshQuality` warnings remain,",
        "and its solver smoke tripped the force-runaway guard at pseudo-time 1.",
        "",
        "## Latest Fine Generator Smoke",
        "",
        f"- smoke case: `{smoke['case_id']}`",
        f"- full-wing cells: `{smoke['cell_count']}`",
        f"- half-wing seed cells: `{smoke['halfwing_seed_cells']}`",
        f"- n_perim / n_radial / span cells: `{smoke['n_perim']}` / `{smoke['n_radial']}` / `{smoke['span_cells']}`",
        f"- wake_cross_cells: `{smoke['wake_cross_cells']}`",
        f"- TE normal blend points: `{smoke['te_normal_blend_points']}`",
        f"- first layer height: `{smoke['first_layer_height_m']} m`",
        f"- open cells: `{smoke['open_cells']}`",
        f"- negative volume cells: `{smoke['negative_volume_cells']}`",
        f"- max cell openness: `{smoke['max_cell_openness']}`",
        f"- min volume: `{smoke['min_volume_m3']} m^3`",
        f"- max non-orthogonality: `{smoke['max_non_ortho_deg']} deg`",
        f"- max skew: `{smoke['max_skew']}`",
        f"- wrong-oriented face pyramids: `{smoke['wrong_oriented_faces']}`",
        f"- failed checks: `{smoke['failed_checks']}`",
        f"- strict checkMesh clean: `{smoke['strict_checkmesh_clean']}`",
        f"- solver status: `{smoke['solver_status']}`",
        f"- remaining blocker: `{smoke['remaining_blocker']}`",
        "",
        "Engineering read: do not send future agents back to the old open-cell or",
        "100 wrong-oriented-face diagnosis as if it were still current. The active",
        "task is a robust same-family Coarse/Medium/Fine generator with strict",
        "family-level checkMesh gating before solver launch.",
        "",
        "## Previous Grid Gate Evidence",
        "",
        f"- grid-gate status: `{grid_gate.get('study_status')}`",
        f"- blocking items: `{grid_gate.get('blocking_items')}`",
        f"- rung cell counts: `{grid_gate.get('rung_cell_counts')}`",
        f"- max CD change observed before failure: `{grid_gate.get('max_abs_cd_percent_change')}%`",
        "",
        "## Required Generator Fixes",
        "",
        "- Preserve the lower-TE generator-level rebalance and keep wrong-oriented face pyramids at zero across Coarse/Medium/Fine.",
        "- Preserve one topology family across Coarse/Medium/Fine; do not use 2.00M and 2.22M as the final family.",
        "- Export explicit LE spacing, TE spacing, BL layer count, BL total thickness, and wall-normal growth metadata.",
        "- Add wake refinement controls for near wake and downstream wake sampling planes.",
        "- Add physical tip/tip-vortex refinement controls rather than relying on artificial side-patch diagnostics.",
        "- Keep first-layer height and y+ checks tied to upper/lower real airfoil walls.",
        "- Add Cp, Cf, wake-profile, and tip-vortex extraction hooks for every grid level.",
        "",
        "## Stop Rule",
        "",
        "If any rung is not strict `checkMesh -meshQuality` clean, produces open cells,",
        "negative volumes, or wrong-oriented face pyramids, the solver phase must not",
        "start. If any solver run cannot reach a stable force window, grid independence",
        "remains not demonstrated and design power must not be updated.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_final_verdict(path: Path, basis: Mapping[str, Any], stable_route: Mapping[str, Any], verdict: Mapping[str, Any]) -> None:
    smoke = LATEST_FINE_GENERATOR_SMOKE
    lines = [
        "# Final HPA Grid-Independence Verdict",
        "",
        "Verdict: `grid_independence_not_demonstrated_yet`",
        "",
        "The latest route-smoke is successful, but grid independence is not demonstrated.",
        "",
        "## Required Answers",
        "",
        f"1. Operating conditions: current CFD basis is `{basis['basis_id']}` with `rho={basis['rho_kg_m3']}`, `V={basis['velocity_mps']}`.",
        f"2. y+ acceptable on latest successful route: yes on upper/lower real airfoil walls (`mean={stable_route.get('yplus_mean')}`, `p95={stable_route.get('yplus_p95')}`, `max={stable_route.get('yplus_max')}`), but not a final all-wall/tip-vortex sign-off.",
        "3. BL layer count/growth: growth is acceptable by generator default, but explicit layer count and total thickness must be documented before final sign-off.",
        f"4. LE / TE / wake / tip refinement: TE open-cell and wrong-oriented-face blockers are repaired in `{smoke['case_id']}`, but wake/tip diagnostics are not yet compared across a passed C/M/F family.",
        "5. Same mesh strategy: not yet proven by a strict-clean Coarse/Medium/Fine run.",
        f"6. checkMesh: latest route-smoke passes solver-smoke gate; repaired Fine has no open/negative/wrong-oriented cells but still fails `{smoke['failed_checks']}` strict meshQuality check.",
        f"7. force histories: latest route-smoke stable; repaired Fine solver status is `{smoke['solver_status']}`.",
        "8. CL/CD/Cm grid independence: not demonstrated.",
        "9. Cp/Cf stability: not yet compared.",
        "10. Wake/tip vortex stability: not yet compared.",
        "11. Can CD around 0.0315 be trusted: no, not for design power.",
        "12. Can design power be updated from 174W: no. Do not update design power.",
        f"13. Exact blocker: `{smoke['remaining_blocker']}` plus missing strict-clean C/M/F checkMesh reports, stable force histories, and Cp/Cf/wake/tip comparisons.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest(
    path: Path,
    basis: Mapping[str, Any],
    comparison: Mapping[str, Any],
    stable_route: Mapping[str, Any],
    grid_gate: Mapping[str, Any],
    verdict: Mapping[str, Any],
) -> None:
    payload = {
        "schema_version": "wo006_hpa_cfd_verification_scaffold.v1",
        "current_openfoam_basis": basis,
        "historical_screening_comparison": comparison,
        "stable_route": dict(stable_route),
        "grid_gate": dict(grid_gate),
        "verdict": dict(verdict),
        "outputs": [
            "hpa_operating_condition_lock.md",
            "current_mesh_quality_audit.md",
            "current_mesh_quality_table.csv",
            "hpa_mesh_strategy.md",
            "local_refinement_zone_table.csv",
            "mesh_generator_fix_report.md",
            "final_hpa_grid_independence_verdict.md",
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _current_chord_reynolds_range(*, nu: float) -> dict[str, float]:
    authority = load_baseline_authority(
        n_perim=BASE_N_PERIM,
        airfoil_loop_mode="open_te_cgrid",
    )
    chords = [station.chord for station in authority.half_stations]
    chord_min = min(chords)
    chord_max = max(chords)
    return {
        "chord_min_m": chord_min,
        "chord_max_m": chord_max,
        "reynolds_min": route_smoke.VELOCITY_MPS * chord_min / nu,
        "reynolds_max": route_smoke.VELOCITY_MPS * chord_max / nu,
    }


def _extract_yplus_patch_table(text: str) -> dict[str, dict[str, float | int]]:
    pattern = re.compile(
        r"\|\s*`([^`]+)`\s*\|\s*`?([-+0-9.eE]+)`?\s*\|\s*`?([-+0-9.eE]+)`?"
        r"\s*\|\s*`?([-+0-9.eE]+)`?\s*\|\s*`?([-+0-9.eE]+)`?\s*\|"
        r"\s*`?([-+0-9.eE]+)`?\s*\|\s*`?([0-9]+)`?\s*\|"
    )
    rows: dict[str, dict[str, float | int]] = {}
    for match in pattern.finditer(text):
        patch, mean, p90, p95, p99, max_value, count = match.groups()
        rows[patch] = {
            "mean": float(mean),
            "p90": float(p90),
            "p95": float(p95),
            "p99": float(p99),
            "max": float(max_value),
            "count": int(count),
        }
    return rows


def _extract_float(text: str, label: str) -> float | None:
    match = re.search(rf"{re.escape(label)}:\s*`?([-+0-9.eE]+)`?", text)
    return None if match is None else float(match.group(1))


def _extract_nested_last_float(text: str, label: str) -> float | None:
    matches = re.findall(rf"['\"]?{re.escape(label)}['\"]?:\s*([-+0-9.eE]+)", text)
    return None if not matches else float(matches[-1])


def _extract_checkmesh_float(text: str, key: str) -> float | None:
    match = re.search(rf"['\"]?{re.escape(key)}['\"]?:\s*([-+0-9.eE]+)", text)
    return None if match is None else float(match.group(1))


def _extract_checkmesh_int(text: str, key: str) -> int | None:
    value = _extract_checkmesh_float(text, key)
    return None if value is None else int(value)


def _extract_failed_checks(text: str) -> int | None:
    match = re.search(r"Failed\s+([0-9]+)\s+mesh checks", text)
    if match:
        return int(match.group(1))
    return _extract_checkmesh_int(text, "failedChecks")


def _contains_bool(text: str, label: str) -> bool:
    match = re.search(rf"{re.escape(label)}:\s*`?(True|False|true|false)`?", text)
    return bool(match and match.group(1).lower() == "true")


if __name__ == "__main__":
    main()
