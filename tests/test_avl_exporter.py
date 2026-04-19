from __future__ import annotations

from hpa_mdo.aero.avl_exporter import export_avl, stage_avl_airfoil_files
from hpa_mdo.aero.aswing_exporter import parse_avl
from hpa_mdo.aero.vsp_geometry_parser import VSPControl, VSPGeometryModel, VSPSection, VSPSurface


def test_export_avl_inserts_control_boundary_sections_for_partial_span_aileron(tmp_path):
    geometry = VSPGeometryModel(
        surfaces=[
            VSPSurface(
                name="Wing",
                surface_type="wing",
                origin=(0.0, 0.0, 0.0),
                rotation=(0.0, 0.0, 0.0),
                symmetry="xz",
                sections=[
                    VSPSection(0.0, 0.0, 0.0, 1.2, 0.0, "NACA 2412"),
                    VSPSection(0.0, 0.4, 0.0, 1.0, 0.0, "NACA 2412"),
                    VSPSection(0.0, 1.0, 0.0, 0.7, 0.0, "NACA 2412"),
                ],
                controls=[
                    VSPControl(
                        name="aileron",
                        control_type="aileron",
                        eta_start=0.5,
                        eta_end=0.75,
                        chord_fraction_start=0.25,
                        chord_fraction_end=0.25,
                    )
                ],
            ),
        ]
    )

    avl_path = export_avl(geometry, tmp_path / "wing_controls.avl")
    model = parse_avl(avl_path)

    wing = model.surfaces[0]
    assert [section.y for section in wing.sections] == [0.0, 0.4, 0.5, 0.75, 1.0]
    assert wing.sections[2].controls == ("aileron",)
    assert wing.sections[3].controls == ("aileron",)
    assert wing.sections[0].controls == ()

    text = avl_path.read_text(encoding="utf-8")
    assert "aileron  1.0  0.750000  0.0 0.0 0.0  -1.0" in text


def test_export_avl_uses_vertical_rudder_hinge_axis(tmp_path):
    geometry = VSPGeometryModel(
        surfaces=[
            VSPSurface(
                name="Wing",
                surface_type="wing",
                origin=(0.0, 0.0, 0.0),
                rotation=(0.0, 0.0, 0.0),
                symmetry="xz",
                sections=[
                    VSPSection(0.0, 0.0, 0.0, 1.0, 0.0, "NACA 2412"),
                    VSPSection(0.0, 1.0, 0.0, 1.0, 0.0, "NACA 2412"),
                ],
            ),
            VSPSurface(
                name="Fin",
                surface_type="v_fin",
                origin=(5.0, 0.0, -0.7),
                rotation=(90.0, 0.0, 0.0),
                symmetry="none",
                sections=[
                    VSPSection(5.0, 0.0, -0.7, 0.7, 0.0, "NACA 0009"),
                    VSPSection(5.0, 0.0, 1.7, 0.7, 0.0, "NACA 0009"),
                ],
            ),
        ]
    )

    avl_path = export_avl(geometry, tmp_path / "case.avl")

    text = avl_path.read_text(encoding="utf-8")
    assert "rudder  1.0  0.000000  0.0 0.0 1.0  1.0" in text
    assert "rudder  1.0  0.000000  0.0 0.0 0.0  1.0" not in text


def test_export_avl_prefers_inline_airfoil_points_over_afile(tmp_path):
    geometry = VSPGeometryModel(
        surfaces=[
            VSPSurface(
                name="Wing",
                surface_type="wing",
                origin=(0.0, 0.0, 0.0),
                rotation=(0.0, 0.0, 0.0),
                symmetry="xz",
                sections=[
                    VSPSection(
                        0.0,
                        0.0,
                        0.0,
                        1.2,
                        0.0,
                        "fx76mp140",
                        airfoil_points=(
                            (1.0, 0.0),
                            (0.5, 0.08),
                            (0.0, 0.0),
                            (0.5, -0.04),
                            (1.0, 0.0),
                        ),
                    ),
                    VSPSection(
                        0.0,
                        1.0,
                        0.0,
                        1.0,
                        0.0,
                        "fx76mp140",
                        airfoil_points=(
                            (1.0, 0.0),
                            (0.5, 0.08),
                            (0.0, 0.0),
                            (0.5, -0.04),
                            (1.0, 0.0),
                        ),
                    ),
                ],
            ),
        ]
    )

    avl_path = export_avl(geometry, tmp_path / "inline_airfoil.avl")

    text = avl_path.read_text(encoding="utf-8")
    assert "AIRFOIL" in text
    assert "AFILE" not in text
    assert "1.000000000  0.000000000" in text


