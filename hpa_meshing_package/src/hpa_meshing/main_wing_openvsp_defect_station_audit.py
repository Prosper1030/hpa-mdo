from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any, Dict, List, Literal
import xml.etree.ElementTree as ET

from pydantic import BaseModel, Field


StationAlignmentStatusType = Literal[
    "defect_stations_aligned_to_openvsp_rule_sections",
    "defect_stations_not_aligned_to_openvsp_rule_sections",
    "no_defect_stations",
    "blocked",
]


class MainWingOpenVSPDefectStationAuditReport(BaseModel):
    schema_version: Literal["main_wing_openvsp_defect_station_audit.v1"] = (
        "main_wing_openvsp_defect_station_audit.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_existing_geometry_artifacts"] = (
        "report_only_existing_geometry_artifacts"
    )
    production_default_changed: bool = False
    station_alignment_status: StationAlignmentStatusType
    defect_localization_path: str
    topology_lineage_path: str
    source_vsp3_path: str
    station_mappings: List[Dict[str, Any]] = Field(default_factory=list)
    alignment_summary: Dict[str, Any] = Field(default_factory=dict)
    blocking_reasons: List[str] = Field(default_factory=list)
    engineering_findings: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_defect_localization_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_su2_topology_defect_localization"
        / "main_wing_su2_topology_defect_localization.v1.json"
    )


def _default_esp_runtime_dir() -> Path:
    return (
        _default_report_root()
        / "main_wing_real_mesh_handoff_probe"
        / "artifacts"
        / "real_mesh_probe"
        / "artifacts"
        / "providers"
        / "esp_rebuilt"
        / "esp_runtime"
    )


def _default_topology_lineage_path() -> Path:
    return _default_esp_runtime_dir() / "topology_lineage_report.json"


def _default_source_vsp3_path() -> Path:
    return _default_esp_runtime_dir() / "main_wing.vsp3"


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


def _float_attr(element: ET.Element | None, child_name: str) -> float | None:
    child = element.find(child_name) if element is not None else None
    if child is None:
        return None
    try:
        return float(child.attrib.get("Value", ""))
    except ValueError:
        return None


def _find_main_wing(root: ET.Element) -> ET.Element | None:
    for geom in root.findall(".//Geom"):
        name = geom.findtext("./ParmContainer/Name")
        geom_id = geom.findtext("./ParmContainer/ID")
        if name == "Main Wing" or geom_id == "IPAWXFWPQF":
            return geom
    return None


def _source_sections(path: Path, blockers: list[str]) -> dict[int, dict[str, Any]]:
    try:
        root = ET.parse(path).getroot()
    except FileNotFoundError:
        blockers.append("source_vsp3_missing")
        return {}
    except ET.ParseError as exc:
        blockers.append(f"source_vsp3_parse_failed:{exc}")
        return {}
    geom = _find_main_wing(root)
    if geom is None:
        blockers.append("source_vsp3_main_wing_missing")
        return {}
    xsec_surf = geom.find(".//XSecSurf")
    xsecs = xsec_surf.findall("./XSec") if xsec_surf is not None else []
    sections: dict[int, dict[str, Any]] = {}
    for index, xsec in enumerate(xsecs):
        params = xsec.find("./ParmContainer/XSec")
        sections[index] = {
            "source_section_index": index,
            "span_m": _float_attr(params, "Span"),
            "root_chord_m": _float_attr(params, "Root_Chord"),
            "tip_chord_m": _float_attr(params, "Tip_Chord"),
            "sect_tess_u": _float_attr(params, "SectTess_U"),
            "sweep_deg": _float_attr(params, "Sweep"),
            "dihedral_deg": _float_attr(params, "Dihedral"),
            "twist_deg": _float_attr(params, "Twist"),
        }
    if not sections:
        blockers.append("source_vsp3_sections_missing")
    return sections


