from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .adapters.su2_backend import run_baseline_case
from .schema import SU2RuntimeConfig


DEFAULT_SURFACE_TRIANGLE_RELATIVE_DRIFT_LIMIT = 0.05
DEFAULT_VOLUME_ELEMENT_RELATIVE_DRIFT_LIMIT = 0.05


def _resolve_path(path_value: str | Path, source_root: Path | None) -> Path:
    path = Path(path_value)
    if path.is_absolute() or source_root is None:
        return path
    return (source_root / path).resolve()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _status_for_checks(*statuses: str) -> str:
    if any(status == "fail" for status in statuses):
        return "fail"
    if any(status == "warn" for status in statuses):
        return "warn"
    return "pass"


def _check(status: str, *, observed: dict[str, Any] | None = None, expected: dict[str, Any] | None = None, notes: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "observed": observed or {},
        "expected": expected or {},
        "notes": notes or [],
    }


def _artifact_path(
    manifest: dict[str, Any],
    manifest_path: Path,
    artifact_key: str,
    fallback_relative_path: str,
) -> Path:
    artifacts = manifest.get("artifacts", {})
    artifact_value = artifacts.get(artifact_key) if isinstance(artifacts, dict) else None
    if isinstance(artifact_value, str) and artifact_value:
        return _resolve_path(artifact_value, manifest_path.parent)
    return manifest_path.parent / fallback_relative_path


def _relative_drift(expected: int | float, observed: int | float) -> float:
    if float(expected) == 0.0:
        return 0.0 if float(observed) == 0.0 else 1.0
    return abs(float(observed) - float(expected)) / abs(float(expected))


def evaluate_shell_v3_baseline_regression(
    manifest_path: str | Path,
    *,
    mesh_handoff_path: str | Path | None = None,
    source_root: Path | None = None,
    surface_triangle_relative_drift_limit: float = DEFAULT_SURFACE_TRIANGLE_RELATIVE_DRIFT_LIMIT,
    volume_element_relative_drift_limit: float = DEFAULT_VOLUME_ELEMENT_RELATIVE_DRIFT_LIMIT,
) -> dict[str, Any]:
    manifest_path = _resolve_path(manifest_path, source_root)
    manifest = _load_json(manifest_path)
    current_run = manifest.get("current_run", {})
    if not isinstance(current_run, dict):
        raise ValueError(f"baseline manifest missing current_run object: {manifest_path}")

    summary_path = manifest_path.with_name("shell_v3_quality_clean_baseline_summary.md")
    resolved_mesh_handoff_path = (
        _resolve_path(mesh_handoff_path, source_root)
        if mesh_handoff_path is not None
        else _artifact_path(
            manifest,
            manifest_path,
            "mesh_metadata_json",
            "artifacts/mesh/mesh_metadata.json",
        )
    )
    gmsh_log_path = _artifact_path(
        manifest,
        manifest_path,
        "gmsh_log_txt",
        "artifacts/mesh/gmsh_log.txt",
    )
    topology_report_path = _artifact_path(
        manifest,
        manifest_path,
        "topology_suppression_report_json",
        "artifacts/providers/esp_rebuilt/esp_runtime/topology_suppression_report.json",
    )

    mesh_handoff = _load_json(resolved_mesh_handoff_path)
    mesh_stats = mesh_handoff.get("mesh_stats", {})
    quality_metrics = mesh_handoff.get("quality_metrics", {})

    gmsh_log_text = gmsh_log_path.read_text(encoding="utf-8", errors="replace")
    topology_report = _load_json(topology_report_path)
    summary_exists = summary_path.exists()

    expected_surface_triangles = int(current_run.get("surface_triangle_count", 0) or 0)
    observed_surface_triangles = int(mesh_stats.get("surface_element_count", 0) or 0)
    expected_volume_elements = int(current_run.get("volume_element_count", 0) or 0)
    observed_volume_elements = int(mesh_stats.get("volume_element_count", 0) or 0)
    observed_ill_shaped = int(quality_metrics.get("ill_shaped_tet_count", 0) or 0)

    surface_triangle_drift = _relative_drift(expected_surface_triangles, observed_surface_triangles)
    volume_element_drift = _relative_drift(expected_volume_elements, observed_volume_elements)

    checks = {
        "manifest_readable": _check(
            "pass",
            observed={"path": str(manifest_path), "baseline_name": manifest.get("baseline_name")},
            expected={"baseline_name": "shell_v3_quality_clean_baseline"},
        ),
        "baseline_summary_readable": _check(
            "pass" if summary_exists else "fail",
            observed={"path": str(summary_path), "exists": summary_exists},
            expected={"exists": True},
        ),
        "mesh_handoff_readable": _check(
            "pass",
            observed={"path": str(resolved_mesh_handoff_path), "contract": mesh_handoff.get("contract")},
            expected={"contract": "mesh_handoff.v1"},
        ),
        "ill_shaped_tet_count": _check(
            "pass" if observed_ill_shaped == 0 else "fail",
            observed={
                "manifest_ill_shaped_tet_count": int(current_run.get("ill_shaped_tet_count", 0) or 0),
                "mesh_handoff_ill_shaped_tet_count": observed_ill_shaped,
            },
            expected={"ill_shaped_tet_count": 0},
        ),
        "surface_triangle_count": _check(
            "pass" if surface_triangle_drift <= surface_triangle_relative_drift_limit else "fail",
            observed={
                "manifest": expected_surface_triangles,
                "mesh_handoff": observed_surface_triangles,
                "relative_drift": surface_triangle_drift,
            },
            expected={"relative_drift_lte": surface_triangle_relative_drift_limit},
        ),
        "volume_element_count": _check(
            "pass" if volume_element_drift <= volume_element_relative_drift_limit else "fail",
            observed={
                "manifest": expected_volume_elements,
                "mesh_handoff": observed_volume_elements,
                "relative_drift": volume_element_drift,
            },
            expected={"relative_drift_lte": volume_element_relative_drift_limit},
        ),
        "gmsh_log": _check(
            "pass" if "No ill-shaped tets in the mesh" in gmsh_log_text else "fail",
            observed={"path": str(gmsh_log_path)},
            expected={"contains": "No ill-shaped tets in the mesh"},
        ),
        "topology_suppression_origin": _check(
            "pass" if topology_report.get("applied") is False else "fail",
            observed={
                "path": str(topology_report_path),
                "applied": topology_report.get("applied"),
                "suppressed_source_section_count": topology_report.get("suppressed_source_section_count"),
            },
            expected={"applied": False},
        ),
    }
    status = _status_for_checks(*(check["status"] for check in checks.values()))
    return {
        "contract": "shell_v3_baseline_regression.v1",
        "baseline_name": manifest.get("baseline_name", "shell_v3_quality_clean_baseline"),
        "status": status,
        "checks": checks,
        "artifacts": {
            "baseline_manifest": str(manifest_path),
            "baseline_summary": str(summary_path),
            "mesh_handoff": str(resolved_mesh_handoff_path),
            "gmsh_log": str(gmsh_log_path),
            "topology_suppression_report": str(topology_report_path),
        },
        "notes": [
            "Regression gate freezes the promoted shell_v3 baseline and checks only baseline-side artifacts.",
            "This gate does not rerun geometry or meshing.",
        ],
    }


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _default_runtime() -> SU2RuntimeConfig:
    return SU2RuntimeConfig(
        enabled=True,
        case_name="shell_v3_alpha0_coarse_baseline",
        max_iterations=80,
        alpha_deg=0.0,
        wall_boundary_condition="adiabatic_no_slip",
    )


