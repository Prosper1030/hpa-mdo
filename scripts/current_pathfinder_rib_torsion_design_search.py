#!/usr/bin/env python3
"""Fast rib/torsion design-search loop for the current pathfinder.

This runner turns the current rib/rear-spar/torsion pathfinder evidence into a
rerunnable fast design loop. The fast model is a search and shortlist tool only:
FEM/APDL/CalculiX samples calibrate the surrogate, and final FEM remains
responsible for local stress, buckling, bond, tube-wall, and hardware claims.
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
DEFAULT_SELECTED_CLOSURE_JSON = (
    REPO_ROOT
    / "output"
    / "current_pathfinder_rib_torsion_rework_verdict"
    / "tail_aware_closure_rerun_hybrid_kernel.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "current_pathfinder_rib_torsion_design_search"
DEFAULT_REPORT_JSON = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "2026-05-09_current_pathfinder_rib_torsion_design_search.json"
)
DEFAULT_REPORT_MD = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "2026-05-09_current_pathfinder_rib_torsion_design_search.md"
)


SCHEMA_VERSION = "current_pathfinder_rib_torsion_design_search_v1"
FAST_PHYSICAL_MODEL_ID = "link_limited_torsion_cell_v2"
LEGACY_FAST_MODEL_ID = "hybrid_main_rear_torsion_cell_scale_v1"
READY_FOR_FEM_CALIBRATION = "fast_design_loop_ready_for_fem_calibration"
UNRELIABLE_NEEDS_CALIBRATION = "fast_model_unreliable_needs_calibration_before_search"
NO_REASONABLE_CANDIDATE = "no_reasonable_rib_torsion_candidate_found"
FAST_MODEL_EVIDENCE = "fast_model_result_needs_FEM_calibration"
FOAM_ONLY_BLOCKER = "foam_only_shape_core_not_structural_bracing"
REAR_1P0_BLOCKER = "rear_spar_participation_1p00_not_allowed_as_selected_basis"


def build_design_variable_contract() -> dict[str, Any]:
    """Return the explicit low-dimensional search contract."""

    return {
        "schema_version": "rib_torsion_design_variable_contract_v1",
        "rib_core_thickness_m": [0.002, 0.003, 0.006, 0.008, 0.010, 0.012, 0.015],
        "thickness_basis": (
            "Includes 3 mm balsa baseline, 10 mm CNC foam board practice, and a "
            "bounded range around both. Thickness is a fast-model variable, not a "
            "released drawing thickness."
        ),
        "material_family_groups": [
            "balsa",
            "eps_xps_foam_core_shape_only",
            "structural_foam_shape_core_reference",
            "hybrid_foam_balsa_cap",
            "hybrid_foam_glass_carbon_face",
        ],
        "rib_spacing_zone_profiles": [
            {
                "profile_key": "uniform_0p30",
                "root_spacing_m": 0.30,
                "torque_zone_spacing_m": 0.30,
                "outboard_spacing_m": 0.30,
                "effective_spacing_m": 0.30,
                "mass_factor": 1.00,
                "stiffness_factor": 1.00,
                "manufacturability_delta": 0.00,
            },
            {
                "profile_key": "torque_zone_0p24_outboard_0p36",
                "root_spacing_m": 0.30,
                "torque_zone_spacing_m": 0.24,
                "outboard_spacing_m": 0.36,
                "effective_spacing_m": 0.285,
                "mass_factor": 1.06,
                "stiffness_factor": 1.08,
                "manufacturability_delta": -0.06,
            },
            {
                "profile_key": "dense_torque_zone_0p20",
                "root_spacing_m": 0.24,
                "torque_zone_spacing_m": 0.20,
                "outboard_spacing_m": 0.30,
                "effective_spacing_m": 0.245,
                "mass_factor": 1.22,
                "stiffness_factor": 1.17,
                "manufacturability_delta": -0.12,
            },
            {
                "profile_key": "manufacturing_relaxed_0p36",
                "root_spacing_m": 0.36,
                "torque_zone_spacing_m": 0.30,
                "outboard_spacing_m": 0.36,
                "effective_spacing_m": 0.345,
                "mass_factor": 0.88,
                "stiffness_factor": 0.92,
                "manufacturability_delta": 0.05,
            },
        ],
        "rear_spar_participation_values": [0.50, 0.65, 0.75],
        "rear_spar_claim_boundary": (
            "0.50/0.65/0.75 are bounded screening values. 1.0 can be kept as an "
            "upper-bound diagnostic elsewhere, but not as selected fast-loop basis."
        ),
        "local_reinforcement_options": {
            "torque_critical_y_m": 2.327757,
            "zone_half_width_m": 0.30,
            "options": [
                {
                    "key": "none",
                    "label": "no local reinforcement credit",
                    "stiffness_factor": 1.00,
                    "mass_delta_kg": 0.00,
                    "manufacturability_delta": 0.00,
                    "requires_fem": False,
                },
                {
                    "key": "balsa_cap_collar_y2p328",
                    "label": "balsa cap/collar around torque-critical zone",
                    "stiffness_factor": 1.14,
                    "mass_delta_kg": 0.18,
                    "manufacturability_delta": -0.06,
                    "requires_fem": True,
                },
                {
                    "key": "glass_face_collar_y2p328",
                    "label": "glass face/collar around torque-critical zone",
                    "stiffness_factor": 1.27,
                    "mass_delta_kg": 0.42,
                    "manufacturability_delta": -0.16,
                    "requires_fem": True,
                },
                {
                    "key": "carbon_face_collar_y2p328",
                    "label": "carbon face/collar around torque-critical zone",
                    "stiffness_factor": 1.36,
                    "mass_delta_kg": 0.35,
                    "manufacturability_delta": -0.22,
                    "requires_fem": True,
                },
            ],
        },
        "cap_face_collar_stiffness_proxy": {
            "proxy_id": FAST_PHYSICAL_MODEL_ID,
            "allowed_role": "search_and_shortlist_only",
            "must_be_calibrated_by": ["local rib-spar FEM", "coupon matrix", "APDL/CalculiX spot-check"],
        },
        "fast_physical_model": {
            "model_id": FAST_PHYSICAL_MODEL_ID,
            "legacy_model_id": LEGACY_FAST_MODEL_ID,
            "physics_basis": (
                "Rib thickness and spacing are treated as shear-transfer link terms "
                "rather than full torsion-cell GJ multipliers. Local collar/carbon "
                "reinforcement improves load introduction but is capped because the "
                "rib web/link path still limits main-to-rear spar torque transfer."
            ),
            "thickness_exponents": {
                "balsa": 1.10,
                "hybrid_foam_balsa_cap": 0.78,
                "hybrid_foam_glass_carbon_face": 0.78,
                "eps_xps_foam_core_shape_only": 0.25,
                "structural_foam_shape_core_reference": 0.25,
            },
            "spacing_exponents": {
                "relaxed_spacing_penalty": 1.65,
                "dense_spacing_reward": 0.55,
            },
            "local_reinforcement_link_factors": {
                "none": 1.00,
                "balsa_cap_collar_y2p328": 1.02,
                "glass_face_collar_y2p328": 1.07,
                "carbon_face_collar_y2p328": 1.10,
            },
            "uncollared_hybrid_torque_zone_factor": 0.64,
            "do_not_fit": [
                "foam-only shape-core rows",
                "rear_spar_participation=1.0 selected basis",
                "single empirical family correction factor",
            ],
        },
        "aircraft_trade_outputs": [
            "mass_kg",
            "cg_x_m",
            "tail_delta_H_margin_deg",
            "static_margin",
            "C_n_beta",
            "manufacturability_score",
        ],
    }


def build_rib_torsion_design_search(
    *,
    sensitivity_payload: Mapping[str, Any],
    selected_closure_payload: Mapping[str, Any],
    calibration_update: Mapping[str, Any] | None = None,
    max_shortlist: int = 12,
) -> dict[str, Any]:
    """Run the fast design search from committed pathfinder artifacts."""

    contract = build_design_variable_contract()
    family_factors = _family_twist_correction_factors(calibration_update)
    closure_anchor = _closure_anchor_twist_factors(
        sensitivity_payload=sensitivity_payload,
        selected_closure_payload=selected_closure_payload,
    )
    candidate_rows = _build_candidate_rows(
        sensitivity_payload=sensitivity_payload,
        selected_closure_payload=selected_closure_payload,
        contract=contract,
        family_factors=family_factors,
        closure_anchor=closure_anchor,
    )
    pareto_rows = _mark_pareto(candidate_rows)
    selectable = [row for row in pareto_rows if row["selection_status"] == "candidate"]
    shortlist = sorted(selectable, key=_candidate_score)[: int(max_shortlist)]
    selected = shortlist[0] if shortlist else None
    calibration_samples = _select_calibration_samples(
        candidate_rows=pareto_rows,
        selected=selected,
    )
    verdict = _search_verdict(
        candidate_rows=pareto_rows,
        selected=selected,
        calibration_update=calibration_update,
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": str(sensitivity_payload.get("candidate_id", "")),
        "engineering_verdict": verdict,
        "selected_fast_candidate": selected,
        "design_variable_contract": contract,
        "fast_model_settings": {
            "physical_model_id": FAST_PHYSICAL_MODEL_ID,
            "twist_bound_deg": _twist_bound_deg(sensitivity_payload, selected_closure_payload),
            "closure_anchor_twist_factors": closure_anchor,
            "fem_calibration_family_twist_factors": family_factors,
            "claim_boundary": (
                "Fast model ranks candidate trade-offs. FEM calibration can shift "
                "family/zone correction factors; final FEM owns local stress and signoff."
            ),
        },
        "candidate_rows": pareto_rows,
        "shortlist": shortlist,
        "pareto_front": [row for row in pareto_rows if row.get("pareto_front")],
        "fem_calibration_samples": calibration_samples,
        "calibration_interface": _calibration_interface(),
        "fem_spotcheck_skeletons": _spotcheck_skeleton_manifest(calibration_samples),
        "engineering_verdict_options": [
            READY_FOR_FEM_CALIBRATION,
            UNRELIABLE_NEEDS_CALIBRATION,
            NO_REASONABLE_CANDIDATE,
        ],
        "engineering_read": _engineering_read(verdict, selected, calibration_samples),
        "claim_boundary": (
            "This output is a fast design-search and FEM-calibration handoff. EPS/XPS "
            "foam-only rows are shape-core references only and rear_spar_participation=1.0 "
            "is not generated as selected basis."
        ),
    }
    if calibration_update:
        summary["applied_calibration_update"] = dict(calibration_update)
    return summary


def write_rib_torsion_design_search_package(
    *,
    sensitivity_payload: Mapping[str, Any] | None = None,
    selected_closure_payload: Mapping[str, Any] | None = None,
    sensitivity_json: Path = DEFAULT_SENSITIVITY_JSON,
    selected_closure_json: Path = DEFAULT_SELECTED_CLOSURE_JSON,
    calibration_update_json: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_json: Path = DEFAULT_REPORT_JSON,
    report_md: Path = DEFAULT_REPORT_MD,
) -> dict[str, Any]:
    """Build and write a rerunnable search package plus FEM skeletons."""

    sensitivity = (
        dict(sensitivity_payload) if sensitivity_payload is not None else _read_json(sensitivity_json)
    )
    closure = (
        dict(selected_closure_payload)
        if selected_closure_payload is not None
        else _read_json(selected_closure_json)
    )
    calibration_update = _read_json(calibration_update_json) if calibration_update_json else None
    summary = build_rib_torsion_design_search(
        sensitivity_payload=sensitivity,
        selected_closure_payload=closure,
        calibration_update=calibration_update,
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Any] = {
        "summary_json": output_dir / "rib_torsion_design_search.json",
        "selected_closure_basis_json": output_dir
        / "selected_fast_candidate_for_tail_aware_closure_rerun.json",
        "candidate_csv": output_dir / "candidate_design_table.csv",
        "shortlist_csv": output_dir / "shortlist.csv",
        "pareto_csv": output_dir / "pareto_front.csv",
        "fem_sample_csv": output_dir / "fem_calibration_samples.csv",
        "calibration_input_template_csv": output_dir / "fem_calibration_results_template.csv",
        "calibration_interface_json": output_dir / "calibration_interface.json",
        "report_json": Path(report_json),
        "report_md": Path(report_md),
    }
    _write_json(paths["summary_json"], summary)
    _write_json(
        paths["selected_closure_basis_json"],
        build_selected_fast_candidate_closure_basis_payload(
            summary,
            sensitivity_payload=sensitivity,
        ),
    )
    _write_csv(paths["candidate_csv"], summary["candidate_rows"])
    _write_csv(paths["shortlist_csv"], summary["shortlist"])
    _write_csv(paths["pareto_csv"], summary["pareto_front"])
    _write_csv(paths["fem_sample_csv"], summary["fem_calibration_samples"])
    _write_csv(
        paths["calibration_input_template_csv"],
        _calibration_results_template_rows(summary["fem_calibration_samples"]),
    )
    _write_json(paths["calibration_interface_json"], summary["calibration_interface"])
    deck_paths = _write_fem_skeletons(output_dir, summary["fem_calibration_samples"])
    paths.update(deck_paths)
    _write_json(paths["report_json"], _compact_report_payload(summary, paths))
    paths["report_md"].parent.mkdir(parents=True, exist_ok=True)
    paths["report_md"].write_text(_render_markdown(summary, paths), encoding="utf-8")
    return paths


def _compact_report_payload(summary: Mapping[str, Any], paths: Mapping[str, Any]) -> dict[str, Any]:
    """Keep committed report JSON compact; full tables live under output/."""

    return {
        "schema_version": summary.get("schema_version"),
        "candidate_id": summary.get("candidate_id"),
        "engineering_verdict": summary.get("engineering_verdict"),
        "selected_fast_candidate": summary.get("selected_fast_candidate"),
        "fast_model_settings": summary.get("fast_model_settings"),
        "candidate_row_count": len(summary.get("candidate_rows") or []),
        "shortlist": summary.get("shortlist"),
        "pareto_front_count": len(summary.get("pareto_front") or []),
        "fem_calibration_samples": summary.get("fem_calibration_samples"),
        "calibration_interface": summary.get("calibration_interface"),
        "artifact_manifest": {
            "full_summary_json": str(paths.get("summary_json")),
            "candidate_csv": str(paths.get("candidate_csv")),
            "shortlist_csv": str(paths.get("shortlist_csv")),
            "pareto_csv": str(paths.get("pareto_csv")),
            "fem_sample_csv": str(paths.get("fem_sample_csv")),
            "calibration_input_template_csv": str(paths.get("calibration_input_template_csv")),
            "selected_closure_basis_json": str(paths.get("selected_closure_basis_json")),
            "calculix_manifest_json": str(paths.get("calculix_manifest_json")),
            "apdl_manifest_json": str(paths.get("apdl_manifest_json")),
        },
        "claim_boundary": summary.get("claim_boundary"),
        "engineering_read": summary.get("engineering_read"),
    }


def build_selected_fast_candidate_closure_basis_payload(
    summary: Mapping[str, Any],
    *,
    sensitivity_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Build selected-basis JSON consumable by tail_aware_aeroelastic_closure."""

    selected = _mapping_at(summary, "selected_fast_candidate")
    if not selected:
        return {
            "schema_version": "tail_aware_selected_basis_override_v1",
            "status": "no_selected_fast_candidate",
        }
    trade = _mapping_at(selected, "trade_metrics")
    baseline_selected = _mapping_at(sensitivity_payload, "selected_basis")
    baseline_cg = dict(_mapping_at(baseline_selected, "cg_impact"))
    baseline_mass = dict(_mapping_at(baseline_selected, "structural_mass_delta"))
    case_id = f"closure_rerun_{selected.get('case_id')}_fast_design_loop_v1"
    material_category = str(selected.get("material_category") or selected.get("material_family_group"))
    rib_basis = {
        "family_key": selected.get("family_key"),
        "material_category": material_category,
        "rib_core_thickness_m": selected.get("rib_core_thickness_m"),
        "rib_spacing_profile": selected.get("rib_spacing_profile"),
        "torque_zone_spacing_m": selected.get("torque_zone_spacing_m"),
        "local_reinforcement": selected.get("local_reinforcement"),
        "material_basis": {
            "family_category": material_category,
            "family_key": selected.get("family_key"),
            "thickness_m": selected.get("rib_core_thickness_m"),
        },
    }
    cg_impact = {
        **baseline_cg,
        "cg_range_x_m": baseline_cg.get("cg_range_x_m", [0.68, 0.75]),
        "final_screening_cg_x_m": trade.get("cg_x_m"),
        "uncompensated_cg_x_m": trade.get("uncompensated_cg_x_m"),
        "required_forward_rebalance_m": trade.get("required_forward_rebalance_m"),
        "forward_rebalance_mass_kg": trade.get("forward_rebalance_mass_kg"),
        "screening_status": trade.get("mass_cg_status"),
        "mass_items": [
            {
                "name": "selected_tail_screening_delta",
                "mass_kg": baseline_mass.get("tail_mass_delta_kg"),
                "x_m": 8.31,
            },
            {
                "name": "fast_design_loop_selected_rib_pack",
                "mass_kg": trade.get("mass_kg"),
                "x_m": 0.461633,
            },
        ],
    }
    selected_basis = {
        "case_id": case_id,
        "rib_spacing_m": selected.get("effective_spacing_m"),
        "rib_count_or_bay_length_assumption": {
            "full_wing_rib_count": 121,
            "max_recommended_subbay_m": selected.get("effective_spacing_m"),
            "source": "current_pathfinder_rib_torsion_design_search fast selected candidate",
        },
        "rear_spar_participation": selected.get("rear_spar_participation"),
        "rear_stiffness_scale": selected.get("rear_stiffness_scale"),
        "warping_knockdown": None,
        "effective_changes_vs_finite_rib_rear_1p00": {
            "GJ_ratio": selected.get("effective_gj_ratio_vs_balsa_selected"),
            "fast_bounded_twist_deg": selected.get("fast_model_bounded_twist_deg"),
            "fast_direct_twist_deg": selected.get("fast_model_direct_twist_deg"),
        },
        "structural_mass_delta": {
            **baseline_mass,
            "estimated_full_wing_rib_mass_kg": trade.get("mass_kg"),
            "basis": (
                "Fast design-loop selected rib pack mass. This is search bookkeeping, "
                "not final part mass."
            ),
        },
        "cg_impact": cg_impact,
        "tail_trim_static_directional_margins_after_mass_stiffness_changes": {
            "worst_static_margin": trade.get("static_margin"),
            "worst_delta_H_margin_to_limit_deg": trade.get("tail_delta_H_margin_deg"),
            "worst_delta_V_margin_to_limit_deg": trade.get("tail_delta_V_margin_deg"),
            "C_n_beta_min_row": trade.get("C_n_beta"),
        },
        "load_remap_diagnostics": {
            "status": "conserved",
            "source": "current_pathfinder_rib_torsion_design_search",
            "engineering_read": (
                "Fast selected stiffness is passed into closure as a torsion-cell "
                "screening surrogate. Rerun closure output remains non-final until FEM calibration."
            ),
        },
        "structural_kernel_stiffness_override": {
            "status": "screening_surrogate_ready_for_closure_rerun",
            "model_id": "hybrid_main_rear_torsion_cell_scale_v1",
            "global_torsion_cell_scale": selected.get("effective_gj_ratio_vs_balsa_selected"),
            "scaled_properties": ["main_j_m4", "rear_j_m4"],
            "assumption_basis": {
                "rib_family_key": selected.get("family_key"),
                "material_category": material_category,
                "core_thickness_m": selected.get("rib_core_thickness_m"),
                "rib_spacing_profile": selected.get("rib_spacing_profile"),
                "local_reinforcement": selected.get("local_reinforcement"),
                "rear_spar_participation": selected.get("rear_spar_participation"),
                "claim_boundary": (
                    "Fast design-loop effective-GJ candidate; FEM calibration must "
                    "confirm or downgrade before final FEM package selection."
                ),
            },
            "claim_boundary": (
                "Screening closure rerun surrogate only. Local FEM/coupon/bond/collar "
                "evidence is still required before package readiness."
            ),
        },
    }
    return {
        "schema_version": "tail_aware_selected_basis_override_v1",
        "candidate_id": summary.get("candidate_id"),
        "rib_basis": rib_basis,
        "selected_basis": selected_basis,
        "structural_cases": [
            {
                "case_id": case_id,
                "status": "fast_design_loop_selected_for_closure_rerun",
                "tip_main_m": None,
                "tip_rear_m": None,
                "wire_tension_max_n": None,
                "link_force_max_n": None,
            }
        ],
        "source_fast_candidate": dict(selected),
        "claim_boundary": (
            "Generated so tail_aware_aeroelastic_closure can rerun the selected fast "
            "candidate. This does not turn fast search into final FEM truth."
        ),
    }


