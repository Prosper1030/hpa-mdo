from __future__ import annotations

from hpa_mdo.aero.avl_exporter import export_avl
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
