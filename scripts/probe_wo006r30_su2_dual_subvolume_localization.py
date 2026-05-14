#!/usr/bin/env python3
"""Localize the R28 SU2 CV sub-volume ratio hotspot.

R29 ruled out whole-tet adjacent volume jumps as the explanation for the
R28 solver-side dual-control-volume pathology.  SU2's own mesh-quality routine
computes ``CV Sub-Volume Ratio`` at vertices from the max/min sub-element
volumes that compose each dual control volume.  This probe mirrors that metric
closely enough to recover the hotspot point, source provenance, and coordinates.

It is a diagnostic only.  It does not repair the mesh, run SU2, or produce CFD
coefficient evidence.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
for path in (SCRIPT_DIR, HPA_MESHING_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import probe_wo006r25_culled_mixed_su2_handoff as r25  # noqa: E402
import probe_wo006r26_remaining_boundary_leak_localization as r26  # noqa: E402
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


SCHEMA_VERSION = "wo006r30_su2_dual_subvolume_localization_probe.v1"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r30_su2_dual_subvolume_localization_probe"
DEFAULT_R25_OUTPUT_DIR = WO006_ROOT / "wo006r25_culled_mixed_su2_handoff_probe"
SU2_TRIANGLE = r25.SU2_TRIANGLE
SU2_TETRA = r25.SU2_TETRA
DEFAULT_RECORD_MIN_RATIO = 1.0e6
DEFAULT_EXTREME_RATIO = 1.0e6
SU2_METRIC_SOURCE = {
    "code_reference": "CPhysicalGeometry::ComputeMeshQualityStatistics",
    "upstream_source_url": (
        "https://github.com/su2code/SU2/blob/develop/Common/src/geometry/"
        "CPhysicalGeometry.cpp"
    ),
    "basis": (
        "SU2 computes CV Sub-Volume Ratio per vertex as max/min of the "
        "sub-element volumes contributing to that vertex dual control volume."
    ),
}


def su2_style_dual_subvolume_hotspots(
    *,
    nodes: Sequence[tuple[float, float, float]],
    elements: Sequence[Mapping[str, Any]],
    min_ratio: float = DEFAULT_RECORD_MIN_RATIO,
    top_count: int = 50,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return vertex hotspots for a SU2-style CV sub-volume max/min ratio."""

    min_records: list[dict[str, Any] | None] = [None] * len(nodes)
    max_records: list[dict[str, Any] | None] = [None] * len(nodes)
    positive_subvolume_count = 0
    skipped_non_tetra = 0
    non_positive_subvolume_count = 0
    for element_index, element in enumerate(elements):
        element_type = int(element["element_type"])
        if element_type != SU2_TETRA:
            skipped_non_tetra += 1
            continue
        element_nodes = r25._parse_nodes(element["nodes"])
        element_points = [nodes[int(node)] for node in element_nodes]
        element_centroid = _centroid_tuple(element_points)
        source = str(element.get("source") or "unknown")
        for face_nodes in _tetra_faces_ordered(element_nodes):
            face_points = [nodes[int(node)] for node in face_nodes]
            face_centroid = _centroid_tuple(face_points)
            for edge_offset, point_index in enumerate(face_nodes):
                next_point_index = face_nodes[(edge_offset + 1) % len(face_nodes)]
                edge_midpoint = _centroid_tuple(
                    [nodes[int(point_index)], nodes[int(next_point_index)]]
                )
                subvolume = _tetra_volume(
                    nodes[int(point_index)],
                    edge_midpoint,
                    face_centroid,
                    element_centroid,
                )
                if subvolume <= 0.0:
                    non_positive_subvolume_count += 1
                    continue
                positive_subvolume_count += 1
                record = {
                    "subvolume_m3": subvolume,
                    "point_index": int(point_index),
                    "element_index": int(element_index),
                    "source": source,
                    "element_nodes": list(int(node) for node in element_nodes),
                    "face_nodes": list(int(node) for node in face_nodes),
                    "edge_nodes": [int(point_index), int(next_point_index)],
                    "element_centroid": _point_payload(element_centroid),
                    "face_centroid": _point_payload(face_centroid),
                    "edge_midpoint": _point_payload(edge_midpoint),
                }
                current_min = min_records[int(point_index)]
                if current_min is None or subvolume < float(current_min["subvolume_m3"]):
                    min_records[int(point_index)] = record
                current_max = max_records[int(point_index)]
                if current_max is None or subvolume > float(current_max["subvolume_m3"]):
                    max_records[int(point_index)] = record

    records: list[dict[str, Any]] = []
    for point_index, (min_record, max_record) in enumerate(zip(min_records, max_records)):
        if min_record is None or max_record is None:
            continue
        min_volume = float(min_record["subvolume_m3"])
        max_volume = float(max_record["subvolume_m3"])
        if min_volume <= 0.0:
            continue
        ratio = max_volume / min_volume
        if ratio < min_ratio:
            continue
        source_pair = "|".join(
            sorted((str(min_record["source"]), str(max_record["source"])))
        )
        records.append(
            {
                "point_index": int(point_index),
                "point": _point_payload(nodes[point_index]),
                "cv_sub_volume_ratio": ratio,
                "source_pair": source_pair,
                "min_subvolume": dict(min_record),
                "max_subvolume": dict(max_record),
            }
        )
    records.sort(key=lambda record: float(record["cv_sub_volume_ratio"]), reverse=True)
    top_records = records[: max(0, int(top_count))]
    metric_summary = summarize_dual_subvolume_records(
        records,
        positive_subvolume_count=positive_subvolume_count,
        non_positive_subvolume_count=non_positive_subvolume_count,
        skipped_non_tetra_count=skipped_non_tetra,
        extreme_ratio=DEFAULT_EXTREME_RATIO,
    )
    return top_records, metric_summary


