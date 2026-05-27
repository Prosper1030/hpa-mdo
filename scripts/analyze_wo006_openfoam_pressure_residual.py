#!/usr/bin/env python3
"""Localize WO-006 OpenFOAM pressure drag on saved wall faces.

This is a diagnostic script for the accepted Fine OpenFOAM case. It reconstructs
pressure force from the saved pressure field and boundary face geometry, then
bins the result by patch, span, and chord. It intentionally does not run a
solver or alter the mesh.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


RHO = 1.225
U_INF = 6.5
S_REF = 33.420059598
DRAG_DIR = np.array([0.999995065, 0.0, 0.00314158749], dtype=np.float64)
LIFT_DIR = np.array([-0.00314158749, 0.0, 0.999995065], dtype=np.float64)
Q_REF = 0.5 * RHO * U_INF * U_INF * S_REF

WALL_PATCHES = (
    "airfoil_upper",
    "airfoil_lower",
    "te_wall",
    "physical_tip_left",
    "physical_tip_right",
)
PRIMARY_PATCHES = ("airfoil_upper", "airfoil_lower")
TOTAL_PHYSICAL_PATCHES = ("airfoil_upper", "airfoil_lower", "te_wall")


@dataclass(frozen=True)
class PatchInfo:
    name: str
    kind: str
    n_faces: int
    start_face: int

    @property
    def stop_face(self) -> int:
        return self.start_face + self.n_faces


def _strip_header_count(path: Path) -> tuple[int, int]:
    """Return (count, line_index_after_open_paren) for an OpenFOAM list."""

    with path.open("r", encoding="utf-8", errors="replace") as stream:
        seen_count = False
        for line_index, line in enumerate(stream):
            text = line.strip()
            if not seen_count and re.fullmatch(r"[0-9]+", text):
                count = int(text)
                seen_count = True
                continue
            if seen_count and text == "(":
                return count, line_index + 1
    raise ValueError(f"Could not find OpenFOAM list payload in {path}")


def parse_boundary(path: Path) -> dict[str, PatchInfo]:
    text = path.read_text(encoding="utf-8", errors="replace")
    patches: dict[str, PatchInfo] = {}
    pattern = re.compile(
        r"\s*(?P<name>[A-Za-z0-9_]+)\s*\{\s*"
        r"type\s+(?P<kind>[A-Za-z0-9_]+);\s*"
        r"nFaces\s+(?P<nfaces>[0-9]+);\s*"
        r"startFace\s+(?P<start>[0-9]+);",
        re.S,
    )
    for match in pattern.finditer(text):
        patches[match.group("name")] = PatchInfo(
            name=match.group("name"),
            kind=match.group("kind"),
            n_faces=int(match.group("nfaces")),
            start_face=int(match.group("start")),
        )
    return patches


def read_points(path: Path) -> np.ndarray:
    count, start_line = _strip_header_count(path)
    points = np.empty((count, 3), dtype=np.float64)
    vec_re = re.compile(r"\(([^()]+)\)")
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for _ in range(start_line):
            next(stream)
        for i in range(count):
            match = vec_re.search(next(stream))
            if match is None:
                raise ValueError(f"Bad point line {i} in {path}")
            points[i, :] = [float(value) for value in match.group(1).split()]
    return points


def read_internal_scalar(path: Path) -> np.ndarray:
    count: int | None = None
    values: list[float] = []
    in_values = False
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            text = line.strip()
            if not in_values:
                if re.fullmatch(r"[0-9]+", text):
                    count = int(text)
                    continue
                if count is not None and text == "(":
                    in_values = True
                continue
            if text == ")":
                break
            values.append(float(text))
    if count is None or len(values) != count:
        raise ValueError(f"Expected {count} scalars, got {len(values)} from {path}")
    return np.asarray(values, dtype=np.float64)


def read_label_window(path: Path, start: int, stop: int) -> np.ndarray:
    count, start_line = _strip_header_count(path)
    if stop > count:
        raise ValueError(f"Requested labels [{start}, {stop}) beyond {count}")
    out = np.empty(stop - start, dtype=np.int64)
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for _ in range(start_line + start):
            next(stream)
        for i in range(stop - start):
            out[i] = int(next(stream).strip())
    return out


def iter_face_window(path: Path, start: int, stop: int) -> Iterable[list[int]]:
    count, start_line = _strip_header_count(path)
    if stop > count:
        raise ValueError(f"Requested faces [{start}, {stop}) beyond {count}")
    face_re = re.compile(r"[0-9]+\(([^()]*)\)")
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for _ in range(start_line + start):
            next(stream)
        for _ in range(stop - start):
            line = next(stream).strip()
            match = face_re.fullmatch(line)
            if match is None:
                raise ValueError(f"Bad face line: {line[:80]}")
            yield [int(value) for value in match.group(1).split()]


def face_area_vector(coords: np.ndarray) -> np.ndarray:
    origin = coords[0]
    area = np.zeros(3, dtype=np.float64)
    for i in range(1, len(coords) - 1):
        area += np.cross(coords[i] - origin, coords[i + 1] - origin)
    return 0.5 * area


def cd_from_force(force: np.ndarray, direction: np.ndarray = DRAG_DIR) -> float:
    return float(np.dot(force, direction) / Q_REF)


def cl_from_force(force: np.ndarray) -> float:
    return float(np.dot(force, LIFT_DIR) / Q_REF)


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def bin_index(value: float, edges: np.ndarray) -> int:
    idx = int(np.searchsorted(edges, value, side="right") - 1)
    return max(0, min(idx, len(edges) - 2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--time", default="2000")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--span-bins", default=40, type=int)
    parser.add_argument("--chord-bins", default=20, type=int)
    parser.add_argument("--top-faces", default=80, type=int)
    args = parser.parse_args()

    case = args.case
    mesh = case / "constant" / "polyMesh"
    time_dir = case / args.time
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)

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
    print(f"Reading points")
    points = read_points(mesh / "points")

    patches_by_face = [""] * (max_stop - min_start)
    for patch in window_patches:
        local_start = max(patch.start_face, min_start) - min_start
        local_stop = min(patch.stop_face, max_stop) - min_start
        for i in range(local_start, local_stop):
            patches_by_face[i] = patch.name
    if len(patches_by_face) != max_stop - min_start:
        raise AssertionError("Unexpected patch face window length")

    records: list[dict[str, object]] = []
    patch_force = {name: np.zeros(3, dtype=np.float64) for name in WALL_PATCHES}
    patch_count = {name: 0 for name in WALL_PATCHES}
    patch_area = {name: 0.0 for name in WALL_PATCHES}

    print(f"Reading faces {min_start}:{max_stop}")
    for local_i, face_points in enumerate(iter_face_window(mesh / "faces", min_start, max_stop)):
        patch_name = patches_by_face[local_i]
        if patch_name not in WALL_PATCHES:
            continue
        coords = points[np.asarray(face_points, dtype=np.int64)]
        center = coords.mean(axis=0)
        sf = face_area_vector(coords)
        area_mag = float(np.linalg.norm(sf))
        owner = int(owners[local_i])
        p_value = float(p_internal[owner])
        pressure_force = RHO * p_value * sf
        dcd = cd_from_force(pressure_force)
        dcl = cl_from_force(pressure_force)
        patch_force[patch_name] += pressure_force
        patch_count[patch_name] += 1
        patch_area[patch_name] += area_mag
        records.append(
            {
                "global_face": min_start + local_i,
                "patch": patch_name,
                "owner": owner,
                "x": float(center[0]),
                "y": float(center[1]),
                "z": float(center[2]),
                "abs_y": abs(float(center[1])),
                "area": area_mag,
                "p": p_value,
                "sf_x": float(sf[0]),
                "sf_y": float(sf[1]),
                "sf_z": float(sf[2]),
                "dCD_pressure": dcd,
                "dCL_pressure": dcl,
            }
        )

    # If the face orientation is opposite to OpenFOAM force output, all force
    # signs will be flipped. Keep both explicit rather than hiding the choice.
    primary_force = sum((patch_force[name] for name in PRIMARY_PATCHES), np.zeros(3))
    if cd_from_force(primary_force) < 0:
        print("Detected negative reconstructed primary drag; flipping pressure force signs.")
        for name in patch_force:
            patch_force[name] *= -1.0
        for rec in records:
            rec["dCD_pressure"] = -float(rec["dCD_pressure"])
            rec["dCL_pressure"] = -float(rec["dCL_pressure"])

    patch_rows: list[dict[str, object]] = []
    for name in WALL_PATCHES:
        force = patch_force[name]
        cd_total = cd_from_force(force)
        cl_total = cl_from_force(force)
        patch_rows.append(
            {
                "patch": name,
                "faces": patch_count[name],
                "area": patch_area[name],
                "Fx_pressure_N": force[0],
                "Fy_pressure_N": force[1],
                "Fz_pressure_N": force[2],
                "CD_pressure": cd_total,
                "CL_pressure": cl_total,
                "CD_x_component": force[0] / Q_REF,
                "CD_z_projection": force[2] * DRAG_DIR[2] / Q_REF,
            }
        )

    def group_row(name: str, patch_names: tuple[str, ...]) -> dict[str, object]:
        force = sum((patch_force[patch] for patch in patch_names), np.zeros(3))
        return {
            "patch": name,
            "faces": sum(patch_count[patch] for patch in patch_names),
            "area": sum(patch_area[patch] for patch in patch_names),
            "Fx_pressure_N": force[0],
            "Fy_pressure_N": force[1],
            "Fz_pressure_N": force[2],
            "CD_pressure": cd_from_force(force),
            "CL_pressure": cl_from_force(force),
            "CD_x_component": force[0] / Q_REF,
            "CD_z_projection": force[2] * DRAG_DIR[2] / Q_REF,
        }

    patch_rows.extend(
        [
            group_row("primary", PRIMARY_PATCHES),
            group_row("total_physical", TOTAL_PHYSICAL_PATCHES),
            group_row("total_with_tips", WALL_PATCHES),
        ]
    )
    write_csv(
        output / "pressure_patch_summary.csv",
        patch_rows,
        [
            "patch",
            "faces",
            "area",
            "Fx_pressure_N",
            "Fy_pressure_N",
            "Fz_pressure_N",
            "CD_pressure",
            "CL_pressure",
            "CD_x_component",
            "CD_z_projection",
        ],
    )

    primary_records = [rec for rec in records if rec["patch"] in PRIMARY_PATCHES]
    span_max = max(float(rec["abs_y"]) for rec in primary_records)
    span_edges = np.linspace(0.0, span_max, args.span_bins + 1)
    span_rows: list[dict[str, object]] = []
    for patch_group, selected in [
        ("primary", primary_records),
        ("upper", [rec for rec in primary_records if rec["patch"] == "airfoil_upper"]),
        ("lower", [rec for rec in primary_records if rec["patch"] == "airfoil_lower"]),
    ]:
        sums = np.zeros(args.span_bins, dtype=np.float64)
        pos = np.zeros(args.span_bins, dtype=np.float64)
        neg = np.zeros(args.span_bins, dtype=np.float64)
        face_counts = np.zeros(args.span_bins, dtype=np.int64)
        for rec in selected:
            idx = bin_index(float(rec["abs_y"]), span_edges)
            dcd = float(rec["dCD_pressure"])
            sums[idx] += dcd
            pos[idx] += max(dcd, 0.0)
            neg[idx] += min(dcd, 0.0)
            face_counts[idx] += 1
        for idx in range(args.span_bins):
            span_rows.append(
                {
                    "group": patch_group,
                    "eta_min": span_edges[idx] / span_max,
                    "eta_max": span_edges[idx + 1] / span_max,
                    "y_abs_min_m": span_edges[idx],
                    "y_abs_max_m": span_edges[idx + 1],
                    "faces": int(face_counts[idx]),
                    "CD_pressure": sums[idx],
                    "positive_CD_pressure": pos[idx],
                    "negative_CD_pressure": neg[idx],
                }
            )
    write_csv(
        output / "pressure_spanwise_bins.csv",
        span_rows,
        [
            "group",
            "eta_min",
            "eta_max",
            "y_abs_min_m",
            "y_abs_max_m",
            "faces",
            "CD_pressure",
            "positive_CD_pressure",
            "negative_CD_pressure",
        ],
    )

    # Chordwise coordinate normalized by min/max x in each span bin.
    span_x_min = np.full(args.span_bins, np.inf)
    span_x_max = np.full(args.span_bins, -np.inf)
    for rec in primary_records:
        idx = bin_index(float(rec["abs_y"]), span_edges)
        span_x_min[idx] = min(span_x_min[idx], float(rec["x"]))
        span_x_max[idx] = max(span_x_max[idx], float(rec["x"]))

    chord_edges = np.linspace(0.0, 1.0, args.chord_bins + 1)
    chord_sums: dict[tuple[str, int], float] = {}
    chord_faces: dict[tuple[str, int], int] = {}
    for rec in primary_records:
        span_idx = bin_index(float(rec["abs_y"]), span_edges)
        denom = max(float(span_x_max[span_idx] - span_x_min[span_idx]), 1e-12)
        x_norm = (float(rec["x"]) - float(span_x_min[span_idx])) / denom
        chord_idx = bin_index(x_norm, chord_edges)
        key = (str(rec["patch"]), chord_idx)
        chord_sums[key] = chord_sums.get(key, 0.0) + float(rec["dCD_pressure"])
        chord_faces[key] = chord_faces.get(key, 0) + 1
    chord_rows: list[dict[str, object]] = []
    for patch in PRIMARY_PATCHES:
        for idx in range(args.chord_bins):
            key = (patch, idx)
            chord_rows.append(
                {
                    "patch": patch,
                    "x_norm_min": chord_edges[idx],
                    "x_norm_max": chord_edges[idx + 1],
                    "faces": chord_faces.get(key, 0),
                    "CD_pressure": chord_sums.get(key, 0.0),
                }
            )
    write_csv(
        output / "pressure_chordwise_bins.csv",
        chord_rows,
        ["patch", "x_norm_min", "x_norm_max", "faces", "CD_pressure"],
    )

    # Region exclusion/what-if rows.
    def sum_records(selected: Iterable[dict[str, object]]) -> float:
        return sum(float(rec["dCD_pressure"]) for rec in selected)

    total_physical_cd = sum_records(rec for rec in records if rec["patch"] in TOTAL_PHYSICAL_PATCHES)
    eta_cuts = (0.02, 0.05, 0.10, 0.90, 0.95, 0.98)
    region_rows: list[dict[str, object]] = [
        {
            "scenario": "baseline_total_physical_pressure",
            "excluded": "none",
            "CD_pressure": total_physical_cd,
            "delta_vs_baseline": 0.0,
        }
    ]
    for eta in eta_cuts:
        if eta < 0.5:
            selected = [
                rec
                for rec in records
                if rec["patch"] in TOTAL_PHYSICAL_PATCHES and float(rec["abs_y"]) / span_max >= eta
            ]
            excluded = f"abs(y)/semiSpan < {eta}"
        else:
            selected = [
                rec
                for rec in records
                if rec["patch"] in TOTAL_PHYSICAL_PATCHES and float(rec["abs_y"]) / span_max <= eta
            ]
            excluded = f"abs(y)/semiSpan > {eta}"
        cd = sum_records(selected)
        region_rows.append(
            {
                "scenario": "span_exclusion",
                "excluded": excluded,
                "CD_pressure": cd,
                "delta_vs_baseline": cd - total_physical_cd,
            }
        )
    for patch in ("te_wall", "airfoil_upper", "airfoil_lower"):
        cd = sum_records(
            rec for rec in records if rec["patch"] in TOTAL_PHYSICAL_PATCHES and rec["patch"] != patch
        )
        region_rows.append(
            {
                "scenario": "patch_exclusion",
                "excluded": patch,
                "CD_pressure": cd,
                "delta_vs_baseline": cd - total_physical_cd,
            }
        )
    write_csv(
        output / "pressure_region_exclusion_checks.csv",
        region_rows,
        ["scenario", "excluded", "CD_pressure", "delta_vs_baseline"],
    )

    top_records = sorted(primary_records, key=lambda rec: abs(float(rec["dCD_pressure"])), reverse=True)[
        : args.top_faces
    ]
    top_positive_records = sorted(
        (rec for rec in primary_records if float(rec["dCD_pressure"]) > 0.0),
        key=lambda rec: float(rec["dCD_pressure"]),
        reverse=True,
    )[: args.top_faces]
    top_negative_records = sorted(
        (rec for rec in primary_records if float(rec["dCD_pressure"]) < 0.0),
        key=lambda rec: float(rec["dCD_pressure"]),
    )[: args.top_faces]
    write_csv(
        output / "top_pressure_faces.csv",
        top_records,
        [
            "global_face",
            "patch",
            "owner",
            "x",
            "y",
            "z",
            "abs_y",
            "area",
            "p",
            "sf_x",
            "sf_y",
            "sf_z",
            "dCD_pressure",
            "dCL_pressure",
        ],
    )
    for file_name, selected in [
        ("top_positive_pressure_faces.csv", top_positive_records),
        ("top_negative_pressure_faces.csv", top_negative_records),
    ]:
        write_csv(
            output / file_name,
            selected,
            [
                "global_face",
                "patch",
                "owner",
                "x",
                "y",
                "z",
                "abs_y",
                "area",
                "p",
                "sf_x",
                "sf_y",
                "sf_z",
                "dCD_pressure",
                "dCL_pressure",
            ],
        )

    summary_lines = [
        "# WO-006 Fine pressure residual localization",
        "",
        f"case: `{case}`",
        f"time: `{args.time}`",
        "",
        "## Reconstructed pressure CD",
        "",
    ]
    for row in patch_rows:
        summary_lines.append(
            f"- `{row['patch']}`: CDp={float(row['CD_pressure']):.8f}, "
            f"CLp={float(row['CL_pressure']):.8f}, faces={row['faces']}"
        )
    max_span = max(
        (row for row in span_rows if row["group"] == "primary"),
        key=lambda row: abs(float(row["CD_pressure"])),
    )
    summary_lines.extend(
        [
            "",
            "## Largest primary span bin",
            "",
            (
                f"`eta={float(max_span['eta_min']):.3f}-{float(max_span['eta_max']):.3f}` "
                f"CDp={float(max_span['CD_pressure']):.8f}, faces={max_span['faces']}"
            ),
            "",
            "Outputs: `pressure_patch_summary.csv`, `pressure_spanwise_bins.csv`, "
            "`pressure_chordwise_bins.csv`, `pressure_region_exclusion_checks.csv`, "
            "`top_pressure_faces.csv`.",
            "",
        ]
    )
    (output / "pressure_residual_localization.md").write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
