from __future__ import annotations

import csv
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from scripts.go_mode_main_wing_closed_loop_final import (
    ReferenceStructuralMetrics,
    build_candidate_fem_spec_from_csv,
    evaluate_fem_support,
    estimate_first_fail,
    estimate_load_factor_rows,
)


def test_estimate_load_factor_rows_scales_linear_response_and_first_fail() -> None:
    reference = ReferenceStructuralMetrics(
        reference_load_factor=2.0,
        failure_index=-0.5,
        buckling_index=-0.75,
        tip_deflection_m=1.0,
        tip_deflection_limit_m=2.5,
        twist_max_deg=0.2,
        twist_limit_deg=2.0,
        wire_tension_n=100.0,
        wire_allowable_n=250.0,
        root_vertical_resultant_n=500.0,
        root_bending_moment_n_m=1000.0,
    )

    rows = estimate_load_factor_rows(reference, load_factors=(1.0, 1.5, 2.0))

    assert rows[0].load_factor == 1.0
    assert rows[0].failure_index == pytest.approx(-0.75)
    assert rows[1].failure_index == pytest.approx(-0.625)
    assert rows[2].tip_deflection_m == pytest.approx(1.0)
    assert rows[2].wire_tension_margin_n == pytest.approx(150.0)

    first_fail = estimate_first_fail(reference)
    assert first_fail.mode == "stress"
    assert first_fail.load_factor == pytest.approx(4.0)


def test_build_candidate_fem_spec_from_csv_uses_candidate_geometry_and_scaled_loads(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "jig_shape_spar_data.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Node",
                "Y_Position_m",
                "Main_X_m",
                "Main_Z_m",
                "Main_Outer_Radius_m",
                "Main_Wall_Thickness_m",
                "Rear_X_m",
                "Rear_Z_m",
                "Rear_Outer_Radius_m",
                "Rear_Wall_Thickness_m",
                "Main_FZ_N",
                "Rear_FZ_N",
                "Is_Joint",
                "Is_Wire_Attach",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "Node": 1,
                "Y_Position_m": 0.0,
                "Main_X_m": 0.25,
                "Main_Z_m": 0.1,
                "Main_Outer_Radius_m": 0.04,
                "Main_Wall_Thickness_m": 0.001,
                "Rear_X_m": 0.7,
                "Rear_Z_m": 0.08,
                "Rear_Outer_Radius_m": 0.02,
                "Rear_Wall_Thickness_m": 0.001,
                "Main_FZ_N": 20.0,
                "Rear_FZ_N": -2.0,
                "Is_Joint": 1,
                "Is_Wire_Attach": 0,
            }
        )
        writer.writerow(
            {
                "Node": 2,
                "Y_Position_m": 1.0,
                "Main_X_m": 0.2,
                "Main_Z_m": 0.2,
                "Main_Outer_Radius_m": 0.02,
                "Main_Wall_Thickness_m": 0.003,
                "Rear_X_m": 0.6,
                "Rear_Z_m": 0.18,
                "Rear_Outer_Radius_m": 0.012,
                "Rear_Wall_Thickness_m": 0.002,
                "Main_FZ_N": 10.0,
                "Rear_FZ_N": -1.0,
                "Is_Joint": 0,
                "Is_Wire_Attach": 1,
            }
        )

    spec = build_candidate_fem_spec_from_csv(
        csv_path=csv_path,
        load_scale=0.5,
        main_material_name="main",
        rear_material_name="rear",
        young_pa=100.0,
        poisson_ratio=0.25,
        density_kgpm3=2.0,
    )

    assert spec.y_nodes_m.tolist() == [0.0, 1.0]
    assert spec.main_outer_radius_m.tolist() == pytest.approx([0.03])
    assert spec.main_thickness_m.tolist() == pytest.approx([0.002])
    assert spec.main_nodal_fz_n.tolist() == pytest.approx([10.0, 5.0])
    assert spec.rear_nodal_fz_n.tolist() == pytest.approx([-1.0, -0.5])
    assert spec.joint_node_indices == (0,)
    assert spec.wire_node_indices == (1,)


def test_evaluate_fem_support_requires_tip_deflection_scale_agreement() -> None:
    reference = ReferenceStructuralMetrics(
        reference_load_factor=2.0,
        failure_index=-0.5,
        buckling_index=-0.75,
        tip_deflection_m=1.5,
        tip_deflection_limit_m=2.5,
        twist_max_deg=0.2,
        twist_limit_deg=2.0,
        wire_tension_n=100.0,
        wire_allowable_n=250.0,
        root_vertical_resultant_n=500.0,
        root_bending_moment_n_m=1000.0,
    )
    load_rows = estimate_load_factor_rows(reference, load_factors=(2.0,))

    blocked = evaluate_fem_support(
        load_rows,
        [
            {
                "load_factor": 2.0,
                "calculix_status": "ran",
                "tip_main_uz_m": 0.08,
                "tip_rear_uz_m": -0.07,
            }
        ],
    )
    assert blocked.final_code.startswith("C.")
    assert "mismatch" in blocked.confidence_label

    supported = evaluate_fem_support(
        load_rows,
        [
            {
                "load_factor": 2.0,
                "calculix_status": "ran",
                "tip_main_uz_m": 1.45,
                "tip_rear_uz_m": -1.40,
            }
        ],
    )
    assert supported.final_code.startswith("A.")
    assert supported.tip_mismatch_fraction < 0.25
