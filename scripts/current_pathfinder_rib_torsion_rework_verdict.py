#!/usr/bin/env python3
"""Rib / rear-spar / torsion rework verdict for the current pathfinder.

This runner consumes the current tail-aware aeroelastic closure, materialized
rib contract audit, and rib/rear-spar sensitivity outputs. It selects the next
engineering candidate without promoting projection-only GJ scaling or missing
bond/shape/local-FEM evidence into a FEM/APDL loadcase package pass.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_SENSITIVITY_JSON = (
    REPO_ROOT / "docs" / "reports" / "2026-05-09_tail_aware_rib_rear_spar_sensitivity.json"
)
DEFAULT_AEROELASTIC_CLOSURE_JSON = (
    REPO_ROOT / "docs" / "reports" / "2026-05-09_tail_aware_aeroelastic_closure.json"
)
DEFAULT_MATERIALIZED_AUDIT_JSON = (
    REPO_ROOT
    / "output"
    / "current_pathfinder_materialized_rib_contract_audit"
    / "materialized_rib_contract_audit.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "current_pathfinder_rib_torsion_rework_verdict"
DEFAULT_REPORT_JSON = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "2026-05-09_current_pathfinder_rib_torsion_rework_verdict.json"
)
DEFAULT_REPORT_MD = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "2026-05-09_current_pathfinder_rib_torsion_rework_verdict.md"
)
DEFAULT_CLOSURE_RERUN_SELECTED_BASIS_JSON = (
    DEFAULT_OUTPUT_DIR / "selected_basis_for_tail_aware_closure_rerun.json"
)

SCHEMA_VERSION = "current_pathfinder_rib_torsion_rework_verdict_v1"
READY_FOR_FEM_LOADCASE_PACKAGE = "ready_for_FEM_loadcase_package"
CANDIDATE_READY_FOR_LOCAL_FEM = "candidate_ready_for_local_FEM_and_coupon_before_FEM_package"
NEEDS_HYBRID_RIB_GEOMETRY_DETAIL = "needs_hybrid_rib_geometry_detail"
STILL_BLOCKED_BY_TORSIONAL_STIFFNESS = "still_blocked_by_torsional_stiffness"
STILL_BLOCKED_BY_BOND_OR_SHAPE_DATA = "still_blocked_by_bond_or_shape_data"

DIRECT_STRESS_BLOCKER = "direct_spar_pair_stress_test_still_above_bound"
HYBRID_PROJECTION_BLOCKER = "hybrid_effective_gj_is_projection_only_not_closure_rerun"


def build_rib_torsion_rework_verdict(
    *,
    sensitivity_payload: Mapping[str, Any],
    closure_payload: Mapping[str, Any],
    audit_payload: Mapping[str, Any],
    closure_rerun_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the next engineering verdict from rerunnable current artifacts."""

    candidate_id = str(
        sensitivity_payload.get("candidate_id")
        or closure_payload.get("candidate_id")
        or audit_payload.get("candidate_id")
        or ""
    )
    baseline = _baseline_basis(sensitivity_payload)
    closure_baseline = _baseline_closure_read(closure_payload)
    trade_rows = _candidate_trade_rows(
        sensitivity_payload=sensitivity_payload,
        baseline_rib_mass_kg=float(baseline.get("rib_mass_kg") or 0.0),
        twist_bound_deg=float(closure_baseline.get("twist_bound_deg") or 3.0),
    )
    selected_trade = _select_rework_trade_row(trade_rows)
    selected = (
        None
        if selected_trade is None
        else _selected_candidate_payload(selected_trade, sensitivity_payload, baseline)
    )
    for row in trade_rows:
        row["selection_status"] = (
            "selected"
            if selected is not None
            and row["family_key"] == selected["family_key"]
            and row["rear_spar_participation"] == selected["rear_spar_participation"]
            else row["selection_status"]
        )

    audit_assessment = _materialized_audit_assessment(audit_payload)
    closure_rerun = _closure_rerun_assessment(
        closure_rerun_payload,
        twist_bound_deg=float(closure_baseline.get("twist_bound_deg") or 3.0),
    )
    fem_gate = _fem_apdl_gate(
        selected=selected,
        audit_assessment=audit_assessment,
        closure_rerun=closure_rerun,
    )
    engineering_verdict = _engineering_verdict(
        selected=selected,
        fem_gate=fem_gate,
        audit_assessment=audit_assessment,
    )
    local_requirements = _local_fem_coupon_requirements(
        audit_payload=audit_payload,
        selected=selected,
        closure_rerun=closure_rerun,
    )
    validation_package = _local_fem_coupon_validation_package(
        selected=selected,
        audit_assessment=audit_assessment,
        closure_rerun=closure_rerun,
        local_requirements=local_requirements,
    )

    summary = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "engineering_verdict": engineering_verdict,
        "selected_rework_candidate": selected,
        "baseline_state": {
            **baseline,
            **closure_baseline,
            "current_closure_verdict": closure_payload.get("engineering_verdict"),
            "current_closure_blockers": list(closure_payload.get("blockers") or []),
            "materialized_audit_verdict": audit_payload.get("overall_verdict"),
        },
        "candidate_trade_rows": trade_rows,
        "materialized_contract_assessment": audit_assessment,
        "closure_rerun_assessment": closure_rerun,
        "local_fem_coupon_requirements": local_requirements,
        "local_fem_coupon_validation_package": validation_package,
        "fem_apdl_package_gate": fem_gate,
        "engineering_read": _engineering_read(
            verdict=engineering_verdict,
            selected=selected,
            fem_gate=fem_gate,
            audit_assessment=audit_assessment,
            closure_rerun=closure_rerun,
        ),
        "claim_boundary": (
            "This is a next-stage engineering verdict. Hybrid effective-GJ rows are "
            "projection-only unless a closure rerun explicitly owns that stiffness "
            "model. FEM/APDL loadcase packaging also remains blocked by bond, collar, "
            "skin sag, transition-station, and local tube-wall evidence."
        ),
    }
    return summary


