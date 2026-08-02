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
    assert complete["contiguous_final_window"] is True


def test_force_window_rejects_time_gap() -> None:
    rows = force_rows(100)
    rows[-1]["time"] += 1.0
    summary = module.summarize_force_rows(rows)
    assert summary["contiguous_final_window"] is False
    assert summary["stable_force_window"] is False


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


def test_update_control_dict_repairs_function_object_write_cadence(tmp_path: Path) -> None:
    system = tmp_path / "system"
    system.mkdir()
    control = system / "controlDict"
    control.write_text(
        """application     simpleFoam;
endTime         2100;
writeInterval   100;
purgeWrite      0;
functions
{
    forceCoeffs_total_physical
    {
        writeControl    timeStep;
        writeInterval   25;
    }
    yPlus
    {
        writeControl    writeTime;
        writeInterval   25;
    }
    yPlusShear
    {
        type            yPlus;
        useWallFunction false;
        writeControl    writeTime;
        writeInterval   1;
    }
}
"""
    )
    module.update_control_dict(tmp_path, 2000.0, 2050.0, "simpleFoam")
    text = control.read_text()
    assert text.count("writeInterval   25;") == 1
    assert text.count("writeInterval   1;") == 2
    assert "yPlusShear" not in text


def test_latest_time_name_uses_highest_numeric_directory(tmp_path: Path) -> None:
    for name in ("constant", "2000", "2025", "postProcessing"):
        (tmp_path / name).mkdir()
    assert module.latest_time_name(tmp_path) == "2025"


def test_lm_warm_start_adds_only_transition_fields(tmp_path: Path) -> None:
    time_dir = tmp_path / "2100"
    time_dir.mkdir()
    expected = {
        "U": ("volVectorField", "[0 1 -1 0 0 0 0]"),
        "p": ("volScalarField", "[0 2 -2 0 0 0 0]"),
        "phi": ("surfaceScalarField", "[0 3 -1 0 0 0 0]"),
        "k": ("volScalarField", "[0 2 -2 0 0 0 0]"),
        "omega": ("volScalarField", "[0 0 -1 0 0 0 0]"),
        "nut": ("volScalarField", "[0 2 -1 0 0 0 0]"),
    }
    preserved = tuple(expected)
    for name, (field_class, dimensions) in expected.items():
        (time_dir / name).write_text(
            f"class {field_class};\ndimensions {dimensions};\ninternalField uniform 0;\n"
        )
    before = {name: (time_dir / name).read_bytes() for name in preserved}
    module.validate_sst_warm_start(tmp_path, "2100")
    module.write_lm_transition_fields(tmp_path, "2100")
    assert {name: (time_dir / name).read_bytes() for name in preserved} == before
    assert (time_dir / "gammaInt").exists()
    assert (time_dir / "ReThetat").exists()
    assert module.CASE_SPECS["lm_warm_from_sst_Tu0p5_L0p001c"].warm_start_source == (
        "sst_Tu0p5_L0p001c"
    )


def test_warm_start_copy_excludes_sst_history(tmp_path: Path) -> None:
    source = tmp_path / "sst"
    destination = tmp_path / "lm"
    for relative in ("constant", "system", "2100"):
        (source / relative).mkdir(parents=True)
        (source / relative / "sentinel").write_text(relative)
    (source / "log.simpleFoam_sst_Tu0p5_L0p001c_2050_to_2100.txt").write_text("SST")
    (source / "postProcessing").mkdir()
    (source / "postProcessing" / "sentinel").write_text("SST")
    module.copy_lean_case(
        source,
        destination,
        include_post_processing=False,
        include_logs=False,
    )
    assert (destination / "2100/sentinel").read_text() == "2100"
    assert not list(destination.glob("log.*"))
    assert not (destination / "postProcessing").exists()


def test_restart_cleanup_removes_only_regenerable_yplus_fields(tmp_path: Path) -> None:
    time_dir = tmp_path / "2050"
    time_dir.mkdir()
    for name in ("U", "p", "phi", "k", "omega", "nut", "yPlus", "yPlusShear:yPlus"):
        (time_dir / name).write_text(name)
    module.remove_derived_restart_fields(tmp_path, "2050")
    assert not (time_dir / "yPlus").exists()
    assert not (time_dir / "yPlusShear:yPlus").exists()
    assert all((time_dir / name).read_text() == name for name in ("U", "p", "phi", "k", "omega", "nut"))


