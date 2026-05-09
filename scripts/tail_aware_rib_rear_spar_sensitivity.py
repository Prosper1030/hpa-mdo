#!/usr/bin/env python3
"""Tail-aware bounded rib / rear-spar stiffness sensitivity for the pathfinder."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import numpy as np
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.core import MaterialDB  # noqa: E402
from hpa_mdo.structure.dual_beam_mainline import (  # noqa: E402
    AnalysisModeName,
    DualBeamMainlineModel,
    LinkMode,
    run_dual_beam_mainline_kernel,
)
from hpa_mdo.structure.rib_properties import derive_warping_knockdown  # noqa: E402
from scripts.phase15_candidate_load_factor_buckling_check import CANDIDATE_ID  # noqa: E402
from scripts.phase22_bracing_sensitivity import (  # noqa: E402
    _max_spar_pair_line_angle_delta_deg,
    build_current_candidate_model,
    clone_with_rear_stiffness_scale,
)
from scripts.phase24_rib_spacing_requirements import (  # noqa: E402
    RibSpacingRequirements,
    build_current_rib_spacing_requirements,
)


DEFAULT_TAIL_SCREENING_JSON = (
    REPO_ROOT / "docs" / "reports" / "2026-05-09_tail_cg_trim_stability_screening_v1.json"
)
DEFAULT_CLOSURE_CSV = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "current_avl_compromise_conservative_closed_closure"
    / "aero_structure_closure_summary.csv"
)
DEFAULT_CONFIG = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "current_avl_compromise_conservative_closed_z_boundary"
    / "smooth_tier2_canonical_config.yaml"
)
DEFAULT_REPORT_JSON = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "2026-05-09_tail_aware_rib_rear_spar_sensitivity.json"
)
DEFAULT_REPORT_MD = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "2026-05-09_tail_aware_rib_rear_spar_sensitivity.md"
)

READY_TAIL_VERDICT = "ready_for_tail_aware_rib_rear_spar_sensitivity"
READY_VERDICT = "ready_for_tail_aware_aeroelastic_closure"
NEEDS_RIB_VERDICT = "needs_rib_rear_spar_redesign_before_aeroelastic_closure"
NEEDS_CG_VERDICT = "needs_tail_cg_rework_before_rib_sensitivity"
NOT_VIABLE_VERDICT = "pathfinder_not_viable_under_reasonable_rib_rear_spar_tail_bounds"


@dataclass(frozen=True)
class MassItem:
    name: str
    mass_kg: float
    x_m: float


@dataclass(frozen=True)
class StructuralSensitivityCase:
    case_id: str
    status: str
    blockers: tuple[str, ...]
    link_mode: str
    rear_stiffness_scale: float
    rear_spar_participation: str
    warping_knockdown: float
    physical_rib_station_count: int
    full_wing_rib_count: int
    tip_main_m: float
    tip_rear_m: float
    max_vertical_displacement_m: float
    max_spar_pair_line_angle_delta_deg: float
    link_force_max_n: float
    wire_tension_max_n: float
    tip_main_delta_vs_baseline_pct: float
    max_vertical_delta_vs_baseline_pct: float
    angle_delta_vs_baseline_deg: float
    effective_ei_flap_ratio_vs_baseline: float
    effective_gj_ratio_vs_baseline: float
    structural_read: str
    effective_ei_flap_nm2: float = 0.0
    effective_gj_nm2: float = 0.0


def assess_mass_cg_coupling(
    *,
    base_mass_kg: float,
    base_cg_x_m: float,
    cg_range_x_m: tuple[float, float],
    final_screening_cg_x_m: float,
    mass_items: Sequence[MassItem],
    forward_rebalance_mass_kg: float = 56.0,
    forward_rebalance_limit_m: float = 0.20,
) -> dict[str, Any]:
    """Assess whether added aft mass silently invalidates the tail screening range."""

    if base_mass_kg <= 0.0:
        raise ValueError("base_mass_kg must be positive.")
    if forward_rebalance_mass_kg <= 0.0:
        raise ValueError("forward_rebalance_mass_kg must be positive.")
    cg_min, cg_max = (float(cg_range_x_m[0]), float(cg_range_x_m[1]))
    if not (cg_min <= final_screening_cg_x_m <= cg_max):
        raise ValueError("final_screening_cg_x_m must be inside cg_range_x_m.")

    total_mass = float(base_mass_kg) + sum(float(item.mass_kg) for item in mass_items)
    moment = float(base_mass_kg) * float(base_cg_x_m) + sum(
        float(item.mass_kg) * float(item.x_m) for item in mass_items
    )
    uncompensated_cg = moment / total_mass
    excess_moment = max(0.0, moment - float(final_screening_cg_x_m) * total_mass)
    required_forward_shift = excess_moment / float(forward_rebalance_mass_kg)

    if uncompensated_cg <= cg_max + 1.0e-12:
        uncompensated_status = "uncompensated_cg_inside_screening_range"
        screening_status = "final_cg_screening_row_available_without_rebalance"
    else:
        uncompensated_status = "uncompensated_cg_exceeds_screening_range"
        screening_status = (
            "final_cg_screening_row_remains_available_with_rebalance"
            if required_forward_shift <= float(forward_rebalance_limit_m) + 1.0e-12
            else "tail_cg_rework_required_before_stiffness_claim"
        )

    return {
        "base_mass_kg": round(float(base_mass_kg), 6),
        "base_cg_x_m": round(float(base_cg_x_m), 6),
        "cg_range_x_m": [round(cg_min, 6), round(cg_max, 6)],
        "final_screening_cg_x_m": round(float(final_screening_cg_x_m), 6),
        "mass_items": [asdict(item) for item in mass_items],
        "total_mass_after_items_kg": round(total_mass, 6),
        "uncompensated_cg_x_m": round(uncompensated_cg, 6),
        "uncompensated_status": uncompensated_status,
        "required_forward_rebalance_m": round(required_forward_shift, 6),
        "forward_rebalance_mass_kg": round(float(forward_rebalance_mass_kg), 6),
        "forward_rebalance_limit_m": round(float(forward_rebalance_limit_m), 6),
        "screening_status": screening_status,
        "engineering_read": (
            "If the uncompensated CG exceeds the committed range, aeroelastic closure must use "
            "the final screening CG row only with an explicit mass-budget rebalance. Do not add "
            "tail/rib/rear-spar mass after the fact and keep the old tail verdict silently."
        ),
    }


def evaluate_structural_case(
    *,
    case_id: str,
    model: DualBeamMainlineModel,
    rear_stiffness_scale: float,
    link_mode: LinkMode,
    warping_knockdown: float,
    require_physical_rib_stations: bool,
    physical_rib_station_count: int,
    baseline: StructuralSensitivityCase | None,
    full_wing_rib_count: int = 0,
    response_tip_limit_m: float | None = None,
    spar_pair_angle_limit_deg: float = 8.0,
    rear_participation_lower_bound: float = 0.50,
    rear_participation_upper_bound: float = 0.85,
) -> StructuralSensitivityCase:
    """Run one bounded structural sensitivity case through the dual-beam kernel."""

    if rear_stiffness_scale <= 0.0:
        raise ValueError("rear_stiffness_scale must be positive.")
    case_model = (
        clone_with_rear_stiffness_scale(model, float(rear_stiffness_scale))
        if abs(float(rear_stiffness_scale) - 1.0) > 1.0e-12
        else model
    )
    mode = (
        AnalysisModeName.DUAL_BEAM_ROBUSTNESS
        if link_mode == LinkMode.DENSE_FINITE_RIB
        else AnalysisModeName.DUAL_BEAM_PRODUCTION
    )
    result = run_dual_beam_mainline_kernel(
        model=case_model,
        mode=mode,
        link_mode=link_mode,
    )
    angle_delta = _max_spar_pair_line_angle_delta_deg(
        case_model,
        result.disp_main_m,
        result.disp_rear_m,
    )
    stiffness = _effective_stiffness(case_model, warping_knockdown=float(warping_knockdown))
    baseline_ei = baseline.effective_ei_flap_nm2 if baseline is not None else stiffness["ei_flap_nm2"]
    baseline_gj = baseline.effective_gj_nm2 if baseline is not None else stiffness["gj_nm2"]
    baseline_tip = baseline.tip_main_m if baseline is not None else result.report.tip_deflection_main_m
    baseline_max = (
        baseline.max_vertical_displacement_m
        if baseline is not None
        else result.report.max_vertical_displacement_m
    )
    baseline_angle = (
        baseline.max_spar_pair_line_angle_delta_deg if baseline is not None else angle_delta
    )
    tip_limit = (
        float(response_tip_limit_m)
        if response_tip_limit_m is not None
        else float(case_model.max_tip_deflection_limit_m or 2.5)
    )

    blockers: list[str] = []
    if require_physical_rib_stations and int(physical_rib_station_count) <= 0:
        blockers.append("physical_rib_station_basis_missing")
    if require_physical_rib_stations and link_mode != LinkMode.DENSE_FINITE_RIB:
        blockers.append("finite_rib_link_basis_missing")
    if rear_stiffness_scale < float(rear_participation_lower_bound):
        blockers.append("rear_spar_participation_below_reasonable_screening_bound")
    if rear_stiffness_scale > float(rear_participation_upper_bound):
        blockers.append("rear_spar_participation_above_selection_bound")
    if result.report.tip_deflection_main_m > tip_limit:
        blockers.append("tip_deflection_exceeds_screening_limit")
    if abs(angle_delta) > float(spar_pair_angle_limit_deg):
        blockers.append("spar_pair_angle_delta_exceeds_screening_limit")
    if (
        len(case_model.wire_allowable_tension_n)
        and result.recovery.max_wire_tension_n
        > float(np.min(case_model.wire_allowable_tension_n)) + 1.0e-9
    ):
        blockers.append("wire_tension_exceeds_allowable")
    if link_mode == LinkMode.DENSE_FINITE_RIB and result.report.link_force_max_n <= 0.0:
        blockers.append("finite_rib_link_force_missing")

    status = "pass_screening_sensitivity" if not blockers else "blocked"
    return StructuralSensitivityCase(
        case_id=str(case_id),
        status=status,
        blockers=tuple(blockers),
        link_mode=link_mode.value,
        rear_stiffness_scale=float(rear_stiffness_scale),
        rear_spar_participation=f"bounded_{int(round(float(rear_stiffness_scale) * 100.0))}pct_screening",
        warping_knockdown=float(warping_knockdown),
        physical_rib_station_count=int(physical_rib_station_count),
        full_wing_rib_count=int(full_wing_rib_count),
        tip_main_m=float(result.report.tip_deflection_main_m),
        tip_rear_m=float(result.report.tip_deflection_rear_m),
        max_vertical_displacement_m=float(result.report.max_vertical_displacement_m),
        max_spar_pair_line_angle_delta_deg=float(angle_delta),
        link_force_max_n=float(result.report.link_force_max_n),
        wire_tension_max_n=float(result.recovery.max_wire_tension_n),
        tip_main_delta_vs_baseline_pct=_pct_delta(
            result.report.tip_deflection_main_m,
            baseline_tip,
        ),
        max_vertical_delta_vs_baseline_pct=_pct_delta(
            result.report.max_vertical_displacement_m,
            baseline_max,
        ),
        angle_delta_vs_baseline_deg=float(angle_delta) - float(baseline_angle),
        effective_ei_flap_ratio_vs_baseline=_safe_ratio(stiffness["ei_flap_nm2"], baseline_ei),
        effective_gj_ratio_vs_baseline=_safe_ratio(stiffness["gj_nm2"], baseline_gj),
        structural_read=(
            "Finite-rib surrogate with bounded rear-spar participation; screening only."
            if status == "pass_screening_sensitivity"
            else "Case is not selectable for the next aeroelastic closure basis."
        ),
        effective_ei_flap_nm2=float(stiffness["ei_flap_nm2"]),
        effective_gj_nm2=float(stiffness["gj_nm2"]),
    )


def build_summary_payload(
    *,
    candidate_id: str,
    tail_basis: Mapping[str, Any],
    structural_cases: Sequence[StructuralSensitivityCase],
    selected_case: StructuralSensitivityCase | None,
    mass_cg_assessment: Mapping[str, Any],
    rib_basis: Mapping[str, Any],
    closure_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the committed verdict payload."""

    verdict = _verdict(
        tail_basis=tail_basis,
        structural_cases=structural_cases,
        selected_case=selected_case,
        mass_cg_assessment=mass_cg_assessment,
    )
    selected_basis = None
    if selected_case is not None:
        tail_margins = _tail_margin_payload(tail_basis)
        selected_basis = {
            "case_id": selected_case.case_id,
            "rib_spacing_m": rib_basis.get("spacing_m"),
            "rib_count_or_bay_length_assumption": {
                "half_wing_station_count": rib_basis.get("half_wing_station_count"),
                "full_wing_rib_count": rib_basis.get("full_wing_rib_count"),
                "max_recommended_subbay_m": rib_basis.get("max_recommended_subbay_m"),
                "source": "Phase24 physical station layout, not bare local-wall bay assumption",
            },
            "rear_spar_participation": selected_case.rear_spar_participation,
            "rear_stiffness_scale": selected_case.rear_stiffness_scale,
            "warping_knockdown": selected_case.warping_knockdown,
            "effective_changes_vs_finite_rib_rear_1p00": {
                "EI_flap_ratio": selected_case.effective_ei_flap_ratio_vs_baseline,
                "GJ_ratio": selected_case.effective_gj_ratio_vs_baseline,
                "tip_main_delta_pct": selected_case.tip_main_delta_vs_baseline_pct,
                "max_vertical_delta_pct": selected_case.max_vertical_delta_vs_baseline_pct,
                "angle_delta_deg": selected_case.angle_delta_vs_baseline_deg,
            },
            "structural_mass_delta": {
                "estimated_full_wing_rib_mass_kg": rib_basis.get(
                    "estimated_full_wing_rib_mass_kg"
                ),
                "tail_mass_delta_kg": _tail_mass_delta(tail_basis),
                "rear_spar_mass_delta_kg": 0.0,
                "basis": (
                    "Rib mass is a screening estimate for making the 0.30 m station "
                    "basis physical; rear-spar scale is participation/stiffness, not a "
                    "new tube redesign mass claim."
                ),
            },
            "cg_impact": dict(mass_cg_assessment),
            "tail_margins_after_mass_stiffness_changes": tail_margins,
            "tail_trim_static_directional_margins_after_mass_stiffness_changes": tail_margins,
            "load_remap_diagnostics": {
                "status": "conserved",
                "source": "docs/reports/2026-05-09_conservative_load_mapper_foundation.md",
                "engineering_read": (
                    "Current committed smoke shows small conservative projection correction "
                    "with no sign reversal; rerun if the aero load owner changes."
                ),
            },
            "closure_ranking_changes": _closure_ranking_read(closure_rows),
        }
    return {
        "schema_version": "tail_aware_rib_rear_spar_sensitivity_v1",
        "candidate_id": str(candidate_id),
        "engineering_verdict": verdict,
        "selected_case_id": None if selected_case is None else selected_case.case_id,
        "tail_screening_basis": _tail_basis_summary(tail_basis),
        "rib_basis": dict(rib_basis),
        "mass_cg_assessment": dict(mass_cg_assessment),
        "structural_cases": [asdict(case) for case in structural_cases],
        "selected_basis": selected_basis,
        "claim_boundary": (
            "Engineering screening only: not final FEM, not hardware certification, not "
            "local wall buckling full-wing signoff, and not an ASWing binary requirement."
        ),
    }