def write_rib_torsion_rework_verdict_package(
    *,
    sensitivity_json: Path = DEFAULT_SENSITIVITY_JSON,
    closure_json: Path = DEFAULT_AEROELASTIC_CLOSURE_JSON,
    materialized_audit_json: Path = DEFAULT_MATERIALIZED_AUDIT_JSON,
    closure_rerun_json: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_json: Path = DEFAULT_REPORT_JSON,
    report_md: Path = DEFAULT_REPORT_MD,
) -> dict[str, Path]:
    """Build and write the current rework verdict package."""

    closure_rerun_payload = _read_json(closure_rerun_json) if closure_rerun_json else None
    summary = build_rib_torsion_rework_verdict(
        sensitivity_payload=_read_json(sensitivity_json),
        closure_payload=_read_json(closure_json),
        audit_payload=_read_json(materialized_audit_json),
        closure_rerun_payload=closure_rerun_payload,
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "candidate_trade_csv": output_dir / "candidate_trade.csv",
        "local_fem_coupon_requirements_json": output_dir
        / "local_fem_coupon_requirements.json",
        "local_fem_coupon_validation_package_json": output_dir
        / "local_fem_coupon_validation_package.json",
        "local_fem_coupon_validation_package_md": output_dir
        / "local_fem_coupon_validation_package.md",
        "summary_json": output_dir / "rib_torsion_rework_verdict.json",
        "report_json": Path(report_json),
        "report_md": Path(report_md),
    }
    _write_csv(paths["candidate_trade_csv"], summary["candidate_trade_rows"])
    _write_json(paths["local_fem_coupon_requirements_json"], summary["local_fem_coupon_requirements"])
    _write_json(
        paths["local_fem_coupon_validation_package_json"],
        summary["local_fem_coupon_validation_package"],
    )
    paths["local_fem_coupon_validation_package_md"].write_text(
        _render_validation_package_markdown(summary["local_fem_coupon_validation_package"]),
        encoding="utf-8",
    )
    _write_json(paths["summary_json"], summary)
    _write_json(paths["report_json"], summary)
    paths["report_md"].parent.mkdir(parents=True, exist_ok=True)
    paths["report_md"].write_text(_render_markdown(summary, paths), encoding="utf-8")
    return paths


def build_closure_rerun_selected_basis_payload(
    *,
    sensitivity_payload: Mapping[str, Any],
    family_key: str,
    rear_spar_participation: str,
) -> dict[str, Any]:
    """Build a selected-basis JSON usable by tail_aware_aeroelastic_closure.

    The closure kernel consumes hybrid effective-GJ as a main/rear torsion-cell
    screening surrogate. This is still not a local rib/collar/bond signoff.
    """

    raw = _raw_candidate_by_family_and_rear(
        sensitivity_payload,
        family_key=family_key,
        rear_spar_participation=rear_spar_participation,
    )
    if not raw:
        raise ValueError(
            f"No stiffness rework candidate found for {family_key} / {rear_spar_participation}."
        )
    baseline_selected = dict(_mapping_at(sensitivity_payload, "selected_basis"))
    baseline_mass = dict(_mapping_at(baseline_selected, "structural_mass_delta"))
    raw_rib_basis = dict(_mapping_at(raw, "rib_basis"))
    raw_projection = dict(_mapping_at(raw, "projection"))
    raw_case = dict(_mapping_at(raw, "selected_case"))
    family = str(raw.get("family_key") or family_key)
    rear = str(raw.get("rear_spar_participation") or rear_spar_participation)
    case_id = f"closure_rerun_{family}_{rear}_structural_kernel_v1"
    effective_gj_ratio = raw_projection.get("effective_gj_ratio_vs_balsa_selected")
    stiffness_override = {
        "status": "screening_surrogate_ready_for_closure_rerun",
        "model_id": "hybrid_main_rear_torsion_cell_scale_v1",
        "global_torsion_cell_scale": effective_gj_ratio,
        "scaled_properties": ["main_j_m4", "rear_j_m4"],
        "assumption_basis": {
            "rib_family_key": family,
            "material_category": raw.get("material_category"),
            "rear_spar_participation": rear,
            "cap_face_collar_basis": (
                "Hybrid rib/cap/collar screening effective-GJ is applied as an "
                "equivalent main-rear torsion-cell scale because the current "
                "dual-beam kernel has no local rib shell/collar elements."
            ),
            "eps_core_role": (
                "EPS core is shape/core support only; balsa/cap/collar detail owns "
                "the structural bracing credit."
            ),
            "bond_and_coupon_boundary": (
                "Requires rib-spar bond/collar local FEM and coupon data before "
                "FEM/APDL package or hardware signoff."
            ),
        },
        "claim_boundary": (
            "Screening closure rerun surrogate only. Local FEM/coupon/bond/collar "
            "evidence is still required before FEM/APDL package readiness."
        ),
    }
    selected_basis = {
        **baseline_selected,
        "case_id": case_id,
        "rib_spacing_m": raw_rib_basis.get(
            "spacing_m",
            baseline_selected.get("rib_spacing_m"),
        ),
        "rear_spar_participation": rear,
        "rear_stiffness_scale": _rear_scale(raw),
        "warping_knockdown": raw_rib_basis.get(
            "warping_knockdown",
            baseline_selected.get("warping_knockdown"),
        ),
        "structural_kernel_stiffness_override": stiffness_override,
        "effective_changes_vs_finite_rib_rear_1p00": {
            "GJ_ratio": effective_gj_ratio,
            "projected_direct_spar_pair_twist_deg": raw_projection.get(
                "projected_direct_spar_pair_twist_deg"
            ),
            "projected_bounded_physical_twist_deg": raw_projection.get(
                "projected_bounded_physical_twist_deg"
            ),
            "source": "current_pathfinder_rib_torsion_rework_verdict selected candidate projection",
        },
        "structural_mass_delta": {
            **baseline_mass,
            "estimated_full_wing_rib_mass_kg": raw_rib_basis.get(
                "estimated_full_wing_rib_mass_kg",
                baseline_mass.get("estimated_full_wing_rib_mass_kg"),
            ),
            "basis": (
                "Rib mass follows the selected rework candidate. Hybrid effective GJ "
                "is consumed by tail_aware_aeroelastic_closure as a screening "
                "torsion-cell surrogate, not as local FEM/coupon signoff."
            ),
        },
        "cg_impact": dict(_mapping_at(raw, "mass_cg_assessment"))
        or dict(_mapping_at(baseline_selected, "cg_impact")),
    }
    if _is_hybrid_category(str(raw.get("material_category", ""))):
        selected_basis["hybrid_effective_gj_claim_boundary"] = (
            "screening_surrogate_consumed_by_structural_kernel"
        )
        selected_basis["closure_rerun_basis_role"] = (
            "rear_spar_participation_rerun_with_hybrid_torsion_cell_surrogate"
        )
    else:
        selected_basis["hybrid_effective_gj_claim_boundary"] = "not_hybrid_candidate"
        selected_basis["closure_rerun_basis_role"] = "rear_spar_participation_rerun"

    structural_cases = []
    if raw_case:
        raw_case["case_id"] = case_id
        structural_cases.append(raw_case)
    return {
        "schema_version": "tail_aware_selected_basis_override_v1",
        "candidate_id": sensitivity_payload.get("candidate_id"),
        "rib_basis": raw_rib_basis,
        "selected_basis": selected_basis,
        "structural_cases": structural_cases,
        "source_rework_candidate": {
            "family_key": family,
            "material_category": raw.get("material_category"),
            "rear_spar_participation": rear,
            "projection": raw_projection,
            "claim_boundary": (
                "This selected-basis override is for closure rerun traceability. "
                "For hybrid rows, effective-GJ is consumed by the closure structural "
                "kernel only as a screening surrogate; local FEM/coupons still own "
                "detail signoff."
            ),
        },
    }


