from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


ExportSourceAuditStatusType = Literal[
    "single_rule_internal_station_export_source_confirmed",
    "export_source_audit_captured",
    "blocked",
]


class MainWingStationSeamExportSourceAuditReport(BaseModel):
    schema_version: Literal[
        "main_wing_station_seam_export_source_audit.v1"
    ] = "main_wing_station_seam_export_source_audit.v1"
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_station_seam_export_source_audit"] = (
        "report_only_station_seam_export_source_audit"
    )
    production_default_changed: bool = False
    audit_status: ExportSourceAuditStatusType
    shape_fix_feasibility_path: str
    topology_fixture_path: str
    normalized_step_path: str | None = None
    rebuild_csm_path: str | None = None
    topology_lineage_path: str | None = None
    csm_summary: Dict[str, Any] = Field(default_factory=dict)
    target_station_mappings: List[Dict[str, Any]] = Field(default_factory=list)
    export_strategy_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    engineering_findings: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_shape_fix_feasibility_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_shape_fix_feasibility"
        / "main_wing_station_seam_shape_fix_feasibility.v1.json"
    )


def _default_topology_fixture_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_openvsp_section_station_topology_fixture"
        / "main_wing_openvsp_section_station_topology_fixture.v1.json"
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


def _station_key(value: Any) -> str | None:
    station_y = _as_float(value)
    if station_y is None:
        return None
    return f"{station_y:.9f}"


def _parse_csm(path: Path, blockers: list[str]) -> dict[str, Any]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        blockers.append("rebuild_csm_missing")
        return {}
    sections: list[dict[str, Any]] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("skbeg "):
            current = [stripped]
            continue
        if current:
            current.append(stripped)
            if stripped == "skend":
                first = current[0].split()
                y_value = _as_float(first[2]) if len(first) >= 4 else None
                sections.append(
                    {
                        "csm_section_index": len(sections),
                        "station_y_m": y_value,
                        "line_count": len(current),
                    }
                )
                current = []
    rule_count = sum(1 for line in lines if line.strip().lower() == "rule")
    dump_count = sum(1 for line in lines if line.strip().lower().startswith("dump "))
    union_count = sum(
        1 for line in lines if re.match(r"^\s*union\b", line, flags=re.IGNORECASE)
    )
    return {
        "rule_count": rule_count,
        "sketch_section_count": len(sections),
        "dump_count": dump_count,
        "union_count": union_count,
        "single_rule_multi_section_loft": rule_count == 1 and len(sections) > 2,
        "station_y_values_m": [
            section["station_y_m"]
            for section in sections
            if section.get("station_y_m") is not None
        ],
        "sections": sections,
    }