def test_lm_warm_start_rejects_unqualified_or_unevolved_sst() -> None:
    spec = module.CASE_SPECS["sst_Tu0p5_L0p001c"]
    stale = {
        "ok": False,
        "stable_force_window": False,
        "finite_force_history": True,
        "contiguous_final_window": False,
        "force_reaches_latest_checkpoint": True,
        "n_force_rows": 50,
        "latest_checkpoint": 2000.0,
    }
    with pytest.raises(RuntimeError, match="qualified, evolved SST"):
        module.require_qualified_sst_summary(stale, spec)

    qualified = {
        **stale,
        "ok": True,
        "stable_force_window": True,
        "contiguous_final_window": True,
        "n_force_rows": 100,
        "latest_checkpoint": 2100.0,
    }
    module.require_qualified_sst_summary(qualified, spec)


def test_case_shell_command_quotes_paths_with_spaces() -> None:
    command = module.case_shell_command(Path("/Volumes/Samsung SSD/cfd case"), "simpleFoam")
    assert command == "cd '/Volumes/Samsung SSD/cfd case' && simpleFoam"


def test_openfoam_scratch_path_rejects_whitespace_before_case_setup(tmp_path: Path) -> None:
    invalid = tmp_path / "scratch with spaces"
    with pytest.raises(ValueError, match="must not contain whitespace"):
        module.validate_openfoam_scratch_path(invalid)
    assert not invalid.exists()


def test_openfoam_scratch_path_accepts_no_whitespace() -> None:
    module.validate_openfoam_scratch_path(Path("/Volumes/hpa-cfd-tmp/architecture_sensitivity"))
    assert not any(character.isspace() for character in str(module.TMP_ROOT))
    assert str(module.SCRATCH_BACKING_ROOT).endswith(
        "/Samsung SSD/hpa-cfd-tmp/architecture_sensitivity"
    )


def test_operational_exit_code_reports_solver_or_preflight_failure() -> None:
    assert module.operational_exit_code([{"process_ok": True}]) == 0
    assert module.operational_exit_code([{"process_ok": True}, {"failure_stage": "dry-run"}]) == 1


def test_solver_lock_rejects_concurrent_runner(tmp_path: Path) -> None:
    first = module.acquire_solver_lock(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="Another WO-006 solver runner"):
            module.acquire_solver_lock(tmp_path)
    finally:
        module.fcntl.flock(first.fileno(), module.fcntl.LOCK_UN)
        first.close()


def test_attempt_ledger_is_append_only(tmp_path: Path) -> None:
    path = tmp_path / "attempts.jsonl"
    first = module.append_attempt_record(path, {"case": "lm", "process_ok": False})
    second = module.append_attempt_record(path, {"case": "sst", "process_ok": True})
    assert first["attempt_id"] == 1
    assert second["attempt_id"] == 2
    rows = [module.json.loads(line) for line in path.read_text().splitlines()]
    assert [row["case"] for row in rows] == ["lm", "sst"]


def test_solver_log_diagnostics_treats_directory_as_missing(tmp_path: Path) -> None:
    assert module.solver_log_diagnostics(tmp_path) == {
        "k_bounding_count": 0,
        "omega_bounding_count": 0,
        "lambda_warning_count": 0,
    }


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


@pytest.mark.parametrize("token", ["nan", "-nan", "inf", "-inf"])
def test_parse_force_coeffs_log_preserves_nonfinite_evidence(tmp_path: Path, token: str) -> None:
    log = tmp_path / "log.simpleFoam_nonfinite.txt"
    log.write_text(
        f"""Time = 2001
forceCoeffs forceCoeffs_total_physical write:
    Cd: 0.030 0.022 {token} 0
    Cl: 1.160 1.159 0.001 0
    CmPitch: -0.130 -0.140 0.010 0
"""
    )
    rows = module.parse_force_coeffs_log(log)
    assert len(rows) == 1
    assert not module.math.isfinite(rows[0]["CD_viscous"])
    assert module.summarize_force_rows(rows)["force_window_status"] == "nonfinite"


def test_force_history_without_time_advance_is_not_a_success(tmp_path: Path) -> None:
    (tmp_path / "2000").mkdir()
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


def test_nonfinite_force_component_cannot_pass_gate() -> None:
    rows = force_rows(100)
    rows[-1]["CD_viscous"] = float("nan")
    summary = module.summarize_force_rows(rows)
    assert summary["finite_force_history"] is False
    assert summary["stable_force_window"] is False
    assert summary["force_window_status"] == "nonfinite"


def test_summarize_discovery_includes_nondefault_existing_recovery_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "OUT_ROOT", tmp_path)
    case_root = tmp_path / "openfoam_cases"
    expected = ["sa_outlet_fixedValue0", "lm_Tu0p5_L0p001c_r2", "pimple_sst_Tu0p5_L0p001c"]
    for name in expected:
        (case_root / name).mkdir(parents=True)
    assert module.discover_existing_case_names() == expected
