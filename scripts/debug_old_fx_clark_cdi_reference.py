#!/usr/bin/env python3
"""Diagnostic-only CDi/e_CDi reference audit for the old FX/Clark baseline."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _REPO_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from hpa_mdo.aero.avl_spanwise import (  # noqa: E402
    build_spanwise_load_from_avl_strip_forces,
    parse_avl_strip_forces,
)
from hpa_mdo.concept.avl_loader import _run_avl_spanwise_case, _run_avl_trim_case  # noqa: E402


DEFAULT_OUTPUT_DIR = (
    _REPO_ROOT / "output" / "baseline_comparisons" / "old_fx_clark_vs_phase7_cdi_debug"
)
DEFAULT_OLD_AVL = _REPO_ROOT / "data" / "blackcat_004_full.avl"
DEFAULT_OLD_VSP = _REPO_ROOT / "data" / "blackcat_004_origin.vsp3"
DEFAULT_OLD_PRE_TIER_DIR = (
    _REPO_ROOT / "output" / "baseline_comparisons" / "old_fx_clark_vs_phase7_pre_tier2"
)
DEFAULT_POLICY_A_AVL = (
    _REPO_ROOT
    / "output"
    / "geometry_exports"
    / "phase7_sidecar_vsp"
    / "policy_A_performance_candidate"
    / "policy_A_performance_candidate.avl"
)
DEFAULT_POLICY_C_AVL = (
    _REPO_ROOT
    / "output"
    / "geometry_exports"
    / "phase7_sidecar_vsp"
    / "policy_C_conservative_baseline"
    / "policy_C_conservative_baseline.avl"
)
DEFAULT_POLICY_A_SECTION_TABLE = DEFAULT_POLICY_A_AVL.parent / "section_table.csv"
DEFAULT_POLICY_C_SECTION_TABLE = DEFAULT_POLICY_C_AVL.parent / "section_table.csv"


_FLOAT = r"[-+]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[Ee][-+]?\d+)?"


def _repo_path(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else _REPO_ROOT / path


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _parse_scalar(text: str, label: str) -> float | None:
    match = re.search(rf"\b{re.escape(label)}\s*=\s*(?P<value>{_FLOAT}|\*+)", text)
    if match is None or "*" in match.group("value"):
        return None
    return float(match.group("value"))


def parse_avl_force_totals_extended(path: str | Path) -> dict[str, float]:
    text = _repo_path(path).read_text(encoding="utf-8", errors="ignore")
    values = {
        "Alpha": _parse_scalar(text, "Alpha"),
        "CLtot": _parse_scalar(text, "CLtot"),
        "CDtot": _parse_scalar(text, "CDtot"),
        "CDvis": _parse_scalar(text, "CDvis"),
        "CDind": _parse_scalar(text, "CDind"),
        "CLff": _parse_scalar(text, "CLff"),
        "CDff": _parse_scalar(text, "CDff"),
        "e_reported": _parse_scalar(text, "e"),
    }
    return {key: float(value) for key, value in values.items() if value is not None}


def manual_e_cdi(cl: float, ar_ref: float, cdi: float) -> float:
    return float(cl) ** 2 / (math.pi * float(ar_ref) * float(cdi))


def _surface_blocks(lines: list[str]) -> tuple[list[str], list[tuple[str, list[str]]]]:
    surface_indices = [
        index for index, line in enumerate(lines) if line.strip().casefold() == "surface"
    ]
    if not surface_indices:
        return lines, []
    header = lines[: surface_indices[0]]
    blocks: list[tuple[str, list[str]]] = []
    for pos, start in enumerate(surface_indices):
        end = surface_indices[pos + 1] if pos + 1 < len(surface_indices) else len(lines)
        block = lines[start:end]
        name = block[1].strip() if len(block) > 1 else ""
        blocks.append((name, block))
    return header, blocks


def extract_main_wing_only_avl_text(path: str | Path) -> str:
    lines = _repo_path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    header, blocks = _surface_blocks(lines)
    main_blocks = [block for name, block in blocks if "".join(name.split()).casefold() == "mainwing"]
    if not main_blocks:
        raise ValueError(f"No Main Wing surface found in {path}")
    return "\n".join(header + main_blocks[0]) + "\n"


def _parse_avl_refs(path: str | Path) -> dict[str, Any]:
    lines = _repo_path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    refs: dict[str, Any] = {}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#IYsym") and index + 1 < len(lines):
            tokens = lines[index + 1].split()
            refs["IYsym"] = int(float(tokens[0]))
            refs["iZsym"] = int(float(tokens[1]))
            refs["Zsym"] = float(tokens[2])
        if stripped.startswith("#Sref") and index + 1 < len(lines):
            tokens = lines[index + 1].split()
            refs["Sref"] = float(tokens[0])
            refs["Cref"] = float(tokens[1])
            refs["Bref"] = float(tokens[2])
        if stripped.startswith("#Xref") and index + 1 < len(lines):
            tokens = lines[index + 1].split()
            refs["Xref"] = float(tokens[0])
            refs["Yref"] = float(tokens[1])
            refs["Zref"] = float(tokens[2])
    refs["AR_ref"] = refs["Bref"] ** 2 / refs["Sref"]
    return refs


def _read_section_table(path: str | Path) -> list[dict[str, Any]]:
    with _repo_path(path).open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _section_area_span(rows: list[dict[str, Any]]) -> dict[str, float]:
    y = [float(row["y_m"]) for row in rows]
    chord = [float(row["chord_m"]) for row in rows]
    half_area = 0.0
    for index in range(1, len(y)):
        half_area += 0.5 * (y[index] - y[index - 1]) * (chord[index] + chord[index - 1])
    return {
        "computed_wing_area_m2": 2.0 * half_area,
        "computed_span_m": 2.0 * max(y),
        "root_chord_m": chord[0],
        "tip_chord_m": chord[-1],
    }


def _surface_names(path: str | Path) -> list[str]:
    lines = _repo_path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    _, blocks = _surface_blocks(lines)
    return [name for name, _ in blocks]


def _surface_uses_yduplicate(path: str | Path, surface_name: str) -> bool:
    lines = _repo_path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    _, blocks = _surface_blocks(lines)
    target = "".join(surface_name.split()).casefold()
    for name, block in blocks:
        if "".join(name.split()).casefold() == target:
            return any(line.strip().casefold() == "yduplicate" for line in block)
    return False


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _load_old_profile_and_comparison(old_pre_tier_dir: Path) -> dict[str, dict[str, Any]]:
    comparison_path = old_pre_tier_dir / "old_vs_policy_A_C_comparison.csv"
    with comparison_path.open(newline="", encoding="utf-8") as handle:
        rows = {row["case"]: dict(row) for row in csv.DictReader(handle)}
    return rows


def _run_avl_case(
    *,
    avl_path: Path,
    output_dir: Path,
    cl_required: float,
    velocity_mps: float,
    density_kgpm3: float,
    target_surface_names: tuple[str, ...],
    avl_binary: str | Path | None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    trim = _run_avl_trim_case(
        avl_path=avl_path,
        case_dir=output_dir,
        cl_required=cl_required,
        velocity_mps=velocity_mps,
        density_kgpm3=density_kgpm3,
        avl_binary=avl_binary,
    )
    ft_path = output_dir / "concept_trim.ft"
    totals = parse_avl_force_totals_extended(ft_path)
    alpha = float(totals.get("Alpha", trim["aoa_trim_deg"]))
    fs_path = _run_avl_spanwise_case(
        avl_path=avl_path,
        case_dir=output_dir,
        alpha_deg=alpha,
        velocity_mps=velocity_mps,
        density_kgpm3=density_kgpm3,
        avl_binary=avl_binary,
    )
    load = build_spanwise_load_from_avl_strip_forces(
        fs_path=fs_path,
        avl_path=avl_path,
        aoa_deg=alpha,
        velocity_mps=velocity_mps,
        density_kgpm3=density_kgpm3,
        target_surface_names=target_surface_names,
        positive_y_only=True,
    )
    y_tip = float(max(load.y)) if len(load.y) else 0.0
    spanload = []
    for idx, (y_m, chord_m, cl, cd, cm) in enumerate(
        zip(load.y, load.chord, load.cl, load.cd, load.cm)
    ):
        spanload.append(
            {
                "station_index": idx,
                "eta": 0.0 if y_tip <= 0.0 else float(y_m) / y_tip,
                "y_m": float(y_m),
                "chord_m": float(chord_m),
                "cl": float(cl),
                "cd_strip": float(cd),
                "cm_c4": float(cm),
            }
        )
    return {
        "trim": totals,
        "alpha_at_CL_req": alpha,
        "CL_req": float(cl_required),
        "ft_path": str(ft_path.resolve()),
        "fs_path": str(fs_path.resolve()),
        "spanload": spanload,
        "surface_strip_summary": _surface_strip_summary(fs_path),
    }


def _surface_strip_summary(fs_path: str | Path) -> dict[str, dict[str, float]]:
    try:
        parsed = parse_avl_strip_forces(
            fs_path,
            target_surface_names=("Main Wing", "Wing", "Elevator", "Fin"),
            positive_y_only=False,
        )
    except Exception:
        return {}
    surfaces: dict[str, list[dict[str, float]]] = defaultdict(list)
    for row in parsed.get("strips", []):
        surfaces["selected"].append(row)
    # parse_avl_strip_forces flattens matched surfaces; use a lightweight direct parse for names.
    text = _repo_path(fs_path).read_text(encoding="utf-8", errors="ignore")
    current_name = None
    in_table = False
    direct: dict[str, list[dict[str, float]]] = defaultdict(list)
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.strip().startswith("Surface #"):
            parts = line.split(None, 3)
            current_name = parts[3].strip() if len(parts) >= 4 else "unknown"
            in_table = False
            continue
        if "Strip Forces referred to Strip Area, Chord" in line:
            in_table = True
            continue
        if not in_table or current_name is None:
            continue
        tokens = line.split()
        if len(tokens) < 15:
            continue
        try:
            values = [float(token) for token in tokens[1:15]]
        except ValueError:
            continue
        direct[current_name].append(
            {
                "y_m": values[1],
                "chord_m": values[3],
                "area_m2": values[4],
                "cl": values[8],
                "cd": values[9],
                "cm": values[11],
            }
        )
    summary: dict[str, dict[str, float]] = {}
    for name, rows in direct.items():
        if not rows:
            continue
        area = sum(row["area_m2"] for row in rows)
        summary[name] = {
            "strip_count": float(len(rows)),
            "strip_area_sum_m2": area,
            "cl_area_weighted": sum(row["cl"] * row["area_m2"] for row in rows) / area
            if area
            else 0.0,
            "cd_area_weighted": sum(row["cd"] * row["area_m2"] for row in rows) / area
            if area
            else 0.0,
            "cl_max": max(row["cl"] for row in rows),
            "cl_min": min(row["cl"] for row in rows),
        }
    return summary


def _manual_fields(totals: dict[str, float], ar_ref: float) -> dict[str, Any]:
    result: dict[str, Any] = {
        "CDi_near_field_CDind": totals.get("CDind"),
        "CDi_trefftz_CDff": totals.get("CDff"),
        "e_CDi_raw_avl_reported": totals.get("e_reported"),
    }
    if totals.get("CLtot") is not None and totals.get("CDind"):
        result["e_CDi_manual_near_field_CLtot_CDind"] = manual_e_cdi(
            totals["CLtot"], ar_ref, totals["CDind"]
        )
    if totals.get("CLff") is not None and totals.get("CDff"):
        result["e_CDi_manual_trefftz_CLff_CDff"] = manual_e_cdi(
            totals["CLff"], ar_ref, totals["CDff"]
        )
    return result


def _audit_row(
    *,
    case: str,
    avl_path: Path,
    section_table: Path,
    full_aircraft: bool,
    cl_owner: str,
    cdi_owner: str,
) -> dict[str, Any]:
    refs = _parse_avl_refs(avl_path)
    section_rows = _read_section_table(section_table)
    geometry = _section_area_span(section_rows)
    surfaces = _surface_names(avl_path)
    symmetry = refs.get("IYsym") == 1
    ydup = any(_surface_uses_yduplicate(avl_path, surface) for surface in surfaces)
    return {
        "case": case,
        "source_avl_path": str(avl_path.resolve()),
        "Sref": refs["Sref"],
        "Bref": refs["Bref"],
        "Cref": refs["Cref"],
        "computed_wing_area_from_sections": geometry["computed_wing_area_m2"],
        "computed_span_from_sections": geometry["computed_span_m"],
        "AR_ref": refs["AR_ref"],
        "full_span_or_half_span_convention": "half_geometry_mirrored"
        if symmetry or ydup
        else "full_or_unsymmetric_geometry",
        "IYsym": refs.get("IYsym"),
        "uses_YDUPLICATE": ydup,
        "surfaces": ";".join(surfaces),
        "tail_or_non_main_surfaces_included": full_aircraft,
        "CL_interpretation": cl_owner,
        "CDi_interpretation": cdi_owner,
        "area_ref_delta_vs_sections": refs["Sref"] - geometry["computed_wing_area_m2"],
        "span_ref_delta_vs_sections": refs["Bref"] - geometry["computed_span_m"],
    }


def _comparison_power(
    *,
    sref: float,
    cl_req: float,
    cdi: float,
    cd0_total: float,
    velocity_mps: float,
    density_kgpm3: float,
    eta_prop: float,
    eta_trans: float,
) -> dict[str, float]:
    cd_total = cdi + cd0_total
    q = 0.5 * density_kgpm3 * velocity_mps**2
    drag_n = q * sref * cd_total
    p_air = drag_n * velocity_mps
    return {
        "CD_total": cd_total,
        "L_over_D": cl_req / cd_total,
        "drag_n": drag_n,
        "P_air_w": p_air,
        "P_crank_w": p_air / (eta_prop * eta_trans),
    }


def _format_float(value: Any, digits: int = 6) -> str:
    parsed = _safe_float(value)
    return "" if parsed is None else f"{parsed:.{digits}f}"


def run_debug(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    old_avl: str | Path = DEFAULT_OLD_AVL,
    old_vsp: str | Path = DEFAULT_OLD_VSP,
    old_pre_tier_dir: str | Path = DEFAULT_OLD_PRE_TIER_DIR,
    policy_a_avl: str | Path = DEFAULT_POLICY_A_AVL,
    policy_c_avl: str | Path = DEFAULT_POLICY_C_AVL,
    avl_binary: str | Path | None = None,
) -> dict[str, Any]:
    out_dir = _repo_path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    old_avl_path = _repo_path(old_avl)
    old_pre_dir = _repo_path(old_pre_tier_dir)
    policy_a_path = _repo_path(policy_a_avl)
    policy_c_path = _repo_path(policy_c_avl)

    tier2_dir = _REPO_ROOT / "output" / "airfoil_db" / "full_alpha_reusable_v1_tier2"
    tier2_mtimes_before = _directory_mtimes(tier2_dir)

    main_wing_text = extract_main_wing_only_avl_text(old_avl_path)
    old_main_wing_avl = out_dir / "old_main_wing_only.avl"
    old_main_wing_avl.write_text(main_wing_text, encoding="utf-8")

    previous_old = json.loads((old_pre_dir / "old_design_avl_results.json").read_text())
    mission = previous_old["mission"]
    velocity = float(mission["speed_mps"])
    density = float(mission["rho"])
    eta_prop = float(mission.get("eta_prop", 0.86))
    eta_trans = float(mission.get("eta_trans", 0.96))
    cl_old = float(previous_old["cl_required"])
    old_profile_rows = _load_old_profile_and_comparison(old_pre_dir)
    old_previous_row = old_profile_rows["Old FX/Clark VSP baseline"]
    policy_a_previous = old_profile_rows["Policy A / D performance candidate"]
    policy_c_previous = old_profile_rows["Policy C / E conservative baseline"]

    old_full_ft = old_pre_dir / "avl_run" / "concept_trim.ft"
    old_full_totals = parse_avl_force_totals_extended(old_full_ft)
    old_full_surface_summary = _surface_strip_summary(old_pre_dir / "avl_run" / "concept_spanwise.fs")
    old_full_ar = _parse_avl_refs(old_avl_path)["AR_ref"]
    old_full_manual = _manual_fields(old_full_totals, old_full_ar)

    old_main_result = _run_avl_case(
        avl_path=old_main_wing_avl,
        output_dir=out_dir / "old_main_wing_only_run",
        cl_required=cl_old,
        velocity_mps=velocity,
        density_kgpm3=density,
        target_surface_names=("Main Wing",),
        avl_binary=avl_binary,
    )
    old_main_ar = _parse_avl_refs(old_main_wing_avl)["AR_ref"]
    old_main_manual = _manual_fields(old_main_result["trim"], old_main_ar)
    old_main_result.update(
        {
            "source_avl_path": str(old_main_wing_avl.resolve()),
            "AR_ref": old_main_ar,
            "manual_e_fields": old_main_manual,
            "diagnosis": (
                "main_wing_only_with_old_sref_bref_cref; retains old nonplanar dihedral and "
                "YDUPLICATE convention, removes elevator and fin"
            ),
        }
    )
    (out_dir / "old_main_wing_only_results.json").write_text(
        json.dumps(_json_ready(old_main_result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    policy_a_cl = float(policy_a_previous["CL_req"])
    policy_c_cl = float(policy_c_previous["CL_req"])
    policy_a_result = _run_avl_case(
        avl_path=policy_a_path,
        output_dir=out_dir / "policy_A_run",
        cl_required=policy_a_cl,
        velocity_mps=velocity,
        density_kgpm3=density,
        target_surface_names=("Wing",),
        avl_binary=avl_binary,
    )
    policy_c_result = _run_avl_case(
        avl_path=policy_c_path,
        output_dir=out_dir / "policy_C_run",
        cl_required=policy_c_cl,
        velocity_mps=velocity,
        density_kgpm3=density,
        target_surface_names=("Wing",),
        avl_binary=avl_binary,
    )
    policy_a_ar = _parse_avl_refs(policy_a_path)["AR_ref"]
    policy_c_ar = _parse_avl_refs(policy_c_path)["AR_ref"]
    policy_a_manual = _manual_fields(policy_a_result["trim"], policy_a_ar)
    policy_c_manual = _manual_fields(policy_c_result["trim"], policy_c_ar)

    audit_rows = [
        _audit_row(
            case="old_full_aircraft",
            avl_path=old_avl_path,
            section_table=old_pre_dir / "old_design_section_table.csv",
            full_aircraft=True,
            cl_owner="total_aircraft_CLtot_including_main_wing_elevator_fin",
            cdi_owner="AVL_total_forces_CDind_and_Trefftz_CDff_for_all_surfaces",
        ),
        _audit_row(
            case="old_main_wing_only",
            avl_path=old_main_wing_avl,
            section_table=old_pre_dir / "old_design_section_table.csv",
            full_aircraft=False,
            cl_owner="main_wing_only_CLtot",
            cdi_owner="main_wing_only_AVL_CDind_and_Trefftz_CDff",
        ),
        _audit_row(
            case="Policy A / D",
            avl_path=policy_a_path,
            section_table=DEFAULT_POLICY_A_SECTION_TABLE,
            full_aircraft=False,
            cl_owner="wing_only_CLtot",
            cdi_owner="wing_only_AVL_CDind_and_Trefftz_CDff",
        ),
        _audit_row(
            case="Policy C / E",
            avl_path=policy_c_path,
            section_table=DEFAULT_POLICY_C_SECTION_TABLE,
            full_aircraft=False,
            cl_owner="wing_only_CLtot",
            cdi_owner="wing_only_AVL_CDind_and_Trefftz_CDff",
        ),
    ]
    _write_csv(out_dir / "old_avl_reference_audit.csv", audit_rows)

    corrected_rows = []
    corrected_rows.append(
        _corrected_row(
            case="Old FX/Clark full aircraft raw",
            previous=old_previous_row,
            refs=_parse_avl_refs(old_avl_path),
            totals=old_full_totals,
            manual=old_full_manual,
            main_manual=old_main_manual,
            cdi_main_wing_only=old_main_result["trim"].get("CDff"),
            cdi_full_aircraft=old_full_totals.get("CDff"),
            comparability_status="full_aircraft_reference_caveat",
            velocity=velocity,
            density=density,
            eta_prop=eta_prop,
            eta_trans=eta_trans,
        )
    )
    corrected_rows.append(
        _corrected_row(
            case="Old FX/Clark main-wing-only comparable",
            previous=old_previous_row,
            refs=_parse_avl_refs(old_main_wing_avl),
            totals=old_main_result["trim"],
            manual=old_main_manual,
            main_manual=old_main_manual,
            cdi_main_wing_only=old_main_result["trim"].get("CDff"),
            cdi_full_aircraft=old_full_totals.get("CDff"),
            comparability_status="comparable_main_wing"
            if (old_main_manual.get("e_CDi_manual_trefftz_CLff_CDff") or 0.0) <= 1.05
            else "needs_manual_review",
            velocity=velocity,
            density=density,
            eta_prop=eta_prop,
            eta_trans=eta_trans,
        )
    )
    corrected_rows.append(
        _corrected_row(
            case="Policy A / D performance candidate",
            previous=policy_a_previous,
            refs=_parse_avl_refs(policy_a_path),
            totals=policy_a_result["trim"],
            manual=policy_a_manual,
            main_manual=policy_a_manual,
            cdi_main_wing_only=policy_a_result["trim"].get("CDff"),
            cdi_full_aircraft=policy_a_result["trim"].get("CDff"),
            comparability_status="comparable_main_wing",
            velocity=velocity,
            density=density,
            eta_prop=eta_prop,
            eta_trans=eta_trans,
        )
    )
    corrected_rows.append(
        _corrected_row(
            case="Policy C / E conservative baseline",
            previous=policy_c_previous,
            refs=_parse_avl_refs(policy_c_path),
            totals=policy_c_result["trim"],
            manual=policy_c_manual,
            main_manual=policy_c_manual,
            cdi_main_wing_only=policy_c_result["trim"].get("CDff"),
            cdi_full_aircraft=policy_c_result["trim"].get("CDff"),
            comparability_status="comparable_main_wing",
            velocity=velocity,
            density=density,
            eta_prop=eta_prop,
            eta_trans=eta_trans,
        )
    )
    _write_csv(out_dir / "corrected_old_vs_policy_A_C_comparison.csv", corrected_rows)

    _write_reference_audit_md(
        out_dir / "old_avl_reference_audit.md",
        audit_rows,
        corrected_rows,
        old_full_surface_summary,
    )
    _write_corrected_comparison_md(
        out_dir / "corrected_old_vs_policy_A_C_comparison.md",
        corrected_rows,
        old_main_result,
        old_full_totals,
    )
    _write_recommendation_md(
        out_dir / "recommended_interpretation.md",
        corrected_rows,
        old_main_result,
        old_full_totals,
    )

    tier2_mtimes_after = _directory_mtimes(tier2_dir)
    run_metadata = {
        "generated_at": _timestamp(),
        "old_source_avl": str(old_avl_path.resolve()),
        "old_source_vsp": str(_repo_path(old_vsp).resolve()),
        "tier2_mtimes_unchanged": tier2_mtimes_before == tier2_mtimes_after,
        "tier2_dir_checked_for_mtime_only": str(tier2_dir.resolve()),
        "outputs": sorted(path.name for path in out_dir.iterdir()),
    }
    (out_dir / "run_metadata.json").write_text(
        json.dumps(_json_ready(run_metadata), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "output_dir": str(out_dir.resolve()),
        "corrected_rows": corrected_rows,
        "old_main_wing_only": old_main_result,
        "tier2_mtimes_unchanged": tier2_mtimes_before == tier2_mtimes_after,
    }


def _corrected_row(
    *,
    case: str,
    previous: dict[str, Any],
    refs: dict[str, Any],
    totals: dict[str, float],
    manual: dict[str, Any],
    main_manual: dict[str, Any],
    cdi_main_wing_only: float | None,
    cdi_full_aircraft: float | None,
    comparability_status: str,
    velocity: float,
    density: float,
    eta_prop: float,
    eta_trans: float,
) -> dict[str, Any]:
    cd0_total = float(previous["CD0_total_est"])
    cdi_comparable = totals.get("CDff") or totals.get("CDind") or float(previous["CDi"])
    power = _comparison_power(
        sref=refs["Sref"],
        cl_req=float(previous["CL_req"]),
        cdi=float(cdi_comparable),
        cd0_total=cd0_total,
        velocity_mps=velocity,
        density_kgpm3=density,
        eta_prop=eta_prop,
        eta_trans=eta_trans,
    )
    return {
        "case": case,
        "Sref": refs["Sref"],
        "Bref": refs["Bref"],
        "Cref": refs["Cref"],
        "AR_ref": refs["AR_ref"],
        "CL_req": previous["CL_req"],
        "alpha_at_CL_req_deg": totals.get("Alpha", previous.get("alpha_at_CL_req_deg", "")),
        "CDi_full_aircraft": cdi_full_aircraft,
        "CDi_main_wing_only": cdi_main_wing_only,
        "CDi_near_field_CDind": totals.get("CDind"),
        "CDi_trefftz_CDff": totals.get("CDff"),
        "CDi_comparable_used": cdi_comparable,
        "e_CDi_raw_avl_reported": manual.get("e_CDi_raw_avl_reported"),
        "e_CDi_manual_ref_checked": manual.get("e_CDi_manual_near_field_CLtot_CDind"),
        "e_CDi_manual_trefftz": manual.get("e_CDi_manual_trefftz_CLff_CDff"),
        "e_CDi_main_wing_only": main_manual.get("e_CDi_manual_trefftz_CLff_CDff"),
        "profile_cd": previous["profile_cd"],
        "CD0_total_est": cd0_total,
        **power,
        "previous_CDi": previous["CDi"],
        "previous_e_CDi": previous["e_CDi"],
        "previous_P_crank_w": previous["P_crank_w"],
        "comparability_status": comparability_status,
        "notes": previous.get("notes", ""),
    }


def _write_reference_audit_md(
    path: Path,
    audit_rows: list[dict[str, Any]],
    corrected_rows: list[dict[str, Any]],
    old_full_surface_summary: dict[str, dict[str, float]],
) -> None:
    lines = [
        "# Old AVL Reference Audit",
        "",
        f"Generated: {_timestamp()}",
        "",
        "This is a diagnostic-only report. It does not change ranking or hard gates.",
        "",
        "## Reference Quantities",
        "",
        "| Case | Sref | Bref | Cref | Area From Sections | Span From Sections | AR_ref | Symmetry | Surfaces |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in audit_rows:
        lines.append(
            "| {case} | {sref} | {bref} | {cref} | {area} | {span} | {ar} | {sym} | {surfaces} |".format(
                case=row["case"],
                sref=_format_float(row["Sref"], 6),
                bref=_format_float(row["Bref"], 6),
                cref=_format_float(row["Cref"], 6),
                area=_format_float(row["computed_wing_area_from_sections"], 6),
                span=_format_float(row["computed_span_from_sections"], 6),
                ar=_format_float(row["AR_ref"], 6),
                sym=row["full_span_or_half_span_convention"],
                surfaces=row["surfaces"],
            )
        )
    lines.extend(
        [
            "",
            "## Findings",
            "",
            "- Old full AVL includes `Main Wing`, `Elevator`, and `Fin`; Policy A/C AVL files are wing-only.",
            "- Old full AVL uses `IYsym=0` plus `YDUPLICATE` on the wing and elevator; Policy A/C use `IYsym=1` half-wing symmetry.",
            "- Old Sref/Bref match the wing section area/span, so the main mismatch is not Sref itself.",
            "- Old `e = 1.2911` is the Trefftz-plane value paired with `CLff/CDff`, not the near-field `CDind` value.",
            "",
            "## Old Full-Aircraft Strip Summary",
            "",
            "| Surface | Strip Area Sum | Area-Weighted Cl | Area-Weighted Cd | Cl Min | Cl Max |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for surface_name, summary in old_full_surface_summary.items():
        lines.append(
            "| {surface} | {area} | {cl} | {cd} | {clmin} | {clmax} |".format(
                surface=surface_name,
                area=_format_float(summary["strip_area_sum_m2"], 6),
                cl=_format_float(summary["cl_area_weighted"], 6),
                cd=_format_float(summary["cd_area_weighted"], 6),
                clmin=_format_float(summary["cl_min"], 6),
                clmax=_format_float(summary["cl_max"], 6),
            )
        )
    lines.extend(
        [
            "",
            "The elevator carries negative lift in the old full-aircraft trim. That is why the full-aircraft Trefftz result should not be used as a wing-only sidecar comparison.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_corrected_comparison_md(
    path: Path,
    rows: list[dict[str, Any]],
    old_main_result: dict[str, Any],
    old_full_totals: dict[str, float],
) -> None:
    lines = [
        "# Corrected Old FX/Clark vs Policy A/C CDi Comparison",
        "",
        "The table separates near-field `CDind` from Trefftz `CDff`. The comparable induced-drag column uses `CDff`, matching AVL's reported span-efficiency convention.",
        "",
        "| Case | Status | CDind | CDff Used | e Manual Near | e Trefftz | CD0 | CD Total | P_crank W |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {case} | {status} | {cdind} | {cdff} | {enear} | {etr} | {cd0} | {cdtot} | {p} |".format(
                case=row["case"],
                status=row["comparability_status"],
                cdind=_format_float(row["CDi_near_field_CDind"], 7),
                cdff=_format_float(row["CDi_comparable_used"], 7),
                enear=_format_float(row["e_CDi_manual_ref_checked"], 6),
                etr=_format_float(row["e_CDi_manual_trefftz"], 6),
                cd0=_format_float(row["CD0_total_est"], 6),
                cdtot=_format_float(row["CD_total"], 6),
                p=_format_float(row["P_crank_w"], 1),
            )
        )
    lines.extend(
        [
            "",
            "## Main-Wing-Only Result",
            "",
            f"- alpha_at_CL_req = {_format_float(old_main_result['alpha_at_CL_req'], 6)} deg",
            f"- CLtot = {_format_float(old_main_result['trim'].get('CLtot'), 6)}",
            f"- CDind = {_format_float(old_main_result['trim'].get('CDind'), 7)}",
            f"- CDff = {_format_float(old_main_result['trim'].get('CDff'), 7)}",
            f"- e_reported = {_format_float(old_main_result['trim'].get('e_reported'), 6)}",
            "",
            "## Full-Aircraft Raw Old Result",
            "",
            f"- CLtot = {_format_float(old_full_totals.get('CLtot'), 6)}",
            f"- CDind = {_format_float(old_full_totals.get('CDind'), 7)}",
            f"- CDff = {_format_float(old_full_totals.get('CDff'), 7)}",
            f"- e_reported = {_format_float(old_full_totals.get('e_reported'), 6)}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_recommendation_md(
    path: Path,
    rows: list[dict[str, Any]],
    old_main_result: dict[str, Any],
    old_full_totals: dict[str, float],
) -> None:
    by_case = {row["case"]: row for row in rows}
    old_main = by_case["Old FX/Clark main-wing-only comparable"]
    old_full = by_case["Old FX/Clark full aircraft raw"]
    policy_a = by_case["Policy A / D performance candidate"]
    policy_c = by_case["Policy C / E conservative baseline"]
    old_beats_policy_a = float(old_main["P_crank_w"]) < float(policy_a["P_crank_w"])
    old_beats_policy_c = float(old_main["P_crank_w"]) < float(policy_c["P_crank_w"])
    old_main_e = float(old_main["e_CDi_main_wing_only"])
    old_main_review = (
        "This is below 1 and is comparable to the Policy A/C wing-only AVL convention."
        if old_main_e <= 1.0
        else "This remains above 1 and should be carried as a manual-review caveat."
    )
    lines = [
        "# Recommended Interpretation",
        "",
        "## Answers",
        "",
        f"1. Is the old `e_CDi=1.291` physically meaningful? It is meaningful only as AVL's Trefftz-plane diagnostic for this old reference setup. It is not comparable to the previous table's `CDind=0.013944`, because that was a near-field CDind. Paired correctly, old full-aircraft near-field manual e is {_format_float(old_full['e_CDi_manual_ref_checked'], 6)} while Trefftz e is {_format_float(old_full['e_CDi_manual_trefftz'], 6)}.",
        f"2. Corrected comparable old main-wing e_CDi: `{_format_float(old_main['e_CDi_main_wing_only'], 6)}` using main-wing-only Trefftz `CDff={_format_float(old_main['CDi_main_wing_only'], 7)}`. {old_main_review}",
        f"3. Does old still require more power after reference correction? Under the Trefftz-comparable convention, old main-wing-only P_crank is `{_format_float(old_main['P_crank_w'], 1)} W`, Policy A is `{_format_float(policy_a['P_crank_w'], 1)} W`, and Policy C is `{_format_float(policy_c['P_crank_w'], 1)} W`. Old {'is lower than' if old_beats_policy_a else 'is higher than'} Policy A and {'lower than' if old_beats_policy_c else 'higher than'} Policy C.",
        f"4. What drives the difference? The previous apparent penalty was mostly reference convention: old near-field `CDind` was being compared against Policy A/C values derived from Trefftz `e`. Once corrected to main-wing-only, old CDff ({_format_float(old_main['CDi_main_wing_only'], 7)}) is slightly higher than Policy A ({_format_float(policy_a['CDi_main_wing_only'], 7)}) and Policy C ({_format_float(policy_c['CDi_main_wing_only'], 7)}). Old profile Cd is lower, but the old wing has larger Sref, so total power remains higher.",
        "5. Should old design remain a fallback baseline? Yes. Keep it as a fallback/reference baseline with the corrected `comparable_main_wing` fields, but do not let the full-aircraft raw `e=1.291` replace Policy A/C reporting.",
        "",
        "## Engineering Caution",
        "",
        "- The full-aircraft old e above 1 is driven by the full-aircraft reference/Trefftz setup, including negative-lift elevator contribution, not by the main wing alone.",
        "- The old main-wing-only result is now in the same e_CDi band as Policy A/C, which makes it suitable as a diagnostic fallback comparison.",
        "- No production ranking or hard gates should change from this diagnostic.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _directory_mtimes(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    return {
        str(item.relative_to(path)): item.stat().st_mtime_ns
        for item in path.rglob("*")
        if item.is_file()
    }


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--old-avl", type=Path, default=DEFAULT_OLD_AVL)
    parser.add_argument("--old-vsp", type=Path, default=DEFAULT_OLD_VSP)
    parser.add_argument("--old-pre-tier-dir", type=Path, default=DEFAULT_OLD_PRE_TIER_DIR)
    parser.add_argument("--policy-a-avl", type=Path, default=DEFAULT_POLICY_A_AVL)
    parser.add_argument("--policy-c-avl", type=Path, default=DEFAULT_POLICY_C_AVL)
    parser.add_argument("--avl-binary", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    result = run_debug(
        output_dir=args.output_dir,
        old_avl=args.old_avl,
        old_vsp=args.old_vsp,
        old_pre_tier_dir=args.old_pre_tier_dir,
        policy_a_avl=args.policy_a_avl,
        policy_c_avl=args.policy_c_avl,
        avl_binary=args.avl_binary,
    )
    print(f"Wrote CDi debug artifacts to {result['output_dir']}")
    for row in result["corrected_rows"]:
        print(
            f"{row['case']}: CDff={_format_float(row['CDi_comparable_used'], 7)}, "
            f"e_trefftz={_format_float(row['e_CDi_manual_trefftz'], 6)}, "
            f"P_crank={_format_float(row['P_crank_w'], 1)} W, "
            f"status={row['comparability_status']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
