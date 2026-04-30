from __future__ import annotations

from collections.abc import Callable
import json
import math
from pathlib import Path
from typing import Any, Dict, Literal

from pydantic import BaseModel, Field


SideAwarePCurveResidualDiagnosticStatusType = Literal[
    "side_aware_station_pcurve_residuals_sampled_clean",
    "side_aware_station_pcurve_residuals_below_tolerance_but_shape_analysis_flags_fail",
    "side_aware_station_pcurve_sampled_residuals_exceed_tolerance",
    "side_aware_station_pcurve_residual_diagnostic_unavailable",
    "blocked",
]

ResidualSampler = Callable[..., dict[str, Any]]


class MainWingStationSeamSideAwarePCurveResidualDiagnosticReport(BaseModel):
    schema_version: Literal[
        "main_wing_station_seam_side_aware_pcurve_residual_diagnostic.v1"
    ] = "main_wing_station_seam_side_aware_pcurve_residual_diagnostic.v1"
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal[
        "report_only_side_aware_station_pcurve_residual_diagnostic"
    ] = "report_only_side_aware_station_pcurve_residual_diagnostic"
    production_default_changed: bool = False
    diagnostic_status: SideAwarePCurveResidualDiagnosticStatusType
    side_aware_brep_validation_probe_path: str
    candidate_step_path: str | None = None
    target_station_y_m: list[float] = Field(default_factory=list)
    sample_count: int = 11
    absolute_tolerance_m: float = 1.0e-12
    target_selection: dict[str, Any] = Field(default_factory=dict)
    residual_summary: dict[str, Any] = Field(default_factory=dict)
    edge_face_residuals: list[dict[str, Any]] = Field(default_factory=list)
    engineering_findings: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_side_aware_brep_validation_probe_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_side_aware_brep_validation_probe"
        / "main_wing_station_seam_side_aware_brep_validation_probe.v1.json"
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


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _float_list(values: Any) -> list[float]:
    if not isinstance(values, list):
        return []
    result: list[float] = []
    for value in values:
        converted = _as_float(value)
        if converted is not None and converted not in result:
            result.append(converted)
    return result


def _int_list(values: Any) -> list[int]:
    if not isinstance(values, list):
        return []
    result: list[int] = []
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            result.append(int(value))
    return result