def derive_fast_model_calibration_update(
    summary: Mapping[str, Any],
    *,
    calibration_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build diagnostic fast-physics alignment feedback from completed FEM rows."""

    samples = {
        str(sample.get("sample_id")): sample
        for sample in summary.get("fem_calibration_samples") or []
        if isinstance(sample, Mapping)
    }
    used_rows: list[dict[str, Any]] = []
    legacy_family_values: dict[str, list[float]] = {}
    for result in calibration_results:
        sample = samples.get(str(result.get("sample_id")))
        if not sample or str(result.get("status", "")).lower() not in {"completed", "pass", "done"}:
            continue
        fem_twist = _float_or_none(result.get("fem_twist_deg"))
        fem_mass = _float_or_none(result.get("fem_mass_kg"))
        revised_fast_twist = _float_or_none(sample.get("fast_model_bounded_twist_deg"))
        legacy_fast_twist = _float_or_none(sample.get("legacy_fast_model_bounded_twist_deg"))
        if legacy_fast_twist is None:
            legacy_fast_twist = revised_fast_twist
        fast_mass = _float_or_none(sample.get("mass_kg"))
        if (
            fem_twist is None
            or revised_fast_twist is None
            or revised_fast_twist <= 0.0
            or legacy_fast_twist is None
            or legacy_fast_twist <= 0.0
        ):
            continue
        revised_factor = fem_twist / revised_fast_twist
        legacy_factor = fem_twist / legacy_fast_twist
        mass_factor = None
        if fem_mass is not None and fast_mass is not None and fast_mass > 0.0:
            mass_factor = fem_mass / fast_mass
        row = {
            "sample_id": str(result.get("sample_id")),
            "sample_role": sample.get("sample_role"),
            "family_key": sample.get("family_key"),
            "solver": result.get("solver"),
            "legacy_fast_model_bounded_twist_deg": legacy_fast_twist,
            "revised_fast_model_bounded_twist_deg": revised_fast_twist,
            "fem_twist_deg": fem_twist,
            "legacy_fast_vs_ccx_factor": round(legacy_factor, 6),
            "revised_fast_vs_ccx_factor": round(revised_factor, 6),
            "legacy_factor_error_pct": round(abs(legacy_factor - 1.0) * 100.0, 6),
            "revised_factor_error_pct": round(abs(revised_factor - 1.0) * 100.0, 6),
            "mass_factor": None if mass_factor is None else round(mass_factor, 6),
            "structural_credit_policy": sample.get("structural_credit_policy"),
        }
        used_rows.append(row)
        legacy_family_values.setdefault(str(sample.get("family_key")), []).append(legacy_factor)
    legacy_family_factors = {
        family: {"twist_factor": round(sum(values) / len(values), 6)}
        for family, values in legacy_family_values.items()
    }
    structural_rows = [
        row
        for row in used_rows
        if row.get("structural_credit_policy") != "shape_core_reference_only"
        and row.get("sample_role") != "baseline_balsa_3mm"
    ]
    max_revised_error = max(
        (float(row["revised_factor_error_pct"]) for row in structural_rows),
        default=None,
    )
    if max_revised_error is None:
        verification_verdict = "fast_physical_model_improved_but_not_verified"
    elif max_revised_error <= 5.0:
        verification_verdict = "fast_physical_model_verified_within_5pct"
    elif max_revised_error <= 10.0:
        verification_verdict = "fast_physical_model_aligned_within_10pct"
    else:
        verification_verdict = "fast_physical_model_improved_but_not_verified"
    status = (
        "fast_physics_alignment_diagnostic_ready"
        if len(structural_rows) >= 2
        else "fast_physics_alignment_waiting_for_more_structural_fem_samples"
    )
    return {
        "schema_version": "rib_torsion_fast_physics_alignment_v2",
        "status": status,
        "physical_model_id": FAST_PHYSICAL_MODEL_ID,
        "used_result_rows": used_rows,
        "family_correction_factors": {},
        "diagnostic_legacy_family_twist_factors": legacy_family_factors,
        "structural_candidate_max_revised_factor_error_pct": None
        if max_revised_error is None
        else round(max_revised_error, 6),
        "verification_verdict": verification_verdict,
        "next_loop_action": "rerun_fast_search_with_revised_physical_model_no_family_factor",
        "claim_boundary": "diagnostic_only_fast_physics_revision_not_final_FEM_truth",
    }


def _build_candidate_rows(
    *,
    sensitivity_payload: Mapping[str, Any],
    selected_closure_payload: Mapping[str, Any],
    contract: Mapping[str, Any],
    family_factors: Mapping[str, float],
    closure_anchor: Mapping[str, float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    tail_metrics = _tail_metrics(selected_closure_payload, sensitivity_payload)
    baseline_mass = _baseline_rib_mass(sensitivity_payload)
    twist_bound = _twist_bound_deg(sensitivity_payload, selected_closure_payload)
    physical_model = _mapping_at(contract, "fast_physical_model")
    spacing_profiles = contract["rib_spacing_zone_profiles"]
    reinforcements = contract["local_reinforcement_options"]["options"]
    thickness_values = tuple(float(value) for value in contract["rib_core_thickness_m"])
    for raw in _iter_search_source_rows(sensitivity_payload):
        if not isinstance(raw, Mapping):
            continue
        family_key = str(raw.get("family_key") or _mapping_at(raw, "rib_basis").get("family_key"))
        category = str(raw.get("material_category") or "")
        group = _material_family_group(family_key, category)
        rear_scale = _rear_scale(raw)
        if rear_scale is None:
            continue
        if not any(abs(rear_scale - value) < 1.0e-9 for value in (0.50, 0.65, 0.75)):
            continue
        rib_basis = _mapping_at(raw, "rib_basis")
        material_basis = _mapping_at(rib_basis, "material_basis")
        base_thickness = _float_or_none(material_basis.get("thickness_m")) or _default_thickness(
            family_key
        )
        base_mass = _float_or_none(rib_basis.get("estimated_full_wing_rib_mass_kg")) or 0.0
        base_cg = _float_or_none(rib_basis.get("estimated_rib_pack_cg_x_m")) or 0.46
        projection = _mapping_at(raw, "projection")
        base_direct = _float_or_none(projection.get("projected_direct_spar_pair_twist_deg"))
        base_bounded = _float_or_none(projection.get("projected_bounded_physical_twist_deg"))
        base_gj = _float_or_none(projection.get("effective_gj_ratio_vs_balsa_selected")) or 0.0
        if base_direct is None or base_bounded is None:
            continue
        for thickness_m in _thickness_values_for_family(
            family_key=family_key,
            group=group,
            base_thickness_m=base_thickness,
            thickness_values=thickness_values,
        ):
            for profile in spacing_profiles:
                mass_factor = float(profile["mass_factor"])
                for reinforcement in reinforcements:
                    legacy_components = _legacy_fast_physics_components(
                        group=group,
                        thickness_m=thickness_m,
                        base_thickness_m=base_thickness,
                        profile=profile,
                        reinforcement=reinforcement,
                    )
                    physics_components = _fast_physics_components(
                        group=group,
                        thickness_m=thickness_m,
                        base_thickness_m=base_thickness,
                        effective_spacing_m=float(profile["effective_spacing_m"]),
                        reinforcement=reinforcement,
                        physical_model=physical_model,
                    )
                    local_factor = physics_components["local_reinforcement_factor"]
                    local_mass = _local_mass_for_group(group, reinforcement)
                    calibration_twist_factor = float(family_factors.get(family_key, 1.0))
                    anchor_twist_factor = float(closure_anchor.get(family_key, 1.0))
                    total_stiffness_factor = physics_components["total_stiffness_factor"]
                    legacy_total_stiffness_factor = legacy_components["total_stiffness_factor"]
                    total_twist_factor = max(0.05, total_stiffness_factor)
                    legacy_total_twist_factor = max(0.05, legacy_total_stiffness_factor)
                    fast_direct = base_direct * anchor_twist_factor * calibration_twist_factor
                    fast_direct /= total_twist_factor
                    fast_bounded = base_bounded * anchor_twist_factor * calibration_twist_factor
                    fast_bounded /= total_twist_factor
                    legacy_fast_direct = base_direct * anchor_twist_factor
                    legacy_fast_direct *= calibration_twist_factor
                    legacy_fast_direct /= legacy_total_twist_factor
                    legacy_fast_bounded = base_bounded * anchor_twist_factor
                    legacy_fast_bounded *= calibration_twist_factor
                    legacy_fast_bounded /= legacy_total_twist_factor
                    mass = (
                        base_mass
                        * (thickness_m / max(base_thickness, 1.0e-12))
                        * mass_factor
                        + local_mass
                    )
                    trade = _trade_metrics(
                        mass_kg=mass,
                        base_mass_kg=base_mass,
                        baseline_mass_kg=baseline_mass,
                        rib_cg_x_m=base_cg,
                        raw=raw,
                        tail_metrics=tail_metrics,
                        manufacturability_score=_manufacturability_score(
                            group=group,
                            thickness_m=thickness_m,
                            profile=profile,
                            reinforcement=reinforcement,
                        ),
                    )
                    blockers = _candidate_blockers(
                        group=group,
                        rear_scale=rear_scale,
                        bounded_twist_deg=fast_bounded,
                        twist_bound_deg=twist_bound,
                        trade_metrics=trade,
                    )
                    candidate_id = _candidate_id(
                        family_key=family_key,
                        thickness_m=thickness_m,
                        spacing_profile=str(profile["profile_key"]),
                        reinforcement=str(reinforcement["key"]),
                        rear_scale=rear_scale,
                    )
                    rows.append(
                        {
                            "case_id": candidate_id,
                            "family_key": family_key,
                            "material_category": category,
                            "material_family_group": group,
                            "rib_core_thickness_m": round(thickness_m, 6),
                            "rib_core_thickness_mm": round(thickness_m * 1000.0, 3),
                            "rib_spacing_profile": profile["profile_key"],
                            "torque_zone_spacing_m": profile["torque_zone_spacing_m"],
                            "effective_spacing_m": profile["effective_spacing_m"],
                            "local_reinforcement": reinforcement["key"],
                            "rear_stiffness_scale": round(rear_scale, 6),
                            "rear_spar_participation": _rear_label(rear_scale),
                            "cap_face_collar_stiffness_proxy": round(local_factor, 6),
                            "legacy_cap_face_collar_stiffness_proxy": round(
                                legacy_components["local_reinforcement_factor"],
                                6,
                            ),
                            "effective_gj_ratio_vs_balsa_selected": round(
                                base_gj * total_stiffness_factor,
                                6,
                            ),
                            "legacy_effective_gj_ratio_vs_balsa_selected": round(
                                base_gj * legacy_total_stiffness_factor,
                                6,
                            ),
                            "fast_model_direct_twist_deg": round(fast_direct, 6),
                            "fast_model_bounded_twist_deg": round(fast_bounded, 6),
                            "legacy_fast_model_direct_twist_deg": round(legacy_fast_direct, 6),
                            "legacy_fast_model_bounded_twist_deg": round(
                                legacy_fast_bounded,
                                6,
                            ),
                            "fast_physics_components": _rounded_component_dict(
                                physics_components,
                            ),
                            "legacy_fast_physics_components": _rounded_component_dict(
                                legacy_components,
                            ),
                            "twist_bound_deg": round(twist_bound, 6),
                            "direct_stress_test_status": _direct_status(fast_direct, twist_bound),
                            "bounded_twist_status": _bounded_status(fast_bounded, twist_bound),
                            "trade_metrics": trade,
                            "mass_delta_vs_balsa_baseline_kg": round(mass - baseline_mass, 6),
                            "manufacturability_score": trade["manufacturability_score"],
                            "selection_status": "rejected" if blockers else "candidate",
                            "blockers": blockers,
                            "evidence_status": FAST_MODEL_EVIDENCE,
                            "fem_calibration_required": True,
                            "structural_bracing_credit": group not in _foam_reference_groups(),
                            "claim_boundary": _row_claim_boundary(group),
                        }
                    )
    return sorted(rows, key=lambda row: (str(row["case_id"]), row["fast_model_bounded_twist_deg"]))


def _iter_search_source_rows(sensitivity_payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = [row for row in sensitivity_payload.get("stiffness_rework_candidates") or [] if isinstance(row, Mapping)]
    existing_families = {str(row.get("family_key")) for row in rows}
    rear_multipliers = _rear_multiplier_map(rows)
    baseline_bounded = _baseline_bounded_twist_from_rows(rows)
    for material_row in sensitivity_payload.get("material_family_sensitivity") or []:
        if not isinstance(material_row, Mapping):
            continue
        family_key = str(material_row.get("family_key"))
        if family_key in existing_families:
            continue
        projection = _mapping_at(material_row, "aeroelastic_closure_projection")
        gj_base = _float_or_none(projection.get("effective_gj_ratio_vs_balsa_selected"))
        baseline_direct = _float_or_none(projection.get("baseline_elastic_twist_max_abs_deg"))
        twist_bound = _float_or_none(projection.get("elastic_twist_screening_bound_deg")) or 3.0
        if gj_base is None or gj_base <= 0.0 or baseline_direct is None:
            continue
        for rear_scale in (0.50, 0.65, 0.75):
            multiplier = rear_multipliers.get(rear_scale, 1.0)
            gj_ratio = gj_base * multiplier
            synthetic_projection = {
                "candidate_rework_verdict": "foam_reference_for_fast_search",
                "effective_gj_ratio_vs_balsa_selected": gj_ratio,
                "projected_direct_spar_pair_twist_deg": baseline_direct / gj_ratio,
                "projected_bounded_physical_twist_deg": baseline_bounded / gj_ratio,
                "baseline_direct_spar_pair_twist_deg": baseline_direct,
                "baseline_bounded_physical_twist_deg": baseline_bounded,
                "elastic_twist_screening_bound_deg": twist_bound,
                "blockers": [FOAM_ONLY_BLOCKER],
            }
            selected_case = dict(_mapping_at(material_row, "selected_case"))
            selected_case["rear_stiffness_scale"] = rear_scale
            selected_case["rear_spar_participation"] = _rear_label(rear_scale)
            rows.append(
                {
                    "family_key": family_key,
                    "material_category": material_row.get("material_category"),
                    "rear_stiffness_scale": rear_scale,
                    "rear_spar_participation": _rear_label(rear_scale),
                    "rib_basis": dict(_mapping_at(material_row, "rib_basis")),
                    "mass_cg_assessment": dict(_mapping_at(material_row, "mass_cg_assessment")),
                    "selected_case": selected_case,
                    "projection": synthetic_projection,
                    "engineering_read": material_row.get("engineering_read"),
                }
            )
    return rows


def _rear_multiplier_map(rows: Sequence[Mapping[str, Any]]) -> dict[float, float]:
    balsa = [
        row
        for row in rows
        if str(row.get("family_key")) == "balsa_sheet_3mm"
        and _float_or_none(_mapping_at(row, "projection").get("effective_gj_ratio_vs_balsa_selected"))
    ]
    base = None
    for row in balsa:
        if abs((_rear_scale(row) or 0.0) - 0.50) < 1.0e-9:
            base = _float_or_none(
                _mapping_at(row, "projection").get("effective_gj_ratio_vs_balsa_selected")
            )
            break
    if base is None or base <= 0.0:
        return {0.50: 1.0, 0.65: 1.248502, 0.75: 1.403825}
    out: dict[float, float] = {0.50: 1.0}
    for row in balsa:
        rear = _rear_scale(row)
        gj = _float_or_none(_mapping_at(row, "projection").get("effective_gj_ratio_vs_balsa_selected"))
        if rear is not None and gj is not None:
            out[round(rear, 2)] = gj / base
    out.setdefault(0.65, 1.248502)
    out.setdefault(0.75, 1.403825)
    return out


def _baseline_bounded_twist_from_rows(rows: Sequence[Mapping[str, Any]]) -> float:
    for row in rows:
        value = _float_or_none(
            _mapping_at(row, "projection").get("baseline_bounded_physical_twist_deg")
        )
        if value is not None:
            return value
    return 3.256324


def _trade_metrics(
    *,
    mass_kg: float,
    base_mass_kg: float,
    baseline_mass_kg: float,
    rib_cg_x_m: float,
    raw: Mapping[str, Any],
    tail_metrics: Mapping[str, Any],
    manufacturability_score: float,
) -> dict[str, Any]:
    cg = _mapping_at(raw, "mass_cg_assessment")
    base_required = _float_or_none(cg.get("required_forward_rebalance_m"))
    base_uncg = _float_or_none(cg.get("uncompensated_cg_x_m"))
    final_cg = (
        _float_or_none(cg.get("final_screening_cg_x_m"))
        or _float_or_none(tail_metrics.get("cg_x_m"))
        or 0.75
    )
    forward_mass = _float_or_none(cg.get("forward_rebalance_mass_kg")) or 56.0
    delta_mass = mass_kg - base_mass_kg
    rebalance_delta = max(0.0, (rib_cg_x_m - final_cg) * delta_mass / forward_mass)
    required_rebalance = max(0.0, (base_required or 0.0) + rebalance_delta)
    uncompensated = (base_uncg or 0.79) + (rib_cg_x_m - (base_uncg or 0.79)) * delta_mass / 100.0
    mass_delta_vs_baseline = mass_kg - baseline_mass_kg
    delta_h_margin = (_float_or_none(tail_metrics.get("tail_delta_H_margin_deg")) or 0.0) - max(
        0.0,
        required_rebalance - (base_required or required_rebalance),
    ) * 4.0
    return {
        "mass_kg": round(mass_kg, 6),
        "rib_mass_delta_vs_baseline_kg": round(mass_delta_vs_baseline, 6),
        "cg_x_m": round(final_cg, 6),
        "uncompensated_cg_x_m": round(uncompensated, 6),
        "required_forward_rebalance_m": round(required_rebalance, 6),
        "forward_rebalance_mass_kg": round(forward_mass, 6),
        "tail_delta_H_margin_deg": round(delta_h_margin, 6),
        "tail_delta_V_margin_deg": tail_metrics.get("tail_delta_V_margin_deg"),
        "static_margin": tail_metrics.get("static_margin"),
        "C_n_beta": tail_metrics.get("C_n_beta"),
        "manufacturability_score": round(manufacturability_score, 6),
        "mass_cg_status": cg.get(
            "screening_status",
            "final_cg_screening_row_remains_available_with_rebalance",
        ),
    }


def _candidate_blockers(
    *,
    group: str,
    rear_scale: float,
    bounded_twist_deg: float,
    twist_bound_deg: float,
    trade_metrics: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if group in _foam_reference_groups():
        blockers.append(FOAM_ONLY_BLOCKER)
    if rear_scale >= 0.999:
        blockers.append(REAR_1P0_BLOCKER)
    if bounded_twist_deg > twist_bound_deg + 1.0e-12:
        blockers.append("bounded_physical_twist_exceeds_3deg_fast_model")
    if str(trade_metrics.get("mass_cg_status")) not in {
        "final_cg_screening_row_available_without_rebalance",
        "final_cg_screening_row_remains_available_with_rebalance",
    }:
        blockers.append("mass_cg_tail_trim_trade_not_closed")
    if (_float_or_none(trade_metrics.get("tail_delta_H_margin_deg")) or -math.inf) < 0.0:
        blockers.append("tail_trim_margin_negative")
    if (_float_or_none(trade_metrics.get("static_margin")) or -math.inf) < 0.05:
        blockers.append("static_margin_below_screening_min")
    if (_float_or_none(trade_metrics.get("C_n_beta")) or -math.inf) < 0.005:
        blockers.append("C_n_beta_below_screening_min")
    return blockers


def _select_calibration_samples(
    *,
    candidate_rows: Sequence[Mapping[str, Any]],
    selected: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    baseline = _find_best_match(
        candidate_rows,
        family_key="balsa_sheet_3mm",
        thickness_m=0.003,
        rear_scale=0.50,
        reinforcement="none",
        spacing_profile="uniform_0p30",
        allow_rejected=True,
    )
    selected_hybrid = _find_best_match(
        candidate_rows,
        family_key="eps_balsa_cap_hybrid_10mm",
        thickness_m=0.010,
        rear_scale=0.75,
        reinforcement="carbon_face_collar_y2p328",
        spacing_profile="manufacturing_relaxed_0p36",
        allow_rejected=True,
    )
    if selected_hybrid is None and selected and str(selected.get("family_key")) == "eps_balsa_cap_hybrid_10mm":
        selected_hybrid = selected
    aggressive = _best_aggressive_candidate(candidate_rows)
    foam = _best_foam_reference(candidate_rows)
    for role, row, solver, priority, purpose in (
        (
            "baseline_balsa_3mm",
            baseline,
            "calculix",
            1,
            "anchor current 3 mm balsa baseline and detect gross fast-model bias",
        ),
        (
            "selected_hybrid_10mm",
            selected_hybrid,
            "apdl_or_calculix",
            1,
            "calibrate selected 10 mm EPS+balsa-cap hybrid torsion prediction",
        ),
        (
            "aggressive_plausible_hybrid",
            aggressive,
            "apdl",
            2,
            "bound how much cap/face/collar stiffness the fast loop may credit",
        ),
        (
            "lightweight_foam_core_reference",
            foam,
            "calculix",
            2,
            "keep foam-only EPS/XPS as shape-core reference, not structural pass",
        ),
    ):
        if row:
            samples.append(_sample_payload(role, row, solver, priority, purpose))
    if (
        selected
        and selected_hybrid
        and selected.get("case_id") != selected_hybrid.get("case_id")
        and selected.get("material_family_group") not in _foam_reference_groups()
    ):
        samples.append(
            _sample_payload(
                "revised_selected_candidate",
                selected,
                "calculix",
                1,
                "validate the revised fast-search selected candidate after physics update",
            )
        )
    return samples


def _sample_payload(
    role: str,
    row: Mapping[str, Any],
    solver: str,
    priority: int,
    purpose: str,
) -> dict[str, Any]:
    trade = _mapping_at(row, "trade_metrics")
    sample_id = f"{role}__{row.get('case_id')}"
    return {
        "sample_id": sample_id,
        "sample_role": role,
        "source_case_id": row.get("case_id"),
        "family_key": row.get("family_key"),
        "material_family_group": row.get("material_family_group"),
        "rib_core_thickness_m": row.get("rib_core_thickness_m"),
        "rib_spacing_profile": row.get("rib_spacing_profile"),
        "torque_zone_spacing_m": row.get("torque_zone_spacing_m"),
        "effective_spacing_m": row.get("effective_spacing_m"),
        "local_reinforcement": row.get("local_reinforcement"),
        "rear_spar_participation": row.get("rear_spar_participation"),
        "rear_stiffness_scale": row.get("rear_stiffness_scale"),
        "cap_face_collar_stiffness_proxy": row.get("cap_face_collar_stiffness_proxy"),
        "effective_gj_ratio_vs_balsa_selected": row.get("effective_gj_ratio_vs_balsa_selected"),
        "legacy_cap_face_collar_stiffness_proxy": row.get(
            "legacy_cap_face_collar_stiffness_proxy"
        ),
        "legacy_effective_gj_ratio_vs_balsa_selected": row.get(
            "legacy_effective_gj_ratio_vs_balsa_selected"
        ),
        "fast_physics_components": row.get("fast_physics_components"),
        "legacy_fast_physics_components": row.get("legacy_fast_physics_components"),
        "fast_model_direct_twist_deg": row.get("fast_model_direct_twist_deg"),
        "fast_model_bounded_twist_deg": row.get("fast_model_bounded_twist_deg"),
        "legacy_fast_model_direct_twist_deg": row.get("legacy_fast_model_direct_twist_deg"),
        "legacy_fast_model_bounded_twist_deg": row.get("legacy_fast_model_bounded_twist_deg"),
        "twist_bound_deg": row.get("twist_bound_deg"),
        "mass_kg": trade.get("mass_kg"),
        "cg_x_m": trade.get("cg_x_m"),
        "static_margin": trade.get("static_margin"),
        "C_n_beta": trade.get("C_n_beta"),
        "selection_status": row.get("selection_status"),
        "blockers": row.get("blockers"),
        "calibration_priority": priority,
        "expected_solver": solver,
        "fem_purpose": purpose,
        "structural_credit_policy": (
            "shape_core_reference_only"
            if row.get("material_family_group") in _foam_reference_groups()
            else "candidate_structural_credit_requires_FEM_calibration"
        ),
        "result_status": "fem_result_required",
    }


def _calibration_interface() -> dict[str, Any]:
    return {
        "schema_version": "rib_torsion_fem_calibration_interface_v1",
        "result_schema": {
            "sample_id": {"required": True, "unit": "string"},
            "solver": {"required": True, "allowed": ["apdl", "calculix", "hand_check"]},
            "status": {"required": True, "allowed": ["completed", "failed", "not_run"]},
            "fem_twist_deg": {"required": True, "unit": "deg"},
            "fem_direct_twist_deg": {"required": False, "unit": "deg"},
            "fem_mass_kg": {"required": False, "unit": "kg"},
            "max_bond_shear_pa": {"required": False, "unit": "Pa"},
            "max_peel_pa": {"required": False, "unit": "Pa"},
            "tube_wall_margin": {"required": False, "unit": "margin"},
            "notes": {"required": False, "unit": "text"},
        },
        "update_policy": {
            "twist_factor": "fem_twist_deg / revised_fast_model_bounded_twist_deg",
            "legacy_twist_factor": "fem_twist_deg / legacy_fast_model_bounded_twist_deg",
            "mass_factor": "fem_mass_kg / fast_model_mass_kg when supplied",
            "next_loop_action": "compare revised fast physics against FEM, then rerun fast search without family correction if aligned",
            "do_not_promote": [
                "FEM calibration factor as a hidden replacement for physics terms",
                "EPS/XPS foam-only as structural bracing pass",
                "rear_spar_participation=1.0 as selected basis",
            ],
        },
    }


def _spotcheck_skeleton_manifest(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "calculix": [
            {
                "sample_id": sample.get("sample_id"),
                "path": f"calculix/{_safe_name(sample.get('sample_id'))}.inp",
                "status": "skeleton_to_complete_or_run_as_equivalent_beam_probe",
            }
            for sample in samples
        ],
        "apdl": [
            {
                "sample_id": sample.get("sample_id"),
                "path": f"apdl/{_safe_name(sample.get('sample_id'))}.mac",
                "status": "skeleton_to_complete_or_run_as_equivalent_beam_probe",
            }
            for sample in samples
        ],
    }


def _write_fem_skeletons(
    output_dir: Path,
    samples: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    calculix_dir = output_dir / "calculix"
    apdl_dir = output_dir / "apdl"
    calculix_dir.mkdir(parents=True, exist_ok=True)
    apdl_dir.mkdir(parents=True, exist_ok=True)
    for stale in calculix_dir.glob("*.inp"):
        stale.unlink()
    for stale in apdl_dir.glob("*.mac"):
        stale.unlink()
    calculix_decks: list[Path] = []
    apdl_decks: list[Path] = []
    calculix_manifest: list[dict[str, Any]] = []
    apdl_manifest: list[dict[str, Any]] = []
    for sample in samples:
        stem = _safe_name(sample.get("sample_id"))
        inp = calculix_dir / f"{stem}.inp"
        mac = apdl_dir / f"{stem}.mac"
        inp.write_text(_render_calculix_skeleton(sample), encoding="utf-8")
        mac.write_text(_render_apdl_skeleton(sample), encoding="utf-8")
        calculix_decks.append(inp)
        apdl_decks.append(mac)
        calculix_manifest.append({"sample_id": sample.get("sample_id"), "path": str(inp)})
        apdl_manifest.append({"sample_id": sample.get("sample_id"), "path": str(mac)})
    calculix_manifest_json = output_dir / "calculix_manifest.json"
    apdl_manifest_json = output_dir / "apdl_manifest.json"
    _write_json(calculix_manifest_json, {"decks": calculix_manifest})
    _write_json(apdl_manifest_json, {"decks": apdl_manifest})
    return {
        "calculix_manifest_json": calculix_manifest_json,
        "apdl_manifest_json": apdl_manifest_json,
        "calculix_decks": calculix_decks,
        "apdl_decks": apdl_decks,
    }


def _render_calculix_skeleton(sample: Mapping[str, Any]) -> str:
    thickness = _float_or_none(sample.get("rib_core_thickness_m")) or 0.010
    length = _float_or_none(sample.get("torque_zone_spacing_m")) or 0.30
    return "\n".join(
        [
            "** FAST MODEL CALIBRATION SKELETON - CalculiX equivalent torsion probe",
            f"** sample_id: {sample.get('sample_id')}",
            f"** source_case_id: {sample.get('source_case_id')}",
            "** foam-only rows are calibration references, not structural pass basis",
            "** Replace the equivalent bar with local rib/collar/bond mesh when geometry is fixed.",
            "*HEADING",
            f"Rib torsion calibration skeleton for {sample.get('sample_role')}",
            "*NODE",
            "1, 0.0, 0.0, 0.0",
            f"2, 0.0, {length:.6f}, 0.0",
            "*ELEMENT, TYPE=B31, ELSET=RIB_TORSION_EQUIV",
            "1, 1, 2",
            "*MATERIAL, NAME=FAST_PROXY",
            "*ELASTIC",
            "4.50E8, 0.30",
            "*BEAM SECTION, ELSET=RIB_TORSION_EQUIV, MATERIAL=FAST_PROXY, SECTION=RECT",
            f"0.050000, {thickness:.6f}",
            "0.0, 0.0, -1.0",
            "*BOUNDARY",
            "1, 1, 6, 0.0",
            "*STEP",
            "*STATIC",
            "*CLOAD",
            "2, 6, 1.0",
            "*NODE FILE",
            "U, RF",
            "*END STEP",
            "",
        ]
    )


def _render_apdl_skeleton(sample: Mapping[str, Any]) -> str:
    thickness = _float_or_none(sample.get("rib_core_thickness_m")) or 0.010
    length = _float_or_none(sample.get("torque_zone_spacing_m")) or 0.30
    return "\n".join(
        [
            "! FAST MODEL CALIBRATION SKELETON - APDL equivalent torsion probe",
            f"! sample_id: {sample.get('sample_id')}",
            f"! source_case_id: {sample.get('source_case_id')}",
            "! foam-only rows are calibration references, not structural pass basis",
            "/PREP7",
            "ET,1,BEAM188",
            "MP,EX,1,4.50E8",
            "MP,PRXY,1,0.30",
            "SECTYPE,1,BEAM,RECT",
            f"SECDATA,0.050000,{thickness:.6f}",
            "N,1,0,0,0",
            f"N,2,0,{length:.6f},0",
            "TYPE,1",
            "MAT,1",
            "SECNUM,1",
            "E,1,2",
            "D,1,ALL,0",
            "F,2,MZ,1.0",
            "/SOLU",
            "ANTYPE,0",
            "SOLVE",
            "/POST1",
            "*GET,TIP_ROTZ,NODE,2,ROT,Z",
            "*CFOPEN,calibration_result,txt",
            "*VWRITE,TIP_ROTZ",
            "(E16.8)",
            "*CFCLOS",
            "FINISH",
            "",
        ]
    )


def _calibration_results_template_rows(samples: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for sample in samples:
        rows.append(
            {
                "sample_id": sample.get("sample_id"),
                "solver": sample.get("expected_solver"),
                "status": "not_run",
                "fem_twist_deg": "",
                "fem_direct_twist_deg": "",
                "fem_mass_kg": "",
                "max_bond_shear_pa": "",
                "max_peel_pa": "",
                "tube_wall_margin": "",
                "notes": "",
            }
        )
    return rows


def _mark_pareto(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = [dict(row) for row in rows]
    candidates = [row for row in out if row.get("selection_status") == "candidate"]
    for row in out:
        row["pareto_front"] = False
    for row in candidates:
        dominated = False
        metrics = _pareto_metrics(row)
        for other in candidates:
            if other is row:
                continue
            other_metrics = _pareto_metrics(other)
            if all(o <= m + 1.0e-12 for o, m in zip(other_metrics, metrics)) and any(
                o < m - 1.0e-12 for o, m in zip(other_metrics, metrics)
            ):
                dominated = True
                break
        row["pareto_front"] = not dominated
    return out


def _pareto_metrics(row: Mapping[str, Any]) -> tuple[float, float, float, float]:
    trade = _mapping_at(row, "trade_metrics")
    return (
        float(trade.get("mass_kg") or math.inf),
        float(row.get("fast_model_bounded_twist_deg") or math.inf),
        float(trade.get("required_forward_rebalance_m") or math.inf),
        -float(trade.get("manufacturability_score") or 0.0),
    )


def _candidate_score(row: Mapping[str, Any]) -> tuple[float, float, float, float, str]:
    trade = _mapping_at(row, "trade_metrics")
    bound = float(row.get("twist_bound_deg") or 3.0)
    bounded = float(row.get("fast_model_bounded_twist_deg") or math.inf)
    direct = float(row.get("fast_model_direct_twist_deg") or math.inf)
    direct_warning = 0.15 if direct > bound else 0.0
    group_preference = {
        "hybrid_foam_balsa_cap": 0.00,
        "hybrid_foam_glass_carbon_face": 0.12,
        "balsa": 0.45,
    }.get(str(row.get("material_family_group")), 0.80)
    twist_margin_score = bounded / max(bound, 1.0e-12)
    mass_score = 0.12 * float(trade.get("mass_kg") or math.inf)
    manufact = -0.08 * float(trade.get("manufacturability_score") or 0.0)
    rebalance = float(trade.get("required_forward_rebalance_m") or math.inf)
    return (
        direct_warning,
        group_preference,
        twist_margin_score + mass_score + manufact,
        rebalance,
        str(row["case_id"]),
    )


def _search_verdict(
    *,
    candidate_rows: Sequence[Mapping[str, Any]],
    selected: Mapping[str, Any] | None,
    calibration_update: Mapping[str, Any] | None,
) -> str:
    if selected is None:
        return NO_REASONABLE_CANDIDATE
    if (
        calibration_update
        and not _family_twist_correction_factors(calibration_update)
        and calibration_update.get("status") != "fast_physics_alignment_diagnostic_ready"
    ):
        return UNRELIABLE_NEEDS_CALIBRATION
    if not candidate_rows:
        return UNRELIABLE_NEEDS_CALIBRATION
    return READY_FOR_FEM_CALIBRATION


def _engineering_read(
    verdict: str,
    selected: Mapping[str, Any] | None,
    samples: Sequence[Mapping[str, Any]],
) -> str:
    if verdict == NO_REASONABLE_CANDIDATE or selected is None:
        return (
            "No non-foam, bounded-rear-spar fast candidate clears bounded physical twist. "
            "The search space needs more torsion path authority before FEM calibration."
        )
    return (
        f"Fast loop selected {selected.get('case_id')} with bounded twist "
        f"{selected.get('fast_model_bounded_twist_deg')} deg. It is ready for FEM "
        f"calibration across {len(samples)} representative samples, not final signoff."
    )


def _closure_anchor_twist_factors(
    *,
    sensitivity_payload: Mapping[str, Any],
    selected_closure_payload: Mapping[str, Any],
) -> dict[str, float]:
    stiffness = _mapping_at(selected_closure_payload, "basis", "selected_stiffness_basis")
    family = str(stiffness.get("rib_family") or "")
    rear = str(stiffness.get("rear_spar_participation") or "")
    actual_bounded = _float_or_none(
        _mapping_at(selected_closure_payload, "basis", "aeroelastic_effects").get(
            "conservative_bounded_physical_projection_max_abs_deg"
        )
    )
    if not family or not rear or actual_bounded is None:
        return {}
    for raw in sensitivity_payload.get("stiffness_rework_candidates") or []:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("family_key")) == family and str(raw.get("rear_spar_participation")) == rear:
            projected = _float_or_none(
                _mapping_at(raw, "projection").get("projected_bounded_physical_twist_deg")
            )
            if projected and projected > 0.0:
                return {family: round(max(1.0, actual_bounded / projected), 6)}
    return {}


def _family_twist_correction_factors(calibration_update: Mapping[str, Any] | None) -> dict[str, float]:
    if not calibration_update:
        return {}
    factors: dict[str, float] = {}
    for family, values in _mapping_at(calibration_update, "family_correction_factors").items():
        if isinstance(values, Mapping):
            factor = _float_or_none(values.get("twist_factor"))
            if factor is not None and factor > 0.0:
                factors[str(family)] = factor
    return factors


def _tail_metrics(
    selected_closure_payload: Mapping[str, Any],
    sensitivity_payload: Mapping[str, Any],
) -> dict[str, Any]:
    trim = _mapping_at(selected_closure_payload, "basis", "trim_static_directional")
    cg = _mapping_at(selected_closure_payload, "basis", "cg_management")
    fallback_tail = _mapping_at(
        sensitivity_payload,
        "selected_basis",
        "tail_trim_static_directional_margins_after_mass_stiffness_changes",
    )
    fallback_cg = _mapping_at(sensitivity_payload, "selected_basis", "cg_impact")
    return {
        "tail_delta_H_margin_deg": _first_float(
            trim.get("delta_H_margin_to_limit_deg"),
            fallback_tail.get("worst_delta_H_margin_to_limit_deg"),
            0.0,
        ),
        "tail_delta_V_margin_deg": _first_float(
            trim.get("delta_V_margin_to_limit_deg"),
            fallback_tail.get("worst_delta_V_margin_to_limit_deg"),
            0.0,
        ),
        "static_margin": _first_float(
            trim.get("static_margin"),
            fallback_tail.get("worst_static_margin"),
            0.0,
        ),
        "C_n_beta": _first_float(
            trim.get("C_n_beta"),
            fallback_tail.get("C_n_beta_min_row"),
            0.0,
        ),
        "cg_x_m": _first_float(
            cg.get("final_cg_x_m"),
            fallback_cg.get("final_screening_cg_x_m"),
            0.75,
        ),
    }


def _twist_bound_deg(
    sensitivity_payload: Mapping[str, Any],
    selected_closure_payload: Mapping[str, Any],
) -> float:
    aero = _mapping_at(selected_closure_payload, "basis", "aeroelastic_effects")
    bound = _float_or_none(aero.get("elastic_twist_screening_bound_deg"))
    if bound is not None:
        return bound
    for raw in sensitivity_payload.get("stiffness_rework_candidates") or []:
        if isinstance(raw, Mapping):
            value = _float_or_none(_mapping_at(raw, "projection").get("elastic_twist_screening_bound_deg"))
            if value is not None:
                return value
    return 3.0


def _baseline_rib_mass(sensitivity_payload: Mapping[str, Any]) -> float:
    mass = _float_or_none(
        _mapping_at(sensitivity_payload, "selected_basis", "structural_mass_delta").get(
            "estimated_full_wing_rib_mass_kg"
        )
    )
    return 0.0 if mass is None else mass


def _thickness_values_for_family(
    *,
    family_key: str,
    group: str,
    base_thickness_m: float,
    thickness_values: Sequence[float],
) -> tuple[float, ...]:
    del thickness_values
    values = {float(base_thickness_m)}
    if group == "balsa":
        values.update({0.002, 0.003, 0.004, 0.006})
    elif group == "eps_xps_foam_core_shape_only":
        values.update({0.006, 0.008, 0.010, 0.012})
    elif group == "structural_foam_shape_core_reference":
        values.update({0.006, 0.008, 0.010, 0.012, 0.015})
    elif group in {"hybrid_foam_balsa_cap", "hybrid_foam_glass_carbon_face"}:
        values.update({0.008, 0.010, 0.012, 0.015})
    else:
        values.update({_default_thickness(family_key)})
    return tuple(sorted(value for value in values if value > 0.0))


def _thickness_stiffness_factor(
    *,
    group: str,
    thickness_m: float,
    base_thickness_m: float,
) -> float:
    ratio = thickness_m / max(base_thickness_m, 1.0e-12)
    if group in {"hybrid_foam_glass_carbon_face", "hybrid_foam_balsa_cap"}:
        exponent = 1.10
    elif group == "balsa":
        exponent = 1.25
    else:
        exponent = 0.70
    return max(0.10, ratio**exponent)


def _legacy_fast_physics_components(
    *,
    group: str,
    thickness_m: float,
    base_thickness_m: float,
    profile: Mapping[str, Any],
    reinforcement: Mapping[str, Any],
) -> dict[str, float | str]:
    thickness_factor = _thickness_stiffness_factor(
        group=group,
        thickness_m=thickness_m,
        base_thickness_m=base_thickness_m,
    )
    spacing_factor = float(profile["stiffness_factor"])
    local_factor = _legacy_local_factor_for_group(group, reinforcement)
    total = thickness_factor * spacing_factor * local_factor
    return {
        "model_id": LEGACY_FAST_MODEL_ID,
        "thickness_factor": thickness_factor,
        "spacing_factor": spacing_factor,
        "local_reinforcement_factor": local_factor,
        "total_stiffness_factor": total,
    }


def _fast_physics_components(
    *,
    group: str,
    thickness_m: float,
    base_thickness_m: float,
    effective_spacing_m: float,
    reinforcement: Mapping[str, Any],
    physical_model: Mapping[str, Any],
) -> dict[str, float | str]:
    """Return link-limited fast physics terms for rib torsion search.

    The model intentionally gives collar material only a modest link-efficiency
    credit. Carbon/glass collars help introduce load into the rib web, but they
    do not turn the whole main/rear spar cell into a rigid closed section.
    """

    thickness_factor = _physics_thickness_factor(
        group=group,
        thickness_m=thickness_m,
        base_thickness_m=base_thickness_m,
        physical_model=physical_model,
    )
    spacing_factor = _physics_spacing_factor(
        effective_spacing_m=effective_spacing_m,
        physical_model=physical_model,
    )
    local_factor = _physics_local_reinforcement_factor(
        group=group,
        reinforcement=reinforcement,
        physical_model=physical_model,
    )
    total = thickness_factor * spacing_factor * local_factor
    return {
        "model_id": FAST_PHYSICAL_MODEL_ID,
        "thickness_factor": thickness_factor,
        "spacing_factor": spacing_factor,
        "local_reinforcement_factor": local_factor,
        "total_stiffness_factor": max(0.05, total),
    }


def _physics_thickness_factor(
    *,
    group: str,
    thickness_m: float,
    base_thickness_m: float,
    physical_model: Mapping[str, Any],
) -> float:
    ratio = thickness_m / max(base_thickness_m, 1.0e-12)
    exponents = _mapping_at(physical_model, "thickness_exponents")
    exponent = _float_or_none(exponents.get(group))
    if exponent is None:
        exponent = 0.78 if group.startswith("hybrid_") else 0.70
    return max(0.10, ratio**exponent)


def _physics_spacing_factor(
    *,
    effective_spacing_m: float,
    physical_model: Mapping[str, Any],
) -> float:
    spacing = max(float(effective_spacing_m), 0.10)
    ratio = 0.30 / spacing
    exponents = _mapping_at(physical_model, "spacing_exponents")
    if spacing >= 0.30:
        exponent = _float_or_none(exponents.get("relaxed_spacing_penalty")) or 1.65
    else:
        exponent = _float_or_none(exponents.get("dense_spacing_reward")) or 0.55
    return max(0.10, ratio**exponent)


def _physics_local_reinforcement_factor(
    *,
    group: str,
    reinforcement: Mapping[str, Any],
    physical_model: Mapping[str, Any],
) -> float:
    key = str(reinforcement.get("key", "none"))
    if group in _foam_reference_groups():
        return 1.0
    if key == "none" and group in {"hybrid_foam_balsa_cap", "hybrid_foam_glass_carbon_face"}:
        factor = _float_or_none(physical_model.get("uncollared_hybrid_torque_zone_factor"))
        return max(0.10, factor if factor is not None else 0.64)
    if key == "none":
        return 1.0
    link_factors = _mapping_at(physical_model, "local_reinforcement_link_factors")
    factor = _float_or_none(link_factors.get(key))
    if factor is not None:
        return max(1.0, factor)
    return 1.0


def _rounded_component_dict(components: Mapping[str, float | str]) -> dict[str, float | str]:
    out: dict[str, float | str] = {}
    for key, value in components.items():
        if isinstance(value, float):
            out[key] = round(value, 6)
        else:
            out[key] = value
    return out


def _local_factor_for_group(group: str, reinforcement: Mapping[str, Any]) -> float:
    return _legacy_local_factor_for_group(group, reinforcement)


def _legacy_local_factor_for_group(group: str, reinforcement: Mapping[str, Any]) -> float:
    key = str(reinforcement.get("key", ""))
    factor = float(reinforcement.get("stiffness_factor", 1.0))
    if key == "none":
        return 1.0
    if group in _foam_reference_groups():
        return 1.0
    if group == "balsa" and "carbon" in key:
        return 1.18
    return factor


def _local_mass_for_group(group: str, reinforcement: Mapping[str, Any]) -> float:
    if str(reinforcement.get("key")) == "none":
        return 0.0
    if group in _foam_reference_groups():
        return 0.0
    return float(reinforcement.get("mass_delta_kg", 0.0))


def _manufacturability_score(
    *,
    group: str,
    thickness_m: float,
    profile: Mapping[str, Any],
    reinforcement: Mapping[str, Any],
) -> float:
    base = {
        "balsa": 0.68,
        "eps_xps_foam_core_shape_only": 0.93,
        "structural_foam_shape_core_reference": 0.76,
        "hybrid_foam_balsa_cap": 0.72,
        "hybrid_foam_glass_carbon_face": 0.56,
    }.get(group, 0.50)
    if abs(thickness_m - 0.010) < 1.0e-9:
        base += 0.05
    if thickness_m <= 0.003:
        base -= 0.04
    base += float(profile.get("manufacturability_delta", 0.0))
    base += float(reinforcement.get("manufacturability_delta", 0.0))
    return min(1.0, max(0.0, base))


def _material_family_group(family_key: str, category: str) -> str:
    text = f"{family_key} {category}".lower()
    if "eps" in text or "xps" in text:
        if "hybrid" in text or "cap" in text:
            return "hybrid_foam_balsa_cap"
        return "eps_xps_foam_core_shape_only"
    if "face" in text or "glass" in text or "carbon" in text:
        return "hybrid_foam_glass_carbon_face"
    if "structural_foam_only" in text or "foam_only" in text:
        return "structural_foam_shape_core_reference"
    if "balsa" in text:
        return "balsa"
    return "other"


def _foam_reference_groups() -> set[str]:
    return {"eps_xps_foam_core_shape_only", "structural_foam_shape_core_reference"}


def _row_claim_boundary(group: str) -> str:
    if group in _foam_reference_groups():
        return (
            "Foam-only row is retained as a shape-core/lightweight calibration reference; "
            "it is not eligible for structural bracing pass."
        )
    return "Fast-model candidate. Requires FEM calibration before any structural pass claim."


def _find_best_match(
    rows: Sequence[Mapping[str, Any]],
    *,
    family_key: str,
    thickness_m: float | None = None,
    rear_scale: float | None = None,
    reinforcement: str | None = None,
    spacing_profile: str | None = None,
    allow_rejected: bool,
) -> Mapping[str, Any] | None:
    matches = []
    for row in rows:
        if str(row.get("family_key")) != family_key:
            continue
        if not allow_rejected and row.get("selection_status") != "candidate":
            continue
        penalty = 0.0
        if thickness_m is not None:
            penalty += abs(float(row.get("rib_core_thickness_m") or 0.0) - thickness_m) * 1000.0
        if rear_scale is not None:
            penalty += abs(float(row.get("rear_stiffness_scale") or 0.0) - rear_scale) * 10.0
        if reinforcement is not None and row.get("local_reinforcement") != reinforcement:
            penalty += 2.0
        if spacing_profile is not None and row.get("rib_spacing_profile") != spacing_profile:
            penalty += 2.0
        matches.append((penalty, _candidate_score(row), row))
    if not matches:
        return None
    return sorted(matches, key=lambda item: (item[0], item[1]))[0][2]


def _best_aggressive_candidate(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    candidates = [
        row
        for row in rows
        if row.get("selection_status") == "candidate"
        and row.get("material_family_group") in {"hybrid_foam_balsa_cap", "hybrid_foam_glass_carbon_face"}
        and row.get("local_reinforcement") != "none"
        and float(row.get("rear_stiffness_scale") or 0.0) >= 0.65
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: (row["fast_model_bounded_twist_deg"], _candidate_score(row)))[0]


def _best_foam_reference(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    refs = [
        row
        for row in rows
        if row.get("material_family_group") in _foam_reference_groups()
        and row.get("rib_core_thickness_m") == 0.010
    ]
    if not refs:
        return None
    return sorted(
        refs,
        key=lambda row: (
            0 if row.get("local_reinforcement") == "none" else 1,
            0 if row.get("rib_spacing_profile") == "uniform_0p30" else 1,
            _mapping_at(row, "trade_metrics").get("mass_kg", math.inf),
        ),
    )[0]


def _direct_status(value: float, bound: float) -> str:
    return "clears_bound" if value <= bound + 1.0e-12 else "warning_above_bound"


def _bounded_status(value: float, bound: float) -> str:
    return "clears_bound" if value <= bound + 1.0e-12 else "blocked_above_bound"


def _candidate_id(
    *,
    family_key: str,
    thickness_m: float,
    spacing_profile: str,
    reinforcement: str,
    rear_scale: float,
) -> str:
    return (
        f"{family_key}__t{thickness_m * 1000.0:.1f}mm__{spacing_profile}__"
        f"{reinforcement}__rear{int(round(rear_scale * 100.0)):02d}"
    ).replace(".", "p")


def _rear_label(scale: float) -> str:
    return f"bounded_{int(round(float(scale) * 100.0)):02d}pct_screening"


def _rear_scale(row: Mapping[str, Any]) -> float | None:
    value = _float_or_none(row.get("rear_stiffness_scale"))
    if value is not None:
        return value
    label = str(row.get("rear_spar_participation", ""))
    match = re.search(r"(\d+)pct", label)
    if match:
        return float(match.group(1)) / 100.0
    return None


def _default_thickness(family_key: str) -> float:
    if "3mm" in family_key:
        return 0.003
    if "5mm" in family_key:
        return 0.005
    if "10mm" in family_key:
        return 0.010
    return 0.010


def _safe_name(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_")


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


def _first_float(*values: Any) -> float:
    for value in values:
        parsed = _float_or_none(value)
        if parsed is not None:
            return parsed
    return 0.0


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
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


def _render_markdown(summary: Mapping[str, Any], paths: Mapping[str, Any]) -> str:
    selected = _mapping_at(summary, "selected_fast_candidate")
    lines = [
        "# Current Pathfinder Rib / Torsion Fast Design Search",
        "",
        f"Candidate: `{summary.get('candidate_id')}`",
        f"Verdict: `{summary.get('engineering_verdict')}`",
        "",
        "## Selected Fast Candidate",
        "",
    ]
    if selected:
        trade = _mapping_at(selected, "trade_metrics")
        lines.extend(
            [
                f"- case: `{selected.get('case_id')}`",
                f"- family / group: `{selected.get('family_key')}` / "
                f"`{selected.get('material_family_group')}`",
                f"- thickness / spacing / local reinforcement: "
                f"`{selected.get('rib_core_thickness_mm')}` mm / "
                f"`{selected.get('rib_spacing_profile')}` / "
                f"`{selected.get('local_reinforcement')}`",
                f"- rear-spar participation: `{selected.get('rear_spar_participation')}`",
                f"- fast direct / bounded twist: "
                f"`{selected.get('fast_model_direct_twist_deg')}` deg / "
                f"`{selected.get('fast_model_bounded_twist_deg')}` deg",
                f"- mass / CG / rebalance: `{trade.get('mass_kg')}` kg / "
                f"`{trade.get('cg_x_m')}` m / `{trade.get('required_forward_rebalance_m')}` m",
                f"- tail trim / SM / C_n_beta: `{trade.get('tail_delta_H_margin_deg')}` deg / "
                f"`{trade.get('static_margin')}` / `{trade.get('C_n_beta')}`",
                "- evidence: `fast_model_result_needs_FEM_calibration`",
            ]
        )
    else:
        lines.append("- No selectable fast candidate.")
    lines.extend(
        [
            "",
            "## Shortlist",
            "",
            "| case | family | rear | mass kg | bounded twist deg | direct status | manuf |",
            "|---|---|---|---:|---:|---|---:|",
        ]
    )
    for row in summary.get("shortlist") or []:
        trade = _mapping_at(row, "trade_metrics")
        lines.append(
            f"| `{row.get('case_id')}` | `{row.get('family_key')}` | "
            f"`{row.get('rear_spar_participation')}` | {trade.get('mass_kg')} | "
            f"{row.get('fast_model_bounded_twist_deg')} | "
            f"`{row.get('direct_stress_test_status')}` | "
            f"{trade.get('manufacturability_score')} |"
        )
    lines.extend(
        [
            "",
            "## FEM Calibration Samples",
            "",
            "| role | family | fast bounded deg | solver | policy |",
            "|---|---|---:|---|---|",
        ]
    )
    for sample in summary.get("fem_calibration_samples") or []:
        lines.append(
            f"| `{sample.get('sample_role')}` | `{sample.get('family_key')}` | "
            f"{sample.get('fast_model_bounded_twist_deg')} | "
            f"`{sample.get('expected_solver')}` | "
            f"`{sample.get('structural_credit_policy')}` |"
        )
    lines.extend(
        [
            "",
            "## Outputs",
            "",
            f"- candidate design table: `{paths.get('candidate_csv')}`",
            f"- shortlist: `{paths.get('shortlist_csv')}`",
            f"- FEM sample set: `{paths.get('fem_sample_csv')}`",
            f"- calibration result template: `{paths.get('calibration_input_template_csv')}`",
            f"- selected closure rerun basis: `{paths.get('selected_closure_basis_json')}`",
            f"- CalculiX manifest: `{paths.get('calculix_manifest_json')}`",
            f"- APDL manifest: `{paths.get('apdl_manifest_json')}`",
            "",
            "## Engineering Boundary",
            "",
            str(summary.get("claim_boundary", "")),
            "",
            str(summary.get("engineering_read", "")),
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sensitivity-json", type=Path, default=DEFAULT_SENSITIVITY_JSON)
    parser.add_argument("--selected-closure-json", type=Path, default=DEFAULT_SELECTED_CLOSURE_JSON)
    parser.add_argument("--calibration-update-json", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    paths = write_rib_torsion_design_search_package(
        sensitivity_json=args.sensitivity_json,
        selected_closure_json=args.selected_closure_json,
        calibration_update_json=args.calibration_update_json,
        output_dir=args.output_dir,
        report_json=args.report_json,
        report_md=args.report_md,
    )
    summary = _read_json(paths["summary_json"])
    print(f"wrote {paths['summary_json']}")
    print(f"wrote {paths['report_json']}")
    print(f"wrote {paths['report_md']}")
    print(f"verdict: {summary['engineering_verdict']}")
    selected = summary.get("selected_fast_candidate") or {}
    if selected:
        print(f"selected: {selected.get('case_id')}")
        print(f"bounded_twist_deg: {selected.get('fast_model_bounded_twist_deg')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
