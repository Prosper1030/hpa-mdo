from __future__ import annotations

from pathlib import Path

import pytest

from scripts.phase20_rear_spar_torsion_audit import (
    build_rear_spar_torsion_audit,
    spar_pair_line_angle_delta_deg,
    tube_i_m4,
    tube_j_m4,
    write_rear_spar_torsion_audit_package,
)


def _jig_rows() -> list[dict[str, str]]:
    return [
        {
            "Node": "1",
            "Y_Position_m": "0.0",
            "Main_X_m": "0.0",
            "Main_Z_m": "0.0",
            "Main_Outer_Radius_m": "0.040",
            "Main_Wall_Thickness_m": "0.002",
            "Rear_X_m": "1.0",
            "Rear_Z_m": "0.0",
            "Rear_Outer_Radius_m": "0.020",
            "Rear_Wall_Thickness_m": "0.001",
            "Is_Joint": "0",
            "Is_Wire_Attach": "0",
        },
        {
            "Node": "2",
            "Y_Position_m": "0.5",
            "Main_X_m": "0.0",
            "Main_Z_m": "0.0",
            "Main_Outer_Radius_m": "0.040",
            "Main_Wall_Thickness_m": "0.002",
            "Rear_X_m": "1.0",
            "Rear_Z_m": "0.0",
            "Rear_Outer_Radius_m": "0.020",
            "Rear_Wall_Thickness_m": "0.001",
            "Is_Joint": "1",
            "Is_Wire_Attach": "0",
        },
        {
            "Node": "3",
            "Y_Position_m": "1.0",
            "Main_X_m": "0.0",
            "Main_Z_m": "0.0",
            "Main_Outer_Radius_m": "0.040",
            "Main_Wall_Thickness_m": "0.002",
            "Rear_X_m": "1.0",
            "Rear_Z_m": "0.0",
            "Rear_Outer_Radius_m": "0.020",
            "Rear_Wall_Thickness_m": "0.001",
            "Is_Joint": "0",
            "Is_Wire_Attach": "0",
        },
    ]


def _loaded_rows() -> list[dict[str, str]]:
    rows = [dict(row) for row in _jig_rows()]
    rows[0]["Rear_Z_m"] = "0.0"
    rows[1]["Rear_Z_m"] = "0.1"
    rows[2]["Rear_Z_m"] = "0.2"
    return rows


def test_tube_section_formulas_use_hollow_circular_geometry() -> None:
    ro = 0.04
    ri = 0.038
    expected_i = pytest.approx(3.141592653589793 / 4.0 * (ro**4 - ri**4))
    expected_j = pytest.approx(3.141592653589793 / 2.0 * (ro**4 - ri**4))

    assert tube_i_m4(ro, 0.002) == expected_i
    assert tube_j_m4(ro, 0.002) == expected_j


def test_spar_pair_line_angle_delta_removes_root_offset() -> None:
    angle_delta = spar_pair_line_angle_delta_deg(_jig_rows(), _loaded_rows())

    assert angle_delta[0] == pytest.approx(0.0)
    assert angle_delta[-1] == pytest.approx(11.30993247, rel=1.0e-6)


def test_rear_spar_torsion_audit_marks_stiffness_as_report_only() -> None:
    audit = build_rear_spar_torsion_audit(
        "sample",
        jig_rows=_jig_rows(),
        loaded_rows=_loaded_rows(),
        young_pa=70.0e9,
        shear_pa=27.0e9,
        nominal_rib_bay_m=0.30,
        equivalent_twist_max_deg=0.2,
    )

    assert audit.overall_status == "rear_spar_and_torsion_not_signoff"
    assert audit.rear_bending_stiffness_fraction_mean > 0.0
    assert audit.rear_torsion_tube_stiffness_fraction_mean > 0.0
    assert audit.max_spar_pair_line_angle_delta_deg == pytest.approx(11.30993247, rel=1.0e-6)
    assert audit.equivalent_twist_max_deg == pytest.approx(0.2)
    by_key = {entry.key: entry for entry in audit.entries}
    assert by_key["rear_spar_stiffness"].status == "section_stiffness_present_global_role_unproven"
    assert by_key["torsion_twist_coupling"].status == "geometry_angle_observed_aeroelastic_loop_unproven"
    assert by_key["rib_spacing_assumption"].status == "mandatory_station_bay_exceeds_nominal_rib_bay"


def test_write_rear_spar_torsion_audit_package_creates_handoff_files(tmp_path: Path) -> None:
    outputs = write_rear_spar_torsion_audit_package(
        tmp_path,
        "sample",
        jig_rows=_jig_rows(),
        loaded_rows=_loaded_rows(),
        young_pa=70.0e9,
        shear_pa=27.0e9,
        nominal_rib_bay_m=0.30,
        equivalent_twist_max_deg=0.2,
    )

    assert {path.name for path in outputs} == {
        "rear_spar_torsion_audit.csv",
        "rear_spar_torsion_audit.json",
        "rear_spar_torsion_audit.md",
    }
    report = (tmp_path / "rear_spar_torsion_audit.md").read_text(encoding="utf-8")
    assert "rear spar section stiffness exists" in report
    assert "aeroelastic twist loop is not closed" in report
    assert "not aero twist" in report
    assert "0.30 m nominal rib-bay" in report
