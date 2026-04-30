from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


HotspotStatusType = Literal[
    "mesh_quality_hotspots_localized",
    "mesh_quality_clean",
    "blocked",
]


class MainWingMeshQualityHotspotAuditReport(BaseModel):
    schema_version: Literal["main_wing_mesh_quality_hotspot_audit.v1"] = (
        "main_wing_mesh_quality_hotspot_audit.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_existing_mesh_quality_artifacts"] = (
        "report_only_existing_mesh_quality_artifacts"
    )
    production_default_changed: bool = False
    hotspot_status: HotspotStatusType
    mesh_handoff_report_path: str
    mesh_metadata_path: str
    hotspot_patch_report_path: str
    surface_patch_diagnostics_path: str
    gmsh_defect_entity_trace_path: str
    quality_summary: Dict[str, Any] = Field(default_factory=dict)
    worst_tet_sample_partition: Dict[str, Any] = Field(default_factory=dict)
    hotspot_surface_summaries: List[Dict[str, Any]] = Field(default_factory=list)
    station_seam_overlap_observed: Dict[str, Any] = Field(default_factory=dict)
    engineering_findings: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_mesh_handoff_report_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )


def _default_mesh_artifact_dir() -> Path:
    return (
        _default_report_root()
        / "main_wing_real_mesh_handoff_probe"
        / "artifacts"
        / "real_mesh_probe"
        / "artifacts"
        / "mesh"
    )


def _default_mesh_metadata_path() -> Path:
    return _default_mesh_artifact_dir() / "mesh_metadata.json"


def _default_hotspot_patch_report_path() -> Path:
    return _default_mesh_artifact_dir() / "hotspot_patch_report.json"


def _default_surface_patch_diagnostics_path() -> Path:
    return _default_mesh_artifact_dir() / "surface_patch_diagnostics.json"


def _default_gmsh_defect_entity_trace_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_gmsh_defect_entity_trace"
        / "main_wing_gmsh_defect_entity_trace.v1.json"
    )


def _load_json(
    path: Path,
    *,
    blockers: list[str],
    label: str,
    required: bool,
) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if required:
            blockers.append(f"{label}_missing")
        return None
    except json.JSONDecodeError as exc:
        if required:
            blockers.append(f"{label}_invalid_json:{exc}")
        return None
    return payload if isinstance(payload, dict) else {}


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _quality_metrics(mesh_metadata: dict[str, Any] | None) -> dict[str, Any]:
    quality = mesh_metadata.get("quality_metrics", {}) if isinstance(mesh_metadata, dict) else {}
    return quality if isinstance(quality, dict) else {}


def _worst_tets(quality_metrics: dict[str, Any]) -> list[dict[str, Any]]:
    entries = quality_metrics.get("worst_20_tets", [])
    return [entry for entry in entries if isinstance(entry, dict)]


def _nearest_surface(entry: dict[str, Any]) -> dict[str, Any]:
    surface = entry.get("nearest_surface", {})
    if isinstance(surface, dict):
        return surface
    return {}


def _nearest_surface_tag(entry: dict[str, Any]) -> int | None:
    surface = _nearest_surface(entry)
    tag = surface.get("surface_tag", entry.get("nearest_surface_id"))
    return _as_int(tag)


def _nearest_physical_name(entry: dict[str, Any]) -> str:
    name = _nearest_surface(entry).get("physical_name")
    if isinstance(name, str) and name:
        return name
    return "unknown"


def _quality_summary(
    *,
    mesh_handoff_report: dict[str, Any] | None,
    quality_metrics: dict[str, Any],
) -> dict[str, Any]:
    worst_tets = _worst_tets(quality_metrics)
    ill_shaped_tet_count = _as_int(quality_metrics.get("ill_shaped_tet_count"))
    worst_count = len(worst_tets)
    summary: dict[str, Any] = {
        "mesh_quality_status": (
            None
            if mesh_handoff_report is None
            else mesh_handoff_report.get("mesh_quality_status")
        ),
        "mesh_quality_advisory_flags": (
            []
            if mesh_handoff_report is None
            else mesh_handoff_report.get("mesh_quality_advisory_flags", [])
        ),
        "tetrahedron_count": _as_int(quality_metrics.get("tetrahedron_count")),
        "ill_shaped_tet_count": ill_shaped_tet_count,
        "min_gamma": _as_float(quality_metrics.get("min_gamma")),
        "min_sicn": _as_float(quality_metrics.get("min_sicn")),
        "min_sige": _as_float(quality_metrics.get("min_sige")),
        "min_volume": _as_float(quality_metrics.get("min_volume")),
        "worst_tet_sample_count": worst_count,
        "worst_tet_sample_covers_all_ill_shaped": (
            None
            if ill_shaped_tet_count is None
            else worst_count >= ill_shaped_tet_count
        ),
    }
    gamma_percentiles = quality_metrics.get("gamma_percentiles")
    if isinstance(gamma_percentiles, dict):
        summary["gamma_percentiles"] = gamma_percentiles
    return summary


