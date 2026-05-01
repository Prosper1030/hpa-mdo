import math

import pytest

from hpa_meshing.mesh_native.wing_surface import (
    Reference,
    Station,
    WingSpec,
    build_wing_surface,
)


def _rect_loop():
    return [
        (1.0, 0.05),
        (0.0, 0.05),
        (0.0, -0.05),
        (1.0, -0.05),
    ]


def _rect_spec() -> WingSpec:
    return WingSpec(
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


def test_build_wing_surface_creates_deterministic_closed_rectangular_mesh():
    mesh = build_wing_surface(_rect_spec())

    assert len(mesh.vertices) == 14
    assert len(mesh.faces) == 16
    assert mesh.marker_counts() == {"wing_wall": 16}
    assert mesh.metadata["station_count"] == 3
    assert mesh.metadata["points_per_station"] == 4
    assert mesh.metadata["span_m"] == pytest.approx(2.0)
    assert mesh.metadata["planform_area_m2"] == pytest.approx(2.0)

    assert mesh.vertices[0] == pytest.approx((1.0, 0.0, 0.05))
    assert mesh.vertices[4] == pytest.approx((1.0, 1.0, 0.05))
    assert mesh.faces[0].nodes == (0, 4, 5, 1)
    assert mesh.faces[0].marker == "wing_wall"
    assert all(face.marker for face in mesh.faces)


def test_build_wing_surface_applies_chord_and_twist_about_quarter_chord():
    spec = WingSpec(
        stations=[
            Station(
                y=0.0,
                airfoil_xz=[(0.25, 0.0), (1.0, 0.0), (0.25, -0.1)],
                chord=2.0,
                twist_deg=0.0,
            ),
            Station(
                y=1.0,
                airfoil_xz=[(0.25, 0.0), (1.0, 0.0), (0.25, -0.1)],
                chord=2.0,
                twist_deg=90.0,
            ),
        ],
        side="full",
        te_rule="finite_thickness",
        tip_rule="planar_cap",
        root_rule="wall_cap",
        reference=Reference(sref_full=2.0, cref=2.0, bref_full=1.0),
    )

    mesh = build_wing_surface(spec)

    quarter_chord = mesh.vertices[3]
    rotated_te = mesh.vertices[4]
    assert quarter_chord == pytest.approx((0.5, 1.0, 0.0))
    assert rotated_te[0] == pytest.approx(0.5, abs=1.0e-12)
    assert rotated_te[1] == pytest.approx(1.0)
    assert rotated_te[2] == pytest.approx(-1.5)
    assert math.isfinite(mesh.metadata["planform_area_m2"])
