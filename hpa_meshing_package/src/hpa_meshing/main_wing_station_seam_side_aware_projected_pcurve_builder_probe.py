from __future__ import annotations

from collections.abc import Callable
import json
import math
from pathlib import Path
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field

from .main_wing_station_seam_side_aware_pcurve_metadata_builder_probe import (
    _check_edge_face,
    _dict_list,
    _load_json,
    _resolve_path,
    _summary,
)


SideAwareProjectedPCurveBuilderStatusType = Literal[
    "side_aware_station_projected_pcurve_builder_recovered",
    "side_aware_station_projected_pcurve_builder_partial",
    "side_aware_station_projected_pcurve_builder_not_recovered",
    "side_aware_station_projected_pcurve_builder_unavailable",
    "blocked",
]
ProjectedPCurveBuilderRunner = Callable[..., Dict[str, Any]]

DEFAULT_PROJECTED_PCURVE_BUILDER_STRATEGIES = [
    "geomprojlib_curve2d_update_edge_then_same_parameter",
    "sampled_surface_project_interpolate_update_edge_then_same_parameter",
    "sampled_surface_project_approx_update_edge_then_same_parameter",
]


class MainWingStationSeamSideAwareProjectedPCurveBuilderProbeReport(BaseModel):
    schema_version: Literal[
        "main_wing_station_seam_side_aware_projected_pcurve_builder_probe.v1"
    ] = "main_wing_station_seam_side_aware_projected_pcurve_builder_probe.v1"
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal[
        "report_only_side_aware_station_projected_pcurve_builder"
    ] = "report_only_side_aware_station_projected_pcurve_builder"
    production_default_changed: bool = False
    projected_builder_status: SideAwareProjectedPCurveBuilderStatusType
    pcurve_metadata_builder_probe_path: str
    candidate_step_path: str | None = None
    target_edges: list[dict[str, Any]] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    sample_count: int = 23
    projection_tolerance_m: float = 1.0e-7
    interpolation_tolerance: float = 1.0e-9
    api_semantics: dict[str, Any] = Field(default_factory=dict)
    upstream_pcurve_metadata_builder_summary: dict[str, Any] = Field(
        default_factory=dict
    )
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


def _default_pcurve_metadata_builder_probe_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_side_aware_pcurve_metadata_builder_probe"
        / "main_wing_station_seam_side_aware_pcurve_metadata_builder_probe.v1.json"
    )


def _point_tuple(point: Any) -> tuple[float, float, float]:
    return (float(point.X()), float(point.Y()), float(point.Z()))


def _dynamic_type_name(shape: Any) -> str | None:
    try:
        return str(shape.DynamicType().Name())
    except Exception:
        return None


