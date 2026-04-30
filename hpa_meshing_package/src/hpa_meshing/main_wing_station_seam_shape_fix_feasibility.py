from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


ShapeFixFeasibilityStatusType = Literal[
    "shape_fix_repair_recovered",
    "shape_fix_repair_not_recovered",
    "unavailable",
    "blocked",
]

ShapeFixRunner = Callable[..., Dict[str, Any]]

DEFAULT_SHAPE_FIX_TOLERANCES = [1e-7, 1e-6, 1e-5, 1e-4, 1e-3]
DEFAULT_SHAPE_FIX_OPERATIONS = [
    "fix_same_parameter_edge",
    "fix_same_parameter_edge_face",
    "fix_reversed_2d_then_same_parameter",
    "fix_vertex_tolerance_then_same_parameter",
    "remove_add_pcurve_then_same_parameter",
]


class MainWingStationSeamShapeFixFeasibilityReport(BaseModel):
    schema_version: Literal[
        "main_wing_station_seam_shape_fix_feasibility.v1"
    ] = "main_wing_station_seam_shape_fix_feasibility.v1"
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_in_memory_shape_fix_feasibility"] = (
        "report_only_in_memory_shape_fix_feasibility"
    )
    production_default_changed: bool = False
    feasibility_status: ShapeFixFeasibilityStatusType
    same_parameter_feasibility_path: str
    normalized_step_path: str | None = None
    requested_curve_tags: List[int] = Field(default_factory=list)
    requested_surface_tags: List[int] = Field(default_factory=list)
    target_edges: List[Dict[str, Any]] = Field(default_factory=list)
    api_semantics: Dict[str, Any] = Field(default_factory=dict)
    baseline_checks: List[Dict[str, Any]] = Field(default_factory=list)
    repair_attempts: List[Dict[str, Any]] = Field(default_factory=list)
    baseline_summary: Dict[str, Any] = Field(default_factory=dict)
    attempt_summary: Dict[str, Any] = Field(default_factory=dict)
    engineering_findings: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_same_parameter_feasibility_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_same_parameter_feasibility"
        / "main_wing_station_seam_same_parameter_feasibility.v1.json"
    )


