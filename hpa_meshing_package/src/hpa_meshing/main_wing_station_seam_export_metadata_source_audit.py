from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


ExportMetadataSourceAuditStatusType = Literal[
    "export_metadata_generation_source_boundary_captured",
    "export_metadata_generation_source_boundary_incomplete",
    "blocked",
]


class MainWingStationSeamExportMetadataSourceAuditReport(BaseModel):
    schema_version: Literal[
        "main_wing_station_seam_export_metadata_source_audit.v1"
    ] = "main_wing_station_seam_export_metadata_source_audit.v1"
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal[
        "report_only_export_metadata_source_boundary_audit"
    ] = "report_only_export_metadata_source_boundary_audit"
    production_default_changed: bool = False
    audit_status: ExportMetadataSourceAuditStatusType
    opcode_variant_probe_path: str
    source_files: dict[str, str] = Field(default_factory=dict)
    source_boundary: dict[str, Any] = Field(default_factory=dict)
    source_evidence: dict[str, Any] = Field(default_factory=dict)
    current_negative_controls: dict[str, Any] = Field(default_factory=dict)
    external_source_inventory: dict[str, Any] = Field(default_factory=dict)
    engineering_findings: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_opcode_variant_probe_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_side_aware_export_opcode_variant_probe"
        / "main_wing_station_seam_side_aware_export_opcode_variant_probe.v1.json"
    )


def _default_source_files() -> dict[str, Path]:
    src = _repo_root() / "hpa_meshing_package" / "src" / "hpa_meshing"
    return {
        "provider": src / "providers" / "esp_pipeline.py",
        "profile_resample": (
            src / "main_wing_station_seam_profile_resample_strategy_probe.py"
        ),
        "side_aware": (
            src / "main_wing_station_seam_side_aware_parametrization_probe.py"
        ),
        "opcode_variant": (
            src
            / "main_wing_station_seam_side_aware_export_opcode_variant_probe.py"
        ),
        "metadata_repair": (
            src / "main_wing_station_seam_side_aware_metadata_repair_probe.py"
        ),
        "projected_builder": (
            src
            / "main_wing_station_seam_side_aware_projected_pcurve_builder_probe.py"
        ),
    }


def _default_external_src_root() -> Path:
    return Path("/Volumes/Samsung SSD/external-src")


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


def _read_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _has_any(text: str, patterns: list[str]) -> bool:
    lowered = text.lower()
    return any(pattern.lower() in lowered for pattern in patterns)


def _source_file_paths(source_files: dict[str, Path] | None) -> dict[str, Path]:
    paths = _default_source_files()
    if source_files:
        paths.update(source_files)
    return paths


def _source_evidence(source_files: dict[str, Path]) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for label, path in source_files.items():
        text = _read_source(path)
        evidence[label] = {
            "path": str(path),
            "exists": bool(text),
            "builds_csm_script": _has_any(
                text,
                ["skbeg", "linseg", "spline", "rule"],
            ),
            "uses_dump_invocation": "DUMP !export_path 0 1" in text,
            "uses_servecsm_batch": _has_any(text, ["serveCSM", "ocsm"]),
            "explicit_pcurve_metadata_api": _has_any(
                text,
                [
                    "CurveOnSurface",
                    "BRep_Builder",
                    ".UpdateEdge",
                    "UpdateEdge(",
                    ".UpdateVertex",
                    "UpdateVertex(",
                    "EG_otherCurve",
                    "EG_makeGeometry",
                ],
            ),
            "post_export_repair_or_projection_api": _has_any(
                text,
                [
                    "BRepLib",
                    "ShapeFix_Edge",
                    "GeomProjLib",
                    "Geom2dAPI",
                ],
            ),
        }
    return evidence


def _external_source_inventory(external_src_root: Path) -> dict[str, Any]:
    if not external_src_root.exists():
        return {
            "root": str(external_src_root),
            "exists": False,
            "opencsm_or_egads_source_available": False,
            "matched_paths": [],
        }
    matched: list[str] = []
    for path in external_src_root.rglob("*"):
        if len(matched) >= 50:
            break
        lower_name = path.name.lower()
        if any(token in lower_name for token in ("opencsm", "egads", "ocsm")):
            matched.append(str(path))
    return {
        "root": str(external_src_root),
        "exists": True,
        "opencsm_or_egads_source_available": bool(matched),
        "matched_paths": matched,
    }


