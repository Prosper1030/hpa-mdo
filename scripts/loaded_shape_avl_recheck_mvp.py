#!/usr/bin/env python3
"""Pipeline v2 MVP 3: AVL recheck on structure-screened loaded shapes.

This script is report-only. It reruns AVL on Stage 5 loaded-shape candidates
without changing production ranking, hard gates, CST/NSGA state, or structural
truth labels.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from hpa_mdo.aero.aswing_exporter import parse_avl  # noqa: E402
from hpa_mdo.aero.avl_spanwise import (  # noqa: E402
    build_spanwise_load_from_avl_strip_forces,
    load_candidate_avl_spanwise_artifact,
)
from hpa_mdo.aero.base import SpanwiseLoad  # noqa: E402
from hpa_mdo.concept.avl_loader import (  # noqa: E402
    _parse_avl_force_totals,
    _run_avl_spanwise_case,
    _run_avl_trim_case,
)


DEFAULT_STAGE2_DIR = REPO_ROOT / "output/pipeline_redesign_v2/structure_budgeted_z_state_mvp"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output/pipeline_redesign_v2/loaded_shape_avl_recheck_mvp"
DEFAULT_DYNAMIC_VISCOSITY_PA_S = 1.18 * 1.46e-5
DEFAULT_DIAGNOSTIC_SECTION_CL_LIMIT = 1.20
GEOMETRY_Z_BASIS = (
    "main_beam_loaded_shape_spar_data_root_offset_removed_as_avl_section_z_proxy"
)
SCHEMA_VERSION = "loaded_shape_avl_recheck_mvp_v1"


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


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
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def normalize_generated_text_file(path: Path) -> Path:
    """Normalize generated solver text to LF and strip line-end padding."""

    if not path.exists():
        return path
    text = path.read_text(encoding="utf-8", errors="ignore")
    normalized = "\n".join(line.rstrip() for line in text.splitlines()) + "\n"
    path.write_text(normalized, encoding="utf-8")
    return path


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().casefold() in {"1", "true", "yes", "y", "pass"}


def _normalize_surface_name(name: str) -> str:
    return "".join(str(name).split()).casefold()


def _target_wing_sections(avl_path: Path, *, target_surface_name: str = "Wing") -> list[Any]:
    model = parse_avl(avl_path)
    target = _normalize_surface_name(target_surface_name)
    for surface in model.surfaces:
        if _normalize_surface_name(surface.name) == target:
            return sorted(surface.sections, key=lambda section: float(section.y))
    available = ", ".join(surface.name for surface in model.surfaces) or "none"
    raise ValueError(f"No target surface {target_surface_name!r} in {avl_path}; available: {available}")


def interpolate_loaded_main_z_to_sections(
    *,
    loaded_rows: Sequence[Mapping[str, Any]],
    section_y_m: Sequence[float],
) -> tuple[float, ...]:
    """Interpolate Stage 5 main-spar loaded Z onto AVL section y locations.

    Stage 5 CSVs are beam-line coordinates and include a root Z offset. AVL only
    cares about relative section heights for the induced-drag recheck, so the
    root offset is removed and the basis is explicitly labelled in artifacts.
    """

    entries: list[tuple[float, float]] = []
    for row in loaded_rows:
        y = _float_or_none(row.get("Y_Position_m"))
        z = _float_or_none(row.get("Main_Z_m"))
        if y is None or z is None:
            continue
        entries.append((float(y), float(z)))
    if len(entries) < 2:
        raise ValueError("Loaded-shape CSV needs at least two Y_Position_m/Main_Z_m rows.")
    entries.sort(key=lambda item: item[0])
    y_values = np.asarray([item[0] for item in entries], dtype=float)
    z_values = np.asarray([item[1] for item in entries], dtype=float)
    section_y = np.asarray([float(value) for value in section_y_m], dtype=float)
    if np.any(np.diff(section_y) < -1.0e-9):
        raise ValueError("AVL section y locations must be nondecreasing.")
    if section_y[0] < y_values[0] - 1.0e-6 or section_y[-1] > y_values[-1] + 1.0e-6:
        raise ValueError(
            "Loaded-shape CSV does not cover AVL section span "
            f"({section_y[0]:.6g}..{section_y[-1]:.6g} m)."
        )
    interpolated = np.interp(section_y, y_values, z_values)
    root_offset = float(interpolated[0])
    return tuple(float(value - root_offset) for value in interpolated)


def rewrite_wing_section_z(
    *,
    source_avl: Path,
    output_avl: Path,
    section_z_m: Sequence[float],
    target_surface_name: str = "Wing",
) -> Path:
    """Copy an AVL file and replace only target-surface SECTION z coordinates."""

    sections = _target_wing_sections(source_avl, target_surface_name=target_surface_name)
    if len(section_z_m) != len(sections):
        raise ValueError(
            f"Need {len(sections)} replacement z values for {target_surface_name}; "
            f"got {len(section_z_m)}."
        )

    target = _normalize_surface_name(target_surface_name)
    lines = source_avl.read_text(encoding="utf-8").splitlines()
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
            x, y, _old_z, chord, ainc = (float(token) for token in tokens[:5])
            z_new = float(section_z_m[replacement_index])
            out_lines[idx] = (
                f"{x:.9f}  {y:.9f}  {z_new:.9f}  {chord:.9f}  {ainc:.9f}"
            )
            replacement_index += 1
            expect_section_values = False
            continue
        if expect_surface_name and stripped:
            current_surface = _normalize_surface_name(stripped)
            expect_surface_name = False
            continue
        if upper == "SURFACE":
            current_surface = None
            expect_surface_name = True
            continue
        if upper == "SECTION" and current_surface == target:
            expect_section_values = True

    if replacement_index != len(section_z_m):
        raise ValueError(
            f"Replaced {replacement_index} SECTION rows in {source_avl}; expected {len(section_z_m)}."
        )
    output_avl.parent.mkdir(parents=True, exist_ok=True)
    output_avl.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return output_avl


def _trapz(values: np.ndarray, x: np.ndarray) -> float:
    return float(np.trapezoid(np.asarray(values, dtype=float), np.asarray(x, dtype=float)))


def root_bending_moment_nm(spanwise_load: SpanwiseLoad) -> float:
    y = np.asarray(spanwise_load.y, dtype=float)
    lift = np.maximum(np.asarray(spanwise_load.lift_per_span, dtype=float), 0.0)
    if y.size < 2:
        return 0.0
    return _trapz(lift * y, y)


def normalized_bending_proxy_m(spanwise_load: SpanwiseLoad) -> float:
    y = np.asarray(spanwise_load.y, dtype=float)
    lift = np.maximum(np.asarray(spanwise_load.lift_per_span, dtype=float), 0.0)
    total = _trapz(lift, y)
    if not math.isfinite(total) or total <= 1.0e-12:
        return 0.0
    return _trapz((lift / total) * y, y)


def local_cl_re_rows(
    *,
    case_label: str,
    span_m: float,
    spanwise_load: SpanwiseLoad,
    density_kgpm3: float,
    dynamic_viscosity_pa_s: float,
    diagnostic_section_cl_limit: float,
    geometry_z_basis: str,
) -> list[dict[str, Any]]:
    y = np.asarray(spanwise_load.y, dtype=float)
    chord = np.asarray(spanwise_load.chord, dtype=float)
    cl = np.asarray(spanwise_load.cl, dtype=float)
    cd = np.asarray(spanwise_load.cd, dtype=float)
    cm = np.asarray(spanwise_load.cm, dtype=float)
    lift = np.asarray(spanwise_load.lift_per_span, dtype=float)
    drag = np.asarray(spanwise_load.drag_per_span, dtype=float)
    half_span = 0.5 * float(span_m)
    limit = float(diagnostic_section_cl_limit)
    rows: list[dict[str, Any]] = []
    for index, y_m in enumerate(y):
        reynolds = float(density_kgpm3) * float(spanwise_load.velocity) * float(chord[index])
        reynolds /= max(float(dynamic_viscosity_pa_s), 1.0e-12)
        stall_margin = limit - float(cl[index])
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "case_label": str(case_label),
                "eta": 0.0 if half_span <= 0.0 else float(y_m / half_span),
                "y_m": float(y_m),
                "chord_m": float(chord[index]),
                "local_cl": float(cl[index]),
                "local_cd": float(cd[index]),
                "cm_c4": float(cm[index]),
                "lift_per_span_npm": float(lift[index]),
                "drag_per_span_npm": float(drag[index]),
                "aoa_deg": float(spanwise_load.aoa_deg),
                "velocity_mps": float(spanwise_load.velocity),
                "dynamic_pressure_pa": float(spanwise_load.dynamic_pressure),
                "density_kgpm3": float(density_kgpm3),
                "dynamic_viscosity_pa_s": float(dynamic_viscosity_pa_s),
                "reynolds": float(reynolds),
                "diagnostic_section_cl_limit": limit,
                "stall_margin_cl": float(stall_margin),
                "stall_utilization": float(cl[index]) / max(limit, 1.0e-12),
                "stall_margin_basis": "diagnostic_constant_section_cl_limit_not_gate",
                "geometry_z_basis": str(geometry_z_basis),
            }
        )
    return rows


def spanload_comparison_rows(
    *,
    case_label: str,
    span_m: float,
    pre_structure_load: SpanwiseLoad,
    loaded_shape_load: SpanwiseLoad,
) -> list[dict[str, Any]]:
    loaded_y = np.asarray(loaded_shape_load.y, dtype=float)
    pre_y = np.asarray(pre_structure_load.y, dtype=float)
    pre_cl = np.interp(loaded_y, pre_y, np.asarray(pre_structure_load.cl, dtype=float))
    pre_lift = np.interp(
        loaded_y,
        pre_y,
        np.asarray(pre_structure_load.lift_per_span, dtype=float),
    )
    loaded_cl = np.asarray(loaded_shape_load.cl, dtype=float)
    loaded_lift = np.asarray(loaded_shape_load.lift_per_span, dtype=float)
    half_span = 0.5 * float(span_m)
    pre_bending = normalized_bending_proxy_m(pre_structure_load)
    loaded_bending = normalized_bending_proxy_m(loaded_shape_load)
    pre_root_moment = root_bending_moment_nm(pre_structure_load)
    loaded_root_moment = root_bending_moment_nm(loaded_shape_load)
    return [
        {
            "schema_version": SCHEMA_VERSION,
            "case_label": str(case_label),
            "eta": 0.0 if half_span <= 0.0 else float(y_m / half_span),
            "y_m": float(y_m),
            "pre_structure_cl": float(pre_cl[index]),
            "loaded_shape_cl": float(loaded_cl[index]),
            "delta_cl_loaded_minus_pre": float(loaded_cl[index] - pre_cl[index]),
            "pre_structure_lift_per_span_npm": float(pre_lift[index]),
            "loaded_shape_lift_per_span_npm": float(loaded_lift[index]),
            "delta_lift_per_span_npm": float(loaded_lift[index] - pre_lift[index]),
            "bending_proxy_pre_structure_m": float(pre_bending),
            "bending_proxy_loaded_shape_m": float(loaded_bending),
            "bending_proxy_delta_m": float(loaded_bending - pre_bending),
            "root_bending_moment_pre_structure_nm": float(pre_root_moment),
            "root_bending_moment_loaded_shape_nm": float(loaded_root_moment),
            "root_bending_moment_ratio_loaded_vs_pre": (
                ""
                if abs(pre_root_moment) <= 1.0e-12
                else float(loaded_root_moment / pre_root_moment)
            ),
            "comparison_basis": "pre_structure_avl_vs_loaded_shape_avl",
        }
        for index, y_m in enumerate(loaded_y)
    ]


def aero_warning_flags(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Return report-only warning flags for loaded-shape aero consequences."""

    flags: list[str] = []
    loaded_e = _float_or_none(row.get("loaded_shape_e_CDi"))
    if loaded_e is not None and loaded_e > 1.0:
        flags.append("superunit_loaded_shape_e_cdi_check_reference_convention")
    stall_margin = _float_or_none(row.get("stall_margin_min"))
    if stall_margin is not None and stall_margin < 0.0:
        flags.append("negative_diagnostic_stall_margin_not_gate")
    z_basis = str(row.get("geometry_z_basis", ""))
    if "main_beam_loaded_shape" in z_basis or "beam" in z_basis:
        flags.append("beam_line_z_proxy_not_aero_surface_truth")
    return tuple(flags)


