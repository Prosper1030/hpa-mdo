from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from hpa_meshing.mesh_native.wing_surface import Station

from cfd_rescue.section_ogrid import build_section_ogrid, transform_section_point


Point3 = tuple[float, float, float]
BOUNDARY_PATCH_ORDER = (
    "wing_upper",
    "wing_lower",
    "tip_left",
    "tip_right",
    "te_wall",
    "closure_wall",
    "farfield",
)
HEX_FACE_NODE_ORDERS = (
    (0, 3, 2, 1),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
)


@dataclass(frozen=True)
class FaceRecord:
    nodes: tuple[int, ...]
    owner: int
    neighbour: int | None
    patch: str | None


@dataclass
class SweptHexaMesh:
    points: list[Point3]
    cells: list[tuple[int, int, int, int, int, int, int, int]]
    faces: list[tuple[int, ...]]
    owner: list[int]
    neighbour: list[int]
    boundary_ranges: dict[str, dict[str, int]]
    boundary_face_counts: dict[str, int]
    metadata: dict[str, Any]
    nonmanifold_face_count: int = 0
    unmarked_boundary_face_count: int = 0

    @property
    def point_count(self) -> int:
        return len(self.points)

    @property
    def cell_count(self) -> int:
        return len(self.cells)

    @property
    def face_count(self) -> int:
        return len(self.faces)

    @property
    def internal_face_count(self) -> int:
        return len(self.neighbour)


def build_swept_ogrid_mesh(
    stations: Sequence[Station],
    *,
    n_radial: int,
    first_layer_height_m: float,
    farfield_chords: float,
    case_id: str,
    near_wall_growth: float = 1.12,
) -> SweptHexaMesh:
    if len(stations) < 2:
        raise ValueError("at least two stations are required")
    n_perim = len(stations[0].airfoil_xz)
    if any(len(station.airfoil_xz) != n_perim for station in stations):
        raise ValueError("all stations must share the same airfoil point count")

    grids = [
        build_section_ogrid(
            station,
            first_layer_height_m=first_layer_height_m,
            n_radial=n_radial,
            farfield_chords=farfield_chords,
            near_wall_growth=near_wall_growth,
        )
        for station in stations
    ]

    points: list[Point3] = []
    for station, grid in zip(stations, grids):
        for radial in range(n_radial + 1):
            for perim in range(n_perim):
                points.append(transform_section_point(station, grid.points[radial][perim]))

    def node(section: int, radial: int, perim: int) -> int:
        return section * (n_radial + 1) * n_perim + radial * n_perim + (perim % n_perim)

    cells: list[tuple[int, int, int, int, int, int, int, int]] = []
    face_map: dict[tuple[int, ...], dict[str, Any]] = {}
    nonmanifold_face_count = 0
    orientation_flip_count = 0

    span_cells = len(stations) - 1
    for section in range(span_cells):
        for radial in range(n_radial):
            for perim in range(n_perim):
                inner = (
                    node(section, radial, perim),
                    node(section + 1, radial, perim),
                    node(section + 1, radial, perim + 1),
                    node(section, radial, perim + 1),
                )
                outer = (
                    node(section, radial + 1, perim),
                    node(section + 1, radial + 1, perim),
                    node(section + 1, radial + 1, perim + 1),
                    node(section, radial + 1, perim + 1),
                )
                base_cell = (*inner, *outer)
                patch_by_key: dict[tuple[int, ...], str] = {}
                if radial == 0:
                    patch_by_key[tuple(sorted(inner))] = grids[section].segment_markers[perim]
                if radial == n_radial - 1:
                    patch_by_key[tuple(sorted(outer))] = "farfield"
                if section == 0:
                    patch_by_key[
                        tuple(sorted((base_cell[3], base_cell[0], base_cell[4], base_cell[7])))
                    ] = "tip_left"
                if section == span_cells - 1:
                    patch_by_key[
                        tuple(sorted((base_cell[1], base_cell[2], base_cell[6], base_cell[5])))
                    ] = "tip_right"

                cell = _best_positive_hex_orientation(points, inner, outer)
                if cell != base_cell:
                    orientation_flip_count += 1
                cell_index = len(cells)
                cells.append(cell)
                for order in HEX_FACE_NODE_ORDERS:
                    face_nodes = tuple(cell[idx] for idx in order)
                    key = tuple(sorted(face_nodes))
                    patch = patch_by_key.get(key)
                    existing = face_map.get(key)
                    if existing is None:
                        face_map[key] = {
                            "nodes": face_nodes,
                            "owner": cell_index,
                            "neighbour": None,
                            "patch": patch,
                            "count": 1,
                        }
                        continue
                    existing["count"] = int(existing["count"]) + 1
                    if existing["neighbour"] is None:
                        existing["neighbour"] = cell_index
                        existing["patch"] = None
                    else:
                        nonmanifold_face_count += 1

    records = [
        FaceRecord(
            nodes=tuple(payload["nodes"]),
            owner=int(payload["owner"]),
            neighbour=None
            if payload["neighbour"] is None
            else int(payload["neighbour"]),
            patch=None if payload["patch"] is None else str(payload["patch"]),
        )
        for payload in face_map.values()
    ]
    internal = [record for record in records if record.neighbour is not None]
    boundary_by_patch: dict[str, list[FaceRecord]] = {
        patch: [] for patch in BOUNDARY_PATCH_ORDER
    }
    unmarked_boundary_face_count = 0
    for record in records:
        if record.neighbour is not None:
            continue
        if record.patch not in boundary_by_patch:
            unmarked_boundary_face_count += 1
            continue
        boundary_by_patch[str(record.patch)].append(record)

    faces: list[tuple[int, ...]] = []
    owner: list[int] = []
    neighbour: list[int] = []
    boundary_ranges: dict[str, dict[str, int]] = {}
    for record in internal:
        faces.append(record.nodes)
        owner.append(record.owner)
        assert record.neighbour is not None
        neighbour.append(record.neighbour)
    for patch in BOUNDARY_PATCH_ORDER:
        start = len(faces)
        for record in boundary_by_patch[patch]:
            faces.append(record.nodes)
            owner.append(record.owner)
        boundary_ranges[patch] = {
            "startFace": start,
            "nFaces": len(boundary_by_patch[patch]),
        }

    return SweptHexaMesh(
        points=points,
        cells=cells,
        faces=faces,
        owner=owner,
        neighbour=neighbour,
        boundary_ranges=boundary_ranges,
        boundary_face_counts={
            patch: boundary_ranges[patch]["nFaces"] for patch in BOUNDARY_PATCH_ORDER
        },
        metadata={
            "schema_version": "wo006_swept_section_ogrid_structured_hexa.v1",
            "case_id": case_id,
            "station_count": len(stations),
            "span_cells": span_cells,
            "n_perim": n_perim,
            "n_radial": n_radial,
            "first_layer_height_m": first_layer_height_m,
            "farfield_chords": farfield_chords,
            "near_wall_growth": near_wall_growth,
            "orientation_flip_count": orientation_flip_count,
            "station_wise_grid": "2d_ogrid_swept_bay_by_bay",
        },
        nonmanifold_face_count=nonmanifold_face_count,
        unmarked_boundary_face_count=unmarked_boundary_face_count,
    )


