from __future__ import annotations

from collections.abc import Callable
import json
import math
from pathlib import Path
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field

from .main_wing_station_seam_profile_resample_repair_feasibility_probe import (
    _target_edges_from_validation,
)
from .main_wing_station_seam_side_aware_pcurve_residual_diagnostic import (
    _sample_distances,
)


SideAwarePCurveMetadataBuilderStatusType = Literal[
    "side_aware_station_pcurve_metadata_builder_recovered",
    "side_aware_station_pcurve_metadata_builder_partial",
    "side_aware_station_pcurve_metadata_builder_not_recovered",
    "side_aware_station_pcurve_metadata_builder_unavailable",
    "blocked",
]
PCurveMetadataBuilderRunner = Callable[..., Dict[str, Any]]

DEFAULT_PCURVE_METADATA_BUILDER_STRATEGIES = [
    "bounded_existing_pcurve_update_edge",
    "bounded_existing_pcurve_update_edge_and_vertex_params",
    "bounded_existing_pcurve_replace",
    "bounded_existing_pcurve_replace_and_vertex_params",
]


class MainWingStationSeamSideAwarePCurveMetadataBuilderProbeReport(BaseModel):
    schema_version: Literal[
        "main_wing_station_seam_side_aware_pcurve_metadata_builder_probe.v1"
    ] = "main_wing_station_seam_side_aware_pcurve_metadata_builder_probe.v1"
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal[
        "report_only_side_aware_station_pcurve_metadata_builder"
    ] = "report_only_side_aware_station_pcurve_metadata_builder"
    production_default_changed: bool = False
    metadata_builder_status: SideAwarePCurveMetadataBuilderStatusType
    side_aware_brep_validation_probe_path: str
    metadata_repair_probe_path: str
    candidate_step_path: str | None = None
    target_edges: list[dict[str, Any]] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    api_semantics: dict[str, Any] = Field(default_factory=dict)
    upstream_metadata_repair_summary: dict[str, Any] = Field(default_factory=dict)
    baseline_checks: list[dict[str, Any]] = Field(default_factory=list)
    baseline_summary: dict[str, Any] = Field(default_factory=dict)
    strategy_attempts: list[dict[str, Any]] = Field(default_factory=list)
    strategy_attempt_summary: dict[str, Any] = Field(default_factory=dict)
    engineering_findings: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_brep_validation_probe_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_side_aware_brep_validation_probe"
        / "main_wing_station_seam_side_aware_brep_validation_probe.v1.json"
    )


def _default_metadata_repair_probe_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_side_aware_metadata_repair_probe"
        / "main_wing_station_seam_side_aware_metadata_repair_probe.v1.json"
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
    if path.is_absolute():
        return path
    repo_path = _repo_root() / path
    if repo_path.exists():
        return repo_path
    package_path = _repo_root() / "hpa_meshing_package" / path
    if package_path.exists():
        return package_path
    return repo_path


def _dict_list(values: Any) -> list[dict[str, Any]]:
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _bool_or_error(label: str, call: Callable[[], Any]) -> tuple[bool | None, str | None]:
    try:
        return bool(call()), None
    except Exception as exc:
        return None, f"{label}: {exc}"


def _dynamic_type_name(shape: Any) -> str | None:
    try:
        return str(shape.DynamicType().Name())
    except Exception:
        return None


def _bounded_domain(first: Any, last: Any) -> bool | None:
    if not isinstance(first, (int, float)) or not isinstance(last, (int, float)):
        return None
    if not math.isfinite(float(first)) or not math.isfinite(float(last)):
        return False
    return abs(float(first)) < 1.0e50 and abs(float(last)) < 1.0e50


def _face_check_passes(face_check: dict[str, Any]) -> bool:
    return all(
        face_check.get(key) is True
        for key in (
            "has_pcurve",
            "pcurve_domain_bounded",
            "check_pcurve_range",
            "check_same_parameter",
            "check_curve3d_with_pcurve",
            "check_vertex_tolerance",
        )
    )