def _first_case_load(path: Path) -> tuple[dict[str, Any], SpanwiseLoad]:
    payload, cases = load_candidate_avl_spanwise_artifact(path)
    selected_aoa = _float_or_none(payload.get("selected_cruise_aoa_deg"))
    if selected_aoa is None:
        return payload, cases[0]
    return payload, min(cases, key=lambda case: abs(float(case.aoa_deg) - float(selected_aoa)))


def _span_m_from_avl(avl_path: Path) -> float:
    model = parse_avl(avl_path)
    if model.bref > 0.0:
        return float(model.bref)
    sections = _target_wing_sections(avl_path)
    return 2.0 * max(float(section.y) for section in sections)


def _run_case(
    *,
    case_row: Mapping[str, Any],
    sweep_row: Mapping[str, Any],
    output_dir: Path,
    dynamic_viscosity_pa_s: float,
    diagnostic_section_cl_limit: float,
    avl_binary: str | Path | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    case_label = str(case_row["case_label"])
    case_dir = output_dir / "runs" / case_label
    case_dir.mkdir(parents=True, exist_ok=True)
    candidate_artifact = Path(str(sweep_row["candidate_avl_artifact"]))
    loaded_shape_csv = Path(str(sweep_row.get("loaded_shape_csv") or case_row["case_dir"])) / (
        "" if sweep_row.get("loaded_shape_csv") else "loaded_shape_spar_data.csv"
    )
    if sweep_row.get("loaded_shape_csv"):
        loaded_shape_csv = Path(str(sweep_row["loaded_shape_csv"]))
    payload, pre_load = _first_case_load(candidate_artifact)
    geometry_artifacts = payload.get("geometry_artifacts", {})
    source_avl = Path(str(geometry_artifacts["avl_path"]))
    pre_trim_force = geometry_artifacts.get("trim_force_path")
    pre_trim = _parse_avl_force_totals(Path(pre_trim_force)) if pre_trim_force else None
    if pre_trim is None or pre_trim.get("cl_trim") is None:
        raise ValueError(f"Pre-structure trim force artifact lacks CLtot: {pre_trim_force}")

    sections = _target_wing_sections(source_avl)
    section_y = [float(section.y) for section in sections]
    loaded_rows = _read_csv_rows(loaded_shape_csv)
    loaded_section_z = interpolate_loaded_main_z_to_sections(
        loaded_rows=loaded_rows,
        section_y_m=section_y,
    )
    loaded_avl = rewrite_wing_section_z(
        source_avl=source_avl,
        output_avl=case_dir / "loaded_shape_wing.avl",
        section_z_m=loaded_section_z,
    )

    velocity_mps = float(payload["velocity_mps"])
    density_kgpm3 = float(payload["density_kgpm3"])
    cl_required = float(pre_trim["cl_trim"])
    avl_run_dir = case_dir / "avl_run"
    loaded_trim = _run_avl_trim_case(
        avl_path=loaded_avl,
        case_dir=avl_run_dir,
        cl_required=cl_required,
        velocity_mps=velocity_mps,
        density_kgpm3=density_kgpm3,
        avl_binary=avl_binary,
    )
    fs_path = _run_avl_spanwise_case(
        avl_path=loaded_avl,
        case_dir=avl_run_dir,
        alpha_deg=float(loaded_trim["aoa_trim_deg"]),
        velocity_mps=velocity_mps,
        density_kgpm3=density_kgpm3,
        avl_binary=avl_binary,
    )
    loaded_load = build_spanwise_load_from_avl_strip_forces(
        fs_path=fs_path,
        avl_path=loaded_avl,
        aoa_deg=float(loaded_trim["aoa_trim_deg"]),
        velocity_mps=velocity_mps,
        density_kgpm3=density_kgpm3,
        target_surface_names=tuple(payload.get("target_surface_names") or ("Wing",)),
        positive_y_only=True,
    )
    for generated_path in (
        avl_run_dir / "concept_trim.ft",
        avl_run_dir / "concept_trim_stdout.log",
        Path(fs_path),
        avl_run_dir / "concept_spanwise_stdout.log",
    ):
        normalize_generated_text_file(generated_path)
    span_m = _span_m_from_avl(source_avl)
    local_rows = local_cl_re_rows(
        case_label=case_label,
        span_m=span_m,
        spanwise_load=loaded_load,
        density_kgpm3=density_kgpm3,
        dynamic_viscosity_pa_s=dynamic_viscosity_pa_s,
        diagnostic_section_cl_limit=diagnostic_section_cl_limit,
        geometry_z_basis=GEOMETRY_Z_BASIS,
    )
    comparison_rows = spanload_comparison_rows(
        case_label=case_label,
        span_m=span_m,
        pre_structure_load=pre_load,
        loaded_shape_load=loaded_load,
    )
    _write_csv(case_dir / "loaded_shape_local_cl_re_envelope.csv", local_rows)
    _write_csv(case_dir / "loaded_shape_spanload_comparison.csv", comparison_rows)

    local_cl_values = [float(row["local_cl"]) for row in local_rows]
    reynolds_values = [float(row["reynolds"]) for row in local_rows]
    stall_margins = [float(row["stall_margin_cl"]) for row in local_rows]
    pre_cdi = _float_or_none(pre_trim.get("cd_induced"))
    loaded_cdi = _float_or_none(loaded_trim.get("cd_induced"))
    pre_e = _float_or_none(pre_trim.get("span_efficiency"))
    loaded_e = _float_or_none(loaded_trim.get("span_efficiency"))
    pre_root_bending = root_bending_moment_nm(pre_load)
    loaded_root_bending = root_bending_moment_nm(loaded_load)
    summary_row = {
        "schema_version": SCHEMA_VERSION,
        "case_label": case_label,
        "status": "rechecked_for_screening",
        "structure_trust_label": sweep_row.get("structure_trust_label", "daily_screening"),
        "geometry_z_basis": GEOMETRY_Z_BASIS,
        "loaded_shape_csv": str(loaded_shape_csv.resolve()),
        "source_pre_structure_avl": str(source_avl.resolve()),
        "loaded_shape_avl": str(loaded_avl.resolve()),
        "loaded_shape_fs_path": str(Path(fs_path).resolve()),
        "candidate_avl_artifact": str(candidate_artifact.resolve()),
        "pre_structure_cl": cl_required,
        "pre_structure_alpha_deg": pre_trim.get("aoa_trim_deg", ""),
        "loaded_shape_alpha_deg": loaded_trim.get("aoa_trim_deg", ""),
        "pre_structure_CDi": "" if pre_cdi is None else pre_cdi,
        "loaded_shape_CDi": "" if loaded_cdi is None else loaded_cdi,
        "delta_CDi_loaded_minus_pre": (
            "" if pre_cdi is None or loaded_cdi is None else float(loaded_cdi - pre_cdi)
        ),
        "pre_structure_e_CDi": "" if pre_e is None else pre_e,
        "loaded_shape_e_CDi": "" if loaded_e is None else loaded_e,
        "delta_e_CDi_loaded_minus_pre": (
            "" if pre_e is None or loaded_e is None else float(loaded_e - pre_e)
        ),
        "local_cl_max": max(local_cl_values),
        "local_cl_min": min(local_cl_values),
        "re_min": min(reynolds_values),
        "re_max": max(reynolds_values),
        "stall_margin_min": min(stall_margins),
        "stall_margin_basis": "diagnostic_constant_section_cl_limit_not_gate",
        "diagnostic_section_cl_limit": float(diagnostic_section_cl_limit),
        "root_bending_moment_pre_structure_nm": pre_root_bending,
        "root_bending_moment_loaded_shape_nm": loaded_root_bending,
        "root_bending_moment_ratio_loaded_vs_pre": (
            "" if abs(pre_root_bending) <= 1.0e-12 else float(loaded_root_bending / pre_root_bending)
        ),
        "bending_proxy_pre_structure_m": normalized_bending_proxy_m(pre_load),
        "bending_proxy_loaded_shape_m": normalized_bending_proxy_m(loaded_load),
        "target_main_tip_z_m": sweep_row.get("target_main_tip_z_m", ""),
        "effective_dihedral_deg": sweep_row.get("effective_dihedral_deg", ""),
        "tube_mass_kg": sweep_row.get("tube_mass_kg", ""),
        "total_structural_mass_kg": sweep_row.get("total_structural_mass_kg", ""),
        "jig_ground_clearance_min_m": sweep_row.get("jig_ground_clearance_min_m", ""),
        "loaded_shape_local_cl_re_envelope_csv": str(
            (case_dir / "loaded_shape_local_cl_re_envelope.csv").resolve()
        ),
        "loaded_shape_spanload_comparison_csv": str(
            (case_dir / "loaded_shape_spanload_comparison.csv").resolve()
        ),
    }
    warning_flags = aero_warning_flags(summary_row)
    summary_row["aero_warning_flags"] = "; ".join(warning_flags)
    if warning_flags:
        summary_row["status"] = "rechecked_for_screening_with_aero_warnings"
    return summary_row, comparison_rows, local_rows


def _select_case_rows(stage2_dir: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    sweep_rows = _read_csv_rows(stage2_dir / "z_state_structure_budget_sweep.csv")
    sweep_by_label = {str(row.get("case_label")): dict(row) for row in sweep_rows}
    shortlist_rows = _read_csv_rows(stage2_dir / "feasible_loaded_shape_shortlist.csv")
    if shortlist_rows:
        return [dict(row) for row in shortlist_rows], sweep_by_label
    feasible_rows = [
        dict(row)
        for row in sweep_rows
        if _boolish(row.get("feasible")) or _boolish(row.get("canonical_overall_feasible"))
    ]
    return feasible_rows, sweep_by_label


def _report_markdown(summary_rows: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Loaded-Shape AVL Recheck MVP",
        "",
        "This is a report-only MVP3 artifact. It does not change production ranking, add hard gates, rerun broad CST/NSGA, run broad FEM, or promote structure to final truth.",
        "",
        "## Geometry Basis",
        "",
        f"- AVL section z basis: `{GEOMETRY_Z_BASIS}`.",
        "- The Stage2 main-beam loaded-shape root Z offset is removed before AVL export; this is a beam-line proxy for aerodynamic-surface Z, not final geometry truth.",
        "- Baseline chord, twist, airfoil files, Sref/Cref/Bref, and AVL trim CL are inherited from the pre-structure smooth Tier2 AVL artifact.",
        "",
        "## Recheck Summary",
        "",
        "| case | CDi pre | CDi loaded | e_CDi pre | e_CDi loaded | max Cl | Re min | stall margin min | root bending ratio |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary_rows:
        lines.append(
            "| {case} | {pre_cdi} | {loaded_cdi} | {pre_e} | {loaded_e} | {clmax} | {remin} | {stall} | {bend} |".format(
                case=row.get("case_label", ""),
                pre_cdi=_fmt(row.get("pre_structure_CDi"), 6),
                loaded_cdi=_fmt(row.get("loaded_shape_CDi"), 6),
                pre_e=_fmt(row.get("pre_structure_e_CDi"), 4),
                loaded_e=_fmt(row.get("loaded_shape_e_CDi"), 4),
                clmax=_fmt(row.get("local_cl_max"), 3),
                remin=_fmt(row.get("re_min"), 0),
                stall=_fmt(row.get("stall_margin_min"), 3),
                bend=_fmt(row.get("root_bending_moment_ratio_loaded_vs_pre"), 3),
            )
        )
    warning_rows = [
        row for row in summary_rows if str(row.get("aero_warning_flags", "")).strip()
    ]
    lines.extend(
        [
            "",
            "## Warning Flags",
            "",
        ]
    )
    if warning_rows:
        for row in warning_rows:
            lines.append(
                f"- `{row.get('case_label', '')}`: {row.get('aero_warning_flags', '')}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Engineering Read",
            "",
            "- Treat any aerodynamic deltas as screening evidence because the Z transfer uses main-beam loaded shape as a proxy for aerodynamic-surface Z.",
            "- `e_CDi > 1` is kept as an AVL/reference-convention warning for this nonplanar loaded proxy, not as proof of a physically superior final wing.",
            "- A negative diagnostic stall margin is a warning for MVP4 airfoil selection, not a gate in this MVP.",
            "- The high-Z screening candidate remains structurally report-only; the recheck answers the aero consequence question, not final manufacturability.",
            "",
            "## Required Outputs",
            "",
            "- `loaded_shape_avl_recheck.csv`",
            "- `loaded_shape_spanload_comparison.csv`",
            "- `loaded_shape_local_cl_re_envelope.csv`",
            "- `loaded_shape_aero_recheck_report.md`",
        ]
    )
    return "\n".join(lines) + "\n"


def _fmt(value: Any, digits: int) -> str:
    parsed = _float_or_none(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:.{digits}f}"


def run_mvp(
    *,
    stage2_dir: Path,
    output_dir: Path,
    dynamic_viscosity_pa_s: float = DEFAULT_DYNAMIC_VISCOSITY_PA_S,
    diagnostic_section_cl_limit: float = DEFAULT_DIAGNOSTIC_SECTION_CL_LIMIT,
    avl_binary: str | Path | None = None,
) -> dict[str, Path]:
    case_rows, sweep_by_label = _select_case_rows(stage2_dir)
    if not case_rows:
        raise ValueError(f"No feasible/near-feasible Stage2 loaded-shape rows found in {stage2_dir}.")

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict[str, Any]] = []
    all_comparison_rows: list[dict[str, Any]] = []
    all_local_rows: list[dict[str, Any]] = []
    for case_row in case_rows:
        case_label = str(case_row["case_label"])
        sweep_row = sweep_by_label.get(case_label)
        if sweep_row is None:
            raise ValueError(f"Stage2 shortlist row has no sweep row for case_label={case_label!r}.")
        try:
            summary, comparison, local = _run_case(
                case_row=case_row,
                sweep_row=sweep_row,
                output_dir=output_dir,
                dynamic_viscosity_pa_s=dynamic_viscosity_pa_s,
                diagnostic_section_cl_limit=diagnostic_section_cl_limit,
                avl_binary=avl_binary,
            )
            summary_rows.append(summary)
            all_comparison_rows.extend(comparison)
            all_local_rows.extend(local)
        except Exception as exc:  # pragma: no cover - CLI artifact path for failed external AVL
            summary_rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "case_label": case_label,
                    "status": "avl_recheck_failed",
                    "error": str(exc),
                    "geometry_z_basis": GEOMETRY_Z_BASIS,
                }
            )

    paths = {
        "loaded_shape_avl_recheck": output_dir / "loaded_shape_avl_recheck.csv",
        "loaded_shape_spanload_comparison": output_dir / "loaded_shape_spanload_comparison.csv",
        "loaded_shape_local_cl_re_envelope": output_dir / "loaded_shape_local_cl_re_envelope.csv",
        "loaded_shape_aero_recheck_report": output_dir / "loaded_shape_aero_recheck_report.md",
        "manifest": output_dir / "loaded_shape_avl_recheck_manifest.json",
    }
    _write_csv(paths["loaded_shape_avl_recheck"], summary_rows)
    _write_csv(paths["loaded_shape_spanload_comparison"], all_comparison_rows)
    _write_csv(paths["loaded_shape_local_cl_re_envelope"], all_local_rows)
    paths["loaded_shape_aero_recheck_report"].write_text(
        _report_markdown(summary_rows),
        encoding="utf-8",
    )
    paths["manifest"].write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "stage2_dir": str(stage2_dir.resolve()),
                "output_dir": str(output_dir.resolve()),
                "case_count": len(case_rows),
                "geometry_z_basis": GEOMETRY_Z_BASIS,
                "diagnostic_section_cl_limit": float(diagnostic_section_cl_limit),
                "dynamic_viscosity_pa_s": float(dynamic_viscosity_pa_s),
                "artifacts": {name: str(path.resolve()) for name, path in paths.items()},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return paths


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage2-dir", type=Path, default=DEFAULT_STAGE2_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--dynamic-viscosity-pa-s",
        type=float,
        default=DEFAULT_DYNAMIC_VISCOSITY_PA_S,
    )
    parser.add_argument(
        "--diagnostic-section-cl-limit",
        type=float,
        default=DEFAULT_DIAGNOSTIC_SECTION_CL_LIMIT,
    )
    parser.add_argument("--avl-binary", default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    paths = run_mvp(
        stage2_dir=args.stage2_dir,
        output_dir=args.output_dir,
        dynamic_viscosity_pa_s=float(args.dynamic_viscosity_pa_s),
        diagnostic_section_cl_limit=float(args.diagnostic_section_cl_limit),
        avl_binary=args.avl_binary,
    )
    print("[pipeline-v2] MVP3 loaded-shape AVL recheck artifacts:")
    for path in paths.values():
        print(f"  - {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
