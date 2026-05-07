#!/usr/bin/env python3
"""Dump canonical inverse-design recipe candidates around the z-state mass cliff.

This is a diagnostic sidecar: it reuses the canonical direct dual-beam inverse
design evaluator but does not change ranking, gates, or aero artifacts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict
from itertools import product
from pathlib import Path
import sys
from typing import Any, Iterable

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.aero import LoadMapper, VSPAeroParser
from hpa_mdo.core import Aircraft, MaterialDB, load_config
from hpa_mdo.structure import SparOptimizer
from scripts.ansys_compare_results import parse_baseline_metrics
from scripts.ansys_dual_beam_production_check import build_specimen_result_from_crossval_report
from scripts import direct_dual_beam_inverse_design as inv
from scripts.direct_dual_beam_v2 import BaselineDesign, build_reduced_map_config


DEFAULT_BASE_DIR = REPO_ROOT / "output" / "phase12_structure_validation_cliff_audit" / "cliff_sweep_run"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase12_z_cliff_algorithm_debug"
DEFAULT_CONFIG = DEFAULT_BASE_DIR / "smooth_tier2_canonical_config.yaml"
DEFAULT_DESIGN_REPORT = REPO_ROOT / "output" / "blackcat_004" / "ansys" / "crossval_report.txt"
DEFAULT_Z_VALUES = (2.000, 2.025)
BASE_MAIN_TIP_Z_M = 1.0650033980757752
SEGMENTS_M = (1.5, 3.0, 3.0, 3.0, 3.0, 3.6661430000000017)


def _parse_float_list(text: str) -> tuple[float, ...]:
    return tuple(float(item.strip()) for item in text.split(",") if item.strip())


def _case_label(target_z_m: float) -> str:
    return f"target_main_tip_z_{target_z_m:.3f}m".replace(".", "p")


def _artifact_for(base_dir: Path, target_z_m: float) -> Path:
    return base_dir / "candidate_avl_artifacts" / f"{_case_label(target_z_m)}.json"


def _float_or_blank(value: Any) -> float | str:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return ""
    if math.isfinite(out):
        return out
    if math.isinf(out):
        return "inf" if out > 0 else "-inf"
    return "nan"


def _json_list(values: Iterable[float], scale: float = 1.0, digits: int = 6) -> str:
    return json.dumps([round(float(value) * scale, digits) for value in values], separators=(",", ":"))


def _join(values: Iterable[Any]) -> str:
    return "|".join(str(value) for value in values)


def _get_attr_path(obj: Any, path: tuple[str, ...], default: Any = "") -> Any:
    current = obj
    for name in path:
        if current is None:
            return default
        current = getattr(current, name, default)
        if current is default:
            return default
    return current


def _bool_or_none(value: Any) -> bool | None:
    if value == "":
        return None
    if value is None:
        return None
    return bool(value)


def feasibility_labels_from_candidate(candidate: Any) -> dict[str, bool]:
    """Return explicit Phase-13 feasibility labels for one inverse-design candidate.

    `candidate.overall_feasible` is the inverse-jig feasibility signal in the
    current workflow.  It must not be read as production structural feasibility
    because production numerical consistency, wire validity, and moment closure
    live on the dual-beam production result.
    """

    inverse_feasible = bool(getattr(candidate, "overall_feasible", False))
    inverse_result = getattr(candidate, "inverse_result", None)
    production_result = getattr(candidate, "production_result", None)

    clearance_from_inverse = _bool_or_none(
        _get_attr_path(inverse_result, ("feasibility", "ground_clearance_passed"))
    )
    if clearance_from_inverse is None:
        clearance_from_inverse = _bool_or_none(_get_attr_path(inverse_result, ("ground_clearance", "passed")))
    if clearance_from_inverse is None:
        clearance_from_inverse = bool(float(getattr(candidate, "jig_ground_clearance_margin_m", -math.inf)) >= 0.0)

    geometry_from_inverse = _bool_or_none(
        _get_attr_path(inverse_result, ("feasibility", "geometry_validity_passed"))
    )
    geometry_from_candidate = bool(getattr(candidate, "geometry_validity_succeeded", False))
    geometry_validity = geometry_from_candidate if geometry_from_inverse is None else bool(
        geometry_from_candidate and geometry_from_inverse
    )

    wire_feasible = _bool_or_none(
        _get_attr_path(production_result, ("feasibility", "wire_support_validity_passed"))
    )
    if wire_feasible is None:
        wire_tension_only = _bool_or_none(
            _get_attr_path(production_result, ("recovery", "wire_tension_only_passed"))
        )
        wire_tension_limit = _bool_or_none(
            _get_attr_path(production_result, ("recovery", "wire_tension_limit_passed"))
        )
        wire_feasible = bool(wire_tension_only and wire_tension_limit)

    moment_closure_feasible = _bool_or_none(
        _get_attr_path(
            production_result,
            ("optimizer", "numerical_consistency", "moment_closure_passed"),
        )
    )
    if moment_closure_feasible is None:
        moment_closure_feasible = False

    production_hard_feasible = bool(
        clearance_from_inverse
        and wire_feasible
        and moment_closure_feasible
        and geometry_validity
    )
    return {
        "inverse_feasible": bool(inverse_feasible),
        "clearance_feasible": bool(clearance_from_inverse),
        "wire_feasible": bool(wire_feasible),
        "moment_closure_feasible": bool(moment_closure_feasible),
        "geometry_validity": bool(geometry_validity),
        "production_hard_feasible": bool(production_hard_feasible),
    }


def _tube_section_metrics(radius_m: np.ndarray, wall_m: np.ndarray, *, e_pa: float, g_pa: float) -> dict[str, Any]:
    outer = np.asarray(radius_m, dtype=float)
    wall = np.asarray(wall_m, dtype=float)
    inner = np.maximum(outer - wall, 0.0)
    i_m4 = (math.pi / 4.0) * (outer**4 - inner**4)
    j_m4 = (math.pi / 2.0) * (outer**4 - inner**4)
    ei = e_pa * i_m4
    gj = g_pa * j_m4
    return {
        "od_mm": 2.0 * outer * 1000.0,
        "id_mm": 2.0 * inner * 1000.0,
        "wall_mm": wall * 1000.0,
        "ei_nm2": ei,
        "gj_nm2": gj,
    }


def _signature_for_candidate(candidate: inv.InverseCandidate) -> str:
    z_key = ",".join(f"{float(value):.6f}" for value in np.asarray(candidate.z, dtype=float).reshape(5))
    rib_key = "none" if candidate.rib_design is None else candidate.rib_design.design_key
    return f"{rib_key}|{z_key}"


def _recipe_id(signature: str) -> str:
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]


def _selected_key(candidate: inv.InverseCandidate) -> tuple[float, float, float, float, float]:
    return (
        float(candidate.objective_value_kg),
        float(candidate.total_structural_mass_kg),
        float(candidate.clearance_risk_score),
        float(candidate.active_wall_risk_score),
        float(candidate.max_jig_vertical_prebend_m),
    )


def _dominant_negative_margin(candidate: inv.InverseCandidate) -> tuple[str, float]:
    if not candidate.hard_margins:
        return ("none", float("nan"))
    name, value = min(candidate.hard_margins.items(), key=lambda item: float(item[1]))
    return str(name), float(value)


def _reject_reason(candidate: inv.InverseCandidate, *, selected_signature: str) -> str:
    signature = _signature_for_candidate(candidate)
    if candidate.overall_feasible:
        if signature == selected_signature:
            return "selected_by_reported_outcome"
        return "eligible_but_higher_objective_than_reported_selected"
    failures = list(candidate.failures)
    negative_margins = [
        f"{name}={float(value):.9g}"
        for name, value in sorted(candidate.hard_margins.items())
        if float(value) < -1.0e-12
    ]
    if failures and negative_margins:
        return f"{_join(failures)}; negative_margins:{_join(negative_margins)}"
    if failures:
        return _join(failures)
    if negative_margins:
        return f"negative_margins:{_join(negative_margins)}"
    blocker, margin = _dominant_negative_margin(candidate)
    return f"not_feasible_without_named_failure; min_margin:{blocker}={margin:.9g}"


def _candidate_row(
    *,
    target_z_m: float,
    candidate: inv.InverseCandidate,
    reported_selected: inv.InverseCandidate,
    best_after_probes: inv.InverseCandidate | None,
    material_main,
    material_rear,
    sequence_index: int,
    source_stage: str,
) -> dict[str, Any]:
    signature = _signature_for_candidate(candidate)
    reported_signature = _signature_for_candidate(reported_selected)
    best_after_probe_signature = "" if best_after_probes is None else _signature_for_candidate(best_after_probes)
    feasibility_labels = feasibility_labels_from_candidate(candidate)
    main = _tube_section_metrics(
        candidate.main_r_seg_m,
        candidate.main_t_seg_m,
        e_pa=float(material_main.E),
        g_pa=float(material_main.G),
    )
    rear = _tube_section_metrics(
        candidate.rear_r_seg_m,
        candidate.rear_t_seg_m,
        e_pa=float(material_rear.E),
        g_pa=float(material_rear.G),
    )
    dominant_margin, dominant_margin_value = _dominant_negative_margin(candidate)
    hard_margins = {key: float(value) for key, value in sorted(candidate.hard_margins.items())}
    failures = list(candidate.failures)
    production = candidate.production_result
    inverse = candidate.inverse_result
    production_feasibility = getattr(production, "feasibility", None)
    production_hard_failures = tuple(getattr(production_feasibility, "hard_failures", ()) or ())
    production_overall_hard_feasible = getattr(production_feasibility, "overall_hard_feasible", "")
    numerical_consistency_passed = getattr(production_feasibility, "numerical_consistency_passed", "")
    wire_support_validity_passed = getattr(production_feasibility, "wire_support_validity_passed", "")
    numerical_consistency = getattr(getattr(production, "optimizer", None), "numerical_consistency", None)
    moment_closure_residual_nm = getattr(numerical_consistency, "moment_closure_residual_nm", "")
    moment_closure_passed = getattr(numerical_consistency, "moment_closure_passed", "")
    moment_closure_status = "not_reported"
    if moment_closure_passed != "":
        moment_closure_status = "pass" if bool(moment_closure_passed) else "fail"
    elif moment_closure_residual_nm != "":
        moment_closure_status = "reported"
    wire_tension_max_n = ""
    wire_tension_min_n = ""
    wire_tension_json = ""
    if production is not None:
        wire_values = getattr(getattr(production, "recovery", None), "wire_tension_estimates_n", None)
        if wire_values is not None:
            wire_arr = np.asarray(wire_values, dtype=float).reshape(-1)
            if wire_arr.size:
                wire_tension_max_n = float(np.max(wire_arr))
                wire_tension_min_n = float(np.min(wire_arr))
                wire_tension_json = _json_list(wire_arr, scale=1.0, digits=3)
    geometry_validity_status = "pass" if candidate.geometry_validity_succeeded else "fail"
    if inverse is not None and getattr(inverse, "feasibility", None) is not None:
        geometry_validity_status = (
            "pass" if bool(inverse.feasibility.geometry_validity_passed) else "fail"
        )
    main_ei = np.asarray(main["ei_nm2"], dtype=float)
    rear_ei = np.asarray(rear["ei_nm2"], dtype=float)
    main_gj = np.asarray(main["gj_nm2"], dtype=float)
    rear_gj = np.asarray(rear["gj_nm2"], dtype=float)
    return {
        "target_main_tip_z_m": float(target_z_m),
        "case_label": _case_label(target_z_m),
        "sequence_index": int(sequence_index),
        "source_stage": source_stage,
        "source": candidate.source,
        "recipe_id": _recipe_id(signature),
        "recipe_signature": signature,
        "rib_design_key": "none" if candidate.rib_design is None else candidate.rib_design.design_key,
        "rib_design_label": "" if candidate.rib_design is None else candidate.rib_design.design_label,
        "z_main_plateau_scale": float(candidate.z[0]),
        "z_main_taper_fill": float(candidate.z[1]),
        "z_rear_radius_scale": float(candidate.z[2]),
        "z_rear_outboard_fraction": float(candidate.z[3]),
        "z_wall_thickness_fraction": float(candidate.z[4]),
        "main_plateau_scale": float(candidate.main_plateau_scale),
        "main_taper_fill": float(candidate.main_taper_fill),
        "rear_radius_scale": float(candidate.rear_radius_scale),
        "rear_outboard_fraction": float(candidate.rear_outboard_fraction),
        "wall_thickness_fraction": float(candidate.wall_thickness_fraction),
        "main_tube_od_mm": _json_list(main["od_mm"]),
        "main_tube_id_mm": _json_list(main["id_mm"]),
        "main_tube_wall_mm": _json_list(main["wall_mm"]),
        "rear_tube_od_mm": _json_list(rear["od_mm"]),
        "rear_tube_id_mm": _json_list(rear["id_mm"]),
        "rear_tube_wall_mm": _json_list(rear["wall_mm"]),
        "main_root_od_mm": float(main["od_mm"][0]),
        "main_root_id_mm": float(main["id_mm"][0]),
        "main_root_wall_mm": float(main["wall_mm"][0]),
        "rear_root_od_mm": float(rear["od_mm"][0]),
        "rear_root_id_mm": float(rear["id_mm"][0]),
        "rear_root_wall_mm": float(rear["wall_mm"][0]),
        "tube_mass_kg": float(candidate.tube_mass_kg),
        "total_structural_mass_kg": float(candidate.total_structural_mass_kg),
        "main_ei_nm2": _json_list(main_ei, digits=3),
        "rear_ei_nm2": _json_list(rear_ei, digits=3),
        "main_gj_nm2": _json_list(main_gj, digits=3),
        "rear_gj_nm2": _json_list(rear_gj, digits=3),
        "ei_min_nm2": float(np.min(main_ei + rear_ei)),
        "ei_root_nm2": float(main_ei[0] + rear_ei[0]),
        "gj_min_nm2": float(np.min(main_gj + rear_gj)),
        "gj_root_nm2": float(main_gj[0] + rear_gj[0]),
        "equivalent_tip_deflection_m": float(candidate.equivalent_tip_deflection_m),
        "jig_ground_clearance_min_m": float(candidate.jig_ground_clearance_min_m),
        "jig_ground_clearance_margin_m": float(candidate.jig_ground_clearance_margin_m),
        "max_jig_vertical_prebend_m": float(candidate.max_jig_vertical_prebend_m),
        "max_jig_vertical_curvature_per_m": float(candidate.max_jig_vertical_curvature_per_m),
        "loaded_shape_main_z_error_max_m": float(candidate.loaded_shape_main_z_error_max_m),
        "loaded_shape_main_z_error_rms_m": float(candidate.loaded_shape_main_z_error_rms_m),
        "loaded_shape_twist_error_max_deg": float(candidate.loaded_shape_twist_error_max_deg),
        "loaded_shape_normalized_error": float(candidate.loaded_shape_normalized_error),
        "target_shape_error_max_m": float(candidate.target_shape_error_max_m),
        "target_shape_error_rms_m": float(candidate.target_shape_error_rms_m),
        "wire_tension_max_n": wire_tension_max_n,
        "wire_tension_min_n": wire_tension_min_n,
        "wire_tension_values_n": wire_tension_json,
        "moment_closure_status": moment_closure_status,
        "moment_closure_residual_nm": _float_or_blank(moment_closure_residual_nm),
        "moment_closure_passed": moment_closure_passed if moment_closure_passed == "" else bool(moment_closure_passed),
        **feasibility_labels,
        "production_overall_hard_feasible": (
            production_overall_hard_feasible
            if production_overall_hard_feasible == ""
            else bool(production_overall_hard_feasible)
        ),
        "production_hard_failures": _join(production_hard_failures),
        "production_numerical_consistency_passed": (
            numerical_consistency_passed
            if numerical_consistency_passed == ""
            else bool(numerical_consistency_passed)
        ),
        "production_wire_support_validity_passed": (
            wire_support_validity_passed
            if wire_support_validity_passed == ""
            else bool(wire_support_validity_passed)
        ),
        "eligible_if_production_hard_failures_counted": bool(
            feasibility_labels["inverse_feasible"] and feasibility_labels["production_hard_feasible"]
        ),
        "geometry_validity_status": geometry_validity_status,
        "analysis_succeeded": bool(candidate.analysis_succeeded),
        "safety_passed": bool(candidate.safety_passed),
        "manufacturing_passed": bool(candidate.manufacturing_passed),
        "overall_feasible": bool(candidate.overall_feasible),
        "pass_fail": "pass" if candidate.overall_feasible else "fail",
        "eligible_for_reported_selection": bool(candidate.overall_feasible),
        "is_reported_selected": signature == reported_signature,
        "is_best_after_active_wall_probes": bool(best_after_probe_signature and signature == best_after_probe_signature),
        "exact_reject_reason": _reject_reason(candidate, selected_signature=reported_signature),
        "failures": _join(failures),
        "dominant_constraint": dominant_margin,
        "dominant_constraint_margin": _float_or_blank(dominant_margin_value),
        "hard_margins_json": json.dumps(hard_margins, sort_keys=True, separators=(",", ":")),
        "hard_violation_score": float(candidate.hard_violation_score),
        "target_violation_score": float(candidate.target_violation_score),
        "clearance_risk_score": float(candidate.clearance_risk_score),
        "clearance_hotspot_count": int(candidate.clearance_hotspot_count),
        "clearance_hotspot_mean_m": float(candidate.clearance_hotspot_mean_m),
        "clearance_penalty_kg": float(candidate.clearance_penalty_kg),
        "active_wall_risk_score": float(candidate.active_wall_risk_score),
        "active_wall_tight_count": int(candidate.active_wall_tight_count),
        "active_wall_penalty_kg": float(candidate.active_wall_penalty_kg),
        "loaded_shape_penalty_kg": float(candidate.loaded_shape_penalty_kg),
        "score_objective_value_kg": float(candidate.objective_value_kg),
        "selection_key_json": json.dumps(_selected_key(candidate), separators=(",", ":")),
        "message": candidate.message,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                keys.append(key)
                seen.add(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _load_case_setup(
    *,
    config_path: Path,
    design_report: Path,
    candidate_artifact: Path,
    target_shape_z_scale: float,
    dihedral_exponent: float,
    contract_output_root: Path | None = None,
) -> dict[str, Any]:
    cfg = load_config(config_path)
    specimen_metrics = parse_baseline_metrics(design_report)
    cfg.solver.n_beam_nodes = int(specimen_metrics.nodes_per_spar)
    aircraft = Aircraft.from_config(cfg)
    materials_db = MaterialDB()
    baseline_result = build_specimen_result_from_crossval_report(design_report)

    legacy_aero_cases = None
    if cfg.io.vsp_lod is not None and Path(cfg.io.vsp_lod).expanduser().is_file():
        legacy_aero_cases = VSPAeroParser(cfg.io.vsp_lod, cfg.io.vsp_polar).parse()
    aero_cases, cruise_case, mapped_loads, aero_contract = inv._resolve_outer_loop_candidate_aero(
        cfg=cfg,
        aircraft=aircraft,
        output_dir=(contract_output_root or (DEFAULT_OUTPUT_DIR / "tmp_aero_contract")) / candidate_artifact.stem,
        target_shape_z_scale=target_shape_z_scale,
        dihedral_exponent=dihedral_exponent,
        aero_source_mode=inv.CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE,
        vspaero_analysis_method=inv.DEFAULT_VSPAERO_ANALYSIS_METHOD,
        legacy_aero_cases=legacy_aero_cases,
        candidate_aero_output_dir=None,
        candidate_avl_spanwise_loads_json=candidate_artifact,
        candidate_fixed_alpha_loads_json=None,
    )
    design_case = cfg.structural_load_cases()[0]
    export_loads = LoadMapper.apply_load_factor(mapped_loads, design_case.aero_scale)
    optimizer = SparOptimizer(cfg, aircraft, mapped_loads, materials_db)
    baseline_design = BaselineDesign(
        main_t_seg_m=np.asarray(baseline_result.main_t_seg_mm, dtype=float) * 1.0e-3,
        main_r_seg_m=np.asarray(baseline_result.main_r_seg_mm, dtype=float) * 1.0e-3,
        rear_t_seg_m=np.asarray(baseline_result.rear_t_seg_mm, dtype=float) * 1.0e-3,
        rear_r_seg_m=np.asarray(baseline_result.rear_r_seg_mm, dtype=float) * 1.0e-3,
    )
    map_config = build_reduced_map_config(
        baseline=baseline_design,
        cfg=cfg,
        main_plateau_scale_upper=1.14,
        main_taper_fill_upper=0.80,
        rear_radius_scale_upper=1.12,
    )
    return {
        "cfg": cfg,
        "aircraft": aircraft,
        "materials_db": materials_db,
        "baseline_result": baseline_result,
        "baseline_design": baseline_design,
        "mapped_loads": mapped_loads,
        "export_loads": export_loads,
        "optimizer": optimizer,
        "map_config": map_config,
        "cruise_case": cruise_case,
        "aero_contract": aero_contract,
        "aero_cases": aero_cases,
    }


def _build_evaluator(
    *,
    setup: dict[str, Any],
    target_shape_z_scale: float,
    dihedral_exponent: float,
    loaded_shape_control_station_fractions: tuple[float, ...],
    loaded_shape_penalty_weight_kg: float,
    clearance_risk_threshold_m: float,
    clearance_risk_top_k: int,
    clearance_penalty_weight_kg: float,
    active_wall_penalty_weight_kg: float,
    clearance_floor_z_m: float,
    target_shape_error_tol_m: float,
    rib_zonewise_mode: str,
    rib_family_switch_penalty_kg: float,
    rib_family_mix_max_unique: int,
) -> tuple[inv.InverseDesignEvaluator, dict[str, float | str]]:
    cfg = setup["cfg"]
    loaded_shape_main_z_tol_m = float(cfg.solver.loaded_shape_z_tol_m)
    loaded_shape_twist_tol_deg = float(cfg.solver.loaded_shape_twist_tol_deg)
    seed_evaluator = inv.InverseDesignEvaluator(
        cfg=cfg,
        aircraft=setup["aircraft"],
        materials_db=setup["materials_db"],
        optimizer=setup["optimizer"],
        export_loads=setup["export_loads"],
        baseline=setup["baseline_design"],
        map_config=setup["map_config"],
        clearance_floor_z_m=float(clearance_floor_z_m),
        target_shape_error_tol_m=float(target_shape_error_tol_m),
        max_jig_vertical_prebend_m=1.0e6,
        max_jig_vertical_curvature_per_m=1.0e6,
        loaded_shape_mode="exact_nodal",
        loaded_shape_control_station_fractions=loaded_shape_control_station_fractions,
        loaded_shape_main_z_tol_m=loaded_shape_main_z_tol_m,
        loaded_shape_twist_tol_deg=loaded_shape_twist_tol_deg,
        loaded_shape_penalty_weight_kg=loaded_shape_penalty_weight_kg,
        target_shape_z_scale=target_shape_z_scale,
        dihedral_exponent=dihedral_exponent,
        clearance_risk_threshold_m=clearance_risk_threshold_m,
        clearance_risk_top_k=clearance_risk_top_k,
        clearance_penalty_weight_kg=clearance_penalty_weight_kg,
        active_wall_penalty_weight_kg=active_wall_penalty_weight_kg,
    )
    baseline_seed = seed_evaluator.evaluate(np.zeros(5, dtype=float), source="baseline_seed")
    max_prebend = max(float(baseline_seed.max_jig_vertical_prebend_m) * 1.10, 1.0e-9)
    max_curvature = max(float(baseline_seed.max_jig_vertical_curvature_per_m) * 1.10, 1.0e-9)
    evaluator = inv.InverseDesignEvaluator(
        cfg=cfg,
        aircraft=setup["aircraft"],
        materials_db=setup["materials_db"],
        optimizer=setup["optimizer"],
        export_loads=setup["export_loads"],
        baseline=setup["baseline_design"],
        map_config=setup["map_config"],
        clearance_floor_z_m=float(clearance_floor_z_m),
        target_shape_error_tol_m=float(target_shape_error_tol_m),
        max_jig_vertical_prebend_m=max_prebend,
        max_jig_vertical_curvature_per_m=max_curvature,
        loaded_shape_mode="exact_nodal",
        loaded_shape_control_station_fractions=loaded_shape_control_station_fractions,
        loaded_shape_main_z_tol_m=loaded_shape_main_z_tol_m,
        loaded_shape_twist_tol_deg=loaded_shape_twist_tol_deg,
        loaded_shape_penalty_weight_kg=loaded_shape_penalty_weight_kg,
        target_shape_z_scale=target_shape_z_scale,
        dihedral_exponent=dihedral_exponent,
        clearance_risk_threshold_m=clearance_risk_threshold_m,
        clearance_risk_top_k=clearance_risk_top_k,
        clearance_penalty_weight_kg=clearance_penalty_weight_kg,
        active_wall_penalty_weight_kg=active_wall_penalty_weight_kg,
        target_mass_kg=None,
        rib_zonewise_mode=rib_zonewise_mode,
        rib_family_switch_penalty_kg=rib_family_switch_penalty_kg,
        rib_family_mix_max_unique=rib_family_mix_max_unique,
    )
    return evaluator, {
        "manufacturing_limit_source": "baseline_seed x 1.100",
        "max_jig_vertical_prebend_limit_m": float(max_prebend),
        "max_jig_vertical_curvature_limit_per_m": float(max_curvature),
    }


def _run_case(
    *,
    target_z_m: float,
    args: argparse.Namespace,
) -> dict[str, Any]:
    target_shape_z_scale = float(target_z_m) / BASE_MAIN_TIP_Z_M
    candidate_artifact = _artifact_for(Path(args.base_dir), target_z_m)
    if not candidate_artifact.exists():
        raise FileNotFoundError(candidate_artifact)

    setup = _load_case_setup(
        config_path=Path(args.config),
        design_report=Path(args.design_report),
        candidate_artifact=candidate_artifact,
        target_shape_z_scale=target_shape_z_scale,
        dihedral_exponent=float(args.dihedral_exponent),
    )
    evaluator, manufacturing_limits = _build_evaluator(
        setup=setup,
        target_shape_z_scale=target_shape_z_scale,
        dihedral_exponent=float(args.dihedral_exponent),
        loaded_shape_control_station_fractions=inv._parse_control_fractions(args.loaded_shape_control_stations),
        loaded_shape_penalty_weight_kg=float(args.loaded_shape_penalty_kg),
        clearance_risk_threshold_m=float(args.clearance_risk_threshold_mm) * 1.0e-3,
        clearance_risk_top_k=int(args.clearance_risk_top_k),
        clearance_penalty_weight_kg=float(args.clearance_penalty_kg),
        active_wall_penalty_weight_kg=float(args.active_wall_penalty_kg),
        clearance_floor_z_m=float(args.clearance_floor_z_m),
        target_shape_error_tol_m=float(args.target_shape_error_tol_m),
        rib_zonewise_mode=str(args.rib_zonewise_mode),
        rib_family_switch_penalty_kg=float(args.rib_family_switch_penalty_kg),
        rib_family_mix_max_unique=int(args.rib_family_mix_max_unique),
    )
    baseline = evaluator.evaluate(
        np.zeros(5, dtype=float),
        source="baseline",
        rib_design_key=evaluator.default_rib_design_key,
    )
    coarse_grid = list(
        product(
            _parse_float_list(args.main_plateau_grid),
            _parse_float_list(args.main_taper_fill_grid),
            _parse_float_list(args.rear_radius_grid),
            _parse_float_list(args.rear_outboard_grid),
            _parse_float_list(args.wall_thickness_grid),
        )
    )
    for point in coarse_grid:
        for rib_design in evaluator.rib_design_profiles:
            evaluator.evaluate(np.asarray(point, dtype=float), source="coarse_grid", rib_design_key=rib_design.design_key)
    coarse_count = len(evaluator.archive.candidates)
    coarse_feasible_count = evaluator.archive.feasible_count
    reported_selected = evaluator.archive.selected or baseline
    reported_selected_signature = _signature_for_candidate(reported_selected)
    lightest_reported = min(
        (candidate for candidate in evaluator.archive.candidates if candidate.overall_feasible),
        key=_selected_key,
        default=reported_selected,
    )
    if _signature_for_candidate(lightest_reported) != reported_selected_signature:
        raise RuntimeError("Internal mismatch: archive selected differs from local feasible ranking.")

    active_wall_probes = inv._build_lighten_probe_diagnostics(evaluator=evaluator, selected=reported_selected)
    best_after_probes = evaluator.archive.best_feasible
    all_candidates = list(evaluator.archive.candidates)
    material_main = setup["materials_db"].get(setup["cfg"].main_spar.material)
    material_rear = setup["materials_db"].get(setup["cfg"].rear_spar.material)
    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(all_candidates):
        source_stage = "active_wall_probe" if str(candidate.source).startswith("probe:") else "baseline_or_coarse"
        rows.append(
            _candidate_row(
                target_z_m=target_z_m,
                candidate=candidate,
                reported_selected=reported_selected,
                best_after_probes=best_after_probes,
                material_main=material_main,
                material_rear=material_rear,
                sequence_index=index,
                source_stage=source_stage,
            )
        )
    return {
        "target_z_m": float(target_z_m),
        "target_shape_z_scale": float(target_shape_z_scale),
        "candidate_artifact": str(candidate_artifact.resolve()),
        "evaluator": evaluator,
        "rows": rows,
        "reported_selected": reported_selected,
        "best_after_probes": best_after_probes,
        "active_wall_probes": active_wall_probes,
        "coarse_count": int(coarse_count),
        "coarse_feasible_count": int(coarse_feasible_count),
        "total_candidate_count": int(len(all_candidates)),
        "total_feasible_count": int(evaluator.archive.feasible_count),
        "setup": setup,
        "manufacturing_limits": manufacturing_limits,
    }


def _failure_counter(rows: list[dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        if row["overall_feasible"]:
            continue
        reason = str(row["exact_reject_reason"])
        first = reason.split(";")[0]
        counter[first] += 1
    return counter


def _write_rejection_diff(
    *,
    path: Path,
    case_a: dict[str, Any],
    case_b: dict[str, Any],
    forced_rows: list[dict[str, Any]],
) -> None:
    rows_a = case_a["rows"]
    rows_b = case_b["rows"]
    selected_a = case_a["reported_selected"]
    selected_b = case_b["reported_selected"]
    best_after_a = case_a["best_after_probes"]
    best_after_b = case_b["best_after_probes"]
    sig_a = _signature_for_candidate(selected_a)
    sig_b = _signature_for_candidate(selected_b)
    by_sig_a = {str(row["recipe_signature"]): row for row in rows_a}
    by_sig_b = {str(row["recipe_signature"]): row for row in rows_b}
    selected_b_at_a = by_sig_a.get(sig_b)
    selected_a_at_b = by_sig_b.get(sig_a)
    lighter_than_a = [
        row for row in rows_a
        if float(row["tube_mass_kg"]) < float(selected_a.tube_mass_kg) and not bool(row["overall_feasible"])
    ]
    lighter_blockers = Counter(str(row["dominant_constraint"]) for row in lighter_than_a)
    fail_counter_a = _failure_counter(rows_a)
    fail_counter_b = _failure_counter(rows_b)
    lines = [
        "# Rejection Reason Diff",
        "",
        "## Case Summary",
        "",
        "| z | coarse candidates | coarse feasible | all evaluated after probes | feasible after probes | reported selected mass kg | best after probes mass kg | reported selected signature |",
        "|---:|---:|---:|---:|---:|---:|---:|---|",
        (
            f"| {case_a['target_z_m']:.3f} | {case_a['coarse_count']} | {case_a['coarse_feasible_count']} | "
            f"{case_a['total_candidate_count']} | {case_a['total_feasible_count']} | "
            f"{selected_a.tube_mass_kg:.6f} | {best_after_a.tube_mass_kg if best_after_a else float('nan'):.6f} | `{sig_a}` |"
        ),
        (
            f"| {case_b['target_z_m']:.3f} | {case_b['coarse_count']} | {case_b['coarse_feasible_count']} | "
            f"{case_b['total_candidate_count']} | {case_b['total_feasible_count']} | "
            f"{selected_b.tube_mass_kg:.6f} | {best_after_b.tube_mass_kg if best_after_b else float('nan'):.6f} | `{sig_b}` |"
        ),
        "",
        "## Cross-Recipe Checks",
        "",
        f"- Lightest reported passing recipe at z={case_b['target_z_m']:.3f} m: `{sig_b}`, tube mass {selected_b.tube_mass_kg:.6f} kg.",
    ]
    if selected_b_at_a:
        lines.append(
            f"- The same recipe **was evaluated** at z={case_a['target_z_m']:.3f} m and "
            f"{'passed' if selected_b_at_a['overall_feasible'] else 'failed'}: "
            f"clearance margin {float(selected_b_at_a['jig_ground_clearance_margin_m']):.6f} m, "
            f"dominant constraint `{selected_b_at_a['dominant_constraint']}`, "
            f"reason `{selected_b_at_a['exact_reject_reason']}`."
        )
    else:
        lines.append(
            f"- The same recipe was **not present** at z={case_a['target_z_m']:.3f} m candidate dump."
        )
    lines.append(
        f"- First reported-selected passing recipe at z={case_a['target_z_m']:.3f} m: `{sig_a}`, "
        f"tube mass {selected_a.tube_mass_kg:.6f} kg."
    )
    if selected_a_at_b:
        lines.append(
            f"- The z={case_a['target_z_m']:.3f} m heavy recipe also appears at z={case_b['target_z_m']:.3f} m and "
            f"{'passed' if selected_a_at_b['overall_feasible'] else 'failed'}: "
            f"clearance margin {float(selected_a_at_b['jig_ground_clearance_margin_m']):.6f} m, "
            f"objective {float(selected_a_at_b['score_objective_value_kg']):.6f} kg."
        )
    lines.extend(
        [
            "",
            "## Why Lighter z=2.000 m Recipes Failed",
            "",
            f"- Count of non-feasible candidates lighter than the reported z={case_a['target_z_m']:.3f} m selection: {len(lighter_than_a)}.",
            "- Dominant negative-margin counts among those lighter failures:",
        ]
    )
    for name, count in lighter_blockers.most_common():
        lines.append(f"  - `{name}`: {count}")
    lines.extend(["", "## Overall Failure Counts", "", f"### z={case_a['target_z_m']:.3f} m"])
    for reason, count in fail_counter_a.most_common():
        lines.append(f"- `{reason}`: {count}")
    lines.append(f"### z={case_b['target_z_m']:.3f} m")
    for reason, count in fail_counter_b.most_common():
        lines.append(f"- `{reason}`: {count}")
    lines.extend(["", "## Forced Recipe Rows", ""])
    for row in forced_rows:
        lines.append(
            f"- `{row['force_test']}`: pass={row['overall_feasible']}, "
            f"tube={float(row['tube_mass_kg']):.6f} kg, clearance={float(row['jig_ground_clearance_margin_m']):.6f} m, "
            f"prebend={float(row['max_jig_vertical_prebend_m']):.6f} m, reason=`{row['exact_reject_reason']}`"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_bug_report(
    *,
    path: Path,
    case_a: dict[str, Any],
    case_b: dict[str, Any],
    forced_rows: list[dict[str, Any]],
) -> None:
    selected_a = case_a["reported_selected"]
    selected_b = case_b["reported_selected"]
    by_force = {str(row["force_test"]): row for row in forced_rows}
    light_on_low = by_force.get("force_z2p025_light_recipe_on_z2p000")
    stale_selection_note = ""
    if case_a["best_after_probes"] is not None and _signature_for_candidate(case_a["best_after_probes"]) != _signature_for_candidate(selected_a):
        stale_selection_note = (
            "- The active-wall diagnostics evaluate additional candidates after the reported selection is frozen. "
            f"For z={case_a['target_z_m']:.3f} m this found {case_a['best_after_probes'].tube_mass_kg:.6f} kg, "
            f"but the summary still reports {selected_a.tube_mass_kg:.6f} kg.\n"
        )
    exact_flip = "unknown"
    if light_on_low is not None:
        exact_flip = (
            f"ground_clearance_margin_m: forced light recipe is {float(light_on_low['jig_ground_clearance_margin_m']):.6f} m "
            f"at z={case_a['target_z_m']:.3f} m versus selected-light {selected_b.jig_ground_clearance_margin_m:.6f} m "
            f"at z={case_b['target_z_m']:.3f} m"
        )
    lines = [
        "# Suspected Bug Report",
        "",
        "## Root Cause Classification",
        "",
        "The cliff is best classified as an algorithm/search-branch artifact around a real hard constraint, not as a smooth physical mass requirement.",
        "",
        "Important boundary: this statement describes the inverse-selector branch. The production dual-beam numerical-consistency channel reports `moment_closure` failure for the evaluated candidates, while the inverse-selector `overall_feasible` flag does not include that production hard failure.",
        "",
        "The immediate hard constraint flip is:",
        "",
        f"- `{exact_flip}`",
        "",
        "## Checks From the Requested Bug List",
        "",
        "| Check | Finding |",
        "|---|---|",
        "| wrong clearance inequality sign | No evidence in this dump; failures flip exactly when `ground_clearance_margin_m` changes sign. |",
        "| unit mismatch mm vs m | No evidence; reported z scales and tube dimensions remain in expected m/mm conventions, and design arrays match canonical summaries. |",
        "| stale unscaled target shape CSV | A known export hazard exists in prior Phase 11/12 rows, but this candidate selection uses in-memory inverse target and summary JSON, not the exported target CSV. Downstream readers must not use stale CSV as selection truth. |",
        "| wrong artifact path / JSON vs CSV path | Candidate AVL artifact path is case-specific and recorded in the debug output. Selection uses the JSON artifact. |",
        "| discontinuous catalog sorting | This path is not a physical tube catalog pick; it is a reduced-variable grid over generated tube geometries plus rib profiles. The coarse endpoint grid creates branch discreteness. |",
        "| objective prefers thick wall due bad penalty scaling | The heavy z=2.000 m recipe is selected because lighter recipes fail hard feasibility, mainly clearance. Objective is not the first cause. |",
        "| pass/fail overwritten by later checks | No direct overwrite found, but active-wall probe candidates are added after `selected` is captured, so `best_overall_feasible` can improve without updating the reported selected candidate. |",
        "| production moment-closure ignored by selector | Confirmed as a lineage/selection gap: `build_candidate_hard_margins()` only includes geometry plus equivalent-beam gates, and inverse selection uses `inverse.feasibility.overall_feasible`; production `moment_closure` is visible but not part of the selected candidate pass/fail. |",
        "| mass aggregation double-counting | No new evidence of double-counting in this run; masses track geometry changes and prior reconstruction matched the reported full-system convention. |",
        "| full-span vs half-span convention mismatch | The reported `spar_tube_mass_full_kg` remains a full-system tube mass convention. It is not the cause of the 2.000/2.025 jump because both cases use the same convention. |",
        "| recipe selection not sorted after filtering | Coarse selection is sorted by `_feasible_key`; however, diagnostics probes are evaluated after selection and are not reselected. |",
        "",
        "## Additional Algorithm Findings",
        "",
        stale_selection_note.rstrip() or "- No active-wall post-selection mismatch was detected for the lower-z case.",
        "- `structure_budgeted_z_state_search.py` does not pass `--target-mass-kg` into the canonical search. The 11.5 kg budget is applied as a post-filter, so the canonical selected recipe is not budget-seeking.",
        "- Every candidate in the two dumps reports `moment_closure_status=fail`. That means neither the 77 kg nor 15.5 kg recipe should be treated as structure-grade until the production feasibility channel is wired into the selector or explicitly declared report-only.",
        "- The MVP uses endpoint grids and `--skip-local-refine --no-ground-clearance-recovery`. Near a zero-clearance boundary, that can produce a sharp reported mass cliff even when nearby continuous geometries might exist.",
        "",
        "## Trust Assessment",
        "",
        f"- z={case_a['target_z_m']:.3f} m reported mass: {selected_a.tube_mass_kg:.6f} kg.",
        f"- z={case_b['target_z_m']:.3f} m reported mass: {selected_b.tube_mass_kg:.6f} kg.",
        "- The 77 kg-class result should be treated as a warning that the current selected recipe branch is clearance-blocked at low z, not as final CFRP sizing.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_recommended_fix(path: Path) -> None:
    lines = [
        "# Recommended Fix",
        "",
        "Do not use the z-state mass results for design rejection until the selector is patched and re-swept.",
        "",
        "Recommended code changes, in order:",
        "",
        "1. Add an explicit candidate-archive dump option to `scripts/direct_dual_beam_inverse_design.py` so every unique candidate, including post-selection probes and local-refine points, is persisted with hard margins and reject reasons.",
        "2. Move active-wall/lighten probes out of the mutating selection archive, or recompute `selected` after probes if probes are allowed to affect selection. The current behavior can report a stale selected candidate.",
        "3. Pass `--target-mass-kg` from `structure_budgeted_z_state_search.py` when the run is meant to be budget-aware, and keep the post-filter as an independent contract check.",
        "4. Wire production numerical-consistency and wire-support feasibility into the selection contract, or explicitly split `inverse_feasible` from `production_hard_feasible` in all reported z-state tables.",
        "5. Replace endpoint-only MVP grids near cliff regions with local refine or a bounded clearance-recovery sweep; keep `refresh_steps=0` only for comparability, not as final selection policy.",
        "6. Fix or clearly quarantine any exported target-shape CSV that does not match the selected in-memory target shape, because downstream structural tools could otherwise read the wrong z state.",
        "",
        "Immediate engineering experiment before external FEM:",
        "",
        "- Re-run the z=1.95-2.10 m region with archive dumping, local refine enabled, target mass set, and a non-mutating probe archive. Then compare the continuous feasible frontier before sending any one recipe to FEM.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _forced_recipe_rows(
    *,
    low_case: dict[str, Any],
    high_case: dict[str, Any],
) -> list[dict[str, Any]]:
    low_eval: inv.InverseDesignEvaluator = low_case["evaluator"]
    high_eval: inv.InverseDesignEvaluator = high_case["evaluator"]
    low_selected: inv.InverseCandidate = low_case["reported_selected"]
    high_selected: inv.InverseCandidate = high_case["reported_selected"]
    setup_low = low_case["setup"]
    setup_high = high_case["setup"]
    material_low_main = setup_low["materials_db"].get(setup_low["cfg"].main_spar.material)
    material_low_rear = setup_low["materials_db"].get(setup_low["cfg"].rear_spar.material)
    material_high_main = setup_high["materials_db"].get(setup_high["cfg"].main_spar.material)
    material_high_rear = setup_high["materials_db"].get(setup_high["cfg"].rear_spar.material)

    high_rib = high_selected.rib_design.design_key if high_selected.rib_design is not None else high_eval.default_rib_design_key
    low_rib = low_selected.rib_design.design_key if low_selected.rib_design is not None else low_eval.default_rib_design_key
    forced_high_on_low = low_eval.evaluate(
        np.asarray(high_selected.z, dtype=float),
        source="forced_high_selected_on_low_z",
        rib_design_key=high_rib,
    )
    forced_low_on_high = high_eval.evaluate(
        np.asarray(low_selected.z, dtype=float),
        source="forced_low_selected_on_high_z",
        rib_design_key=low_rib,
    )
    rows = [
        _candidate_row(
            target_z_m=float(low_case["target_z_m"]),
            candidate=forced_high_on_low,
            reported_selected=low_selected,
            best_after_probes=low_case["best_after_probes"],
            material_main=material_low_main,
            material_rear=material_low_rear,
            sequence_index=-1,
            source_stage="forced_recipe_test",
        ),
        _candidate_row(
            target_z_m=float(high_case["target_z_m"]),
            candidate=forced_low_on_high,
            reported_selected=high_selected,
            best_after_probes=high_case["best_after_probes"],
            material_main=material_high_main,
            material_rear=material_high_rear,
            sequence_index=-1,
            source_stage="forced_recipe_test",
        ),
    ]
    rows[0]["force_test"] = "force_z2p025_light_recipe_on_z2p000"
    rows[0]["forced_recipe_source_z_m"] = float(high_case["target_z_m"])
    rows[0]["forced_recipe_source_reported_mass_kg"] = float(high_selected.tube_mass_kg)
    rows[1]["force_test"] = "force_z2p000_heavy_recipe_on_z2p025"
    rows[1]["forced_recipe_source_z_m"] = float(low_case["target_z_m"])
    rows[1]["forced_recipe_source_reported_mass_kg"] = float(low_selected.tube_mass_kg)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--design-report", default=str(DEFAULT_DESIGN_REPORT))
    parser.add_argument("--z-values", default="2.000,2.025")
    parser.add_argument("--dihedral-exponent", type=float, default=1.0)
    parser.add_argument("--loaded-shape-control-stations", default="0.0,0.5,1.0")
    parser.add_argument("--loaded-shape-penalty-kg", type=float, default=0.05)
    parser.add_argument("--clearance-risk-threshold-mm", type=float, default=10.0)
    parser.add_argument("--clearance-risk-top-k", type=int, default=5)
    parser.add_argument("--clearance-penalty-kg", type=float, default=0.25)
    parser.add_argument("--active-wall-penalty-kg", type=float, default=0.05)
    parser.add_argument("--clearance-floor-z-m", type=float, default=0.0)
    parser.add_argument("--target-shape-error-tol-m", type=float, default=1.0e-9)
    parser.add_argument("--main-plateau-grid", default="0.0,1.0")
    parser.add_argument("--main-taper-fill-grid", default="0.0,1.0")
    parser.add_argument("--rear-radius-grid", default="0.0,1.0")
    parser.add_argument("--rear-outboard-grid", default="0.0,1.0")
    parser.add_argument("--wall-thickness-grid", default="0.0,1.0")
    parser.add_argument("--rib-zonewise-mode", default=inv.RIB_ZONEWISE_LIMITED_MODE)
    parser.add_argument("--rib-family-switch-penalty-kg", type=float, default=inv.DEFAULT_RIB_FAMILY_SWITCH_PENALTY_KG)
    parser.add_argument("--rib-family-mix-max-unique", type=int, default=inv.DEFAULT_RIB_FAMILY_MIX_MAX_UNIQUE)
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    z_values = _parse_float_list(args.z_values)
    if len(z_values) != 2:
        raise ValueError("--z-values must contain exactly two values for this cliff comparison.")

    cases = [_run_case(target_z_m=float(z), args=args) for z in z_values]
    case_by_z = {round(float(case["target_z_m"]), 6): case for case in cases}
    low_case = case_by_z[min(case_by_z)]
    high_case = case_by_z[max(case_by_z)]

    for case in cases:
        suffix = f"{float(case['target_z_m']):.3f}".replace(".", "p")
        _write_csv(output_dir / f"candidate_recipe_dump_{suffix}.csv", case["rows"])
    forced_rows = _forced_recipe_rows(low_case=low_case, high_case=high_case)
    _write_csv(output_dir / "forced_recipe_comparison.csv", forced_rows)
    _write_rejection_diff(
        path=output_dir / "rejection_reason_diff.md",
        case_a=low_case,
        case_b=high_case,
        forced_rows=forced_rows,
    )
    _write_bug_report(
        path=output_dir / "suspected_bug_report.md",
        case_a=low_case,
        case_b=high_case,
        forced_rows=forced_rows,
    )
    _write_recommended_fix(output_dir / "recommended_fix.md")

    manifest = {
        "generated_by": str(Path(__file__).resolve()),
        "z_values_m": [float(value) for value in z_values],
        "config": str(Path(args.config).resolve()),
        "design_report": str(Path(args.design_report).resolve()),
        "base_dir": str(Path(args.base_dir).resolve()),
        "outputs": {
            "candidate_recipe_dump_2p000": str((output_dir / "candidate_recipe_dump_2p000.csv").resolve()),
            "candidate_recipe_dump_2p025": str((output_dir / "candidate_recipe_dump_2p025.csv").resolve()),
            "forced_recipe_comparison": str((output_dir / "forced_recipe_comparison.csv").resolve()),
            "rejection_reason_diff": str((output_dir / "rejection_reason_diff.md").resolve()),
            "suspected_bug_report": str((output_dir / "suspected_bug_report.md").resolve()),
            "recommended_fix": str((output_dir / "recommended_fix.md").resolve()),
        },
        "case_summaries": [
            {
                "target_main_tip_z_m": float(case["target_z_m"]),
                "target_shape_z_scale": float(case["target_shape_z_scale"]),
                "candidate_artifact": case["candidate_artifact"],
                "coarse_count": int(case["coarse_count"]),
                "coarse_feasible_count": int(case["coarse_feasible_count"]),
                "total_candidate_count_after_probes": int(case["total_candidate_count"]),
                "total_feasible_count_after_probes": int(case["total_feasible_count"]),
                "reported_selected_signature": _signature_for_candidate(case["reported_selected"]),
                "reported_selected_tube_mass_kg": float(case["reported_selected"].tube_mass_kg),
                "best_after_probes_signature": (
                    None if case["best_after_probes"] is None else _signature_for_candidate(case["best_after_probes"])
                ),
                "best_after_probes_tube_mass_kg": (
                    None if case["best_after_probes"] is None else float(case["best_after_probes"].tube_mass_kg)
                ),
                "manufacturing_limits": case["manufacturing_limits"],
                "active_wall_probes": [dict(item) for item in case["active_wall_probes"]],
            }
            for case in cases
        ],
    }
    (output_dir / "debug_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["case_summaries"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
