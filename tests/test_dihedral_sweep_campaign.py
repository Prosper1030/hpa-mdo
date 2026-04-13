# ruff: noqa: E402
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from scripts.dihedral_sweep_campaign import (
    AeroPerformanceEvaluation,
    AvlEvaluation,
    _build_arg_parser,
    _build_result_row,
    evaluate_aero_performance,
    parse_avl_force_totals,
    parse_avl_eigenvalue_file,
    parse_avl_mode_stdout,
    run_inverse_design_case,
    scale_avl_dihedral_text,
    select_dutch_roll_mode,
)  # noqa: E402


class DihedralSweepCampaignTests(unittest.TestCase):
    def test_scale_avl_dihedral_text_multiplies_only_wing_surface(self) -> None:
        base_text = "\n".join(
            [
                "SURFACE",
                "Wing",
                "SECTION",
                "0.0  0.0  0.100000000  1.2  0.0",
                "SURFACE",
                "Elevator",
                "SECTION",
                "4.0  0.5  0.300000000  0.8  0.0 ! fixed",
                "",
            ]
        )

        scaled_text, count = scale_avl_dihedral_text(base_text, multiplier=2.0)

        self.assertEqual(count, 1)
        self.assertIn("0.200000000", scaled_text)
        self.assertIn("0.300000000", scaled_text)
        self.assertIn("! fixed", scaled_text)

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
                python_executable=Path(sys.executable),
                main_plateau_grid="0.0,1.0",
                main_taper_fill_grid="0.0,1.0",
                rear_radius_grid="0.0,1.0",
                rear_outboard_grid="0.0,1.0",
                wall_thickness_grid="0.0,1.0",
                refresh_steps=1,
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
                    python_executable=Path(sys.executable),
                    main_plateau_grid="0.0,1.0",
                    main_taper_fill_grid="0.0,1.0",
                    rear_radius_grid="0.0,1.0",
                    rear_outboard_grid="0.0,1.0",
                    wall_thickness_grid="0.0,1.0",
                    refresh_steps=1,
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
            dynamic_pressure_pa=25.878125,
            reference_area_m2=30.69,
            cruise_velocity_mps=6.5,
            min_lift_n=981.0,
            min_ld_ratio=25.0,
            cd_profile_estimate=0.010,
            max_trim_aoa_deg=12.0,
        )

        self.assertFalse(perf.aero_performance_feasible)
        self.assertEqual(perf.aero_performance_reason, "ld_below_minimum")
        self.assertIsNotNone(perf.ld_ratio)


if __name__ == "__main__":
    unittest.main()