def enrich_hotspot_records_with_point_context(
    *,
    records: Sequence[Mapping[str, Any]],
    markers: Mapping[str, Sequence[Mapping[str, Any]]],
    elements: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    marker_by_point = _point_marker_map(markers)
    source_counts_by_point = _incident_source_counts_by_point(elements)
    enriched: list[dict[str, Any]] = []
    for record in records:
        point_index = int(record["point_index"])
        payload = dict(record)
        payload["point_markers"] = sorted(marker_by_point.get(point_index, set()))
        payload["incident_element_source_counts"] = dict(
            sorted(source_counts_by_point.get(point_index, {}).items())
        )
        enriched.append(payload)
    return enriched


def summarize_dual_subvolume_records(
    records: Sequence[Mapping[str, Any]],
    *,
    positive_subvolume_count: int,
    non_positive_subvolume_count: int,
    skipped_non_tetra_count: int,
    extreme_ratio: float = DEFAULT_EXTREME_RATIO,
) -> dict[str, Any]:
    worst = max(
        records,
        key=lambda record: float(record.get("cv_sub_volume_ratio") or 0.0),
        default=None,
    )
    max_ratio = 0.0 if worst is None else float(worst.get("cv_sub_volume_ratio") or 0.0)
    blockers = []
    if max_ratio > extreme_ratio:
        blockers.append("su2_style_dual_subvolume_ratio_extreme")
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "record_count": len(records),
        "positive_subvolume_count": int(positive_subvolume_count),
        "non_positive_subvolume_count": int(non_positive_subvolume_count),
        "skipped_non_tetra_count": int(skipped_non_tetra_count),
        "extreme_ratio": float(extreme_ratio),
        "max_cv_sub_volume_ratio": max_ratio,
        "worst_point_index": None if worst is None else int(worst["point_index"]),
        "worst_point": None if worst is None else dict(worst.get("point") or {}),
        "worst_source_pair": None if worst is None else str(worst.get("source_pair")),
        "by_source_pair": _count_by_source_pair(records),
        "su2_metric_source": dict(SU2_METRIC_SOURCE),
    }


def build_probe_summary(
    *,
    output_dir: Path,
    geometry_source: str,
    mesh_context: Mapping[str, Any],
    dual_metric_summary: Mapping[str, Any],
    top_records: Sequence[Mapping[str, Any]],
    elapsed_s: float,
) -> dict[str, Any]:
    blockers = list(dual_metric_summary.get("blockers") or [])
    blockers.extend(
        [
            "solver_postprocessed_surface_yplus_missing",
            "su2_solver_ladder_not_run",
        ]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": (
            "su2_dual_subvolume_hotspot_localized_repair_target_ready"
            if dual_metric_summary.get("status") == "fail"
            else "su2_dual_subvolume_hotspot_not_found"
        ),
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "coefficient_interpretable": False,
        "output_dir": str(output_dir),
        "geometry_source": geometry_source,
        "mesh_context": dict(mesh_context),
        "dual_subvolume_metric_summary": dict(dual_metric_summary),
        "top_dual_subvolume_hotspots": [dict(record) for record in top_records],
        "blockers": sorted(set(blockers)),
        "blocked_claims": [
            "SU2 coarse/medium/fine ladder",
            "CL/CD/Cm interpretation",
            "grid convergence",
            "Baseline A drag or power truth",
        ],
        "elapsed_s": elapsed_s,
        "engineering_read": _engineering_read(dual_metric_summary),
    }


