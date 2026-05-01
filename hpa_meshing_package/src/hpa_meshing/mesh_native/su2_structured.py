from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Literal

from .wing_surface import SurfaceMesh, Vertex

SU2_QUAD = 9
SU2_HEXAHEDRON = 12
_AXES = ("x", "y", "z")


def write_structured_box_shell_su2(
    wing: SurfaceMesh,
    farfield: SurfaceMesh,
    out_path: Path | str,
    *,
    wall_marker: str = "wing_wall",
    farfield_marker: str = "farfield",
) -> dict[str, Any]:
    """Write a tiny mesh-native SU2 smoke mesh around the wing bounding box.

    This is deliberately a topology/marker/SU2-parser smoke mesh: the actual
    wing surface is represented by its bounding box, so aerodynamic coefficients
    from this mesh are not physically meaningful.
    """
    out_path = Path(out_path)
    volume = _structured_box_shell_volume(
        wing,
        farfield,
        wall_marker=wall_marker,
        farfield_marker=farfield_marker,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_su2_text(volume), encoding="utf-8")
    return _report(volume)


def parse_su2_marker_summary(path: Path | str) -> dict[str, Any]:
    lines = [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    ndime = _header_int(lines, "NDIME")
    nelem = _header_int(lines, "NELEM")
    npoin = _header_int(lines, "NPOIN")
    nmark = _header_int(lines, "NMARK")

    markers: dict[str, dict[str, Any]] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("MARKER_TAG="):
            index += 1
            continue
        marker = line.split("=", 1)[1].strip()
        elem_count = int(lines[index + 1].split("=", 1)[1].strip())
        type_counts: dict[str, int] = {}
        for elem_line in lines[index + 2 : index + 2 + elem_count]:
            elem_type = elem_line.split()[0]
            type_counts[elem_type] = type_counts.get(elem_type, 0) + 1
        markers[marker] = {
            "element_count": elem_count,
            "element_type_counts": dict(sorted(type_counts.items())),
        }
        index += 2 + elem_count

    return {
        "ndime": ndime,
        "nelem": nelem,
        "npoin": npoin,
        "nmark": nmark,
        "markers": markers,
    }


def _header_int(lines: Iterable[str], key: str) -> int:
    prefix = f"{key}="
    for line in lines:
        if line.startswith(prefix):
            return int(line.split("=", 1)[1].strip())
    raise ValueError(f"SU2 header missing: {key}")


def _structured_box_shell_volume(
    wing: SurfaceMesh,
    farfield: SurfaceMesh,
    *,
    wall_marker: str,
    farfield_marker: str,
) -> dict[str, Any]:
    wing_bounds = wing.bounds()
    farfield_bounds = farfield.bounds()
    axes = {
        axis: _axis_values(wing_bounds, farfield_bounds, axis)
        for axis in _AXES
    }
    nodes = _nodes(axes)
    elements: list[tuple[int, tuple[int, ...]]] = []
    marker_faces: dict[str, list[tuple[int, tuple[int, ...]]]] = {
        farfield_marker: [],
        wall_marker: [],
    }
    excluded = (1, 1, 1)

    for i in range(3):
        for j in range(3):
            for k in range(3):
                cell = (i, j, k)
                if cell == excluded:
                    continue
                elements.append((SU2_HEXAHEDRON, _hex_nodes(i, j, k)))
                for direction in _cell_faces(i, j, k):
                    neighbor = (
                        i + direction["delta"][0],
                        j + direction["delta"][1],
                        k + direction["delta"][2],
                    )
                    if _outside_grid(neighbor):
                        marker_faces[farfield_marker].append((SU2_QUAD, direction["nodes"]))
                    elif neighbor == excluded:
                        marker_faces[wall_marker].append((SU2_QUAD, direction["nodes"]))

    return {
        "nodes": nodes,
        "elements": elements,
        "marker_faces": marker_faces,
        "wing_bounds": wing_bounds,
        "farfield_bounds": farfield_bounds,
    }


def _axis_values(
    wing_bounds: dict[str, float],
    farfield_bounds: dict[str, float],
    axis: Literal["x", "y", "z"],
) -> list[float]:
    values = [
        farfield_bounds[f"{axis}_min"],
        wing_bounds[f"{axis}_min"],
        wing_bounds[f"{axis}_max"],
        farfield_bounds[f"{axis}_max"],
    ]
    if not values[0] < values[1] < values[2] < values[3]:
        raise ValueError("Farfield bounds must strictly enclose wing bounds")
    return values


def _node_id(i: int, j: int, k: int) -> int:
    return i * 16 + j * 4 + k


def _nodes(axes: dict[str, list[float]]) -> list[Vertex]:
    nodes: list[Vertex] = []
    for i in range(4):
        for j in range(4):
            for k in range(4):
                nodes.append((axes["x"][i], axes["y"][j], axes["z"][k]))
    return nodes


def _hex_nodes(i: int, j: int, k: int) -> tuple[int, ...]:
    return (
        _node_id(i, j, k),
        _node_id(i + 1, j, k),
        _node_id(i + 1, j + 1, k),
        _node_id(i, j + 1, k),
        _node_id(i, j, k + 1),
        _node_id(i + 1, j, k + 1),
        _node_id(i + 1, j + 1, k + 1),
        _node_id(i, j + 1, k + 1),
    )


def _cell_faces(i: int, j: int, k: int) -> list[dict[str, Any]]:
    return [
        {
            "delta": (-1, 0, 0),
            "nodes": (
                _node_id(i, j, k),
                _node_id(i, j + 1, k),
                _node_id(i, j + 1, k + 1),
                _node_id(i, j, k + 1),
            ),
        },
        {
            "delta": (1, 0, 0),
            "nodes": (
                _node_id(i + 1, j, k),
                _node_id(i + 1, j, k + 1),
                _node_id(i + 1, j + 1, k + 1),
                _node_id(i + 1, j + 1, k),
            ),
        },
        {
            "delta": (0, -1, 0),
            "nodes": (
                _node_id(i, j, k),
                _node_id(i, j, k + 1),
                _node_id(i + 1, j, k + 1),
                _node_id(i + 1, j, k),
            ),
        },
        {
            "delta": (0, 1, 0),
            "nodes": (
                _node_id(i, j + 1, k),
                _node_id(i + 1, j + 1, k),
                _node_id(i + 1, j + 1, k + 1),
                _node_id(i, j + 1, k + 1),
            ),
        },
        {
            "delta": (0, 0, -1),
            "nodes": (
                _node_id(i, j, k),
                _node_id(i + 1, j, k),
                _node_id(i + 1, j + 1, k),
                _node_id(i, j + 1, k),
            ),
        },
        {
            "delta": (0, 0, 1),
            "nodes": (
                _node_id(i, j, k + 1),
                _node_id(i, j + 1, k + 1),
                _node_id(i + 1, j + 1, k + 1),
                _node_id(i + 1, j, k + 1),
            ),
        },
    ]


def _outside_grid(cell: tuple[int, int, int]) -> bool:
    return any(index < 0 or index > 2 for index in cell)


def _su2_text(volume: dict[str, Any]) -> str:
    lines = [
        "% Mesh-native structured box-shell smoke mesh.",
        "% The inner wing_wall marker is the wing bounding box, not the true wing surface.",
        "NDIME= 3",
        f"NELEM= {len(volume['elements'])}",
    ]
    for elem_id, (elem_type, nodes) in enumerate(volume["elements"]):
        lines.append(f"{elem_type} {' '.join(str(node) for node in nodes)} {elem_id}")

    lines.append(f"NPOIN= {len(volume['nodes'])}")
    for node_id, (x, y, z) in enumerate(volume["nodes"]):
        lines.append(f"{x:.16g} {y:.16g} {z:.16g} {node_id}")

    marker_faces = volume["marker_faces"]
    lines.append(f"NMARK= {len(marker_faces)}")
    for marker in sorted(marker_faces):
        faces = marker_faces[marker]
        lines.append(f"MARKER_TAG= {marker}")
        lines.append(f"MARKER_ELEMS= {len(faces)}")
        for elem_type, nodes in faces:
            lines.append(f"{elem_type} {' '.join(str(node) for node in nodes)}")
    lines.append("")
    return "\n".join(lines)


def _report(volume: dict[str, Any]) -> dict[str, Any]:
    return {
        "route": "mesh_native_structured_box_shell_smoke",
        "node_count": len(volume["nodes"]),
        "volume_element_count": len(volume["elements"]),
        "marker_summary": _marker_summary(volume["marker_faces"]),
        "wing_bounds": volume["wing_bounds"],
        "farfield_bounds": volume["farfield_bounds"],
        "caveats": [
            "wing boundary is represented by the wing bounding box for SU2 smoke only",
            "not valid for aerodynamic coefficient interpretation",
        ],
    }


def _marker_summary(marker_faces: dict[str, list[tuple[int, tuple[int, ...]]]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for marker in sorted(marker_faces):
        type_counts: dict[str, int] = {}
        for elem_type, _nodes_for_face in marker_faces[marker]:
            key = str(elem_type)
            type_counts[key] = type_counts.get(key, 0) + 1
        summary[marker] = {
            "element_count": len(marker_faces[marker]),
            "element_type_counts": dict(sorted(type_counts.items())),
        }
    return summary
