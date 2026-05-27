#!/usr/bin/env python3
"""Summarize the WO-006 kOmegaSSTLM transition OpenFOAM diagnostic case."""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path
from typing import Iterable


FORCE_COLUMNS = (
    "Time",
    "Cd",
    "Cd(f)",
    "Cd(r)",
    "Cl",
    "Cl(f)",
    "Cl(r)",
    "CmPitch",
    "CmRoll",
    "CmYaw",
    "Cs",
    "Cs(f)",
    "Cs(r)",
)

RHO = 1.225
U_INF = 6.5
AREF = 33.420059598
NU = 1.4607e-05
DRAG_DIR = (0.999995065, 0.0, 0.00314158749)
LIFT_DIR = (-0.00314158749, 0.0, 0.999995065)
WALL_PATCHES = (
    "airfoil_upper",
    "airfoil_lower",
    "te_wall",
    "physical_tip_left",
    "physical_tip_right",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sa-grid-csv", type=Path, required=True)
    args = parser.parse_args()

    case_dir = args.case_dir.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    groups = {
        name: read_coefficients(case_dir, name)
        for name in (
            "primary",
            "total_physical",
            "airfoil_upper",
            "airfoil_lower",
            "te_wall",
            "physical_tip_left",
            "physical_tip_right",
        )
    }
    write_history(out_dir / "transition_force_history.csv", groups)
    force_summary = write_force_summary(out_dir / "transition_force_summary.csv", groups)
    split_rows = write_pressure_viscous_split(
        out_dir / "transition_pressure_viscous_split.csv", case_dir
    )

    boundary_counts = read_boundary_counts(case_dir / "constant" / "polyMesh" / "boundary")
    latest_time = latest_numeric_time(case_dir)
    yplus_path = case_dir / latest_time / "yPlus"
    yplus_rows = write_yplus_summary(
        out_dir / "transition_yplus_summary.csv", yplus_path, boundary_counts
    )
    wall_shear_rows = write_wall_shear_summary(
        out_dir / "transition_wall_shear_summary.csv",
        case_dir / latest_time / "wallShearStress",
        boundary_counts,
    )
    cp_row = write_cp_summary(out_dir / "transition_cp_internal_summary.csv", case_dir / latest_time / "p")

    field_rows = []
    for field in ("gammaInt", "ReThetat", "nut"):
        field_path = case_dir / latest_time / field
        if field_path.exists():
            field_rows.append(scalar_internal_summary(field, field_path))
    write_dict_rows(out_dir / "transition_field_summary.csv", field_rows)

    old_fine = read_sa_fine(args.sa_grid_csv)
    write_comparison(out_dir / "transition_vs_sa_comparison.csv", old_fine, force_summary, split_rows)
    write_report(
        out_dir / "transition_sst_lm_Tu0p5_report.md",
        case_dir,
        latest_time,
        old_fine,
        force_summary,
        split_rows,
        yplus_rows,
        field_rows,
        wall_shear_rows,
        cp_row,
    )


def read_coefficients(case_dir: Path, group: str) -> list[dict[str, float]]:
    path = case_dir / "postProcessing" / f"forceCoeffs_{group}"
    files = sorted(path.glob("*/coefficient.dat"), key=lambda p: float(p.parent.name))
    rows: list[dict[str, float]] = []
    for file in files:
        with file.open() as handle:
            for line in handle:
                if not line.strip() or line.startswith("#"):
                    continue
                vals = [float(item) for item in line.split()]
                rows.append(dict(zip(FORCE_COLUMNS, vals)))
    rows.sort(key=lambda row: row["Time"])
    return rows


def write_history(path: Path, groups: dict[str, list[dict[str, float]]]) -> None:
    times = sorted({row["Time"] for rows in groups.values() for row in rows})
    by_group = {name: {row["Time"]: row for row in rows} for name, rows in groups.items()}
    columns = ["Time"]
    for group in groups:
        columns.extend([f"{group}_Cd", f"{group}_Cl", f"{group}_CmPitch"])
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for time in times:
            out = {"Time": time}
            for group in groups:
                row = by_group[group].get(time, {})
                out[f"{group}_Cd"] = row.get("Cd")
                out[f"{group}_Cl"] = row.get("Cl")
                out[f"{group}_CmPitch"] = row.get("CmPitch")
            writer.writerow(out)


def write_force_summary(path: Path, groups: dict[str, list[dict[str, float]]]) -> dict[str, dict[str, float]]:
    summary: dict[str, dict[str, float]] = {}
    for group, rows in groups.items():
        if not rows:
            continue
        last = rows[-1]
        item = {
            "Time": last["Time"],
            "Cd": last["Cd"],
            "Cl": last["Cl"],
            "CmPitch": last["CmPitch"],
            "rows": len(rows),
        }
        for window in (20, 50, 100):
            item[f"Cd_window{window}_rel_span"] = relative_span(rows, "Cd", window)
            item[f"Cl_window{window}_rel_span"] = relative_span(rows, "Cl", window)
            item[f"CmPitch_window{window}_rel_span"] = relative_span(rows, "CmPitch", window)
        summary[group] = item
    write_dict_rows(path, [{"group": group, **values} for group, values in summary.items()])
    return summary


def relative_span(rows: list[dict[str, float]], key: str, window: int) -> float | None:
    if len(rows) < window:
        return None
    vals = [row[key] for row in rows[-window:]]
    mean = sum(vals) / len(vals)
    if abs(mean) < 1e-30:
        return None
    return (max(vals) - min(vals)) / abs(mean)


def write_pressure_viscous_split(path: Path, case_dir: Path) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    q_s = 0.5 * RHO * U_INF**2 * AREF
    for group in (
        "primary",
        "total_physical",
        "airfoil_upper",
        "airfoil_lower",
        "te_wall",
        "physical_tip_left",
        "physical_tip_right",
    ):
        force = read_last_force(case_dir, group)
        if not force:
            continue
        pressure = force["pressure"]
        viscous = force["viscous"]
        rows.append(
            {
                "group": group,
                "Time": force["Time"],
                "CD_pressure": dot(pressure, DRAG_DIR) / q_s,
                "CD_viscous": dot(viscous, DRAG_DIR) / q_s,
                "CD_pressure_plus_viscous": dot(add(pressure, viscous), DRAG_DIR) / q_s,
                "CL_pressure": dot(pressure, LIFT_DIR) / q_s,
                "CL_viscous": dot(viscous, LIFT_DIR) / q_s,
                "CL_pressure_plus_viscous": dot(add(pressure, viscous), LIFT_DIR) / q_s,
            }
        )
    write_dict_rows(path, rows)
    return rows


def read_last_force(case_dir: Path, group: str) -> dict[str, object] | None:
    path = case_dir / "postProcessing" / f"forces_{group}"
    files = sorted(path.glob("*/force.dat"), key=lambda p: float(p.parent.name))
    last: dict[str, object] | None = None
    for file in files:
        with file.open() as handle:
            for line in handle:
                if not line.strip() or line.startswith("#"):
                    continue
                vals = [float(item) for item in line.split()]
                last = {
                    "Time": vals[0],
                    "total": tuple(vals[1:4]),
                    "pressure": tuple(vals[4:7]),
                    "viscous": tuple(vals[7:10]),
                }
    return last


def read_boundary_counts(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    current: str | None = None
    name_re = re.compile(r"^\s*([A-Za-z0-9_]+)\s*$")
    with path.open() as handle:
        for line in handle:
            match = name_re.match(line)
            if match:
                current = match.group(1)
            elif current and "nFaces" in line:
                counts[current] = int(line.split()[1].rstrip(";"))
    return counts


def latest_numeric_time(case_dir: Path) -> str:
    times = [path.name for path in case_dir.iterdir() if path.is_dir() and is_float(path.name)]
    return max(times, key=float)


def is_float(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def write_yplus_summary(
    path: Path, field_path: Path, boundary_counts: dict[str, int]
) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    for patch in WALL_PATCHES:
        values = list(read_scalar_patch_values(field_path, patch, boundary_counts.get(patch, 0)))
        if not values:
            continue
        rows.append(
            {
                "patch": patch,
                "faces": len(values),
                "min": min(values),
                "mean": sum(values) / len(values),
                "max": max(values),
                "pct_lt_1": pct(values, lambda value: value < 1),
                "pct_lt_5": pct(values, lambda value: value < 5),
                "pct_gt_20": pct(values, lambda value: value > 20),
            }
        )
    write_dict_rows(path, rows)
    return rows


def write_wall_shear_summary(
    path: Path, field_path: Path, boundary_counts: dict[str, int]
) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    if not field_path.exists():
        path.write_text("", encoding="utf-8")
        return rows
    for patch in WALL_PATCHES:
        vectors = list(read_vector_patch_values(field_path, patch, boundary_counts.get(patch, 0)))
        if not vectors:
            continue
        mags = [math.sqrt(x * x + y * y + z * z) for x, y, z in vectors]
        rows.append(
            {
                "patch": patch,
                "faces": len(mags),
                "mag_min": min(mags),
                "mag_mean": sum(mags) / len(mags),
                "mag_max": max(mags),
            }
        )
    write_dict_rows(path, rows)
    return rows


def write_cp_summary(path: Path, field_path: Path) -> dict[str, float | str | int]:
    row = {"field": "Cp", "source": "p_internal_at_saved_field_time"}
    values = []
    q_kinematic = 0.5 * U_INF**2
    with field_path.open() as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith("internalField") and "nonuniform" in line:
                count = int(next(handle).strip())
                next(handle)
                total = 0.0
                min_v = math.inf
                max_v = -math.inf
                for _ in range(count):
                    value = float(next(handle).strip()) / q_kinematic
                    total += value
                    min_v = min(min_v, value)
                    max_v = max(max_v, value)
                row.update({"count": count, "min": min_v, "mean": total / count, "max": max_v})
                write_dict_rows(path, [row])
                return row
            if line.startswith("internalField") and "uniform" in line:
                value = float(line.rstrip(";").split()[-1]) / q_kinematic
                row.update({"count": 1, "min": value, "mean": value, "max": value})
                write_dict_rows(path, [row])
                return row
    row["status"] = "missing"
    write_dict_rows(path, [row])
    return row


def read_scalar_patch_values(field_path: Path, patch: str, n_faces: int) -> Iterable[float]:
    in_patch = False
    with field_path.open() as handle:
        for raw in handle:
            line = raw.strip()
            if line == patch:
                in_patch = True
                continue
            if not in_patch:
                continue
            if line.startswith("value") and "nonuniform" in line:
                count = int(next(handle).strip())
                next(handle)
                for _ in range(count):
                    yield float(next(handle).strip())
                return
            if line.startswith("value") and "uniform" in line:
                value = float(line.rstrip(";").split()[-1])
                yield from (value for _ in range(n_faces))
                return
            if line == "}":
                return


def read_vector_patch_values(field_path: Path, patch: str, n_faces: int) -> Iterable[tuple[float, float, float]]:
    in_patch = False
    with field_path.open() as handle:
        for raw in handle:
            line = raw.strip()
            if line == patch:
                in_patch = True
                continue
            if not in_patch:
                continue
            if line.startswith("value") and "nonuniform" in line:
                count = int(next(handle).strip())
                next(handle)
                for _ in range(count):
                    yield parse_vector(next(handle).strip())
                return
            if line.startswith("value") and "uniform" in line:
                value = parse_vector(line.split("uniform", 1)[1].rstrip(";").strip())
                yield from (value for _ in range(n_faces))
                return
            if line == "}":
                return


def parse_vector(text: str) -> tuple[float, float, float]:
    parts = text.strip().strip("()").split()
    return (float(parts[0]), float(parts[1]), float(parts[2]))


def scalar_internal_summary(field: str, field_path: Path) -> dict[str, float | str | int]:
    with field_path.open() as handle:
        for raw in handle:
            line = raw.strip()
            if line.startswith("internalField") and "nonuniform" in line:
                count = int(next(handle).strip())
                next(handle)
                total = 0.0
                min_v = math.inf
                max_v = -math.inf
                lt01 = lt05 = gt09 = 0
                for _ in range(count):
                    value = float(next(handle).strip())
                    total += value
                    min_v = min(min_v, value)
                    max_v = max(max_v, value)
                    lt01 += value < 0.1
                    lt05 += value < 0.5
                    gt09 += value > 0.9
                mean = total / count
                row: dict[str, float | str | int] = {
                    "field": field,
                    "representation": "nonuniform",
                    "count": count,
                    "min": min_v,
                    "mean": mean,
                    "max": max_v,
                }
                if field == "gammaInt":
                    row["pct_lt_0p1"] = 100 * lt01 / count
                    row["pct_lt_0p5"] = 100 * lt05 / count
                    row["pct_gt_0p9"] = 100 * gt09 / count
                if field == "nut":
                    row["nut_over_nu_mean"] = mean / NU
                    row["nut_over_nu_max"] = max_v / NU
                return row
            if line.startswith("internalField") and "uniform" in line:
                value = float(line.rstrip(";").split()[-1])
                out = stats_row(field, [value])
                out["representation"] = "uniform"
                return out
    return {"field": field, "representation": "missing"}


def stats_row(field: str, values: list[float]) -> dict[str, float | str | int]:
    return {
        "field": field,
        "count": len(values),
        "min": min(values),
        "mean": sum(values) / len(values),
        "max": max(values),
    }


def pct(values: list[float], predicate) -> float:
    return 100.0 * sum(1 for value in values if predicate(value)) / len(values)


def read_sa_fine(path: Path) -> dict[str, float]:
    with path.open() as handle:
        for row in csv.DictReader(handle):
            if row.get("grid") == "fine":
                return {key: parse_float(value) for key, value in row.items() if key != "grid"}
    raise RuntimeError(f"fine row not found in {path}")


def parse_float(value: str) -> float:
    if value in ("", "True", "False"):
        return math.nan
    return float(value)


def write_comparison(
    path: Path,
    old_fine: dict[str, float],
    force_summary: dict[str, dict[str, float]],
    split_rows: list[dict[str, float | str]],
) -> None:
    split = {str(row["group"]): row for row in split_rows}
    primary = force_summary["primary"]
    total = force_summary["total_physical"]
    rows = [
        {
            "quantity": "CD_primary",
            "SA_fine": old_fine["CD_primary"],
            "transition_Tu0p5": primary["Cd"],
            "delta_abs": primary["Cd"] - old_fine["CD_primary"],
            "delta_pct": 100 * (primary["Cd"] / old_fine["CD_primary"] - 1),
        },
        {
            "quantity": "CD_total_physical",
            "SA_fine": old_fine["CD_total_physical"],
            "transition_Tu0p5": total["Cd"],
            "delta_abs": total["Cd"] - old_fine["CD_total_physical"],
            "delta_pct": 100 * (total["Cd"] / old_fine["CD_total_physical"] - 1),
        },
        {
            "quantity": "CL_primary",
            "SA_fine": old_fine["CL_primary"],
            "transition_Tu0p5": primary["Cl"],
            "delta_abs": primary["Cl"] - old_fine["CL_primary"],
            "delta_pct": 100 * (primary["Cl"] / old_fine["CL_primary"] - 1),
        },
        {
            "quantity": "CD_pressure_total_physical",
            "SA_fine": old_fine["CD_pressure_total_physical"],
            "transition_Tu0p5": split["total_physical"]["CD_pressure"],
            "delta_abs": split["total_physical"]["CD_pressure"] - old_fine["CD_pressure_total_physical"],
            "delta_pct": 100
            * (split["total_physical"]["CD_pressure"] / old_fine["CD_pressure_total_physical"] - 1),
        },
        {
            "quantity": "CD_viscous_total_physical",
            "SA_fine": old_fine["CD_viscous_total_physical"],
            "transition_Tu0p5": split["total_physical"]["CD_viscous"],
            "delta_abs": split["total_physical"]["CD_viscous"] - old_fine["CD_viscous_total_physical"],
            "delta_pct": 100
            * (split["total_physical"]["CD_viscous"] / old_fine["CD_viscous_total_physical"] - 1),
        },
    ]
    write_dict_rows(path, rows)


def write_report(
    path: Path,
    case_dir: Path,
    latest_time: str,
    old_fine: dict[str, float],
    force_summary: dict[str, dict[str, float]],
    split_rows: list[dict[str, float | str]],
    yplus_rows: list[dict[str, float | str]],
    field_rows: list[dict[str, float | str | int]],
    wall_shear_rows: list[dict[str, float | str]],
    cp_row: dict[str, float | str | int],
) -> None:
    split = {str(row["group"]): row for row in split_rows}
    total = force_summary.get("total_physical", {})
    primary = force_summary.get("primary", {})
    y_by_patch = {str(row["patch"]): row for row in yplus_rows}
    field_by_name = {str(row["field"]): row for row in field_rows}
    force_time = max(
        (
            float(row.get("Time", 0.0))
            for row in force_summary.values()
            if row.get("Time") is not None
        ),
        default=math.nan,
    )
    omega_warnings, omega_max = omega_bound_summary(case_dir / "log.simpleFoam_transition_2200")
    status = "usable as engineering diagnostic"
    reason = "force history is finite and wall yPlus is in the transition-model range"
    if total.get("Cd_window50_rel_span") is None or total.get("Cd_window50_rel_span", 1.0) > 0.01:
        status = "not usable due to instability / insufficient force-window convergence"
        reason = "the available force window has not met the 1% CD stability gate"
    if omega_warnings:
        status = "not usable due to instability / bad transition-equation behavior"
        reason = "omega was repeatedly bounded to extreme values during the continuation"
    if is_float(latest_time) and not math.isnan(force_time) and float(latest_time) < force_time:
        status = "not usable due to instability / no evolved transition field written"
        reason = "the solver was terminated after unstable force drift before a converged transition field was written"
    if y_by_patch:
        primary_wall_rows = [
            y_by_patch[patch]
            for patch in ("airfoil_upper", "airfoil_lower", "te_wall")
            if patch in y_by_patch
        ]
        max_primary_y = max(float(row["max"]) for row in primary_wall_rows)
        if max_primary_y > 20:
            status = "not usable due to wall resolution"
            reason = "primary airfoil/TE wall faces exceed yPlus 20"
    lines = [
        "# Transition SST LM Tu0p5 Diagnostic",
        "",
        f"Verdict: `{status}`",
        "",
        f"- reason: {reason}",
        f"- case: `{case_dir}`",
        f"- latest saved field time analyzed: `{latest_time}`",
        f"- force history reached: `{force_time:g}`",
        "- model: `kOmegaSSTLM` Langtry-Menter gamma-ReTheta Transition SST",
        "- source BC pattern: OpenFOAM-v2512 `tutorials/incompressible/simpleFoam/T3A`, adapted to this case's `farfield`/`outlet` convention.",
        "- preserved refs: `U=6.5 m/s`, `rhoInf=1.225`, `nu=1.4607e-05`, `AoA=0.18 deg`, `lRef=1.003721543`, `Aref=33.420059598`.",
        "- transition inlet values: `Tu=0.5%`, `k=0.001584375 m2/s2`, `c_ref=1.003721543 m`, `L=0.07026050801 m`, `omega=1.03432513267 1/s`, `ReThetat=879.6744`, `gammaInt=1`.",
        f"- omega bounding warnings: `{omega_warnings}`; largest reported omega max: `{omega_max}`.",
        "- CD/CL numbers below are the last unstable force samples, not accepted converged coefficients.",
        "",
        "## SA Fine vs Transition",
        "",
        "| quantity | SA Fine | transition Tu0p5 | delta % |",
        "|---|---:|---:|---:|",
        row_line("CD_total_physical", old_fine["CD_total_physical"], total.get("Cd")),
        row_line("CD_primary", old_fine["CD_primary"], primary.get("Cd")),
        row_line("CL_primary", old_fine["CL_primary"], primary.get("Cl")),
        row_line("CD_pressure_total_physical", old_fine["CD_pressure_total_physical"], split["total_physical"]["CD_pressure"]),
        row_line("CD_viscous_total_physical", old_fine["CD_viscous_total_physical"], split["total_physical"]["CD_viscous"]),
        "",
        "## yPlus",
        "",
        "| patch | mean | max | % < 1 | % < 5 | % > 20 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for patch in ("airfoil_upper", "airfoil_lower", "te_wall", "physical_tip_left", "physical_tip_right"):
        row = y_by_patch.get(patch)
        if row:
            lines.append(
                f"| `{patch}` | {float(row['mean']):.6g} | {float(row['max']):.6g} | "
                f"{float(row['pct_lt_1']):.3f} | {float(row['pct_lt_5']):.3f} | {float(row['pct_gt_20']):.3f} |"
            )
    gamma = field_by_name.get("gammaInt", {})
    retheta = field_by_name.get("ReThetat", {})
    nut = field_by_name.get("nut", {})
    lines.extend(
        [
            "",
            "## Transition Fields",
            "",
            "The listed transition fields are the saved initialization fields at time 2000. The unstable continuation reached the force log at later iterations, but no evolved gamma/ReTheta/nut field was written before termination.",
            f"- gammaInt mean/min/max: `{gamma.get('mean')}` / `{gamma.get('min')}` / `{gamma.get('max')}`",
            f"- gammaInt volume fractions: `<0.1 {gamma.get('pct_lt_0p1')}%`, `<0.5 {gamma.get('pct_lt_0p5')}%`, `>0.9 {gamma.get('pct_gt_0p9')}%`",
            f"- ReThetat mean/min/max: `{retheta.get('mean')}` / `{retheta.get('min')}` / `{retheta.get('max')}`",
            f"- nut/nu mean/max: `{nut.get('nut_over_nu_mean')}` / `{nut.get('nut_over_nu_max')}`",
            "",
            "## Engineering Read",
            "",
            "- Primary airfoil/TE yPlus is in a reasonable near-wall range for a transition-model diagnostic, but the physical tip closure walls are not.",
            "- The unstable transition run does not support claiming a drag reduction relative to SA/Fine. The last force sample shows higher CD and much higher pressure-drag split, while omega behavior is not physically trustworthy.",
            "- Because the evolved gammaInt field was not written, transition location, laminar separation bubble behavior, and TE pressure-drag localization remain unanswered.",
            f"- Saved-field Cp internal summary: min/mean/max `{cp_row.get('min')}` / `{cp_row.get('mean')}` / `{cp_row.get('max')}`.",
            f"- Wall-shear patch summaries were written for `{len(wall_shear_rows)}` wall patches.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def omega_bound_summary(path: Path) -> tuple[int, float | None]:
    if not path.exists():
        return (0, None)
    count = 0
    max_seen: float | None = None
    pattern = re.compile(r"bounding omega, .* max: ([0-9.eE+-]+)")
    with path.open(errors="ignore") as handle:
        for line in handle:
            match = pattern.search(line)
            if not match:
                continue
            count += 1
            value = float(match.group(1))
            if max_seen is None or value > max_seen:
                max_seen = value
    return (count, max_seen)


def row_line(name: str, old: float, new: float | None) -> str:
    if new is None:
        return f"| `{name}` | {old:.8g} |  |  |"
    return f"| `{name}` | {old:.8g} | {new:.8g} | {100 * (new / old - 1):.3f} |"


def write_dict_rows(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def dot(left: Iterable[float], right: Iterable[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def add(left: Iterable[float], right: Iterable[float]) -> tuple[float, float, float]:
    values = tuple(a + b for a, b in zip(left, right))
    return values  # type: ignore[return-value]


if __name__ == "__main__":
    main()
