from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from .adapters.su2_backend import parse_history, parse_solver_log_quality_metrics
from .convergence import evaluate_baseline_convergence_gate
from .main_wing_real_su2_handoff_probe import (
    _load_mesh_handoff_from_case_report,
    _source_root_for_mesh_handoff,
)


SolverExecutionStatusType = Literal[
    "solver_executed",
    "solver_failed",
    "solver_timeout",
    "solver_unavailable",
    "blocked_before_solver",
]
ConvergenceGateStatusType = Literal["pass", "warn", "fail", "not_run", "unavailable"]
LiftAcceptanceStatusType = Literal["pass", "fail", "not_evaluated"]
MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5 = 1.0


class MainWingRealSolverSmokeProbeReport(BaseModel):
    schema_version: Literal["main_wing_real_solver_smoke_probe.v1"] = (
        "main_wing_real_solver_smoke_probe.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    source_su2_probe_schema: Literal["main_wing_real_su2_handoff_probe.v1"] = (
        "main_wing_real_su2_handoff_probe.v1"
    )
    execution_mode: Literal["real_su2_handoff_solver_smoke"] = (
        "real_su2_handoff_solver_smoke"
    )
    production_default_changed: bool = False
    materialized_handoff_consumed: bool = False
    source_su2_probe_path: str | None = None
    source_materialization_status: str | None = None
    source_mesh_case_report_path: str | None = None
    case_dir: str | None = None
    su2_handoff_path: str | None = None
    runtime_cfg_path: str | None = None
    solver_log_path: str | None = None
    history_path: str | None = None
    convergence_gate_path: str | None = None
    pruned_output_paths: List[str] = Field(default_factory=list)
    retained_output_paths: List[str] = Field(default_factory=list)
    solver_command: List[str] = Field(default_factory=list)
    timeout_seconds: float
    solver_execution_status: SolverExecutionStatusType
    convergence_gate_status: ConvergenceGateStatusType
    run_status: str
    return_code: int | None = None
    final_iteration: int | None = None
    final_coefficients: Dict[str, float | str | None] = Field(default_factory=dict)
    solver_log_quality_metrics: Dict[str, Any] = Field(default_factory=dict)
    main_wing_lift_acceptance_status: LiftAcceptanceStatusType = "not_evaluated"
    minimum_acceptable_cl: float = MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5
    convergence_comparability_level: str | None = None
    component_force_ownership_status: str | None = None
    reference_geometry_status: str | None = None
    observed_velocity_mps: float | None = None
    runtime_max_iterations: int | None = None
    volume_element_count: int | None = None
    hpa_mdo_guarantees: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    error: str | None = None


def _default_source_su2_probe_report_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "reports"
        / "main_wing_real_su2_handoff_probe"
        / "main_wing_real_su2_handoff_probe.v1.json"
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _resolve_payload_path(
    value: str | None,
    *,
    source_report_path: Path,
    fallback: Path | None = None,
) -> Path | None:
    if value is None:
        return fallback
    raw = Path(value)
    if raw.is_absolute():
        return raw
    for root in [Path.cwd(), source_report_path.parent, *source_report_path.parents]:
        candidate = (root / raw).resolve()
        if candidate.exists():
            return candidate
    return (Path.cwd() / raw).resolve()


def _runtime_velocity(su2_handoff: dict[str, Any], source_report: dict[str, Any]) -> float | None:
    runtime = su2_handoff.get("runtime", {})
    velocity = runtime.get("velocity_mps") if isinstance(runtime, dict) else None
    if isinstance(velocity, (int, float)):
        return float(velocity)
    report_velocity = source_report.get("observed_velocity_mps")
    return float(report_velocity) if isinstance(report_velocity, (int, float)) else None


def _runtime_max_iterations(
    su2_handoff: dict[str, Any],
    source_report: dict[str, Any],
) -> int | None:
    runtime = su2_handoff.get("runtime", {})
    max_iterations = runtime.get("max_iterations") if isinstance(runtime, dict) else None
    if isinstance(max_iterations, int):
        return max_iterations
    if isinstance(max_iterations, float):
        return int(max_iterations)
    report_iterations = source_report.get("runtime_max_iterations")
    if isinstance(report_iterations, int):
        return report_iterations
    if isinstance(report_iterations, float):
        return int(report_iterations)
    return None