def _face_operation_records(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for attempt in attempts:
        for operation_result in _dict_list(attempt.get("operation_results", [])):
            for face_operation in _dict_list(
                operation_result.get("face_operations", [])
            ):
                records.append(face_operation)
    return records


def _projected_face_count(attempts: list[dict[str, Any]]) -> int:
    return sum(
        operation.get("projected_pcurve_built") is True
        for operation in _face_operation_records(attempts)
    )


def _endpoint_orientation_pass_count(attempts: list[dict[str, Any]]) -> int:
    count = 0
    for operation in _face_operation_records(attempts):
        gate = operation.get("endpoint_orientation_gate", {})
        if not isinstance(gate, dict):
            continue
        if (
            gate.get("orientation_preserved") is True
            and gate.get("endpoint_residual_within_tolerance") is True
        ):
            count += 1
    return count


def _max_projection_distance(attempts: list[dict[str, Any]]) -> float | None:
    values = [
        float(distance)
        for operation in _face_operation_records(attempts)
        if isinstance(distance := operation.get("max_projection_distance_m"), (int, float))
        and not isinstance(distance, bool)
        and math.isfinite(float(distance))
    ]
    return max(values) if values else None


def _flags_true_but_gate_fails(attempts: list[dict[str, Any]]) -> bool:
    for attempt in attempts:
        for check in _dict_list(attempt.get("checks", [])):
            for face_check in _dict_list(check.get("face_checks", [])):
                flags_true = (
                    face_check.get("same_parameter_flag") is True
                    and face_check.get("same_range_flag") is True
                )
                gate_failed = any(
                    face_check.get(key) is False
                    for key in (
                        "check_same_parameter",
                        "check_curve3d_with_pcurve",
                        "check_vertex_tolerance",
                    )
                )
                if flags_true and gate_failed:
                    return True
    return False


def _attempt_summary(
    *,
    baseline_summary: dict[str, Any],
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    attempt_summaries: list[dict[str, Any]] = []
    for attempt in attempts:
        attempt_summaries.append(
            {
                "strategy": attempt.get("strategy"),
                **_summary(_dict_list(attempt.get("checks", []))),
                "projected_pcurve_built_face_count": _projected_face_count([attempt]),
                "endpoint_orientation_pass_face_count": (
                    _endpoint_orientation_pass_count([attempt])
                ),
                "max_projection_distance_m": _max_projection_distance([attempt]),
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
    projected_count = _projected_face_count(attempts)
    endpoint_pass_count = _endpoint_orientation_pass_count(attempts)
    baseline_bounded = int(baseline_summary.get("bounded_pcurve_face_count") or 0)
    baseline_passed = int(baseline_summary.get("passed_face_count") or 0)
    partial = (
        projected_count > 0
        or endpoint_pass_count > 0
        or best_bounded > baseline_bounded
        or best_passed > baseline_passed
    )
    return {
        "attempt_count": len(attempts),
        "strategies_evaluated": [
            str(attempt.get("strategy"))
            for attempt in attempts
            if attempt.get("strategy") is not None
        ],
        "recovered_attempt_count": len(recovered),
        "first_recovered_strategy": recovered[0].get("strategy") if recovered else None,
        "projected_pcurve_built_face_count": projected_count,
        "endpoint_orientation_pass_face_count": endpoint_pass_count,
        "max_projection_distance_m": _max_projection_distance(attempts),
        "best_bounded_face_count": best_bounded,
        "best_passed_face_count": best_passed,
        "partial_progress_observed": partial,
        "same_parameter_or_same_range_flags_true_but_gate_failed": (
            _flags_true_but_gate_fails(attempts)
        ),
        "attempt_summaries": attempt_summaries,
    }


def _api_semantics() -> dict[str, Any]:
    return {
        "primary_api_family": "OCCT/OCP in-memory projected PCurve reconstruction",
        "candidate_operations": [
            "GeomProjLib.Curve2d(c3d, first, last, surface, tolerance)",
            "GeomAPI_ProjectPointOnSurf sampled on BRepTools.UVBounds(face)",
            "Geom2dAPI_Interpolate(points, parameters)",
            "Geom2dAPI_PointsToBSpline(points, parameters)",
            "BRep_Builder.UpdateEdge(edge, projected_pcurve, face, tolerance)",
            "BRep_Builder.UpdateVertex(vertex, parameter, edge, face, tolerance)",
            "BRepLib.SameParameter(edge, tolerance)",
        ],
        "success_gate": [
            "projected PCurve built",
            "endpoint orientation gate preserved",
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
        "metadata_builder_status": payload.get("metadata_builder_status"),
        "baseline_summary": payload.get("baseline_summary", {}),
        "strategy_attempt_summary": payload.get("strategy_attempt_summary", {}),
        "blocking_reasons": payload.get("blocking_reasons", []),
    }


def _status(
    *,
    blockers: list[str],
    runner_payload: dict[str, Any],
    attempt_summary: dict[str, Any],
) -> SideAwareProjectedPCurveBuilderStatusType:
    if blockers:
        return "blocked"
    if runner_payload.get("runtime_status") != "evaluated":
        return "side_aware_station_projected_pcurve_builder_unavailable"
    if int(attempt_summary.get("recovered_attempt_count") or 0) > 0:
        return "side_aware_station_projected_pcurve_builder_recovered"
    if attempt_summary.get("partial_progress_observed") is True:
        return "side_aware_station_projected_pcurve_builder_partial"
    return "side_aware_station_projected_pcurve_builder_not_recovered"


def _engineering_findings(
    *,
    status: SideAwareProjectedPCurveBuilderStatusType,
    upstream_pcurve_metadata_builder_summary: dict[str, Any],
    attempt_summary: dict[str, Any],
) -> list[str]:
    if status == "blocked":
        return ["side_aware_projected_pcurve_builder_blocked"]
    if status == "side_aware_station_projected_pcurve_builder_unavailable":
        return ["side_aware_projected_pcurve_builder_runtime_unavailable"]
    findings = ["side_aware_projected_pcurve_builder_evaluated"]
    if upstream_pcurve_metadata_builder_summary.get("metadata_builder_status") in {
        "side_aware_station_pcurve_metadata_builder_partial",
        "side_aware_station_pcurve_metadata_builder_not_recovered",
    }:
        findings.append("upstream_bounded_pcurve_builder_not_recovered")
    if int(attempt_summary.get("projected_pcurve_built_face_count") or 0) > 0:
        findings.append("projected_or_sampled_pcurves_materialized_in_memory")
    if int(attempt_summary.get("endpoint_orientation_pass_face_count") or 0) > 0:
        findings.append("projected_endpoint_orientation_gate_passed")
    max_projection_distance = attempt_summary.get("max_projection_distance_m")
    if isinstance(max_projection_distance, (int, float)) and max_projection_distance <= 1.0e-7:
        findings.append("projected_sampled_geometry_residuals_within_projection_tolerance")
    if status == "side_aware_station_projected_pcurve_builder_recovered":
        findings.append("projected_or_sampled_pcurve_builder_recovered_station_gate")
    else:
        findings.append("shape_analysis_gate_still_fails_after_projected_or_sampled_pcurves")
    if attempt_summary.get("same_parameter_or_same_range_flags_true_but_gate_failed") is True:
        findings.append("same_parameter_flags_are_not_shape_analysis_truth_source")
    return list(dict.fromkeys(findings))


def _blocking_reasons(
    status: SideAwareProjectedPCurveBuilderStatusType,
    blockers: list[str],
) -> list[str]:
    reasons = list(blockers)
    if status == "side_aware_station_projected_pcurve_builder_unavailable":
        reasons.append("side_aware_station_projected_pcurve_builder_runtime_unavailable")
    if status in {
        "side_aware_station_projected_pcurve_builder_not_recovered",
        "side_aware_station_projected_pcurve_builder_partial",
    }:
        reasons.append("side_aware_station_projected_pcurve_builder_not_recovered")
        reasons.append("side_aware_candidate_mesh_handoff_not_run")
    if status == "blocked" and not reasons:
        reasons.append("side_aware_projected_pcurve_builder_blocked")
    return list(dict.fromkeys(reasons))


def _next_actions(status: SideAwareProjectedPCurveBuilderStatusType) -> list[str]:
    if status == "side_aware_station_projected_pcurve_builder_recovered":
        return [
            "materialize_projected_pcurve_repaired_step_as_separate_artifact",
            "rerun_side_aware_brep_validation_on_projected_pcurve_repaired_step",
            "run_bounded_main_wing_mesh_handoff_from_repaired_step",
        ]
    if status in {
        "side_aware_station_projected_pcurve_builder_not_recovered",
        "side_aware_station_projected_pcurve_builder_partial",
    }:
        return [
            "move_repair_upstream_to_section_parametrization_or_export_pcurve_generation",
            "do_not_advance_to_mesh_until_shape_analysis_gate_passes",
            "use_projected_pcurve_probe_as_negative_control_for_future_export_changes",
        ]
    if status == "side_aware_station_projected_pcurve_builder_unavailable":
        return ["restore_ocp_runtime_before_projected_pcurve_builder_claims"]
    return ["restore_projected_pcurve_builder_inputs"]


def _endpoint_orientation_gate(
    *,
    edge: Any,
    face: Any,
    pcurve: Any,
    tolerance: float,
) -> dict[str, Any]:
    from OCP.BRep import BRep_Tool
    from OCP.TopExp import TopExp

    edge_range = BRep_Tool.Range_s(edge)
    surface = BRep_Tool.Surface_s(face)
    curve3d = BRep_Tool.Curve_s(edge, 0.0, 0.0)
    first = float(edge_range[0])
    last = float(edge_range[1])
    start_uv = pcurve.Value(first)
    end_uv = pcurve.Value(last)
    start_surface = surface.Value(float(start_uv.X()), float(start_uv.Y()))
    end_surface = surface.Value(float(end_uv.X()), float(end_uv.Y()))
    first_curve = curve3d.Value(first)
    last_curve = curve3d.Value(last)
    first_vertex = TopExp.FirstVertex_s(edge)
    last_vertex = TopExp.LastVertex_s(edge)
    first_vertex_point = BRep_Tool.Pnt_s(first_vertex)
    last_vertex_point = BRep_Tool.Pnt_s(last_vertex)
    start_to_first_vertex = math.dist(
        _point_tuple(start_surface),
        _point_tuple(first_vertex_point),
    )
    start_to_last_vertex = math.dist(
        _point_tuple(start_surface),
        _point_tuple(last_vertex_point),
    )
    end_to_first_vertex = math.dist(
        _point_tuple(end_surface),
        _point_tuple(first_vertex_point),
    )
    end_to_last_vertex = math.dist(
        _point_tuple(end_surface),
        _point_tuple(last_vertex_point),
    )
    start_curve_residual = math.dist(_point_tuple(start_surface), _point_tuple(first_curve))
    end_curve_residual = math.dist(_point_tuple(end_surface), _point_tuple(last_curve))
    return {
        "start_uv": [float(start_uv.X()), float(start_uv.Y())],
        "end_uv": [float(end_uv.X()), float(end_uv.Y())],
        "start_surface_to_curve3d_m": start_curve_residual,
        "end_surface_to_curve3d_m": end_curve_residual,
        "start_surface_to_first_vertex_m": start_to_first_vertex,
        "start_surface_to_last_vertex_m": start_to_last_vertex,
        "end_surface_to_first_vertex_m": end_to_first_vertex,
        "end_surface_to_last_vertex_m": end_to_last_vertex,
        "orientation_preserved": (
            start_to_first_vertex <= start_to_last_vertex
            and end_to_last_vertex <= end_to_first_vertex
        ),
        "endpoint_residual_within_tolerance": max(
            start_curve_residual,
            end_curve_residual,
        )
        <= max(float(tolerance), 1.0e-12),
    }


def evaluate_side_aware_station_projected_pcurve_builder_strategies(
    *,
    step_path: Path,
    target_edges: list[dict[str, Any]],
    strategies: list[str],
    sample_count: int = 23,
    projection_tolerance_m: float = 1.0e-7,
    interpolation_tolerance: float = 1.0e-9,
) -> dict[str, Any]:
    try:
        from OCP.BRep import BRep_Builder, BRep_Tool
        from OCP.BRepLib import BRepLib
        from OCP.BRepTools import BRepTools
        from OCP.Geom2dAPI import Geom2dAPI_Interpolate, Geom2dAPI_PointsToBSpline
        from OCP.GeomAbs import GeomAbs_C2
        from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
        from OCP.GeomProjLib import GeomProjLib
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.STEPControl import STEPControl_Reader
        from OCP.TColgp import TColgp_Array1OfPnt2d, TColgp_HArray1OfPnt2d
        from OCP.TColStd import TColStd_Array1OfReal, TColStd_HArray1OfReal
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
        from OCP.TopExp import TopExp
        from OCP.TopTools import TopTools_IndexedMapOfShape
        from OCP.TopoDS import TopoDS
        from OCP.gp import gp_Pnt2d
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
                face_check = _check_edge_face(
                    edge=edge,
                    face=face,
                    face_id=face_index,
                    sample_count=sample_count,
                )
                face_check["same_parameter_flag"] = bool(
                    BRep_Tool.SameParameter_s(edge)
                )
                face_check["same_range_flag"] = bool(BRep_Tool.SameRange_s(edge))
                face_checks.append(face_check)
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

    def _sampled_projected_pcurve(edge, face, mode: str):
        edge_range = BRep_Tool.Range_s(edge)
        curve3d = BRep_Tool.Curve_s(edge, 0.0, 0.0)
        surface = BRep_Tool.Surface_s(face)
        uv_bounds = BRepTools.UVBounds_s(face)
        projector = GeomAPI_ProjectPointOnSurf()
        projector.Init(
            surface,
            float(uv_bounds[0]),
            float(uv_bounds[1]),
            float(uv_bounds[2]),
            float(uv_bounds[3]),
            float(projection_tolerance_m),
        )
        count = max(2, int(sample_count))
        points = TColgp_Array1OfPnt2d(1, count)
        parameters = TColStd_Array1OfReal(1, count)
        projection_distances: list[float] = []
        for index in range(count):
            fraction = index / (count - 1)
            parameter = float(edge_range[0]) + (
                float(edge_range[1]) - float(edge_range[0])
            ) * fraction
            point = curve3d.Value(parameter)
            projector.Perform(point)
            if not projector.IsDone() or projector.NbPoints() < 1:
                raise RuntimeError(f"surface projection failed at sample {index}")
            u_value, v_value = projector.LowerDistanceParameters()
            points.SetValue(index + 1, gp_Pnt2d(float(u_value), float(v_value)))
            parameters.SetValue(index + 1, parameter)
            projection_distances.append(float(projector.LowerDistance()))
        if mode == "interpolate":
            interpolator = Geom2dAPI_Interpolate(
                TColgp_HArray1OfPnt2d(points),
                TColStd_HArray1OfReal(parameters),
                False,
                float(interpolation_tolerance),
            )
            interpolator.Perform()
            if not interpolator.IsDone():
                raise RuntimeError("Geom2dAPI_Interpolate did not finish")
            pcurve = interpolator.Curve()
        else:
            approximator = Geom2dAPI_PointsToBSpline(
                points,
                parameters,
                3,
                8,
                GeomAbs_C2,
                float(interpolation_tolerance),
            )
            if not approximator.IsDone():
                raise RuntimeError("Geom2dAPI_PointsToBSpline did not finish")
            pcurve = approximator.Curve()
        return pcurve, {
            "sample_count": count,
            "max_projection_distance_m": (
                max(projection_distances) if projection_distances else None
            ),
            "mean_projection_distance_m": (
                sum(projection_distances) / len(projection_distances)
                if projection_distances
                else None
            ),
        }

    def _projected_pcurve_for_strategy(edge, face, strategy: str):
        edge_range = BRep_Tool.Range_s(edge)
        curve3d = BRep_Tool.Curve_s(edge, 0.0, 0.0)
        surface = BRep_Tool.Surface_s(face)
        if strategy == "geomprojlib_curve2d_update_edge_then_same_parameter":
            pcurve = GeomProjLib.Curve2d_s(
                curve3d,
                float(edge_range[0]),
                float(edge_range[1]),
                surface,
                float(projection_tolerance_m),
            )
            if pcurve is None:
                raise RuntimeError("GeomProjLib.Curve2d returned null")
            return pcurve, {
                "projection_method": "GeomProjLib.Curve2d",
                "sample_count": None,
                "max_projection_distance_m": None,
                "mean_projection_distance_m": None,
            }
        if strategy == "sampled_surface_project_interpolate_update_edge_then_same_parameter":
            pcurve, diagnostics = _sampled_projected_pcurve(
                edge,
                face,
                "interpolate",
            )
            return pcurve, {
                "projection_method": "GeomAPI_ProjectPointOnSurf+Geom2dAPI_Interpolate",
                **diagnostics,
            }
        if strategy == "sampled_surface_project_approx_update_edge_then_same_parameter":
            pcurve, diagnostics = _sampled_projected_pcurve(edge, face, "approx")
            return pcurve, {
                "projection_method": "GeomAPI_ProjectPointOnSurf+Geom2dAPI_PointsToBSpline",
                **diagnostics,
            }
        raise ValueError(f"unknown projected PCurve strategy: {strategy}")

    def _apply_strategy(face_index_map, edge_index_map, strategy: str) -> list[dict[str, Any]]:
        builder = BRep_Builder()
        operation_results: list[dict[str, Any]] = []
        for target in target_edges:
            edge_index = int(target["edge_index"])
            if edge_index < 1 or edge_index > edge_index_map.Size():
                operation_results.append(
                    {**target, "edge_found": False, "face_operations": []}
                )
                continue
            edge = TopoDS.Edge_s(edge_index_map.FindKey(edge_index))
            edge_range = BRep_Tool.Range_s(edge)
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
                            "called": False,
                            "projected_pcurve_built": False,
                            "error": "face_not_found",
                        }
                    )
                    continue
                face = TopoDS.Face_s(face_index_map.FindKey(face_index))
                try:
                    pcurve, diagnostics = _projected_pcurve_for_strategy(
                        edge,
                        face,
                        strategy,
                    )
                    endpoint_gate = _endpoint_orientation_gate(
                        edge=edge,
                        face=face,
                        pcurve=pcurve,
                        tolerance=edge_tolerance,
                    )
                    builder.UpdateEdge(edge, pcurve, face, edge_tolerance)
                    builder.Range(edge, face, float(edge_range[0]), float(edge_range[1]))
                    builder.UpdateVertex(
                        first_vertex,
                        float(edge_range[0]),
                        edge,
                        face,
                        edge_tolerance,
                    )
                    builder.UpdateVertex(
                        last_vertex,
                        float(edge_range[1]),
                        edge,
                        face,
                        edge_tolerance,
                    )
                    builder.SameParameter(edge, False)
                    builder.SameRange(edge, False)
                    BRepLib.SameRange_s(edge, float(projection_tolerance_m))
                    BRepLib.SameParameter_s(edge, float(projection_tolerance_m))
                    face_operations.append(
                        {
                            "face_id": face_index,
                            "called": True,
                            "projected_pcurve_built": True,
                            "projection_method": diagnostics.get("projection_method"),
                            "pcurve_type": _dynamic_type_name(pcurve),
                            "pcurve_first_parameter": float(pcurve.FirstParameter()),
                            "pcurve_last_parameter": float(pcurve.LastParameter()),
                            "max_projection_distance_m": diagnostics.get(
                                "max_projection_distance_m"
                            ),
                            "mean_projection_distance_m": diagnostics.get(
                                "mean_projection_distance_m"
                            ),
                            "sample_count": diagnostics.get("sample_count"),
                            "endpoint_orientation_gate": endpoint_gate,
                            "error": None,
                        }
                    )
                except Exception as exc:
                    face_operations.append(
                        {
                            "face_id": face_index,
                            "called": False,
                            "projected_pcurve_built": False,
                            "error": str(exc),
                        }
                    )
            operation_results.append(
                {
                    **target,
                    "edge_found": True,
                    "edge_tolerance": edge_tolerance,
                    "edge_range": [float(edge_range[0]), float(edge_range[1])],
                    "face_operations": face_operations,
                }
            )
        return operation_results

    try:
        _, baseline_face_map, baseline_edge_map = _load_shape()
        baseline_checks = _evaluate(baseline_face_map, baseline_edge_map)
        attempts: list[dict[str, Any]] = []
        for strategy in strategies:
            _, face_map, edge_map = _load_shape()
            operation_results = _apply_strategy(face_map, edge_map, strategy)
            checks = _evaluate(face_map, edge_map)
            attempts.append(
                {
                    "strategy": strategy,
                    "operation_results": operation_results,
                    "checks": checks,
                }
            )
    except Exception as exc:
        return {
            "runtime_status": "unavailable",
            "reason": "projected_pcurve_builder_exception",
            "error": str(exc),
            "baseline_checks": [],
            "strategy_attempts": [],
        }
    return {
        "runtime_status": "evaluated",
        "baseline_checks": baseline_checks,
        "strategy_attempts": attempts,
    }


def build_main_wing_station_seam_side_aware_projected_pcurve_builder_probe_report(
    *,
    pcurve_metadata_builder_probe_path: Path | None = None,
    strategies: list[str] | None = None,
    sample_count: int = 23,
    projection_tolerance_m: float = 1.0e-7,
    interpolation_tolerance: float = 1.0e-9,
    projected_pcurve_builder_runner: ProjectedPCurveBuilderRunner | None = None,
) -> MainWingStationSeamSideAwareProjectedPCurveBuilderProbeReport:
    probe_path = (
        _default_pcurve_metadata_builder_probe_path()
        if pcurve_metadata_builder_probe_path is None
        else pcurve_metadata_builder_probe_path
    )
    selected_strategies = strategies or DEFAULT_PROJECTED_PCURVE_BUILDER_STRATEGIES
    blockers: list[str] = []
    pcurve_payload = _load_json(
        probe_path,
        blockers,
        "pcurve_metadata_builder_probe",
    )
    step_path = _resolve_path(
        pcurve_payload.get("candidate_step_path")
        if isinstance(pcurve_payload, dict)
        else None
    )
    if step_path is None:
        blockers.append("side_aware_candidate_step_path_missing")
    elif not step_path.exists():
        blockers.append("side_aware_candidate_step_missing")
    target_edges = (
        _dict_list(pcurve_payload.get("target_edges", []))
        if isinstance(pcurve_payload, dict)
        else []
    )
    if not target_edges:
        blockers.append("side_aware_station_target_edges_missing")
    runner = (
        projected_pcurve_builder_runner
        or evaluate_side_aware_station_projected_pcurve_builder_strategies
    )
    runner_payload: dict[str, Any]
    if blockers or step_path is None:
        runner_payload = {
            "runtime_status": "blocked",
            "baseline_checks": [],
            "strategy_attempts": [],
        }
    else:
        runner_payload = runner(
            step_path=step_path,
            target_edges=target_edges,
            strategies=selected_strategies,
            sample_count=sample_count,
            projection_tolerance_m=projection_tolerance_m,
            interpolation_tolerance=interpolation_tolerance,
        )
    baseline_checks = _dict_list(runner_payload.get("baseline_checks", []))
    attempts = _dict_list(runner_payload.get("strategy_attempts", []))
    baseline_summary = _summary(baseline_checks)
    attempt_summary = _attempt_summary(
        baseline_summary=baseline_summary,
        attempts=attempts,
    )
    status = _status(
        blockers=blockers,
        runner_payload=runner_payload,
        attempt_summary=attempt_summary,
    )
    upstream_summary = _upstream_summary(pcurve_payload)
    return MainWingStationSeamSideAwareProjectedPCurveBuilderProbeReport(
        projected_builder_status=status,
        pcurve_metadata_builder_probe_path=str(probe_path),
        candidate_step_path=str(step_path) if step_path is not None else None,
        target_edges=target_edges,
        strategies=list(selected_strategies),
        sample_count=int(sample_count),
        projection_tolerance_m=float(projection_tolerance_m),
        interpolation_tolerance=float(interpolation_tolerance),
        api_semantics=_api_semantics(),
        upstream_pcurve_metadata_builder_summary=upstream_summary,
        baseline_checks=baseline_checks,
        baseline_summary=baseline_summary,
        strategy_attempts=attempts,
        strategy_attempt_summary=attempt_summary,
        engineering_findings=_engineering_findings(
            status=status,
            upstream_pcurve_metadata_builder_summary=upstream_summary,
            attempt_summary=attempt_summary,
        ),
        blocking_reasons=_blocking_reasons(status, blockers),
        next_actions=_next_actions(status),
        limitations=[
            "This probe edits topology metadata in memory only; it does not export a repaired STEP.",
            "A projected or sampled PCurve is not accepted unless the full ShapeAnalysis gate passes.",
            "SameParameter/SameRange flags are recorded as diagnostics only, not as pass criteria.",
        ],
    )


def write_main_wing_station_seam_side_aware_projected_pcurve_builder_probe_report(
    out_dir: Path,
    *,
    report: MainWingStationSeamSideAwareProjectedPCurveBuilderProbeReport | None = None,
    pcurve_metadata_builder_probe_path: Path | None = None,
    strategies: list[str] | None = None,
    sample_count: int = 23,
    projection_tolerance_m: float = 1.0e-7,
    interpolation_tolerance: float = 1.0e-9,
    projected_pcurve_builder_runner: ProjectedPCurveBuilderRunner | None = None,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_station_seam_side_aware_projected_pcurve_builder_probe_report(
            pcurve_metadata_builder_probe_path=pcurve_metadata_builder_probe_path,
            strategies=strategies,
            sample_count=sample_count,
            projection_tolerance_m=projection_tolerance_m,
            interpolation_tolerance=interpolation_tolerance,
            projected_pcurve_builder_runner=projected_pcurve_builder_runner,
        )
    json_path = (
        out_dir
        / "main_wing_station_seam_side_aware_projected_pcurve_builder_probe.v1.json"
    )
    markdown_path = (
        out_dir
        / "main_wing_station_seam_side_aware_projected_pcurve_builder_probe.v1.md"
    )
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_lines = [
        "# Main Wing Station Seam Side-Aware Projected PCurve Builder Probe v1",
        "",
        f"- status: `{report.projected_builder_status}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        f"- candidate_step_path: `{report.candidate_step_path}`",
        f"- target_edge_count: `{len(report.target_edges)}`",
        f"- strategies: `{', '.join(report.strategies)}`",
        f"- projected_pcurve_built_face_count: `{report.strategy_attempt_summary.get('projected_pcurve_built_face_count')}`",
        f"- endpoint_orientation_pass_face_count: `{report.strategy_attempt_summary.get('endpoint_orientation_pass_face_count')}`",
        f"- best_passed_face_count: `{report.strategy_attempt_summary.get('best_passed_face_count')}`",
        f"- max_projection_distance_m: `{report.strategy_attempt_summary.get('max_projection_distance_m')}`",
        "",
        "## Engineering Findings",
        "",
    ]
    markdown_lines.extend(f"- `{finding}`" for finding in report.engineering_findings)
    markdown_lines.extend(["", "## Blocking Reasons", ""])
    markdown_lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    markdown_lines.extend(["", "## Next Actions", ""])
    markdown_lines.extend(f"- `{action}`" for action in report.next_actions)
    markdown_lines.extend(["", "## Limitations", ""])
    markdown_lines.extend(f"- {item}" for item in report.limitations)
    markdown_path.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