def mesh_quality_summary(mesh: SweptHexaMesh) -> dict[str, Any]:
    volumes: list[float] = []
    aspect_ratios: list[float] = []
    non_positive = 0
    for cell in mesh.cells:
        volume = _hex_signed_volume(mesh.points, cell)
        volumes.append(volume)
        if volume <= 0.0 or not math.isfinite(volume):
            non_positive += 1
        aspect_ratios.append(_hex_aspect_ratio_proxy(mesh.points, cell))
    duplicate_points = _duplicate_point_count(mesh.points)
    blockers = []
    if non_positive:
        blockers.append("non_positive_hex_volume")
    if duplicate_points:
        blockers.append("duplicate_points")
    if mesh.nonmanifold_face_count:
        blockers.append("nonmanifold_faces")
    if mesh.unmarked_boundary_face_count:
        blockers.append("unmarked_boundary_faces")
    if len(mesh.owner) != len(mesh.faces):
        blockers.append("owner_face_count_mismatch")
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "node_count": mesh.point_count,
        "cell_count": mesh.cell_count,
        "face_count": mesh.face_count,
        "internal_face_count": mesh.internal_face_count,
        "boundary_face_counts": mesh.boundary_face_counts,
        "non_positive_volume_count": non_positive,
        "duplicate_point_count": duplicate_points,
        "nonmanifold_face_count": mesh.nonmanifold_face_count,
        "unmarked_boundary_face_count": mesh.unmarked_boundary_face_count,
        "min_signed_volume": min(volumes, default=None),
        "max_signed_volume": max(volumes, default=None),
        "aspect_ratio_proxy": _percentiles(aspect_ratios),
        "volume": _percentiles(volumes),
    }