def _solver_command(su2_handoff: dict[str, Any]) -> list[str]:
    command = su2_handoff.get("solver_command")
    if isinstance(command, list) and all(isinstance(item, str) for item in command):
        return list(command)
    runtime = su2_handoff.get("runtime", {})
    solver = runtime.get("solver_command", "SU2_CFD") if isinstance(runtime, dict) else "SU2_CFD"
    threads = runtime.get("cpu_threads", 4) if isinstance(runtime, dict) else 4
    try:
        thread_count = max(1, int(threads))
    except (TypeError, ValueError):
        thread_count = 4
    return [str(solver), "-t", str(thread_count), "su2_runtime.cfg"]


def _runtime_env(su2_handoff: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    command = _solver_command(su2_handoff)
    if "-t" in command:
        index = command.index("-t")
        if index + 1 < len(command):
            env["OMP_NUM_THREADS"] = command[index + 1]
    return env


def _missing_executable(command: list[str], su2_handoff: dict[str, Any]) -> str | None:
    if not command:
        return "SU2_CFD"
    launch_command = command[0]
    if shutil.which(launch_command) is None:
        return launch_command
    runtime = su2_handoff.get("runtime", {})
    solver_command = (
        runtime.get("solver_command") if isinstance(runtime, dict) else None
    )
    if launch_command in {"mpirun", "mpiexec"} and isinstance(solver_command, str):
        if shutil.which(solver_command) is None:
            return solver_command
    return None


def _find_history_file(case_dir: Path) -> Path | None:
    for candidate in (
        case_dir / "history.csv",
        case_dir / "history.dat",
        case_dir / "conv_history.csv",
        case_dir / "conv_history.dat",
    ):
        if candidate.exists():
            return candidate
    return None


def _clear_known_history_outputs(case_dir: Path) -> None:
    for name in ("history.csv", "history.dat", "conv_history.csv", "conv_history.dat"):
        path = case_dir / name
        if path.exists():
            path.unlink()


def _clear_previous_solver_outputs(case_dir: Path) -> None:
    _clear_known_history_outputs(case_dir)
    for name in ("restart.csv", "surface.csv", "forces_breakdown.dat", "vol_solution.vtk"):
        path = case_dir / name
        if path.exists():
            path.unlink()


def _prune_heavy_solver_outputs(case_dir: Path) -> list[Path]:
    pruned: list[Path] = []
    for name in ("restart.csv", "vol_solution.vtk"):
        path = case_dir / name
        if path.exists():
            path.unlink()
            pruned.append(path)
    return pruned


def _retained_surface_force_output_paths(case_dir: Path) -> list[Path]:
    return [
        path
        for path in (case_dir / "surface.csv", case_dir / "forces_breakdown.dat")
        if path.exists()
    ]


def _gate_status(convergence_gate: Any) -> str | None:
    overall = getattr(convergence_gate, "overall_convergence_gate", None)
    status = getattr(overall, "status", None)
    return str(status) if status is not None else None


def _gate_comparability(convergence_gate: Any) -> str | None:
    overall = getattr(convergence_gate, "overall_convergence_gate", None)
    level = getattr(overall, "comparability_level", None)
    return str(level) if level is not None else None


def _main_wing_lift_acceptance_status(
    *,
    cl: Any,
    observed_velocity_mps: float | None,
) -> LiftAcceptanceStatusType:
    if observed_velocity_mps is None or abs(observed_velocity_mps - 6.5) > 1.0e-9:
        return "not_evaluated"
    if not isinstance(cl, (int, float)):
        return "not_evaluated"
    return "pass" if float(cl) > MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5 else "fail"


def _apply_main_wing_lift_acceptance_to_gate_payload(
    gate_payload: dict[str, Any],
    *,
    lift_status: LiftAcceptanceStatusType,
    cl: Any,
    observed_velocity_mps: float | None,
) -> dict[str, Any]:
    lift_section = {
        "status": lift_status,
        "confidence": "high" if lift_status in {"pass", "fail"} else "low",
        "checks": {
            "main_wing_cl_at_hpa_6p5": {
                "status": lift_status,
                "observed": {
                    "cl": cl,
                    "velocity_mps": observed_velocity_mps,
                },
                "expected": {
                    "velocity_mps": 6.5,
                    "minimum_acceptable_cl_exclusive": MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5,
                },
                "warnings": (
                    ["main_wing_cl_below_expected_lift"]
                    if lift_status == "fail"
                    else []
                ),
                "notes": [
                    "Main-wing convergence acceptance at HPA 6.5 m/s requires CL > 1."
                ],
            }
        },
        "warnings": (
            ["main_wing_cl_below_expected_lift"] if lift_status == "fail" else []
        ),
        "notes": [
            "This is a main-wing lift sanity gate; it does not replace residual or coefficient stability checks."
        ],
    }
    gate_payload["main_wing_lift_acceptance"] = lift_section
    overall = gate_payload.get("overall_convergence_gate", {})
    if isinstance(overall, dict):
        checks = overall.setdefault("checks", {})
        if isinstance(checks, dict):
            checks["main_wing_lift_acceptance"] = {
                "status": lift_status,
                "observed": {"status": lift_status},
                "expected": {"status": "pass"},
                "warnings": (
                    ["main_wing_cl_below_expected_lift"]
                    if lift_status == "fail"
                    else []
                ),
                "notes": [],
            }
        if lift_status == "fail":
            overall["status"] = "fail"
            overall["confidence"] = "low"
            overall["comparability_level"] = "not_comparable"
            warnings = overall.setdefault("warnings", [])
            if isinstance(warnings, list) and "main_wing_lift_acceptance=fail" not in warnings:
                warnings.append("main_wing_lift_acceptance=fail")
            notes = overall.setdefault("notes", [])
            if isinstance(notes, list):
                notes.append(
                    "Main-wing CL is below the HPA 6.5 m/s acceptance threshold."
                )
    return gate_payload


def _copy_solver_raw_artifacts(
    out_dir: Path,
    report: MainWingRealSolverSmokeProbeReport,
) -> None:
    raw_dir = out_dir / "artifacts" / "raw_solver"
    candidates: list[Path] = []
    for value in (
        report.history_path,
        report.solver_log_path,
        *report.retained_output_paths,
    ):
        if value:
            candidates.append(Path(value))
    if report.case_dir:
        case_dir = Path(report.case_dir)
        candidates.extend(
            [
                case_dir / "surface.csv",
                case_dir / "forces_breakdown.dat",
            ]
        )
    copied: set[Path] = set()
    for source in candidates:
        if not source.exists() or not source.is_file():
            continue
        resolved = source.resolve()
        if resolved in copied:
            continue
        raw_dir.mkdir(parents=True, exist_ok=True)
        destination = raw_dir / source.name
        if destination.exists() and destination.resolve() == resolved:
            copied.add(resolved)
            continue
        shutil.copy2(source, destination)
        copied.add(resolved)


def _blocked_report(
    *,
    source_report_path: Path | None,
    source_report: dict[str, Any] | None,
    timeout_seconds: float,
    run_status: str,
    solver_execution_status: SolverExecutionStatusType,
    blocking_reasons: list[str],
    error: str | None = None,
) -> MainWingRealSolverSmokeProbeReport:
    return MainWingRealSolverSmokeProbeReport(
        materialized_handoff_consumed=False,
        source_su2_probe_path=None if source_report_path is None else str(source_report_path),
        source_materialization_status=None
        if source_report is None
        else str(source_report.get("materialization_status")),
        source_mesh_case_report_path=None
        if source_report is None
        else source_report.get("source_mesh_case_report_path"),
        case_dir=None if source_report is None else source_report.get("case_dir"),
        timeout_seconds=float(timeout_seconds),
        solver_execution_status=solver_execution_status,
        convergence_gate_status="not_run",
        run_status=run_status,
        component_force_ownership_status=None
        if source_report is None
        else source_report.get("component_force_ownership_status"),
        reference_geometry_status=None
        if source_report is None
        else source_report.get("reference_geometry_status"),
        observed_velocity_mps=None
        if source_report is None
        else source_report.get("observed_velocity_mps"),
        runtime_max_iterations=None
        if source_report is None
        else source_report.get("runtime_max_iterations"),
        volume_element_count=None
        if source_report is None
        else source_report.get("volume_element_count"),
        hpa_mdo_guarantees=[
            "solver_not_claimed_converged",
            "production_default_unchanged",
        ],
        blocking_reasons=blocking_reasons,
        limitations=[
            "SU2_CFD did not complete a usable solver smoke run.",
            "convergence_gate.v1 was not emitted.",
            "Production defaults were not changed.",
        ],
        error=error,
    )


def build_main_wing_real_solver_smoke_probe_report(
    out_dir: Path,
    *,
    source_su2_probe_report_path: Path | None = None,
    timeout_seconds: float = 120.0,
) -> MainWingRealSolverSmokeProbeReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    source_report_path = (
        _default_source_su2_probe_report_path()
        if source_su2_probe_report_path is None
        else source_su2_probe_report_path
    )
    try:
        source_report = _load_json(source_report_path)
    except Exception as exc:
        return _blocked_report(
            source_report_path=source_report_path,
            source_report=None,
            timeout_seconds=timeout_seconds,
            run_status="source_su2_probe_report_unavailable",
            solver_execution_status="blocked_before_solver",
            blocking_reasons=[
                "main_wing_real_su2_handoff_probe_report_unavailable",
                "main_wing_solver_not_run",
                "convergence_gate_not_run",
            ],
            error=str(exc),
        )

    if source_report.get("materialization_status") != "su2_handoff_written":
        return _blocked_report(
            source_report_path=source_report_path,
            source_report=source_report,
            timeout_seconds=timeout_seconds,
            run_status="blocked_before_solver",
            solver_execution_status="blocked_before_solver",
            blocking_reasons=[
                "main_wing_real_su2_handoff_not_materialized",
                "main_wing_solver_not_run",
                "convergence_gate_not_run",
            ],
            error=source_report.get("error"),
        )

    case_dir = _resolve_payload_path(
        source_report.get("case_dir"),
        source_report_path=source_report_path,
    )
    su2_handoff_path = _resolve_payload_path(
        source_report.get("su2_handoff_path"),
        source_report_path=source_report_path,
        fallback=None if case_dir is None else case_dir / "su2_handoff.json",
    )
    if case_dir is None or su2_handoff_path is None:
        return _blocked_report(
            source_report_path=source_report_path,
            source_report=source_report,
            timeout_seconds=timeout_seconds,
            run_status="case_paths_unavailable",
            solver_execution_status="blocked_before_solver",
            blocking_reasons=[
                "main_wing_real_su2_case_paths_unavailable",
                "main_wing_solver_not_run",
                "convergence_gate_not_run",
            ],
        )

    try:
        su2_handoff = _load_json(su2_handoff_path)
    except Exception as exc:
        return _blocked_report(
            source_report_path=source_report_path,
            source_report=source_report,
            timeout_seconds=timeout_seconds,
            run_status="su2_handoff_unavailable",
            solver_execution_status="blocked_before_solver",
            blocking_reasons=[
                "main_wing_real_su2_handoff_json_unavailable",
                "main_wing_solver_not_run",
                "convergence_gate_not_run",
            ],
            error=str(exc),
        )

    runtime_cfg_path = _resolve_payload_path(
        source_report.get("runtime_cfg_path")
        or su2_handoff.get("runtime_cfg_path"),
        source_report_path=source_report_path,
        fallback=case_dir / "su2_runtime.cfg",
    )
    case_outputs = su2_handoff.get("case_output_paths", {})
    solver_log_path = _resolve_payload_path(
        case_outputs.get("solver_log") if isinstance(case_outputs, dict) else None,
        source_report_path=source_report_path,
        fallback=case_dir / "solver.log",
    )
    source_mesh_case_report_path = _resolve_payload_path(
        source_report.get("source_mesh_case_report_path"),
        source_report_path=source_report_path,
    )
    command = _solver_command(su2_handoff)
    missing_executable = _missing_executable(command, su2_handoff)
    observed_velocity = _runtime_velocity(su2_handoff, source_report)
    runtime_max_iterations = _runtime_max_iterations(su2_handoff, source_report)
    base_guarantees = [
        "real_main_wing_su2_handoff_v1_consumed",
        "solver_not_claimed_converged_without_gate_pass",
        "production_default_unchanged",
    ]
    if observed_velocity == 6.5:
        base_guarantees.append("hpa_standard_flow_conditions_6p5_mps")

    if missing_executable is not None:
        return MainWingRealSolverSmokeProbeReport(
            materialized_handoff_consumed=True,
            source_su2_probe_path=str(source_report_path),
            source_materialization_status=str(source_report.get("materialization_status")),
            source_mesh_case_report_path=None
            if source_mesh_case_report_path is None
            else str(source_mesh_case_report_path),
            case_dir=str(case_dir),
            su2_handoff_path=str(su2_handoff_path),
            runtime_cfg_path=None if runtime_cfg_path is None else str(runtime_cfg_path),
            solver_log_path=None if solver_log_path is None else str(solver_log_path),
            solver_command=command,
            timeout_seconds=float(timeout_seconds),
            solver_execution_status="solver_unavailable",
            convergence_gate_status="not_run",
            run_status="solver_executable_missing",
            component_force_ownership_status=source_report.get("component_force_ownership_status"),
            reference_geometry_status=source_report.get("reference_geometry_status"),
            observed_velocity_mps=observed_velocity,
            runtime_max_iterations=runtime_max_iterations,
            volume_element_count=source_report.get("volume_element_count"),
            hpa_mdo_guarantees=base_guarantees,
            blocking_reasons=[
                "su2_solver_executable_missing",
                "main_wing_solver_not_run",
                "convergence_gate_not_run",
            ],
            limitations=[
                "SU2_CFD executable was not available on PATH, so no solver run happened.",
                "convergence_gate.v1 was not emitted.",
                "Production defaults were not changed.",
            ],
            error=f"{missing_executable} not found on PATH",
        )

    if solver_log_path is None:
        solver_log_path = case_dir / "solver.log"
    solver_log_path.parent.mkdir(parents=True, exist_ok=True)
    _clear_previous_solver_outputs(case_dir)
    _prune_heavy_solver_outputs(case_dir)

    try:
        with solver_log_path.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                command,
                cwd=case_dir,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=float(timeout_seconds),
                env=_runtime_env(su2_handoff),
            )
    except subprocess.TimeoutExpired as exc:
        pruned_output_paths = _prune_heavy_solver_outputs(case_dir)
        return MainWingRealSolverSmokeProbeReport(
            materialized_handoff_consumed=True,
            source_su2_probe_path=str(source_report_path),
            source_materialization_status=str(source_report.get("materialization_status")),
            source_mesh_case_report_path=None
            if source_mesh_case_report_path is None
            else str(source_mesh_case_report_path),
            case_dir=str(case_dir),
            su2_handoff_path=str(su2_handoff_path),
            runtime_cfg_path=None if runtime_cfg_path is None else str(runtime_cfg_path),
            solver_log_path=str(solver_log_path),
            solver_command=command,
            timeout_seconds=float(timeout_seconds),
            solver_execution_status="solver_timeout",
            convergence_gate_status="not_run",
            run_status="solver_timeout",
            component_force_ownership_status=source_report.get("component_force_ownership_status"),
            reference_geometry_status=source_report.get("reference_geometry_status"),
            observed_velocity_mps=observed_velocity,
            runtime_max_iterations=runtime_max_iterations,
            volume_element_count=source_report.get("volume_element_count"),
            hpa_mdo_guarantees=base_guarantees,
            blocking_reasons=[
                "main_wing_solver_timeout",
                "convergence_gate_not_run",
            ],
            limitations=[
                "SU2_CFD was launched but exceeded the bounded smoke timeout.",
                "A timeout is not a convergence result.",
                "Production defaults were not changed.",
            ],
            error=str(exc),
        )
    except Exception as exc:
        return MainWingRealSolverSmokeProbeReport(
            materialized_handoff_consumed=True,
            source_su2_probe_path=str(source_report_path),
            source_materialization_status=str(source_report.get("materialization_status")),
            source_mesh_case_report_path=None
            if source_mesh_case_report_path is None
            else str(source_mesh_case_report_path),
            case_dir=str(case_dir),
            su2_handoff_path=str(su2_handoff_path),
            runtime_cfg_path=None if runtime_cfg_path is None else str(runtime_cfg_path),
            solver_log_path=str(solver_log_path),
            solver_command=command,
            timeout_seconds=float(timeout_seconds),
            solver_execution_status="solver_failed",
            convergence_gate_status="not_run",
            run_status="solver_execution_failed",
            component_force_ownership_status=source_report.get("component_force_ownership_status"),
            reference_geometry_status=source_report.get("reference_geometry_status"),
            observed_velocity_mps=observed_velocity,
            runtime_max_iterations=runtime_max_iterations,
            volume_element_count=source_report.get("volume_element_count"),
            hpa_mdo_guarantees=base_guarantees,
            blocking_reasons=[
                "main_wing_solver_execution_failed",
                "convergence_gate_not_run",
            ],
            limitations=[
                "SU2_CFD launch failed before a parseable history could be evaluated.",
                "convergence_gate.v1 was not emitted.",
                "Production defaults were not changed.",
            ],
            error=str(exc),
        )

    pruned_output_paths = _prune_heavy_solver_outputs(case_dir)

    if completed.returncode != 0:
        return MainWingRealSolverSmokeProbeReport(
            materialized_handoff_consumed=True,
            source_su2_probe_path=str(source_report_path),
            source_materialization_status=str(source_report.get("materialization_status")),
            source_mesh_case_report_path=None
            if source_mesh_case_report_path is None
            else str(source_mesh_case_report_path),
            case_dir=str(case_dir),
            su2_handoff_path=str(su2_handoff_path),
            runtime_cfg_path=None if runtime_cfg_path is None else str(runtime_cfg_path),
            solver_log_path=str(solver_log_path),
            solver_command=command,
            timeout_seconds=float(timeout_seconds),
            solver_execution_status="solver_failed",
            convergence_gate_status="not_run",
            run_status="solver_execution_failed",
            return_code=int(completed.returncode),
            component_force_ownership_status=source_report.get("component_force_ownership_status"),
            reference_geometry_status=source_report.get("reference_geometry_status"),
            observed_velocity_mps=observed_velocity,
            runtime_max_iterations=runtime_max_iterations,
            volume_element_count=source_report.get("volume_element_count"),
            hpa_mdo_guarantees=base_guarantees,
            blocking_reasons=[
                "main_wing_solver_execution_failed",
                "convergence_gate_not_run",
            ],
            limitations=[
                "SU2_CFD returned a nonzero exit code.",
                "A failed solver launch is not convergence evidence.",
                "Production defaults were not changed.",
            ],
            error=f"{command[0]} exited with code {completed.returncode}",
        )

    history_path = _find_history_file(case_dir)
    if history_path is None:
        return MainWingRealSolverSmokeProbeReport(
            materialized_handoff_consumed=True,
            source_su2_probe_path=str(source_report_path),
            source_materialization_status=str(source_report.get("materialization_status")),
            source_mesh_case_report_path=None
            if source_mesh_case_report_path is None
            else str(source_mesh_case_report_path),
            case_dir=str(case_dir),
            su2_handoff_path=str(su2_handoff_path),
            runtime_cfg_path=None if runtime_cfg_path is None else str(runtime_cfg_path),
            solver_log_path=str(solver_log_path),
            solver_command=command,
            timeout_seconds=float(timeout_seconds),
            solver_execution_status="solver_executed",
            convergence_gate_status="not_run",
            run_status="history_missing",
            return_code=0,
            component_force_ownership_status=source_report.get("component_force_ownership_status"),
            reference_geometry_status=source_report.get("reference_geometry_status"),
            observed_velocity_mps=observed_velocity,
            runtime_max_iterations=runtime_max_iterations,
            volume_element_count=source_report.get("volume_element_count"),
            hpa_mdo_guarantees=base_guarantees,
            blocking_reasons=[
                "main_wing_solver_history_missing",
                "convergence_gate_not_run",
            ],
            limitations=[
                "SU2_CFD exited with code 0 but did not leave a parseable history file.",
                "convergence_gate.v1 was not emitted.",
                "Production defaults were not changed.",
            ],
            error="SU2 completed without writing a history file",
        )

    try:
        parsed_history = parse_history(history_path)
    except Exception as exc:
        return MainWingRealSolverSmokeProbeReport(
            materialized_handoff_consumed=True,
            source_su2_probe_path=str(source_report_path),
            source_materialization_status=str(source_report.get("materialization_status")),
            source_mesh_case_report_path=None
            if source_mesh_case_report_path is None
            else str(source_mesh_case_report_path),
            case_dir=str(case_dir),
            su2_handoff_path=str(su2_handoff_path),
            runtime_cfg_path=None if runtime_cfg_path is None else str(runtime_cfg_path),
            solver_log_path=str(solver_log_path),
            history_path=str(history_path),
            solver_command=command,
            timeout_seconds=float(timeout_seconds),
            solver_execution_status="solver_executed",
            convergence_gate_status="not_run",
            run_status="history_parse_failed",
            return_code=0,
            component_force_ownership_status=source_report.get("component_force_ownership_status"),
            reference_geometry_status=source_report.get("reference_geometry_status"),
            observed_velocity_mps=observed_velocity,
            runtime_max_iterations=runtime_max_iterations,
            volume_element_count=source_report.get("volume_element_count"),
            hpa_mdo_guarantees=base_guarantees,
            blocking_reasons=[
                "main_wing_solver_history_parse_failed",
                "convergence_gate_not_run",
            ],
            limitations=[
                "SU2_CFD executed, but the history file could not be parsed.",
                "convergence_gate.v1 was not emitted.",
                "Production defaults were not changed.",
            ],
            error=str(exc),
        )

    try:
        if source_mesh_case_report_path is None:
            raise ValueError("source_mesh_case_report_path missing")
        mesh_handoff = _load_mesh_handoff_from_case_report(source_mesh_case_report_path)
        convergence_gate = evaluate_baseline_convergence_gate(
            mesh_handoff,
            history_path=history_path,
            provenance_gates=su2_handoff.get("provenance_gates", {}),
            source_root=_source_root_for_mesh_handoff(mesh_handoff, source_report_path),
        )
    except Exception as exc:
        return MainWingRealSolverSmokeProbeReport(
            materialized_handoff_consumed=True,
            source_su2_probe_path=str(source_report_path),
            source_materialization_status=str(source_report.get("materialization_status")),
            source_mesh_case_report_path=None
            if source_mesh_case_report_path is None
            else str(source_mesh_case_report_path),
            case_dir=str(case_dir),
            su2_handoff_path=str(su2_handoff_path),
            runtime_cfg_path=None if runtime_cfg_path is None else str(runtime_cfg_path),
            solver_log_path=str(solver_log_path),
            history_path=str(history_path),
            solver_command=command,
            timeout_seconds=float(timeout_seconds),
            solver_execution_status="solver_executed",
            convergence_gate_status="unavailable",
            run_status="convergence_gate_evaluation_failed",
            return_code=0,
            final_iteration=parsed_history.get("final_iteration"),
            final_coefficients={
                "cl": parsed_history.get("cl"),
                "cd": parsed_history.get("cd"),
                "cm": parsed_history.get("cm"),
                "cm_axis": parsed_history.get("cm_axis"),
            },
            component_force_ownership_status=source_report.get("component_force_ownership_status"),
            reference_geometry_status=source_report.get("reference_geometry_status"),
            observed_velocity_mps=observed_velocity,
            runtime_max_iterations=runtime_max_iterations,
            volume_element_count=source_report.get("volume_element_count"),
            hpa_mdo_guarantees=base_guarantees,
            blocking_reasons=[
                "main_wing_convergence_gate_evaluation_failed",
            ],
            limitations=[
                "SU2_CFD executed and history exists, but convergence gate evaluation failed.",
                "This is solver smoke evidence only, not a convergence pass.",
                "Production defaults were not changed.",
            ],
            error=str(exc),
        )

    gate_payload = (
        convergence_gate.model_dump(mode="json")
        if hasattr(convergence_gate, "model_dump")
        else dict(convergence_gate)
    )
    solver_log_quality_metrics = parse_solver_log_quality_metrics(solver_log_path)
    final_cl = parsed_history.get("cl")
    lift_acceptance_status = _main_wing_lift_acceptance_status(
        cl=final_cl,
        observed_velocity_mps=observed_velocity,
    )
    gate_payload = _apply_main_wing_lift_acceptance_to_gate_payload(
        gate_payload,
        lift_status=lift_acceptance_status,
        cl=final_cl,
        observed_velocity_mps=observed_velocity,
    )
    convergence_gate_path = out_dir / "artifacts" / "convergence_gate.v1.json"
    _write_json(convergence_gate_path, gate_payload)
    status = (
        gate_payload.get("overall_convergence_gate", {}).get("status")
        if isinstance(gate_payload.get("overall_convergence_gate"), dict)
        else _gate_status(convergence_gate)
    ) or "unavailable"
    comparability = (
        gate_payload.get("overall_convergence_gate", {}).get("comparability_level")
        if isinstance(gate_payload.get("overall_convergence_gate"), dict)
        else _gate_comparability(convergence_gate)
    )
    if status == "pass":
        run_status = "solver_executed_and_converged"
        blocking_reasons: list[str] = []
    else:
        run_status = "solver_executed_but_not_converged"
        blocking_reasons = ["solver_executed_but_not_converged"]
    if lift_acceptance_status == "fail":
        blocking_reasons.append("main_wing_cl_below_expected_lift")
    reference_status = source_report.get("reference_geometry_status")
    if reference_status in {"warn", "fail"}:
        blocking_reasons.append(f"main_wing_real_reference_geometry_{reference_status}")
    retained_output_paths = _retained_surface_force_output_paths(case_dir)

    guarantees = [
        *base_guarantees,
        "su2_solver_executed",
        "history_file_written",
        "convergence_gate_v1_emitted",
    ]
    if status == "pass":
        guarantees.append("convergence_gate_passed")
    if pruned_output_paths:
        guarantees.append("heavy_solver_outputs_pruned")
    if retained_output_paths:
        guarantees.append("surface_force_outputs_retained")

    return MainWingRealSolverSmokeProbeReport(
        materialized_handoff_consumed=True,
        source_su2_probe_path=str(source_report_path),
        source_materialization_status=str(source_report.get("materialization_status")),
        source_mesh_case_report_path=None
        if source_mesh_case_report_path is None
        else str(source_mesh_case_report_path),
        case_dir=str(case_dir),
        su2_handoff_path=str(su2_handoff_path),
        runtime_cfg_path=None if runtime_cfg_path is None else str(runtime_cfg_path),
        solver_log_path=str(solver_log_path),
        history_path=str(history_path),
        convergence_gate_path=str(convergence_gate_path),
        pruned_output_paths=[str(path) for path in pruned_output_paths],
        retained_output_paths=[str(path) for path in retained_output_paths],
        solver_command=command,
        timeout_seconds=float(timeout_seconds),
        solver_execution_status="solver_executed",
        convergence_gate_status=(
            status if status in {"pass", "warn", "fail"} else "unavailable"
        ),
        run_status=run_status,
        return_code=0,
        final_iteration=parsed_history.get("final_iteration"),
        final_coefficients={
            "cl": final_cl,
            "cd": parsed_history.get("cd"),
            "cm": parsed_history.get("cm"),
            "cm_axis": parsed_history.get("cm_axis"),
        },
        solver_log_quality_metrics=solver_log_quality_metrics,
        main_wing_lift_acceptance_status=lift_acceptance_status,
        minimum_acceptable_cl=MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5,
        convergence_comparability_level=comparability,
        component_force_ownership_status=source_report.get("component_force_ownership_status"),
        reference_geometry_status=reference_status,
        observed_velocity_mps=observed_velocity,
        runtime_max_iterations=runtime_max_iterations,
        volume_element_count=source_report.get("volume_element_count"),
        hpa_mdo_guarantees=guarantees,
        blocking_reasons=blocking_reasons,
        limitations=[
            "Solver execution is not the same as convergence; only a pass convergence gate can be called converged.",
            "At HPA standard V=6.5 m/s, main-wing convergence acceptance additionally requires CL > 1.",
            "Reference geometry warn/fail remains a comparability blocker even when the solver runs.",
            "The upstream mesh is a coarse bounded probe, not production default sizing.",
            "Production defaults were not changed.",
        ],
    )


