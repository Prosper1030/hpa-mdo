from __future__ import annotations

import csv
from dataclasses import replace
import json
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
from hpa_mdo.structure.rib_surrogate import build_rib_bay_surrogate_summary
from scripts.dihedral_sweep_campaign import (
    SweepResult as DihedralSweepResult,
    _annotate_campaign_selection,
    _build_arg_parser as _build_dihedral_campaign_arg_parser,
    _build_campaign_search_budget,
    _build_result_row as _build_dihedral_result_row,
    run_inverse_design_case as _run_dihedral_inverse_design_case,
)
from scripts.direct_dual_beam_inverse_design_feasibility_sweep import (
    SweepCaseResult as FeasibilitySweepCaseResult,
    _annotate_case_selection as _annotate_feasibility_case_selection,
    _build_arg_parser as _build_feasibility_sweep_arg_parser,
    _build_search_budget_summary as _build_feasibility_search_budget_summary,
    _build_report_text as _build_feasibility_report_text,
    _extract_mission_snapshot,
    _score_contract_formula_label as _feasibility_score_contract_formula_label,
    _run_one_case as _run_feasibility_case,
)
from scripts.direct_dual_beam_inverse_design import (
    CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE,
    CANDIDATE_RERUN_AERO_SOURCE_MODE,
    DEFAULT_RIB_FAMILY_MIX_MAX_UNIQUE,
    DEFAULT_RIB_FAMILY_SWITCH_PENALTY_KG,
    GroundClearanceRecoveryAttempt,
    GroundClearanceRecoverySummary,
    LEGACY_AERO_SOURCE_MODE,
    ORIGIN_VSP_FIXED_ALPHA_CORRECTOR_AERO_SOURCE_MODE,
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
    _build_ground_clearance_recovery_specs,
    _clearance_risk_metrics,
    _collect_mandatory_rib_stations,
    _ground_clearance_recovery_selection_key,
    _resolve_zonewise_rib_designs,
    _lift_wire_rigging_records,
    _mapped_load_delta_metrics,
    _write_deflection_csv,
    candidate_to_summary_dict,
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
        rib_bay_surrogate=None,
        rib_design=None,
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
            rib_bay_surrogate=rib_bay_surrogate,
            rib_design=rib_design,
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
                "--no-ground-clearance-recovery",
            ]
        )

        self.assertAlmostEqual(args.loaded_shape_z_tol, 0.031)
        self.assertAlmostEqual(args.loaded_shape_twist_tol, 0.22)
        self.assertAlmostEqual(args.loaded_shape_main_z_tol_mm, 40.0)
        self.assertAlmostEqual(args.loaded_shape_twist_tol_deg, 0.6)
        self.assertAlmostEqual(args.dihedral_exponent, 2.0)
        self.assertFalse(args.ground_clearance_recovery)

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

    def test_rib_bay_surrogate_summary_derives_bay_length_delta_over_chord_and_risk(self) -> None:
        cfg = SimpleNamespace(
            rib=SimpleNamespace(
                enabled=True,
                family="balsa_sheet_3mm",
                spacing_m=0.4,
                catalog_path=None,
            ),
            safety=SimpleNamespace(dual_spar_warping_knockdown=0.5),
        )
        aircraft = SimpleNamespace(
            wing=SimpleNamespace(
                y=np.array([0.0, 0.5, 1.0], dtype=float),
                chord=np.array([1.0, 1.0, 1.0], dtype=float),
            )
        )
        loaded_shape = StructuralNodeShape(
            main_nodes_m=np.array(
                [
                    [0.0, 0.0, 0.0],
                    [0.0, 0.5, 0.05],
                    [0.0, 1.0, 0.10],
                ],
                dtype=float,
            ),
            rear_nodes_m=np.array(
                [
                    [1.0, 0.0, 0.0],
                    [1.0, 0.5, 0.025],
                    [1.0, 1.0, 0.05],
                ],
                dtype=float,
            ),
        )

        summary = build_rib_bay_surrogate_summary(
            cfg=cfg,
            aircraft=aircraft,
            loaded_shape=loaded_shape,
        )

        self.assertTrue(summary.enabled)
        self.assertEqual(summary.family_key, "balsa_sheet_3mm")
        self.assertEqual(summary.bay_count, 3)
        self.assertAlmostEqual(summary.spacing_m, 0.4)
        self.assertAlmostEqual(summary.max_bay_length_m, 0.4)
        self.assertAlmostEqual(summary.max_local_delta_over_chord, 0.04)
        self.assertGreater(summary.max_shape_retention_risk, 0.0)
        self.assertEqual(summary.dominant_bay_index, 1)
        self.assertAlmostEqual(summary.bays[0].bay_length_m, 0.4)
        self.assertAlmostEqual(summary.bays[0].local_delta_over_chord, 0.04)
        self.assertAlmostEqual(summary.bays[0].shape_retention_risk, 0.032)

    def test_candidate_summary_dict_surfaces_rib_bay_surrogate_contract(self) -> None:
        cfg = SimpleNamespace(
            rib=SimpleNamespace(
                enabled=True,
                family="balsa_sheet_3mm",
                spacing_m=0.4,
                catalog_path=None,
            ),
            safety=SimpleNamespace(dual_spar_warping_knockdown=0.5),
        )
        aircraft = SimpleNamespace(
            wing=SimpleNamespace(
                y=np.array([0.0, 0.5, 1.0], dtype=float),
                chord=np.array([1.0, 1.0, 1.0], dtype=float),
            )
        )
        loaded_shape = StructuralNodeShape(
            main_nodes_m=np.array(
                [
                    [0.0, 0.0, 0.0],
                    [0.0, 0.5, 0.05],
                    [0.0, 1.0, 0.10],
                ],
                dtype=float,
            ),
            rear_nodes_m=np.array(
                [
                    [1.0, 0.0, 0.0],
                    [1.0, 0.5, 0.025],
                    [1.0, 1.0, 0.05],
                ],
                dtype=float,
            ),
        )
        candidate = replace(
            self._make_inverse_candidate(
                mass_kg=10.0,
                source="selected",
                feasible=True,
                violation=0.0,
            ),
            rib_bay_surrogate=build_rib_bay_surrogate_summary(
                cfg=cfg,
                aircraft=aircraft,
                loaded_shape=loaded_shape,
            ),
        )

        summary = candidate_to_summary_dict(candidate)

        rib_surrogate = summary["rib_bay_surrogate"]
        self.assertIsInstance(rib_surrogate, dict)
        self.assertEqual(rib_surrogate["bay_count"], 3)
        self.assertAlmostEqual(rib_surrogate["max_local_delta_over_chord"], 0.04)
        self.assertEqual(rib_surrogate["dominant_bay_index"], 1)
        self.assertEqual(len(rib_surrogate["bays"]), 3)
        self.assertAlmostEqual(rib_surrogate["bays"][0]["shape_retention_risk"], 0.032)

    def test_zonewise_rib_design_contract_keeps_mandatory_stations_and_limits_mix(self) -> None:
        cfg = SimpleNamespace(
            rib=SimpleNamespace(
                enabled=True,
                family="balsa_sheet_3mm",
                spacing_m=0.30,
                catalog_path=None,
            ),
            main_spar=SimpleNamespace(segments=[1.5, 3.0, 3.0]),
            lift_wires=SimpleNamespace(
                enabled=True,
                attachments=[SimpleNamespace(y=4.5, label="wire-1")],
            ),
            safety=SimpleNamespace(dual_spar_warping_knockdown=0.5),
        )
        aircraft = SimpleNamespace(
            wing=SimpleNamespace(
                y=np.array([0.0, 3.75, 7.5], dtype=float),
                chord=np.array([1.0, 0.9, 0.8], dtype=float),
            )
        )

        mandatory = _collect_mandatory_rib_stations(cfg, aircraft)
        designs = _resolve_zonewise_rib_designs(
            cfg=cfg,
            aircraft=aircraft,
            materials_db=MaterialDB(),
            zonewise_mode="limited_zonewise",
            family_switch_penalty_kg=0.20,
            family_mix_max_unique=2,
        )

        self.assertEqual([round(station.y_m, 3) for station in mandatory], [0.0, 1.5, 4.5, 7.5])
        by_key = {design.design_key: design for design in designs}
        baseline = by_key["baseline_uniform"]
        reinforced = by_key["inboard_reinforced_mix"]

        self.assertEqual(baseline.zone_count, 3)
        self.assertEqual(baseline.family_switch_count, 0)
        self.assertAlmostEqual(baseline.objective_penalty_kg, 0.0)
        self.assertEqual(baseline.unique_family_count, 1)
        self.assertTrue(reinforced.within_unique_family_limit)
        self.assertEqual(reinforced.max_unique_families, 2)
        self.assertGreaterEqual(reinforced.family_switch_count, 1)
        self.assertAlmostEqual(reinforced.family_switch_penalty_kg, 0.20)
        self.assertEqual(reinforced.unique_family_count, 2)
        self.assertEqual(reinforced.mandatory_stations_m, (0.0, 1.5, 4.5, 7.5))
        self.assertLessEqual(reinforced.zones[0].realized_pitch_m, reinforced.zones[0].target_pitch_m + 1.0e-12)
        self.assertGreater(reinforced.effective_warping_knockdown, 0.0)

    def test_candidate_summary_dict_surfaces_zonewise_rib_design_contract(self) -> None:
        cfg = SimpleNamespace(
            rib=SimpleNamespace(
                enabled=True,
                family="balsa_sheet_3mm",
                spacing_m=0.30,
                catalog_path=None,
            ),
            main_spar=SimpleNamespace(segments=[1.5, 3.0, 3.0]),
            lift_wires=SimpleNamespace(
                enabled=True,
                attachments=[SimpleNamespace(y=4.5, label="wire-1")],
            ),
            safety=SimpleNamespace(dual_spar_warping_knockdown=0.5),
        )
        aircraft = SimpleNamespace(
            wing=SimpleNamespace(
                y=np.array([0.0, 3.75, 7.5], dtype=float),
                chord=np.array([1.0, 0.9, 0.8], dtype=float),
            )
        )
        design = {
            item.design_key: item
            for item in _resolve_zonewise_rib_designs(
                cfg=cfg,
                aircraft=aircraft,
                materials_db=MaterialDB(),
                zonewise_mode="limited_zonewise",
                family_switch_penalty_kg=DEFAULT_RIB_FAMILY_SWITCH_PENALTY_KG,
                family_mix_max_unique=DEFAULT_RIB_FAMILY_MIX_MAX_UNIQUE,
            )
        }["inboard_reinforced_mix"]
        candidate = self._make_inverse_candidate(
            mass_kg=10.0,
            source="selected",
            feasible=True,
            violation=0.0,
            rib_design=design,
        )

        summary = candidate_to_summary_dict(candidate)

        rib_design = summary["rib_design"]
        self.assertIsInstance(rib_design, dict)
        self.assertEqual(rib_design["design_key"], "inboard_reinforced_mix")
        self.assertEqual(rib_design["zone_count"], 3)
        self.assertEqual(rib_design["unique_family_count"], 2)
        self.assertGreaterEqual(rib_design["family_switch_count"], 1)
        self.assertAlmostEqual(
            rib_design["objective_penalty_kg"],
            DEFAULT_RIB_FAMILY_SWITCH_PENALTY_KG,
        )
        self.assertEqual(rib_design["zones"][0]["zone_key"], "zone_01")
        self.assertEqual(rib_design["zones"][0]["start_labels"], ("root",))

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

    def test_lightweight_load_refresh_allows_single_fixed_alpha_case_when_enabled(self) -> None:
        y = np.array([0.0, 1.0, 2.0], dtype=float)
        chord = np.array([1.0, 1.0, 1.0], dtype=float)
        q = 50.0
        fixed_case = SpanwiseLoad(
            y=y,
            chord=chord,
            cl=np.array([0.8, 0.7, 0.6], dtype=float),
            cd=np.array([0.02, 0.02, 0.02], dtype=float),
            cm=np.array([0.01, 0.01, 0.01], dtype=float),
            lift_per_span=q * chord * np.array([0.8, 0.7, 0.6], dtype=float),
            drag_per_span=q * chord * 0.02,
            aoa_deg=0.0,
            velocity=10.0,
            dynamic_pressure=q,
        )
        cfg = SimpleNamespace(flight=SimpleNamespace(velocity=10.0, air_density=1.0))
        aircraft = SimpleNamespace(wing=SimpleNamespace(y=y))
        model = LightweightLoadRefreshModel(
            aero_cases=[fixed_case],
            baseline_case=fixed_case,
            cfg=cfg,
            aircraft=aircraft,
            washout_scale=1.0,
            allow_single_case=True,
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

        np.testing.assert_allclose(refreshed["cl"], fixed_case.cl)
        np.testing.assert_allclose(refreshed["lift_per_span"], fixed_case.lift_per_span)
        self.assertAlmostEqual(metrics.aoa_eff_min_deg, 0.0, places=6)
        self.assertAlmostEqual(metrics.aoa_eff_max_deg, 0.0, places=6)
        self.assertGreater(metrics.aoa_clip_fraction, 0.0)

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
                    "analysis_method": "panel",
                    "solver_backend": "openvsp_api",
                    "error": None,
                },
            ) as build_and_run_mock, mock.patch(
                "scripts.direct_dual_beam_inverse_design.VSPAeroParser.parse",
                autospec=True,
                return_value=rerun_cases,
            ) as parse_mock:
                aero_cases, cruise_case, mapped_loads, contract = _resolve_outer_loop_candidate_aero(
                    cfg=cfg,
                    aircraft=aircraft,
                    output_dir=output_dir,
                    target_shape_z_scale=1.3,
                    dihedral_exponent=2.0,
                    aero_source_mode=CANDIDATE_RERUN_AERO_SOURCE_MODE,
                    vspaero_analysis_method="panel",
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
        self.assertEqual(contract.geometry_artifacts["vspaero_analysis_method"], "panel")
        self.assertEqual(contract.geometry_artifacts["vspaero_solver_backend"], "openvsp_api")
        parser_self = parse_mock.call_args.args[0]
        self.assertEqual(parser_self.component_ids, (1,))
        builder_self, output_arg = build_and_run_mock.call_args.args[:2]
        self.assertTrue(str(output_arg).endswith("candidate_aero"))
        self.assertEqual(builder_self.vspaero_analysis_method, "panel")
        self.assertEqual(build_and_run_mock.call_args.kwargs["aoa_list"], [0.0, 10.0])

    def test_resolve_outer_loop_candidate_aero_candidate_avl_spanwise_marks_candidate_owned_artifacts(self) -> None:
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
        legacy_cases = [
            self._make_spanwise_case(aoa_deg=10.0, cl_value=1.1),
            self._make_spanwise_case(aoa_deg=14.0, cl_value=1.4),
        ]
        case_lo = self._make_spanwise_case(aoa_deg=12.2, cl_value=0.55)
        case_hi = self._make_spanwise_case(aoa_deg=16.0, cl_value=1.2)
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_path = Path(tmpdir) / "candidate_avl_spanwise.json"
            artifact_path.write_text(
                json.dumps(
                    {
                        "requested_knobs": {
                            "target_shape_z_scale": 4.0,
                            "dihedral_multiplier": 4.0,
                            "dihedral_exponent": 2.2,
                        },
                        "selected_cruise_aoa_deg": 12.2,
                        "selected_cruise_aoa_source": "outer_loop_avl_trim",
                        "selected_load_state_owner": "outer_loop_avl_trim_and_gates",
                        "aoa_sweep_deg": [10.0, 12.2],
                        "boundary_padding": "nearest_strip_coefficients_with_avl_root_tip_chord",
                        "geometry_artifacts": {
                            "candidate_output_dir": str((Path(tmpdir) / "candidate_avl_spanwise").resolve()),
                            "avl_path": str((Path(tmpdir) / "case.avl").resolve()),
                            "trim_force_path": str((Path(tmpdir) / "trim.ft").resolve()),
                        },
                        "notes": ["candidate-owned AVL strip-force sweep"],
                        "cases": [
                            {
                                "aoa_deg": 12.2,
                                "fs_path": str((Path(tmpdir) / "aoa_12p2.fs").resolve()),
                                "stdout_log_path": str((Path(tmpdir) / "aoa_12p2.log").resolve()),
                                "y": case_lo.y.tolist(),
                                "chord": case_lo.chord.tolist(),
                                "cl": case_lo.cl.tolist(),
                                "cd": case_lo.cd.tolist(),
                                "cm": case_lo.cm.tolist(),
                                "lift_per_span": case_lo.lift_per_span.tolist(),
                                "drag_per_span": case_lo.drag_per_span.tolist(),
                                "velocity_mps": float(case_lo.velocity),
                                "dynamic_pressure_pa": float(case_lo.dynamic_pressure),
                            },
                            {
                                "aoa_deg": 16.0,
                                "fs_path": str((Path(tmpdir) / "aoa_16p0.fs").resolve()),
                                "stdout_log_path": str((Path(tmpdir) / "aoa_16p0.log").resolve()),
                                "y": case_hi.y.tolist(),
                                "chord": case_hi.chord.tolist(),
                                "cl": case_hi.cl.tolist(),
                                "cd": case_hi.cd.tolist(),
                                "cm": case_hi.cm.tolist(),
                                "lift_per_span": case_hi.lift_per_span.tolist(),
                                "drag_per_span": case_hi.drag_per_span.tolist(),
                                "velocity_mps": float(case_hi.velocity),
                                "dynamic_pressure_pa": float(case_hi.dynamic_pressure),
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            aero_cases, cruise_case, mapped_loads, contract = _resolve_outer_loop_candidate_aero(
                cfg=cfg,
                aircraft=aircraft,
                output_dir=Path(tmpdir) / "inverse",
                target_shape_z_scale=4.0,
                dihedral_exponent=2.2,
                aero_source_mode=CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE,
                legacy_aero_cases=legacy_cases,
                candidate_avl_spanwise_loads_json=artifact_path,
            )

        self.assertEqual(len(aero_cases), 2)
        self.assertAlmostEqual(cruise_case.aoa_deg, 10.0)
        self.assertAlmostEqual(mapped_loads["total_lift"], 110.0)
        self.assertAlmostEqual(
            float(np.trapezoid(np.abs(mapped_loads["torque_per_span"]), mapped_loads["y"])),
            5.0,
        )
        self.assertEqual(contract.source_mode, CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE)
        self.assertIn("legacy_refresh still owns the structural selected load-state", contract.load_ownership)
        self.assertIn("AVL geometry, trim, strip-force, and spanwise-load artifacts", contract.artifact_ownership)
        self.assertEqual(contract.aoa_sweep_deg, (10.0, 14.0))
        self.assertTrue(
            any("legacy_refresh owner" in note for note in contract.notes)
        )
        self.assertTrue(
            any("shape AoA 16.000 deg" in note for note in contract.notes)
        )
        self.assertTrue(
            str(contract.geometry_artifacts["candidate_avl_spanwise_loads_json"]).endswith(
                "candidate_avl_spanwise.json"
            )
        )

    def test_resolve_outer_loop_candidate_aero_candidate_avl_spanwise_reuses_outer_loop_artifact_during_recovery(self) -> None:
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
        legacy_cases = [
            self._make_spanwise_case(aoa_deg=10.0, cl_value=1.1),
            self._make_spanwise_case(aoa_deg=14.0, cl_value=1.4),
        ]
        case = self._make_spanwise_case(aoa_deg=12.2, cl_value=1.1)
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_path = Path(tmpdir) / "candidate_avl_spanwise.json"
            artifact_path.write_text(
                json.dumps(
                    {
                        "requested_knobs": {
                            "target_shape_z_scale": 4.0,
                            "dihedral_multiplier": 4.0,
                            "dihedral_exponent": 2.2,
                        },
                        "selected_cruise_aoa_deg": 12.2,
                        "selected_cruise_aoa_source": "outer_loop_avl_trim",
                        "selected_load_state_owner": "outer_loop_avl_trim_and_gates",
                        "aoa_sweep_deg": [10.0, 12.2],
                        "geometry_artifacts": {
                            "candidate_output_dir": str((Path(tmpdir) / "candidate_avl_spanwise").resolve()),
                            "avl_path": str((Path(tmpdir) / "case.avl").resolve()),
                        },
                        "notes": ["candidate-owned AVL strip-force sweep"],
                        "cases": [
                            {
                                "aoa_deg": 12.2,
                                "fs_path": str((Path(tmpdir) / "aoa_12p2.fs").resolve()),
                                "stdout_log_path": str((Path(tmpdir) / "aoa_12p2.log").resolve()),
                                "y": case.y.tolist(),
                                "chord": case.chord.tolist(),
                                "cl": case.cl.tolist(),
                                "cd": case.cd.tolist(),
                                "cm": case.cm.tolist(),
                                "lift_per_span": case.lift_per_span.tolist(),
                                "drag_per_span": case.drag_per_span.tolist(),
                                "velocity_mps": float(case.velocity),
                                "dynamic_pressure_pa": float(case.dynamic_pressure),
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            _, cruise_case, _, contract = _resolve_outer_loop_candidate_aero(
                cfg=cfg,
                aircraft=aircraft,
                output_dir=Path(tmpdir) / "inverse",
                target_shape_z_scale=4.25,
                dihedral_exponent=2.45,
                aero_source_mode=CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE,
                legacy_aero_cases=legacy_cases,
                candidate_avl_spanwise_loads_json=artifact_path,
            )

        self.assertAlmostEqual(cruise_case.aoa_deg, 10.0)
        self.assertTrue(
            any("reuses the original outer-loop-selected AVL spanwise artifact during structural recovery" in note for note in contract.notes)
        )

    def test_resolve_outer_loop_candidate_aero_origin_fixed_alpha_corrector_uses_artifact_loads(self) -> None:
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
        case = self._make_spanwise_case(aoa_deg=0.0, cl_value=1.05)
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_path = Path(tmpdir) / "candidate_fixed_alpha_loads.json"
            artifact_path.write_text(
                json.dumps(
                    {
                        "requested_knobs": {
                            "target_shape_z_scale": 4.0,
                            "dihedral_multiplier": 4.0,
                            "dihedral_exponent": 2.2,
                        },
                        "fixed_design_alpha_deg": 0.0,
                        "selected_cruise_aoa_deg": 0.0,
                        "selected_cruise_aoa_source": "fixed_design_alpha",
                        "geometry_artifacts": {
                            "origin_vsp3_path": "/tmp/reference.vsp3",
                            "baseline_lod_path": "/tmp/origin_panel.lod",
                            "candidate_avl_path": "/tmp/case.avl",
                        },
                        "notes": ["origin fixed-alpha corrected loads"],
                        "cases": [
                            {
                                "aoa_deg": 0.0,
                                "y": case.y.tolist(),
                                "chord": case.chord.tolist(),
                                "cl": case.cl.tolist(),
                                "cd": case.cd.tolist(),
                                "cm": case.cm.tolist(),
                                "lift_per_span": case.lift_per_span.tolist(),
                                "drag_per_span": case.drag_per_span.tolist(),
                                "velocity_mps": float(case.velocity),
                                "dynamic_pressure_pa": float(case.dynamic_pressure),
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            aero_cases, cruise_case, mapped_loads, contract = _resolve_outer_loop_candidate_aero(
                cfg=cfg,
                aircraft=aircraft,
                output_dir=Path(tmpdir) / "inverse",
                target_shape_z_scale=4.0,
                dihedral_exponent=2.2,
                aero_source_mode=ORIGIN_VSP_FIXED_ALPHA_CORRECTOR_AERO_SOURCE_MODE,
                candidate_fixed_alpha_loads_json=artifact_path,
            )

        self.assertEqual(len(aero_cases), 1)
        self.assertAlmostEqual(cruise_case.aoa_deg, 0.0)
        self.assertAlmostEqual(mapped_loads["total_lift"], 105.0)
        self.assertEqual(contract.source_mode, ORIGIN_VSP_FIXED_ALPHA_CORRECTOR_AERO_SOURCE_MODE)
        self.assertEqual(contract.baseline_load_source, "origin_vsp_panel_fixed_alpha_baseline")
        self.assertEqual(contract.refresh_load_source, "mathematical_dihedral_corrector_from_origin_panel_baseline")
        self.assertTrue(any("fixed design alpha" in note for note in contract.notes))
        self.assertTrue(
            str(contract.geometry_artifacts["candidate_fixed_alpha_loads_json"]).endswith(
                "candidate_fixed_alpha_loads.json"
            )
        )

    def test_ground_clearance_recovery_specs_are_unique_and_tip_biased(self) -> None:
        specs = _build_ground_clearance_recovery_specs(
            target_shape_z_scale=1.0,
            dihedral_exponent=1.0,
        )

        self.assertEqual(specs[0][0], "tip_bias_only")
        self.assertGreater(specs[0][2], 1.0)
        self.assertTrue(all(scale >= 1.0 for _, scale, _ in specs))
        self.assertEqual(len(specs), len({(scale, exponent) for _, scale, exponent in specs}))

    def test_ground_clearance_recovery_selection_prefers_cases_that_clear_ground_blocker(self) -> None:
        blocked_candidate = replace(
            self._make_candidate(mass_kg=20.5, source="blocked"),
            overall_feasible=False,
            overall_target_feasible=False,
            target_mass_passed=True,
            jig_ground_clearance_min_m=-0.010,
            jig_ground_clearance_margin_m=-0.010,
            failures=("ground_clearance",),
            hard_margins={"ground_clearance_margin_m": -0.010},
            hard_violation_score=0.20,
            target_violation_score=0.20,
        )
        recovered_candidate = replace(
            self._make_candidate(mass_kg=20.8, source="recovered"),
            overall_feasible=False,
            overall_target_feasible=False,
            target_mass_passed=True,
            jig_ground_clearance_min_m=0.018,
            jig_ground_clearance_margin_m=0.018,
            failures=("loaded_shape_main_z",),
            hard_margins={"loaded_shape_main_z_margin_m": -0.002},
            hard_violation_score=0.10,
            target_violation_score=0.10,
            target_shape_error_max_m=0.002,
        )

        def _make_refinement(candidate: InverseCandidate) -> RefreshRefinementOutcome:
            outcome = InverseOutcome(
                success=False,
                feasible=False,
                target_mass_kg=22.0,
                message=candidate.message,
                total_wall_time_s=0.1,
                baseline_eval_wall_time_s=0.01,
                nfev=1,
                nit=0,
                equivalent_analysis_calls=1,
                production_analysis_calls=1,
                unique_evaluations=1,
                cache_hits=0,
                feasible_count=0,
                target_feasible_count=0,
                baseline=candidate,
                best_overall_feasible=None,
                best_target_feasible=None,
                coarse_selected=candidate,
                coarse_candidate_count=1,
                coarse_feasible_count=0,
                coarse_target_feasible_count=0,
                selected=candidate,
                local_refine=None,
                active_wall_diagnostics=None,
                manufacturing_limit_source="explicit",
                max_jig_vertical_prebend_limit_m=0.1,
                max_jig_vertical_curvature_limit_per_m=0.01,
                artifacts=None,
            )
            iteration = RefreshIterationResult(
                iteration_index=0,
                load_source="test",
                outcome=outcome,
                load_metrics=RefreshLoadMetrics(
                    total_lift_half_n=100.0,
                    total_drag_half_n=2.0,
                    total_abs_torque_half_nm=1.0,
                    max_lift_per_span_npm=50.0,
                    max_abs_torque_per_span_nmpm=0.5,
                    twist_abs_max_deg=0.0,
                    aoa_eff_min_deg=8.0,
                    aoa_eff_max_deg=8.0,
                    aoa_clip_fraction=0.0,
                ),
                mapped_loads={},
            )
            return RefreshRefinementOutcome(
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
                aero_contract=None,
            )

        self.assertLess(
            _ground_clearance_recovery_selection_key(_make_refinement(recovered_candidate)),
            _ground_clearance_recovery_selection_key(_make_refinement(blocked_candidate)),
        )

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
            ground_clearance_recovery=GroundClearanceRecoverySummary(
                enabled=True,
                triggered=True,
                trigger_reason="ground_clearance_failure",
                selected_attempt_label="clearance_recovery_stage1",
                baseline_requested_knobs={
                    "target_shape_z_scale": 1.0,
                    "dihedral_multiplier": 1.0,
                    "dihedral_exponent": 1.0,
                },
                selected_requested_knobs={
                    "target_shape_z_scale": 1.25,
                    "dihedral_multiplier": 1.25,
                    "dihedral_exponent": 1.6,
                },
                attempts=(
                    GroundClearanceRecoveryAttempt(
                        label="baseline_requested",
                        requested_target_shape_z_scale=1.0,
                        requested_dihedral_exponent=1.0,
                        case_output_dir="/tmp/baseline_requested",
                        run_completed=True,
                        selected_source="baseline",
                        feasible=False,
                        ground_clearance_failure=True,
                        analysis_succeeded=True,
                        jig_ground_clearance_min_m=-0.005,
                        target_shape_error_max_m=0.004,
                        selected_total_mass_kg=21.0,
                        primary_driver="ground clearance",
                        message="baseline blocked",
                    ),
                ),
            ),
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
        self.assertTrue(summary["ground_clearance_recovery"]["triggered"])
        self.assertEqual(
            summary["ground_clearance_recovery"]["selected_attempt_label"],
            "clearance_recovery_stage1",
        )
        self.assertIn("candidate-level geometry rebuild", summary["refinement_definition"]["refresh_method"])
        self.assertTrue(
            any(
                "no per-refresh geometry rebuild or aero rerun" in item
                for item in summary["refinement_definition"]["difference_from_full_coupling"]
            )
        )
        self.assertTrue(summary["iterations"][0]["load_source"].startswith("candidate_rerun_vspaero:"))

    def test_build_refresh_summary_json_surfaces_candidate_avl_spanwise_contract(self) -> None:
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
            source_mode=CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE,
            baseline_load_source="candidate_owned_avl_geometry_plus_spanwise_strip_force_sweep",
            refresh_load_source="candidate_owned_twist_refresh_from_avl_spanwise_sweep",
            load_ownership="candidate-owned AVL strip-force sweep",
            artifact_ownership="candidate-owned AVL artifacts",
            requested_knobs={
                "target_shape_z_scale": 4.0,
                "dihedral_multiplier": 4.0,
                "dihedral_exponent": 2.2,
            },
            aoa_sweep_deg=(10.0, 12.2, 14.0),
            selected_cruise_aoa_deg=12.2,
            geometry_artifacts={
                "candidate_output_dir": "/tmp/candidate_avl_spanwise",
                "avl_path": "/tmp/candidate_avl_spanwise/case.avl",
                "candidate_avl_spanwise_loads_json": "/tmp/candidate_avl_spanwise/candidate_avl_spanwise_loads.json",
            },
            notes=("Boundary coverage: nearest_strip_coefficients_with_avl_root_tip_chord.",),
        )
        iteration = RefreshIterationResult(
            iteration_index=0,
            load_source=(
                "candidate_avl_spanwise:"
                "candidate_owned_avl_geometry_plus_spanwise_strip_force_sweep:"
                "aoa_12.200deg"
            ),
            outcome=inverse_outcome,
            load_metrics=RefreshLoadMetrics(
                total_lift_half_n=110.0,
                total_drag_half_n=2.0,
                total_abs_torque_half_nm=1.0,
                max_lift_per_span_npm=55.0,
                max_abs_torque_per_span_nmpm=0.5,
                twist_abs_max_deg=0.0,
                aoa_eff_min_deg=12.2,
                aoa_eff_max_deg=12.2,
                aoa_clip_fraction=0.0,
            ),
            mapped_loads={
                "y": np.array([0.0, 1.0, 2.0], dtype=float),
                "lift_per_span": np.array([55.0, 55.0, 55.0], dtype=float),
                "drag_per_span": np.array([1.0, 1.0, 1.0], dtype=float),
                "torque_per_span": np.array([0.5, 0.5, 0.5], dtype=float),
            },
            map_config_summary={},
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
            ground_clearance_recovery=None,
        )

        summary = build_refresh_summary_json(
            config_path=Path("/tmp/config.yaml"),
            design_report=Path("/tmp/report.txt"),
            cruise_aoa_deg=12.2,
            map_config=SimpleNamespace(
                main_plateau_scale_upper=1.14,
                main_taper_fill_upper=0.80,
                rear_radius_scale_upper=1.12,
                delta_t_global_max_m=0.001,
                delta_t_rear_outboard_max_m=0.0005,
            ),
            outcome=refinement,
            refresh_washout_scale=1.0,
        )

        self.assertEqual(summary["aero_contract"]["source_mode"], CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE)
        self.assertTrue(summary["iterations"][0]["load_source"].startswith("candidate_avl_spanwise:"))
        self.assertIn("AVL geometry + strip-force AoA sweep", summary["refinement_definition"]["refresh_method"])
        self.assertTrue(
            any(
                "no per-refresh AVL rerun" in item
                for item in summary["refinement_definition"]["difference_from_full_coupling"]
            )
        )


    def test_build_refresh_summary_json_surfaces_mission_block_for_feasibility(self) -> None:
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
        iteration = RefreshIterationResult(
            iteration_index=0,
            load_source="candidate_rerun_vspaero:candidate_owned_vsp_geometry_rebuild_plus_vspaero_rerun:aoa_8.000deg",
            outcome=inverse_outcome,
            load_metrics=RefreshLoadMetrics(
                total_lift_half_n=110.0,
                total_drag_half_n=20.0,
                total_abs_torque_half_nm=1.0,
                max_lift_per_span_npm=55.0,
                max_abs_torque_per_span_nmpm=0.5,
                twist_abs_max_deg=0.0,
                aoa_eff_min_deg=8.0,
                aoa_eff_max_deg=8.0,
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
            aero_contract=CandidateAeroContract(
                source_mode=CANDIDATE_RERUN_AERO_SOURCE_MODE,
                baseline_load_source="candidate_owned_vsp_geometry_rebuild_plus_vspaero_rerun",
                refresh_load_source="candidate_owned_twist_refresh_from_rerun_sweep",
                load_ownership="candidate-owned rerun loads",
                artifact_ownership="candidate-owned artifacts",
                requested_knobs={
                    "target_shape_z_scale": 1.25,
                    "dihedral_multiplier": 1.25,
                    "dihedral_exponent": 1.6,
                },
                aoa_sweep_deg=(0.0, 8.0, 10.0),
                selected_cruise_aoa_deg=8.0,
                geometry_artifacts={
                    "candidate_output_dir": "/tmp/candidate_aero",
                    "vsp3_path": "/tmp/candidate_aero/candidate.vsp3",
                    "vspscript_path": None,
                    "lod_path": "/tmp/candidate_aero/candidate.lod",
                    "polar_path": "/tmp/candidate_aero/candidate.polar",
                },
                notes=(),
            ),
            ground_clearance_recovery=None,
        )

        summary = build_refresh_summary_json(
            config_path=REPO_ROOT / "configs" / "blackcat_004.yaml",
            design_report=Path("/tmp/report.txt"),
            cruise_aoa_deg=8.0,
            map_config=SimpleNamespace(
                main_plateau_scale_upper=1.14,
                main_taper_fill_upper=0.80,
                rear_radius_scale_upper=1.12,
                delta_t_global_max_m=0.001,
                delta_t_rear_outboard_max_m=0.0005,
            ),
            outcome=refinement,
            refresh_washout_scale=1.0,
        )

        self.assertIn("mission", summary)
        self.assertIsNotNone(summary["mission"]["mission_objective_mode"])
        self.assertEqual(summary["mission"]["pilot_power_model"], "fake_anchor_curve")
        expected_reference_power_w = 2.0 * 20.0 * 6.5
        expected_min_power_w = expected_reference_power_w * (6.0 / 6.5) ** 3
        self.assertAlmostEqual(summary["mission"]["min_power_w"], expected_min_power_w)
        self.assertLess(summary["mission"]["mission_score"], 0.0)

        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "target_20.0kg"
            case_dir.mkdir(parents=True, exist_ok=True)
            summary_path = case_dir / "direct_dual_beam_inverse_design_refresh_summary.json"
            report_path = case_dir / "direct_dual_beam_inverse_design_refresh_report.txt"
            summary_path.write_text(json.dumps(summary) + "\n", encoding="utf-8")
            report_path.write_text("ok\n", encoding="utf-8")

            args = _build_feasibility_sweep_arg_parser().parse_args(
                [
                    "--config",
                    str(REPO_ROOT / "configs" / "blackcat_004.yaml"),
                    "--design-report",
                    str(Path("/tmp/report.txt")),
                ]
            )
            with mock.patch(
                "scripts.direct_dual_beam_inverse_design_feasibility_sweep.subprocess.run",
                autospec=True,
                return_value=SimpleNamespace(returncode=0),
            ):
                result = _run_feasibility_case(args, target_mass_kg=20.0, case_dir=case_dir)

        self.assertEqual(result.mission_objective_mode, "max_range")
        self.assertTrue(result.mission_feasible)
        self.assertIsNotNone(result.target_range_km)
        self.assertIsNotNone(result.best_range_m)
        self.assertIsNotNone(result.mission_score)
        self.assertEqual(result.pilot_power_model, "fake_anchor_curve")

        bad_iteration = replace(
            iteration,
            load_metrics=replace(iteration.load_metrics, total_drag_half_n=0.0),
        )
        bad_refinement = replace(refinement, iterations=(bad_iteration,))
        bad_summary = build_refresh_summary_json(
            config_path=REPO_ROOT / "configs" / "blackcat_004.yaml",
            design_report=Path("/tmp/report.txt"),
            cruise_aoa_deg=8.0,
            map_config=SimpleNamespace(
                main_plateau_scale_upper=1.14,
                main_taper_fill_upper=0.80,
                rear_radius_scale_upper=1.12,
                delta_t_global_max_m=0.001,
                delta_t_rear_outboard_max_m=0.0005,
            ),
            outcome=bad_refinement,
            refresh_washout_scale=1.0,
        )

        self.assertIn("mission", bad_summary)
        self.assertTrue(all(value is None for value in bad_summary["mission"].values()))


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
        aero_source_mode: str | None = CANDIDATE_RERUN_AERO_SOURCE_MODE,
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
            aero_source_mode=aero_source_mode,
            baseline_load_source=(
                "candidate_owned_vsp_geometry_rebuild_plus_vspaero_rerun"
                if aero_source_mode == CANDIDATE_RERUN_AERO_SOURCE_MODE
                else "legacy_shared_vspaero_reference"
            ),
            refresh_load_source=(
                "candidate_owned_twist_refresh_from_rerun_sweep"
                if aero_source_mode == CANDIDATE_RERUN_AERO_SOURCE_MODE
                else "legacy_twist_refresh_from_shared_sweep"
            ),
            load_ownership=(
                "candidate-owned rerun loads"
                if aero_source_mode == CANDIDATE_RERUN_AERO_SOURCE_MODE
                else "shared legacy refresh loads"
            ),
            artifact_ownership=(
                "candidate-owned artifacts"
                if aero_source_mode == CANDIDATE_RERUN_AERO_SOURCE_MODE
                else "shared legacy artifacts"
            ),
            selected_cruise_aoa_deg=8.0,
            aero_contract_json_path=f"/tmp/target_{target_mass_kg:.1f}_aero_contract.json",
            rib_design_key="baseline_uniform",
            rib_design_mode="limited_zonewise",
            rib_effective_warping_knockdown=0.5,
            rib_design_penalty_kg=0.0,
            rib_unique_family_count=1,
            rib_family_switch_count=0,
            rib_zone_count=6,
        )

    @staticmethod
    def _attach_mission_fields(
        case: FeasibilitySweepCaseResult,
        *,
        mission_objective_mode: str | None,
        mission_feasible: bool | None,
        target_range_passed: bool | None = None,
        mission_score: float | None,
        min_power_w: float | None = 190.0,
    ) -> FeasibilitySweepCaseResult:
        object.__setattr__(case, "mission_objective_mode", mission_objective_mode)
        object.__setattr__(case, "mission_feasible", mission_feasible)
        object.__setattr__(case, "target_range_km", 42.0)
        object.__setattr__(case, "target_range_passed", target_range_passed)
        object.__setattr__(case, "target_range_margin_m", 1200.0)
        object.__setattr__(case, "best_range_m", 43210.0)
        object.__setattr__(case, "best_range_speed_mps", 16.0)
        object.__setattr__(case, "best_endurance_s", 5400.0)
        object.__setattr__(case, "min_power_w", min_power_w)
        object.__setattr__(case, "min_power_speed_mps", 14.5)
        object.__setattr__(case, "mission_score", mission_score)
        object.__setattr__(case, "mission_score_reason", "maximize_range")
        object.__setattr__(case, "pilot_power_model", "fake_anchor_curve")
        object.__setattr__(case, "pilot_power_anchor", "240.0W@30.0min")
        return case

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
        aero_source_mode: str | None = CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE,
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
            aero_source_mode=aero_source_mode,
            baseline_load_source=(
                "candidate_owned_avl_geometry_plus_spanwise_strip_force_sweep"
                if aero_source_mode == CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE
                else (
                "candidate_owned_vsp_geometry_rebuild_plus_vspaero_rerun"
                if aero_source_mode == CANDIDATE_RERUN_AERO_SOURCE_MODE
                else "legacy_shared_vspaero_reference"
                )
            ),
            refresh_load_source=(
                "candidate_owned_twist_refresh_from_avl_spanwise_sweep"
                if aero_source_mode == CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE
                else (
                "candidate_owned_twist_refresh_from_rerun_sweep"
                if aero_source_mode == CANDIDATE_RERUN_AERO_SOURCE_MODE
                else "legacy_twist_refresh_from_shared_sweep"
                )
            ),
            load_ownership=(
                "candidate-owned AVL strip-force loads"
                if aero_source_mode == CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE
                else (
                "candidate-owned rerun loads"
                if aero_source_mode == CANDIDATE_RERUN_AERO_SOURCE_MODE
                else "shared legacy refresh loads"
                )
            ),
            artifact_ownership=(
                "candidate-owned AVL artifacts"
                if aero_source_mode == CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE
                else (
                "candidate-owned artifacts"
                if aero_source_mode == CANDIDATE_RERUN_AERO_SOURCE_MODE
                else "shared legacy artifacts"
                )
            ),
            selected_cruise_aoa_deg=8.0,
            aero_contract_json_path=f"/tmp/mult_{dihedral_multiplier:.3f}_aero_contract.json",
        )

    def test_feasibility_sweep_budget_summary_uses_richer_default_grids(self) -> None:
        args = _build_feasibility_sweep_arg_parser().parse_args([])

        budget = _build_feasibility_search_budget_summary(args)

        self.assertEqual(args.aero_source_mode, CANDIDATE_RERUN_AERO_SOURCE_MODE)
        self.assertEqual(args.vspaero_analysis_method, "vlm")
        self.assertEqual(args.rib_zonewise_mode, "limited_zonewise")
        self.assertEqual(budget["coarse_axes"]["main_plateau_grid_points"], 4)
        self.assertEqual(budget["coarse_axes"]["rear_outboard_grid_points"], 3)
        self.assertEqual(budget["coarse_grid_points_per_case"], 576)
        self.assertEqual(budget["coarse_candidate_contracts_per_case"], 1728)
        self.assertEqual(budget["aero_source_mode"], CANDIDATE_RERUN_AERO_SOURCE_MODE)
        self.assertEqual(budget["vspaero_analysis_method"], "vlm")
        self.assertTrue(budget["ground_clearance_recovery"])
        self.assertEqual(budget["rib_zonewise_mode"], "limited_zonewise")
        self.assertEqual(budget["rib_design_profiles_per_point"], 3)

    def test_feasibility_sweep_run_one_case_passes_rerun_aero_mode_and_reads_contract(self) -> None:
        args = _build_feasibility_sweep_arg_parser().parse_args(
            [
                "--config",
                "/tmp/config.yaml",
                "--design-report",
                "/tmp/report.txt",
                "--vspaero-analysis-method",
                "panel",
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "target_20.0kg"
            case_dir.mkdir(parents=True, exist_ok=True)
            summary_path = case_dir / "direct_dual_beam_inverse_design_refresh_summary.json"
            report_path = case_dir / "direct_dual_beam_inverse_design_refresh_report.txt"
            summary_path.write_text(
                json.dumps(
                    {
                        "iterations": [
                            {
                                "selected": {
                                    "hard_margins": {"ground_clearance_margin_m": 0.01},
                                    "target_mass_passed": True,
                                    "overall_feasible": True,
                                    "mass_margin_kg": 0.5,
                                    "total_structural_mass_kg": 22.0,
                                    "objective_value_kg": 22.0,
                                    "target_violation_score": 0.0,
                                    "target_shape_error_max_m": 0.004,
                                    "jig_ground_clearance_min_m": 0.035,
                                    "max_jig_vertical_prebend_m": 0.08,
                                    "max_jig_vertical_curvature_per_m": 0.01,
                                    "equivalent_failure_index": -0.2,
                                    "equivalent_buckling_index": -0.1,
                                    "rib_design": {
                                        "design_key": "inboard_reinforced_mix",
                                        "design_mode": "limited_zonewise",
                                        "effective_warping_knockdown": 0.62,
                                        "objective_penalty_kg": 0.15,
                                        "unique_family_count": 2,
                                        "family_switch_count": 1,
                                        "zone_count": 6,
                                    },
                                },
                                "search_diagnostics": {
                                    "best_target_feasible": {"total_structural_mass_kg": 22.0},
                                    "best_overall_feasible": {"total_structural_mass_kg": 22.0},
                                },
                                "forward_check": None,
                                "run_metrics": {"feasible": True},
                            }
                        ],
                        "aero_contract": {
                            "source_mode": CANDIDATE_RERUN_AERO_SOURCE_MODE,
                            "baseline_load_source": "candidate_owned_vsp_geometry_rebuild_plus_vspaero_rerun",
                            "refresh_load_source": "candidate_owned_twist_refresh_from_rerun_sweep",
                            "load_ownership": "candidate-owned rerun loads",
                            "artifact_ownership": "candidate-owned artifacts",
                            "requested_knobs": {
                                "target_shape_z_scale": 1.25,
                                "dihedral_exponent": 1.6,
                            },
                            "selected_cruise_aoa_deg": 8.0,
                        },
                        "ground_clearance_recovery": {
                            "triggered": True,
                            "selected_attempt_label": "clearance_recovery_stage1",
                            "trigger_reason": "ground_clearance_failure",
                            "attempts": [{}, {}],
                        },
                        "artifacts": {
                            "aero_contract_json": "/tmp/target_20.0kg_aero_contract.json",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            report_path.write_text("ok\n", encoding="utf-8")

            with mock.patch(
                "scripts.direct_dual_beam_inverse_design_feasibility_sweep.subprocess.run",
                autospec=True,
                return_value=SimpleNamespace(returncode=0),
            ) as run_mock:
                result = _run_feasibility_case(args, target_mass_kg=20.0, case_dir=case_dir)

        cmd = run_mock.call_args.args[0]
        self.assertIn("--aero-source-mode", cmd)
        self.assertEqual(
            cmd[cmd.index("--aero-source-mode") + 1],
            CANDIDATE_RERUN_AERO_SOURCE_MODE,
        )
        self.assertIn("--vspaero-analysis-method", cmd)
        self.assertEqual(cmd[cmd.index("--vspaero-analysis-method") + 1], "panel")
        self.assertIn("--ground-clearance-recovery", cmd)
        self.assertIn("--rib-zonewise-mode", cmd)
        self.assertEqual(cmd[cmd.index("--rib-zonewise-mode") + 1], "limited_zonewise")
        self.assertEqual(result.aero_source_mode, CANDIDATE_RERUN_AERO_SOURCE_MODE)
        self.assertAlmostEqual(result.requested_target_shape_z_scale, 1.25)
        self.assertAlmostEqual(result.requested_dihedral_exponent, 1.6)
        self.assertTrue(result.ground_clearance_recovery_triggered)
        self.assertEqual(result.ground_clearance_recovery_selected_attempt, "clearance_recovery_stage1")
        self.assertEqual(result.ground_clearance_recovery_attempt_count, 2)
        self.assertEqual(
            result.refresh_load_source,
            "candidate_owned_twist_refresh_from_rerun_sweep",
        )
        self.assertEqual(
            result.aero_contract_json_path,
            "/tmp/target_20.0kg_aero_contract.json",
        )
        self.assertEqual(result.rib_design_key, "inboard_reinforced_mix")
        self.assertAlmostEqual(result.rib_effective_warping_knockdown, 0.62)
        self.assertAlmostEqual(result.rib_design_penalty_kg, 0.15)

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
        self.assertEqual(winner["aero_source_mode"], CANDIDATE_RERUN_AERO_SOURCE_MODE)
        self.assertEqual(winner["rib_design"]["design_key"], "baseline_uniform")
        self.assertEqual(by_target[20.0].selection_status, "winner")
        self.assertEqual(by_target[22.0].selection_status, "feasible_runner_up")
        self.assertEqual(by_target[18.0].selection_status, "rejected")
        assert by_target[20.0].winner_evidence is not None
        self.assertIn("lowest feasible contract score", by_target[20.0].winner_evidence)
        self.assertIn("candidate rerun-aero", by_target[20.0].winner_evidence)
        self.assertIn("rib design=baseline_uniform", by_target[20.0].winner_evidence)

    def test_feasibility_mission_snapshot_extracts_summary_mission_fields(self) -> None:
        summary = {
            "mission": {
                "mission_objective_mode": "max_range",
                "mission_feasible": True,
                "target_range_km": 38.5,
                "target_range_passed": True,
                "target_range_margin_m": 1250.0,
                "best_range_m": 40250.0,
                "best_range_speed_mps": 17.5,
                "best_endurance_s": 5200.0,
                "min_power_w": 185.0,
                "min_power_speed_mps": 14.0,
                "mission_score": -40250.0,
                "mission_score_reason": "maximize_range",
                "pilot_power_model": "fake_anchor_curve",
                "pilot_power_anchor": "240.0W@30.0min",
            }
        }

        snapshot = _extract_mission_snapshot(summary)

        self.assertEqual(snapshot["mission_objective_mode"], "max_range")
        self.assertTrue(snapshot["mission_feasible"])
        self.assertAlmostEqual(snapshot["target_range_km"], 38.5)
        self.assertAlmostEqual(snapshot["best_range_m"], 40250.0)
        self.assertEqual(snapshot["pilot_power_anchor"], "240.0W@30.0min")

    def test_feasibility_sweep_selection_prefers_better_mission_score_for_max_range(self) -> None:
        slower = self._attach_mission_fields(
            self._make_feasibility_case(
                target_mass_kg=20.0,
                feasible=True,
                candidate_score=24.0,
                selected_total_mass_kg=24.0,
            ),
            mission_objective_mode="max_range",
            mission_feasible=True,
            mission_score=-39000.0,
        )
        object.__setattr__(slower, "target_violation_score", 0.010)
        better_range = self._attach_mission_fields(
            self._make_feasibility_case(
                target_mass_kg=22.0,
                feasible=True,
                candidate_score=25.0,
                selected_total_mass_kg=25.0,
            ),
            mission_objective_mode="max_range",
            mission_feasible=True,
            mission_score=-42000.0,
        )
        object.__setattr__(better_range, "target_violation_score", 0.002)

        annotated, winner = _annotate_feasibility_case_selection([slower, better_range])

        self.assertIsNotNone(winner)
        assert winner is not None
        self.assertEqual(winner["requested_knobs"]["target_mass_kg"], 22.0)
        self.assertEqual(winner["selection_status"], "winner")
        self.assertAlmostEqual(winner["candidate_score"], -41998.0)
        self.assertAlmostEqual(annotated[1].candidate_score, -41998.0)
        self.assertEqual(
            {case.target_mass_kg: case.selection_status for case in annotated}[22.0],
            "winner",
        )

    def test_feasibility_sweep_prefers_mission_passing_min_power_case_over_lower_power_failure(self) -> None:
        failing = self._attach_mission_fields(
            self._make_feasibility_case(
                target_mass_kg=20.0,
                feasible=True,
                candidate_score=24.0,
                selected_total_mass_kg=24.0,
            ),
            mission_objective_mode="min_power",
            mission_feasible=False,
            target_range_passed=False,
            mission_score=10.0,
            min_power_w=175.0,
        )
        object.__setattr__(failing, "target_violation_score", 0.010)
        passing = self._attach_mission_fields(
            self._make_feasibility_case(
                target_mass_kg=22.0,
                feasible=True,
                candidate_score=25.0,
                selected_total_mass_kg=25.0,
            ),
            mission_objective_mode="min_power",
            mission_feasible=True,
            target_range_passed=True,
            mission_score=11.0,
            min_power_w=178.0,
        )
        object.__setattr__(passing, "target_violation_score", 0.010)

        annotated, winner = _annotate_feasibility_case_selection([failing, passing])

        self.assertIsNotNone(winner)
        assert winner is not None
        self.assertEqual(winner["requested_knobs"]["target_mass_kg"], 22.0)
        self.assertEqual(winner["selection_status"], "winner")
        self.assertEqual(winner["mission_objective_mode"], "min_power")
        self.assertTrue(winner["mission_feasible"])
        self.assertTrue(winner["target_range_passed"])
        self.assertEqual(winner["min_power_w"], 178.0)
        self.assertEqual(winner["min_power_speed_mps"], 14.5)
        self.assertEqual(
            {case.target_mass_kg: case.selection_status for case in annotated}[20.0],
            "rejected",
        )
        self.assertEqual(
            {case.target_mass_kg: case.selection_status for case in annotated}[22.0],
            "winner",
        )
        self.assertEqual(
            {case.target_mass_kg: case.min_power_w for case in annotated}[22.0],
            178.0,
        )

    def test_feasibility_sweep_mixed_mission_data_falls_back_to_legacy_scoring(self) -> None:
        mission_case = self._attach_mission_fields(
            self._make_feasibility_case(
                target_mass_kg=20.0,
                feasible=True,
                candidate_score=240.0,
                selected_total_mass_kg=24.0,
            ),
            mission_objective_mode="max_range",
            mission_feasible=True,
            mission_score=-50000.0,
        )
        object.__setattr__(mission_case, "target_violation_score", 0.020)
        legacy_case = self._make_feasibility_case(
            target_mass_kg=22.0,
            feasible=True,
            candidate_score=25.0,
            selected_total_mass_kg=25.0,
        )

        annotated, winner = _annotate_feasibility_case_selection([mission_case, legacy_case])

        self.assertIsNotNone(winner)
        assert winner is not None
        self.assertEqual(winner["requested_knobs"]["target_mass_kg"], 22.0)
        self.assertEqual(winner["candidate_score"], 24.0)
        self.assertIsNone(winner["mission_objective_mode"])
        self.assertEqual(
            {case.target_mass_kg: case.selection_status for case in annotated}[22.0],
            "winner",
        )

    def test_feasibility_sweep_mission_pool_handles_legacy_rejected_row(self) -> None:
        mission_winner = self._attach_mission_fields(
            self._make_feasibility_case(
                target_mass_kg=20.0,
                feasible=True,
                candidate_score=24.0,
                selected_total_mass_kg=24.0,
            ),
            mission_objective_mode="max_range",
            mission_feasible=True,
            mission_score=-39000.0,
        )
        object.__setattr__(mission_winner, "target_violation_score", 0.010)
        mission_runner_up = self._attach_mission_fields(
            self._make_feasibility_case(
                target_mass_kg=21.0,
                feasible=True,
                candidate_score=25.0,
                selected_total_mass_kg=25.0,
            ),
            mission_objective_mode="max_range",
            mission_feasible=True,
            mission_score=-42000.0,
        )
        object.__setattr__(mission_runner_up, "target_violation_score", 0.002)
        legacy_rejected = self._make_feasibility_case(
            target_mass_kg=22.0,
            feasible=False,
            candidate_score=240.0,
            selected_total_mass_kg=26.0,
            main_blocker="ground clearance",
        )

        annotated, winner = _annotate_feasibility_case_selection(
            [mission_winner, mission_runner_up, legacy_rejected]
        )

        self.assertIsNotNone(winner)
        assert winner is not None
        self.assertEqual(winner["requested_knobs"]["target_mass_kg"], 21.0)
        self.assertEqual(winner["mission_objective_mode"], "max_range")
        self.assertAlmostEqual(winner["candidate_score"], -41998.0)
        self.assertEqual(
            _feasibility_score_contract_formula_label(winner["mission_objective_mode"]),
            "mission_score if available else objective_value_kg + 1000*target_violation_score + gate penalty",
        )
        search_budget = _build_feasibility_search_budget_summary(
            _build_feasibility_sweep_arg_parser().parse_args([])
        )
        report_text = _build_feasibility_report_text(
            output_dir=Path("/tmp/out"),
            cases=annotated,
            search_budget=search_budget,
            winner_summary=winner,
        )
        self.assertIn(
            "mission_score if available else objective_value_kg + 1000*target_violation_score + gate penalty",
            report_text,
        )
        by_target = {case.target_mass_kg: case for case in annotated}
        self.assertEqual(by_target[22.0].selection_status, "rejected")
        self.assertIsNone(by_target[22.0].mission_objective_mode)
        self.assertGreater(by_target[22.0].candidate_score, 1000.0)

    def test_dihedral_campaign_budget_summary_accepts_local_refine_controls(self) -> None:
        args = _build_dihedral_campaign_arg_parser().parse_args(
            [
                "--cobyla-maxiter",
                "240",
                "--local-refine-max-starts",
                "6",
                "--local-refine-feasible-seeds",
                "2",
                "--dihedral-exponent",
                "2.2",
            ]
        )

        budget = _build_campaign_search_budget(args)

        self.assertEqual(args.aero_source_mode, CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE)
        self.assertEqual(args.vspaero_analysis_method, "vlm")
        self.assertAlmostEqual(args.dihedral_exponent, 2.2)
        self.assertEqual(budget["cobyla_maxiter"], 240)
        self.assertEqual(budget["local_refine_max_starts"], 6)
        self.assertEqual(budget["local_refine_feasible_seeds"], 2)
        self.assertEqual(budget["coarse_grid_points_per_case"], 576)
        self.assertEqual(budget["aero_source_mode"], CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE)
        self.assertEqual(budget["vspaero_analysis_method"], "vlm")
        self.assertEqual(budget["rib_zonewise_mode"], "limited_zonewise")

    def test_dihedral_run_inverse_design_case_passes_candidate_avl_spanwise_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "inverse"
            output_dir.mkdir(parents=True, exist_ok=True)
            summary_path = output_dir / "direct_dual_beam_inverse_design_refresh_summary.json"
            summary_path.write_text("{}\n", encoding="utf-8")
            with mock.patch(
                "scripts.dihedral_sweep_campaign.subprocess.run",
                autospec=True,
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ) as run_mock:
                returned_summary_path, _, error_message = _run_dihedral_inverse_design_case(
                    inverse_script=Path("/tmp/direct_dual_beam_inverse_design.py"),
                    config_path=Path("/tmp/config.yaml"),
                    design_report=Path("/tmp/report.txt"),
                    output_dir=output_dir,
                    target_shape_z_scale=1.2,
                    dihedral_exponent=1.0,
                    python_executable=Path(sys.executable),
                    main_plateau_grid="0.0,1.0",
                    main_taper_fill_grid="0.0,1.0",
                    rear_radius_grid="0.0,1.0",
                    rear_outboard_grid="0.0,1.0",
                    wall_thickness_grid="0.0,1.0",
                    refresh_steps=1,
                    cobyla_maxiter=20,
                    cobyla_rhobeg=0.1,
                    skip_local_refine=True,
                    local_refine_feasible_seeds=1,
                    local_refine_near_feasible_seeds=1,
                    local_refine_max_starts=1,
                    local_refine_early_stop_patience=1,
                    local_refine_early_stop_abs_improvement_kg=0.05,
                    aero_source_mode=CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE,
                    vspaero_analysis_method="panel",
                    candidate_avl_spanwise_loads_json=Path("/tmp/candidate_avl_spanwise.json"),
                    candidate_fixed_alpha_loads_json=None,
                    rib_zonewise_mode="off",
                    skip_step_export=True,
                )

        cmd = run_mock.call_args.args[0]
        self.assertIn("--aero-source-mode", cmd)
        self.assertEqual(
            cmd[cmd.index("--aero-source-mode") + 1],
            CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE,
        )
        self.assertIn("--vspaero-analysis-method", cmd)
        self.assertEqual(cmd[cmd.index("--vspaero-analysis-method") + 1], "panel")
        self.assertIn("--candidate-avl-spanwise-loads-json", cmd)
        self.assertEqual(
            cmd[cmd.index("--candidate-avl-spanwise-loads-json") + 1],
            "/tmp/candidate_avl_spanwise.json",
        )
        self.assertNotIn("--no-ground-clearance-recovery", cmd)
        self.assertIn("--rib-zonewise-mode", cmd)
        self.assertEqual(cmd[cmd.index("--rib-zonewise-mode") + 1], "off")
        self.assertEqual(returned_summary_path, str(summary_path.resolve()))
        self.assertIsNone(error_message)

    def test_dihedral_run_inverse_design_case_passes_fixed_alpha_corrector_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "inverse"
            output_dir.mkdir(parents=True, exist_ok=True)
            summary_path = output_dir / "direct_dual_beam_inverse_design_refresh_summary.json"
            summary_path.write_text("{}\n", encoding="utf-8")
            with mock.patch(
                "scripts.dihedral_sweep_campaign.subprocess.run",
                autospec=True,
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ) as run_mock:
                returned_summary_path, _, error_message = _run_dihedral_inverse_design_case(
                    inverse_script=Path("/tmp/direct_dual_beam_inverse_design.py"),
                    config_path=Path("/tmp/config.yaml"),
                    design_report=Path("/tmp/report.txt"),
                    output_dir=output_dir,
                    target_shape_z_scale=1.2,
                    dihedral_exponent=1.0,
                    python_executable=Path(sys.executable),
                    main_plateau_grid="0.0,1.0",
                    main_taper_fill_grid="0.0,1.0",
                    rear_radius_grid="0.0,1.0",
                    rear_outboard_grid="0.0,1.0",
                    wall_thickness_grid="0.0,1.0",
                    refresh_steps=1,
                    cobyla_maxiter=20,
                    cobyla_rhobeg=0.1,
                    skip_local_refine=True,
                    local_refine_feasible_seeds=1,
                    local_refine_near_feasible_seeds=1,
                    local_refine_max_starts=1,
                    local_refine_early_stop_patience=1,
                    local_refine_early_stop_abs_improvement_kg=0.05,
                    aero_source_mode=ORIGIN_VSP_FIXED_ALPHA_CORRECTOR_AERO_SOURCE_MODE,
                    vspaero_analysis_method="panel",
                    candidate_avl_spanwise_loads_json=None,
                    candidate_fixed_alpha_loads_json=Path("/tmp/candidate_fixed_alpha_loads.json"),
                    rib_zonewise_mode="off",
                    skip_step_export=True,
                )

        cmd = run_mock.call_args.args[0]
        self.assertIn("--aero-source-mode", cmd)
        self.assertEqual(
            cmd[cmd.index("--aero-source-mode") + 1],
            ORIGIN_VSP_FIXED_ALPHA_CORRECTOR_AERO_SOURCE_MODE,
        )
        self.assertIn("--candidate-fixed-alpha-loads-json", cmd)
        self.assertEqual(
            cmd[cmd.index("--candidate-fixed-alpha-loads-json") + 1],
            "/tmp/candidate_fixed_alpha_loads.json",
        )
        self.assertEqual(returned_summary_path, str(summary_path.resolve()))
        self.assertIsNone(error_message)

    def test_dihedral_build_result_row_extracts_candidate_aero_contract(self) -> None:
        row = _build_dihedral_result_row(
            multiplier=1.2,
            dihedral_exponent=1.0,
            avl_eval=SimpleNamespace(
                avl_case_path="/tmp/case.avl",
                mode_file_path=None,
                dutch_roll_found=True,
                dutch_roll_selection="oscillatory_lateral_mode",
                dutch_roll_real=-0.02,
                dutch_roll_imag=0.10,
                aero_status="stable",
                spiral_eval=SimpleNamespace(
                    real=-0.01,
                    time_to_double_s=None,
                    time_to_half_s=80.0,
                    feasible=True,
                    reason="stable",
                ),
            ),
            aero_perf_eval=SimpleNamespace(
                aero_performance_feasible=True,
                aero_performance_reason="ok",
                cl_trim=None,
                cd_induced=None,
                cd_total_est=None,
                ld_ratio=28.0,
                aoa_trim_deg=None,
                span_efficiency=None,
                lift_total_n=None,
                aero_power_w=None,
            ),
            beta_eval=None,
            control_eval=None,
            summary_payload={
                "iterations": [
                    {
                        "selected": {
                            "overall_feasible": True,
                            "total_structural_mass_kg": 22.4,
                            "jig_ground_clearance_min_m": 0.036,
                            "equivalent_failure_index": -0.2,
                            "equivalent_buckling_index": -0.1,
                            "objective_value_kg": 22.6,
                            "target_shape_error_max_m": 0.004,
                        }
                    }
                ],
                "aero_contract": {
                    "source_mode": CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE,
                    "baseline_load_source": "candidate_owned_avl_geometry_plus_spanwise_strip_force_sweep",
                    "refresh_load_source": "candidate_owned_twist_refresh_from_avl_spanwise_sweep",
                    "load_ownership": "candidate-owned AVL strip-force loads",
                    "artifact_ownership": "candidate-owned AVL artifacts",
                    "selected_cruise_aoa_deg": 8.0,
                },
                "artifacts": {
                    "aero_contract_json": "/tmp/mult_1.200_aero_contract.json",
                },
            },
            selected_output_dir="/tmp/inverse",
            summary_json_path="/tmp/inverse_summary.json",
            error_message=None,
        )

        self.assertEqual(row.aero_source_mode, CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE)
        self.assertEqual(
            row.refresh_load_source,
            "candidate_owned_twist_refresh_from_avl_spanwise_sweep",
        )
        self.assertEqual(
            row.aero_contract_json_path,
            "/tmp/mult_1.200_aero_contract.json",
        )

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
        self.assertEqual(winner["aero_source_mode"], CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE)
        self.assertEqual(by_multiplier[1.20].selection_status, "winner")
        self.assertEqual(by_multiplier[1.40].reject_reason, "structural:ground_clearance")
        self.assertEqual(by_multiplier[1.60].reject_reason, "aero_performance:ld_ratio_below_min")
        assert by_multiplier[1.20].winner_evidence is not None
        self.assertIn("lowest fully-passing campaign score", by_multiplier[1.20].winner_evidence)
        self.assertIn("candidate AVL spanwise", by_multiplier[1.20].winner_evidence)


if __name__ == "__main__":
    unittest.main()
