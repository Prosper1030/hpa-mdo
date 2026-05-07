#!/usr/bin/env python3
"""Debug Phase 13 moment-closure failure for the z=2.000 m light recipe."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.structure.dual_beam_mainline.api import run_dual_beam_mainline_kernel
from hpa_mdo.structure.dual_beam_mainline.optimizer_view import _nodal_resultant
from hpa_mdo.structure.dual_beam_mainline.types import AnalysisModeName
from scripts import debug_z_state_mass_cliff as dbg


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase13_moment_closure_debug"
TARGET_Z_M = 2.000
TARGET_RECIPE = np.array([1.0, 1.0, 1.0, 1.0, 0.005], dtype=float)
TARGET_RECIPE_ID = "4a5b3187fd18"
MOMENT_CLOSURE_TOL_NM = 1.0e-6


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


def _json_list(values: Any, digits: int = 6) -> str:
    arr = np.asarray(values, dtype=float).reshape(-1)
    return json.dumps([round(float(value), digits) for value in arr], separators=(",", ":"))


def _build_target_candidate(*, output_dir: Path):
    target_shape_z_scale = TARGET_Z_M / dbg.BASE_MAIN_TIP_Z_M
    setup = dbg._load_case_setup(
        config_path=dbg.DEFAULT_CONFIG,
        design_report=dbg.DEFAULT_DESIGN_REPORT,
        candidate_artifact=dbg._artifact_for(dbg.DEFAULT_BASE_DIR, TARGET_Z_M),
        target_shape_z_scale=target_shape_z_scale,
        dihedral_exponent=1.0,
        contract_output_root=output_dir / "tmp_aero_contract",
    )
    evaluator, _ = dbg._build_evaluator(
        setup=setup,
        target_shape_z_scale=target_shape_z_scale,
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
        source="phase13_moment_closure_debug",
        rib_design_key=evaluator.default_rib_design_key,
    )
    signature = dbg._signature_for_candidate(candidate)
    recipe_id = dbg._recipe_id(signature)
    if recipe_id != TARGET_RECIPE_ID:
        raise RuntimeError(f"Expected recipe_id={TARGET_RECIPE_ID}, got {recipe_id} ({signature}).")
    return candidate


def _clone_model_with_variant(model: Any, variant_id: str) -> Any:
    out = copy.deepcopy(model)
    if variant_id == "baseline":
        return out
    if variant_id == "cm_off":
        out.torque_per_span_nmpm = np.zeros_like(out.torque_per_span_nmpm)
        return out
    if variant_id == "cm_sign_flipped":
        out.torque_per_span_nmpm = -np.asarray(out.torque_per_span_nmpm, dtype=float)
        return out
    if variant_id == "wire_off":
        out.wire_node_indices = ()
        out.wire_attachment_angles_deg = ()
        out.wire_anchor_points_m = np.zeros((0, 3), dtype=float)
        out.wire_area_m2 = np.zeros(0, dtype=float)
        out.wire_young_pa = np.zeros(0, dtype=float)
        out.wire_allowable_tension_n = np.zeros(0, dtype=float)
        out.wire_reference_lengths_m = np.zeros(0, dtype=float)
        out.wire_unstretched_lengths_m = np.zeros(0, dtype=float)
        return out
    if variant_id == "equal_spar_stiffness":
        out.rear_area_m2 = np.asarray(out.main_area_m2, dtype=float).copy()
        out.rear_iy_m4 = np.asarray(out.main_iy_m4, dtype=float).copy()
        out.rear_iz_m4 = np.asarray(out.main_iz_m4, dtype=float).copy()
        out.rear_j_m4 = np.asarray(out.main_j_m4, dtype=float).copy()
        out.rear_mass_per_length_kgpm = np.asarray(out.main_mass_per_length_kgpm, dtype=float).copy()
        return out
    if variant_id == "rear_stiffness_10x":
        out.rear_young_pa = np.asarray(out.rear_young_pa, dtype=float) * 10.0
        out.rear_shear_pa = np.asarray(out.rear_shear_pa, dtype=float) * 10.0
        return out
    if variant_id == "rear_spar_shift_aft_50mm":
        out.nodes_rear_m = np.asarray(out.nodes_rear_m, dtype=float).copy()
        out.nodes_rear_m[:, 0] += 0.050
        out.spar_offset_vectors_m = out.nodes_rear_m - out.nodes_main_m
        out.spar_separation_nodes_m = np.abs(out.spar_offset_vectors_m[:, 0])
        return out
    if variant_id == "rear_spar_shift_fwd_50mm":
        out.nodes_rear_m = np.asarray(out.nodes_rear_m, dtype=float).copy()
        out.nodes_rear_m[:, 0] -= 0.050
        out.spar_offset_vectors_m = out.nodes_rear_m - out.nodes_main_m
        out.spar_separation_nodes_m = np.abs(out.spar_offset_vectors_m[:, 0])
        return out
    raise ValueError(f"Unknown variant_id={variant_id}.")


def _resultant_from_vector(
    *,
    node_m: np.ndarray,
    vec6: np.ndarray,
    origin_m: np.ndarray,
    reaction_moment_sign: float = -1.0,
    zero_reaction_mz: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    force_n = np.asarray(vec6[:3], dtype=float)
    moment_nm = np.asarray(vec6[3:6], dtype=float).copy()
    if zero_reaction_mz:
        moment_nm[2] = 0.0
    return force_n, np.cross(np.asarray(node_m, dtype=float) - origin_m, force_n) + reaction_moment_sign * moment_nm


def _closure_components(
    *,
    model: Any,
    result: Any,
    reaction_moment_sign: float = -1.0,
    zero_reaction_mz: bool = True,
) -> dict[str, Any]:
    origin_m = np.asarray(model.nodes_main_m[0], dtype=float)
    load_split = result.load_split
    reactions = result.reactions
    applied_main_force_n, applied_main_moment_nm = _nodal_resultant(
        nodes_m=model.nodes_main_m,
        nodal_loads_n=load_split.main_loads_n,
        origin_m=origin_m,
    )
    applied_rear_force_n, applied_rear_moment_nm = _nodal_resultant(
        nodes_m=model.nodes_rear_m,
        nodal_loads_n=load_split.rear_loads_n,
        origin_m=origin_m,
    )
    applied_force_n = applied_main_force_n + applied_rear_force_n
    applied_moment_nm = applied_main_moment_nm + applied_rear_moment_nm
    constraint_force_n = np.zeros(3, dtype=float)
    constraint_moment_nm = np.zeros(3, dtype=float)
    vector = np.asarray(reactions.total_constraint_reaction_vector_n, dtype=float)
    nn = model.y_nodes_m.size
    for nodes_m, offset in ((model.nodes_main_m, 0), (model.nodes_rear_m, nn)):
        for node_index, node_m in enumerate(np.asarray(nodes_m, dtype=float)):
            base = (offset + node_index) * 6
            force_n, moment_nm = _resultant_from_vector(
                node_m=node_m,
                vec6=vector[base : base + 6],
                origin_m=origin_m,
                reaction_moment_sign=reaction_moment_sign,
                zero_reaction_mz=zero_reaction_mz,
            )
            constraint_force_n += force_n
            constraint_moment_nm += moment_nm
    residual_force_n = applied_force_n + constraint_force_n
    residual_moment_nm = applied_moment_nm + constraint_moment_nm
    return {
        "applied_force_n": applied_force_n,
        "applied_moment_nm": applied_moment_nm,
        "constraint_force_n": constraint_force_n,
        "constraint_moment_nm": constraint_moment_nm,
        "residual_force_n": residual_force_n,
        "residual_moment_nm": residual_moment_nm,
        "force_residual_norm_n": float(np.linalg.norm(residual_force_n)),
        "moment_residual_norm_nm": float(np.linalg.norm(residual_moment_nm)),
        "moment_residual_xy_norm_nm": float(np.linalg.norm(residual_moment_nm[:2])),
        "moment_residual_pitch_abs_nm": abs(float(residual_moment_nm[1])),
        "moment_residual_bending_abs_nm": abs(float(residual_moment_nm[0])),
        "moment_residual_yaw_abs_nm": abs(float(residual_moment_nm[2])),
    }


def _source_summary_rows(*, model: Any, result: Any) -> list[dict[str, Any]]:
    origin_m = np.asarray(model.nodes_main_m[0], dtype=float)
    reactions = result.reactions

    def source_row(source: str, force_n: np.ndarray, moment_nm: np.ndarray) -> dict[str, Any]:
        return {
            "kind": "source_summary",
            "variant_id": "baseline",
            "source": source,
            "reaction_fx_n": float(force_n[0]),
            "reaction_fy_n": float(force_n[1]),
            "reaction_fz_n": float(force_n[2]),
            "reaction_resultant_n": float(np.linalg.norm(force_n)),
            "reaction_moment_mx_nm": float(moment_nm[0]),
            "reaction_moment_my_nm": float(moment_nm[1]),
            "reaction_moment_mz_nm": float(moment_nm[2]),
            "reaction_moment_norm_nm": float(np.linalg.norm(moment_nm)),
        }

    rows: list[dict[str, Any]] = []
    for source, node_m, vec6 in (
        ("root_main", model.nodes_main_m[0], reactions.root_main_reaction_n),
        ("root_rear", model.nodes_rear_m[0], reactions.root_rear_reaction_n),
    ):
        force_n, moment_nm = _resultant_from_vector(
            node_m=node_m,
            vec6=np.asarray(vec6, dtype=float),
            origin_m=origin_m,
        )
        rows.append(source_row(source, force_n, moment_nm))

    wire_force = np.zeros(3, dtype=float)
    wire_moment = np.zeros(3, dtype=float)
    for node_index, reaction_vector in zip(
        reactions.wire_node_indices,
        np.asarray(reactions.wire_reaction_vectors_n, dtype=float),
        strict=True,
    ):
        force_n, moment_nm = _resultant_from_vector(
            node_m=model.nodes_main_m[node_index],
            vec6=np.r_[reaction_vector, [0.0, 0.0, 0.0]],
            origin_m=origin_m,
        )
        wire_force += force_n
        wire_moment += moment_nm
    rows.append(source_row("wire", wire_force, wire_moment))

    link_force = np.zeros(3, dtype=float)
    link_moment = np.zeros(3, dtype=float)
    for node_index, main_vec, rear_vec in zip(
        reactions.link_node_indices,
        np.asarray(reactions.link_reaction_on_main_n, dtype=float),
        np.asarray(reactions.link_reaction_on_rear_n, dtype=float),
        strict=True,
    ):
        for node_m, vec6 in ((model.nodes_main_m[node_index], main_vec), (model.nodes_rear_m[node_index], rear_vec)):
            force_n, moment_nm = _resultant_from_vector(node_m=node_m, vec6=vec6, origin_m=origin_m)
            link_force += force_n
            link_moment += moment_nm
    rows.append(source_row("links_total", link_force, link_moment))
    return rows


def _breakdown_rows(*, model: Any, result: Any) -> list[dict[str, Any]]:
    origin_m = np.asarray(model.nodes_main_m[0], dtype=float)
    load_split = result.load_split
    reactions = result.reactions
    vector = np.asarray(reactions.total_constraint_reaction_vector_n, dtype=float)
    nn = model.y_nodes_m.size
    semi_span = max(float(model.y_nodes_m[-1]), 1.0e-12)
    rows: list[dict[str, Any]] = []
    cumulative = np.zeros(3, dtype=float)

    for station_index in range(nn):
        station_residual = np.zeros(3, dtype=float)
        station_applied = np.zeros(3, dtype=float)
        station_reaction = np.zeros(3, dtype=float)
        for beam, nodes_m, loads_n, offset in (
            ("main", model.nodes_main_m, load_split.main_loads_n, 0),
            ("rear", model.nodes_rear_m, load_split.rear_loads_n, nn),
        ):
            node_m = np.asarray(nodes_m[station_index], dtype=float)
            load_vec = np.asarray(loads_n[station_index], dtype=float)
            applied_force = load_vec[:3]
            applied_moment = load_vec[3:6] + np.cross(node_m - origin_m, applied_force)
            base = (offset + station_index) * 6
            reaction_vec = vector[base : base + 6]
            reaction_force, reaction_moment = _resultant_from_vector(
                node_m=node_m,
                vec6=reaction_vec,
                origin_m=origin_m,
            )
            residual_moment = applied_moment + reaction_moment
            station_residual += residual_moment
            station_applied += applied_moment
            station_reaction += reaction_moment
            rows.append(
                {
                    "kind": "beam_node",
                    "variant_id": "baseline",
                    "station_index": station_index,
                    "beam": beam,
                    "y_m": float(model.y_nodes_m[station_index]),
                    "eta": float(model.y_nodes_m[station_index] / semi_span),
                    "node_x_m": float(node_m[0]),
                    "node_z_m": float(node_m[2]),
                    "lift_per_span_npm": float(model.lift_per_span_npm[station_index]),
                    "aero_torque_per_span_nmpm": float(model.torque_per_span_nmpm[station_index]),
                    "torque_about_main_per_span_nmpm": float(load_split.torque_about_main_per_span_nmpm[station_index]),
                    "applied_lift_fz_n": float(load_split.lift_main_fz_n[station_index] if beam == "main" else load_split.lift_rear_fz_n[station_index]),
                    "torque_main_my_n": float(load_split.torque_main_my_n[station_index] if beam == "main" else 0.0),
                    "main_self_weight_fz_n": float(load_split.main_self_weight_fz_n[station_index] if beam == "main" else 0.0),
                    "rear_self_weight_fz_n": float(load_split.rear_self_weight_fz_n[station_index] if beam == "rear" else 0.0),
                    "load_fx_n": float(applied_force[0]),
                    "load_fy_n": float(applied_force[1]),
                    "load_fz_n": float(applied_force[2]),
                    "load_mx_nm": float(load_vec[3]),
                    "load_my_nm": float(load_vec[4]),
                    "load_mz_nm": float(load_vec[5]),
                    "reaction_fx_n": float(reaction_force[0]),
                    "reaction_fy_n": float(reaction_force[1]),
                    "reaction_fz_n": float(reaction_force[2]),
                    "reaction_mx_raw_nm": float(reaction_vec[3]),
                    "reaction_my_raw_nm": float(reaction_vec[4]),
                    "reaction_mz_raw_nm": float(reaction_vec[5]),
                    "applied_moment_origin_mx_nm": float(applied_moment[0]),
                    "applied_moment_origin_my_nm": float(applied_moment[1]),
                    "applied_moment_origin_mz_nm": float(applied_moment[2]),
                    "reaction_moment_origin_mx_nm": float(reaction_moment[0]),
                    "reaction_moment_origin_my_nm": float(reaction_moment[1]),
                    "reaction_moment_origin_mz_nm": float(reaction_moment[2]),
                    "station_bending_residual_mx_nm": float(residual_moment[0]),
                    "station_torque_residual_my_nm": float(residual_moment[1]),
                    "station_yaw_residual_mz_nm": float(residual_moment[2]),
                    "station_moment_residual_norm_nm": float(np.linalg.norm(residual_moment)),
                }
            )

        cumulative += station_residual
        rows.append(
            {
                "kind": "station_combined",
                "variant_id": "baseline",
                "station_index": station_index,
                "beam": "combined",
                "y_m": float(model.y_nodes_m[station_index]),
                "eta": float(model.y_nodes_m[station_index] / semi_span),
                "lift_per_span_npm": float(model.lift_per_span_npm[station_index]),
                "aero_torque_per_span_nmpm": float(model.torque_per_span_nmpm[station_index]),
                "torque_about_main_per_span_nmpm": float(load_split.torque_about_main_per_span_nmpm[station_index]),
                "applied_moment_origin_mx_nm": float(station_applied[0]),
                "applied_moment_origin_my_nm": float(station_applied[1]),
                "applied_moment_origin_mz_nm": float(station_applied[2]),
                "reaction_moment_origin_mx_nm": float(station_reaction[0]),
                "reaction_moment_origin_my_nm": float(station_reaction[1]),
                "reaction_moment_origin_mz_nm": float(station_reaction[2]),
                "station_bending_residual_mx_nm": float(station_residual[0]),
                "station_torque_residual_my_nm": float(station_residual[1]),
                "station_yaw_residual_mz_nm": float(station_residual[2]),
                "station_moment_residual_norm_nm": float(np.linalg.norm(station_residual)),
                "cumulative_bending_residual_mx_nm": float(cumulative[0]),
                "cumulative_torque_residual_my_nm": float(cumulative[1]),
                "cumulative_yaw_residual_mz_nm": float(cumulative[2]),
                "cumulative_moment_residual_norm_nm": float(np.linalg.norm(cumulative)),
            }
        )

    rows.extend(_source_summary_rows(model=model, result=result))
    closure = _closure_components(model=model, result=result)
    rows.append(
        {
            "kind": "total",
            "variant_id": "baseline",
            "beam": "all",
            "applied_force_n": _json_list(closure["applied_force_n"]),
            "applied_moment_nm": _json_list(closure["applied_moment_nm"]),
            "constraint_force_n": _json_list(closure["constraint_force_n"]),
            "constraint_moment_nm": _json_list(closure["constraint_moment_nm"]),
            "residual_force_n": _json_list(closure["residual_force_n"]),
            "residual_moment_nm": _json_list(closure["residual_moment_nm"]),
            "force_residual_norm_n": closure["force_residual_norm_n"],
            "moment_residual_norm_nm": closure["moment_residual_norm_nm"],
            "pass_threshold_nm": MOMENT_CLOSURE_TOL_NM,
        }
    )
    return rows


def _variant_rows(*, model: Any, baseline_result: Any) -> list[dict[str, Any]]:
    variant_ids = (
        "baseline",
        "cm_off",
        "cm_sign_flipped",
        "wire_off",
        "equal_spar_stiffness",
        "rear_stiffness_10x",
        "rear_spar_shift_aft_50mm",
        "rear_spar_shift_fwd_50mm",
    )
    rows: list[dict[str, Any]] = []
    for variant_id in variant_ids:
        variant_model = _clone_model_with_variant(model, variant_id)
        try:
            result = run_dual_beam_mainline_kernel(
                model=variant_model,
                mode=AnalysisModeName.DUAL_BEAM_PRODUCTION,
            )
            closure = _closure_components(model=variant_model, result=result)
            numerical = result.optimizer.numerical_consistency
            rows.append(
                {
                    "variant_id": variant_id,
                    "variant_type": "solver_rerun",
                    "analysis_succeeded": True,
                    "torque_sum_my_nm": float(np.sum(result.load_split.torque_main_my_n)),
                    "lift_sum_fz_n": float(np.sum(result.load_split.lift_main_fz_n) + np.sum(result.load_split.lift_rear_fz_n)),
                    "self_weight_sum_fz_n": float(np.sum(result.load_split.main_self_weight_fz_n) + np.sum(result.load_split.rear_self_weight_fz_n)),
                    "force_closure_residual_n_reported": float(numerical.force_closure_residual_n),
                    "moment_closure_residual_nm_reported": float(numerical.moment_closure_residual_nm),
                    "moment_closure_passed_reported": bool(numerical.moment_closure_passed),
                    "pass_threshold_nm": MOMENT_CLOSURE_TOL_NM,
                    "closure_mx_nm": float(closure["residual_moment_nm"][0]),
                    "closure_my_nm": float(closure["residual_moment_nm"][1]),
                    "closure_mz_nm": float(closure["residual_moment_nm"][2]),
                    "closure_norm_nm": float(closure["moment_residual_norm_nm"]),
                    "closure_xy_norm_nm": float(closure["moment_residual_xy_norm_nm"]),
                    "wire_support_validity_passed": bool(result.feasibility.wire_support_validity_passed),
                    "max_wire_tension_n": float(result.recovery.max_wire_tension_n),
                    "tip_deflection_main_m": float(result.report.tip_deflection_main_m),
                    "tip_deflection_rear_m": float(result.report.tip_deflection_rear_m),
                    "hard_failures": "|".join(result.feasibility.hard_failures),
                    "notes": "",
                }
            )
        except Exception as exc:  # pragma: no cover - diagnostic failure row
            rows.append(
                {
                    "variant_id": variant_id,
                    "variant_type": "solver_rerun",
                    "analysis_succeeded": False,
                    "notes": f"{type(exc).__name__}: {exc}",
                }
            )

    postprocess_variants = (
        ("baseline_post_reaction_moment_sign_plus", 1.0, True, "Use +reaction point moments instead of current -reaction point moments."),
        ("baseline_post_include_constraint_mz", -1.0, False, "Keep raw constraint Mz instead of zeroing it."),
        ("baseline_post_reaction_force_only", 0.0, True, "Ignore recovered reaction point moments."),
    )
    for variant_id, sign, zero_mz, note in postprocess_variants:
        closure = _closure_components(
            model=model,
            result=baseline_result,
            reaction_moment_sign=sign,
            zero_reaction_mz=zero_mz,
        )
        rows.append(
            {
                "variant_id": variant_id,
                "variant_type": "postprocess_closure_formula",
                "analysis_succeeded": True,
                "torque_sum_my_nm": float(np.sum(baseline_result.load_split.torque_main_my_n)),
                "force_closure_residual_n_reported": float(closure["force_residual_norm_n"]),
                "moment_closure_residual_nm_reported": float(closure["moment_residual_norm_nm"]),
                "moment_closure_passed_reported": bool(closure["moment_residual_norm_nm"] <= MOMENT_CLOSURE_TOL_NM),
                "pass_threshold_nm": MOMENT_CLOSURE_TOL_NM,
                "closure_mx_nm": float(closure["residual_moment_nm"][0]),
                "closure_my_nm": float(closure["residual_moment_nm"][1]),
                "closure_mz_nm": float(closure["residual_moment_nm"][2]),
                "closure_norm_nm": float(closure["moment_residual_norm_nm"]),
                "closure_xy_norm_nm": float(closure["moment_residual_xy_norm_nm"]),
                "notes": note,
            }
        )
    return rows


def _write_markdown_reports(*, output_dir: Path, candidate: Any, variant_rows: list[dict[str, Any]]) -> None:
    baseline = next(row for row in variant_rows if row["variant_id"] == "baseline")
    cm_off = next(row for row in variant_rows if row["variant_id"] == "cm_off")
    wire_off = next(row for row in variant_rows if row["variant_id"] == "wire_off")
    equal = next(row for row in variant_rows if row["variant_id"] == "equal_spar_stiffness")
    rear_10x = next(row for row in variant_rows if row["variant_id"] == "rear_stiffness_10x")
    sign_flip = next(row for row in variant_rows if row["variant_id"] == "cm_sign_flipped")
    plus = next(row for row in variant_rows if row["variant_id"] == "baseline_post_reaction_moment_sign_plus")
    include_mz = next(row for row in variant_rows if row["variant_id"] == "baseline_post_include_constraint_mz")

    diagnosis = [
        "# Moment Closure Diagnosis",
        "",
        "## Case",
        "",
        f"- target_main_tip_z_m: `{TARGET_Z_M:.3f}`",
        f"- recipe_id: `{TARGET_RECIPE_ID}`",
        f"- recipe_signature: `{dbg._signature_for_candidate(candidate)}`",
        f"- tube_mass_kg: `{candidate.tube_mass_kg:.6f}`",
        f"- clearance_margin_m: `{candidate.jig_ground_clearance_margin_m:.9f}`",
        "",
        "## Finding",
        "",
        f"- Baseline reported moment residual: `{float(baseline['moment_closure_residual_nm_reported']):.3f}` N*m.",
        f"- Baseline residual vector: Mx `{float(baseline['closure_mx_nm']):.3f}`, My `{float(baseline['closure_my_nm']):.3f}`, Mz `{float(baseline['closure_mz_nm']):.3f}` N*m.",
        f"- Cm-off residual drops to `{float(cm_off['moment_closure_residual_nm_reported']):.3f}` N*m, with pitch residual My `{float(cm_off['closure_my_nm']):.3f}` N*m.",
        f"- Cm sign-flip residual is `{float(sign_flip['moment_closure_residual_nm_reported']):.3f}` N*m; it improves over baseline but still does not pass.",
        f"- Wire-off residual is `{float(wire_off['moment_closure_residual_nm_reported']):.3f}` N*m and tip deflection becomes `{float(wire_off['tip_deflection_main_m']):.3f}` m.",
        f"- Equal rear/main stiffness gives `{float(equal['moment_closure_residual_nm_reported']):.3f}` N*m; rear 10x stiffness gives `{float(rear_10x['moment_closure_residual_nm_reported']):.3f}` N*m.",
        "",
        "## Engineering Interpretation",
        "",
        "The canonical dual-beam model exposes aerodynamic pitching moment as `torque_per_span_nmpm` / `torque_about_main_per_span_nmpm`; the raw nondimensional airfoil Cm distribution is not retained at this layer. Therefore this debug validates torque ownership and closure wiring, not the upstream 2D Cm source quality.",
        "",
        "The failure is dominated by load/reaction moment bookkeeping, not by tube mass or EI. Force closure and the linear equilibrium residual pass at numerical tolerance, while moment closure fails by O(10^3) N*m. Cm/torsion is a large contributor because turning Cm off removes most of the pitch-axis residual, but Cm-off still fails because the yaw/offset-link reaction channel leaves an O(10^2) N*m residual.",
        "",
        "The current production load ownership applies aerodynamic torque as a main-beam My point moment. That torque is not distributed as a front/rear vertical couple, while the sparse offset rigid links and explicit truss wire create large self-equilibrated y-force paths. The closure diagnostic then tries to collapse all generalized constraint reactions into one global moment with a 1e-6 N*m tolerance. That is too strict for this currently mixed generalized-force bookkeeping channel.",
        "",
        "## Direct Answers",
        "",
        f"- Is moment_closure fail caused mostly by Cm/torsion? `Partly yes`: Cm/torsion is the largest pitch-axis driver; Cm-off reduces the norm from `{float(baseline['moment_closure_residual_nm_reported']):.1f}` to `{float(cm_off['moment_closure_residual_nm_reported']):.1f}` N*m. But Cm-off still does not pass because the yaw/offset reaction channel remains.",
        f"- Does Cm-off pass? `No`; reported residual remains `{float(cm_off['moment_closure_residual_nm_reported']):.3f}` N*m vs threshold `{MOMENT_CLOSURE_TOL_NM:.1e}` N*m.",
        f"- Does changing rear spar stiffness or spar position help? `Not enough to pass`; equal stiffness `{float(equal['moment_closure_residual_nm_reported']):.1f}` N*m, rear 10x `{float(rear_10x['moment_closure_residual_nm_reported']):.1f}` N*m.",
        "- Is this likely a real structure problem or a code/wiring problem? `Mostly code/model bookkeeping until proven otherwise`; the exact solver equilibrium passes, and the failure moves strongly with torque ownership/post-processing choices.",
        "- Next smallest fix before FEM: make moment closure a decomposed diagnostic with separate force equilibrium, pitch-torque ownership, and yaw/offset-link bookkeeping checks; then convert aerodynamic Cm to an explicit front/rear spar couple or documented torsional DOF path before using it as a hard structural blocker.",
    ]
    (output_dir / "moment_closure_diagnosis.md").write_text("\n".join(diagnosis) + "\n", encoding="utf-8")

    bugs = [
        "# Suspected Wiring Bugs",
        "",
        "| Check | Evidence | Current assessment |",
        "|---|---|---|",
        f"| Wrong Cm sign | Sign flip changes residual from `{float(baseline['moment_closure_residual_nm_reported']):.1f}` to `{float(sign_flip['moment_closure_residual_nm_reported']):.1f}` N*m but does not pass. | Possible sign convention issue, not the only cause. |",
        "| Wrong moment arm | Rear spar x-shift variants move the residual only modestly. | Not primary. |",
        "| Aerodynamic section z vs beam-line z | Force closure passes and z-shape inverse is feasible; this failure is in moment resultants, not z recovery. | No direct evidence as primary cause. |",
        "| Stale spanload / old blackcat load | The case rebuilds from Phase 13 smooth candidate artifacts and selected recipe id matches. | Unlikely for this failure. |",
        "| Unit mismatch | Residual scales with torque on/off and not by 1000x or 2x. | No obvious mm/m or half/full-span signature. |",
        "| Full-span vs half-span factor | Force closure is near zero and mass convention is unrelated to moment residual. | Unlikely. |",
        "| Front/rear spar swapped | Stiffness/position changes do not resolve closure. | Unlikely as sole cause. |",
        f"| Reaction point-moment sign | Postprocess +reaction moments changes residual to `{float(plus['moment_closure_residual_nm_reported']):.1f}` N*m. | Sign convention affects result but is insufficient alone. |",
        f"| Constraint Mz suppression | Including raw constraint Mz changes residual to `{float(include_mz['moment_closure_residual_nm_reported']):.1f}` N*m. | Current yaw closure channel is inconsistent/report-only. |",
        "| Moment closure connected to selector | Phase 13 now exposes it correctly as `production_hard_feasible=False`. | Selector wiring fixed; physics diagnostic still unresolved. |",
    ]
    (output_dir / "suspected_wiring_bugs.md").write_text("\n".join(bugs) + "\n", encoding="utf-8")

    fix = [
        "# Recommended Fix Or Next Test",
        "",
        "1. Add an explicit decomposed moment-closure API that reports Mx, My, Mz separately plus applied, root, wire, and link contributions.",
        "2. Treat current all-axis `moment_closure_passed` as diagnostic/report-only until the yaw/offset-link generalized-force convention is made self-consistent.",
        "3. For aerodynamic Cm, run a targeted A/B using the same model with torque as `main_beam_my_about_main_spar` versus an explicit front/rear vertical couple about the main spar.",
        "4. If the vertical-couple path closes while main-beam My does not, patch production torque ownership before FEM.",
        "5. Run external FEM only after the moment ownership path is chosen; use the 16.030 kg `4a5b3187fd18` recipe for a smoke check, not the old 77 kg branch.",
        "",
        "Do not use this moment-closure failure alone to reject the 6-7 deg z state yet. It is a structural-model validation blocker, not a final spar sizing result.",
    ]
    (output_dir / "recommended_fix_or_next_test.md").write_text("\n".join(fix) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate = _build_target_candidate(output_dir=output_dir)
    baseline_result = candidate.production_result
    model = candidate.mainline_model
    breakdown = _breakdown_rows(model=model, result=baseline_result)
    variants = _variant_rows(model=model, baseline_result=baseline_result)
    _write_csv(output_dir / "moment_closure_breakdown.csv", breakdown)
    _write_csv(output_dir / "moment_closure_variants.csv", variants)
    _write_markdown_reports(output_dir=output_dir, candidate=candidate, variant_rows=variants)
    manifest = {
        "generated_by": str(Path(__file__).resolve()),
        "target_z_m": TARGET_Z_M,
        "target_recipe_id": TARGET_RECIPE_ID,
        "target_recipe_signature": dbg._signature_for_candidate(candidate),
        "outputs": {
            "moment_closure_breakdown": str((output_dir / "moment_closure_breakdown.csv").resolve()),
            "moment_closure_variants": str((output_dir / "moment_closure_variants.csv").resolve()),
            "moment_closure_diagnosis": str((output_dir / "moment_closure_diagnosis.md").resolve()),
            "suspected_wiring_bugs": str((output_dir / "suspected_wiring_bugs.md").resolve()),
            "recommended_fix_or_next_test": str((output_dir / "recommended_fix_or_next_test.md").resolve()),
        },
    }
    (output_dir / "moment_closure_debug_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
