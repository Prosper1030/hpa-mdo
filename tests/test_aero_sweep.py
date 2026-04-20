from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from hpa_mdo.aero.aero_sweep import (
    build_vspaero_sweep_points,
    load_su2_alpha_sweep,
    sweep_points_to_dataframe,
)


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def test_build_vspaero_sweep_points_uses_polar_coefficients_and_lod_reference_values(tmp_path: Path) -> None:
    lod_path = _write_text(
        tmp_path / "origin.lod",
        """
        Sref_ 35.1750000 Lunit^2
        Bref_ 33.0000000 Lunit
        Cref_ 1.0425000 Lunit
        Rho_ 1.2250000 Munit/Lunit^3
        Vinf_ 6.5000000 Lunit/Tunit
        """,
    )
    polar_path = _write_text(
        tmp_path / "origin.polar",
        """
        Beta Mach AoA Re/1e6 CLo CLi CLtot CDo CDi CDtot CSo CSi CStot L/D E CMox CMoy CMoz CMix CMiy CMiz CMxtot CMytot CMztot
        0.0 0.0 -2.0 0.46 -0.0002 0.8463 0.8461 0.0182 0.0084 0.0266 0.0 0.0 0.0 31.7 0.87 0.0 0.0040 0.0 0.0 -0.4033 0.0 0.0 -0.3992 0.0
        0.0 0.0  0.0 0.46 -0.0010 1.0577 1.0567 0.0206 0.0127 0.0333 0.0 0.0 0.0 31.7 0.90 0.0 0.0045 0.0 0.0 -0.4943 0.0 0.0 -0.4898 0.0
        """,
    )

    points = build_vspaero_sweep_points(lod_path=lod_path, polar_path=polar_path)

    assert [point.alpha_deg for point in points] == [-2.0, 0.0]
    assert all(point.solver == "vspaero" for point in points)
    assert points[0].cl == pytest.approx(0.8461)
    assert points[0].cd == pytest.approx(0.0266)
    assert points[0].cm == pytest.approx(0.0040)

    q = 0.5 * 1.225 * 6.5**2
    expected_lift = q * 35.175 * 0.8461
    expected_drag = q * 35.175 * 0.0266
    assert points[0].lift_n == pytest.approx(expected_lift)
    assert points[0].drag_n == pytest.approx(expected_drag)

    df = sweep_points_to_dataframe(points)
    assert list(df.columns) == [
        "solver",
        "alpha_deg",
        "cl",
        "cd",
        "cm",
        "lift_n",
        "drag_n",
        "source_path",
        "notes",
    ]
    assert df["alpha_deg"].tolist() == [-2.0, 0.0]


def test_load_su2_alpha_sweep_reads_csv_and_dat_cases_and_derives_alpha_from_name_or_cfg(
    tmp_path: Path,
) -> None:
    alpha_from_name = tmp_path / "alpha_m2p0"
    _write_text(
        alpha_from_name / "history.csv",
        """
        "Time_Iter","Inner_Iter","CD","CL","CMy"
        0,49,0.0210,0.8400,-0.0310
        """,
    )
    _write_text(
        alpha_from_name / "su2_runtime.cfg",
        """
        REF_AREA= 35.175
        INC_DENSITY_INIT= 1.225
        INC_VELOCITY_INIT= ( 6.5, 0.0, 0.0 )
        """,
    )
    _write_text(
        alpha_from_name / "case_metadata.json",
        """
        {
          "mesh_preset": "study_medium"
        }
        """,
    )

    alpha_from_cfg = tmp_path / "trimmed_case"
    _write_text(
        alpha_from_cfg / "history.dat",
        """
        ITER,DRAG,LIFT,MOMENT_Y
        50,0.0330,1.1000,-0.0400
        """,
    )
    _write_text(
        alpha_from_cfg / "su2_runtime.cfg",
        """
        AOA= 2.0
        REF_AREA= 35.175
        INC_DENSITY_INIT= 1.225
        INC_VELOCITY_INIT= ( 6.5, 0.0, 0.0 )
        """,
    )
    _write_text(
        tmp_path / "su2_run_summary.json",
        """
        {
          "cases": [
            {
              "case_name": "alpha_m2p0",
              "status": "completed_but_weak"
            }
          ]
        }
        """,
    )

    points = load_su2_alpha_sweep(tmp_path)

    assert [point.alpha_deg for point in points] == [-2.0, 2.0]
    assert all(point.solver == "su2" for point in points)
    assert points[0].cd == pytest.approx(0.0210)
    assert points[0].cl == pytest.approx(0.8400)
    assert points[0].cm == pytest.approx(-0.0310)
    assert points[1].cd == pytest.approx(0.0330)
    assert points[1].cl == pytest.approx(1.1000)
    assert points[1].cm == pytest.approx(-0.0400)

    q = 0.5 * 1.225 * 6.5**2
    assert points[0].drag_n == pytest.approx(q * 35.175 * 0.0210)
    assert points[1].lift_n == pytest.approx(q * 35.175 * 1.1000)

    df = sweep_points_to_dataframe(points)
    assert isinstance(df, pd.DataFrame)
    assert df["solver"].tolist() == ["su2", "su2"]
    assert math.isfinite(float(df.iloc[0]["drag_n"]))
    assert "alpha_source=case_name" in points[0].notes
    assert "run_status=completed_but_weak" in points[0].notes
    assert "mesh_preset=study_medium" in points[0].notes
