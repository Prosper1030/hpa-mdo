#!/usr/bin/env python3
"""Screen current pathfinder tail geometry against CG, trim, and stability gates."""

from __future__ import annotations

import argparse
import copy
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import sys
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.aero.avl_exporter import stage_avl_airfoil_files  # noqa: E402
from hpa_mdo.aero.avl_runner import run_avl_derivatives  # noqa: E402
from hpa_mdo.core.constants import G_STANDARD  # noqa: E402
from scripts import full_aircraft_tail_avl_audit_v0 as tail_avl  # noqa: E402
from scripts import vtail_cg_reference_sensitivity_v0 as vtail_sensitivity  # noqa: E402


DEFAULT_CONTRACT = REPO_ROOT / "configs" / "current_pathfinder_tail_contract_v0.yaml"
DEFAULT_WING_AVL = tail_avl.DEFAULT_WING_AVL
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "current_pathfinder_tail_cg_trim_stability_v1"
DEFAULT_REPORT_JSON = (
    REPO_ROOT / "docs" / "reports" / "2026-05-09_tail_cg_trim_stability_screening_v1.json"
)
DEFAULT_REPORT_MD = (
    REPO_ROOT / "docs" / "reports" / "2026-05-09_tail_cg_trim_stability_screening_v1.md"
)
DEFAULT_REFERENCE_MASS_CONFIG = REPO_ROOT / "configs" / "blackcat_004.yaml"


@dataclass(frozen=True)
class TailCgTrimSizingCase:
    """One bounded H-tail / V-tail redesign case."""

    name: str
    h_area_multiplier: float
    h_aft_shift_m: float
    v_area_multiplier: float
    v_aft_shift_m: float


DEFAULT_SIZING_CASE = TailCgTrimSizingCase(
    name="h1p25_xaft1p5_v2p0_xaft1p0",
    h_area_multiplier=1.25,
    h_aft_shift_m=1.5,
    v_area_multiplier=2.0,
    v_aft_shift_m=1.0,
)
DEFAULT_CG_VALUES_M = (0.68, 0.72, 0.75)


def build_tail_contract_variant(
    contract: Mapping[str, Any],
    sizing_case: TailCgTrimSizingCase,
) -> tuple[dict[str, Any], list[str]]:
    """Apply bounded H-tail and V-tail sizing changes without mutating the source."""

    variant, v_warnings = vtail_sensitivity.build_vtail_contract_variant(
        contract,
        vtail_sensitivity.VtailSizingCase(
            name=sizing_case.name,
            area_multiplier=float(sizing_case.v_area_multiplier),
            aft_shift_m=float(sizing_case.v_aft_shift_m),
        ),
    )
    variant = copy.deepcopy(variant)
    h_box = _mutable_mapping_at(variant, "horizontal_tail", "design_box")
    wing = _mapping_at(variant, "reference", "wing")

    base_area = _read_number(h_box.get("S_H_m2"))
    span = _read_number(h_box.get("span_m"))
    base_x_le = _read_number(h_box.get("x_le_m"))
    x_ref = _read_number(wing.get("x_ref_avl_m"))
    if None in (base_area, span, base_x_le, x_ref):
        raise ValueError("H-tail variant requires S_H, span, x_le, and wing x_ref_avl_m.")

    area = float(base_area) * float(sizing_case.h_area_multiplier)
    chord = area / float(span)
    x_le = float(base_x_le) + float(sizing_case.h_aft_shift_m)
    x_ac = x_le + 0.25 * chord
    tail_arm = x_ac - float(x_ref)
    _set_number_node(h_box, "S_H_m2", area)
    _set_number_node(h_box, "mean_chord_m", chord)
    _set_number_node(h_box, "x_le_m", x_le)
    _set_number_node(h_box, "x_ac_H_m", x_ac)
    _set_number_node(h_box, "l_H_m", tail_arm)

    warnings = list(v_warnings)
    if area <= 0.0 or chord <= 0.0 or float(span) <= 0.0:
        warnings.append("invalid_nonpositive_htail_geometry")
    if tail_arm <= 0.0:
        warnings.append("invalid_nonpositive_htail_arm")
    if sizing_case.h_area_multiplier > 1.75:
        warnings.append("htail_area_multiplier_outside_v1_bound")
    if sizing_case.h_area_multiplier >= 1.75:
        warnings.append("large_htail_area_screening_only")
    if abs(sizing_case.h_aft_shift_m) > 1.5:
        warnings.append("htail_aft_shift_outside_v1_bound")
    aspect_ratio = float(span) * float(span) / area if area > 0.0 else math.inf
    if aspect_ratio < 2.0:
        warnings.append("very_low_horizontal_tail_aspect_ratio")
    return variant, sorted(set(warnings))


