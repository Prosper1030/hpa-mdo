import pytest

from hpa_meshing.mesh_native.patches import (
    marker_summary,
    surface_patches_by_marker,
)
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


def test_surface_patches_by_marker_returns_deterministic_marker_payloads():
    patches = surface_patches_by_marker(_merged_boundary())

    assert [patch.marker for patch in patches] == ["farfield", "wing_wall"]
    farfield = patches[0]
    wing_wall = patches[1]

    assert farfield.node_tags == tuple(range(15, 23))
    assert farfield.triangle_count == 0
    assert farfield.quad_count == 6
    assert farfield.element_count == 6
    assert farfield.quad_connectivity[0] == (15, 18, 17, 16)

    assert wing_wall.node_tags == tuple(range(1, 15))
    assert wing_wall.triangle_count == 8
    assert wing_wall.quad_count == 8
    assert wing_wall.element_count == 16
    assert wing_wall.triangle_connectivity[0] == (13, 2, 1)
    assert wing_wall.bounds["x_max"] == pytest.approx(1.0)


def test_marker_summary_reports_required_marker_counts_and_bounds():
    summary = marker_summary(_merged_boundary())

    assert summary["wing_wall"]["exists"] is True
    assert summary["wing_wall"]["element_count"] == 16
    assert summary["wing_wall"]["triangle_count"] == 8
    assert summary["wing_wall"]["quad_count"] == 8
    assert summary["wing_wall"]["node_count"] == 14

    assert summary["farfield"]["exists"] is True
    assert summary["farfield"]["element_count"] == 6
    assert summary["farfield"]["triangle_count"] == 0
    assert summary["farfield"]["quad_count"] == 6
    assert summary["farfield"]["node_count"] == 8