def _current_negative_controls(
    opcode_variant_probe: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(opcode_variant_probe, dict):
        return {}
    summary = opcode_variant_probe.get("variant_summary", {})
    return {
        "opcode_variant_status": opcode_variant_probe.get("opcode_variant_status"),
        "variant_count": (
            summary.get("variant_count") if isinstance(summary, dict) else None
        ),
        "materialized_variant_count": (
            summary.get("materialized_variant_count")
            if isinstance(summary, dict)
            else None
        ),
        "validated_variant_count": (
            summary.get("validated_variant_count")
            if isinstance(summary, dict)
            else None
        ),
        "recovered_variant_count": (
            summary.get("recovered_variant_count")
            if isinstance(summary, dict)
            else None
        ),
        "surface_count_guard_skipped_count": (
            summary.get("surface_count_guard_skipped_count")
            if isinstance(summary, dict)
            else None
        ),
        "best_station_edge_check_count": (
            summary.get("best_station_edge_check_count")
            if isinstance(summary, dict)
            else None
        ),
        "engineering_findings": opcode_variant_probe.get(
            "engineering_findings",
            [],
        ),
    }


def _source_boundary() -> dict[str, list[str]]:
    return {
        "hpa_mdo_controls": [
            "section_coordinates",
            "sketch_opcode_policy",
            "rule_grouping",
            "dump_invocation",
        ],
        "external_controls": [
            "opencsm_rule_loft_surface_construction",
            "opencsm_rule_loft_pcurve_metadata",
            "egads_step_export_metadata",
            "occt_shape_analysis_semantics_after_step_import",
        ],
        "post_export_hpa_mdo_diagnostics": [
            "same_parameter_shape_fix_sweeps",
            "bounded_existing_pcurve_rewrite_attempts",
            "projected_or_sampled_pcurve_negative_controls",
        ],
    }


def _status(
    *,
    blockers: list[str],
    evidence: dict[str, Any],
    current_negative_controls: dict[str, Any],
) -> ExportMetadataSourceAuditStatusType:
    if blockers:
        return "blocked"
    provider = evidence.get("provider", {})
    side_aware = evidence.get("side_aware", {})
    if (
        isinstance(provider, dict)
        and isinstance(side_aware, dict)
        and provider.get("builds_csm_script") is True
        and provider.get("uses_dump_invocation") is True
        and side_aware.get("builds_csm_script") is True
        and current_negative_controls.get("recovered_variant_count") == 0
    ):
        return "export_metadata_generation_source_boundary_captured"
    return "export_metadata_generation_source_boundary_incomplete"


def _engineering_findings(
    *,
    status: ExportMetadataSourceAuditStatusType,
    evidence: dict[str, Any],
    external_inventory: dict[str, Any],
    current_negative_controls: dict[str, Any],
) -> list[str]:
    if status == "blocked":
        return ["export_metadata_source_audit_blocked"]
    findings = ["export_metadata_source_boundary_audit_captured"]
    provider = evidence.get("provider", {})
    side_aware = evidence.get("side_aware", {})
    if isinstance(provider, dict) and provider.get("uses_dump_invocation") is True:
        findings.append("provider_export_uses_opencsm_rule_then_dump")
    if isinstance(side_aware, dict) and side_aware.get("builds_csm_script") is True:
        findings.append("side_aware_candidate_export_is_csm_script_level_control")
    csm_generation_labels = (
        "provider",
        "profile_resample",
        "side_aware",
        "opcode_variant",
    )
    if not any(
        isinstance(item := evidence.get(label), dict)
        and item.get("explicit_pcurve_metadata_api") is True
        for label in csm_generation_labels
    ):
        findings.append("hpa_mdo_csm_generation_has_no_explicit_pcurve_metadata_api")
    if current_negative_controls.get("recovered_variant_count") == 0:
        findings.append("report_local_opcode_variants_do_not_recover_metadata_gate")
    if (
        external_inventory.get("opencsm_or_egads_source_available")
        is not True
    ):
        findings.append("external_opencsm_egads_source_not_available_in_external_src")
    return list(dict.fromkeys(findings))


def _blocking_reasons(
    status: ExportMetadataSourceAuditStatusType,
    blockers: list[str],
) -> list[str]:
    reasons = list(blockers)
    if status != "export_metadata_generation_source_boundary_captured":
        reasons.append("export_metadata_source_boundary_incomplete")
    reasons.append("export_pcurve_metadata_generation_not_owned_by_hpa_mdo")
    reasons.append("side_aware_candidate_mesh_handoff_not_run")
    return list(dict.fromkeys(reasons))


def _next_actions(status: ExportMetadataSourceAuditStatusType) -> list[str]:
    if status == "blocked":
        return ["restore_export_metadata_source_audit_inputs"]
    return [
        "inspect_opencsm_egads_step_export_metadata_controls_or_add_owned_occ_export_path",
        "avoid_more_simple_csm_opcode_sweeps",
        "keep_mesh_handoff_blocked_until_station_metadata_gate_passes",
    ]


def build_main_wing_station_seam_export_metadata_source_audit_report(
    *,
    opcode_variant_probe_path: Path | None = None,
    source_files: dict[str, Path] | None = None,
    external_src_root: Path | None = None,
) -> MainWingStationSeamExportMetadataSourceAuditReport:
    opcode_path = (
        _default_opcode_variant_probe_path()
        if opcode_variant_probe_path is None
        else opcode_variant_probe_path
    )
    blockers: list[str] = []
    opcode_variant_probe = _load_json(
        opcode_path,
        blockers,
        "opcode_variant_probe",
    )
    resolved_source_files = _source_file_paths(source_files)
    evidence = _source_evidence(resolved_source_files)
    required_source_labels = ("provider", "side_aware", "opcode_variant")
    for label in required_source_labels:
        if not evidence.get(label, {}).get("exists"):
            blockers.append(f"{label}_source_missing")
    external_inventory = _external_source_inventory(
        _default_external_src_root()
        if external_src_root is None
        else external_src_root
    )
    negative_controls = _current_negative_controls(opcode_variant_probe)
    status = _status(
        blockers=blockers,
        evidence=evidence,
        current_negative_controls=negative_controls,
    )
    return MainWingStationSeamExportMetadataSourceAuditReport(
        audit_status=status,
        opcode_variant_probe_path=str(opcode_path),
        source_files={label: str(path) for label, path in resolved_source_files.items()},
        source_boundary=_source_boundary(),
        source_evidence=evidence,
        current_negative_controls=negative_controls,
        external_source_inventory=external_inventory,
        engineering_findings=_engineering_findings(
            status=status,
            evidence=evidence,
            external_inventory=external_inventory,
            current_negative_controls=negative_controls,
        ),
        blocking_reasons=_blocking_reasons(status, blockers),
        next_actions=_next_actions(status),
        limitations=[
            "This audit reads source and reports only; it does not mutate provider defaults.",
            "It does not run serveCSM, Gmsh, SU2_CFD, or convergence gates.",
            "It separates hpa-mdo CSM-script controls from OpenCSM/EGADS/OCCT metadata generation.",
            "CL acceptance remains a solver/convergence gate, not a source-audit output.",
        ],
    )


def write_main_wing_station_seam_export_metadata_source_audit_report(
    out_dir: Path,
    *,
    report: MainWingStationSeamExportMetadataSourceAuditReport | None = None,
    opcode_variant_probe_path: Path | None = None,
    source_files: dict[str, Path] | None = None,
    external_src_root: Path | None = None,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_station_seam_export_metadata_source_audit_report(
            opcode_variant_probe_path=opcode_variant_probe_path,
            source_files=source_files,
            external_src_root=external_src_root,
        )
    json_path = out_dir / "main_wing_station_seam_export_metadata_source_audit.v1.json"
    markdown_path = out_dir / "main_wing_station_seam_export_metadata_source_audit.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Main Wing Station Seam Export Metadata Source Audit v1",
        "",
        f"- status: `{report.audit_status}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        f"- opcode_variant_probe_path: `{report.opcode_variant_probe_path}`",
        f"- current_negative_controls: `{json.dumps(report.current_negative_controls, ensure_ascii=False)}`",
        "",
        "## Source Boundary",
        "",
    ]
    for key, values in report.source_boundary.items():
        lines.append(f"- {key}: `{json.dumps(values, ensure_ascii=False)}`")
    lines.extend(["", "## Engineering Findings", ""])
    lines.extend(f"- `{finding}`" for finding in report.engineering_findings)
    lines.extend(["", "## Blocking Reasons", ""])
    lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- `{action}`" for action in report.next_actions)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.limitations)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
