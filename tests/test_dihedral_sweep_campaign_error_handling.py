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
    run_inverse_design_case,
)


class DihedralSweepCampaignErrorHandlingTests(unittest.TestCase):
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
    def test_run_inverse_design_case_reports_error_without_strict(
        self,
        mocked_run: mock.Mock,
    ) -> None:
        mocked_run.return_value = subprocess.CompletedProcess(
            args=["python"],
            returncode=7,
            stdout="stdout",
            stderr="stderr",
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
            args=["python"],
            returncode=9,
            stdout="",
            stderr="",
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
                    skip_step_export=True,
                    strict=True,
                )

    def test_arg_parser_accepts_strict_flag(self) -> None:
        args = _build_arg_parser().parse_args(["--strict"])
        self.assertTrue(args.strict)


if __name__ == "__main__":
    unittest.main()
