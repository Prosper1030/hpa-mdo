from __future__ import annotations

import pytest

from hpa_mdo.aero.vsp_geometry_parser import VSPGeometryParser


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
        <X_Rotation>0.0</X_Rotation>
        <Y_Rotation>0.0</Y_Rotation>
        <Z_Rotation>0.0</Z_Rotation>
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
          <Twist>0.0</Twist>
          <Airfoil>NACA 2412</Airfoil>
        </XSec>
        <XSec>
          <XLE>0.1</XLE>
          <YLE>16.5</YLE>
          <ZLE>1.73</ZLE>
          <Chord>0.47</Chord>
          <Twist>0.0</Twist>
          <Airfoil>NACA 2412</Airfoil>
        </XSec>
      </XSec_Surf>
    </Geom>
    <Geom>
      <Name>Elevator</Name>
      <XForm>
        <X_Location>4.0</X_Location>
        <Y_Location>0.0</Y_Location>
        <Z_Location>0.0</Z_Location>
        <X_Rotation>0.0</X_Rotation>
        <Y_Rotation>0.0</Y_Rotation>
        <Z_Rotation>0.0</Z_Rotation>
      </XForm>
      <Sym>
        <Sym_Planar_Flag>2</Sym_Planar_Flag>
      </Sym>
      <XSec_Surf>
        <XSec>
          <XLE>0.0</XLE>
          <YLE>0.0</YLE>
          <ZLE>0.0</ZLE>
          <Chord>0.8</Chord>
          <Twist>0.0</Twist>
          <Airfoil>NACA 0009</Airfoil>
        </XSec>
        <XSec>
          <XLE>0.0</XLE>
          <YLE>1.5</YLE>
          <ZLE>0.0</ZLE>
          <Chord>0.8</Chord>
          <Twist>0.0</Twist>
          <Airfoil>NACA 0009</Airfoil>
        </XSec>
      </XSec_Surf>
    </Geom>
    <Geom>
      <Name>Fin</Name>
      <XForm>
        <X_Location>5.0</X_Location>
        <Y_Location>0.0</Y_Location>
        <Z_Location>-0.7</Z_Location>
        <X_Rotation>90.0</X_Rotation>
        <Y_Rotation>0.0</Y_Rotation>
        <Z_Rotation>0.0</Z_Rotation>
      </XForm>
      <Sym>
        <Sym_Planar_Flag>0</Sym_Planar_Flag>
      </Sym>
      <XSec_Surf>
        <XSec>
          <XLE>0.0</XLE>
          <YLE>0.0</YLE>
          <ZLE>0.0</ZLE>
          <Chord>0.7</Chord>
          <Twist>0.0</Twist>
          <Airfoil>NACA 0009</Airfoil>
        </XSec>
        <XSec>
          <XLE>0.0</XLE>
          <YLE>2.4</YLE>
          <ZLE>0.0</ZLE>
          <Chord>0.7</Chord>
          <Twist>0.0</Twist>
          <Airfoil>NACA 0009</Airfoil>
        </XSec>
      </XSec_Surf>
    </Geom>
  </Vehicle>
</OpenVSP>
"""


def test_vsp_geometry_parser_extracts_surfaces_and_sections(tmp_path):
    vsp3_path = tmp_path / "mock.vsp3"
    vsp3_path.write_text(_mock_vsp3_xml(), encoding="utf-8")

    geometry = VSPGeometryParser(vsp3_path).parse()

    assert len(geometry.surfaces) == 3
    wing = geometry.get_wing()
    h_stab = geometry.get_h_stab()
    v_fin = geometry.get_v_fin()
    assert wing is not None
    assert h_stab is not None
    assert v_fin is not None

    assert wing.name == "Main Wing"
    assert wing.symmetry == "xz"
    assert len(wing.sections) == 2
    assert wing.sections[0].chord == pytest.approx(1.39)
    assert wing.sections[1].y_le == pytest.approx(16.5)

    assert h_stab.name == "Elevator"
    assert h_stab.origin == pytest.approx((4.0, 0.0, 0.0))
    assert h_stab.sections[1].y_le == pytest.approx(1.5)

    assert v_fin.name == "Fin"
    assert v_fin.surface_type == "v_fin"
    assert v_fin.origin == pytest.approx((5.0, 0.0, -0.7))
    assert v_fin.rotation[0] == pytest.approx(90.0)
    assert v_fin.sections[1].z_le == pytest.approx(1.7, abs=1.0e-6)


def test_vsp_geometry_parser_raises_when_missing_file(tmp_path):
    missing = tmp_path / "missing.vsp3"
    with pytest.raises(FileNotFoundError):
        VSPGeometryParser(missing).parse()
