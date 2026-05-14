#!/usr/bin/env python3
"""Diagnose WO-006K boundary-layer prism quality hotspots.

This is a mesh-quality localization tool, not a CFD completion runner. It maps
the worst BL element quality samples back onto the Baseline A section table so
transition-band and trailing-edge prism problems are visible before any
coarse/medium/fine SU2 ladder is attempted.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
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
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
    / "wo006k_bl_hotspot_diagnosis"
)
SCHEMA_VERSION = "wo006k_bl_hotspot_diagnosis.v1"


def classify_hotspot(
    hotspot: Mapping[str, Any],
    section_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    centroid = hotspot.get("centroid_xyz_m")
    if not isinstance(centroid, Sequence) or len(centroid) < 3:
        raise ValueError("hotspot centroid_xyz_m must contain x, y, z")
    x_m = _as_float(centroid[0], "centroid x")
    y_m = _as_float(centroid[1], "centroid y")
    z_m = _as_float(centroid[2], "centroid z")
    abs_y = abs(y_m)

    interval = _section_interval_for_abs_y(section_rows, abs_y)
    x_le = _lerp(interval["left_x_le_m"], interval["right_x_le_m"], interval["eta"])
    chord = _lerp(interval["left_chord_m"], interval["right_chord_m"], interval["eta"])
    x_over_chord = (x_m - x_le) / chord if chord > 0.0 else math.nan

    min_sicn = _optional_float(hotspot.get("min_sicn"))
    min_sige = _optional_float(hotspot.get("min_sige"))
    flags: list[str] = []
    if interval["is_airfoil_transition"]:
        flags.append("airfoil_transition_band")
    if math.isfinite(x_over_chord) and x_over_chord >= 0.75:
        flags.append("aft_or_te_hotspot")
    if min_sicn is not None and min_sicn <= 0.0:
        flags.append("non_positive_min_sicn")
    if min_sige is not None and min_sige <= 0.0:
        flags.append("non_positive_min_sige")

    return {
        **dict(hotspot),
        "centroid_xyz_m": [x_m, y_m, z_m],
        "abs_y_m": abs_y,
        "x_over_local_chord": x_over_chord,
        "section_interval": interval,
        "location_flags": flags,
    }


def summarize_hotspots(
    hotspots: Sequence[Mapping[str, Any]],
    section_rows: Sequence[Mapping[str, Any]],
    *,
    top_n: int = 40,
) -> dict[str, Any]:
    classified = [classify_hotspot(hotspot, section_rows) for hotspot in hotspots]
    classified.sort(key=lambda item: float(item.get("min_sicn", math.inf)))
    top = classified[: max(1, int(top_n))]

    min_sicn_values = [
        float(item["min_sicn"])
        for item in classified
        if _optional_float(item.get("min_sicn")) is not None
    ]
    min_sige_values = [
        float(item["min_sige"])
        for item in classified
        if _optional_float(item.get("min_sige")) is not None
    ]
    non_positive_sicn_count = sum(
        1 for item in classified if (_optional_float(item.get("min_sicn")) or 0.0) <= 0.0
    )
    non_positive_sige_count = sum(
        1 for item in classified if (_optional_float(item.get("min_sige")) or 0.0) <= 0.0
    )
    transition_count = sum(
        1 for item in classified if "airfoil_transition_band" in item["location_flags"]
    )
    aft_count = sum(1 for item in classified if "aft_or_te_hotspot" in item["location_flags"])

    blockers: list[str] = []
    if non_positive_sicn_count:
        blockers.append("non_positive_bl_sicn_hotspots")
    if non_positive_sige_count:
        blockers.append("non_positive_bl_sige_hotspots")
    if transition_count:
        blockers.append("bl_hotspot_in_airfoil_transition_band")
    if aft_count:
        blockers.append("bl_hotspot_near_trailing_edge")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "blocked" if blockers else "pass",
        "blockers": blockers,
        "hotspot_count": len(classified),
        "top_hotspot_count": len(top),
        "worst_min_sicn": min(min_sicn_values) if min_sicn_values else None,
        "worst_min_sige": min(min_sige_values) if min_sige_values else None,
        "non_positive_sicn_hotspot_count": non_positive_sicn_count,
        "non_positive_sige_hotspot_count": non_positive_sige_count,
        "airfoil_transition_hotspot_count": transition_count,
        "aft_or_te_hotspot_count": aft_count,
        "top_hotspots": top,
        "engineering_read": _engineering_read(blockers),
    }


def load_section_table(path: Path | str) -> list[dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) < 2:
        raise ValueError(f"section table needs at least two rows: {path}")
    return rows


def load_hotspots_json(path: Path | str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("top_hotspots") or payload.get("hotspots") or []
    if not isinstance(payload, list):
        raise ValueError("hotspots JSON must be a list or contain top_hotspots/hotspots")
    return [dict(item) for item in payload if isinstance(item, Mapping)]


def extract_worst_bl_hotspots_from_mesh_report(
    mesh_report_path: Path | str,
    *,
    limit: int = 80,
) -> list[dict[str, Any]]:
    report_path = Path(mesh_report_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    mesh_report = payload.get("mesh_report") if isinstance(payload.get("mesh_report"), dict) else payload
    mesh_path = resolve_report_mesh_path(
        str(mesh_report.get("mesh_path") or ""),
        report_parent=report_path.parent,
        search_root=REPO_ROOT,
    )
    bl_payload = mesh_report.get("boundary_layer") or {}
    bl_volume_tags = [int(tag) for tag in bl_payload.get("volume_tags") or []]
    if not mesh_path.is_file():
        raise FileNotFoundError(f"mesh file missing: {mesh_path}")
    if not bl_volume_tags:
        raise ValueError("mesh report does not contain boundary_layer.volume_tags")

    import gmsh  # noqa: PLC0415 - optional runtime dependency for CLI extraction.

    rows: list[dict[str, Any]] = []
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.open(str(mesh_path))
        for entity_tag in bl_volume_tags:
            element_types, element_tags_by_type, _ = gmsh.model.mesh.getElements(3, entity_tag)
            for element_type, element_tags in zip(element_types, element_tags_by_type):
                tags = [int(tag) for tag in element_tags]
                if not tags:
                    continue
                sicn = list(gmsh.model.mesh.getElementQualities(tags, "minSICN"))
                sige = list(gmsh.model.mesh.getElementQualities(tags, "minSIGE"))
                for tag, min_sicn, min_sige in zip(tags, sicn, sige):
                    candidate = _mesh_element_hotspot(
                        gmsh,
                        element_tag=int(tag),
                        entity_tag=int(entity_tag),
                        element_type=int(element_type),
                        min_sicn=float(min_sicn),
                        min_sige=float(min_sige),
                    )
                    rows.append(candidate)
                    rows.sort(key=lambda item: float(item["min_sicn"]))
                    del rows[int(limit) :]
    finally:
        gmsh.finalize()
    return rows


def write_markdown_report(summary: Mapping[str, Any], path: Path | str) -> None:
    lines = [
        "# WO-006K BL Hotspot Diagnosis",
        "",
        f"- Status: `{summary.get('status')}`",
        f"- Blockers: `{summary.get('blockers')}`",
        f"- Worst minSICN: `{summary.get('worst_min_sicn')}`",
        f"- Worst minSIGE: `{summary.get('worst_min_sige')}`",
        f"- Airfoil-transition hotspot count: `{summary.get('airfoil_transition_hotspot_count')}`",
        f"- Aft/TE hotspot count: `{summary.get('aft_or_te_hotspot_count')}`",
        "",
        "## Engineering Read",
        "",
        str(summary.get("engineering_read") or ""),
        "",
        "## Top Hotspots",
        "",
        "| rank | minSICN | minSIGE | x/c | abs y m | interval | flags |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for index, hotspot in enumerate(summary.get("top_hotspots") or [], start=1):
        interval = hotspot.get("section_interval") or {}
        left = interval.get("left_airfoil_id")
        right = interval.get("right_airfoil_id")
        interval_text = f"{left}->{right}"
        lines.append(
            "| "
            f"{index} | {_fmt(hotspot.get('min_sicn'))} | {_fmt(hotspot.get('min_sige'))} | "
            f"{_fmt(hotspot.get('x_over_local_chord'))} | {_fmt(hotspot.get('abs_y_m'))} | "
            f"{interval_text} | {', '.join(hotspot.get('location_flags') or [])} |"
        )
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def resolve_report_mesh_path(
    raw_path: str | Path,
    *,
    report_parent: Path,
    search_root: Path = REPO_ROOT,
) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    root_relative = search_root / path
    if root_relative.exists():
        return root_relative
    return report_parent / path


def run_diagnosis(
    *,
    section_table: Path,
    output_dir: Path,
    mesh_report: Path | None = None,
    hotspots_json: Path | None = None,
    top_n: int = 40,
) -> dict[str, Any]:
    if hotspots_json is None and mesh_report is None:
        raise ValueError("Either mesh_report or hotspots_json is required")
    output_dir.mkdir(parents=True, exist_ok=True)
    sections = load_section_table(section_table)
    hotspots = (
        load_hotspots_json(hotspots_json)
        if hotspots_json is not None
        else extract_worst_bl_hotspots_from_mesh_report(mesh_report, limit=max(top_n, 80))
    )
    summary = summarize_hotspots(hotspots, sections, top_n=top_n)
    summary.update(
        {
            "section_table_path": str(section_table),
            "mesh_report_path": None if mesh_report is None else str(mesh_report),
            "hotspots_json_path": None if hotspots_json is None else str(hotspots_json),
        }
    )
    json_path = output_dir / "bl_hotspot_diagnosis.json"
    md_path = output_dir / "bl_hotspot_diagnosis.md"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_markdown_report(summary, md_path)
    summary["output_paths"] = {"json": str(json_path), "markdown": str(md_path)}
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--section-table", type=Path, default=DEFAULT_SECTION_TABLE)
    parser.add_argument("--mesh-report", type=Path)
    parser.add_argument("--hotspots-json", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-n", type=int, default=40)
    args = parser.parse_args(argv)

    summary = run_diagnosis(
        section_table=args.section_table,
        output_dir=args.output_dir,
        mesh_report=args.mesh_report,
        hotspots_json=args.hotspots_json,
        top_n=args.top_n,
    )
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"] == "pass" else 2


def _mesh_element_hotspot(
    gmsh: Any,
    *,
    element_tag: int,
    entity_tag: int,
    element_type: int,
    min_sicn: float,
    min_sige: float,
) -> dict[str, Any]:
    _, node_tags, _, _ = gmsh.model.mesh.getElement(element_tag)
    coords = []
    for node_tag in node_tags:
        coord, _, _, _ = gmsh.model.mesh.getNode(int(node_tag))
        coords.append(coord)
    centroid = [
        float(sum(coord[axis] for coord in coords) / len(coords)) for axis in range(3)
    ]
    return {
        "element_tag": int(element_tag),
        "entity_tag": int(entity_tag),
        "element_type": int(element_type),
        "min_sicn": float(min_sicn),
        "min_sige": float(min_sige),
        "centroid_xyz_m": centroid,
    }


def _section_interval_for_abs_y(
    section_rows: Sequence[Mapping[str, Any]],
    abs_y: float,
) -> dict[str, Any]:
    rows = sorted((_section_payload(row) for row in section_rows), key=lambda row: row["y_m"])
    if abs_y <= rows[0]["y_m"]:
        left, right = rows[0], rows[1]
    elif abs_y >= rows[-1]["y_m"]:
        left, right = rows[-2], rows[-1]
    else:
        left, right = rows[-2], rows[-1]
        for candidate_left, candidate_right in zip(rows[:-1], rows[1:]):
            if candidate_left["y_m"] <= abs_y <= candidate_right["y_m"]:
                left, right = candidate_left, candidate_right
                break
    dy = right["y_m"] - left["y_m"]
    eta = 0.0 if abs(dy) <= 1.0e-12 else (abs_y - left["y_m"]) / dy
    return {
        "left_section_index": left["section_index"],
        "right_section_index": right["section_index"],
        "left_y_m": left["y_m"],
        "right_y_m": right["y_m"],
        "eta": eta,
        "left_airfoil_id": left["airfoil_id"],
        "right_airfoil_id": right["airfoil_id"],
        "is_airfoil_transition": left["airfoil_id"] != right["airfoil_id"],
        "left_chord_m": left["chord_m"],
        "right_chord_m": right["chord_m"],
        "left_x_le_m": left["x_le_m"],
        "right_x_le_m": right["x_le_m"],
    }


def _section_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "section_index": int(float(row.get("section_index", 0))),
        "y_m": _as_float(row.get("y_m"), "y_m"),
        "chord_m": _as_float(row.get("chord_m"), "chord_m"),
        "x_le_m": _optional_float(row.get("x_le_m")) or 0.0,
        "airfoil_id": str(row.get("airfoil_id") or "unknown"),
    }


def _engineering_read(blockers: Sequence[str]) -> str:
    if not blockers:
        return (
            "No severe BL hotspot blocker was found in the sampled elements. This is only a "
            "mesh-quality localization pass; CFD still requires y+, force stability, and a "
            "coarse/medium/fine ladder."
        )
    return (
        "The sampled BL quality hotspots are still blocking CFD ladder use. If the blockers "
        "localize to the aft airfoil-transition band, the next repair should target local "
        "TE/tip/transition prism topology rather than more SU2 iterations."
    )


def _as_float(value: Any, label: str) -> float:
    result = _optional_float(value)
    if result is None:
        raise ValueError(f"Expected finite float for {label}: {value!r}")
    return result


def _optional_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str) and value.strip():
        result = float(value)
    else:
        return None
    return result if math.isfinite(result) else None


def _lerp(left: float, right: float, eta: float) -> float:
    return float(left) + (float(right) - float(left)) * float(eta)


def _fmt(value: Any) -> str:
    parsed = _optional_float(value)
    if parsed is None:
        return ""
    return f"{parsed:.6g}"


if __name__ == "__main__":
    raise SystemExit(main())