def _rule_sections(topology_lineage: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(topology_lineage, dict):
        return []
    sections: list[dict[str, Any]] = []
    for surface in topology_lineage.get("surfaces", []):
        if not isinstance(surface, dict):
            continue
        if surface.get("component") not in (None, "main_wing"):
            continue
        for section in surface.get("rule_sections", []):
            if isinstance(section, dict):
                sections.append(section)
    return sections


def _defect_stations(defect_localization: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(defect_localization, dict):
        return []
    stations = defect_localization.get("station_summary", [])
    return [station for station in stations if isinstance(station, dict)]


def _nearest_rule_section(
    *,
    station_y: float,
    rule_sections: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, float | None]:
    nearest: dict[str, Any] | None = None
    nearest_delta: float | None = None
    for section in rule_sections:
        y_le = section.get("y_le")
        if not isinstance(y_le, (int, float)):
            continue
        delta = abs(float(y_le) - station_y)
        if nearest_delta is None or delta < nearest_delta:
            nearest = section
            nearest_delta = delta
    return nearest, nearest_delta


def _station_mappings(
    *,
    defect_stations: list[dict[str, Any]],
    rule_sections: list[dict[str, Any]],
    source_sections: dict[int, dict[str, Any]],
    tolerance_m: float,
) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    for station in defect_stations:
        raw_y = station.get("station_y_m")
        if not isinstance(raw_y, (int, float)):
            continue
        station_y = float(raw_y)
        nearest, delta = _nearest_rule_section(
            station_y=station_y,
            rule_sections=rule_sections,
        )
        source_section: dict[str, Any] | None = None
        if isinstance(nearest, dict):
            source_index = nearest.get("source_section_index")
            if isinstance(source_index, int):
                source_section = source_sections.get(source_index)
        mappings.append(
            {
                "defect_station_y_m": station_y,
                "defect_count": station.get("defect_count"),
                "defect_kind_counts": station.get("defect_kind_counts", {}),
                "nearest_rule_section": nearest or {},
                "source_section": source_section or {},
                "delta_y_m": delta,
                "exact_rule_section_match": (
                    delta is not None and delta <= tolerance_m
                ),
            }
        )
    return mappings


def _alignment_summary(mappings: list[dict[str, Any]]) -> dict[str, Any]:
    deltas = [
        float(mapping["delta_y_m"])
        for mapping in mappings
        if isinstance(mapping.get("delta_y_m"), (int, float))
    ]
    source_indices = [
        mapping.get("nearest_rule_section", {}).get("source_section_index")
        for mapping in mappings
        if isinstance(mapping.get("nearest_rule_section"), dict)
    ]
    return {
        "defect_station_count": len(mappings),
        "exact_rule_section_match_count": sum(
            1 for mapping in mappings if mapping.get("exact_rule_section_match") is True
        ),
        "max_abs_delta_y_m": max(deltas) if deltas else None,
        "matched_source_section_indices": sorted(
            {
                int(index)
                for index in source_indices
                if isinstance(index, int)
            }
        ),
    }


def _status(
    *,
    blockers: list[str],
    mappings: list[dict[str, Any]],
) -> StationAlignmentStatusType:
    if blockers:
        return "blocked"
    if not mappings:
        return "no_defect_stations"
    if all(mapping.get("exact_rule_section_match") is True for mapping in mappings):
        return "defect_stations_aligned_to_openvsp_rule_sections"
    return "defect_stations_not_aligned_to_openvsp_rule_sections"


def _engineering_findings(
    *,
    status: StationAlignmentStatusType,
    mappings: list[dict[str, Any]],
) -> list[str]:
    if status == "blocked":
        return ["openvsp_defect_station_audit_blocked"]
    if not mappings:
        return ["no_localized_defect_stations_to_map"]
    findings: list[str] = []
    if status == "defect_stations_aligned_to_openvsp_rule_sections":
        findings.append("defect_stations_align_with_openvsp_rule_sections")
    kind_counts: Counter[str] = Counter()
    source_indices = set()
    sides = set()
    for mapping in mappings:
        kind_counts.update(
            {
                str(kind): int(count)
                for kind, count in mapping.get("defect_kind_counts", {}).items()
                if isinstance(count, int)
            }
        )
        nearest = mapping.get("nearest_rule_section", {})
        if isinstance(nearest, dict):
            source_index = nearest.get("source_section_index")
            if isinstance(source_index, int):
                source_indices.add(source_index)
            side = nearest.get("side")
            if isinstance(side, str):
                sides.add(side)
    if len(mappings) <= 3:
        findings.append("defect_stations_clustered_at_few_openvsp_sections")
    if kind_counts.get("nonmanifold_edge", 0) > 0:
        findings.append("defect_stations_include_nonmanifold_edges")
    if len(source_indices) > 1:
        findings.append("defect_stations_span_multiple_source_sections")
    if any(side.startswith("left") for side in sides) and any(
        side.startswith("right") for side in sides
    ):
        findings.append("left_right_section_station_defects_observed")
    return findings


def _next_actions(status: StationAlignmentStatusType) -> list[str]:
    if status == "blocked":
        return ["restore_missing_openvsp_station_audit_inputs"]
    if status == "no_defect_stations":
        return ["continue_with_source_backed_solver_budget_after_geometry_audit"]
    return [
        "trace_defect_edges_to_gmsh_entities_at_openvsp_section_stations",
        "build_minimal_openvsp_section_station_topology_fixture",
        "decide_if_station_seam_repair_or_closed_thickness_export_is_required",
    ]


def build_main_wing_openvsp_defect_station_audit_report(
    *,
    defect_localization_path: Path | None = None,
    topology_lineage_path: Path | None = None,
    source_vsp3_path: Path | None = None,
    tolerance_m: float = 1.0e-6,
) -> MainWingOpenVSPDefectStationAuditReport:
    defect_path = (
        _default_defect_localization_path()
        if defect_localization_path is None
        else defect_localization_path
    )
    topology_path = (
        _default_topology_lineage_path()
        if topology_lineage_path is None
        else topology_lineage_path
    )
    vsp3_path = _default_source_vsp3_path() if source_vsp3_path is None else source_vsp3_path
    blockers: list[str] = []
    defect_localization = _load_json(
        defect_path,
        blockers,
        "defect_localization_report",
    )
    topology_lineage = _load_json(topology_path, blockers, "topology_lineage_report")
    source_sections = _source_sections(vsp3_path, blockers)
    rules = _rule_sections(topology_lineage)
    stations = _defect_stations(defect_localization)
    if stations and isinstance(topology_lineage, dict) and not rules:
        blockers.append("topology_lineage_rule_sections_missing")
    mappings = _station_mappings(
        defect_stations=stations,
        rule_sections=rules,
        source_sections=source_sections,
        tolerance_m=tolerance_m,
    )
    status = _status(blockers=blockers, mappings=mappings)
    return MainWingOpenVSPDefectStationAuditReport(
        station_alignment_status=status,
        defect_localization_path=str(defect_path),
        topology_lineage_path=str(topology_path),
        source_vsp3_path=str(vsp3_path),
        station_mappings=mappings,
        alignment_summary=_alignment_summary(mappings),
        blocking_reasons=blockers,
        engineering_findings=_engineering_findings(status=status, mappings=mappings),
        next_actions=_next_actions(status),
        limitations=[
            "This report maps localized mesh topology defects to OpenVSP/ESP station evidence only; it does not repair geometry.",
            "Station alignment is route-risk provenance, not proof of SU2 convergence behavior.",
            "VSP3 section parameters identify source stations but do not by themselves identify the Gmsh curve or surface entity that produced each edge.",
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


def _render_markdown(report: MainWingOpenVSPDefectStationAuditReport) -> str:
    lines = [
        "# Main Wing OpenVSP Defect Station Audit v1",
        "",
        "This report reads existing OpenVSP/ESP topology artifacts only; it does not repair geometry.",
        "",
        f"- station_alignment_status: `{report.station_alignment_status}`",
        f"- defect_localization_path: `{report.defect_localization_path}`",
        f"- topology_lineage_path: `{report.topology_lineage_path}`",
        f"- source_vsp3_path: `{report.source_vsp3_path}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Alignment Summary",
        "",
    ]
    for key, value in report.alignment_summary.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Station Mappings", ""])
    for mapping in report.station_mappings:
        lines.append(f"- `{_fmt(mapping)}`")
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


def write_main_wing_openvsp_defect_station_audit_report(
    out_dir: Path,
    *,
    report: MainWingOpenVSPDefectStationAuditReport | None = None,
    defect_localization_path: Path | None = None,
    topology_lineage_path: Path | None = None,
    source_vsp3_path: Path | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_openvsp_defect_station_audit_report(
            defect_localization_path=defect_localization_path,
            topology_lineage_path=topology_lineage_path,
            source_vsp3_path=source_vsp3_path,
        )
    json_path = out_dir / "main_wing_openvsp_defect_station_audit.v1.json"
    markdown_path = out_dir / "main_wing_openvsp_defect_station_audit.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
