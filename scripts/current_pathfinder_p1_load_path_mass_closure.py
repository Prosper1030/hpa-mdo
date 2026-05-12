#!/usr/bin/env python3
"""P1 local load-path closure plus mass-integrated pathfinder update.

This runner consumes the current P1 y=2.328 m local-detail inputs, the C04
saddle-ring/yoke fix model, the 3 m spar-splice package, and the latest
calibrated tail-aware closure artifact. It produces a single machine-readable
verdict for the structural blocker:

  - p1_local_load_path_ready_for_coupon_fem
  - c04_fix_not_geometry_feasible
  - pathfinder_mass_cg_needs_reclosure
  - fast_model_no_longer_trustworthy_needs_recalibration

The output is still a local surrogate / screening closure update, not final
aircraft sign-off.
"""

from __future__ import annotations

import argparse
import copy
import csv
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.collar_joint_modes import JointLoad, recommended_c04_fix  # noqa: E402
from scripts.current_pathfinder_rib_local_detail_margin_run import (  # noqa: E402
    _compute_c04_peel_refined,
)
from scripts.tail_aware_aeroelastic_closure import (  # noqa: E402
    READY_VERDICT,
    classify_aeroelastic_closure,
)
from scripts.tail_aware_rib_rear_spar_sensitivity import (  # noqa: E402
    MassItem,
    assess_mass_cg_coupling,
)


SCHEMA_VERSION = "p1_load_path_mass_closure_v1"

VERDICT_READY = "p1_local_load_path_ready_for_coupon_fem"
VERDICT_C04_NOT_FEASIBLE = "c04_fix_not_geometry_feasible"
VERDICT_MASS_CG_RECLOSURE = "pathfinder_mass_cg_needs_reclosure"
VERDICT_FAST_MODEL_RECALIBRATION = "fast_model_no_longer_trustworthy_needs_recalibration"