def _load_json(path: Path, blockers: list[str], label: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        blockers.append(f"{label}_missing")
        return None
    except json.JSONDecodeError as exc:
        blockers.append(f"{label}_invalid_json:{exc}")
        return None
    return payload if isinstance(payload, dict) else {}


def _resolve_path(value: Any) -> Path | None:
    if value is None or value == "":
        return None
    path = Path(str(value))
    return path if path.is_absolute() else _repo_root() / path


def _as_int_list(values: Any) -> list[int]:
    if not isinstance(values, list):
        return []
    result: set[int] = set()
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            result.add(int(value))
    return sorted(result)


def _target_edges(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    targets: list[dict[str, Any]] = []
    for target in payload.get("target_edges", []):
        if not isinstance(target, dict):
            continue
        curve_id = target.get("curve_id")
        edge_index = target.get("edge_index")
        if not isinstance(curve_id, int) or not isinstance(edge_index, int):
            continue
        targets.append(
            {
                "curve_id": int(curve_id),
                "edge_index": int(edge_index),
                "face_ids": _as_int_list(target.get("face_ids")),
            }
        )
    return targets


def _all_face_checks(checks: list[dict[str, Any]], key: str) -> bool:
    values: list[bool] = []
    for check in checks:
        for face_check in check.get("face_checks", []):
            if isinstance(face_check, dict) and isinstance(face_check.get(key), bool):
                values.append(bool(face_check[key]))
    return bool(values) and all(values)


def _summary(checks: list[dict[str, Any]]) -> dict[str, Any]:
    all_target_pcurves_present = _all_face_checks(checks, "has_pcurve")
    all_same_parameter_checks_pass = _all_face_checks(
        checks,
        "check_same_parameter",
    )
    all_curve3d_with_pcurve_checks_pass = _all_face_checks(
        checks,
        "check_curve3d_with_pcurve",
    )
    all_vertex_tolerance_checks_pass = _all_face_checks(
        checks,
        "check_vertex_tolerance",
    )
    return {
        "target_edge_count": len(checks),
        "all_target_pcurves_present": all_target_pcurves_present,
        "all_same_parameter_checks_pass": all_same_parameter_checks_pass,
        "all_curve3d_with_pcurve_checks_pass": all_curve3d_with_pcurve_checks_pass,
        "all_vertex_tolerance_checks_pass": all_vertex_tolerance_checks_pass,
        "all_station_checks_pass": (
            all_target_pcurves_present
            and all_same_parameter_checks_pass
            and all_curve3d_with_pcurve_checks_pass
            and all_vertex_tolerance_checks_pass
        ),
    }


def _attempt_recovered(attempt: dict[str, Any]) -> bool:
    if attempt.get("recovered") is True:
        return True
    checks = attempt.get("checks", [])
    return isinstance(checks, list) and _summary(checks).get(
        "all_station_checks_pass"
    ) is True


def _attempt_summary(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    recovered = [attempt for attempt in attempts if _attempt_recovered(attempt)]
    return {
        "attempt_count": len(attempts),
        "operations_evaluated": sorted(
            {
                str(attempt.get("operation"))
                for attempt in attempts
                if attempt.get("operation") is not None
            }
        ),
        "tolerances_evaluated": sorted(
            {
                float(attempt.get("tolerance"))
                for attempt in attempts
                if isinstance(attempt.get("tolerance"), (int, float))
                and not isinstance(attempt.get("tolerance"), bool)
            }
        ),
        "recovered_attempt_count": len(recovered),
        "first_recovered_operation": (
            recovered[0].get("operation") if recovered else None
        ),
        "first_recovered_tolerance": (
            recovered[0].get("tolerance") if recovered else None
        ),
    }


def _status(
    *,
    blockers: list[str],
    runner_payload: dict[str, Any],
    attempts: list[dict[str, Any]],
) -> ShapeFixFeasibilityStatusType:
    if blockers:
        return "blocked"
    if runner_payload.get("runtime_status") == "unavailable":
        return "unavailable"
    if any(_attempt_recovered(attempt) for attempt in attempts):
        return "shape_fix_repair_recovered"
    return "shape_fix_repair_not_recovered"


def _engineering_findings(
    status: ShapeFixFeasibilityStatusType,
    baseline: dict[str, Any],
    attempts: dict[str, Any],
) -> list[str]:
    if status == "blocked":
        return ["station_shape_fix_feasibility_blocked"]
    if status == "unavailable":
        return ["station_shape_fix_feasibility_runtime_unavailable"]
    findings = ["station_shape_fix_feasibility_evaluated"]
    if baseline.get("all_target_pcurves_present") is True:
        findings.append("station_target_pcurves_present_before_shape_fix")
    if baseline.get("all_station_checks_pass") is False:
        findings.append("station_shape_fix_baseline_checks_fail")
    if status == "shape_fix_repair_recovered":
        findings.append("shape_fix_edge_recovered_station_curve_checks")
    if status == "shape_fix_repair_not_recovered":
        findings.append("shape_fix_edge_did_not_recover_station_curve_checks")
    if attempts.get("recovered_attempt_count") == 0:
        findings.append("shape_fix_operation_sweep_no_recovery")
    return findings


def _blocking_reasons(
    status: ShapeFixFeasibilityStatusType,
    blockers: list[str],
) -> list[str]:
    reasons = list(blockers)
    if status == "unavailable":
        reasons.append("station_shape_fix_feasibility_runtime_unavailable")
    if status == "shape_fix_repair_not_recovered":
        reasons.append("station_shape_fix_repair_not_recovered")
    return reasons


def _next_actions(status: ShapeFixFeasibilityStatusType) -> list[str]:
    if status == "shape_fix_repair_recovered":
        return [
            "materialize_candidate_step_shape_fix_for_station_fixture",
            "rerun_station_fixture_brep_hotspot_and_gmsh_trace_on_shape_fix_candidate",
        ]
    if status == "shape_fix_repair_not_recovered":
        return [
            "rebuild_station_pcurves_or_export_station_seams_before_meshing_policy",
            "avoid_more_occt_edge_fix_sweeps_until_pcurve_generation_strategy_changes",
        ]
    if status == "unavailable":
        return ["restore_ocp_runtime_before_shape_fix_feasibility_claims"]
    return ["restore_shape_fix_feasibility_inputs"]


def _run_shape_fix_feasibility(
    *,
    step_path: Path,
    target_edges: list[dict[str, Any]],
    tolerances: list[float],
    operations: list[str],
) -> dict[str, Any]:
    try:
        from OCP.BRep import BRep_Tool
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.ShapeAnalysis import ShapeAnalysis_Edge
        from OCP.ShapeFix import ShapeFix_Edge
        from OCP.STEPControl import STEPControl_Reader
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
        from OCP.TopExp import TopExp
        from OCP.TopTools import TopTools_IndexedMapOfShape
        from OCP.TopoDS import TopoDS
    except Exception as exc:
        return {
            "runtime_status": "unavailable",
            "reason": "ocp_python_runtime_not_available",
            "error": str(exc),
            "baseline_checks": [],
            "repair_attempts": [],
        }

    def _load_shape():
        reader = STEPControl_Reader()
        status = reader.ReadFile(str(step_path))
        if status != IFSelect_RetDone:
            raise RuntimeError(f"STEP reader failed with status {int(status)}")
        reader.TransferRoots()
        return reader.OneShape()

    def _maps(shape):
        face_index_map = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, TopAbs_FACE, face_index_map)
        edge_index_map = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, TopAbs_EDGE, edge_index_map)
        return face_index_map, edge_index_map

    def _evaluate(shape) -> list[dict[str, Any]]:
        face_index_map, edge_index_map = _maps(shape)
        analyzer = ShapeAnalysis_Edge()
        checks: list[dict[str, Any]] = []
        for target in target_edges:
            edge_index = int(target["edge_index"])
            if edge_index < 1 or edge_index > edge_index_map.Size():
                checks.append({**target, "edge_found": False, "face_checks": []})
                continue
            edge = TopoDS.Edge_s(edge_index_map.FindKey(edge_index))
            face_checks: list[dict[str, Any]] = []
            for face_id in target.get("face_ids", []):
                face_index = int(face_id)
                if face_index < 1 or face_index > face_index_map.Size():
                    face_checks.append({"face_id": face_index, "face_found": False})
                    continue
                face = TopoDS.Face_s(face_index_map.FindKey(face_index))
                face_checks.append(
                    {
                        "face_id": face_index,
                        "face_found": True,
                        "has_pcurve": bool(analyzer.HasPCurve(edge, face)),
                        "check_same_parameter": bool(
                            analyzer.CheckSameParameter(edge, face, 0.0, 23)
                        ),
                        "check_curve3d_with_pcurve": bool(
                            analyzer.CheckCurve3dWithPCurve(edge, face)
                        ),
                        "check_vertex_tolerance": bool(
                            analyzer.CheckVertexTolerance(edge, face, 0.0, 0.0)
                        ),
                    }
                )
            checks.append(
                {
                    **target,
                    "edge_found": True,
                    "edge_tolerance": float(BRep_Tool.Tolerance_s(edge)),
                    "same_parameter_flag": bool(BRep_Tool.SameParameter_s(edge)),
                    "same_range_flag": bool(BRep_Tool.SameRange_s(edge)),
                    "face_checks": face_checks,
                }
            )
        return checks

    def _call(label: str, operation_call) -> dict[str, Any]:
        try:
            result = operation_call()
        except Exception as exc:
            return {
                "label": label,
                "called": False,
                "result": None,
                "error": str(exc),
            }
        return {
            "label": label,
            "called": True,
            "result": bool(result) if isinstance(result, bool) else result,
            "error": None,
        }

    def _apply_operation(shape, operation: str, tolerance: float) -> list[dict[str, Any]]:
        face_index_map, edge_index_map = _maps(shape)
        fixer = ShapeFix_Edge()
        operation_results: list[dict[str, Any]] = []
        for target in target_edges:
            edge_index = int(target["edge_index"])
            if edge_index < 1 or edge_index > edge_index_map.Size():
                operation_results.append(
                    {
                        **target,
                        "edge_found": False,
                        "face_operations": [],
                    }
                )
                continue
            edge = TopoDS.Edge_s(edge_index_map.FindKey(edge_index))
            face_operations: list[dict[str, Any]] = []
            if operation == "fix_same_parameter_edge":
                face_operations.append(
                    _call(
                        "FixSameParameter(edge, tolerance)",
                        lambda: fixer.FixSameParameter(edge, float(tolerance)),
                    )
                )
            for face_id in target.get("face_ids", []):
                face_index = int(face_id)
                if face_index < 1 or face_index > face_index_map.Size():
                    face_operations.append(
                        {
                            "label": f"face {face_index}",
                            "called": False,
                            "result": None,
                            "error": "face_not_found",
                        }
                    )
                    continue
                face = TopoDS.Face_s(face_index_map.FindKey(face_index))
                if operation == "fix_same_parameter_edge_face":
                    face_operations.append(
                        _call(
                            "FixSameParameter(edge, face, tolerance)",
                            lambda: fixer.FixSameParameter(
                                edge,
                                face,
                                float(tolerance),
                            ),
                        )
                    )
                elif operation == "fix_reversed_2d_then_same_parameter":
                    face_operations.append(
                        _call(
                            "FixReversed2d(edge, face)",
                            lambda: fixer.FixReversed2d(edge, face),
                        )
                    )
                    face_operations.append(
                        _call(
                            "FixSameParameter(edge, face, tolerance)",
                            lambda: fixer.FixSameParameter(
                                edge,
                                face,
                                float(tolerance),
                            ),
                        )
                    )
                elif operation == "fix_vertex_tolerance_then_same_parameter":
                    face_operations.append(
                        _call(
                            "FixVertexTolerance(edge, face)",
                            lambda: fixer.FixVertexTolerance(edge, face),
                        )
                    )
                    face_operations.append(
                        _call(
                            "FixSameParameter(edge, face, tolerance)",
                            lambda: fixer.FixSameParameter(
                                edge,
                                face,
                                float(tolerance),
                            ),
                        )
                    )
                elif operation == "remove_add_pcurve_then_same_parameter":
                    face_operations.append(
                        _call(
                            "FixRemovePCurve(edge, face)",
                            lambda: fixer.FixRemovePCurve(edge, face),
                        )
                    )
                    face_operations.append(
                        _call(
                            "FixAddPCurve(edge, face, is_seam, tolerance)",
                            lambda: fixer.FixAddPCurve(
                                edge,
                                face,
                                False,
                                float(tolerance),
                            ),
                        )
                    )
                    face_operations.append(
                        _call(
                            "FixSameParameter(edge, face, tolerance)",
                            lambda: fixer.FixSameParameter(
                                edge,
                                face,
                                float(tolerance),
                            ),
                        )
                    )
            operation_results.append(
                {
                    **target,
                    "edge_found": True,
                    "face_operations": face_operations,
                }
            )
        return operation_results

    try:
        baseline_shape = _load_shape()
        baseline_checks = _evaluate(baseline_shape)
        attempts: list[dict[str, Any]] = []
        for tolerance in tolerances:
            for operation in operations:
                shape = _load_shape()
                operation_results = _apply_operation(shape, operation, float(tolerance))
                checks = _evaluate(shape)
                attempts.append(
                    {
                        "operation": operation,
                        "tolerance": float(tolerance),
                        "recovered": _summary(checks).get("all_station_checks_pass")
                        is True,
                        "operation_results": operation_results,
                        "checks": checks,
                    }
                )
    except Exception as exc:
        return {
            "runtime_status": "unavailable",
            "reason": "shape_fix_feasibility_exception",
            "error": str(exc),
            "baseline_checks": [],
            "repair_attempts": [],
        }
    return {
        "runtime_status": "evaluated",
        "baseline_checks": baseline_checks,
        "repair_attempts": attempts,
    }


def build_main_wing_station_seam_shape_fix_feasibility_report(
    *,
    same_parameter_feasibility_path: Path | None = None,
    tolerances: list[float] | None = None,
    operations: list[str] | None = None,
    feasibility_runner: ShapeFixRunner | None = None,
) -> MainWingStationSeamShapeFixFeasibilityReport:
    source_path = (
        _default_same_parameter_feasibility_path()
        if same_parameter_feasibility_path is None
        else same_parameter_feasibility_path
    )
    blockers: list[str] = []
    source_payload = _load_json(source_path, blockers, "same_parameter_feasibility")
    target_edges = _target_edges(source_payload)
    if not target_edges:
        blockers.append("shape_fix_target_edges_missing")
    step_path = _resolve_path(
        source_payload.get("normalized_step_path")
        if isinstance(source_payload, dict)
        else None
    )
    if step_path is None:
        blockers.append("normalized_step_path_missing")
    elif not step_path.exists():
        blockers.append("normalized_step_missing")
    tolerance_values = (
        list(DEFAULT_SHAPE_FIX_TOLERANCES)
        if tolerances is None
        else [float(value) for value in tolerances]
    )
    operation_values = (
        list(DEFAULT_SHAPE_FIX_OPERATIONS)
        if operations is None
        else [str(value) for value in operations]
    )
    runner_payload: dict[str, Any] = {}
    if not blockers and step_path is not None:
        runner = feasibility_runner or _run_shape_fix_feasibility
        runner_payload = runner(
            step_path=step_path,
            target_edges=target_edges,
            tolerances=tolerance_values,
            operations=operation_values,
        )
    baseline_checks = [
        check
        for check in runner_payload.get("baseline_checks", [])
        if isinstance(check, dict)
    ]
    repair_attempts = [
        attempt
        for attempt in runner_payload.get("repair_attempts", [])
        if isinstance(attempt, dict)
    ]
    baseline_summary = _summary(baseline_checks)
    attempt_summary = _attempt_summary(repair_attempts)
    status = _status(
        blockers=blockers,
        runner_payload=runner_payload,
        attempts=repair_attempts,
    )
    requested_curves = (
        _as_int_list(source_payload.get("requested_curve_tags"))
        if isinstance(source_payload, dict)
        else []
    )
    requested_surfaces = (
        _as_int_list(source_payload.get("requested_surface_tags"))
        if isinstance(source_payload, dict)
        else []
    )
    return MainWingStationSeamShapeFixFeasibilityReport(
        feasibility_status=status,
        same_parameter_feasibility_path=str(source_path),
        normalized_step_path=str(step_path) if step_path is not None else None,
        requested_curve_tags=requested_curves,
        requested_surface_tags=requested_surfaces,
        target_edges=target_edges,
        api_semantics={
            "scope": (
                "ShapeFix_Edge operators are evaluated in memory only and never "
                "written back to production geometry by this report."
            ),
            "recovered_definition": (
                "An attempt is recovered only when PCurve presence, same-parameter, "
                "curve-3D-with-PCurve, and vertex-tolerance checks all pass."
            ),
            "operations": operation_values,
        },
        baseline_checks=baseline_checks,
        repair_attempts=repair_attempts,
        baseline_summary=baseline_summary,
        attempt_summary=attempt_summary,
        engineering_findings=_engineering_findings(
            status,
            baseline_summary,
            attempt_summary,
        ),
        blocking_reasons=_blocking_reasons(status, blockers),
        next_actions=_next_actions(status),
        limitations=[
            "This report does not write a repaired STEP file and does not change production defaults.",
            "It does not run Gmsh, SU2_CFD, or any CL/convergence acceptance gate.",
            "ShapeFix operation return values are diagnostic only; recovery is defined by the post-operation geometry checks.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_markdown(
    report: MainWingStationSeamShapeFixFeasibilityReport,
) -> str:
    lines = [
        "# Main Wing Station Seam ShapeFix Feasibility v1",
        "",
        "This report tests whether bounded in-memory OCCT ShapeFix_Edge operations can recover the station seam checks.",
        "",
        f"- feasibility_status: `{report.feasibility_status}`",
        f"- same_parameter_feasibility_path: `{report.same_parameter_feasibility_path}`",
        f"- normalized_step_path: `{report.normalized_step_path}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Baseline Summary",
        "",
    ]
    for key, value in report.baseline_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Attempt Summary", ""])
    for key, value in report.attempt_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Target Edges", ""])
    lines.extend(f"- `{_fmt(item)}`" for item in report.target_edges)
    lines.extend(["", "## API Semantics", ""])
    for key, value in report.api_semantics.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Baseline Checks", ""])
    if report.baseline_checks:
        lines.extend(f"- `{_fmt(item)}`" for item in report.baseline_checks)
    else:
        lines.append("- none")
    lines.extend(["", "## Repair Attempts", ""])
    if report.repair_attempts:
        lines.extend(f"- `{_fmt(item)}`" for item in report.repair_attempts)
    else:
        lines.append("- none")
    lines.extend(["", "## Engineering Findings", ""])
    lines.extend(f"- `{finding}`" for finding in report.engineering_findings)
    lines.extend(["", "## Blocking Reasons", ""])
    if report.blocking_reasons:
        lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    else:
        lines.append("- none")
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- `{action}`" for action in report.next_actions)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_main_wing_station_seam_shape_fix_feasibility_report(
    out_dir: Path,
    *,
    report: MainWingStationSeamShapeFixFeasibilityReport | None = None,
    same_parameter_feasibility_path: Path | None = None,
    tolerances: list[float] | None = None,
    operations: list[str] | None = None,
    feasibility_runner: ShapeFixRunner | None = None,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_station_seam_shape_fix_feasibility_report(
            same_parameter_feasibility_path=same_parameter_feasibility_path,
            tolerances=tolerances,
            operations=operations,
            feasibility_runner=feasibility_runner,
        )
    json_path = out_dir / "main_wing_station_seam_shape_fix_feasibility.v1.json"
    markdown_path = out_dir / "main_wing_station_seam_shape_fix_feasibility.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
