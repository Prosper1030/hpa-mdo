from __future__ import annotations

import csv
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.structure.inverse_design import (
    StructuralNodeShape,
    check_monotonic_deflection,
    build_frozen_load_inverse_design,
    build_frozen_load_inverse_design_from_mainline,
    build_inverse_design_margins,
    build_target_loaded_shape,
    write_shape_csv_from_template,
)
from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.core import MaterialDB
from scripts.direct_dual_beam_inverse_design import (
    CandidateArchive,
    InverseCandidate,
    LightweightLoadRefreshModel,
    _build_arg_parser,
    _clearance_risk_metrics,
    _lift_wire_rigging_records,
    _mapped_load_delta_metrics,
    _write_deflection_csv,
)


class InverseDesignTests(unittest.TestCase):
    @staticmethod
    def _make_inverse_candidate(
        *,
        mass_kg: float,
        source: str,
        feasible: bool,
        violation: float,
    ) -> InverseCandidate:
        zeros = np.zeros(2, dtype=float)
        z = np.array([mass_kg, violation, float(feasible), 0.0, 0.0], dtype=float) * 1.0e-3
        return InverseCandidate(
            z=z,
            source=source,
            message="ok",
            eval_wall_time_s=0.0,
            main_plateau_scale=1.0,
            main_taper_fill=1.0,
            rear_radius_scale=1.0,
            rear_outboard_fraction=1.0,
            wall_thickness_fraction=1.0,
            main_t_seg_m=zeros.copy(),
            main_r_seg_m=zeros.copy(),
            rear_t_seg_m=zeros.copy(),
            rear_r_seg_m=zeros.copy(),
            tube_mass_kg=mass_kg,
            total_structural_mass_kg=mass_kg,
            equivalent_failure_index=-0.5,
            equivalent_buckling_index=-0.5,
            equivalent_tip_deflection_m=0.0,
            equivalent_twist_max_deg=0.0,
            analysis_succeeded=True,
            geometry_validity_succeeded=True,
            loaded_shape_main_z_error_max_m=0.0,
            loaded_shape_main_z_error_rms_m=0.0,
            loaded_shape_twist_error_max_deg=0.0,
            loaded_shape_twist_error_rms_deg=0.0,
            loaded_shape_normalized_error=0.0,
            loaded_shape_penalty_kg=0.0,
            clearance_risk_score=0.0,
            clearance_hotspot_count=0,
            clearance_hotspot_mean_m=0.01,
            clearance_penalty_kg=0.0,
            active_wall_risk_score=0.0,
            active_wall_tight_count=0,
            active_wall_penalty_kg=0.0,
            technically_clearance_fragile=False,
            objective_value_kg=mass_kg,
            target_shape_error_max_m=0.0,
            target_shape_error_rms_m=0.0,
            jig_ground_clearance_min_m=0.01,
            jig_ground_clearance_margin_m=0.01,
            max_jig_vertical_prebend_m=0.1,
            max_jig_vertical_curvature_per_m=0.01,
            safety_passed=feasible,
            manufacturing_passed=feasible,
            overall_feasible=feasible,
            mass_margin_kg=5.0,
            target_mass_passed=True,
            overall_target_feasible=feasible,
            failures=tuple(),
            hard_margins={"dummy": 1.0},
            hard_violation_score=violation,
            target_violation_score=violation,
            inverse_result=None,
            equivalent_result=None,
            mainline_model=None,
            production_result=None,
        )

    def test_loaded_shape_tolerance_cli_overrides_accept_new_and_legacy_flags(self) -> None:
        args = _build_arg_parser().parse_args(
            [
                "--loaded-shape-z-tol",
                "0.031",
                "--loaded-shape-twist-tol",
                "0.22",
                "--loaded-shape-main-z-tol-mm",
                "40.0",
                "--loaded-shape-twist-tol-deg",
                "0.6",
                "--dihedral-exponent",
                "2.0",
            ]
        )

        self.assertAlmostEqual(args.loaded_shape_z_tol, 0.031)
        self.assertAlmostEqual(args.loaded_shape_twist_tol, 0.22)
        self.assertAlmostEqual(args.loaded_shape_main_z_tol_mm, 40.0)
        self.assertAlmostEqual(args.loaded_shape_twist_tol_deg, 0.6)
        self.assertAlmostEqual(args.dihedral_exponent, 2.0)

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
        self.assertAlmostEqual(margins["loaded_shape_main_z_margin_m"], 0.025)
        self.assertAlmostEqual(margins["loaded_shape_twist_margin_deg"], 0.15)
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

    def test_build_frozen_load_inverse_design_keeps_equivalent_gates_as_legacy_reference_only(self) -> None:
        target = StructuralNodeShape(
            main_nodes_m=np.array(
                [
                    [0.0, 0.0, 0.0],
                    [0.0, 1.0, 0.10],
                    [0.0, 2.0, 0.25],
                ],
                dtype=float,
            ),
            rear_nodes_m=np.array(
                [
                    [1.0, 0.0, 0.0],
                    [1.0, 1.0, 0.08],
                    [1.0, 2.0, 0.22],
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
            equivalent_failure_passed=False,
            equivalent_buckling_passed=False,
            equivalent_tip_passed=False,
            equivalent_twist_passed=False,
            clearance_floor_z_m=0.0,
            target_shape_error_tol_m=1.0e-9,
            max_abs_vertical_prebend_m=0.25,
            max_abs_vertical_curvature_per_m=0.01,
        )

        self.assertTrue(result.feasibility.safety_passed)
        self.assertTrue(result.feasibility.overall_feasible)
        self.assertFalse(result.feasibility.legacy_reference_passed)
        self.assertEqual(
            result.feasibility.legacy_reference_failures,
            (
                "equivalent_failure",
                "equivalent_buckling",
                "equivalent_tip_deflection",
                "equivalent_twist",
            ),
        )
        self.assertEqual(result.feasibility.failures, ())

    def test_low_dim_loaded_shape_matching_relaxes_nodewise_closure(self) -> None:
        target = StructuralNodeShape(
            main_nodes_m=np.array(
                [
                    [0.0, 0.0, 0.00],
                    [0.0, 1.0, 0.10],
                    [0.0, 2.0, 0.25],
                    [0.0, 3.0, 0.45],
                    [0.0, 4.0, 0.70],
                ],
                dtype=float,
            ),
            rear_nodes_m=np.array(
                [
                    [1.0, 0.0, -0.05],
                    [1.0, 1.0, 0.04],
                    [1.0, 2.0, 0.18],
                    [1.0, 3.0, 0.37],
                    [1.0, 4.0, 0.61],
                ],
                dtype=float,
            ),
        )
        disp_main = np.array(
            [
                [0.0, 0.0, 0.00, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.14, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.20, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.32, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.55, 0.0, 0.0, 0.0],
            ],
            dtype=float,
        )
        disp_rear = np.array(
            [
                [0.0, 0.0, 0.00, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.10, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.14, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.24, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.43, 0.0, 0.0, 0.0],
            ],
            dtype=float,
        )

        exact = build_frozen_load_inverse_design(
            target_loaded_shape=target,
            disp_main_m=disp_main,
            disp_rear_m=disp_rear,
            y_nodes_m=np.array([0.0, 1.0, 2.0, 3.0, 4.0], dtype=float),
            analysis_succeeded=True,
            geometry_validity_passed=True,
            equivalent_failure_passed=True,
            equivalent_buckling_passed=True,
            equivalent_tip_passed=True,
            equivalent_twist_passed=True,
            max_abs_vertical_prebend_m=None,
            max_abs_vertical_curvature_per_m=None,
            loaded_shape_mode="exact_nodal",
            loaded_shape_control_station_fractions=(0.0, 0.5, 1.0),
            loaded_shape_main_z_tol_m=1.0e-9,
            loaded_shape_twist_tol_deg=1.0e-9,
        )
        low_dim = build_frozen_load_inverse_design(
            target_loaded_shape=target,
            disp_main_m=disp_main,
            disp_rear_m=disp_rear,
            y_nodes_m=np.array([0.0, 1.0, 2.0, 3.0, 4.0], dtype=float),
            analysis_succeeded=True,
            geometry_validity_passed=True,
            equivalent_failure_passed=True,
            equivalent_buckling_passed=True,
            equivalent_tip_passed=True,
            equivalent_twist_passed=True,
            max_abs_vertical_prebend_m=None,
            max_abs_vertical_curvature_per_m=None,
            loaded_shape_mode="low_dim_descriptor",
            loaded_shape_control_station_fractions=(0.0, 0.5, 1.0),
            loaded_shape_main_z_tol_m=1.0e-9,
            loaded_shape_twist_tol_deg=1.0e-9,
        )

        self.assertAlmostEqual(exact.target_shape_error.max_abs_error_m, 0.0)
        self.assertTrue(low_dim.loaded_shape_match.passed)
        self.assertGreater(low_dim.target_shape_error.max_abs_error_m, 0.01)
        self.assertGreater(low_dim.jig_shape.main_nodes_m[1, 2], exact.jig_shape.main_nodes_m[1, 2])
        margins = build_inverse_design_margins(low_dim)
        self.assertGreaterEqual(margins["loaded_shape_main_z_margin_m"], -1.0e-12)
        self.assertGreaterEqual(margins["loaded_shape_twist_margin_deg"], -1.0e-12)

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

    def test_build_target_loaded_shape_scales_z_coordinates_progressively(self) -> None:
        model = SimpleNamespace(
            nodes_main_m=np.array([[0.0, 0.0, 0.10], [0.0, 1.0, 0.30]], dtype=float),
            nodes_rear_m=np.array([[1.0, 0.0, 0.05], [1.0, 1.0, 0.25]], dtype=float),
        )

        shape = build_target_loaded_shape(model=model, z_scale=2.0)

        # Default exponent=1.0 keeps root nearly fixed and scales tip most.
        self.assertTrue(np.allclose(shape.main_nodes_m[:, 2], [0.10, 0.60]))
        self.assertTrue(np.allclose(shape.rear_nodes_m[:, 2], [0.05, 0.50]))

    def test_build_target_loaded_shape_exponent_zero_matches_uniform_scaling(self) -> None:
        model = SimpleNamespace(
            nodes_main_m=np.array([[0.0, 0.0, 0.10], [0.0, 1.0, 0.30]], dtype=float),
            nodes_rear_m=np.array([[1.0, 0.0, 0.05], [1.0, 1.0, 0.25]], dtype=float),
        )

        shape = build_target_loaded_shape(
            model=model,
            z_scale=2.0,
            dihedral_exponent=0.0,
        )

        self.assertTrue(np.allclose(shape.main_nodes_m[:, 2], [0.20, 0.60]))
        self.assertTrue(np.allclose(shape.rear_nodes_m[:, 2], [0.10, 0.50]))

    def test_write_deflection_csv_exports_main_and_rear_with_rotation_columns(self) -> None:
        inverse_result = SimpleNamespace(
            displacement_main_m=np.array(
                [
                    [0.0, 0.0, 0.01],
                    [0.0, 0.0, 0.02],
                ],
                dtype=float,
            ),
            displacement_rear_m=np.array(
                [
                    [0.0, 0.0, 0.03],
                    [0.0, 0.0, 0.04],
                ],
                dtype=float,
            ),
        )
        production_result = SimpleNamespace(
            disp_main_m=np.array(
                [
                    [1.0, 2.0, 3.0, 0.1, 0.2, 0.3],
                    [4.0, 5.0, 6.0, 0.4, 0.5, 0.6],
                ],
                dtype=float,
            ),
            disp_rear_m=np.array(
                [
                    [7.0, 8.0, 9.0, 0.7, 0.8, 0.9],
                    [10.0, 11.0, 12.0, 1.0, 1.1, 1.2],
                ],
                dtype=float,
            ),
        )
        candidate = SimpleNamespace(
            inverse_result=inverse_result,
            production_result=production_result,
        )
        model = SimpleNamespace(
            nodes_main_m=np.array([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=float),
            nodes_rear_m=np.array([[1.0, 0.0, 0.0], [1.0, 1.0, 0.0]], dtype=float),
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "node_deflections.csv"
            _write_deflection_csv(path, candidate=candidate, model=model)
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["spar"], "main")
        self.assertEqual(rows[2]["spar"], "rear")
        self.assertEqual(rows[0]["y_m"], "0.000000")
        self.assertEqual(rows[1]["y_m"], "1.000000")
        self.assertEqual(rows[0]["uz_m"], "3.00000000e+00")
        self.assertEqual(rows[0]["theta_x_rad"], "1.00000000e-01")
        self.assertEqual(rows[0]["theta_y_rad"], "2.00000000e-01")
        self.assertEqual(rows[0]["theta_z_rad"], "3.00000000e-01")

    def test_check_monotonic_deflection_passes_with_wire_segment_split(self) -> None:
        check = check_monotonic_deflection(
            y_nodes_m=np.array([0.0, 3.0, 7.5, 12.0, 16.5], dtype=float),
            uz_m=np.array([0.0, 0.01, 0.02, 0.08, 0.15], dtype=float),
            wire_y_positions=(7.5,),
            tolerance_m=1.0e-4,
        )

        self.assertTrue(check.passed)
        self.assertEqual(check.segments_checked, 2)
        self.assertEqual(check.segments_monotonic, 2)
        self.assertAlmostEqual(check.worst_violation_m, 0.0)
        self.assertEqual(check.details, ())

    def test_check_monotonic_deflection_reports_worst_violation(self) -> None:
        check = check_monotonic_deflection(
            y_nodes_m=np.array([0.0, 3.0, 7.5, 12.0, 16.5], dtype=float),
            uz_m=np.array([0.0, 0.01, 0.02, 0.015, 0.15], dtype=float),
            wire_y_positions=(7.5,),
            tolerance_m=1.0e-4,
        )

        self.assertFalse(check.passed)
        self.assertEqual(check.segments_checked, 2)
        self.assertEqual(check.segments_monotonic, 1)
        self.assertGreater(check.worst_violation_m, 0.0)
        self.assertAlmostEqual(check.worst_violation_node_y_m, 12.0)
        self.assertGreaterEqual(len(check.details), 1)

    def test_build_from_mainline_populates_monotonic_deflection_diagnostic(self) -> None:
        model = SimpleNamespace(
            nodes_main_m=np.array(
                [[0.0, 0.0, 0.0], [0.0, 1.0, 0.1], [0.0, 2.0, 0.2]],
                dtype=float,
            ),
            nodes_rear_m=np.array(
                [[1.0, 0.0, 0.0], [1.0, 1.0, 0.1], [1.0, 2.0, 0.2]],
                dtype=float,
            ),
            y_nodes_m=np.array([0.0, 1.0, 2.0], dtype=float),
        )
        result = SimpleNamespace(
            disp_main_m=np.array(
                [
                    [0.0, 0.0, 0.00, 0.0, 0.0, 0.0],
                    [0.0, 0.0, 0.05, 0.0, 0.0, 0.0],
                    [0.0, 0.0, 0.10, 0.0, 0.0, 0.0],
                ],
                dtype=float,
            ),
            disp_rear_m=np.array(
                [
                    [0.0, 0.0, 0.00, 0.0, 0.0, 0.0],
                    [0.0, 0.0, 0.04, 0.0, 0.0, 0.0],
                    [0.0, 0.0, 0.09, 0.0, 0.0, 0.0],
                ],
                dtype=float,
            ),
            feasibility=SimpleNamespace(
                analysis_succeeded=True,
                geometry_validity_succeeded=True,
                equivalent_failure_passed=True,
                equivalent_buckling_passed=True,
                equivalent_tip_passed=True,
                equivalent_twist_passed=True,
            ),
        )

        inverse = build_frozen_load_inverse_design_from_mainline(
            model=model,
            result=result,
            wire_y_positions=(1.0,),
        )

        self.assertIsNotNone(inverse.monotonic_deflection)
        assert inverse.monotonic_deflection is not None
        self.assertTrue(inverse.monotonic_deflection.passed)
        self.assertEqual(inverse.monotonic_deflection.segments_checked, 2)

    def test_lightweight_load_refresh_interpolates_lower_effective_aoa_from_twist(self) -> None:
        y = np.array([0.0, 1.0, 2.0], dtype=float)
        chord = np.array([1.0, 1.0, 1.0], dtype=float)
        q = 50.0
        low_case = SpanwiseLoad(
            y=y,
            chord=chord,
            cl=np.array([0.2, 0.2, 0.2], dtype=float),
            cd=np.array([0.01, 0.01, 0.01], dtype=float),
            cm=np.array([0.05, 0.05, 0.05], dtype=float),
            lift_per_span=q * chord * 0.2,
            drag_per_span=q * chord * 0.01,
            aoa_deg=0.0,
            velocity=10.0,
            dynamic_pressure=q,
        )
        high_case = SpanwiseLoad(
            y=y,
            chord=chord,
            cl=np.array([1.0, 1.0, 1.0], dtype=float),
            cd=np.array([0.05, 0.05, 0.05], dtype=float),
            cm=np.array([0.15, 0.15, 0.15], dtype=float),
            lift_per_span=q * chord * 1.0,
            drag_per_span=q * chord * 0.05,
            aoa_deg=10.0,
            velocity=10.0,
            dynamic_pressure=q,
        )
        cfg = SimpleNamespace(flight=SimpleNamespace(velocity=10.0, air_density=1.0))
        aircraft = SimpleNamespace(wing=SimpleNamespace(y=y))
        model = LightweightLoadRefreshModel(
            aero_cases=[high_case, low_case],
            baseline_case=high_case,
            cfg=cfg,
            aircraft=aircraft,
            washout_scale=1.0,
        )
        equivalent_result = SimpleNamespace(
            nodes=np.column_stack((np.zeros_like(y), y, np.zeros_like(y))),
            disp=np.array(
                [
                    [0.0, 0.0, 0.0, 0.0, np.radians(0.0), 0.0],
                    [0.0, 0.0, 0.0, 0.0, np.radians(3.0), 0.0],
                    [0.0, 0.0, 0.0, 0.0, np.radians(6.0), 0.0],
                ],
                dtype=float,
            ),
        )

        refreshed, metrics = model.refresh_mapped_loads(equivalent_result=equivalent_result)

        expected_cl = np.array([1.0, 0.76, 0.52], dtype=float)
        self.assertTrue(np.allclose(refreshed["cl"], expected_cl, atol=1.0e-9))
        self.assertTrue(np.allclose(refreshed["lift_per_span"], q * chord * expected_cl, atol=1.0e-9))
        self.assertAlmostEqual(metrics.twist_abs_max_deg, 6.0, places=6)
        self.assertAlmostEqual(metrics.aoa_eff_min_deg, 4.0, places=6)
        self.assertAlmostEqual(metrics.aoa_eff_max_deg, 10.0, places=6)
        self.assertAlmostEqual(metrics.aoa_clip_fraction, 0.0, places=6)

    def test_mapped_load_delta_metrics_reports_rms_and_peak_changes(self) -> None:
        previous = {
            "y": np.array([0.0, 1.0, 2.0], dtype=float),
            "lift_per_span": np.array([10.0, 20.0, 30.0], dtype=float),
            "torque_per_span": np.array([1.0, 2.0, 3.0], dtype=float),
        }
        current = {
            "y": np.array([0.0, 1.0, 2.0], dtype=float),
            "lift_per_span": np.array([13.0, 17.0, 33.0], dtype=float),
            "torque_per_span": np.array([0.0, 4.0, 6.0], dtype=float),
        }

        lift_rms, lift_peak, torque_rms, torque_peak = _mapped_load_delta_metrics(previous, current)

        self.assertAlmostEqual(lift_rms, float(np.sqrt((9.0 + 9.0 + 9.0) / 3.0)))
        self.assertAlmostEqual(lift_peak, 3.0)
        self.assertAlmostEqual(torque_rms, float(np.sqrt((1.0 + 4.0 + 9.0) / 3.0)))
        self.assertAlmostEqual(torque_peak, 3.0)

    def test_clearance_risk_metrics_uses_top_hotspots_and_flags_fragility(self) -> None:
        inverse_result = SimpleNamespace(
            jig_shape=StructuralNodeShape(
                main_nodes_m=np.array(
                    [
                        [0.0, 0.0, 0.0000],
                        [0.0, 1.0, 0.0040],
                        [0.0, 2.0, 0.0200],
                    ],
                    dtype=float,
                ),
                rear_nodes_m=np.array(
                    [
                        [1.0, 0.0, 0.0010],
                        [1.0, 1.0, 0.0060],
                        [1.0, 2.0, 0.0300],
                    ],
                    dtype=float,
                ),
            )
        )

        metrics = _clearance_risk_metrics(
            inverse_result=inverse_result,
            clearance_floor_z_m=0.0,
            threshold_m=0.010,
            top_k=4,
        )

        self.assertAlmostEqual(metrics.minimum_clearance_m, 0.0)
        self.assertEqual(metrics.hotspot_count_below_threshold, 4)
        self.assertTrue(metrics.fragile)
        self.assertEqual(metrics.hotspots[0].spar, "main")
        self.assertGreater(metrics.risk_score, 0.0)

    def test_lift_wire_rigging_records_backsolve_cut_length_from_tension(self) -> None:
        cfg = SimpleNamespace(
            lift_wires=SimpleNamespace(
                enabled=True,
                cable_material="steel_4130",
                cable_diameter=0.002,
                max_tension_fraction=0.4,
                wire_angle_deg=30.0,
                attachments=(SimpleNamespace(label="wire-1", fuselage_z=-1.50),),
            )
        )
        candidate = self._make_inverse_candidate(
            mass_kg=25.0,
            source="wire_case",
            feasible=True,
            violation=0.0,
        )
        candidate = InverseCandidate(
            **{
                **candidate.__dict__,
                "mainline_model": SimpleNamespace(
                    wire_node_indices=(1,),
                    nodes_main_m=np.array(
                        [
                            [0.0, 0.0, 0.0],
                            [0.5, 7.5, 1.0],
                        ],
                        dtype=float,
                    ),
                    y_nodes_m=np.array([0.0, 7.5], dtype=float),
                ),
                "production_result": SimpleNamespace(
                    disp_main_m=np.array(
                        [
                            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                            [0.1, 0.0, 0.2, 0.0, 0.0, 0.0],
                        ],
                        dtype=float,
                    ),
                    reactions=SimpleNamespace(
                        wire_reactions_n=np.array([100.0], dtype=float),
                    ),
                ),
            }
        )

        records = _lift_wire_rigging_records(
            candidate=candidate,
            cfg=cfg,
            materials_db=MaterialDB(),
        )

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.identifier, "wire-1")
        self.assertAlmostEqual(record.tension_force_n, 200.0, places=6)
        self.assertGreater(record.L_flight_m, record.L_cut_m)
        self.assertAlmostEqual(record.delta_L_m, record.L_flight_m - record.L_cut_m, places=12)
        self.assertGreater(record.tension_margin_n, 0.0)

    def test_candidate_archive_local_refine_starts_prioritizes_feasible_then_near_feasible(self) -> None:
        archive = CandidateArchive()
        baseline = self._make_inverse_candidate(
            mass_kg=40.0,
            source="baseline",
            feasible=False,
            violation=10.0,
        )
        heavy_feasible = self._make_inverse_candidate(
            mass_kg=50.0,
            source="heavy_feasible",
            feasible=True,
            violation=0.0,
        )
        light_feasible = self._make_inverse_candidate(
            mass_kg=30.0,
            source="light_feasible",
            feasible=True,
            violation=0.0,
        )
        near_feasible = self._make_inverse_candidate(
            mass_kg=20.0,
            source="near_feasible",
            feasible=False,
            violation=0.25,
        )
        archive.add(heavy_feasible)
        archive.add(light_feasible)
        archive.add(near_feasible)

        starts = archive.local_refine_starts(
            feasible_limit=1,
            near_feasible_limit=1,
            baseline=baseline,
        )

        self.assertEqual([candidate.source for candidate in starts], ["light_feasible", "near_feasible", "baseline"])

    def test_candidate_archive_target_mass_prefers_target_feasible_then_target_violation(self) -> None:
        archive = CandidateArchive(target_mass_kg=22.0)
        over_cap_feasible = self._make_inverse_candidate(
            mass_kg=24.0,
            source="over_cap_feasible",
            feasible=True,
            violation=0.0,
        )
        over_cap_feasible = InverseCandidate(
            **{**over_cap_feasible.__dict__, "mass_margin_kg": -2.0, "target_mass_passed": False, "overall_target_feasible": False, "target_violation_score": (2.0 / 22.0) ** 2}
        )
        under_cap_feasible = self._make_inverse_candidate(
            mass_kg=21.5,
            source="under_cap_feasible",
            feasible=True,
            violation=0.0,
        )
        under_cap_feasible = InverseCandidate(
            **{**under_cap_feasible.__dict__, "mass_margin_kg": 0.5, "target_mass_passed": True, "overall_target_feasible": True, "target_violation_score": 0.0}
        )
        under_cap_violate = self._make_inverse_candidate(
            mass_kg=21.0,
            source="under_cap_violate",
            feasible=False,
            violation=0.2,
        )
        under_cap_violate = InverseCandidate(
            **{**under_cap_violate.__dict__, "mass_margin_kg": 1.0, "target_mass_passed": True, "overall_target_feasible": False, "target_violation_score": 0.2}
        )
        archive.add(over_cap_feasible)
        archive.add(under_cap_feasible)
        archive.add(under_cap_violate)

        self.assertEqual(archive.selected.source, "under_cap_feasible")
        starts = archive.local_refine_starts(
            feasible_limit=1,
            near_feasible_limit=1,
            max_starts=3,
        )
        self.assertEqual([candidate.source for candidate in starts], ["under_cap_feasible", "over_cap_feasible"])


if __name__ == "__main__":
    unittest.main()