def write_openfoam_poly_mesh(poly_mesh_dir: Path, mesh: SweptHexaMesh) -> None:
    poly_mesh_dir.mkdir(parents=True, exist_ok=True)
    _write_openfoam_points(poly_mesh_dir / "points", mesh.points)
    _write_openfoam_faces(poly_mesh_dir / "faces", mesh.faces)
    _write_openfoam_label_list(poly_mesh_dir / "owner", "owner", mesh.owner)
    _write_openfoam_label_list(poly_mesh_dir / "neighbour", "neighbour", mesh.neighbour)
    _write_openfoam_boundary(poly_mesh_dir / "boundary", mesh.boundary_ranges)


def _write_openfoam_points(path: Path, points: Sequence[Point3]) -> None:
    lines = [_foam_header("vectorField", "points"), str(len(points)), "("]
    lines.extend(f"({x:.12g} {y:.12g} {z:.12g})" for x, y, z in points)
    lines.extend([")", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_openfoam_faces(path: Path, faces: Sequence[Sequence[int]]) -> None:
    lines = [_foam_header("faceList", "faces"), str(len(faces)), "("]
    for face in faces:
        lines.append(f"{len(face)}(" + " ".join(str(node) for node in face) + ")")
    lines.extend([")", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_openfoam_label_list(path: Path, object_name: str, values: Sequence[int]) -> None:
    lines = [_foam_header("labelList", object_name), str(len(values)), "("]
    lines.extend(str(value) for value in values)
    lines.extend([")", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_openfoam_boundary(
    path: Path,
    boundary_ranges: Mapping[str, Mapping[str, int]],
) -> None:
    lines = [_foam_header("polyBoundaryMesh", "boundary"), str(len(BOUNDARY_PATCH_ORDER)), "("]
    for patch in BOUNDARY_PATCH_ORDER:
        payload = boundary_ranges[patch]
        patch_type = "patch" if patch == "farfield" else "wall"
        lines.extend(
            [
                f"    {patch}",
                "    {",
                f"        type            {patch_type};",
                f"        nFaces          {int(payload['nFaces'])};",
                f"        startFace       {int(payload['startFace'])};",
                "    }",
            ]
        )
    lines.extend([")", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _foam_header(class_name: str, object_name: str) -> str:
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       {class_name};
    location    "constant/polyMesh";
    object      {object_name};
}}"""


def _best_positive_hex_orientation(
    points: Sequence[Point3],
    inner: Sequence[int],
    outer: Sequence[int],
) -> tuple[int, int, int, int, int, int, int, int]:
    candidates = []
    base_orders = (
        (0, 1, 2, 3),
        (1, 2, 3, 0),
        (2, 3, 0, 1),
        (3, 0, 1, 2),
        (0, 3, 2, 1),
        (3, 2, 1, 0),
        (2, 1, 0, 3),
        (1, 0, 3, 2),
    )
    for order in base_orders:
        candidates.append(
            tuple(inner[idx] for idx in order) + tuple(outer[idx] for idx in order)
        )
    return max(candidates, key=lambda cell: _hex_signed_volume(points, cell))


def _hex_signed_volume(points: Sequence[Point3], cell: Sequence[int]) -> float:
    volume = 0.0
    for order in HEX_FACE_NODE_ORDERS:
        face_nodes = [cell[index] for index in order]
        tris = (
            (face_nodes[0], face_nodes[1], face_nodes[2]),
            (face_nodes[0], face_nodes[2], face_nodes[3]),
        )
        for a, b, c in tris:
            volume += _tetra_signed_volume(points[a], points[b], points[c])
    return volume


def _tetra_signed_volume(a: Point3, b: Point3, c: Point3) -> float:
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    ) / 6.0


def _hex_aspect_ratio_proxy(points: Sequence[Point3], cell: Sequence[int]) -> float:
    edges = (
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    )
    lengths = [_distance(points[cell[a]], points[cell[b]]) for a, b in edges]
    shortest = min(lengths)
    longest = max(lengths)
    return math.inf if shortest <= 0.0 else longest / shortest


def _duplicate_point_count(points: Sequence[Point3], precision: int = 12) -> int:
    seen: set[tuple[float, float, float]] = set()
    duplicates = 0
    for point in points:
        key = tuple(round(component, precision) for component in point)
        if key in seen:
            duplicates += 1
        seen.add(key)
    return duplicates


def _distance(left: Point3, right: Point3) -> float:
    return math.sqrt(
        (right[0] - left[0]) ** 2
        + (right[1] - left[1]) ** 2
        + (right[2] - left[2]) ** 2
    )


def _percentiles(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "p50": None, "p95": None, "max": None}
    ordered = sorted(values)

    def pct(q: float) -> float:
        index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
        return ordered[index]

    return {
        "min": ordered[0],
        "p50": pct(0.50),
        "p95": pct(0.95),
        "max": ordered[-1],
    }