def test_stage_avl_airfoil_files_copies_and_rewrites_afile_entries(tmp_path):
    airfoil_dir = tmp_path / "airfoils"
    airfoil_dir.mkdir()
    (airfoil_dir / "fx76mp140.dat").write_text("fx\n0 0\n1 0\n", encoding="utf-8")
    (airfoil_dir / "clarkysm.dat").write_text("clark\n0 0\n1 0\n", encoding="utf-8")
    avl_path = tmp_path / "cases" / "case.avl"
    avl_path.parent.mkdir()
    avl_path.write_text(
        "\n".join(
            [
                "demo",
                "SURFACE",
                "Wing",
                "SECTION",
                "0 0 0 1 0",
                "AFILE",
                "fx76mp140.dat",
                "SECTION",
                "0 1 0 1 0",
                "AFILE",
                "clarkysm.dat ! keep comment",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    staged = stage_avl_airfoil_files(avl_path, airfoil_dir=airfoil_dir)

    assert [path.name for path in staged] == ["fx76mp140.dat", "clarkysm.dat"]
    assert (avl_path.parent / "fx76mp140.dat").exists()
    assert (avl_path.parent / "clarkysm.dat").exists()
    text = avl_path.read_text(encoding="utf-8")
    assert "AFILE\nfx76mp140.dat" in text
    assert "AFILE\nclarkysm.dat ! keep comment" in text


def test_stage_avl_airfoil_files_disambiguates_same_basename_from_different_sources(tmp_path):
    af_a = tmp_path / "a"
    af_b = tmp_path / "b"
    af_a.mkdir()
    af_b.mkdir()
    (af_a / "shared.dat").write_text("a\n0 0\n1 0\n", encoding="utf-8")
    (af_b / "shared.dat").write_text("b\n0 0\n1 0\n", encoding="utf-8")
    avl_path = tmp_path / "case.avl"
    avl_path.write_text(
        "\n".join(
            [
                "demo",
                "SURFACE",
                "Wing",
                "SECTION",
                "0 0 0 1 0",
                "AFILE",
                str((af_a / "shared.dat").resolve()),
                "SECTION",
                "0 1 0 1 0",
                "AFILE",
                str((af_b / "shared.dat").resolve()),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    staged = stage_avl_airfoil_files(avl_path)

    assert len(staged) == 2
    assert staged[0].name == "shared.dat"
    assert staged[1].name.startswith("shared_")
    assert staged[1].suffix == ".dat"


def test_export_avl_uses_mac_for_cref_and_quarter_mac_xref(tmp_path):
    geometry = VSPGeometryModel(
        surfaces=[
            VSPSurface(
                name="Wing",
                surface_type="wing",
                origin=(0.0, 0.0, 0.0),
                rotation=(0.0, 0.0, 0.0),
                symmetry="xz",
                sections=[
                    VSPSection(0.0, 0.0, 0.0, 1.300, 0.0, "fx76mp140"),
                    VSPSection(0.0, 4.5, 0.07854, 1.300, 0.0, "fx76mp140"),
                    VSPSection(0.0, 7.5, 0.18330, 1.175, 0.0, "fx76mp140"),
                    VSPSection(0.0, 10.5, 0.34055, 1.040, 0.0, "fx76mp140"),
                    VSPSection(0.0, 13.5, 0.55035, 0.830, 0.0, "fx76mp140"),
                    VSPSection(0.0, 16.5, 0.81280, 0.435, 0.0, "clarkysm"),
                ],
            ),
        ]
    )

    avl_path = export_avl(geometry, tmp_path / "mac_reference.avl")
    text = avl_path.read_text(encoding="utf-8")

    assert "#Sref  Cref  Bref\n35.175000000  1.130189765  33.000000000" in text
    assert "#Xref  Yref  Zref\n0.282547441  0.000000000  0.000000000" in text
