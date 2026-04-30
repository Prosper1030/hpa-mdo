import json
from pathlib import Path

import pytest

from hpa_meshing.main_wing_geometry_provenance_probe import (
    build_main_wing_geometry_provenance_probe_report,
    write_main_wing_geometry_provenance_probe_report,
)


def _write_vsp_fixture(path: Path) -> Path:
    path.write_text(
        """<Vehicle>
  <Geom>
    <ParmContainer>
      <ID>IPAWXFWPQF</ID>
      <Name>Main Wing</Name>
      <XForm>
        <X_Rotation Value="0.0"/>
        <Y_Rotation Value="3.0"/>
        <Z_Rotation Value="0.0"/>
      </XForm>
    </ParmContainer>
    <WingGeom>
      <XSecSurf>
        <XSec>
          <ParmContainer>
            <XSec>
              <Span Value="1.0"/>
              <Root_Chord Value="1.0"/>
              <Tip_Chord Value="1.3"/>
              <Twist Value="0.0"/>
              <Dihedral Value="0.0"/>
              <Sweep Value="0.0"/>
            </XSec>
          </ParmContainer>
          <XSec>
            <XSecCurve>
              <FileAirfoil>
                <AirfoilName>FX 76-MP-140</AirfoilName>
                <UpperPnts>0, 0, 0, 0.5, 0.12, 0, 1, 0, 0,</UpperPnts>
                <LowerPnts>0, 0, 0, 0.5, -0.02, 0, 1, 0, 0,</LowerPnts>
              </FileAirfoil>
            </XSecCurve>
          </XSec>
        </XSec>
        <XSec>
          <ParmContainer>
            <XSec>
              <Span Value="2.0"/>
              <Root_Chord Value="1.3"/>
              <Tip_Chord Value="0.8"/>
              <Twist Value="0.0"/>
              <Dihedral Value="2.0"/>
              <Sweep Value="1.0"/>
            </XSec>
          </ParmContainer>
          <XSec>
            <XSecCurve>
              <FileAirfoil>
                <AirfoilName>CLARK-Y 11.7% smoothed</AirfoilName>
                <UpperPnts>0, 0, 0, 0.5, 0.1, 0, 1, 0, 0,</UpperPnts>
                <LowerPnts>0, 0, 0, 0.5, -0.04, 0, 1, 0, 0,</LowerPnts>
              </FileAirfoil>
            </XSecCurve>
          </XSec>
        </XSec>
      </XSecSurf>
    </WingGeom>
  </Geom>
</Vehicle>
""",
        encoding="utf-8",
    )
    return path


def test_main_wing_geometry_provenance_probe_records_incidence_twist_and_camber(
    tmp_path: Path,
):
    source = _write_vsp_fixture(tmp_path / "wing.vsp3")

    report = build_main_wing_geometry_provenance_probe_report(source_path=source)

    assert report.geometry_provenance_status == "provenance_available"
    assert report.selected_geom_name == "Main Wing"
    assert report.installation_incidence_deg == 3.0
    assert report.twist_summary["all_sections_zero_twist"] is True
    assert report.airfoil_summary["cambered_airfoil_coordinates_observed"] is True
    assert report.airfoil_summary["max_abs_camber_over_chord"] == pytest.approx(0.05)
    assert report.sections[0].airfoil_name == "FX 76-MP-140"
    assert report.sections[0].airfoil_max_thickness_over_chord == pytest.approx(0.14)
    assert (
        report.alpha_zero_interpretation
        == "alpha_zero_expected_positive_lift_but_not_acceptance_lift"
    )


def test_main_wing_geometry_provenance_probe_reports_missing_main_wing(tmp_path: Path):
    source = tmp_path / "empty.vsp3"
    source.write_text("<Vehicle><Geom><ParmContainer><Name>Tail</Name></ParmContainer></Geom></Vehicle>")

    report = build_main_wing_geometry_provenance_probe_report(source_path=source)

    assert report.geometry_provenance_status == "provenance_missing"
    assert report.error == "Main Wing geometry not found"


def test_write_main_wing_geometry_provenance_probe_report(tmp_path: Path):
    source = _write_vsp_fixture(tmp_path / "wing.vsp3")
    out_dir = tmp_path / "report"

    written = write_main_wing_geometry_provenance_probe_report(
        out_dir,
        source_path=source,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == "main_wing_geometry_provenance_probe.v1"
    assert payload["installation_incidence_deg"] == 3.0
    assert "Main Wing Geometry Provenance Probe v1" in markdown
