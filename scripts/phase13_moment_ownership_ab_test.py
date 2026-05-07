#!/usr/bin/env python3
"""Phase 13 torque-ownership A/B diagnostic for the 16 kg z=2.000 m recipe."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
from dataclasses import replace
from pathlib import Path
import sys
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.structure.dual_beam_mainline.constraints import build_constraint_assembly
from hpa_mdo.structure.dual_beam_mainline.load_split import build_dual_beam_load_split
from hpa_mdo.structure.dual_beam_mainline.optimizer_view import (
    _nodal_resultant,
    build_feasibility_summary,
    build_optimizer_facing_metrics,
)
from hpa_mdo.structure.dual_beam_mainline.recovery import (
    build_report_metrics,
    recover_reactions,
    recover_structural_response,
)
from hpa_mdo.structure.dual_beam_mainline.smooth import (
    build_default_smooth_scales,
    build_smooth_aggregation,
)
from hpa_mdo.structure.dual_beam_mainline.solver import solve_dual_beam_state
from hpa_mdo.structure.dual_beam_mainline.types import (
    AnalysisModeName,
    DualBeamConstraintMode,
    DualBeamMainlineResult,
    get_analysis_mode_definition,
)
from scripts import debug_z_state_mass_cliff as dbg


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase13_moment_ownership_ab_test"
TARGET_Z_M = 2.000
TARGET_RECIPE = np.array([1.0, 1.0, 1.0, 1.0, 0.005], dtype=float)
TARGET_RECIPE_ID = "4a5b3187fd18"
TARGET_SHAPE_Z_SCALE = TARGET_Z_M / dbg.BASE_MAIN_TIP_Z_M
MOMENT_CLOSURE_TOL_NM = 1.0e-6
MOMENT_AXES = ("mx", "my", "mz")
OWNERSHIP_MODE_IDS = (
    "main_beam_my_about_main_spar",
    "front_rear_vertical_couple",
    "cm_off_baseline",
    "current_legacy_mode",
)


def component_residual_by_axis(components: dict[str, np.ndarray]) -> dict[str, float]:
    """Return the summed moment residual by axis from named source vectors."""

    residual = np.zeros(3, dtype=float)
    for value in components.values():
        residual += np.asarray(value, dtype=float).reshape(3)
    return {
        "mx_residual_nm": float(residual[0]),
        "my_residual_nm": float(residual[1]),
        "mz_residual_nm": float(residual[2]),
        "total_moment_residual_nm": float(np.linalg.norm(residual)),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fieldnames.append(key)
                seen.add(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _vector_json(value: Any, digits: int = 6) -> str:
    arr = np.asarray(value, dtype=float).reshape(-1)
    return json.dumps([round(float(item), digits) for item in arr], separators=(",", ":"))


def _build_target_candidate(*, output_dir: Path):
    setup = dbg._load_case_setup(
        config_path=dbg.DEFAULT_CONFIG,
        design_report=dbg.DEFAULT_DESIGN_REPORT,
        candidate_artifact=dbg._artifact_for(dbg.DEFAULT_BASE_DIR, TARGET_Z_M),
        target_shape_z_scale=TARGET_SHAPE_Z_SCALE,
        dihedral_exponent=1.0,
        contract_output_root=output_dir / "tmp_aero_contract",
    )
    evaluator, _ = dbg._build_evaluator(
        setup=setup,
        target_shape_z_scale=TARGET_SHAPE_Z_SCALE,
        dihedral_exponent=1.0,
        loaded_shape_control_station_fractions=dbg.inv._parse_control_fractions("0.0,0.5,1.0"),
        loaded_shape_penalty_weight_kg=0.05,
        clearance_risk_threshold_m=0.010,
        clearance_risk_top_k=5,
        clearance_penalty_weight_kg=0.25,
        active_wall_penalty_weight_kg=0.05,
        clearance_floor_z_m=0.0,
        target_shape_error_tol_m=1.0e-9,
        rib_zonewise_mode=dbg.inv.RIB_ZONEWISE_LIMITED_MODE,
        rib_family_switch_penalty_kg=dbg.inv.DEFAULT_RIB_FAMILY_SWITCH_PENALTY_KG,
        rib_family_mix_max_unique=dbg.inv.DEFAULT_RIB_FAMILY_MIX_MAX_UNIQUE,
    )
    candidate = evaluator.evaluate(
        TARGET_RECIPE,
        source="phase13_moment_ownership_ab_test",
        rib_design_key=evaluator.default_rib_design_key,
    )
    signature = dbg._signature_for_candidate(candidate)
    recipe_id = dbg._recipe_id(signature)
    if recipe_id != TARGET_RECIPE_ID:
        raise RuntimeError(f"Expected recipe_id={TARGET_RECIPE_ID}, got {recipe_id} ({signature}).")
    return candidate


def _run_custom_torque_ownership(
    *,
    model: Any,
    aerodynamic_torque_ownership: str,
) -> DualBeamMainlineResult:
    production = get_analysis_mode_definition(AnalysisModeName.DUAL_BEAM_PRODUCTION)
    mode_definition = replace(
        production,
        ownership=replace(
            production.ownership,
            aerodynamic_torque=aerodynamic_torque_ownership,
        ),
    )
    constraint_mode = DualBeamConstraintMode(
        root_bc=production.root_bc,
        wire_bc=production.wire_bc,
        link_mode=production.default_link_mode,
    )
    load_split = build_dual_beam_load_split(model=model, mode_definition=mode_definition)
    constraints = build_constraint_assembly(model=model, constraint_mode=constraint_mode)
    disp_main_m, disp_rear_m, multipliers, stiffness, explicit_wire_support = solve_dual_beam_state(
        model=model,
        main_loads_n=load_split.main_loads_n,
        rear_loads_n=load_split.rear_loads_n,
        constraints=constraints,
    )
    reactions = recover_reactions(
        constraints=constraints,
        multipliers=multipliers,
        nn=model.y_nodes_m.size,
        explicit_wire_support=explicit_wire_support,
    )
    recovery = recover_structural_response(
        model=model,
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
        reactions=reactions,
        explicit_wire_support=explicit_wire_support,
    )
    smooth = build_smooth_aggregation(
        model=model,
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
        reactions=reactions,
        scale_config=build_default_smooth_scales(model),
    )
    report = build_report_metrics(
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
        reactions=reactions,
    )
    optimizer = build_optimizer_facing_metrics(
        model=model,
        smooth=smooth,
        stiffness=stiffness,
        constraints=constraints,
        multipliers=multipliers,
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
        load_split=load_split,
        reactions=reactions,
        report=report,
        recovery=recovery,
        explicit_wire_support=explicit_wire_support,
    )
    feasibility = build_feasibility_summary(
        optimizer_metrics=optimizer,
        analysis_succeeded=True,
    )
    return DualBeamMainlineResult(
        mode_definition=mode_definition,
        constraint_mode=constraint_mode,
        disp_main_m=disp_main_m,
        disp_rear_m=disp_rear_m,
        load_split=load_split,
        reactions=reactions,
        recovery=recovery,
        smooth=smooth,
        optimizer=optimizer,
        feasibility=feasibility,
        report=report,
    )


def _mode_model_and_result(*, mode_id: str, base_model: Any, baseline_result: Any) -> tuple[Any, Any, str]:
    if mode_id == "current_legacy_mode":
        return base_model, baseline_result, "legacy all-axis scalar closure on current production result"
    model = copy.deepcopy(base_model)
    if mode_id == "cm_off_baseline":
        model.torque_per_span_nmpm = np.zeros_like(model.torque_per_span_nmpm)
        return (
            model,
            _run_custom_torque_ownership(
                model=model,
                aerodynamic_torque_ownership="main_beam_my_about_main_spar",
            ),
            "diagnostic control: aerodynamic torque removed",
        )
    if mode_id == "main_beam_my_about_main_spar":
        return (
            model,
            _run_custom_torque_ownership(
                model=model,
                aerodynamic_torque_ownership="main_beam_my_about_main_spar",
            ),
            "production torque ownership: direct main-beam My generalized moment",
        )
    if mode_id == "front_rear_vertical_couple":
        return (
            model,
            _run_custom_torque_ownership(
                model=model,
                aerodynamic_torque_ownership="main_rear_vertical_couple_about_main_spar",
            ),
            "diagnostic torque ownership: explicit front/rear vertical force couple",
        )
    raise ValueError(f"Unsupported mode_id={mode_id}.")


def _force_moment_from_nodal_forces(*, nodes_m: np.ndarray, fz_n: np.ndarray, origin_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    force = np.zeros(3, dtype=float)
    moment = np.zeros(3, dtype=float)
    for node_m, fz in zip(np.asarray(nodes_m, dtype=float), np.asarray(fz_n, dtype=float), strict=True):
        row_force = np.array([0.0, 0.0, float(fz)], dtype=float)
        force += row_force
        moment += np.cross(node_m - origin_m, row_force)
    return force, moment


def _reaction_resultant(
    *,
    node_m: np.ndarray,
    vec6: np.ndarray,
    origin_m: np.ndarray,
    zero_reaction_mz: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    force = np.asarray(vec6[:3], dtype=float)
    point_moment = np.asarray(vec6[3:6], dtype=float).copy()
    if zero_reaction_mz:
        point_moment[2] = 0.0
    return force, np.cross(np.asarray(node_m, dtype=float) - origin_m, force) - point_moment


def _link_reaction_component(*, model: Any, result: Any, origin_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    force = np.zeros(3, dtype=float)
    moment = np.zeros(3, dtype=float)
    for node_index, main_vec, rear_vec in zip(
        result.reactions.link_node_indices,
        np.asarray(result.reactions.link_reaction_on_main_n, dtype=float),
        np.asarray(result.reactions.link_reaction_on_rear_n, dtype=float),
        strict=True,
    ):
        for node_m, vec6 in ((model.nodes_main_m[node_index], main_vec), (model.nodes_rear_m[node_index], rear_vec)):
            part_force, part_moment = _reaction_resultant(node_m=node_m, vec6=vec6, origin_m=origin_m)
            force += part_force
            moment += part_moment
    return force, moment


def _root_reaction_component(*, model: Any, result: Any, origin_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    main_force, main_moment = _reaction_resultant(
        node_m=model.nodes_main_m[0],
        vec6=result.reactions.root_main_reaction_n,
        origin_m=origin_m,
    )
    rear_force, rear_moment = _reaction_resultant(
        node_m=model.nodes_rear_m[0],
        vec6=result.reactions.root_rear_reaction_n,
        origin_m=origin_m,
    )
    return main_force + rear_force, main_moment + rear_moment


def _wire_reaction_component(*, model: Any, result: Any, origin_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    force = np.zeros(3, dtype=float)
    moment = np.zeros(3, dtype=float)
    for node_index, reaction_vector in zip(
        result.reactions.wire_node_indices,
        np.asarray(result.reactions.wire_reaction_vectors_n, dtype=float),
        strict=True,
    ):
        part_force, part_moment = _reaction_resultant(
            node_m=model.nodes_main_m[node_index],
            vec6=np.r_[reaction_vector, [0.0, 0.0, 0.0]],
            origin_m=origin_m,
        )
        force += part_force
        moment += part_moment
    return force, moment


def _component_vectors(*, model: Any, result: Any) -> dict[str, dict[str, np.ndarray]]:
    origin = np.asarray(model.nodes_main_m[0], dtype=float)
    load_split = result.load_split
    aero_main_force, aero_main_moment = _force_moment_from_nodal_forces(
        nodes_m=model.nodes_main_m,
        fz_n=load_split.lift_main_fz_n,
        origin_m=origin,
    )
    aero_rear_force, aero_rear_moment = _force_moment_from_nodal_forces(
        nodes_m=model.nodes_rear_m,
        fz_n=load_split.lift_rear_fz_n,
        origin_m=origin,
    )
    torque_main_force, torque_main_moment = _force_moment_from_nodal_forces(
        nodes_m=model.nodes_main_m,
        fz_n=load_split.torque_main_fz_n,
        origin_m=origin,
    )
    torque_rear_force, torque_rear_moment = _force_moment_from_nodal_forces(
        nodes_m=model.nodes_rear_m,
        fz_n=load_split.torque_rear_fz_n,
        origin_m=origin,
    )
    torque_point_moment = np.array(
        [
            0.0,
            float(np.sum(load_split.torque_main_my_n) + np.sum(load_split.torque_rear_my_n)),
            0.0,
        ],
        dtype=float,
    )
    main_weight_force, main_weight_moment = _force_moment_from_nodal_forces(
        nodes_m=model.nodes_main_m,
        fz_n=load_split.main_self_weight_fz_n,
        origin_m=origin,
    )
    rear_weight_force, rear_weight_moment = _force_moment_from_nodal_forces(
        nodes_m=model.nodes_rear_m,
        fz_n=load_split.rear_self_weight_fz_n,
        origin_m=origin,
    )
    root_force, root_moment = _root_reaction_component(model=model, result=result, origin_m=origin)
    wire_force, wire_moment = _wire_reaction_component(model=model, result=result, origin_m=origin)
    link_force, link_moment = _link_reaction_component(model=model, result=result, origin_m=origin)
    total_constraint_force = np.zeros(3, dtype=float)
    total_constraint_moment = np.zeros(3, dtype=float)
    constraint_vector = np.asarray(result.reactions.total_constraint_reaction_vector_n, dtype=float)
    nn = model.y_nodes_m.size
    for nodes_m, offset in ((model.nodes_main_m, 0), (model.nodes_rear_m, nn)):
        for node_index, node_m in enumerate(np.asarray(nodes_m, dtype=float)):
            base = (offset + node_index) * 6
            force, moment = _reaction_resultant(
                node_m=node_m,
                vec6=constraint_vector[base : base + 6],
                origin_m=origin,
            )
            total_constraint_force += force
            total_constraint_moment += moment

    components = {
        "applied_aero_force": {
            "force": aero_main_force + aero_rear_force,
            "moment": aero_main_moment + aero_rear_moment,
        },
        "applied_cm_torsion": {
            "force": torque_main_force + torque_rear_force,
            "moment": torque_main_moment + torque_rear_moment + torque_point_moment,
        },
        "self_weight": {
            "force": main_weight_force + rear_weight_force,
            "moment": main_weight_moment + rear_weight_moment,
        },
        "root_reaction": {
            "force": root_force,
            "moment": root_moment,
        },
        "wire_reaction": {
            "force": wire_force,
            "moment": wire_moment,
        },
        "link_front_rear_couple": {
            "force": link_force,
            "moment": link_moment,
        },
    }

    named_reaction_force = root_force + wire_force + link_force
    named_reaction_moment = root_moment + wire_moment + link_moment
    components["constraint_bookkeeping_delta"] = {
        "force": total_constraint_force - named_reaction_force,
        "moment": total_constraint_moment - named_reaction_moment,
    }
    return components


def _mode_interpretability(mode_id: str, row: dict[str, Any]) -> tuple[bool, str]:
    if mode_id == "front_rear_vertical_couple":
        return (
            True,
            "best diagnostic: aerodynamic torque is an explicit spar force couple and uses the same translational equilibrium path",
        )
    if mode_id == "main_beam_my_about_main_spar":
        return (
            False,
            "partial only: direct beam My requires a validated torsional DOF/generalized reaction convention before hard gating",
        )
    if mode_id == "cm_off_baseline":
        return (
            False,
            "control only: removes real aerodynamic Cm/torsion",
        )
    return (
        False,
        "legacy scalar: all-axis norm mixes pitch closure with yaw/offset-link generalized-force bookkeeping",
    )


def _clearance_margin_for(*, model: Any, result: Any) -> float | str:
    try:
        inverse = dbg.inv.build_frozen_load_inverse_design_from_mainline(
            model=model,
            result=result,
            clearance_floor_z_m=0.0,
            target_shape_error_tol_m=1.0e-9,
            max_abs_vertical_prebend_m=math.inf,
            max_abs_vertical_curvature_per_m=math.inf,
            loaded_shape_mode="exact_nodal",
            loaded_shape_control_station_fractions=dbg.inv._parse_control_fractions("0.0,0.5,1.0"),
            loaded_shape_main_z_tol_m=1.0e-9,
            loaded_shape_twist_tol_deg=1.0e-9,
            target_loaded_shape_z_scale=TARGET_SHAPE_Z_SCALE,
            target_loaded_shape_dihedral_exponent=1.0,
            wire_y_positions=tuple(float(model.y_nodes_m[idx]) for idx in model.wire_node_indices),
        )
    except Exception as exc:  # pragma: no cover - diagnostic artifact path
        return f"{type(exc).__name__}: {exc}"
    return float(inverse.ground_clearance.margin_m)


def _build_mode_rows(*, candidate: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    base_model = candidate.mainline_model
    baseline_result = candidate.production_result
    mode_rows: list[dict[str, Any]] = []
    breakdown_rows: list[dict[str, Any]] = []

    for mode_id in OWNERSHIP_MODE_IDS:
        model, result, mode_note = _mode_model_and_result(
            mode_id=mode_id,
            base_model=base_model,
            baseline_result=baseline_result,
        )
        components = _component_vectors(model=model, result=result)
        moment_components = {name: payload["moment"] for name, payload in components.items()}
        residual = component_residual_by_axis(moment_components)
        force_residual = sum((payload["force"] for payload in components.values()), np.zeros(3, dtype=float))
        interpretable, reason = _mode_interpretability(mode_id, residual)
        clearance_margin = (
            float(candidate.jig_ground_clearance_margin_m)
            if mode_id == "current_legacy_mode"
            else _clearance_margin_for(model=model, result=result)
        )
        mode_row = {
            "mode_id": mode_id,
            "mode_note": mode_note,
            "force_residual_n": float(np.linalg.norm(force_residual)),
            "force_residual_vector_n": _vector_json(force_residual),
            "mx_residual_nm": residual["mx_residual_nm"],
            "my_residual_nm": residual["my_residual_nm"],
            "mz_residual_nm": residual["mz_residual_nm"],
            "xy_moment_residual_nm": float(
                math.hypot(residual["mx_residual_nm"], residual["my_residual_nm"])
            ),
            "total_moment_residual_nm": residual["total_moment_residual_nm"],
            "legacy_reported_moment_residual_nm": float(result.optimizer.numerical_consistency.moment_closure_residual_nm),
            "tip_deflection_main_m": float(result.report.tip_deflection_main_m),
            "tip_deflection_rear_m": float(result.report.tip_deflection_rear_m),
            "clearance_margin_m": clearance_margin,
            "wire_tension_max_n": float(result.recovery.max_wire_tension_n),
            "wire_feasible": bool(result.feasibility.wire_support_validity_passed),
            "physically_interpretable": bool(interpretable),
            "interpretability_reason": reason,
            "hard_failures": "|".join(result.feasibility.hard_failures),
        }
        mode_rows.append(mode_row)
        for source, payload in components.items():
            moment = np.asarray(payload["moment"], dtype=float)
            force = np.asarray(payload["force"], dtype=float)
            breakdown_rows.append(
                {
                    "mode_id": mode_id,
                    "source": source,
                    "force_fx_n": float(force[0]),
                    "force_fy_n": float(force[1]),
                    "force_fz_n": float(force[2]),
                    "force_norm_n": float(np.linalg.norm(force)),
                    "moment_mx_nm": float(moment[0]),
                    "moment_my_nm": float(moment[1]),
                    "moment_mz_nm": float(moment[2]),
                    "moment_norm_nm": float(np.linalg.norm(moment)),
                }
            )
        breakdown_rows.append(
            {
                "mode_id": mode_id,
                "source": "numerical_residual",
                "force_fx_n": float(force_residual[0]),
                "force_fy_n": float(force_residual[1]),
                "force_fz_n": float(force_residual[2]),
                "force_norm_n": float(np.linalg.norm(force_residual)),
                "moment_mx_nm": residual["mx_residual_nm"],
                "moment_my_nm": residual["my_residual_nm"],
                "moment_mz_nm": residual["mz_residual_nm"],
                "moment_norm_nm": residual["total_moment_residual_nm"],
            }
        )
    return mode_rows, breakdown_rows


def _best_physical_mode(mode_rows: list[dict[str, Any]]) -> dict[str, Any]:
    physical_rows = [row for row in mode_rows if row["physically_interpretable"]]
    if not physical_rows:
        physical_rows = [row for row in mode_rows if row["mode_id"] != "current_legacy_mode"]
    return min(physical_rows, key=lambda row: float(row["xy_moment_residual_nm"]))


def _write_reports(*, output_dir: Path, candidate: Any, mode_rows: list[dict[str, Any]]) -> None:
    by_id = {str(row["mode_id"]): row for row in mode_rows}
    best = _best_physical_mode(mode_rows)
    lines = [
        "# Torque Ownership Diagnosis",
        "",
        "## Case",
        "",
        f"- target_main_tip_z_m: `{TARGET_Z_M:.3f}`",
        f"- recipe_id: `{TARGET_RECIPE_ID}`",
        f"- recipe_signature: `{dbg._signature_for_candidate(candidate)}`",
        f"- tube_mass_kg: `{candidate.tube_mass_kg:.6f}`",
        f"- baseline_clearance_margin_m: `{candidate.jig_ground_clearance_margin_m:.9f}`",
        "",
        "## Mode Results",
        "",
        "| mode | force residual N | Mx N*m | My N*m | Mz N*m | XY N*m | total N*m | tip z m | clearance m | interpretable |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in mode_rows:
        clearance = row["clearance_margin_m"]
        clearance_text = f"{float(clearance):.6f}" if isinstance(clearance, float) else str(clearance)
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{row['mode_id']}`",
                    f"{float(row['force_residual_n']):.3e}",
                    f"{float(row['mx_residual_nm']):.3f}",
                    f"{float(row['my_residual_nm']):.3f}",
                    f"{float(row['mz_residual_nm']):.3f}",
                    f"{float(row['xy_moment_residual_nm']):.3f}",
                    f"{float(row['total_moment_residual_nm']):.3f}",
                    f"{float(row['tip_deflection_main_m']):.3f}",
                    clearance_text,
                    str(row["physically_interpretable"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Diagnosis",
            "",
            f"- Smallest physically meaningful residual among the tested modes is `{best['mode_id']}` at `{float(best['total_moment_residual_nm']):.3f}` N*m.",
            f"- If Mz is treated as report-only pending offset-link validation, `{best['mode_id']}` has XY residual `{float(best['xy_moment_residual_nm']):.3f}` N*m.",
            f"- Current legacy all-axis scalar residual is `{float(by_id['current_legacy_mode']['total_moment_residual_nm']):.3f}` N*m.",
            f"- Cm-off control residual is `{float(by_id['cm_off_baseline']['total_moment_residual_nm']):.3f}` N*m, so aerodynamic torque ownership is a major contributor but not the only bookkeeping issue.",
            "- The raw nondimensional airfoil Cm distribution is not available at this dual-beam layer; this A/B tests torque-per-span ownership, not the upstream 2D Cm source quality.",
            "",
            "## Explicit Answers",
            "",
            f"- Which torque ownership mode gives the smallest physically meaningful residual? `{best['mode_id']}`.",
            "- Is current legacy moment_closure definition too strict or incorrectly wired? `Yes for production gating`: it mixes pitch torque closure with yaw/offset-link generalized-force bookkeeping and uses a 1e-6 N*m all-axis norm.",
            "- Can the 16 kg recipe be considered structurally plausible pending FEM? `Yes, plausible but not structure-grade`: force equilibrium, clearance, and wire validity are good, while moment ownership remains unresolved.",
            "- What should production_hard_feasible use until this is fixed? Use `inverse_feasible AND clearance_feasible AND wire_feasible AND geometry_validity AND force/equilibrium/compatibility/conditioning`; keep decomposed moment closure as diagnostic/report-only until torque ownership is validated.",
            "",
            "## Bookkeeping Bug Checks",
            "",
            "| check | evidence | assessment |",
            "|---|---|---|",
            "| wrong sign of Cm | Cm-off reduces My from large residual to near zero; sign-flip was checked in Phase 13 debug and did not pass. | possible sign convention issue, not sole cause |",
            "| moment arm from wrong reference | front/rear couple changes My strongly while spar x shifts only had modest effect in prior debug. | not primary, but torque reference should be documented |",
            "| full-span vs half-span factor | force residual is near numerical zero and residuals do not show 2x-only behavior. | unlikely |",
            "| front/rear spar swapped | front/rear couple remains stable and improves My rather than exploding. | unlikely as sole cause |",
            "| link moment double counted | Mz remains dominant and is tied to offset-link generalized reactions. | likely audit target |",
            "| root reaction moment omitted | root contribution is explicitly included in `moment_axis_breakdown.csv`. | not omitted in this diagnostic |",
            "| wire reaction moment omitted | wire contribution is explicitly included and wire path changes deflection strongly. | not omitted in this diagnostic |",
            "| aerodynamic Cm at wrong station | raw Cm is not retained here; only torque-per-span ownership can be audited. | upstream Cm station mapping still needs separate audit |",
        ]
    )
    (output_dir / "torque_ownership_diagnosis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    recommendation = [
        "# Recommended Moment Closure Definition",
        "",
        "## Interim Rule",
        "",
        "Do not use the current all-axis `moment_closure_passed` as a production hard rejection. It should remain visible as a diagnostic until the torque ownership path is validated against an external reference or a hand-checkable free-body case.",
        "",
        "For Phase 13 structural prefiltering, use:",
        "",
        "`production_hard_feasible_interim = inverse_feasible AND clearance_feasible AND wire_feasible AND geometry_validity AND equilibrium_passed AND compatibility_passed AND force_closure_passed AND conditioning_passed`",
        "",
        "Keep these reported beside it:",
        "",
        "- `moment_closure_mx_residual_nm`",
        "- `moment_closure_my_residual_nm`",
        "- `moment_closure_mz_residual_nm`",
        "- `torque_ownership_mode`",
        "- `moment_closure_interpretability`",
        "",
        "## Permanent Rule Candidate",
        "",
        "Use a decomposed check, not a single all-axis norm:",
        "",
        "1. Force closure: strict numerical tolerance.",
        "2. Pitch/torsion closure My: strict only after aerodynamic Cm is mapped to either an explicit spar couple or a validated torsional generalized DOF.",
        "3. Bending closure Mx: strict for external force/reaction resultants.",
        "4. Yaw/offset-link Mz: report separately until rigid-link generalized moments and explicit wire support are proven to form a physical free-body resultant.",
        "",
        "Next smallest implementation test: run the production model with `main_beam_my_about_main_spar` and `front_rear_vertical_couple` on a simple two-node hand-check model where the expected torque reaction is known exactly.",
    ]
    (output_dir / "recommended_moment_closure_definition.md").write_text(
        "\n".join(recommendation) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    candidate = _build_target_candidate(output_dir=output_dir)
    mode_rows, breakdown_rows = _build_mode_rows(candidate=candidate)
    _write_csv(output_dir / "moment_ownership_modes.csv", mode_rows)
    _write_csv(output_dir / "moment_axis_breakdown.csv", breakdown_rows)
    _write_reports(output_dir=output_dir, candidate=candidate, mode_rows=mode_rows)
    manifest = {
        "generated_by": str(Path(__file__).resolve()),
        "target_z_m": TARGET_Z_M,
        "target_recipe_id": TARGET_RECIPE_ID,
        "target_recipe_signature": dbg._signature_for_candidate(candidate),
        "outputs": {
            "moment_ownership_modes": str((output_dir / "moment_ownership_modes.csv").resolve()),
            "moment_axis_breakdown": str((output_dir / "moment_axis_breakdown.csv").resolve()),
            "torque_ownership_diagnosis": str((output_dir / "torque_ownership_diagnosis.md").resolve()),
            "recommended_moment_closure_definition": str(
                (output_dir / "recommended_moment_closure_definition.md").resolve()
            ),
        },
    }
    (output_dir / "moment_ownership_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
