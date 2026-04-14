from __future__ import annotations

from hpa_mdo.aero.avl_exporter import export_avl
from hpa_mdo.aero.vsp_geometry_parser import VSPGeometryModel, VSPSection, VSPSurface


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
    assert "rudder  1.0  0.0  0.0 0.0 1.0  1.0" in text
    assert "rudder  1.0  0.0  0.0 0.0 0.0  1.0" not in text