def run_probe(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    r25_output_dir: Path = DEFAULT_R25_OUTPUT_DIR,
    points_per_side: int = 16,
    spanwise_subdivisions: int = 2,
    merge_digits: int = 10,
    min_ratio: float = DEFAULT_RECORD_MIN_RATIO,
    top_count: int = 50,
) -> dict[str, Any]:
    start = time.monotonic()
    output_dir.mkdir(parents=True, exist_ok=True)
    state = r26.build_r25_state_with_provenance(
        r25_output_dir=r25_output_dir,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
        merge_digits=merge_digits,
    )
    top_records, dual_metric_summary = su2_style_dual_subvolume_hotspots(
        nodes=state["nodes"],
        elements=state["elements"],
        min_ratio=min_ratio,
        top_count=top_count,
    )
    top_records = enrich_hotspot_records_with_point_context(
        records=top_records,
        markers=state["markers"],
        elements=state["elements"],
    )
    source_counts = Counter(str(element.get("source") or "unknown") for element in state["elements"])
    mesh_context = {
        "node_count": len(state["nodes"]),
        "volume_element_count": len(state["elements"]),
        "source_counts": dict(sorted(source_counts.items())),
        "marker_counts": {marker: len(faces) for marker, faces in state["markers"].items()},
        "min_recorded_cv_sub_volume_ratio": float(min_ratio),
    }
    summary = build_probe_summary(
        output_dir=output_dir,
        geometry_source=str(state["geometry_source"]),
        mesh_context=mesh_context,
        dual_metric_summary=dual_metric_summary,
        top_records=top_records,
        elapsed_s=time.monotonic() - start,
    )
    write_json(output_dir / "summary.json", summary)
    write_csv(output_dir / "dual_subvolume_hotspots.csv", top_records)
    (output_dir / "dual_subvolume_localization_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    metric = summary.get("dual_subvolume_metric_summary") or {}
    mesh = summary.get("mesh_context") or {}
    worst = metric.get("worst_point") or {}
    return "\n".join(
        [
            "# WO-006R30 SU2 Dual Subvolume Localization Probe",
            "",
            "This is SU2 mesh-quality localization, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary.get('goal_status')}`",
            f"CFD_STATUS: `{summary.get('cfd_status')}`",
            f"- verdict: `{summary.get('verdict')}`",
            f"- nodes / volume elements: `{mesh.get('node_count')}` / `{mesh.get('volume_element_count')}`",
            f"- max SU2-style CV sub-volume ratio: `{metric.get('max_cv_sub_volume_ratio')}`",
            f"- worst point index: `{metric.get('worst_point_index')}`",
            f"- worst point xyz: `{worst}`",
            f"- worst source pair: `{metric.get('worst_source_pair')}`",
            f"- blockers: `{summary.get('blockers')}`",
            "",
            f"Engineering read: {summary.get('engineering_read')}",
            "",
        ]
    )


def write_csv(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "point_index",
        "x",
        "y",
        "z",
        "cv_sub_volume_ratio",
        "source_pair",
        "min_source",
        "min_element_index",
        "min_subvolume_m3",
        "max_source",
        "max_element_index",
        "max_subvolume_m3",
        "point_markers",
        "incident_element_source_counts",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            point = record.get("point") or {}
            min_record = record.get("min_subvolume") or {}
            max_record = record.get("max_subvolume") or {}
            writer.writerow(
                {
                    "point_index": record.get("point_index"),
                    "x": point.get("x"),
                    "y": point.get("y"),
                    "z": point.get("z"),
                    "cv_sub_volume_ratio": record.get("cv_sub_volume_ratio"),
                    "source_pair": record.get("source_pair"),
                    "min_source": min_record.get("source"),
                    "min_element_index": min_record.get("element_index"),
                    "min_subvolume_m3": min_record.get("subvolume_m3"),
                    "max_source": max_record.get("source"),
                    "max_element_index": max_record.get("element_index"),
                    "max_subvolume_m3": max_record.get("subvolume_m3"),
                    "point_markers": json.dumps(record.get("point_markers")),
                    "incident_element_source_counts": json.dumps(
                        record.get("incident_element_source_counts")
                    ),
                }
            )


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _tetra_faces_ordered(nodes: Sequence[int]) -> tuple[tuple[int, int, int], ...]:
    a, b, c, d = (int(node) for node in nodes)
    return ((a, b, c), (a, b, d), (a, c, d), (b, c, d))


def _centroid_tuple(points: Sequence[Sequence[float]]) -> tuple[float, float, float]:
    count = float(len(points))
    return (
        sum(float(point[0]) for point in points) / count,
        sum(float(point[1]) for point in points) / count,
        sum(float(point[2]) for point in points) / count,
    )


def _point_payload(point: Sequence[float]) -> dict[str, float]:
    return {"x": float(point[0]), "y": float(point[1]), "z": float(point[2])}


def _tetra_volume(
    a: Sequence[float],
    b: Sequence[float],
    c: Sequence[float],
    d: Sequence[float],
) -> float:
    ab = (float(b[0]) - float(a[0]), float(b[1]) - float(a[1]), float(b[2]) - float(a[2]))
    ac = (float(c[0]) - float(a[0]), float(c[1]) - float(a[1]), float(c[2]) - float(a[2]))
    ad = (float(d[0]) - float(a[0]), float(d[1]) - float(a[1]), float(d[2]) - float(a[2]))
    cross = (
        ac[1] * ad[2] - ac[2] * ad[1],
        ac[2] * ad[0] - ac[0] * ad[2],
        ac[0] * ad[1] - ac[1] * ad[0],
    )
    return abs(ab[0] * cross[0] + ab[1] * cross[1] + ab[2] * cross[2]) / 6.0


def _count_by_source_pair(records: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for record in records:
        pair = str(record.get("source_pair") or "unknown")
        ratio = float(record.get("cv_sub_volume_ratio") or 0.0)
        bucket = buckets.setdefault(
            pair,
            {"count": 0, "max_cv_sub_volume_ratio": 0.0},
        )
        bucket["count"] = int(bucket["count"]) + 1
        bucket["max_cv_sub_volume_ratio"] = max(
            float(bucket["max_cv_sub_volume_ratio"]),
            ratio,
        )
    return dict(sorted(buckets.items()))


def _point_marker_map(
    markers: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[int, set[str]]:
    marker_by_point: dict[int, set[str]] = {}
    for marker, faces in markers.items():
        marker_name = str(marker)
        for face in faces:
            for node in r25._parse_nodes(face["nodes"]):
                marker_by_point.setdefault(int(node), set()).add(marker_name)
    return marker_by_point


def _incident_source_counts_by_point(
    elements: Sequence[Mapping[str, Any]],
) -> dict[int, dict[str, int]]:
    source_counts_by_point: dict[int, dict[str, int]] = {}
    for element in elements:
        source = str(element.get("source") or "unknown")
        for node in r25._parse_nodes(element["nodes"]):
            point_bucket = source_counts_by_point.setdefault(int(node), {})
            point_bucket[source] = point_bucket.get(source, 0) + 1
    return source_counts_by_point


def _engineering_read(metric: Mapping[str, Any]) -> str:
    if metric.get("status") == "fail":
        point = metric.get("worst_point") or {}
        return (
            "The R28 SU2 CV sub-volume ratio is reproduced by a SU2-style "
            f"vertex subvolume scan at point {metric.get('worst_point_index')} "
            f"near x={point.get('x')}, y={point.get('y')}, z={point.get('z')}. "
            "Repair should target the local dual-volume construction around this "
            "tip/farfield/core transition before another SU2 route-smoke or mesh ladder."
        )
    return (
        "No SU2-style dual subvolume hotspot exceeded the configured threshold. "
        "That would contradict R28 and should trigger a metric/source audit."
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--r25-output-dir", type=Path, default=DEFAULT_R25_OUTPUT_DIR)
    parser.add_argument("--points-per-side", type=int, default=16)
    parser.add_argument("--spanwise-subdivisions", type=int, default=2)
    parser.add_argument("--merge-digits", type=int, default=10)
    parser.add_argument("--min-ratio", type=float, default=DEFAULT_RECORD_MIN_RATIO)
    parser.add_argument("--top-count", type=int, default=50)
    args = parser.parse_args(argv)

    summary = run_probe(
        output_dir=args.output_dir,
        r25_output_dir=args.r25_output_dir,
        points_per_side=args.points_per_side,
        spanwise_subdivisions=args.spanwise_subdivisions,
        merge_digits=args.merge_digits,
        min_ratio=args.min_ratio,
        top_count=args.top_count,
    )
    print(json.dumps(summary, indent=2))
    return (
        0
        if summary.get("verdict") == "su2_dual_subvolume_hotspot_localized_repair_target_ready"
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
