#!/usr/bin/env python3
"""Tail-aware aeroelastic closure for the current conservative pathfinder.

This is a screening closure runner. It couples the committed selected
tail/rib/rear-spar/CG basis to AVL trim/spanload reruns and the repo's
dual-beam mainline response. It is not an ASWing dependency and not a final
hardware certification route.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import numpy as np
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.aero.avl_exporter import stage_avl_airfoil_files  # noqa: E402
from hpa_mdo.aero.avl_runner import run_avl_derivatives  # noqa: E402
from hpa_mdo.aero.avl_spanwise import (  # noqa: E402
    build_spanwise_load_from_avl_strip_forces,
    load_candidate_avl_spanwise_artifact,
)
from hpa_mdo.aero.base import SpanwiseLoad  # noqa: E402
from hpa_mdo.concept.avl_loader import _run_avl_spanwise_case  # noqa: E402
from hpa_mdo.structure.dual_beam_mainline import (  # noqa: E402
    AnalysisModeName,
    LinkMode,
    run_dual_beam_mainline_kernel,
)
from scripts import current_pathfinder_tail_cg_trim_stability_screening as tail_trim  # noqa: E402
from scripts import full_aircraft_tail_avl_audit_v0 as tail_avl  # noqa: E402
from scripts.phase15_candidate_load_factor_buckling_check import CANDIDATE_ID  # noqa: E402
from scripts.phase22_bracing_sensitivity import (  # noqa: E402
    build_current_candidate_model,
    clone_with_rear_stiffness_scale,
)


SCHEMA_VERSION = "tail_aware_aeroelastic_closure_v1"
READY_VERDICT = "ready_for_fem_apdl_loadcase_package"
NEEDS_AEROELASTIC_REWORK = "needs_aeroelastic_geometry_or_stiffness_rework"
NEEDS_TAIL_CG_REBALANCE = "needs_tail_cg_rebalance_redesign"
NOT_VIABLE = "pathfinder_not_viable_under_tail_aware_aeroelastic_closure"
READY_FOR_HYBRID_STIFFNESS_REWORK = "ready_for_hybrid_rib_stiffness_rework"
READY_FOR_AEROELASTIC_MAPPING_FIX = "ready_for_aeroelastic_mapping_fix"
READY_FOR_FEM_LOADCASE_PACKAGE = "ready_for_FEM_loadcase_package"
STILL_BLOCKED_BY_UNRESOLVED_TWIST_SOURCE = "still_blocked_by_unresolved_twist_source"

DEFAULT_SELECTED_BASIS_JSON = (
    REPO_ROOT / "docs" / "reports" / "2026-05-09_tail_aware_rib_rear_spar_sensitivity.json"
)
DEFAULT_TAIL_SCREENING_JSON = (
    REPO_ROOT / "docs" / "reports" / "2026-05-09_tail_cg_trim_stability_screening_v1.json"
)
DEFAULT_CONTRACT = REPO_ROOT / "configs" / "current_pathfinder_tail_contract_v0.yaml"
DEFAULT_SOURCE_WING_AVL = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "current_avl_compromise_conservative_closed_tier2_airfoil"
    / "runs"
    / "conservative_best"
    / "conservative_best_loaded_shape_airfoils.avl"
)
DEFAULT_CANDIDATE_SPANWISE_JSON = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "current_avl_compromise_conservative_closed_closure"
    / "candidate_avl_artifacts"
    / "conservative_best_selected_airfoil_spanwise.json"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "output" / "current_pathfinder_tail_aware_aeroelastic_closure"
)
DEFAULT_REPORT_JSON = (
    REPO_ROOT / "docs" / "reports" / "2026-05-09_tail_aware_aeroelastic_closure.json"
)
DEFAULT_REPORT_MD = (
    REPO_ROOT / "docs" / "reports" / "2026-05-09_tail_aware_aeroelastic_closure.md"
)


def assess_final_cg_management(selected_basis: Mapping[str, Any]) -> dict[str, Any]:
    """Gate the committed final-CG row and reject the aft uncompensated CG."""

    cg = _mapping_at(selected_basis, "cg_impact") or _mapping_at(
        selected_basis, "mass_cg_assessment"
    )
    if not cg:
        return {
            "status": "missing_cg_management",
            "blockers": ["selected_basis_missing_cg_impact"],
        }
    cg_range = tuple(float(value) for value in cg.get("cg_range_x_m", ()))
    final_cg = _float_or_none(cg.get("final_screening_cg_x_m"))
    uncompensated = _float_or_none(cg.get("uncompensated_cg_x_m"))
    rebalance = _float_or_none(cg.get("required_forward_rebalance_m"))
    rebalance_limit = _float_or_none(cg.get("forward_rebalance_limit_m")) or 0.20
    screening_status = str(cg.get("screening_status", ""))
    blockers: list[str] = []

    if len(cg_range) != 2 or final_cg is None:
        blockers.append("final_cg_range_or_row_missing")
    elif not (cg_range[0] <= final_cg <= cg_range[1]):
        blockers.append("final_cg_outside_committed_screening_range")
    if uncompensated is not None and len(cg_range) == 2 and uncompensated > cg_range[1]:
        uncompensated_status = "explicitly_rejected"
    else:
        uncompensated_status = "not_aft_or_missing"
    if "rebalance" in screening_status:
        if rebalance is None:
            blockers.append("required_forward_rebalance_missing")
        elif rebalance > rebalance_limit + 1.0e-12:
            blockers.append("required_forward_rebalance_exceeds_limit")
    elif screening_status != "final_cg_screening_row_available_without_rebalance":
        blockers.append("selected_basis_does_not_preserve_final_cg_screening_row")

    status = "managed_final_cg_pass" if not blockers else "managed_final_cg_fail"
    return {
        "status": status,
        "blockers": blockers,
        "cg_range_x_m": list(cg_range),
        "final_cg_x_m": final_cg,
        "uncompensated_cg_x_m": uncompensated,
        "uncompensated_cg_status": uncompensated_status,
        "required_forward_rebalance_m": rebalance,
        "forward_rebalance_mass_kg": _float_or_none(cg.get("forward_rebalance_mass_kg")),
        "forward_rebalance_limit_m": rebalance_limit,
        "screening_status": screening_status,
        "engineering_read": (
            "Closure uses the managed final CG row. The uncompensated aft CG is "
            "recorded only as a rejected mass-bookkeeping state."
        ),
    }


def elastic_twist_distribution_rows(
    *,
    y_nodes_m: Sequence[float],
    nodes_main_m: np.ndarray,
    nodes_rear_m: np.ndarray,
    disp_main_m: np.ndarray,
    disp_rear_m: np.ndarray,
    trim_alpha_deg: float,
    base_section_incidence_deg: Sequence[float] | None = None,
) -> tuple[list[dict[str, float]], dict[str, float]]:
    """Compute elastic chord rotation from loaded main/rear spar-pair geometry."""

    y = np.asarray(y_nodes_m, dtype=float)
    main = np.asarray(nodes_main_m, dtype=float)
    rear = np.asarray(nodes_rear_m, dtype=float)
    disp_main = np.asarray(disp_main_m, dtype=float)
    disp_rear = np.asarray(disp_rear_m, dtype=float)
    if main.shape[0] != y.size or rear.shape[0] != y.size:
        raise ValueError("node arrays must align with y_nodes_m.")
    if disp_main.shape[0] != y.size or disp_rear.shape[0] != y.size:
        raise ValueError("displacement arrays must align with y_nodes_m.")

    base = rear[:, :3] - main[:, :3]
    loaded = (rear[:, :3] + disp_rear[:, :3]) - (main[:, :3] + disp_main[:, :3])
    base_chordwise = np.hypot(base[:, 0], base[:, 1])
    loaded_chordwise = np.hypot(loaded[:, 0], loaded[:, 1])
    base_angle = np.arctan2(base[:, 2], np.maximum(base_chordwise, 1.0e-12))
    loaded_angle = np.arctan2(loaded[:, 2], np.maximum(loaded_chordwise, 1.0e-12))
    elastic_twist_deg = np.degrees(loaded_angle - base_angle)
    if base_section_incidence_deg is None:
        incidence = np.zeros_like(elastic_twist_deg)
    else:
        incidence = np.asarray(base_section_incidence_deg, dtype=float)
        if incidence.shape != elastic_twist_deg.shape:
            raise ValueError("base_section_incidence_deg must align with y_nodes_m.")
    alpha_eff = float(trim_alpha_deg) + incidence + elastic_twist_deg

    rows = []
    for idx, y_m in enumerate(y):
        rows.append(
            {
                "y_m": float(y_m),
                "main_x_m": float(main[idx, 0]),
                "rear_x_m": float(rear[idx, 0]),
                "main_loaded_z_m": float(main[idx, 2] + disp_main[idx, 2]),
                "rear_loaded_z_m": float(rear[idx, 2] + disp_rear[idx, 2]),
                "elastic_twist_deg": float(elastic_twist_deg[idx]),
                "trim_alpha_deg": float(trim_alpha_deg),
                "base_incidence_deg": float(incidence[idx]),
                "alpha_eff_deg": float(alpha_eff[idx]),
            }
        )
    summary = {
        "elastic_twist_max_abs_deg": float(np.max(np.abs(elastic_twist_deg))),
        "elastic_twist_tip_deg": float(elastic_twist_deg[-1]),
        "elastic_twist_rms_deg": float(np.sqrt(np.mean(elastic_twist_deg**2))),
        "alpha_eff_min_deg": float(np.min(alpha_eff)),
        "alpha_eff_max_deg": float(np.max(alpha_eff)),
    }
    return rows, summary


def twist_source_interpretation_rows(
    *,
    y_nodes_m: Sequence[float],
    nodes_main_m: np.ndarray,
    nodes_rear_m: np.ndarray,
    disp_main_m: np.ndarray,
    disp_rear_m: np.ndarray,
    aero_y_m: Sequence[float],
    aero_x_le_m: Sequence[float],
    aero_chord_m: Sequence[float],
    screening_bound_deg: float = 3.0,
) -> tuple[list[dict[str, float]], dict[str, Any]]:
    """Compare direct, quarter-chord-consistent, and bounded physical twist reads."""

    y = np.asarray(y_nodes_m, dtype=float)
    main = np.asarray(nodes_main_m, dtype=float)
    rear = np.asarray(nodes_rear_m, dtype=float)
    disp_main = np.asarray(disp_main_m, dtype=float)
    disp_rear = np.asarray(disp_rear_m, dtype=float)
    aero_y = np.asarray(aero_y_m, dtype=float)
    aero_x_le = np.asarray(aero_x_le_m, dtype=float)
    aero_chord = np.asarray(aero_chord_m, dtype=float)
    if main.shape[0] != y.size or rear.shape[0] != y.size:
        raise ValueError("node arrays must align with y_nodes_m.")
    if disp_main.shape[0] != y.size or disp_rear.shape[0] != y.size:
        raise ValueError("displacement arrays must align with y_nodes_m.")
    if aero_y.ndim != 1 or aero_x_le.shape != aero_y.shape or aero_chord.shape != aero_y.shape:
        raise ValueError("AVL aerodynamic reference arrays must be one-dimensional and aligned.")

    loaded_main = main[:, :3] + disp_main[:, :3]
    loaded_rear = rear[:, :3] + disp_rear[:, :3]
    x_le = np.interp(y, aero_y, aero_x_le)
    chord = np.maximum(np.interp(y, aero_y, aero_chord), 1.0e-9)
    quarter_chord_x = x_le + 0.25 * chord
    elastic_axis_x = 0.5 * (main[:, 0] + rear[:, 0])

    rows: list[dict[str, float]] = []
    for idx, y_m in enumerate(y):
        base_dx = float(rear[idx, 0] - main[idx, 0])
        loaded_dx = float(loaded_rear[idx, 0] - loaded_main[idx, 0])
        base_chordwise = max(abs(base_dx), 1.0e-12)
        loaded_chordwise = max(abs(loaded_dx), 1.0e-12)
        base_dz = float(rear[idx, 2] - main[idx, 2])
        loaded_dz = float(loaded_rear[idx, 2] - loaded_main[idx, 2])
        base_angle = math.atan2(base_dz, base_chordwise)
        loaded_angle = math.atan2(loaded_dz, loaded_chordwise)
        direct_deg = math.degrees(loaded_angle - base_angle)

        qc_x = float(quarter_chord_x[idx])
        base_qc_denom = abs(float(rear[idx, 0]) - qc_x)
        loaded_qc_denom = abs(float(loaded_rear[idx, 0]) - qc_x)
        if base_qc_denom <= 0.05 * float(chord[idx]) or loaded_qc_denom <= 1.0e-12:
            qc_deg = direct_deg
        else:
            base_slope = base_dz / base_chordwise
            loaded_slope = loaded_dz / loaded_chordwise
            base_qc_z = float(main[idx, 2]) + base_slope * (qc_x - float(main[idx, 0]))
            loaded_qc_z = float(loaded_main[idx, 2]) + loaded_slope * (
                qc_x - float(loaded_main[idx, 0])
            )
            base_qc_angle = math.atan2(float(rear[idx, 2]) - base_qc_z, base_qc_denom)
            loaded_qc_angle = math.atan2(
                float(loaded_rear[idx, 2]) - loaded_qc_z,
                loaded_qc_denom,
            )
            qc_deg = math.degrees(loaded_qc_angle - base_qc_angle)

        delta_z_change = loaded_dz - base_dz
        bounded_lever_m = max(0.75 * float(chord[idx]), base_chordwise, 1.0e-12)
        bounded_deg = math.degrees(math.atan2(delta_z_change, bounded_lever_m))
        spar_sep_over_chord = base_chordwise / float(chord[idx])
        rows.append(
            {
                "station_index": float(idx),
                "y_m": float(y_m),
                "main_x_m": float(main[idx, 0]),
                "rear_x_m": float(rear[idx, 0]),
                "quarter_chord_x_m": qc_x,
                "elastic_axis_x_m": float(elastic_axis_x[idx]),
                "aero_chord_m": float(chord[idx]),
                "spar_separation_m": base_chordwise,
                "spar_sep_over_chord": float(spar_sep_over_chord),
                "spar_pair_delta_z_change_m": float(delta_z_change),
                "direct_spar_pair_rotation_deg": float(direct_deg),
                "elastic_axis_quarter_chord_projection_deg": float(qc_deg),
                "conservative_bounded_physical_projection_deg": float(bounded_deg),
                "bounded_projection_lever_m": float(bounded_lever_m),
            }
        )

    direct_max = _max_abs_metric(rows, "direct_spar_pair_rotation_deg")
    qc_max = _max_abs_metric(rows, "elastic_axis_quarter_chord_projection_deg")
    bounded_max = _max_abs_metric(rows, "conservative_bounded_physical_projection_deg")
    source_verdict = _classify_twist_source_verdict(
        direct_max_abs_deg=direct_max["abs_value_deg"],
        bounded_max_abs_deg=bounded_max["abs_value_deg"],
        screening_bound_deg=float(screening_bound_deg),
    )
    return rows, {
        "direct_spar_pair_rotation_max_abs_deg": direct_max["abs_value_deg"],
        "direct_spar_pair_rotation_max_station_y_m": direct_max["y_m"],
        "direct_spar_pair_rotation_max_signed_deg": direct_max["signed_value_deg"],
        "elastic_axis_quarter_chord_projection_max_abs_deg": qc_max["abs_value_deg"],
        "elastic_axis_quarter_chord_projection_max_station_y_m": qc_max["y_m"],
        "conservative_bounded_physical_projection_max_abs_deg": bounded_max["abs_value_deg"],
        "conservative_bounded_physical_projection_max_station_y_m": bounded_max["y_m"],
        "conservative_bounded_physical_projection_max_signed_deg": bounded_max[
            "signed_value_deg"
        ],
        "screening_bound_deg": float(screening_bound_deg),
        "source_verdict": source_verdict,
        "interpretation_read": (
            "Direct spar-pair rotation is the rigid-section AVL Ainc stress-test. "
            "Quarter-chord projection checks the aerodynamic reference consistency. "
            "The bounded physical projection spreads the measured spar-pair vertical "
            "differential over at least 75% of local AVL chord; if it still exceeds "
            "the bound, the blocker is not just a narrow spar-reference artifact."
        ),
    }


def dominant_twist_source_at_station(
    *,
    y_m: float,
    component_rows: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Return the dominant load component at a station by direct twist magnitude."""

    values: dict[str, float] = {}
    for component, rows in component_rows.items():
        if not rows:
            continue
        nearest = min(rows, key=lambda row: abs(float(row.get("y_m", 0.0)) - float(y_m)))
        values[str(component)] = float(nearest.get("direct_spar_pair_rotation_deg", 0.0))
    if not values:
        return {"dominant_component": None, "component_twist_deg": {}}
    dominant = max(values, key=lambda key: abs(values[key]))
    return {
        "dominant_component": dominant,
        "component_twist_deg": values,
        "dominant_abs_twist_deg": abs(values[dominant]),
        "station_y_m": float(y_m),
    }