def _summary(checks: list[dict[str, Any]]) -> dict[str, Any]:
    face_checks = [
        face_check
        for check in checks
        for face_check in _dict_list(check.get("face_checks", []))
    ]
    return {
        "target_edge_count": len(checks),
        "target_face_count": len(face_checks),
        "pcurve_present_face_count": sum(
            face_check.get("has_pcurve") is True for face_check in face_checks
        ),
        "bounded_pcurve_face_count": sum(
            face_check.get("pcurve_domain_bounded") is True
            for face_check in face_checks
        ),
        "same_parameter_pass_face_count": sum(
            face_check.get("check_same_parameter") is True for face_check in face_checks
        ),
        "curve3d_with_pcurve_pass_face_count": sum(
            face_check.get("check_curve3d_with_pcurve") is True
            for face_check in face_checks
        ),
        "vertex_tolerance_pass_face_count": sum(
            face_check.get("check_vertex_tolerance") is True for face_check in face_checks
        ),
        "passed_face_count": sum(_face_check_passes(face_check) for face_check in face_checks),
        "check_error_count": sum(
            bool(face_check.get("check_errors")) for face_check in face_checks
        ),
        "all_station_metadata_checks_pass": bool(face_checks)
        and all(_face_check_passes(face_check) for face_check in face_checks),
    }


