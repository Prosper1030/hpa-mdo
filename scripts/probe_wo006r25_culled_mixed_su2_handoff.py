#!/usr/bin/env python3
"""Write a culled global-star mixed SU2 handoff probe for WO-006.

R24 proved that the only degenerate global-star triangles are unmarked
``wake_receiver`` zero-area faces.  This probe takes the next bounded step:
materialize a single SU2 mesh from

* the R22/R24 culled global-star near-wall tets,
* the R19 loop-cap owner pyramids, and
* the R13 repaired loop-cap core tet mesh.

It then audits whether every exterior volume face is explicitly owned by a SU2
boundary marker.  This is still a mesh-handoff/y+ setup probe, not a solver
ladder and not CFD coefficient evidence.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sys
import time
import traceback
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
for path in (SCRIPT_DIR, HPA_MESHING_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hpa_meshing.mesh_native.gmsh_polyhedral import (  # noqa: E402
    write_core_tet_mesh_from_inner_surface,
)
from hpa_meshing.mesh_native.near_wall_block import (  # noqa: E402
    BoundaryLayerBlockSpec,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.wing_surface import build_farfield_box_surface  # noqa: E402
from probe_wo006ad_near_wall_merged_volume_candidate import (  # noqa: E402
    _face_records,
    build_near_wall_merged_volume_candidate,
    merged_boundary_face_rows,
    volume_cell_rows,
)
from probe_wo006r11_core_facing_loop_closure import core_facing_rows  # noqa: E402
from probe_wo006r13_loop_cap_geometric_seam_repair import (  # noqa: E402
    build_loop_cap_surface,
    repair_loop_cap_geometric_seams,
)
from probe_wo006r17_hybrid_tet_prism_split import (  # noqa: E402
    audit_hybrid_tet_prism_split_compatibility,
)
from probe_wo006r19_loop_cap_owner_pyramid import (  # noqa: E402
    PHYSICAL_WALL_EDGE_RECEIVER,
    audit_loop_cap_owner_pyramids,
)
from probe_wo006r22_global_star_split_basis import (  # noqa: E402
    global_star_target_triangle_rows,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    build_yplus_nearwall_summary,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


SCHEMA_VERSION = "wo006r25_culled_mixed_su2_handoff_probe.v1"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r25_culled_mixed_su2_handoff_probe"

SU2_TRIANGLE = 5
SU2_QUAD = 9
SU2_TETRA = 10
SU2_PYRAMID = 14
SU2_VOLUME_NODE_COUNTS = {SU2_TETRA: 4, SU2_PYRAMID: 5}
SU2_SURFACE_NODE_COUNTS = {SU2_TRIANGLE: 3, SU2_QUAD: 4}
HEX_FACE_LOCAL_NODES = (
    (0, 1, 2, 3),
    (4, 7, 6, 5),
    (0, 4, 5, 1),
    (1, 5, 6, 2),
    (2, 6, 7, 3),
    (3, 7, 4, 0),
)
FINAL_BOUNDARY_MARKERS = ("wing_wall", "farfield")


class MixedMeshBuilder:
    """Coordinate-merging node accumulator for a mesh-native/SU2 merge probe."""

    def __init__(self, *, digits: int = 10) -> None:
        self.digits = int(digits)
        self.nodes: list[tuple[float, float, float]] = []
        self._node_by_key: dict[tuple[float, float, float], int] = {}

    def add_point(self, point: Sequence[float]) -> int:
        key = _point_key(point, digits=self.digits)
        if key in self._node_by_key:
            return self._node_by_key[key]
        index = len(self.nodes)
        self.nodes.append((float(point[0]), float(point[1]), float(point[2])))
        self._node_by_key[key] = index
        return index

    def add_candidate_node(
        self,
        vertices: Sequence[tuple[float, float, float]],
        node: int,
    ) -> int:
        return self.add_point(vertices[int(node)])


def build_culled_global_star_near_wall_elements(
    *,
    vertices: Sequence[tuple[float, float, float]],
    candidate_cells: Sequence[Mapping[str, Any]],
    target_triangle_rows: Sequence[Mapping[str, Any]],
    writer: MixedMeshBuilder,
    external_boundary_rows: Sequence[Mapping[str, Any]] = (),
    boundary_marker_roles: Iterable[str] = ("wing_wall",),
    area_tol: float = 1.0e-14,
) -> dict[str, Any]:
    target_groups: dict[tuple[int, tuple[int, ...]], list[Mapping[str, Any]]] = {}
    for row in target_triangle_rows:
        cell_index = int(row.get("cell_index", -1))
        face_key = _face_node_key(_parse_nodes(row.get("face_nodes")))
        target_groups.setdefault((cell_index, face_key), []).append(row)

    boundary_role_by_face_key: dict[tuple[int, ...], str] = {}
    for row in external_boundary_rows:
        face_key = _face_node_key(_parse_nodes(row.get("nodes")))
        role = str(row.get("role") or "")
        previous = boundary_role_by_face_key.get(face_key)
        if previous == "wing_wall":
            continue
        if role == "wing_wall" or previous is None:
            boundary_role_by_face_key[face_key] = role
    final_marker_roles = set(boundary_marker_roles)
    elements: list[dict[str, Any]] = []
    marker_faces: dict[str, list[dict[str, Any]]] = {role: [] for role in final_marker_roles}
    culled_degenerate = 0
    non_positive = 0
    min_volume = None
    max_volume = None
    source_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()

    for raw_cell_index, cell in enumerate(candidate_cells):
        cell_index = int(cell.get("cell_index", raw_cell_index))
        cell_nodes = _parse_nodes(cell.get("nodes"))
        if len(cell_nodes) != 8:
            continue
        center_node = writer.add_point(_mean_point(vertices, cell_nodes))
        source = str(cell.get("source") or "")
        role = str(cell.get("role") or "")
        source_counts[source] += 1
        role_counts[role] += 1
        for local_face in HEX_FACE_LOCAL_NODES:
            face_nodes = tuple(cell_nodes[index] for index in local_face)
            face_key = _face_node_key(face_nodes)
            external_boundary_role = boundary_role_by_face_key.get(face_key, "")
            target_rows = target_groups.get((cell_index, face_key))
            if target_rows:
                triangles = [_parse_nodes(row.get("triangle_nodes")) for row in target_rows]
                boundary_role = str(target_rows[0].get("marker") or "")
            else:
                triangles = _deterministic_quad_triangulation(face_nodes)
                boundary_role = external_boundary_role

            for triangle in triangles:
                triangle_points = [vertices[int(node)] for node in triangle]
                if _triangle_area(*triangle_points) <= area_tol:
                    culled_degenerate += 1
                    continue
                global_triangle = tuple(
                    writer.add_candidate_node(vertices, int(node)) for node in triangle
                )
                element_nodes = (center_node, *global_triangle)
                if len(set(element_nodes)) != 4:
                    culled_degenerate += 1
                    continue
                volume = _tetra_volume_from_points(
                    writer.nodes[element_nodes[0]],
                    writer.nodes[element_nodes[1]],
                    writer.nodes[element_nodes[2]],
                    writer.nodes[element_nodes[3]],
                )
                if volume <= area_tol:
                    non_positive += 1
                min_volume = volume if min_volume is None else min(min_volume, volume)
                max_volume = volume if max_volume is None else max(max_volume, volume)
                elements.append(
                    {
                        "element_type": SU2_TETRA,
                        "nodes": element_nodes,
                        "source": "culled_global_star_near_wall",
                    }
                )
                final_marker_role = (
                    external_boundary_role
                    if external_boundary_role in final_marker_roles
                    else boundary_role
                    if boundary_role in final_marker_roles
                    else ""
                )
                if final_marker_role:
                    marker_faces.setdefault(final_marker_role, []).append(
                        {
                            "element_type": SU2_TRIANGLE,
                            "nodes": global_triangle,
                        }
                    )

    return {
        "schema_version": "wo006r25_culled_global_star_near_wall.v1",
        "element_count": len(elements),
        "elements": elements,
        "boundary_marker_faces": marker_faces,
        "culled_degenerate_triangle_count": culled_degenerate,
        "non_positive_volume_count": non_positive,
        "min_volume_m3": 0.0 if min_volume is None else min_volume,
        "max_volume_m3": 0.0 if max_volume is None else max_volume,
        "candidate_cell_count": len(candidate_cells),
        "candidate_cell_counts_by_source": dict(sorted(source_counts.items())),
        "candidate_cell_counts_by_role": dict(sorted(role_counts.items())),
    }


def build_loop_cap_owner_pyramid_elements(
    *,
    candidate_vertices: Sequence[tuple[float, float, float]],
    core_vertices: Sequence[tuple[float, float, float]],
    owner_pyramid_rows: Sequence[Mapping[str, Any]],
    writer: MixedMeshBuilder,
    volume_tol: float = 1.0e-14,
) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    non_positive = 0
    min_volume = None
    max_volume = None
    for row in owner_pyramid_rows:
        base_nodes = _parse_nodes(row.get("base_nodes"))
        if len(base_nodes) != 4:
            continue
        apex_node = int(row.get("center_node"))
        global_base_by_candidate = {
            int(node): writer.add_candidate_node(candidate_vertices, int(node))
            for node in base_nodes
        }
        global_apex = writer.add_point(core_vertices[apex_node])
        global_nodes = (
            global_base_by_candidate[int(base_nodes[0])],
            global_base_by_candidate[int(base_nodes[1])],
            global_base_by_candidate[int(base_nodes[2])],
            global_base_by_candidate[int(base_nodes[3])],
            global_apex,
        )
        volume = _pyramid_volume_from_nodes(writer.nodes, global_nodes)
        if volume <= volume_tol:
            non_positive += 1
        min_volume = volume if min_volume is None else min(min_volume, volume)
        max_volume = volume if max_volume is None else max(max_volume, volume)
        for triangle in _deterministic_quad_triangulation(base_nodes):
            global_triangle = tuple(global_base_by_candidate[int(node)] for node in triangle)
            elements.append(
                {
                    "element_type": SU2_TETRA,
                    "nodes": (global_apex, *global_triangle),
                    "source": "loop_cap_owner_pyramid_tet_split",
                }
            )
    return {
        "schema_version": "wo006r25_loop_cap_owner_pyramid_elements.v1",
        "element_count": len(elements),
        "elements": elements,
        "split_policy": "two_tets_per_owner_pyramid_to_match_global_star_base_diagonal",
        "non_positive_volume_count": non_positive,
        "min_volume_m3": 0.0 if min_volume is None else min_volume,
        "max_volume_m3": 0.0 if max_volume is None else max_volume,
    }


def parse_su2_mesh(path: Path | str) -> dict[str, Any]:
    lines = [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    index = 0
    nodes: list[tuple[float, float, float]] = []
    elements: list[dict[str, Any]] = []
    markers: dict[str, list[dict[str, Any]]] = {}
    while index < len(lines):
        line = lines[index]
        if line.startswith("NELEM="):
            count = int(line.split("=", 1)[1])
            for raw in lines[index + 1 : index + 1 + count]:
                parts = raw.split()
                element_type = int(parts[0])
                node_count = SU2_VOLUME_NODE_COUNTS.get(element_type)
                if node_count is None:
                    raise ValueError(f"Unsupported SU2 volume element type: {element_type}")
                elements.append(
                    {
                        "element_type": element_type,
                        "nodes": tuple(int(value) for value in parts[1 : 1 + node_count]),
                        "source": "core_tet_mesh",
                    }
                )
            index += count + 1
            continue
        if line.startswith("NPOIN="):
            count = int(line.split("=", 1)[1])
            for raw in lines[index + 1 : index + 1 + count]:
                parts = raw.split()
                nodes.append((float(parts[0]), float(parts[1]), float(parts[2])))
            index += count + 1
            continue
        if line.startswith("NMARK="):
            index += 1
            while index < len(lines):
                if not lines[index].startswith("MARKER_TAG="):
                    break
                marker = lines[index].split("=", 1)[1].strip()
                marker_count_line = lines[index + 1]
                if not marker_count_line.startswith("MARKER_ELEMS="):
                    raise ValueError(f"Malformed SU2 marker block for {marker}")
                count = int(marker_count_line.split("=", 1)[1])
                marker_elements = []
                for raw in lines[index + 2 : index + 2 + count]:
                    parts = raw.split()
                    element_type = int(parts[0])
                    node_count = SU2_SURFACE_NODE_COUNTS.get(element_type)
                    if node_count is None:
                        raise ValueError(
                            f"Unsupported SU2 marker element type {element_type} "
                            f"for marker {marker}"
                        )
                    marker_elements.append(
                        {
                            "element_type": element_type,
                            "nodes": tuple(int(value) for value in parts[1 : 1 + node_count]),
                        }
                    )
                markers[marker] = marker_elements
                index += count + 2
            continue
        index += 1
    return {
        "nodes": nodes,
        "elements": elements,
        "markers": markers,
    }


def add_core_mesh_to_mixed_builder(
    *,
    core_mesh: Mapping[str, Any],
    writer: MixedMeshBuilder,
) -> dict[str, Any]:
    core_nodes = list(core_mesh.get("nodes") or [])
    node_map = [writer.add_point(point) for point in core_nodes]
    elements = []
    for element in core_mesh.get("elements") or []:
        elements.append(
            {
                "element_type": int(element["element_type"]),
                "nodes": tuple(node_map[int(node)] for node in element["nodes"]),
                "source": "core_tet_mesh",
            }
        )
    farfield_faces = []
    for face in (core_mesh.get("markers") or {}).get("farfield", []):
        farfield_faces.append(
            {
                "element_type": int(face["element_type"]),
                "nodes": tuple(node_map[int(node)] for node in face["nodes"]),
            }
        )
    return {
        "elements": elements,
        "farfield_marker_faces": farfield_faces,
        "core_node_count": len(core_nodes),
        "core_element_count": len(elements),
        "core_marker_names": sorted((core_mesh.get("markers") or {}).keys()),
    }


def audit_volume_boundary_markers(
    *,
    elements: Sequence[Mapping[str, Any]],
    markers: Mapping[str, Sequence[Mapping[str, Any]]],
    nodes: Sequence[tuple[float, float, float]] | None = None,
) -> dict[str, Any]:
    face_counts: Counter[tuple[int, ...]] = Counter()
    for element in elements:
        for face in _volume_element_faces(
            int(element["element_type"]),
            _parse_nodes(element["nodes"]),
        ):
            face_counts[_face_node_key(face)] += 1
    boundary_keys = {key for key, count in face_counts.items() if count == 1}
    nonmanifold_face_count = sum(1 for count in face_counts.values() if count > 2)
    marker_key_counts: Counter[tuple[int, ...]] = Counter()
    marker_face_counts: dict[str, int] = {}
    for marker, faces in markers.items():
        marker_face_counts[str(marker)] = len(faces)
        for face in faces:
            marker_key_counts[_face_node_key(_parse_nodes(face["nodes"]))] += 1
    marker_keys = set(marker_key_counts)
    duplicate_marker_face_count = sum(count - 1 for count in marker_key_counts.values() if count > 1)
    unmarked = boundary_keys - marker_keys
    extra = marker_keys - boundary_keys
    missing_required = [
        marker for marker in FINAL_BOUNDARY_MARKERS if marker_face_counts.get(marker, 0) <= 0
    ]
    unmarked_area = (
        sum(_surface_face_area(nodes, face) for face in unmarked)
        if nodes is not None
        else None
    )
    marked_boundary_area = (
        sum(_surface_face_area(nodes, face) for face in boundary_keys & marker_keys)
        if nodes is not None
        else None
    )
    blockers = []
    if unmarked:
        blockers.append("volume_boundary_faces_without_su2_marker")
    if extra:
        blockers.append("marker_faces_not_on_volume_boundary")
    if duplicate_marker_face_count:
        blockers.append("duplicate_su2_marker_faces")
    if nonmanifold_face_count:
        blockers.append("nonmanifold_volume_faces")
    if missing_required:
        blockers.append("required_final_boundary_marker_missing")
    return {
        "schema_version": "wo006r25_volume_boundary_marker_audit.v1",
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "boundary_face_count": len(boundary_keys),
        "marked_boundary_face_count": len(boundary_keys & marker_keys),
        "unmarked_boundary_face_count": len(unmarked),
        "extra_marker_face_count": len(extra),
        "duplicate_marker_face_count": duplicate_marker_face_count,
        "nonmanifold_volume_face_count": nonmanifold_face_count,
        "missing_required_markers": missing_required,
        "marker_face_counts": dict(sorted(marker_face_counts.items())),
        "unmarked_boundary_area_m2": unmarked_area,
        "marked_boundary_area_m2": marked_boundary_area,
        "unmarked_boundary_face_samples": [list(key) for key in sorted(unmarked)[:20]],
        "extra_marker_face_samples": [list(key) for key in sorted(extra)[:20]],
    }


def recover_wall_closure_marker_faces(
    *,
    nodes: Sequence[tuple[float, float, float]],
    elements: Sequence[Mapping[str, Any]],
    markers: Mapping[str, Sequence[Mapping[str, Any]]],
    candidate_vertices: Sequence[tuple[float, float, float]],
    candidate_face_records: Sequence[Mapping[str, Any]],
    digits: int = 10,
) -> dict[str, Any]:
    recoverable_keys: dict[tuple[tuple[float, float, float], ...], str] = {}
    for record in candidate_face_records:
        role = str(record.get("role") or "")
        if role not in {"wing_wall", PHYSICAL_WALL_EDGE_RECEIVER}:
            continue
        for triangle in _deterministic_quad_triangulation(_parse_nodes(record.get("nodes"))):
            key = _point_polygon_key(
                [candidate_vertices[int(node)] for node in triangle],
                digits=digits,
            )
            recoverable_keys[key] = role

    marker_face_keys = {
        _face_node_key(_parse_nodes(face["nodes"]))
        for faces in markers.values()
        for face in faces
    }
    face_counts: Counter[tuple[int, ...]] = Counter()
    for element in elements:
        for face in _volume_element_faces(
            int(element["element_type"]),
            _parse_nodes(element["nodes"]),
        ):
            face_counts[_face_node_key(face)] += 1

    recovered_faces = []
    recovered_by_role: Counter[str] = Counter()
    for face_key, count in sorted(face_counts.items()):
        if count != 1 or face_key in marker_face_keys:
            continue
        point_key = _point_polygon_key([nodes[int(node)] for node in face_key], digits=digits)
        role = recoverable_keys.get(point_key)
        if role is None:
            continue
        if len(face_key) == 3:
            element_type = SU2_TRIANGLE
        elif len(face_key) == 4:
            element_type = SU2_QUAD
        else:
            continue
        recovered_faces.append({"element_type": element_type, "nodes": tuple(face_key)})
        recovered_by_role[role] += 1
    return {
        "schema_version": "wo006r25_wall_closure_marker_recovery.v1",
        "recovered_face_count": len(recovered_faces),
        "recovered_by_source_role": dict(sorted(recovered_by_role.items())),
        "faces": recovered_faces,
        "policy": (
            "Only exterior volume faces already proven unmarked by the boundary audit "
            "and matching candidate wing_wall/physical_wall_edge_receiver geometry are "
            "promoted to the final wing_wall marker."
        ),
    }


def evaluate_mixed_mesh_quality(
    *,
    nodes: Sequence[tuple[float, float, float]],
    elements: Sequence[Mapping[str, Any]],
    volume_tol: float = 1.0e-14,
) -> dict[str, Any]:
    volumes = [
        _element_volume(nodes, int(element["element_type"]), _parse_nodes(element["nodes"]))
        for element in elements
    ]
    non_positive = sum(1 for volume in volumes if volume <= volume_tol)
    blockers = []
    if non_positive:
        blockers.append("non_positive_mixed_volume_elements")
    return {
        "schema_version": "wo006r25_mixed_mesh_quality.v1",
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "volume_element_count": len(elements),
        "non_positive_volume_count": non_positive,
        "min_volume_m3": min(volumes) if volumes else 0.0,
        "max_volume_m3": max(volumes) if volumes else 0.0,
    }


def write_su2_mesh(
    *,
    path: Path,
    nodes: Sequence[tuple[float, float, float]],
    elements: Sequence[Mapping[str, Any]],
    markers: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["NDIME= 3", f"NELEM= {len(elements)}"]
    for index, element in enumerate(elements):
        nodes_text = " ".join(str(int(node)) for node in element["nodes"])
        lines.append(f"{int(element['element_type'])} {nodes_text} {index}")
    lines.append(f"NPOIN= {len(nodes)}")
    for index, point in enumerate(nodes):
        lines.append(
            f"{point[0]:.16e} {point[1]:.16e} {point[2]:.16e} {index}"
        )
    non_empty_markers = {marker: list(faces) for marker, faces in markers.items() if faces}
    lines.append(f"NMARK= {len(non_empty_markers)}")
    for marker, faces in non_empty_markers.items():
        lines.append(f"MARKER_TAG= {marker}")
        lines.append(f"MARKER_ELEMS= {len(faces)}")
        for face in faces:
            nodes_text = " ".join(str(int(node)) for node in face["nodes"])
            lines.append(f"{int(face['element_type'])} {nodes_text}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_probe_summary(
    *,
    output_dir: Path,
    geometry_source: str,
    handoff: Mapping[str, Any],
    boundary_audit: Mapping[str, Any],
    quality: Mapping[str, Any],
    yplus: Mapping[str, Any],
    core_report: Mapping[str, Any],
    star_split: Mapping[str, Any],
    loop_cap: Mapping[str, Any],
) -> dict[str, Any]:
    handoff_pass = (
        handoff.get("status") == "mixed_su2_handoff_written"
        and boundary_audit.get("status") == "pass"
        and quality.get("status") == "pass"
    )
    blockers = []
    if handoff.get("status") != "mixed_su2_handoff_written":
        blockers.append("mixed_su2_handoff_not_written")
    blockers.extend(str(item) for item in boundary_audit.get("blockers") or [])
    blockers.extend(str(item) for item in quality.get("blockers") or [])
    blockers.extend(
        [
            "su2_solver_ladder_not_run",
            "solver_postprocessed_surface_yplus_missing",
        ]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": (
            "mixed_su2_handoff_written_solver_ladder_pending"
            if handoff_pass
            else "mixed_su2_handoff_marker_or_quality_blocked"
        ),
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "coefficient_interpretable": False,
        "output_dir": str(output_dir),
        "geometry_source": geometry_source,
        "mixed_su2_handoff": dict(handoff),
        "volume_boundary_marker_audit": dict(boundary_audit),
        "mixed_mesh_quality": dict(quality),
        "near_wall_yplus": dict(yplus),
        "core_report": dict(core_report),
        "star_split": _drop_heavy_elements(star_split),
        "loop_cap_owner_pyramids": _drop_heavy_elements(loop_cap),
        "blockers": sorted(set(blockers)),
        "blocked_claims": [
            "SU2 coarse/medium/fine ladder",
            "CL/CD/Cm interpretation",
            "grid convergence",
            "Baseline A drag or power truth",
        ],
        "engineering_read": (
            "The culled mixed SU2 handoff is marker/quality-audited enough for the "
            "next bounded step: wire a solver smoke and then a grid ladder. It is "
            "still not CFD evidence because no Baseline A SU2 ladder has run and "
            "surface y+ has not been solver-postprocessed."
            if handoff_pass
            else "The mixed SU2 handoff still has marker or volume-quality blockers. "
            "Do not run medium/fine SU2 until the boundary leak/quality report is clear."
        ),
    }


def run_probe(
    *,
    output_dir: Path,
    clean: bool = True,
    points_per_side: int = 16,
    spanwise_subdivisions: int = 2,
    core_mesh_size: float = 1.0,
    farfield_mesh_size: float = 8.0,
    gmsh_threads: int = 4,
    merge_digits: int = 10,
) -> dict[str, Any]:
    start = time.monotonic()
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    geometry = load_campaign_geometry(
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    block = build_wing_boundary_layer_block(
        geometry.spec.wing_spec,
        BoundaryLayerBlockSpec(
            first_layer_height_m=BL_FIRST_HEIGHT_M,
            growth_ratio=BL_GROWTH_RATIO,
            layer_count=BL_LAYERS,
        ),
    )
    candidate = build_near_wall_merged_volume_candidate(block)
    boundary_rows = merged_boundary_face_rows(block, candidate)
    core_boundary_rows = core_facing_rows(boundary_rows)
    cap_surface = build_loop_cap_surface(block, candidate)
    repaired_surface, repair = repair_loop_cap_geometric_seams(cap_surface)
    hybrid_audit = audit_hybrid_tet_prism_split_compatibility(
        vertices=candidate.vertices,
        candidate_cells=volume_cell_rows(candidate),
        candidate_boundary_faces=core_boundary_rows,
        core_interface=repaired_surface,
    )
    target_rows = global_star_target_triangle_rows(
        candidate_vertices=candidate.vertices,
        candidate_cells=volume_cell_rows(candidate),
        candidate_boundary_faces=core_boundary_rows,
        core_vertices=repaired_surface.vertices,
        core_triangle_rows=hybrid_audit["core_triangle_rows"],
    )
    loop_cap_audit = audit_loop_cap_owner_pyramids(
        candidate_vertices=candidate.vertices,
        core_vertices=repaired_surface.vertices,
        physical_wall_edge_rows=[
            row
            for row in boundary_rows
            if str(row.get("role") or "") == PHYSICAL_WALL_EDGE_RECEIVER
        ],
        core_triangle_rows=hybrid_audit["core_triangle_rows"],
    )

    core_dir = output_dir / "core_probe_artifacts"
    core_dir.mkdir(parents=True, exist_ok=True)
    farfield = build_farfield_box_surface(
        repaired_surface,
        upstream_factor=2.0,
        downstream_factor=4.0,
        lateral_factor=2.0,
        vertical_factor=2.0,
    )
    core_report_path = core_dir / "r25_repaired_loop_cap_core_probe_report.json"
    if not clean and core_report_path.exists():
        core_report = json.loads(core_report_path.read_text(encoding="utf-8"))
    else:
        try:
            core_report = write_core_tet_mesh_from_inner_surface(
                repaired_surface,
                farfield,
                core_dir / "r25_repaired_loop_cap_core_probe.msh",
                su2_path=core_dir / "r25_repaired_loop_cap_core_probe.su2",
                mesh_size=core_mesh_size,
                farfield_mesh_size=farfield_mesh_size,
                preserve_boundary_mesh=True,
                preserved_boundary_representation="triangulated",
                gmsh_threads=gmsh_threads,
                mesh_algorithm3d=10,
                owned_bl_block=block,
            )
        except Exception as exc:  # pragma: no cover - captures real mesher failures.
            core_report = {
                "status": "failed",
                "failure_code": "r25_core_mesh_generation_failed",
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "su2_path": None,
                "mesh_quality_gate": {"status": "fail", "blockers": ["core_mesh_exception"]},
            }
        write_json(core_report_path, core_report)

    writer = MixedMeshBuilder(digits=merge_digits)
    star_split = build_culled_global_star_near_wall_elements(
        vertices=candidate.vertices,
        candidate_cells=volume_cell_rows(candidate),
        target_triangle_rows=target_rows,
        external_boundary_rows=boundary_rows,
        writer=writer,
    )
    loop_cap = build_loop_cap_owner_pyramid_elements(
        candidate_vertices=candidate.vertices,
        core_vertices=repaired_surface.vertices,
        owner_pyramid_rows=loop_cap_audit.get("owner_pyramid_rows") or [],
        writer=writer,
    )
    elements = [
        *star_split["elements"],
        *loop_cap["elements"],
    ]
    markers = {
        "wing_wall": list((star_split.get("boundary_marker_faces") or {}).get("wing_wall") or []),
        "farfield": [],
    }
    if core_report.get("status") == "meshed" and core_report.get("su2_path"):
        core_mesh = parse_su2_mesh(Path(str(core_report["su2_path"])))
        core_merge = add_core_mesh_to_mixed_builder(core_mesh=core_mesh, writer=writer)
        elements.extend(core_merge["elements"])
        markers["farfield"] = core_merge["farfield_marker_faces"]
    else:
        core_merge = {
            "elements": [],
            "farfield_marker_faces": [],
            "core_node_count": 0,
            "core_element_count": 0,
            "core_marker_names": [],
        }

    quality = evaluate_mixed_mesh_quality(nodes=writer.nodes, elements=elements)
    initial_boundary_audit = audit_volume_boundary_markers(
        elements=elements,
        markers=markers,
        nodes=writer.nodes,
    )
    wall_marker_recovery = recover_wall_closure_marker_faces(
        nodes=writer.nodes,
        elements=elements,
        markers=markers,
        candidate_vertices=candidate.vertices,
        candidate_face_records=_face_records(block, candidate),
        digits=merge_digits,
    )
    if wall_marker_recovery["recovered_face_count"]:
        markers["wing_wall"].extend(wall_marker_recovery["faces"])
    boundary_audit = audit_volume_boundary_markers(
        elements=elements,
        markers=markers,
        nodes=writer.nodes,
    )
    mesh_path = output_dir / "culled_global_star_mixed_handoff.su2"
    handoff_status = (
        "mixed_su2_handoff_written"
        if core_report.get("status") == "meshed"
        else "mixed_su2_handoff_core_mesh_missing"
    )
    write_su2_mesh(path=mesh_path, nodes=writer.nodes, elements=elements, markers=markers)
    handoff = {
        "schema_version": "wo006r25_mixed_su2_handoff.v1",
        "status": handoff_status,
        "mesh_path": str(mesh_path),
        "node_count": len(writer.nodes),
        "volume_element_count": len(elements),
        "volume_element_type_counts": dict(
            sorted(Counter(str(element["element_type"]) for element in elements).items())
        ),
        "marker_counts": {marker: len(faces) for marker, faces in sorted(markers.items())},
        "core_merge": _drop_heavy_elements(core_merge),
        "wall_marker_recovery": _drop_heavy_elements(wall_marker_recovery),
        "initial_volume_boundary_marker_audit": _drop_heavy_elements(initial_boundary_audit),
        "surface_ownership": {
            "wing_wall": "physical Baseline A wall faces from the owned near-wall BL candidate",
            "farfield": "R13 repaired-loop-cap core-mesh farfield box",
            "bl/core interface": (
                "internalized by coordinate-merging candidate global-star faces, "
                "loop-cap owner pyramids, and preserved core interface triangles"
            ),
        },
    }
    summary = build_probe_summary(
        output_dir=output_dir,
        geometry_source=str(geometry.section_table_path),
        handoff=handoff,
        boundary_audit=boundary_audit,
        quality=quality,
        yplus={
            **build_yplus_nearwall_summary(geometry),
            "status": "estimate_ready_not_solver_postprocessed",
        },
        core_report={
            "status": core_report.get("status"),
            "mesh_path": core_report.get("mesh_path"),
            "su2_path": core_report.get("su2_path"),
            "node_count": core_report.get("node_count"),
            "volume_element_count": core_report.get("volume_element_count"),
            "mesh_quality_gate": core_report.get("mesh_quality_gate"),
            "interface_conformality": core_report.get("interface_conformality"),
        },
        star_split=star_split,
        loop_cap=loop_cap,
    )
    summary["baseline_a_authority"] = {
        "source": "current GO Baseline A geometry via load_campaign_geometry",
        "points_per_side": int(points_per_side),
        "spanwise_subdivisions": int(spanwise_subdivisions),
        "bl_first_height_m": BL_FIRST_HEIGHT_M,
        "bl_growth_ratio": BL_GROWTH_RATIO,
        "bl_layers": BL_LAYERS,
        "coordinate_merge_digits": int(merge_digits),
    }
    summary["repair_basis"] = {
        "loop_cap_repair_status": repair.get("status"),
        "dropped_duplicate_face_count": repair.get("dropped_duplicate_face_count"),
        "hybrid_split_status": hybrid_audit.get("status"),
        "loop_cap_owner_status": loop_cap_audit.get("status"),
        "matched_loop_cap_triangles": loop_cap_audit.get(
            "matched_core_wall_loop_cap_triangle_count"
        ),
        "core_wall_loop_cap_triangle_count": loop_cap_audit.get(
            "core_wall_loop_cap_triangle_count"
        ),
    }
    summary["elapsed_s"] = time.monotonic() - start
    write_json(output_dir / "summary.json", summary)
    write_json(output_dir / "mixed_su2_handoff_report.json", handoff)
    (output_dir / "culled_mixed_su2_handoff_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    handoff = summary.get("mixed_su2_handoff") or {}
    boundary = summary.get("volume_boundary_marker_audit") or {}
    quality = summary.get("mixed_mesh_quality") or {}
    yplus = summary.get("near_wall_yplus") or {}
    yplus_estimate = yplus.get("current_go_first_layer_yplus_estimate") or {}
    return "\n".join(
        [
            "# WO-006R25 Culled Mixed SU2 Handoff Probe",
            "",
            "This is mesh-handoff setup evidence, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary.get('goal_status')}`",
            f"CFD_STATUS: `{summary.get('cfd_status')}`",
            f"- verdict: `{summary.get('verdict')}`",
            f"- mesh: `{handoff.get('mesh_path')}`",
            f"- nodes / volume elements: `{handoff.get('node_count')}` / `{handoff.get('volume_element_count')}`",
            f"- element types: `{handoff.get('volume_element_type_counts')}`",
            f"- marker counts: `{handoff.get('marker_counts')}`",
            f"- boundary marker audit: `{boundary.get('status')}`",
            f"- unmarked / extra marker faces: `{boundary.get('unmarked_boundary_face_count')}` / `{boundary.get('extra_marker_face_count')}`",
            f"- mixed quality: `{quality.get('status')}`",
            f"- non-positive volume elements: `{quality.get('non_positive_volume_count')}`",
            f"- first-layer y+ estimate for 5e-5 m: `{yplus_estimate.get('yplus_for_5e-5m')}`",
            f"- blockers: `{summary.get('blockers')}`",
            "",
            f"Engineering read: {summary.get('engineering_read')}",
            "",
        ]
    )


def _volume_element_faces(element_type: int, nodes: Sequence[int]) -> list[tuple[int, ...]]:
    if element_type == SU2_TETRA:
        a, b, c, d = nodes
        return [(a, b, c), (a, b, d), (a, c, d), (b, c, d)]
    if element_type == SU2_PYRAMID:
        a, b, c, d, e = nodes
        return [(a, b, c, d), (a, b, e), (b, c, e), (c, d, e), (d, a, e)]
    raise ValueError(f"Unsupported volume element type for face audit: {element_type}")


def _element_volume(
    nodes: Sequence[tuple[float, float, float]],
    element_type: int,
    element_nodes: Sequence[int],
) -> float:
    if element_type == SU2_TETRA:
        a, b, c, d = [nodes[int(node)] for node in element_nodes]
        return _tetra_volume_from_points(a, b, c, d)
    if element_type == SU2_PYRAMID:
        return _pyramid_volume_from_nodes(nodes, element_nodes)
    raise ValueError(f"Unsupported volume element type for quality audit: {element_type}")


def _surface_face_area(
    nodes: Sequence[tuple[float, float, float]],
    face: Sequence[int],
) -> float:
    face_nodes = tuple(int(node) for node in face)
    if len(face_nodes) == 3:
        return _triangle_area(*(nodes[node] for node in face_nodes))
    if len(face_nodes) == 4:
        a, b, c, d = [nodes[node] for node in face_nodes]
        return _triangle_area(a, b, c) + _triangle_area(a, c, d)
    return 0.0


def _pyramid_volume_from_nodes(
    nodes: Sequence[tuple[float, float, float]],
    element_nodes: Sequence[int],
) -> float:
    a, b, c, d, e = [nodes[int(node)] for node in element_nodes]
    return _tetra_volume_from_points(e, a, b, c) + _tetra_volume_from_points(e, a, c, d)


def _deterministic_quad_triangulation(nodes: Sequence[int]) -> list[tuple[int, ...]]:
    node_tuple = tuple(int(node) for node in nodes)
    if len(node_tuple) == 3:
        return [node_tuple]
    if len(node_tuple) != 4:
        raise ValueError("Only triangle or quad faces can be triangulated")
    diagonals = [
        tuple(sorted((node_tuple[0], node_tuple[2]))),
        tuple(sorted((node_tuple[1], node_tuple[3]))),
    ]
    selected = min(diagonals)
    if selected == tuple(sorted((node_tuple[0], node_tuple[2]))):
        return [
            (node_tuple[0], node_tuple[1], node_tuple[2]),
            (node_tuple[0], node_tuple[2], node_tuple[3]),
        ]
    return [
        (node_tuple[1], node_tuple[2], node_tuple[3]),
        (node_tuple[1], node_tuple[3], node_tuple[0]),
    ]


def _mean_point(
    vertices: Sequence[tuple[float, float, float]],
    nodes: Sequence[int],
) -> tuple[float, float, float]:
    count = float(len(nodes))
    return (
        sum(vertices[int(node)][0] for node in nodes) / count,
        sum(vertices[int(node)][1] for node in nodes) / count,
        sum(vertices[int(node)][2] for node in nodes) / count,
    )


def _tetra_volume_from_points(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
    d: tuple[float, float, float],
) -> float:
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    ad = (d[0] - a[0], d[1] - a[1], d[2] - a[2])
    cross = (
        ac[1] * ad[2] - ac[2] * ad[1],
        ac[2] * ad[0] - ac[0] * ad[2],
        ac[0] * ad[1] - ac[1] * ad[0],
    )
    return abs(ab[0] * cross[0] + ab[1] * cross[1] + ab[2] * cross[2]) / 6.0


def _triangle_area(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> float:
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    cross = (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )
    return 0.5 * (cross[0] ** 2 + cross[1] ** 2 + cross[2] ** 2) ** 0.5


def _face_node_key(nodes: Sequence[int]) -> tuple[int, ...]:
    return tuple(sorted(int(node) for node in nodes))


def _point_key(point: Sequence[float], *, digits: int) -> tuple[float, float, float]:
    return tuple(round(float(value), digits) for value in point)


def _point_polygon_key(
    points: Sequence[tuple[float, float, float]],
    *,
    digits: int,
) -> tuple[tuple[float, float, float], ...]:
    return tuple(sorted(_point_key(point, digits=digits) for point in points))


def _parse_nodes(raw: Any) -> tuple[int, ...]:
    if isinstance(raw, str):
        return tuple(int(part.strip()) for part in raw.strip("[]").split(",") if part.strip())
    return tuple(int(node) for node in raw)


def _drop_heavy_elements(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"elements", "boundary_marker_faces", "farfield_marker_faces", "faces"}
    }


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-clean", action="store_true")
    parser.add_argument("--points-per-side", type=int, default=16)
    parser.add_argument("--spanwise-subdivisions", type=int, default=2)
    parser.add_argument("--core-mesh-size", type=float, default=1.0)
    parser.add_argument("--farfield-mesh-size", type=float, default=8.0)
    parser.add_argument("--gmsh-threads", type=int, default=4)
    parser.add_argument("--merge-digits", type=int, default=10)
    args = parser.parse_args(argv)
    summary = run_probe(
        output_dir=args.output_dir,
        clean=not args.no_clean,
        points_per_side=args.points_per_side,
        spanwise_subdivisions=args.spanwise_subdivisions,
        core_mesh_size=args.core_mesh_size,
        farfield_mesh_size=args.farfield_mesh_size,
        gmsh_threads=args.gmsh_threads,
        merge_digits=args.merge_digits,
    )
    handoff = summary["mixed_su2_handoff"]
    boundary = summary["volume_boundary_marker_audit"]
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "mesh_path": handoff["mesh_path"],
                "node_count": handoff["node_count"],
                "volume_element_count": handoff["volume_element_count"],
                "marker_counts": handoff["marker_counts"],
                "boundary_marker_status": boundary["status"],
                "unmarked_boundary_faces": boundary["unmarked_boundary_face_count"],
                "extra_marker_faces": boundary["extra_marker_face_count"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
