#!/usr/bin/env python3
"""Quantify Baseline A airfoil-transition normal jumps for WO-006 BL repair.

This is a geometry/near-wall diagnostic, not CFD completion evidence. It checks
whether the current Baseline A main-wing station-to-station airfoil transition
creates large aft-wall normal and shape jumps that can explain BL prism quality
failures before any coarse/medium/fine SU2 ladder is attempted.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
for path in (SCRIPT_DIR, HPA_MESHING_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hpa_meshing.mesh_native.near_wall_block import split_airfoil_wall_loop  # noqa: E402
from run_wo006r2_cfd_recovery_campaign import load_campaign_geometry  # noqa: E402
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006q_transition_normal_jump_probe"
SCHEMA_VERSION = "wo006q_transition_normal_jump_probe.v1"
NORMAL_JUMP_BLOCKER_DEG = 20.0
AFT_SHAPE_DELTA_BLOCKER = 0.03
AFT_X_OVER_CHORD_MIN = 0.75


def run_probe(
    *,
    output_dir: Path,
    points_per_side: int = 32,
    spanwise_subdivisions: int = 1,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    geometry = load_campaign_geometry(
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    section_rows = load_section_table(geometry.section_table_path)
    metrics = build_interval_metrics(
        geometry.spec.wing_spec.stations,
        section_rows,
    )
    summary = summarize_interval_metrics(metrics)
    summary.update(
        {
            "output_dir": str(output_dir),
            "geometry_source": str(geometry.section_table_path),
            "geometry_manifest_path": str(geometry.geometry_manifest_path),
            "points_per_side": int(points_per_side),
            "spanwise_subdivisions": int(spanwise_subdivisions),
            "intervals": metrics,
        }
    )
    write_json(output_dir / "summary.json", summary)
    write_csv(output_dir / "interval_metrics.csv", metrics)
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def build_interval_metrics(
    stations: Sequence[Any],
    section_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows_by_abs_y = {
        round(abs(as_float(row["y_m"])), 6): row
        for row in section_rows
    }
    metrics: list[dict[str, Any]] = []
    for index, (left, right) in enumerate(zip(stations[:-1], stations[1:])):
        left_row = section_row_for_station(left, rows_by_abs_y)
        right_row = section_row_for_station(right, rows_by_abs_y)
        left_wall = split_airfoil_wall_loop(left.airfoil_xz).wall_path
        right_wall = split_airfoil_wall_loop(right.airfoil_xz).wall_path
        if len(left_wall) != len(right_wall):
            raise ValueError("Adjacent station wall loops have different point counts")
        left_normals = outward_vertex_normals(left_wall)
        right_normals = outward_vertex_normals(right_wall)

        all_angles: list[float] = []
        aft_angles: list[float] = []
        shape_deltas: list[float] = []
        aft_shape_deltas: list[float] = []
        for left_point, right_point, left_normal, right_normal in zip(
            left_wall,
            right_wall,
            left_normals,
            right_normals,
        ):
            angle = normal_angle_deg(left_normal, right_normal)
            delta = math.hypot(right_point[0] - left_point[0], right_point[1] - left_point[1])
            x_mid = 0.5 * (left_point[0] + right_point[0])
            all_angles.append(angle)
            shape_deltas.append(delta)
            if x_mid >= AFT_X_OVER_CHORD_MIN:
                aft_angles.append(angle)
                aft_shape_deltas.append(delta)
        is_transition = str(left_row.get("airfoil_id")) != str(right_row.get("airfoil_id"))
        metrics.append(
            {
                "interval_id": f"{index}:{left.y:.6f}->{right.y:.6f}",
                "interval_index": index,
                "left_y_m": float(left.y),
                "right_y_m": float(right.y),
                "left_abs_y_m": abs(float(left.y)),
                "right_abs_y_m": abs(float(right.y)),
                "left_airfoil_id": left_row.get("airfoil_id"),
                "right_airfoil_id": right_row.get("airfoil_id"),
                "is_airfoil_transition": is_transition,
                "span_m": abs(float(right.y) - float(left.y)),
                "max_normal_angle_deg": max(all_angles),
                "max_aft_normal_angle_deg": max(aft_angles) if aft_angles else None,
                "max_shape_delta_xz": max(shape_deltas),
                "max_aft_shape_delta_xz": max(aft_shape_deltas) if aft_shape_deltas else None,
                "aft_sample_count": len(aft_angles),
            }
        )
    return metrics


def summarize_interval_metrics(metrics: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    transition_metrics = [row for row in metrics if row.get("is_airfoil_transition") is True]
    worst_transition = max(
        transition_metrics,
        key=lambda row: optional_float(row.get("max_aft_normal_angle_deg")) or -math.inf,
        default=None,
    )
    max_transition_angle = optional_float(
        None if worst_transition is None else worst_transition.get("max_aft_normal_angle_deg")
    )
    max_transition_shape = max(
        [
            optional_float(row.get("max_aft_shape_delta_xz")) or 0.0
            for row in transition_metrics
        ],
        default=0.0,
    )

    blockers: list[str] = []
    if max_transition_angle is not None and max_transition_angle >= NORMAL_JUMP_BLOCKER_DEG:
        blockers.append("airfoil_transition_aft_normal_jump")
    if max_transition_shape >= AFT_SHAPE_DELTA_BLOCKER:
        blockers.append("airfoil_transition_aft_shape_jump")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "blocked" if blockers else "pass",
        "blockers": blockers,
        "transition_interval_count": len(transition_metrics),
        "worst_transition_interval": worst_transition,
        "max_transition_aft_normal_angle_deg": max_transition_angle,
        "max_transition_aft_shape_delta_xz": max_transition_shape,
        "thresholds": {
            "aft_x_over_chord_min": AFT_X_OVER_CHORD_MIN,
            "normal_jump_blocker_deg": NORMAL_JUMP_BLOCKER_DEG,
            "aft_shape_delta_blocker": AFT_SHAPE_DELTA_BLOCKER,
        },
        "recommended_repair": (
            "receiver_sleeve_or_local_airfoil_transition_smoothing"
            if blockers
            else "none"
        ),
        "coefficient_interpretable": False,
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "engineering_read": engineering_read(blockers),
    }


def engineering_read(blockers: Sequence[str]) -> str:
    if "airfoil_transition_aft_normal_jump" in blockers:
        return (
            "The current airfoil transition creates a large aft-wall normal jump. "
            "This is consistent with BL prism inversion/low-SICN near the DAE31 -> "
            "CST transition band; repair topology/near-wall shape before SU2 ladder runs."
        )
    if blockers:
        return (
            "The airfoil transition has an aft shape jump large enough to block BL "
            "confidence. Repair near-wall topology before SU2 ladder runs."
        )
    return (
        "No large aft transition normal/shape jump was detected by this geometric probe. "
        "This does not prove CFD readiness; it only clears this diagnostic."
    )


def section_row_for_station(
    station: Any,
    rows_by_abs_y: Mapping[float, Mapping[str, Any]],
    *,
    tolerance: float = 1.0e-5,
) -> Mapping[str, Any]:
    target = abs(float(station.y))
    key = round(target, 6)
    if key in rows_by_abs_y:
        return rows_by_abs_y[key]
    nearest_key = min(rows_by_abs_y, key=lambda value: abs(value - target))
    if abs(nearest_key - target) <= tolerance:
        return rows_by_abs_y[nearest_key]
    raise ValueError(f"No section-table row matches station |y|={target}")


def load_section_table(path: Path | str) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def outward_vertex_normals(wall: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    normals: list[tuple[float, float]] = []
    count = len(wall)
    for index in range(count):
        previous_point = wall[index - 1]
        next_point = wall[(index + 1) % count]
        tangent = (next_point[0] - previous_point[0], next_point[1] - previous_point[1])
        length = math.hypot(*tangent)
        if length <= 0.0:
            raise ValueError("Cannot compute normal for duplicate airfoil points")
        unit_tangent = (tangent[0] / length, tangent[1] / length)
        normals.append((unit_tangent[1], -unit_tangent[0]))
    return normals


def normal_angle_deg(
    left: tuple[float, float],
    right: tuple[float, float],
) -> float:
    dot = max(-1.0, min(1.0, left[0] * right[0] + left[1] * right[1]))
    return math.degrees(math.acos(dot))


def render_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# WO-006Q Airfoil-Transition Normal-Jump Probe",
        "",
        f"GOAL_STATUS: `{summary['goal_status']}`",
        f"CFD_STATUS: `{summary['cfd_status']}`",
        f"- status: `{summary['status']}`",
        f"- blockers: `{summary['blockers']}`",
        f"- recommended repair: `{summary['recommended_repair']}`",
        f"- engineering read: {summary['engineering_read']}",
        "",
        "| interval | airfoil transition | max aft normal deg | max aft shape delta | span m | left airfoil | right airfoil |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for row in summary.get("intervals") or []:
        lines.append(
            "| {interval} | {transition} | {angle} | {shape} | {span} | `{left}` | `{right}` |".format(
                interval=row.get("interval_id"),
                transition=row.get("is_airfoil_transition"),
                angle=row.get("max_aft_normal_angle_deg"),
                shape=row.get("max_aft_shape_delta_xz"),
                span=row.get("span_m"),
                left=row.get("left_airfoil_id"),
                right=row.get("right_airfoil_id"),
            )
        )
    lines.extend(
        [
            "",
            "Blocked claims:",
            "- BL/y+ viscous drag calibration",
            "- medium/fine CFD ladder readiness",
            "- Baseline A drag or power truth",
        ]
    )
    return "\n".join(lines) + "\n"


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def as_float(value: Any) -> float:
    return float(str(value).strip())


def optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--points-per-side", type=int, default=32)
    parser.add_argument("--spanwise-subdivisions", type=int, default=1)
    args = parser.parse_args(argv)
    summary = run_probe(
        output_dir=args.output_dir,
        points_per_side=args.points_per_side,
        spanwise_subdivisions=args.spanwise_subdivisions,
    )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "blockers": summary["blockers"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