def _attempt_summary(
    *,
    baseline_summary: dict[str, Any],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    attempt_summaries: list[dict[str, Any]] = []
    for attempt in attempts:
        checks = _dict_list(attempt.get("checks", []))
        attempt_summaries.append(
            {
                "strategy": attempt.get("strategy"),
                **_summary(checks),
            }
        )
    recovered = [
        summary
        for summary in attempt_summaries
        if summary.get("all_station_metadata_checks_pass") is True
    ]
    best_bounded = max(
        (
            int(summary.get("bounded_pcurve_face_count") or 0)
            for summary in attempt_summaries
        ),
        default=0,
    )
    best_passed = max(
        (int(summary.get("passed_face_count") or 0) for summary in attempt_summaries),
        default=0,
    )
    baseline_bounded = int(baseline_summary.get("bounded_pcurve_face_count") or 0)
    baseline_passed = int(baseline_summary.get("passed_face_count") or 0)
    partial = best_bounded > baseline_bounded or best_passed > baseline_passed
    return {
        "attempt_count": len(attempts),
        "strategies_evaluated": [
            str(attempt.get("strategy"))
            for attempt in attempts
            if attempt.get("strategy") is not None
        ],
        "recovered_attempt_count": len(recovered),
        "first_recovered_strategy": recovered[0].get("strategy") if recovered else None,
        "best_bounded_face_count": best_bounded,
        "best_passed_face_count": best_passed,
        "partial_progress_observed": partial,
        "attempt_summaries": attempt_summaries,
    }


def _api_semantics() -> dict[str, Any]:
    return {
        "primary_api_family": "OCCT/OCP in-memory topology metadata editing",
        "candidate_operations": [
            "BRep_Builder.UpdateEdge(edge, pcurve, face, tolerance)",
            "BRep_Builder.Range(edge, face, first, last)",
            "BRep_Builder.UpdateVertex(vertex, parameter, edge, face, tolerance)",
            "ShapeBuild_Edge.ReplacePCurve(edge, pcurve, face)",
            "Geom2d_TrimmedCurve(existing_pcurve, first, last, sense)",
        ],
        "success_gate": [
            "HasPCurve",
            "bounded PCurve domain",
            "CheckPCurveRange",
            "CheckSameParameter",
            "CheckCurve3dWithPCurve",
            "CheckVertexTolerance",
        ],
        "truth_source": "ShapeAnalysis_Edge checks, not SameParameter/SameRange flags alone",
    }


def _upstream_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return {
        "metadata_repair_status": payload.get("metadata_repair_status"),
        "same_parameter_attempt_summary": payload.get(
            "same_parameter_attempt_summary",
            {},
        ),
        "shape_fix_attempt_summary": payload.get("shape_fix_attempt_summary", {}),
        "residual_context_summary": payload.get("residual_context_summary", {}),
        "blocking_reasons": payload.get("blocking_reasons", []),
    }


def _status(
    *,
    blockers: list[str],
    runner_payload: dict[str, Any],
    attempt_summary: dict[str, Any],
) -> SideAwarePCurveMetadataBuilderStatusType:
    if blockers:
        return "blocked"
    if runner_payload.get("runtime_status") != "evaluated":
        return "side_aware_station_pcurve_metadata_builder_unavailable"
    if int(attempt_summary.get("recovered_attempt_count") or 0) > 0:
        return "side_aware_station_pcurve_metadata_builder_recovered"
    if attempt_summary.get("partial_progress_observed") is True:
        return "side_aware_station_pcurve_metadata_builder_partial"
    return "side_aware_station_pcurve_metadata_builder_not_recovered"


def _engineering_findings(
    *,
    status: SideAwarePCurveMetadataBuilderStatusType,
    upstream_metadata_repair_summary: dict[str, Any],
    baseline_summary: dict[str, Any],
    attempt_summary: dict[str, Any],
) -> list[str]:
    if status == "blocked":
        return ["side_aware_pcurve_metadata_builder_blocked"]
    if status == "side_aware_station_pcurve_metadata_builder_unavailable":
        return ["side_aware_pcurve_metadata_builder_runtime_unavailable"]
    findings = ["side_aware_pcurve_metadata_builder_evaluated"]
    if (
        upstream_metadata_repair_summary.get("metadata_repair_status")
        == "side_aware_station_metadata_repair_not_recovered"
    ):
        findings.append("upstream_same_parameter_shape_fix_repair_not_recovered")
    if int(baseline_summary.get("bounded_pcurve_face_count") or 0) < int(
        baseline_summary.get("target_face_count") or 0
    ):
        findings.append("unbounded_existing_pcurve_domain_observed")
    if status == "side_aware_station_pcurve_metadata_builder_recovered":
        findings.append("bounded_pcurve_metadata_builder_recovered_station_gate")
    elif status == "side_aware_station_pcurve_metadata_builder_partial":
        findings.append("bounded_pcurve_domains_observed_without_station_metadata_recovery")
        findings.append("projected_or_sampled_pcurve_builder_still_needed")
    else:
        findings.append("pcurve_metadata_builder_strategy_sweep_no_recovery")
    if int(attempt_summary.get("best_passed_face_count") or 0) == 0:
        findings.append("no_target_edge_face_pair_passed_full_metadata_gate")
    return findings


def _blocking_reasons(
    status: SideAwarePCurveMetadataBuilderStatusType,
    blockers: list[str],
) -> list[str]:
    reasons = list(blockers)
    if status == "side_aware_station_pcurve_metadata_builder_unavailable":
        reasons.append("side_aware_station_pcurve_metadata_builder_runtime_unavailable")
    if status in {
        "side_aware_station_pcurve_metadata_builder_not_recovered",
        "side_aware_station_pcurve_metadata_builder_partial",
    }:
        reasons.append("side_aware_station_pcurve_metadata_builder_not_recovered")
        reasons.append("side_aware_candidate_mesh_handoff_not_run")
    if status == "blocked" and not reasons:
        reasons.append("side_aware_pcurve_metadata_builder_blocked")
    return list(dict.fromkeys(reasons))


def _next_actions(status: SideAwarePCurveMetadataBuilderStatusType) -> list[str]:
    if status == "side_aware_station_pcurve_metadata_builder_recovered":
        return [
            "materialize_repaired_side_aware_step_as_separate_artifact",
            "rerun_side_aware_brep_validation_on_repaired_step",
            "run_bounded_main_wing_mesh_handoff_from_repaired_step",
        ]
    if status in {
        "side_aware_station_pcurve_metadata_builder_not_recovered",
        "side_aware_station_pcurve_metadata_builder_partial",
    }:
        return [
            "prototype_projected_or_sampled_pcurve_builder_with_vertex_orientation_gate",
            "avoid_claiming_mesh_handoff_readiness_from_bounded_pcurve_domain_only",
            "do_not_advance_to_solver_budget_until_station_metadata_gate_passes",
        ]
    if status == "side_aware_station_pcurve_metadata_builder_unavailable":
        return ["restore_ocp_runtime_before_pcurve_metadata_builder_claims"]
    return ["restore_side_aware_pcurve_metadata_builder_inputs"]


def _check_edge_face(
    *,
    edge: Any,
    face: Any,
    face_id: int,
    sample_count: int,
) -> dict[str, Any]:
    from OCP.BRep import BRep_Tool
    from OCP.ShapeAnalysis import ShapeAnalysis_Edge

    analyzer = ShapeAnalysis_Edge()
    has_pcurve, has_error = _bool_or_error(
        "HasPCurve",
        lambda: analyzer.HasPCurve(edge, face),
    )
    check_errors = [has_error] if has_error else []
    edge_range = BRep_Tool.Range_s(edge)
    face_range = None
    pcurve = None
    pcurve_type = None
    pcurve_first = None
    pcurve_last = None
    pcurve_bounded = None
    if has_pcurve:
        try:
            face_range = BRep_Tool.Range_s(edge, face)
            pcurve = BRep_Tool.CurveOnSurface_s(edge, face, 0.0, 0.0)
            pcurve_type = _dynamic_type_name(pcurve)
            pcurve_first = float(pcurve.FirstParameter())
            pcurve_last = float(pcurve.LastParameter())
            pcurve_bounded = _bounded_domain(pcurve_first, pcurve_last)
        except Exception as exc:
            check_errors.append(f"read_pcurve: {exc}")

    if pcurve is not None:
        check_pcurve_range, error = _bool_or_error(
            "CheckPCurveRange",
            lambda: analyzer.CheckPCurveRange(
                float(edge_range[0]),
                float(edge_range[1]),
                pcurve,
            ),
        )
        if error:
            check_errors.append(error)
        check_curve3d, error = _bool_or_error(
            "CheckCurve3dWithPCurve",
            lambda: analyzer.CheckCurve3dWithPCurve(edge, face),
        )
        if error:
            check_errors.append(error)
    else:
        check_pcurve_range = None
        check_curve3d = None

    check_same, error = _bool_or_error(
        "CheckSameParameter",
        lambda: analyzer.CheckSameParameter(edge, face, 0.0, 23),
    )
    if error:
        check_errors.append(error)
    check_vertex, error = _bool_or_error(
        "CheckVertexTolerance",
        lambda: analyzer.CheckVertexTolerance(edge, face, 0.0, 0.0),
    )
    if error:
        check_errors.append(error)

    sampled: dict[str, Any] = {}
    if pcurve is not None:
        try:
            sampled = _sample_distances(
                edge=edge,
                face=face,
                sample_count=sample_count,
            )
        except Exception as exc:
            check_errors.append(f"sample_distances: {exc}")

    return {
        "face_id": int(face_id),
        "face_found": True,
        "has_pcurve": has_pcurve,
        "edge_range": [float(edge_range[0]), float(edge_range[1])],
        "pcurve_edge_range": (
            None if face_range is None else [float(face_range[0]), float(face_range[1])]
        ),
        "pcurve_type": pcurve_type,
        "pcurve_first_parameter": pcurve_first,
        "pcurve_last_parameter": pcurve_last,
        "pcurve_domain_bounded": pcurve_bounded,
        "check_pcurve_range": check_pcurve_range,
        "check_same_parameter": check_same,
        "check_curve3d_with_pcurve": check_curve3d,
        "check_vertex_tolerance": check_vertex,
        "max_sample_distance_m": sampled.get("max_sample_distance_m"),
        "max_sample_distance_over_edge_tolerance": sampled.get(
            "max_sample_distance_over_edge_tolerance"
        ),
        "check_errors": [error for error in check_errors if error],
    }


def evaluate_side_aware_station_pcurve_metadata_builder_strategies(
    *,
    step_path: Path,
    target_edges: list[dict[str, Any]],
    strategies: list[str],
    sample_count: int = 11,
) -> dict[str, Any]:
    try:
        from OCP.BRep import BRep_Builder, BRep_Tool
        from OCP.Geom2d import Geom2d_TrimmedCurve
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.ShapeBuild import ShapeBuild_Edge
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
            "strategy_attempts": [],
        }

    def _load_shape():
        reader = STEPControl_Reader()
        status = reader.ReadFile(str(step_path))
        if status != IFSelect_RetDone:
            raise RuntimeError(f"STEP reader failed with status {int(status)}")
        reader.TransferRoots()
        shape = reader.OneShape()
        face_index_map = TopTools_IndexedMapOfShape()
        edge_index_map = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, TopAbs_FACE, face_index_map)
        TopExp.MapShapes_s(shape, TopAbs_EDGE, edge_index_map)
        return shape, face_index_map, edge_index_map

    def _evaluate(face_index_map, edge_index_map) -> list[dict[str, Any]]:
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
                    _check_edge_face(
                        edge=edge,
                        face=face,
                        face_id=face_index,
                        sample_count=sample_count,
                    )
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

    def _call(label: str, call: Callable[[], Any]) -> dict[str, Any]:
        try:
            result = call()
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

    def _apply_strategy(face_index_map, edge_index_map, strategy: str) -> list[dict[str, Any]]:
        builder = BRep_Builder()
        shape_builder = ShapeBuild_Edge()
        operation_results: list[dict[str, Any]] = []
        for target in target_edges:
            edge_index = int(target["edge_index"])
            if edge_index < 1 or edge_index > edge_index_map.Size():
                operation_results.append(
                    {**target, "edge_found": False, "face_operations": []}
                )
                continue
            edge = TopoDS.Edge_s(edge_index_map.FindKey(edge_index))
            edge_tolerance = float(BRep_Tool.Tolerance_s(edge))
            first_vertex = TopExp.FirstVertex_s(edge)
            last_vertex = TopExp.LastVertex_s(edge)
            face_operations: list[dict[str, Any]] = []
            for face_id in target.get("face_ids", []):
                face_index = int(face_id)
                if face_index < 1 or face_index > face_index_map.Size():
                    face_operations.append(
                        {
                            "face_id": face_index,
                            "label": f"face {face_index}",
                            "called": False,
                            "result": None,
                            "error": "face_not_found",
                        }
                    )
                    continue
                face = TopoDS.Face_s(face_index_map.FindKey(face_index))
                try:
                    old_pcurve = BRep_Tool.CurveOnSurface_s(edge, face, 0.0, 0.0)
                    pcurve_range = BRep_Tool.Range_s(edge, face)
                    first = float(pcurve_range[0])
                    last = float(pcurve_range[1])
                    trimmed = Geom2d_TrimmedCurve(old_pcurve, first, last, True)
                except Exception as exc:
                    face_operations.append(
                        {
                            "face_id": face_index,
                            "label": "build_bounded_existing_pcurve",
                            "called": False,
                            "result": None,
                            "error": str(exc),
                        }
                    )
                    continue
                if strategy.startswith("bounded_existing_pcurve_replace"):
                    face_operations.append(
                        {
                            "face_id": face_index,
                            **_call(
                                "ShapeBuild_Edge.ReplacePCurve(trimmed, face)",
                                lambda edge=edge, trimmed=trimmed, face=face: shape_builder.ReplacePCurve(
                                    edge,
                                    trimmed,
                                    face,
                                ),
                            ),
                        }
                    )
                elif strategy.startswith("bounded_existing_pcurve_update_edge"):
                    face_operations.append(
                        {
                            "face_id": face_index,
                            **_call(
                                "BRep_Builder.UpdateEdge(trimmed, face, tolerance)",
                                lambda edge=edge, trimmed=trimmed, face=face: builder.UpdateEdge(
                                    edge,
                                    trimmed,
                                    face,
                                    edge_tolerance,
                                ),
                            ),
                        }
                    )
                else:
                    face_operations.append(
                        {
                            "face_id": face_index,
                            "label": strategy,
                            "called": False,
                            "result": None,
                            "error": "unsupported_strategy",
                        }
                    )
                    continue
                face_operations.append(
                    {
                        "face_id": face_index,
                        **_call(
                            "BRep_Builder.Range(edge, face, first, last)",
                            lambda edge=edge, face=face, first=first, last=last: builder.Range(
                                edge,
                                face,
                                first,
                                last,
                            ),
                        ),
                    }
                )
                if strategy.endswith("_and_vertex_params"):
                    if not first_vertex.IsNull():
                        face_operations.append(
                            {
                                "face_id": face_index,
                                **_call(
                                    "BRep_Builder.UpdateVertex(first, first_param, edge, face)",
                                    lambda vertex=first_vertex, edge=edge, face=face, first=first: builder.UpdateVertex(
                                        vertex,
                                        first,
                                        edge,
                                        face,
                                        edge_tolerance,
                                    ),
                                ),
                            }
                        )
                    if not last_vertex.IsNull():
                        face_operations.append(
                            {
                                "face_id": face_index,
                                **_call(
                                    "BRep_Builder.UpdateVertex(last, last_param, edge, face)",
                                    lambda vertex=last_vertex, edge=edge, face=face, last=last: builder.UpdateVertex(
                                        vertex,
                                        last,
                                        edge,
                                        face,
                                        edge_tolerance,
                                    ),
                                ),
                            }
                        )
            operation_results.append(
                {**target, "edge_found": True, "face_operations": face_operations}
            )
        return operation_results

    try:
        _, baseline_faces, baseline_edges = _load_shape()
        baseline_checks = _evaluate(baseline_faces, baseline_edges)
        attempts: list[dict[str, Any]] = []
        for strategy in strategies:
            _, face_index_map, edge_index_map = _load_shape()
            operation_results = _apply_strategy(
                face_index_map,
                edge_index_map,
                str(strategy),
            )
            checks = _evaluate(face_index_map, edge_index_map)
            attempts.append(
                {
                    "strategy": str(strategy),
                    "operation_results": operation_results,
                    "checks": checks,
                }
            )
    except Exception as exc:
        return {
            "runtime_status": "unavailable",
            "reason": "pcurve_metadata_builder_exception",
            "error": str(exc),
            "baseline_checks": [],
            "strategy_attempts": [],
        }
    return {
        "runtime_status": "evaluated",
        "baseline_checks": baseline_checks,
        "strategy_attempts": attempts,
    }


