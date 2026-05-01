from __future__ import annotations

from dataclasses import dataclass

from .wing_surface import SurfaceMesh


@dataclass(frozen=True)
class SurfacePatch:
    marker: str
    node_tags: tuple[int, ...]
    triangle_connectivity: tuple[tuple[int, int, int], ...]
    quad_connectivity: tuple[tuple[int, int, int, int], ...]
    bounds: dict[str, float]

    @property
    def triangle_count(self) -> int:
        return len(self.triangle_connectivity)

    @property
    def quad_count(self) -> int:
        return len(self.quad_connectivity)

    @property
    def element_count(self) -> int:
        return self.triangle_count + self.quad_count


def surface_patches_by_marker(mesh: SurfaceMesh) -> list[SurfacePatch]:
    faces_by_marker: dict[str, list[tuple[int, ...]]] = {}
    for face in mesh.faces:
        faces_by_marker.setdefault(face.marker, []).append(face.nodes)

    patches: list[SurfacePatch] = []
    for marker in sorted(faces_by_marker):
        faces = faces_by_marker[marker]
        node_indices = sorted({node for face in faces for node in face})
        triangles = tuple(
            tuple(node + 1 for node in face)
            for face in faces
            if len(face) == 3
        )
        quads = tuple(
            tuple(node + 1 for node in face)
            for face in faces
            if len(face) == 4
        )
        patches.append(
            SurfacePatch(
                marker=marker,
                node_tags=tuple(node + 1 for node in node_indices),
                triangle_connectivity=triangles,
                quad_connectivity=quads,
                bounds=_patch_bounds(mesh, node_indices),
            )
        )
    return patches


def marker_summary(mesh: SurfaceMesh) -> dict[str, dict[str, object]]:
    summary: dict[str, dict[str, object]] = {}
    for patch in surface_patches_by_marker(mesh):
        summary[patch.marker] = {
            "exists": True,
            "element_count": patch.element_count,
            "triangle_count": patch.triangle_count,
            "quad_count": patch.quad_count,
            "node_count": len(patch.node_tags),
            "bounds": patch.bounds,
        }
    return summary


def _patch_bounds(mesh: SurfaceMesh, node_indices: list[int]) -> dict[str, float]:
    vertices = [mesh.vertices[node] for node in node_indices]
    return {
        "x_min": min(vertex[0] for vertex in vertices),
        "x_max": max(vertex[0] for vertex in vertices),
        "y_min": min(vertex[1] for vertex in vertices),
        "y_max": max(vertex[1] for vertex in vertices),
        "z_min": min(vertex[2] for vertex in vertices),
        "z_max": max(vertex[2] for vertex in vertices),
    }
