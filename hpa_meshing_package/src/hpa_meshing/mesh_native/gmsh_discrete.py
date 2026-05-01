from __future__ import annotations

from pathlib import Path
from typing import Any

from .patches import SurfacePatch, surface_patches_by_marker
from .wing_surface import SurfaceMesh


def write_discrete_surface_msh(mesh: SurfaceMesh, out_path: Path | str) -> dict[str, Any]:
    import gmsh

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    patches = surface_patches_by_marker(mesh)

    gmsh.initialize()
    try:
        gmsh.model.add("mesh_native_boundary")
        element_tag_cursor = 1
        for surface_tag, patch in enumerate(patches, start=1):
            gmsh.model.addDiscreteEntity(2, surface_tag)
            _add_patch_nodes(gmsh, mesh, surface_tag, patch)
            element_tag_cursor = _add_patch_elements(
                gmsh,
                surface_tag,
                patch,
                element_tag_cursor,
            )
            physical_tag = gmsh.model.addPhysicalGroup(
                2,
                [surface_tag],
                tag=surface_tag,
            )
            gmsh.model.setPhysicalName(2, physical_tag, patch.marker)
        gmsh.write(str(path))
    finally:
        gmsh.finalize()

    return {
        "path": str(path),
        "marker_names": [patch.marker for patch in patches],
        "surface_count": len(patches),
        "element_count": sum(patch.element_count for patch in patches),
        "node_count": sum(len(patch.node_tags) for patch in patches),
    }


def _add_patch_nodes(
    gmsh,
    mesh: SurfaceMesh,
    surface_tag: int,
    patch: SurfacePatch,
) -> None:
    coords: list[float] = []
    for node_tag in patch.node_tags:
        vertex = mesh.vertices[node_tag - 1]
        coords.extend(vertex)
    gmsh.model.mesh.addNodes(2, surface_tag, list(patch.node_tags), coords)


def _add_patch_elements(
    gmsh,
    surface_tag: int,
    patch: SurfacePatch,
    first_element_tag: int,
) -> int:
    element_types: list[int] = []
    element_tags: list[list[int]] = []
    element_node_tags: list[list[int]] = []
    cursor = first_element_tag

    if patch.triangle_connectivity:
        triangle_tags = list(range(cursor, cursor + patch.triangle_count))
        cursor += patch.triangle_count
        element_types.append(2)
        element_tags.append(triangle_tags)
        element_node_tags.append(
            [node for triangle in patch.triangle_connectivity for node in triangle]
        )

    if patch.quad_connectivity:
        quad_tags = list(range(cursor, cursor + patch.quad_count))
        cursor += patch.quad_count
        element_types.append(3)
        element_tags.append(quad_tags)
        element_node_tags.append([node for quad in patch.quad_connectivity for node in quad])

    gmsh.model.mesh.addElements(
        2,
        surface_tag,
        element_types,
        element_tags,
        element_node_tags,
    )
    return cursor
