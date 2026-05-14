#!/usr/bin/env python3
"""Localize WO-006J high drag from SU2 surface and force-breakdown outputs.

This is a diagnostic tool, not a CFD completion runner. It reads an existing
SU2 mesh plus one or more case directories containing ``surface.csv`` and
``forces_breakdown.dat`` and writes a compact pressure-drag source report.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALIDATION_ROOT = (
    REPO_ROOT / "output" / "baseline_A_team_release" / "wo006_su2_baseline_validation"
)
DEFAULT_DIAG_DIR = DEFAULT_VALIDATION_ROOT / "wo006j_high_cd_invalid_ladder_diagnosis"
DEFAULT_MESH_PATH = (
    DEFAULT_VALIDATION_ROOT
    / "wo006j_farfield20x40_euler_force_breakdown_probe_wing020"
    / "mesh.su2"
)
DEFAULT_SECTION_TABLE = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "final_candidate_package"
    / "geometry_exports"
    / "avl_parity"
    / "current_avl_compromise_conservative_closed"
    / "section_table.csv"
)
DEFAULT_CASES = (
    "euler:"
    + str(DEFAULT_VALIDATION_ROOT / "wo006j_farfield20x40_euler_force_breakdown_probe_wing020"),
    "rans_bl:"
    + str(DEFAULT_VALIDATION_ROOT / "wo006j_farfield20x40_rans_bl_force_breakdown_probe_wing020"),
)
DEFAULT_REF_FORCE_N = 864.8484902
DEFAULT_REF_AREA_M2 = 33.420059598


Vector = tuple[float, float, float]


@dataclass(frozen=True)
class SU2WallMesh:
    coordinates: dict[int, Vector]
    triangles: tuple[tuple[int, int, int], ...]
    marker: str


def parse_forces_breakdown_text(text: str) -> dict[str, Any]:
    """Parse SU2 ``forces_breakdown.dat`` total and surface coefficients."""

    total_coefficients: dict[str, dict[str, float]] = {}
    surface_coefficients: dict[str, dict[str, dict[str, float]]] = {}
    current_surface: str | None = None

    for raw_line in text.splitlines():
        surface_match = re.match(r"\s*Surface name:\s*(.+?)\s*$", raw_line)
        if surface_match is not None:
            current_surface = surface_match.group(1).strip()
            surface_coefficients.setdefault(current_surface, {})
            continue

        parsed = _parse_force_breakdown_line(raw_line)
        if parsed is None:
            continue
        key, values = parsed
        if current_surface is None:
            total_coefficients[key] = values
        else:
            surface_coefficients.setdefault(current_surface, {})[key] = values

    return {**total_coefficients, "surface_coefficients": surface_coefficients}


def read_su2_wall_triangles(path: Path | str, *, marker: str = "wing_wall") -> SU2WallMesh:
    """Read SU2 point coordinates and triangular elements for one boundary marker."""

    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    npoin_index = next(
        (index for index, line in enumerate(lines) if line.strip().startswith("NPOIN=")),
        None,
    )
    if npoin_index is None:
        raise ValueError(f"SU2 mesh missing NPOIN: {path}")
    point_count = int(lines[npoin_index].split("=", maxsplit=1)[1])
    coordinates: dict[int, Vector] = {}
    for offset in range(point_count):
        parts = lines[npoin_index + 1 + offset].split()
        if len(parts) < 3:
            raise ValueError(f"Malformed SU2 point line: {lines[npoin_index + 1 + offset]!r}")
        point_id = int(parts[3]) if len(parts) >= 4 else offset
        coordinates[point_id] = (float(parts[0]), float(parts[1]), float(parts[2]))

    marker_index = next(
        (index for index, line in enumerate(lines) if line.strip() == f"MARKER_TAG= {marker}"),
        None,
    )
    if marker_index is None:
        raise ValueError(f"SU2 mesh missing marker {marker!r}: {path}")
    marker_elems = int(lines[marker_index + 1].split("=", maxsplit=1)[1])
    triangles: list[tuple[int, int, int]] = []
    for offset in range(marker_elems):
        parts = lines[marker_index + 2 + offset].split()
        if parts and parts[0] == "5":
            triangles.append((int(parts[1]), int(parts[2]), int(parts[3])))
    if not triangles:
        raise ValueError(f"Marker {marker!r} contains no triangular elements")

    return SU2WallMesh(coordinates=coordinates, triangles=tuple(triangles), marker=marker)


def integrate_pressure_source(
    *,
    mesh: SU2WallMesh,
    surface_csv_path: Path | str,
    ref_force: float,
    ref_area: float,
    section_table_path: Path | str | None = None,
) -> dict[str, Any]:
    """Integrate pressure over marker triangles and group drag by geometry bins."""

    if ref_force <= 0.0:
        raise ValueError("ref_force must be positive")
    if ref_area <= 0.0:
        raise ValueError("ref_area must be positive")

    pressures = _read_surface_pressures(Path(surface_csv_path))
    section_table = _read_section_table(Path(section_table_path)) if section_table_path else None
    y_edges = _section_y_edges(section_table)
    y_labels = _bin_labels(y_edges, precision=2)
    x_edges = (0.0, 0.02, 0.1, 0.3, 0.6, 0.9, 0.98, 1.0)
    x_labels = _bin_labels(x_edges, precision=2)
    normal_labels = (
        "x_forward_or_aft_facing",
        "y_tip_or_span_cap",
        "z_upper_lower_like",
        "mixed",
    )

    total_force = [0.0, 0.0, 0.0]
    total_area = 0.0
    abs_projected = [0.0, 0.0, 0.0]
    signed_area = [0.0, 0.0, 0.0]
    by_y = {label: 0.0 for label in y_labels}
    by_x = {label: 0.0 for label in x_labels}
    by_role = {label: 0.0 for label in normal_labels}
    by_pressure_sign = {"positive_pressure": 0.0, "negative_pressure": 0.0}
    top_positive: list[dict[str, Any]] = []
    top_negative: list[dict[str, Any]] = []

    for triangle_index, triangle in enumerate(mesh.triangles):
        try:
            v0, v1, v2 = (mesh.coordinates[node] for node in triangle)
            pressure = sum(pressures[node] for node in triangle) / 3.0
        except KeyError as exc:
            raise ValueError(
                f"Surface CSV is missing pressure for mesh node {exc.args[0]}"
            ) from exc

        area_vector = _scale(_cross(_sub(v1, v0), _sub(v2, v0)), 0.5)
        area = _norm(area_vector)
        if area <= 0.0:
            continue
        force = _scale(area_vector, -pressure / ref_force)
        centroid = _scale(_add(_add(v0, v1), v2), 1.0 / 3.0)
        normal = _scale(area_vector, 1.0 / area)
        cd = force[0]

        for index, value in enumerate(force):
            total_force[index] += value
        for index, value in enumerate(area_vector):
            abs_projected[index] += abs(value)
            signed_area[index] += value
        total_area += area

        _add_bucket(by_y, _bin_label(abs(centroid[1]), y_edges, y_labels), cd)
        _add_bucket(
            by_x, _bin_label(_x_over_local_chord(centroid, section_table), x_edges, x_labels), cd
        )
        normal_role = _normal_role(normal)
        _add_bucket(by_role, normal_role, cd)
        _add_bucket(
            by_pressure_sign,
            "positive_pressure" if pressure >= 0.0 else "negative_pressure",
            cd,
        )

        contribution = {
            "tri_index": triangle_index,
            "nodes": list(triangle),
            "centroid": list(centroid),
            "area_m2": area,
            "pressure_pa": pressure,
            "normal": list(normal),
            "cd_pressure_contribution": cd,
            "cl_pressure_contribution": force[2],
            "abs_y_m": abs(centroid[1]),
            "x_over_local_chord": _x_over_local_chord(centroid, section_table),
            "normal_role": normal_role,
        }
        _keep_top(top_positive, contribution, reverse=True)
        _keep_top(top_negative, contribution, reverse=False)

    return {
        "surface_point_count": len(pressures),
        "triangle_count": len(mesh.triangles),
        "integrated_pressure_coefficients_from_surface_csv": {
            "cd": total_force[0],
            "cfy": total_force[1],
            "cl": total_force[2],
        },
        "geometry_surface_metrics": {
            "wetted_area_m2": total_area,
            "abs_projected_area_x_m2": abs_projected[0],
            "abs_projected_area_y_m2": abs_projected[1],
            "abs_projected_area_z_m2": abs_projected[2],
            "closed_surface_one_sided_x_projected_area_estimate_m2": 0.5 * abs_projected[0],
            "abs_projected_area_x_over_sref": abs_projected[0] / ref_area,
            "signed_area_vector_m2": signed_area,
        },
        "pressure_cd_by_abs_y_band_m": by_y,
        "pressure_cd_by_x_over_local_chord_bin": by_x,
        "pressure_cd_by_normal_role": by_role,
        "pressure_cd_by_pressure_sign": by_pressure_sign,
        "top_positive_pressure_cd_triangles": top_positive,
        "top_negative_pressure_cd_triangles": top_negative,
    }


def build_drag_source_report(
    *,
    mesh_path: Path,
    cases: Mapping[str, Path],
    output_dir: Path,
    section_table_path: Path = DEFAULT_SECTION_TABLE,
    ref_force: float = DEFAULT_REF_FORCE_N,
    ref_area: float = DEFAULT_REF_AREA_M2,
    marker: str = "wing_wall",
) -> dict[str, Any]:
    mesh = read_su2_wall_triangles(mesh_path, marker=marker)
    case_payloads: dict[str, Any] = {}
    for label, case_dir in cases.items():
        surface_csv = case_dir / "surface.csv"
        forces_breakdown = case_dir / "forces_breakdown.dat"
        pressure = integrate_pressure_source(
            mesh=mesh,
            surface_csv_path=surface_csv,
            ref_force=ref_force,
            ref_area=ref_area,
            section_table_path=section_table_path,
        )
        pressure["forces_breakdown"] = parse_forces_breakdown_text(
            forces_breakdown.read_text(encoding="utf-8", errors="replace")
        )
        case_payloads[label] = pressure

    report = {
        "schema_version": "wo006j_drag_source_localization.v1",
        "diagnostic_only": True,
        "mesh_path": str(mesh_path),
        "geometry_source": str(section_table_path),
        "wall_marker": marker,
        "ref_force_n": ref_force,
        "ref_area_m2": ref_area,
        "cases": case_payloads,
        "engineering_read": _engineering_read(case_payloads),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "drag_source_localization.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "drag_source_localization.md").write_text(
        _markdown_report(report),
        encoding="utf-8",
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh", type=Path, default=DEFAULT_MESH_PATH)
    parser.add_argument("--section-table", type=Path, default=DEFAULT_SECTION_TABLE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIAG_DIR)
    parser.add_argument("--case", action="append", default=list(DEFAULT_CASES))
    parser.add_argument("--marker", default="wing_wall")
    parser.add_argument("--ref-force", type=float, default=DEFAULT_REF_FORCE_N)
    parser.add_argument("--ref-area", type=float, default=DEFAULT_REF_AREA_M2)
    args = parser.parse_args(argv)

    cases = _parse_case_args(args.case)
    build_drag_source_report(
        mesh_path=args.mesh,
        cases=cases,
        output_dir=args.output_dir,
        section_table_path=args.section_table,
        ref_force=args.ref_force,
        ref_area=args.ref_area,
        marker=args.marker,
    )
    print(args.output_dir / "drag_source_localization.md")
    return 0


def _parse_force_breakdown_line(line: str) -> tuple[str, dict[str, float]] | None:
    match = re.search(
        r"Total\s+(CL/CD|CL|CD|CSF|CMx|CMy|CMz|CFx|CFy|CFz)"
        r"(?:\s*\([^)]*\))?\s*:\s*([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)"
        r"\s*\| Pressure\s*\([^)]*\):\s*([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)"
        r"\s*\| Friction\s*\([^)]*\):\s*([-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)",
        line,
    )
    if match is None:
        return None
    key = match.group(1).lower().replace("/", "_over_")
    return key, {
        "total": float(match.group(2)),
        "pressure": float(match.group(3)),
        "friction": float(match.group(4)),
    }


def _read_surface_pressures(path: Path) -> dict[int, float]:
    with path.open(newline="", encoding="utf-8") as stream:
        return {int(row["PointID"]): float(row["Pressure"]) for row in csv.DictReader(stream)}


def _read_section_table(path: Path) -> tuple[dict[str, float], ...]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = []
        for row in csv.DictReader(stream):
            rows.append(
                {
                    "y_m": float(row["y_m"]),
                    "chord_m": float(row["chord_m"]),
                }
            )
    return tuple(rows)


def _section_y_edges(section_table: Sequence[Mapping[str, float]] | None) -> tuple[float, ...]:
    if not section_table:
        return (0.0, math.inf)
    edges = tuple(float(row["y_m"]) for row in section_table)
    return (*edges[:-1], edges[-1] + 1.0e-9)


def _bin_labels(edges: Sequence[float], *, precision: int) -> list[str]:
    labels = []
    for left, right in zip(edges[:-1], edges[1:]):
        labels.append(f"{left:.{precision}f}-{right:.{precision}f}")
    return labels


def _bin_label(value: float, edges: Sequence[float], labels: Sequence[str]) -> str:
    for index, (left, right) in enumerate(zip(edges[:-1], edges[1:])):
        if left <= value < right:
            return labels[index]
    return labels[-1]


def _x_over_local_chord(
    centroid: Vector,
    section_table: Sequence[Mapping[str, float]] | None,
) -> float:
    if not section_table:
        return centroid[0]
    y = abs(centroid[1])
    rows = sorted(section_table, key=lambda row: row["y_m"])
    if y <= rows[0]["y_m"]:
        chord = rows[0]["chord_m"]
    elif y >= rows[-1]["y_m"]:
        chord = rows[-1]["chord_m"]
    else:
        chord = rows[-1]["chord_m"]
        for left, right in zip(rows[:-1], rows[1:]):
            if left["y_m"] <= y <= right["y_m"]:
                span = right["y_m"] - left["y_m"]
                fraction = 0.0 if span == 0.0 else (y - left["y_m"]) / span
                chord = left["chord_m"] + fraction * (right["chord_m"] - left["chord_m"])
                break
    return centroid[0] / chord if chord else math.nan


def _normal_role(normal: Vector) -> str:
    abs_normal = tuple(abs(value) for value in normal)
    if abs_normal[0] > 0.55:
        return "x_forward_or_aft_facing"
    if abs_normal[1] > 0.75:
        return "y_tip_or_span_cap"
    if abs_normal[2] > 0.55:
        return "z_upper_lower_like"
    return "mixed"


def _keep_top(items: list[dict[str, Any]], candidate: dict[str, Any], *, reverse: bool) -> None:
    items.append(candidate)
    items.sort(key=lambda item: item["cd_pressure_contribution"], reverse=reverse)
    del items[20:]


def _engineering_read(cases: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    read: dict[str, Any] = {
        "interpretation": (
            "Force-breakdown probes are diagnostic only. Pressure drag remains "
            "implausibly high before grid convergence can be meaningful."
        )
    }
    if "euler" in cases:
        read["euler_cd_pressure"] = cases["euler"]["forces_breakdown"]["cd"]["pressure"]
    if "rans_bl" in cases:
        read["rans_bl_cd_pressure"] = cases["rans_bl"]["forces_breakdown"]["cd"]["pressure"]
        read["rans_bl_cd_friction"] = cases["rans_bl"]["forces_breakdown"]["cd"]["friction"]
    return read


def _markdown_report(report: Mapping[str, Any]) -> str:
    lines = [
        "# WO-006J Drag Source Localization",
        "",
        "Diagnostic only: restart probes with `SURFACE_CSV` and "
        "`WRT_FORCES_BREAKDOWN=YES`; not CFD ladder rungs.",
        "",
        "| case | CD total | CD pressure | CD friction | CL total | pressure CD by normal role |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for label, case in report["cases"].items():
        force = case["forces_breakdown"]
        cd = force["cd"]
        cl = force["cl"]
        roles = ", ".join(
            f"{key}={value:.4f}" for key, value in case["pressure_cd_by_normal_role"].items()
        )
        lines.append(
            f"| `{label}` | {cd['total']:.6f} | {cd['pressure']:.6f} | "
            f"{cd['friction']:.6f} | {cl['total']:.6f} | {roles} |"
        )
    first_case = next(iter(report["cases"].values()))
    metrics = first_case["geometry_surface_metrics"]
    lines.extend(
        [
            "",
            (
                "Geometry wall area check: wetted area "
                f"`{metrics['wetted_area_m2']:.3f} m^2`, abs x-projected wall area "
                f"`{metrics['abs_projected_area_x_m2']:.3f} m^2`, closed-surface "
                "one-sided x-projection estimate "
                f"`{metrics['closed_surface_one_sided_x_projected_area_estimate_m2']:.3f} m^2`."
            ),
            "",
            "Engineering read: Euler/slip-wall drag is pressure-only; RANS/BL drag "
            "contains both excessive pressure drag and excessive friction drag. "
            "This invalidates the current ladder for grid-convergence use.",
            "",
            "Top positive pressure-drag contributors are retained in "
            "`drag_source_localization.json` for span/x/chord/normal inspection.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_case_args(raw_cases: Iterable[str]) -> dict[str, Path]:
    cases: dict[str, Path] = {}
    for raw in raw_cases:
        label, sep, path = raw.partition(":")
        if not sep or not label or not path:
            raise ValueError(f"Case must be label:path, got {raw!r}")
        cases[label] = Path(path)
    return cases


def _add(left: Vector, right: Vector) -> Vector:
    return (left[0] + right[0], left[1] + right[1], left[2] + right[2])


def _sub(left: Vector, right: Vector) -> Vector:
    return (left[0] - right[0], left[1] - right[1], left[2] - right[2])


def _scale(vector: Vector, factor: float) -> Vector:
    return (vector[0] * factor, vector[1] * factor, vector[2] * factor)


def _cross(left: Vector, right: Vector) -> Vector:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _norm(vector: Vector) -> float:
    return math.sqrt(vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2)


def _add_bucket(bucket: dict[str, float], key: str, value: float) -> None:
    bucket[key] = bucket.get(key, 0.0) + value


if __name__ == "__main__":
    raise SystemExit(main())