def run_tail_aware_rib_rear_spar_sensitivity(
    *,
    tail_screening_json: Path = DEFAULT_TAIL_SCREENING_JSON,
    closure_csv: Path = DEFAULT_CLOSURE_CSV,
    config_path: Path = DEFAULT_CONFIG,
    report_json_path: Path = DEFAULT_REPORT_JSON,
    report_md_path: Path = DEFAULT_REPORT_MD,
    base_mass_kg: float = 96.0,
    base_cg_x_m: float = 0.72,
    final_screening_cg_x_m: float = 0.75,
    forward_rebalance_mass_kg: float = 56.0,
    forward_rebalance_limit_m: float = 0.20,
) -> dict[str, Any]:
    tail_basis = _read_json(Path(tail_screening_json))
    _validate_tail_basis(tail_basis)
    model = build_current_candidate_model()
    spacing_requirements = build_current_rib_spacing_requirements()
    rib_basis = build_rib_basis(
        spacing_requirements=spacing_requirements,
        model=model,
        config_path=Path(config_path),
    )
    tail_item = MassItem("selected_tail_screening_delta", _tail_mass_delta(tail_basis), _tail_cg_x(tail_basis))
    rib_item = MassItem(
        "physical_rib_station_pack",
        float(rib_basis["estimated_full_wing_rib_mass_kg"]),
        float(rib_basis["estimated_rib_pack_cg_x_m"]),
    )
    mass_cg = assess_mass_cg_coupling(
        base_mass_kg=float(base_mass_kg),
        base_cg_x_m=float(base_cg_x_m),
        cg_range_x_m=tuple(_cg_range(tail_basis)),
        final_screening_cg_x_m=float(final_screening_cg_x_m),
        mass_items=(tail_item, rib_item),
        forward_rebalance_mass_kg=float(forward_rebalance_mass_kg),
        forward_rebalance_limit_m=float(forward_rebalance_limit_m),
    )

    baseline = evaluate_structural_case(
        case_id="finite_rib_rear_1p00_upper_bound",
        model=model,
        rear_stiffness_scale=1.0,
        link_mode=LinkMode.DENSE_FINITE_RIB,
        warping_knockdown=float(rib_basis["warping_knockdown"]),
        require_physical_rib_stations=True,
        physical_rib_station_count=int(rib_basis["half_wing_station_count"]),
        full_wing_rib_count=int(rib_basis["full_wing_rib_count"]),
        baseline=None,
    )
    cases = [
        evaluate_structural_case(
            case_id="joint_only_current_rear_1p00_not_selectable",
            model=model,
            rear_stiffness_scale=1.0,
            link_mode=LinkMode.JOINT_ONLY_OFFSET_RIGID,
            warping_knockdown=float(rib_basis["warping_knockdown"]),
            require_physical_rib_stations=True,
            physical_rib_station_count=0,
            full_wing_rib_count=0,
            baseline=baseline,
        ),
        evaluate_structural_case(
            case_id="finite_rib_rear_0p30_stress_case",
            model=model,
            rear_stiffness_scale=0.30,
            link_mode=LinkMode.DENSE_FINITE_RIB,
            warping_knockdown=float(rib_basis["warping_knockdown"]),
            require_physical_rib_stations=True,
            physical_rib_station_count=int(rib_basis["half_wing_station_count"]),
            full_wing_rib_count=int(rib_basis["full_wing_rib_count"]),
            baseline=baseline,
        ),
        evaluate_structural_case(
            case_id="finite_rib_rear_0p50_selected_screening_basis",
            model=model,
            rear_stiffness_scale=0.50,
            link_mode=LinkMode.DENSE_FINITE_RIB,
            warping_knockdown=float(rib_basis["warping_knockdown"]),
            require_physical_rib_stations=True,
            physical_rib_station_count=int(rib_basis["half_wing_station_count"]),
            full_wing_rib_count=int(rib_basis["full_wing_rib_count"]),
            baseline=baseline,
        ),
        evaluate_structural_case(
            case_id="finite_rib_rear_0p65_confirmation",
            model=model,
            rear_stiffness_scale=0.65,
            link_mode=LinkMode.DENSE_FINITE_RIB,
            warping_knockdown=float(rib_basis["warping_knockdown"]),
            require_physical_rib_stations=True,
            physical_rib_station_count=int(rib_basis["half_wing_station_count"]),
            full_wing_rib_count=int(rib_basis["full_wing_rib_count"]),
            baseline=baseline,
        ),
        baseline,
    ]
    selected = _select_case(cases)
    closure_rows = _read_csv_rows(Path(closure_csv))
    summary = build_summary_payload(
        candidate_id=CANDIDATE_ID,
        tail_basis=tail_basis,
        structural_cases=tuple(cases),
        selected_case=selected,
        mass_cg_assessment=mass_cg,
        rib_basis=rib_basis,
        closure_rows=tuple(closure_rows),
    )
    report_json_path.parent.mkdir(parents=True, exist_ok=True)
    report_json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_md_path.parent.mkdir(parents=True, exist_ok=True)
    report_md_path.write_text(_render_markdown(summary), encoding="utf-8")
    return summary


