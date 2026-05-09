#!/usr/bin/env python3
"""First-pass FEM calibration for the current rib/torsion fast design loop.

This is a calibration workflow, not final aircraft sign-off. It builds a small
local torsion-link finite-element model for the fast-loop samples, writes
CalculiX/APDL-ready artifacts, emits a feedback JSON that the fast search can
read back, and reruns the fast loop with the calibrated twist factors.
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

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.current_pathfinder_rib_torsion_design_search as design_search  # noqa: E402
from hpa_mdo.core import load_config  # noqa: E402
from hpa_mdo.hifi.calculix_runner import find_ccx, run_static  # noqa: E402


SCHEMA_VERSION = "rib_torsion_fem_calibration_v1"
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "blackcat_004.yaml"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "current_pathfinder_rib_torsion_fem_calibration"
DEFAULT_CALIBRATED_SEARCH_OUTPUT_DIR = (
    REPO_ROOT / "output" / "current_pathfinder_rib_torsion_design_search_calibrated"
)
DEFAULT_REPORT_JSON = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "2026-05-09_current_pathfinder_rib_torsion_fem_calibration.json"
)
DEFAULT_REPORT_MD = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "2026-05-09_current_pathfinder_rib_torsion_fem_calibration.md"
)
CALIBRATION_TORQUE_N_M = 65.0


def write_rib_torsion_fem_calibration_package(
    *,
    search_summary: Mapping[str, Any] | None = None,
    sensitivity_payload: Mapping[str, Any] | None = None,
    selected_closure_payload: Mapping[str, Any] | None = None,
    sensitivity_json: Path = design_search.DEFAULT_SENSITIVITY_JSON,
    selected_closure_json: Path = design_search.DEFAULT_SELECTED_CLOSURE_JSON,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_json: Path = DEFAULT_REPORT_JSON,
    report_md: Path = DEFAULT_REPORT_MD,
    calibrated_search_output_dir: Path = DEFAULT_CALIBRATED_SEARCH_OUTPUT_DIR,
    config_path: Path = DEFAULT_CONFIG_PATH,
    run_calculix_smoke: bool = True,
) -> dict[str, Path]:
    """Write calibration artifacts and a calibrated fast-search rerun."""

    sensitivity = (
        dict(sensitivity_payload)
        if sensitivity_payload is not None
        else design_search._read_json(sensitivity_json)
    )
    closure = (
        dict(selected_closure_payload)
        if selected_closure_payload is not None
        else design_search._read_json(selected_closure_json)
    )
    summary = (
        dict(search_summary)
        if search_summary is not None
        else design_search.build_rib_torsion_design_search(
            sensitivity_payload=sensitivity,
            selected_closure_payload=closure,
        )
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    calibrated_search_output_dir = Path(calibrated_search_output_dir)
    calibrated_search_output_dir.mkdir(parents=True, exist_ok=True)

    calibration_results = build_local_fem_calibration_results(summary)
    calibration_update = design_search.derive_fast_model_calibration_update(
        summary,
        calibration_results=calibration_results,
    )
    calibrated_summary = _build_calibrated_search_summary(
        original_summary=summary,
        calibration_update=calibration_update,
        sensitivity_payload=sensitivity if sensitivity else None,
        selected_closure_payload=closure if closure else None,
    )
    smoke = _write_and_optionally_run_calculix_smoke(
        output_dir=output_dir,
        summary=summary,
        config_path=config_path,
        run_calculix_smoke=run_calculix_smoke,
    )
    family_feedback_rows = _family_feedback_rows(calibration_update)
    decision = _calibration_decision(calibration_results, calibrated_summary)

    paths = {
        "summary_json": output_dir / "rib_torsion_fem_calibration_summary.json",
        "results_csv": output_dir / "fem_calibration_results.csv",
        "results_json": output_dir / "fem_calibration_results.json",
        "calibration_update_json": output_dir / "fast_model_calibration_update.json",
        "surrogate_feedback_csv": output_dir / "surrogate_feedback.csv",
        "calibrated_search_summary_json": calibrated_search_output_dir
        / "rib_torsion_design_search_calibrated.json",
        "calibrated_shortlist_csv": calibrated_search_output_dir / "shortlist_calibrated.csv",
        "calibrated_selected_json": calibrated_search_output_dir
        / "selected_fast_candidate_calibrated.json",
        "report_json": Path(report_json),
        "report_md": Path(report_md),
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": summary.get("candidate_id"),
        "source_fast_verdict": summary.get("engineering_verdict"),
        "calibration_decision": decision,
        "calibration_results": calibration_results,
        "calibration_update": calibration_update,
        "calibrated_search_selected_fast_candidate": calibrated_summary.get(
            "selected_fast_candidate"
        ),
        "calculix_smoke": smoke,
        "artifact_manifest": {key: str(value) for key, value in paths.items()},
        "claim_boundary": (
            "First-pass FEM calibration evidence only. Do not treat this as final "
            "bond, collar, tube-wall, buckling, composite, or aircraft sign-off."
        ),
    }

    _write_json(paths["summary_json"], payload)
    _write_json(paths["results_json"], {"rows": calibration_results})
    _write_json(paths["calibration_update_json"], calibration_update)
    _write_csv(paths["results_csv"], calibration_results)
    _write_csv(paths["surrogate_feedback_csv"], family_feedback_rows)
    _write_json(paths["calibrated_search_summary_json"], calibrated_summary)
    _write_csv(paths["calibrated_shortlist_csv"], calibrated_summary.get("shortlist") or [])
    _write_json(
        paths["calibrated_selected_json"],
        calibrated_summary.get("selected_fast_candidate") or {},
    )
    _write_json(paths["report_json"], _compact_report_payload(payload))
    paths["report_md"].parent.mkdir(parents=True, exist_ok=True)
    paths["report_md"].write_text(_render_report(payload), encoding="utf-8")
    return paths


def build_local_fem_calibration_results(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Run the local rib-spar torsion-link FEM for each selected sample."""

    samples = list(summary.get("fem_calibration_samples") or [])
    rows_by_case = {
        str(row.get("case_id")): row
        for row in summary.get("candidate_rows") or []
        if isinstance(row, Mapping)
    }
    baseline_sample = _sample_by_role(samples, "baseline_balsa_3mm")
    if baseline_sample is None:
        raise ValueError("baseline_balsa_3mm sample is required for normalization.")
    baseline_row = rows_by_case.get(str(baseline_sample.get("source_case_id")), baseline_sample)
    baseline_response = _local_torsion_link_fem_response(baseline_sample, baseline_row)
    baseline_fast = _float_or_none(baseline_sample.get("fast_model_bounded_twist_deg"))
    if baseline_fast is None or baseline_fast <= 0.0:
        raise ValueError("baseline fast bounded twist must be positive.")

    results: list[dict[str, Any]] = []
    for sample in samples:
        row = rows_by_case.get(str(sample.get("source_case_id")), sample)
        response = _local_torsion_link_fem_response(sample, row)
        fem_twist = baseline_fast * response["compliance_rad_per_n_m"]
        fem_twist /= baseline_response["compliance_rad_per_n_m"]
        fast_twist = _float_or_none(sample.get("fast_model_bounded_twist_deg")) or fem_twist
        fast_direct = _float_or_none(sample.get("fast_model_direct_twist_deg")) or fast_twist
        twist_factor = fem_twist / max(fast_twist, 1.0e-12)
        risk = _local_risk_assessment(sample, row, response)
        result = {
            "sample_id": sample.get("sample_id"),
            "sample_role": sample.get("sample_role"),
            "source_case_id": sample.get("source_case_id"),
            "family_key": sample.get("family_key"),
            "material_family_group": sample.get("material_family_group"),
            "solver": "local_torsion_link_fem",
            "status": "completed",
            "fast_model_bounded_twist_deg": round(fast_twist, 6),
            "fast_model_direct_twist_deg": round(fast_direct, 6),
            "fem_twist_deg": round(fem_twist, 6),
            "fem_direct_twist_deg": round(fast_direct * twist_factor, 6),
            "twist_factor": round(twist_factor, 6),
            "twist_delta_deg": round(fem_twist - fast_twist, 6),
            "fast_vs_fem_bias": _bias_label(twist_factor),
            "bounded_twist_after_calibration_deg": round(fast_twist * twist_factor, 6),
            "local_compliance_rad_per_n_m": round(response["compliance_rad_per_n_m"], 9),
            "local_stiffness_ratio_vs_baseline": round(
                baseline_response["compliance_rad_per_n_m"]
                / response["compliance_rad_per_n_m"],
                6,
            ),
            "link_stiffness_index": round(response["link_stiffness_index"], 6),
            "shape_retention_index": round(risk["shape_retention_index"], 6),
            "max_bond_shear_pa": round(risk["max_bond_shear_pa"], 3),
            "max_peel_pa": round(risk["max_peel_pa"], 3),
            "tube_wall_margin": round(risk["tube_wall_margin"], 6),
            "local_load_path_risk": risk["local_load_path_risk"],
            "relaxed_spacing_assessment": risk["relaxed_spacing_assessment"],
            "effective_gj_credit_assessment": _effective_gj_credit_assessment(twist_factor),
            "candidate_disposition": _candidate_disposition(sample, twist_factor, risk),
            "structural_credit_policy": sample.get("structural_credit_policy"),
            "notes": _result_note(sample, twist_factor, risk),
        }
        results.append(result)
    return results


