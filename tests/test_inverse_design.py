from __future__ import annotations

import csv
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

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
from scripts.dihedral_sweep_campaign import (
    SweepResult as DihedralSweepResult,
    _annotate_campaign_selection,
    _build_arg_parser as _build_dihedral_campaign_arg_parser,
    _build_campaign_search_budget,
)
from scripts.direct_dual_beam_inverse_design_feasibility_sweep import (
    SweepCaseResult as FeasibilitySweepCaseResult,
    _annotate_case_selection as _annotate_feasibility_case_selection,
    _build_arg_parser as _build_feasibility_sweep_arg_parser,
    _build_search_budget_summary as _build_feasibility_search_budget_summary,
)
from scripts.direct_dual_beam_inverse_design import (
    CANDIDATE_RERUN_AERO_SOURCE_MODE,
    LEGACY_AERO_SOURCE_MODE,
    CandidateAeroContract,
    CandidateArchive,
    InverseCandidate,
    InverseOutcome,
    LightweightLoadRefreshModel,
    RefreshIterationResult,
    RefreshLoadMetrics,
    RefreshRefinementOutcome,
    _resolve_outer_loop_candidate_aero,
    _build_validity_summary_payload,
    _build_arg_parser as _build_direct_inverse_arg_parser,
    _clearance_risk_metrics,
    _lift_wire_rigging_records,
    _mapped_load_delta_metrics,
    _write_deflection_csv,
    build_refresh_summary_json,
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
        args = _build_direct_inverse_arg_parser().parse_args(
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

    def test_lift_wire_rigging_records_prefer_explicit_wire_geometry_and_resultant(self) -> None:
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
                    wire_anchor_points_m=np.array([[0.25, 0.0, -1.25]], dtype=float),
                    wire_unstretched_lengths_m=np.array([7.8], dtype=float),
                    wire_area_m2=np.array([np.pi * (0.5 * 0.002) ** 2], dtype=float),
                    wire_young_pa=np.array([205.0e9], dtype=float),
                    wire_allowable_tension_n=np.array([3200.0], dtype=float),
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
                        wire_resultants_n=np.array([280.0], dtype=float),
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
        expected_loaded_attach = np.array([0.6, 7.5, 1.2], dtype=float)
        expected_anchor = np.array([0.25, 0.0, -1.25], dtype=float)
        expected_L_flight_m = float(np.linalg.norm(expected_loaded_attach - expected_anchor))
        self.assertAlmostEqual(record.tension_force_n, 280.0, places=9)
        self.assertAlmostEqual(record.L_cut_m, 7.8, places=9)
        self.assertAlmostEqual(record.L_flight_m, expected_L_flight_m, places=9)
        self.assertAlmostEqual(record.delta_L_m, expected_L_flight_m - 7.8, places=9)
        self.assertAlmostEqual(record.allowable_tension_n, 3200.0, places=9)
        self.assertAlmostEqual(record.tension_margin_n, 3200.0 - 280.0, places=9)

    def test_build_validity_summary_payload_marks_legacy_only_issues_as_warn(self) -> None:
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
        inverse = build_frozen_load_inverse_design(
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
        candidate = self._make_inverse_candidate(
            mass_kg=21.7,
            source="selected",
            feasible=True,
            violation=0.0,
        )
        candidate = InverseCandidate(
            **{
                **candidate.__dict__,
                "inverse_result": inverse,
                "hard_margins": {
                    "loaded_shape_main_z_margin_m": 0.02,
                    "loaded_shape_twist_margin_deg": 0.10,
                    "ground_clearance_margin_m": 0.0,
                    "jig_prebend_margin_m": 0.05,
                    "jig_curvature_margin_per_m": -0.002,
                },
                "active_wall_risk_score": 0.35,
            }
        )

        payload = _build_validity_summary_payload(
            candidate=candidate,
            active_wall_diagnostics=None,
        )

        self.assertEqual(payload["overall_status"], "warn")
        self.assertEqual(payload["validity_status"]["mainline_gate_status"], "pass")
        self.assertEqual(payload["validity_status"]["legacy_reference_status"], "warn")
        self.assertTrue(payload["mainline_feasibility"]["overall_feasible"])
        self.assertEqual(
            payload["legacy_reference"]["failures"],
            [
                "equivalent_failure",
                "equivalent_buckling",
                "equivalent_tip_deflection",
                "equivalent_twist",
            ],
        )
        self.assertIn("jig_curvature_margin_per_m", payload["blockers"]["negative_hard_margins"])

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


class CandidateAeroContractTests(unittest.TestCase):
    @staticmethod
    def _make_candidate(
        *,
        mass_kg: float = 21.0,
        source: str = "selected",
    ) -> InverseCandidate:
        zeros = np.zeros(2, dtype=float)
        return InverseCandidate(
            z=np.zeros(5, dtype=float),
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
            safety_passed=True,
            manufacturing_passed=True,
            overall_feasible=True,
            mass_margin_kg=1.0,
            target_mass_passed=True,
            overall_target_feasible=True,
            failures=tuple(),
            hard_margins={"dummy": 1.0},
            hard_violation_score=0.0,
            target_violation_score=0.0,
            inverse_result=None,
            equivalent_result=None,
            mainline_model=None,
            production_result=None,
        )

    @staticmethod
    def _make_spanwise_case(
        *,
        aoa_deg: float,
        cl_value: float,
        q: float = 50.0,
    ) -> SpanwiseLoad:
        y = np.array([0.0, 1.0, 2.0], dtype=float)
        chord = np.array([1.0, 1.0, 1.0], dtype=float)
        cl = np.full_like(y, cl_value, dtype=float)
        cd = np.full_like(y, 0.02, dtype=float)
        cm = np.full_like(y, 0.05, dtype=float)
        return SpanwiseLoad(
            y=y,
            chord=chord,
            cl=cl,
            cd=cd,
            cm=cm,
            lift_per_span=q * chord * cl,
            drag_per_span=q * chord * cd,
            aoa_deg=aoa_deg,
            velocity=10.0,
            dynamic_pressure=q,
        )

    def test_resolve_outer_loop_candidate_aero_legacy_marks_shared_artifacts(self) -> None:
        legacy_cases = [
            self._make_spanwise_case(aoa_deg=0.0, cl_value=0.3),
            self._make_spanwise_case(aoa_deg=8.0, cl_value=1.0),
        ]
        cfg = SimpleNamespace(
            flight=SimpleNamespace(velocity=10.0, air_density=1.0),
            io=SimpleNamespace(
                vsp_model="/tmp/reference.vsp3",
                vsp_lod="/tmp/legacy.lod",
                vsp_polar="/tmp/legacy.polar",
            ),
        )
        aircraft = SimpleNamespace(
            wing=SimpleNamespace(y=np.array([0.0, 1.0, 2.0], dtype=float)),
            weight_N=200.0,
        )

        aero_cases, cruise_case, mapped_loads, contract = _resolve_outer_loop_candidate_aero(
            cfg=cfg,
            aircraft=aircraft,
            output_dir=Path("/tmp/direct_inverse"),
            target_shape_z_scale=1.2,
            dihedral_exponent=1.5,
            aero_source_mode=LEGACY_AERO_SOURCE_MODE,
            legacy_aero_cases=legacy_cases,
        )

        self.assertEqual(len(aero_cases), 2)
        self.assertAlmostEqual(cruise_case.aoa_deg, 8.0)
        self.assertAlmostEqual(mapped_loads["total_lift"], 100.0)
        self.assertEqual(contract.source_mode, LEGACY_AERO_SOURCE_MODE)
        self.assertIn("shared cfg.io.vsp_lod / cfg.io.vsp_polar", contract.load_ownership)
        self.assertIn("No candidate-owned OpenVSP / VSPAero artifacts", contract.artifact_ownership)
        self.assertAlmostEqual(contract.requested_knobs["dihedral_multiplier"], 1.2)
        self.assertTrue(str(contract.geometry_artifacts["lod_path"]).endswith("legacy.lod"))

    def test_resolve_outer_loop_candidate_aero_rerun_marks_candidate_owned_artifacts(self) -> None:
        legacy_cases = [
            self._make_spanwise_case(aoa_deg=0.0, cl_value=0.2),
            self._make_spanwise_case(aoa_deg=10.0, cl_value=0.9),
        ]
        rerun_cases = [
            self._make_spanwise_case(aoa_deg=0.0, cl_value=0.1),
            self._make_spanwise_case(aoa_deg=10.0, cl_value=1.1),
        ]
        cfg = SimpleNamespace(
            flight=SimpleNamespace(velocity=10.0, air_density=1.0),
            io=SimpleNamespace(
                vsp_model="/tmp/reference.vsp3",
                vsp_lod="/tmp/legacy.lod",
                vsp_polar="/tmp/legacy.polar",
            ),
        )
        aircraft = SimpleNamespace(
            wing=SimpleNamespace(y=np.array([0.0, 1.0, 2.0], dtype=float)),
            weight_N=220.0,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "inverse"
            with mock.patch(
                "scripts.direct_dual_beam_inverse_design.VSPBuilder.build_and_run",
                autospec=True,
                return_value={
                    "success": True,
                    "vsp3_path": str((output_dir / "candidate_aero" / "candidate.vsp3").resolve()),
                    "lod_path": str((output_dir / "candidate_aero" / "candidate.lod").resolve()),
                    "polar_path": str((output_dir / "candidate_aero" / "candidate.polar").resolve()),
                    "error": None,
                },
            ) as build_and_run_mock, mock.patch(
                "scripts.direct_dual_beam_inverse_design.VSPAeroParser.parse",
                autospec=True,
                return_value=rerun_cases,
            ):
                aero_cases, cruise_case, mapped_loads, contract = _resolve_outer_loop_candidate_aero(
                    cfg=cfg,
                    aircraft=aircraft,
                    output_dir=output_dir,
                    target_shape_z_scale=1.3,
                    dihedral_exponent=2.0,
                    aero_source_mode=CANDIDATE_RERUN_AERO_SOURCE_MODE,
                    legacy_aero_cases=legacy_cases,
                )

        self.assertEqual(len(aero_cases), 2)
        self.assertAlmostEqual(cruise_case.aoa_deg, 10.0)
        self.assertAlmostEqual(mapped_loads["total_lift"], 110.0)
        self.assertEqual(contract.source_mode, CANDIDATE_RERUN_AERO_SOURCE_MODE)
        self.assertIn("candidate-owned OpenVSP geometry rebuild", contract.load_ownership)
        self.assertIn("candidate-owned geometry and aero artifacts", contract.artifact_ownership.lower())
        self.assertEqual(contract.aoa_sweep_deg, (0.0, 10.0))
        self.assertTrue(str(contract.geometry_artifacts["lod_path"]).endswith("candidate.lod"))
        _, output_arg = build_and_run_mock.call_args.args[:2]
        self.assertTrue(str(output_arg).endswith("candidate_aero"))
        self.assertEqual(build_and_run_mock.call_args.kwargs["aoa_list"], [0.0, 10.0])

    def test_build_refresh_summary_json_surfaces_candidate_aero_contract(self) -> None:
        candidate = self._make_candidate()
        inverse_outcome = InverseOutcome(
            success=True,
            feasible=True,
            target_mass_kg=None,
            message="ok",
            total_wall_time_s=0.1,
            baseline_eval_wall_time_s=0.01,
            nfev=1,
            nit=0,
            equivalent_analysis_calls=1,
            production_analysis_calls=1,
            unique_evaluations=1,
            cache_hits=0,
            feasible_count=1,
            target_feasible_count=1,
            baseline=candidate,
            best_overall_feasible=candidate,
            best_target_feasible=None,
            coarse_selected=candidate,
            coarse_candidate_count=1,
            coarse_feasible_count=1,
            coarse_target_feasible_count=1,
            selected=candidate,
            local_refine=None,
            active_wall_diagnostics=None,
            manufacturing_limit_source="explicit",
            max_jig_vertical_prebend_limit_m=0.1,
            max_jig_vertical_curvature_limit_per_m=0.01,
            artifacts=None,
        )
        contract = CandidateAeroContract(
            source_mode=CANDIDATE_RERUN_AERO_SOURCE_MODE,
            baseline_load_source="candidate_owned_vsp_geometry_rebuild_plus_vspaero_rerun",
            refresh_load_source="candidate_owned_twist_refresh_from_rerun_sweep",
            load_ownership="candidate-owned rerun loads",
            artifact_ownership="candidate-owned artifacts",
            requested_knobs={
                "target_shape_z_scale": 1.25,
                "dihedral_multiplier": 1.25,
                "dihedral_exponent": 2.0,
            },
            aoa_sweep_deg=(0.0, 10.0),
            selected_cruise_aoa_deg=10.0,
            geometry_artifacts={
                "candidate_output_dir": "/tmp/candidate_aero",
                "vsp3_path": "/tmp/candidate_aero/candidate.vsp3",
                "vspscript_path": None,
                "lod_path": "/tmp/candidate_aero/candidate.lod",
                "polar_path": "/tmp/candidate_aero/candidate.polar",
            },
            notes=("contract note",),
        )
        iteration = RefreshIterationResult(
            iteration_index=0,
            load_source=(
                "candidate_rerun_vspaero:"
                "candidate_owned_vsp_geometry_rebuild_plus_vspaero_rerun:"
                "aoa_10.000deg"
            ),
            outcome=inverse_outcome,
            load_metrics=RefreshLoadMetrics(
                total_lift_half_n=110.0,
                total_drag_half_n=2.0,
                total_abs_torque_half_nm=1.0,
                max_lift_per_span_npm=55.0,
                max_abs_torque_per_span_nmpm=0.5,
                twist_abs_max_deg=0.0,
                aoa_eff_min_deg=10.0,
                aoa_eff_max_deg=10.0,
                aoa_clip_fraction=0.0,
            ),
            mapped_loads={
                "y": np.array([0.0, 1.0, 2.0], dtype=float),
                "lift_per_span": np.array([55.0, 55.0, 55.0], dtype=float),
                "drag_per_span": np.array([1.0, 1.0, 1.0], dtype=float),
                "torque_per_span": np.array([0.5, 0.5, 0.5], dtype=float),
            },
            map_config_summary={
                "main_plateau_scale_upper": 1.14,
                "main_taper_fill_upper": 0.80,
                "rear_radius_scale_upper": 1.12,
                "delta_t_global_max_m": 0.001,
                "delta_t_rear_outboard_max_m": 0.0005,
            },
            dynamic_design_space_applied=False,
        )
        refinement = RefreshRefinementOutcome(
            refresh_steps_requested=1,
            refresh_steps_completed=0,
            dynamic_design_space_enabled=False,
            dynamic_design_space_rebuilds=0,
            converged=False,
            convergence_reason=None,
            manufacturing_limit_source="explicit",
            max_jig_vertical_prebend_limit_m=0.1,
            max_jig_vertical_curvature_limit_per_m=0.01,
            iterations=(iteration,),
            artifacts=None,
            aero_contract=contract,
        )
        map_config = SimpleNamespace(
            main_plateau_scale_upper=1.14,
            main_taper_fill_upper=0.80,
            rear_radius_scale_upper=1.12,
            delta_t_global_max_m=0.001,
            delta_t_rear_outboard_max_m=0.0005,
        )

        summary = build_refresh_summary_json(
            config_path=Path("/tmp/config.yaml"),
            design_report=Path("/tmp/report.txt"),
            cruise_aoa_deg=10.0,
            map_config=map_config,
            outcome=refinement,
            refresh_washout_scale=1.0,
        )

        self.assertEqual(summary["aero_contract"]["source_mode"], CANDIDATE_RERUN_AERO_SOURCE_MODE)
        self.assertIn("candidate-level geometry rebuild", summary["refinement_definition"]["refresh_method"])
        self.assertTrue(
            any(
                "no per-refresh geometry rebuild or aero rerun" in item
                for item in summary["refinement_definition"]["difference_from_full_coupling"]
            )
        )
        self.assertTrue(summary["iterations"][0]["load_source"].startswith("candidate_rerun_vspaero:"))


class OuterLoopContractTests(unittest.TestCase):
    @staticmethod
    def _make_feasibility_case(
        *,
        target_mass_kg: float,
        feasible: bool,
        candidate_score: float,
        selected_total_mass_kg: float = 24.0,
        objective_value_kg: float = 24.0,
        mismatch_m: float = 0.006,
        clearance_m: float = 0.040,
        main_blocker: str = "none",
    ) -> FeasibilitySweepCaseResult:
        return FeasibilitySweepCaseResult(
            target_mass_kg=target_mass_kg,
            feasible=feasible,
            best_feasible_mass_kg=selected_total_mass_kg if feasible else None,
            best_near_feasible_mass_kg=None if feasible else selected_total_mass_kg,
            selected_total_mass_kg=selected_total_mass_kg,
            objective_value_kg=objective_value_kg,
            mass_margin_kg=0.5 if feasible else -1.0,
            target_violation_score=0.0 if feasible else 0.2,
            candidate_score=candidate_score,
            target_shape_error_max_m=mismatch_m,
            ground_clearance_min_m=clearance_m,
            max_jig_prebend_m=0.10,
            max_jig_curvature_per_m=0.01,
            failure_index=-0.2,
            buckling_index=-0.1,
            forward_mismatch_max_m=None,
            main_blocker="none" if feasible else main_blocker,
            reject_reason="none" if feasible else main_blocker,
            nearest_boundary="none" if feasible else main_blocker,
            summary_json_path=f"/tmp/target_{target_mass_kg:.1f}.json",
            report_path=f"/tmp/target_{target_mass_kg:.1f}.txt",
        )

    @staticmethod
    def _make_dihedral_result(
        *,
        dihedral_multiplier: float,
        aero_status: str = "stable",
        aero_performance_feasible: bool = True,
        aero_performance_reason: str = "ok",
        beta_pass: bool = True,
        spiral_ok: bool = True,
        structure_status: str = "feasible",
        total_mass_kg: float | None = 23.0,
        objective_value_kg: float | None = 23.0,
        mismatch_mm: float | None = 6.0,
        clearance_mm: float | None = 35.0,
        structural_reject_reason: str | None = None,
        error_message: str | None = None,
    ) -> DihedralSweepResult:
        return DihedralSweepResult(
            dihedral_multiplier=dihedral_multiplier,
            dihedral_exponent=1.0,
            avl_case_path="/tmp/case.avl",
            mode_file_path=None,
            dutch_roll_found=True,
            dutch_roll_selection="oscillatory_lateral_mode",
            dutch_roll_real=-0.02,
            dutch_roll_imag=0.10,
            aero_status=aero_status,
            aero_performance_feasible=aero_performance_feasible,
            aero_performance_reason=aero_performance_reason,
            cl_trim=None,
            cd_induced=None,
            cd_total_est=None,
            ld_ratio=28.0,
            aoa_trim_deg=None,
            span_efficiency=None,
            lift_total_n=None,
            aero_power_w=None,
            beta_sweep_max_beta_deg=12.0,
            beta_sweep_cn_beta_per_rad=0.20,
            beta_sweep_cl_beta_per_rad=0.05,
            beta_sweep_directional_stable=beta_pass,
            beta_sweep_sideslip_feasible=beta_pass,
            rudder_cl_derivative=None,
            rudder_cn_derivative=None,
            rudder_roll_to_yaw_ratio=None,
            rudder_coupling_reason=None,
            spiral_mode_real=-0.01 if spiral_ok else 0.05,
            spiral_time_to_double_s=None if spiral_ok else 4.0,
            spiral_time_to_half_s=80.0 if spiral_ok else None,
            spiral_check_ok=spiral_ok,
            spiral_reason="stable" if spiral_ok else "time_to_double_below_limit",
            structure_status=structure_status,
            total_mass_kg=total_mass_kg,
            min_jig_clearance_mm=clearance_mm,
            wire_tension_n=None,
            wire_margin_n=None,
            failure_index=-0.2 if total_mass_kg is not None else None,
            buckling_index=-0.1 if total_mass_kg is not None else None,
            objective_value_kg=objective_value_kg,
            realizable_mismatch_max_mm=mismatch_mm,
            structural_reject_reason=structural_reject_reason,
            selected_output_dir=None,
            summary_json_path=f"/tmp/mult_{dihedral_multiplier:.3f}.json",
            wire_rigging_json_path=None,
            error_message=error_message,
        )

    def test_feasibility_sweep_budget_summary_uses_richer_default_grids(self) -> None:
        args = _build_feasibility_sweep_arg_parser().parse_args([])

        budget = _build_feasibility_search_budget_summary(args)

        self.assertEqual(budget["coarse_axes"]["main_plateau_grid_points"], 4)
        self.assertEqual(budget["coarse_axes"]["rear_outboard_grid_points"], 3)
        self.assertEqual(budget["coarse_grid_points_per_case"], 576)

    def test_feasibility_sweep_selection_prefers_lowest_feasible_contract_score(self) -> None:
        rejected = self._make_feasibility_case(
            target_mass_kg=18.0,
            feasible=False,
            candidate_score=1024.0,
            main_blocker="ground clearance",
        )
        winner_case = self._make_feasibility_case(
            target_mass_kg=20.0,
            feasible=True,
            candidate_score=24.0,
            selected_total_mass_kg=24.0,
        )
        runner_up = self._make_feasibility_case(
            target_mass_kg=22.0,
            feasible=True,
            candidate_score=25.5,
            selected_total_mass_kg=25.5,
        )

        annotated, winner = _annotate_feasibility_case_selection([rejected, winner_case, runner_up])

        by_target = {case.target_mass_kg: case for case in annotated}
        self.assertIsNotNone(winner)
        assert winner is not None
        self.assertEqual(winner["selection_status"], "winner")
        self.assertAlmostEqual(winner["requested_knobs"]["target_mass_kg"], 20.0)
        self.assertEqual(by_target[20.0].selection_status, "winner")
        self.assertEqual(by_target[22.0].selection_status, "feasible_runner_up")
        self.assertEqual(by_target[18.0].selection_status, "rejected")
        assert by_target[20.0].winner_evidence is not None
        self.assertIn("lowest feasible contract score", by_target[20.0].winner_evidence)

    def test_dihedral_campaign_budget_summary_accepts_local_refine_controls(self) -> None:
        args = _build_dihedral_campaign_arg_parser().parse_args(
            [
                "--cobyla-maxiter",
                "240",
                "--local-refine-max-starts",
                "6",
                "--local-refine-feasible-seeds",
                "2",
            ]
        )

        budget = _build_campaign_search_budget(args)

        self.assertEqual(budget["cobyla_maxiter"], 240)
        self.assertEqual(budget["local_refine_max_starts"], 6)
        self.assertEqual(budget["local_refine_feasible_seeds"], 2)
        self.assertEqual(budget["coarse_grid_points_per_case"], 576)

    def test_dihedral_campaign_selection_marks_winner_and_reject_reasons(self) -> None:
        winner_row = self._make_dihedral_result(
            dihedral_multiplier=1.20,
            total_mass_kg=22.5,
            objective_value_kg=22.6,
            mismatch_mm=5.0,
            clearance_mm=42.0,
        )
        structural_reject = self._make_dihedral_result(
            dihedral_multiplier=1.40,
            structure_status="infeasible",
            total_mass_kg=21.5,
            objective_value_kg=21.7,
            mismatch_mm=7.5,
            clearance_mm=8.0,
            structural_reject_reason="ground_clearance",
        )
        aero_reject = self._make_dihedral_result(
            dihedral_multiplier=1.60,
            aero_performance_feasible=False,
            aero_performance_reason="ld_ratio_below_min",
            structure_status="skipped",
            total_mass_kg=None,
            objective_value_kg=None,
            mismatch_mm=None,
            clearance_mm=None,
        )

        annotated, winner = _annotate_campaign_selection([winner_row, structural_reject, aero_reject])

        by_multiplier = {case.dihedral_multiplier: case for case in annotated}
        self.assertIsNotNone(winner)
        assert winner is not None
        self.assertEqual(winner["selection_status"], "winner")
        self.assertAlmostEqual(winner["requested_knobs"]["dihedral_multiplier"], 1.20)
        self.assertEqual(by_multiplier[1.20].selection_status, "winner")
        self.assertEqual(by_multiplier[1.40].reject_reason, "structural:ground_clearance")
        self.assertEqual(by_multiplier[1.60].reject_reason, "aero_performance:ld_ratio_below_min")
        assert by_multiplier[1.20].winner_evidence is not None
        self.assertIn("lowest fully-passing campaign score", by_multiplier[1.20].winner_evidence)


if __name__ == "__main__":
    unittest.main()
