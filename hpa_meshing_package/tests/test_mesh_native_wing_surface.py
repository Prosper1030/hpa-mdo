import json
import math

import pytest

from hpa_meshing.mesh_native.wing_surface import (
    Face,
    Reference,
    Station,
    SurfaceMesh,
    WingSpec,
    build_farfield_box_surface,
    build_wing_surface,
    load_wing_spec,
    merge_surface_meshes,
    surface_orientation_summary,
    validate_surface_mesh,
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
    assert mesh.faces[0].marker == "wing_wall"
    assert all(face.marker for face in mesh.faces)

    orientation = surface_orientation_summary(mesh)
    assert orientation["component_count"] == 1
    assert orientation["inconsistent_edge_count"] == 0
    assert orientation["negative_signed_volume_component_count"] == 0
    assert orientation["signed_volume"] > 0.0


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


def test_build_wing_surface_rejects_non_increasing_station_y():
    spec = WingSpec(
        stations=[
            Station(y=0.0, airfoil_xz=_rect_loop(), chord=1.0, twist_deg=0.0),
            Station(y=0.0, airfoil_xz=_rect_loop(), chord=1.0, twist_deg=0.0),
        ],
        side="full",
        te_rule="finite_thickness",
        tip_rule="planar_cap",
        root_rule="wall_cap",
        reference=Reference(sref_full=1.0, cref=1.0, bref_full=1.0),
    )

    with pytest.raises(ValueError, match="strictly increasing"):
        build_wing_surface(spec)


def _closed_tetra_mesh(marker: str = "wing_wall") -> SurfaceMesh:
    return SurfaceMesh(
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        ],
        faces=[
            Face(nodes=(0, 2, 1), marker=marker),
            Face(nodes=(0, 1, 3), marker=marker),
            Face(nodes=(1, 2, 3), marker=marker),
            Face(nodes=(2, 0, 3), marker=marker),
        ],
    )


def test_validate_surface_mesh_rejects_missing_required_marker():
    mesh = _closed_tetra_mesh(marker="farfield")

    with pytest.raises(ValueError, match="Required marker missing: wing_wall"):
        validate_surface_mesh(mesh, required_markers=("wing_wall",))


def test_validate_surface_mesh_rejects_unknown_marker():
    mesh = _closed_tetra_mesh(marker="not_owned")

    with pytest.raises(ValueError, match="Unknown marker: not_owned"):
        validate_surface_mesh(mesh)


def test_validate_surface_mesh_rejects_open_edges():
    mesh = SurfaceMesh(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[Face(nodes=(0, 1, 2), marker="wing_wall")],
    )

    with pytest.raises(ValueError, match="Non-watertight surface"):
        validate_surface_mesh(mesh)


def test_validate_surface_mesh_rejects_zero_area_face():
    mesh = SurfaceMesh(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
        faces=[Face(nodes=(0, 1, 2), marker="wing_wall")],
    )

    with pytest.raises(ValueError, match="Zero or tiny face area"):
        validate_surface_mesh(mesh)


def test_load_wing_spec_from_json_manifest_builds_surface(tmp_path):
    spec_path = tmp_path / "main_wing.mesh_native.json"
    spec_path.write_text(
        json.dumps(
            {
                "units": "m",
                "side": "full",
                "te_rule": "finite_thickness",
                "tip_rule": "planar_cap",
                "root_rule": "wall_cap",
                "reference": {
                    "sref_full": 2.0,
                    "cref": 1.0,
                    "bref_full": 2.0,
                },
                "stations": [
                    {
                        "y": 0.0,
                        "airfoil_xz": _rect_loop(),
                        "chord": 1.0,
                        "twist_deg": 0.0,
                    },
                    {
                        "y": 1.0,
                        "airfoil_xz": _rect_loop(),
                        "chord": 1.0,
                        "twist_deg": 0.0,
                    },
                    {
                        "y": 2.0,
                        "airfoil_xz": _rect_loop(),
                        "chord": 1.0,
                        "twist_deg": 0.0,
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    spec = load_wing_spec(spec_path)
    mesh = build_wing_surface(spec)

    assert spec.reference.sref_full == pytest.approx(2.0)
    assert mesh.metadata["span_m"] == pytest.approx(2.0)
    assert mesh.marker_counts() == {"wing_wall": 16}


def test_load_wing_spec_rejects_non_meter_units(tmp_path):
    spec_path = tmp_path / "main_wing.mesh_native.json"
    spec_path.write_text(
        json.dumps(
            {
                "units": "mm",
                "side": "full",
                "te_rule": "finite_thickness",
                "tip_rule": "planar_cap",
                "root_rule": "wall_cap",
                "reference": {
                    "sref_full": 2.0,
                    "cref": 1.0,
                    "bref_full": 2.0,
                },
                "stations": [
                    {
                        "y": 0.0,
                        "airfoil_xz": _rect_loop(),
                        "chord": 1.0,
                        "twist_deg": 0.0,
                    },
                    {
                        "y": 1.0,
                        "airfoil_xz": _rect_loop(),
                        "chord": 1.0,
                        "twist_deg": 0.0,
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Mesh-native wing spec units must be m"):
        load_wing_spec(spec_path)


def test_build_farfield_box_surface_wraps_wing_bounds_with_farfield_marker():
    wing = build_wing_surface(_rect_spec())

    farfield = build_farfield_box_surface(
        wing,
        upstream_factor=2.0,
        downstream_factor=3.0,
        lateral_factor=4.0,
        vertical_factor=5.0,
    )

    assert len(farfield.vertices) == 8
    assert len(farfield.faces) == 6
    assert farfield.marker_counts() == {"farfield": 6}
    assert farfield.metadata["x_min"] == pytest.approx(-2.0)
    assert farfield.metadata["x_max"] == pytest.approx(4.0)
    assert farfield.metadata["y_min"] == pytest.approx(-8.0)
    assert farfield.metadata["y_max"] == pytest.approx(10.0)
    assert farfield.metadata["z_min"] == pytest.approx(-10.05)
    assert farfield.metadata["z_max"] == pytest.approx(10.05)
    validate_surface_mesh(farfield, required_markers=("farfield",))
    orientation = surface_orientation_summary(farfield)
    assert orientation["inconsistent_edge_count"] == 0
    assert orientation["negative_signed_volume_component_count"] == 0


def test_merge_surface_meshes_preserves_wing_and_farfield_marker_ownership():
    wing = build_wing_surface(_rect_spec())
    farfield = build_farfield_box_surface(wing)

    merged = merge_surface_meshes([wing, farfield])

    assert len(merged.vertices) == len(wing.vertices) + len(farfield.vertices)
    assert len(merged.faces) == len(wing.faces) + len(farfield.faces)
    assert merged.marker_counts() == {"wing_wall": 16, "farfield": 6}
    validate_surface_mesh(merged, required_markers=("wing_wall", "farfield"))
