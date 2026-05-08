from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

from scripts import tier2_loaded_shape_airfoil_mvp as mvp4


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _record(
    *,
    airfoil_id: str,
    zone_hint: str,
    cd0: float,
    source_quality: str = "full_polar_mission_grade_candidate",
) -> dict[str, object]:
    points = []
    for re_value in (250_000.0, 400_000.0, 600_000.0):
        for cl_value in (0.1, 0.5, 0.9, 1.3, 1.6):
            points.append(
                {
                    "Re": re_value,
                    "cl": cl_value,
                    "cd": cd0 + 0.002 * (cl_value - 0.8) ** 2,
                    "cm": -0.04,
                    "alpha_deg": -2.0 + cl_value * 8.0,
                    "roughness_mode": "clean",
                }
            )
    return {
        "airfoil_id": airfoil_id,
        "name": airfoil_id,
        "source": "unit_test",
        "source_quality": source_quality,
        "zone_hint": zone_hint,
        "thickness_ratio": 0.12,
        "max_camber": 0.03,
        "alpha_L0_deg": -2.0,
        "cl_alpha_per_rad": 2.0 * math.pi,
        "cm_design": -0.04,
        "safe_clmax": 1.5,
        "usable_clmax": 1.65,
        "polar_points": points,
        "notes": "unit test full-alpha fixture",
    }


def _write_tier2_db(path: Path) -> None:
    records = []
    for zone in ("root", "mid1", "mid2", "tip"):
        records.append(_record(airfoil_id=f"{zone}_raw_low_cd", zone_hint=zone, cd0=0.009))
        records.append(_record(airfoil_id=f"{zone}_conservative", zone_hint=zone, cd0=0.010))
    records.append(
        _record(
            airfoil_id="root_not_mission_grade_fast",
            zone_hint="root",
            cd0=0.006,
            source_quality="full_polar_candidate_not_mission_grade",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"records": records}, indent=2) + "\n", encoding="utf-8")


def _write_stage6(stage6_dir: Path) -> None:
    local_rows = [
        {
            "case_label": "loaded_case",
            "eta": eta,
            "y_m": eta * 10.0,
            "chord_m": chord,
            "local_cl": cl,
            "reynolds": reynolds,
            "velocity_mps": 6.6,
            "density_kgpm3": 1.18,
            "dynamic_viscosity_pa_s": 1.7228e-5,
            "geometry_z_basis": "unit_test_loaded_shape",
        }
        for eta, chord, cl, reynolds in (
            (0.0, 1.2, 1.25, 545_000.0),
            (0.2, 1.1, 1.28, 500_000.0),
            (0.4, 1.0, 1.20, 455_000.0),
            (0.65, 0.82, 1.0, 375_000.0),
            (0.85, 0.70, 0.75, 320_000.0),
            (1.0, 0.65, 0.25, 295_000.0),
        )
    ]
    _write_csv(stage6_dir / "loaded_shape_local_cl_re_envelope.csv", local_rows)
    _write_csv(
        stage6_dir / "loaded_shape_avl_recheck.csv",
        [
            {
                "case_label": "loaded_case",
                "status": "rechecked_for_screening",
                "loaded_shape_CDi": 0.012,
                "pre_structure_cl": 1.16,
                "loaded_shape_alpha_deg": -0.4,
                "loaded_shape_local_cl_re_envelope_csv": str(
                    (stage6_dir / "loaded_shape_local_cl_re_envelope.csv").resolve()
                ),
            }
        ],
    )


def test_stage6_rows_are_converted_to_zone_requirements_from_actual_loaded_cl() -> None:
    rows = [
        {"eta": "0.0", "local_cl": "1.2", "reynolds": "500000", "chord_m": "1.1", "y_m": "0.0"},
        {"eta": "0.3", "local_cl": "1.1", "reynolds": "450000", "chord_m": "1.0", "y_m": "3.0"},
    ]

    converted = mvp4.stage6_rows_for_airfoil_sidecar(rows)

    assert converted[0]["avl_local_cl"] == pytest.approx(1.2)
    assert converted[0]["cl_actual_avl"] == pytest.approx(1.2)
    assert "fourier_target_cl" not in converted[0]


def test_run_mvp_writes_assignment_combo_and_profile_artifacts_without_avl(tmp_path: Path) -> None:
    stage6_dir = tmp_path / "stage6"
    output_dir = tmp_path / "mvp4"
    db_path = tmp_path / "tier2" / "airfoil_database.json"
    _write_stage6(stage6_dir)
    _write_tier2_db(db_path)

    paths = mvp4.run_mvp(
        stage6_dir=stage6_dir,
        tier2_database_json=db_path,
        output_dir=output_dir,
        rerun_avl=False,
        top_k_per_zone=2,
        max_combo_count=16,
    )

    assignment = json.loads(paths["assignment"].read_text(encoding="utf-8"))
    combo_rows = list(csv.DictReader(paths["combo_search"].open(encoding="utf-8")))
    profile_rows = list(csv.DictReader(paths["profile_drag"].open(encoding="utf-8")))
    report = paths["report"].read_text(encoding="utf-8")

    assert assignment["schema_version"] == mvp4.SCHEMA_VERSION
    assert assignment["cl_re_source"] == "stage6_loaded_shape_avl_actual_local_cl_re"
    assert assignment["raw_best"]["assignment"]
    assert assignment["conservative_best"]["assignment"]
    assert combo_rows
    assert {row["cl_source_shape_mode"] for row in combo_rows} == {"loaded_dihedral_avl"}
    assert all("fourier" not in row["cl_source_shape_mode"] for row in combo_rows)
    assert profile_rows
    assert {row["selected_role"] for row in profile_rows} >= {"raw_best", "conservative_best"}
    assert "No broad CST/NSGA rerun" in report