def build_rib_basis(
    *,
    spacing_requirements: RibSpacingRequirements,
    model: DualBeamMainlineModel,
    config_path: Path,
    family_key: str = "balsa_sheet_3mm",
) -> dict[str, Any]:
    """Make the rib spacing assumption physical enough for screening bookkeeping."""

    spacing_m = float(spacing_requirements.target_bay_m)
    max_subbay = float(spacing_requirements.max_recommended_subbay_m)
    warping_knockdown = derive_warping_knockdown(family_key, max_subbay)
    stations = _recommended_half_wing_stations(spacing_requirements)
    rib_mass = _estimate_full_wing_rib_mass_kg(
        stations_y_m=stations,
        config_path=Path(config_path),
        family_key=family_key,
    )
    rib_cg = _estimate_rib_pack_cg_x_m(stations_y_m=stations, model=model)
    half_count = len(stations)
    return {
        "family_key": family_key,
        "spacing_m": round(spacing_m, 6),
        "max_recommended_subbay_m": round(max_subbay, 6),
        "half_wing_station_count": int(half_count),
        "full_wing_rib_count": int(2 * half_count - 1),
        "added_half_wing_station_count_from_phase24": int(
            spacing_requirements.total_added_bracing_stations
        ),
        "warping_knockdown": round(float(warping_knockdown), 6),
        "estimated_full_wing_rib_mass_kg": round(float(rib_mass), 6),
        "estimated_rib_pack_cg_x_m": round(float(rib_cg), 6),
        "mass_model": (
            "airfoil side-area proxy: 0.65 * t/c * chord^2, 55% solid web/cap "
            "fraction, 15% adhesive/cap factor; screening only."
        ),
        "engineering_read": (
            "The 0.30 m bay is accepted only as this materialized station layout, "
            "not as a naked local-wall-buckling assumption."
        ),
    }


