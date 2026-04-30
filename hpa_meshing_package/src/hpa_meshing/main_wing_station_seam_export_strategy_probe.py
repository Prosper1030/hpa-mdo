from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from .gmsh_runtime import GmshRuntimeError, load_gmsh


ExportStrategyProbeStatusType = Literal[
    "export_strategy_candidate_materialized_needs_brep_validation",
    "export_strategy_candidate_materialized_but_topology_risk",
    "export_strategy_candidate_materialization_failed",
    "export_strategy_candidate_source_only_ready_for_materialization",
    "blocked",
]


class MainWingStationSeamExportStrategyProbeReport(BaseModel):
    schema_version: Literal[
        "main_wing_station_seam_export_strategy_probe.v1"
    ] = "main_wing_station_seam_export_strategy_probe.v1"
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_station_seam_export_strategy_probe"] = (
        "report_only_station_seam_export_strategy_probe"
    )
    production_default_changed: bool = False
    probe_status: ExportStrategyProbeStatusType
    export_source_audit_path: str
    rebuild_csm_path: str | None = None
    materialization_requested: bool = False
    target_rule_section_indices: list[int] = Field(default_factory=list)
    candidate_reports: list[dict[str, Any]] = Field(default_factory=list)
    engineering_findings: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_export_source_audit_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_export_source_audit"
        / "main_wing_station_seam_export_source_audit.v1.json"
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


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _parse_csm_sections(path: Path, blockers: list[str]) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        blockers.append("rebuild_csm_missing")
        return []
    sections: list[dict[str, Any]] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("skbeg "):
            current = [line.rstrip()]
            continue
        if current:
            current.append(line.rstrip())
            if stripped == "skend":
                first = current[0].split()
                sections.append(
                    {
                        "csm_section_index": len(sections),
                        "station_y_m": _as_float(first[2]) if len(first) >= 4 else None,
                        "line_count": len(current),
                        "lines": current,
                    }
                )
                current = []
    if not sections:
        blockers.append("rebuild_csm_sections_missing")
    return sections


def _target_indices(audit_payload: dict[str, Any] | None) -> list[int]:
    if not isinstance(audit_payload, dict):
        return []
    indices: set[int] = set()
    for mapping in audit_payload.get("target_station_mappings", []):
        if not isinstance(mapping, dict):
            continue
        index = _as_int(mapping.get("csm_section_index"))
        if index is not None:
            indices.add(index)
    return sorted(indices)


def _split_at_target_groups(section_count: int, target_indices: list[int]) -> list[list[int]]:
    boundaries = [0, *target_indices, section_count - 1]
    unique_boundaries = sorted(
        {index for index in boundaries if 0 <= index < section_count}
    )
    groups: list[list[int]] = []
    for start, end in zip(unique_boundaries, unique_boundaries[1:]):
        if end <= start:
            continue
        groups.append(list(range(start, end + 1)))
    return groups


def _roles_for_targets(
    *,
    groups: list[list[int]],
    target_indices: list[int],
) -> dict[str, list[dict[str, Any]]]:
    roles: dict[str, list[dict[str, Any]]] = {}
    for target in target_indices:
        target_roles: list[dict[str, Any]] = []
        for group_index, group in enumerate(groups):
            if target not in group:
                continue
            offset = group.index(target)
            if len(group) < 2:
                role = "invalid_single_section_group"
            elif offset == 0:
                role = "start_boundary"
            elif offset == len(group) - 1:
                role = "end_boundary"
            else:
                role = "internal"
            target_roles.append(
                {
                    "group_index": group_index,
                    "role": role,
                    "group_section_indices": group,
                }
            )
        roles[str(target)] = target_roles
    return roles


def _all_targets_boundary(roles: dict[str, list[dict[str, Any]]]) -> bool:
    return bool(roles) and all(
        target_roles
        and all(item.get("role") in {"start_boundary", "end_boundary"} for item in target_roles)
        for target_roles in roles.values()
    )