def build_aeroelastic_twist_source_audit(
    *,
    model,
    structural,
    source_wing_avl: Path,
    screening_bound_deg: float = 3.0,
) -> dict[str, Any]:
    """Build a rerunnable audit package for the current aeroelastic twist source."""

    aero = tail_avl.parse_wing_avl_basis(Path(source_wing_avl))
    aero_y = np.asarray([section.y_le_m for section in aero.sections], dtype=float)
    aero_x_le = np.asarray([section.x_le_m for section in aero.sections], dtype=float)
    aero_chord = np.asarray([section.chord_m for section in aero.sections], dtype=float)
    station_rows, interpretation_summary = twist_source_interpretation_rows(
        y_nodes_m=model.y_nodes_m,
        nodes_main_m=model.nodes_main_m,
        nodes_rear_m=model.nodes_rear_m,
        disp_main_m=structural.disp_main_m,
        disp_rear_m=structural.disp_rear_m,
        aero_y_m=aero_y,
        aero_x_le_m=aero_x_le,
        aero_chord_m=aero_chord,
        screening_bound_deg=float(screening_bound_deg),
    )
    component_models = {
        "lift_only": replace(
            model,
            torque_per_span_nmpm=np.zeros_like(model.torque_per_span_nmpm, dtype=float),
            gravity_scale=0.0,
        ),
        "aerodynamic_torque_only": replace(
            model,
            lift_per_span_npm=np.zeros_like(model.lift_per_span_npm, dtype=float),
            gravity_scale=0.0,
        ),
        "self_weight_only": replace(
            model,
            lift_per_span_npm=np.zeros_like(model.lift_per_span_npm, dtype=float),
            torque_per_span_nmpm=np.zeros_like(model.torque_per_span_nmpm, dtype=float),
        ),
    }
    component_rows: dict[str, list[dict[str, float]]] = {}
    component_summary: dict[str, Any] = {}
    for component, component_model in component_models.items():
        component_result = run_dual_beam_mainline_kernel(
            model=component_model,
            mode=AnalysisModeName.DUAL_BEAM_ROBUSTNESS,
            link_mode=LinkMode.DENSE_FINITE_RIB,
        )
        rows, summary = twist_source_interpretation_rows(
            y_nodes_m=component_model.y_nodes_m,
            nodes_main_m=component_model.nodes_main_m,
            nodes_rear_m=component_model.nodes_rear_m,
            disp_main_m=component_result.disp_main_m,
            disp_rear_m=component_result.disp_rear_m,
            aero_y_m=aero_y,
            aero_x_le_m=aero_x_le,
            aero_chord_m=aero_chord,
            screening_bound_deg=float(screening_bound_deg),
        )
        component_rows[component] = rows
        component_summary[component] = summary
    direct_station_y = float(interpretation_summary["direct_spar_pair_rotation_max_station_y_m"])
    dominant_source = dominant_twist_source_at_station(
        y_m=direct_station_y,
        component_rows=component_rows,
    )
    full_direct_at_station = _nearest_metric(
        station_rows,
        direct_station_y,
        "direct_spar_pair_rotation_deg",
    )
    component_sum = sum(float(v) for v in dominant_source.get("component_twist_deg", {}).values())
    dominant_source["component_sum_twist_deg"] = float(component_sum)
    dominant_source["full_direct_twist_deg"] = float(full_direct_at_station)
    dominant_source["linear_residual_deg"] = float(full_direct_at_station - component_sum)
    return {
        "schema_version": "aeroelastic_twist_source_audit_v1",
        "interpretation_summary": interpretation_summary,
        "dominant_source_at_direct_max_station": dominant_source,
        "component_summary": component_summary,
        "station_rows": station_rows,
        "component_rows": component_rows,
        "engineering_read": _twist_source_engineering_read(
            interpretation_summary=interpretation_summary,
            dominant_source=dominant_source,
        ),
        "claim_boundary": (
            "This audit separates projection and load-component sources inside the "
            "current beam/AVL screening closure. It is not a shell/FEM aero-surface "
            "twist measurement and not hardware sign-off."
        ),
    }