def write_closure_rerun_selected_basis_payload(
    *,
    sensitivity_json: Path = DEFAULT_SENSITIVITY_JSON,
    family_key: str,
    rear_spar_participation: str,
    output_json: Path = DEFAULT_CLOSURE_RERUN_SELECTED_BASIS_JSON,
) -> Path:
    payload = build_closure_rerun_selected_basis_payload(
        sensitivity_payload=_read_json(sensitivity_json),
        family_key=family_key,
        rear_spar_participation=rear_spar_participation,
    )
    _write_json(Path(output_json), payload)
    return Path(output_json)


def _baseline_basis(payload: Mapping[str, Any]) -> dict[str, Any]:
    selected = _mapping_at(payload, "selected_basis")
    mass = _mapping_at(selected, "structural_mass_delta")
    cg = _mapping_at(selected, "cg_impact")
    return {
        "selected_case_id": selected.get("case_id"),
        "baseline_rib_family": "balsa_sheet_3mm",
        "baseline_rear_spar_participation": selected.get("rear_spar_participation"),
        "baseline_rear_stiffness_scale": _float_or_none(selected.get("rear_stiffness_scale")),
        "baseline_warping_knockdown": _float_or_none(selected.get("warping_knockdown")),
        "rib_spacing_m": _float_or_none(selected.get("rib_spacing_m")),
        "rib_mass_kg": _float_or_none(mass.get("estimated_full_wing_rib_mass_kg")),
        "tail_mass_delta_kg": _float_or_none(mass.get("tail_mass_delta_kg")),
        "rear_spar_mass_delta_kg": _float_or_none(mass.get("rear_spar_mass_delta_kg")),
        "final_cg_x_m": _float_or_none(cg.get("final_screening_cg_x_m")),
        "uncompensated_cg_x_m": _float_or_none(cg.get("uncompensated_cg_x_m")),
        "required_forward_rebalance_m": _float_or_none(cg.get("required_forward_rebalance_m")),
        "forward_rebalance_mass_kg": _float_or_none(cg.get("forward_rebalance_mass_kg")),
    }


def _baseline_closure_read(payload: Mapping[str, Any]) -> dict[str, Any]:
    aero = _mapping_at(payload, "basis", "aeroelastic_effects")
    audit = _mapping_at(payload, "basis", "aeroelastic_twist_source_audit")
    interpretation = _mapping_at(audit, "interpretation_summary")
    dominant = _mapping_at(audit, "dominant_source_at_direct_max_station")
    direct = _float_or_none(
        interpretation.get("direct_spar_pair_rotation_max_abs_deg")
    ) or _float_or_none(aero.get("direct_spar_pair_rotation_max_abs_deg"))
    bounded = _float_or_none(
        interpretation.get("conservative_bounded_physical_projection_max_abs_deg")
    ) or _float_or_none(aero.get("conservative_bounded_physical_projection_max_abs_deg"))
    twist_bound = (
        _float_or_none(interpretation.get("screening_bound_deg"))
        or _float_or_none(aero.get("elastic_twist_screening_bound_deg"))
        or 3.0
    )
    return {
        "baseline_elastic_twist_max_abs_deg": _float_or_none(
            aero.get("elastic_twist_max_abs_deg")
        ),
        "baseline_direct_spar_pair_twist_deg": direct,
        "baseline_bounded_physical_twist_deg": bounded,
        "twist_bound_deg": twist_bound,
        "torque_critical_y_m": _float_or_none(
            interpretation.get("direct_spar_pair_rotation_max_station_y_m")
        )
        or _float_or_none(dominant.get("station_y_m")),
        "dominant_twist_source": dominant.get("dominant_component"),
    }


