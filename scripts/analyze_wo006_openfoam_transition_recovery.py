#!/usr/bin/env python3
"""Build compact, restart-safe WO-006 SST/LM recovery evidence.

The analyzer never runs a solver.  It reads per-iteration coefficient logs,
saved OpenFOAM fields, wall-face yPlus, and patch-owner cells on the accepted
Fine mesh.  Large volume fields are processed one at a time.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import math
import re
import shutil
import sys
from pathlib import Path

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import analyze_wo006_openfoam_pressure_residual as mesh_tools  # noqa: E402
import run_wo006_hpa_model_architecture_sensitivity as campaign  # noqa: E402


EXPECTED_CELLS = 6_090_240
NU = 1.4607e-5
PRIMARY_PATCHES = ("airfoil_upper", "airfoil_lower")
YPLUS_PATCHES = (*PRIMARY_PATCHES, "te_wall", "physical_tip_left", "physical_tip_right")
FIELD_NAMES = ("U", "p", "k", "omega", "nut", "gammaInt", "ReThetat")
SST_FIELD_NAMES = ("U", "p", "k", "omega", "nut")
SA_TOTAL_PHYSICAL = {
    "CD_pressure": 0.0229500141077,
    "CD_viscous": 0.0103155482202,
    "CD_total": 0.03326556,
    "CL": 1.160927,
    "CmPitch": -0.1322138,
}
SA_FORCE_HISTORY = (
    campaign.ROOT
    / "output/baseline_A_team_release/wo006_su2_baseline_validation"
    / "cfd_release_v0_hpa_solver_campaign_repair/fine_force_history.csv"
)
NONFINITE_TOKEN = re.compile(
    r"(?<![A-Za-z])[-+]?(?:nan|inf(?:inity)?)(?![A-Za-z])",
    flags=re.I,
)
SOLVER_RESIDUAL = re.compile(
    r"(?:smoothSolver|GAMG):\s+Solving for ([^,]+), Initial residual = ([^,]+), "
    r"Final residual = ([^,]+)"
)
CONTINUITY = re.compile(
    r"time step continuity errors\s*:\s*sum local = ([^,]+), global = ([^,]+), "
    r"cumulative = ([^\s]+)"
)


def numeric_time_dirs(case_dir: Path) -> list[Path]:
    rows: list[tuple[float, Path]] = []
    for path in case_dir.iterdir():
        if not path.is_dir():
            continue
        try:
            value = float(path.name)
        except ValueError:
            continue
        rows.append((value, path))
    return [path for _, path in sorted(rows)]


def _internal_header(line: str) -> tuple[str, str] | None:
    stripped = line.strip().rstrip(";")
    if not stripped.startswith("internalField"):
        return None
    if " uniform " in f" {stripped} ":
        return ("uniform", stripped.split("uniform", 1)[1].strip())
    if " nonuniform " in f" {stripped} ":
        return ("nonuniform", "")
    raise ValueError(f"Unsupported internalField declaration: {stripped}")


def _parse_vector(text: str) -> tuple[float, float, float]:
    values = text.strip().strip("();").split()
    if len(values) != 3:
        raise ValueError(f"Expected vector, got {text!r}")
    return (float(values[0]), float(values[1]), float(values[2]))


def summarize_field(path: Path, field: str, expected_cells: int = EXPECTED_CELLS) -> dict[str, object]:
    """Stream one OpenFOAM volume field and report strict finite ranges."""
    vector = field == "U"
    count = 0
    total = 0.0
    minimum = math.inf
    maximum = -math.inf
    component_min = [math.inf, math.inf, math.inf]
    component_max = [-math.inf, -math.inf, -math.inf]
    gamma_lt_01 = gamma_mid = gamma_gt_09 = gamma_outside = 0
    nonfinite_tokens = 0
    representation = "missing"
    found_internal = False

    def observe(raw_value: str) -> None:
        nonlocal count, total, minimum, maximum
        nonlocal gamma_lt_01, gamma_mid, gamma_gt_09, gamma_outside
        if vector:
            values = _parse_vector(raw_value)
            for index, value in enumerate(values):
                component_min[index] = min(component_min[index], value)
                component_max[index] = max(component_max[index], value)
            value = math.sqrt(sum(item * item for item in values))
        else:
            value = float(raw_value.strip().rstrip(";"))
        count += 1
        total += value
        minimum = min(minimum, value)
        maximum = max(maximum, value)
        if field == "gammaInt":
            gamma_lt_01 += value < 0.1
            gamma_mid += 0.1 <= value <= 0.9
            gamma_gt_09 += value > 0.9
            gamma_outside += value < 0.0 or value > 1.001

    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            nonfinite_tokens += len(NONFINITE_TOKEN.findall(line))
            if found_internal:
                continue
            header = _internal_header(line)
            if header is None:
                continue
            representation, inline = header
            if representation == "uniform":
                observe(inline)
                found_internal = True
                continue
            count_line = next(stream)
            nonfinite_tokens += len(NONFINITE_TOKEN.findall(count_line))
            declared_count = int(count_line.strip())
            opening = next(stream)
            if opening.strip() != "(":
                raise ValueError(f"Missing internalField list opener in {path}")
            for _ in range(declared_count):
                value_line = next(stream)
                nonfinite_tokens += len(NONFINITE_TOKEN.findall(value_line))
                observe(value_line)
            if count != declared_count:
                raise ValueError(f"Expected {declared_count} values, read {count}: {path}")
            found_internal = True

    finite = bool(
        count
        and nonfinite_tokens == 0
        and math.isfinite(total)
        and math.isfinite(minimum)
        and math.isfinite(maximum)
    )
    row: dict[str, object] = {
        "time": path.parent.name,
        "field": field,
        "representation": representation,
        "count": count,
        "expected_count": expected_cells,
        "count_ok": representation == "nonuniform" and count == expected_cells,
        "finite": finite,
        "nonfinite_tokens": nonfinite_tokens,
        "min": minimum,
        "mean": total / count if count else math.nan,
        "max": maximum,
    }
    if vector:
        for index, axis in enumerate("xyz"):
            row[f"{axis}_min"] = component_min[index]
            row[f"{axis}_max"] = component_max[index]
    if field == "gammaInt" and count:
        row.update(
            {
                "pct_lt_0p1": 100.0 * gamma_lt_01 / count,
                "pct_0p1_to_0p9": 100.0 * gamma_mid / count,
                "pct_gt_0p9": 100.0 * gamma_gt_09 / count,
                "pct_outside_0_to_1p001": 100.0 * gamma_outside / count,
            }
        )
    if field == "nut":
        row["mean_over_nu"] = float(row["mean"]) / NU
        row["max_over_nu"] = float(row["max"]) / NU
    return row


def read_patch_values(path: Path, patch: str, expected_faces: int) -> list[float]:
    in_patch = False
    with path.open(encoding="utf-8", errors="replace") as stream:
        for raw in stream:
            line = raw.strip()
            if line == patch:
                in_patch = True
                continue
            if not in_patch:
                continue
            if line.startswith("value") and "nonuniform" in line:
                count = int(next(stream).strip())
                if next(stream).strip() != "(":
                    raise ValueError(f"Missing patch list opener for {patch}: {path}")
                values = [float(next(stream).strip()) for _ in range(count)]
                if count != expected_faces:
                    raise ValueError(f"{patch}: expected {expected_faces} faces, got {count}")
                return values
            if line.startswith("value") and "uniform" in line:
                value = float(line.rstrip(";").split()[-1])
                return [value] * expected_faces
            if line == "}":
                return []
    return []


def yplus_rows(path: Path, boundary: dict[str, mesh_tools.PatchInfo], definition: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for patch in YPLUS_PATCHES:
        expected = boundary[patch].n_faces
        values = read_patch_values(path, patch, expected)
        finite = len(values) == expected and all(math.isfinite(value) for value in values)
        if not values:
            rows.append({"definition": definition, "patch": patch, "faces": 0, "finite": False})
            continue
        rows.append(
            {
                "definition": definition,
                "patch": patch,
                "faces": len(values),
                "expected_faces": expected,
                "finite": finite,
                "min": min(values),
                "mean": sum(values) / len(values),
                "max": max(values),
                "pct_lt_1": 100.0 * sum(value < 1 for value in values) / len(values),
                "pct_lt_5": 100.0 * sum(value < 5 for value in values) / len(values),
                "pct_gt_20": 100.0 * sum(value > 20 for value in values) / len(values),
            }
        )
    return rows


def linear_slope(values: list[float], times: list[float]) -> float:
    x_mean = sum(times) / len(times)
    y_mean = sum(values) / len(values)
    denominator = sum((value - x_mean) ** 2 for value in times)
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(times, values)) / denominator


def summarize_solver_log(path: Path) -> dict[str, object]:
    """Summarize numerical health without retaining a multi-megabyte solver log."""
    times: list[float] = []
    initial_residuals: list[float] = []
    final_residuals: list[float] = []
    continuity_local: list[float] = []
    continuity_global: list[float] = []
    continuity_cumulative: list[float] = []
    k_bounding_count = 0
    omega_bounding_count = 0
    lambda_warning_count = 0
    foam_warning_count = 0
    nonfinite_tokens = 0
    ended_normally = False

    with path.open(encoding="utf-8", errors="replace") as stream:
        for raw in stream:
            line = raw.strip()
            nonfinite_tokens += len(NONFINITE_TOKEN.findall(line))
            if line.startswith("Time ="):
                value = float(line.split("=", 1)[1].strip())
                times.append(value)
            residual = SOLVER_RESIDUAL.search(line)
            if residual:
                initial_residuals.append(float(residual.group(2)))
                final_residuals.append(float(residual.group(3)))
            continuity = CONTINUITY.search(line)
            if continuity:
                continuity_local.append(float(continuity.group(1)))
                continuity_global.append(float(continuity.group(2)))
                continuity_cumulative.append(float(continuity.group(3)))
            k_bounding_count += "bounding k," in line
            omega_bounding_count += "bounding omega," in line
            lambda_warning_count += "maxLambdaIter" in line
            foam_warning_count += line.startswith("FOAM Warning")
            ended_normally = ended_normally or line == "End"

    numeric_values = (
        times
        + initial_residuals
        + final_residuals
        + continuity_local
        + continuity_global
        + continuity_cumulative
    )
    finite = bool(numeric_values and all(math.isfinite(value) for value in numeric_values))
    return {
        "log": path.name,
        "bytes": path.stat().st_size,
        "time_count": len(times),
        "time_min": min(times) if times else None,
        "time_max": max(times) if times else None,
        "ended_normally": ended_normally,
        "numeric_values_finite": finite,
        "nonfinite_tokens": nonfinite_tokens,
        "residual_solve_count": len(initial_residuals),
        "initial_residual_max": max(initial_residuals) if initial_residuals else None,
        "final_residual_max": max(final_residuals) if final_residuals else None,
        "continuity_count": len(continuity_local),
        "continuity_sum_local_max_abs": max(map(abs, continuity_local)) if continuity_local else None,
        "continuity_global_max_abs": max(map(abs, continuity_global)) if continuity_global else None,
        "continuity_cumulative_max_abs": (
            max(map(abs, continuity_cumulative)) if continuity_cumulative else None
        ),
        "k_bounding_count": k_bounding_count,
        "omega_bounding_count": omega_bounding_count,
        "lambda_warning_count": lambda_warning_count,
        "foam_warning_count": foam_warning_count,
    }


def summarize_solver_logs(case_dir: Path, case_name: str, solver: str) -> dict[str, object]:
    chunk_logs = sorted(case_dir.glob(f"log.{solver}_{case_name}_*_to_*.txt"))
    if not chunk_logs:
        fallback = case_dir / f"log.{solver}_{case_name}.txt"
        chunk_logs = [fallback] if fallback.exists() else []
    rows = [summarize_solver_log(path) for path in chunk_logs]
    return {
        "case": case_name,
        "solver": solver,
        "chunk_count": len(rows),
        "all_logs_ended_normally": bool(rows and all(row["ended_normally"] for row in rows)),
        "all_logged_numeric_values_finite": bool(
            rows
            and all(row["numeric_values_finite"] and row["nonfinite_tokens"] == 0 for row in rows)
        ),
        "total_k_bounding_count": sum(int(row["k_bounding_count"]) for row in rows),
        "total_omega_bounding_count": sum(int(row["omega_bounding_count"]) for row in rows),
        "total_lambda_warning_count": sum(int(row["lambda_warning_count"]) for row in rows),
        "chunks": rows,
    }


def force_gate(rows: list[dict[str, float]], latest_time: float) -> dict[str, object]:
    final = rows[-campaign.MIN_FORCE_WINDOW_ROWS :]
    summary = campaign.summarize_force_rows(final)
    summary["source_unique_rows"] = len(rows)
    summary["exactly_100_rows_written"] = len(final) == campaign.MIN_FORCE_WINDOW_ROWS
    summary["force_reaches_latest_checkpoint"] = bool(
        final and math.isclose(final[-1]["time"], latest_time, abs_tol=1e-9)
    )
    if len(final) < campaign.MIN_FORCE_WINDOW_ROWS:
        summary["formal_gate_pass"] = False
        return summary
    times = [row["time"] for row in final]
    for key in ("CD_pressure", "CD_viscous", "CD_total", "CL", "CmPitch"):
        source_key = "CD_total" if key == "CD_total" else key
        values = [row[source_key] for row in final]
        summary[f"{key}_linear_slope_per_iteration"] = linear_slope(values, times)
        summary[f"{key}_mean_first_25"] = sum(values[:25]) / 25
        summary[f"{key}_mean_last_25"] = sum(values[-25:]) / 25
    summary["max_abs_CD_component_closure_error"] = max(
        abs(row["CD_pressure"] + row["CD_viscous"] - row["CD_total"]) for row in final
    )
    summary["formal_gate_pass"] = bool(
        summary.get("stable_force_window")
        and summary.get("finite_force_history")
        and summary.get("contiguous_final_window")
        and summary["force_reaches_latest_checkpoint"]
    )
    return summary


def sa_comparison_rows(
    final_force_rows: list[dict[str, float]], gate: dict[str, object]
) -> list[dict[str, object]]:
    if not final_force_rows:
        return []
    last = final_force_rows[-1]
    rows: list[dict[str, object]] = []
    for metric in ("CD_pressure", "CD_viscous", "CD_total", "CL", "CmPitch"):
        sa_value = SA_TOTAL_PHYSICAL[metric]
        case_last = last[metric]
        case_window_mean = float(gate[f"{metric}_mean_final_window"])
        rows.append(
            {
                "metric": metric,
                "accepted_sa": sa_value,
                "case_last": case_last,
                "case_final_100_mean": case_window_mean,
                "last_minus_sa": case_last - sa_value,
                "last_percent_vs_sa": 100.0 * (case_last - sa_value) / abs(sa_value),
                "final_100_mean_minus_sa": case_window_mean - sa_value,
                "final_100_mean_percent_vs_sa": (
                    100.0 * (case_window_mean - sa_value) / abs(sa_value)
                ),
                "comparison_basis": "identical total_physical patches/reference/directions",
            }
        )
    return rows


def extract_surface_geometry(case_dir: Path, boundary: dict[str, mesh_tools.PatchInfo]) -> dict[str, np.ndarray]:
    patches = [boundary[name] for name in PRIMARY_PATCHES]
    start = min(patch.start_face for patch in patches)
    stop = max(patch.stop_face for patch in patches)
    owners = mesh_tools.read_label_window(case_dir / "constant/polyMesh/owner", start, stop)
    points = mesh_tools.read_points(case_dir / "constant/polyMesh/points")
    patch_names: list[str] = []
    owner_ids: list[int] = []
    centers: list[np.ndarray] = []
    for offset, face_points in enumerate(
        mesh_tools.iter_face_window(case_dir / "constant/polyMesh/faces", start, stop)
    ):
        face = start + offset
        patch = next((item.name for item in patches if item.start_face <= face < item.stop_face), "")
        if not patch:
            continue
        patch_names.append(patch)
        owner_ids.append(int(owners[offset]))
        centers.append(points[np.asarray(face_points, dtype=np.int64)].mean(axis=0))
    return {
        "patch": np.asarray(patch_names),
        "owner": np.asarray(owner_ids, dtype=np.int64),
        "center": np.asarray(centers, dtype=np.float64),
    }


def transition_surface_rows(
    case_dir: Path,
    time_dir: Path,
    boundary: dict[str, mesh_tools.PatchInfo],
    span_bins: int,
    chord_bins: int,
) -> list[dict[str, object]]:
    geometry = extract_surface_geometry(case_dir, boundary)
    owners = geometry["owner"]
    centers = geometry["center"]
    fields: dict[str, np.ndarray] = {}
    for name in ("gammaInt", "ReThetat", "nut", "k"):
        internal = mesh_tools.read_internal_scalar(time_dir / name)
        if len(internal) != EXPECTED_CELLS or not np.isfinite(internal).all():
            raise ValueError(f"Non-finite or wrong-size {name} field at {time_dir.name}")
        fields[name] = internal[owners]
        del internal

    abs_y = np.abs(centers[:, 1])
    eta = abs_y / abs_y.max()
    span_index = np.minimum((eta * span_bins).astype(int), span_bins - 1)
    chord_fraction = np.empty(len(eta), dtype=np.float64)
    for index in range(span_bins):
        selected = span_index == index
        x = centers[selected, 0]
        chord_fraction[selected] = (x - x.min()) / max(float(x.max() - x.min()), 1e-12)
    chord_index = np.minimum((chord_fraction * chord_bins).astype(int), chord_bins - 1)
    sides = np.where(centers[:, 1] < 0, "left", "right")

    rows: list[dict[str, object]] = []
    for patch in PRIMARY_PATCHES:
        for side in ("left", "right"):
            for span in range(span_bins):
                for chord in range(chord_bins):
                    selected = (
                        (geometry["patch"] == patch)
                        & (sides == side)
                        & (span_index == span)
                        & (chord_index == chord)
                    )
                    count = int(selected.sum())
                    if not count:
                        continue
                    gamma = fields["gammaInt"][selected]
                    row: dict[str, object] = {
                        "time": time_dir.name,
                        "patch": patch,
                        "side": side,
                        "eta_min": span / span_bins,
                        "eta_max": (span + 1) / span_bins,
                        "x_over_c_min": chord / chord_bins,
                        "x_over_c_max": (chord + 1) / chord_bins,
                        "faces": count,
                        "gamma_min": float(gamma.min()),
                        "gamma_mean": float(gamma.mean()),
                        "gamma_max": float(gamma.max()),
                        "gamma_pct_lt_0p1": float(100 * np.mean(gamma < 0.1)),
                        "gamma_pct_0p1_to_0p9": float(100 * np.mean((gamma >= 0.1) & (gamma <= 0.9))),
                        "gamma_pct_gt_0p9": float(100 * np.mean(gamma > 0.9)),
                    }
                    for name in ("ReThetat", "nut", "k"):
                        values = fields[name][selected]
                        row[f"{name}_mean"] = float(values.mean())
                        row[f"{name}_max"] = float(values.max())
                    row["nut_over_nu_mean"] = float(row["nut_mean"]) / NU
                    rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("")
        return
    fields: list[str] = []
    for row in rows:
        fields.extend(key for key in row if key not in fields)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def checkpoint_change_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_field: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_field.setdefault(str(row["field"]), []).append(row)
    output: list[dict[str, object]] = []
    for field, values in by_field.items():
        values.sort(key=lambda row: float(row["time"]))
        if len(values) != 2:
            continue
        old, new = values
        item: dict[str, object] = {
            "field": field,
            "from_time": old["time"],
            "to_time": new["time"],
            "both_finite_and_sized": bool(
                old.get("finite")
                and old.get("count_ok")
                and new.get("finite")
                and new.get("count_ok")
            ),
        }
        for key in ("min", "mean", "max"):
            before = float(old[key])
            after = float(new[key])
            item[f"{key}_delta"] = after - before
            item[f"{key}_relative_change"] = (
                math.inf if abs(before) < 1e-30 else (after - before) / abs(before)
            )
        output.append(item)
    return output


def write_dictionary_diff(case_dir: Path, output: Path, case_name: str) -> None:
    files = (
        "system/controlDict",
        "system/fvSchemes",
        "system/fvSolution",
        "constant/turbulenceProperties",
    )
    lines: list[str] = []
    for relative in files:
        authority = campaign.SOURCE_CASE / relative
        candidate = case_dir / relative
        lines.extend(
            difflib.unified_diff(
                authority.read_text().splitlines(keepends=True),
                candidate.read_text().splitlines(keepends=True),
                fromfile=f"accepted_sa/{relative}",
                tofile=f"{case_name}/{relative}",
            )
        )
    diff_text = "".join(lines)
    normalized = "\n".join(line.rstrip() for line in diff_text.splitlines())
    output.write_text(normalized + ("\n" if normalized else ""))


def write_dictionary_snapshots(case_dir: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for relative in (
        "system/controlDict",
        "system/fvSchemes",
        "system/fvSolution",
        "constant/turbulenceProperties",
    ):
        source = case_dir / relative
        shutil.copy2(source, output / relative.replace("/", "__"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_configuration_manifest(
    case_dir: Path,
    output: Path,
    case_name: str,
    spec: campaign.CaseSpec,
    times: list[Path],
) -> None:
    mesh_files = ("boundary", "points", "faces", "owner", "neighbour")
    mesh = case_dir / "constant/polyMesh"
    case_manifest_path = case_dir / "architecture_sensitivity_manifest.json"
    case_manifest = json.loads(case_manifest_path.read_text()) if case_manifest_path.exists() else {}
    status_path = case_dir / "architecture_sensitivity_status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {}
    case_mesh_sha256 = {name: sha256_file(mesh / name) for name in mesh_files}
    authority_mesh = campaign.SOURCE_CASE / "constant/polyMesh"
    authority_mesh_sha256 = {name: sha256_file(authority_mesh / name) for name in mesh_files}
    transition_inlet = case_manifest.get("transition_inlet", {})
    freestream_turbulence_inputs = {
        key: transition_inlet[key]
        for key in ("Tu", "k", "L_for_LM", "omega_for_LM")
        if key in transition_inlet
    }
    lm_transition_inputs: dict[str, object]
    if spec.turbulence_model == "kOmegaSSTLM":
        lm_transition_inputs = {
            key: transition_inlet[key]
            for key in ("gammaInt", "ReThetat")
            if key in transition_inlet
        }
    else:
        lm_transition_inputs = {"applicable": False, "reason": "fully turbulent kOmegaSST"}
    manifest = {
        "case": case_name,
        "solver": spec.solver,
        "turbulence_model": spec.turbulence_model,
        "openfoam_release": "OpenCFD-v2512",
        "accepted_fine_cells": EXPECTED_CELLS,
        "same_mesh": case_mesh_sha256 == authority_mesh_sha256,
        "retained_times": [float(path.name) for path in times],
        "reference": {
            "rho_kg_m3": campaign.RHO,
            "velocity_m_s": campaign.U_INF,
            "nu_m2_s": NU,
            "aoa_deg": 0.18,
            "Sref_m2": campaign.S_REF,
            "Cref_m": campaign.C_REF,
            "drag_direction": campaign.DRAG_DIR,
            "lift_direction": campaign.LIFT_DIR,
        },
        "force_basis": {
            "name": "total_physical",
            "patches": ["airfoil_upper", "airfoil_lower", "te_wall"],
            "excluded_direct_force_patches": ["physical_tip_left", "physical_tip_right"],
        },
        "freestream_turbulence_inputs": freestream_turbulence_inputs,
        "lm_transition_inputs": lm_transition_inputs,
        "transition_input_classification": {
            "Tu_0p5pct": "assumed physical/model input; not measured HPA atmosphere",
            "L_0p001c": "numerical freestream-decay stabilization input; not atmosphere truth",
            "gammaInt_1": (
                "model-recommended freestream inlet convention"
                if spec.turbulence_model == "kOmegaSSTLM"
                else "not applicable to fully turbulent kOmegaSST"
            ),
            "ReThetat_879p6744": (
                "LM correlation-derived inlet value; not measured momentum thickness"
                if spec.turbulence_model == "kOmegaSSTLM"
                else "not applicable to fully turbulent kOmegaSST"
            ),
        },
        "scratch": {
            "solver_visible_root": status.get("scratch_root"),
            "external_ssd_backing_root": status.get("scratch_backing_root"),
            "free_before_bytes": status.get("scratch_free_before_bytes"),
            "free_after_bytes": status.get("scratch_free_after_bytes"),
        },
        "case_mesh_sha256": case_mesh_sha256,
        "accepted_fine_mesh_sha256": authority_mesh_sha256,
        "accepted_sa_provenance": {
            "force_history": str(SA_FORCE_HISTORY),
            "force_history_sha256": sha256_file(SA_FORCE_HISTORY),
            "total_physical": SA_TOTAL_PHYSICAL,
        },
        "dictionary_sha256": {
            relative: sha256_file(case_dir / relative)
            for relative in (
                "system/controlDict",
                "system/fvSchemes",
                "system/fvSolution",
                "constant/turbulenceProperties",
            )
        },
    }
    output.write_text(json.dumps(manifest, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case-name")
    parser.add_argument("--span-bins", type=int, default=5)
    parser.add_argument("--chord-bins", type=int, default=10)
    parser.add_argument("--skip-surface-bins", action="store_true")
    args = parser.parse_args(argv)

    case_dir = args.case_dir.resolve()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    case_name = args.case_name or case_dir.name
    spec = campaign.CASE_SPECS[case_name]
    status_path = case_dir / "architecture_sensitivity_status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {}
    times = numeric_time_dirs(case_dir)
    if len(times) < 2 or float(times[-1].name) <= 2000:
        raise RuntimeError("Need two evolved retained checkpoints after time 2000")

    force_rows, force_sources = campaign.collect_force_rows(case_dir, spec)
    final_force_rows = force_rows[-campaign.MIN_FORCE_WINDOW_ROWS :]
    final_force_output = [
        {
            "time": row["time"],
            "CD_pressure": row["CD_pressure"],
            "CD_viscous": row["CD_viscous"],
            "CD_total": row["CD_total"],
            "CL": row["CL"],
            "CmPitch": row["CmPitch"],
        }
        for row in final_force_rows
    ]
    write_csv(output / "final_100_force_history.csv", final_force_output)
    gate = force_gate(force_rows, float(times[-1].name))
    gate["force_sources"] = force_sources
    gate["accepted_sa_total_physical"] = SA_TOTAL_PHYSICAL
    if final_force_rows:
        last = final_force_rows[-1]
        gate["delta_vs_sa"] = {
            "CD_pressure": last["CD_pressure"] - SA_TOTAL_PHYSICAL["CD_pressure"],
            "CD_viscous": last["CD_viscous"] - SA_TOTAL_PHYSICAL["CD_viscous"],
            "CD_total": last["CD_total"] - SA_TOTAL_PHYSICAL["CD_total"],
            "CL": last["CL"] - SA_TOTAL_PHYSICAL["CL"],
            "CmPitch": last["CmPitch"] - SA_TOTAL_PHYSICAL["CmPitch"],
        }
    (output / "force_gate.json").write_text(json.dumps(gate, indent=2) + "\n")
    write_csv(output / "sa_fine_comparison.csv", sa_comparison_rows(final_force_rows, gate))
    solver_log_summary = summarize_solver_logs(case_dir, case_name, spec.solver)
    (output / "solver_log_summary.json").write_text(
        json.dumps(solver_log_summary, indent=2) + "\n"
    )

    required_fields = FIELD_NAMES if spec.turbulence_model == "kOmegaSSTLM" else SST_FIELD_NAMES
    field_rows: list[dict[str, object]] = []
    for time_dir in times[-2:]:
        for field in required_fields:
            path = time_dir / field
            if not path.exists():
                field_rows.append({"time": time_dir.name, "field": field, "finite": False, "status": "missing"})
                continue
            field_rows.append(summarize_field(path, field))
    write_csv(output / "checkpoint_field_ranges.csv", field_rows)
    write_csv(output / "checkpoint_field_changes.csv", checkpoint_change_rows(field_rows))

    boundary = mesh_tools.parse_boundary(case_dir / "constant/polyMesh/boundary")
    yplus_path = times[-1] / "yPlus"
    y_rows = yplus_rows(yplus_path, boundary, "wall_function_default") if yplus_path.exists() else []
    for shear_name in ("yPlusShear:yPlus", "yPlusShear_yPlus"):
        shear_path = times[-1] / shear_name
        if shear_path.exists():
            y_rows.extend(yplus_rows(shear_path, boundary, "shear_derived_useWallFunction_false"))
            break
    write_csv(output / "yplus_summary.csv", y_rows)
    primary_yplus_acceptable = all(
        any(
            row.get("patch") == patch
            and row.get("finite")
            and int(row.get("faces", 0)) == int(row.get("expected_faces", -1))
            and float(row.get("max", math.inf)) < 5.0
            and float(row.get("pct_gt_20", math.inf)) == 0.0
            for row in y_rows
        )
        for patch in PRIMARY_PATCHES
    )

    if not args.skip_surface_bins and spec.turbulence_model == "kOmegaSSTLM":
        surface_rows = transition_surface_rows(
            case_dir,
            times[-1],
            boundary,
            span_bins=args.span_bins,
            chord_bins=args.chord_bins,
        )
        write_csv(output / "transition_surface_bins.csv", surface_rows)

    write_dictionary_diff(case_dir, output / "openfoam_dictionary_diff.patch", case_name)
    write_dictionary_snapshots(case_dir, output / "dictionary_snapshots")
    write_configuration_manifest(
        case_dir,
        output / "configuration_manifest.json",
        case_name,
        spec,
        times,
    )
    qualification = {
        "case": case_name,
        "latest_time": float(times[-1].name),
        "formal_force_gate_pass": gate["formal_gate_pass"],
        "solver_logs_finite_and_normally_terminated": bool(
            solver_log_summary["all_logs_ended_normally"]
            and solver_log_summary["all_logged_numeric_values_finite"]
        ),
        "all_required_fields_finite_and_sized": all(
            row.get("finite") and row.get("count_ok") for row in field_rows
        ),
        "primary_yplus_available": all(
            any(row.get("patch") == patch and row.get("finite") for row in y_rows)
            for patch in PRIMARY_PATCHES
        ),
        "primary_yplus_wall_resolved_acceptable": primary_yplus_acceptable,
        "latest_attempt_rss_guard_pass": bool(
            status.get("solve_peak_rss_bytes")
            and float(status["solve_peak_rss_bytes"]) <= float(status["solve_max_rss_bytes"])
            and not status.get("solve_stopped_by_memory_guard", False)
        ),
        "latest_attempt_scratch_gate_pass": bool(
            status.get("scratch_free_before_bytes")
            and float(status["scratch_free_before_bytes"]) >= 20 * 10**9
        ),
        "warning_counts": {
            "k_bounding": solver_log_summary["total_k_bounding_count"],
            "omega_bounding": solver_log_summary["total_omega_bounding_count"],
            "maxLambdaIter": solver_log_summary["total_lambda_warning_count"],
        },
        "note": "Force pass is necessary but not sufficient; component cancellation and transition-field evolution require engineering review.",
    }
    (output / "qualification_status.json").write_text(json.dumps(qualification, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