def _likely_root_cause(failure_code: str | None) -> str:
    if failure_code in {"materialization_failed"}:
        return "export"
    if failure_code in {"solver_execution_failed", "solver_not_found", "history_missing", "history_parse_failed"}:
        return "config"
    return "unknown"


def _no_go_summary(
    *,
    baseline_regression: dict[str, Any],
    run_result: dict[str, Any] | None,
    failure_stage: str,
    out_dir: Path,
) -> dict[str, Any]:
    failure_code = None if run_result is None else run_result.get("failure_code")
    summary = {
        "contract": "solver_smoke_no_go_summary.v1",
        "status": "failed",
        "failure_stage": failure_stage,
        "raw_evidence": {} if run_result is None else run_result,
        "issue_assessment": {
            "likely_root_cause": _likely_root_cause(failure_code),
            "geometry_baseline_related": False,
        },
        "baseline_regression_status": baseline_regression.get("status"),
        "next_minimal_patch_point": {
            "baseline_regression": "repair frozen baseline artifact contract before touching geometry",
            "solver_smoke": "fix solver boundary/config glue on the frozen mesh before touching geometry",
        }[failure_stage],
    }
    _write_json(out_dir / "solver_smoke_no_go_summary.json", summary)
    summary["artifacts"] = {
        "baseline_regression": str(out_dir / "baseline_regression.json"),
        "solver_smoke_no_go_summary": str(out_dir / "solver_smoke_no_go_summary.json"),
    }
    return summary


