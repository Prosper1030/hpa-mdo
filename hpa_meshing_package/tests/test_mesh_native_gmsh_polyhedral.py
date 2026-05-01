from pathlib import Path

import pytest

from hpa_meshing.mesh_native.gmsh_polyhedral import write_faceted_volume_mesh
from hpa_meshing.mesh_native.su2_structured import parse_su2_marker_summary
from hpa_meshing.mesh_native.wing_surface import (
    Reference,
    Station,
    WingSpec,
    build_farfield_box_surface,
    build_wing_surface,
)


def _rect_loop():
    return [
        (1.0, 0.05),
        (0.0, 0.05),
        (0.0, -0.05),
        (1.0, -0.05),
    ]


def _wing_and_close_farfield():
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
    farfield = build_farfield_box_surface(
        wing,
        upstream_factor=1.5,
        downstream_factor=2.0,
        lateral_factor=1.5,
        vertical_factor=1.5,
    )
    return wing, farfield


def test_write_faceted_volume_mesh_preserves_su2_boundary_markers(tmp_path: Path):
    pytest.importorskip("gmsh")
    wing, farfield = _wing_and_close_farfield()
    msh_path = tmp_path / "faceted_wing_volume.msh"
    su2_path = tmp_path / "faceted_wing_volume.su2"

    report = write_faceted_volume_mesh(
        wing,
        farfield,
        msh_path,
        su2_path=su2_path,
        mesh_size=2.0,
    )

    assert report["status"] == "meshed"
    assert report["volume_count"] == 1
    assert report["volume_element_count"] > 0
    assert report["node_count"] > 0
    assert report["surface_triangle_count"] == 36
    assert report["physical_groups"]["wing_wall"]["dimension"] == 2
    assert report["physical_groups"]["farfield"]["dimension"] == 2
    assert report["physical_groups"]["fluid"]["dimension"] == 3
    assert report["physical_groups"]["wing_wall"]["entity_count"] == 24
    assert report["physical_groups"]["farfield"]["entity_count"] == 12
    assert msh_path.exists()
    assert su2_path.exists()

    su2_summary = parse_su2_marker_summary(su2_path)
    assert su2_summary["ndime"] == 3
    assert su2_summary["nelem"] == report["volume_element_count"]
    assert su2_summary["nmark"] == 2
    assert set(su2_summary["markers"]) == {"wing_wall", "farfield"}
    assert su2_summary["markers"]["wing_wall"]["element_count"] > 0
    assert su2_summary["markers"]["farfield"]["element_count"] > 0
