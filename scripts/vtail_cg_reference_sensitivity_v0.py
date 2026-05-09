#!/usr/bin/env python3
"""Run bounded current-pathfinder V-tail and CG/reference sensitivity v0."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import copy
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.aero.avl_exporter import stage_avl_airfoil_files  # noqa: E402
from hpa_mdo.aero.avl_runner import run_avl_derivatives  # noqa: E402
from scripts import full_aircraft_tail_avl_audit_v0 as tail_avl  # noqa: E402


DEFAULT_CONTRACT = REPO_ROOT / "configs" / "current_pathfinder_tail_contract_v0.yaml"
DEFAULT_WING_AVL = tail_avl.DEFAULT_WING_AVL
DEFAULT_FULL_AIRCRAFT_AUDIT_JSON = (
    REPO_ROOT / "docs" / "reports" / "2026-05-09_full_aircraft_tail_avl_audit_v0.json"
)
DEFAULT_MASS_CONFIG = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "current_avl_compromise_conservative_closed_z_boundary"
    / "smooth_tier2_canonical_config.yaml"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "current_pathfinder_vtail_sensitivity_v0"
DEFAULT_REPORT_JSON = (
    REPO_ROOT / "docs" / "reports" / "2026-05-09_vtail_cg_reference_sensitivity_v0.json"
)
DEFAULT_REPORT_MD = (
    REPO_ROOT / "docs" / "reports" / "2026-05-09_vtail_cg_reference_sensitivity_v0.md"
)
DEFAULT_AREA_MULTIPLIERS = (1.0, 1.5, 2.0, 2.5, 3.0)
DEFAULT_AFT_SHIFTS_M = (0.0, 0.5, 1.0)


@dataclass(frozen=True)
class VtailSizingCase:
    """A bounded vertical-tail sizing/position variant."""

    name: str
    area_multiplier: float
    aft_shift_m: float
    z_shift_m: float = 0.0


def default_sensitivity_cases(
    *,
    area_multipliers: Sequence[float] = DEFAULT_AREA_MULTIPLIERS,
    aft_shifts_m: Sequence[float] = DEFAULT_AFT_SHIFTS_M,
) -> tuple[VtailSizingCase, ...]:
    """Return the low-dimensional V-tail box requested for v0."""

    cases: list[VtailSizingCase] = []
    for area_multiplier in area_multipliers:
        for aft_shift_m in aft_shifts_m:
            cases.append(
                VtailSizingCase(
                    name=(
                        f"sv{_token(area_multiplier)}"
                        f"_xaft{_token(aft_shift_m)}"
                        "_z0p0"
                    ),
                    area_multiplier=float(area_multiplier),
                    aft_shift_m=float(aft_shift_m),
                    z_shift_m=0.0,
                )
            )
    return tuple(cases)


def build_vtail_contract_variant(
    contract: Mapping[str, Any],
    case: VtailSizingCase,
) -> tuple[dict[str, Any], list[str]]:
    """Scale V-tail area by chord and optionally move the tail aft.

    The existing all-moving AVL generator uses the contract's V-tail geometry
    fields directly. This function keeps height fixed, scales area through mean
    chord, and updates x_ac/l_V consistently with the AVL Xref reference point.
    """

    variant = copy.deepcopy(dict(contract))
    vbox = _mutable_mapping_at(variant, "vertical_tail", "design_box")
    wing = _mapping_at(variant, "reference", "wing")

    base_area = _read_number(vbox.get("S_V_m2"))
    base_height = _read_number(vbox.get("height_or_span_m"))
    base_chord = _read_number(vbox.get("mean_chord_m"))
    base_x_le = _read_number(vbox.get("x_le_m"))
    base_z_ac = _read_number(vbox.get("z_ac_V_m")) or 0.0
    x_ref = _read_number(wing.get("x_ref_avl_m"))
    if None in (base_area, base_height, base_chord, base_x_le, x_ref):
        raise ValueError("V-tail contract variant requires S_V, height, chord, x_le, and Xref.")

    area = float(base_area) * float(case.area_multiplier)
    height = float(base_height)
    chord = area / height
    x_le = float(base_x_le) + float(case.aft_shift_m)
    z_ac = float(base_z_ac) + float(case.z_shift_m)
    x_ac = x_le + 0.25 * chord
    tail_arm = x_ac - float(x_ref)

    _set_number_node(vbox, "S_V_m2", area)
    _set_number_node(vbox, "mean_chord_m", chord)
    _set_number_node(vbox, "x_le_m", x_le)
    _set_number_node(vbox, "x_ac_V_m", x_ac)
    _set_number_node(vbox, "z_ac_V_m", z_ac)
    _set_number_node(vbox, "l_V_m", tail_arm)

    warnings = _geometry_warnings(
        case=case,
        base_area=float(base_area),
        area=area,
        base_x_le=float(base_x_le),
        x_le=x_le,
        chord=chord,
        height=height,
        tail_arm=tail_arm,
    )
    return variant, warnings


def vertical_tail_volume(contract: Mapping[str, Any]) -> float | None:
    """Compute V_V = S_V l_V / (S_W b_W)."""

    wing = _mapping_at(contract, "reference", "wing")
    vbox = _mapping_at(contract, "vertical_tail", "design_box")
    area = _read_number(vbox.get("S_V_m2"))
    arm = _read_number(vbox.get("l_V_m"))
    s_w = _read_number(wing.get("S_w_m2"))
    b_w = _read_number(wing.get("b_w_m"))
    if None in (area, arm, s_w, b_w):
        return None
    if abs(float(s_w)) <= 1.0e-12 or abs(float(b_w)) <= 1.0e-12:
        return None
    return float(area) * float(arm) / (float(s_w) * float(b_w))


def audit_cg_reference_contract(
    contract: Mapping[str, Any],
    *,
    full_aircraft_audit: Mapping[str, Any] | None = None,
    candidate_mass_config: Mapping[str, Any] | None = None,
    candidate_mass_config_tracked: bool = False,
) -> dict[str, Any]:
    """Classify longitudinal references without promoting unverified proxies."""

    full_aircraft_audit = full_aircraft_audit or {}
    candidate_mass_config = candidate_mass_config or {}
    wing = _mapping_at(contract, "reference", "wing")
    cg_range = _mapping_at(contract, "reference", "cg_range_x_m")
    raw_neutral = _mapping_at(
        full_aircraft_audit,
        "case_results",
        "neutral",
        "raw_derivatives",
    )

    xref_value = _first_number(_read_number(wing.get("x_ref_avl_m")), raw_neutral.get("Xref"))
    xnp_value = _read_number(raw_neutral.get("Xnp"))
    x_ac_value = _read_number(wing.get("x_ac_w_m"))
    cg_value = _read_number(cg_range)
    mass_budget = _mapping_at(candidate_mass_config, "mass_budget")
    pilot = _mapping_at(mass_budget, "pilot")

    x_ac_status = "available_explicit_artifact" if x_ac_value is not None else "blocking_missing"
    x_cg_status = "available_explicit_range" if cg_value is not None else "blocking_missing"
    if mass_budget:
        if candidate_mass_config_tracked and pilot.get("source") != "estimated":
            mass_status = "mass_manifest_present_but_not_promoted_as_cg_range"
        else:
            mass_status = "estimated_or_untracked_not_promoted"
    else:
        mass_status = "not_found"

    blocked_fields: list[str] = []
    if x_ac_status == "blocking_missing":
        blocked_fields.append("x_ac_w")
    if x_cg_status == "blocking_missing":
        blocked_fields.append("x_cg")

    return {
        "schema_version": "cg_reference_contract_audit_v0",
        "overall_status": (
            "blocked_by_missing_cg_or_reference_moment"
            if blocked_fields
            else "reference_contract_available_if_moment_convention_verified"
        ),
        "Xref": {
            "value_m": _round_or_none(xref_value),
            "status": "reference_only_not_aerodynamic_center",
            "source": _source_or_note(wing.get("x_ref_avl_m"), "AVL coefficient reference point"),
            "engineering_read": "AVL Xref is a coefficient reference, not x_ac_w or x_cg.",
        },
        "Xnp": {
            "value_m": _round_or_none(xnp_value),
            "status": (
                "candidate_only_convention_not_verified"
                if xnp_value is not None
                else "not_found"
            ),
            "engineering_read": (
                "Neutral point candidate only. Use for static margin only after parser, "
                "axis, reference point, and sign convention are verified."
            ),
        },
        "x_ac_w": {
            "value_m": _round_or_none(x_ac_value),
            "status": x_ac_status,
            "engineering_read": "Wing aerodynamic center remains missing unless explicit artifact exists.",
        },
        "x_cg": {
            "value_m": _round_or_none(cg_value),
            "status": x_cg_status,
            "engineering_read": "Aircraft CG/range remains missing unless explicit manifest exists.",
        },
        "moment_reference": {
            "status": "reference_point_available_not_cg" if xref_value is not None else "missing",
            "engineering_read": (
                "Static margin cannot be claimed unless coefficients are referenced about "
                "CG, or x_np and x_cg are both available with verified convention."
            ),
        },
        "mass_manifest": {
            "status": mass_status,
            "tracked_by_git": bool(candidate_mass_config_tracked),
            "pilot_entry": {
                "m_kg": _round_or_none(_read_number(pilot.get("m_kg"))),
                "xyz_m": pilot.get("xyz_m") if isinstance(pilot.get("xyz_m"), list) else None,
                "source": pilot.get("source"),
            },
            "engineering_read": (
                "Estimated or ignored-output mass entries are useful clues, but they are not "
                "a promoted CG range or moment reference contract."
            ),
        },
        "blocked_fields": blocked_fields,
        "required_relationships": {
            "static_margin_from_np": "SM ~= (x_np - x_cg) / cbar_W",
            "static_margin_from_derivatives": (
                "SM ~= -C_m_alpha / C_L_alpha only if coefficients are referenced about "
                "CG and sign convention is verified."
            ),
        },
    }


def summarize_vtail_case(
    *,
    case: VtailSizingCase,
    variant_contract: Mapping[str, Any],
    case_results: Mapping[str, Mapping[str, Any]],
    small_delta_deg: float,
    run_status: str,
    geometry_warnings: Sequence[str],
) -> dict[str, Any]:
    """Return one bounded V-tail case row for JSON/Markdown reporting."""

    neutral = _mapping_at(case_results.get("neutral", {}), "derivatives")
    cn_beta = _read_number(neutral.get("Cn_beta"))
    cl_beta = _read_number(neutral.get("Cl_beta"))
    cn_delta_v = _finite_difference(
        case_results,
        minus_key="v_delta_minus_small",
        plus_key="v_delta_plus_small",
        coefficient="Cn",
        delta_deg=small_delta_deg,
    )
    cl_delta_v = _finite_difference(
        case_results,
        minus_key="v_delta_minus_small",
        plus_key="v_delta_plus_small",
        coefficient="Cl",
        delta_deg=small_delta_deg,
    )
    vbox = _mapping_at(variant_contract, "vertical_tail", "design_box")
    signs = _derivative_signs(cn_beta=cn_beta, cn_delta_v=cn_delta_v, cl_beta=cl_beta)
    coupling = _yaw_roll_coupling_warning(
        cn_beta=cn_beta,
        cl_beta=cl_beta,
        cn_delta_v=cn_delta_v,
        cl_delta_v=cl_delta_v,
    )
    warnings = list(geometry_warnings)
    if cn_beta is not None and abs(cn_beta) < 0.005:
        warnings.append("very_small_C_n_beta_return_to_tail_sizing")
    if cn_delta_v is not None and abs(cn_delta_v) < 0.005:
        warnings.append("very_small_C_n_deltaV_return_to_tail_sizing")
    v_v = vertical_tail_volume(variant_contract)
    if v_v is not None and v_v <= 0.015:
        warnings.append("low_V_V_directional_authority_risk")

    return {
        "case": case.name,
        "area_multiplier": float(case.area_multiplier),
        "aft_shift_m": float(case.aft_shift_m),
        "z_shift_m": float(case.z_shift_m),
        "S_V_m2": _round_or_none(_read_number(vbox.get("S_V_m2"))),
        "x_ac_V_m": _round_or_none(_read_number(vbox.get("x_ac_V_m"))),
        "z_ac_V_m": _round_or_none(_read_number(vbox.get("z_ac_V_m"))),
        "l_V_m": _round_or_none(_read_number(vbox.get("l_V_m"))),
        "V_V": _round_or_none(v_v),
        "C_n_beta": _round_or_none(cn_beta),
        "C_n_deltaV": _round_or_none(cn_delta_v),
        "C_l_beta": _round_or_none(cl_beta),
        "C_l_deltaV": _round_or_none(cl_delta_v),
        "yaw_roll_coupling_warning": coupling,
        "deck_run_status": run_status,
        "derivative_signs": signs,
        "geometry_warnings": list(geometry_warnings),
        "warnings": sorted(set(warnings)),
        "directional_box_candidate": _directional_box_candidate(
            run_status=run_status,
            cn_beta=cn_beta,
            cn_delta_v=cn_delta_v,
            geometry_warnings=geometry_warnings,
        ),
        "authority_equation_status": {
            "status": "not_solved_without_beta_case" if run_status == "completed" else run_status,
            "equation": "exists delta_V such that C_n(beta, delta_V) = 0",
            "reason": "No promoted yaw/turn beta case is available.",
        },
    }


def run_vtail_cg_reference_sensitivity_v0(
    *,
    contract: Mapping[str, Any],
    wing_avl_path: Path,
    output_dir: Path,
    report_json_path: Path,
    report_md_path: Path,
    cases: Sequence[VtailSizingCase] | None = None,
    run_avl: bool = True,
    avl_binary: str | None = None,
    small_delta_deg: float = 2.0,
    timeout_s: float = 120.0,
    full_aircraft_audit: Mapping[str, Any] | None = None,
    candidate_mass_config: Mapping[str, Any] | None = None,
    candidate_mass_config_tracked: bool = False,
) -> dict[str, Any]:
    """Write bounded V-tail sensitivity decks plus JSON/Markdown reports."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if cases is None:
        cases = default_sensitivity_cases()

    deck_records: list[dict[str, Any]] = []
    sensitivity_rows: list[dict[str, Any]] = []
    global_runner_status = "completed"
    if not run_avl:
        global_runner_status = "runner_disabled"

    for case in cases:
        variant, geometry_warnings = build_vtail_contract_variant(contract, case)
        case_dir = output_dir / case.name
        case_dir.mkdir(parents=True, exist_ok=True)
        case_results: dict[str, dict[str, Any]] = {}
        case_run_status = "completed" if run_avl else "runner_disabled"

        for sweep_name, delta_v in _vertical_sweep_cases(small_delta_deg):
            deck_dir = case_dir / sweep_name
            deck_dir.mkdir(parents=True, exist_ok=True)
            deck_path = deck_dir / f"{case.name}_{sweep_name}.avl"
            deck_text, deck_manifest = tail_avl.build_full_aircraft_deck_text(
                wing_avl_path=Path(wing_avl_path),
                contract=variant,
                delta_h_deg=0.0,
                delta_v_deg=delta_v,
            )
            deck_path.write_text(deck_text, encoding="utf-8")
            staged_airfoils = stage_avl_airfoil_files(deck_path)
            deck_manifest.update(
                {
                    "sensitivity_case": case.__dict__,
                    "deck_path": str(deck_path.resolve()),
                    "geometry_warnings": list(geometry_warnings),
                    "staged_airfoil_files": [
                        str(path.resolve()) for path in staged_airfoils
                    ],
                }
            )
            deck_manifest_path = deck_dir / f"{case.name}_{sweep_name}_deck_manifest.json"
            deck_manifest_path.write_text(
                json.dumps(deck_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            deck_record = {
                "case": case.name,
                "sweep": sweep_name,
                "delta_H_deg": 0.0,
                "delta_V_deg": delta_v,
                "deck_path": str(deck_path.resolve()),
                "deck_manifest_path": str(deck_manifest_path.resolve()),
            }
            deck_records.append(deck_record)

            if not run_avl:
                continue
            avl_result = run_avl_derivatives(
                avl_path=deck_path,
                out_dir=deck_dir,
                avl_binary=avl_binary,
                alpha_deg=0.0,
                velocity=_cruise_value(contract, "speed_mps"),
                density=_cruise_value(contract, "rho_kgpm3"),
                timeout_s=timeout_s,
                stem=f"{case.name}_{sweep_name}",
            )
            deck_record["avl_run"] = avl_result.as_dict()
            if avl_result.error or avl_result.st_path is None:
                case_run_status = avl_result.error or "st_file_not_produced"
                global_runner_status = case_run_status
                case_results[sweep_name] = {"run_status": case_run_status}
                continue
            case_results[sweep_name] = tail_avl._parse_case_result(avl_result.st_path)

        if case_run_status == "avl_binary_not_found":
            case_run_status = "runner_missing"
        row = summarize_vtail_case(
            case=case,
            variant_contract=variant,
            case_results=case_results,
            small_delta_deg=small_delta_deg,
            run_status=case_run_status,
            geometry_warnings=geometry_warnings,
        )
        sensitivity_rows.append(row)

    if global_runner_status == "avl_binary_not_found":
        global_runner_status = "runner_missing"

    reference_audit = audit_cg_reference_contract(
        contract,
        full_aircraft_audit=full_aircraft_audit,
        candidate_mass_config=candidate_mass_config,
        candidate_mass_config_tracked=candidate_mass_config_tracked,
    )
    manifest = {
        "schema_version": "vtail_cg_reference_sensitivity_manifest_v0",
        "output_dir": str(output_dir.resolve()),
        "deck_count": len(deck_records),
        "cases": deck_records,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = {
        "schema_version": "vtail_cg_reference_sensitivity_v0",
        "candidate_id": str(_mapping_at(contract, "pathfinder").get("candidate_id", "")),
        "contract_id": str(contract.get("contract_id", "")),
        "runner_status": global_runner_status,
        "artifact_manifest": manifest,
        "sensitivity_grid": {
            "S_V_multipliers": sorted({row["area_multiplier"] for row in sensitivity_rows}),
            "aft_shifts_m": sorted({row["aft_shift_m"] for row in sensitivity_rows}),
            "z_shifts_m": sorted({row["z_shift_m"] for row in sensitivity_rows}),
            "small_delta_deg": float(small_delta_deg),
            "excluded_scopes": [
                "rib_or_rear_spar_sensitivity",
                "ASWing_lite",
                "FEM",
                "tail_airfoil_NSGA2",
            ],
        },
        "sensitivity_cases": sensitivity_rows,
        "best_directional_box_candidates": _best_directional_candidates(sensitivity_rows),
        "cg_reference_audit": reference_audit,
        "engineering_verdict": _engineering_verdict(
            runner_status=global_runner_status,
            rows=sensitivity_rows,
            reference_audit=reference_audit,
        ),
        "claim_boundary": (
            "This is bounded V-tail sizing/position/authority sensitivity plus CG/reference "
            "audit. It is not a rib sensitivity, ASWing run, FEM sign-off, tail airfoil "
            "optimization, or aircraft feasibility pass."
        ),
        "required_math": {
            "V_V": "V_V = S_V l_V / (S_W b_W)",
            "C_n_deltaV": (
                "C_n_deltaV ~= [C_n(+Delta delta_V) - C_n(-Delta delta_V)] "
                "/ (2 Delta delta_V)"
            ),
            "yaw_roll": "C_l,V ~ Y_V z_V / (q S_W b_W)",
            "SM_xnp": "SM ~= (x_np - x_cg) / cbar_W",
            "SM_derivatives": (
                "SM ~= -C_m_alpha / C_L_alpha only if coefficients are referenced "
                "about CG and sign convention is verified."
            ),
        },
    }
    report_json_path.parent.mkdir(parents=True, exist_ok=True)
    report_json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_md_path.parent.mkdir(parents=True, exist_ok=True)
    report_md_path.write_text(_render_markdown_report(summary), encoding="utf-8")
    return summary


def _vertical_sweep_cases(small_delta_deg: float) -> tuple[tuple[str, float], ...]:
    return (
        ("neutral", 0.0),
        ("v_delta_minus_small", -float(small_delta_deg)),
        ("v_delta_plus_small", float(small_delta_deg)),
    )


def _geometry_warnings(
    *,
    case: VtailSizingCase,
    base_area: float,
    area: float,
    base_x_le: float,
    x_le: float,
    chord: float,
    height: float,
    tail_arm: float,
) -> list[str]:
    warnings: list[str] = []
    if area <= 0.0 or chord <= 0.0 or height <= 0.0:
        warnings.append("invalid_nonpositive_vtail_geometry")
    if tail_arm <= 0.0:
        warnings.append("invalid_nonpositive_vtail_arm")
    if case.area_multiplier > 3.0:
        warnings.append("area_multiplier_outside_v0_bound")
    if case.area_multiplier >= 3.0:
        warnings.append("large_vtail_area_screening_only")
    if abs(case.aft_shift_m) > 1.0:
        warnings.append("aft_shift_outside_v0_bound")
    if x_le < base_x_le - 1.0e-9:
        warnings.append("forward_vtail_shift_not_in_v0_box")
    aspect_ratio = height * height / area if area > 0.0 else math.inf
    if aspect_ratio < 1.0:
        warnings.append("very_low_vertical_tail_aspect_ratio")
    if area > 3.0 * base_area + 1.0e-9:
        warnings.append("area_exceeds_requested_v0_box")
    return warnings


def _derivative_signs(
    *,
    cn_beta: float | None,
    cn_delta_v: float | None,
    cl_beta: float | None,
) -> dict[str, dict[str, Any]]:
    return {
        "C_n_beta": {
            "physically_plausible": cn_beta is not None and cn_beta > 0.0,
            "expected": "positive directional stability derivative in AVL convention",
            "status": _sign_status(cn_beta, positive=True),
        },
        "C_n_deltaV": {
            "physically_plausible": cn_delta_v is not None and abs(cn_delta_v) > 1.0e-6,
            "expected": "finite all-moving V-tail yaw control derivative",
            "status": "finite_control_authority" if cn_delta_v is not None else "missing",
        },
        "C_l_beta": {
            "physically_plausible": cl_beta is not None and math.isfinite(float(cl_beta)),
            "expected": "finite roll-with-sideslip derivative; sign is configuration-dependent",
            "status": "finite_configuration_dependent" if cl_beta is not None else "missing",
        },
    }


def _sign_status(value: float | None, *, positive: bool) -> str:
    if value is None:
        return "missing"
    if positive:
        return "expected_positive" if value > 0.0 else "unexpected_nonpositive"
    return "finite"


def _yaw_roll_coupling_warning(
    *,
    cn_beta: float | None,
    cl_beta: float | None,
    cn_delta_v: float | None,
    cl_delta_v: float | None,
) -> dict[str, Any]:
    beta_ratio = _ratio_abs(cl_beta, cn_beta)
    control_ratio = _ratio_abs(cl_delta_v, cn_delta_v)
    notes: list[str] = []
    if beta_ratio is not None and beta_ratio > 20.0:
        notes.append("roll_sideslip_derivative_large_relative_to_yaw_stability")
    if control_ratio is not None and control_ratio > 0.25:
        notes.append("roll_control_derivative_not_negligible_relative_to_yaw_control")
    return {
        "formula": "C_l,V ~ Y_V z_V / (q S_W b_W)",
        "status": "warning_not_limit_checked",
        "abs_C_l_beta_over_C_n_beta": _round_or_none(beta_ratio),
        "abs_C_l_deltaV_over_C_n_deltaV": _round_or_none(control_ratio),
        "notes": notes,
    }


def _directional_box_candidate(
    *,
    run_status: str,
    cn_beta: float | None,
    cn_delta_v: float | None,
    geometry_warnings: Sequence[str],
) -> bool:
    blocking_geometry = {
        "invalid_nonpositive_vtail_geometry",
        "invalid_nonpositive_vtail_arm",
        "area_multiplier_outside_v0_bound",
        "aft_shift_outside_v0_bound",
        "area_exceeds_requested_v0_box",
    }
    return (
        run_status == "completed"
        and cn_beta is not None
        and cn_beta > 0.005
        and cn_delta_v is not None
        and abs(cn_delta_v) > 0.005
        and not blocking_geometry.intersection(geometry_warnings)
    )


def _best_directional_candidates(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    candidates = [row for row in rows if row.get("directional_box_candidate")]
    ranked = sorted(
        candidates,
        key=lambda row: (
            float(row.get("C_n_beta") or -math.inf),
            float(row.get("C_n_deltaV") or -math.inf),
        ),
        reverse=True,
    )
    keys = (
        "case",
        "area_multiplier",
        "aft_shift_m",
        "V_V",
        "C_n_beta",
        "C_n_deltaV",
        "C_l_beta",
        "C_l_deltaV",
        "warnings",
    )
    return [{key: row.get(key) for key in keys} for row in ranked[:5]]


def _engineering_verdict(
    *,
    runner_status: str,
    rows: Sequence[Mapping[str, Any]],
    reference_audit: Mapping[str, Any],
) -> str:
    if runner_status != "completed":
        return "blocked_by_geometry_or_avl_generation"
    if any(_has_blocking_geometry(row) for row in rows):
        return "blocked_by_geometry_or_avl_generation"
    if reference_audit.get("overall_status") == "blocked_by_missing_cg_or_reference_moment":
        return "blocked_by_missing_cg_or_reference_moment"
    if any(row.get("directional_box_candidate") for row in rows):
        return "vtail_sizing_box_found_for_next_tail_aware_rib_sensitivity"
    return "blocked_by_vtail_size_or_authority"


def _has_blocking_geometry(row: Mapping[str, Any]) -> bool:
    blocking = {
        "invalid_nonpositive_vtail_geometry",
        "invalid_nonpositive_vtail_arm",
        "area_multiplier_outside_v0_bound",
        "aft_shift_outside_v0_bound",
        "area_exceeds_requested_v0_box",
    }
    warnings = row.get("geometry_warnings")
    return isinstance(warnings, list) and bool(blocking.intersection(warnings))


def _render_markdown_report(summary: Mapping[str, Any]) -> str:
    rows = list(summary.get("sensitivity_cases") or [])
    ref = _mapping_at(summary, "cg_reference_audit")
    best = list(summary.get("best_directional_box_candidates") or [])
    lines = [
        "# V-tail / CG Reference Sizing Sensitivity V0",
        "",
        f"Candidate: `{summary.get('candidate_id')}`",
        f"Runner status: `{summary.get('runner_status')}`",
        f"Engineering verdict: `{summary.get('engineering_verdict')}`",
        "",
        "## Scope",
        "",
        "This is a bounded current-pathfinder V-tail sizing / aft-position / authority",
        "sensitivity plus a CG / x_ac reference audit. It deliberately does not run rib",
        "or rear-spar sensitivity, ASWing-lite, FEM, or tail-airfoil NSGA2.",
        "",
        "## Required Math",
        "",
        "```text",
        "V_V = S_V l_V / (S_W b_W)",
        "C_n_beta > C_n_beta_min",
        "exists delta_V such that C_n(beta, delta_V) = 0",
        "C_n_deltaV ~= [C_n(+Delta delta_V) - C_n(-Delta delta_V)] / (2 Delta delta_V)",
        "C_l,V ~ Y_V z_V / (q S_W b_W)",
        "SM ~= (x_np - x_cg) / cbar_W",
        "SM ~= -C_m_alpha / C_L_alpha only if referenced about CG and convention verified",
        "```",
        "",
        "## Sensitivity Grid",
        "",
        f"- Output dir: `{summary['artifact_manifest']['output_dir']}`",
        f"- Deck count: `{summary['artifact_manifest']['deck_count']}`",
        f"- S_V multipliers: `{summary['sensitivity_grid']['S_V_multipliers']}`",
        f"- Aft shifts m: `{summary['sensitivity_grid']['aft_shifts_m']}`",
        f"- z shifts m: `{summary['sensitivity_grid']['z_shifts_m']}`",
        "",
        "## Case Summary",
        "",
        (
            "| case | V_V | C_n_beta | C_n_deltaV | C_l_beta | C_l_deltaV | "
            "signs | yaw-roll | status | warnings |"
        ),
        "|---|---:|---:|---:|---:|---:|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| "
            f"`{row.get('case')}` | "
            f"{_md_num(row.get('V_V'))} | "
            f"{_md_num(row.get('C_n_beta'))} | "
            f"{_md_num(row.get('C_n_deltaV'))} | "
            f"{_md_num(row.get('C_l_beta'))} | "
            f"{_md_num(row.get('C_l_deltaV'))} | "
            f"`{_sign_summary(row)}` | "
            f"`{_yaw_roll_summary(row)}` | "
            f"`{row.get('deck_run_status')}` | "
            f"`{row.get('warnings')}` |"
        )
    lines.extend(
        [
            "",
            "## Directional Box Read",
            "",
        ]
    )
    if best:
        lines.append(
            "Some bounded variants have screening-level positive C_n_beta and finite "
            "C_n_deltaV, but this is not a pass/fail claim because no promoted "
            "C_n_beta_min, beta case, or yaw-roll coupling limit exists."
        )
        for row in best:
            lines.append(
                f"- `{row.get('case')}`: V_V=`{row.get('V_V')}`, "
                f"C_n_beta=`{row.get('C_n_beta')}`, C_n_deltaV=`{row.get('C_n_deltaV')}`"
            )
    else:
        lines.append(
            "No bounded variant cleared the v0 directional screening heuristic with "
            "available derivatives."
        )
    lines.extend(
        [
            "",
            "## CG / x_ac Reference Audit",
            "",
            f"- Overall: `{ref.get('overall_status')}`",
            f"- Xref: `{ref.get('Xref')}`",
            f"- Xnp: `{ref.get('Xnp')}`",
            f"- x_ac_w: `{ref.get('x_ac_w')}`",
            f"- x_cg: `{ref.get('x_cg')}`",
            f"- moment reference: `{ref.get('moment_reference')}`",
            f"- mass manifest: `{ref.get('mass_manifest')}`",
            "",
            "## Engineering Read",
            "",
            "The V-tail sensitivity is useful for seeing whether the current low V_V can be",
            "moved in the right direction by bounded area/arm changes. Static margin and",
            "longitudinal trim remain blocked until CG range, wing aerodynamic center or",
            "verified neutral point convention, and moment reference are promoted. Passing",
            "these script checks is not tailboom, pivot, hardware, manufacturing, or flight",
            "sign-off.",
            "",
        ]
    )
    return "\n".join(lines)


def _finite_difference(
    case_results: Mapping[str, Mapping[str, Any]],
    *,
    minus_key: str,
    plus_key: str,
    coefficient: str,
    delta_deg: float,
) -> float | None:
    minus = _read_number(_mapping_at(case_results.get(minus_key, {}), "coefficients").get(coefficient))
    plus = _read_number(_mapping_at(case_results.get(plus_key, {}), "coefficients").get(coefficient))
    if minus is None or plus is None:
        return None
    delta_rad = math.radians(float(delta_deg))
    if abs(delta_rad) <= 1.0e-12:
        return None
    return (float(plus) - float(minus)) / (2.0 * delta_rad)


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
            raise TypeError(f"Expected mapping at {key}")
        child = node.setdefault(key, {})
        if not isinstance(child, dict):
            raise TypeError(f"Expected mapping at {key}")
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


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _read_number(value)
        if number is not None:
            return number
    return None


def _source_or_note(node: Any, fallback: str) -> str:
    if isinstance(node, Mapping) and node.get("source"):
        return str(node["source"])
    return fallback


def _ratio_abs(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or abs(float(denominator)) <= 1.0e-12:
        return None
    return abs(float(numerator) / float(denominator))


def _cruise_value(contract: Mapping[str, Any], field: str) -> float | None:
    return _read_number(_mapping_at(contract, "reference", "mission_cases", "cruise").get(field))


def _token(value: float) -> str:
    return f"{float(value):.1f}".replace("-", "m").replace(".", "p")


def _md_num(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, int | float):
        return f"`{float(value):.6g}`"
    return f"`{value}`"


def _sign_summary(row: Mapping[str, Any]) -> str:
    signs = _mapping_at(row, "derivative_signs")
    cnb = _mapping_at(signs, "C_n_beta").get("status")
    cnd = _mapping_at(signs, "C_n_deltaV").get("status")
    return f"Cnb={cnb}; CndV={cnd}"


def _yaw_roll_summary(row: Mapping[str, Any]) -> str:
    yaw_roll = _mapping_at(row, "yaw_roll_coupling_warning")
    beta_ratio = yaw_roll.get("abs_C_l_beta_over_C_n_beta")
    control_ratio = yaw_roll.get("abs_C_l_deltaV_over_C_n_deltaV")
    notes = yaw_roll.get("notes")
    return f"Clb/Cnb={beta_ratio}; ClDV/CnDV={control_ratio}; notes={notes}"


def _load_json_if_present(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _load_yaml_if_present(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return loaded if isinstance(loaded, dict) else {}


def _is_git_tracked(path: Path) -> bool:
    try:
        relative = path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        return False
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(relative)],
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


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
    parser.add_argument("--full-aircraft-audit-json", type=Path, default=DEFAULT_FULL_AIRCRAFT_AUDIT_JSON)
    parser.add_argument("--candidate-mass-config", type=Path, default=DEFAULT_MASS_CONFIG)
    parser.add_argument("--area-multipliers", type=_parse_float_list, default=DEFAULT_AREA_MULTIPLIERS)
    parser.add_argument("--aft-shifts-m", type=_parse_float_list, default=DEFAULT_AFT_SHIFTS_M)
    parser.add_argument("--small-delta-deg", type=float, default=2.0)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--avl-binary", default=None)
    parser.add_argument("--no-run-avl", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8")) or {}
    if not isinstance(contract, Mapping):
        raise TypeError("Tail contract YAML must contain a mapping.")
    cases = default_sensitivity_cases(
        area_multipliers=args.area_multipliers,
        aft_shifts_m=args.aft_shifts_m,
    )
    summary = run_vtail_cg_reference_sensitivity_v0(
        contract=contract,
        wing_avl_path=args.wing_avl,
        output_dir=args.output_dir,
        report_json_path=args.report_json,
        report_md_path=args.report_md,
        cases=cases,
        run_avl=not args.no_run_avl,
        avl_binary=args.avl_binary,
        small_delta_deg=float(args.small_delta_deg),
        timeout_s=float(args.timeout_s),
        full_aircraft_audit=_load_json_if_present(args.full_aircraft_audit_json),
        candidate_mass_config=_load_yaml_if_present(args.candidate_mass_config),
        candidate_mass_config_tracked=_is_git_tracked(args.candidate_mass_config),
    )
    print(f"wrote {args.report_json}")
    print(f"wrote {args.report_md}")
    print(f"verdict: {summary['engineering_verdict']}")


if __name__ == "__main__":
    main()