def _candidate_trade_rows(
    *,
    sensitivity_payload: Mapping[str, Any],
    baseline_rib_mass_kg: float,
    twist_bound_deg: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in sensitivity_payload.get("stiffness_rework_candidates") or []:
        if not isinstance(raw, Mapping):
            continue
        projection = _mapping_at(raw, "projection")
        rib_basis = _mapping_at(raw, "rib_basis")
        category = str(raw.get("material_category") or rib_basis.get("material_category") or "")
        family_key = str(raw.get("family_key") or rib_basis.get("family_key") or "")
        rear_scale = _rear_scale(raw)
        rib_mass = _float_or_none(rib_basis.get("estimated_full_wing_rib_mass_kg")) or 0.0
        direct = _float_or_none(projection.get("projected_direct_spar_pair_twist_deg"))
        bounded = _float_or_none(projection.get("projected_bounded_physical_twist_deg"))
        reasons = _candidate_rejection_reasons(
            raw,
            family_key=family_key,
            category=category,
            rear_scale=rear_scale,
            direct_twist_deg=direct,
            bounded_twist_deg=bounded,
            twist_bound_deg=float(twist_bound_deg),
        )
        rows.append(
            {
                "family_key": family_key,
                "material_category": category,
                "rear_stiffness_scale": rear_scale,
                "rear_spar_participation": str(raw.get("rear_spar_participation", "")),
                "warping_knockdown": _float_or_none(rib_basis.get("warping_knockdown")),
                "candidate_rib_mass_kg": rib_mass,
                "rib_mass_delta_vs_baseline_kg": rib_mass - float(baseline_rib_mass_kg),
                "effective_gj_ratio_vs_balsa_selected": _float_or_none(
                    projection.get("effective_gj_ratio_vs_balsa_selected")
                ),
                "projected_direct_spar_pair_twist_deg": direct,
                "projected_bounded_physical_twist_deg": bounded,
                "elastic_twist_screening_bound_deg": _float_or_none(
                    projection.get("elastic_twist_screening_bound_deg")
                )
                or float(twist_bound_deg),
                "projection_verdict": projection.get("candidate_rework_verdict"),
                "projection_blockers": list(projection.get("blockers") or []),
                "mass_cg_status": _mapping_at(raw, "mass_cg_assessment").get(
                    "screening_status"
                ),
                "selection_status": "rejected" if reasons else "candidate",
                "rejection_reasons": reasons,
                "engineering_read": raw.get("engineering_read", ""),
            }
        )
    return rows


def _candidate_rejection_reasons(
    raw: Mapping[str, Any],
    *,
    family_key: str,
    category: str,
    rear_scale: float | None,
    direct_twist_deg: float | None,
    bounded_twist_deg: float | None,
    twist_bound_deg: float,
) -> list[str]:
    projection = _mapping_at(raw, "projection")
    reasons: list[str] = []
    if _is_foam_only(family_key, category):
        reasons.append("foam_only_not_allowed_as_structural_bracing")
    if rear_scale is None:
        reasons.append("rear_spar_participation_missing")
    elif rear_scale >= 0.999:
        reasons.append("rear_spar_participation_1p00_is_upper_bound_only")
    elif rear_scale > 0.85:
        reasons.append("rear_spar_participation_above_bounded_rework_range")
    if projection.get("candidate_rework_verdict") != "candidate_for_tail_aware_closure_rerun":
        reasons.append("projection_not_ready_for_tail_aware_closure_rerun")
    if bounded_twist_deg is None:
        reasons.append("projected_bounded_twist_missing")
    elif bounded_twist_deg > float(twist_bound_deg) + 1.0e-12:
        reasons.append("bounded_physical_twist_still_exceeds_screening_bound")
    if direct_twist_deg is None:
        reasons.append("projected_direct_twist_missing")
    if _mapping_at(raw, "mass_cg_assessment").get("screening_status") not in {
        "final_cg_screening_row_available_without_rebalance",
        "final_cg_screening_row_remains_available_with_rebalance",
    }:
        reasons.append("final_cg_management_not_closed")
    return reasons


def _select_rework_trade_row(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    candidates = [row for row in rows if row.get("selection_status") == "candidate"]
    if not candidates:
        return None

    def score(row: Mapping[str, Any]) -> tuple[float, float, float, float, str]:
        bound = _float_or_none(row.get("elastic_twist_screening_bound_deg")) or 3.0
        direct = _float_or_none(row.get("projected_direct_spar_pair_twist_deg")) or math.inf
        bounded = _float_or_none(row.get("projected_bounded_physical_twist_deg")) or math.inf
        category = str(row.get("material_category", ""))
        family = str(row.get("family_key", ""))
        direct_penalty = 0.0 if direct <= bound + 1.0e-12 else 1.0
        hybrid_penalty = 0.0 if _is_hybrid_category(category) else 0.5
        mass_delta = _float_or_none(row.get("rib_mass_delta_vs_baseline_kg")) or 0.0
        rear = _float_or_none(row.get("rear_stiffness_scale")) or math.inf
        bounded_margin = max(0.0, bounded / max(bound, 1.0e-12))
        return (direct_penalty, hybrid_penalty, mass_delta, rear + bounded_margin * 0.01, family)

    return min(candidates, key=score)


def _selected_candidate_payload(
    row: Mapping[str, Any],
    sensitivity_payload: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    raw = _matching_raw_candidate(sensitivity_payload, row)
    mass_cg = _mapping_at(raw, "mass_cg_assessment")
    rib_basis = _mapping_at(raw, "rib_basis")
    projection = _mapping_at(raw, "projection")
    baseline_mass = float(baseline.get("rib_mass_kg") or 0.0)
    candidate_mass = _float_or_none(row.get("candidate_rib_mass_kg")) or 0.0
    direct = _float_or_none(row.get("projected_direct_spar_pair_twist_deg"))
    bounded = _float_or_none(row.get("projected_bounded_physical_twist_deg"))
    bound = _float_or_none(row.get("elastic_twist_screening_bound_deg")) or 3.0
    return {
        "family_key": row.get("family_key"),
        "material_category": row.get("material_category"),
        "rear_stiffness_scale": row.get("rear_stiffness_scale"),
        "rear_spar_participation": row.get("rear_spar_participation"),
        "warping_knockdown": row.get("warping_knockdown"),
        "effective_gj_ratio_vs_balsa_selected": row.get(
            "effective_gj_ratio_vs_balsa_selected"
        ),
        "projected_direct_spar_pair_twist_deg": direct,
        "projected_bounded_physical_twist_deg": bounded,
        "elastic_twist_screening_bound_deg": bound,
        "projected_direct_stress_test_status": (
            "clears_bound" if direct is not None and direct <= bound + 1.0e-12 else "still_high"
        ),
        "projected_bounded_twist_status": (
            "clears_bound"
            if bounded is not None and bounded <= bound + 1.0e-12
            else "still_high"
        ),
        "mass_cg_tail_trim_impact": {
            "baseline_rib_mass_kg": baseline_mass,
            "candidate_rib_mass_kg": candidate_mass,
            "rib_mass_delta_vs_baseline_kg": candidate_mass - baseline_mass,
            "tail_mass_delta_kg": baseline.get("tail_mass_delta_kg"),
            "final_cg_x_m": mass_cg.get("final_screening_cg_x_m")
            or baseline.get("final_cg_x_m"),
            "uncompensated_cg_x_m": mass_cg.get("uncompensated_cg_x_m"),
            "required_forward_rebalance_m": mass_cg.get("required_forward_rebalance_m"),
            "forward_rebalance_mass_kg": mass_cg.get("forward_rebalance_mass_kg"),
            "mass_cg_status": mass_cg.get("screening_status"),
        },
        "rib_basis": dict(rib_basis),
        "projection": dict(projection),
        "selection_basis": (
            "Lowest added rib mass among non-foam, non-upper-bound rework candidates "
            "that project both direct stress-test and bounded physical twist below "
            "the screening bound."
        ),
        "claim_boundary": (
            "Selected as the next local FEM/coupon candidate, not as FEM/APDL "
            "loadcase-package pass. Hybrid stiffness is still projection-only here."
        ),
    }


def _matching_raw_candidate(
    sensitivity_payload: Mapping[str, Any],
    row: Mapping[str, Any],
) -> Mapping[str, Any]:
    for raw in sensitivity_payload.get("stiffness_rework_candidates") or []:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("family_key")) == str(row.get("family_key")) and str(
            raw.get("rear_spar_participation")
        ) == str(row.get("rear_spar_participation")):
            return raw
    return {}


def _raw_candidate_by_family_and_rear(
    sensitivity_payload: Mapping[str, Any],
    *,
    family_key: str,
    rear_spar_participation: str,
) -> Mapping[str, Any]:
    for raw in sensitivity_payload.get("stiffness_rework_candidates") or []:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("family_key")) == str(family_key) and str(
            raw.get("rear_spar_participation")
        ) == str(rear_spar_participation):
            return raw
    return {}


def _materialized_audit_assessment(audit_payload: Mapping[str, Any]) -> dict[str, Any]:
    missing = [
        str(row.get("contract_item"))
        for row in audit_payload.get("mandatory_rib_reason") or []
        if isinstance(row, Mapping) and row.get("status") == "missing_contract"
    ]
    sag_statuses = {
        str(row.get("shape_sag_status"))
        for row in audit_payload.get("skin_sag_screening") or []
        if isinstance(row, Mapping)
    }
    bond_statuses = {
        str(row.get("bond_risk_status"))
        for row in audit_payload.get("bond_collar_risk_screening") or []
        if isinstance(row, Mapping)
    }
    local = _mapping_at(audit_payload, "local_fem_trigger_report")
    blockers: list[str] = []
    if missing:
        blockers.append("missing_transition_or_control_station_contract")
    if any(status.startswith("unknown_requires_test") for status in sag_statuses):
        blockers.append("skin_sag_unknown_requires_test")
    if any(status.startswith("needs_data") for status in bond_statuses):
        blockers.append("bond_collar_spar_contact_needs_data")
    if local.get("overall_verdict") == "local_fem_required_before_hybrid_pass_claim":
        blockers.append("torque_critical_local_fem_required")
    return {
        "overall_verdict": audit_payload.get("overall_verdict"),
        "station_bay_trace": dict(_mapping_at(audit_payload, "station_bay_trace")),
        "missing_contract_items": missing,
        "skin_sag_statuses": sorted(sag_statuses),
        "bond_collar_statuses": sorted(bond_statuses),
        "torque_critical_y_m": _float_or_none(local.get("peak_twist_station_y_m")),
        "dominant_twist_source": local.get("dominant_twist_source"),
        "recommended_hybrid_reinforcement_zones": list(
            local.get("recommended_hybrid_reinforcement_zones") or []
        ),
        "blockers": blockers,
        "ready_for_fem_package_detail_basis": not blockers,
    }


def _closure_rerun_assessment(
    payload: Mapping[str, Any] | None,
    *,
    twist_bound_deg: float,
) -> dict[str, Any]:
    if not payload:
        return {
            "status": "not_run_for_selected_hybrid_effective_gj",
            "closure_verdict": None,
            "bounded_twist_status": "not_rerun",
            "direct_stress_test_status": "not_rerun",
            "blockers": [HYBRID_PROJECTION_BLOCKER],
            "claim_boundary": (
                "Current selected hybrid GJ improvement is a projection. Rerun closure "
                "after the rib stiffness model is wired into the structural kernel."
            ),
        }
    aero = _mapping_at(payload, "basis", "aeroelastic_effects")
    stiffness = _mapping_at(payload, "basis", "selected_stiffness_basis")
    override = _mapping_at(stiffness, "structural_kernel_stiffness_override")
    artifact_manifest = _mapping_at(payload, "artifact_manifest")
    interpretation = _mapping_at(
        payload,
        "basis",
        "aeroelastic_twist_source_audit",
        "interpretation_summary",
    )
    direct = _float_or_none(aero.get("direct_spar_pair_rotation_max_abs_deg"))
    bounded = _float_or_none(aero.get("conservative_bounded_physical_projection_max_abs_deg"))
    elastic = _float_or_none(aero.get("elastic_twist_max_abs_deg"))
    bound = _float_or_none(aero.get("elastic_twist_screening_bound_deg")) or float(twist_bound_deg)
    blockers: list[str] = []
    warnings: list[str] = []
    if payload.get("engineering_verdict") not in {
        "ready_for_fem_apdl_loadcase_package",
        READY_FOR_FEM_LOADCASE_PACKAGE,
    }:
        blockers.append("closure_rerun_not_package_ready")
    if bounded is None or bounded > bound + 1.0e-12:
        blockers.append("closure_rerun_bounded_twist_exceeds_bound")
    if direct is not None and direct > bound + 1.0e-12:
        if bounded is not None and bounded <= bound + 1.0e-12:
            warnings.append("direct_spar_pair_stress_test_above_bound_conservative_mapping")
        else:
            blockers.append(DIRECT_STRESS_BLOCKER)
    owns_hybrid_override = override.get("status") == "applied_screening_surrogate"
    return {
        "status": "rerun_supplied",
        "closure_verdict": payload.get("engineering_verdict"),
        "elastic_twist_max_abs_deg": elastic,
        "direct_spar_pair_rotation_max_abs_deg": direct,
        "direct_spar_pair_rotation_max_station_y_m": _float_or_none(
            interpretation.get("direct_spar_pair_rotation_max_station_y_m")
        ),
        "conservative_bounded_physical_projection_max_abs_deg": bounded,
        "conservative_bounded_physical_projection_max_station_y_m": _float_or_none(
            interpretation.get("conservative_bounded_physical_projection_max_station_y_m")
        ),
        "elastic_twist_screening_bound_deg": bound,
        "structural_kernel_stiffness_override_status": override.get("status"),
        "structural_kernel_stiffness_override_model_id": override.get("model_id"),
        "structural_kernel_stiffness_override_scale": override.get(
            "applied_global_torsion_cell_scale"
        ),
        "owns_selected_hybrid_stiffness_model": bool(owns_hybrid_override),
        "bounded_twist_status": (
            "clears_bound" if bounded is not None and bounded <= bound + 1.0e-12 else "still_high"
        ),
        "direct_stress_test_status": _direct_stress_test_status(
            direct=direct,
            bounded=bounded,
            bound=bound,
        ),
        "blockers": blockers,
        "warnings": warnings,
        "artifact_manifest": dict(artifact_manifest),
        "claim_boundary": (
            "Closure rerun evidence is still not enough for package readiness if "
            "detail, bond, collar, skin sag, transition stations, or local FEM are missing."
        ),
    }


def _fem_apdl_gate(
    *,
    selected: Mapping[str, Any] | None,
    audit_assessment: Mapping[str, Any],
    closure_rerun: Mapping[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    blockers.extend(str(item) for item in closure_rerun.get("blockers") or [])
    blockers.extend(str(item) for item in audit_assessment.get("blockers") or [])
    if selected is None:
        blockers.append("no_selectable_rework_candidate")
    elif _is_hybrid_category(str(selected.get("material_category", ""))):
        if (
            not _closure_rerun_owns_selected_hybrid_stiffness(closure_rerun)
            and HYBRID_PROJECTION_BLOCKER not in blockers
        ):
            blockers.append(HYBRID_PROJECTION_BLOCKER)
    blockers = _dedupe(blockers)
    return {
        "ready": not blockers,
        "verdict_if_ready": READY_FOR_FEM_LOADCASE_PACKAGE,
        "blockers": blockers,
        "claim_boundary": (
            "A ready gate requires a closure rerun that owns the selected stiffness "
            "plus no missing local detail, bond/collar, skin sag, transition station, "
            "or local FEM blockers."
        ),
    }


def _engineering_verdict(
    *,
    selected: Mapping[str, Any] | None,
    fem_gate: Mapping[str, Any],
    audit_assessment: Mapping[str, Any],
) -> str:
    if fem_gate.get("ready"):
        return READY_FOR_FEM_LOADCASE_PACKAGE
    if selected is None:
        return STILL_BLOCKED_BY_TORSIONAL_STIFFNESS
    blockers = set(str(item) for item in fem_gate.get("blockers") or [])
    if DIRECT_STRESS_BLOCKER in blockers and not audit_assessment.get("blockers"):
        return NEEDS_HYBRID_RIB_GEOMETRY_DETAIL
    if blockers and not (
        selected.get("projected_direct_stress_test_status") == "clears_bound"
        and selected.get("projected_bounded_twist_status") == "clears_bound"
    ):
        return STILL_BLOCKED_BY_TORSIONAL_STIFFNESS
    if blockers:
        return CANDIDATE_READY_FOR_LOCAL_FEM
    return STILL_BLOCKED_BY_BOND_OR_SHAPE_DATA


def _direct_stress_test_status(
    *,
    direct: float | None,
    bounded: float | None,
    bound: float,
) -> str:
    if direct is None:
        return "missing"
    if direct <= bound + 1.0e-12:
        return "clears_bound"
    if bounded is not None and bounded <= bound + 1.0e-12:
        return "above_bound_conservative_stress_test"
    return "still_above_screening_bound"


def _closure_rerun_owns_selected_hybrid_stiffness(closure_rerun: Mapping[str, Any]) -> bool:
    return bool(closure_rerun.get("owns_selected_hybrid_stiffness_model"))


def _local_fem_coupon_validation_package(
    *,
    selected: Mapping[str, Any] | None,
    audit_assessment: Mapping[str, Any],
    closure_rerun: Mapping[str, Any],
    local_requirements: Mapping[str, Any],
) -> dict[str, Any]:
    closure_ready = (
        closure_rerun.get("bounded_twist_status") == "clears_bound"
        and _closure_rerun_owns_selected_hybrid_stiffness(closure_rerun)
    )
    package_verdict = (
        "ready_to_start_local_FEM_and_coupon_definition_not_FEM_APDL_package"
        if closure_ready
        else "needs_hybrid_kernel_closure_before_local_FEM_coupon_package"
    )
    zones = list(audit_assessment.get("recommended_hybrid_reinforcement_zones") or [])
    closure_artifacts = dict(_mapping_at(closure_rerun, "artifact_manifest"))
    return {
        "package_verdict": package_verdict,
        "fem_apdl_package_ready": False,
        "selected_family_key": None if selected is None else selected.get("family_key"),
        "selected_rear_spar_participation": None
        if selected is None
        else selected.get("rear_spar_participation"),
        "closure_evidence": dict(
            _mapping_at(local_requirements, "closure_evidence_to_carry_forward")
        ),
        "load_owner_artifacts": {
            "closure_summary_json": closure_artifacts.get("report_json")
            or closure_artifacts.get("output_dir"),
            "final_trimmed_wing_fs": closure_artifacts.get("final_trimmed_wing_fs"),
            "final_wing_spanload_redistribution_csv": closure_artifacts.get(
                "final_wing_spanload_redistribution_csv"
            ),
            "final_elastic_twist_alpha_eff_csv": closure_artifacts.get(
                "final_elastic_twist_alpha_eff_csv"
            ),
            "final_twist_source_audit_csv": closure_artifacts.get(
                "final_twist_source_audit_csv"
            ),
        },
        "local_fem_zones": zones,
        "validation_workstreams": [
            {
                "workstream_id": "rib_spar_bond_collar_local_fem",
                "scope": (
                    "Positive and negative torque-critical hybrid zones around "
                    "y≈2.328 m, including rib-to-main/rear-spar bondline, collar/"
                    "gusset geometry, tube-wall bearing/crush, and peel/shear load transfer."
                ),
                "inputs_needed": [
                    "cap/face/collar dimensions and material allowables",
                    "bondline width, adhesive system, cure/process notes",
                    "main/rear spar OD, wall, local contact footprint, and collar fit",
                    "closure load-owner spanload/twist artifacts listed in this package",
                ],
                "exit_condition": (
                    "Local FEM or hand/FEM hybrid margins are positive for bond shear/"
                    "peel, collar bearing, tube-wall crush, and rib cap/shear path."
                ),
            },
            {
                "workstream_id": "hybrid_rib_coupon_matrix",
                "scope": (
                    "Coupons for EPS+balsa/cap hybrid rib shear transfer; EPS core is "
                    "not credited as structural bracing by itself."
                ),
                "inputs_needed": [
                    "cap strip material and grain/fiber direction",
                    "rib web/core thickness and adhesive interface",
                    "coupon shear, compression, peel, and repeatability data",
                ],
                "exit_condition": (
                    "Coupon allowables support the effective-GJ surrogate or force a "
                    "lower stiffness scale before FEM/APDL packaging."
                ),
            },
            {
                "workstream_id": "skin_sag_panel_coupon",
                "scope": (
                    "0.30 m bay shape-keeping and skin sag check for the materialized "
                    "121-station / 120-bay rib layout."
                ),
                "inputs_needed": [
                    "skin material/thickness and attachment method",
                    "representative pressure/handling load or conservative panel load",
                    "allowable sag/twist tolerance tied to airfoil shape quality",
                ],
                "exit_condition": (
                    "Sag/shape coupon or panel analysis clears the bay tolerance without "
                    "relying on foam-only structural bracing."
                ),
            },
            {
                "workstream_id": "transition_control_station_manifest",
                "scope": (
                    "Transport joint, control station, airfoil transition, and twist "
                    "transition station manifest."
                ),
                "inputs_needed": [
                    "station IDs and y locations",
                    "local rib type changes and reinforcement details",
                    "control/transition hardware interfaces",
                ],
                "exit_condition": (
                    "Missing transition/control station contract blockers are closed "
                    "before FEM/APDL package export."
                ),
            },
            {
                "workstream_id": "direct_stress_test_aero_surface_mapping",
                "scope": (
                    "Map the conservative main/rear direct stress-test twist to a qualified "
                    "aero-surface or elastic-axis twist observable."
                ),
                "inputs_needed": [
                    "direct stress-test max station from closure rerun",
                    "rib/shell/skin local geometry for aero-surface interpolation",
                    "comparison against bounded physical projection and FEM shell mapping",
                ],
                "exit_condition": (
                    "Either the direct 3+ deg stress-test is shown conservative for the "
                    "aero surface, or the stiffness model is downgraded and rerun."
                ),
            },
        ],
        "do_not_promote": list(local_requirements.get("do_not_promote") or []),
        "next_recommended_task": (
            "Define the rib-spar bond/collar local FEM input deck and coupon matrix "
            "for the positive y≈2.328 m torque-critical zone first; mirror the negative "
            "zone after the geometry assumptions are stable."
        ),
        "claim_boundary": (
            "This package starts local FEM/coupon definition. It is not FEM/APDL "
            "package readiness and not flight hardware signoff."
        ),
    }


def _local_fem_coupon_requirements(
    *,
    audit_payload: Mapping[str, Any],
    selected: Mapping[str, Any] | None,
    closure_rerun: Mapping[str, Any],
) -> dict[str, Any]:
    local = _mapping_at(audit_payload, "local_fem_trigger_report")
    family = None if selected is None else selected.get("family_key")
    required_before_package = [
        "hybrid rib cap/face/collar geometry at y≈2.328 m torque-critical zone",
        "rib-to-main/rear-spar bondline and collar/contact geometry",
        "tube-wall local bearing/crush/peel allowables or local FEM",
        "skin sag coupon/panel evidence for 0.30 m bays",
        "transport/control/airfoil/twist transition station manifest",
    ]
    if not _closure_rerun_owns_selected_hybrid_stiffness(closure_rerun):
        required_before_package.append(
            "closure rerun with the selected effective stiffness model wired in"
        )
    return {
        "selected_family_key": family,
        "selected_rear_spar_participation": None
        if selected is None
        else selected.get("rear_spar_participation"),
        "torque_critical_y_m": local.get("peak_twist_station_y_m"),
        "dominant_twist_source": local.get("dominant_twist_source"),
        "recommended_hybrid_reinforcement_zones": list(
            local.get("recommended_hybrid_reinforcement_zones") or []
        ),
        "required_before_fem_apdl_package": required_before_package,
        "closure_evidence_to_carry_forward": {
            "status": closure_rerun.get("status"),
            "closure_verdict": closure_rerun.get("closure_verdict"),
            "owns_selected_hybrid_stiffness_model": bool(
                closure_rerun.get("owns_selected_hybrid_stiffness_model")
            ),
            "bounded_twist_status": closure_rerun.get("bounded_twist_status"),
            "direct_stress_test_status": closure_rerun.get("direct_stress_test_status"),
            "conservative_bounded_physical_projection_max_abs_deg": closure_rerun.get(
                "conservative_bounded_physical_projection_max_abs_deg"
            ),
            "direct_spar_pair_rotation_max_abs_deg": closure_rerun.get(
                "direct_spar_pair_rotation_max_abs_deg"
            ),
            "structural_kernel_stiffness_override_scale": closure_rerun.get(
                "structural_kernel_stiffness_override_scale"
            ),
        },
        "do_not_promote": [
            "rear_spar_participation_1p00_as_selected_basis",
            "EPS/XPS/structural-foam-only as structural bracing",
            "GJ scaling projection as FEM-ready evidence",
        ],
    }


def _engineering_read(
    *,
    verdict: str,
    selected: Mapping[str, Any] | None,
    fem_gate: Mapping[str, Any],
    audit_assessment: Mapping[str, Any],
    closure_rerun: Mapping[str, Any],
) -> str:
    if selected is None:
        return (
            "No bounded non-foam, non-upper-bound rework candidate clears the current "
            "bounded twist projection. The blocker remains torsional stiffness."
        )
    family = selected.get("family_key")
    rear = selected.get("rear_spar_participation")
    if verdict == CANDIDATE_READY_FOR_LOCAL_FEM:
        rerun_owns = bool(closure_rerun.get("owns_selected_hybrid_stiffness_model"))
        stiffness_read = (
            "the closure rerun now consumes the hybrid effective-GJ screening surrogate"
            if rerun_owns
            else "the hybrid stiffness is still projection-only"
        )
        return (
            f"The next useful candidate is {family} with {rear}. It projects direct "
            "and bounded twist below 3 deg with mass/CG carried, but it is not "
            f"FEM/APDL-loadcase ready because {stiffness_read} and materialized "
            "bond/collar/skin sag/transition/local FEM data are still "
            f"open: {audit_assessment.get('blockers')}. Closure rerun status is "
            f"{closure_rerun.get('status')}."
        )
    return (
        f"Verdict {verdict}. FEM/APDL gate blockers: {fem_gate.get('blockers')}. "
        "Do not package loadcases until these are explicitly closed."
    )


def _render_markdown(summary: Mapping[str, Any], paths: Mapping[str, Path]) -> str:
    selected = _mapping_at(summary, "selected_rework_candidate")
    baseline = _mapping_at(summary, "baseline_state")
    gate = _mapping_at(summary, "fem_apdl_package_gate")
    contract = _mapping_at(summary, "materialized_contract_assessment")
    closure_rerun = _mapping_at(summary, "closure_rerun_assessment")
    local = _mapping_at(summary, "local_fem_coupon_requirements")
    lines = [
        "# Current Pathfinder Rib / Torsion Rework Verdict",
        "",
        f"Candidate: `{summary.get('candidate_id')}`",
        f"Verdict: `{summary.get('engineering_verdict')}`",
        f"FEM/APDL package ready: `{gate.get('ready')}`",
        f"Gate blockers: `{gate.get('blockers')}`",
        "",
        "## Baseline Blocker",
        "",
        f"- Baseline rib/rear-spar: `{baseline.get('baseline_rib_family')}` / `{baseline.get('baseline_rear_spar_participation')}`.",
        f"- Baseline direct / bounded twist: `{_fmt(baseline.get('baseline_direct_spar_pair_twist_deg'))}` deg / `{_fmt(baseline.get('baseline_bounded_physical_twist_deg'))}` deg.",
        f"- Screening bound: `{_fmt(baseline.get('twist_bound_deg'))}` deg.",
        f"- Torque-critical y: `{_fmt(baseline.get('torque_critical_y_m'), 3)}` m; dominant source `{baseline.get('dominant_twist_source')}`.",
        "",
        "## Selected Next Candidate",
        "",
    ]
    if selected:
        mass = _mapping_at(selected, "mass_cg_tail_trim_impact")
        lines.extend(
            [
                f"- Family / rear-spar participation: `{selected.get('family_key')}` / `{selected.get('rear_spar_participation')}`.",
                f"- Effective GJ ratio vs balsa selected: `{_fmt(selected.get('effective_gj_ratio_vs_balsa_selected'))}`.",
                f"- Projected direct / bounded twist: `{_fmt(selected.get('projected_direct_spar_pair_twist_deg'))}` deg / `{_fmt(selected.get('projected_bounded_physical_twist_deg'))}` deg.",
                f"- Rib mass: `{_fmt(mass.get('candidate_rib_mass_kg'), 3)}` kg, delta vs baseline `{_fmt(mass.get('rib_mass_delta_vs_baseline_kg'), 3)}` kg.",
                f"- CG status: `{mass.get('mass_cg_status')}`; required forward rebalance `{_fmt(mass.get('required_forward_rebalance_m'), 6)}` m on `{_fmt(mass.get('forward_rebalance_mass_kg'), 1)}` kg.",
                "- This is a local FEM/coupon candidate, not a FEM/APDL package pass.",
            ]
        )
    else:
        lines.append("- No selectable non-foam, non-upper-bound candidate found.")
    lines.extend(
        [
            "",
            "## Closure Rerun Boundary",
            "",
            f"- Rerun status: `{closure_rerun.get('status')}`.",
            f"- Rerun verdict: `{closure_rerun.get('closure_verdict')}`.",
            f"- Bounded twist status: `{closure_rerun.get('bounded_twist_status')}`.",
            f"- Direct stress-test status: `{closure_rerun.get('direct_stress_test_status')}`.",
            "",
            "## Detail Blockers",
            "",
            f"- Missing contract items: `{contract.get('missing_contract_items')}`.",
            f"- Skin sag statuses: `{contract.get('skin_sag_statuses')}`.",
            f"- Bond/collar statuses: `{contract.get('bond_collar_statuses')}`.",
            f"- Local FEM torque-critical y: `{_fmt(contract.get('torque_critical_y_m'), 3)}` m.",
            f"- Reinforcement zones: `{contract.get('recommended_hybrid_reinforcement_zones')}`.",
            "",
            "## Required Before FEM/APDL Package",
            "",
        ]
    )
    for item in local.get("required_before_fem_apdl_package") or []:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- candidate trade CSV: `{paths.get('candidate_trade_csv')}`",
            f"- local FEM/coupon requirements: `{paths.get('local_fem_coupon_requirements_json')}`",
            "- local FEM/coupon validation package: "
            f"`{paths.get('local_fem_coupon_validation_package_json')}`",
            f"- summary JSON: `{paths.get('summary_json')}`",
            "",
            "## Engineering Read",
            "",
            str(summary.get("engineering_read", "")),
            "",
        ]
    )
    return "\n".join(lines)


def _render_validation_package_markdown(package: Mapping[str, Any]) -> str:
    closure = _mapping_at(package, "closure_evidence")
    lines = [
        "# Current Pathfinder Local FEM / Coupon Validation Package",
        "",
        f"Verdict: `{package.get('package_verdict')}`",
        f"FEM/APDL package ready: `{package.get('fem_apdl_package_ready')}`",
        "",
        "## Closure Evidence",
        "",
        f"- Selected basis: `{package.get('selected_family_key')}` / "
        f"`{package.get('selected_rear_spar_participation')}`.",
        f"- Bounded twist status: `{closure.get('bounded_twist_status')}`; bounded twist "
        f"`{_fmt(closure.get('conservative_bounded_physical_projection_max_abs_deg'))}` deg.",
        f"- Direct stress-test status: `{closure.get('direct_stress_test_status')}`; "
        f"direct twist `{_fmt(closure.get('direct_spar_pair_rotation_max_abs_deg'))}` deg.",
        "- Hybrid stiffness model owned by closure: "
        f"`{closure.get('owns_selected_hybrid_stiffness_model')}` at scale "
        f"`{_fmt(closure.get('structural_kernel_stiffness_override_scale'))}`.",
        "",
        "## Local FEM Zones",
        "",
    ]
    for zone in package.get("local_fem_zones") or []:
        lines.append(
            f"- `{zone.get('zone_id')}`: y `{_fmt(zone.get('y_start_m'), 3)}` to "
            f"`{_fmt(zone.get('y_end_m'), 3)}` m; stations `{zone.get('station_ids')}`; "
            f"bays `{zone.get('bay_ids')}`."
        )
    lines.extend(["", "## Workstreams", ""])
    for row in package.get("validation_workstreams") or []:
        lines.append(f"### {row.get('workstream_id')}")
        lines.append("")
        lines.append(str(row.get("scope", "")))
        lines.append("")
        lines.append("Inputs needed:")
        for item in row.get("inputs_needed") or []:
            lines.append(f"- {item}")
        lines.append("")
        lines.append(f"Exit condition: {row.get('exit_condition')}")
        lines.append("")
    lines.extend(
        [
            "## Do Not Promote",
            "",
        ]
    )
    for item in package.get("do_not_promote") or []:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Next Task",
            "",
            str(package.get("next_recommended_task", "")),
            "",
            "## Claim Boundary",
            "",
            str(package.get("claim_boundary", "")),
            "",
        ]
    )
    return "\n".join(lines)