def _edge_face_targets(brep_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(brep_payload, dict):
        return []
    targets: list[dict[str, Any]] = []
    for check in brep_payload.get("station_edge_checks", []):
        if not isinstance(check, dict):
            continue
        edge_index = check.get("candidate_step_edge_index")
        curve_tag = check.get("candidate_step_curve_tag")
        if not isinstance(edge_index, int) or isinstance(edge_index, bool):
            continue
        face_tags = _int_list(check.get("ancestor_face_ids")) or _int_list(
            check.get("owner_surface_tags")
        )
        for face_tag in face_tags:
            targets.append(
                {
                    "station_y_m": check.get("station_y_m"),
                    "candidate_step_curve_tag": curve_tag,
                    "candidate_step_edge_index": int(edge_index),
                    "candidate_step_face_tag": int(face_tag),
                    "source_shape_analysis": {
                        "pcurve_presence_complete": check.get(
                            "pcurve_presence_complete"
                        ),
                        "curve3d_with_pcurve_consistent": check.get(
                            "curve3d_with_pcurve_consistent"
                        ),
                        "same_parameter_by_face_ok": check.get(
                            "same_parameter_by_face_ok"
                        ),
                        "vertex_tolerance_by_face_ok": check.get(
                            "vertex_tolerance_by_face_ok"
                        ),
                        "pcurve_range_matches_edge_range": check.get(
                            "pcurve_range_matches_edge_range"
                        ),
                    },
                }
            )
    return targets


def _dynamic_type_name(shape: Any) -> str | None:
    try:
        return str(shape.DynamicType().Name())
    except Exception:
        return None


def _point_tuple(point: Any) -> tuple[float, float, float]:
    return (float(point.X()), float(point.Y()), float(point.Z()))


def _vertex_tolerance(edge: Any) -> tuple[float | None, float | None, float | None]:
    try:
        from OCP.BRep import BRep_Tool
        from OCP.TopExp import TopExp

        first = TopExp.FirstVertex_s(edge)
        last = TopExp.LastVertex_s(edge)
        first_tolerance = (
            None if first.IsNull() else float(BRep_Tool.Tolerance_s(first))
        )
        last_tolerance = None if last.IsNull() else float(BRep_Tool.Tolerance_s(last))
    except Exception:
        return None, None, None
    values = [
        value for value in (first_tolerance, last_tolerance) if value is not None
    ]
    return first_tolerance, last_tolerance, max(values) if values else None


def _sample_distances(
    *,
    edge: Any,
    face: Any,
    sample_count: int,
) -> dict[str, Any]:
    from OCP.BRep import BRep_Tool

    edge_range = BRep_Tool.Range_s(edge)
    face_range = BRep_Tool.Range_s(edge, face)
    curve3d = BRep_Tool.Curve_s(edge, 0.0, 0.0)
    pcurve = BRep_Tool.CurveOnSurface_s(edge, face, 0.0, 0.0)
    surface = BRep_Tool.Surface_s(face)
    count = max(2, int(sample_count))
    distances: list[float] = []
    for index in range(count):
        fraction = index / (count - 1)
        edge_parameter = float(edge_range[0]) + (
            float(edge_range[1]) - float(edge_range[0])
        ) * fraction
        pcurve_parameter = float(face_range[0]) + (
            float(face_range[1]) - float(face_range[0])
        ) * fraction
        point_3d = curve3d.Value(edge_parameter)
        uv = pcurve.Value(pcurve_parameter)
        point_surface = surface.Value(float(uv.X()), float(uv.Y()))
        distances.append(math.dist(_point_tuple(point_3d), _point_tuple(point_surface)))
    return {
        "curve3d_type": _dynamic_type_name(curve3d),
        "pcurve_type": _dynamic_type_name(pcurve),
        "edge_range": [float(edge_range[0]), float(edge_range[1])],
        "pcurve_edge_range": [float(face_range[0]), float(face_range[1])],
        "curve3d_first_parameter": float(curve3d.FirstParameter()),
        "curve3d_last_parameter": float(curve3d.LastParameter()),
        "pcurve_first_parameter": float(pcurve.FirstParameter()),
        "pcurve_last_parameter": float(pcurve.LastParameter()),
        "sample_count": count,
        "max_sample_distance_m": max(distances),
        "mean_sample_distance_m": sum(distances) / len(distances),
        "start_sample_distance_m": distances[0],
        "end_sample_distance_m": distances[-1],
    }


def sample_side_aware_station_pcurve_residuals(
    *,
    step_path: Path,
    edge_face_targets: list[dict[str, Any]],
    sample_count: int = 11,
) -> dict[str, Any]:
    try:
        from OCP.BRep import BRep_Tool
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.ShapeAnalysis import ShapeAnalysis_Edge
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
            "edge_face_residuals": [],
        }

    try:
        reader = STEPControl_Reader()
        status = reader.ReadFile(str(step_path))
        if status != IFSelect_RetDone:
            return {
                "runtime_status": "unavailable",
                "reason": "step_reader_failed",
                "reader_status": int(status),
                "edge_face_residuals": [],
            }
        reader.TransferRoots()
        shape = reader.OneShape()
        face_index_map = TopTools_IndexedMapOfShape()
        edge_index_map = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, TopAbs_FACE, face_index_map)
        TopExp.MapShapes_s(shape, TopAbs_EDGE, edge_index_map)
        analyzer = ShapeAnalysis_Edge()
        residuals: list[dict[str, Any]] = []
        for target in edge_face_targets:
            edge_index = int(target["candidate_step_edge_index"])
            face_tag = int(target["candidate_step_face_tag"])
            record = {
                "station_y_m": target.get("station_y_m"),
                "candidate_step_curve_tag": target.get("candidate_step_curve_tag"),
                "candidate_step_edge_index": edge_index,
                "candidate_step_face_tag": face_tag,
            }
            if edge_index < 1 or edge_index > edge_index_map.Size():
                residuals.append({**record, "edge_found": False})
                continue
            if face_tag < 1 or face_tag > face_index_map.Size():
                residuals.append({**record, "face_found": False})
                continue
            edge = TopoDS.Edge_s(edge_index_map.FindKey(edge_index))
            face = TopoDS.Face_s(face_index_map.FindKey(face_tag))
            pcurve_present = bool(analyzer.HasPCurve(edge, face))
            first_vertex_tolerance, last_vertex_tolerance, max_vertex_tolerance = (
                _vertex_tolerance(edge)
            )
            base = {
                **record,
                "edge_found": True,
                "face_found": True,
                "pcurve_present": pcurve_present,
                "shape_analysis_curve3d_with_pcurve": (
                    bool(analyzer.CheckCurve3dWithPCurve(edge, face))
                    if pcurve_present
                    else None
                ),
                "shape_analysis_same_parameter": bool(
                    analyzer.CheckSameParameter(edge, face, 0.0, 23)
                ),
                "shape_analysis_vertex_tolerance": bool(
                    analyzer.CheckVertexTolerance(edge, face, 0.0, 0.0)
                ),
                "edge_tolerance_m": float(BRep_Tool.Tolerance_s(edge)),
                "first_vertex_tolerance_m": first_vertex_tolerance,
                "last_vertex_tolerance_m": last_vertex_tolerance,
                "max_vertex_tolerance_m": max_vertex_tolerance,
            }
            if not pcurve_present:
                residuals.append(base)
                continue
            try:
                sampled = _sample_distances(
                    edge=edge,
                    face=face,
                    sample_count=sample_count,
                )
            except Exception as exc:
                residuals.append(
                    {
                        **base,
                        "sample_error": str(exc),
                    }
                )
                continue
            edge_tolerance = float(base["edge_tolerance_m"])
            max_distance = float(sampled["max_sample_distance_m"])
            residuals.append(
                {
                    **base,
                    **sampled,
                    "max_sample_distance_over_edge_tolerance": (
                        None
                        if edge_tolerance <= 0.0
                        else max_distance / edge_tolerance
                    ),
                }
            )
    except Exception as exc:
        return {
            "runtime_status": "unavailable",
            "reason": "station_pcurve_residual_sampling_failed",
            "error": str(exc),
            "edge_face_residuals": [],
        }
    return {
        "runtime_status": "evaluated",
        "edge_face_residuals": residuals,
    }