def _effective_stiffness(
    model: DualBeamMainlineModel,
    *,
    warping_knockdown: float,
) -> dict[str, float]:
    main_e = _elem_array(model.main_young_pa, model.main_area_m2)
    rear_e = _elem_array(model.rear_young_pa, model.rear_area_m2)
    main_g = _elem_array(model.main_shear_pa, model.main_area_m2)
    rear_g = _elem_array(model.rear_shear_pa, model.rear_area_m2)
    main_a = np.asarray(model.main_area_m2, dtype=float)
    rear_a = np.asarray(model.rear_area_m2, dtype=float)
    main_i = np.asarray(model.main_iy_m4, dtype=float)
    rear_i = np.asarray(model.rear_iy_m4, dtype=float)
    main_j = np.asarray(model.main_j_m4, dtype=float)
    rear_j = np.asarray(model.rear_j_m4, dtype=float)
    main_z = _element_mean(np.asarray(model.nodes_main_m[:, 2], dtype=float))
    rear_z = _element_mean(np.asarray(model.nodes_rear_m[:, 2], dtype=float))
    separation = _element_mean(np.asarray(model.spar_separation_nodes_m, dtype=float))
    denom = main_e * main_a + rear_e * rear_a + 1.0e-30
    z_na = (main_e * main_a * main_z + rear_e * rear_a * rear_z) / denom
    ei_flap = (
        main_e * (main_i + main_a * (main_z - z_na) ** 2)
        + rear_e * (rear_i + rear_a * (rear_z - z_na) ** 2)
    )
    gj = (
        main_g * main_j
        + rear_g * rear_j
        + float(warping_knockdown) * (main_e * main_a * rear_e * rear_a) / denom * separation**2
    )
    weights = np.asarray(model.element_lengths_m, dtype=float)
    return {
        "ei_flap_nm2": float(np.average(ei_flap, weights=weights)),
        "gj_nm2": float(np.average(gj, weights=weights)),
    }


