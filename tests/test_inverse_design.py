from __future__ import annotations

import csv
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.structure.inverse_design import (
    StructuralNodeShape,
    build_frozen_load_inverse_design,
    build_inverse_design_margins,
    write_shape_csv_from_template,
)


class InverseDesignTests(unittest.TestCase):
    def test_build_frozen_load_inverse_design_backsolves_jig_shape_and_margins(self) -> None:
        target = StructuralNodeShape(
            main_nodes_m=np.array(
                [
                    [0.0, 0.0, 0.0],
                    [0.0, 1.0, 0.30],
                    [0.0, 2.0, 0.70],
                ],
                dtype=float,
            ),
            rear_nodes_m=np.array(
                [
                    [1.0, 0.0, 0.0],
                    [1.0, 1.0, 0.25],
                    [1.0, 2.0, 0.60],
                ],
                dtype=float,
            ),
        )
        disp_main = np.array(
            [
                [0.0, 0.0, 0.00, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.10, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.20, 0.0, 0.0, 0.0],
            ],
            dtype=float,
        )
        disp_rear = np.array(
            [
                [0.0, 0.0, 0.00, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.08, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.16, 0.0, 0.0, 0.0],
            ],
            dtype=float,
        )

        result = build_frozen_load_inverse_design(
            target_loaded_shape=target,
            disp_main_m=disp_main,
            disp_rear_m=disp_rear,
            y_nodes_m=np.array([0.0, 1.0, 2.0], dtype=float),
            analysis_succeeded=True,
            geometry_validity_passed=True,
            equivalent_failure_passed=True,
            equivalent_buckling_passed=True,
            equivalent_tip_passed=True,
            equivalent_twist_passed=True,
            clearance_floor_z_m=0.0,
            target_shape_error_tol_m=1.0e-9,
            max_abs_vertical_prebend_m=0.25,
            max_abs_vertical_curvature_per_m=0.01,
        )

        self.assertTrue(np.allclose(result.jig_shape.main_nodes_m[:, 2], [0.0, 0.20, 0.50]))
        self.assertTrue(np.allclose(result.jig_shape.rear_nodes_m[:, 2], [0.0, 0.17, 0.44]))
        self.assertAlmostEqual(result.target_shape_error.max_abs_error_m, 0.0)
        self.assertTrue(result.target_shape_error.passed)
        self.assertAlmostEqual(result.ground_clearance.min_z_m, 0.0)
        self.assertAlmostEqual(result.ground_clearance.margin_m, 0.0)
        self.assertAlmostEqual(result.manufacturing.max_abs_vertical_prebend_m, 0.20)
        self.assertAlmostEqual(result.manufacturing.max_abs_vertical_curvature_per_m, 0.0)
        self.assertTrue(result.feasibility.overall_feasible)

        margins = build_inverse_design_margins(result)
        self.assertAlmostEqual(margins["target_shape_error_margin_m"], 1.0e-9)
        self.assertAlmostEqual(margins["ground_clearance_margin_m"], 0.0)
        self.assertAlmostEqual(margins["jig_prebend_margin_m"], 0.05)
        self.assertAlmostEqual(margins["jig_curvature_margin_per_m"], 0.01)

    def test_build_frozen_load_inverse_design_flags_ground_and_manufacturing_failures(self) -> None:
        target = StructuralNodeShape(
            main_nodes_m=np.array(
                [
                    [0.0, 0.0, 0.0],
                    [0.0, 1.0, 0.10],
                    [0.0, 2.0, 0.10],
                ],
                dtype=float,
            ),
            rear_nodes_m=np.array(
                [
                    [1.0, 0.0, 0.0],
                    [1.0, 1.0, 0.12],
                    [1.0, 2.0, 0.12],
                ],
                dtype=float,
            ),
        )
        disp_main = np.array(
            [
                [0.0, 0.0, 0.00, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.12, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.36, 0.0, 0.0, 0.0],
            ],
            dtype=float,
        )
        disp_rear = np.array(
            [
                [0.0, 0.0, 0.00, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.10, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.34, 0.0, 0.0, 0.0],
            ],
            dtype=float,
        )

        result = build_frozen_load_inverse_design(
            target_loaded_shape=target,
            disp_main_m=disp_main,
            disp_rear_m=disp_rear,
            y_nodes_m=np.array([0.0, 1.0, 2.0], dtype=float),
            analysis_succeeded=True,
            geometry_validity_passed=True,
            equivalent_failure_passed=True,
            equivalent_buckling_passed=True,
            equivalent_tip_passed=True,
            equivalent_twist_passed=True,
            clearance_floor_z_m=0.0,
            target_shape_error_tol_m=1.0e-9,
            max_abs_vertical_prebend_m=0.20,
            max_abs_vertical_curvature_per_m=0.10,
        )

        self.assertFalse(result.ground_clearance.passed)
        self.assertFalse(result.manufacturing.prebend_passed)
        self.assertFalse(result.manufacturing.curvature_passed)
        self.assertIn("ground_clearance", result.feasibility.failures)
        self.assertIn("jig_prebend", result.feasibility.failures)
        self.assertIn("jig_curvature", result.feasibility.failures)

    def test_write_shape_csv_from_template_rewrites_main_and_rear_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            template_path = tmp_dir / "template.csv"
            with template_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "Y_Position_m",
                        "Main_X_m",
                        "Main_Z_m",
                        "Rear_X_m",
                        "Rear_Z_m",
                        "Main_Outer_Radius_m",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "Y_Position_m": "0.0",
                        "Main_X_m": "0.2",
                        "Main_Z_m": "0.0",
                        "Rear_X_m": "0.8",
                        "Rear_Z_m": "0.0",
                        "Main_Outer_Radius_m": "0.03",
                    }
                )
                writer.writerow(
                    {
                        "Y_Position_m": "1.0",
                        "Main_X_m": "0.2",
                        "Main_Z_m": "0.1",
                        "Rear_X_m": "0.8",
                        "Rear_Z_m": "0.1",
                        "Main_Outer_Radius_m": "0.03",
                    }
                )

            shape = StructuralNodeShape(
                main_nodes_m=np.array([[0.25, 0.0, 0.01], [0.30, 1.0, 0.22]], dtype=float),
                rear_nodes_m=np.array([[0.82, 0.0, 0.03], [0.90, 1.0, 0.28]], dtype=float),
            )
            output_path = tmp_dir / "jig.csv"
            write_shape_csv_from_template(
                template_csv_path=template_path,
                output_csv_path=output_path,
                shape=shape,
            )

            with output_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(rows[0]["Y_Position_m"], "0")
            self.assertEqual(rows[0]["Main_X_m"], "0.25")
            self.assertEqual(rows[0]["Main_Z_m"], "0.01")
            self.assertEqual(rows[0]["Rear_X_m"], "0.82")
            self.assertEqual(rows[0]["Rear_Z_m"], "0.03")
            self.assertEqual(rows[1]["Main_Outer_Radius_m"], "0.03")


if __name__ == "__main__":
    unittest.main()
