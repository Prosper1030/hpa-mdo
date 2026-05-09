#!/usr/bin/env python3
"""Build the current pathfinder all-moving full-aircraft AVL audit v0."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

import yaml

from hpa_mdo.aero.avl_exporter import stage_avl_airfoil_files
from hpa_mdo.aero.avl_runner import run_avl_derivatives
from hpa_mdo.aero.avl_stability_parser import parse_st_file
from hpa_mdo.core.constants import G_STANDARD


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = REPO_ROOT / "configs" / "current_pathfinder_tail_contract_v0.yaml"
DEFAULT_WING_AVL = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "final_candidate_package"
    / "geometry_exports"
    / "avl_parity"
    / "current_avl_compromise_conservative_closed"
    / "current_avl_compromise_conservative_closed.avl"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "current_pathfinder_tail_avl_audit_v0"
DEFAULT_REPORT_JSON = (
    REPO_ROOT / "docs" / "reports" / "2026-05-09_full_aircraft_tail_avl_audit_v0.json"
)
DEFAULT_REPORT_MD = (
    REPO_ROOT / "docs" / "reports" / "2026-05-09_full_aircraft_tail_avl_audit_v0.md"
)


@dataclass(frozen=True)
class AvlHeader:
    title: str
    mach: float
    sref: float
    cref: float
    bref: float
    xref: float
    yref: float
    zref: float
    cdp: float


@dataclass(frozen=True)
class AvlSection:
    x_le_m: float
    y_le_m: float
    z_le_m: float
    chord_m: float
    twist_deg: float
    airfoil_lines: tuple[str, ...]

    def as_manifest(self) -> dict[str, Any]:
        return {
            "x_le_m": round(float(self.x_le_m), 9),
            "y_le_m": round(float(self.y_le_m), 9),
            "z_le_m": round(float(self.z_le_m), 9),
            "chord_m": round(float(self.chord_m), 9),
            "twist_deg": round(float(self.twist_deg), 9),
        }


@dataclass(frozen=True)
class WingBasis:
    header: AvlHeader
    sections: tuple[AvlSection, ...]
    source_path: str


def build_full_aircraft_deck_text(
    *,
    wing_avl_path: Path,
    contract: Mapping[str, Any],
    delta_h_deg: float,
    delta_v_deg: float,
) -> tuple[str, dict[str, Any]]:
    """Return an AVL deck with whole-surface all-moving tail geometry."""

    wing = parse_wing_avl_basis(Path(wing_avl_path))
    h_sections, h_manifest = _horizontal_tail_sections(contract, delta_h_deg=delta_h_deg)
    v_sections, v_manifest = _vertical_tail_sections(contract, delta_v_deg=delta_v_deg)

    h = wing.header
    lines: list[str] = [
        (
            "Current pathfinder full-aircraft tail AVL audit v0 "
            f"(delta_H={delta_h_deg:.3f} deg, delta_V={delta_v_deg:.3f} deg)"
        ),
        "#Mach",
        f"{h.mach:.6f}",
        "#IYsym  iZsym  Zsym",
        "0  0  0.000000",
        "#Sref  Cref  Bref",
        f"{h.sref:.9f}  {h.cref:.9f}  {h.bref:.9f}",
        "#Xref  Yref  Zref",
        f"{h.xref:.9f}  {h.yref:.9f}  {h.zref:.9f}",
        "#CDp",
        f"{h.cdp:.6f}",
        "#",
        "! all_moving_geometry: r_H' = r_p,H + R_pitch(delta_H) * (r_H - r_p,H)",
        "! all_moving_geometry: r_V' = r_p,V + R_yaw(delta_V) * (r_V - r_p,V)",
        "! control_model: whole_surface_geometry_sweep_no_hinged_control_proxy",
        "#",
    ]
    lines.extend(_render_surface("Wing", wing.sections, component=1, yduplicate=True))
    lines.extend(
        _render_surface("HorizontalTail_all_moving", h_sections, component=2, yduplicate=True)
    )
    lines.extend(
        _render_surface("VerticalTail_all_moving", v_sections, component=3, yduplicate=False)
    )

    manifest = {
        "schema_version": "full_aircraft_tail_avl_deck_manifest_v0",
        "source_wing_avl_path": str(Path(wing_avl_path).resolve()),
        "reference": {
            "Sref": h.sref,
            "Cref": h.cref,
            "Bref": h.bref,
            "Xref": h.xref,
            "Yref": h.yref,
            "Zref": h.zref,
        },
        "deflections_deg": {
            "delta_H": float(delta_h_deg),
            "delta_V": float(delta_v_deg),
        },
        "control_model": "whole_surface_geometry_sweep_no_hinged_CONTROL_proxy",
        "all_moving_geometry": {
            "horizontal_tail": "r_H' = r_p,H + R_pitch(delta_H) * (r_H - r_p,H)",
            "vertical_tail": "r_V' = r_p,V + R_yaw(delta_V) * (r_V - r_p,V)",
        },
        "tail_surfaces": {
            "horizontal_tail": h_manifest,
            "vertical_tail": v_manifest,
        },
    }
    return "\n".join(lines) + "\n", manifest


def parse_wing_avl_basis(path: Path) -> WingBasis:
    """Parse the subset of a wing-only AVL deck needed for the audit deck."""

    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    header = AvlHeader(
        title=lines[0].strip() if lines else "",
        mach=_read_tagged_float(lines, "#Mach", 0.0),
        sref=_read_tagged_triplet(lines, "#Sref")[0],
        cref=_read_tagged_triplet(lines, "#Sref")[1],
        bref=_read_tagged_triplet(lines, "#Sref")[2],
        xref=_read_tagged_triplet(lines, "#Xref")[0],
        yref=_read_tagged_triplet(lines, "#Xref")[1],
        zref=_read_tagged_triplet(lines, "#Xref")[2],
        cdp=_read_tagged_float(lines, "#CDp", 0.0),
    )
    sections = tuple(_parse_first_surface_sections(lines))
    if not sections:
        raise ValueError(f"No wing SECTION blocks found in {path}")
    return WingBasis(header=header, sections=sections, source_path=str(path.resolve()))


def compute_screening(
    *,
    contract: Mapping[str, Any],
    case_results: Mapping[str, Mapping[str, Any]],
    small_delta_h_deg: float,
    small_delta_v_deg: float,
    runner_status: str,
) -> dict[str, Any]:
    """Compute screening-level trim/stability fields from AVL or missing-runner data."""

    cruise = _mapping_at(contract, "reference", "mission_cases", "cruise")
    wing = _mapping_at(contract, "reference", "wing")
    h_box = _mapping_at(contract, "horizontal_tail", "design_box")
    v_box = _mapping_at(contract, "vertical_tail", "design_box")

    sref = _read_number(wing.get("S_w_m2"))
    bref = _read_number(wing.get("b_w_m"))
    cref = _read_number(wing.get("cbar_w_m"))
    q_pa = _read_number(cruise.get("dynamic_pressure_pa"))
    if q_pa is None:
        rho = _read_number(cruise.get("rho_kgpm3"))
        velocity = _read_number(cruise.get("speed_mps"))
        q_pa = None if None in (rho, velocity) else 0.5 * float(rho) * float(velocity) ** 2
    mass = _read_number(cruise.get("mass_kg"))
    load_factor = _read_number(cruise.get("load_factor")) or 1.0
    cl_required = None
    if None not in (mass, q_pa, sref):
        cl_required = float(mass) * G_STANDARD * float(load_factor) / (float(q_pa) * float(sref))

    neutral = case_results.get("neutral", {})
    coeff = _mapping_at(neutral, "coefficients")
    deriv = _mapping_at(neutral, "derivatives")
    cm_delta_h = _finite_difference(
        case_results,
        minus_key="h_delta_minus_small",
        plus_key="h_delta_plus_small",
        coefficient="Cm",
        delta_deg=small_delta_h_deg,
    )
    cl_delta_h = _finite_difference(
        case_results,
        minus_key="h_delta_minus_small",
        plus_key="h_delta_plus_small",
        coefficient="CL",
        delta_deg=small_delta_h_deg,
    )
    cn_delta_v = _finite_difference(
        case_results,
        minus_key="v_delta_minus_small",
        plus_key="v_delta_plus_small",
        coefficient="Cn",
        delta_deg=small_delta_v_deg,
    )
    cl_roll_delta_v = _finite_difference(
        case_results,
        minus_key="v_delta_minus_small",
        plus_key="v_delta_plus_small",
        coefficient="Cl",
        delta_deg=small_delta_v_deg,
    )

    missing_cg_or_xac = _is_missing(_mapping_at(contract, "reference", "cg_range_x_m")) or _is_missing(
        _mapping_at(contract, "reference", "wing", "x_ac_w_m")
    )
    runner_completed = runner_status == "completed"
    longitudinal = _longitudinal_screening(
        missing_cg_or_xac=missing_cg_or_xac,
        runner_completed=runner_completed,
        cl_required=cl_required,
        coeff=coeff,
        deriv=deriv,
        cm_delta_h=cm_delta_h,
        cl_delta_h=cl_delta_h,
        h_box=h_box,
    )
    directional = _directional_screening(
        runner_completed=runner_completed,
        contract=contract,
        v_box=v_box,
        sref=sref,
        bref=bref,
        cn_delta_v=cn_delta_v,
        cl_roll_delta_v=cl_roll_delta_v,
        neutral_derivatives=deriv,
    )

    blockers = []
    if not runner_completed:
        blockers.append(
            {
                "field": "avl_runner",
                "reason": "AVL runner did not produce derivative artifacts.",
            }
        )
    if missing_cg_or_xac:
        blockers.append(
            {
                "field": "reference.cg_range_x_m_or_reference.wing.x_ac_w_m",
                "reason": "CG range or wing aerodynamic center is missing.",
            }
        )
    if directional["status"] == "blocked_by_directional_stability_or_vtail_authority":
        blockers.append(
            {
                "field": "directional_stability_or_vtail_authority",
                "reason": "Directional derivative or all-moving V-tail authority is missing or weak.",
            }
        )

    if not runner_completed:
        verdict = "blocked_by_avl_runner_or_geometry_generation"
    elif directional["status"] == "blocked_by_directional_stability_or_vtail_authority":
        verdict = "blocked_by_directional_stability_or_vtail_authority"
    elif missing_cg_or_xac:
        verdict = "blocked_by_missing_cg_or_reference_moment"
    else:
        verdict = "tail_avl_audit_go_for_tail_aware_rib_sensitivity"

    return {
        "CL_required": _round_or_none(cl_required),
        "longitudinal_trim": longitudinal,
        "directional": directional,
        "static_stability": {
            "C_m_alpha": _round_or_none(_read_plain_number(deriv.get("Cm_alpha"))),
            "C_L_alpha": _round_or_none(_read_plain_number(deriv.get("CL_alpha"))),
            "static_margin": _static_margin(deriv, cref=cref, missing_cg_or_xac=missing_cg_or_xac),
            "claim_boundary": (
                "SM ~= -C_m_alpha / C_L_alpha only after CG reference and sign "
                "conventions are verified."
            ),
        },
        "tail_load_envelope_placeholder": {
            "status": "placeholder_not_sized",
            "required_next_input": "tail strip/surface loads, pivot moments, tail mass model",
        },
        "blockers": blockers,
        "engineering_verdict": verdict,
    }


def audit_full_aircraft_tail_avl_v0(
    *,
    contract: Mapping[str, Any],
    wing_avl_path: Path,
    output_dir: Path,
    report_json_path: Path,
    report_md_path: Path,
    run_avl: bool = True,
    avl_binary: str | None = None,
    small_delta_deg: float = 2.0,
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    """Write decks, optionally run AVL, and emit JSON/Markdown audit artifacts."""

    output_dir = Path(output_dir)
    cases = _sweep_cases(contract, small_delta_deg=small_delta_deg)
    output_dir.mkdir(parents=True, exist_ok=True)

    deck_records: list[dict[str, Any]] = []
    case_results: dict[str, dict[str, Any]] = {}
    runner_status = "completed"
    for case_name, delta_h, delta_v in cases:
        case_dir = output_dir / case_name
        case_dir.mkdir(parents=True, exist_ok=True)
        deck_path = case_dir / f"{case_name}.avl"
        deck_text, deck_manifest = build_full_aircraft_deck_text(
            wing_avl_path=Path(wing_avl_path),
            contract=contract,
            delta_h_deg=delta_h,
            delta_v_deg=delta_v,
        )
        deck_path.write_text(deck_text, encoding="utf-8")
        staged_airfoils = stage_avl_airfoil_files(deck_path)
        deck_manifest_path = case_dir / f"{case_name}_deck_manifest.json"
        deck_manifest["deck_path"] = str(deck_path.resolve())
        deck_manifest["staged_airfoil_files"] = [str(path.resolve()) for path in staged_airfoils]
        deck_manifest_path.write_text(
            json.dumps(deck_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        deck_record = {
            "case": case_name,
            "delta_H_deg": delta_h,
            "delta_V_deg": delta_v,
            "deck_path": str(deck_path.resolve()),
            "deck_manifest_path": str(deck_manifest_path.resolve()),
        }
        deck_records.append(deck_record)

        if not run_avl:
            runner_status = "runner_disabled"
            continue
        avl_result = run_avl_derivatives(
            avl_path=deck_path,
            out_dir=case_dir,
            avl_binary=avl_binary,
            alpha_deg=0.0,
            velocity=_cruise_value(contract, "speed_mps"),
            density=_cruise_value(contract, "rho_kgpm3"),
            timeout_s=timeout_s,
            stem=case_name,
        )
        deck_record["avl_run"] = avl_result.as_dict()
        if avl_result.error or avl_result.st_path is None:
            runner_status = avl_result.error or "st_file_not_produced"
            case_results[case_name] = {"run_status": runner_status}
            continue
        case_results[case_name] = _parse_case_result(avl_result.st_path)

    manifest = {
        "schema_version": "full_aircraft_tail_avl_audit_manifest_v0",
        "output_dir": str(output_dir.resolve()),
        "deck_count": len(deck_records),
        "cases": deck_records,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if runner_status != "completed" and runner_status != "runner_disabled":
        # Keep the user-facing status requested by the task when the binary/run is unavailable.
        runner_status = "runner_missing" if runner_status == "avl_binary_not_found" else runner_status

    screening = compute_screening(
        contract=contract,
        case_results=case_results,
        small_delta_h_deg=small_delta_deg,
        small_delta_v_deg=small_delta_deg,
        runner_status=runner_status,
    )
    summary = {
        "schema_version": "full_aircraft_tail_avl_audit_v0",
        "candidate_id": str(_mapping_at(contract, "pathfinder").get("candidate_id", "")),
        "contract_id": str(contract.get("contract_id", "")),
        "runner_status": runner_status,
        "artifact_manifest": manifest,
        "case_results": case_results,
        "screening": screening,
        "parser_notes": [
            (
                "C_n_beta is extracted from the stability-axis Cn row, not from AVL's "
                "spiral diagnostic line 'Clb Cnr / Clr Cnb = ...'."
            )
        ],
        "engineering_verdict": screening["engineering_verdict"],
        "claim_boundary": (
            "Do not claim aircraft-feasible until CG/x_ac, trim equations, derivative signs, "
            "directional authority, tail drag/mass, and load paths are resolved."
        ),
    }
    report_json_path.parent.mkdir(parents=True, exist_ok=True)
    report_json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_md_path.parent.mkdir(parents=True, exist_ok=True)
    report_md_path.write_text(_render_markdown_report(summary), encoding="utf-8")
    return summary


def _horizontal_tail_sections(
    contract: Mapping[str, Any],
    *,
    delta_h_deg: float,
) -> tuple[tuple[AvlSection, ...], dict[str, Any]]:
    box = _mapping_at(contract, "horizontal_tail", "design_box")
    span = _read_number(box.get("span_m")) or 4.0
    chord = _read_number(box.get("mean_chord_m")) or _mean_chord_from_area(box, span, "S_H_m2")
    x_le = _read_number(box.get("x_le_m")) or 0.0
    z_le = _read_number(box.get("z_ac_H_m")) or 0.0
    incidence = _read_number(box.get("incidence_zero_deg")) or 0.0
    pivot_xc = _read_number(box.get("pivot_x_over_chord")) or 0.25
    airfoil_lines = _airfoil_lines(_default_airfoil(box, fallback="naca0010"))
    base = (
        (x_le, 0.0, z_le),
        (x_le, 0.5 * float(span), z_le),
    )
    sections = []
    pivots = []
    for point in base:
        pivot = (point[0] + pivot_xc * chord, point[1], point[2])
        rotated = _rotate_pitch(point, pivot, delta_h_deg)
        pivots.append(pivot)
        sections.append(
            AvlSection(
                x_le_m=rotated[0],
                y_le_m=rotated[1],
                z_le_m=rotated[2],
                chord_m=chord,
                twist_deg=incidence + float(delta_h_deg),
                airfoil_lines=airfoil_lines,
            )
        )
    manifest = {
        "delta_deg": float(delta_h_deg),
        "pivot_x_over_chord": pivot_xc,
        "rotation_formula": "r_H' = r_p,H + R_pitch(delta_H) * (r_H - r_p,H)",
        "pivots": [_point_manifest(pivot) for pivot in pivots],
        "sections": [section.as_manifest() for section in sections],
    }
    return tuple(sections), manifest


def _vertical_tail_sections(
    contract: Mapping[str, Any],
    *,
    delta_v_deg: float,
) -> tuple[tuple[AvlSection, ...], dict[str, Any]]:
    box = _mapping_at(contract, "vertical_tail", "design_box")
    height = _read_number(box.get("height_or_span_m")) or 2.4
    chord = _read_number(box.get("mean_chord_m")) or _mean_chord_from_area(box, height, "S_V_m2")
    x_le = _read_number(box.get("x_le_m")) or 0.0
    z_ac = _read_number(box.get("z_ac_V_m"))
    z_root = -0.5 * float(height) if z_ac is None else float(z_ac) - 0.5 * float(height)
    z_tip = z_root + float(height)
    incidence = _read_number(box.get("incidence_zero_deg")) or 0.0
    pivot_xc = _read_number(box.get("pivot_x_over_chord")) or 0.25
    airfoil_lines = _airfoil_lines(_default_airfoil(box, fallback="naca0009"))
    base = ((x_le, 0.0, z_root), (x_le, 0.0, z_tip))
    sections = []
    pivots = []
    for point in base:
        pivot = (point[0] + pivot_xc * chord, point[1], point[2])
        rotated = _rotate_yaw(point, pivot, delta_v_deg)
        pivots.append(pivot)
        sections.append(
            AvlSection(
                x_le_m=rotated[0],
                y_le_m=rotated[1],
                z_le_m=rotated[2],
                chord_m=chord,
                twist_deg=incidence + float(delta_v_deg),
                airfoil_lines=airfoil_lines,
            )
        )
    manifest = {
        "delta_deg": float(delta_v_deg),
        "pivot_x_over_chord": pivot_xc,
        "rotation_formula": "r_V' = r_p,V + R_yaw(delta_V) * (r_V - r_p,V)",
        "pivots": [_point_manifest(pivot) for pivot in pivots],
        "sections": [section.as_manifest() for section in sections],
    }
    return tuple(sections), manifest


def _render_surface(
    name: str,
    sections: tuple[AvlSection, ...],
    *,
    component: int,
    yduplicate: bool,
) -> list[str]:
    lines = ["SURFACE", name, "12  1.0  20  -2.0", "#", "COMPONENT", str(component)]
    if yduplicate:
        lines.extend(["YDUPLICATE", "0.0"])
    lines.append("#")
    for section in sections:
        lines.extend(
            [
                "SECTION",
                (
                    f"{section.x_le_m:.9f}  {section.y_le_m:.9f}  "
                    f"{section.z_le_m:.9f}  {section.chord_m:.9f}  {section.twist_deg:.9f}"
                ),
            ]
        )
        lines.extend(section.airfoil_lines)
        lines.append("#")
    return lines


def _parse_first_surface_sections(lines: list[str]) -> list[AvlSection]:
    try:
        idx = next(i for i, line in enumerate(lines) if line.strip().upper() == "SURFACE")
    except StopIteration:
        return []
    idx += 1
    sections: list[AvlSection] = []
    while idx < len(lines):
        if lines[idx].strip().upper() == "SECTION":
            if idx + 1 >= len(lines):
                break
            values = [float(item) for item in lines[idx + 1].split()[:5]]
            idx += 2
            airfoil_lines: list[str] = []
            while idx < len(lines):
                marker = lines[idx].strip().upper()
                if marker in {"SECTION", "SURFACE"}:
                    break
                if marker == "#":
                    idx += 1
                    break
                airfoil_lines.append(lines[idx])
                idx += 1
            sections.append(
                AvlSection(
                    x_le_m=values[0],
                    y_le_m=values[1],
                    z_le_m=values[2],
                    chord_m=values[3],
                    twist_deg=values[4],
                    airfoil_lines=tuple(airfoil_lines),
                )
            )
            continue
        idx += 1
    return sections


def _read_tagged_float(lines: list[str], tag: str, default: float) -> float:
    for idx, line in enumerate(lines):
        if line.strip().lower().startswith(tag.lower()) and idx + 1 < len(lines):
            try:
                return float(lines[idx + 1].split()[0])
            except (IndexError, ValueError):
                return default
    return default


def _read_tagged_triplet(lines: list[str], tag: str) -> tuple[float, float, float]:
    for idx, line in enumerate(lines):
        if line.strip().lower().startswith(tag.lower()) and idx + 1 < len(lines):
            parts = [float(item) for item in lines[idx + 1].split()[:3]]
            if len(parts) == 3:
                return (parts[0], parts[1], parts[2])
    raise ValueError(f"Missing AVL header triplet {tag}")


def _sweep_cases(
    contract: Mapping[str, Any],
    *,
    small_delta_deg: float,
) -> list[tuple[str, float, float]]:
    h_box = _mapping_at(contract, "horizontal_tail", "design_box")
    v_box = _mapping_at(contract, "vertical_tail", "design_box")
    h_useful = _usable_range(h_box) or [-15.0, 15.0]
    v_useful = _usable_range(v_box) or [-20.0, 20.0]
    return [
        ("neutral", 0.0, 0.0),
        ("h_delta_minus_small", -float(small_delta_deg), 0.0),
        ("h_delta_plus_small", float(small_delta_deg), 0.0),
        ("h_delta_min_useful", float(h_useful[0]), 0.0),
        ("h_delta_max_useful", float(h_useful[1]), 0.0),
        ("v_delta_minus_small", 0.0, -float(small_delta_deg)),
        ("v_delta_plus_small", 0.0, float(small_delta_deg)),
        ("v_delta_min_useful", 0.0, float(v_useful[0])),
        ("v_delta_max_useful", 0.0, float(v_useful[1])),
    ]


def _parse_case_result(st_path: Path) -> dict[str, Any]:
    parsed = parse_st_file(st_path)
    raw = parsed.raw_derivatives
    axis = _parse_stability_axis_derivatives(st_path)
    return {
        "run_status": "completed",
        "st_path": str(st_path.resolve()),
        "coefficients": {
            "CL": _read_plain_number(parsed.CL_trim),
            "CD": _read_plain_number(parsed.CD_trim),
            "Cm": _read_plain_number(parsed.Cm_trim),
            "CY": _pick_raw(raw, "CYtot"),
            "Cl": _pick_raw(raw, "Cltot", "Cl"),
            "Cn": _pick_raw(raw, "Cntot", "Cn"),
        },
        "derivatives": {
            "CL_alpha": axis.get("CL_alpha", _read_plain_number(parsed.CL_alpha)),
            "Cm_alpha": axis.get("Cm_alpha", _read_plain_number(parsed.Cm_alpha)),
            "Cn_beta": axis.get("Cn_beta", _read_plain_number(parsed.Cn_beta)),
            "Cl_beta": axis.get("Cl_beta", _read_plain_number(parsed.Cl_beta)),
            "CY_beta": axis.get("CY_beta", _read_plain_number(parsed.CY_beta)),
        },
        "raw_derivatives": raw,
    }


def _parse_stability_axis_derivatives(st_path: Path) -> dict[str, float]:
    """Extract stability-axis derivatives from their own AVL table lines.

    The generic parser intentionally scans all ``name = value`` pairs. AVL's
    later spiral diagnostic contains ``... Cnb = ratio`` text, which is not the
    directional-stability derivative. This table-specific pass prevents that
    diagnostic ratio from overwriting the real ``Cnb`` row value.
    """

    out: dict[str, float] = {}
    for line in st_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "z' force CL" in line:
            _store_pair(out, "CL_alpha", line, "CLa")
        elif "y  force CY" in line:
            _store_pair(out, "CY_beta", line, "CYb")
        elif "x' mom.  Cl" in line:
            _store_pair(out, "Cl_beta", line, "Clb")
        elif "y  mom.  Cm" in line:
            _store_pair(out, "Cm_alpha", line, "Cma")
        elif "z' mom.  Cn" in line:
            _store_pair(out, "Cn_beta", line, "Cnb")
    return out


def _store_pair(out: dict[str, float], field: str, line: str, avl_name: str) -> None:
    match = re.search(rf"\b{re.escape(avl_name)}\s*=\s*([-+]?\d+\.\d+(?:[eE][-+]?\d+)?)", line)
    if match is None:
        return
    out[field] = float(match.group(1))


def _finite_difference(
    case_results: Mapping[str, Mapping[str, Any]],
    *,
    minus_key: str,
    plus_key: str,
    coefficient: str,
    delta_deg: float,
) -> float | None:
    minus = _read_plain_number(_mapping_at(case_results.get(minus_key, {}), "coefficients").get(coefficient))
    plus = _read_plain_number(_mapping_at(case_results.get(plus_key, {}), "coefficients").get(coefficient))
    if minus is None or plus is None:
        return None
    delta_rad = math.radians(float(delta_deg))
    if abs(delta_rad) <= 1.0e-12:
        return None
    return (float(plus) - float(minus)) / (2.0 * delta_rad)


def _longitudinal_screening(
    *,
    missing_cg_or_xac: bool,
    runner_completed: bool,
    cl_required: float | None,
    coeff: Mapping[str, Any],
    deriv: Mapping[str, Any],
    cm_delta_h: float | None,
    cl_delta_h: float | None,
    h_box: Mapping[str, Any],
) -> dict[str, Any]:
    if not runner_completed:
        status = "blocked_by_avl_runner"
        reason = "AVL derivative artifacts are missing."
    elif missing_cg_or_xac:
        status = "blocked_by_missing_cg_or_x_ac"
        reason = "CG range or wing aerodynamic center is missing; Cm=0 cannot be claimed."
    else:
        status = "linearized_trim_screen_available"
        reason = ""

    delta_required: dict[str, Any] = {"status": status}
    if reason:
        delta_required["reason"] = reason
    if status == "linearized_trim_screen_available":
        solved = _solve_linear_trim(coeff, deriv, cl_required, cm_delta_h, cl_delta_h)
        delta_required.update(solved)
        status = str(solved.get("status", status))

    return {
        "status": status,
        "CL_required": _round_or_none(cl_required),
        "delta_H_required": delta_required,
        "H_tail_CL_utilization": {
            "status": "missing_tail_CLmax",
            "reason": "No current H-tail safe CLmax polar is promoted.",
        },
        "C_m_deltaH": _round_or_none(cm_delta_h),
        "C_L_deltaH": _round_or_none(cl_delta_h),
        "usable_delta_H_range_deg": _usable_range(h_box),
        "equations": {
            "CL": "CL(alpha, delta_H) = W / (q S)",
            "Cm": "Cm(alpha, delta_H, x_cg) = 0",
        },
    }


def _directional_screening(
    *,
    runner_completed: bool,
    contract: Mapping[str, Any],
    v_box: Mapping[str, Any],
    sref: float | None,
    bref: float | None,
    cn_delta_v: float | None,
    cl_roll_delta_v: float | None,
    neutral_derivatives: Mapping[str, Any],
) -> dict[str, Any]:
    cn_beta = _read_plain_number(neutral_derivatives.get("Cn_beta"))
    cl_beta = _read_plain_number(neutral_derivatives.get("Cl_beta"))
    warnings: list[str] = []
    v_v = _vertical_tail_volume(contract, sref=sref, bref=bref)
    if v_v is not None and v_v <= 0.015:
        warnings.append("low_V_V_directional_authority_risk")
    if cn_beta is not None and abs(cn_beta) < 0.005:
        warnings.append("very_small_C_n_beta_return_to_tail_sizing")
    if cn_delta_v is not None and abs(cn_delta_v) < 0.005:
        warnings.append("very_small_C_n_deltaV_return_to_tail_sizing")
    if (
        cn_beta is None
        or cn_delta_v is None
        or abs(cn_beta) < 0.005
        or abs(cn_delta_v) < 0.005
    ):
        status = "blocked_by_directional_stability_or_vtail_authority"
    elif not runner_completed:
        status = "blocked_by_avl_runner"
    else:
        status = "directional_derivatives_screen_available"

    usable = _usable_range(v_box)
    return {
        "status": status,
        "V_V": _round_or_none(v_v),
        "C_n_beta": _round_or_none(cn_beta),
        "C_n_deltaV": _round_or_none(cn_delta_v),
        "C_l_beta": _round_or_none(cl_beta),
        "C_l_deltaV": _round_or_none(cl_roll_delta_v),
        "delta_V_required": {
            "status": "not_solved_without_beta_case" if runner_completed else "blocked_by_avl_runner",
            "reason": "No promoted yaw/turn beta case is available for Cn(beta, delta_V)=0.",
        },
        "usable_delta_V_range_deg": usable,
        "yaw_roll_coupling_warning": {
            "formula": "C_l,V ~ Y_V z_V / (q S_W b_W)",
            "status": "warning_not_limit_checked",
        },
        "warnings": warnings,
        "equations": {
            "directional_stability": "C_n_beta > C_n_beta_min",
            "authority": "exists delta_V such that C_n(beta, delta_V) = 0",
        },
    }


def _solve_linear_trim(
    coeff: Mapping[str, Any],
    deriv: Mapping[str, Any],
    cl_required: float | None,
    cm_delta_h: float | None,
    cl_delta_h: float | None,
) -> dict[str, Any]:
    cl0 = _read_plain_number(coeff.get("CL"))
    cm0 = _read_plain_number(coeff.get("Cm"))
    cl_alpha = _read_plain_number(deriv.get("CL_alpha"))
    cm_alpha = _read_plain_number(deriv.get("Cm_alpha"))
    if None in (cl_required, cl0, cm0, cl_alpha, cm_alpha, cm_delta_h, cl_delta_h):
        return {"status": "blocked_by_missing_derivative"}
    det = float(cl_alpha) * float(cm_delta_h) - float(cl_delta_h) * float(cm_alpha)
    if abs(det) <= 1.0e-12:
        return {"status": "blocked_by_singular_trim_linearization"}
    rhs_cl = float(cl_required) - float(cl0)
    rhs_cm = -float(cm0)
    alpha_rad = (rhs_cl * float(cm_delta_h) - float(cl_delta_h) * rhs_cm) / det
    delta_rad = (float(cl_alpha) * rhs_cm - rhs_cl * float(cm_alpha)) / det
    return {
        "status": "solved_linearized_screening",
        "alpha_required_deg": round(math.degrees(alpha_rad), 6),
        "delta_H_required_deg": round(math.degrees(delta_rad), 6),
    }


def _static_margin(
    deriv: Mapping[str, Any],
    *,
    cref: float | None,
    missing_cg_or_xac: bool,
) -> dict[str, Any]:
    cm_alpha = _read_plain_number(deriv.get("Cm_alpha"))
    cl_alpha = _read_plain_number(deriv.get("CL_alpha"))
    if missing_cg_or_xac:
        return {
            "status": "missing_reference_moment_or_cg",
            "reason": "CG reference and wing AC are not promoted.",
        }
    if cm_alpha is None or cl_alpha is None or abs(cl_alpha) <= 1.0e-12:
        return {"status": "missing_derivatives"}
    return {
        "status": "computed_if_conventions_verified",
        "value": round(-float(cm_alpha) / float(cl_alpha), 6),
        "normalization": f"MAC={cref}" if cref is not None else "MAC missing",
    }


def _render_markdown_report(summary: Mapping[str, Any]) -> str:
    screening = _mapping_at(summary, "screening")
    longitudinal = _mapping_at(screening, "longitudinal_trim")
    directional = _mapping_at(screening, "directional")
    static = _mapping_at(screening, "static_stability")
    blockers = screening.get("blockers") or []
    lines = [
        "# Full-Aircraft Tail AVL Audit V0",
        "",
        f"Candidate: `{summary.get('candidate_id')}`",
        f"Runner status: `{summary.get('runner_status')}`",
        f"Engineering verdict: `{summary.get('engineering_verdict')}`",
        "",
        "## Scope",
        "",
        "This artifact instantiates the current pathfinder wing with all-moving H-tail",
        "and V-tail geometry sweeps. It does not use AVL hinged CONTROL lines as the",
        "production representation of the all-moving tails.",
        "",
        "## Required Math",
        "",
        "```text",
        "r_H' = r_p,H + R_pitch(delta_H) * (r_H - r_p,H)",
        "r_V' = r_p,V + R_yaw(delta_V) * (r_V - r_p,V)",
        "C_m_deltaH ~= [C_m(+Delta delta_H) - C_m(-Delta delta_H)] / (2 Delta delta_H)",
        "C_n_deltaV ~= [C_n(+Delta delta_V) - C_n(-Delta delta_V)] / (2 Delta delta_V)",
        "CL(alpha, delta_H) = W / (q S)",
        "Cm(alpha, delta_H, x_cg) = 0",
        "C_m_alpha < 0",
        "SM ~= -C_m_alpha / C_L_alpha, if referenced about CG and conventions verified",
        "C_n_beta > C_n_beta_min",
        "exists delta_V such that C_n(beta, delta_V) = 0",
        "C_l,V ~ Y_V z_V / (q S_W b_W)",
        "```",
        "",
        "## Artifact Manifest",
        "",
        f"- Output dir: `{summary['artifact_manifest']['output_dir']}`",
        f"- Deck count: `{summary['artifact_manifest']['deck_count']}`",
        "",
        "## Parser Note",
        "",
        "- `C_n_beta` is extracted from AVL's stability-axis `z' mom. Cn'` row, not from",
        "  the later spiral diagnostic ratio line `Clb Cnr / Clr Cnb = ...`.",
        "",
        "## Longitudinal Trim Screening",
        "",
        f"- Status: `{longitudinal.get('status')}`",
        f"- CL_required: `{longitudinal.get('CL_required')}`",
        f"- delta_H_required: `{longitudinal.get('delta_H_required')}`",
        f"- H-tail CL utilization: `{longitudinal.get('H_tail_CL_utilization')}`",
        f"- C_m_deltaH: `{longitudinal.get('C_m_deltaH')}`",
        "",
        "## Static Stability",
        "",
        f"- C_m_alpha: `{static.get('C_m_alpha')}`",
        f"- Static margin: `{static.get('static_margin')}`",
        "",
        "## Directional / V-Tail Screening",
        "",
        f"- Status: `{directional.get('status')}`",
        f"- V_V: `{directional.get('V_V')}`",
        f"- C_n_beta: `{directional.get('C_n_beta')}`",
        f"- C_n_deltaV: `{directional.get('C_n_deltaV')}`",
        f"- C_l_beta: `{directional.get('C_l_beta')}`",
        f"- C_l_deltaV: `{directional.get('C_l_deltaV')}`",
        f"- yaw-roll coupling warning: `{directional.get('yaw_roll_coupling_warning')}`",
        f"- warnings: `{directional.get('warnings')}`",
        "",
        "## Tail Load Envelope Placeholder",
        "",
        f"`{screening.get('tail_load_envelope_placeholder')}`",
        "",
        "## Blockers",
        "",
    ]
    if blockers:
        for item in blockers:
            lines.append(f"- `{item.get('field')}`: {item.get('reason')}")
    else:
        lines.append("- none recorded by this v0 screen")
    lines.extend(
        [
            "",
            "## Engineering Read",
            "",
            "Passing tests or producing AVL derivatives is not aircraft sign-off. CG range,",
            "wing aerodynamic center, reference moment convention, tail CL/CY limits, tail",
            "drag/mass, tailboom loads, pivot loads, and hardware load paths remain outside",
            "this v0 audit unless explicitly populated above.",
            "",
        ]
    )
    return "\n".join(lines)


def _mapping_at(root: Any, *keys: str) -> Mapping[str, Any]:
    node = root
    for key in keys:
        if not isinstance(node, Mapping):
            return {}
        node = node.get(key, {})
    return node if isinstance(node, Mapping) else {}


def _read_number(node: Any) -> float | None:
    if isinstance(node, int | float):
        return float(node)
    if isinstance(node, Mapping):
        for key in ("value", "nominal"):
            value = node.get(key)
            if isinstance(value, int | float):
                return float(value)
        raw_range = node.get("range")
        if isinstance(raw_range, list | tuple) and len(raw_range) == 2:
            low, high = raw_range
            if isinstance(low, int | float) and isinstance(high, int | float):
                return 0.5 * (float(low) + float(high))
    return None


def _read_plain_number(value: Any) -> float | None:
    if isinstance(value, int | float) and math.isfinite(float(value)):
        return float(value)
    return None


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)


def _is_missing(node: Mapping[str, Any]) -> bool:
    if not node:
        return True
    status = str(node.get("status", "")).lower()
    return node.get("value") is None or status in {"missing", "blocking_missing", "required_missing"}


def _mean_chord_from_area(box: Mapping[str, Any], span: float, area_key: str) -> float:
    area = _read_number(box.get(area_key))
    if area is not None and abs(float(span)) > 1.0e-12:
        return float(area) / float(span)
    return 1.0


def _default_airfoil(box: Mapping[str, Any], *, fallback: str) -> str:
    candidates = _mapping_at(box, "airfoil_candidates")
    default = candidates.get("default")
    if isinstance(default, list | tuple) and default:
        return str(default[0])
    if isinstance(default, str):
        return default
    return fallback


def _airfoil_lines(name: str) -> tuple[str, ...]:
    normalized = str(name).strip().lower().replace(" ", "")
    if normalized.startswith("naca"):
        return ("NACA", normalized.replace("naca", ""))
    return ("AFILE", str(name))


def _usable_range(box: Mapping[str, Any]) -> list[float] | None:
    raw_range = box.get("deflection_range_deg")
    reserve = _read_number(box.get("deflection_reserve_deg"))
    if not isinstance(raw_range, list | tuple) or len(raw_range) != 2 or reserve is None:
        return None
    low, high = raw_range
    if not isinstance(low, int | float) or not isinstance(high, int | float):
        return None
    return [float(low) + float(reserve), float(high) - float(reserve)]


def _vertical_tail_volume(
    contract: Mapping[str, Any],
    *,
    sref: float | None,
    bref: float | None,
) -> float | None:
    box = _mapping_at(contract, "vertical_tail", "design_box")
    area = _read_number(box.get("S_V_m2"))
    arm = _read_number(box.get("l_V_m"))
    if arm is None:
        x_ref = _read_number(_mapping_at(contract, "reference", "wing").get("x_ref_avl_m")) or 0.0
        x_le = _read_number(box.get("x_le_m"))
        chord = _read_number(box.get("mean_chord_m"))
        if x_le is not None and chord is not None:
            arm = float(x_le) + 0.25 * float(chord) - float(x_ref)
    if None in (area, arm, sref, bref) or float(sref) == 0.0 or float(bref) == 0.0:
        return None
    return float(area) * float(arm) / (float(sref) * float(bref))


def _cruise_value(contract: Mapping[str, Any], field: str) -> float | None:
    return _read_number(_mapping_at(contract, "reference", "mission_cases", "cruise").get(field))


def _pick_raw(raw: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _read_plain_number(raw.get(key))
        if value is not None:
            return value
    return None


def _rotate_pitch(
    point: tuple[float, float, float],
    pivot: tuple[float, float, float],
    delta_deg: float,
) -> tuple[float, float, float]:
    theta = math.radians(float(delta_deg))
    dx = point[0] - pivot[0]
    dy = point[1] - pivot[1]
    dz = point[2] - pivot[2]
    return (
        pivot[0] + math.cos(theta) * dx + math.sin(theta) * dz,
        pivot[1] + dy,
        pivot[2] - math.sin(theta) * dx + math.cos(theta) * dz,
    )


def _rotate_yaw(
    point: tuple[float, float, float],
    pivot: tuple[float, float, float],
    delta_deg: float,
) -> tuple[float, float, float]:
    theta = math.radians(float(delta_deg))
    dx = point[0] - pivot[0]
    dy = point[1] - pivot[1]
    dz = point[2] - pivot[2]
    return (
        pivot[0] + math.cos(theta) * dx - math.sin(theta) * dy,
        pivot[1] + math.sin(theta) * dx + math.cos(theta) * dy,
        pivot[2] + dz,
    )


def _point_manifest(point: tuple[float, float, float]) -> dict[str, float]:
    return {
        "x_m": round(float(point[0]), 9),
        "y_m": round(float(point[1]), 9),
        "z_m": round(float(point[2]), 9),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--wing-avl", type=Path, default=DEFAULT_WING_AVL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    parser.add_argument("--avl-binary", default=None)
    parser.add_argument("--small-delta-deg", type=float, default=2.0)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--no-run-avl", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8")) or {}
    if not isinstance(contract, Mapping):
        raise TypeError("Tail contract YAML must contain a mapping.")
    summary = audit_full_aircraft_tail_avl_v0(
        contract=contract,
        wing_avl_path=args.wing_avl,
        output_dir=args.output_dir,
        report_json_path=args.report_json,
        report_md_path=args.report_md,
        run_avl=not args.no_run_avl,
        avl_binary=args.avl_binary,
        small_delta_deg=float(args.small_delta_deg),
        timeout_s=float(args.timeout_s),
    )
    print(f"wrote {args.report_json}")
    print(f"wrote {args.report_md}")
    print(f"verdict: {summary['engineering_verdict']}")


if __name__ == "__main__":
    main()
