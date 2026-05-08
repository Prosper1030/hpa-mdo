from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts import aero_structure_closure_mvp as closure


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


def test_closure_status_prefers_airfoil_loopback_for_query_warnings() -> None:
    status = closure.closure_status(
        actual_query_quality="actual_loaded_shape_query_warning_not_mission_grade",
        structure_run_succeeded=True,
        spanload_delta_pct=1.0,
        e_cdi_delta_pct=1.0,
        mass_delta_pct=1.0,
        deflection_delta_pct=1.0,
        clearance_margin_m=0.04,
    )

    assert status == "loop_back_to_airfoil_selection"


def test_closure_status_reports_minor_mismatch_for_small_clean_deltas() -> None:
    status = closure.closure_status(
        actual_query_quality="actual_loaded_shape_query_pass",
        structure_run_succeeded=True,
        spanload_delta_pct=2.5,
        e_cdi_delta_pct=2.0,
        mass_delta_pct=1.0,
        deflection_delta_pct=1.5,
        clearance_margin_m=0.03,
    )

    assert status == "minor_mismatch"


def test_run_mvp_writes_summary_report_and_loopback_with_existing_structure_fixture(
    tmp_path: Path,
) -> None:
    stage2_dir = tmp_path / "stage2"
    mvp4_dir = tmp_path / "mvp4"
    output_dir = tmp_path / "closure"
    structure_summary = tmp_path / "structure_summary.json"
    _write_csv(
        stage2_dir / "z_state_structure_budget_sweep.csv",
        [
            {
                "case_label": "target_main_tip_z_4p250m",
                "target_shape_z_scale_generator": 3.99,
                "dihedral_exponent": 1.0,
                "config_path": "/tmp/config.yaml",
                "design_report": "/tmp/design.txt",
                "target_main_tip_z_m": 4.25,
                "tube_mass_kg": 10.0,
                "total_structural_mass_kg": 12.5,
                "jig_ground_clearance_min_m": 0.04,
                "equivalent_tip_deflection_m": 2.9,
                "wire_tension_n": 3000.0,
                "loaded_shape_error": 0.0,
                "loaded_shape_csv": "/tmp/loaded.csv",
            }
        ],
    )
    _write_csv(
        stage2_dir / "feasible_loaded_shape_shortlist.csv",
        [{"case_label": "target_main_tip_z_4p250m"}],
    )
    _write_csv(
        tmp_path / "stage6" / "loaded_shape_avl_recheck.csv",
        [
            {
                "case_label": "target_main_tip_z_4p250m",
                "loaded_shape_CDi": 0.0120,
                "loaded_shape_e_CDi": 1.0,
                "loaded_shape_spanload_comparison_csv": str(
                    (tmp_path / "stage6" / "loaded_shape_spanload_comparison.csv").resolve()
                ),
            }
        ],
    )
    _write_csv(
        tmp_path / "stage6" / "loaded_shape_spanload_comparison.csv",
        [
            {"y_m": 0.0, "loaded_shape_lift_per_span_npm": 10.0},
            {"y_m": 1.0, "loaded_shape_lift_per_span_npm": 20.0},
        ],
    )
    (mvp4_dir / "tier2_loaded_shape_airfoil_assignment.json").parent.mkdir(parents=True)
    (mvp4_dir / "tier2_loaded_shape_airfoil_assignment.json").write_text(
        json.dumps(
            {
                "selected_avl_reruns": [
                    {
                        "selected_role": "conservative_best",
                        "assignment": "root:a|mid1:b|mid2:c|tip:d",
                        "status": "selected_assignment_avl_rerun_ok",
                        "CDi": 0.0121,
                        "e_CDi": 0.99,
                        "profile_cd": 0.009,
                        "P_crank": 170.0,
                        "P_crank_conservative": 175.0,
                        "actual_query_quality": "actual_loaded_shape_query_pass",
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    structure_summary.write_text(
        json.dumps(
            {
                "iterations": [
                    {
                        "selected": {
                            "overall_feasible": True,
                            "tube_mass_kg": 10.2,
                            "total_structural_mass_kg": 12.7,
                            "jig_ground_clearance_min_m": 0.039,
                            "equivalent_tip_deflection_m": 2.95,
                            "loaded_shape_main_z_error_max_m": 0.002,
                        }
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    paths = closure.run_mvp(
        stage2_dir=stage2_dir,
        stage6_dir=tmp_path / "stage6",
        mvp4_dir=mvp4_dir,
        output_dir=output_dir,
        run_structure=False,
        fixture_structure_summary_by_role={"conservative_best": structure_summary},
        fixture_selected_spanload_by_role={
            "conservative_best": [
                {"y_m": 0.0, "lift_per_span_npm": 10.0},
                {"y_m": 1.0, "lift_per_span_npm": 21.0},
            ]
        },
    )

    summary_rows = list(csv.DictReader(paths["summary"].open(encoding="utf-8")))
    assert summary_rows[0]["selected_role"] == "conservative_best"
    assert summary_rows[0]["closure_status"] in {
        "closed_for_screening",
        "minor_mismatch",
    }
    assert paths["report"].read_text(encoding="utf-8").startswith("# Aero-Structure Closure MVP")
    assert "loopback" in paths["loopback"].read_text(encoding="utf-8").lower()
