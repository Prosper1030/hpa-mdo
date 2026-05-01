from __future__ import annotations

from pathlib import Path
from typing import Any

from .wing_surface import Face, SurfaceMesh


def write_faceted_volume_mesh(
    wing: SurfaceMesh,
    farfield: SurfaceMesh,
    out_path: Path | str,
    *,
    su2_path: Path | str | None = None,
    mesh_size: float = 2.0,
    wall_marker: str = "wing_wall",
    farfield_marker: str = "farfield",
    fluid_marker: str = "fluid",
) -> dict[str, Any]:
    """Generate a Gmsh volume from mesh-native faceted boundary surfaces.

    The geometry source of truth remains the mesh-native indexed surface. Gmsh is
    used here as a volume mesher over built-in plane surfaces, not as a CAD repair
    step or STEP/BREP importer.
    """
    import gmsh

    msh_path = Path(out_path)
    msh_path.parent.mkdir(parents=True, exist_ok=True)
    su2_output_path = Path(su2_path) if su2_path is not None else None
    if su2_output_path is not None:
        su2_output_path.parent.mkdir(parents=True, exist_ok=True)

    if mesh_size <= 0.0:
        raise ValueError("mesh_size must be positive")

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("mesh_native_faceted_volume")

        vertices = [*wing.vertices, *farfield.vertices]
        point_tags = [
            gmsh.model.geo.addPoint(x, y, z, mesh_size)
            for x, y, z in vertices
        ]
        line_cache: dict[tuple[int, int], tuple[int, int, int]] = {}
        wing_surfaces = _add_mesh_surfaces(
            gmsh,
            wing.faces,
            point_tags=point_tags,
            line_cache=line_cache,
            node_offset=0,
        )
        farfield_surfaces = _add_mesh_surfaces(
            gmsh,
            farfield.faces,
            point_tags=point_tags,
            line_cache=line_cache,
            node_offset=len(wing.vertices),
        )

        outer_loop = gmsh.model.geo.addSurfaceLoop(farfield_surfaces)
        inner_loop = gmsh.model.geo.addSurfaceLoop(wing_surfaces)
        fluid_volume = gmsh.model.geo.addVolume([outer_loop, inner_loop])
        gmsh.model.geo.synchronize()

        wing_group = gmsh.model.addPhysicalGroup(2, wing_surfaces)
        gmsh.model.setPhysicalName(2, wing_group, wall_marker)
        farfield_group = gmsh.model.addPhysicalGroup(2, farfield_surfaces)
        gmsh.model.setPhysicalName(2, farfield_group, farfield_marker)
        fluid_group = gmsh.model.addPhysicalGroup(3, [fluid_volume])
        gmsh.model.setPhysicalName(3, fluid_group, fluid_marker)

        gmsh.option.setNumber("Mesh.MeshSizeMin", mesh_size)
        gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_size)
        gmsh.option.setNumber("Mesh.Algorithm", 5)
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.model.mesh.generate(3)

        node_tags, _, _ = gmsh.model.mesh.getNodes()
        volume_element_types, volume_element_tags, _ = gmsh.model.mesh.getElements(3)
        volume_type_counts = {
            str(element_type): len(tags)
            for element_type, tags in zip(volume_element_types, volume_element_tags)
        }
        volume_element_count = sum(volume_type_counts.values())
        gmsh.write(str(msh_path))
        if su2_output_path is not None:
            gmsh.write(str(su2_output_path))

        return {
            "status": "meshed",
            "route": "mesh_native_faceted_gmsh_volume",
            "mesh_path": str(msh_path),
            "su2_path": None if su2_output_path is None else str(su2_output_path),
            "volume_count": len(gmsh.model.getEntities(3)),
            "node_count": len(node_tags),
            "volume_element_count": volume_element_count,
            "volume_element_type_counts": volume_type_counts,
            "surface_triangle_count": len(wing_surfaces) + len(farfield_surfaces),
            "physical_groups": {
                wall_marker: {
                    "dimension": 2,
                    "physical_tag": wing_group,
                    "entity_count": len(wing_surfaces),
                },
                farfield_marker: {
                    "dimension": 2,
                    "physical_tag": farfield_group,
                    "entity_count": len(farfield_surfaces),
                },
                fluid_marker: {
                    "dimension": 3,
                    "physical_tag": fluid_group,
                    "entity_count": 1,
                },
            },
            "caveats": [
                "wing boundary is faceted from mesh-native panels",
                "tet volume mesh only; no boundary-layer prism strategy",
            ],
        }
    finally:
        gmsh.finalize()


def _add_mesh_surfaces(
    gmsh,
    faces: list[Face],
    *,
    point_tags: list[int],
    line_cache: dict[tuple[int, int], tuple[int, int, int]],
    node_offset: int,
) -> list[int]:
    surfaces: list[int] = []
    for face in faces:
        for triangle in _triangulate(face):
            shifted = tuple(node + node_offset for node in triangle)
            curve_loop = gmsh.model.geo.addCurveLoop(
                [
                    _line_between(gmsh, point_tags, line_cache, shifted[0], shifted[1]),
                    _line_between(gmsh, point_tags, line_cache, shifted[1], shifted[2]),
                    _line_between(gmsh, point_tags, line_cache, shifted[2], shifted[0]),
                ]
            )
            surfaces.append(gmsh.model.geo.addPlaneSurface([curve_loop]))
    return surfaces


def _triangulate(face: Face) -> list[tuple[int, int, int]]:
    nodes = tuple(face.nodes)
    if len(nodes) == 3:
        return [nodes]
    if len(nodes) == 4:
        return [
            (nodes[0], nodes[1], nodes[2]),
            (nodes[0], nodes[2], nodes[3]),
        ]
    raise ValueError("Only triangle and quad faces can be converted to plane surfaces")


def _line_between(
    gmsh,
    point_tags: list[int],
    line_cache: dict[tuple[int, int], tuple[int, int, int]],
    start: int,
    end: int,
) -> int:
    key = tuple(sorted((start, end)))
    if key not in line_cache:
        line_cache[key] = (
            gmsh.model.geo.addLine(point_tags[key[0]], point_tags[key[1]]),
            key[0],
            key[1],
        )
    line_tag, stored_start, stored_end = line_cache[key]
    return line_tag if (start, end) == (stored_start, stored_end) else -line_tag
