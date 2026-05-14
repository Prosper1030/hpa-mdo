#!/usr/bin/env python3
"""Probe whether WO-006J pressure drag is partly numerical-scheme driven.

This is a diagnostic-only runner. It reuses the existing WO-006J large-domain
Euler mesh and rewrites the solver config for an explicit FDS + MUSCL probe.
It does not generate a new Baseline A geometry, does not change external shape,
and must not be promoted to CFD ladder completion.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_ROOT = REPO_ROOT / "output" / "baseline_A_team_release" / "wo006_su2_baseline_validation"
DEFAULT_SOURCE_CASE = VALIDATION_ROOT / "wo006j_farfield20x40_euler_pressure_probe_wing020"
DEFAULT_OUTPUT_DIR = VALIDATION_ROOT / "wo006j_numerics_sensitivity_probe"
DEFAULT_SOLVER_COMMAND = "/Users/linyuan/.local/opt/su2/current/bin/SU2_CFD"
HPA_MAIN_WING_CD_PLAUSIBILITY_MAX = 0.15


@dataclass(frozen=True)
class HistorySummary:
    row_count: int
    final_iteration: int | None
    final_coefficients: dict[str, float | None]
    last_window: dict[str, Any]


def force_single_su2_key(cfg_text: str, key: str, value: str) -> str:
    """Return config text with exactly one ``KEY= value`` assignment."""

    key_pattern = re.compile(rf"^\s*{re.escape(key)}\s*=", flags=re.IGNORECASE)
    replacement = f"{key}= {value}"
    lines = cfg_text.splitlines()
    output: list[str] = []
    replaced = False
    for line in lines:
        if not key_pattern.match(line):
            output.append(line)
            continue
        if not replaced:
            output.append(replacement)
            replaced = True
    if not replaced:
        output.append(replacement)
    return "\n".join(output).rstrip() + "\n"


def prepare_probe_case(
    *,
    source_case_dir: Path,
    output_case_dir: Path,
    iteration_count: int = 750,
    cfl_number: float = 0.5,
    slope_limiter_flow: str = "NONE",
) -> dict[str, Any]:
    """Copy the existing mesh and prepare a second-order FDS/MUSCL config."""

    if iteration_count <= 0:
        raise ValueError("iteration_count must be positive")
    if cfl_number <= 0.0:
        raise ValueError("cfl_number must be positive")
    resolved_slope_limiter = slope_limiter_flow.strip().upper()
    if not resolved_slope_limiter:
        raise ValueError("slope_limiter_flow must not be empty")

    source_case_dir = Path(source_case_dir)
    output_case_dir = Path(output_case_dir)
    source_mesh = source_case_dir / "mesh.su2"
    source_cfg = source_case_dir / "su2_runtime.cfg"
    if not source_mesh.is_file():
        raise FileNotFoundError(f"Missing source mesh: {source_mesh}")
    if not source_cfg.is_file():
        raise FileNotFoundError(f"Missing source SU2 config: {source_cfg}")

    output_case_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_mesh, output_case_dir / "mesh.su2")

    cfg = source_cfg.read_text(encoding="utf-8", errors="replace")
    cfg = force_single_su2_key(cfg, "SOLVER", "INC_EULER")
    cfg = force_single_su2_key(cfg, "KIND_TURB_MODEL", "NONE")
    cfg = force_single_su2_key(cfg, "CONV_NUM_METHOD_FLOW", "FDS")
    cfg = force_single_su2_key(cfg, "MUSCL_FLOW", "YES")
    cfg = force_single_su2_key(cfg, "SLOPE_LIMITER_FLOW", resolved_slope_limiter)
    cfg = force_single_su2_key(cfg, "ITER", str(int(iteration_count)))
    cfg = force_single_su2_key(cfg, "CFL_NUMBER", _format_su2_value(cfl_number))
    cfg = force_single_su2_key(cfg, "CONV_STARTITER", "10000")
    cfg = force_single_su2_key(cfg, "OUTPUT_FILES", "(RESTART_ASCII, SURFACE_CSV)")
    cfg += (
        "\n% WO-006J diagnostic only: FDS + MUSCL pressure-drag sensitivity probe.\n"
        "% Do not treat this case as BL-resolved CFD or grid-convergence evidence.\n"
    )
    (output_case_dir / "su2_runtime.cfg").write_text(cfg, encoding="utf-8")

    return {
        "status": "prepared",
        "source_case_dir": str(source_case_dir),
        "output_case_dir": str(output_case_dir),
        "mesh_path": str(output_case_dir / "mesh.su2"),
        "runtime_cfg_path": str(output_case_dir / "su2_runtime.cfg"),
        "flow_discretization": diagnose_flow_discretization(cfg),
        "slope_limiter_flow": resolved_slope_limiter,
    }


def diagnose_flow_discretization(cfg_text: str) -> dict[str, Any]:
    """Classify whether the config is adequate for a numerical-scheme probe."""

    values = _cfg_assignments(cfg_text)
    method = (values.get("CONV_NUM_METHOD_FLOW") or "").strip().upper()
    muscl = (values.get("MUSCL_FLOW") or "").strip().upper()
    blockers: list[str] = []
    warnings: list[str] = []

    if method == "FDS" and muscl != "YES":
        blockers.append("fds_without_muscl_second_order_reconstruction")
    if method in {"", "JST", "LAX-FRIEDRICH"}:
        warnings.append("not_an_upwind_fds_second_order_pressure_probe")
    if len(_cfg_key_occurrences(cfg_text, "MUSCL_FLOW")) > 1:
        blockers.append("duplicate_muscl_flow_assignments")

    return {
        "status": "second_order_probe_ready"
        if method == "FDS" and muscl == "YES" and not blockers
        else "first_order_or_low_order_diagnostic_only",
        "conv_num_method_flow": method or None,
        "muscl_flow": muscl or None,
        "blockers": blockers,
        "warnings": warnings,
        "manual_basis": {
            "su2_convective_schemes": "https://su2code.github.io/docs_v7/Convective-Schemes/",
            "read": (
                "SU2's incompressible FDS is the low-speed-preconditioned upwind "
                "scheme; second-order space reconstruction needs MUSCL enabled."
            ),
        },
    }


def run_solver(
    *,
    case_dir: Path,
    solver_command: str,
    threads: int = 4,
    timeout_seconds: float = 1800.0,
) -> dict[str, Any]:
    case_dir = Path(case_dir)
    solver_log = case_dir / "solver.log"
    history_path = case_dir / "history.csv"
    command = [str(solver_command), "-t", str(max(1, int(threads))), "su2_runtime.cfg"]
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(max(1, int(threads)))
    start = time.monotonic()
    try:
        with solver_log.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(
                command,
                cwd=case_dir,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                env=env,
                timeout=timeout_seconds,
            )
        elapsed = time.monotonic() - start
        run_status = (
            "completed" if completed.returncode == 0 and history_path.exists() else "failed"
        )
        failure_code = None if run_status == "completed" else "solver_failed_or_history_missing"
        return {
            "run_status": run_status,
            "failure_code": failure_code,
            "returncode": completed.returncode,
            "elapsed_seconds": elapsed,
            "solver_command": command,
            "solver_log_path": str(solver_log),
            "history_path": str(history_path) if history_path.exists() else None,
        }
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        return {
            "run_status": "timeout",
            "failure_code": "solver_timeout",
            "returncode": None,
            "elapsed_seconds": elapsed,
            "solver_command": command,
            "solver_log_path": str(solver_log),
            "history_path": str(history_path) if history_path.exists() else None,
        }


def summarize_history(path: Path | str, *, window: int = 100) -> dict[str, Any]:
    path = Path(path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"SU2 history has no rows: {path}")
    final = {_normalize_key(key): value for key, value in rows[-1].items()}
    cd_values = [
        _lookup_float({_normalize_key(k): v for k, v in row.items()}, "CD", "DRAG") for row in rows
    ]
    cl_values = [
        _lookup_float({_normalize_key(k): v for k, v in row.items()}, "CL", "LIFT") for row in rows
    ]
    cmy_values = [
        _lookup_float({_normalize_key(k): v for k, v in row.items()}, "CMY", "CM") for row in rows
    ]
    final_cd = _lookup_float(final, "CD", "DRAG")
    final_cl = _lookup_float(final, "CL", "LIFT")
    final_cmy = _lookup_float(final, "CMY", "CM")
    summary = HistorySummary(
        row_count=len(rows),
        final_iteration=_lookup_int(final, "INNER_ITER", "OUTER_ITER", "ITER"),
        final_coefficients={"cl": final_cl, "cd": final_cd, "cmy": final_cmy},
        last_window={
            "window": min(window, len(rows)),
            "cd_span_pct": _relative_span_pct(cd_values[-window:]),
            "cl_span_pct": _relative_span_pct(cl_values[-window:]),
            "cmy_abs_span": _absolute_span(cmy_values[-window:]),
            "cd_endpoint_delta_pct": _endpoint_delta_pct(cd_values[-window:]),
        },
    )
    return {
        "row_count": summary.row_count,
        "final_iteration": summary.final_iteration,
        "final_coefficients": summary.final_coefficients,
        "last_window": summary.last_window,
        "cd_plausibility_gate": {
            "status": "pass"
            if final_cd is not None
            and math.isfinite(final_cd)
            and final_cd <= HPA_MAIN_WING_CD_PLAUSIBILITY_MAX
            else "fail",
            "limit": HPA_MAIN_WING_CD_PLAUSIBILITY_MAX,
        },
    }


def build_report(
    *,
    source_case_dir: Path,
    output_case_dir: Path,
    run_payload: Mapping[str, Any] | None,
    output_dir: Path,
) -> dict[str, Any]:
    source_case_dir = Path(source_case_dir)
    output_case_dir = Path(output_case_dir)
    output_dir = Path(output_dir)
    source_cfg = (source_case_dir / "su2_runtime.cfg").read_text(encoding="utf-8", errors="replace")
    probe_cfg = (output_case_dir / "su2_runtime.cfg").read_text(encoding="utf-8", errors="replace")
    source_history = (
        summarize_history(source_case_dir / "history.csv")
        if (source_case_dir / "history.csv").is_file()
        else None
    )
    probe_history = (
        summarize_history(output_case_dir / "history.csv")
        if (output_case_dir / "history.csv").is_file()
        else None
    )
    report = {
        "schema_version": "wo006j_numerics_sensitivity_probe.v1",
        "diagnostic_only": True,
        "source_case_dir": str(source_case_dir),
        "probe_case_dir": str(output_case_dir),
        "source_flow_discretization": diagnose_flow_discretization(source_cfg),
        "probe_flow_discretization": diagnose_flow_discretization(probe_cfg),
        "source_history": source_history,
        "probe_history": probe_history,
        "solver_run": dict(run_payload or {"run_status": "not_run"}),
        "engineering_read": _engineering_read(source_history, probe_history),
        "manual_sources": {
            "su2_convective_schemes": "https://su2code.github.io/docs_v7/Convective-Schemes/",
            "su2_physical_definition": "https://su2code.github.io/docs_v7/Physical-Definition/",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "numerics_sensitivity_report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "numerics_sensitivity_report.md").write_text(
        _markdown_report(report),
        encoding="utf-8",
    )
    return report


def _engineering_read(
    source_history: Mapping[str, Any] | None,
    probe_history: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if probe_history is None:
        return {
            "verdict": "second_order_probe_not_run_or_no_history",
            "cfd_use": "diagnostic_only",
            "next_action": "run the prepared FDS+MUSCL probe before changing BL settings",
        }
    probe_cd = _optional_float((probe_history.get("final_coefficients") or {}).get("cd"))
    source_cd = (
        None
        if source_history is None
        else _optional_float((source_history.get("final_coefficients") or {}).get("cd"))
    )
    delta_pct = None
    if source_cd is not None and probe_cd is not None and abs(source_cd) > 1.0e-12:
        delta_pct = 100.0 * (probe_cd - source_cd) / abs(source_cd)
    if (
        probe_cd is not None
        and math.isfinite(probe_cd)
        and probe_cd <= HPA_MAIN_WING_CD_PLAUSIBILITY_MAX
    ):
        verdict = "pressure_drag_order_improved_but_still_requires_bl_ladder"
        next_action = "repeat force-breakdown and then rebuild BL ladder with this numerical setup"
    else:
        verdict = "second_order_numerics_did_not_restore_drag_order"
        next_action = "continue geometry/pressure-field/BL-friction root-cause work before any larger mesh ladder"
    return {
        "verdict": verdict,
        "cfd_use": "diagnostic_only_not_grid_convergence",
        "source_cd": source_cd,
        "probe_cd": probe_cd,
        "probe_minus_source_cd_pct": delta_pct,
        "cd_plausibility_limit": HPA_MAIN_WING_CD_PLAUSIBILITY_MAX,
        "next_action": next_action,
    }


def _markdown_report(report: Mapping[str, Any]) -> str:
    source_hist = report.get("source_history") or {}
    probe_hist = report.get("probe_history") or {}
    source_coeffs = source_hist.get("final_coefficients") or {}
    probe_coeffs = probe_hist.get("final_coefficients") or {}
    engineering = report["engineering_read"]
    lines = [
        "# WO-006J Numerics Sensitivity Probe",
        "",
        "Diagnostic only: same existing large-domain Euler mesh; no geometry or Baseline A authority change.",
        "",
        f"Verdict: `{engineering['verdict']}`",
        "",
        "| case | flow setup | iter | CL | CD | CMy | CD gate |",
        "|---|---|---:|---:|---:|---:|---|",
        _history_row(
            "source_euler_probe",
            report.get("source_flow_discretization") or {},
            source_hist,
            source_coeffs,
        ),
        _history_row(
            "fds_muscl_probe",
            report.get("probe_flow_discretization") or {},
            probe_hist,
            probe_coeffs,
        ),
        "",
        "Engineering read:",
        "",
        f"- CFD use: `{engineering['cfd_use']}`.",
        f"- Next action: {engineering['next_action']}.",
        "- Manual basis: SU2 convective-scheme docs identify incompressible `FDS` as the low-speed-preconditioned upwind scheme; second-order reconstruction needs `MUSCL_FLOW= YES`.",
        "",
    ]
    return "\n".join(lines)


def _history_row(
    label: str,
    diagnostic: Mapping[str, Any],
    history: Mapping[str, Any],
    coeffs: Mapping[str, Any],
) -> str:
    if not history:
        return f"| `{label}` | `{diagnostic.get('status')}` | n/a | n/a | n/a | n/a | n/a |"
    gate = history.get("cd_plausibility_gate") or {}
    return (
        f"| `{label}` | `{diagnostic.get('status')}` | "
        f"{_fmt(history.get('final_iteration'))} | "
        f"{_fmt(coeffs.get('cl'))} | {_fmt(coeffs.get('cd'))} | "
        f"{_fmt(coeffs.get('cmy'))} | `{gate.get('status')}` |"
    )


def _cfg_assignments(cfg_text: str) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for line in cfg_text.splitlines():
        match = re.match(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*(?:%.*)?$", line)
        if match is None:
            continue
        assignments[match.group(1).strip().upper()] = match.group(2).strip()
    return assignments


def _cfg_key_occurrences(cfg_text: str, key: str) -> list[str]:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=", flags=re.IGNORECASE)
    return [line for line in cfg_text.splitlines() if pattern.match(line)]


def _normalize_key(value: str) -> str:
    return value.strip().strip('"').upper().replace(" ", "")


def _lookup_float(row: Mapping[str, str], *names: str) -> float | None:
    for name in names:
        value = row.get(_normalize_key(name))
        if value in {None, ""}:
            continue
        return _optional_float(value)
    return None


def _lookup_int(row: Mapping[str, str], *names: str) -> int | None:
    value = _lookup_float(row, *names)
    if value is None:
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _relative_span_pct(values: Sequence[float | None]) -> float | None:
    finite = [float(value) for value in values if value is not None and math.isfinite(value)]
    if len(finite) < 2:
        return None
    mean_abs = sum(abs(value) for value in finite) / len(finite)
    if mean_abs <= 1.0e-12:
        return None
    return 100.0 * (max(finite) - min(finite)) / mean_abs


def _endpoint_delta_pct(values: Sequence[float | None]) -> float | None:
    finite = [float(value) for value in values if value is not None and math.isfinite(value)]
    if len(finite) < 2 or abs(finite[0]) <= 1.0e-12:
        return None
    return 100.0 * (finite[-1] - finite[0]) / abs(finite[0])


def _absolute_span(values: Sequence[float | None]) -> float | None:
    finite = [float(value) for value in values if value is not None and math.isfinite(value)]
    if len(finite) < 2:
        return None
    return max(finite) - min(finite)


def _format_su2_value(value: float | str) -> str:
    if isinstance(value, str):
        return value
    return f"{float(value):.12g}"


def _fmt(value: Any) -> str:
    number = _optional_float(value)
    if number is None or not math.isfinite(number):
        return "n/a"
    if abs(number) >= 100:
        return f"{number:.0f}"
    return f"{number:.6g}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-case-dir", type=Path, default=DEFAULT_SOURCE_CASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--iterations", type=int, default=750)
    parser.add_argument("--cfl-number", type=float, default=0.5)
    parser.add_argument("--slope-limiter-flow", default="NONE")
    parser.add_argument("--solver-command", default=DEFAULT_SOLVER_COMMAND)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--skip-run", action="store_true")
    parser.add_argument("--no-clean", action="store_true")
    args = parser.parse_args(argv)

    probe_case_dir = args.output_dir / "fds_muscl_euler_probe"
    if args.output_dir.exists() and not args.no_clean:
        shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prepared = prepare_probe_case(
        source_case_dir=args.source_case_dir,
        output_case_dir=probe_case_dir,
        iteration_count=args.iterations,
        cfl_number=args.cfl_number,
        slope_limiter_flow=args.slope_limiter_flow,
    )
    run_payload = (
        {"run_status": "skipped_by_cli"}
        if args.skip_run
        else run_solver(
            case_dir=probe_case_dir,
            solver_command=args.solver_command,
            threads=args.threads,
            timeout_seconds=args.timeout_seconds,
        )
    )
    report = build_report(
        source_case_dir=args.source_case_dir,
        output_case_dir=probe_case_dir,
        run_payload=run_payload,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "prepared": prepared["status"],
                "run_status": run_payload.get("run_status"),
                "report": str(args.output_dir / "numerics_sensitivity_report.md"),
                "verdict": report["engineering_read"]["verdict"],
                "probe_cd": report["engineering_read"].get("probe_cd"),
            },
            indent=2,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