def verify_xnp_convention(
    neutral_case_result: Mapping[str, Any],
    *,
    xref_m: float,
    cref_m: float,
    tolerance_m: float = 1.0e-3,
) -> dict[str, Any]:
    """Verify AVL Xnp against Xref - Cma / CLa * Cref before using it."""

    derivatives = _mapping_at(neutral_case_result, "derivatives")
    raw = _mapping_at(neutral_case_result, "raw_derivatives")
    cl_alpha = _read_number(derivatives.get("CL_alpha"))
    cm_alpha = _read_number(derivatives.get("Cm_alpha"))
    xnp_raw = _read_number(raw.get("Xnp"))
    if None in (cl_alpha, cm_alpha, xnp_raw) or abs(float(cl_alpha)) <= 1.0e-12:
        return {
            "status": "missing_derivatives_do_not_use_xnp",
            "xnp_raw_m": _round_or_none(xnp_raw),
            "xnp_from_derivatives_m": None,
            "residual_m": None,
            "formula": "Xnp = Xref - C_m_alpha / C_L_alpha * Cref",
        }
    xnp_from_derivatives = float(xref_m) - float(cm_alpha) / float(cl_alpha) * float(cref_m)
    residual = abs(float(xnp_raw) - xnp_from_derivatives)
    status = (
        "verified_by_Cma_CLa_reference_sweep_formula"
        if residual <= float(tolerance_m)
        else "inconsistent_do_not_use_xnp"
    )
    return {
        "status": status,
        "xnp_raw_m": float(xnp_raw),
        "xnp_from_derivatives_m": xnp_from_derivatives,
        "residual_m": residual,
        "tolerance_m": float(tolerance_m),
        "formula": "Xnp = Xref - C_m_alpha / C_L_alpha * Cref",
    }


def summarize_cg_screening_row(
    *,
    sizing_case: TailCgTrimSizingCase,
    variant_contract: Mapping[str, Any],
    cg_x_m: float,
    case_results: Mapping[str, Mapping[str, Any]],
    cl_required: float,
    small_delta_deg: float,
    beta_screen_deg: float,
    static_margin_min: float,
    xnp_tolerance_m: float,
    alpha_limit_deg: float = 12.0,
    cn_beta_min: float = 0.005,
    cn_delta_v_min: float = 0.005,
    yaw_roll_ratio_limit: float = 20.0,
) -> dict[str, Any]:
    """Summarize one CG row with moment reference explicitly located at CG."""

    neutral = case_results.get("neutral", {})
    wing = _mapping_at(variant_contract, "reference", "wing")
    h_box = _mapping_at(variant_contract, "horizontal_tail", "design_box")
    v_box = _mapping_at(variant_contract, "vertical_tail", "design_box")
    cref = _read_number(wing.get("cbar_w_m"))
    if cref is None:
        raise ValueError("Screening row requires reference.wing.cbar_w_m.")

    cm_delta_h = tail_avl._finite_difference(
        case_results,
        minus_key="h_delta_minus_small",
        plus_key="h_delta_plus_small",
        coefficient="Cm",
        delta_deg=small_delta_deg,
    )
    cl_delta_h = tail_avl._finite_difference(
        case_results,
        minus_key="h_delta_minus_small",
        plus_key="h_delta_plus_small",
        coefficient="CL",
        delta_deg=small_delta_deg,
    )
    trim_solution = tail_avl._solve_linear_trim(
        _mapping_at(neutral, "coefficients"),
        _mapping_at(neutral, "derivatives"),
        cl_required,
        cm_delta_h,
        cl_delta_h,
    )
    xnp_check = verify_xnp_convention(
        neutral,
        xref_m=float(cg_x_m),
        cref_m=float(cref),
        tolerance_m=float(xnp_tolerance_m),
    )
    static_margin = None
    if xnp_check["status"] == "verified_by_Cma_CLa_reference_sweep_formula":
        static_margin = (float(xnp_check["xnp_raw_m"]) - float(cg_x_m)) / float(cref)

    h_usable = _usable_range(h_box)
    delta_h = _read_number(trim_solution.get("delta_H_required_deg"))
    alpha = _read_number(trim_solution.get("alpha_required_deg"))
    h_margin = _range_margin(delta_h, h_usable)

    cn_delta_v = tail_avl._finite_difference(
        case_results,
        minus_key="v_delta_minus_small",
        plus_key="v_delta_plus_small",
        coefficient="Cn",
        delta_deg=small_delta_deg,
    )
    cl_delta_v = tail_avl._finite_difference(
        case_results,
        minus_key="v_delta_minus_small",
        plus_key="v_delta_plus_small",
        coefficient="Cl",
        delta_deg=small_delta_deg,
    )
    coefficients = _mapping_at(neutral, "coefficients")
    derivatives = _mapping_at(neutral, "derivatives")
    cn0 = _read_number(coefficients.get("Cn")) or 0.0
    cn_beta = _read_number(derivatives.get("Cn_beta"))
    cl_beta = _read_number(derivatives.get("Cl_beta"))
    delta_v = _solve_delta_v_required_deg(
        cn0=cn0,
        cn_beta=cn_beta,
        cn_delta_v=cn_delta_v,
        beta_screen_deg=beta_screen_deg,
    )
    v_usable = _usable_range(v_box)
    v_margin = _range_margin(delta_v, v_usable)
    yaw_roll_ratio = _ratio_abs(cl_beta, cn_beta)
    control_roll_ratio = _ratio_abs(cl_delta_v, cn_delta_v)

    blockers = []
    if xnp_check["status"] != "verified_by_Cma_CLa_reference_sweep_formula":
        blockers.append("xnp_convention_not_verified")
    if trim_solution.get("status") != "solved_linearized_screening":
        blockers.append("longitudinal_trim_not_solved")
    if static_margin is None or static_margin < float(static_margin_min):
        blockers.append("static_margin_below_screening_min")
    if alpha is None or abs(alpha) > float(alpha_limit_deg):
        blockers.append("alpha_required_outside_screening_limit")
    if h_margin is None or h_margin < 0.0:
        blockers.append("h_tail_deflection_reserve_exceeded")
    if cn_beta is None or cn_beta < float(cn_beta_min):
        blockers.append("directional_stability_below_screening_min")
    if cn_delta_v is None or abs(cn_delta_v) < float(cn_delta_v_min):
        blockers.append("v_tail_authority_below_screening_min")
    if v_margin is None or v_margin < 0.0:
        blockers.append("v_tail_deflection_reserve_exceeded")
    if yaw_roll_ratio is not None and yaw_roll_ratio > float(yaw_roll_ratio_limit):
        blockers.append("yaw_roll_coupling_ratio_above_screening_limit")

    return {
        "case": sizing_case.name,
        "cg_x_m": round(float(cg_x_m), 6),
        "status": "pass_screening" if not blockers else "blocked",
        "blockers": blockers,
        "moment_reference": {
            "Xref_m": round(float(cg_x_m), 6),
            "Xref_role": "screening_cg_moment_reference",
            "reason": "AVL pitch moments for this row are explicitly referenced about CG.",
        },
        "xnp_convention": _round_nested(xnp_check),
        "longitudinal_trim": {
            "CL_required": round(float(cl_required), 6),
            "alpha_required_deg": _round_or_none(alpha),
            "alpha_limit_deg": float(alpha_limit_deg),
            "delta_H_required_deg": _round_or_none(delta_h),
            "usable_delta_H_range_deg": h_usable,
            "delta_H_margin_to_limit_deg": _round_or_none(h_margin),
            "static_margin": _round_or_none(static_margin),
            "static_margin_min": float(static_margin_min),
            "C_m_alpha": _round_or_none(_read_number(derivatives.get("Cm_alpha"))),
            "C_L_alpha": _round_or_none(_read_number(derivatives.get("CL_alpha"))),
            "C_m_deltaH": _round_or_none(cm_delta_h),
            "C_L_deltaH": _round_or_none(cl_delta_h),
            "trim_solution_status": trim_solution.get("status"),
            "H_tail_CL_utilization": {
                "status": "not_available_screening_uses_deflection_reserve",
                "reason": "No promoted H-tail polar/strip-load CLmax exists yet.",
            },
        },
        "directional": {
            "beta_screen_deg": float(beta_screen_deg),
            "C_n_beta": _round_or_none(cn_beta),
            "C_n_beta_min": float(cn_beta_min),
            "C_n_deltaV": _round_or_none(cn_delta_v),
            "C_n_deltaV_min_abs": float(cn_delta_v_min),
            "delta_V_required_deg": _round_or_none(delta_v),
            "usable_delta_V_range_deg": v_usable,
            "delta_V_margin_to_limit_deg": _round_or_none(v_margin),
            "C_l_beta": _round_or_none(cl_beta),
            "C_l_deltaV": _round_or_none(cl_delta_v),
            "abs_C_l_beta_over_C_n_beta": _round_or_none(yaw_roll_ratio),
            "abs_C_l_deltaV_over_C_n_deltaV": _round_or_none(control_roll_ratio),
            "yaw_roll_ratio_limit": float(yaw_roll_ratio_limit),
        },
        "geometry": _geometry_payload(variant_contract),
    }


