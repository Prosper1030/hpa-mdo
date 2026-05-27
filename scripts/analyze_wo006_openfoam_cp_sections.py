#!/usr/bin/env python3
"""Compare accepted WO-006 Fine OpenFOAM section Cp against local XFOIL Cp.

The script is deliberately diagnostic-only: it reads the saved OpenFOAM mesh and
pressure field, extracts three spanwise Cp strips on the primary airfoil
surfaces, and runs XFOIL at matched sectional lift for each local airfoil.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_wo006_openfoam_pressure_residual import (  # noqa: E402
    DRAG_DIR,
    LIFT_DIR,
    RHO,
    U_INF,
    cd_from_force,
    cl_from_force,
    face_area_vector,
    iter_face_window,
    parse_boundary,
    read_internal_scalar,
    read_label_window,
    read_points,
    write_csv,
)
from cfd_rescue.baseline_geometry import interpolate_station, load_baseline_authority  # noqa: E402


HALF_SPAN = 17.166143
NU = 1.4607e-05
Q_KIN = 0.5 * U_INF * U_INF
Q_DYN = 0.5 * RHO * U_INF * U_INF
PRIMARY_PATCHES = ("airfoil_upper", "airfoil_lower")
WALL_PATCHES = (
    "airfoil_upper",
    "airfoil_lower",
    "te_wall",
    "physical_tip_left",
    "physical_tip_right",
)


@dataclass(frozen=True)
class SectionTarget:
    label: str
    eta: float
    half_width: float

    @property
    def eta_min(self) -> float:
        return max(0.0, self.eta - self.half_width)

    @property
    def eta_max(self) -> float:
        return min(1.0, self.eta + self.half_width)


@dataclass
class FaceRecord:
    patch: str
    global_face: int
    center: np.ndarray
    sf: np.ndarray
    area: float
    cp: float
    force: np.ndarray
    x_over_c: float
    eta_abs: float

    @property
    def global_cdp(self) -> float:
        return cd_from_force(self.force)

    @property
    def global_clp(self) -> float:
        return cl_from_force(self.force)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--time", default="2000")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--xfoil", default="/Users/linyuan/.local/bin/xfoil", type=Path)
    parser.add_argument("--n-perim", default=240, type=int)
    parser.add_argument("--station", action="append", default=[])
    parser.add_argument("--x-bins", default=80, type=int)
    args = parser.parse_args()

    targets = parse_targets(args.station)
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    authority = load_baseline_authority(n_perim=args.n_perim, airfoil_loop_mode="open_te_cgrid")
    half_stations = authority.half_stations

    case = args.case
    records = read_primary_wall_records(case=case, time_name=args.time, half_stations=half_stations)
    station_rows, of_cp_rows = summarize_openfoam_sections(
        records=records,
        targets=targets,
        half_stations=half_stations,
        x_bins=args.x_bins,
    )
    write_csv(
        out_dir / "openfoam_cp_sections.csv",
        of_cp_rows,
        [
            "station",
            "eta",
            "eta_min",
            "eta_max",
            "surface",
            "x_over_c",
            "Cp",
            "area_weight_m2",
            "face_count",
        ],
    )

    xfoil_cp_rows: list[dict[str, object]] = []
    xfoil_summary: list[dict[str, object]] = []
    for station_row in station_rows:
        target = next(t for t in targets if t.label == station_row["station"])
        local_station = station_at_eta(half_stations, target.eta)
        xfoil_case_dir = out_dir / "xfoil" / target.label
        cp_rows, summary = run_xfoil_for_station(
            xfoil=args.xfoil,
            station_label=target.label,
            station=local_station,
            target_cl=float(station_row["clp_section"]),
            reynolds=float(station_row["Re"]),
            case_dir=xfoil_case_dir,
        )
        xfoil_cp_rows.extend(cp_rows)
        xfoil_summary.append(summary)

    write_csv(
        out_dir / "xfoil_cp_sections.csv",
        xfoil_cp_rows,
        ["station", "surface", "x_over_c", "Cp"],
    )
    write_csv(
        out_dir / "xfoil_cp_summary.csv",
        xfoil_summary,
        [
            "station",
            "status",
            "target_cl",
            "Re",
            "alpha_deg",
            "cp_file",
            "polar_file",
            "stdout_file",
            "upper_cp_min",
            "upper_x_at_cp_min",
            "upper_cp_0p70_0p90_mean",
            "upper_cp_0p95_1p00_mean",
            "lower_cp_0p95_1p00_mean",
            "te_delta_cp_lower_minus_upper",
            "point_count",
        ],
    )

    comparison_rows = compare_openfoam_to_xfoil(
        station_rows, of_cp_rows, xfoil_cp_rows, xfoil_summary
    )
    write_csv(
        out_dir / "cp_comparison_summary.csv",
        comparison_rows,
        [
            "station",
            "eta",
            "airfoil",
            "chord_m",
            "Re",
            "of_clp_section",
            "of_cdp_section",
            "of_global_CDp_strip",
            "of_upper_cp_min",
            "of_upper_x_at_cp_min",
            "xfoil_status",
            "xfoil_alpha_deg",
            "xfoil_upper_cp_min",
            "xfoil_upper_x_at_cp_min",
            "of_upper_cp_0p70_0p90_mean",
            "xfoil_upper_cp_0p70_0p90_mean",
            "of_upper_cp_0p95_1p00_mean",
            "xfoil_upper_cp_0p95_1p00_mean",
            "of_lower_cp_0p95_1p00_mean",
            "xfoil_lower_cp_0p95_1p00_mean",
            "of_te_delta_cp_lower_minus_upper",
            "xfoil_te_delta_cp_lower_minus_upper",
            "upper_min_delta_of_minus_xfoil",
            "aft_upper_delta_of_minus_xfoil",
            "te_delta_of_minus_xfoil",
        ],
    )

    region_rows = summarize_pressure_regions(records)
    write_csv(
        out_dir / "cp_pressure_region_summary.csv",
        region_rows,
        [
            "span_region",
            "chord_region",
            "surface",
            "face_count",
            "CDp_global",
            "CLp_global",
            "mean_Cp_area_weighted",
        ],
    )
    region_net_rows = summarize_net_pressure_regions(region_rows)
    write_csv(
        out_dir / "cp_pressure_region_net_summary.csv",
        region_net_rows,
        ["span_region", "chord_region", "face_count", "CDp_global", "CLp_global"],
    )

    write_report(
        out_dir / "cp_reasonableness_check.md",
        comparison_rows,
        region_rows,
        region_net_rows,
    )
    write_plots(out_dir, of_cp_rows, xfoil_cp_rows)
    print(f"Wrote {out_dir}")
    return 0


def parse_targets(items: list[str]) -> list[SectionTarget]:
    if not items:
        return [
            SectionTarget("root_eta0p10", 0.10, 0.0125),
            SectionTarget("mid_eta0p50", 0.50, 0.0125),
            SectionTarget("outboard_eta0p80", 0.80, 0.0125),
        ]
    targets: list[SectionTarget] = []
    for item in items:
        parts = item.split(":")
        if len(parts) not in {2, 3}:
            raise ValueError("--station must be label:eta[:half_width]")
        targets.append(
            SectionTarget(
                label=parts[0],
                eta=float(parts[1]),
                half_width=0.0125 if len(parts) == 2 else float(parts[2]),
            )
        )
    return targets


def station_at_eta(half_stations: tuple[object, ...], eta: float) -> object:
    y = eta * HALF_SPAN
    if y <= half_stations[0].y:
        return half_stations[0]
    if y >= half_stations[-1].y:
        return half_stations[-1]
    for left, right in zip(half_stations[:-1], half_stations[1:]):
        if left.y <= y <= right.y:
            local = (y - left.y) / (right.y - left.y)
            return interpolate_station(left, right, local)
    raise ValueError(f"eta out of range: {eta}")


def airfoil_label_at_eta(half_rows: Iterable[dict[str, str]], eta: float) -> str:
    rows = list(half_rows)
    y = eta * HALF_SPAN
    for left, right in zip(rows[:-1], rows[1:]):
        yl = float(left["y_m"])
        yr = float(right["y_m"])
        if yl <= y <= yr:
            left_id = left.get("airfoil_id", "")
            right_id = right.get("airfoil_id", "")
            if left_id == right_id:
                return left_id
            frac = (y - yl) / (yr - yl)
            return f"{left_id}_to_{right_id}@{frac:.3f}"
    return rows[-1].get("airfoil_id", "unknown")


def read_primary_wall_records(
    *,
    case: Path,
    time_name: str,
    half_stations: tuple[object, ...],
) -> list[FaceRecord]:
    mesh = case / "constant" / "polyMesh"
    time_dir = case / time_name
    boundary = parse_boundary(mesh / "boundary")
    wanted = [boundary[name] for name in WALL_PATCHES]
    min_start = min(patch.start_face for patch in wanted)
    max_stop = max(patch.stop_face for patch in wanted)
    window_patches = sorted(
        (
            patch
            for patch in boundary.values()
            if patch.stop_face > min_start and patch.start_face < max_stop
        ),
        key=lambda patch: patch.start_face,
    )

    print(f"Reading p from {time_dir / 'p'}")
    p_internal = read_internal_scalar(time_dir / "p")
    print(f"Reading owners {min_start}:{max_stop}")
    owners = read_label_window(mesh / "owner", min_start, max_stop)
    print("Reading points")
    points = read_points(mesh / "points")

    patches_by_face = [""] * (max_stop - min_start)
    for patch in window_patches:
        local_start = max(patch.start_face, min_start) - min_start
        local_stop = min(patch.stop_face, max_stop) - min_start
        for idx in range(local_start, local_stop):
            patches_by_face[idx] = patch.name

    records: list[FaceRecord] = []
    print(f"Reading faces {min_start}:{max_stop}")
    for local_i, face_points in enumerate(iter_face_window(mesh / "faces", min_start, max_stop)):
        patch_name = patches_by_face[local_i]
        if patch_name not in PRIMARY_PATCHES:
            continue
        coords = points[np.asarray(face_points, dtype=np.int64)]
        center = coords.mean(axis=0)
        eta_abs = min(1.0, abs(float(center[1])) / HALF_SPAN)
        station = station_at_eta(half_stations, eta_abs)
        x_over_c = local_x_over_c(station, center)
        if not (-0.05 <= x_over_c <= 1.05):
            continue
        sf = face_area_vector(coords)
        p_value = float(p_internal[int(owners[local_i])])
        force = RHO * p_value * sf
        records.append(
            FaceRecord(
                patch=patch_name,
                global_face=min_start + local_i,
                center=center,
                sf=sf,
                area=float(np.linalg.norm(sf)),
                cp=p_value / Q_KIN,
                force=force,
                x_over_c=x_over_c,
                eta_abs=eta_abs,
            )
        )
    return records


def local_x_over_c(station: object, center: np.ndarray) -> float:
    theta = math.radians(float(station.twist_deg))
    cos_theta = math.cos(theta)
    sin_theta = math.sin(theta)
    chord = float(station.chord)
    axis = 0.25 * chord
    x_rot_minus_axis = float(center[0]) - float(station.x_le) - axis
    z_rot = float(center[2]) - float(station.z_le)
    x_local = axis + cos_theta * x_rot_minus_axis - sin_theta * z_rot
    return x_local / chord


def summarize_openfoam_sections(
    *,
    records: list[FaceRecord],
    targets: list[SectionTarget],
    half_stations: tuple[object, ...],
    x_bins: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    authority = load_baseline_authority(n_perim=240, airfoil_loop_mode="open_te_cgrid")
    station_rows: list[dict[str, object]] = []
    cp_rows: list[dict[str, object]] = []
    x_edges = np.linspace(0.0, 1.0, x_bins + 1)

    for target in targets:
        station = station_at_eta(half_stations, target.eta)
        selected = [
            record
            for record in records
            if target.eta_min <= record.eta_abs <= target.eta_max
            and 0.0 <= record.x_over_c <= 1.0
        ]
        if not selected:
            raise ValueError(f"No OpenFOAM faces selected for {target.label}")
        force = np.sum([record.force for record in selected], axis=0)
        strip_width = 2.0 * (target.eta_max - target.eta_min) * HALF_SPAN
        q_local_area = Q_DYN * float(station.chord) * strip_width
        station_rows.append(
            {
                "station": target.label,
                "eta": target.eta,
                "eta_min": target.eta_min,
                "eta_max": target.eta_max,
                "chord_m": float(station.chord),
                "Re": U_INF * float(station.chord) / NU,
                "twist_deg": float(station.twist_deg),
                "airfoil": airfoil_label_at_eta(authority.rows, target.eta),
                "face_count": len(selected),
                "strip_width_m_full_wing": strip_width,
                "clp_section": float(np.dot(force, LIFT_DIR) / q_local_area),
                "cdp_section": float(np.dot(force, DRAG_DIR) / q_local_area),
                "global_CDp_strip": float(sum(record.global_cdp for record in selected)),
                "global_CLp_strip": float(sum(record.global_clp for record in selected)),
            }
        )

        for surface in PRIMARY_PATCHES:
            surface_records = [record for record in selected if record.patch == surface]
            for i in range(x_bins):
                low = x_edges[i]
                high = x_edges[i + 1]
                bin_records = [
                    record for record in surface_records if low <= record.x_over_c < high
                ]
                if not bin_records:
                    continue
                area_sum = sum(record.area for record in bin_records)
                cp_mean = sum(record.cp * record.area for record in bin_records) / area_sum
                cp_rows.append(
                    {
                        "station": target.label,
                        "eta": target.eta,
                        "eta_min": target.eta_min,
                        "eta_max": target.eta_max,
                        "surface": "upper" if surface == "airfoil_upper" else "lower",
                        "x_over_c": 0.5 * (low + high),
                        "Cp": cp_mean,
                        "area_weight_m2": area_sum,
                        "face_count": len(bin_records),
                    }
                )
    return station_rows, cp_rows


def run_xfoil_for_station(
    *,
    xfoil: Path,
    station_label: str,
    station: object,
    target_cl: float,
    reynolds: float,
    case_dir: Path,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    case_dir.mkdir(parents=True, exist_ok=True)
    airfoil_path = case_dir / f"{station_label}.dat"
    cp_path = case_dir / "cp.dat"
    polar_path = case_dir / "polar.dat"
    stdout_path = case_dir / "xfoil_stdout.txt"
    input_path = case_dir / "run_xfoil.in"
    write_airfoil_dat(airfoil_path, station_label, station.airfoil_xz)
    for stale_path in (cp_path, polar_path, stdout_path):
        if stale_path.exists():
            stale_path.unlink()

    commands = "\n".join(
        [
            "PLOP",
            "G F",
            "",
            f"LOAD {airfoil_path.name}",
            "PANE",
            "OPER",
            f"VISC {reynolds:.8g}",
            "MACH 0",
            "ITER 180",
            f"CL {target_cl:.8f}",
            "CPWR",
            cp_path.name,
            "",
            "QUIT",
            "",
        ]
    )
    input_path.write_text(commands, encoding="utf-8")
    status = "not_run"
    stdout = ""
    try:
        result = subprocess.run(
            [str(xfoil)],
            input=commands,
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
            cwd=case_dir,
        )
        stdout = result.stdout + "\n" + result.stderr
        status = "returncode_0" if result.returncode == 0 else f"returncode_{result.returncode}"
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "") + "\n" + (exc.stderr or "")
        status = "timeout"
    stdout_path.write_text(stdout, encoding="utf-8", errors="replace")
    for bl_path in case_dir.glob("*.bl"):
        bl_path.unlink()
    strip_trailing_whitespace(stdout_path)
    if cp_path.exists():
        strip_trailing_whitespace(cp_path)

    cp_rows = read_xfoil_cp(cp_path, station_label)
    if not cp_rows:
        status = f"{status}_no_cp"
    polar = parse_last_xfoil_operating_point(stdout)
    summary = summarize_cp_distribution(cp_rows)
    summary.update(
        {
            "station": station_label,
            "status": status,
            "target_cl": target_cl,
            "Re": reynolds,
            "alpha_deg": polar.get("alpha"),
            "cp_file": str(cp_path),
            "polar_file": str(polar_path),
            "stdout_file": str(stdout_path),
        }
    )
    return cp_rows, summary


def write_airfoil_dat(path: Path, label: str, points: Iterable[tuple[float, float]]) -> None:
    lines = [label]
    for x, z in points:
        lines.append(f"{x:.10f} {z:.10f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def strip_trailing_whitespace(path: Path) -> None:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    path.write_text("\n".join(line.rstrip() for line in lines) + "\n", encoding="utf-8")


def read_xfoil_cp(path: Path, station_label: str) -> list[dict[str, object]]:
    if not path.exists():
        return []
    raw: list[tuple[float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        values = parse_float_line(line)
        if len(values) >= 2:
            raw.append((values[0], values[-1]))
    if len(raw) < 4:
        return []
    le_index = min(range(len(raw)), key=lambda idx: raw[idx][0])
    rows: list[dict[str, object]] = []
    for idx, (x, cp) in enumerate(raw):
        rows.append(
            {
                "station": station_label,
                "surface": "upper" if idx <= le_index else "lower",
                "x_over_c": x,
                "Cp": cp,
            }
        )
    return rows


def read_xfoil_polar_last(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        values = parse_float_line(line)
        if len(values) >= 7:
            rows.append(values)
    if not rows:
        return {}
    row = rows[-1]
    return {"alpha": row[0], "CL": row[1], "CD": row[2], "CM": row[4]}


def parse_last_xfoil_operating_point(stdout: str) -> dict[str, float]:
    alpha = cl = cd = None
    for line in stdout.splitlines():
        match = re.search(r"a\s*=\s*([-+0-9.Ee]+)\s+CL\s*=\s*([-+0-9.Ee]+)", line)
        if match:
            alpha = float(match.group(1))
            cl = float(match.group(2))
            continue
        match = re.search(r"CD\s*=\s*([-+0-9.Ee]+)", line)
        if match:
            cd = float(match.group(1))
    out: dict[str, float] = {}
    if alpha is not None:
        out["alpha"] = alpha
    if cl is not None:
        out["CL"] = cl
    if cd is not None:
        out["CD"] = cd
    return out


def parse_float_line(line: str) -> list[float]:
    out: list[float] = []
    for part in line.replace("D", "E").split():
        try:
            out.append(float(part))
        except ValueError:
            continue
    return out


def summarize_cp_distribution(rows: list[dict[str, object]]) -> dict[str, object]:
    if not rows:
        return {
            "upper_cp_min": None,
            "upper_x_at_cp_min": None,
            "upper_cp_0p70_0p90_mean": None,
            "upper_cp_0p95_1p00_mean": None,
            "lower_cp_0p95_1p00_mean": None,
            "te_delta_cp_lower_minus_upper": None,
            "point_count": 0,
        }
    upper = [row for row in rows if row["surface"] == "upper"]
    lower = [row for row in rows if row["surface"] == "lower"]
    min_upper = min(upper, key=lambda row: float(row["Cp"])) if upper else None
    upper_te = mean_cp(upper, 0.95, 1.0)
    lower_te = mean_cp(lower, 0.95, 1.0)
    return {
        "upper_cp_min": None if min_upper is None else float(min_upper["Cp"]),
        "upper_x_at_cp_min": None if min_upper is None else float(min_upper["x_over_c"]),
        "upper_cp_0p70_0p90_mean": mean_cp(upper, 0.70, 0.90),
        "upper_cp_0p95_1p00_mean": upper_te,
        "lower_cp_0p95_1p00_mean": lower_te,
        "te_delta_cp_lower_minus_upper": None
        if upper_te is None or lower_te is None
        else lower_te - upper_te,
        "point_count": len(rows),
    }


def mean_cp(rows: list[dict[str, object]], low: float, high: float) -> float | None:
    vals = [
        float(row["Cp"])
        for row in rows
        if low <= float(row["x_over_c"]) <= high
    ]
    if not vals:
        return None
    return sum(vals) / len(vals)


def compare_openfoam_to_xfoil(
    station_rows: list[dict[str, object]],
    of_cp_rows: list[dict[str, object]],
    xfoil_cp_rows: list[dict[str, object]],
    xfoil_summary_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    xfoil_by_station: dict[str, list[dict[str, object]]] = {}
    of_by_station: dict[str, list[dict[str, object]]] = {}
    for row in xfoil_cp_rows:
        xfoil_by_station.setdefault(str(row["station"]), []).append(row)
    for row in of_cp_rows:
        of_by_station.setdefault(str(row["station"]), []).append(row)

    xfoil_summary_by_station = {
        station: summarize_cp_distribution(rows)
        for station, rows in xfoil_by_station.items()
    }
    of_summary_by_station = {
        station: summarize_cp_distribution(rows)
        for station, rows in of_by_station.items()
    }
    alpha_by_station = {
        str(row["station"]): row.get("alpha_deg") for row in xfoil_summary_rows
    }
    out: list[dict[str, object]] = []
    for row in station_rows:
        station = str(row["station"])
        of = of_summary_by_station.get(station, summarize_cp_distribution([]))
        xf = xfoil_summary_by_station.get(station, summarize_cp_distribution([]))
        out.append(
            {
                "station": station,
                "eta": row["eta"],
                "airfoil": row["airfoil"],
                "chord_m": row["chord_m"],
                "Re": row["Re"],
                "of_clp_section": row["clp_section"],
                "of_cdp_section": row["cdp_section"],
                "of_global_CDp_strip": row["global_CDp_strip"],
                "of_upper_cp_min": of["upper_cp_min"],
                "of_upper_x_at_cp_min": of["upper_x_at_cp_min"],
                "xfoil_status": "available" if xf["point_count"] else "missing",
                "xfoil_alpha_deg": alpha_by_station.get(station),
                "xfoil_upper_cp_min": xf["upper_cp_min"],
                "xfoil_upper_x_at_cp_min": xf["upper_x_at_cp_min"],
                "of_upper_cp_0p70_0p90_mean": of["upper_cp_0p70_0p90_mean"],
                "xfoil_upper_cp_0p70_0p90_mean": xf["upper_cp_0p70_0p90_mean"],
                "of_upper_cp_0p95_1p00_mean": of["upper_cp_0p95_1p00_mean"],
                "xfoil_upper_cp_0p95_1p00_mean": xf["upper_cp_0p95_1p00_mean"],
                "of_lower_cp_0p95_1p00_mean": of["lower_cp_0p95_1p00_mean"],
                "xfoil_lower_cp_0p95_1p00_mean": xf["lower_cp_0p95_1p00_mean"],
                "of_te_delta_cp_lower_minus_upper": of["te_delta_cp_lower_minus_upper"],
                "xfoil_te_delta_cp_lower_minus_upper": xf[
                    "te_delta_cp_lower_minus_upper"
                ],
                "upper_min_delta_of_minus_xfoil": nullable_delta(
                    of["upper_cp_min"], xf["upper_cp_min"]
                ),
                "aft_upper_delta_of_minus_xfoil": nullable_delta(
                    of["upper_cp_0p70_0p90_mean"], xf["upper_cp_0p70_0p90_mean"]
                ),
                "te_delta_of_minus_xfoil": nullable_delta(
                    of["te_delta_cp_lower_minus_upper"],
                    xf["te_delta_cp_lower_minus_upper"],
                ),
            }
        )
    return out


def nullable_delta(a: object, b: object) -> float | None:
    if a is None or b is None:
        return None
    return float(a) - float(b)


def summarize_pressure_regions(records: list[FaceRecord]) -> list[dict[str, object]]:
    span_regions = [
        ("root_0p00_0p25", 0.0, 0.25),
        ("mid_0p25_0p65", 0.25, 0.65),
        ("outboard_0p65_0p90", 0.65, 0.90),
        ("tip_0p90_1p00", 0.90, 1.0),
    ]
    chord_regions = [
        ("LE_0p00_0p20", 0.0, 0.20),
        ("mid_0p20_0p60", 0.20, 0.60),
        ("aft_0p60_0p90", 0.60, 0.90),
        ("TE_0p90_1p00", 0.90, 1.00),
    ]
    rows: list[dict[str, object]] = []
    for span_name, eta_low, eta_high in span_regions:
        for chord_name, x_low, x_high in chord_regions:
            for surface, patch in (("upper", "airfoil_upper"), ("lower", "airfoil_lower")):
                selected = [
                    record
                    for record in records
                    if patch == record.patch
                    and eta_low <= record.eta_abs < eta_high
                    and x_low <= record.x_over_c < x_high
                ]
                if not selected:
                    continue
                area = sum(record.area for record in selected)
                rows.append(
                    {
                        "span_region": span_name,
                        "chord_region": chord_name,
                        "surface": surface,
                        "face_count": len(selected),
                        "CDp_global": sum(record.global_cdp for record in selected),
                        "CLp_global": sum(record.global_clp for record in selected),
                        "mean_Cp_area_weighted": sum(
                            record.cp * record.area for record in selected
                        )
                        / area,
                    }
                )
    return rows


def summarize_net_pressure_regions(region_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_region: dict[tuple[str, str], dict[str, object]] = {}
    for row in region_rows:
        key = (str(row["span_region"]), str(row["chord_region"]))
        item = by_region.setdefault(
            key,
            {
                "span_region": key[0],
                "chord_region": key[1],
                "face_count": 0,
                "CDp_global": 0.0,
                "CLp_global": 0.0,
            },
        )
        item["face_count"] = int(item["face_count"]) + int(row["face_count"])
        item["CDp_global"] = float(item["CDp_global"]) + float(row["CDp_global"])
        item["CLp_global"] = float(item["CLp_global"]) + float(row["CLp_global"])
    return sorted(by_region.values(), key=lambda row: float(row["CDp_global"]), reverse=True)


def write_report(
    path: Path,
    comparison_rows: list[dict[str, object]],
    region_rows: list[dict[str, object]],
    region_net_rows: list[dict[str, object]],
) -> None:
    top_regions = sorted(region_rows, key=lambda row: float(row["CDp_global"]), reverse=True)[:8]
    top_net_regions = region_net_rows[:8]
    lines = [
        "# WO-006 Fine Cp reasonableness check",
        "",
        "This diagnostic extracts OpenFOAM Cp from the accepted Fine saved pressure field on",
        "the primary airfoil surfaces and compares each station with local XFOIL Cp at",
        "matched OpenFOAM pressure-sectional lift.",
        "",
        "## Station comparison",
        "",
        "| station | eta | OF clp | OF cdp | OF upper Cpmin | XFOIL upper Cpmin | OF aft upper Cp | XFOIL aft upper Cp | OF TE dCp | XFOIL TE dCp |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in comparison_rows:
        lines.append(
            "| {station} | {eta:.2f} | {of_clp_section:.3f} | {of_cdp_section:.4f} | "
            "{of_upper_cp_min:.3f} | {xfoil_upper_cp_min:.3f} | "
            "{of_upper_cp_0p70_0p90_mean:.3f} | {xfoil_upper_cp_0p70_0p90_mean:.3f} | "
            "{of_te_delta_cp_lower_minus_upper:.3f} | {xfoil_te_delta_cp_lower_minus_upper:.3f} |".format(
                **format_row(row)
            )
        )
    lines.extend(
        [
            "",
            "## Largest net pressure-drag regions",
            "",
            "| span region | chord region | CDp global | CLp global |",
            "|---|---|---:|---:|",
        ]
    )
    for row in top_net_regions:
        lines.append(
            f"| {row['span_region']} | {row['chord_region']} | "
            f"{float(row['CDp_global']):.6f} | {float(row['CLp_global']):.6f} |"
        )
    lines.extend(
        [
            "",
            "## Largest positive pressure-drag regions",
            "",
            "| span region | chord region | surface | CDp global | mean Cp |",
            "|---|---|---|---:|---:|",
        ]
    )
    for row in top_regions:
        lines.append(
            f"| {row['span_region']} | {row['chord_region']} | {row['surface']} | "
            f"{float(row['CDp_global']):.6f} | {float(row['mean_Cp_area_weighted']):.3f} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def format_row(row: dict[str, object]) -> dict[str, object]:
    out = dict(row)
    for key, value in list(out.items()):
        if value is None:
            out[key] = float("nan")
    return out


def write_plots(
    out_dir: Path,
    of_cp_rows: list[dict[str, object]],
    xfoil_cp_rows: list[dict[str, object]],
) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return
    stations = sorted({str(row["station"]) for row in of_cp_rows})
    for station in stations:
        fig, ax = plt.subplots(figsize=(7.0, 4.5))
        for source, rows, style in (
            ("OpenFOAM", of_cp_rows, "-"),
            ("XFOIL", xfoil_cp_rows, "--"),
        ):
            for surface, color in (("upper", "tab:blue"), ("lower", "tab:orange")):
                pts = [
                    row
                    for row in rows
                    if str(row["station"]) == station and row["surface"] == surface
                ]
                if not pts:
                    continue
                pts.sort(key=lambda row: float(row["x_over_c"]))
                ax.plot(
                    [float(row["x_over_c"]) for row in pts],
                    [float(row["Cp"]) for row in pts],
                    linestyle=style,
                    color=color,
                    label=f"{source} {surface}",
                )
        ax.invert_yaxis()
        ax.set_xlabel("x/c")
        ax.set_ylabel("Cp")
        ax.set_title(station)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=8)
        fig.tight_layout()
        fig.savefig(out_dir / f"cp_{station}.png", dpi=160)
        plt.close(fig)


if __name__ == "__main__":
    raise SystemExit(main())