def _estimate_full_wing_rib_mass_kg(
    *,
    stations_y_m: Sequence[float],
    config_path: Path,
    family_key: str,
) -> float:
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    wing = config.get("wing") if isinstance(config, Mapping) else {}
    if not isinstance(wing, Mapping):
        raise ValueError("config wing section is required for rib mass estimate.")
    chord_schedule = wing.get("chord_schedule")
    if not isinstance(chord_schedule, list):
        chord_schedule = [
            [0.0, float(wing["root_chord"])],
            [0.5 * float(wing["span"]), float(wing["tip_chord"])],
        ]
    root_tc = float(wing.get("airfoil_root_tc", 0.14))
    tip_tc = float(wing.get("airfoil_tip_tc", root_tc))
    half_span = 0.5 * float(wing["span"])
    catalog_material = MaterialDB().get("balsa" if family_key == "balsa_sheet_3mm" else "balsa")
    thickness = 0.003 if family_key == "balsa_sheet_3mm" else 0.003
    total = 0.0
    for index, y_m in enumerate(stations_y_m):
        chord = _interp_schedule(chord_schedule, float(y_m))
        tc = root_tc + (tip_tc - root_tc) * min(max(float(y_m) / half_span, 0.0), 1.0)
        side_area = 0.65 * tc * chord * chord
        single_rib_mass = side_area * thickness * float(catalog_material.density) * 0.55 * 1.15
        mirror_factor = 1.0 if index == 0 else 2.0
        total += mirror_factor * single_rib_mass
    return float(total)