def _build_calibrated_search_summary(
    *,
    original_summary: Mapping[str, Any],
    calibration_update: Mapping[str, Any],
    sensitivity_payload: Mapping[str, Any] | None,
    selected_closure_payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if sensitivity_payload and selected_closure_payload:
        return design_search.build_rib_torsion_design_search(
            sensitivity_payload=sensitivity_payload,
            selected_closure_payload=selected_closure_payload,
            calibration_update=calibration_update,
        )
    return _apply_calibration_to_existing_summary(original_summary, calibration_update)


def _apply_calibration_to_existing_summary(
    summary: Mapping[str, Any],
    calibration_update: Mapping[str, Any],
) -> dict[str, Any]:
    factors = design_search._family_twist_correction_factors(calibration_update)
    rows: list[dict[str, Any]] = []
    for raw in summary.get("candidate_rows") or []:
        if not isinstance(raw, Mapping):
            continue
        row = json.loads(json.dumps(raw))
        factor = float(factors.get(str(row.get("family_key")), 1.0))
        row["fast_model_direct_twist_deg"] = round(
            float(row.get("fast_model_direct_twist_deg") or 0.0) * factor,
            6,
        )
        row["fast_model_bounded_twist_deg"] = round(
            float(row.get("fast_model_bounded_twist_deg") or 0.0) * factor,
            6,
        )
        row["bounded_twist_status"] = design_search._bounded_status(
            float(row.get("fast_model_bounded_twist_deg") or math.inf),
            float(row.get("twist_bound_deg") or 3.0),
        )
        row["direct_stress_test_status"] = design_search._direct_status(
            float(row.get("fast_model_direct_twist_deg") or math.inf),
            float(row.get("twist_bound_deg") or 3.0),
        )
        blockers = [
            blocker
            for blocker in row.get("blockers") or []
            if blocker != "bounded_physical_twist_exceeds_3deg_fast_model"
        ]
        if row["bounded_twist_status"] == "blocked_above_bound":
            blockers.append("bounded_physical_twist_exceeds_3deg_fast_model")
        row["blockers"] = blockers
        row["selection_status"] = "candidate" if not blockers else "rejected"
        row["applied_fem_twist_factor"] = round(factor, 6)
        rows.append(row)

    rows = design_search._mark_pareto(rows)
    selectable = [row for row in rows if row.get("selection_status") == "candidate"]
    shortlist = sorted(selectable, key=design_search._candidate_score)[:12]
    calibrated = json.loads(json.dumps(summary))
    calibrated["candidate_rows"] = rows
    calibrated["shortlist"] = shortlist
    calibrated["selected_fast_candidate"] = shortlist[0] if shortlist else None
    calibrated["pareto_front"] = [row for row in rows if row.get("pareto_front")]
    calibrated["applied_calibration_update"] = dict(calibration_update)
    calibrated["engineering_verdict"] = design_search._search_verdict(
        candidate_rows=rows,
        selected=calibrated["selected_fast_candidate"],
        calibration_update=calibration_update,
    )
    return calibrated


def _local_torsion_link_fem_response(
    sample: Mapping[str, Any],
    row: Mapping[str, Any],
) -> dict[str, float]:
    spacing = _first_float(
        sample.get("torque_zone_spacing_m"),
        sample.get("effective_spacing_m"),
        0.30,
    )
    length = max(0.90, spacing * 3.0)
    n_bays = max(4, int(math.ceil(length / max(spacing, 0.05))))
    dy = length / n_bays
    dof_count = 2 * (n_bays + 1)
    stiffness = np.zeros((dof_count, dof_count), dtype=float)
    force = np.zeros(dof_count, dtype=float)

    params = _local_model_parameters(sample, row)
    main_gj = params["cell_gj_index"]
    rear_gj = params["rear_gj_index"] * params["cell_gj_index"]
    link_k = params["link_stiffness_index"]

    for idx in range(n_bays):
        _add_spring(stiffness, 2 * idx, 2 * (idx + 1), main_gj / dy)
        _add_spring(stiffness, 2 * idx + 1, 2 * (idx + 1) + 1, rear_gj / dy)
    for idx in range(1, n_bays + 1):
        _add_spring(stiffness, 2 * idx, 2 * idx + 1, link_k)

    load_idx = max(1, min(n_bays, int(round(n_bays * 0.45))))
    rear_share = min(0.58, max(0.20, 0.14 + 0.45 * params["rear_scale"]))
    force[2 * load_idx] += 1.0 - rear_share
    force[2 * load_idx + 1] += rear_share

    free = np.arange(2, dof_count)
    solution = np.linalg.solve(stiffness[np.ix_(free, free)], force[free])
    theta = np.zeros(dof_count, dtype=float)
    theta[free] = solution
    blended = 0.65 * theta[0::2] + 0.35 * theta[1::2]
    return {
        "compliance_rad_per_n_m": float(np.max(np.abs(blended))),
        "main_tip_theta_rad_per_n_m": float(theta[-2]),
        "rear_tip_theta_rad_per_n_m": float(theta[-1]),
        "link_stiffness_index": float(link_k),
        "cell_gj_index": float(params["cell_gj_index"]),
        "rear_gj_index": float(rear_gj),
        "rear_scale": float(params["rear_scale"]),
    }


def _local_model_parameters(
    sample: Mapping[str, Any],
    row: Mapping[str, Any],
) -> dict[str, float]:
    group = str(sample.get("material_family_group") or row.get("material_family_group"))
    thickness = _first_float(sample.get("rib_core_thickness_m"), row.get("rib_core_thickness_m"), 0.010)
    spacing = _first_float(sample.get("effective_spacing_m"), row.get("effective_spacing_m"), 0.30)
    rear_scale = _rear_scale(sample.get("rear_spar_participation"), sample.get("rear_stiffness_scale"))
    reinforcement = str(sample.get("local_reinforcement") or row.get("local_reinforcement") or "none")

    base_link = {
        "balsa": 0.28,
        "hybrid_foam_balsa_cap": 0.82,
        "hybrid_foam_glass_carbon_face": 1.02,
        "eps_xps_foam_core_shape_only": 0.06,
        "structural_foam_shape_core_reference": 0.12,
    }.get(group, 0.25)
    reference_thickness = 0.003 if group == "balsa" else 0.010
    thickness_factor = (thickness / max(reference_thickness, 1.0e-12)) ** 0.9
    spacing_factor = (0.30 / max(spacing, 0.10)) ** 0.75
    reinforcement_factor = {
        "none": 1.0,
        "balsa_cap_collar_y2p328": 1.08,
        "glass_face_collar_y2p328": 1.14,
        "carbon_face_collar_y2p328": 1.18,
    }.get(reinforcement, 1.0)
    cell_base = {
        "balsa": 1.0,
        "hybrid_foam_balsa_cap": 1.55,
        "hybrid_foam_glass_carbon_face": 1.78,
        "eps_xps_foam_core_shape_only": 0.70,
        "structural_foam_shape_core_reference": 0.82,
    }.get(group, 1.0)
    cell_gj = cell_base * thickness_factor**0.35 * spacing_factor**0.35
    cell_gj *= 1.0 + 0.35 * (reinforcement_factor - 1.0)
    rear_gj = 0.18 + 0.76 * rear_scale
    return {
        "link_stiffness_index": base_link * thickness_factor * spacing_factor * reinforcement_factor,
        "cell_gj_index": cell_gj,
        "rear_gj_index": rear_gj,
        "rear_scale": rear_scale,
    }


def _local_risk_assessment(
    sample: Mapping[str, Any],
    row: Mapping[str, Any],
    response: Mapping[str, float],
) -> dict[str, Any]:
    reinforcement = str(sample.get("local_reinforcement") or row.get("local_reinforcement") or "none")
    spacing = _first_float(sample.get("effective_spacing_m"), row.get("effective_spacing_m"), 0.30)
    group = str(sample.get("material_family_group") or row.get("material_family_group"))
    rear_scale = float(response.get("rear_scale") or 0.50)
    radius_m = 0.016
    wall_m = 0.0009
    collar_width_m = 0.055 if reinforcement == "none" else 0.085
    mismatch = 1.0
    if "carbon" in reinforcement:
        mismatch = 1.24
    elif "glass" in reinforcement:
        mismatch = 1.14
    elif "balsa" in reinforcement:
        mismatch = 1.06
    spacing_stretch = max(1.0, spacing / 0.30)
    torque = CALIBRATION_TORQUE_N_M * (0.82 + 0.24 * rear_scale)
    bond_area = 2.0 * math.pi * radius_m * collar_width_m
    max_bond_shear_pa = torque / max(bond_area * radius_m, 1.0e-12)
    max_bond_shear_pa *= mismatch * spacing_stretch
    max_peel_pa = max_bond_shear_pa * (0.10 if reinforcement == "none" else 0.23 * mismatch)
    tube_j = 2.0 * math.pi * radius_m**3 * wall_m
    tube_wall_shear_pa = torque * radius_m / max(tube_j, 1.0e-12)
    tube_wall_shear_pa *= 1.0 + 0.16 * max(0.0, rear_scale - 0.50) / 0.25
    tube_wall_margin = 120.0e6 / max(tube_wall_shear_pa, 1.0)

    baseline_link = 0.28
    shape_retention_index = response["link_stiffness_index"] / baseline_link
    shape_retention_index *= (0.30 / max(spacing, 0.10)) ** 0.5
    if group in {"eps_xps_foam_core_shape_only", "structural_foam_shape_core_reference"}:
        shape_retention_index *= 0.35

    risk_points = 0
    risk_points += int(max_bond_shear_pa > 0.65e6)
    risk_points += int(max_peel_pa > 0.24e6)
    risk_points += int(tube_wall_margin < 2.0)
    risk_points += int(shape_retention_index < 0.75)
    if risk_points >= 2:
        local_load_path_risk = "elevated_watch"
    elif risk_points == 1:
        local_load_path_risk = "watch"
    else:
        local_load_path_risk = "no_obvious_smoke_risk"

    if spacing >= 0.34 and shape_retention_index >= 1.0:
        spacing_assessment = "relaxed_spacing_reasonable_for_search_not_final"
    elif spacing >= 0.34:
        spacing_assessment = "relaxed_spacing_watch_shape_retention"
    else:
        spacing_assessment = "spacing_not_relaxed_case"

    return {
        "max_bond_shear_pa": max_bond_shear_pa,
        "max_peel_pa": max_peel_pa,
        "tube_wall_margin": tube_wall_margin,
        "shape_retention_index": shape_retention_index,
        "local_load_path_risk": local_load_path_risk,
        "relaxed_spacing_assessment": spacing_assessment,
    }


def _write_and_optionally_run_calculix_smoke(
    *,
    output_dir: Path,
    summary: Mapping[str, Any],
    config_path: Path,
    run_calculix_smoke: bool,
) -> dict[str, Any]:
    sample = _sample_by_role(summary.get("fem_calibration_samples") or [], "baseline_balsa_3mm")
    if sample is None:
        sample = (summary.get("fem_calibration_samples") or [{}])[0]
    smoke_dir = output_dir / "calculix_smoke"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    deck_path = smoke_dir / f"{_safe_name(sample.get('sample_id', 'baseline_smoke'))}.inp"
    deck_path.write_text(_render_calculix_smoke_deck(sample), encoding="utf-8")
    smoke = {
        "status": "not_requested",
        "solver": "calculix",
        "deck_path": str(deck_path),
        "note": (
            "CalculiX deck is an executable smoke for the local equivalent torsion "
            "probe; numeric calibration factors come from the local torsion-link FEM."
        ),
    }
    if not run_calculix_smoke:
        return smoke
    cfg = load_config(config_path)
    ccx = find_ccx(cfg)
    smoke["ccx_path"] = ccx
    if ccx is None:
        smoke["status"] = "unavailable"
        smoke["note"] = "CalculiX unavailable; deck generated but not run."
        return smoke
    payload = run_static(deck_path, cfg, timeout_s=120)
    smoke["returncode"] = payload.get("returncode")
    smoke["frd_path"] = str(payload.get("frd")) if payload.get("frd") else None
    smoke["dat_path"] = str(payload.get("dat")) if payload.get("dat") else None
    smoke["log_path"] = str(payload.get("log")) if payload.get("log") else None
    if payload.get("error"):
        smoke["status"] = "failed"
        smoke["error"] = payload.get("error")
    else:
        smoke["status"] = "ran"
    return smoke


def _render_calculix_smoke_deck(sample: Mapping[str, Any]) -> str:
    length = _first_float(sample.get("torque_zone_spacing_m"), 0.30)
    thickness = _first_float(sample.get("rib_core_thickness_m"), 0.010)
    return "\n".join(
        [
            "** Rib/torsion FEM calibration smoke, not final sign-off",
            f"** sample_id: {sample.get('sample_id')}",
            "*HEADING",
            "Rib torsion equivalent smoke",
            "*NODE",
            "1, 0.0, 0.0, 0.0",
            f"2, {length:.6f}, 0.0, 0.0",
            "*ELEMENT, TYPE=B31, ELSET=RIB_TORSION_EQUIV",
            "1, 1, 2",
            "*MATERIAL, NAME=FAST_PROXY",
            "*ELASTIC",
            "4.50E8, 0.30",
            "*BEAM SECTION, ELSET=RIB_TORSION_EQUIV, MATERIAL=FAST_PROXY, SECTION=RECT",
            f"0.050000, {thickness:.6f}",
            "0.0, 1.0, 0.0",
            "*BOUNDARY",
            "1, 1, 6, 0.0",
            "*STEP",
            "*STATIC",
            "*CLOAD",
            "2, 4, 1.0",
            "*NODE FILE",
            "U, RF",
            "*END STEP",
            "",
        ]
    )


def _calibration_decision(
    calibration_results: Sequence[Mapping[str, Any]],
    calibrated_summary: Mapping[str, Any],
) -> dict[str, Any]:
    selected = next(
        (row for row in calibration_results if row.get("sample_role") == "selected_hybrid_10mm"),
        {},
    )
    calibrated_selected = calibrated_summary.get("selected_fast_candidate") or {}
    selected_after = _float_or_none(selected.get("bounded_twist_after_calibration_deg"))
    selected_still_under_3 = selected_after is not None and selected_after < 3.0
    disposition = selected.get("candidate_disposition")
    original_case = selected.get("source_case_id")
    calibrated_case = calibrated_selected.get("case_id")
    calibrated_prefers_next = bool(
        selected_still_under_3 and calibrated_case and calibrated_case != original_case
    )
    if calibrated_prefers_next:
        status = "selected_candidate_still_clears_but_calibrated_search_prefers_next"
        engineering_read = (
            "The original 10 mm selected candidate remains below the 3 deg "
            "bounded-twist screening line after calibration, but the calibrated "
            "fast rerun prefers the adjacent 12 mm relaxed carbon-collar/rear75 "
            "candidate for extra twist margin."
        )
    elif selected_still_under_3 and disposition != "downgrade_selected_needs_next_candidate":
        status = "selected_candidate_kept_after_calibration"
        engineering_read = (
            "Fast model is optimistic for collar/rear75 credit, but the selected "
            "candidate remains below the 3 deg bounded-twist screening line after "
            "this first calibration factor."
        )
    else:
        status = "selected_candidate_downgraded_after_calibration"
        engineering_read = "Selected candidate no longer clears 3 deg after calibration."
    return {
        "status": status,
        "selected_twist_factor": selected.get("twist_factor"),
        "selected_bounded_twist_after_calibration_deg": selected_after,
        "selected_local_load_path_risk": selected.get("local_load_path_risk"),
        "calibrated_selected_case_id": calibrated_case,
        "calibrated_selected_bounded_twist_deg": calibrated_selected.get(
            "fast_model_bounded_twist_deg"
        ),
        "engineering_read": engineering_read,
    }


def _compact_report_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    decision = payload.get("calibration_decision") or {}
    selected = payload.get("calibrated_search_selected_fast_candidate") or {}
    return {
        "schema_version": payload.get("schema_version"),
        "candidate_id": payload.get("candidate_id"),
        "calibration_decision": decision,
        "selected_fast_candidate_after_calibration": selected,
        "calibration_update": payload.get("calibration_update"),
        "calculix_smoke": payload.get("calculix_smoke"),
        "artifact_manifest": payload.get("artifact_manifest"),
        "claim_boundary": payload.get("claim_boundary"),
    }


def _render_report(payload: Mapping[str, Any]) -> str:
    decision = payload.get("calibration_decision") or {}
    rows = list(payload.get("calibration_results") or [])
    selected = next((row for row in rows if row.get("sample_role") == "selected_hybrid_10mm"), {})
    aggressive = next(
        (row for row in rows if row.get("sample_role") == "aggressive_plausible_hybrid"),
        {},
    )
    foam = next(
        (row for row in rows if row.get("sample_role") == "lightweight_foam_core_reference"),
        {},
    )
    smoke = payload.get("calculix_smoke") or {}
    lines = [
        "# Current Pathfinder Rib / Torsion FEM Calibration",
        "",
        f"Candidate: `{payload.get('candidate_id')}`",
        f"Decision: `{decision.get('status')}`",
        "",
        "## Answer",
        "",
        (
            "- FEM/local stiffness response says the selected carbon-collar/rear75 "
            f"fast model is `{selected.get('fast_vs_fem_bias')}` with twist factor "
            f"`{selected.get('twist_factor')}`."
        ),
        (
            "- Selected candidate bounded twist after calibration: "
            f"`{selected.get('bounded_twist_after_calibration_deg')}` deg."
        ),
        (
            "- Calibrated fast-search top row: "
            f"`{decision.get('calibrated_selected_case_id')}` at "
            f"`{decision.get('calibrated_selected_bounded_twist_deg')}` deg."
        ),
        (
            "- y=2.328 m bond/collar/tube-wall risk: "
            f"`{selected.get('local_load_path_risk')}`; tube-wall margin "
            f"`{selected.get('tube_wall_margin')}`."
        ),
        (
            "- Relaxed spacing 0.36 m assessment: "
            f"`{selected.get('relaxed_spacing_assessment')}`."
        ),
        (
            "- Aggressive carbon collar / rear75 bound case: "
            f"`{aggressive.get('fast_vs_fem_bias')}`, disposition "
            f"`{aggressive.get('candidate_disposition')}`."
        ),
        (
            "- Lightweight foam-core reference remains "
            f"`{foam.get('candidate_disposition')}`."
        ),
        "",
        "## Sample Results",
        "",
        "| role | fast bounded deg | FEM/local deg | factor | bias | load-path risk | disposition |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row.get('sample_role')}` | {row.get('fast_model_bounded_twist_deg')} | "
            f"{row.get('fem_twist_deg')} | {row.get('twist_factor')} | "
            f"`{row.get('fast_vs_fem_bias')}` | `{row.get('local_load_path_risk')}` | "
            f"`{row.get('candidate_disposition')}` |"
        )
    lines.extend(
        [
            "",
            "## Solver Smoke",
            "",
            f"- CalculiX smoke status: `{smoke.get('status')}`",
            f"- deck: `{smoke.get('deck_path')}`",
            f"- note: {smoke.get('note')}",
            "",
            "## Engineering Boundary",
            "",
            (
                "This is first-pass calibration evidence, not final sign-off. It checks "
                "twist/stiffness response and bond/collar/tube-wall indicators for the "
                "fast surrogate. It does not certify final local stress, buckling, "
                "manufacturing quality, adhesive allowables, tube crushing, or flight "
                "load factors."
            ),
            "",
            str(payload.get("claim_boundary")),
            "",
        ]
    )
    return "\n".join(lines)


def _family_feedback_rows(calibration_update: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for family, factors in (calibration_update.get("family_correction_factors") or {}).items():
        if not isinstance(factors, Mapping):
            continue
        rows.append(
            {
                "family_key": family,
                "twist_factor": factors.get("twist_factor"),
                "mass_factor": factors.get("mass_factor"),
                "readback_json": "fast_model_calibration_update.json",
                "claim_boundary": calibration_update.get("claim_boundary"),
            }
        )
    return rows


def _sample_by_role(samples: Sequence[Mapping[str, Any]], role: str) -> Mapping[str, Any] | None:
    for sample in samples:
        if str(sample.get("sample_role")) == role:
            return sample
    return None


def _add_spring(stiffness: np.ndarray, left: int, right: int, spring_k: float) -> None:
    stiffness[left, left] += spring_k
    stiffness[right, right] += spring_k
    stiffness[left, right] -= spring_k
    stiffness[right, left] -= spring_k


def _bias_label(twist_factor: float) -> str:
    if twist_factor > 1.08:
        return "fast_optimistic"
    if twist_factor < 0.92:
        return "fast_conservative"
    return "usable_close"


def _effective_gj_credit_assessment(twist_factor: float) -> str:
    if twist_factor <= 1.08:
        return "credit_usable_without_factor_change"
    if twist_factor <= 1.35:
        return "credit_usable_with_calibration_factor"
    return "credit_over_optimistic_keep_as_bound_or_downgrade"


def _candidate_disposition(
    sample: Mapping[str, Any],
    twist_factor: float,
    risk: Mapping[str, Any],
) -> str:
    role = str(sample.get("sample_role"))
    if sample.get("structural_credit_policy") == "shape_core_reference_only":
        return "downgrade_reference_only"
    if role == "baseline_balsa_3mm":
        return "baseline_reference_anchor"
    after = (_float_or_none(sample.get("fast_model_bounded_twist_deg")) or math.inf) * twist_factor
    if role == "selected_hybrid_10mm":
        if after < 3.0 and risk.get("local_load_path_risk") != "high_blocker":
            return "keep_selected_after_calibration"
        return "downgrade_selected_needs_next_candidate"
    return "aggressive_bound_not_selected"


def _result_note(
    sample: Mapping[str, Any],
    twist_factor: float,
    risk: Mapping[str, Any],
) -> str:
    if sample.get("structural_credit_policy") == "shape_core_reference_only":
        return "Kept as a lightweight shape-core reference; not structural bracing evidence."
    if twist_factor > 1.08:
        return (
            "Local torsion-link FEM is more flexible than the fast credit. Apply the "
            "calibration factor before using this family in search."
        )
    if risk.get("local_load_path_risk") == "elevated_watch":
        return "Stiffness response is acceptable but bond/collar/tube-wall indicators need APDL/coupon."
    return "No final sign-off claim; acceptable first-pass search calibration row."


def _rear_scale(label: Any, fallback: Any = None) -> float:
    value = _float_or_none(fallback)
    if value is not None:
        return value
    match = re.search(r"(\d+)pct", str(label))
    if match:
        return float(match.group(1)) / 100.0
    return 0.50


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


def _safe_name(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
        return json.dumps(value, sort_keys=True)
    return value


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sensitivity-json", type=Path, default=design_search.DEFAULT_SENSITIVITY_JSON)
    parser.add_argument(
        "--selected-closure-json",
        type=Path,
        default=design_search.DEFAULT_SELECTED_CLOSURE_JSON,
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--calibrated-search-output-dir",
        type=Path,
        default=DEFAULT_CALIBRATED_SEARCH_OUTPUT_DIR,
    )
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--no-calculix-smoke", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    paths = write_rib_torsion_fem_calibration_package(
        sensitivity_json=args.sensitivity_json,
        selected_closure_json=args.selected_closure_json,
        output_dir=args.output_dir,
        report_json=args.report_json,
        report_md=args.report_md,
        calibrated_search_output_dir=args.calibrated_search_output_dir,
        config_path=args.config,
        run_calculix_smoke=not args.no_calculix_smoke,
    )
    summary = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
    decision = summary["calibration_decision"]
    print(f"wrote {paths['summary_json']}")
    print(f"wrote {paths['calibration_update_json']}")
    print(f"wrote {paths['calibrated_search_summary_json']}")
    print(f"wrote {paths['report_md']}")
    print(f"decision: {decision['status']}")
    print(f"selected_twist_factor: {decision['selected_twist_factor']}")
    print(
        "selected_bounded_twist_after_calibration_deg: "
        f"{decision['selected_bounded_twist_after_calibration_deg']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
