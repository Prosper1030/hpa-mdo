#!/usr/bin/env python3
"""Run a structure-budgeted loaded-Z state search with the canonical inverse route."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hpa_mdo.aero.avl_spanwise import write_candidate_avl_spanwise_artifact  # noqa: E402
from scripts.run_phase10_2_canonical_inverse_design_check import (  # noqa: E402
    SMOOTH_AVL_RUN_DIR,
    SMOOTH_BASELINE_DIR,
    SMOOTH_PROD_GEOM_DIR,
    SMOOTH_RHO_KGPM3,
    SMOOTH_VELOCITY_MPS,
    build_smooth_canonical_config,
    smooth_aero_summary_row,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase11_structure_budgeted_z_state_search_mvp"
DEFAULT_SECTION_TABLE = SMOOTH_PROD_GEOM_DIR / "section_table.csv"
DEFAULT_AVL_PATH = SMOOTH_PROD_GEOM_DIR / "smooth_tier2_production_baseline.avl"
DEFAULT_AERO_SUMMARY = SMOOTH_BASELINE_DIR / "aerodynamic_summary.csv"
DEFAULT_DESIGN_REPORT = REPO_ROOT / "output" / "blackcat_004" / "ansys" / "crossval_report.txt"
FALLBACK_DESIGN_REPORT = (
    REPO_ROOT
    / "output"
    / "_archive_pre_2026_04_15"
    / "blackcat_004_dual_beam_production_check"
    / "ansys"
    / "crossval_report.txt"
)
PHASE10_BASE_SUMMARY = (
    REPO_ROOT
    / "output"
    / "phase10_2_canonical_inverse_design_check"
    / "smooth_tier2_canonical_run"
    / "direct_dual_beam_inverse_design_refresh_summary.json"
)
PHASE10_BASE_TARGET_CSV = PHASE10_BASE_SUMMARY.with_name("target_loaded_shape_spar_data.csv")
OLD_X4_EQUIVALENT_TARGET_MAIN_TIP_Z_M = 4.25
DEFAULT_EFFECTIVE_DIHEDRAL_DEG = "5,6,7,8,8.5,9"
DEFAULT_TARGET_MAIN_TIP_Z_M = "2.65,2.675,2.70"
DEFAULT_SPANWISE_FS_NAME = "concept_spanwise.fs"
DEFAULT_TRIM_FT_NAME = "concept_trim.ft"
DEFAULT_HEALTHY_CLEARANCE_M = 0.020
DEFAULT_LOADED_SHAPE_ERROR_TOL_M = 0.005
DEFAULT_SPAR_TUBE_MASS_TARGET_KG = 11.5


@dataclass(frozen=True)
class ZStateRequest:
    label: str
    target_main_tip_z_m: float
    source: str
    requested_effective_dihedral_deg: float | None


def fnum(value: Any, digits: int = 3) -> str:
    number = _float(value)
    if not math.isfinite(number):
        return "n/a"
    return f"{number:.{digits}f}"


def _float(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _isfinite(value: Any) -> bool:
    return math.isfinite(_float(value))


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        keys: list[str] = []
        for row in rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
    else:
        keys = list(fields)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in keys})


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _tip_z_from_shape_dict(shape: Mapping[str, Any]) -> tuple[float, float]:
    main_nodes = shape.get("main_nodes_m") or []
    rear_nodes = shape.get("rear_nodes_m") or []
    main_tip = main_nodes[-1] if main_nodes else [float("nan"), float("nan"), float("nan")]
    rear_tip = rear_nodes[-1] if rear_nodes else [float("nan"), float("nan"), float("nan")]
    return _float(main_tip[2]), _float(rear_tip[2])


def _root_z_from_shape_dict(shape: Mapping[str, Any]) -> tuple[float, float]:
    main_nodes = shape.get("main_nodes_m") or []
    rear_nodes = shape.get("rear_nodes_m") or []
    main_root = main_nodes[0] if main_nodes else [float("nan"), float("nan"), float("nan")]
    rear_root = rear_nodes[0] if rear_nodes else [float("nan"), float("nan"), float("nan")]
    return _float(main_root[2]), _float(rear_root[2])


def _target_tip_from_csv(path: Path) -> tuple[float, float]:
    rows = _read_csv_rows(path)
    if not rows:
        raise ValueError(f"Target shape CSV is empty: {path}")
    tip = rows[-1]
    return _float(tip["Main_Z_m"]), _float(tip["Rear_Z_m"])


def _parse_float_list(text: str | None) -> list[float]:
    if not text:
        return []
    values: list[float] = []
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        value = _float(part)
        if not math.isfinite(value):
            raise ValueError(f"Could not parse numeric sweep value: {part!r}")
        values.append(value)
    return values


def _case_label(target_main_tip_z_m: float) -> str:
    return f"target_main_tip_z_{target_main_tip_z_m:.3f}m".replace(".", "p")


def target_main_tip_z_for_effective_dihedral(effective_dihedral_deg_value: float, semi_span_m: float) -> float:
    if semi_span_m <= 0.0:
        raise ValueError("semi_span_m must be positive.")
    return math.tan(math.radians(float(effective_dihedral_deg_value))) * float(semi_span_m)


def effective_dihedral_deg(z_tip_m: float, semi_span_m: float) -> float:
    if semi_span_m <= 0.0:
        raise ValueError("semi_span_m must be positive.")
    return round(math.degrees(math.atan2(float(z_tip_m), float(semi_span_m))), 12)


def unique_z_state_requests(
    *,
    semi_span_m: float,
    effective_dihedral_deg_values: Sequence[float],
    target_main_tip_z_m_values: Sequence[float],
    include_old_x4_equivalent: bool,
) -> list[ZStateRequest]:
    requests: dict[float, ZStateRequest] = {}

    for deg in effective_dihedral_deg_values:
        if deg <= 0.0:
            raise ValueError("Effective dihedral targets must be positive.")
        target_z = target_main_tip_z_for_effective_dihedral(deg, semi_span_m)
        key = round(target_z, 6)
        requests.setdefault(
            key,
            ZStateRequest(
                label=_case_label(target_z),
                target_main_tip_z_m=target_z,
                source="effective_dihedral_deg",
                requested_effective_dihedral_deg=float(deg),
            ),
        )

    for target_z in target_main_tip_z_m_values:
        if target_z <= 0.0:
            raise ValueError("Target main-tip Z states must be positive.")
        key = round(float(target_z), 6)
        requests.setdefault(
            key,
            ZStateRequest(
                label=_case_label(float(target_z)),
                target_main_tip_z_m=float(target_z),
                source="target_main_tip_z_m",
                requested_effective_dihedral_deg=None,
            ),
        )

    if include_old_x4_equivalent:
        target_z = OLD_X4_EQUIVALENT_TARGET_MAIN_TIP_Z_M
        requests.setdefault(
            round(target_z, 6),
            ZStateRequest(
                label=_case_label(target_z),
                target_main_tip_z_m=target_z,
                source="old_x4_equivalent",
                requested_effective_dihedral_deg=None,
            ),
        )

    return [requests[key] for key in sorted(requests)]


def shortlist_status(
    *,
    request: ZStateRequest,
    actual_target_main_tip_z_m: float,
    semi_span_m: float,
    tube_mass_kg: float,
    total_structural_mass_kg: float,
    jig_ground_clearance_min_m: float,
    loaded_shape_error_m: float,
    spar_tube_mass_target_kg: float,
    healthy_clearance_m: float,
    loaded_shape_error_tol_m: float = DEFAULT_LOADED_SHAPE_ERROR_TOL_M,
) -> dict[str, Any]:
    meets_mass = _isfinite(tube_mass_kg) and float(tube_mass_kg) <= float(spar_tube_mass_target_kg)
    healthy_clearance = _isfinite(jig_ground_clearance_min_m) and float(jig_ground_clearance_min_m) >= float(healthy_clearance_m)
    loaded_shape_ok = _isfinite(loaded_shape_error_m) and abs(float(loaded_shape_error_m)) <= float(loaded_shape_error_tol_m)
    effective_deg = effective_dihedral_deg(actual_target_main_tip_z_m, semi_span_m)
    return {
        "case_label": request.label,
        "target_main_tip_z_m": float(actual_target_main_tip_z_m),
        "target_source": request.source,
        "requested_effective_dihedral_deg": request.requested_effective_dihedral_deg,
        "effective_dihedral_deg": effective_deg,
        "tube_mass_kg": tube_mass_kg,
        "total_structural_mass_kg": total_structural_mass_kg,
        "tube_mass_margin_kg": float(spar_tube_mass_target_kg) - _float(tube_mass_kg),
        "jig_ground_clearance_min_m": jig_ground_clearance_min_m,
        "clearance_margin_vs_healthy_m": _float(jig_ground_clearance_min_m) - float(healthy_clearance_m),
        "loaded_shape_error_m": loaded_shape_error_m,
        "meets_tube_mass_target": bool(meets_mass),
        "healthy_clearance": bool(healthy_clearance),
        "loaded_shape_error_ok": bool(loaded_shape_ok),
        "recommended_for_avl_recheck": bool(meets_mass and healthy_clearance and loaded_shape_ok),
    }


def _section_z_audit(section_table: Path) -> dict[str, Any]:
    rows = _read_csv_rows(section_table)
    if not rows:
        raise ValueError(f"Section table is empty: {section_table}")
    root = rows[0]
    tip = rows[-1]
    semi_span = max(_float(row.get("y_m")) for row in rows)
    root_z = _float(root.get("z_m"))
    tip_z = _float(tip.get("z_m"))
    return {
        "section_table": str(section_table.resolve()),
        "semi_span_m": semi_span,
        "root_z_reference_m": root_z,
        "aerodynamic_tip_z_m": tip_z,
        "built_in_geometric_z_m": tip_z - root_z,
        "aerodynamic_effective_dihedral_deg": effective_dihedral_deg(tip_z - root_z, semi_span),
        "root_chord_m": _float(root.get("chord_m")),
        "tip_chord_m": _float(tip.get("chord_m")),
        "section_count": len(rows),
    }


def _base_canonical_target_shape() -> dict[str, Any]:
    if PHASE10_BASE_SUMMARY.exists():
        summary = _read_json(PHASE10_BASE_SUMMARY)
        selected = ((summary.get("iterations") or [{}])[-1].get("selected") or {})
        target_shape = selected.get("target_loaded_shape") or {}
        main_tip_z, rear_tip_z = _tip_z_from_shape_dict(target_shape)
        main_root_z, rear_root_z = _root_z_from_shape_dict(target_shape)
        if math.isfinite(main_tip_z):
            return {
                "source": str(PHASE10_BASE_SUMMARY.resolve()),
                "target_main_tip_z_m": main_tip_z,
                "target_rear_tip_z_m": rear_tip_z,
                "target_main_root_z_m": main_root_z,
                "target_rear_root_z_m": rear_root_z,
                "elastic_deflection_z_m": _float(selected.get("equivalent_tip_deflection_m")),
                "target_shape_error_max_m": _float(selected.get("target_shape_error_max_m")),
                "loaded_shape_main_z_error_max_m": _float(selected.get("loaded_shape_main_z_error_max_m")),
            }
    if PHASE10_BASE_TARGET_CSV.exists():
        main_tip_z, rear_tip_z = _target_tip_from_csv(PHASE10_BASE_TARGET_CSV)
        rows = _read_csv_rows(PHASE10_BASE_TARGET_CSV)
        return {
            "source": str(PHASE10_BASE_TARGET_CSV.resolve()),
            "target_main_tip_z_m": main_tip_z,
            "target_rear_tip_z_m": rear_tip_z,
            "target_main_root_z_m": _float(rows[0]["Main_Z_m"]) if rows else float("nan"),
            "target_rear_root_z_m": _float(rows[0]["Rear_Z_m"]) if rows else float("nan"),
            "elastic_deflection_z_m": float("nan"),
            "target_shape_error_max_m": float("nan"),
            "loaded_shape_main_z_error_max_m": float("nan"),
        }
    section = _section_z_audit(DEFAULT_SECTION_TABLE)
    return {
        "source": str(DEFAULT_SECTION_TABLE.resolve()),
        "target_main_tip_z_m": section["aerodynamic_tip_z_m"],
        "target_rear_tip_z_m": section["aerodynamic_tip_z_m"],
        "target_main_root_z_m": section["root_z_reference_m"],
        "target_rear_root_z_m": section["root_z_reference_m"],
        "elastic_deflection_z_m": float("nan"),
        "target_shape_error_max_m": float("nan"),
        "loaded_shape_main_z_error_max_m": float("nan"),
    }


def _base_main_tip_z_m() -> float:
    return float(_base_canonical_target_shape()["target_main_tip_z_m"])


def _select_design_report(path: Path | None) -> Path:
    if path is not None:
        if not path.exists():
            raise FileNotFoundError(path)
        return path
    if DEFAULT_DESIGN_REPORT.exists():
        return DEFAULT_DESIGN_REPORT
    if FALLBACK_DESIGN_REPORT.exists():
        return FALLBACK_DESIGN_REPORT
    raise FileNotFoundError(f"No design report found: {DEFAULT_DESIGN_REPORT} or {FALLBACK_DESIGN_REPORT}")


def _write_candidate_avl_artifact(
    *,
    artifact_path: Path,
    avl_path: Path,
    avl_run_dir: Path,
    target_shape_z_scale: float,
    dihedral_exponent: float,
    selected_cruise_aoa_deg: float,
    velocity_mps: float,
    density_kgpm3: float,
) -> None:
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    write_candidate_avl_spanwise_artifact(
        artifact_path,
        avl_path=avl_path,
        candidate_output_dir=avl_run_dir,
        requested_knobs={
            "target_shape_z_scale": float(target_shape_z_scale),
            "dihedral_multiplier": float(target_shape_z_scale),
            "dihedral_exponent": float(dihedral_exponent),
        },
        selected_cruise_aoa_deg=float(selected_cruise_aoa_deg),
        selected_cruise_aoa_source="smooth_tier2_avl_trim_alpha_at_CL_req",
        selected_load_state_owner="smooth_tier2_avl_trim_and_gates",
        velocity_mps=velocity_mps,
        density_kgpm3=density_kgpm3,
        load_case_specs=[
            {
                "aoa_deg": float(selected_cruise_aoa_deg),
                "fs_path": avl_run_dir / DEFAULT_SPANWISE_FS_NAME,
                "stdout_log_path": avl_run_dir / "concept_spanwise_stdout.log",
            }
        ],
        trim_force_path=avl_run_dir / DEFAULT_TRIM_FT_NAME,
        trim_stdout_log_path=avl_run_dir / "concept_trim_stdout.log",
        target_surface_names=("Wing",),
        notes=(
            "Phase 11 structure-budgeted z-state search artifact: candidate AVL strip-force shape is held fixed.",
            "target_shape_z_scale is only the generator knob; reported target Z comes from selected.target_loaded_shape.",
            "refresh_steps=0 is used by default for MVP comparability.",
        ),
    )


def _copy_candidate_artifact_with_knobs(
    *,
    source_path: Path,
    artifact_path: Path,
    target_shape_z_scale: float,
    dihedral_exponent: float,
) -> None:
    payload = _read_json(source_path)
    payload["requested_knobs"] = {
        "target_shape_z_scale": float(target_shape_z_scale),
        "dihedral_multiplier": float(target_shape_z_scale),
        "dihedral_exponent": float(dihedral_exponent),
    }
    notes = list(payload.get("notes") or [])
    notes.append("Phase 11 copied spanwise-load artifact with updated requested z-state knobs.")
    payload["notes"] = notes
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _wire_metrics(case_dir: Path) -> dict[str, Any]:
    path = case_dir / "lift_wire_rigging.json"
    if not path.exists():
        return {
            "wire_rigging_path": "",
            "wire_count": "",
            "wire_min_tension_n": "",
            "wire_max_tension_n": "",
            "wire_min_tension_margin_n": "",
            "wire_slack_count": "",
        }
    payload = _read_json(path)
    wires = list(payload.get("wire_rigging") or [])
    tensions = [_float(wire.get("tension_force_n")) for wire in wires if _isfinite(wire.get("tension_force_n"))]
    margins = [_float(wire.get("tension_margin_n")) for wire in wires if _isfinite(wire.get("tension_margin_n"))]
    return {
        "wire_rigging_path": str(path.resolve()),
        "wire_count": len(wires),
        "wire_min_tension_n": min(tensions) if tensions else "",
        "wire_max_tension_n": max(tensions) if tensions else "",
        "wire_min_tension_margin_n": min(margins) if margins else "",
        "wire_slack_count": sum(1 for value in tensions if value <= 0.0),
    }


def _command_for_case(
    *,
    config_path: Path,
    design_report: Path,
    case_dir: Path,
    candidate_avl_artifact: Path,
    target_shape_z_scale: float,
    dihedral_exponent: float,
    refresh_steps: int,
    skip_local_refine: bool,
    skip_step_export: bool,
    no_ground_clearance_recovery: bool,
    cobyla_maxiter: int,
    rib_zonewise_mode: str,
) -> list[str]:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "direct_dual_beam_inverse_design.py"),
        "--config",
        str(config_path),
        "--design-report",
        str(design_report),
        "--output-dir",
        str(case_dir),
        "--aero-source-mode",
        "candidate_avl_spanwise",
        "--candidate-avl-spanwise-loads-json",
        str(candidate_avl_artifact),
        "--target-shape-z-scale",
        f"{target_shape_z_scale:.12g}",
        "--dihedral-exponent",
        f"{float(dihedral_exponent):.12g}",
        "--refresh-steps",
        str(int(refresh_steps)),
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
        str(int(cobyla_maxiter)),
        "--rib-zonewise-mode",
        str(rib_zonewise_mode),
    ]
    if skip_local_refine:
        command.append("--skip-local-refine")
    if skip_step_export:
        command.append("--skip-step-export")
    if no_ground_clearance_recovery:
        command.append("--no-ground-clearance-recovery")
    return command


def _run_case(
    *,
    request: ZStateRequest,
    output_dir: Path,
    config_path: Path,
    design_report: Path,
    semi_span_m: float,
    base_main_tip_z_m: float,
    avl_path: Path,
    avl_run_dir: Path,
    source_candidate_artifact: Path | None,
    selected_cruise_aoa_deg: float,
    velocity_mps: float,
    density_kgpm3: float,
    dihedral_exponent: float,
    refresh_steps: int,
    skip_local_refine: bool,
    skip_step_export: bool,
    no_ground_clearance_recovery: bool,
    cobyla_maxiter: int,
    rib_zonewise_mode: str,
    spar_tube_mass_target_kg: float,
    healthy_clearance_m: float,
    loaded_shape_error_tol_m: float,
    rerun: bool,
) -> dict[str, Any]:
    case_dir = output_dir / "runs" / request.label
    summary_path = case_dir / "direct_dual_beam_inverse_design_refresh_summary.json"
    target_shape_z_scale = request.target_main_tip_z_m / max(base_main_tip_z_m, 1.0e-9)
    artifact_path = output_dir / "candidate_avl_artifacts" / f"{request.label}.json"

    if source_candidate_artifact is not None:
        _copy_candidate_artifact_with_knobs(
            source_path=source_candidate_artifact,
            artifact_path=artifact_path,
            target_shape_z_scale=target_shape_z_scale,
            dihedral_exponent=dihedral_exponent,
        )
    else:
        _write_candidate_avl_artifact(
            artifact_path=artifact_path,
            avl_path=avl_path,
            avl_run_dir=avl_run_dir,
            target_shape_z_scale=target_shape_z_scale,
            dihedral_exponent=dihedral_exponent,
            selected_cruise_aoa_deg=selected_cruise_aoa_deg,
            velocity_mps=velocity_mps,
            density_kgpm3=density_kgpm3,
        )

    command = _command_for_case(
        config_path=config_path,
        design_report=design_report,
        case_dir=case_dir,
        candidate_avl_artifact=artifact_path,
        target_shape_z_scale=target_shape_z_scale,
        dihedral_exponent=dihedral_exponent,
        refresh_steps=refresh_steps,
        skip_local_refine=skip_local_refine,
        skip_step_export=skip_step_export,
        no_ground_clearance_recovery=no_ground_clearance_recovery,
        cobyla_maxiter=cobyla_maxiter,
        rib_zonewise_mode=rib_zonewise_mode,
    )

    if rerun or not summary_path.exists():
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "command.txt").write_text(shlex.join(command) + "\n", encoding="utf-8")
        (case_dir / "stdout.log").write_text(completed.stdout, encoding="utf-8")
        (case_dir / "stderr.log").write_text(completed.stderr, encoding="utf-8")
        returncode = int(completed.returncode)
    else:
        returncode = 0

    row: dict[str, Any] = {
        "case_label": request.label,
        "target_source": request.source,
        "requested_effective_dihedral_deg": request.requested_effective_dihedral_deg,
        "requested_target_main_tip_z_m": request.target_main_tip_z_m,
        "target_shape_z_scale_generator": target_shape_z_scale,
        "dihedral_exponent": dihedral_exponent,
        "refresh_steps": refresh_steps,
        "returncode": returncode,
        "run_succeeded": summary_path.exists() and returncode == 0,
        "canonical_entrypoint": str((REPO_ROOT / "scripts" / "direct_dual_beam_inverse_design.py").resolve()),
        "canonical_command_txt_path": str((case_dir / "command.txt").resolve()),
        "canonical_command_used": shlex.join(command),
        "case_dir": str(case_dir.resolve()),
        "summary_path": str(summary_path.resolve()) if summary_path.exists() else "",
        "candidate_avl_artifact": str(artifact_path.resolve()),
        "config_path": str(config_path.resolve()),
        "design_report": str(design_report.resolve()),
    }
    if not summary_path.exists():
        row["feasible"] = False
        row["message"] = "summary_not_written"
        return row

    summary = _read_json(summary_path)
    final_iteration = (summary.get("iterations") or [{}])[-1]
    selected = final_iteration.get("selected") or {}
    target_shape = selected.get("target_loaded_shape") or {}
    target_main_tip_z, target_rear_tip_z = _tip_z_from_shape_dict(target_shape)
    target_root_main_z, target_root_rear_z = _root_z_from_shape_dict(target_shape)
    target_main_tip_z_for_status = target_main_tip_z if math.isfinite(target_main_tip_z) else request.target_main_tip_z_m
    loaded_shape_error = _float(
        selected.get("loaded_shape_main_z_error_max_m"),
        _float(selected.get("target_shape_error_max_m")),
    )
    status = shortlist_status(
        request=request,
        actual_target_main_tip_z_m=target_main_tip_z_for_status,
        semi_span_m=semi_span_m,
        tube_mass_kg=_float(selected.get("tube_mass_kg")),
        total_structural_mass_kg=_float(selected.get("total_structural_mass_kg")),
        jig_ground_clearance_min_m=_float(selected.get("jig_ground_clearance_min_m")),
        loaded_shape_error_m=loaded_shape_error,
        spar_tube_mass_target_kg=spar_tube_mass_target_kg,
        healthy_clearance_m=healthy_clearance_m,
        loaded_shape_error_tol_m=loaded_shape_error_tol_m,
    )

    canonical_overall_feasible = bool(selected.get("overall_feasible"))
    row.update(
        {
            "target_main_tip_z_m": target_main_tip_z_for_status,
            "target_rear_tip_z_m": target_rear_tip_z,
            "target_root_main_z_m": target_root_main_z,
            "target_root_rear_z_m": target_root_rear_z,
            "effective_dihedral_deg": status["effective_dihedral_deg"],
            "canonical_overall_feasible": canonical_overall_feasible,
            "feasible": bool(canonical_overall_feasible and status["recommended_for_avl_recheck"]),
            "tube_mass_kg": status["tube_mass_kg"],
            "total_structural_mass_kg": status["total_structural_mass_kg"],
            "spar_tube_mass_target_kg": spar_tube_mass_target_kg,
            "tube_mass_margin_kg": status["tube_mass_margin_kg"],
            "meets_tube_mass_target": status["meets_tube_mass_target"],
            "jig_ground_clearance_min_m": status["jig_ground_clearance_min_m"],
            "healthy_clearance_m": healthy_clearance_m,
            "clearance_margin_vs_healthy_m": status["clearance_margin_vs_healthy_m"],
            "healthy_clearance": status["healthy_clearance"],
            "max_jig_prebend_m": selected.get("max_jig_vertical_prebend_m"),
            "max_jig_vertical_curvature_per_m": selected.get("max_jig_vertical_curvature_per_m"),
            "loaded_shape_error": loaded_shape_error,
            "loaded_shape_error_tol_m": loaded_shape_error_tol_m,
            "loaded_shape_error_ok": status["loaded_shape_error_ok"],
            "equivalent_tip_deflection_m": selected.get("equivalent_tip_deflection_m"),
            "equivalent_twist_max_deg": selected.get("equivalent_twist_max_deg"),
            "equivalent_failure_index": selected.get("equivalent_failure_index"),
            "equivalent_buckling_index": selected.get("equivalent_buckling_index"),
            "target_shape_error_max_m": selected.get("target_shape_error_max_m"),
            "target_shape_error_rms_m": selected.get("target_shape_error_rms_m"),
            "loaded_shape_main_z_error_max_m": selected.get("loaded_shape_main_z_error_max_m"),
            "selected_source": selected.get("source"),
            "failures": "|".join(str(item) for item in (selected.get("failures") or [])),
            "moment_closure_status": "not_reported_by_canonical_summary",
            "warning_flags": "",
            "message": selected.get("message", ""),
        }
    )
    row.update(_wire_metrics(case_dir))

    design_mm = selected.get("design_mm") or {}
    for key in ("main_r", "main_t", "rear_r", "rear_t"):
        if key in design_mm:
            row[f"{key}_mm"] = json.dumps(design_mm[key], separators=(",", ":"))

    target_csv = case_dir / "target_loaded_shape_spar_data.csv"
    jig_csv = case_dir / "jig_shape_spar_data.csv"
    loaded_csv = case_dir / "loaded_shape_spar_data.csv"
    row["target_loaded_shape_csv"] = str(target_csv.resolve()) if target_csv.exists() else ""
    row["jig_shape_csv"] = str(jig_csv.resolve()) if jig_csv.exists() else ""
    row["loaded_shape_csv"] = str(loaded_csv.resolve()) if loaded_csv.exists() else ""
    if target_csv.exists():
        export_main_tip_z, export_rear_tip_z = _target_tip_from_csv(target_csv)
        row["export_csv_target_main_tip_z_m"] = export_main_tip_z
        row["export_csv_target_rear_tip_z_m"] = export_rear_tip_z
        if math.isfinite(target_main_tip_z) and abs(export_main_tip_z - target_main_tip_z) > 1.0e-6:
            row["warning_flags"] = "legacy_target_csv_tip_z_differs_from_selected_target_shape"
    if jig_csv.exists():
        jig_rows = _read_csv_rows(jig_csv)
        row["jig_main_tip_z_m"] = _float(jig_rows[-1]["Main_Z_m"]) if jig_rows else ""
        row["jig_rear_tip_z_m"] = _float(jig_rows[-1]["Rear_Z_m"]) if jig_rows else ""
    return row


def _row_float(row: Mapping[str, Any], key: str) -> float:
    return _float(row.get(key))


def _write_z_definition_audit(
    *,
    output_dir: Path,
    section_audit: Mapping[str, Any],
    base_target: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    semi_span = float(section_audit["semi_span_m"])
    base_target_main_tip_z = _float(base_target.get("target_main_tip_z_m"))
    base_target_rear_tip_z = _float(base_target.get("target_rear_tip_z_m"))
    target_effective_deg = effective_dihedral_deg(base_target_main_tip_z, semi_span)
    elastic = _float(base_target.get("elastic_deflection_z_m"))
    lines = [
        "# Z Definition Audit",
        "",
        "Case: smooth_tier2_production_baseline.",
        "",
        "## Current Exported Smooth Geometry",
        "",
        "| quantity | value | source / meaning |",
        "| --- | ---: | --- |",
        f"| aerodynamic_tip_z_m | {fnum(section_audit.get('aerodynamic_tip_z_m'), 6)} | tip z_m in section_table.csv, aerodynamic exported section line |",
        "| quarter_chord_tip_z_m | n/a | not exported as an independent field in this production package |",
        f"| root_z_reference | {fnum(section_audit.get('root_z_reference_m'), 6)} | section_table root z_m; aerodynamic geometry root reference |",
        f"| built_in_geometric_z_m | {fnum(section_audit.get('built_in_geometric_z_m'), 6)} | aerodynamic_tip_z_m minus root_z_reference |",
        f"| total_cruise_effective_z_m | {fnum(section_audit.get('built_in_geometric_z_m'), 6)} | exported loaded aero surface tip height relative to aerodynamic root for the current smooth geometry |",
        f"| effective_dihedral_deg | {fnum(section_audit.get('aerodynamic_effective_dihedral_deg'), 6)} | atan(total_cruise_effective_z_m / semi_span) |",
        "",
        "## Canonical Beam-Line Target Shape",
        "",
        "| quantity | value | source / meaning |",
        "| --- | ---: | --- |",
        f"| target_main_tip_z_m | {fnum(base_target_main_tip_z, 6)} | selected.target_loaded_shape.main_nodes_m tip z in canonical inverse summary |",
        f"| target_rear_tip_z_m | {fnum(base_target_rear_tip_z, 6)} | selected.target_loaded_shape.rear_nodes_m tip z in canonical inverse summary |",
        f"| main/root beam z | {fnum(base_target.get('target_main_root_z_m'), 6)} | beam-line structural root coordinate, not the aerodynamic root reference |",
        f"| rear/root beam z | {fnum(base_target.get('target_rear_root_z_m'), 6)} | beam-line structural root coordinate, not the aerodynamic root reference |",
        f"| elastic_deflection_z_m | {fnum(elastic, 6)} | selected.equivalent_tip_deflection_m when available; beam-line recovery metric |",
        f"| target_main_effective_dihedral_deg | {fnum(target_effective_deg, 6)} | atan(target_main_tip_z_m / semi_span); beam-line proxy only |",
        "",
        "## Frozen Interpretation",
        "",
        "- Canonical inverse design consumes the beam-line requested loaded shape: `target_loaded_shape.main_nodes_m` and `target_loaded_shape.rear_nodes_m`. In this MVP the sweep controls that state through `--target-shape-z-scale`, but the reported source of truth is the `selected.target_loaded_shape` object written by `scripts/direct_dual_beam_inverse_design.py`.",
        "- The 5-7 deg HPA guideline should be compared against total cruise effective Z of the physical loaded wing/aero surface, preferably quarter-chord or the explicitly defined aerodynamic section reference. For this smooth production package the independent quarter-chord Z is not exported, so the section-table tip `z_m` is the best available aerodynamic reference.",
        "- `target_main_tip_z_m` and `target_rear_tip_z_m` are beam-line structural quantities. They are valid control variables for inverse jig design, but they should not be treated as final aerodynamic effective dihedral unless the beam-to-aero-surface offset is explicitly mapped.",
        "- The Phase 11 CSV includes `effective_dihedral_deg = atan(target_main_tip_z_m / semi_span)` as an MVP beam-line proxy so the sweep can be compared consistently with earlier z-state work.",
        "",
    ]
    if rows:
        first = min(rows, key=lambda row: _row_float(row, "target_main_tip_z_m"))
        last = max(rows, key=lambda row: _row_float(row, "target_main_tip_z_m"))
        lines.extend(
            [
                "## Sweep Span",
                "",
                f"- lowest sampled beam-line target_main_tip_z_m: {fnum(first.get('target_main_tip_z_m'), 3)} m ({fnum(first.get('effective_dihedral_deg'), 3)} deg proxy)",
                f"- highest sampled beam-line target_main_tip_z_m: {fnum(last.get('target_main_tip_z_m'), 3)} m ({fnum(last.get('effective_dihedral_deg'), 3)} deg proxy)",
            ]
        )
    (output_dir / "z_definition_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _rows_sorted(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(rows, key=lambda row: _row_float(row, "target_main_tip_z_m"))


def _first_row(rows: Iterable[Mapping[str, Any]], key: str = "target_main_tip_z_m") -> Mapping[str, Any] | None:
    candidates = list(rows)
    if not candidates:
        return None
    return min(candidates, key=lambda row: _row_float(row, key))


def _write_summary_reports(
    *,
    output_dir: Path,
    rows: Sequence[Mapping[str, Any]],
    semi_span_m: float,
    spar_tube_mass_target_kg: float,
    healthy_clearance_m: float,
) -> None:
    sorted_rows = _rows_sorted(rows)
    deg_5_7 = [
        row
        for row in sorted_rows
        if _row_float(row, "effective_dihedral_deg") >= 5.0 - 1.0e-9
        and _row_float(row, "effective_dihedral_deg") <= 7.0 + 1.0e-9
    ]
    pass_rows = [row for row in sorted_rows if str(row.get("meets_tube_mass_target")) == "True" or row.get("meets_tube_mass_target") is True]
    feasible_rows = [row for row in sorted_rows if str(row.get("feasible")) == "True" or row.get("feasible") is True]
    healthy_pass_rows = [
        row
        for row in pass_rows
        if str(row.get("healthy_clearance")) == "True" or row.get("healthy_clearance") is True
    ]
    first_pass = _first_row(pass_rows)
    first_feasible = _first_row(feasible_rows)
    row_6deg = min(
        sorted_rows,
        key=lambda row: abs(_row_float(row, "effective_dihedral_deg") - 6.0),
        default=None,
    )
    prior_2675 = min(sorted_rows, key=lambda row: abs(_row_float(row, "target_main_tip_z_m") - 2.675), default=None)
    prior_2700 = min(sorted_rows, key=lambda row: abs(_row_float(row, "target_main_tip_z_m") - 2.700), default=None)
    old_x4 = max((row for row in sorted_rows if row.get("target_source") == "old_x4_equivalent"), key=lambda row: _row_float(row, "target_main_tip_z_m"), default=None)

    deg_5_7_meets = any(row in pass_rows for row in deg_5_7)
    deg_5_7_feasible = any(row in feasible_rows for row in deg_5_7)
    low_healthy = _first_row(healthy_pass_rows)

    lines = [
        "# Z-State Structure-Budget Sweep Summary",
        "",
        "This MVP holds the smooth_tier2_production_baseline geometry and AVL spanwise lift ownership fixed, then sweeps requested loaded beam-line Z through the canonical `scripts/direct_dual_beam_inverse_design.py` entrypoint.",
        "",
        "## Contract",
        "",
        f"- spar/tube mass target: {spar_tube_mass_target_kg:.3f} kg",
        f"- healthy jig clearance threshold: {healthy_clearance_m * 1000.0:.1f} mm",
        "- refresh_steps: 0",
        "- aero source: candidate_avl_spanwise from smooth production AVL strip-force artifact",
        "- ranking / hard gates: unchanged",
        "",
        "## Results",
        "",
    ]
    if first_pass is None:
        lines.append("No sampled state meets the spar/tube mass target.")
    else:
        lines.extend(
            [
                f"- first sampled mass pass: {fnum(first_pass.get('target_main_tip_z_m'), 3)} m, {fnum(first_pass.get('effective_dihedral_deg'), 3)} deg, tube {fnum(first_pass.get('tube_mass_kg'), 3)} kg, clearance {fnum(_row_float(first_pass, 'jig_ground_clearance_min_m') * 1000.0, 1)} mm",
            ]
        )
    if first_feasible is None:
        lines.append("- no sampled state simultaneously meets tube mass, healthy clearance, loaded-shape error, and canonical feasibility.")
    else:
        lines.append(
            f"- first sampled feasible contract pass: {fnum(first_feasible.get('target_main_tip_z_m'), 3)} m, {fnum(first_feasible.get('effective_dihedral_deg'), 3)} deg, tube {fnum(first_feasible.get('tube_mass_kg'), 3)} kg, clearance {fnum(_row_float(first_feasible, 'jig_ground_clearance_min_m') * 1000.0, 1)} mm"
        )
    if old_x4 is not None:
        lines.append(
            f"- old x4-equivalent check: {fnum(old_x4.get('target_main_tip_z_m'), 3)} m, {fnum(old_x4.get('effective_dihedral_deg'), 3)} deg, tube {fnum(old_x4.get('tube_mass_kg'), 3)} kg, clearance {fnum(_row_float(old_x4, 'jig_ground_clearance_min_m') * 1000.0, 1)} mm"
        )
    lines.extend(
        [
            "",
            "## Explicit Answers",
            "",
            "1. Total effective cruise dihedral corresponds to the loaded aerodynamic surface tip Z relative to the aerodynamic root reference. In this MVP, `effective_dihedral_deg` in the sweep CSV uses beam-line `target_main_tip_z_m / semi_span` as a proxy because canonical inverse design is driven by spar beam-line targets.",
            f"2. 5-7 deg sampled states meet the {spar_tube_mass_target_kg:.1f} kg tube target: {'yes' if deg_5_7_meets else 'no'}. They meet the full MVP budget including healthy clearance: {'yes' if deg_5_7_feasible else 'no'}.",
        ]
    )
    if row_6deg is not None:
        lines.append(
            f"3. At the sampled 6 deg target, the required selected tube mass is {fnum(row_6deg.get('tube_mass_kg'), 3)} kg under this canonical MVP sweep."
        )
    else:
        lines.append("3. A 6 deg target was not sampled.")
    if low_healthy is not None:
        lines.append(
            f"4. The lowest sampled state meeting tube mass with healthy clearance is {fnum(low_healthy.get('target_main_tip_z_m'), 3)} m / {fnum(low_healthy.get('effective_dihedral_deg'), 3)} deg."
        )
    else:
        lines.append("4. No sampled state meets both tube mass and healthy clearance.")
    if prior_2675 is not None and prior_2700 is not None:
        lines.append(
            f"5. The previous 2.675-2.70 m points are {fnum(prior_2675.get('effective_dihedral_deg'), 3)}-{fnum(prior_2700.get('effective_dihedral_deg'), 3)} deg beam-line proxy, so they sit above the preferred 5-7 deg range."
        )
    else:
        lines.append("5. The previous 2.675-2.70 m points were not both sampled.")
    if first_feasible is not None:
        lines.append(
            f"6. Send {fnum(first_feasible.get('target_main_tip_z_m'), 3)} m first to AVL loaded-shape recheck; also keep the nearest lower non-healthy/mass-boundary point and old x4-equivalent row as sensitivity checks."
        )
    else:
        lines.append("6. Do not send a production AVL recheck yet; sample a higher Z or richer structural layout first.")
    lines.extend(
        [
            "",
            "## Engineering Read",
            "",
            "- The current smooth aero geometry by itself is only about 3.5 deg effective dihedral by the exported section-table z; the low-mass structural states found here require much higher beam-line target Z.",
            "- That mismatch is an engineering warning, not a software failure: before finalizing the production state we need an explicit aero-surface-to-beam-line offset contract and an AVL recheck of the realizable loaded shape.",
        ]
    )
    (output_dir / "z_state_sweep_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    rec_lines = [
        "# Recommended Z State For Next AVL Recheck",
        "",
    ]
    if first_feasible is None:
        rec_lines.extend(
            [
                "No sampled Z state is ready as a production AVL loaded-shape recheck input under the MVP budget contract.",
                "",
                "Next action: extend the structural search above the highest sampled mass-boundary region or adapt the beam/wire layout before rerunning AVL.",
            ]
        )
    else:
        rec_lines.extend(
            [
                "Primary next AVL loaded-shape recheck:",
                f"- target_main_tip_z_m: {fnum(first_feasible.get('target_main_tip_z_m'), 6)}",
                f"- target_rear_tip_z_m: {fnum(first_feasible.get('target_rear_tip_z_m'), 6)}",
                f"- effective_dihedral_deg beam-line proxy: {fnum(first_feasible.get('effective_dihedral_deg'), 6)}",
                f"- tube_mass_kg: {fnum(first_feasible.get('tube_mass_kg'), 6)}",
                f"- jig_ground_clearance_min_m: {fnum(first_feasible.get('jig_ground_clearance_min_m'), 6)}",
                f"- canonical run: {first_feasible.get('case_dir')}",
                "",
                "Sensitivity points:",
            ]
        )
        for row in (prior_2675, prior_2700, old_x4):
            if row is None:
                continue
            rec_lines.append(
                f"- {row.get('case_label')}: z={fnum(row.get('target_main_tip_z_m'), 3)} m, "
                f"dihedral={fnum(row.get('effective_dihedral_deg'), 3)} deg, "
                f"tube={fnum(row.get('tube_mass_kg'), 3)} kg, "
                f"clearance={fnum(_row_float(row, 'jig_ground_clearance_min_m') * 1000.0, 1)} mm"
            )
    (output_dir / "recommended_z_state_for_next_avl_recheck.md").write_text(
        "\n".join(rec_lines) + "\n",
        encoding="utf-8",
    )


def _copy_config_template(config_template: Path, output_dir: Path) -> Path:
    output_path = output_dir / config_template.name
    if config_template.resolve() != output_path.resolve():
        shutil.copyfile(config_template, output_path)
    return output_path


def _selected_cruise_aoa_from_csv(path: Path) -> float:
    rows = _read_csv_rows(path)
    if not rows:
        raise ValueError(f"Aero summary CSV is empty: {path}")
    if "alpha_at_CL_req" not in rows[0]:
        raise ValueError(f"Aero summary CSV lacks alpha_at_CL_req: {path}")
    return float(rows[0]["alpha_at_CL_req"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Search requested loaded-Z states against a structural budget with the canonical inverse-design route."
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--case-id", default="smooth_tier2_production_baseline")
    parser.add_argument("--section-table", default=str(DEFAULT_SECTION_TABLE))
    parser.add_argument("--avl-path", default=str(DEFAULT_AVL_PATH))
    parser.add_argument("--avl-run-dir", default=str(SMOOTH_AVL_RUN_DIR))
    parser.add_argument("--aero-summary-csv", default=str(DEFAULT_AERO_SUMMARY))
    parser.add_argument("--candidate-avl-spanwise-loads-json", default="")
    parser.add_argument("--config-template", default="")
    parser.add_argument("--design-report", default="")
    parser.add_argument("--effective-dihedral-deg", default=DEFAULT_EFFECTIVE_DIHEDRAL_DEG)
    parser.add_argument("--target-main-tip-z-m", default=DEFAULT_TARGET_MAIN_TIP_Z_M)
    parser.add_argument("--include-old-x4-equivalent", action="store_true", default=True)
    parser.add_argument("--no-old-x4-equivalent", dest="include_old_x4_equivalent", action="store_false")
    parser.add_argument("--dihedral-exponent", type=float, default=1.0)
    parser.add_argument("--refresh-steps", type=int, default=0)
    parser.add_argument("--run-local-refine", action="store_true")
    parser.add_argument("--export-step", action="store_true")
    parser.add_argument("--enable-ground-clearance-recovery", action="store_true")
    parser.add_argument("--cobyla-maxiter", type=int, default=40)
    parser.add_argument("--rib-zonewise-mode", default="limited_zonewise")
    parser.add_argument("--spar-tube-mass-target-kg", type=float, default=DEFAULT_SPAR_TUBE_MASS_TARGET_KG)
    parser.add_argument("--healthy-clearance-m", type=float, default=DEFAULT_HEALTHY_CLEARANCE_M)
    parser.add_argument("--loaded-shape-error-tol-m", type=float, default=DEFAULT_LOADED_SHAPE_ERROR_TOL_M)
    parser.add_argument("--velocity-mps", type=float, default=SMOOTH_VELOCITY_MPS)
    parser.add_argument("--density-kgpm3", type=float, default=SMOOTH_RHO_KGPM3)
    parser.add_argument("--rerun", action="store_true")
    args = parser.parse_args(argv)

    if int(args.refresh_steps) != 0:
        print(
            "[structure-budgeted-z] warning: refresh_steps is not 0; MVP comparability is best with --refresh-steps 0.",
            file=sys.stderr,
        )

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    section_table = Path(args.section_table).expanduser().resolve()
    avl_path = Path(args.avl_path).expanduser().resolve()
    avl_run_dir = Path(args.avl_run_dir).expanduser().resolve()
    aero_summary_csv = Path(args.aero_summary_csv).expanduser().resolve()
    design_report = _select_design_report(
        Path(args.design_report).expanduser().resolve() if str(args.design_report).strip() else None
    )
    source_candidate_artifact = (
        Path(args.candidate_avl_spanwise_loads_json).expanduser().resolve()
        if str(args.candidate_avl_spanwise_loads_json).strip()
        else None
    )
    if source_candidate_artifact is not None and not source_candidate_artifact.exists():
        raise FileNotFoundError(source_candidate_artifact)

    section_audit = _section_z_audit(section_table)
    semi_span_m = float(section_audit["semi_span_m"])
    base_target = _base_canonical_target_shape()
    base_main_tip_z_m = float(base_target["target_main_tip_z_m"])

    if str(args.config_template).strip():
        config_path = _copy_config_template(Path(args.config_template).expanduser().resolve(), output_dir)
        config_manifest: dict[str, Any] = {"config_path": str(config_path.resolve()), "source": "config_template"}
    else:
        config_path, config_manifest = build_smooth_canonical_config(output_dir)

    if source_candidate_artifact is None:
        selected_cruise_aoa_deg = _selected_cruise_aoa_from_csv(aero_summary_csv)
    else:
        payload = _read_json(source_candidate_artifact)
        selected_cruise_aoa_deg = _float(
            payload.get("selected_cruise_aoa_deg"),
            _selected_cruise_aoa_from_csv(aero_summary_csv) if aero_summary_csv.exists() else 0.0,
        )

    effective_targets = _parse_float_list(args.effective_dihedral_deg)
    z_targets = _parse_float_list(args.target_main_tip_z_m)
    requests = unique_z_state_requests(
        semi_span_m=semi_span_m,
        effective_dihedral_deg_values=effective_targets,
        target_main_tip_z_m_values=z_targets,
        include_old_x4_equivalent=bool(args.include_old_x4_equivalent),
    )
    if not requests:
        raise ValueError("No z-state requests were generated.")

    rows: list[dict[str, Any]] = []
    for request in requests:
        print(
            f"[structure-budgeted-z] running {request.label}: target_main_tip_z={request.target_main_tip_z_m:.6f} m"
        )
        rows.append(
            _run_case(
                request=request,
                output_dir=output_dir,
                config_path=config_path,
                design_report=design_report,
                semi_span_m=semi_span_m,
                base_main_tip_z_m=base_main_tip_z_m,
                avl_path=avl_path,
                avl_run_dir=avl_run_dir,
                source_candidate_artifact=source_candidate_artifact,
                selected_cruise_aoa_deg=selected_cruise_aoa_deg,
                velocity_mps=float(args.velocity_mps),
                density_kgpm3=float(args.density_kgpm3),
                dihedral_exponent=float(args.dihedral_exponent),
                refresh_steps=int(args.refresh_steps),
                skip_local_refine=not bool(args.run_local_refine),
                skip_step_export=not bool(args.export_step),
                no_ground_clearance_recovery=not bool(args.enable_ground_clearance_recovery),
                cobyla_maxiter=int(args.cobyla_maxiter),
                rib_zonewise_mode=str(args.rib_zonewise_mode),
                spar_tube_mass_target_kg=float(args.spar_tube_mass_target_kg),
                healthy_clearance_m=float(args.healthy_clearance_m),
                loaded_shape_error_tol_m=float(args.loaded_shape_error_tol_m),
                rerun=bool(args.rerun),
            )
        )

    rows = sorted(rows, key=lambda row: _row_float(row, "target_main_tip_z_m"))
    feasible_rows = [row for row in rows if bool(row.get("feasible"))]
    _write_csv(output_dir / "z_state_structure_budget_sweep.csv", rows)
    _write_csv(
        output_dir / "feasible_loaded_shape_shortlist.csv",
        feasible_rows,
        fields=[
            "case_label",
            "target_main_tip_z_m",
            "target_rear_tip_z_m",
            "effective_dihedral_deg",
            "tube_mass_kg",
            "total_structural_mass_kg",
            "jig_ground_clearance_min_m",
            "loaded_shape_error",
            "canonical_command_txt_path",
            "case_dir",
            "summary_path",
        ],
    )
    _write_z_definition_audit(
        output_dir=output_dir,
        section_audit=section_audit,
        base_target=base_target,
        rows=rows,
    )
    _write_summary_reports(
        output_dir=output_dir,
        rows=rows,
        semi_span_m=semi_span_m,
        spar_tube_mass_target_kg=float(args.spar_tube_mass_target_kg),
        healthy_clearance_m=float(args.healthy_clearance_m),
    )

    manifest = {
        "case_id": str(args.case_id),
        "workflow": "structure_budgeted_z_state_search_mvp",
        "canonical_entrypoint": str((REPO_ROOT / "scripts" / "direct_dual_beam_inverse_design.py").resolve()),
        "section_table": str(section_table),
        "avl_path": str(avl_path),
        "avl_run_dir": str(avl_run_dir),
        "aero_summary_csv": str(aero_summary_csv),
        "design_report": str(design_report),
        "config": config_manifest,
        "semi_span_m": semi_span_m,
        "base_main_tip_z_m": base_main_tip_z_m,
        "spar_tube_mass_target_kg": float(args.spar_tube_mass_target_kg),
        "healthy_clearance_m": float(args.healthy_clearance_m),
        "loaded_shape_error_tol_m": float(args.loaded_shape_error_tol_m),
        "effective_dihedral_targets_deg": effective_targets,
        "target_main_tip_z_targets_m": z_targets,
        "include_old_x4_equivalent": bool(args.include_old_x4_equivalent),
        "refresh_steps": int(args.refresh_steps),
        "notes": [
            "No aerodynamic ranking or hard gates are changed by this diagnostic.",
            "Canonical inverse command is recorded per case in canonical_command_used and command.txt.",
            "The CSV effective_dihedral_deg column is a beam-line target_main_tip_z_m proxy.",
        ],
    }
    (output_dir / "z_state_search_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {output_dir / 'z_state_structure_budget_sweep.csv'}")
    print(f"Wrote {output_dir / 'feasible_loaded_shape_shortlist.csv'}")
    print(f"Wrote {output_dir / 'z_definition_audit.md'}")
    print(f"Wrote {output_dir / 'z_state_sweep_summary.md'}")
    print(f"Wrote {output_dir / 'recommended_z_state_for_next_avl_recheck.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
