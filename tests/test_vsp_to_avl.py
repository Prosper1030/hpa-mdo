from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import vsp_to_avl  # noqa: E402
from hpa_mdo.aero.vsp_geometry_parser import VSPGeometryModel, VSPSection, VSPSurface  # noqa: E402


def _write_minimal_config(path: Path, *, extra_io: list[str] | None = None) -> None:
    lines = [
        'project_name: "Config Geometry Demo"',
        "flight:",
        "  velocity: 8.0",
        "  air_density: 1.225",
        "weight:",
        "  airframe_kg: 30.0",
        "  pilot_kg: 55.0",
        "  max_takeoff_kg: 95.0",
        "wing:",
        "  span: 20.0",
        "  root_chord: 1.2",
        "  tip_chord: 0.6",
        '  airfoil_root: "clarkysm"',
        '  airfoil_tip: "fx76mp140"',
        "horizontal_tail:",
        "  enabled: true",
        '  name: "Elevator"',
        "  x_location: 6.0",
        "  y_location: 0.0",
        "  z_location: 0.1",
        "  span: 4.0",
        "  root_chord: 0.8",
        "  tip_chord: 0.8",
        '  airfoil: "NACA 0009"',
        '  symmetry: "xz"',
        "vertical_fin:",
        "  enabled: true",
        '  name: "Fin"',
        "  x_location: 6.5",
        "  y_location: 0.0",
        "  z_location: -0.5",
        "  span: 2.4",
        "  root_chord: 0.7",
        "  tip_chord: 0.7",
        '  airfoil: "NACA 0009"',
        '  symmetry: "none"',
        "  x_rotation_deg: 90.0",
        "main_spar:",
        '  material: "carbon_fiber_hm"',
        "  segments: [5.0, 5.0]",
        "io:",
        "  output_dir: output",
    ]
    if extra_io:
        lines.extend(extra_io)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mock_vsp3_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<OpenVSP>
  <Vehicle>
    <Geom>
      <Name>Main Wing</Name>
      <XForm>
        <X_Location>0.0</X_Location>
        <Y_Location>0.0</Y_Location>
        <Z_Location>0.0</Z_Location>
      </XForm>
      <Sym>
        <Sym_Planar_Flag>2</Sym_Planar_Flag>
      </Sym>
      <XSec_Surf>
        <XSec>
          <XLE>0.0</XLE>
          <YLE>0.0</YLE>
          <ZLE>0.0</ZLE>
          <Chord>1.39</Chord>
          <Airfoil>NACA 2412</Airfoil>
        </XSec>
        <XSec>
          <XLE>0.0</XLE>
          <YLE>16.5</YLE>
          <ZLE>1.73</ZLE>
          <Chord>0.47</Chord>
          <Airfoil>NACA 2412</Airfoil>
        </XSec>
      </XSec_Surf>
    </Geom>
  </Vehicle>
</OpenVSP>
"""


def test_vsp_to_avl_uses_yaml_geometry_when_no_vsp_exists(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    output_path = tmp_path / "from_config.avl"
    _write_minimal_config(config_path)

    rc = vsp_to_avl.main(["--config", str(config_path), "--output", str(output_path)])

    assert rc == 0
    text = output_path.read_text(encoding="utf-8")
    assert "Config Geometry Demo" in text
    assert "SURFACE\nMainWing" in text
    assert "0.000000000  10.000000000  0.524438142  0.600000000  0.000000000" in text
    assert "SURFACE\nElevator" in text
    assert "6.000000000  2.000000000  0.100000000  0.800000000  0.000000000" in text
    assert "elevator" in text
    assert "SURFACE\nFin" in text
    assert "6.500000000  0.000000000  1.900000000  0.700000000  0.000000000" in text
    assert "rudder" in text


def test_vsp_to_avl_prefers_config_vsp_model_over_yaml_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vsp3_path = tmp_path / "reference.vsp3"
    vsp3_path.write_text(_mock_vsp3_xml(), encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    output_path = tmp_path / "from_vsp.avl"
    _write_minimal_config(config_path, extra_io=[f"  vsp_model: {vsp3_path}"])
    monkeypatch.setattr(
        vsp_to_avl,
        "summarize_vsp_surfaces",
        lambda _path, airfoil_dir=None: {
            "source_path": str(vsp3_path),
            "main_wing": None,
            "horizontal_tail": None,
            "vertical_fin": None,
        },
    )

    rc = vsp_to_avl.main(["--config", str(config_path), "--output", str(output_path)])

    assert rc == 0
    text = output_path.read_text(encoding="utf-8")
    assert "Geometry source:" not in text
    assert "0.000000000  0.000000000  0.000000000  1.390000000  0.000000000" in text
    assert "0.000000000  16.500000000  1.730000000  0.470000000  0.000000000" in text
    assert "10.000000000  0.874886635" not in text


def test_vsp_to_avl_attaches_introspected_controls_when_vsp_is_present(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vsp3_path = tmp_path / "reference.vsp3"
    vsp3_path.write_text(_mock_vsp3_xml(), encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    output_path = tmp_path / "from_vsp_controls.avl"
    _write_minimal_config(config_path, extra_io=[f"  vsp_model: {vsp3_path}"])

    geometry = VSPGeometryModel(
        surfaces=[
            VSPSurface(
                name="Main Wing",
                surface_type="wing",
                origin=(0.0, 0.0, 0.0),
                rotation=(0.0, 0.0, 0.0),
                symmetry="xz",
                sections=[
                    VSPSection(0.0, 0.0, 0.0, 1.39, 0.0, "NACA 2412"),
                    VSPSection(0.0, 16.5, 1.73, 0.47, 0.0, "NACA 2412"),
                ],
            ),
        ]
    )

    monkeypatch.setattr(
        vsp_to_avl,
        "VSPGeometryParser",
        lambda _path: SimpleNamespace(parse=lambda: geometry),
    )
    monkeypatch.setattr(
        vsp_to_avl,
        "summarize_vsp_surfaces",
        lambda _path, airfoil_dir=None: {
            "source_path": str(vsp3_path),
            "main_wing": {
                "controls": [
                    {
                        "name": "Outboard Aileron",
                        "type": "aileron",
                        "eta_start": 0.6,
                        "eta_end": 1.0,
                        "chord_fraction_start": 0.25,
                        "chord_fraction_end": 0.25,
                        "edge": "trailing",
                        "surf_type": "both",
                    }
                ]
            },
            "horizontal_tail": None,
            "vertical_fin": None,
        },
    )

    rc = vsp_to_avl.main(["--config", str(config_path), "--output", str(output_path)])

    assert rc == 0
    text = output_path.read_text(encoding="utf-8")
    assert "aileron" in text
    assert "9.900000000" in text
    assert "aileron  1.0  0.750000  0.0 0.0 0.0  -1.0" in text
