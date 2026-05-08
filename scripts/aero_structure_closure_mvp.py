#!/usr/bin/env python3
"""Pipeline v2 MVP 5: aero-structure closure after Tier2 airfoil selection.

This report-only closure step compares MVP4 selected-airfoil AVL reruns against
the MVP2 structure-budgeted loaded-Z result, then reruns the canonical
candidate-AVL-spanwise structure response with the same mass/recipe basis. It
does not change production ranking, add hard gates, run broad FEM, or promote
screening structure to final truth.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Mapping, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hpa_mdo.aero.avl_spanwise import (  # noqa: E402
    load_candidate_avl_spanwise_artifact,
    write_candidate_avl_spanwise_artifact,
)


DEFAULT_STAGE2_DIR = REPO_ROOT / "output/pipeline_redesign_v2/structure_budgeted_z_state_mvp"
DEFAULT_STAGE6_DIR = REPO_ROOT / "output/pipeline_redesign_v2/loaded_shape_avl_recheck_mvp"
DEFAULT_MVP4_DIR = REPO_ROOT / "output/pipeline_redesign_v2/tier2_loaded_shape_airfoil_mvp"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output/pipeline_redesign_v2/aero_structure_closure_mvp"
SCHEMA_VERSION = "aero_structure_closure_mvp_v1"
CLOSURE_STATUSES = {
    "closed_for_screening",
    "minor_mismatch",
    "loop_back_to_fourier_geometry",
    "loop_back_to_z_state",
    "loop_back_to_airfoil_selection",
}


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        if fieldnames:
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _csv_value(row.get(key, "")) for key in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict | list | tuple):
        return json.dumps(value, sort_keys=True)
    return value


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _pct_delta(new: Any, old: Any) -> float | None:
    new_f = _float_or_none(new)
    old_f = _float_or_none(old)
    if new_f is None or old_f is None or abs(old_f) <= 1.0e-12:
        return None
    return 100.0 * (new_f - old_f) / old_f


def _fmt(value: Any, digits: int = 3) -> str:
    parsed = _float_or_none(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:.{digits}f}"


def closure_status(
    *,
    actual_query_quality: str,
    structure_run_succeeded: bool,
    spanload_delta_pct: float | None,
    e_cdi_delta_pct: float | None,
    mass_delta_pct: float | None,
    deflection_delta_pct: float | None,
    clearance_margin_m: float | None,
) -> str:
    """Classify closure with report-only soft thresholds."""

    quality = str(actual_query_quality or "")
    if "warning" in quality or "not_mission_grade" in quality:
        return "loop_back_to_airfoil_selection"
    if not structure_run_succeeded:
        return "loop_back_to_z_state"
    if clearance_margin_m is not None and clearance_margin_m < 0.020:
        return "loop_back_to_z_state"
    if abs(float(mass_delta_pct or 0.0)) > 5.0 or abs(float(deflection_delta_pct or 0.0)) > 5.0:
        return "loop_back_to_z_state"
    if abs(float(spanload_delta_pct or 0.0)) > 7.5 or abs(float(e_cdi_delta_pct or 0.0)) > 7.5:
        return "loop_back_to_fourier_geometry"
    if (
        abs(float(spanload_delta_pct or 0.0)) <= 1.0
        and abs(float(e_cdi_delta_pct or 0.0)) <= 1.0
        and abs(float(mass_delta_pct or 0.0)) <= 1.0
        and abs(float(deflection_delta_pct or 0.0)) <= 1.0
    ):
        return "closed_for_screening"
    return "minor_mismatch"


def _baseline_stage2_row(stage2_dir: Path, case_label: str | None) -> dict[str, str]:
    sweep_rows = _read_csv_rows(stage2_dir / "z_state_structure_budget_sweep.csv")
    if not sweep_rows:
        raise FileNotFoundError(stage2_dir / "z_state_structure_budget_sweep.csv")
    if case_label:
        for row in sweep_rows:
            if str(row.get("case_label")) == str(case_label):
                return dict(row)
    shortlist = _read_csv_rows(stage2_dir / "feasible_loaded_shape_shortlist.csv")
    if shortlist:
        target = str(shortlist[0].get("case_label"))
        for row in sweep_rows:
            if str(row.get("case_label")) == target:
                return dict(row)
    return dict(sweep_rows[-1])


def _stage6_summary(stage6_dir: Path) -> dict[str, str]:
    rows = _read_csv_rows(stage6_dir / "loaded_shape_avl_recheck.csv")
    if not rows:
        raise FileNotFoundError(stage6_dir / "loaded_shape_avl_recheck.csv")
    return dict(rows[0])


def _selected_mvp4_rows(mvp4_dir: Path) -> list[dict[str, Any]]:
    payload = _read_json(mvp4_dir / "tier2_loaded_shape_airfoil_assignment.json")
    rows = [dict(row) for row in payload.get("selected_avl_reruns", []) if isinstance(row, Mapping)]
    rows = [row for row in rows if str(row.get("status", "")).endswith("_ok")]
    if rows:
        return rows
    fallback: list[dict[str, Any]] = []
    for role in ("raw_best", "conservative_best"):
        summary = payload.get(role, {}).get("summary", {})
        if isinstance(summary, Mapping):
            fallback.append({"selected_role": role, **dict(summary)})
    return fallback


def _velocity_density_from_stage2(row: Mapping[str, Any]) -> tuple[float, float]:
    artifact = Path(str(row.get("candidate_avl_artifact") or ""))
    if artifact.is_file():
        payload = _read_json(artifact)
        return float(payload.get("velocity_mps", 6.6)), float(payload.get("density_kgpm3", 1.18))
    return 6.6, 1.18


def _write_selected_candidate_artifact(
    *,
    selected: Mapping[str, Any],
    baseline_row: Mapping[str, Any],
    output_dir: Path,
) -> Path | None:
    avl_path = Path(str(selected.get("selected_airfoil_avl") or ""))
    fs_path = Path(str(selected.get("selected_airfoil_fs") or ""))
    if not avl_path.is_file() or not fs_path.is_file():
        return None
    role = str(selected.get("selected_role", "selected"))
    velocity, density = _velocity_density_from_stage2(baseline_row)
    target_shape_z_scale = _float_or_none(baseline_row.get("target_shape_z_scale_generator")) or 1.0
    dihedral_exponent = _float_or_none(baseline_row.get("dihedral_exponent")) or 1.0
    alpha = _float_or_none(selected.get("alpha_deg")) or 0.0
    artifact_path = output_dir / "candidate_avl_artifacts" / f"{role}_selected_airfoil_spanwise.json"
    return write_candidate_avl_spanwise_artifact(
        artifact_path,
        avl_path=avl_path,
        candidate_output_dir=fs_path.parent,
        requested_knobs={
            "target_shape_z_scale": float(target_shape_z_scale),
            "dihedral_multiplier": float(target_shape_z_scale),
            "dihedral_exponent": float(dihedral_exponent),
        },
        selected_cruise_aoa_deg=float(alpha),
        selected_cruise_aoa_source="mvp4_selected_airfoil_avl_trim",
        selected_load_state_owner="mvp4_selected_airfoil_loaded_shape_avl_rerun",
        velocity_mps=float(velocity),
        density_kgpm3=float(density),
        load_case_specs=[
            {
                "aoa_deg": float(alpha),
                "fs_path": fs_path,
                "stdout_log_path": fs_path.with_name("concept_spanwise_stdout.log"),
            }
        ],
        trim_force_path=fs_path.with_name("concept_trim.ft"),
        trim_stdout_log_path=fs_path.with_name("concept_trim_stdout.log"),
        target_surface_names=("Wing",),
        notes=(
            "Pipeline v2 MVP5 closure artifact from MVP4 selected-airfoil AVL rerun.",
            "Structure response remains daily-screening/report-only.",
        ),
    )


def _structure_command(
    *,
    baseline_row: Mapping[str, Any],
    case_dir: Path,
    candidate_artifact: Path,
) -> list[str]:
    target_mass = _float_or_none(baseline_row.get("canonical_total_structural_mass_target_kg"))
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts/direct_dual_beam_inverse_design.py"),
        "--config",
        str(baseline_row.get("config_path")),
        "--design-report",
        str(baseline_row.get("design_report")),
        "--output-dir",
        str(case_dir),
        "--aero-source-mode",
        "candidate_avl_spanwise",
        "--candidate-avl-spanwise-loads-json",
        str(candidate_artifact),
        "--target-shape-z-scale",
        f"{_float_or_none(baseline_row.get('target_shape_z_scale_generator')) or 1.0:.12g}",
        "--dihedral-exponent",
        f"{_float_or_none(baseline_row.get('dihedral_exponent')) or 1.0:.12g}",
        "--refresh-steps",
        "0",
        "--main-plateau-grid",
        "0.0,1.0",
        "--main-taper-fill-grid",
        "0.0,1.0",
        "--rear-radius-grid",
        "0.0,1.0",
        "--rear-outboard-grid",
        "0.0,1.0",
        "--wall-thickness-grid",
        "0.0,1.0",
        "--cobyla-maxiter",
        "40",
        "--rib-zonewise-mode",
        "limited_zonewise",
        "--skip-local-refine",
        "--skip-step-export",
        "--no-ground-clearance-recovery",
    ]
    if target_mass is not None:
        command.extend(["--target-mass-kg", f"{float(target_mass):.12g}"])
    return command


def _run_structure_response(
    *,
    role: str,
    baseline_row: Mapping[str, Any],
    candidate_artifact: Path | None,
    output_dir: Path,
    run_structure: bool,
    fixture_structure_summary_by_role: Mapping[str, Path] | None,
) -> tuple[dict[str, Any], Path | None]:
    fixture_path = None if fixture_structure_summary_by_role is None else fixture_structure_summary_by_role.get(role)
    if fixture_path is not None:
        return _parse_structure_summary(Path(fixture_path), case_dir=Path(fixture_path).parent), Path(fixture_path)
    if candidate_artifact is None:
        return {"run_succeeded": False, "error": "missing_selected_candidate_avl_artifact"}, None
    case_dir = output_dir / "runs" / role / "structure_response"
    summary_path = case_dir / "direct_dual_beam_inverse_design_refresh_summary.json"
    command = _structure_command(
        baseline_row=baseline_row,
        case_dir=case_dir,
        candidate_artifact=candidate_artifact,
    )
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "command.txt").write_text(shlex.join(command) + "\n", encoding="utf-8")
    if run_structure:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        (case_dir / "stdout.log").write_text(completed.stdout, encoding="utf-8")
        (case_dir / "stderr.log").write_text(completed.stderr, encoding="utf-8")
    if not summary_path.is_file():
        return {"run_succeeded": False, "summary_path": str(summary_path), "error": "summary_not_written"}, None
    return _parse_structure_summary(summary_path, case_dir=case_dir), summary_path


def _parse_structure_summary(path: Path, *, case_dir: Path) -> dict[str, Any]:
    payload = _read_json(path)
    selected = ((payload.get("iterations") or [{}])[-1].get("selected") or {})
    wire = _wire_metrics(case_dir)
    return {
        "run_succeeded": True,
        "summary_path": str(path.resolve()),
        "overall_feasible": bool(selected.get("overall_feasible", False)),
        "tube_mass_kg": selected.get("tube_mass_kg", ""),
        "total_structural_mass_kg": selected.get("total_structural_mass_kg", ""),
        "jig_ground_clearance_min_m": selected.get("jig_ground_clearance_min_m", ""),
        "equivalent_tip_deflection_m": selected.get("equivalent_tip_deflection_m", ""),
        "loaded_shape_error": selected.get(
            "loaded_shape_main_z_error_max_m",
            selected.get("target_shape_error_max_m", ""),
        ),
        "equivalent_twist_max_deg": selected.get("equivalent_twist_max_deg", ""),
        "equivalent_failure_index": selected.get("equivalent_failure_index", ""),
        "equivalent_buckling_index": selected.get("equivalent_buckling_index", ""),
        **wire,
    }


def _wire_metrics(case_dir: Path) -> dict[str, Any]:
    path = case_dir / "lift_wire_rigging.json"
    if not path.is_file():
        return {
            "wire_rigging_path": "",
            "wire_tension_n": "",
            "wire_min_tension_n": "",
            "wire_max_tension_n": "",
            "wire_slack_count": "",
        }
    payload = _read_json(path)
    wires = list(payload.get("wire_rigging") or [])
    tensions = [_float_or_none(wire.get("tension_force_n")) for wire in wires]
    clean = [float(value) for value in tensions if value is not None]
    return {
        "wire_rigging_path": str(path.resolve()),
        "wire_tension_n": max(clean) if clean else "",
        "wire_min_tension_n": min(clean) if clean else "",
        "wire_max_tension_n": max(clean) if clean else "",
        "wire_slack_count": sum(1 for value in clean if value <= 0.0),
    }


def _stage6_baseline_spanload(stage6_summary: Mapping[str, Any]) -> list[dict[str, float]]:
    comparison_path = Path(str(stage6_summary.get("loaded_shape_spanload_comparison_csv") or ""))
    rows = _read_csv_rows(comparison_path) if comparison_path.is_file() else []
    out: list[dict[str, float]] = []
    for row in rows:
        y_m = _float_or_none(row.get("y_m"))
        lift = _float_or_none(row.get("loaded_shape_lift_per_span_npm"))
        if y_m is not None and lift is not None:
            out.append({"y_m": float(y_m), "lift_per_span_npm": float(lift)})
    return out


def _selected_spanload_rows(
    *,
    role: str,
    artifact_path: Path | None,
    fixture_selected_spanload_by_role: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> list[dict[str, float]]:
    if fixture_selected_spanload_by_role is not None and role in fixture_selected_spanload_by_role:
        return [
            {
                "y_m": float(row["y_m"]),
                "lift_per_span_npm": float(row["lift_per_span_npm"]),
            }
            for row in fixture_selected_spanload_by_role[role]
        ]
    if artifact_path is None:
        return []
    _, cases = load_candidate_avl_spanwise_artifact(artifact_path)
    load = cases[0]
    return [
        {"y_m": float(y), "lift_per_span_npm": float(lift)}
        for y, lift in zip(load.y, load.lift_per_span, strict=True)
    ]


def spanload_delta_pct(
    baseline_rows: Sequence[Mapping[str, Any]],
    selected_rows: Sequence[Mapping[str, Any]],
) -> float | None:
    if len(baseline_rows) < 2 or len(selected_rows) < 2:
        return None
    base_y = np.asarray([float(row["y_m"]) for row in baseline_rows], dtype=float)
    base_lift = np.asarray([float(row["lift_per_span_npm"]) for row in baseline_rows], dtype=float)
    selected_y = np.asarray([float(row["y_m"]) for row in selected_rows], dtype=float)
    selected_lift = np.asarray([float(row["lift_per_span_npm"]) for row in selected_rows], dtype=float)
    y_min = max(float(base_y.min()), float(selected_y.min()))
    y_max = min(float(base_y.max()), float(selected_y.max()))
    if y_max <= y_min:
        return None
    y_common = np.linspace(y_min, y_max, 100)
    base_interp = np.interp(y_common, base_y, base_lift)
    selected_interp = np.interp(y_common, selected_y, selected_lift)
    base_total = float(np.trapezoid(base_interp, y_common))
    selected_total = float(np.trapezoid(selected_interp, y_common))
    if abs(base_total) <= 1.0e-12 or abs(selected_total) <= 1.0e-12:
        return None
    base_norm = base_interp / base_total
    selected_norm = selected_interp / selected_total
    denom = float(np.mean(np.abs(base_norm)))
    if denom <= 1.0e-12:
        return None
    return float(100.0 * np.sqrt(np.mean((selected_norm - base_norm) ** 2)) / denom)


def _summary_row(
    *,
    selected: Mapping[str, Any],
    baseline_row: Mapping[str, Any],
    stage6_row: Mapping[str, Any],
    structure: Mapping[str, Any],
    spanload_delta: float | None,
    candidate_artifact: Path | None,
) -> dict[str, Any]:
    e_delta = _pct_delta(selected.get("e_CDi"), stage6_row.get("loaded_shape_e_CDi"))
    mass_delta = _pct_delta(structure.get("total_structural_mass_kg"), baseline_row.get("total_structural_mass_kg"))
    deflection_delta = _pct_delta(
        structure.get("equivalent_tip_deflection_m"),
        baseline_row.get("equivalent_tip_deflection_m"),
    )
    clearance = _float_or_none(structure.get("jig_ground_clearance_min_m"))
    status = closure_status(
        actual_query_quality=str(selected.get("actual_query_quality", "")),
        structure_run_succeeded=bool(structure.get("run_succeeded")),
        spanload_delta_pct=spanload_delta,
        e_cdi_delta_pct=e_delta,
        mass_delta_pct=mass_delta,
        deflection_delta_pct=deflection_delta,
        clearance_margin_m=clearance,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "selected_role": selected.get("selected_role", ""),
        "assignment": selected.get("assignment", ""),
        "closure_status": status,
        "selected_airfoil_avl_status": selected.get("status", ""),
        "selected_candidate_avl_artifact": "" if candidate_artifact is None else str(candidate_artifact.resolve()),
        "structure_summary_path": structure.get("summary_path", ""),
        "structure_run_succeeded": bool(structure.get("run_succeeded")),
        "stage6_loaded_shape_CDi": stage6_row.get("loaded_shape_CDi", ""),
        "selected_airfoil_CDi": selected.get("CDi", ""),
        "closure_CDi_delta_pct": _pct_delta(selected.get("CDi"), stage6_row.get("loaded_shape_CDi")),
        "stage6_loaded_shape_e_CDi": stage6_row.get("loaded_shape_e_CDi", ""),
        "selected_airfoil_e_CDi": selected.get("e_CDi", ""),
        "closure_e_CDi_delta_pct": e_delta,
        "closure_spanload_delta_pct": spanload_delta,
        "baseline_total_structural_mass_kg": baseline_row.get("total_structural_mass_kg", ""),
        "closure_total_structural_mass_kg": structure.get("total_structural_mass_kg", ""),
        "closure_mass_delta_pct": mass_delta,
        "baseline_equivalent_tip_deflection_m": baseline_row.get("equivalent_tip_deflection_m", ""),
        "closure_equivalent_tip_deflection_m": structure.get("equivalent_tip_deflection_m", ""),
        "closure_deflection_delta_pct": deflection_delta,
        "baseline_jig_ground_clearance_min_m": baseline_row.get("jig_ground_clearance_min_m", ""),
        "closure_jig_ground_clearance_min_m": structure.get("jig_ground_clearance_min_m", ""),
        "closure_clearance_delta_m": (
            None
            if _float_or_none(structure.get("jig_ground_clearance_min_m")) is None
            or _float_or_none(baseline_row.get("jig_ground_clearance_min_m")) is None
            else float(structure["jig_ground_clearance_min_m"]) - float(baseline_row["jig_ground_clearance_min_m"])
        ),
        "baseline_wire_tension_n": baseline_row.get("wire_tension_n", ""),
        "closure_wire_tension_n": structure.get("wire_tension_n", ""),
        "closure_wire_tension_delta_pct": _pct_delta(structure.get("wire_tension_n"), baseline_row.get("wire_tension_n")),
        "closure_loaded_shape_error": structure.get("loaded_shape_error", ""),
        "selected_profile_cd": selected.get("profile_cd", ""),
        "selected_P_crank": selected.get("P_crank", ""),
        "selected_P_crank_conservative": selected.get("P_crank_conservative", ""),
        "actual_query_quality": selected.get("actual_query_quality", ""),
        "structure_trust_label": "daily_screening_not_final_truth",
    }


def _report_markdown(rows: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Aero-Structure Closure MVP",
        "",
        "This is a report-only MVP5 artifact. It does not change production ranking, add hard gates, run broad FEM, or promote structure to final truth.",
        "",
        "## Closure Summary",
        "",
        "| role | status | e_CDi delta % | spanload delta % | mass delta % | deflection delta % | clearance m | query quality |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            "| {role} | `{status}` | {e} | {span} | {mass} | {defl} | {clearance} | {quality} |".format(
                role=row.get("selected_role", ""),
                status=row.get("closure_status", ""),
                e=_fmt(row.get("closure_e_CDi_delta_pct"), 2),
                span=_fmt(row.get("closure_spanload_delta_pct"), 2),
                mass=_fmt(row.get("closure_mass_delta_pct"), 2),
                defl=_fmt(row.get("closure_deflection_delta_pct"), 2),
                clearance=_fmt(row.get("closure_jig_ground_clearance_min_m"), 4),
                quality=row.get("actual_query_quality", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Engineering Read",
            "",
            "- `closed_for_screening` still means daily-screening closure only, not final structural truth.",
            "- Airfoil query warnings route to airfoil-selection loopback before structure conclusions are promoted.",
            "- Large spanload or e_CDi deltas indicate the Fourier/geometry aero bridge should be revisited before claiming closure.",
            "- Mass, clearance, and deflection mismatches route back to the Z-state structure basis.",
        ]
    )
    return "\n".join(lines) + "\n"


def _loopback_markdown(rows: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(row.get("closure_status", "")) for row in rows}
    lines = [
        "# Closure Loopback Recommendation",
        "",
        "## Status Mix",
        "",
    ]
    for status in sorted(statuses):
        lines.append(f"- `{status}`")
    lines.extend(["", "## Recommendation", ""])
    if "loop_back_to_airfoil_selection" in statuses:
        lines.append("- Loopback to MVP4 airfoil selection for any role with query-quality warnings before treating drag wins as production candidates.")
    if "loop_back_to_z_state" in statuses:
        lines.append("- Loopback to MVP2 Z-state structure basis for mass, clearance, deflection, or failed structure-response mismatch.")
    if "loop_back_to_fourier_geometry" in statuses:
        lines.append("- Loopback to Fourier/geometry realization because the selected-airfoil spanload changed too much for closure.")
    if statuses <= {"closed_for_screening", "minor_mismatch"}:
        lines.append("- No immediate loopback is required for screening; carry the conservative row into the structural trust layer as diagnostic evidence.")
    return "\n".join(lines) + "\n"


def _normalize_generated_text_files(output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        path.write_text("\n".join(line.rstrip() for line in text.splitlines()) + "\n", encoding="utf-8")


def run_mvp(
    *,
    stage2_dir: Path = DEFAULT_STAGE2_DIR,
    stage6_dir: Path = DEFAULT_STAGE6_DIR,
    mvp4_dir: Path = DEFAULT_MVP4_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    run_structure: bool = True,
    fixture_structure_summary_by_role: Mapping[str, Path] | None = None,
    fixture_selected_spanload_by_role: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Path]:
    stage6_row = _stage6_summary(Path(stage6_dir))
    baseline_row = _baseline_stage2_row(Path(stage2_dir), stage6_row.get("case_label"))
    selected_rows = _selected_mvp4_rows(Path(mvp4_dir))
    if not selected_rows:
        raise ValueError(f"No selected MVP4 AVL reruns found in {mvp4_dir}.")
    baseline_spanload = _stage6_baseline_spanload(stage6_row)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict[str, Any]] = []
    for selected in selected_rows:
        role = str(selected.get("selected_role", "selected"))
        candidate_artifact = _write_selected_candidate_artifact(
            selected=selected,
            baseline_row=baseline_row,
            output_dir=output_dir,
        )
        structure, _summary_path = _run_structure_response(
            role=role,
            baseline_row=baseline_row,
            candidate_artifact=candidate_artifact,
            output_dir=output_dir,
            run_structure=run_structure,
            fixture_structure_summary_by_role=fixture_structure_summary_by_role,
        )
        selected_spanload = _selected_spanload_rows(
            role=role,
            artifact_path=candidate_artifact,
            fixture_selected_spanload_by_role=fixture_selected_spanload_by_role,
        )
        summary_rows.append(
            _summary_row(
                selected=selected,
                baseline_row=baseline_row,
                stage6_row=stage6_row,
                structure=structure,
                spanload_delta=spanload_delta_pct(baseline_spanload, selected_spanload),
                candidate_artifact=candidate_artifact,
            )
        )
    paths = {
        "summary": output_dir / "aero_structure_closure_summary.csv",
        "report": output_dir / "aero_structure_closure_report.md",
        "loopback": output_dir / "closure_loopback_recommendation.md",
    }
    _write_csv(paths["summary"], summary_rows)
    paths["report"].write_text(_report_markdown(summary_rows), encoding="utf-8")
    paths["loopback"].write_text(_loopback_markdown(summary_rows), encoding="utf-8")
    _normalize_generated_text_files(output_dir)
    return paths


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage2-dir", type=Path, default=DEFAULT_STAGE2_DIR)
    parser.add_argument("--stage6-dir", type=Path, default=DEFAULT_STAGE6_DIR)
    parser.add_argument("--mvp4-dir", type=Path, default=DEFAULT_MVP4_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skip-structure-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    paths = run_mvp(
        stage2_dir=args.stage2_dir,
        stage6_dir=args.stage6_dir,
        mvp4_dir=args.mvp4_dir,
        output_dir=args.output_dir,
        run_structure=not bool(args.skip_structure_run),
    )
    print("[pipeline-v2] MVP5 aero-structure closure artifacts:")
    for path in paths.values():
        print(f"  - {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
