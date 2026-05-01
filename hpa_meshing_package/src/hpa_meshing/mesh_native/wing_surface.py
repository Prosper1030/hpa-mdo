from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

import yaml


TERule = Literal["sharp", "finite_thickness", "blunt"]
TipRule = Literal["planar_cap", "rounded_cap", "pinched"]
RootRule = Literal["full", "symmetry", "wall_cap"]
SideRule = Literal["full", "half"]
Vertex = tuple[float, float, float]
DEFAULT_ALLOWED_MARKERS = frozenset(
    {
        "wing_wall",
        "farfield",
        "symmetry",
        "root_wall",
        "wake_refinement_region",
        "tip_refinement_region",
    }
)


@dataclass(frozen=True)
class Station:
    y: float
    airfoil_xz: list[tuple[float, float]]
    chord: float
    twist_deg: float
    x_le: float = 0.0
    z_le: float = 0.0


@dataclass(frozen=True)
class Reference:
    sref_full: float
    cref: float
    bref_full: float


@dataclass(frozen=True)
class WingSpec:
    stations: list[Station]
    side: SideRule
    te_rule: TERule
    tip_rule: TipRule
    root_rule: RootRule
    reference: Reference
    twist_axis_x: float = 0.25


@dataclass(frozen=True)
class Face:
    nodes: tuple[int, ...]
    marker: str


@dataclass
class SurfaceMesh:
    vertices: list[Vertex]
    faces: list[Face]
    metadata: dict[str, float | int | str] = field(default_factory=dict)

    def marker_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for face in self.faces:
            counts[face.marker] = counts.get(face.marker, 0) + 1
        return counts

    def bounds(self) -> dict[str, float]:
        return _bounds(self.vertices)


def build_wing_surface(spec: WingSpec) -> SurfaceMesh:
    stations = _ordered_stations(spec)
    points_per_station = len(stations[0].airfoil_xz)
    vertices: list[Vertex] = []

    for station in stations:
        if len(station.airfoil_xz) != points_per_station:
            raise ValueError("All station loops must have the same point count")
        vertices.extend(_transform_station(station, spec.twist_axis_x))

    faces: list[Face] = []

    def vid(section: int, point: int) -> int:
        return section * points_per_station + (point % points_per_station)

    for section in range(len(stations) - 1):
        for point in range(points_per_station):
            next_point = (point + 1) % points_per_station
            faces.append(
                Face(
                    nodes=(
                        vid(section, point),
                        vid(section + 1, point),
                        vid(section + 1, next_point),
                        vid(section, next_point),
                    ),
                    marker="wing_wall",
                )
            )

    _append_section_cap(
        vertices,
        faces,
        [vid(0, point) for point in range(points_per_station)],
        marker="wing_wall",
        reverse=True,
    )
    _append_section_cap(
        vertices,
        faces,
        [vid(len(stations) - 1, point) for point in range(points_per_station)],
        marker="wing_wall",
        reverse=False,
    )

    mesh = SurfaceMesh(
        vertices=vertices,
        faces=faces,
        metadata={
            "station_count": len(stations),
            "points_per_station": points_per_station,
            "span_m": stations[-1].y - stations[0].y,
            "planform_area_m2": _planform_area(stations),
            "side": spec.side,
            "te_rule": spec.te_rule,
            "tip_rule": spec.tip_rule,
            "root_rule": spec.root_rule,
        },
    )
    validate_surface_mesh(mesh)
    return mesh


def build_farfield_box_surface(
    body: SurfaceMesh,
    *,
    upstream_factor: float = 5.0,
    downstream_factor: float = 12.0,
    lateral_factor: float = 8.0,
    vertical_factor: float = 8.0,
    marker: str = "farfield",
) -> SurfaceMesh:
    body_bounds = body.bounds()
    x_span = max(body_bounds["x_max"] - body_bounds["x_min"], 1.0e-9)
    y_span = max(body_bounds["y_max"] - body_bounds["y_min"], 1.0e-9)
    z_span = max(body_bounds["z_max"] - body_bounds["z_min"], 1.0e-9)
    z_reference = max(x_span, y_span, z_span)

    x_min = body_bounds["x_min"] - upstream_factor * x_span
    x_max = body_bounds["x_max"] + downstream_factor * x_span
    y_min = body_bounds["y_min"] - lateral_factor * y_span
    y_max = body_bounds["y_max"] + lateral_factor * y_span
    z_min = body_bounds["z_min"] - vertical_factor * z_reference
    z_max = body_bounds["z_max"] + vertical_factor * z_reference

    vertices: list[Vertex] = [
        (x_min, y_min, z_min),
        (x_max, y_min, z_min),
        (x_max, y_max, z_min),
        (x_min, y_max, z_min),
        (x_min, y_min, z_max),
        (x_max, y_min, z_max),
        (x_max, y_max, z_max),
        (x_min, y_max, z_max),
    ]
    faces = [
        Face(nodes=(0, 3, 2, 1), marker=marker),
        Face(nodes=(4, 5, 6, 7), marker=marker),
        Face(nodes=(0, 1, 5, 4), marker=marker),
        Face(nodes=(1, 2, 6, 5), marker=marker),
        Face(nodes=(2, 3, 7, 6), marker=marker),
        Face(nodes=(3, 0, 4, 7), marker=marker),
    ]
    mesh = SurfaceMesh(
        vertices=vertices,
        faces=faces,
        metadata={
            "surface_role": "farfield_box",
            "x_min": x_min,
            "x_max": x_max,
            "y_min": y_min,
            "y_max": y_max,
            "z_min": z_min,
            "z_max": z_max,
        },
    )
    validate_surface_mesh(mesh, required_markers=(marker,))
    return mesh


