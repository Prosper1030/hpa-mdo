#!/usr/bin/env python3
"""Localize R28 SU2 dual-volume quality blockers back to mixed-mesh sources.

R28 proved that the R27 repaired mesh is marker-readable by SU2, but the solver
log reports pathological dual-control-volume quality.  This probe does not
change the mesh and does not run SU2.  It rebuilds the source-provenance mixed
mesh and measures source-aware primal size jumps across internal faces, which
are a bounded next diagnostic for the SU2 dual-volume pathology.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
import math
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


SCHEMA_VERSION = "wo006r29_dual_quality_source_localization_probe.v1"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r29_dual_quality_source_localization_probe"
DEFAULT_R25_OUTPUT_DIR = WO006_ROOT / "wo006r25_culled_mixed_su2_handoff_probe"
SU2_TETRA = r25.SU2_TETRA
DEFAULT_BLOCKER_RATIO = 1.0e6
DEFAULT_RECORD_MIN_RATIO = 1.0e3


def internal_face_volume_jump_records(
    *,
    nodes: Sequence[tuple[float, float, float]],
    elements: Sequence[Mapping[str, Any]],
    min_ratio: float = DEFAULT_RECORD_MIN_RATIO,
) -> list[dict[str, Any]]:
    """Return internal faces whose adjacent element volumes differ strongly."""

    element_volumes = [
        r25._element_volume(nodes, int(element["element_type"]), r25._parse_nodes(element["nodes"]))
        for element in elements
    ]
    face_entries: dict[tuple[int, ...], list[int]] = defaultdict(list)
    for element_index, element in enumerate(elements):
        for face in r25._volume_element_faces(
            int(element["element_type"]),
            r25._parse_nodes(element["nodes"]),
        ):
            face_entries[r25._face_node_key(face)].append(element_index)

    records: list[dict[str, Any]] = []
    for face_key, adjacent in face_entries.items():
        if len(adjacent) != 2:
            continue
        left_index, right_index = adjacent
        left_volume = float(element_volumes[left_index])
        right_volume = float(element_volumes[right_index])
        ratio = _positive_ratio(left_volume, right_volume)
        if ratio is None or ratio < min_ratio:
            continue
        left_source = str(elements[left_index].get("source") or "unknown")
        right_source = str(elements[right_index].get("source") or "unknown")
        source_pair = "|".join(sorted((left_source, right_source)))
        points = [nodes[int(node)] for node in face_key]
        records.append(
            {
                "face_nodes": list(face_key),
                "face_centroid": _centroid(points),
                "face_area_m2": r25._surface_face_area(nodes, face_key),
                "adjacent_element_indices": [left_index, right_index],
                "adjacent_sources": [left_source, right_source],
                "source_pair": source_pair,
                "adjacent_volumes_m3": [left_volume, right_volume],
                "volume_ratio": ratio,
                "smaller_element_index": left_index
                if left_volume <= right_volume
                else right_index,
                "larger_element_index": right_index
                if left_volume <= right_volume
                else left_index,
            }
        )
    records.sort(key=lambda record: float(record["volume_ratio"]), reverse=True)
    return records


def summarize_source_pair_jumps(
    records: Sequence[Mapping[str, Any]],
    *,
    blocker_ratio: float = DEFAULT_BLOCKER_RATIO,
) -> dict[str, Any]:
    by_pair: dict[str, dict[str, Any]] = {}
    for record in records:
        pair = str(record.get("source_pair") or "unknown")
        ratio = float(record.get("volume_ratio") or 0.0)
        area = float(record.get("face_area_m2") or 0.0)
        bucket = by_pair.setdefault(
            pair,
            {
                "count": 0,
                "max_volume_ratio": 0.0,
                "total_face_area_m2": 0.0,
            },
        )
        bucket["count"] = int(bucket["count"]) + 1
        bucket["max_volume_ratio"] = max(float(bucket["max_volume_ratio"]), ratio)
        bucket["total_face_area_m2"] = float(bucket["total_face_area_m2"]) + area

    max_record = max(records, key=lambda record: float(record.get("volume_ratio") or 0.0), default=None)
    max_ratio = 0.0 if max_record is None else float(max_record.get("volume_ratio") or 0.0)
    blockers = []
    if max_ratio > blocker_ratio:
        blockers.append(f"internal_face_volume_jump_above_{_ratio_label(blocker_ratio)}")
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "record_count": len(records),
        "blocker_ratio": float(blocker_ratio),
        "max_volume_ratio": max_ratio,
        "worst_source_pair": None if max_record is None else str(max_record.get("source_pair")),
        "by_source_pair": dict(sorted(by_pair.items())),
    }


def build_probe_summary(
    *,
    output_dir: Path,
    geometry_source: str,
    mesh_context: Mapping[str, Any],
    source_pair_summary: Mapping[str, Any],
    top_records: Sequence[Mapping[str, Any]],
    elapsed_s: float,
) -> dict[str, Any]:
    blockers = list(source_pair_summary.get("blockers") or [])
    blockers.extend(
        [
            "solver_postprocessed_surface_yplus_missing",
            "su2_solver_ladder_not_run",
        ]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": (
            "dual_quality_source_localized_repair_target_ready"
            if source_pair_summary.get("status") == "fail"
            else "dual_quality_source_localization_no_large_jump_found"
        ),
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "coefficient_interpretable": False,
        "output_dir": str(output_dir),
        "geometry_source": geometry_source,
        "mesh_context": dict(mesh_context),
        "source_pair_jump_summary": dict(source_pair_summary),
        "top_internal_face_jump_records": [dict(record) for record in top_records],
        "blockers": sorted(set(blockers)),
        "blocked_claims": [
            "dual_quality_source_localization_only",
            "SU2 coarse/medium/fine ladder",
            "CL/CD/Cm interpretation",
            "grid convergence",
            "Baseline A drag or power truth",
        ],
        "elapsed_s": elapsed_s,
        "engineering_read": (
            "The R28 dual-volume pathology is now localized to source-aware "
            "internal-face size jumps. Repair the worst source-pair transition "
            "before rerunning SU2 route-smoke."
            if source_pair_summary.get("status") == "fail"
            else "No extreme source-pair volume jump was found by this primal "
            "proxy. SU2 dual metrics still need another localization method."
        ),
    }


def run_probe(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    r25_output_dir: Path = DEFAULT_R25_OUTPUT_DIR,
    points_per_side: int = 16,
    spanwise_subdivisions: int = 2,
    merge_digits: int = 10,
    min_ratio: float = DEFAULT_RECORD_MIN_RATIO,
    blocker_ratio: float = DEFAULT_BLOCKER_RATIO,
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
    records = internal_face_volume_jump_records(
        nodes=state["nodes"],
        elements=state["elements"],
        min_ratio=min_ratio,
    )
    source_pair_summary = summarize_source_pair_jumps(
        records,
        blocker_ratio=blocker_ratio,
    )
    source_counts = Counter(str(element.get("source") or "unknown") for element in state["elements"])
    mesh_context = {
        "node_count": len(state["nodes"]),
        "volume_element_count": len(state["elements"]),
        "source_counts": dict(sorted(source_counts.items())),
        "marker_counts": {marker: len(faces) for marker, faces in state["markers"].items()},
        "min_recorded_volume_jump_ratio": float(min_ratio),
    }
    top_records = records[: max(0, int(top_count))]
    summary = build_probe_summary(
        output_dir=output_dir,
        geometry_source=str(state["geometry_source"]),
        mesh_context=mesh_context,
        source_pair_summary=source_pair_summary,
        top_records=top_records,
        elapsed_s=time.monotonic() - start,
    )
    write_json(output_dir / "summary.json", summary)
    write_csv(output_dir / "internal_face_volume_jump_records.csv", records)
    (output_dir / "dual_quality_source_localization_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    jump = summary.get("source_pair_jump_summary") or {}
    mesh = summary.get("mesh_context") or {}
    return "\n".join(
        [
            "# WO-006R29 Dual Quality Source Localization Probe",
            "",
            "This is a mesh-source localization diagnostic, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary.get('goal_status')}`",
            f"CFD_STATUS: `{summary.get('cfd_status')}`",
            f"- verdict: `{summary.get('verdict')}`",
            f"- nodes / volume elements: `{mesh.get('node_count')}` / `{mesh.get('volume_element_count')}`",
            f"- source counts: `{mesh.get('source_counts')}`",
            f"- max internal-face volume jump: `{jump.get('max_volume_ratio')}`",
            f"- worst source pair: `{jump.get('worst_source_pair')}`",
            f"- blockers: `{summary.get('blockers')}`",
            "",
            f"Engineering read: {summary.get('engineering_read')}",
            "",
        ]
    )


def write_csv(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_pair",
        "volume_ratio",
        "face_area_m2",
        "face_centroid_x",
        "face_centroid_y",
        "face_centroid_z",
        "adjacent_sources",
        "adjacent_element_indices",
        "adjacent_volumes_m3",
        "face_nodes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            centroid = record.get("face_centroid") or {}
            writer.writerow(
                {
                    "source_pair": record.get("source_pair"),
                    "volume_ratio": record.get("volume_ratio"),
                    "face_area_m2": record.get("face_area_m2"),
                    "face_centroid_x": centroid.get("x"),
                    "face_centroid_y": centroid.get("y"),
                    "face_centroid_z": centroid.get("z"),
                    "adjacent_sources": json.dumps(record.get("adjacent_sources")),
                    "adjacent_element_indices": json.dumps(record.get("adjacent_element_indices")),
                    "adjacent_volumes_m3": json.dumps(record.get("adjacent_volumes_m3")),
                    "face_nodes": json.dumps(record.get("face_nodes")),
                }
            )


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _positive_ratio(left: float, right: float) -> float | None:
    if left <= 0.0 or right <= 0.0:
        return None
    return max(left, right) / min(left, right)


def _centroid(points: Sequence[Sequence[float]]) -> dict[str, float]:
    if not points:
        return {"x": 0.0, "y": 0.0, "z": 0.0}
    return {
        "x": sum(float(point[0]) for point in points) / len(points),
        "y": sum(float(point[1]) for point in points) / len(points),
        "z": sum(float(point[2]) for point in points) / len(points),
    }


def _ratio_label(value: float) -> str:
    if value <= 0:
        return "0"
    exponent = round(math.log10(value))
    if math.isclose(value, 10**exponent):
        return f"1e{exponent}"
    return f"{value:.0f}".replace(".", "p")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--r25-output-dir", type=Path, default=DEFAULT_R25_OUTPUT_DIR)
    parser.add_argument("--points-per-side", type=int, default=16)
    parser.add_argument("--spanwise-subdivisions", type=int, default=2)
    parser.add_argument("--merge-digits", type=int, default=10)
    parser.add_argument("--min-ratio", type=float, default=DEFAULT_RECORD_MIN_RATIO)
    parser.add_argument("--blocker-ratio", type=float, default=DEFAULT_BLOCKER_RATIO)
    parser.add_argument("--top-count", type=int, default=50)
    args = parser.parse_args(argv)

    summary = run_probe(
        output_dir=args.output_dir,
        r25_output_dir=args.r25_output_dir,
        points_per_side=args.points_per_side,
        spanwise_subdivisions=args.spanwise_subdivisions,
        merge_digits=args.merge_digits,
        min_ratio=args.min_ratio,
        blocker_ratio=args.blocker_ratio,
        top_count=args.top_count,
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("verdict") == "dual_quality_source_localized_repair_target_ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