def _target_boundary_duplication_count(roles: dict[str, list[dict[str, Any]]]) -> int:
    return sum(max(len(target_roles) - 1, 0) for target_roles in roles.values())


def _expected_station_bounds(sections: list[dict[str, Any]]) -> dict[str, float | None]:
    y_values = [
        float(section["station_y_m"])
        for section in sections
        if isinstance(section.get("station_y_m"), (int, float))
    ]
    return {
        "y_min": min(y_values) if y_values else None,
        "y_max": max(y_values) if y_values else None,
    }


def _span_y_bounds_preserved(
    *,
    topology: dict[str, Any],
    expected_bounds: dict[str, float | None],
    tolerance: float = 1.0e-3,
) -> bool | None:
    bbox = topology.get("bbox")
    expected_min = expected_bounds.get("y_min")
    expected_max = expected_bounds.get("y_max")
    if (
        not isinstance(bbox, list)
        or len(bbox) < 5
        or not isinstance(expected_min, (int, float))
        or not isinstance(expected_max, (int, float))
    ):
        return None
    return (
        abs(float(bbox[1]) - float(expected_min)) <= tolerance
        and abs(float(bbox[4]) - float(expected_max)) <= tolerance
    )


def _candidate_specs(
    *,
    section_count: int,
    target_indices: list[int],
) -> list[dict[str, Any]]:
    split_groups = _split_at_target_groups(section_count, target_indices)
    if not split_groups:
        return []
    return [
        {
            "candidate": "split_at_defect_sections_no_union",
            "groups": split_groups,
            "apply_union": False,
            "intended_use": "diagnostic_pcure_boundary_probe",
            "risk": "multiple touching solids and duplicate internal station caps",
        },
        {
            "candidate": "split_at_defect_sections_union",
            "groups": split_groups,
            "apply_union": True,
            "intended_use": "single_body_candidate_before_brep_validation",
            "risk": "boolean union may fail or keep internal cap scars",
        },
    ]


def _build_candidate_csm(
    *,
    candidate: str,
    sections: list[dict[str, Any]],
    groups: list[list[int]],
    apply_union: bool,
    export_filename: str,
    source_csm_path: Path,
) -> str:
    lines = [
        "# Auto-generated by hpa_meshing.main_wing_station_seam_export_strategy_probe",
        "# Report-only candidate; not a production provider default",
        f"# Source rebuild.csm: {source_csm_path}",
        f"# Candidate: {candidate}",
        f"SET export_path $\"{export_filename}\"",
        "",
    ]
    for group_index, group in enumerate(groups):
        lines.extend(
            [
                f"# Split rule group {group_index}: sections {group}",
                "mark",
            ]
        )
        for section_index in group:
            lines.extend(str(line) for line in sections[section_index]["lines"])
        name = f"main_wing_{candidate}_{group_index}"
        lines.extend(
            [
                "rule",
                f"ATTRIBUTE _name ${name}",
                "ATTRIBUTE capsGroup $main_wing",
                "",
            ]
        )
    if apply_union:
        lines.append(f"UNION {len(groups)}")
    lines.extend(["DUMP !export_path 0 1", "END", ""])
    return "\n".join(lines)


def _write_command_log(
    *,
    log_path: Path,
    args: list[str],
    returncode: int | str,
    stdout: str,
    stderr: str,
) -> None:
    log_path.write_text(
        "\n".join(
            [
                "command: " + " ".join(args),
                f"returncode: {returncode}",
                "--- stdout ---",
                stdout,
                "--- stderr ---",
                stderr,
                "",
            ]
        ),
        encoding="utf-8",
    )