def merge_surface_meshes(meshes: Sequence[SurfaceMesh]) -> SurfaceMesh:
    vertices: list[Vertex] = []
    faces: list[Face] = []
    marker_counts: dict[str, int] = {}

    for mesh in meshes:
        offset = len(vertices)
        vertices.extend(mesh.vertices)
        for face in mesh.faces:
            faces.append(
                Face(
                    nodes=tuple(node + offset for node in face.nodes),
                    marker=face.marker,
                )
            )
            marker_counts[face.marker] = marker_counts.get(face.marker, 0) + 1

    merged = SurfaceMesh(
        vertices=vertices,
        faces=faces,
        metadata={
            "surface_role": "merged_boundary_shells",
            "source_mesh_count": len(meshes),
            **_bounds(vertices),
        },
    )
    validate_surface_mesh(merged, required_markers=tuple(sorted(marker_counts)))
    return merged


def load_wing_spec(path: Path | str) -> WingSpec:
    spec_path = Path(path)
    if spec_path.suffix.lower() == ".json":
        payload = json.loads(spec_path.read_text(encoding="utf-8"))
    elif spec_path.suffix.lower() in {".yaml", ".yml"}:
        payload = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"Unsupported mesh-native wing spec suffix: {spec_path.suffix}")
    if not isinstance(payload, Mapping):
        raise ValueError("Mesh-native wing spec must contain a mapping")
    return wing_spec_from_mapping(payload)


def wing_spec_from_mapping(payload: Mapping[str, Any]) -> WingSpec:
    units = payload.get("units")
    if units != "m":
        raise ValueError("Mesh-native wing spec units must be m")

    reference_payload = _required_mapping(payload, "reference")
    stations_payload = payload.get("stations")
    if not isinstance(stations_payload, list):
        raise ValueError("Mesh-native wing spec stations must be a list")

    stations = [
        Station(
            y=_required_float(station_payload, "y"),
            airfoil_xz=_required_airfoil_xz(station_payload),
            chord=_required_float(station_payload, "chord"),
            twist_deg=_required_float(station_payload, "twist_deg"),
            x_le=float(station_payload.get("x_le", 0.0)),
            z_le=float(station_payload.get("z_le", 0.0)),
        )
        for station_payload in stations_payload
        if isinstance(station_payload, Mapping)
    ]
    if len(stations) != len(stations_payload):
        raise ValueError("Every station must be a mapping")

    return WingSpec(
        stations=stations,
        side=_literal_value(payload, "side", {"full", "half"}),
        te_rule=_literal_value(payload, "te_rule", {"sharp", "finite_thickness", "blunt"}),
        tip_rule=_literal_value(payload, "tip_rule", {"planar_cap", "rounded_cap", "pinched"}),
        root_rule=_literal_value(payload, "root_rule", {"full", "symmetry", "wall_cap"}),
        reference=Reference(
            sref_full=_required_float(reference_payload, "sref_full"),
            cref=_required_float(reference_payload, "cref"),
            bref_full=_required_float(reference_payload, "bref_full"),
        ),
        twist_axis_x=float(payload.get("twist_axis_x", 0.25)),
    )


def _ordered_stations(spec: WingSpec) -> list[Station]:
    if len(spec.stations) < 2:
        raise ValueError("At least two stations are required")
    if any(station.chord <= 0.0 for station in spec.stations):
        raise ValueError("Station chord must be positive")
    if not spec.stations[0].airfoil_xz:
        raise ValueError("Station airfoil loop must not be empty")
    for left, right in zip(spec.stations[:-1], spec.stations[1:]):
        if right.y <= left.y:
            raise ValueError("Station y values must be strictly increasing")
    return list(spec.stations)


def _bounds(vertices: Sequence[Vertex]) -> dict[str, float]:
    if not vertices:
        raise ValueError("Cannot compute bounds for an empty vertex list")
    return {
        "x_min": min(vertex[0] for vertex in vertices),
        "x_max": max(vertex[0] for vertex in vertices),
        "y_min": min(vertex[1] for vertex in vertices),
        "y_max": max(vertex[1] for vertex in vertices),
        "z_min": min(vertex[2] for vertex in vertices),
        "z_max": max(vertex[2] for vertex in vertices),
    }


def _required_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"Mesh-native wing spec field must be a mapping: {key}")
    return value


def _required_float(payload: Mapping[str, Any], key: str) -> float:
    value = payload.get(key)
    if not isinstance(value, (int, float)):
        raise ValueError(f"Mesh-native wing spec field must be numeric: {key}")
    return float(value)