def _shape_analysis_flags_fail(residual: dict[str, Any]) -> bool:
    return any(
        residual.get(key) is False
        for key in (
            "shape_analysis_curve3d_with_pcurve",
            "shape_analysis_same_parameter",
            "shape_analysis_vertex_tolerance",
        )
    )


def _effective_edge_tolerance(
    residual: dict[str, Any],
    absolute_tolerance_m: float,
) -> float:
    edge_tolerance = _as_float(residual.get("edge_tolerance_m")) or 0.0
    return max(edge_tolerance, float(absolute_tolerance_m))


def _residual_exceeds_tolerance(
    residual: dict[str, Any],
    absolute_tolerance_m: float,
) -> bool:
    distance = _as_float(residual.get("max_sample_distance_m"))
    if distance is None:
        return False
    return distance > _effective_edge_tolerance(residual, absolute_tolerance_m)


def _pcurve_domain_is_unbounded(residual: dict[str, Any]) -> bool:
    first = _as_float(residual.get("pcurve_first_parameter"))
    last = _as_float(residual.get("pcurve_last_parameter"))
    return (
        first is not None
        and last is not None
        and (abs(first) >= 1.0e50 or abs(last) >= 1.0e50)
    )


def _residual_summary(
    residuals: list[dict[str, Any]],
    *,
    absolute_tolerance_m: float,
) -> dict[str, Any]:
    distances = [
        float(distance)
        for residual in residuals
        if (distance := _as_float(residual.get("max_sample_distance_m"))) is not None
    ]
    ratios = [
        float(ratio)
        for residual in residuals
        if (ratio := _as_float(residual.get("max_sample_distance_over_edge_tolerance")))
        is not None
    ]
    sampled = [residual for residual in residuals if "max_sample_distance_m" in residual]
    return {
        "edge_face_residual_count": len(residuals),
        "sampled_edge_face_count": len(sampled),
        "shape_analysis_flag_failure_count": sum(
            _shape_analysis_flags_fail(residual) for residual in residuals
        ),
        "pcurve_missing_count": sum(
            residual.get("pcurve_present") is False for residual in residuals
        ),
        "sample_error_count": sum("sample_error" in residual for residual in residuals),
        "residual_exceeds_edge_tolerance_count": sum(
            _residual_exceeds_tolerance(
                residual,
                absolute_tolerance_m,
            )
            for residual in residuals
        ),
        "unbounded_pcurve_domain_count": sum(
            _pcurve_domain_is_unbounded(residual) for residual in residuals
        ),
        "max_sample_distance_m": max(distances) if distances else None,
        "max_sample_distance_over_edge_tolerance": max(ratios) if ratios else None,
    }