def _probe_step_topology(step_path: Path) -> dict[str, Any]:
    try:
        gmsh = load_gmsh()
    except GmshRuntimeError as exc:
        return {"status": "gmsh_unavailable", "error": str(exc)}

    gmsh_initialized = False
    try:
        gmsh.initialize()
        gmsh_initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(f"main_wing_split_candidate_{int(time.time() * 1000)}")
        imported = gmsh.model.occ.importShapes(str(step_path))
        gmsh.model.occ.synchronize()
        volumes = gmsh.model.getEntities(3)
        surfaces = gmsh.model.getEntities(2)
        curves = gmsh.model.getEntities(1)
        points = gmsh.model.getEntities(0)
        bbox = None
        if volumes:
            model_bbox = [float("inf"), float("inf"), float("inf"), float("-inf"), float("-inf"), float("-inf")]
            for _, tag in volumes:
                current = [float(value) for value in gmsh.model.getBoundingBox(3, tag)]
                model_bbox[0] = min(model_bbox[0], current[0])
                model_bbox[1] = min(model_bbox[1], current[1])
                model_bbox[2] = min(model_bbox[2], current[2])
                model_bbox[3] = max(model_bbox[3], current[3])
                model_bbox[4] = max(model_bbox[4], current[4])
                model_bbox[5] = max(model_bbox[5], current[5])
            bbox = model_bbox
        return {
            "status": "topology_counted",
            "imported_entity_count": len(imported),
            "body_count": len(volumes),
            "volume_count": len(volumes),
            "surface_count": len(surfaces),
            "curve_count": len(curves),
            "point_count": len(points),
            "bbox": bbox,
        }
    except Exception as exc:
        return {"status": "topology_probe_failed", "error": str(exc)}
    finally:
        if gmsh_initialized:
            gmsh.finalize()