def run_tail_cg_trim_stability_screening(
    *,
    contract: Mapping[str, Any],
    wing_avl_path: Path,
    output_dir: Path,
    report_json_path: Path,
    report_md_path: Path,
    sizing_case: TailCgTrimSizingCase = DEFAULT_SIZING_CASE,
    cg_values_m: Sequence[float] = DEFAULT_CG_VALUES_M,
    run_avl: bool = True,
    avl_binary: str | None = None,
    small_delta_deg: float = 2.0,
    timeout_s: float = 120.0,
    beta_screen_deg: float = 12.0,
    static_margin_min: float = 0.05,
    xnp_tolerance_m: float = 1.0e-3,
    tail_profile_cd0: float = 0.010,
    reference_mass_config_path: Path = DEFAULT_REFERENCE_MASS_CONFIG,
) -> dict[str, Any]:
    """Generate the current pathfinder tail / CG / trim / stability screen."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    variant, geometry_warnings = build_tail_contract_variant(contract, sizing_case)
    cl_required = _cl_required(variant)

    deck_records: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    runner_status = "completed" if run_avl else "runner_disabled"
    sweep_cases = (
        ("neutral", 0.0, 0.0),
        ("h_delta_minus_small", -float(small_delta_deg), 0.0),
        ("h_delta_plus_small", float(small_delta_deg), 0.0),
        ("v_delta_minus_small", 0.0, -float(small_delta_deg)),
        ("v_delta_plus_small", 0.0, float(small_delta_deg)),
    )

    for cg_x_m in cg_values_m:
        cg_token = _token(cg_x_m)
        case_results: dict[str, dict[str, Any]] = {}
        for sweep_name, delta_h, delta_v in sweep_cases:
            case_dir = output_dir / sizing_case.name / f"cg_{cg_token}" / sweep_name
            case_dir.mkdir(parents=True, exist_ok=True)
            deck_path = case_dir / f"{sizing_case.name}_cg{cg_token}_{sweep_name}.avl"
            deck_text, deck_manifest = tail_avl.build_full_aircraft_deck_text(
                wing_avl_path=Path(wing_avl_path),
                contract=variant,
                delta_h_deg=delta_h,
                delta_v_deg=delta_v,
                moment_reference_x_m=float(cg_x_m),
                moment_reference_role="screening_cg_moment_reference",
            )
            deck_path.write_text(deck_text, encoding="utf-8")
            staged_airfoils = stage_avl_airfoil_files(deck_path)
            deck_manifest.update(
                {
                    "sizing_case": asdict(sizing_case),
                    "cg_x_m": float(cg_x_m),
                    "geometry_warnings": geometry_warnings,
                    "staged_airfoil_files": [str(path.resolve()) for path in staged_airfoils],
                }
            )
            manifest_path = case_dir / f"{deck_path.stem}_deck_manifest.json"
            manifest_path.write_text(
                json.dumps(deck_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            deck_record = {
                "case": sizing_case.name,
                "cg_x_m": float(cg_x_m),
                "sweep": sweep_name,
                "delta_H_deg": delta_h,
                "delta_V_deg": delta_v,
                "deck_path": str(deck_path.resolve()),
                "deck_manifest_path": str(manifest_path.resolve()),
            }
            deck_records.append(deck_record)
            if not run_avl:
                case_results[sweep_name] = {"run_status": "runner_disabled"}
                continue

            result = run_avl_derivatives(
                avl_path=deck_path,
                out_dir=case_dir,
                avl_binary=avl_binary,
                alpha_deg=0.0,
                velocity=_cruise_value(variant, "speed_mps"),
                density=_cruise_value(variant, "rho_kgpm3"),
                timeout_s=timeout_s,
                stem=deck_path.stem,
            )
            deck_record["avl_run"] = result.as_dict()
            if result.error or result.st_path is None:
                runner_status = "runner_missing" if result.error == "avl_binary_not_found" else (
                    result.error or "st_file_not_produced"
                )
                case_results[sweep_name] = {"run_status": runner_status}
                continue
            case_results[sweep_name] = tail_avl._parse_case_result(result.st_path)

        if run_avl and all(item.get("run_status") == "completed" for item in case_results.values()):
            row = summarize_cg_screening_row(
                sizing_case=sizing_case,
                variant_contract=variant,
                cg_x_m=float(cg_x_m),
                case_results=case_results,
                cl_required=cl_required,
                small_delta_deg=float(small_delta_deg),
                beta_screen_deg=float(beta_screen_deg),
                static_margin_min=float(static_margin_min),
                xnp_tolerance_m=float(xnp_tolerance_m),
            )
        else:
            row = {
                "case": sizing_case.name,
                "cg_x_m": round(float(cg_x_m), 6),
                "status": "blocked",
                "blockers": [runner_status],
                "case_results": case_results,
            }
        rows.append(row)

    artifact_manifest = {
        "schema_version": "tail_cg_trim_stability_screening_manifest_v1",
        "output_dir": str(output_dir.resolve()),
        "deck_count": len(deck_records),
        "cases": deck_records,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(artifact_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    verdict = _overall_verdict(rows=rows, runner_status=runner_status)
    summary = {
        "schema_version": "tail_cg_trim_stability_screening_v1",
        "candidate_id": str(_mapping_at(contract, "pathfinder").get("candidate_id", "")),
        "contract_id": str(contract.get("contract_id", "")),
        "engineering_verdict": verdict,
        "runner_status": runner_status,
        "sizing_case": asdict(sizing_case),
        "screening_assumption_contract": {
            "cg_range_x_m": [min(cg_values_m), max(cg_values_m)],
            "cg_grid_x_m": [float(value) for value in cg_values_m],
            "cg_status": "screening_assumption_not_measured_cg_truth",
            "cg_basis": [
                "AVL moments in this artifact are explicitly referenced about each CG row.",
                "Tracked M14 mass-budget estimates are used only as a CG clue, not truth.",
                "The next rib/rear-spar sensitivity must keep CG as an input range.",
            ],
            "moment_reference_convention": "Set AVL Xref equal to the row CG for trim rows.",
            "xnp_convention_gate": "Use Xnp only when Xnp = Xref - Cma/CLa*Cref is verified.",
            "beta_screen_deg": float(beta_screen_deg),
            "static_margin_min": float(static_margin_min),
        },
        "artifact_manifest": artifact_manifest,
        "rows": rows,
        "selected_basis": _selected_basis_payload(variant, rows),
        "tail_drag_mass_treatment": estimate_tail_drag_mass_treatment(
            baseline_contract=contract,
            selected_contract=variant,
            tail_profile_cd0=tail_profile_cd0,
        ),
        "mass_cg_clue": estimate_mass_budget_cg_clue(reference_mass_config_path),
        "geometry_warnings": geometry_warnings,
        "claim_boundary": (
            "Screening-level AVL + algebraic basis only. This is not final FEM, "
            "hardware certification, tail polar signoff, or a measured CG manifest."
        ),
    }
    report_json_path.parent.mkdir(parents=True, exist_ok=True)
    report_json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_md_path.parent.mkdir(parents=True, exist_ok=True)
    report_md_path.write_text(_render_markdown(summary), encoding="utf-8")
    return summary


def estimate_tail_drag_mass_treatment(
    *,
    baseline_contract: Mapping[str, Any],
    selected_contract: Mapping[str, Any],
    tail_profile_cd0: float,
    baseline_tail_mass_kg: float = 2.4,
) -> dict[str, Any]:
    """Return a traceable screening tail drag/mass delta, not a final budget."""

    base = _tail_geometry_totals(baseline_contract)
    selected = _tail_geometry_totals(selected_contract)
    s_w = _read_number(_mapping_at(selected_contract, "reference", "wing").get("S_w_m2"))
    cruise = _mapping_at(selected_contract, "reference", "mission_cases", "cruise")
    q_pa = _read_number(cruise.get("dynamic_pressure_pa"))
    speed = _read_number(cruise.get("speed_mps"))
    selected_area = selected["S_H_m2"] + selected["S_V_m2"]
    baseline_area = base["S_H_m2"] + base["S_V_m2"]
    mass_scale = selected_area / baseline_area if baseline_area > 0.0 else None
    selected_tail_mass = None if mass_scale is None else float(baseline_tail_mass_kg) * mass_scale
    cd0_increment = (
        None
        if s_w is None
        else float(tail_profile_cd0) * selected_area / float(s_w)
    )
    power_increment_w = (
        None
        if None in (q_pa, speed, s_w, cd0_increment)
        else float(q_pa) * float(s_w) * float(cd0_increment) * float(speed)
    )
    return {
        "status": "screening_delta_not_charged_to_candidate_truth",
        "tail_profile_cd0_assumption": float(tail_profile_cd0),
        "baseline_tail_mass_kg_assumption": float(baseline_tail_mass_kg),
        "baseline_tail_area_m2": round(baseline_area, 6),
        "selected_tail_area_m2": round(selected_area, 6),
        "selected_tail_mass_kg_estimate": _round_or_none(selected_tail_mass),
        "tail_mass_delta_kg_estimate": _round_or_none(
            None if selected_tail_mass is None else selected_tail_mass - baseline_tail_mass_kg
        ),
        "tail_cd0_increment_estimate": _round_or_none(cd0_increment),
        "tail_profile_power_increment_w_estimate": _round_or_none(power_increment_w),
        "cg_coupling_warning": (
            "Selected tail mass is aft of the wing reference. Keep the next sensitivity "
            "inside the recommended CG range or rerun this screen with the aft-shifted CG; "
            "do not silently add tail mass and keep the same stability claim."
        ),
        "engineering_read": (
            "Use as a screening penalty in the next sensitivity. It is not a measured "
            "tail structural mass, pivot mass, or full trim-induced drag model."
        ),
    }


def estimate_mass_budget_cg_clue(path: Path) -> dict[str, Any]:
    """Read the tracked M14 mass budget as a clue without promoting it to truth."""

    path = Path(path)
    if not path.exists():
        return {"status": "not_found", "path": str(path)}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    mass_budget = loaded.get("mass_budget") if isinstance(loaded, Mapping) else None
    if not isinstance(mass_budget, Mapping):
        return {"status": "mass_budget_missing", "path": str(path)}
    rows = []
    for key, value in mass_budget.items():
        if not isinstance(value, Mapping):
            continue
        mass = _read_number(value.get("m_kg"))
        xyz = value.get("xyz_m")
        if mass is None or not isinstance(xyz, list | tuple) or len(xyz) != 3:
            continue
        rows.append({"name": str(key), "m_kg": float(mass), "x_m": float(xyz[0])})
    total = sum(row["m_kg"] for row in rows)
    point_cg = None if total <= 0.0 else sum(row["m_kg"] * row["x_m"] for row in rows) / total
    target_total = _read_number(mass_budget.get("target_total_mass_kg"))
    remainder = None if target_total is None else float(target_total) - total
    remainder_x = 0.35
    target_cg = None
    if target_total is not None and float(target_total) > 0.0 and remainder is not None:
        target_cg = (
            sum(row["m_kg"] * row["x_m"] for row in rows) + remainder * remainder_x
        ) / float(target_total)
    return {
        "status": "estimated_clue_not_promoted_truth",
        "path": str(path),
        "point_mass_total_kg": _round_or_none(total),
        "point_mass_cg_x_m": _round_or_none(point_cg),
        "target_total_mass_kg": _round_or_none(target_total),
        "remainder_mass_kg": _round_or_none(remainder),
        "remainder_x_m_assumption": remainder_x,
        "target_total_cg_x_m_clue": _round_or_none(target_cg),
        "engineering_read": (
            "This tracked M14 estimate suggests the current CG may be around the upper "
            "screening range, but it is not a current pathfinder measured CG manifest."
        ),
    }


def _selected_basis_payload(
    selected_contract: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    pass_rows = [row for row in rows if row.get("status") == "pass_screening"]
    worst_h_margin = _min_field(pass_rows, ("longitudinal_trim", "delta_H_margin_to_limit_deg"))
    worst_v_margin = _min_field(pass_rows, ("directional", "delta_V_margin_to_limit_deg"))
    min_static_margin = _min_field(pass_rows, ("longitudinal_trim", "static_margin"))
    max_delta_h = _max_abs_field(pass_rows, ("longitudinal_trim", "delta_H_required_deg"))
    max_delta_v = _max_abs_field(pass_rows, ("directional", "delta_V_required_deg"))
    return {
        "geometry": _geometry_payload(selected_contract),
        "recommended_cg_range_x_m": [
            min(row["cg_x_m"] for row in rows),
            max(row["cg_x_m"] for row in rows),
        ],
        "row_count": len(rows),
        "pass_row_count": len(pass_rows),
        "worst_static_margin": _round_or_none(min_static_margin),
        "max_abs_delta_H_required_deg": _round_or_none(max_delta_h),
        "worst_delta_H_margin_to_limit_deg": _round_or_none(worst_h_margin),
        "max_abs_delta_V_required_deg": _round_or_none(max_delta_v),
        "worst_delta_V_margin_to_limit_deg": _round_or_none(worst_v_margin),
    }


def _overall_verdict(*, rows: Sequence[Mapping[str, Any]], runner_status: str) -> str:
    if runner_status != "completed":
        return "needs_cg_mass_contract_before_any_tail_claim"
    if rows and all(row.get("status") == "pass_screening" for row in rows):
        return "ready_for_tail_aware_rib_rear_spar_sensitivity"
    blockers = {blocker for row in rows for blocker in row.get("blockers", [])}
    if any("xnp" in blocker or "trim" in blocker for blocker in blockers):
        return "needs_cg_mass_contract_before_any_tail_claim"
    if any("tail" in blocker or "directional" in blocker for blocker in blockers):
        return "needs_tail_geometry_redesign_before_rib_sensitivity"
    return "pathfinder_not_aircraft_feasible_under_reasonable_tail_bounds"


def _cl_required(contract: Mapping[str, Any]) -> float:
    wing = _mapping_at(contract, "reference", "wing")
    cruise = _mapping_at(contract, "reference", "mission_cases", "cruise")
    sref = _read_number(wing.get("S_w_m2"))
    q_pa = _read_number(cruise.get("dynamic_pressure_pa"))
    if q_pa is None:
        rho = _read_number(cruise.get("rho_kgpm3"))
        speed = _read_number(cruise.get("speed_mps"))
        q_pa = None if None in (rho, speed) else 0.5 * float(rho) * float(speed) ** 2
    mass = _read_number(cruise.get("mass_kg"))
    load_factor = _read_number(cruise.get("load_factor")) or 1.0
    if None in (sref, q_pa, mass):
        raise ValueError("CL_required needs cruise mass, q, and Sref.")
    return float(mass) * G_STANDARD * float(load_factor) / (float(q_pa) * float(sref))


def _geometry_payload(contract: Mapping[str, Any]) -> dict[str, Any]:
    h_box = _mapping_at(contract, "horizontal_tail", "design_box")
    v_box = _mapping_at(contract, "vertical_tail", "design_box")
    wing = _mapping_at(contract, "reference", "wing")
    s_w = _read_number(wing.get("S_w_m2"))
    b_w = _read_number(wing.get("b_w_m"))
    c_w = _read_number(wing.get("cbar_w_m"))
    s_h = _read_number(h_box.get("S_H_m2"))
    l_h = _read_number(h_box.get("l_H_m"))
    s_v = _read_number(v_box.get("S_V_m2"))
    l_v = _read_number(v_box.get("l_V_m"))
    return {
        "horizontal_tail": {
            "S_H_m2": _round_or_none(s_h),
            "span_m": _round_or_none(_read_number(h_box.get("span_m"))),
            "mean_chord_m": _round_or_none(_read_number(h_box.get("mean_chord_m"))),
            "x_le_m": _round_or_none(_read_number(h_box.get("x_le_m"))),
            "x_ac_H_m": _round_or_none(_read_number(h_box.get("x_ac_H_m"))),
            "l_H_m": _round_or_none(l_h),
            "V_H": _round_or_none(
                None if None in (s_h, l_h, s_w, c_w) else float(s_h) * float(l_h) / (float(s_w) * float(c_w))
            ),
        },
        "vertical_tail": {
            "S_V_m2": _round_or_none(s_v),
            "height_or_span_m": _round_or_none(_read_number(v_box.get("height_or_span_m"))),
            "mean_chord_m": _round_or_none(_read_number(v_box.get("mean_chord_m"))),
            "x_le_m": _round_or_none(_read_number(v_box.get("x_le_m"))),
            "x_ac_V_m": _round_or_none(_read_number(v_box.get("x_ac_V_m"))),
            "l_V_m": _round_or_none(l_v),
            "V_V": _round_or_none(
                None if None in (s_v, l_v, s_w, b_w) else float(s_v) * float(l_v) / (float(s_w) * float(b_w))
            ),
        },
    }


def _tail_geometry_totals(contract: Mapping[str, Any]) -> dict[str, float]:
    h = _mapping_at(contract, "horizontal_tail", "design_box")
    v = _mapping_at(contract, "vertical_tail", "design_box")
    return {
        "S_H_m2": float(_read_number(h.get("S_H_m2")) or 0.0),
        "S_V_m2": float(_read_number(v.get("S_V_m2")) or 0.0),
    }


def _render_markdown(summary: Mapping[str, Any]) -> str:
    selected = _mapping_at(summary, "selected_basis")
    rows = list(summary.get("rows") or [])
    lines = [
        "# Tail / CG / Trim / Stability Screening V1",
        "",
        f"Candidate: `{summary.get('candidate_id')}`",
        f"Verdict: `{summary.get('engineering_verdict')}`",
        f"Runner status: `{summary.get('runner_status')}`",
        "",
        "## Screening Contract",
        "",
        f"- CG range: `{_mapping_at(summary, 'screening_assumption_contract').get('cg_range_x_m')}` m",
        "- Moment reference: AVL `Xref` is explicitly set to each row CG.",
        "- Xnp use gate: `Xnp = Xref - Cma/CLa*Cref` must close within tolerance.",
        "- This is screening evidence, not measured CG, tail polar, FEM, or hardware sign-off.",
        "",
        "## Selected Geometry",
        "",
        f"- H-tail: `{_mapping_at(selected, 'geometry', 'horizontal_tail')}`",
        f"- V-tail: `{_mapping_at(selected, 'geometry', 'vertical_tail')}`",
        "",
        "## Margins",
        "",
        f"- Worst static margin: `{selected.get('worst_static_margin')}` MAC",
        f"- Max |delta_H|: `{selected.get('max_abs_delta_H_required_deg')}` deg",
        f"- Worst H-tail deflection reserve: `{selected.get('worst_delta_H_margin_to_limit_deg')}` deg",
        f"- Max |delta_V| at beta screen: `{selected.get('max_abs_delta_V_required_deg')}` deg",
        f"- Worst V-tail deflection reserve: `{selected.get('worst_delta_V_margin_to_limit_deg')}` deg",
        "",
        "## CG Rows",
        "",
        "| CG x m | status | SM | alpha deg | delta_H deg | Cn_beta | delta_V deg | blockers |",
        "|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        longi = _mapping_at(row, "longitudinal_trim")
        direc = _mapping_at(row, "directional")
        lines.append(
            f"| `{row.get('cg_x_m')}` | `{row.get('status')}` | "
            f"`{longi.get('static_margin')}` | `{longi.get('alpha_required_deg')}` | "
            f"`{longi.get('delta_H_required_deg')}` | `{direc.get('C_n_beta')}` | "
            f"`{direc.get('delta_V_required_deg')}` | `{row.get('blockers')}` |"
        )
    lines.extend(
        [
            "",
            "## Tail Drag / Mass Treatment",
            "",
            f"`{summary.get('tail_drag_mass_treatment')}`",
            "",
            "## Mass / CG Clue",
            "",
            f"`{summary.get('mass_cg_clue')}`",
            "",
            "## Engineering Read",
            "",
            "This establishes a bounded screening basis for tail-aware rib / rear-spar",
            "sensitivity only if that next study carries CG as an explicit input range and",
            "charges the screening tail drag/mass penalty. It does not prove the aircraft",
            "is final-design feasible.",
            "",
        ]
    )
    return "\n".join(lines)


def _solve_delta_v_required_deg(
    *,
    cn0: float | None,
    cn_beta: float | None,
    cn_delta_v: float | None,
    beta_screen_deg: float,
) -> float | None:
    if None in (cn0, cn_beta, cn_delta_v) or abs(float(cn_delta_v)) <= 1.0e-12:
        return None
    beta_rad = math.radians(float(beta_screen_deg))
    delta_rad = -(float(cn0) + float(cn_beta) * beta_rad) / float(cn_delta_v)
    return math.degrees(delta_rad)


def _range_margin(value: float | None, bounds: Sequence[float] | None) -> float | None:
    if value is None or bounds is None or len(bounds) != 2:
        return None
    lower, upper = float(bounds[0]), float(bounds[1])
    return min(float(value) - lower, upper - float(value))


def _usable_range(box: Mapping[str, Any]) -> list[float] | None:
    return tail_avl._usable_range(box)


def _mapping_at(root: Any, *keys: str) -> Mapping[str, Any]:
    node = root
    for key in keys:
        if not isinstance(node, Mapping):
            return {}
        node = node.get(key, {})
    return node if isinstance(node, Mapping) else {}


def _mutable_mapping_at(root: dict[str, Any], *keys: str) -> dict[str, Any]:
    node: Any = root
    for key in keys:
        if not isinstance(node, dict):
            raise TypeError(f"Expected mapping at {key}.")
        child = node.setdefault(key, {})
        if not isinstance(child, dict):
            raise TypeError(f"Expected mapping at {key}.")
        node = child
    return node


def _read_number(node: Any) -> float | None:
    if isinstance(node, int | float) and math.isfinite(float(node)):
        return float(node)
    if isinstance(node, Mapping):
        for key in ("value", "nominal"):
            value = node.get(key)
            if isinstance(value, int | float) and math.isfinite(float(value)):
                return float(value)
        raw_range = node.get("range")
        if isinstance(raw_range, list | tuple) and len(raw_range) == 2:
            low, high = raw_range
            if isinstance(low, int | float) and isinstance(high, int | float):
                return 0.5 * (float(low) + float(high))
    return None


def _set_number_node(mapping: dict[str, Any], key: str, value: float) -> None:
    node = mapping.get(key)
    if isinstance(node, dict):
        if "nominal" in node:
            node["nominal"] = float(value)
        elif "value" in node:
            node["value"] = float(value)
        else:
            node["nominal"] = float(value)
        if "range" in node:
            node["range"] = [float(value), float(value)]
        return
    mapping[key] = {"nominal": float(value)}


def _round_or_none(value: Any) -> float | None:
    number = _read_number(value)
    return None if number is None else round(float(number), 6)


def _round_nested(node: Any) -> Any:
    if isinstance(node, float):
        return round(node, 6)
    if isinstance(node, Mapping):
        return {str(key): _round_nested(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_round_nested(value) for value in node]
    return node


def _ratio_abs(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or abs(float(denominator)) <= 1.0e-12:
        return None
    return abs(float(numerator) / float(denominator))


def _min_field(rows: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> float | None:
    values = []
    for row in rows:
        node: Any = row
        for key in keys:
            node = node.get(key, {}) if isinstance(node, Mapping) else {}
        number = _read_number(node)
        if number is not None:
            values.append(number)
    return min(values) if values else None


def _max_abs_field(rows: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> float | None:
    values = []
    for row in rows:
        node: Any = row
        for key in keys:
            node = node.get(key, {}) if isinstance(node, Mapping) else {}
        number = _read_number(node)
        if number is not None:
            values.append(abs(number))
    return max(values) if values else None


def _cruise_value(contract: Mapping[str, Any], field: str) -> float | None:
    return _read_number(_mapping_at(contract, "reference", "mission_cases", "cruise").get(field))


def _token(value: float) -> str:
    return f"{float(value):.3f}".replace("-", "m").replace(".", "p")


def _parse_float_list(raw: str) -> tuple[float, ...]:
    values = tuple(float(part.strip()) for part in raw.split(",") if part.strip())
    if not values:
        raise argparse.ArgumentTypeError("expected at least one comma-separated number")
    return values


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--wing-avl", type=Path, default=DEFAULT_WING_AVL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    parser.add_argument("--cg-values-m", type=_parse_float_list, default=DEFAULT_CG_VALUES_M)
    parser.add_argument("--h-area-multiplier", type=float, default=DEFAULT_SIZING_CASE.h_area_multiplier)
    parser.add_argument("--h-aft-shift-m", type=float, default=DEFAULT_SIZING_CASE.h_aft_shift_m)
    parser.add_argument("--v-area-multiplier", type=float, default=DEFAULT_SIZING_CASE.v_area_multiplier)
    parser.add_argument("--v-aft-shift-m", type=float, default=DEFAULT_SIZING_CASE.v_aft_shift_m)
    parser.add_argument("--small-delta-deg", type=float, default=2.0)
    parser.add_argument("--beta-screen-deg", type=float, default=12.0)
    parser.add_argument("--static-margin-min", type=float, default=0.05)
    parser.add_argument("--xnp-tolerance-m", type=float, default=1.0e-3)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--avl-binary", default=None)
    parser.add_argument("--no-run-avl", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8")) or {}
    if not isinstance(contract, Mapping):
        raise TypeError("Tail contract YAML must contain a mapping.")
    sizing_case = TailCgTrimSizingCase(
        name=(
            f"h{_token(args.h_area_multiplier)}_xaft{_token(args.h_aft_shift_m)}_"
            f"v{_token(args.v_area_multiplier)}_xaft{_token(args.v_aft_shift_m)}"
        ),
        h_area_multiplier=float(args.h_area_multiplier),
        h_aft_shift_m=float(args.h_aft_shift_m),
        v_area_multiplier=float(args.v_area_multiplier),
        v_aft_shift_m=float(args.v_aft_shift_m),
    )
    summary = run_tail_cg_trim_stability_screening(
        contract=contract,
        wing_avl_path=args.wing_avl,
        output_dir=args.output_dir,
        report_json_path=args.report_json,
        report_md_path=args.report_md,
        sizing_case=sizing_case,
        cg_values_m=args.cg_values_m,
        run_avl=not args.no_run_avl,
        avl_binary=args.avl_binary,
        small_delta_deg=float(args.small_delta_deg),
        timeout_s=float(args.timeout_s),
        beta_screen_deg=float(args.beta_screen_deg),
        static_margin_min=float(args.static_margin_min),
        xnp_tolerance_m=float(args.xnp_tolerance_m),
    )
    print(f"wrote {args.report_json}")
    print(f"wrote {args.report_md}")
    print(f"verdict: {summary['engineering_verdict']}")


if __name__ == "__main__":
    main()
