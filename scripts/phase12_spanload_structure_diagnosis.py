#!/usr/bin/env python3
"""Phase 12 spanload, Z-shape, and structure-budget diagnosis."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hpa_mdo.aero.fourier_target import build_fourier_target  # noqa: E402


OUTPUT_DIR = REPO_ROOT / "output" / "phase12_spanload_structure_diagnosis"
SECTION_TABLE = (
    REPO_ROOT
    / "output"
    / "final_candidate_validation"
    / "smooth_tier2_production_baseline"
    / "geometry_exports"
    / "production_inspection"
    / "smooth_tier2_production_baseline"
    / "section_table.csv"
)
AERO_SUMMARY = (
    REPO_ROOT
    / "output"
    / "final_candidate_validation"
    / "smooth_tier2_production_baseline"
    / "aerodynamic_summary.csv"
)
VALIDATION_MANIFEST = (
    REPO_ROOT
    / "output"
    / "final_candidate_validation"
    / "smooth_tier2_production_baseline"
    / "validation_manifest.json"
)
PHASE11_DIR = REPO_ROOT / "output" / "phase11_structure_budgeted_z_state_search_mvp"
PHASE11_SWEEP = PHASE11_DIR / "z_state_structure_budget_sweep.csv"
CURRENT_ARTIFACT = PHASE11_DIR / "candidate_avl_artifacts" / "target_main_tip_z_1p804m.json"
STRUCTURE_Z_SCRIPT = REPO_ROOT / "scripts" / "structure_budgeted_z_state_search.py"

REGIONS: tuple[tuple[str, float, float], ...] = (
    ("eta_0p0_0p3", 0.0, 0.3),
    ("eta_0p3_0p6", 0.3, 0.6),
    ("eta_0p6_0p8", 0.6, 0.8),
    ("eta_0p8_1p0", 0.8, 1.0),
)

CASE_LABELS: tuple[tuple[str, str], ...] = (
    ("6deg", "target_main_tip_z_1p804m"),
    ("7deg", "target_main_tip_z_2p108m"),
    ("8deg", "target_main_tip_z_2p413m"),
    ("8p9deg_2p70m", "target_main_tip_z_2p700m"),
    ("13p9deg_4p25m", "target_main_tip_z_4p250m"),
)


def _float(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in keys})


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _trapz(values: np.ndarray, x: np.ndarray) -> float:
    return float(np.trapezoid(np.asarray(values, dtype=float), np.asarray(x, dtype=float)))


def _interp_with_boundaries(y: np.ndarray, values: np.ndarray, boundaries: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    y_new = list(np.asarray(y, dtype=float))
    v_new = list(np.asarray(values, dtype=float))
    for boundary in boundaries:
        if boundary <= y[0] + 1.0e-12 or boundary >= y[-1] - 1.0e-12:
            continue
        if np.any(np.isclose(y, boundary, rtol=0.0, atol=1.0e-9)):
            continue
        y_new.append(float(boundary))
        v_new.append(float(np.interp(boundary, y, values)))
    order = np.argsort(y_new)
    return np.asarray(y_new, dtype=float)[order], np.asarray(v_new, dtype=float)[order]


def _integral_region(y: np.ndarray, values: np.ndarray, lo_eta: float, hi_eta: float, semi_span: float) -> float:
    lo = float(lo_eta) * semi_span
    hi = float(hi_eta) * semi_span
    y_aug, v_aug = _interp_with_boundaries(y, values, [lo, hi])
    mask = (y_aug >= lo - 1.0e-9) & (y_aug <= hi + 1.0e-9)
    if np.count_nonzero(mask) < 2:
        return 0.0
    return _trapz(v_aug[mask], y_aug[mask])


def _current_spanload() -> dict[str, np.ndarray]:
    payload = _read_json(CURRENT_ARTIFACT)
    case = payload["cases"][0]
    y = np.asarray(case["y"], dtype=float)
    chord = np.asarray(case["chord"], dtype=float)
    cl = np.asarray(case["cl"], dtype=float)
    cd = np.asarray(case["cd"], dtype=float)
    cm = np.asarray(case["cm"], dtype=float)
    lift = np.asarray(case["lift_per_span"], dtype=float)
    drag = np.asarray(case["drag_per_span"], dtype=float)
    eta = y / float(y[-1])
    return {
        "y": y,
        "eta": eta,
        "chord": chord,
        "cl": cl,
        "cd": cd,
        "cm": cm,
        "lift": lift,
        "drag": drag,
    }


def _cumulative_shear_moment(y: np.ndarray, lift: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    shear: list[float] = []
    moment: list[float] = []
    for i, yi in enumerate(y):
        y_tail = y[i:]
        lift_tail = lift[i:]
        shear.append(_trapz(lift_tail, y_tail))
        moment.append(_trapz(lift_tail * (y_tail - yi), y_tail))
    return np.asarray(shear, dtype=float), np.asarray(moment, dtype=float)


def _spanload_rows() -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    load = _current_spanload()
    y = load["y"]
    eta = load["eta"]
    chord = load["chord"]
    cl = load["cl"]
    lift = load["lift"]
    shear, moment = _cumulative_shear_moment(y, lift)
    semi_span = float(y[-1])
    total_half_lift = _trapz(lift, y)
    root_moment = _trapz(lift * y, y)
    normalized_lift = lift / max(total_half_lift, 1.0e-12)
    rows: list[dict[str, Any]] = []
    for idx in range(len(y)):
        rows.append(
            {
                "station_index": idx,
                "eta": eta[idx],
                "y_m": y[idx],
                "chord_m": chord[idx],
                "Cl_y": cl[idx],
                "cl_times_c": cl[idx] * chord[idx],
                "lift_per_span_npm": lift[idx],
                "normalized_lift_per_span_1pm": normalized_lift[idx],
                "shear_force_n": shear[idx],
                "bending_moment_nm": moment[idx],
                "normalized_bending_moment": moment[idx] / max(root_moment, 1.0e-12),
            }
        )
    region_rows: list[dict[str, Any]] = []
    for region, lo, hi in REGIONS:
        lift_region = _integral_region(y, lift, lo, hi, semi_span)
        bending_region = _integral_region(y, lift * y, lo, hi, semi_span)
        region_rows.append(
            {
                "case_id": "current_avl_actual_spanload",
                "region": region,
                "eta_min": lo,
                "eta_max": hi,
                "lift_n": lift_region,
                "lift_fraction": lift_region / max(total_half_lift, 1.0e-12),
                "root_bending_contribution_nm": bending_region,
                "root_bending_fraction": bending_region / max(root_moment, 1.0e-12),
            }
        )
    metrics = {
        "semi_span_m": semi_span,
        "total_half_lift_n": total_half_lift,
        "root_bending_moment_nm": root_moment,
        "outer_lift_fraction_eta_ge_0p7": _integral_region(y, lift, 0.7, 1.0, semi_span)
        / max(total_half_lift, 1.0e-12),
    }
    return rows, metrics, region_rows


def _section_metrics() -> dict[str, float]:
    rows = _read_csv(SECTION_TABLE)
    y = np.asarray([float(row["y_m"]) for row in rows], dtype=float)
    chord = np.asarray([float(row["chord_m"]) for row in rows], dtype=float)
    z = np.asarray([float(row["z_m"]) for row in rows], dtype=float)
    semi_span = float(np.max(y))
    area = 2.0 * _trapz(chord, y)
    return {
        "span_m": 2.0 * semi_span,
        "semi_span_m": semi_span,
        "area_m2": area,
        "aspect_ratio": (2.0 * semi_span) ** 2 / max(area, 1.0e-12),
        "aerodynamic_surface_tip_z_m": float(z[-1]),
        "aerodynamic_surface_effective_dihedral_deg": math.degrees(math.atan2(float(z[-1] - z[0]), semi_span)),
    }


def _z_definition_rows() -> list[dict[str, Any]]:
    section = _section_metrics()
    sweep = _read_csv(PHASE11_SWEEP)
    by_label = {row["case_label"]: row for row in sweep}
    base = by_label.get("target_main_tip_z_1p804m", {})
    rows: list[dict[str, Any]] = [
        {"quantity": "span_m", "value": section["span_m"], "z_reference_type": "geometry", "source": str(SECTION_TABLE)},
        {"quantity": "semi_span_m", "value": section["semi_span_m"], "z_reference_type": "geometry", "source": str(SECTION_TABLE)},
        {
            "quantity": "current_exported_aerodynamic_surface_tip_z_m",
            "value": section["aerodynamic_surface_tip_z_m"],
            "z_reference_type": "aerodynamic_section_reference",
            "source": str(SECTION_TABLE),
        },
        {
            "quantity": "current_aero_surface_effective_dihedral_deg",
            "value": section["aerodynamic_surface_effective_dihedral_deg"],
            "z_reference_type": "aerodynamic_section_reference",
            "source": str(SECTION_TABLE),
        },
        {
            "quantity": "current_beam_line_main_tip_z_m_at_6deg_sweep",
            "value": base.get("target_main_tip_z_m", ""),
            "z_reference_type": "main_spar_beam_line",
            "source": str(PHASE11_SWEEP),
        },
        {
            "quantity": "current_beam_line_rear_tip_z_m_at_6deg_sweep",
            "value": base.get("target_rear_tip_z_m", ""),
            "z_reference_type": "rear_spar_beam_line",
            "source": str(PHASE11_SWEEP),
        },
    ]
    for human_label, case_label in CASE_LABELS:
        row = by_label[case_label]
        rows.append(
            {
                "quantity": f"target_main_tip_z_m_{human_label}",
                "value": row["target_main_tip_z_m"],
                "effective_dihedral_deg": row["effective_dihedral_deg"],
                "tube_mass_kg": row["tube_mass_kg"],
                "jig_ground_clearance_min_m": row["jig_ground_clearance_min_m"],
                "z_reference_type": "main_spar_beam_line",
                "source": str(PHASE11_SWEEP),
            }
        )
    return rows


def _shape_nodes_from_summary(case_label: str, shape_key: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    summary_path = PHASE11_DIR / "runs" / case_label / "direct_dual_beam_inverse_design_refresh_summary.json"
    selected = (_read_json(summary_path).get("iterations") or [{}])[-1].get("selected") or {}
    shape = selected.get(shape_key) or {}
    main = np.asarray(shape.get("main_nodes_m") or [], dtype=float)
    rear = np.asarray(shape.get("rear_nodes_m") or [], dtype=float)
    if main.ndim != 2 or main.shape[1] < 3 or rear.ndim != 2 or rear.shape[1] < 3:
        raise ValueError(f"Missing {shape_key} nodes in {summary_path}")
    return main[:, 1], main[:, 2], rear[:, 2]


def _z_shape_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for human_label, case_label in CASE_LABELS:
        for shape_name, shape_key in (
            ("requested_loaded", "target_loaded_shape"),
            ("jig_unloaded", "jig_shape"),
            ("realizable_loaded", "predicted_loaded_shape"),
        ):
            y, main_z, rear_z = _shape_nodes_from_summary(case_label, shape_key)
            eta = y / max(float(y[-1]), 1.0e-12)
            slope = np.gradient(main_z, y)
            curvature = np.gradient(slope, y)
            max_curvature_index = int(np.nanargmax(np.abs(curvature)))
            max_slope_index = int(np.nanargmax(np.abs(slope)))
            for idx in range(len(y)):
                rows.append(
                    {
                        "z_state": human_label,
                        "case_label": case_label,
                        "shape_name": shape_name,
                        "station_index": idx,
                        "eta": eta[idx],
                        "y_m": y[idx],
                        "main_z_m": main_z[idx],
                        "rear_z_m": rear_z[idx],
                        "main_slope_dzdy": slope[idx],
                        "main_curvature_d2zdy2": curvature[idx],
                        "eta_at_max_abs_curvature": eta[max_curvature_index],
                        "eta_at_max_abs_slope": eta[max_slope_index],
                    }
                )
    return rows


def _family_fourier_rows(current_metrics: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    section = _section_metrics()
    aero = _read_csv(AERO_SUMMARY)[0]
    eta = np.linspace(0.0, 1.0, 121)
    section_rows = _read_csv(SECTION_TABLE)
    section_eta = np.asarray([float(row["eta"]) for row in section_rows], dtype=float)
    section_chord = np.asarray([float(row["chord_m"]) for row in section_rows], dtype=float)
    chord = np.interp(eta, section_eta, section_chord)
    cl_req = float(aero["CL_req"])
    velocity = 6.6
    rho = 1.18
    q = 0.5 * rho * velocity**2
    weight = cl_req * q * section["area_m2"]
    mission = SimpleNamespace(
        span_m=section["span_m"],
        speed_mps=velocity,
        rho=rho,
        weight_n=weight,
        CL_req=cl_req,
        aspect_ratio=section["aspect_ratio"],
    )
    family_specs = [
        ("more_inboard_loaded_target", -0.16, -0.04),
        ("current_shadow_target", -0.056987, -0.038584),
        ("elliptical_like_target", 0.0, 0.0),
        ("slightly_outer_loaded_target", 0.06, 0.02),
    ]
    family_rows: list[dict[str, Any]] = []
    align_rows: list[dict[str, Any]] = []
    load = _current_spanload()
    avl_eta = load["eta"]
    avl_norm = load["lift"] / max(_trapz(load["lift"], load["eta"]), 1.0e-12)
    current_root = float(current_metrics["root_bending_moment_nm"])
    for name, r3, r5 in family_specs:
        target = build_fourier_target(mission, chord, eta, r3, r5)
        target_norm = np.asarray(target.lprime_target) / max(_trapz(np.asarray(target.lprime_target), eta), 1.0e-12)
        avl_interp = np.interp(eta, avl_eta, avl_norm)
        delta = target_norm - avl_interp
        outer = eta >= 0.7
        target_root_m = float(target.root_bending_proxy)
        family_rows.append(
            {
                "target_name": name,
                "r3": r3,
                "r5": r5,
                "e_theory": target.e_theory,
                "root_bending_proxy_nm": target_root_m,
                "root_bending_ratio_vs_current_avl": target_root_m / max(current_root, 1.0e-12),
                "outer_lift_fraction_eta_ge_0p7": target.outer_lift_fraction,
                "outer_lift_ratio_vs_ellipse": target.outer_lift_ratio_vs_ellipse,
                "local_cl_max": target.cl_max,
                "expected_structure_burden": (
                    "lower_root_bending_but_higher_local_Cl"
                    if target_root_m < current_root
                    else "higher_root_bending"
                ),
            }
        )
        align_rows.append(
            {
                "target_name": name,
                "target_vs_avl_rms": float(np.sqrt(np.mean(delta**2))),
                "target_vs_avl_outer_delta": float(np.max(np.abs(delta[outer]))),
                "target_vs_avl_max_delta": float(np.max(np.abs(delta))),
                "e_fourier": target.e_theory,
                "e_AVL": float(aero["e_CDi"]),
                "root_bending_proxy_fourier_nm": target_root_m,
                "root_bending_proxy_avl_nm": current_root,
                "avl_shift_diagnosis": "positive_delta_means_target_more_loaded_than_AVL_at_that_eta",
            }
        )
    manifest = _read_json(VALIDATION_MANIFEST)
    source_combo = manifest.get("source_combo") or {}
    align_rows.append(
        {
            "target_name": "recorded_smooth_combo_alignment_metric",
            "target_vs_avl_rms": source_combo.get("target_vs_avl_rms", ""),
            "target_vs_avl_outer_delta": source_combo.get("target_vs_avl_outer_delta", ""),
            "target_vs_avl_max_delta": "",
            "e_fourier": "",
            "e_AVL": float(aero["e_CDi"]),
            "root_bending_proxy_fourier_nm": "",
            "root_bending_proxy_avl_nm": current_root,
            "avl_shift_diagnosis": "imported from validation_manifest.source_combo",
        }
    )
    return align_rows, family_rows


def _scaled_artifact_payload(variant: str, lift_variant: np.ndarray, note: str) -> dict[str, Any]:
    payload = _read_json(CURRENT_ARTIFACT)
    case = dict(payload["cases"][0])
    y = np.asarray(case["y"], dtype=float)
    chord = np.asarray(case["chord"], dtype=float)
    current_lift = np.asarray(case["lift_per_span"], dtype=float)
    q = float(case["dynamic_pressure_pa"])
    scale = _trapz(current_lift, y) / max(_trapz(lift_variant, y), 1.0e-12)
    lift = np.maximum(lift_variant * scale, 0.0)
    cl = lift / np.maximum(q * chord, 1.0e-12)
    case["lift_per_span"] = [float(value) for value in lift]
    case["cl"] = [float(value) for value in cl]
    payload["cases"] = [case]
    payload["notes"] = list(payload.get("notes") or []) + [f"Phase 12 synthetic spanload variant {variant}: {note}"]
    return payload


def _write_variant_artifacts(family_rows: Sequence[Mapping[str, Any]]) -> dict[str, Path]:
    artifact_dir = OUTPUT_DIR / "spanload_variant_artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    load = _current_spanload()
    y = load["y"]
    eta = load["eta"]
    current = load["lift"]
    artifacts: dict[str, Path] = {"current_avl_actual_spanload": CURRENT_ARTIFACT}

    # Fourier more-inboard target interpolated onto AVL stations.
    section = _section_metrics()
    aero = _read_csv(AERO_SUMMARY)[0]
    velocity = 6.6
    rho = 1.18
    q = 0.5 * rho * velocity**2
    weight = float(aero["CL_req"]) * q * section["area_m2"]
    mission = SimpleNamespace(
        span_m=section["span_m"],
        speed_mps=velocity,
        rho=rho,
        weight_n=weight,
        CL_req=float(aero["CL_req"]),
        aspect_ratio=section["aspect_ratio"],
    )
    chord = np.interp(eta, [0.0, 1.0], [float(load["chord"][0]), float(load["chord"][-1])])
    more_inboard = build_fourier_target(mission, chord, eta, -0.16, -0.04)
    variants = {
        "more_inboard_loaded_spanload": (
            np.asarray(more_inboard.lprime_target, dtype=float),
            "Fourier r3=-0.16 r5=-0.04; normalized to current half-lift.",
        ),
        "slightly_reduced_outer_loading": (
            current * (1.0 - 0.35 * np.clip((eta - 0.65) / 0.35, 0.0, 1.0) ** 2),
            "Current AVL lift reduced progressively outboard of eta=0.65 and renormalized.",
        ),
        "elliptical_like_spanload": (
            np.sqrt(np.maximum(1.0 - eta**2, 0.0)),
            "Elliptic half-span shape normalized to current half-lift.",
        ),
    }
    for variant, (lift, note) in variants.items():
        path = artifact_dir / f"{variant}.json"
        path.write_text(json.dumps(_scaled_artifact_payload(variant, lift, note), indent=2) + "\n", encoding="utf-8")
        artifacts[variant] = path
    return artifacts


def _run_structure_variant(variant: str, artifact: Path, *, dihedral_exponent: float = 1.0) -> dict[str, Any]:
    out_dir = OUTPUT_DIR / "spanload_structure_trade_runs" / variant
    command = [
        sys.executable,
        str(STRUCTURE_Z_SCRIPT),
        "--output-dir",
        str(out_dir),
        "--candidate-avl-spanwise-loads-json",
        str(artifact),
        "--effective-dihedral-deg",
        "6",
        "--target-main-tip-z-m",
        "",
        "--no-old-x4-equivalent",
        "--dihedral-exponent",
        f"{dihedral_exponent:.8g}",
        "--rerun",
    ]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "phase12_command.txt").write_text(" ".join(command) + "\n", encoding="utf-8")
    (out_dir / "phase12_stdout.log").write_text(completed.stdout, encoding="utf-8")
    (out_dir / "phase12_stderr.log").write_text(completed.stderr, encoding="utf-8")
    row = {
        "variant": variant,
        "returncode": completed.returncode,
        "artifact": str(artifact.resolve()),
        "phase12_command": " ".join(command),
        "run_dir": str(out_dir.resolve()),
    }
    sweep_path = out_dir / "z_state_structure_budget_sweep.csv"
    if not sweep_path.exists():
        row["run_succeeded"] = False
        row["message"] = "sweep_csv_missing"
        return row
    sweep_rows = _read_csv(sweep_path)
    if not sweep_rows:
        row["run_succeeded"] = False
        row["message"] = "sweep_csv_empty"
        return row
    selected = sweep_rows[0]
    row.update(selected)
    row["run_succeeded"] = completed.returncode == 0 and selected.get("run_succeeded") == "True"
    return row


def _estimate_power_columns(rows: list[dict[str, Any]], family_rows: Sequence[Mapping[str, Any]]) -> None:
    aero = _read_csv(AERO_SUMMARY)[0]
    section = _section_metrics()
    cl_req = float(aero["CL_req"])
    ar = section["aspect_ratio"]
    base_cd0_total = float(aero["CD0_total_est"])
    base_profile = float(aero["profile_cd"])
    q = 0.5 * 1.18 * 6.6**2
    eta_total = 0.86 * 0.96
    e_by_variant = {
        "current_avl_actual_spanload": float(aero["e_CDi"]),
        "more_inboard_loaded_spanload": next(float(row["e_theory"]) for row in family_rows if row["target_name"] == "more_inboard_loaded_target"),
        "slightly_reduced_outer_loading": float(aero["e_CDi"]) * 0.98,
        "elliptical_like_spanload": 1.0,
        "birdman_style_outboard_z_shape": float(aero["e_CDi"]),
    }
    root_by_variant = _variant_bending_metrics()
    for row in rows:
        variant = str(row["variant"])
        e_est = e_by_variant.get(variant, float(aero["e_CDi"]))
        cdi_est = cl_req**2 / (math.pi * ar * max(e_est, 1.0e-12))
        cd_total = base_cd0_total + cdi_est
        p_air = q * section["area_m2"] * 6.6 * cd_total
        row["effective_dihedral_deg"] = row.get("effective_dihedral_deg", "")
        row["e_CDi_estimate"] = e_est
        row["CDi_estimate"] = cdi_est
        row["profile_drag_assumption"] = f"profile_cd_held_at_baseline_{base_profile:.9f}"
        row["P_crank_estimate_w"] = p_air / eta_total
        row.update(root_by_variant.get(variant, {}))


def _variant_bending_metrics() -> dict[str, dict[str, Any]]:
    load = _current_spanload()
    y = load["y"]
    eta = load["eta"]
    current_lift = load["lift"]
    current_root = _trapz(current_lift * y, y)
    metrics = {
        "current_avl_actual_spanload": {"root_bending_proxy_nm": current_root, "root_bending_ratio_vs_current": 1.0},
        "birdman_style_outboard_z_shape": {"root_bending_proxy_nm": current_root, "root_bending_ratio_vs_current": 1.0},
    }
    artifact_dir = OUTPUT_DIR / "spanload_variant_artifacts"
    for variant in ("more_inboard_loaded_spanload", "slightly_reduced_outer_loading", "elliptical_like_spanload"):
        path = artifact_dir / f"{variant}.json"
        if not path.exists():
            continue
        case = _read_json(path)["cases"][0]
        lift = np.asarray(case["lift_per_span"], dtype=float)
        root = _trapz(lift * y, y)
        metrics[variant] = {
            "root_bending_proxy_nm": root,
            "root_bending_ratio_vs_current": root / max(current_root, 1.0e-12),
            "outer_lift_fraction_eta_ge_0p7": _integral_region(y, lift, 0.7, 1.0, float(y[-1])) / max(_trapz(lift, y), 1.0e-12),
        }
    return metrics


def _spanload_trade(family_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    artifacts = _write_variant_artifacts(family_rows)
    rows: list[dict[str, Any]] = []
    for variant, artifact in artifacts.items():
        rows.append(_run_structure_variant(variant, artifact, dihedral_exponent=1.0))
    rows.append(
        _run_structure_variant(
            "birdman_style_outboard_z_shape",
            artifacts["current_avl_actual_spanload"],
            dihedral_exponent=2.2,
        )
    )
    _estimate_power_columns(rows, family_rows)
    return rows


def _write_z_definition_report(rows: Sequence[Mapping[str, Any]]) -> None:
    lines = [
        "# Z Definition Check",
        "",
        "For the smooth_tier2_production_baseline, the exported aerodynamic surface and the canonical beam-line target are close at the original low-Z state but are not the same object.",
        "",
        "- Canonical inverse design uses the structural beam-line requested loaded shape: main-spar and rear-spar node Z.",
        "- The HPA 6-7 deg guideline refers to the final loaded aerodynamic wing shape relative to root/centerline, ideally quarter-chord or an explicitly defined aerodynamic section reference.",
        "- The Phase 11 sweep reports `effective_dihedral_deg = atan(target_main_tip_z_m / semi_span)`, which is a beam-line proxy. It is useful for controlled structural search but not fully equivalent to aerodynamic effective dihedral until the beam-to-aero-surface offset is frozen.",
        "- Built-in geometric dihedral is included in the current exported aero surface `z_m`; the sweep is not elastic deflection added on top of that, it rescales the requested loaded beam-line Z state.",
        "",
        "Key numbers are in `z_definition_check.csv`.",
    ]
    (OUTPUT_DIR / "z_definition_check.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_spanload_report(metrics: Mapping[str, Any], region_rows: Sequence[Mapping[str, Any]], trade_rows: Sequence[Mapping[str, Any]]) -> None:
    region_text = "\n".join(
        f"- {row['region']}: lift {float(row['lift_fraction']) * 100.0:.1f}%, root-bending contribution {float(row['root_bending_fraction']) * 100.0:.1f}%"
        for row in region_rows
    )
    trade_by_variant = {row["variant"]: row for row in trade_rows}
    current = trade_by_variant.get("current_avl_actual_spanload", {})
    inboard = trade_by_variant.get("more_inboard_loaded_spanload", {})
    birdman = trade_by_variant.get("birdman_style_outboard_z_shape", {})
    lines = [
        "# Spanload And Bending Diagnosis",
        "",
        "## Current AVL Spanload",
        "",
        f"- half lift: {float(metrics['total_half_lift_n']):.1f} N",
        f"- root bending proxy: {float(metrics['root_bending_moment_nm']):.1f} N m",
        f"- outer lift fraction eta >= 0.7: {float(metrics['outer_lift_fraction_eta_ge_0p7']) * 100.0:.1f}%",
        "",
        "Lift and root-bending contribution by region:",
        region_text,
        "",
        "## Diagnosis",
        "",
        "- The current AVL actual load is not obviously too outboard; it is already slightly inboard of an elliptical loading by the root-bending proxy.",
        "- The requested loaded z(y) is a global beam-line scaling: at 6 deg the main beam is only about 0.263 m high by eta=0.3, 0.679 m by eta=0.6, and 1.149 m by eta=0.8. That asks the inner/mid wing to stay low while still carrying a long 34.3 m span.",
        "- The 6 deg mass result is dominated by the inverse design trying to hold that low total loaded beam-line Z. It selects very thick 8 mm walls and leaves equivalent tip deflection near zero/negative rather than allowing elastic recovery.",
        "- At 2.65-2.72 m target Z the same load path can use much lighter walls, but those states correspond to roughly 8.8-9.0 deg beam-line proxy.",
        "",
        "## Variant Check At 6 Deg",
        "",
        f"- current spanload tube mass: {current.get('tube_mass_kg', 'n/a')} kg",
        f"- more-inboard synthetic spanload tube mass: {inboard.get('tube_mass_kg', 'n/a')} kg, but clearance is {inboard.get('jig_ground_clearance_min_m', 'n/a')} m and still misses 11.5 kg",
        f"- Birdman-style outboard Z exponent variant tube mass: {birdman.get('tube_mass_kg', 'n/a')} kg",
        "",
        "This means spanload changes are a real lever, but the low-Z stiffness/clearance contract remains the larger blocker in this canonical model.",
    ]
    (OUTPUT_DIR / "spanload_bending_diagnosis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_fourier_report(align_rows: Sequence[Mapping[str, Any]], family_rows: Sequence[Mapping[str, Any]]) -> None:
    lines = [
        "# Fourier AVL Diagnosis",
        "",
        "Fourier is useful as a controllable spanload family, but AVL remains the authority for realized loading and CDi once the actual geometry exists.",
        "",
        "Current finding:",
        "- More inboard Fourier targets reduce root-bending proxy, but they also reduce ideal e and raise local Cl demand.",
        "- Elliptical and outer-loaded targets increase root-bending proxy versus the current AVL spanload.",
        "- The recorded smooth combo Fourier-vs-AVL mismatch is modest enough for diagnostic use, but it is not yet a controlled design loop.",
        "",
        "Decision rule:",
        "- If AVL setup/reference area/panel contract is sane, AVL is not 'wrong' when it differs from Fourier; the Fourier target is either unrealized by chord/twist/airfoil/incidence or not worth the structural penalty.",
        "- Fourier should be used upstream to propose families, then AVL actual should feed structure and Tier2 work points.",
    ]
    (OUTPUT_DIR / "fourier_avl_diagnosis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_trade_summary(rows: Sequence[Mapping[str, Any]]) -> None:
    lines = [
        "# Spanload Structure Trade Summary",
        "",
        "All variants are diagnostic 6 deg beam-line proxy runs through the canonical inverse-design wrapper with refresh_steps=0. Synthetic spanload rows are not new aerodynamic rankings.",
        "",
    ]
    for row in rows:
        lines.append(
            f"- {row['variant']}: tube {row.get('tube_mass_kg', 'n/a')} kg, clearance {row.get('jig_ground_clearance_min_m', 'n/a')} m, root-bending ratio {row.get('root_bending_ratio_vs_current', 'n/a')}, P_crank estimate {row.get('P_crank_estimate_w', 'n/a')} W"
        )
    lines.extend(
        [
            "",
            "Answer:",
            "- Shifting load inboard can reduce the bending proxy and, in this synthetic case, cuts tube mass from 77.0 kg to 14.7 kg. It still misses 11.5 kg and fails the 20 mm clearance threshold.",
            "- A small outer-load reduction did not escape the 77 kg catalog wall in this MVP run; elliptical loading raised root bending and also stayed at 77 kg.",
            "- The simple Birdman-style exponent-only z(y) test did not help; the useful next step is a control-station loaded-shape search plus wire/layout options, not just a scalar exponent.",
            "- Under the current 34.3 m span, wire layout, and catalog search, 11.5 kg at 6 deg is unrealistic. That is not proof that 6 deg is physically impossible; it is proof that the current structural contract is not yet the right one.",
        ]
    )
    (OUTPUT_DIR / "spanload_structure_trade_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_reference_survey() -> None:
    lines = [
        "# HPA Reference Survey",
        "",
        "## Sourced Facts",
        "",
        "- MIT/Drela structural design paper: Daedalus' desired dihedral was defined by a 2.0 m tip deflection, obtained by matching spar EI distribution with lift-wire length/stiffness; the same paper also emphasizes GJ/torsional stiffness because aeroelastic twist must be known before fabrication. Source: https://web.mit.edu/drela/Public/web/hpa/hpa_structure.pdf",
        "- MDPI HPA FSI paper: Daedalus span is reported as 34 m, area about 31 m2, tip/root chord ratio 1/3, cruise speed 6.7 m/s, and designed tip deflection 2 m. It also states a six-degree design dihedral and notes that dihedral has little direct aerodynamic-performance influence in their AVL sensitivity, while twist can reduce tip loading and bending. Source: https://www.mdpi.com/2226-4310/3/3/26",
        "- The same MDPI paper reports a Daedalus spar reference mass of 8.62 kg and says larger span eventually requires stiffer/heavier spar when the lift wire reaches its useful limit. Source: https://www.mdpi.com/2226-4310/3/3/26",
        "- Tohoku University Windnauts public news reports six championships and a 2023 student-record distance of 42,837.78 m; the 2024 design was described as smaller/different wing shape for higher speed and wind resistance. Source: https://www.tohoku.ac.jp/en/news/university_news/the_skys_the_limit_for_the_tohoku_university_windnauts.html",
        "- DMG Mori reported BIRDMAN HOUSE Iga's 2019 60 km triangular-course record and says the aircraft was made at the DMG Mori Iga factory. Source: https://www.dmgmori.co.jp/corporate/news/pdf/20190828_birdman.pdf",
        "- RAeS describes DMG Mori Birdman House Phoenix as current state-of-the-art efficient HPF and reports a 2023 Phoenix flight of 69.8 km at average 10 m/s. Source: https://www.aerosociety.com/events-calendar/raes-lecture-human-powered-flight-2026-ancient-history-and-the-state-of-the-art/",
        "",
        "## Visual Inference",
        "",
        "- Public Birdman Rally imagery and reporting show very long arcing wings in flight and recovery. A MyNavi field report describes wings drawing a long beautiful arc, but this is not an engineering measurement. Source: https://news.mynavi.jp/article/20190828-birdman/",
        "- From public imagery alone, Birdman House-style bending appears smooth and substantial, but the public sources do not provide beam-line z(y), EI(y), wire pretension, or exact spanload. Treat any claim about outboard-concentrated bending as a hypothesis.",
        "",
        "## Engineering Guess",
        "",
        "- The useful lesson from Daedalus and Japanese teams is not merely 'use 6 deg'; it is to co-design cruise loaded shape, spar EI/GJ distribution, wire length/stiffness, twist, and spanload.",
        "- Birdman House may be achieving low mass through better structural layout, CFRP tube/joint quality, stress-skin/D-box technology, and tuned wire/jig setup, not through spanload alone.",
    ]
    (OUTPUT_DIR / "hpa_reference_survey.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_root_cause_report(trade_rows: Sequence[Mapping[str, Any]]) -> None:
    more_inboard = next((row for row in trade_rows if row["variant"] == "more_inboard_loaded_spanload"), {})
    current = next((row for row in trade_rows if row["variant"] == "current_avl_actual_spanload"), {})
    lines = [
        "# Root Cause Report",
        "",
        "## Clear Diagnosis",
        "",
        "The 6-7 deg states are heavy because the canonical model is being asked to realize a low total loaded beam-line Z with the current span, wire setup, catalog tubes, spanload, and target z(y) scaling. At 6 deg the selected design jumps to thick 8 mm walls and about 77 kg of tube, while at about 8.9 deg it can allow about 1.64 m equivalent elastic recovery and drops to about 11.6 kg.",
        "",
        "This points to a coupled shape/spanload/stiffness recovery problem, not an aerodynamic power problem.",
        "",
        "## Cause Ranking",
        "",
        "1. Most likely root cause: requested loaded z(y) is too globally low/stiff for this beam/wire/jig model. The model cannot allow the natural elastic recovery it wants, so it buys stiffness with huge tube wall thickness.",
        "2. Second likely root cause: the current AVL spanload is not absurdly outboard, but it is still structurally consequential. A deliberately more-inboard synthetic target reduced 6 deg tube mass from 77.0 kg to 14.7 kg, although it still failed mass and clearance.",
        "3. Third likely root cause: beam-line vs aerodynamic z definition is still only a proxy. The 6-7 deg guideline belongs to loaded aero surface/quarter-chord geometry; our sweep controls main/rear structural beam lines.",
        "4. Fourth likely root cause: structural layout/wire geometry/catalog discretization. The current catalog creates large mass jumps, and the single available wire geometry may not exploit lift-wire relief enough at low loaded Z.",
        "",
        "## Fourier And AVL",
        "",
        f"- Current 6 deg tube mass: {current.get('tube_mass_kg', 'n/a')} kg.",
        f"- More-inboard synthetic spanload 6 deg tube mass: {more_inboard.get('tube_mass_kg', 'n/a')} kg.",
        "- Fourier+AVL can reduce structural burden by generating lower root-bending families, but it cannot fix an incompatible loaded z(y)/wire/jig contract by itself.",
        "- The current AVL spanload is already slightly inboard of ellipse; therefore the answer is not 'move load outward like a pretty bent wing'. Moving load outward increases root bending.",
        "",
        "## Birdman House-Style Hypothesis",
        "",
        "Yes, Birdman House-style outboard bending suggests we should change the requested loaded z(y) shape, not just scalar tip z. The simple exponent-only test did not change the 77 kg result, so the right experiment is a control-station loaded-shape family with wire attach/pretension/layout options, then AVL rerun on the realizable loaded shape.",
        "",
        "## Immediate Next Experiment",
        "",
        "Run a two-dimensional structure search at 6-7 deg aerodynamic effective dihedral: target tip z plus loaded-shape exponent/control-station z(y), with wire attach/pretension options. Keep AVL spanload fixed first, then repeat for one more-inboard Fourier target. Success criterion: <11.5 kg tube mass, >=20 mm jig clearance, acceptable wire tension, and AVL loaded-shape power penalty quantified.",
        "",
        "## What Not To Do Yet",
        "",
        "- Do not rerun broad CST/NSGA.",
        "- Do not promote 4.25 m / 13.9 deg as production just because it passes mass.",
        "- Do not treat Fourier e_theory as ranking truth without AVL realization.",
        "- Do not change hard gates until beam-line-to-aero-surface z mapping and real loaded-shape AVL recheck are closed.",
    ]
    (OUTPUT_DIR / "root_cause_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    spanload_rows, metrics, region_rows = _spanload_rows()
    _write_csv(OUTPUT_DIR / "current_spanload_bending.csv", spanload_rows)
    _write_csv(OUTPUT_DIR / "bending_by_span_region.csv", region_rows)
    z_rows = _z_definition_rows()
    _write_csv(OUTPUT_DIR / "z_definition_check.csv", z_rows)
    _write_z_definition_report(z_rows)
    z_shape_rows = _z_shape_rows()
    _write_csv(OUTPUT_DIR / "z_shape_comparison.csv", z_shape_rows)
    align_rows, family_rows = _family_fourier_rows(metrics)
    _write_csv(OUTPUT_DIR / "fourier_avl_alignment.csv", align_rows)
    _write_csv(OUTPUT_DIR / "fourier_family_bending_trade.csv", family_rows)
    trade_rows = _spanload_trade(family_rows)
    _write_csv(OUTPUT_DIR / "spanload_structure_trade.csv", trade_rows)
    _write_spanload_report(metrics, region_rows, trade_rows)
    _write_fourier_report(align_rows, family_rows)
    _write_trade_summary(trade_rows)
    _write_reference_survey()
    _write_root_cause_report(trade_rows)
    print(f"Wrote Phase 12 diagnostics to {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