def _sample_partition(worst_tets: list[dict[str, Any]]) -> dict[str, Any]:
    physical_counts = Counter(_nearest_physical_name(entry) for entry in worst_tets)
    surface_counts = Counter(
        tag for entry in worst_tets if (tag := _nearest_surface_tag(entry)) is not None
    )
    return {
        "sample_count": len(worst_tets),
        "by_nearest_physical_name": dict(sorted(physical_counts.items())),
        "by_nearest_surface_tag": {
            int(tag): count for tag, count in sorted(surface_counts.items())
        },
        "farfield_sample_count": int(physical_counts.get("farfield", 0)),
        "main_wing_sample_count": int(physical_counts.get("main_wing", 0)),
        "unknown_sample_count": int(physical_counts.get("unknown", 0)),
    }


def _surface_records(
    surface_patch_diagnostics: dict[str, Any] | None,
) -> dict[int, dict[str, Any]]:
    records: dict[int, dict[str, Any]] = {}
    payload = (
        surface_patch_diagnostics.get("surface_records", [])
        if isinstance(surface_patch_diagnostics, dict)
        else []
    )
    for record in payload:
        if isinstance(record, dict) and isinstance(record.get("tag"), int):
            records[int(record["tag"])] = record
    return records


def _surface_reports(
    hotspot_patch_report: dict[str, Any] | None,
) -> dict[int, dict[str, Any]]:
    reports: dict[int, dict[str, Any]] = {}
    payload = (
        hotspot_patch_report.get("surface_reports", [])
        if isinstance(hotspot_patch_report, dict)
        else []
    )
    for report in payload:
        tag = _as_int(report.get("surface_id")) if isinstance(report, dict) else None
        if tag is not None:
            reports[tag] = report
    return reports


def _physical_counts_for_surface(
    entries: list[dict[str, Any]],
) -> dict[str, int]:
    return dict(sorted(Counter(_nearest_physical_name(entry) for entry in entries).items()))


def _majority_physical_name(entries: list[dict[str, Any]]) -> str | None:
    counts = Counter(_nearest_physical_name(entry) for entry in entries)
    if not counts:
        return None
    return str(counts.most_common(1)[0][0])


def _range(values: list[float]) -> list[float] | None:
    if not values:
        return None
    return [min(values), max(values)]


def _entry_edge_ratio(entry: dict[str, Any]) -> float | None:
    min_edge = _as_float(
        entry.get("tetra_edge_length_min", entry.get("local_tetra_edge_length_min"))
    )
    max_edge = _as_float(
        entry.get("tetra_edge_length_max", entry.get("local_tetra_edge_length_max"))
    )
    if min_edge is None or max_edge is None or min_edge <= 0.0:
        return None
    return max_edge / min_edge