def build_main_wing_station_seam_side_aware_pcurve_metadata_builder_probe_report(
    *,
    side_aware_brep_validation_probe_path: Path | None = None,
    metadata_repair_probe_path: Path | None = None,
    strategies: list[str] | None = None,
    metadata_builder_runner: PCurveMetadataBuilderRunner | None = None,
) -> MainWingStationSeamSideAwarePCurveMetadataBuilderProbeReport:
    brep_path = (
        _default_brep_validation_probe_path()
        if side_aware_brep_validation_probe_path is None
        else side_aware_brep_validation_probe_path
    )
    metadata_path = (
        _default_metadata_repair_probe_path()
        if metadata_repair_probe_path is None
        else metadata_repair_probe_path
    )
    blockers: list[str] = []
    brep_payload = _load_json(brep_path, blockers, "side_aware_brep_validation_probe")
    metadata_payload = _load_json(
        metadata_path,
        blockers,
        "side_aware_metadata_repair_probe",
    )
    step_path = _resolve_path(
        (
            metadata_payload.get("candidate_step_path")
            if isinstance(metadata_payload, dict)
            else None
        )
        or (
            brep_payload.get("candidate_step_path")
            if isinstance(brep_payload, dict)
            else None
        )
    )
    if step_path is None:
        blockers.append("side_aware_candidate_step_path_missing")
    elif not step_path.exists():
        blockers.append("side_aware_candidate_step_missing")
    target_edges = (
        _dict_list(metadata_payload.get("target_edges", []))
        if isinstance(metadata_payload, dict)
        else []
    )
    if not target_edges:
        target_edges = _target_edges_from_validation(brep_payload)
    if not target_edges:
        blockers.append("side_aware_pcurve_metadata_builder_target_edges_missing")
    strategy_values = (
        list(DEFAULT_PCURVE_METADATA_BUILDER_STRATEGIES)
        if strategies is None
        else [str(value) for value in strategies]
    )

    runner_payload: dict[str, Any] = {}
    if not blockers and step_path is not None:
        runner = (
            metadata_builder_runner
            or evaluate_side_aware_station_pcurve_metadata_builder_strategies
        )
        runner_payload = runner(
            step_path=step_path,
            target_edges=target_edges,
            strategies=strategy_values,
        )

    baseline_checks = _dict_list(runner_payload.get("baseline_checks", []))
    strategy_attempts = _dict_list(runner_payload.get("strategy_attempts", []))
    baseline_summary = _summary(baseline_checks)
    strategy_attempt_summary = _attempt_summary(
        baseline_summary=baseline_summary,
        attempts=strategy_attempts,
    )
    upstream_summary = _upstream_summary(metadata_payload)
    metadata_builder_status = _status(
        blockers=blockers,
        runner_payload=runner_payload,
        attempt_summary=strategy_attempt_summary,
    )

    return MainWingStationSeamSideAwarePCurveMetadataBuilderProbeReport(
        metadata_builder_status=metadata_builder_status,
        side_aware_brep_validation_probe_path=str(brep_path),
        metadata_repair_probe_path=str(metadata_path),
        candidate_step_path=str(step_path) if step_path is not None else None,
        target_edges=target_edges,
        strategies=strategy_values,
        api_semantics=_api_semantics(),
        upstream_metadata_repair_summary=upstream_summary,
        baseline_checks=baseline_checks,
        baseline_summary=baseline_summary,
        strategy_attempts=strategy_attempts,
        strategy_attempt_summary=strategy_attempt_summary,
        engineering_findings=_engineering_findings(
            status=metadata_builder_status,
            upstream_metadata_repair_summary=upstream_summary,
            baseline_summary=baseline_summary,
            attempt_summary=strategy_attempt_summary,
        ),
        blocking_reasons=_blocking_reasons(metadata_builder_status, blockers),
        next_actions=_next_actions(metadata_builder_status),
        limitations=[
            "This probe evaluates in-memory PCurve metadata construction only and writes no repaired STEP.",
            "It does not change production defaults or promote the side-aware candidate to mesh handoff.",
            "Bounding an existing PCurve domain is recorded as partial progress only unless all ShapeAnalysis gates pass.",
            "SameParameter/SameRange flags are not treated as proof; ShapeAnalysis_Edge checks are the route gate.",
            "It does not run Gmsh volume meshing, SU2_CFD, CL acceptance, or convergence checks.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_markdown(
    report: MainWingStationSeamSideAwarePCurveMetadataBuilderProbeReport,
) -> str:
    lines = [
        "# Main Wing Station-Seam Side-Aware PCurve Metadata Builder Probe v1",
        "",
        "This report tests in-memory PCurve metadata construction strategies on the side-aware station-seam candidate without writing repaired geometry.",
        "",
        f"- metadata_builder_status: `{report.metadata_builder_status}`",
        f"- side_aware_brep_validation_probe_path: `{report.side_aware_brep_validation_probe_path}`",
        f"- metadata_repair_probe_path: `{report.metadata_repair_probe_path}`",
        f"- candidate_step_path: `{report.candidate_step_path}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Baseline Summary",
        "",
    ]
    for key, value in report.baseline_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Strategy Attempt Summary", ""])
    for key, value in report.strategy_attempt_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Target Edges", ""])
    if report.target_edges:
        lines.extend(f"- `{_fmt(item)}`" for item in report.target_edges)
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


def write_main_wing_station_seam_side_aware_pcurve_metadata_builder_probe_report(
    out_dir: Path,
    *,
    report: MainWingStationSeamSideAwarePCurveMetadataBuilderProbeReport | None = None,
    side_aware_brep_validation_probe_path: Path | None = None,
    metadata_repair_probe_path: Path | None = None,
    strategies: list[str] | None = None,
    metadata_builder_runner: PCurveMetadataBuilderRunner | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_station_seam_side_aware_pcurve_metadata_builder_probe_report(
            side_aware_brep_validation_probe_path=side_aware_brep_validation_probe_path,
            metadata_repair_probe_path=metadata_repair_probe_path,
            strategies=strategies,
            metadata_builder_runner=metadata_builder_runner,
        )
    json_path = (
        out_dir
        / "main_wing_station_seam_side_aware_pcurve_metadata_builder_probe.v1.json"
    )
    markdown_path = (
        out_dir
        / "main_wing_station_seam_side_aware_pcurve_metadata_builder_probe.v1.md"
    )
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