def _estimate_rib_pack_cg_x_m(
    *,
    stations_y_m: Sequence[float],
    model: DualBeamMainlineModel,
) -> float:
    y_nodes = np.asarray(model.y_nodes_m, dtype=float)
    main_x = np.asarray(model.nodes_main_m[:, 0], dtype=float)
    rear_x = np.asarray(model.nodes_rear_m[:, 0], dtype=float)
    xs = []
    for y_m in stations_y_m:
        main = float(np.interp(float(y_m), y_nodes, main_x))
        rear = float(np.interp(float(y_m), y_nodes, rear_x))
        xs.append(0.5 * (main + rear))
    return float(np.mean(xs))


def _recommended_half_wing_stations(requirements: RibSpacingRequirements) -> tuple[float, ...]:
    stations: set[float] = set()
    for row in requirements.rows:
        stations.add(float(row.start_y_m))
        stations.add(float(row.end_y_m))
        stations.update(float(value) for value in row.recommended_intermediate_y_m)
    return tuple(sorted(stations))


def _select_case(cases: Sequence[StructuralSensitivityCase]) -> StructuralSensitivityCase | None:
    preferred = [
        case
        for case in cases
        if case.status == "pass_screening_sensitivity"
        and 0.50 <= case.rear_stiffness_scale <= 0.75
        and case.link_mode == LinkMode.DENSE_FINITE_RIB.value
    ]
    if preferred:
        return sorted(preferred, key=lambda case: (case.rear_stiffness_scale, case.tip_main_m))[0]
    passing = [case for case in cases if case.status == "pass_screening_sensitivity"]
    return passing[0] if passing else None


def _verdict(
    *,
    tail_basis: Mapping[str, Any],
    structural_cases: Sequence[StructuralSensitivityCase],
    selected_case: StructuralSensitivityCase | None,
    mass_cg_assessment: Mapping[str, Any],
) -> str:
    if tail_basis.get("engineering_verdict") != READY_TAIL_VERDICT:
        return NEEDS_CG_VERDICT
    if mass_cg_assessment.get("screening_status") == "tail_cg_rework_required_before_stiffness_claim":
        return NEEDS_CG_VERDICT
    if selected_case is None:
        if any(case.status == "blocked" for case in structural_cases):
            return NEEDS_RIB_VERDICT
        return NOT_VIABLE_VERDICT
    return READY_VERDICT