def _materialize_candidate(
    *,
    candidate_dir: Path,
    csm_text: str,
    batch_binary: str | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    candidate_dir = candidate_dir.resolve()
    candidate_dir.mkdir(parents=True, exist_ok=True)
    csm_path = candidate_dir / "candidate.csm"
    step_path = candidate_dir / "candidate_raw_dump.stp"
    command_log_path = candidate_dir / "ocsm.log"
    csm_path.write_text(csm_text, encoding="utf-8")

    if batch_binary is None:
        _write_command_log(
            log_path=command_log_path,
            args=[],
            returncode="not_run",
            stdout="",
            stderr="Neither serveCSM nor ocsm was resolvable on PATH.",
        )
        return {
            "status": "not_run_batch_binary_missing",
            "csm_path": str(csm_path),
            "step_path": str(step_path),
            "command_log_path": str(command_log_path),
        }

    args = [batch_binary, "-batch", str(csm_path)]
    try:
        completed = subprocess.run(
            args,
            cwd=str(candidate_dir),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        _write_command_log(
            log_path=command_log_path,
            args=args,
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
    except subprocess.TimeoutExpired as exc:
        _write_command_log(
            log_path=command_log_path,
            args=args,
            returncode="timeout",
            stdout=exc.stdout if isinstance(exc.stdout, str) else "",
            stderr=exc.stderr if isinstance(exc.stderr, str) else "",
        )
        return {
            "status": "timeout",
            "csm_path": str(csm_path),
            "step_path": str(step_path),
            "command_log_path": str(command_log_path),
            "timeout_seconds": float(timeout_seconds),
        }

    topology = _probe_step_topology(step_path) if step_path.exists() else {}
    return {
        "status": (
            "materialized"
            if completed.returncode == 0 and step_path.exists()
            else "failed"
        ),
        "returncode": completed.returncode,
        "csm_path": str(csm_path),
        "step_path": str(step_path),
        "step_exists": step_path.exists(),
        "step_size_bytes": step_path.stat().st_size if step_path.exists() else None,
        "command_log_path": str(command_log_path),
        "stdout_tail": (completed.stdout or "")[-1000:],
        "stderr_tail": (completed.stderr or "")[-1000:],
        "topology": topology,
    }


def _build_candidate_reports(
    *,
    sections: list[dict[str, Any]],
    target_indices: list[int],
    source_csm_path: Path,
    materialization_requested: bool,
    materialization_root: Path | None,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    batch_binary = shutil.which("serveCSM") or shutil.which("ocsm")
    reports: list[dict[str, Any]] = []
    expected_bounds = _expected_station_bounds(sections)
    for spec in _candidate_specs(section_count=len(sections), target_indices=target_indices):
        groups = spec["groups"]
        roles = _roles_for_targets(groups=groups, target_indices=target_indices)
        candidate = str(spec["candidate"])
        export_filename = "candidate_raw_dump.stp"
        csm_text = _build_candidate_csm(
            candidate=candidate,
            sections=sections,
            groups=groups,
            apply_union=bool(spec["apply_union"]),
            export_filename=export_filename,
            source_csm_path=source_csm_path,
        )
        report: dict[str, Any] = {
            "candidate": candidate,
            "apply_union": bool(spec["apply_union"]),
            "intended_use": spec["intended_use"],
            "risk": spec["risk"],
            "rule_count": len(groups),
            "section_groups": groups,
            "target_section_roles": roles,
            "all_targets_exported_as_rule_boundaries": _all_targets_boundary(roles),
            "target_boundary_duplication_count": _target_boundary_duplication_count(roles),
            "expected_station_bounds": expected_bounds,
            "materialization": {"status": "not_requested"},
        }
        if materialization_requested and materialization_root is not None:
            report["materialization"] = _materialize_candidate(
                candidate_dir=materialization_root / "artifacts" / candidate,
                csm_text=csm_text,
                batch_binary=batch_binary,
                timeout_seconds=timeout_seconds,
            )
            topology = report["materialization"].get("topology", {})
            report["span_y_bounds_preserved"] = _span_y_bounds_preserved(
                topology=topology if isinstance(topology, dict) else {},
                expected_bounds=expected_bounds,
            )
        reports.append(report)
    return reports


def _probe_status(
    *,
    blockers: list[str],
    materialization_requested: bool,
    candidates: list[dict[str, Any]],
) -> ExportStrategyProbeStatusType:
    if blockers or not candidates:
        return "blocked"
    if not materialization_requested:
        return "export_strategy_candidate_source_only_ready_for_materialization"
    materialized = [
        candidate
        for candidate in candidates
        if candidate.get("materialization", {}).get("status") == "materialized"
    ]
    if not materialized:
        return "export_strategy_candidate_materialization_failed"
    single_volume_candidate = any(
        candidate.get("all_targets_exported_as_rule_boundaries") is True
        and candidate.get("span_y_bounds_preserved") is True
        and candidate.get("materialization", {})
        .get("topology", {})
        .get("body_count")
        == 1
        and candidate.get("materialization", {})
        .get("topology", {})
        .get("volume_count")
        == 1
        for candidate in materialized
    )
    if single_volume_candidate:
        return "export_strategy_candidate_materialized_needs_brep_validation"
    return "export_strategy_candidate_materialized_but_topology_risk"


def _engineering_findings(
    *,
    status: ExportStrategyProbeStatusType,
    candidates: list[dict[str, Any]],
) -> list[str]:
    findings = ["station_seam_export_strategy_probe_captured"]
    if any(candidate.get("all_targets_exported_as_rule_boundaries") is True for candidate in candidates):
        findings.append("split_candidate_moves_target_stations_to_rule_boundaries")
    if any(int(candidate.get("target_boundary_duplication_count", 0)) > 0 for candidate in candidates):
        findings.append("split_candidate_duplicates_station_boundaries")
    for candidate in candidates:
        materialization = candidate.get("materialization", {})
        topology = materialization.get("topology", {})
        name = candidate.get("candidate")
        if materialization.get("status") != "materialized":
            continue
        if candidate.get("span_y_bounds_preserved") is False:
            findings.append(f"{name}_materialized_but_span_bounds_not_preserved")
        if (
            topology.get("body_count") == 1
            and topology.get("volume_count") == 1
            and candidate.get("span_y_bounds_preserved") is True
        ):
            findings.append(f"{name}_materialized_single_volume_candidate")
        elif topology:
            findings.append(f"{name}_materialized_with_topology_risk")
    if status == "export_strategy_candidate_source_only_ready_for_materialization":
        findings.append("candidate_source_ready_for_servecsm_materialization")
    if status == "export_strategy_candidate_materialized_needs_brep_validation":
        findings.append("candidate_materialized_but_needs_station_brep_validation")
    return findings


def _blocking_reasons(
    *,
    status: ExportStrategyProbeStatusType,
    blockers: list[str],
    candidates: list[dict[str, Any]],
) -> list[str]:
    reasons = list(blockers)
    if status == "export_strategy_candidate_source_only_ready_for_materialization":
        reasons.append("candidate_materialization_not_run")
    elif status == "export_strategy_candidate_materialization_failed":
        reasons.append("all_export_strategy_candidate_materializations_failed")
    elif status == "export_strategy_candidate_materialized_but_topology_risk":
        reasons.append("split_candidate_topology_not_single_volume_or_has_duplicate_cap_risk")
    elif status == "export_strategy_candidate_materialized_needs_brep_validation":
        reasons.append("candidate_needs_station_brep_pcurve_validation_before_route_promotion")
    if any(candidate.get("span_y_bounds_preserved") is False for candidate in candidates):
        reasons.append("split_candidate_does_not_preserve_full_span_bounds")
    if any(int(candidate.get("target_boundary_duplication_count", 0)) > 0 for candidate in candidates):
        reasons.append("split_candidate_duplicates_target_station_sections")
    return reasons


def _next_actions(status: ExportStrategyProbeStatusType) -> list[str]:
    if status == "export_strategy_candidate_materialized_needs_brep_validation":
        return [
            "run_station_seam_brep_hotspot_probe_on_split_candidate",
            "compare_candidate_mesh_handoff_without_promoting_default",
        ]
    if status == "export_strategy_candidate_materialized_but_topology_risk":
        return [
            "inspect_split_candidate_internal_caps_before_mesh_handoff",
            "try_pcurve_rebuild_strategy_if_split_candidate_keeps_duplicate_caps",
        ]
    if status == "export_strategy_candidate_source_only_ready_for_materialization":
        return ["materialize_split_bay_export_candidate_with_servecsm"]
    if status == "export_strategy_candidate_materialization_failed":
        return ["inspect_servecsm_split_candidate_logs"]
    return ["restore_station_seam_export_strategy_probe_inputs"]


def build_main_wing_station_seam_export_strategy_probe_report(
    *,
    export_source_audit_path: Path | None = None,
    materialization_requested: bool = False,
    materialization_root: Path | None = None,
    timeout_seconds: float = 90.0,
) -> MainWingStationSeamExportStrategyProbeReport:
    audit_path = (
        _default_export_source_audit_path()
        if export_source_audit_path is None
        else export_source_audit_path
    )
    blockers: list[str] = []
    audit_payload = _load_json(audit_path, blockers, "export_source_audit")
    csm_path = _resolve_path(
        audit_payload.get("rebuild_csm_path") if isinstance(audit_payload, dict) else None
    )
    if csm_path is None:
        blockers.append("rebuild_csm_path_missing")
    target_indices = _target_indices(audit_payload)
    if not target_indices:
        blockers.append("target_rule_section_indices_missing")
    sections = _parse_csm_sections(csm_path, blockers) if csm_path is not None else []
    candidates: list[dict[str, Any]] = []
    if not blockers:
        candidates = _build_candidate_reports(
            sections=sections,
            target_indices=target_indices,
            source_csm_path=csm_path,
            materialization_requested=materialization_requested,
            materialization_root=materialization_root,
            timeout_seconds=timeout_seconds,
        )
    status = _probe_status(
        blockers=blockers,
        materialization_requested=materialization_requested,
        candidates=candidates,
    )
    return MainWingStationSeamExportStrategyProbeReport(
        probe_status=status,
        export_source_audit_path=str(audit_path),
        rebuild_csm_path=str(csm_path) if csm_path is not None else None,
        materialization_requested=materialization_requested,
        target_rule_section_indices=target_indices,
        candidate_reports=candidates,
        engineering_findings=_engineering_findings(status=status, candidates=candidates),
        blocking_reasons=_blocking_reasons(
            status=status,
            blockers=blockers,
            candidates=candidates,
        ),
        next_actions=_next_actions(status),
        limitations=[
            "This probe writes candidate export sources only under its report directory.",
            "It does not change esp_rebuilt, Gmsh, SU2, or production defaults.",
            "A materialized split candidate is not a CFD-ready geometry until BRep, mesh handoff, marker ownership, and solver gates pass.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_markdown(report: MainWingStationSeamExportStrategyProbeReport) -> str:
    lines = [
        "# Main Wing Station Seam Export Strategy Probe v1",
        "",
        "This report prototypes station-seam export strategies without changing production defaults.",
        "",
        f"- probe_status: `{report.probe_status}`",
        f"- export_source_audit_path: `{report.export_source_audit_path}`",
        f"- rebuild_csm_path: `{report.rebuild_csm_path}`",
        f"- materialization_requested: `{report.materialization_requested}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        f"- target_rule_section_indices: `{_fmt(report.target_rule_section_indices)}`",
        "",
        "## Candidate Reports",
        "",
    ]
    for candidate in report.candidate_reports:
        materialization = candidate.get("materialization", {})
        topology = materialization.get("topology", {}) if isinstance(materialization, dict) else {}
        bbox = topology.get("bbox") if isinstance(topology, dict) else None
        bbox_y = [bbox[1], bbox[4]] if isinstance(bbox, list) and len(bbox) >= 5 else None
        lines.append(f"### {candidate.get('candidate')}")
        lines.append("")
        lines.append(f"- apply_union: `{candidate.get('apply_union')}`")
        lines.append(f"- rule_count: `{candidate.get('rule_count')}`")
        lines.append(
            "- all_targets_exported_as_rule_boundaries: "
            f"`{candidate.get('all_targets_exported_as_rule_boundaries')}`"
        )
        lines.append(
            "- target_boundary_duplication_count: "
            f"`{candidate.get('target_boundary_duplication_count')}`"
        )
        lines.append(f"- span_y_bounds_preserved: `{candidate.get('span_y_bounds_preserved')}`")
        lines.append(f"- materialization_status: `{materialization.get('status')}`")
        lines.append(f"- returncode: `{materialization.get('returncode')}`")
        lines.append(f"- csm_path: `{materialization.get('csm_path')}`")
        lines.append(f"- step_path: `{materialization.get('step_path')}`")
        lines.append(f"- topology_body_count: `{topology.get('body_count')}`")
        lines.append(f"- topology_volume_count: `{topology.get('volume_count')}`")
        lines.append(f"- topology_surface_count: `{topology.get('surface_count')}`")
        lines.append(f"- topology_bbox_y: `{_fmt(bbox_y)}`")
        lines.append("")
    if not report.candidate_reports:
        lines.append("- none")
    lines.extend(["## Engineering Findings", ""])
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


def write_main_wing_station_seam_export_strategy_probe_report(
    out_dir: Path,
    *,
    report: MainWingStationSeamExportStrategyProbeReport | None = None,
    export_source_audit_path: Path | None = None,
    materialization_requested: bool = False,
    timeout_seconds: float = 90.0,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_station_seam_export_strategy_probe_report(
            export_source_audit_path=export_source_audit_path,
            materialization_requested=materialization_requested,
            materialization_root=out_dir,
            timeout_seconds=timeout_seconds,
        )
    json_path = out_dir / "main_wing_station_seam_export_strategy_probe.v1.json"
    markdown_path = out_dir / "main_wing_station_seam_export_strategy_probe.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