def _fixture_cases(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    return [
        case
        for case in payload.get("station_fixture_cases", [])
        if isinstance(case, dict)
    ]


def _lineage_sections(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    sections: list[dict[str, Any]] = []
    for surface in payload.get("surfaces", []):
        if not isinstance(surface, dict):
            continue
        for section in surface.get("rule_sections", []):
            if isinstance(section, dict):
                sections.append(section)
    return sections


def _sections_by_station(sections: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for section in sections:
        key = _station_key(section.get("station_y_m", section.get("y_le")))
        if key is not None:
            result[key] = section
    return result


def _station_role(index: int | None, count: int) -> str:
    if index is None:
        return "unknown"
    if index == 0:
        return "start_tip"
    if index == count - 1:
        return "end_tip"
    return "internal_station"


def _target_station_mappings(
    *,
    fixture_payload: dict[str, Any] | None,
    csm_summary: dict[str, Any],
    topology_lineage: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    csm_by_station = _sections_by_station(csm_summary.get("sections", []))
    lineage_by_station = _sections_by_station(_lineage_sections(topology_lineage))
    section_count = int(csm_summary.get("sketch_section_count") or 0)
    mappings: list[dict[str, Any]] = []
    for case in _fixture_cases(fixture_payload):
        key = _station_key(case.get("defect_station_y_m"))
        csm_section = csm_by_station.get(key or "")
        lineage_section = lineage_by_station.get(key or "")
        csm_index = (
            int(csm_section["csm_section_index"])
            if isinstance(csm_section, dict)
            and isinstance(csm_section.get("csm_section_index"), int)
            else None
        )
        mappings.append(
            {
                "defect_station_y_m": case.get("defect_station_y_m"),
                "candidate_curve_tags": _as_int_list(case.get("candidate_curve_tags")),
                "owner_surface_entity_tags": _as_int_list(
                    case.get("owner_surface_entity_tags")
                ),
                "fixture_source_section_index": case.get("source_section_index"),
                "csm_section_index": csm_index,
                "csm_station_role": _station_role(csm_index, section_count),
                "lineage_rule_section_index": (
                    lineage_section.get("rule_section_index")
                    if isinstance(lineage_section, dict)
                    else None
                ),
                "lineage_source_section_index": (
                    lineage_section.get("source_section_index")
                    if isinstance(lineage_section, dict)
                    else None
                ),
                "lineage_mirrored": (
                    lineage_section.get("mirrored")
                    if isinstance(lineage_section, dict)
                    else None
                ),
                "lineage_side": (
                    lineage_section.get("side")
                    if isinstance(lineage_section, dict)
                    else None
                ),
            }
        )
    return mappings


def _all_targets_internal(mappings: list[dict[str, Any]]) -> bool:
    return bool(mappings) and all(
        mapping.get("csm_station_role") == "internal_station"
        for mapping in mappings
    )


def _status(
    *,
    blockers: list[str],
    shape_fix_payload: dict[str, Any] | None,
    csm_summary: dict[str, Any],
    mappings: list[dict[str, Any]],
) -> ExportSourceAuditStatusType:
    if blockers:
        return "blocked"
    if (
        shape_fix_payload.get("feasibility_status")
        == "shape_fix_repair_not_recovered"
        and csm_summary.get("single_rule_multi_section_loft") is True
        and _all_targets_internal(mappings)
    ):
        return "single_rule_internal_station_export_source_confirmed"
    return "export_source_audit_captured"


def _export_strategy_candidates(
    status: ExportSourceAuditStatusType,
) -> list[dict[str, Any]]:
    if status == "blocked":
        return []
    return [
        {
            "candidate": "station_pcurve_or_export_rebuild",
            "priority": "high",
            "scope": "provider_or_export_strategy_probe",
            "rationale": (
                "Generic post-export OCCT edge repair did not recover the station "
                "checks, so the next probe should change how station seams are "
                "generated or exported."
            ),
        },
        {
            "candidate": "split_bay_rule_loft_probe",
            "priority": "medium",
            "scope": "report_only_candidate_before_production_default",
            "rationale": (
                "Build span bays as separate rule loft candidates and inspect "
                "station ownership/PCurves before considering any Gmsh policy."
            ),
            "risk": "may introduce duplicate internal caps or multiple solids",
        },
        {
            "candidate": "avoid_more_generic_occt_edge_fix_sweeps",
            "priority": "high",
            "scope": "negative_result_guardrail",
            "rationale": (
                "BRepLib.SameParameter and ShapeFix_Edge operation sweeps already "
                "returned zero recovered target station checks."
            ),
        },
    ]


def _engineering_findings(
    status: ExportSourceAuditStatusType,
    *,
    shape_fix_payload: dict[str, Any] | None,
    csm_summary: dict[str, Any],
    mappings: list[dict[str, Any]],
) -> list[str]:
    if status == "blocked":
        return ["station_seam_export_source_audit_blocked"]
    findings = ["station_seam_export_source_audit_captured"]
    if csm_summary.get("single_rule_multi_section_loft") is True:
        findings.append("opencsm_export_uses_single_rule_loft_over_multiple_sections")
    if _all_targets_internal(mappings):
        findings.append("station_defects_map_to_internal_rule_sections")
    if shape_fix_payload.get("feasibility_status") == "shape_fix_repair_not_recovered":
        findings.append("generic_occt_edge_fix_sweeps_exhausted_without_recovery")
    if status == "single_rule_internal_station_export_source_confirmed":
        findings.append("export_strategy_probe_is_next_geometry_gate")
    return findings


def _blocking_reasons(
    status: ExportSourceAuditStatusType,
    blockers: list[str],
) -> list[str]:
    reasons = list(blockers)
    if status == "single_rule_internal_station_export_source_confirmed":
        reasons.append("station_single_rule_internal_export_source_requires_strategy_probe")
    return reasons


def _next_actions(status: ExportSourceAuditStatusType) -> list[str]:
    if status == "single_rule_internal_station_export_source_confirmed":
        return [
            "prototype_station_seam_export_strategy_before_solver_budget",
            "compare_split_bay_or_pcurve_rebuild_candidate_against_station_fixture",
        ]
    if status == "export_source_audit_captured":
        return ["review_station_export_source_audit_before_repair_candidate"]
    return ["restore_station_export_source_audit_inputs"]


def build_main_wing_station_seam_export_source_audit_report(
    *,
    shape_fix_feasibility_path: Path | None = None,
    topology_fixture_path: Path | None = None,
    rebuild_csm_path: Path | None = None,
    topology_lineage_path: Path | None = None,
) -> MainWingStationSeamExportSourceAuditReport:
    shape_path = (
        _default_shape_fix_feasibility_path()
        if shape_fix_feasibility_path is None
        else shape_fix_feasibility_path
    )
    fixture_path = (
        _default_topology_fixture_path()
        if topology_fixture_path is None
        else topology_fixture_path
    )
    blockers: list[str] = []
    shape_payload = _load_json(shape_path, blockers, "shape_fix_feasibility")
    fixture_payload = _load_json(fixture_path, blockers, "topology_fixture")
    normalized_step_path = _resolve_path(
        shape_payload.get("normalized_step_path") if isinstance(shape_payload, dict) else None
    )
    if normalized_step_path is None:
        blockers.append("normalized_step_path_missing")
    elif not normalized_step_path.exists():
        blockers.append("normalized_step_missing")
    resolved_csm_path = (
        rebuild_csm_path
        if rebuild_csm_path is not None
        else normalized_step_path.parent / "rebuild.csm"
        if normalized_step_path is not None
        else None
    )
    resolved_lineage_path = (
        topology_lineage_path
        if topology_lineage_path is not None
        else normalized_step_path.parent / "topology_lineage_report.json"
        if normalized_step_path is not None
        else None
    )
    csm_summary = (
        _parse_csm(resolved_csm_path, blockers)
        if resolved_csm_path is not None
        else {}
    )
    topology_lineage = (
        _load_json(resolved_lineage_path, blockers, "topology_lineage")
        if resolved_lineage_path is not None
        else None
    )
    mappings = _target_station_mappings(
        fixture_payload=fixture_payload,
        csm_summary=csm_summary,
        topology_lineage=topology_lineage,
    )
    if not mappings:
        blockers.append("target_station_mappings_missing")
    status = _status(
        blockers=blockers,
        shape_fix_payload=shape_payload if isinstance(shape_payload, dict) else {},
        csm_summary=csm_summary,
        mappings=mappings,
    )
    return MainWingStationSeamExportSourceAuditReport(
        audit_status=status,
        shape_fix_feasibility_path=str(shape_path),
        topology_fixture_path=str(fixture_path),
        normalized_step_path=(
            str(normalized_step_path) if normalized_step_path is not None else None
        ),
        rebuild_csm_path=(
            str(resolved_csm_path) if resolved_csm_path is not None else None
        ),
        topology_lineage_path=(
            str(resolved_lineage_path) if resolved_lineage_path is not None else None
        ),
        csm_summary=csm_summary,
        target_station_mappings=mappings,
        export_strategy_candidates=_export_strategy_candidates(status),
        engineering_findings=_engineering_findings(
            status,
            shape_fix_payload=shape_payload if isinstance(shape_payload, dict) else {},
            csm_summary=csm_summary,
            mappings=mappings,
        ),
        blocking_reasons=_blocking_reasons(status, blockers),
        next_actions=_next_actions(status),
        limitations=[
            "This report reads existing OpenCSM/STEP lineage artifacts only.",
            "It does not run serveCSM, Gmsh, SU2_CFD, or convergence gates.",
            "Export strategy candidates are diagnostic proposals, not production defaults.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_markdown(report: MainWingStationSeamExportSourceAuditReport) -> str:
    lines = [
        "# Main Wing Station Seam Export Source Audit v1",
        "",
        "This report ties the station-seam blocker back to the generated OpenCSM export source.",
        "",
        f"- audit_status: `{report.audit_status}`",
        f"- shape_fix_feasibility_path: `{report.shape_fix_feasibility_path}`",
        f"- topology_fixture_path: `{report.topology_fixture_path}`",
        f"- rebuild_csm_path: `{report.rebuild_csm_path}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## CSM Summary",
        "",
    ]
    for key, value in report.csm_summary.items():
        if key == "sections":
            continue
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Target Station Mappings", ""])
    if report.target_station_mappings:
        lines.extend(f"- `{_fmt(item)}`" for item in report.target_station_mappings)
    else:
        lines.append("- none")
    lines.extend(["", "## Export Strategy Candidates", ""])
    if report.export_strategy_candidates:
        lines.extend(f"- `{_fmt(item)}`" for item in report.export_strategy_candidates)
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


def write_main_wing_station_seam_export_source_audit_report(
    out_dir: Path,
    *,
    report: MainWingStationSeamExportSourceAuditReport | None = None,
    shape_fix_feasibility_path: Path | None = None,
    topology_fixture_path: Path | None = None,
    rebuild_csm_path: Path | None = None,
    topology_lineage_path: Path | None = None,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_station_seam_export_source_audit_report(
            shape_fix_feasibility_path=shape_fix_feasibility_path,
            topology_fixture_path=topology_fixture_path,
            rebuild_csm_path=rebuild_csm_path,
            topology_lineage_path=topology_lineage_path,
        )
    json_path = out_dir / "main_wing_station_seam_export_source_audit.v1.json"
    markdown_path = out_dir / "main_wing_station_seam_export_source_audit.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