def _is_foam_only(family_key: str, category: str) -> bool:
    text = f"{family_key} {category}".lower()
    return "foam_only" in text or ("eps" in text and "hybrid" not in text and "cap" not in text)


def _is_hybrid_category(category: str) -> bool:
    lowered = category.lower()
    return "hybrid" in lowered or "cap" in lowered or "face" in lowered


def _rear_scale(row: Mapping[str, Any]) -> float | None:
    value = _float_or_none(row.get("rear_stiffness_scale"))
    if value is not None:
        return value
    label = str(row.get("rear_spar_participation", ""))
    match = re.search(r"(\d+)pct", label)
    if match:
        return float(match.group(1)) / 100.0
    return None


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _fmt(value: Any, digits: int = 6) -> str:
    parsed = _float_or_none(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:.{digits}f}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sensitivity-json", type=Path, default=DEFAULT_SENSITIVITY_JSON)
    parser.add_argument("--closure-json", type=Path, default=DEFAULT_AEROELASTIC_CLOSURE_JSON)
    parser.add_argument("--materialized-audit-json", type=Path, default=DEFAULT_MATERIALIZED_AUDIT_JSON)
    parser.add_argument("--closure-rerun-json", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    parser.add_argument("--write-closure-rerun-basis", type=Path, default=None)
    parser.add_argument(
        "--closure-rerun-family",
        default="eps_balsa_cap_hybrid_10mm",
    )
    parser.add_argument(
        "--closure-rerun-rear-spar-participation",
        default="bounded_65pct_screening",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    paths = write_rib_torsion_rework_verdict_package(
        sensitivity_json=args.sensitivity_json,
        closure_json=args.closure_json,
        materialized_audit_json=args.materialized_audit_json,
        closure_rerun_json=args.closure_rerun_json,
        output_dir=args.output_dir,
        report_json=args.report_json,
        report_md=args.report_md,
    )
    summary = _read_json(paths["report_json"])
    print(f"wrote {paths['report_json']}")
    print(f"wrote {paths['report_md']}")
    print(f"verdict: {summary['engineering_verdict']}")
    if _mapping_at(summary, "fem_apdl_package_gate").get("blockers"):
        print(f"gate blockers: {_mapping_at(summary, 'fem_apdl_package_gate').get('blockers')}")
    if args.write_closure_rerun_basis is not None:
        basis_path = write_closure_rerun_selected_basis_payload(
            sensitivity_json=args.sensitivity_json,
            family_key=args.closure_rerun_family,
            rear_spar_participation=args.closure_rerun_rear_spar_participation,
            output_json=args.write_closure_rerun_basis,
        )
        print(f"wrote closure rerun selected basis: {basis_path}")


if __name__ == "__main__":
    main()