def _coarse_cfd_sanity(
    run_result: dict[str, Any],
    runtime: SU2RuntimeConfig,
) -> tuple[str, dict[str, Any], dict[str, str], dict[str, str]]:
    coefficients = run_result.get("final_coefficients", {})
    convergence = run_result.get("convergence_gate", {}) or {}
    iterative_gate = convergence.get("iterative_gate", {}) or {}
    residual_trend = (iterative_gate.get("checks", {}) or {}).get("residual_trend", {}) or {}

    finite_coefficients = all(_is_finite_number(coefficients.get(name)) for name in ("cl", "cd", "cm"))
    positive_drag = _is_finite_number(coefficients.get("cd")) and float(coefficients["cd"]) > 0.0
    residual_not_failed = residual_trend.get("status", iterative_gate.get("status")) != "fail"
    wall_contract_ok = runtime.wall_boundary_condition == "adiabatic_no_slip"

    checks = {
        "finite_coefficients": _check(
            "pass" if finite_coefficients else "fail",
            observed={name: coefficients.get(name) for name in ("cl", "cd", "cm")},
            expected={"all_finite": True},
        ),
        "residual_basic_drop": _check(
            "pass" if residual_not_failed else "fail",
            observed={"residual_trend_status": residual_trend.get("status", iterative_gate.get("status"))},
            expected={"status_not": "fail"},
        ),
        "drag_sign": _check(
            "pass" if positive_drag else "fail",
            observed={"cd": coefficients.get("cd"), "alpha_deg": runtime.alpha_deg},
            expected={"cd_positive": True},
            notes=["External-flow coarse sanity expects positive drag at this stage."],
        ),
        "wall_boundary_contract": _check(
            "pass" if wall_contract_ok else "fail",
            observed={"wall_boundary_condition": runtime.wall_boundary_condition},
            expected={"wall_boundary_condition": "adiabatic_no_slip"},
        ),
    }
    status = _status_for_checks(*(check["status"] for check in checks.values()))
    primary_limitation = (
        {
            "category": "boundary_condition_contract",
            "reason": "Current solver wall BC is still slip-wall oriented, so force signs are not trustworthy for coarse CFD.",
        }
        if not wall_contract_ok or not positive_drag
        else {
            "category": "boundary_layer_treatment",
            "reason": "The case now runs with a physically readable wall contract, but the coarse tetra baseline still lacks boundary-layer treatment for trustworthy drag magnitude.",
        }
    )
    next_mainline = (
        {
            "category": "boundary_condition_contract",
            "action": "Keep the frozen shell_v3 mesh and switch the aircraft marker to adiabatic no-slip before touching mesh or geometry.",
        }
        if primary_limitation["category"] == "boundary_condition_contract"
        else {
            "category": "boundary_layer_treatment",
            "action": "Keep the frozen shell_v3 geometry and add the first boundary-layer-capable near-wall meshing pass on this same SU2 route.",
        }
    )
    return status, checks, primary_limitation, next_mainline


def run_shell_v3_baseline_cfd(
    manifest_path: str | Path,
    *,
    out_dir: str | Path,
    mesh_handoff_path: str | Path | None = None,
    runtime: SU2RuntimeConfig | None = None,
    source_root: Path | None = None,
) -> dict[str, Any]:
    out_dir = _resolve_path(out_dir, source_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline_regression = evaluate_shell_v3_baseline_regression(
        manifest_path,
        mesh_handoff_path=mesh_handoff_path,
        source_root=source_root,
    )
    _write_json(out_dir / "baseline_regression.json", baseline_regression)
    if baseline_regression["status"] != "pass":
        return _no_go_summary(
            baseline_regression=baseline_regression,
            run_result=None,
            failure_stage="baseline_regression",
            out_dir=out_dir,
        )

    runtime = runtime or _default_runtime()
    runtime_payload = {
        "baseline_manifest": str(_resolve_path(manifest_path, source_root)),
        "mesh_handoff": baseline_regression["artifacts"]["mesh_handoff"],
        "runtime": runtime.model_dump(mode="json"),
    }
    _write_json(out_dir / "solver_smoke_config.json", runtime_payload)

    mesh_handoff = _load_json(Path(baseline_regression["artifacts"]["mesh_handoff"]))
    run_result = run_baseline_case(
        mesh_handoff,
        runtime,
        out_dir / "artifacts" / "su2",
        source_root=source_root,
    )
    if run_result.get("run_status") != "completed":
        return _no_go_summary(
            baseline_regression=baseline_regression,
            run_result=run_result,
            failure_stage="solver_smoke",
            out_dir=out_dir,
        )

    coarse_status, coarse_checks, primary_limitation, next_mainline = _coarse_cfd_sanity(run_result, runtime)
    classification = "coarse_cfd_baseline" if coarse_status == "pass" else "solver_smoke_only"
    summary = {
        "contract": "shell_v3_solver_smoke_summary.v1",
        "status": "success",
        "baseline_name": baseline_regression.get("baseline_name"),
        "classification": classification,
        "solver_smoke": {
            "status": "pass",
            "run_status": run_result.get("run_status"),
            "final_iteration": run_result.get("final_iteration"),
            "final_coefficients": run_result.get("final_coefficients"),
        },
        "coarse_cfd_sanity": {
            "status": coarse_status,
            "checks": coarse_checks,
        },
        "primary_limitation": primary_limitation,
        "next_mainline": next_mainline,
        "artifacts": {
            "baseline_regression": str(out_dir / "baseline_regression.json"),
            "solver_smoke_config": str(out_dir / "solver_smoke_config.json"),
            "solver_smoke_summary": str(out_dir / "solver_smoke_summary.json"),
            "su2_case_contract": (
                None
                if run_result.get("case_output_paths") is None
                else run_result["case_output_paths"].get("contract_path")
            ),
            "history_path": run_result.get("history_path"),
        },
        "run_result": run_result,
    }
    _write_json(out_dir / "solver_smoke_summary.json", summary)
    return summary