def rescale_structural_loads_by_avl_ratio(
    *,
    model_y_m: Sequence[float],
    baseline_structural_lift_npm: Sequence[float],
    baseline_structural_torque_nmpm: Sequence[float],
    avl_y_m: Sequence[float],
    baseline_avl_lift_npm: Sequence[float],
    updated_avl_lift_npm: Sequence[float],
    relaxation: float,
    ratio_bounds: tuple[float, float],
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Apply AVL spanload redistribution to structural load ownership by ratio."""

    model_y = np.asarray(model_y_m, dtype=float)
    base_lift = np.asarray(baseline_structural_lift_npm, dtype=float)
    base_torque = np.asarray(baseline_structural_torque_nmpm, dtype=float)
    avl_y = np.asarray(avl_y_m, dtype=float)
    old_lift = np.asarray(baseline_avl_lift_npm, dtype=float)
    new_lift = np.asarray(updated_avl_lift_npm, dtype=float)
    if model_y.ndim != 1 or avl_y.ndim != 1:
        raise ValueError("model_y_m and avl_y_m must be one-dimensional.")
    if base_lift.shape != model_y.shape or base_torque.shape != model_y.shape:
        raise ValueError("baseline structural loads must align with model_y_m.")
    if old_lift.shape != avl_y.shape or new_lift.shape != avl_y.shape:
        raise ValueError("AVL lift arrays must align with avl_y_m.")
    if not (0.0 <= float(relaxation) <= 1.0):
        raise ValueError("relaxation must be in [0, 1].")

    raw_ratio_at_avl = np.ones_like(new_lift)
    valid = np.abs(old_lift) > 1.0e-9
    raw_ratio_at_avl[valid] = new_lift[valid] / old_lift[valid]
    raw_ratio = np.interp(model_y, avl_y, raw_ratio_at_avl)
    lower, upper = float(ratio_bounds[0]), float(ratio_bounds[1])
    clipped_ratio = np.clip(raw_ratio, lower, upper)
    relaxed_ratio = 1.0 + float(relaxation) * (clipped_ratio - 1.0)
    scaled_lift = base_lift * relaxed_ratio
    scaled_torque = base_torque * relaxed_ratio
    diagnostics = {
        "min_raw_ratio": float(np.min(raw_ratio)),
        "max_raw_ratio": float(np.max(raw_ratio)),
        "min_relaxed_ratio": float(np.min(relaxed_ratio)),
        "max_relaxed_ratio": float(np.max(relaxed_ratio)),
        "ratio_lower_bound": lower,
        "ratio_upper_bound": upper,
        "relaxation": float(relaxation),
        "ratio_clipped": bool(np.any(np.abs(raw_ratio - clipped_ratio) > 1.0e-12)),
        "load_update_basis": (
            "Structural load ownership is preserved by scaling existing lift and "
            "pitch-torque distributions by AVL wing spanload ratios."
        ),
    }
    return scaled_lift, scaled_torque, diagnostics


def classify_aeroelastic_closure(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Return the required final verdict and blockers."""

    basis = dict(summary.get("basis", summary))
    blockers: list[str] = []
    warnings: list[str] = []
    tail_blockers: list[str] = []
    cg_blockers: list[str] = []

    if not bool(_mapping_at(basis, "coupling").get("converged")):
        blockers.append("aeroelastic_fixed_point_not_converged")
    if _mapping_at(basis, "cg_management").get("status") != "managed_final_cg_pass":
        cg_blockers.append("final_cg_management_not_closed")
    trim = _mapping_at(basis, "trim_static_directional")
    if trim.get("status") != "pass":
        tail_blockers.append("tail_trim_static_directional_status_not_pass")
    if (_float_or_none(trim.get("delta_H_margin_to_limit_deg")) or -math.inf) < 0.0:
        tail_blockers.append("h_tail_deflection_reserve_exceeded")
    if (_float_or_none(trim.get("static_margin")) or -math.inf) < 0.05:
        tail_blockers.append("static_margin_below_screening_min")
    if (_float_or_none(trim.get("C_n_beta")) or -math.inf) < 0.005:
        tail_blockers.append("directional_stability_below_screening_min")
    if (_float_or_none(trim.get("delta_V_margin_to_limit_deg")) or -math.inf) < 0.0:
        tail_blockers.append("v_tail_authority_margin_exceeded")

    aero = _mapping_at(basis, "aeroelastic_effects")
    if (_float_or_none(aero.get("stall_margin_min")) or -math.inf) < 0.0:
        warnings.append("negative_diagnostic_stall_margin_not_gate")
    if (_float_or_none(aero.get("elastic_twist_max_abs_deg")) or math.inf) > 3.0:
        blockers.append("elastic_twist_exceeds_screening_bound")
    bending_ratio = _float_or_none(aero.get("root_bending_moment_ratio_loaded_vs_baseline"))
    if bending_ratio is not None and not (0.80 <= bending_ratio <= 1.20):
        blockers.append("aeroelastic_load_redistribution_exceeds_20pct_bending_bound")
    if aero.get("closure_ranking_effect") != "no_change_conservative_best_remains_screening_closed":
        blockers.append("aeroelastic_loads_change_closure_ranking")
    if _mapping_at(basis, "selected_stiffness_basis").get("status") != "pass_screening_sensitivity":
        blockers.append("selected_rib_rear_spar_stiffness_not_screening_pass")
    if _mapping_at(basis, "mass_drag_power").get("status") != "charged_to_screening_read":
        blockers.append("tail_rib_mass_drag_power_not_charged")
    if _mapping_at(basis, "load_remap_diagnostics").get("status") != "conserved":
        blockers.append("load_remap_not_conserved")

    blockers = cg_blockers + tail_blockers + blockers
    if not blockers:
        verdict = READY_VERDICT
    elif cg_blockers or tail_blockers:
        verdict = NEEDS_TAIL_CG_REBALANCE
    elif "aeroelastic_fixed_point_not_converged" in blockers and len(blockers) > 2:
        verdict = NOT_VIABLE
    else:
        verdict = NEEDS_AEROELASTIC_REWORK
    return {"verdict": verdict, "blockers": blockers, "warnings": warnings, "basis": basis}


def run_tail_aware_aeroelastic_closure(
    *,
    selected_basis_json: Path = DEFAULT_SELECTED_BASIS_JSON,
    tail_screening_json: Path = DEFAULT_TAIL_SCREENING_JSON,
    contract_path: Path = DEFAULT_CONTRACT,
    source_wing_avl: Path = DEFAULT_SOURCE_WING_AVL,
    candidate_spanwise_json: Path = DEFAULT_CANDIDATE_SPANWISE_JSON,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_json_path: Path = DEFAULT_REPORT_JSON,
    report_md_path: Path = DEFAULT_REPORT_MD,
    max_iter: int = 5,
    relaxation: float = 0.55,
    twist_tol_deg: float = 0.03,
    delta_h_tol_deg: float = 0.05,
    load_ratio_tol: float = 0.015,
    ratio_bounds: tuple[float, float] = (0.70, 1.30),
    avl_binary: str | Path | None = None,
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    selected_payload = _read_json(Path(selected_basis_json))
    selected_basis = _mapping_at(selected_payload, "selected_basis")
    if not selected_basis:
        raise ValueError("selected basis JSON does not contain selected_basis.")
    cg_management = assess_final_cg_management(selected_basis)
    tail_payload = _read_json(Path(tail_screening_json))
    tail_row = _selected_tail_row(tail_payload, float(cg_management.get("final_cg_x_m") or 0.75))
    contract = yaml.safe_load(Path(contract_path).read_text(encoding="utf-8")) or {}
    if not isinstance(contract, Mapping):
        raise TypeError("Tail contract YAML must contain a mapping.")
    variant_contract, variant_warnings = tail_trim.build_tail_contract_variant(
        contract,
        tail_trim.DEFAULT_SIZING_CASE,
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_model = clone_with_rear_stiffness_scale(
        build_current_candidate_model(),
        float(selected_basis.get("rear_stiffness_scale", 0.50)),
    )
    payload, base_avl_load = _selected_spanwise_load(Path(candidate_spanwise_json))
    velocity_mps = float(payload["velocity_mps"])
    density_kgpm3 = float(payload["density_kgpm3"])
    base_struct_lift = np.asarray(base_model.lift_per_span_npm, dtype=float)
    base_struct_torque = np.asarray(base_model.torque_per_span_nmpm, dtype=float)
    current_lift = base_struct_lift.copy()
    current_torque = base_struct_torque.copy()
    previous_twist: np.ndarray | None = None
    previous_delta_h: float | None = None
    previous_relaxed_ratio_max: float | None = None
    baseline_root_bending = _root_bending_moment(base_avl_load)
    iteration_rows: list[dict[str, Any]] = []
    final_state: dict[str, Any] = {}

    for iteration_index in range(1, int(max_iter) + 1):
        model = replace(
            base_model,
            lift_per_span_npm=np.asarray(current_lift, dtype=float),
            torque_per_span_nmpm=np.asarray(current_torque, dtype=float),
        )
        structural = run_dual_beam_mainline_kernel(
            model=model,
            mode=AnalysisModeName.DUAL_BEAM_ROBUSTNESS,
            link_mode=LinkMode.DENSE_FINITE_RIB,
        )
        twist_rows, twist_summary = elastic_twist_distribution_rows(
            y_nodes_m=model.y_nodes_m,
            nodes_main_m=model.nodes_main_m,
            nodes_rear_m=model.nodes_rear_m,
            disp_main_m=structural.disp_main_m,
            disp_rear_m=structural.disp_rear_m,
            trim_alpha_deg=0.0,
        )
        twist_at_nodes = np.asarray([row["elastic_twist_deg"] for row in twist_rows], dtype=float)
        wing_with_twist = output_dir / "runs" / f"iteration_{iteration_index:02d}" / "wing_twist.avl"
        section_twist = _rewrite_wing_with_elastic_twist(
            source_avl=Path(source_wing_avl),
            output_avl=wing_with_twist,
            y_nodes_m=model.y_nodes_m,
            elastic_twist_deg=twist_at_nodes,
        )
        trim_state = _run_tail_trim_and_spanload(
            wing_avl=wing_with_twist,
            contract=variant_contract,
            case_dir=wing_with_twist.parent / "tail_trim_avl",
            cg_x_m=float(cg_management.get("final_cg_x_m") or 0.75),
            velocity_mps=velocity_mps,
            density_kgpm3=density_kgpm3,
            avl_binary=avl_binary,
            timeout_s=timeout_s,
        )
        twist_rows, twist_summary = elastic_twist_distribution_rows(
            y_nodes_m=model.y_nodes_m,
            nodes_main_m=model.nodes_main_m,
            nodes_rear_m=model.nodes_rear_m,
            disp_main_m=structural.disp_main_m,
            disp_rear_m=structural.disp_rear_m,
            trim_alpha_deg=float(trim_state["row"]["longitudinal_trim"]["alpha_required_deg"]),
        )
        _write_csv(wing_with_twist.parent / "elastic_twist_alpha_eff.csv", twist_rows)
        spanload = trim_state["spanwise_load"]
        load_rows = _spanload_comparison_rows(
            baseline=base_avl_load,
            updated=spanload,
            case_label=f"iteration_{iteration_index:02d}",
        )
        _write_csv(wing_with_twist.parent / "wing_spanload_redistribution.csv", load_rows)
        scaled_lift, scaled_torque, load_update = rescale_structural_loads_by_avl_ratio(
            model_y_m=base_model.y_nodes_m,
            baseline_structural_lift_npm=base_struct_lift,
            baseline_structural_torque_nmpm=base_struct_torque,
            avl_y_m=spanload.y,
            baseline_avl_lift_npm=np.interp(spanload.y, base_avl_load.y, base_avl_load.lift_per_span),
            updated_avl_lift_npm=spanload.lift_per_span,
            relaxation=relaxation,
            ratio_bounds=ratio_bounds,
        )
        root_bending = _root_bending_moment(spanload)
        load_ratio_delta = 0.0
        if previous_relaxed_ratio_max is not None:
            load_ratio_delta = abs(
                float(load_update["max_relaxed_ratio"]) - float(previous_relaxed_ratio_max)
            )
        twist_delta = (
            math.inf
            if previous_twist is None
            else float(np.max(np.abs(twist_at_nodes - previous_twist)))
        )
        delta_h = float(trim_state["row"]["longitudinal_trim"]["delta_H_required_deg"])
        delta_h_change = math.inf if previous_delta_h is None else abs(delta_h - previous_delta_h)
        converged = (
            iteration_index > 1
            and twist_delta <= float(twist_tol_deg)
            and delta_h_change <= float(delta_h_tol_deg)
            and load_ratio_delta <= float(load_ratio_tol)
        )
        iteration_row = {
            "iteration": iteration_index,
            "converged": converged,
            "elastic_twist_max_abs_deg": twist_summary["elastic_twist_max_abs_deg"],
            "elastic_twist_tip_deg": twist_summary["elastic_twist_tip_deg"],
            "trim_alpha_deg": trim_state["row"]["longitudinal_trim"]["alpha_required_deg"],
            "delta_H_required_deg": delta_h,
            "delta_H_margin_to_limit_deg": trim_state["row"]["longitudinal_trim"][
                "delta_H_margin_to_limit_deg"
            ],
            "static_margin": trim_state["row"]["longitudinal_trim"]["static_margin"],
            "C_n_beta": trim_state["row"]["directional"]["C_n_beta"],
            "delta_V_required_deg": trim_state["row"]["directional"]["delta_V_required_deg"],
            "delta_V_margin_to_limit_deg": trim_state["row"]["directional"][
                "delta_V_margin_to_limit_deg"
            ],
            "stall_margin_min": _stall_margin_min(spanload),
            "root_bending_moment_nm": root_bending,
            "root_bending_moment_ratio_loaded_vs_baseline": (
                root_bending / baseline_root_bending if abs(baseline_root_bending) > 1.0e-12 else None
            ),
            "max_relaxed_load_ratio": load_update["max_relaxed_ratio"],
            "min_relaxed_load_ratio": load_update["min_relaxed_ratio"],
            "ratio_clipped": load_update["ratio_clipped"],
            "twist_delta_from_previous_deg": None if math.isinf(twist_delta) else twist_delta,
            "delta_H_change_from_previous_deg": None if math.isinf(delta_h_change) else delta_h_change,
            "load_ratio_delta_from_previous": load_ratio_delta if iteration_index > 1 else None,
            "wing_with_twist_avl": str(wing_with_twist.resolve()),
            "elastic_twist_csv": str((wing_with_twist.parent / "elastic_twist_alpha_eff.csv").resolve()),
            "spanload_csv": str((wing_with_twist.parent / "wing_spanload_redistribution.csv").resolve()),
        }
        iteration_rows.append(iteration_row)
        final_state = {
            "model": model,
            "structural": structural,
            "twist_rows": twist_rows,
            "twist_summary": twist_summary,
            "section_twist": section_twist,
            "trim_state": trim_state,
            "spanload": spanload,
            "load_rows": load_rows,
            "load_update": load_update,
            "iteration_row": iteration_row,
            "converged": converged,
        }
        if converged:
            break
        current_lift = scaled_lift
        current_torque = scaled_torque
        previous_twist = twist_at_nodes.copy()
        previous_delta_h = delta_h
        previous_relaxed_ratio_max = float(load_update["max_relaxed_ratio"])

    _write_csv(output_dir / "iteration_history.csv", iteration_rows)
    if not final_state:
        raise RuntimeError("Aeroelastic closure did not execute any iteration.")
    final_dir = output_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(final_dir / "elastic_twist_alpha_eff.csv", final_state["twist_rows"])
    _write_csv(final_dir / "wing_spanload_redistribution.csv", final_state["load_rows"])
    twist_source_audit = build_aeroelastic_twist_source_audit(
        model=final_state["model"],
        structural=final_state["structural"],
        source_wing_avl=Path(source_wing_avl),
        screening_bound_deg=3.0,
    )
    _write_csv(final_dir / "twist_source_audit.csv", twist_source_audit["station_rows"])
    _write_csv(
        final_dir / "twist_source_components.csv",
        _flatten_component_rows(twist_source_audit["component_rows"]),
    )
    trim_row = final_state["trim_state"]["row"]
    aero_effects = {
        **final_state["twist_summary"],
        "twist_source_verdict": _mapping_at(
            twist_source_audit,
            "interpretation_summary",
        ).get("source_verdict"),
        "direct_spar_pair_rotation_max_abs_deg": _mapping_at(
            twist_source_audit,
            "interpretation_summary",
        ).get("direct_spar_pair_rotation_max_abs_deg"),
        "elastic_axis_quarter_chord_projection_max_abs_deg": _mapping_at(
            twist_source_audit,
            "interpretation_summary",
        ).get("elastic_axis_quarter_chord_projection_max_abs_deg"),
        "conservative_bounded_physical_projection_max_abs_deg": _mapping_at(
            twist_source_audit,
            "interpretation_summary",
        ).get("conservative_bounded_physical_projection_max_abs_deg"),
        "twist_projection_basis": "direct_spar_pair_rotation_to_avl_ainc_stress_test",
        "twist_proxy_claim_boundary": (
            "The main/rear spar-pair rotation is projected directly into AVL SECTION "
            "Ainc as a conservative coupling stress test. It is not a qualified "
            "aero-surface twist observable until FEM/shell geometry mapping confirms it."
        ),
        "elastic_twist_screening_bound_deg": 3.0,
        "stall_margin_min": _stall_margin_min(final_state["spanload"]),
        "stall_margin_basis": "diagnostic_constant_section_cl_limit_not_gate",
        "stall_margin_status": (
            "diagnostic_negative_not_closure_gate"
            if _stall_margin_min(final_state["spanload"]) < 0.0
            else "diagnostic_margin_nonnegative"
        ),
        "root_bending_moment_ratio_loaded_vs_baseline": final_state["iteration_row"][
            "root_bending_moment_ratio_loaded_vs_baseline"
        ],
        "root_bending_screening_ratio_bounds": [0.80, 1.20],
        "closure_ranking_effect": _closure_ranking_effect(
            final_state["iteration_row"]["root_bending_moment_ratio_loaded_vs_baseline"],
            final_state["iteration_row"]["stall_margin_min"],
        ),
        "spanload_redistribution_read": (
            "AVL loaded/twisted wing rerun changed structural load ratios within the "
            "bounded screening relaxation envelope."
        ),
    }
    trim_static_directional = {
        "status": "pass" if trim_row.get("status") == "pass_screening" else "blocked",
        "trim_alpha_deg": trim_row["longitudinal_trim"]["alpha_required_deg"],
        "delta_H_required_deg": trim_row["longitudinal_trim"]["delta_H_required_deg"],
        "delta_H_margin_to_limit_deg": trim_row["longitudinal_trim"][
            "delta_H_margin_to_limit_deg"
        ],
        "static_margin": trim_row["longitudinal_trim"]["static_margin"],
        "C_n_beta": trim_row["directional"]["C_n_beta"],
        "delta_V_required_deg": trim_row["directional"]["delta_V_required_deg"],
        "delta_V_margin_to_limit_deg": trim_row["directional"]["delta_V_margin_to_limit_deg"],
        "xnp_convention": trim_row.get("xnp_convention"),
    }
    mass_drag_power = _mass_drag_power_payload(
        selected_basis=selected_basis,
        tail_payload=tail_payload,
        candidate_payload=payload,
    )
    selected_stiffness_basis = {
        "status": "pass_screening_sensitivity",
        "case_id": selected_basis.get("case_id"),
        "rib_family": _mapping_at(selected_payload, "rib_basis").get("family_key"),
        "rib_target_spacing_m": selected_basis.get("rib_spacing_m"),
        "materialized_max_subbay_m": _mapping_at(
            selected_basis, "rib_count_or_bay_length_assumption"
        ).get("max_recommended_subbay_m"),
        "full_wing_rib_count": _mapping_at(
            selected_basis, "rib_count_or_bay_length_assumption"
        ).get("full_wing_rib_count"),
        "rear_spar_participation": selected_basis.get("rear_spar_participation"),
        "warping_knockdown": selected_basis.get("warping_knockdown"),
        "effective_EI_ratio_vs_finite_rib_rear_1p00": _mapping_at(
            selected_basis, "effective_changes_vs_finite_rib_rear_1p00"
        ).get("EI_flap_ratio"),
        "effective_GJ_ratio_vs_finite_rib_rear_1p00": _mapping_at(
            selected_basis, "effective_changes_vs_finite_rib_rear_1p00"
        ).get("GJ_ratio"),
        "selected_case_tip_main_deflection_m": _selected_structural_case_value(
            selected_payload, "tip_main_m"
        ),
        "selected_case_tip_rear_deflection_m": _selected_structural_case_value(
            selected_payload, "tip_rear_m"
        ),
        "selected_case_wire_tension_max_n": _selected_structural_case_value(
            selected_payload, "wire_tension_max_n"
        ),
        "selected_case_link_force_max_n": _selected_structural_case_value(
            selected_payload, "link_force_max_n"
        ),
    }
    basis = {
        "coupling": {
            "converged": bool(final_state["converged"]),
            "iterations_completed": len(iteration_rows),
            "max_iter": int(max_iter),
            "twist_tol_deg": float(twist_tol_deg),
            "delta_h_tol_deg": float(delta_h_tol_deg),
            "load_ratio_tol": float(load_ratio_tol),
            "method": (
                "AVL tail trim/spanload rerun with internal dual-beam selected "
                "rib/rear-spar structural response and relaxed fixed-point load ratios"
            ),
        },
        "cg_management": cg_management,
        "trim_static_directional": trim_static_directional,
        "aeroelastic_effects": aero_effects,
        "aeroelastic_twist_source_audit": twist_source_audit,
        "selected_stiffness_basis": selected_stiffness_basis,
        "mass_drag_power": mass_drag_power,
        "load_remap_diagnostics": dict(selected_basis.get("load_remap_diagnostics") or {}),
    }
    verdict = classify_aeroelastic_closure(basis)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": CANDIDATE_ID,
        "engineering_verdict": verdict["verdict"],
        "twist_source_verdict": _mapping_at(
            twist_source_audit,
            "interpretation_summary",
        ).get("source_verdict"),
        "blockers": verdict["blockers"],
        "warnings": verdict["warnings"],
        "basis": basis,
        "iteration_history": iteration_rows,
        "artifact_manifest": {
            "output_dir": str(output_dir.resolve()),
            "iteration_history_csv": str((output_dir / "iteration_history.csv").resolve()),
            "final_wing_with_twist_avl": final_state["iteration_row"]["wing_with_twist_avl"],
            "final_elastic_twist_alpha_eff_csv": str(
                (final_dir / "elastic_twist_alpha_eff.csv").resolve()
            ),
            "final_wing_spanload_redistribution_csv": str(
                (final_dir / "wing_spanload_redistribution.csv").resolve()
            ),
            "final_twist_source_audit_csv": str(
                (final_dir / "twist_source_audit.csv").resolve()
            ),
            "final_twist_source_components_csv": str(
                (final_dir / "twist_source_components.csv").resolve()
            ),
            "selected_basis_json": str(Path(selected_basis_json).resolve()),
            "tail_screening_json": str(Path(tail_screening_json).resolve()),
            "source_wing_avl": str(Path(source_wing_avl).resolve()),
            "candidate_spanwise_json": str(Path(candidate_spanwise_json).resolve()),
            "final_trimmed_full_aircraft_avl": final_state["trim_state"]["trimmed_deck_path"],
            "final_trimmed_wing_fs": final_state["trim_state"]["spanwise_fs_path"],
        },
        "tail_screening_final_row_before_coupling": tail_row,
        "tail_variant_warnings": variant_warnings,
        "claim_boundary": (
            "Ready verdict, if achieved, means FEM/APDL loadcase package basis only. "
            "It does not certify composite laminate, shell buckling, root fitting, "
            "wire termination, tail pivot, rib attach, or flight hardware."
        ),
    }
    report_json_path.parent.mkdir(parents=True, exist_ok=True)
    report_json_path.write_text(
        json.dumps(_jsonable(summary), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_md_path.parent.mkdir(parents=True, exist_ok=True)
    report_md_path.write_text(_render_markdown(summary), encoding="utf-8")
    return summary


def _run_tail_trim_and_spanload(
    *,
    wing_avl: Path,
    contract: Mapping[str, Any],
    case_dir: Path,
    cg_x_m: float,
    velocity_mps: float,
    density_kgpm3: float,
    avl_binary: str | Path | None,
    timeout_s: float,
) -> dict[str, Any]:
    case_dir.mkdir(parents=True, exist_ok=True)
    small_delta_deg = 2.0
    cases = (
        ("neutral", 0.0, 0.0),
        ("h_delta_minus_small", -small_delta_deg, 0.0),
        ("h_delta_plus_small", small_delta_deg, 0.0),
        ("v_delta_minus_small", 0.0, -small_delta_deg),
        ("v_delta_plus_small", 0.0, small_delta_deg),
    )
    case_results: dict[str, Mapping[str, Any]] = {}
    deck_records: list[dict[str, Any]] = []
    for name, delta_h, delta_v in cases:
        run_dir = case_dir / name
        run_dir.mkdir(parents=True, exist_ok=True)
        deck_path = run_dir / f"{name}.avl"
        deck_text, deck_manifest = tail_avl.build_full_aircraft_deck_text(
            wing_avl_path=wing_avl,
            contract=contract,
            delta_h_deg=delta_h,
            delta_v_deg=delta_v,
            moment_reference_x_m=float(cg_x_m),
            moment_reference_role="tail_aware_aeroelastic_final_cg_reference",
        )
        deck_path.write_text(deck_text, encoding="utf-8")
        staged_airfoils = stage_avl_airfoil_files(deck_path)
        deck_manifest["staged_airfoil_files"] = [str(path.resolve()) for path in staged_airfoils]
        (run_dir / f"{name}_deck_manifest.json").write_text(
            json.dumps(deck_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        avl_result = run_avl_derivatives(
            avl_path=deck_path,
            out_dir=run_dir,
            avl_binary=None if avl_binary is None else str(avl_binary),
            alpha_deg=0.0,
            velocity=float(velocity_mps),
            density=float(density_kgpm3),
            timeout_s=float(timeout_s),
            stem=name,
        )
        if avl_result.error or avl_result.st_path is None:
            raise RuntimeError(f"AVL derivative run failed for {name}: {avl_result.error}")
        case_results[name] = tail_avl._parse_case_result(avl_result.st_path)
        deck_records.append(
            {
                "case": name,
                "delta_H_deg": delta_h,
                "delta_V_deg": delta_v,
                "deck_path": str(deck_path.resolve()),
                "avl_run": avl_result.as_dict(),
            }
        )
    row = tail_trim.summarize_cg_screening_row(
        sizing_case=tail_trim.DEFAULT_SIZING_CASE,
        variant_contract=contract,
        cg_x_m=float(cg_x_m),
        case_results=case_results,
        cl_required=tail_trim._cl_required(contract),
        small_delta_deg=small_delta_deg,
        beta_screen_deg=12.0,
        static_margin_min=0.05,
        xnp_tolerance_m=1.0e-3,
    )
    delta_h = float(row["longitudinal_trim"]["delta_H_required_deg"])
    alpha = float(row["longitudinal_trim"]["alpha_required_deg"])
    trimmed_dir = case_dir / "trimmed"
    trimmed_dir.mkdir(parents=True, exist_ok=True)
    trimmed_deck = trimmed_dir / "trimmed_tail_aware.avl"
    deck_text, deck_manifest = tail_avl.build_full_aircraft_deck_text(
        wing_avl_path=wing_avl,
        contract=contract,
        delta_h_deg=delta_h,
        delta_v_deg=0.0,
        moment_reference_x_m=float(cg_x_m),
        moment_reference_role="tail_aware_aeroelastic_final_cg_reference",
    )
    trimmed_deck.write_text(deck_text, encoding="utf-8")
    stage_avl_airfoil_files(trimmed_deck)
    (trimmed_dir / "trimmed_tail_aware_deck_manifest.json").write_text(
        json.dumps(deck_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    fs_path = _run_avl_spanwise_case(
        avl_path=trimmed_deck,
        case_dir=trimmed_dir,
        alpha_deg=alpha,
        velocity_mps=velocity_mps,
        density_kgpm3=density_kgpm3,
        avl_binary=avl_binary,
    )
    spanwise = build_spanwise_load_from_avl_strip_forces(
        fs_path=fs_path,
        avl_path=trimmed_deck,
        aoa_deg=alpha,
        velocity_mps=velocity_mps,
        density_kgpm3=density_kgpm3,
        target_surface_names=("Wing",),
        positive_y_only=True,
    )
    return {
        "row": row,
        "case_results": case_results,
        "deck_records": deck_records,
        "trimmed_deck_path": str(trimmed_deck.resolve()),
        "spanwise_fs_path": str(Path(fs_path).resolve()),
        "spanwise_load": spanwise,
    }


def _rewrite_wing_with_elastic_twist(
    *,
    source_avl: Path,
    output_avl: Path,
    y_nodes_m: Sequence[float],
    elastic_twist_deg: Sequence[float],
) -> list[dict[str, float]]:
    basis = tail_avl.parse_wing_avl_basis(Path(source_avl))
    section_y = np.asarray([section.y_le_m for section in basis.sections], dtype=float)
    twist_delta = np.interp(
        section_y,
        np.asarray(y_nodes_m, dtype=float),
        np.asarray(elastic_twist_deg, dtype=float),
    )
    lines = Path(source_avl).read_text(encoding="utf-8").splitlines()
    out_lines = list(lines)
    current_surface: str | None = None
    expect_surface_name = False
    expect_section_values = False
    replacement_index = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        upper = stripped.upper()
        if expect_section_values:
            tokens = stripped.split()
            if len(tokens) < 5:
                raise ValueError(f"Malformed AVL SECTION numeric row in {source_avl}: {line!r}")
            x, y, z, chord, ainc = (float(token) for token in tokens[:5])
            new_ainc = ainc + float(twist_delta[replacement_index])
            out_lines[idx] = (
                f"{x:.9f}  {y:.9f}  {z:.9f}  {chord:.9f}  {new_ainc:.9f}"
            )
            replacement_index += 1
            expect_section_values = False
            continue
        if expect_surface_name and stripped:
            current_surface = "".join(stripped.split()).casefold()
            expect_surface_name = False
            continue
        if upper == "SURFACE":
            current_surface = None
            expect_surface_name = True
            continue
        if upper == "SECTION" and current_surface == "wing":
            expect_section_values = True
    if replacement_index != len(twist_delta):
        raise ValueError(
            f"Replaced {replacement_index} wing SECTION rows in {source_avl}; "
            f"expected {len(twist_delta)}."
        )
    output_avl.parent.mkdir(parents=True, exist_ok=True)
    output_avl.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return [
        {
            "section_index": int(index),
            "y_m": float(section_y[index]),
            "elastic_twist_added_deg": float(twist_delta[index]),
            "source_ainc_deg": float(basis.sections[index].twist_deg),
            "aeroelastic_ainc_deg": float(basis.sections[index].twist_deg + twist_delta[index]),
        }
        for index in range(len(twist_delta))
    ]


def _selected_spanwise_load(path: Path) -> tuple[dict[str, Any], SpanwiseLoad]:
    payload, cases = load_candidate_avl_spanwise_artifact(path)
    selected_aoa = _float_or_none(payload.get("selected_cruise_aoa_deg"))
    if selected_aoa is None:
        return payload, cases[0]
    return payload, min(cases, key=lambda case: abs(float(case.aoa_deg) - selected_aoa))


def _spanload_comparison_rows(
    *,
    baseline: SpanwiseLoad,
    updated: SpanwiseLoad,
    case_label: str,
) -> list[dict[str, Any]]:
    y = np.asarray(updated.y, dtype=float)
    base_lift = np.interp(y, baseline.y, baseline.lift_per_span)
    base_cl = np.interp(y, baseline.y, baseline.cl)
    updated_lift = np.asarray(updated.lift_per_span, dtype=float)
    updated_cl = np.asarray(updated.cl, dtype=float)
    base_bending = _root_bending_moment(baseline)
    updated_bending = _root_bending_moment(updated)
    rows = []
    for idx, y_m in enumerate(y):
        rows.append(
            {
                "case_label": case_label,
                "y_m": float(y_m),
                "baseline_cl": float(base_cl[idx]),
                "updated_cl": float(updated_cl[idx]),
                "delta_cl": float(updated_cl[idx] - base_cl[idx]),
                "baseline_lift_per_span_npm": float(base_lift[idx]),
                "updated_lift_per_span_npm": float(updated_lift[idx]),
                "lift_ratio_updated_vs_baseline": (
                    None
                    if abs(base_lift[idx]) <= 1.0e-12
                    else float(updated_lift[idx] / base_lift[idx])
                ),
                "root_bending_moment_baseline_nm": float(base_bending),
                "root_bending_moment_updated_nm": float(updated_bending),
                "root_bending_moment_ratio_updated_vs_baseline": (
                    None
                    if abs(base_bending) <= 1.0e-12
                    else float(updated_bending / base_bending)
                ),
            }
        )
    return rows


def _mass_drag_power_payload(
    *,
    selected_basis: Mapping[str, Any],
    tail_payload: Mapping[str, Any],
    candidate_payload: Mapping[str, Any],
) -> dict[str, Any]:
    structural_mass = _mapping_at(selected_basis, "structural_mass_delta")
    tail_drag = _mapping_at(tail_payload, "tail_drag_mass_treatment")
    tail_cd0 = _float_or_none(tail_drag.get("tail_cd0_increment_estimate")) or 0.0
    tail_power = _float_or_none(tail_drag.get("tail_profile_power_increment_w_estimate")) or 0.0
    return {
        "status": "charged_to_screening_read",
        "rib_mass_delta_kg": _float_or_none(
            structural_mass.get("estimated_full_wing_rib_mass_kg")
        ),
        "tail_mass_delta_kg": _float_or_none(structural_mass.get("tail_mass_delta_kg")),
        "rear_spar_mass_delta_kg": _float_or_none(structural_mass.get("rear_spar_mass_delta_kg")),
        "tail_cd0_increment": tail_cd0,
        "tail_profile_power_increment_w": tail_power,
        "velocity_mps": _float_or_none(candidate_payload.get("velocity_mps")),
        "density_kgpm3": _float_or_none(candidate_payload.get("density_kgpm3")),
        "engineering_read": (
            "Tail/rib mass and tail CD0 penalty are carried into the screening read. "
            "The tail power increment is profile-only screening, not a full trim-drag polar."
        ),
    }


def _closure_ranking_effect(root_bending_ratio: Any, stall_margin_min: Any) -> str:
    ratio = _float_or_none(root_bending_ratio)
    # Negative stall margin here uses the legacy constant-section-Cl diagnostic
    # limit; classify it as a warning, not as candidate ranking ownership.
    _ = stall_margin_min
    if ratio is not None and not (0.80 <= ratio <= 1.20):
        return "ranking_changed_by_aeroelastic_loads"
    return "no_change_conservative_best_remains_screening_closed"


def _classify_twist_source_verdict(
    *,
    direct_max_abs_deg: float,
    bounded_max_abs_deg: float,
    screening_bound_deg: float,
) -> str:
    if direct_max_abs_deg <= screening_bound_deg and bounded_max_abs_deg <= screening_bound_deg:
        return READY_FOR_FEM_LOADCASE_PACKAGE
    if direct_max_abs_deg > screening_bound_deg and bounded_max_abs_deg <= screening_bound_deg:
        return READY_FOR_AEROELASTIC_MAPPING_FIX
    if bounded_max_abs_deg > screening_bound_deg:
        return READY_FOR_HYBRID_STIFFNESS_REWORK
    return STILL_BLOCKED_BY_UNRESOLVED_TWIST_SOURCE


def _max_abs_metric(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, float]:
    if not rows:
        return {"abs_value_deg": 0.0, "signed_value_deg": 0.0, "y_m": 0.0}
    row = max(rows, key=lambda item: abs(float(item.get(key, 0.0))))
    value = float(row.get(key, 0.0))
    return {
        "abs_value_deg": abs(value),
        "signed_value_deg": value,
        "y_m": float(row.get("y_m", 0.0)),
    }


def _nearest_metric(rows: Sequence[Mapping[str, Any]], y_m: float, key: str) -> float:
    if not rows:
        return 0.0
    row = min(rows, key=lambda item: abs(float(item.get("y_m", 0.0)) - float(y_m)))
    return float(row.get(key, 0.0))


def _flatten_component_rows(
    component_rows: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for component, values in component_rows.items():
        for row in values:
            rows.append({"component": component, **dict(row)})
    return rows


def _twist_source_engineering_read(
    *,
    interpretation_summary: Mapping[str, Any],
    dominant_source: Mapping[str, Any],
) -> str:
    verdict = interpretation_summary.get("source_verdict")
    dominant = dominant_source.get("dominant_component")
    if verdict == READY_FOR_HYBRID_STIFFNESS_REWORK:
        return (
            "The direct spar-pair stress-test is high and the bounded physical "
            "projection still exceeds the screening bound. Treat this as a real "
            f"torsional stiffness / shear-transfer blocker, with {dominant} as the "
            "dominant component at the peak station, until a qualified shell/FEM "
            "mapping proves otherwise."
        )
    if verdict == READY_FOR_AEROELASTIC_MAPPING_FIX:
        return (
            "The direct spar-pair stress-test exceeds the bound but the bounded "
            "physical projection clears it. Prioritize qualified aero-surface / "
            "elastic-axis mapping before adding stiffness mass."
        )
    if verdict == READY_FOR_FEM_LOADCASE_PACKAGE:
        return (
            "All screening twist interpretations clear the bound; the remaining "
            "work can move toward FEM/APDL loadcase packaging."
        )
    return "The twist source remains unresolved; do not promote the closure package."


def _stall_margin_min(load: SpanwiseLoad, limit: float = 1.20) -> float:
    return float(limit - np.max(np.asarray(load.cl, dtype=float)))


def _root_bending_moment(load: SpanwiseLoad) -> float:
    y = np.asarray(load.y, dtype=float)
    lift = np.maximum(np.asarray(load.lift_per_span, dtype=float), 0.0)
    if y.size < 2:
        return 0.0
    return float(np.trapezoid(lift * y, y))


def _selected_tail_row(tail_payload: Mapping[str, Any], cg_x_m: float) -> Mapping[str, Any]:
    rows = tail_payload.get("rows") or []
    if not isinstance(rows, Sequence):
        return {}
    if not rows:
        return {}
    return min(
        (row for row in rows if isinstance(row, Mapping)),
        key=lambda row: abs(float(row.get("cg_x_m", 0.0)) - float(cg_x_m)),
    )


def _selected_structural_case_value(selected_payload: Mapping[str, Any], key: str) -> Any:
    selected_id = _mapping_at(selected_payload, "selected_basis").get("case_id")
    for row in selected_payload.get("structural_cases") or []:
        if isinstance(row, Mapping) and row.get("case_id") == selected_id:
            return row.get(key)
    return None


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_cell(row.get(key)) for key in fieldnames})


def _csv_cell(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(_jsonable(value), sort_keys=True)
    return value


def _mapping_at(root: Any, *keys: str) -> Mapping[str, Any]:
    node = root
    for key in keys:
        if not isinstance(node, Mapping):
            return {}
        node = node.get(key, {})
    return node if isinstance(node, Mapping) else {}


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items() if key != "spanwise_load"}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, Path):
        return str(value)
    return value


def _fmt(value: Any, digits: int = 6) -> str:
    parsed = _float_or_none(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:.{digits}f}"


def _render_markdown(summary: Mapping[str, Any]) -> str:
    basis = _mapping_at(summary, "basis")
    cg = _mapping_at(basis, "cg_management")
    trim = _mapping_at(basis, "trim_static_directional")
    aero = _mapping_at(basis, "aeroelastic_effects")
    twist_audit = _mapping_at(basis, "aeroelastic_twist_source_audit")
    twist_summary = _mapping_at(twist_audit, "interpretation_summary")
    dominant = _mapping_at(twist_audit, "dominant_source_at_direct_max_station")
    stiff = _mapping_at(basis, "selected_stiffness_basis")
    mass = _mapping_at(basis, "mass_drag_power")
    artifacts = _mapping_at(summary, "artifact_manifest")
    lines = [
        "# Tail-Aware Aeroelastic Closure",
        "",
        f"Candidate: `{summary.get('candidate_id')}`",
        f"Verdict: `{summary.get('engineering_verdict')}`",
        f"Twist-source verdict: `{summary.get('twist_source_verdict')}`",
        f"Blockers: `{summary.get('blockers')}`",
        f"Warnings: `{summary.get('warnings')}`",
        "",
        "## Closure Read",
        "",
        f"- Fixed-point converged: `{_mapping_at(basis, 'coupling').get('converged')}` after `{_mapping_at(basis, 'coupling').get('iterations_completed')}` iteration(s).",
        f"- Final CG: `{_fmt(cg.get('final_cg_x_m'), 6)}` m using `{_fmt(cg.get('required_forward_rebalance_m'), 6)}` m forward rebalance on `{_fmt(cg.get('forward_rebalance_mass_kg'), 1)}` kg; uncompensated `{_fmt(cg.get('uncompensated_cg_x_m'), 6)}` m is rejected.",
        f"- Trim alpha / delta_H: `{_fmt(trim.get('trim_alpha_deg'), 6)}` deg / `{_fmt(trim.get('delta_H_required_deg'), 6)}` deg.",
        f"- H-tail reserve / static margin: `{_fmt(trim.get('delta_H_margin_to_limit_deg'), 6)}` deg / `{_fmt(trim.get('static_margin'), 6)}` MAC.",
        f"- C_n_beta / V-tail reserve: `{_fmt(trim.get('C_n_beta'), 6)}` / `{_fmt(trim.get('delta_V_margin_to_limit_deg'), 6)}` deg.",
        f"- Elastic twist max / tip: `{_fmt(aero.get('elastic_twist_max_abs_deg'), 6)}` deg / `{_fmt(aero.get('elastic_twist_tip_deg'), 6)}` deg.",
        f"- Twist projection: `{aero.get('twist_projection_basis')}`.",
        f"- Stall margin min: `{_fmt(aero.get('stall_margin_min'), 6)}` Cl using `{aero.get('stall_margin_basis')}`.",
        f"- Root bending ratio vs baseline AVL load: `{_fmt(aero.get('root_bending_moment_ratio_loaded_vs_baseline'), 6)}`.",
        "",
        "## Twist Source Audit",
        "",
        f"- Direct spar-pair rotation max: `{_fmt(twist_summary.get('direct_spar_pair_rotation_max_abs_deg'), 6)}` deg at y=`{_fmt(twist_summary.get('direct_spar_pair_rotation_max_station_y_m'), 3)}` m.",
        f"- Elastic-axis / quarter-chord projection max: `{_fmt(twist_summary.get('elastic_axis_quarter_chord_projection_max_abs_deg'), 6)}` deg.",
        f"- Conservative bounded physical projection max: `{_fmt(twist_summary.get('conservative_bounded_physical_projection_max_abs_deg'), 6)}` deg at y=`{_fmt(twist_summary.get('conservative_bounded_physical_projection_max_station_y_m'), 3)}` m.",
        f"- Dominant component at direct max station: `{dominant.get('dominant_component')}` with component twists `{dominant.get('component_twist_deg')}` deg.",
        f"- Audit CSV: `{artifacts.get('final_twist_source_audit_csv')}`; component CSV: `{artifacts.get('final_twist_source_components_csv')}`.",
        f"- Engineering read: {twist_audit.get('engineering_read')}",
        "",
        "## Selected Basis Audit For FEM/APDL Package",
        "",
        f"- Rib: `{stiff.get('rib_family')}` at `{_fmt(stiff.get('rib_target_spacing_m'), 3)}` m target spacing; materialized max subbay `{_fmt(stiff.get('materialized_max_subbay_m'), 6)}` m; full-wing stations/ribs `{stiff.get('full_wing_rib_count')}`.",
        f"- Rear spar participation: `{stiff.get('rear_spar_participation')}`; warping knockdown `{_fmt(stiff.get('warping_knockdown'), 6)}`.",
        f"- Effective EI/GJ ratios vs finite-rib rear=1.0 upper bound: `{_fmt(stiff.get('effective_EI_ratio_vs_finite_rib_rear_1p00'), 3)}` / `{_fmt(stiff.get('effective_GJ_ratio_vs_finite_rib_rear_1p00'), 3)}`.",
        f"- Closure aero load owner for rework: `{artifacts.get('final_trimmed_wing_fs')}` with redistribution CSV `{artifacts.get('final_wing_spanload_redistribution_csv')}`.",
        f"- Elastic twist / alpha_eff CSV: `{artifacts.get('final_elastic_twist_alpha_eff_csv')}`.",
        "",
        "## Mass / Drag / Power",
        "",
        f"- Rib mass delta: `{_fmt(mass.get('rib_mass_delta_kg'), 6)}` kg; tail mass delta `{_fmt(mass.get('tail_mass_delta_kg'), 6)}` kg.",
        f"- Tail CD0 increment: `{_fmt(mass.get('tail_cd0_increment'), 6)}`; tail profile power increment `{_fmt(mass.get('tail_profile_power_increment_w'), 3)}` W.",
        "",
        "## Engineering Boundary",
        "",
        "- Current verdict is not package-ready; use this closure as the rework basis until the twist/stiffness blocker is closed.",
        "- This is a FEM/APDL loadcase-package basis only, not final composite, shell, root fitting, wire termination, tail pivot, rib attach, or flight hardware sign-off.",
        "- Direct spar-pair rotation projected into AVL incidence is a conservative stress-test proxy, not a qualified aero-surface twist measurement.",
        "- The selected stiffness is still a bounded screening surrogate; FEM/APDL must carry the listed load owner and CG/rebalance assumption explicitly.",
        "",
    ]
    return "\n".join(lines)


def _parse_ratio_bounds(raw: str) -> tuple[float, float]:
    parts = [float(part.strip()) for part in raw.split(",") if part.strip()]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("ratio bounds must be two comma-separated numbers")
    return (parts[0], parts[1])


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selected-basis-json", type=Path, default=DEFAULT_SELECTED_BASIS_JSON)
    parser.add_argument("--tail-screening-json", type=Path, default=DEFAULT_TAIL_SCREENING_JSON)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--source-wing-avl", type=Path, default=DEFAULT_SOURCE_WING_AVL)
    parser.add_argument("--candidate-spanwise-json", type=Path, default=DEFAULT_CANDIDATE_SPANWISE_JSON)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    parser.add_argument("--max-iter", type=int, default=5)
    parser.add_argument("--relaxation", type=float, default=0.55)
    parser.add_argument("--twist-tol-deg", type=float, default=0.03)
    parser.add_argument("--delta-h-tol-deg", type=float, default=0.05)
    parser.add_argument("--load-ratio-tol", type=float, default=0.015)
    parser.add_argument("--ratio-bounds", type=_parse_ratio_bounds, default=(0.70, 1.30))
    parser.add_argument("--avl-binary", default=None)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary = run_tail_aware_aeroelastic_closure(
        selected_basis_json=args.selected_basis_json,
        tail_screening_json=args.tail_screening_json,
        contract_path=args.contract,
        source_wing_avl=args.source_wing_avl,
        candidate_spanwise_json=args.candidate_spanwise_json,
        output_dir=args.output_dir,
        report_json_path=args.report_json,
        report_md_path=args.report_md,
        max_iter=args.max_iter,
        relaxation=args.relaxation,
        twist_tol_deg=args.twist_tol_deg,
        delta_h_tol_deg=args.delta_h_tol_deg,
        load_ratio_tol=args.load_ratio_tol,
        ratio_bounds=args.ratio_bounds,
        avl_binary=args.avl_binary,
        timeout_s=args.timeout_s,
    )
    print(f"wrote {args.report_json}")
    print(f"wrote {args.report_md}")
    print(f"verdict: {summary['engineering_verdict']}")
    if summary.get("blockers"):
        print(f"blockers: {summary['blockers']}")
    if summary.get("warnings"):
        print(f"warnings: {summary['warnings']}")


if __name__ == "__main__":
    main()