def _tail_basis_summary(tail_basis: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping_at(tail_basis, "selected_basis")
    return {
        "engineering_verdict": tail_basis.get("engineering_verdict"),
        "cg_range_x_m": _cg_range(tail_basis),
        "horizontal_tail": _mapping_at(selected, "geometry", "horizontal_tail"),
        "vertical_tail": _mapping_at(selected, "geometry", "vertical_tail"),
        "tail_drag_mass_treatment": tail_basis.get("tail_drag_mass_treatment"),
    }


def _tail_margin_payload(tail_basis: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping_at(tail_basis, "selected_basis")
    return {
        "worst_static_margin": selected.get("worst_static_margin"),
        "max_abs_delta_H_required_deg": selected.get("max_abs_delta_H_required_deg"),
        "worst_delta_H_margin_to_limit_deg": selected.get(
            "worst_delta_H_margin_to_limit_deg"
        ),
        "max_abs_delta_V_required_deg": selected.get("max_abs_delta_V_required_deg"),
        "worst_delta_V_margin_to_limit_deg": selected.get(
            "worst_delta_V_margin_to_limit_deg"
        ),
        "C_n_beta_min_row": _min_tail_row_field(tail_basis, ("directional", "C_n_beta")),
        "basis": "Committed tail v1 rows; stiffness changes do not alter AVL tail derivatives in this screening runner.",
    }


def _closure_ranking_read(closure_rows: Sequence[Mapping[str, Any]]) -> str:
    by_role = {str(row.get("selected_role")): row for row in closure_rows}
    conservative = str(by_role.get("conservative_best", {}).get("closure_status", ""))
    raw = str(by_role.get("raw_best", {}).get("closure_status", ""))
    if conservative == "closed_for_screening" and raw != "closed_for_screening":
        return "no_change_conservative_best_remains_screening_closed"
    if conservative == "closed_for_screening":
        return "conservative_best_still_screening_closed_but_raw_role_needs_review"
    return "closure_ranking_requires_loopback"


def _validate_tail_basis(tail_basis: Mapping[str, Any]) -> None:
    if tail_basis.get("engineering_verdict") != READY_TAIL_VERDICT:
        raise ValueError(f"Tail basis is not ready: {tail_basis.get('engineering_verdict')}")
    cg_range = _cg_range(tail_basis)
    if [round(cg_range[0], 2), round(cg_range[1], 2)] != [0.68, 0.75]:
        raise ValueError(f"Unexpected committed CG range: {cg_range}")


def _tail_mass_delta(tail_basis: Mapping[str, Any]) -> float:
    return float(
        _mapping_at(tail_basis, "tail_drag_mass_treatment").get(
            "tail_mass_delta_kg_estimate",
            0.0,
        )
    )


def _tail_cg_x(tail_basis: Mapping[str, Any]) -> float:
    geom = _mapping_at(tail_basis, "selected_basis", "geometry")
    h = _mapping_at(geom, "horizontal_tail")
    v = _mapping_at(geom, "vertical_tail")
    h_area = float(h.get("S_H_m2", 0.0))
    v_area = float(v.get("S_V_m2", 0.0))
    total = h_area + v_area
    if total <= 0.0:
        return float(h.get("x_ac_H_m", 0.0) or 0.0)
    return (h_area * float(h["x_ac_H_m"]) + v_area * float(v["x_ac_V_m"])) / total


def _cg_range(tail_basis: Mapping[str, Any]) -> list[float]:
    selected = _mapping_at(tail_basis, "selected_basis")
    values = selected.get("recommended_cg_range_x_m")
    if not isinstance(values, list | tuple) or len(values) != 2:
        values = _mapping_at(tail_basis, "screening_assumption_contract").get("cg_range_x_m")
    if not isinstance(values, list | tuple) or len(values) != 2:
        raise ValueError("Tail basis must carry a two-value CG range.")
    return [float(values[0]), float(values[1])]


def _min_tail_row_field(tail_basis: Mapping[str, Any], path: tuple[str, str]) -> float | None:
    values = []
    for row in tail_basis.get("rows", []):
        if not isinstance(row, Mapping):
            continue
        container = row.get(path[0])
        if isinstance(container, Mapping) and container.get(path[1]) is not None:
            values.append(float(container[path[1]]))
    return None if not values else round(min(values), 6)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _render_markdown(summary: Mapping[str, Any]) -> str:
    selected = summary.get("selected_basis")
    lines = [
        "# Tail-Aware Rib / Rear-Spar Sensitivity",
        "",
        f"Candidate: `{summary.get('candidate_id')}`",
        f"Verdict: `{summary.get('engineering_verdict')}`",
        "",
        "## Selected Basis",
        "",
    ]
    if isinstance(selected, Mapping):
        eff = _mapping_at(selected, "effective_changes_vs_finite_rib_rear_1p00")
        mass = _mapping_at(selected, "structural_mass_delta")
        cg = _mapping_at(selected, "cg_impact")
        tail = _mapping_at(selected, "tail_trim_static_directional_margins_after_mass_stiffness_changes")
        lines.extend(
            [
                f"- case: `{selected.get('case_id')}`",
                f"- rib spacing / bay: `{selected.get('rib_spacing_m')}` m target; "
                f"max materialized subbay `{_mapping_at(selected, 'rib_count_or_bay_length_assumption').get('max_recommended_subbay_m')}` m",
                f"- rib count basis: `{_mapping_at(selected, 'rib_count_or_bay_length_assumption').get('full_wing_rib_count')}` full-wing ribs/stations",
                f"- rear spar participation: `{selected.get('rear_spar_participation')}`",
                f"- warping knockdown: `{selected.get('warping_knockdown')}`",
                f"- EI/GJ ratios vs finite-rib rear=1.0 upper bound: "
                f"`EI {eff.get('EI_flap_ratio'):.3f}`, `GJ {eff.get('GJ_ratio'):.3f}`",
                f"- structural / aircraft mass deltas: rib `{mass.get('estimated_full_wing_rib_mass_kg')}` kg, "
                f"tail `{mass.get('tail_mass_delta_kg')}` kg, rear spar `{mass.get('rear_spar_mass_delta_kg')}` kg",
                f"- CG status: `{cg.get('screening_status')}`; uncompensated CG `{cg.get('uncompensated_cg_x_m')}` m; "
                f"required forward rebalance `{cg.get('required_forward_rebalance_m')}` m on "
                f"`{cg.get('forward_rebalance_mass_kg')}` kg",
                f"- tail margins: SM `{tail.get('worst_static_margin')}` MAC, "
                f"delta_H reserve `{tail.get('worst_delta_H_margin_to_limit_deg')}` deg, "
                f"C_n_beta min `{tail.get('C_n_beta_min_row')}`",
                f"- load remap: `{_mapping_at(selected, 'load_remap_diagnostics').get('status')}`",
                f"- closure ranking: `{selected.get('closure_ranking_changes')}`",
            ]
        )
    else:
        lines.append("- No selectable basis.")
    lines.extend(
        [
            "",
            "## Structural Cases",
            "",
            "| case | status | blockers | rear scale | link | tip m | angle deg | link force N | wire N | EI ratio | GJ ratio |",
            "|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for case in summary.get("structural_cases", []):
        lines.append(
            f"| {case['case_id']} | `{case['status']}` | `{case['blockers']}` | "
            f"{case['rear_stiffness_scale']:.2f} | `{case['link_mode']}` | "
            f"{case['tip_main_m']:.3f} | {case['max_spar_pair_line_angle_delta_deg']:.3f} | "
            f"{case['link_force_max_n']:.1f} | {case['wire_tension_max_n']:.1f} | "
            f"{case['effective_ei_flap_ratio_vs_baseline']:.3f} | "
            f"{case['effective_gj_ratio_vs_baseline']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Boundary",
            "",
            "- This is an engineering-screening basis for the next aeroelastic closure, not final FEM or hardware certification.",
            "- The 0.30 m rib bay is only accepted because this report ties it to physical station count and mass bookkeeping.",
            "- The selected rear-spar participation is bounded below the rigid 1.0 upper-bound case.",
            "- Uncompensated tail/rib mass moves CG aft of the committed range; the selected basis requires explicit final-CG management before closure claims.",
            "",
        ]
    )
    return "\n".join(lines)


def _mapping_at(mapping: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key, {})
    return current if isinstance(current, Mapping) else {}


def _elem_array(value: np.ndarray | float, like: np.ndarray) -> np.ndarray:
    if np.isscalar(value):
        return np.full_like(np.asarray(like, dtype=float), float(value), dtype=float)
    return np.asarray(value, dtype=float)


def _element_mean(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    return 0.5 * (values[:-1] + values[1:])


def _pct_delta(value: float, baseline: float) -> float:
    denom = max(abs(float(baseline)), 1.0e-12)
    return float((float(value) - float(baseline)) / denom * 100.0)


def _safe_ratio(value: float, baseline: float) -> float:
    denom = max(abs(float(baseline)), 1.0e-30)
    return float(value) / denom


def _interp_schedule(schedule: Sequence[Sequence[float]], y_m: float) -> float:
    points = sorted((float(row[0]), float(row[1])) for row in schedule)
    ys = np.asarray([point[0] for point in points], dtype=float)
    values = np.asarray([point[1] for point in points], dtype=float)
    return float(np.interp(float(y_m), ys, values))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tail-screening-json", type=Path, default=DEFAULT_TAIL_SCREENING_JSON)
    parser.add_argument("--closure-csv", type=Path, default=DEFAULT_CLOSURE_CSV)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    parser.add_argument("--base-mass-kg", type=float, default=96.0)
    parser.add_argument("--base-cg-x-m", type=float, default=0.72)
    parser.add_argument("--final-screening-cg-x-m", type=float, default=0.75)
    args = parser.parse_args(argv)

    summary = run_tail_aware_rib_rear_spar_sensitivity(
        tail_screening_json=args.tail_screening_json,
        closure_csv=args.closure_csv,
        config_path=args.config,
        report_json_path=args.report_json,
        report_md_path=args.report_md,
        base_mass_kg=float(args.base_mass_kg),
        base_cg_x_m=float(args.base_cg_x_m),
        final_screening_cg_x_m=float(args.final_screening_cg_x_m),
    )
    print(summary["engineering_verdict"])
    print(args.report_json)
    print(args.report_md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
