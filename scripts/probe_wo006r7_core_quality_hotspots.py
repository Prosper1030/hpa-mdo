#!/usr/bin/env python3
"""Diagnose WO-006R7 preserved-core quality hotspots.

R6 proved that the owned BL block exists, but the preserved-interface core
probe still has non-positive volume/SICN/SIGE elements. This probe localizes
those core-volume quality failures back to element family, interface marker,
and Baseline A section interval before any medium/fine SU2 ladder is attempted.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from diagnose_wo006k_bl_hotspots import (  # noqa: E402
    DEFAULT_SECTION_TABLE,
    classify_hotspot,
    load_hotspots_json,
    load_section_table,
    resolve_report_mesh_path,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


SCHEMA_VERSION = "wo006r7_core_quality_hotspots.v1"
DEFAULT_CORE_REPORT = (
    WO006_ROOT / "wo006r6_core_interface_repair" / "core_probe_summary.json"
)
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r7_core_quality_hotspot_diagnosis"
CSV_FIELDS = (
    "rank",
    "element_tag",
    "element_family",
    "element_type",
    "element_type_name",
    "min_sicn",
    "min_sige",
    "volume",
    "matched_boundary_marker",
    "matched_boundary_element_type",
    "nearest_boundary_marker",
    "nearest_boundary_distance_m",
    "x_over_local_chord",
    "abs_y_m",
    "section_interval",
    "location_flags",
)


def classify_core_hotspot(
    hotspot: Mapping[str, Any],
    section_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    classified = classify_hotspot(hotspot, section_rows)
    flags = list(classified.get("location_flags") or [])
    element_family = _element_family(
        _optional_int(hotspot.get("element_type")),
        str(hotspot.get("element_type_name") or ""),
    )
    matched_marker = str(hotspot.get("matched_boundary_marker") or "")
    matched_boundary_element_type = _optional_int(
        hotspot.get("matched_boundary_element_type")
    )
    volume = _optional_float(hotspot.get("volume"))

    if volume is not None and volume <= 0.0:
        _append_unique(flags, "non_positive_core_volume")
    if element_family == "pyramid":
        _append_unique(flags, "core_pyramid_element")
    if matched_marker == "bl_outer_interface":
        _append_unique(flags, "adjacent_to_bl_outer_interface")
    if (
        element_family == "pyramid"
        and matched_marker == "bl_outer_interface"
        and matched_boundary_element_type == 3
    ):
        _append_unique(flags, "preserved_quad_to_core_pyramid_transition")

    return {
        **classified,
        "element_family": element_family,
        "matched_boundary_marker": matched_marker or None,
        "matched_boundary_element_type": matched_boundary_element_type,
        "location_flags": flags,
    }


def summarize_core_hotspots(
    hotspots: Sequence[Mapping[str, Any]],
    section_rows: Sequence[Mapping[str, Any]],
    *,
    top_n: int = 80,
) -> dict[str, Any]:
    classified = [classify_core_hotspot(hotspot, section_rows) for hotspot in hotspots]
    classified.sort(key=_quality_sort_key)
    top = classified[: max(1, int(top_n))]
    family_counts = _counts(str(item.get("element_family") or "unknown") for item in classified)
    marker_counts = _counts(
        str(item.get("matched_boundary_marker") or "unmatched") for item in classified
    )
    flag_counts = _counts(
        flag
        for item in classified
        for flag in (item.get("location_flags") or [])
    )

    non_positive_quality_count = sum(
        1
        for item in classified
        if (_optional_float(item.get("min_sicn")) or 0.0) <= 0.0
        or (_optional_float(item.get("min_sige")) or 0.0) <= 0.0
        or (_optional_float(item.get("volume")) or 0.0) <= 0.0
    )
    bl_outer_pyramid_count = sum(
        1
        for item in classified
        if item.get("element_family") == "pyramid"
        and item.get("matched_boundary_marker") == "bl_outer_interface"
    )
    aft_count = int(flag_counts.get("aft_or_te_hotspot") or 0)
    transition_count = int(flag_counts.get("airfoil_transition_band") or 0)

    blockers: list[str] = []
    if non_positive_quality_count:
        blockers.append("non_positive_core_volume_quality_hotspots")
    if bl_outer_pyramid_count:
        blockers.append("core_pyramid_hotspots_on_bl_outer_interface")
    if aft_count:
        blockers.append("core_quality_hotspots_near_trailing_edge")
    if transition_count:
        blockers.append("core_quality_hotspots_in_airfoil_transition_band")

    min_sicn_values = [
        value
        for value in (_optional_float(item.get("min_sicn")) for item in classified)
        if value is not None
    ]
    min_sige_values = [
        value
        for value in (_optional_float(item.get("min_sige")) for item in classified)
        if value is not None
    ]
    volume_values = [
        value
        for value in (_optional_float(item.get("volume")) for item in classified)
        if value is not None
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "blocked" if blockers else "pass",
        "blockers": blockers,
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "coefficient_interpretable": False,
        "hotspot_count": len(classified),
        "top_hotspot_count": len(top),
        "non_positive_core_quality_hotspot_count": non_positive_quality_count,
        "bl_outer_interface_pyramid_hotspot_count": bl_outer_pyramid_count,
        "aft_or_te_hotspot_count": aft_count,
        "airfoil_transition_hotspot_count": transition_count,
        "worst_min_sicn": min(min_sicn_values) if min_sicn_values else None,
        "worst_min_sige": min(min_sige_values) if min_sige_values else None,
        "worst_volume": min(volume_values) if volume_values else None,
        "element_family_counts": dict(sorted(family_counts.items())),
        "matched_boundary_marker_counts": dict(sorted(marker_counts.items())),
        "location_flag_counts": dict(sorted(flag_counts.items())),
        "top_hotspots": top,
        "engineering_read": _engineering_read(blockers),
    }


def extract_core_hotspots_from_core_report(
    core_report_path: Path | str,
    *,
    limit: int = 160,
) -> list[dict[str, Any]]:
    report_path = Path(core_report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    mesh_path = resolve_report_mesh_path(
        str(report.get("mesh_path") or ""),
        report_parent=report_path.parent,
        search_root=REPO_ROOT,
    )
    return extract_core_hotspots_from_mesh(mesh_path, limit=limit)


def extract_core_hotspots_from_mesh(
    mesh_path: Path | str,
    *,
    limit: int = 160,
) -> list[dict[str, Any]]:
    import gmsh  # noqa: PLC0415 - optional runtime dependency for CLI extraction.

    path = Path(mesh_path)
    if not path.is_file():
        raise FileNotFoundError(f"mesh file missing: {path}")

    rows: list[dict[str, Any]] = []
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.open(str(path))
        node_xyz = _node_xyz_map(gmsh)
        boundary_by_key, boundary_centers = _boundary_element_lookup(gmsh, node_xyz)
        element_types, element_tags_by_type, element_nodes_by_type = gmsh.model.mesh.getElements(3)
        for element_type, element_tags, flat_nodes in zip(
            element_types,
            element_tags_by_type,
            element_nodes_by_type,
        ):
            element_type = int(element_type)
            name, _dim, _order, node_count, *_rest = gmsh.model.mesh.getElementProperties(
                element_type
            )
            tags = [int(tag) for tag in element_tags]
            if not tags:
                continue
            sicn = [float(value) for value in gmsh.model.mesh.getElementQualities(tags, "minSICN")]
            sige = [float(value) for value in gmsh.model.mesh.getElementQualities(tags, "minSIGE")]
            volume = [float(value) for value in gmsh.model.mesh.getElementQualities(tags, "volume")]
            for index, element_tag in enumerate(tags):
                if sicn[index] > 0.0 and sige[index] > 0.0 and volume[index] > 0.0:
                    continue
                nodes = tuple(
                    int(node)
                    for node in flat_nodes[index * node_count : (index + 1) * node_count]
                )
                matched = _matched_boundary_element(element_type, nodes, boundary_by_key)
                centroid = _centroid(node_xyz, nodes)
                nearest = _nearest_boundary_element(centroid, boundary_centers)
                rows.append(
                    {
                        "element_tag": element_tag,
                        "element_type": element_type,
                        "element_type_name": str(name),
                        "min_sicn": sicn[index],
                        "min_sige": sige[index],
                        "volume": volume[index],
                        "centroid_xyz_m": list(centroid),
                        "matched_boundary_marker": None
                        if matched is None
                        else matched["marker"],
                        "matched_boundary_element_tag": None
                        if matched is None
                        else matched["element_tag"],
                        "matched_boundary_element_type": None
                        if matched is None
                        else matched["element_type"],
                        "nearest_boundary_marker": None
                        if nearest is None
                        else nearest["marker"],
                        "nearest_boundary_distance_m": None
                        if nearest is None
                        else nearest["distance_m"],
                    }
                )
                rows.sort(key=_quality_sort_key)
                del rows[int(limit) :]
    finally:
        gmsh.finalize()
    return rows


def run_diagnosis(
    *,
    section_table: Path,
    output_dir: Path,
    core_report: Path | None = None,
    mesh_path: Path | None = None,
    hotspots_json: Path | None = None,
    top_n: int = 80,
) -> dict[str, Any]:
    if sum(item is not None for item in (core_report, mesh_path, hotspots_json)) != 1:
        raise ValueError("Provide exactly one of core_report, mesh_path, or hotspots_json")
    output_dir.mkdir(parents=True, exist_ok=True)
    section_rows = load_section_table(section_table)
    if hotspots_json is not None:
        hotspots = load_hotspots_json(hotspots_json)
    elif mesh_path is not None:
        hotspots = extract_core_hotspots_from_mesh(mesh_path, limit=max(top_n, 160))
    else:
        assert core_report is not None
        hotspots = extract_core_hotspots_from_core_report(core_report, limit=max(top_n, 160))

    summary = summarize_core_hotspots(hotspots, section_rows, top_n=top_n)
    summary.update(
        {
            "section_table_path": str(section_table),
            "core_report_path": None if core_report is None else str(core_report),
            "mesh_path": None if mesh_path is None else str(mesh_path),
            "hotspots_json_path": None if hotspots_json is None else str(hotspots_json),
        }
    )
    json_path = output_dir / "core_quality_hotspots.json"
    csv_path = output_dir / "core_quality_hotspots.csv"
    md_path = output_dir / "core_quality_hotspot_report.md"
    summary["output_paths"] = {
        "json": str(json_path),
        "csv": str(csv_path),
        "markdown": str(md_path),
    }
    write_json(json_path, summary)
    write_hotspot_csv(csv_path, summary.get("top_hotspots") or [])
    write_markdown_report(summary, md_path)
    return summary


def write_hotspot_csv(path: Path | str, hotspots: Sequence[Mapping[str, Any]]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for rank, hotspot in enumerate(hotspots, start=1):
            interval = hotspot.get("section_interval") or {}
            writer.writerow(
                {
                    "rank": rank,
                    "element_tag": hotspot.get("element_tag"),
                    "element_family": hotspot.get("element_family"),
                    "element_type": hotspot.get("element_type"),
                    "element_type_name": hotspot.get("element_type_name"),
                    "min_sicn": hotspot.get("min_sicn"),
                    "min_sige": hotspot.get("min_sige"),
                    "volume": hotspot.get("volume"),
                    "matched_boundary_marker": hotspot.get("matched_boundary_marker"),
                    "matched_boundary_element_type": hotspot.get(
                        "matched_boundary_element_type"
                    ),
                    "nearest_boundary_marker": hotspot.get("nearest_boundary_marker"),
                    "nearest_boundary_distance_m": hotspot.get(
                        "nearest_boundary_distance_m"
                    ),
                    "x_over_local_chord": hotspot.get("x_over_local_chord"),
                    "abs_y_m": hotspot.get("abs_y_m"),
                    "section_interval": (
                        f"{interval.get('left_airfoil_id')}->{interval.get('right_airfoil_id')}"
                    ),
                    "location_flags": ",".join(hotspot.get("location_flags") or []),
                }
            )


def write_markdown_report(summary: Mapping[str, Any], path: Path | str) -> None:
    lines = [
        "# WO-006R7 Core Quality Hotspot Diagnosis",
        "",
        f"- Status: `{summary.get('status')}`",
        f"- GOAL_STATUS: `{summary.get('goal_status')}`",
        f"- CFD_STATUS: `{summary.get('cfd_status')}`",
        f"- Coefficients interpretable: `{summary.get('coefficient_interpretable')}`",
        f"- Blockers: `{summary.get('blockers')}`",
        f"- Hotspots: `{summary.get('hotspot_count')}`",
        f"- Worst minSICN: `{summary.get('worst_min_sicn')}`",
        f"- Worst minSIGE: `{summary.get('worst_min_sige')}`",
        f"- Worst volume: `{summary.get('worst_volume')}`",
        "",
        "## Engineering Read",
        "",
        str(summary.get("engineering_read") or ""),
        "",
        "## Top Hotspots",
        "",
        "| rank | family | marker | minSICN | minSIGE | volume | x/c | abs y m | interval | flags |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for index, hotspot in enumerate(summary.get("top_hotspots") or [], start=1):
        interval = hotspot.get("section_interval") or {}
        interval_text = f"{interval.get('left_airfoil_id')}->{interval.get('right_airfoil_id')}"
        lines.append(
            "| "
            f"{index} | {hotspot.get('element_family')} | "
            f"{hotspot.get('matched_boundary_marker')} | "
            f"{_fmt(hotspot.get('min_sicn'))} | {_fmt(hotspot.get('min_sige'))} | "
            f"{_fmt(hotspot.get('volume'))} | {_fmt(hotspot.get('x_over_local_chord'))} | "
            f"{_fmt(hotspot.get('abs_y_m'))} | {interval_text} | "
            f"{', '.join(hotspot.get('location_flags') or [])} |"
        )
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_json(path: Path | str, payload: Mapping[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--section-table", type=Path, default=DEFAULT_SECTION_TABLE)
    parser.add_argument("--core-report", type=Path, default=DEFAULT_CORE_REPORT)
    parser.add_argument("--mesh-path", type=Path)
    parser.add_argument("--hotspots-json", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-n", type=int, default=80)
    args = parser.parse_args(argv)
    core_report = args.core_report
    if args.mesh_path is not None or args.hotspots_json is not None:
        core_report = None
    summary = run_diagnosis(
        section_table=args.section_table,
        output_dir=args.output_dir,
        core_report=core_report,
        mesh_path=args.mesh_path,
        hotspots_json=args.hotspots_json,
        top_n=args.top_n,
    )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "hotspot_count": summary["hotspot_count"],
                "blockers": summary["blockers"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


def _node_xyz_map(gmsh: Any) -> dict[int, tuple[float, float, float]]:
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    return {
        int(tag): (
            float(coords[3 * index]),
            float(coords[3 * index + 1]),
            float(coords[3 * index + 2]),
        )
        for index, tag in enumerate(node_tags)
    }


def _boundary_element_lookup(
    gmsh: Any,
    node_xyz: Mapping[int, tuple[float, float, float]],
) -> tuple[dict[tuple[int, ...], dict[str, Any]], list[dict[str, Any]]]:
    by_key: dict[tuple[int, ...], dict[str, Any]] = {}
    centers: list[dict[str, Any]] = []
    for dim, physical_tag in gmsh.model.getPhysicalGroups(2):
        marker = gmsh.model.getPhysicalName(dim, physical_tag)
        for entity_tag in gmsh.model.getEntitiesForPhysicalGroup(dim, physical_tag):
            element_types, element_tags_by_type, flat_nodes_by_type = gmsh.model.mesh.getElements(
                dim,
                entity_tag,
            )
            for element_type, element_tags, flat_nodes in zip(
                element_types,
                element_tags_by_type,
                flat_nodes_by_type,
            ):
                element_type = int(element_type)
                _name, _dim, _order, node_count, *_rest = gmsh.model.mesh.getElementProperties(
                    element_type
                )
                for index, element_tag in enumerate(element_tags):
                    nodes = tuple(
                        int(node)
                        for node in flat_nodes[
                            index * node_count : (index + 1) * node_count
                        ]
                    )
                    centroid = _centroid(node_xyz, nodes)
                    record = {
                        "marker": marker,
                        "element_tag": int(element_tag),
                        "element_type": element_type,
                        "nodes": nodes,
                        "centroid_xyz_m": centroid,
                    }
                    by_key[tuple(sorted(nodes))] = record
                    centers.append(record)
    return by_key, centers


def _matched_boundary_element(
    element_type: int,
    nodes: Sequence[int],
    boundary_by_key: Mapping[tuple[int, ...], Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    for face in _volume_boundary_face_candidates(element_type, nodes):
        match = boundary_by_key.get(tuple(sorted(face)))
        if match is not None:
            return match
    for size in (4, 3):
        for face in itertools.combinations(tuple(nodes), size):
            match = boundary_by_key.get(tuple(sorted(face)))
            if match is not None:
                return match
    return None


def _volume_boundary_face_candidates(
    element_type: int,
    nodes: Sequence[int],
) -> list[tuple[int, ...]]:
    item = tuple(int(node) for node in nodes)
    if element_type == 4 and len(item) == 4:
        a, b, c, d = item
        return [(a, c, b), (a, b, d), (b, c, d), (c, a, d)]
    if element_type == 7 and len(item) == 5:
        a, b, c, d, e = item
        return [(a, b, c, d), (a, e, b), (b, e, c), (c, e, d), (d, e, a)]
    if element_type == 6 and len(item) == 6:
        a, b, c, d, e, f = item
        return [(a, b, c), (d, f, e), (a, d, e, b), (b, e, f, c), (c, f, d, a)]
    if element_type == 5 and len(item) == 8:
        a, b, c, d, e, f, g, h = item
        return [
            (a, b, c, d),
            (e, h, g, f),
            (a, e, f, b),
            (b, f, g, c),
            (c, g, h, d),
            (d, h, e, a),
        ]
    return []


def _nearest_boundary_element(
    point: Sequence[float],
    boundary_centers: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if not boundary_centers:
        return None
    best = min(
        boundary_centers,
        key=lambda record: _distance(point, record["centroid_xyz_m"]),
    )
    return {
        **dict(best),
        "distance_m": _distance(point, best["centroid_xyz_m"]),
    }


def _centroid(
    node_xyz: Mapping[int, tuple[float, float, float]],
    nodes: Sequence[int],
) -> tuple[float, float, float]:
    coords = [node_xyz[int(node)] for node in nodes]
    return tuple(
        float(sum(coord[axis] for coord in coords) / len(coords)) for axis in range(3)
    )


def _element_family(element_type: int | None, element_type_name: str) -> str:
    name = element_type_name.lower()
    if element_type == 7 or "pyramid" in name:
        return "pyramid"
    if element_type == 4 or "tetra" in name:
        return "tetra"
    if element_type == 6 or "prism" in name:
        return "prism"
    if element_type == 5 or "hexa" in name:
        return "hexahedron"
    return "unknown"


def _quality_sort_key(item: Mapping[str, Any]) -> tuple[float, float, float]:
    return (
        _optional_float(item.get("min_sicn")) or math.inf,
        _optional_float(item.get("min_sige")) or math.inf,
        _optional_float(item.get("volume")) or math.inf,
    )


def _engineering_read(blockers: Sequence[str]) -> str:
    if "core_pyramid_hotspots_on_bl_outer_interface" in blockers:
        return (
            "R6 core quality is dominated by non-positive pyramid transition elements "
            "attached to the preserved BL outer-interface quads. That points to the "
            "quad-to-tet pyramid transition/orientation/warped-face interface, not to "
            "SU2 iteration count, force convergence settings, or no-BL solver tuning."
        )
    if blockers:
        return (
            "The preserved core still has non-positive volume-quality hotspots, so it "
            "cannot be promoted to a BL/core handoff mesh."
        )
    return "No non-positive preserved-core quality hotspots were found."


def _counts(values: Sequence[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _optional_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _distance(
    left: Sequence[float],
    right: Sequence[float],
) -> float:
    return math.sqrt(sum((float(left[index]) - float(right[index])) ** 2 for index in range(3)))


def _fmt(value: Any) -> str:
    numeric = _optional_float(value)
    if numeric is None:
        return ""
    return f"{numeric:.6g}"


if __name__ == "__main__":
    raise SystemExit(main())
