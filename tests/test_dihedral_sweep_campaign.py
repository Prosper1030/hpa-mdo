# ruff: noqa: E402
from __future__ import annotations

import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.aero import AvlAeroGateSettings
from scripts.dihedral_sweep_campaign import (
    AeroPerformanceEvaluation,
    AvlEvaluation,
    BetaSweepPoint,
    _build_arg_parser,
    _build_result_row,
    _evaluate_beta_sweep_points,
    evaluate_aero_performance,
    parse_avl_force_totals,
    parse_avl_stability_derivatives,
    parse_avl_eigenvalue_file,
    parse_avl_mode_stdout,
    run_inverse_design_case,
    run_avl_spanwise_load_case,
    scale_avl_dihedral_text,
    select_dutch_roll_mode,
    select_spiral_mode,
)  # noqa: E402


class DihedralSweepCampaignTests(unittest.TestCase):
    def test_scale_avl_dihedral_text_applies_progressive_scaling_only_to_wing_surface(self) -> None:
        base_text = "\n".join(
            [
                "SURFACE",
                "Wing",
                "SECTION",
                "0.0  0.0  0.100000000  1.2  0.0",
                "SECTION",
                "0.0  10.0  0.200000000  1.0  0.0",
                "SURFACE",
                "Elevator",
                "SECTION",
                "4.0  0.5  0.300000000  0.8  0.0 ! fixed",
                "",
            ]
        )

        scaled_text, count, samples = scale_avl_dihedral_text(
            base_text,
            multiplier=2.0,
            half_span=10.0,
            dihedral_exponent=1.0,
        )

        self.assertEqual(count, 2)
        # Root section keeps original Z (eta=0 => factor=1).
        self.assertIn("0.100000000", scaled_text)
        # Tip section uses full multiplier (eta=1 => factor=2).
        self.assertIn("0.400000000", scaled_text)
        self.assertIn("0.300000000", scaled_text)
        self.assertIn("! fixed", scaled_text)
        self.assertEqual(len(samples), 2)
        self.assertAlmostEqual(samples[0].local_factor, 1.0)
        self.assertAlmostEqual(samples[1].local_factor, 2.0)

    def test_scale_avl_dihedral_text_exponent_zero_matches_uniform_scaling(self) -> None:
        base_text = "\n".join(
            [
                "SURFACE",
                "Wing",
                "SECTION",
                "0.0  0.0  0.100000000  1.2  0.0",
                "",
            ]
        )

        scaled_text, count, samples = scale_avl_dihedral_text(
            base_text,
            multiplier=2.0,
            half_span=10.0,
            dihedral_exponent=0.0,
        )

        self.assertEqual(count, 1)
        self.assertIn("0.200000000", scaled_text)
        self.assertEqual(len(samples), 1)
        self.assertAlmostEqual(samples[0].local_factor, 2.0)

    def test_parse_mode_stdout_and_select_dutch_roll(self) -> None:
        stdout_text = """
 Run case  1:   example

  mode 1:  -0.20000       2.50000
 u  :     0.1000     0.0000      v  :     4.0000     0.0000      x  :   0.000       0.000
 w  :     0.0500     0.0000      p  :     2.0000     0.0000      y  :   0.100       0.000
 q  :     0.0200     0.0000      r  :     3.0000     0.0000      z  :   0.000       0.000
 the:     0.0100     0.0000      phi:     1.5000     0.0000      psi:   1.200       0.000

  mode 2:  -0.05000       0.40000
 u  :     5.0000     0.0000      v  :     0.2000     0.0000      x  :   0.000       0.000
 w  :     2.0000     0.0000      p  :     0.1000     0.0000      y  :   0.000       0.000
 q  :     1.0000     0.0000      r  :     0.1000     0.0000      z  :   0.000       0.000
 the:     0.5000     0.0000      phi:     0.1000     0.0000      psi:   0.100       0.000
"""
        blocks = parse_avl_mode_stdout(stdout_text)
        found, selection, real, imag = select_dutch_roll_mode(
            eigenvalues=(),
            mode_blocks=blocks,
            allow_missing_mode=False,
        )

        self.assertTrue(found)
        self.assertEqual(selection, "oscillatory_lateral_mode")
        self.assertAlmostEqual(real, -0.2)
        self.assertAlmostEqual(imag, 2.5)

    def test_parse_avl_eigenvalue_file_reads_saved_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "modes.st"
            path.write_text(
                "\n".join(
                    [
                        "# demo",
                        "       1    -0.3000000         1.1000000",
                        "       1    -0.3000000        -1.1000000",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            eigs = parse_avl_eigenvalue_file(path)

        self.assertEqual(len(eigs), 2)
        self.assertAlmostEqual(eigs[0].real, -0.3)
        self.assertAlmostEqual(eigs[0].imag, 1.1)

    def test_build_result_row_marks_structural_failed_on_inverse_error(self) -> None:
        avl_eval = AvlEvaluation(
            avl_case_path="/tmp/case.avl",
            mode_file_path=None,
            stdout_log_path=None,
            dutch_roll_found=True,
            dutch_roll_selection="oscillatory_lateral_mode",
            dutch_roll_real=-0.1,
            dutch_roll_imag=0.6,
            aero_status="stable",
            aero_feasible=True,
            eigenvalue_count=4,
        )

        row = _build_result_row(
            multiplier=1.5,
            dihedral_exponent=1.0,
            avl_eval=avl_eval,
            aero_perf_eval=AeroPerformanceEvaluation(
                cl_trim=1.24,
                cd_induced=0.017,
                cd_total_est=0.027,
                ld_ratio=45.9,
                aoa_trim_deg=11.0,
                span_efficiency=0.64,
                lift_total_n=981.0,
                aero_power_w=138.9,
                aero_performance_feasible=True,
                aero_performance_reason="ok",
            ),
            beta_eval=None,
            control_eval=None,
            summary_payload=None,
            selected_output_dir="/tmp/inverse",
            summary_json_path=None,
            error_message="inverse-design subprocess failed",
        )

        self.assertEqual(row.structure_status, "structural_failed")
        self.assertEqual(row.error_message, "inverse-design subprocess failed")

    @mock.patch("scripts.dihedral_sweep_campaign.subprocess.run")
    def test_run_inverse_design_case_reports_error_without_strict(self, mocked_run: mock.Mock) -> None:
        mocked_run.return_value = subprocess.CompletedProcess(
            args=["python"], returncode=7, stdout="stdout", stderr="stderr"
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "inverse"
            summary_path, stdout_log, error_message = run_inverse_design_case(
                inverse_script=Path("/tmp/missing_inverse.py"),
                config_path=Path("/tmp/config.yaml"),
                design_report=Path("/tmp/design.txt"),
                output_dir=output_dir,
                target_shape_z_scale=1.0,
                dihedral_exponent=1.0,
                python_executable=Path(sys.executable),
                main_plateau_grid="0.0,1.0",
                main_taper_fill_grid="0.0,1.0",
                rear_radius_grid="0.0,1.0",
                rear_outboard_grid="0.0,1.0",
                wall_thickness_grid="0.0,1.0",
                refresh_steps=1,
                cobyla_maxiter=10,
                cobyla_rhobeg=0.2,
                skip_local_refine=True,
                local_refine_feasible_seeds=1,
                local_refine_near_feasible_seeds=1,
                local_refine_max_starts=1,
                local_refine_early_stop_patience=1,
                local_refine_early_stop_abs_improvement_kg=0.05,
                aero_source_mode="legacy_refresh",
                vspaero_analysis_method="vlm",
                candidate_avl_spanwise_loads_json=None,
                candidate_fixed_alpha_loads_json=None,
                rib_zonewise_mode="off",
                skip_step_export=True,
                strict=False,
            )
            self.assertIsNotNone(stdout_log)
            self.assertTrue(Path(str(stdout_log)).exists())

        self.assertIsNone(summary_path)
        self.assertIsNotNone(error_message)
        self.assertIn("rc=7", str(error_message))

    @mock.patch("scripts.dihedral_sweep_campaign.subprocess.run")
    def test_run_inverse_design_case_strict_raises(self, mocked_run: mock.Mock) -> None:
        mocked_run.return_value = subprocess.CompletedProcess(
            args=["python"], returncode=9, stdout="", stderr=""
        )
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "inverse"
            with self.assertRaises(RuntimeError):
                run_inverse_design_case(
                    inverse_script=Path("/tmp/missing_inverse.py"),
                    config_path=Path("/tmp/config.yaml"),
                    design_report=Path("/tmp/design.txt"),
                    output_dir=output_dir,
                    target_shape_z_scale=1.0,
                    dihedral_exponent=1.0,
                    python_executable=Path(sys.executable),
                    main_plateau_grid="0.0,1.0",
                    main_taper_fill_grid="0.0,1.0",
                    rear_radius_grid="0.0,1.0",
                    rear_outboard_grid="0.0,1.0",
                    wall_thickness_grid="0.0,1.0",
                    refresh_steps=1,
                    cobyla_maxiter=10,
                    cobyla_rhobeg=0.2,
                    skip_local_refine=True,
                    local_refine_feasible_seeds=1,
                    local_refine_near_feasible_seeds=1,
                    local_refine_max_starts=1,
                    local_refine_early_stop_patience=1,
                    local_refine_early_stop_abs_improvement_kg=0.05,
                    aero_source_mode="legacy_refresh",
                    vspaero_analysis_method="vlm",
                    candidate_avl_spanwise_loads_json=None,
                    candidate_fixed_alpha_loads_json=None,
                    rib_zonewise_mode="off",
                    skip_step_export=True,
                    strict=True,
                )

    def test_arg_parser_accepts_strict_flag(self) -> None:
        args = _build_arg_parser().parse_args(["--strict"])
        self.assertTrue(args.strict)

    def test_parse_avl_force_totals_extracts_trim_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            force_path = Path(tmp) / "case_trim.ft"
            force_path.write_text(
                "\n".join(
                    [
                        "  Alpha =  11.03899",
                        "  CLtot =   1.24000",
                        "  Beta  =   5.00000",
                        "  CXtot =   0.22036     Cltot =  -0.01234",
                        "  CZtot =  -1.22039     Cntot =  -0.05678",
                        "  CDvis =   0.00000     CDind = 0.0173939",
                        "  CYff  =   0.00000         e =    0.6381    | Plane",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            payload = parse_avl_force_totals(force_path)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertAlmostEqual(payload["cl_trim"], 1.24, places=6)
        self.assertAlmostEqual(payload["cd_induced"], 0.0173939, places=7)
        self.assertAlmostEqual(payload["aoa_trim_deg"], 11.03899, places=5)
        self.assertAlmostEqual(payload["span_efficiency"], 0.6381, places=4)
        self.assertAlmostEqual(payload["cl_roll_total"], -0.01234, places=5)
        self.assertAlmostEqual(payload["cn_total"], -0.05678, places=5)

    def test_parse_avl_stability_derivatives_extracts_beta_and_rudder_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            st_path = Path(tmp) / "case_trim.st"
            st_path.write_text(
                "\n".join(
                    [
                        " Stability-axis derivatives...",
                        "",
                        " x' mom.  Cl'|    Cla =  -0.000000    Clb =   0.031415",
                        " z' mom.  Cn'|    Cna =  -0.000000    Cnb =  -0.120000",
                        "",
                        "                  elevator     d01     rudder       d02 ",
                        " x' mom.  Cl'|   Cld01 =  -0.000000   Cld02 =   0.015000",
                        " z' mom.  Cn'|   Cnd01 =  -0.000000   Cnd02 =  -0.040000",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            payload = parse_avl_stability_derivatives(st_path)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertAlmostEqual(payload["clb"], 0.031415, places=6)
        self.assertAlmostEqual(payload["cnb"], -0.12, places=6)
        self.assertAlmostEqual(payload["cld02"], 0.015, places=6)
        self.assertAlmostEqual(payload["cnd02"], -0.04, places=6)

    def test_parse_avl_stability_derivatives_treats_starred_entries_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            st_path = Path(tmp) / "case_trim.st"
            st_path.write_text(
                "\n".join(
                    [
                        " x' mom.  Cl'|    Cla =  -0.000000    Clb =***********",
                        " z' mom.  Cn'|    Cna =  -0.000000    Cnb =   0.000000",
                        " x' mom.  Cl'|   Cld01 =  -0.000000   Cld02 =***********",
                        " z' mom.  Cn'|   Cnd01 =  -0.000000   Cnd02 =  -0.000000",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            payload = parse_avl_stability_derivatives(st_path)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertIsNone(payload["clb"])
        self.assertIsNone(payload["cld02"])
        self.assertEqual(payload["cnb"], 0.0)
        self.assertEqual(payload["cnd02"], -0.0)

    @mock.patch("scripts.dihedral_sweep_campaign.subprocess.run")
    def test_run_avl_spanwise_load_case_stages_airfoils_in_case_dir(
        self,
        mocked_run: mock.Mock,
    ) -> None:
        def _fake_run(*_args, **kwargs):
            cwd = Path(kwargs["cwd"])
            (cwd / "aoa_0p000.fs").write_text("strip data\n", encoding="utf-8")
            return subprocess.CompletedProcess(args=["avl"], returncode=0, stdout="", stderr="")

        mocked_run.side_effect = _fake_run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "source_case"
            source_dir.mkdir()
            avl_path = source_dir / "case.avl"
            avl_path.write_text(
                "\n".join(
                    [
                        "demo",
                        "SURFACE",
                        "Wing",
                        "SECTION",
                        "0 0 0 1 0",
                        "AFILE",
                        "fx76mp140.dat",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            airfoil_dir = root / "airfoils"
            airfoil_dir.mkdir()
            (airfoil_dir / "fx76mp140.dat").write_text("fx\n0 0\n1 0\n", encoding="utf-8")

            result = run_avl_spanwise_load_case(
                avl_bin=Path("/tmp/avl"),
                case_avl_path=avl_path,
                case_dir=root / "candidate_avl_spanwise",
                alpha_deg=0.0,
                velocity_mps=6.5,
                density_kgpm3=1.225,
                output_stem="aoa_0p000",
                airfoil_dir=airfoil_dir,
            )

            staged_case = root / "candidate_avl_spanwise" / "case.avl"
            self.assertTrue((root / "candidate_avl_spanwise" / "fx76mp140.dat").exists())
            self.assertIn("AFILE\nfx76mp140.dat", staged_case.read_text(encoding="utf-8"))
            self.assertTrue(result.run_completed)

    def test_evaluate_aero_performance_flags_low_ld(self) -> None:
        trim_eval = mock.Mock(
            trim_converged=True,
            trim_status="trim_converged",
            cl_trim=1.24,
            cd_induced=0.09,
            aoa_trim_deg=8.0,
            span_efficiency=0.4,
        )

        perf = evaluate_aero_performance(
            trim_eval=trim_eval,
            gate_settings=AvlAeroGateSettings(
                reference_area_source="unit_test",
                reference_area_m2=30.69,
                reference_area_case_path="/tmp/case.avl",
                air_density_kgpm3=1.225,
                cruise_velocity_mps=6.5,
                dynamic_pressure_pa=25.878125,
                trim_target_weight_kg=100.0,
                trim_target_weight_n=981.0,
                cl_required=1.2352,
                min_lift_kg=100.0,
                min_lift_n=981.0,
                min_ld_ratio=25.0,
                cd_profile_estimate=0.010,
                max_trim_aoa_deg=12.0,
                soft_trim_aoa_deg=10.0,
                stall_alpha_deg=13.5,
                min_stall_margin_deg=2.0,
            ),
        )

        self.assertFalse(perf.aero_performance_feasible)
        self.assertEqual(perf.aero_performance_reason, "ld_below_minimum")
        self.assertIsNotNone(perf.ld_ratio)

    def test_evaluate_beta_sweep_points_flags_positive_cn_slope_as_unstable(self) -> None:
        beta_eval = _evaluate_beta_sweep_points(
            (
                BetaSweepPoint(
                    beta_deg=0.0,
                    cl_trim=1.24,
                    cd_induced=0.017,
                    aoa_trim_deg=11.0,
                    cn_total=0.0,
                    cl_roll_total=0.0,
                    trim_converged=True,
                ),
                BetaSweepPoint(
                    beta_deg=5.0,
                    cl_trim=1.24,
                    cd_induced=0.018,
                    aoa_trim_deg=11.2,
                    cn_total=0.02,
                    cl_roll_total=0.0,
                    trim_converged=True,
                ),
                BetaSweepPoint(
                    beta_deg=12.0,
                    cl_trim=1.24,
                    cd_induced=0.020,
                    aoa_trim_deg=11.5,
                    cn_total=0.05,
                    cl_roll_total=0.0,
                    trim_converged=True,
                ),
            ),
            required_max_beta_deg=12.0,
        )

        self.assertTrue(beta_eval.sideslip_feasible)
        self.assertFalse(beta_eval.directional_stable)
        self.assertEqual(beta_eval.sideslip_reason, "cn_beta_positive")
        self.assertIsNotNone(beta_eval.cn_beta_per_rad)
        assert beta_eval.cn_beta_per_rad is not None
        self.assertGreater(beta_eval.cn_beta_per_rad, 0.0)

    def test_evaluate_beta_sweep_points_flags_missing_required_trim(self) -> None:
        beta_eval = _evaluate_beta_sweep_points(
            (
                BetaSweepPoint(
                    beta_deg=0.0,
                    cl_trim=1.24,
                    cd_induced=0.017,
                    aoa_trim_deg=11.0,
                    cn_total=0.0,
                    cl_roll_total=0.0,
                    trim_converged=True,
                ),
                BetaSweepPoint(
                    beta_deg=5.0,
                    cl_trim=1.24,
                    cd_induced=0.018,
                    aoa_trim_deg=11.2,
                    cn_total=-0.02,
                    cl_roll_total=0.0,
                    trim_converged=True,
                ),
                BetaSweepPoint(
                    beta_deg=12.0,
                    cl_trim=None,
                    cd_induced=None,
                    aoa_trim_deg=None,
                    cn_total=None,
                    cl_roll_total=None,
                    trim_converged=False,
                ),
            ),
            required_max_beta_deg=12.0,
        )

        self.assertEqual(beta_eval.max_trimmed_beta_deg, 5.0)
        self.assertFalse(beta_eval.sideslip_feasible)
        self.assertEqual(beta_eval.sideslip_reason, "trim_not_converged_at_beta_12.0")

    def test_evaluate_beta_sweep_points_extracts_directional_derivatives(self) -> None:
        beta_eval = _evaluate_beta_sweep_points(
            (
                BetaSweepPoint(
                    beta_deg=0.0,
                    cl_trim=1.24,
                    cd_induced=0.017,
                    aoa_trim_deg=11.0,
                    cn_total=0.0,
                    cl_roll_total=0.0,
                    trim_converged=True,
                ),
                BetaSweepPoint(
                    beta_deg=5.0,
                    cl_trim=1.24,
                    cd_induced=0.018,
                    aoa_trim_deg=11.2,
                    cn_total=-0.1,
                    cl_roll_total=-0.02,
                    trim_converged=True,
                ),
                BetaSweepPoint(
                    beta_deg=10.0,
                    cl_trim=1.24,
                    cd_induced=0.019,
                    aoa_trim_deg=11.3,
                    cn_total=-0.2,
                    cl_roll_total=-0.04,
                    trim_converged=True,
                ),
            ),
            required_max_beta_deg=10.0,
        )

        self.assertTrue(beta_eval.sideslip_feasible)
        self.assertTrue(beta_eval.directional_stable)
        assert beta_eval.cn_beta_per_rad is not None
        assert beta_eval.cl_beta_per_rad is not None
        self.assertAlmostEqual(beta_eval.cn_beta_per_rad, -0.02 / math.radians(1.0), places=6)
        self.assertAlmostEqual(beta_eval.cl_beta_per_rad, -0.004 / math.radians(1.0), places=6)

    def test_select_spiral_mode_uses_lateral_real_root_time_to_double(self) -> None:
        stdout_text = """
 Run case  1:   example

  mode 1:   0.05000       0.00000
 u  :     0.1000     0.0000      v  :     4.0000     0.0000      x  :   0.000       0.000
 w  :     0.0500     0.0000      p  :     2.0000     0.0000      y  :   0.100       0.000
 q  :     0.0200     0.0000      r  :     3.0000     0.0000      z  :   0.000       0.000
 the:     0.0100     0.0000      phi:     1.5000     0.0000      psi:   1.200       0.000

  mode 2:   0.20000       0.00000
 u  :     5.0000     0.0000      v  :     0.2000     0.0000      x  :   0.000       0.000
 w  :     2.0000     0.0000      p  :     0.1000     0.0000      y  :   0.000       0.000
 q  :     1.0000     0.0000      r  :     0.1000     0.0000      z  :   0.000       0.000
 the:     0.5000     0.0000      phi:     0.1000     0.0000      psi:   0.100       0.000
 """
        blocks = parse_avl_mode_stdout(stdout_text)

        spiral = select_spiral_mode(
            mode_blocks=blocks,
            min_time_to_double_s=10.0,
        )

        self.assertTrue(spiral.mode_found)
        self.assertAlmostEqual(spiral.real, 0.05)
        assert spiral.time_to_double_s is not None
        self.assertAlmostEqual(spiral.time_to_double_s, math.log(2.0) / 0.05, places=6)
        self.assertTrue(spiral.feasible)

    def test_select_spiral_mode_marks_unavailable_when_no_lateral_real_mode_exists(self) -> None:
        stdout_text = """
 Run case  1:   example

  mode 1:  -0.20000       0.00000
 u  :     5.0000     0.0000      v  :     0.0000     0.0000      x  :   0.000       0.000
 w  :     2.0000     0.0000      p  :     0.0000     0.0000      y  :   0.000       0.000
 q  :     1.0000     0.0000      r  :     0.0000     0.0000      z  :   0.000       0.000
 the:     0.5000     0.0000      phi:     0.0000     0.0000      psi:   0.000       0.000
 """
        blocks = parse_avl_mode_stdout(stdout_text)

        spiral = select_spiral_mode(
            mode_blocks=blocks,
            min_time_to_double_s=10.0,
        )

        self.assertFalse(spiral.mode_found)
        self.assertIsNone(spiral.real)
        self.assertEqual(spiral.reason, "spiral_mode_unavailable")

    def test_arg_parser_accepts_beta_sweep_flags(self) -> None:
        args = _build_arg_parser().parse_args(
            ["--skip-beta-sweep", "--max-sideslip-deg", "8.0"]
        )

        self.assertTrue(args.skip_beta_sweep)
        self.assertAlmostEqual(args.max_sideslip_deg, 8.0)

    def test_arg_parser_accepts_spiral_time_override(self) -> None:
        args = _build_arg_parser().parse_args(
            ["--min-spiral-time-to-double-s", "12.5"]
        )

        self.assertAlmostEqual(args.min_spiral_time_to_double_s, 12.5)


if __name__ == "__main__":
    unittest.main()
