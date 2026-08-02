from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/run_wo006_hpa_model_architecture_sensitivity.py"
SPEC = importlib.util.spec_from_file_location("wo006_hpa_model_architecture_sensitivity", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def force_rows(count: int, start: float = 2001.0) -> list[dict[str, float]]:
    return [
        {
            "time": start + index,
            "CD_total": 0.03 + index * 1.0e-7,
            "CD_pressure": 0.022,
            "CD_viscous": 0.008 + index * 1.0e-7,
            "CL": 1.16 + index * 1.0e-6,
            "CmPitch": -0.13 + index * 1.0e-7,
        }
        for index in range(count)
    ]


def test_force_window_requires_one_hundred_rows() -> None:
    short = module.summarize_force_rows(force_rows(5))
    assert short["force_window_status"] == "insufficient_rows"
    assert short["stable_force_window"] is False
    assert short["CD_total_last"] == pytest.approx(0.0300004)

    complete = module.summarize_force_rows(force_rows(100))
    assert complete["force_window_status"] == "available"
    assert complete["stable_force_window"] is True


def test_missing_force_history_is_not_a_success(tmp_path: Path) -> None:
    status = {"process_ok": True, "start_time": 2000.0, "elapsed_s": 1.0}
    summary = module.summarize_case(tmp_path, module.CASE_SPECS["pimple_sst_Tu0p5_L0p001c"], status)
    assert summary["process_ok"] is True
    assert summary["ok"] is False
    assert summary["stable_force_window"] is False
    assert summary["failure_stage"] == "force-history-missing"


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (5, 5),
        (25, 25),
        (30, 15),
        (50, 25),
        (100, 25),
    ],
)
def test_checkpoint_interval_always_writes_the_final_steady_state(duration: int, expected: int) -> None:
    interval = module.checkpoint_interval(2000.0, 2000.0 + duration)
    assert interval == expected
    assert duration % interval == 0


def test_checkpoint_interval_rejects_fractional_steady_iteration() -> None:
    with pytest.raises(ValueError, match="whole number"):
        module.checkpoint_interval(2000.0, 2000.5)


def test_update_control_dict_uses_ram_safe_checkpoint_interval(tmp_path: Path) -> None:
    system = tmp_path / "system"
    system.mkdir()
    control = system / "controlDict"
    control.write_text(
        """application     simpleFoam;
endTime         2100;
writeInterval   100;
purgeWrite      0;
"""
    )
    module.update_control_dict(tmp_path, 2000.0, 2050.0, "simpleFoam")
    text = control.read_text()
    assert "endTime         2050;" in text
    assert "writeInterval   25;" in text
    assert "purgeWrite      2;" in text


def test_latest_time_name_uses_highest_numeric_directory(tmp_path: Path) -> None:
    for name in ("constant", "2000", "2025", "postProcessing"):
        (tmp_path / name).mkdir()
    assert module.latest_time_name(tmp_path) == "2025"


def test_case_shell_command_quotes_paths_with_spaces() -> None:
    command = module.case_shell_command(Path("/Volumes/Samsung SSD/cfd case"), "simpleFoam")
    assert command == "cd '/Volumes/Samsung SSD/cfd case' && simpleFoam"


def test_parse_force_coeffs_log_includes_pitch_moment(tmp_path: Path) -> None:
    log = tmp_path / "log.simpleFoam_case_2000_to_2050.txt"
    log.write_text(
        """Time = 2001
forceCoeffs forceCoeffs_total_physical write:
    Cd: 0.030 0.022 0.008 0
    Cl: 1.160 1.159 0.001 0
    CmPitch: -0.130 -0.140 0.010 0
"""
    )
    assert module.parse_force_coeffs_log(log) == [
        {
            "time": 2001.0,
            "CD_total": 0.03,
            "CD_pressure": 0.022,
            "CD_viscous": 0.008,
            "CL": 1.16,
            "CmPitch": -0.13,
        }
    ]


def test_force_history_without_time_advance_is_not_a_success(tmp_path: Path) -> None:
    log = tmp_path / "log.simpleFoam_sa_outlet_fixedValue0_2000_to_2050.txt"
    log.write_text(
        """Time = 2000
forceCoeffs forceCoeffs_total_physical write:
    Cd: 0.030 0.022 0.008 0
    Cl: 1.160 1.159 0.001 0
    CmPitch: -0.130 -0.140 0.010 0
"""
    )
    status = {"process_ok": True, "start_time": 2000.0}
    summary = module.summarize_case(tmp_path, module.CASE_SPECS["sa_outlet_fixedValue0"], status)
    assert summary["ok"] is False
    assert summary["failure_stage"] == "time-not-advanced"