def _render_markdown(report: MainWingRealSolverSmokeProbeReport) -> str:
    lines = [
        "# main_wing real solver smoke probe v1",
        "",
        "This probe runs SU2_CFD from the real main-wing SU2 handoff and keeps solver execution separate from convergence.",
        "",
        f"- run_status: `{report.run_status}`",
        f"- solver_execution_status: `{report.solver_execution_status}`",
        f"- convergence_gate_status: `{report.convergence_gate_status}`",
        f"- convergence_comparability_level: `{report.convergence_comparability_level}`",
        f"- return_code: `{report.return_code}`",
        f"- final_iteration: `{report.final_iteration}`",
        f"- observed_velocity_mps: `{report.observed_velocity_mps}`",
        f"- minimum_acceptable_cl: `{report.minimum_acceptable_cl}`",
        f"- main_wing_lift_acceptance_status: `{report.main_wing_lift_acceptance_status}`",
        f"- component_force_ownership_status: `{report.component_force_ownership_status}`",
        f"- reference_geometry_status: `{report.reference_geometry_status}`",
        f"- runtime_max_iterations: `{report.runtime_max_iterations}`",
        f"- history_path: `{report.history_path}`",
        f"- solver_log_path: `{report.solver_log_path}`",
        f"- convergence_gate_path: `{report.convergence_gate_path}`",
        f"- error: `{report.error}`",
        "",
        "## Blocking Reasons",
        "",
    ]
    lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    if report.solver_log_quality_metrics:
        dual_quality = report.solver_log_quality_metrics.get(
            "dual_control_volume_quality", {}
        )
        curvature = report.solver_log_quality_metrics.get("surface_curvature", {})
        lines.extend(["", "## Solver Log Mesh Quality", ""])
        lines.extend(
            [
                f"- max_surface_curvature: `{curvature.get('max')}`",
                "- min_orthogonality_angle_deg: "
                f"`{dual_quality.get('orthogonality_angle_deg', {}).get('min')}`",
                "- max_cv_face_area_aspect_ratio: "
                f"`{dual_quality.get('cv_face_area_aspect_ratio', {}).get('max')}`",
                "- max_cv_sub_volume_ratio: "
                f"`{dual_quality.get('cv_sub_volume_ratio', {}).get('max')}`",
            ]
        )
    lines.extend(["", "## HPA-MDO Guarantees", ""])
    lines.extend(f"- `{guarantee}`" for guarantee in report.hpa_mdo_guarantees)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_main_wing_real_solver_smoke_probe_report(
    out_dir: Path,
    report: MainWingRealSolverSmokeProbeReport | None = None,
    *,
    source_su2_probe_report_path: Path | None = None,
    timeout_seconds: float = 120.0,
) -> Dict[str, Path]:
    if report is None:
        report = build_main_wing_real_solver_smoke_probe_report(
            out_dir,
            source_su2_probe_report_path=source_su2_probe_report_path,
            timeout_seconds=timeout_seconds,
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "main_wing_real_solver_smoke_probe.v1.json"
    markdown_path = out_dir / "main_wing_real_solver_smoke_probe.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    _copy_solver_raw_artifacts(out_dir, report)
    return {"json": json_path, "markdown": markdown_path}