def _hotspot_surface_summaries(
    *,
    worst_tets: list[dict[str, Any]],
    hotspot_patch_report: dict[str, Any] | None,
    surface_patch_diagnostics: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    surface_entries: dict[int, list[dict[str, Any]]] = {}
    for entry in worst_tets:
        tag = _nearest_surface_tag(entry)
        if tag is not None:
            surface_entries.setdefault(tag, []).append(entry)
    reports = _surface_reports(hotspot_patch_report)
    records = _surface_records(surface_patch_diagnostics)
    surface_tags = sorted(set(surface_entries) | set(reports))
    summaries: list[dict[str, Any]] = []
    for tag in surface_tags:
        entries = surface_entries.get(tag, [])
        report = reports.get(tag, {})
        record = records.get(tag, {})
        worst_near = (
            report.get("worst_tets_near_this_surface", {})
            if isinstance(report, dict)
            else {}
        )
        if not isinstance(worst_near, dict):
            worst_near = {}
        physical_name = _majority_physical_name(entries)
        surface_role = (
            record.get("surface_role")
            or report.get("surface_role")
            or physical_name
            or "unknown"
        )
        family_hints = record.get("family_hints") or report.get("family_hints") or []
        gammas = [
            value
            for entry in entries
            if (value := _as_float(entry.get("gamma"))) is not None
        ]
        edge_ratios = [
            value for entry in entries if (value := _entry_edge_ratio(entry)) is not None
        ]
        y_values = [
            float(entry["barycenter"][1])
            for entry in entries
            if isinstance(entry.get("barycenter"), list)
            and len(entry["barycenter"]) >= 2
            and isinstance(entry["barycenter"][1], (int, float))
        ]
        summaries.append(
            {
                "surface_tag": tag,
                "surface_role": surface_role,
                "nearest_physical_name_counts": _physical_counts_for_surface(entries),
                "sample_worst_tet_count": len(entries),
                "sample_element_ids": [
                    int(entry["element_id"])
                    for entry in entries
                    if isinstance(entry.get("element_id"), int)
                ],
                "sample_min_gamma": min(gammas) if gammas else None,
                "sample_max_edge_ratio": max(edge_ratios) if edge_ratios else None,
                "sample_barycenter_y_range_m": _range(y_values),
                "hotspot_patch_entry_count": _as_int(worst_near.get("count")),
                "hotspot_patch_min_gamma": _as_float(worst_near.get("min_gamma")),
                "bbox": record.get("bbox") or report.get("surface_bbox"),
                "curve_tags": record.get("curve_tags", []),
                "short_curve_tags": record.get("short_curve_tags", []),
                "family_hints": family_hints if isinstance(family_hints, list) else [],
                "suspect_score": record.get("suspect_score"),
            }
        )
    return sorted(
        summaries,
        key=lambda item: (
            math.inf
            if item.get("sample_min_gamma") is None
            else float(item["sample_min_gamma"]),
            int(item["surface_tag"]),
        ),
    )


def _station_overlap(
    *,
    hotspot_surface_summaries: list[dict[str, Any]],
    gmsh_defect_entity_trace: dict[str, Any] | None,
) -> dict[str, Any]:
    trace_summary = (
        gmsh_defect_entity_trace.get("trace_summary", {})
        if isinstance(gmsh_defect_entity_trace, dict)
        else {}
    )
    if not isinstance(trace_summary, dict):
        trace_summary = {}
    traced_surface_tags = sorted(
        {
            int(tag)
            for tag in trace_summary.get("involved_surface_entity_tags", [])
            if isinstance(tag, int)
        }
    )
    candidate_curve_tags = sorted(
        {
            int(tag)
            for tag in trace_summary.get("candidate_curve_tags", [])
            if isinstance(tag, int)
        }
    )
    main_wing_surface_tags = sorted(
        {
            int(summary["surface_tag"])
            for summary in hotspot_surface_summaries
            if (
                summary.get("surface_role") in {"aircraft", "main_wing"}
                or "main_wing"
                in summary.get("nearest_physical_name_counts", {})
            )
        }
    )
    overlap_tags = sorted(set(main_wing_surface_tags).intersection(traced_surface_tags))
    overlap_count = sum(
        int(summary.get("sample_worst_tet_count", 0) or 0)
        for summary in hotspot_surface_summaries
        if summary.get("surface_tag") in overlap_tags
    )
    return {
        "trace_status": (
            None
            if gmsh_defect_entity_trace is None
            else gmsh_defect_entity_trace.get("trace_status")
        ),
        "traced_surface_entity_tags": traced_surface_tags,
        "candidate_curve_tags": candidate_curve_tags,
        "main_wing_hotspot_surface_tags": main_wing_surface_tags,
        "overlap_surface_tags": overlap_tags,
        "overlap_worst_tet_sample_count": overlap_count,
    }


def _status(
    *,
    blockers: list[str],
    quality_summary: dict[str, Any],
) -> HotspotStatusType:
    if blockers:
        return "blocked"
    flags = quality_summary.get("mesh_quality_advisory_flags", [])
    ill_shaped_count = quality_summary.get("ill_shaped_tet_count")
    min_gamma = quality_summary.get("min_gamma")
    if (
        not flags
        and isinstance(ill_shaped_count, int)
        and ill_shaped_count == 0
        and (min_gamma is None or float(min_gamma) >= 1.0e-4)
    ):
        return "mesh_quality_clean"
    return "mesh_quality_hotspots_localized"


def _engineering_findings(
    *,
    status: HotspotStatusType,
    quality_summary: dict[str, Any],
    partition: dict[str, Any],
    surface_summaries: list[dict[str, Any]],
    station_overlap: dict[str, Any],
) -> list[str]:
    if status == "blocked":
        return ["mesh_quality_hotspot_audit_blocked"]
    if status == "mesh_quality_clean":
        return ["mesh_quality_clean_in_existing_artifacts"]
    findings: list[str] = []
    findings.append("mesh_quality_warning_present")
    if int(quality_summary.get("ill_shaped_tet_count", 0) or 0) > 0:
        findings.append("gmsh_ill_shaped_tets_present")
    min_gamma = quality_summary.get("min_gamma")
    if isinstance(min_gamma, (int, float)) and float(min_gamma) < 1.0e-4:
        findings.append("gmsh_min_gamma_below_1e_minus_4")
    if quality_summary.get("worst_tet_sample_covers_all_ill_shaped") is False:
        findings.append("worst_tet_sample_incomplete_for_all_ill_shaped_tets")
    if int(partition.get("farfield_sample_count", 0) or 0) > int(
        partition.get("main_wing_sample_count", 0) or 0
    ):
        findings.append("worst_tet_sample_mostly_farfield")
    if int(partition.get("main_wing_sample_count", 0) or 0) > 0:
        findings.append("main_wing_near_surface_quality_hotspots_present")
    if station_overlap.get("overlap_surface_tags"):
        findings.append("main_wing_quality_hotspot_overlaps_station_seam_trace")
    if any(
        "short_curve_candidate" in summary.get("family_hints", [])
        for summary in surface_summaries
        if summary.get("surface_role") in {"aircraft", "main_wing"}
    ):
        findings.append("main_wing_hotspot_surfaces_include_short_curve_strips")
    return list(dict.fromkeys(findings))


def _next_actions(
    *,
    status: HotspotStatusType,
    partition: dict[str, Any],
    station_overlap: dict[str, Any],
) -> list[str]:
    if status == "blocked":
        return ["restore_main_wing_mesh_quality_artifacts_before_hotspot_audit"]
    if status == "mesh_quality_clean":
        return ["continue_with_source_backed_solver_budget_after_geometry_audit"]
    actions: list[str] = []
    if station_overlap.get("overlap_surface_tags"):
        actions.append("repair_station_seam_export_before_solver_iteration_budget")
    main_wing_tags = station_overlap.get("main_wing_hotspot_surface_tags", [])
    if main_wing_tags:
        joined = "_".join(str(tag) for tag in main_wing_tags)
        actions.append(
            f"inspect_main_wing_hotspot_surfaces_{joined}_after_station_pcurve_fix"
        )
    if int(partition.get("farfield_sample_count", 0) or 0) > int(
        partition.get("main_wing_sample_count", 0) or 0
    ):
        actions.append("separate_farfield_sliver_cleanup_from_lift_gap_root_cause")
    actions.append("avoid_more_solver_iterations_until_geometry_and_mesh_gates_are_clean")
    return list(dict.fromkeys(actions))


def build_main_wing_mesh_quality_hotspot_audit_report(
    *,
    mesh_handoff_report_path: Path | None = None,
    mesh_metadata_path: Path | None = None,
    hotspot_patch_report_path: Path | None = None,
    surface_patch_diagnostics_path: Path | None = None,
    gmsh_defect_entity_trace_path: Path | None = None,
) -> MainWingMeshQualityHotspotAuditReport:
    mesh_handoff_path = (
        _default_mesh_handoff_report_path()
        if mesh_handoff_report_path is None
        else mesh_handoff_report_path
    )
    mesh_metadata = (
        _default_mesh_metadata_path()
        if mesh_metadata_path is None
        else mesh_metadata_path
    )
    hotspot_patch = (
        _default_hotspot_patch_report_path()
        if hotspot_patch_report_path is None
        else hotspot_patch_report_path
    )
    surface_patch = (
        _default_surface_patch_diagnostics_path()
        if surface_patch_diagnostics_path is None
        else surface_patch_diagnostics_path
    )
    defect_trace_path = (
        _default_gmsh_defect_entity_trace_path()
        if gmsh_defect_entity_trace_path is None
        else gmsh_defect_entity_trace_path
    )
    blockers: list[str] = []
    mesh_handoff_report = _load_json(
        mesh_handoff_path,
        blockers=blockers,
        label="mesh_handoff_report",
        required=False,
    )
    mesh_metadata_report = _load_json(
        mesh_metadata,
        blockers=blockers,
        label="mesh_metadata",
        required=True,
    )
    hotspot_patch_report = _load_json(
        hotspot_patch,
        blockers=blockers,
        label="hotspot_patch_report",
        required=False,
    )
    surface_patch_diagnostics = _load_json(
        surface_patch,
        blockers=blockers,
        label="surface_patch_diagnostics",
        required=False,
    )
    gmsh_defect_entity_trace = _load_json(
        defect_trace_path,
        blockers=blockers,
        label="gmsh_defect_entity_trace",
        required=False,
    )
    quality = _quality_metrics(mesh_metadata_report)
    if not quality and "mesh_metadata_missing" not in blockers:
        blockers.append("mesh_quality_metrics_missing")
    worst_tets = _worst_tets(quality)
    quality_summary = _quality_summary(
        mesh_handoff_report=mesh_handoff_report,
        quality_metrics=quality,
    )
    partition = _sample_partition(worst_tets)
    surface_summaries = _hotspot_surface_summaries(
        worst_tets=worst_tets,
        hotspot_patch_report=hotspot_patch_report,
        surface_patch_diagnostics=surface_patch_diagnostics,
    )
    station_overlap = _station_overlap(
        hotspot_surface_summaries=surface_summaries,
        gmsh_defect_entity_trace=gmsh_defect_entity_trace,
    )
    status = _status(blockers=blockers, quality_summary=quality_summary)
    findings = _engineering_findings(
        status=status,
        quality_summary=quality_summary,
        partition=partition,
        surface_summaries=surface_summaries,
        station_overlap=station_overlap,
    )
    return MainWingMeshQualityHotspotAuditReport(
        hotspot_status=status,
        mesh_handoff_report_path=str(mesh_handoff_path),
        mesh_metadata_path=str(mesh_metadata),
        hotspot_patch_report_path=str(hotspot_patch),
        surface_patch_diagnostics_path=str(surface_patch),
        gmsh_defect_entity_trace_path=str(defect_trace_path),
        quality_summary=quality_summary,
        worst_tet_sample_partition=partition,
        hotspot_surface_summaries=surface_summaries,
        station_seam_overlap_observed=station_overlap,
        engineering_findings=findings,
        blocking_reasons=list(dict.fromkeys(blockers)),
        next_actions=_next_actions(
            status=status,
            partition=partition,
            station_overlap=station_overlap,
        ),
        limitations=[
            "This audit reads existing mesh-quality artifacts only; it does not remesh or repair topology.",
            "The worst-tet list is a bounded sample, not a complete localization of every ill-shaped tet.",
            "Quality hotspots are route-risk evidence, not SU2 convergence evidence.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _render_markdown(report: MainWingMeshQualityHotspotAuditReport) -> str:
    lines = [
        "# Main Wing Mesh Quality Hotspot Audit v1",
        "",
        "This report reads existing mesh-quality artifacts only; it does not run Gmsh or SU2.",
        "",
        f"- hotspot_status: `{report.hotspot_status}`",
        f"- mesh_handoff_report_path: `{report.mesh_handoff_report_path}`",
        f"- mesh_metadata_path: `{report.mesh_metadata_path}`",
        f"- hotspot_patch_report_path: `{report.hotspot_patch_report_path}`",
        f"- surface_patch_diagnostics_path: `{report.surface_patch_diagnostics_path}`",
        f"- gmsh_defect_entity_trace_path: `{report.gmsh_defect_entity_trace_path}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Quality Summary",
        "",
    ]
    for key, value in report.quality_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Worst-Tet Sample Partition", ""])
    for key, value in report.worst_tet_sample_partition.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Station-Seam Overlap", ""])
    for key, value in report.station_seam_overlap_observed.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Hotspot Surface Summaries", ""])
    for summary in report.hotspot_surface_summaries:
        lines.append(f"- `{_fmt(summary)}`")
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


def write_main_wing_mesh_quality_hotspot_audit_report(
    out_dir: Path,
    *,
    report: MainWingMeshQualityHotspotAuditReport | None = None,
    mesh_handoff_report_path: Path | None = None,
    mesh_metadata_path: Path | None = None,
    hotspot_patch_report_path: Path | None = None,
    surface_patch_diagnostics_path: Path | None = None,
    gmsh_defect_entity_trace_path: Path | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_mesh_quality_hotspot_audit_report(
            mesh_handoff_report_path=mesh_handoff_report_path,
            mesh_metadata_path=mesh_metadata_path,
            hotspot_patch_report_path=hotspot_patch_report_path,
            surface_patch_diagnostics_path=surface_patch_diagnostics_path,
            gmsh_defect_entity_trace_path=gmsh_defect_entity_trace_path,
        )
    json_path = out_dir / "main_wing_mesh_quality_hotspot_audit.v1.json"
    markdown_path = out_dir / "main_wing_mesh_quality_hotspot_audit.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