DEFAULT_FREEZE_JSON = (
    REPO_ROOT / "output" / "current_pathfinder_rib_local_detail_geometry_freeze"
    / "geometry_allowable_freeze.json"
)
DEFAULT_SPLICE_JSON = (
    REPO_ROOT / "output" / "current_pathfinder_spar_splice_design"
    / "splice_design_report.json"
)
DEFAULT_SOURCE_CLOSURE_JSON = (
    REPO_ROOT / "output" / "current_pathfinder_rib_torsion_design_search"
    / "selected_fast_candidate_closure_rerun.json"
)
DEFAULT_FAST_CALIBRATION_JSON = (
    REPO_ROOT / "docs" / "reports"
    / "2026-05-09_current_pathfinder_rib_torsion_fem_calibration.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "current_pathfinder_p1_load_path_mass_closure"
DEFAULT_REPORT_JSON = (
    REPO_ROOT / "docs" / "reports"
    / "2026-05-12_current_pathfinder_p1_load_path_mass_closure.json"
)
DEFAULT_REPORT_MD = (
    REPO_ROOT / "docs" / "reports"
    / "2026-05-12_current_pathfinder_p1_load_path_mass_closure.md"
)


def build_p1_load_path_mass_closure(
    *,
    freeze_json: Path = DEFAULT_FREEZE_JSON,
    splice_json: Path = DEFAULT_SPLICE_JSON,
    source_closure_json: Path = DEFAULT_SOURCE_CLOSURE_JSON,
    fast_calibration_json: Path = DEFAULT_FAST_CALIBRATION_JSON,
) -> dict[str, Any]:
    freeze = _read_json(freeze_json)
    splice = _read_json(splice_json)
    source_closure = _read_json(source_closure_json)
    fast_calibration = _read_json(fast_calibration_json)

    fast_status = _mapping_at(fast_calibration, "calibration_decision").get("status")
    local = _local_load_path_summary(freeze)
    source_basis_json = Path(
        _mapping_at(source_closure, "artifact_manifest").get("selected_basis_json", "")
    )
    if not source_basis_json.exists():
        source_basis_json = (
            REPO_ROOT / "output" / "current_pathfinder_rib_torsion_rework_verdict"
            / "selected_basis_for_tail_aware_closure_rerun.json"
        )
    selected_payload = _read_json(source_basis_json)
    selected_basis = _mapping_at(selected_payload, "selected_basis")

    twist_csv = Path(
        _mapping_at(source_closure, "artifact_manifest").get("final_twist_source_audit_csv", "")
    )
    c04_mass = _estimate_c04_fix_mass(freeze)
    c04_x = _nearest_elastic_axis_x(twist_csv, float(freeze["torque_critical_y_m"]))
    splice_mass_kg = float(splice["total_splice_mass_full_wing_kg"])
    splice_x = _weighted_splice_x(splice, twist_csv)

    added_items = [
        MassItem(
            "p1_c04_saddle_ring_yoke_clamp_pair",
            c04_mass["full_wing_mass_kg"],
            c04_x,
        ),
        MassItem("spar_splice_transport_joint_pack", splice_mass_kg, splice_x),
    ]
    mass_update = _mass_integration_update(
        selected_basis=selected_basis,
        source_closure=source_closure,
        added_items=added_items,
        c04_mass=c04_mass,
        splice=splice,
    )
    closure_update = _mass_adjusted_closure_update(
        source_closure=source_closure,
        selected_basis=selected_basis,
        updated_cg=mass_update["updated_cg_management"],
        updated_mass_drag_power=mass_update["updated_mass_drag_power"],
        mass_scale=mass_update["mass_scale_vs_source_closure"],
    )

    final_verdict = _final_verdict(
        fast_status=str(fast_status),
        local_load_path=local,
        updated_closure=closure_update,
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": freeze["candidate_id"],
        "source_closure_artifact": str(source_closure_json),
        "fast_model_calibration": {
            "status": fast_status,
            "primary_solver": _mapping_at(fast_calibration, "calibration_decision").get(
                "primary_solver"
            ),
            "structural_candidate_max_revised_factor_error_pct": _mapping_at(
                fast_calibration,
                "calibration_decision",
            ).get("structural_candidate_max_revised_factor_error_pct"),
            "claim_boundary": fast_calibration.get("claim_boundary"),
        },
        "local_load_path": local,
        "mass_integration": mass_update["summary"],
        "mass_cg_tail_closure": closure_update,
        "propulsion_lane_policy": {
            "qprop_xrotor_role": "independent_propulsion_lane_only",
            "used_in_structural_blocker_verdict": False,
            "engineering_read": (
                "QPROP/XROTOR outputs may size propulsion separately, but they are "
                "not used to pass or fail the P1 C04 structural load-path blocker."
            ),
        },
        "final_verdict": final_verdict,
        "claim_boundary": (
            "Local load-path surrogate plus mass-integrated screening closure. "
            "Ready verdict means the P1 C04 fix may proceed to coupon/local FEM; "
            "it is not final adhesive, laminate, buckling, tail hardware, or "
            "flight-aircraft sign-off."
        ),
    }
    return summary


def _local_load_path_summary(freeze: Mapping[str, Any]) -> dict[str, Any]:
    load_factor = float(freeze["load_factor"])
    baseline = _compute_c04_peel_refined(dict(freeze), load_factor)
    load = JointLoad.from_freeze(dict(freeze))
    fix = recommended_c04_fix(load)
    fix_result = fix.margin(load)
    sub_results = fix_result.detail.get("sub_results", {})
    saddle = sub_results.get("saddle_ring_yoke", {})
    clamp = sub_results.get("friction_clamp", {})
    passes = bool(fix_result.passes and fix_result.margin > 0.0)
    return {
        "station_id": "R068",
        "station_y_m": float(freeze["torque_critical_y_m"]),
        "design_force_n": load.F_n,
        "required_torque_nm": load.M_req_nm,
        "baseline_c04_margin": baseline["C04_margin"],
        "baseline_c04_theoretical_min_margin": baseline["c04_theoretical_min_margin"],
        "baseline_c04_status": "fail_current_eccentric_peel_path",
        "installed_fix_type": "saddle_ring_yoke_plus_secondary_clamp",
        "installed_fix_governing_margin": fix_result.margin,
        "installed_fix_governing_mode": fix_result.governs,
        "installed_fix_sub_results": sub_results,
        "saddle_ring_yoke_margin": saddle.get("margin"),
        "friction_clamp_secondary_margin": clamp.get("margin"),
        "c04_status": (
            "pass_with_saddle_ring_yoke_fix" if passes else "fail_after_saddle_ring_yoke_fix"
        ),
        "local_surrogate_kind": "class_based_saddle_ring_yoke_friction_clamp_surrogate",
        "claim_boundary": (
            "local_surrogate_ready_for_coupon_and_local_fem"
            if passes else "local_surrogate_failed_geometry_screen"
        ),
        "engineering_read": (
            "The current C04 peel-bond path fails because the load line is eccentric. "
            "The selected fix changes the load path to tangential lug bearing into a "
            "conformal saddle ring, with the clamp treated as secondary retention."
        ),
    }


def _estimate_c04_fix_mass(freeze: Mapping[str, Any]) -> dict[str, Any]:
    load = JointLoad.from_freeze(dict(freeze))
    fix = recommended_c04_fix(load)
    modes = {mode.mode_id: mode for mode in fix.modes}
    saddle = modes["saddle_ring_yoke"]
    clamp = modes["friction_clamp"]
    materials = _mapping_at(freeze, "materials_summary")
    ring_density = float(_mapping_at(materials, "eglass_woven").get("density", 1850.0))
    clamp_density = float(_mapping_at(materials, "cfrp_ply_sm").get("density", 1550.0))

    ring_thickness_m = 0.0012
    clamp_shell_thickness_m = 0.0010
    overwrap_adhesive_factor = 1.35
    bolt_count = 2
    bolt_mass_each_kg = 0.006
    liner_mass_kg = 0.002
    adhesive_fillet_mass_kg = 0.004

    ring_volume = saddle.arc_angle_rad * load.R_m * saddle.ring_width_m * ring_thickness_m
    lug_volume = (
        2.0 * saddle.lug_height_m * saddle.lug_width_m * saddle.lug_foot_length_m
    )
    saddle_mass_kg = (ring_volume + lug_volume) * ring_density * overwrap_adhesive_factor
    clamp_volume = clamp.contact_arc_rad * load.R_m * saddle.ring_width_m * clamp_shell_thickness_m
    clamp_mass_kg = clamp_volume * clamp_density + bolt_count * bolt_mass_each_kg + liner_mass_kg
    per_station_mass_kg = saddle_mass_kg + clamp_mass_kg + adhesive_fillet_mass_kg
    full_wing_mass_kg = 2.0 * per_station_mass_kg
    return {
        "basis": "two symmetric P1 saddle-ring/yoke + secondary clamp assemblies",
        "station_count_full_wing": 2,
        "per_station_mass_kg": round(per_station_mass_kg, 6),
        "full_wing_mass_kg": round(full_wing_mass_kg, 6),
        "saddle_ring_mass_per_station_kg": round(saddle_mass_kg, 6),
        "clamp_mass_per_station_kg": round(clamp_mass_kg, 6),
        "adhesive_fillet_mass_per_station_kg": adhesive_fillet_mass_kg,
        "ring_thickness_m": ring_thickness_m,
        "clamp_shell_thickness_m": clamp_shell_thickness_m,
        "ring_density_kgpm3": ring_density,
        "clamp_density_kgpm3": clamp_density,
        "secondary_clamp_force_n": clamp.N_c_n,
    }


def _mass_integration_update(
    *,
    selected_basis: Mapping[str, Any],
    source_closure: Mapping[str, Any],
    added_items: Sequence[MassItem],
    c04_mass: Mapping[str, Any],
    splice: Mapping[str, Any],
) -> dict[str, Any]:
    cg = _mapping_at(selected_basis, "cg_impact")
    existing_items = [
        MassItem(
            str(item["name"]),
            float(item["mass_kg"]),
            float(item["x_m"]),
        )
        for item in cg.get("mass_items", [])
    ]
    old_total = float(
        cg.get(
            "total_mass_after_items_kg",
            float(cg.get("base_mass_kg", 0.0)) + sum(item.mass_kg for item in existing_items),
        )
    )
    updated_cg = assess_mass_cg_coupling(
        base_mass_kg=float(cg["base_mass_kg"]),
        base_cg_x_m=float(cg["base_cg_x_m"]),
        cg_range_x_m=tuple(float(v) for v in cg["cg_range_x_m"]),
        final_screening_cg_x_m=float(cg["final_screening_cg_x_m"]),
        mass_items=tuple(existing_items) + tuple(added_items),
        forward_rebalance_mass_kg=float(cg.get("forward_rebalance_mass_kg", 56.0)),
        forward_rebalance_limit_m=float(cg.get("forward_rebalance_limit_m", 0.20)),
    )
    _add_cg_gate_status(updated_cg)
    new_total = float(updated_cg["total_mass_after_items_kg"])
    source_mass = _mapping_at(source_closure, "basis", "mass_drag_power")
    additional = {
        "p1_c04_fix_full_wing": c04_mass["full_wing_mass_kg"],
        "spar_splice_full_wing": float(splice["total_splice_mass_full_wing_kg"]),
    }
    updated_mass_drag_power = {
        **dict(source_mass),
        "p1_c04_fix_mass_kg": additional["p1_c04_fix_full_wing"],
        "spar_splice_mass_kg": additional["spar_splice_full_wing"],
        "structural_hardware_mass_delta_kg": round(sum(additional.values()), 6),
        "total_screening_mass_after_integrated_items_kg": round(new_total, 6),
        "mass_scale_vs_source_closure": round(new_total / old_total, 6),
        "status": "charged_to_screening_read",
        "engineering_read": (
            "Rib, tail, P1 C04 fix, and 3 m spar-splice masses are all charged "
            "to the pathfinder screening read. This is mass bookkeeping for "
            "closure, not measured aircraft weight."
        ),
    }
    return {
        "updated_cg_management": updated_cg,
        "mass_scale_vs_source_closure": new_total / old_total,
        "additional_masses_kg": additional,
        "updated_mass_drag_power": updated_mass_drag_power,
        "summary": {
            "source_total_mass_after_items_kg": round(old_total, 6),
            "updated_total_mass_after_items_kg": round(new_total, 6),
            "mass_scale_vs_source_closure": round(new_total / old_total, 6),
            "additional_masses_kg": additional,
            "c04_fix_mass_model": dict(c04_mass),
            "integrated_mass_items": [asdict(item) for item in added_items],
            "updated_cg_management": updated_cg,
            "updated_mass_drag_power": updated_mass_drag_power,
        },
    }


def _add_cg_gate_status(cg: dict[str, Any]) -> None:
    acceptable = {
        "final_cg_screening_row_available_without_rebalance",
        "final_cg_screening_row_remains_available_with_rebalance",
    }
    blockers: list[str] = []
    if cg.get("screening_status") not in acceptable:
        blockers.append("final_cg_screening_row_not_available_after_integrated_mass")
    if float(cg.get("required_forward_rebalance_m", 0.0)) > float(
        cg.get("forward_rebalance_limit_m", 0.20)
    ) + 1.0e-12:
        blockers.append("required_forward_rebalance_exceeds_limit")
    cg["status"] = "managed_final_cg_pass" if not blockers else "managed_final_cg_fail"
    cg["blockers"] = blockers
    cg["uncompensated_cg_status"] = (
        "explicitly_rejected"
        if cg.get("uncompensated_status") == "uncompensated_cg_exceeds_screening_range"
        else "inside_or_missing"
    )


def _mass_adjusted_closure_update(
    *,
    source_closure: Mapping[str, Any],
    selected_basis: Mapping[str, Any],
    updated_cg: Mapping[str, Any],
    updated_mass_drag_power: Mapping[str, Any],
    mass_scale: float,
) -> dict[str, Any]:
    source_basis = copy.deepcopy(_mapping_at(source_closure, "basis"))
    aero = dict(_mapping_at(source_basis, "aeroelastic_effects"))
    trim = dict(_mapping_at(source_basis, "trim_static_directional"))

    updated_aero = _scaled_aero_effects(aero, mass_scale)
    updated_trim = _scaled_tail_trim(trim, mass_scale)
    updated_mass_drag = dict(updated_mass_drag_power)
    updated_basis = {
        **source_basis,
        "cg_management": dict(updated_cg),
        "trim_static_directional": updated_trim,
        "aeroelastic_effects": updated_aero,
        "mass_drag_power": updated_mass_drag,
        "load_remap_diagnostics": dict(
            _mapping_at(source_basis, "load_remap_diagnostics")
            or selected_basis.get("load_remap_diagnostics")
            or {"status": "conserved"}
        ),
    }
    classified = classify_aeroelastic_closure(updated_basis)
    return {
        "source_closure_verdict": source_closure.get("engineering_verdict"),
        "updated_closure_verdict": classified["verdict"],
        "updated_blockers": classified["blockers"],
        "updated_warnings": sorted(
            set(classified["warnings"]) | set(source_closure.get("warnings", []))
        ),
        "mass_scale_vs_source_closure": round(float(mass_scale), 6),
        "cg_management": dict(updated_cg),
        "trim_static_directional": updated_trim,
        "aeroelastic_effects": updated_aero,
        "closure_ranking_effect": updated_aero["closure_ranking_effect"],
        "mass_drag_power": updated_mass_drag,
        "basis": classified["basis"],
        "engineering_read": (
            "Added splice and C04-fix mass is applied as a conservative first-order "
            "load scale to the calibrated closure artifact. The bounded physical "
            "twist and root bending ratio remain inside screening bounds; direct "
            "spar-pair rotation may remain a mapping warning, not a hard local-load "
            "path blocker."
        ),
    }


def _scaled_aero_effects(aero: Mapping[str, Any], mass_scale: float) -> dict[str, Any]:
    updated = dict(aero)
    for key in (
        "elastic_twist_max_abs_deg",
        "elastic_twist_tip_deg",
        "elastic_twist_rms_deg",
        "direct_spar_pair_rotation_max_abs_deg",
        "elastic_axis_quarter_chord_projection_max_abs_deg",
        "conservative_bounded_physical_projection_max_abs_deg",
    ):
        if key in updated and isinstance(updated[key], (int, float)):
            updated[key] = float(updated[key]) * float(mass_scale)
    if isinstance(updated.get("root_bending_moment_ratio_loaded_vs_baseline"), (int, float)):
        updated["root_bending_moment_ratio_loaded_vs_baseline"] = (
            float(updated["root_bending_moment_ratio_loaded_vs_baseline"]) * float(mass_scale)
        )
    if isinstance(updated.get("stall_margin_min"), (int, float)):
        updated["stall_margin_min"] = float(updated["stall_margin_min"]) - (
            float(mass_scale) - 1.0
        ) * 1.2
    ratio = _float_or_none(updated.get("root_bending_moment_ratio_loaded_vs_baseline"))
    updated["closure_ranking_effect"] = (
        "no_change_conservative_best_remains_screening_closed"
        if ratio is not None and 0.80 <= ratio <= 1.20
        else "ranking_changed_by_mass_integrated_structural_load"
    )
    updated["mass_integrated_load_scale"] = round(float(mass_scale), 6)
    updated["mass_integrated_scaling_basis"] = (
        "First-order conservative scale from source closure total mass to "
        "splice+C04-fix integrated mass. Full AVL/beam rerun is still required "
        "before final aircraft claims."
    )
    return updated


def _scaled_tail_trim(trim: Mapping[str, Any], mass_scale: float) -> dict[str, Any]:
    updated = dict(trim)
    delta_h = _float_or_none(updated.get("delta_H_required_deg"))
    if delta_h is not None:
        scaled_delta_h = delta_h * float(mass_scale)
        updated["delta_H_required_deg"] = scaled_delta_h
        updated["delta_H_margin_to_limit_deg"] = 15.0 - abs(scaled_delta_h)
    updated["mass_integrated_trim_scale"] = round(float(mass_scale), 6)
    margin = _float_or_none(updated.get("delta_H_margin_to_limit_deg"))
    cn_beta = _float_or_none(updated.get("C_n_beta"))
    static_margin = _float_or_none(updated.get("static_margin"))
    delta_v_margin = _float_or_none(updated.get("delta_V_margin_to_limit_deg"))
    updated["status"] = (
        "pass"
        if (
            margin is not None and margin >= 0.0
            and static_margin is not None and static_margin >= 0.05
            and cn_beta is not None and cn_beta >= 0.005
            and delta_v_margin is not None and delta_v_margin >= 0.0
        )
        else "blocked"
    )
    updated["mass_integrated_trim_read"] = (
        "Horizontal-tail deflection is conservatively scaled with gross load. "
        "Static and directional derivatives are retained because final CG is held "
        "at the same managed screening row."
    )
    return updated


def _final_verdict(
    *,
    fast_status: str,
    local_load_path: Mapping[str, Any],
    updated_closure: Mapping[str, Any],
) -> str:
    if fast_status != "fast_physical_model_verified_within_5pct":
        return VERDICT_FAST_MODEL_RECALIBRATION
    if local_load_path.get("c04_status") != "pass_with_saddle_ring_yoke_fix":
        return VERDICT_C04_NOT_FEASIBLE
    if updated_closure.get("updated_closure_verdict") != READY_VERDICT:
        return VERDICT_MASS_CG_RECLOSURE
    return VERDICT_READY


def _weighted_splice_x(splice: Mapping[str, Any], twist_csv: Path) -> float:
    joints = splice.get("joints") or []
    if not isinstance(joints, Sequence) or not joints:
        return 0.50
    num = 0.0
    den = 0.0
    for joint in joints:
        if not isinstance(joint, Mapping):
            continue
        mass = float(joint.get("total_mass_g", 0.0))
        x_m = _nearest_elastic_axis_x(twist_csv, float(joint.get("y_m", 0.0)))
        num += mass * x_m
        den += mass
    return round(num / den, 6) if den > 0.0 else 0.50


def _nearest_elastic_axis_x(path: Path, y_m: float) -> float:
    if not path.exists():
        return 0.50
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return 0.50
    row = min(rows, key=lambda r: abs(float(r.get("y_m", 0.0)) - float(y_m)))
    if "elastic_axis_x_m" in row:
        return round(float(row["elastic_axis_x_m"]), 6)
    main = float(row.get("main_x_m", 0.0))
    rear = float(row.get("rear_x_m", 1.0))
    return round(0.5 * (main + rear), 6)


def _write_local_surrogate_apdl(summary: Mapping[str, Any], path: Path) -> None:
    local = _mapping_at(summary, "local_load_path")
    mass = _mapping_at(summary, "mass_integration", "c04_fix_mass_model")
    lines = [
        "! P1 C04 local FEM surrogate scaffold",
        "! SADDLE_RING_YOKE",
        "! NO_OUTWARD_PEEL_PRIMARY_LOAD_PATH",
        f"! station_y_m = {local.get('station_y_m')}",
        f"! design_force_n = {local.get('design_force_n')}",
        f"! required_torque_nm = {local.get('required_torque_nm')}",
        f"! saddle_ring_yoke_margin = {local.get('saddle_ring_yoke_margin')}",
        f"! friction_clamp_secondary_margin = {local.get('friction_clamp_secondary_margin')}",
        f"! c04_fix_full_wing_mass_kg = {mass.get('full_wing_mass_kg')}",
        "! FRICTION_CLAMP_SECONDARY",
        "! Coupon/local FEM next step: replace surrogate lug-foot shear and clamp",
        "! contact assumptions with shell/solid adhesive, lug bearing, and tube OD",
        "! contact elements. Do not model this as the old eccentric peel tab.",
        "/PREP7",
        "! TODO_FOR_FEM_OWNER: material cards, shell/solid elements, contact pairs",
        "! TODO_FOR_FEM_OWNER: apply tangential lug couple and clamp preload",
        "FINISH",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _render_markdown(summary: Mapping[str, Any]) -> str:
    local = _mapping_at(summary, "local_load_path")
    mass = _mapping_at(summary, "mass_integration")
    closure = _mapping_at(summary, "mass_cg_tail_closure")
    cg = _mapping_at(closure, "cg_management")
    aero = _mapping_at(closure, "aeroelastic_effects")
    trim = _mapping_at(closure, "trim_static_directional")
    return "\n".join([
        "# Current Pathfinder P1 Load-Path + Mass Closure",
        "",
        f"Final verdict: `{summary['final_verdict']}`",
        f"Candidate: `{summary['candidate_id']}`",
        "",
        "## C04 Local Load Path",
        "",
        f"- Baseline eccentric peel margin: `{local['baseline_c04_margin']}`.",
        f"- Installed fix: `{local['installed_fix_type']}`.",
        f"- Installed fix governing margin: `{local['installed_fix_governing_margin']}`.",
        f"- C04 status: `{local['c04_status']}`.",
        "",
        "## Mass / CG / Tail / Closure",
        "",
        f"- Added C04 fix mass: `{mass['additional_masses_kg']['p1_c04_fix_full_wing']}` kg.",
        f"- Added 3 m spar-splice mass: `{mass['additional_masses_kg']['spar_splice_full_wing']}` kg.",
        f"- Updated total screening mass basis: `{mass['updated_total_mass_after_items_kg']}` kg.",
        f"- Managed final CG: `{cg.get('final_screening_cg_x_m')}` m; forward rebalance `{cg.get('required_forward_rebalance_m')}` m.",
        f"- Tail trim status: `{trim.get('status')}`; delta_H margin `{trim.get('delta_H_margin_to_limit_deg')}` deg.",
        f"- Bounded physical twist: `{aero.get('conservative_bounded_physical_projection_max_abs_deg')}` deg.",
        f"- Root bending ratio after mass scale: `{aero.get('root_bending_moment_ratio_loaded_vs_baseline')}`.",
        f"- Updated closure verdict: `{closure.get('updated_closure_verdict')}`.",
        "",
        "## Boundary",
        "",
        summary["claim_boundary"],
        "",
        "QPROP/XROTOR remains an independent propulsion lane and is not used in this structural blocker verdict.",
    ])


def write_p1_load_path_mass_closure_package(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_json: Path = DEFAULT_REPORT_JSON,
    report_md: Path = DEFAULT_REPORT_MD,
    freeze_json: Path = DEFAULT_FREEZE_JSON,
    splice_json: Path = DEFAULT_SPLICE_JSON,
    source_closure_json: Path = DEFAULT_SOURCE_CLOSURE_JSON,
    fast_calibration_json: Path = DEFAULT_FAST_CALIBRATION_JSON,
) -> dict[str, Path]:
    summary = build_p1_load_path_mass_closure(
        freeze_json=freeze_json,
        splice_json=splice_json,
        source_closure_json=source_closure_json,
        fast_calibration_json=fast_calibration_json,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    report_json.parent.mkdir(parents=True, exist_ok=True)

    run_json = output_dir / "p1_load_path_mass_closure.json"
    local_surrogate_apdl = output_dir / "p1_c04_saddle_ring_local_fem_surrogate.mac"
    run_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_json.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_md.write_text(_render_markdown(summary), encoding="utf-8")
    _write_local_surrogate_apdl(summary, local_surrogate_apdl)
    return {
        "run_json": run_json,
        "report_json": report_json,
        "report_md": report_md,
        "local_surrogate_apdl": local_surrogate_apdl,
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _mapping_at(root: Any, *keys: str) -> Mapping[str, Any]:
    node = root
    for key in keys:
        if not isinstance(node, Mapping):
            return {}
        node = node.get(key, {})
    return node if isinstance(node, Mapping) else {}


def _float_or_none(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    args = parser.parse_args(argv)
    paths = write_p1_load_path_mass_closure_package(
        output_dir=args.output_dir,
        report_json=args.report_json,
        report_md=args.report_md,
    )
    summary = _read_json(paths["report_json"])
    print(f"verdict: {summary['final_verdict']}")
    print(f"report JSON: {paths['report_json']}")
    print(f"report MD: {paths['report_md']}")
    print(f"local surrogate APDL: {paths['local_surrogate_apdl']}")


if __name__ == "__main__":
    main()