def _status(
    *,
    blockers: list[str],
    sampler_payload: dict[str, Any],
    summary: dict[str, Any],
) -> SideAwarePCurveResidualDiagnosticStatusType:
    if blockers:
        return "blocked"
    if sampler_payload.get("runtime_status") != "evaluated":
        return "side_aware_station_pcurve_residual_diagnostic_unavailable"
    if int(summary.get("residual_exceeds_edge_tolerance_count") or 0) > 0:
        return "side_aware_station_pcurve_sampled_residuals_exceed_tolerance"
    if int(summary.get("shape_analysis_flag_failure_count") or 0) > 0:
        return (
            "side_aware_station_pcurve_residuals_below_tolerance_but_shape_analysis_flags_fail"
        )
    return "side_aware_station_pcurve_residuals_sampled_clean"


def _engineering_findings(
    *,
    status: SideAwarePCurveResidualDiagnosticStatusType,
    target_selection: dict[str, Any],
    summary: dict[str, Any],
) -> list[str]:
    if status == "blocked":
        return ["side_aware_pcurve_residual_diagnostic_blocked"]
    if status == "side_aware_station_pcurve_residual_diagnostic_unavailable":
        return ["side_aware_pcurve_residual_diagnostic_runtime_unavailable"]
    findings = ["side_aware_pcurve_residual_diagnostic_captured"]
    if target_selection.get("source_fixture_tags_replayed") is False:
        findings.append("source_fixture_curve_surface_tags_not_replayed")
    if int(summary.get("sampled_edge_face_count") or 0) > 0:
        findings.append("station_pcurve_residuals_sampled_on_candidate_step")
    if int(summary.get("residual_exceeds_edge_tolerance_count") or 0) == 0:
        findings.append("station_pcurve_sampled_geometric_residuals_within_edge_tolerance")
    else:
        findings.append("station_pcurve_sampled_geometric_residuals_exceed_edge_tolerance")
    if int(summary.get("shape_analysis_flag_failure_count") or 0) > 0:
        findings.append("shape_analysis_flags_fail_despite_low_sampled_residual")
    if int(summary.get("unbounded_pcurve_domain_count") or 0) > 0:
        findings.append("unbounded_line_pcurve_parameter_domain_observed")
    findings.append("side_aware_candidate_still_not_mesh_ready")
    return findings


