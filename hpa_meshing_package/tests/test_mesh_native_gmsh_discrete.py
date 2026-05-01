import pytest

from hpa_meshing.mesh_native.gmsh_discrete import write_discrete_surface_msh
from hpa_meshing.mesh_native.wing_surface import (
    Reference,
    Station,
    WingSpec,
    build_farfield_box_surface,
    build_wing_surface,
    merge_surface_meshes,
)


def _rect_loop():
    return [
        (1.0, 0.05),
        (0.0, 0.05),
        (0.0, -0.05),
        (1.0, -0.05),
    ]


def _merged_boundary():
    wing = build_wing_surface(
        WingSpec(
            stations=[
                Station(y=0.0, airfoil_xz=_rect_loop(), chord=1.0, twist_deg=0.0),
                Station(y=1.0, airfoil_xz=_rect_loop(), chord=1.0, twist_deg=0.0),
                Station(y=2.0, airfoil_xz=_rect_loop(), chord=1.0, twist_deg=0.0),
            ],
            side="full",
            te_rule="finite_thickness",
            tip_rule="planar_cap",
            root_rule="wall_cap",
            reference=Reference(sref_full=2.0, cref=1.0, bref_full=2.0),
        )
    )
    return merge_surface_meshes([wing, build_farfield_box_surface(wing)])


def test_write_discrete_surface_msh_preserves_physical_marker_names(tmp_path):
    gmsh = pytest.importorskip("gmsh")
    out_path = tmp_path / "mesh_native_boundary.msh"

    report = write_discrete_surface_msh(_merged_boundary(), out_path)

    assert out_path.exists()
    assert report["marker_names"] == ["farfield", "wing_wall"]
    assert report["surface_count"] == 2
    assert report["element_count"] == 22

    gmsh.initialize()
    try:
        gmsh.open(str(out_path))
        names = {
            gmsh.model.getPhysicalName(dim, tag)
            for dim, tag in gmsh.model.getPhysicalGroups(2)
        }
    finally:
        gmsh.finalize()

    assert names == {"farfield", "wing_wall"}