def _required_airfoil_xz(payload: Mapping[str, Any]) -> list[tuple[float, float]]:
    value = payload.get("airfoil_xz")
    if not isinstance(value, list):
        raise ValueError("Mesh-native wing spec airfoil_xz must be a list")
    points: list[tuple[float, float]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("Each airfoil_xz point must have two coordinates")
        x, z = item
        if not isinstance(x, (int, float)) or not isinstance(z, (int, float)):
            raise ValueError("Each airfoil_xz coordinate must be numeric")
        points.append((float(x), float(z)))
    return points


def _literal_value(payload: Mapping[str, Any], key: str, allowed: set[str]) -> Any:
    value = payload.get(key)
    if value not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ValueError(f"Mesh-native wing spec {key} must be one of: {allowed_values}")
    return value


def validate_surface_mesh(
    mesh: SurfaceMesh,
    *,
    allowed_markers: frozenset[str] = DEFAULT_ALLOWED_MARKERS,
    required_markers: Sequence[str] = ("wing_wall",),
    area_tolerance: float = 1.0e-14,
) -> None:
    if not mesh.vertices:
        raise ValueError("Surface mesh has no vertices")
    if not mesh.faces:
        raise ValueError("Surface mesh has no faces")
    for vertex in mesh.vertices:
        if len(vertex) != 3 or not all(math.isfinite(value) for value in vertex):
            raise ValueError(f"Invalid vertex coordinates: {vertex}")

    edge_counts: dict[tuple[int, int], int] = {}
    marker_counts: dict[str, int] = {}
    max_node = len(mesh.vertices) - 1

    for face in mesh.faces:
        if face.marker not in allowed_markers:
            raise ValueError(f"Unknown marker: {face.marker}")
        if len(face.nodes) not in (3, 4):
            raise ValueError("Only triangle and quad faces are supported")
        if any(node < 0 or node > max_node for node in face.nodes):
            raise ValueError(f"Face references node outside vertex array: {face.nodes}")

        marker_counts[face.marker] = marker_counts.get(face.marker, 0) + 1
        area = _face_area([mesh.vertices[node] for node in face.nodes])
        if area <= area_tolerance:
            raise ValueError(f"Zero or tiny face area: {area}")

        for left, right in zip(face.nodes, face.nodes[1:] + face.nodes[:1]):
            edge = tuple(sorted((left, right)))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1

    for marker in required_markers:
        if marker_counts.get(marker, 0) == 0:
            raise ValueError(f"Required marker missing: {marker}")

    bad_edges = {edge: count for edge, count in edge_counts.items() if count != 2}
    if bad_edges:
        raise ValueError(f"Non-watertight surface: {len(bad_edges)} bad edges")


def _transform_station(station: Station, twist_axis_x: float) -> list[Vertex]:
    theta = math.radians(station.twist_deg)
    cos_theta = math.cos(theta)
    sin_theta = math.sin(theta)
    twist_axis = station.chord * twist_axis_x
    transformed: list[Vertex] = []

    for x_norm, z_norm in station.airfoil_xz:
        x = station.chord * x_norm
        z = station.chord * z_norm
        x_rot = twist_axis + cos_theta * (x - twist_axis) + sin_theta * z
        z_rot = -sin_theta * (x - twist_axis) + cos_theta * z
        transformed.append((station.x_le + x_rot, station.y, station.z_le + z_rot))

    return transformed


def _append_section_cap(
    vertices: list[Vertex],
    faces: list[Face],
    boundary: list[int],
    *,
    marker: str,
    reverse: bool,
) -> None:
    center = _centroid([vertices[node] for node in boundary])
    center_index = len(vertices)
    vertices.append(center)

    for index, node in enumerate(boundary):
        next_node = boundary[(index + 1) % len(boundary)]
        tri = (center_index, next_node, node) if reverse else (center_index, node, next_node)
        faces.append(Face(nodes=tri, marker=marker))


def _centroid(points: list[Vertex]) -> Vertex:
    scale = 1.0 / len(points)
    return (
        sum(point[0] for point in points) * scale,
        sum(point[1] for point in points) * scale,
        sum(point[2] for point in points) * scale,
    )


def _face_area(points: list[Vertex]) -> float:
    if len(points) == 3:
        return _triangle_area(points[0], points[1], points[2])
    if len(points) == 4:
        return _triangle_area(points[0], points[1], points[2]) + _triangle_area(
            points[0],
            points[2],
            points[3],
        )
    raise ValueError("Only triangle and quad faces are supported")


def _triangle_area(a: Vertex, b: Vertex, c: Vertex) -> float:
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    cross = (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )
    return 0.5 * math.sqrt(
        cross[0] * cross[0] + cross[1] * cross[1] + cross[2] * cross[2]
    )


def _planform_area(stations: list[Station]) -> float:
    area = 0.0
    for left, right in zip(stations[:-1], stations[1:]):
        area += (right.y - left.y) * 0.5 * (left.chord + right.chord)
    return area