def _blocking_reasons(
    *,
    status: SideAwarePCurveResidualDiagnosticStatusType,
    blockers: list[str],
) -> list[str]:
    reasons = list(blockers)
    if status == "side_aware_station_pcurve_sampled_residuals_exceed_tolerance":
        reasons.append("side_aware_station_pcurve_geometric_residual_exceeds_tolerance")
    if (
        status
        == "side_aware_station_pcurve_residuals_below_tolerance_but_shape_analysis_flags_fail"
    ):
        reasons.append("side_aware_station_shape_analysis_flags_still_block_mesh_handoff")
    if status == "side_aware_station_pcurve_residual_diagnostic_unavailable":
        reasons.append("side_aware_station_pcurve_residual_sampling_unavailable")
    if status == "blocked" and not reasons:
        reasons.append("side_aware_pcurve_residual_diagnostic_blocked")
    reasons.append("side_aware_candidate_mesh_handoff_not_run")
    return reasons


def _next_actions(status: SideAwarePCurveResidualDiagnosticStatusType) -> list[str]:
    if (
        status
        == "side_aware_station_pcurve_residuals_below_tolerance_but_shape_analysis_flags_fail"
    ):
        return [
            "test_side_aware_same_parameter_metadata_repair_before_mesh_handoff",
            "correlate_shape_analysis_flags_with_gmsh_volume_recovery_before_solver_budget",
            "avoid_solver_iteration_budget_until_station_metadata_gate_is_clean",
        ]
    if status == "side_aware_station_pcurve_sampled_residuals_exceed_tolerance":
        return [
            "repair_side_aware_candidate_station_pcurve_geometry_before_metadata_repair",
            "do_not_advance_to_mesh_handoff_until_sampled_residuals_are_within_tolerance",
        ]
    if status == "side_aware_station_pcurve_residuals_sampled_clean":
        return [
            "run_bounded_same_parameter_metadata_repair_probe",
            "rerun_side_aware_brep_validation_after_metadata_repair",
        ]
    if status == "side_aware_station_pcurve_residual_diagnostic_unavailable":
        return ["restore_ocp_runtime_before_station_pcurve_residual_claims"]
    return ["restore_side_aware_pcurve_residual_diagnostic_inputs"]


def build_main_wing_station_seam_side_aware_pcurve_residual_diagnostic_report(
    *,
    side_aware_brep_validation_probe_path: Path | None = None,
    candidate_step_path: Path | None = None,
    sample_count: int = 11,
    absolute_tolerance_m: float = 1.0e-12,
    residual_sampler: ResidualSampler | None = None,
) -> MainWingStationSeamSideAwarePCurveResidualDiagnosticReport:
    brep_path = (
        _default_side_aware_brep_validation_probe_path()
        if side_aware_brep_validation_probe_path is None
        else side_aware_brep_validation_probe_path
    )
    blockers: list[str] = []
    brep_payload = _load_json(brep_path, blockers, "side_aware_brep_validation_probe")
    step_path = candidate_step_path or _resolve_path(
        brep_payload.get("candidate_step_path") if isinstance(brep_payload, dict) else None
    )
    if step_path is None:
        blockers.append("side_aware_candidate_step_path_missing")
    elif not step_path.exists():
        blockers.append("side_aware_candidate_step_missing")
    targets = _edge_face_targets(brep_payload)
    if not targets:
        blockers.append("side_aware_station_edge_face_targets_missing")
    target_selection = (
        brep_payload.get("target_selection", {})
        if isinstance(brep_payload, dict)
        else {}
    )
    target_selection = target_selection if isinstance(target_selection, dict) else {}
    target_station_y_m = _float_list(
        brep_payload.get("target_station_y_m") if isinstance(brep_payload, dict) else []
    )

    sampler_payload: dict[str, Any] = {}
    if not blockers and step_path is not None:
        sampler = residual_sampler or sample_side_aware_station_pcurve_residuals
        sampler_payload = sampler(
            step_path=step_path,
            edge_face_targets=targets,
            sample_count=sample_count,
        )
    residuals = [
        residual
        for residual in sampler_payload.get("edge_face_residuals", [])
        if isinstance(residual, dict)
    ]
    summary = _residual_summary(
        residuals,
        absolute_tolerance_m=absolute_tolerance_m,
    )
    status = _status(
        blockers=blockers,
        sampler_payload=sampler_payload,
        summary=summary,
    )
    return MainWingStationSeamSideAwarePCurveResidualDiagnosticReport(
        diagnostic_status=status,
        side_aware_brep_validation_probe_path=str(brep_path),
        candidate_step_path=str(step_path) if step_path is not None else None,
        target_station_y_m=target_station_y_m,
        sample_count=max(2, int(sample_count)),
        absolute_tolerance_m=float(absolute_tolerance_m),
        target_selection=target_selection,
        residual_summary=summary,
        edge_face_residuals=residuals,
        engineering_findings=_engineering_findings(
            status=status,
            target_selection=target_selection,
            summary=summary,
        ),
        blocking_reasons=_blocking_reasons(status=status, blockers=blockers),
        next_actions=_next_actions(status),
        limitations=[
            "This diagnostic samples existing side-aware candidate STEP PCurves; it does not change production defaults.",
            "Low sampled residual is diagnostic evidence only; it does not override failed ShapeAnalysis/SameParameter route gates.",
            "A sampled-clean PCurve residual report is not a CFD-ready or mesh-ready claim until BRep validation and mesh handoff pass.",
            "It does not run Gmsh volume meshing, SU2_CFD, CL acceptance, or convergence checks.",
            "Engineering acceptance still requires CL >= 1 under the HPA 6.5 m/s flow condition when solver evidence is evaluated.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_markdown(
    report: MainWingStationSeamSideAwarePCurveResidualDiagnosticReport,
) -> str:
    lines = [
        "# Main Wing Station Seam Side-Aware PCurve Residual Diagnostic v1",
        "",
        "This report samples 3D edge curves against their PCurves on owner faces for the side-aware candidate STEP.",
        "",
        f"- diagnostic_status: `{report.diagnostic_status}`",
        f"- side_aware_brep_validation_probe_path: `{report.side_aware_brep_validation_probe_path}`",
        f"- candidate_step_path: `{report.candidate_step_path}`",
        f"- target_station_y_m: `{_fmt(report.target_station_y_m)}`",
        f"- sample_count: `{report.sample_count}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Residual Summary",
        "",
    ]
    for key, value in report.residual_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Edge Face Residuals", ""])
    if report.edge_face_residuals:
        lines.extend(f"- `{_fmt(item)}`" for item in report.edge_face_residuals)
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


def write_main_wing_station_seam_side_aware_pcurve_residual_diagnostic_report(
    out_dir: Path,
    *,
    report: MainWingStationSeamSideAwarePCurveResidualDiagnosticReport | None = None,
    side_aware_brep_validation_probe_path: Path | None = None,
    candidate_step_path: Path | None = None,
    sample_count: int = 11,
    absolute_tolerance_m: float = 1.0e-12,
    residual_sampler: ResidualSampler | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_station_seam_side_aware_pcurve_residual_diagnostic_report(
            side_aware_brep_validation_probe_path=side_aware_brep_validation_probe_path,
            candidate_step_path=candidate_step_path,
            sample_count=sample_count,
            absolute_tolerance_m=absolute_tolerance_m,
            residual_sampler=residual_sampler,
        )
    json_path = (
        out_dir
        / "main_wing_station_seam_side_aware_pcurve_residual_diagnostic.v1.json"
    )
    markdown_path = (
        out_dir / "main_wing_station_seam_side_aware_pcurve_residual_diagnostic.v1.md"
    )
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
