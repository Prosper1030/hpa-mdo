from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Literal

from pydantic import BaseModel, Field

from .main_wing_station_seam_profile_resample_strategy_probe import (
    _parse_csm_sections,
    _probe_step_surface_inventory,
    _write_command_log,
)
from .main_wing_station_seam_side_aware_brep_validation_probe import (
    build_main_wing_station_seam_side_aware_brep_validation_probe_report,
)
from .main_wing_station_seam_side_aware_parametrization_probe import (
    _build_candidate_csm,
    _float_list,
    _resolve_path,
    _side_parametrized_sections,
    _target_side_counts,
)


ExportFormatBoundaryStatusType = Literal[
    "export_format_boundary_all_formats_station_gate_valid",
    "export_format_boundary_step_loss_suspected",
    "export_format_boundary_step_suspect_non_step_validation_unavailable",
    "export_format_boundary_partial_recovery",
    "export_format_boundary_rule_loft_metadata_suspect",
    "export_format_boundary_materialization_failed",
    "export_format_boundary_validation_unavailable",
    "export_format_boundary_source_only_ready_for_materialization",
    "blocked",
]
FormatMaterializer = Callable[..., dict[str, Any]]
FormatValidator = Callable[..., dict[str, Any]]

DEFAULT_FORMATS = ["step", "brep", "egads"]
FORMAT_EXPORT_FILENAMES = {
    "step": "candidate_raw_dump.stp",
    "brep": "candidate_raw_dump.brep",
    "egads": "candidate_raw_dump.egads",
}


class MainWingStationSeamExportFormatBoundaryProbeReport(BaseModel):
    schema_version: Literal[
        "main_wing_station_seam_export_format_boundary_probe.v1"
    ] = "main_wing_station_seam_export_format_boundary_probe.v1"
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal[
        "report_only_station_seam_export_format_boundary_probe"
    ] = "report_only_station_seam_export_format_boundary_probe"
    production_default_changed: bool = False
    probe_status: ExportFormatBoundaryStatusType
    profile_parametrization_audit_path: str
    export_metadata_source_audit_path: str
    source_csm_path: str | None = None
    materialize_formats: bool = False
    formats: list[str] = Field(default_factory=list)
    target_station_y_m: list[float] = Field(default_factory=list)
    side_parametrization_summary: dict[str, Any] = Field(default_factory=dict)
    format_reports: list[dict[str, Any]] = Field(default_factory=list)
    format_summary: dict[str, Any] = Field(default_factory=dict)
    source_evidence: dict[str, Any] = Field(default_factory=dict)
    engineering_findings: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_report_root() -> Path:
    return _repo_root() / "hpa_meshing_package" / "docs" / "reports"


def _default_profile_parametrization_audit_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_profile_parametrization_audit"
        / "main_wing_station_seam_profile_parametrization_audit.v1.json"
    )


def _default_export_metadata_source_audit_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_station_seam_export_metadata_source_audit"
        / "main_wing_station_seam_export_metadata_source_audit.v1.json"
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


def _source_evidence(external_src_root: Path | None) -> dict[str, Any]:
    opencsm_header = None
    egads_io_source = None
    if external_src_root is not None:
        opencsm_header = external_src_root / "include" / "OpenCSM.h"
        egads_io_source = external_src_root / "src" / "EGADS" / "src" / "egadsIO.cpp"
    evidence: dict[str, Any] = {
        "external_src_root": None if external_src_root is None else str(external_src_root),
        "opencsm_dump_supported_extensions": [],
        "egads_save_model_branches": [],
    }
    if opencsm_header is not None and opencsm_header.exists():
        text = opencsm_header.read_text(encoding="utf-8", errors="ignore")
        evidence["opencsm_header_path"] = str(opencsm_header)
        evidence["opencsm_dump_supported_extensions"] = [
            extension
            for extension in [".stp", ".step", ".brep", ".egads"]
            if extension in text
        ]
    if egads_io_source is not None and egads_io_source.exists():
        text = egads_io_source.read_text(encoding="utf-8", errors="ignore")
        evidence["egads_io_source_path"] = str(egads_io_source)
        evidence["egads_save_model_branches"] = [
            branch
            for branch in ["STEPControl_Writer", ".brep", ".egads"]
            if branch in text
        ]
    return evidence


def _materialize_format_candidate(
    *,
    format_name: str,
    out_dir: Path,
    csm_text: str,
    export_filename: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    csm_path = out_dir / "candidate.csm"
    export_path = out_dir / export_filename
    command_log_path = out_dir / "ocsm.log"
    csm_path.write_text(csm_text, encoding="utf-8")

    batch_binary = shutil.which("serveCSM") or shutil.which("ocsm")
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
            "format": format_name,
            "csm_path": str(csm_path),
            "export_path": str(export_path),
            "command_log_path": str(command_log_path),
        }

    args = [batch_binary, "-batch", csm_path.name]
    try:
        completed = subprocess.run(
            args,
            cwd=str(out_dir),
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
            "format": format_name,
            "csm_path": str(csm_path),
            "export_path": str(export_path),
            "command_log_path": str(command_log_path),
            "timeout_seconds": float(timeout_seconds),
        }

    topology = _probe_step_surface_inventory(export_path) if export_path.exists() else {}
    return {
        "status": (
            "materialized"
            if completed.returncode == 0 and export_path.exists()
            else "failed"
        ),
        "format": format_name,
        "returncode": completed.returncode,
        "csm_path": str(csm_path),
        "export_path": str(export_path),
        "export_exists": export_path.exists(),
        "export_size_bytes": export_path.stat().st_size if export_path.exists() else None,
        "command_log_path": str(command_log_path),
        "stdout_tail": (completed.stdout or "")[-1000:],
        "stderr_tail": (completed.stderr or "")[-1000:],
        "topology": topology,
    }


def _validate_format_candidate(
    *,
    format_name: str,
    export_path: Path,
    station_y_targets: list[float],
) -> dict[str, Any]:
    report = build_main_wing_station_seam_side_aware_brep_validation_probe_report(
        candidate_step_path=export_path,
        station_y_targets=station_y_targets,
    )
    payload = report.model_dump(mode="json")
    payload["validated_export_format"] = format_name
    hotspot_summary = payload.get("hotspot_summary", {})
    if (
        format_name != "step"
        and isinstance(hotspot_summary, dict)
        and hotspot_summary.get("hotspot_status") == "failed_to_read_step"
    ):
        payload["original_probe_status"] = payload.get("probe_status")
        payload["probe_status"] = "side_aware_candidate_station_brep_validation_unavailable"
        payload["format_boundary_normalization_reason"] = (
            "existing_station_hotspot_gate_uses_step_reader_for_non_step_export"
        )
    return payload


def _format_summary(format_reports: list[dict[str, Any]]) -> dict[str, Any]:
    materialized = [
        report
        for report in format_reports
        if report.get("materialization", {}).get("status") == "materialized"
    ]
    validated = [
        report
        for report in format_reports
        if isinstance(report.get("validation"), dict)
        and report.get("validation", {}).get("probe_status") is not None
    ]
    passed = [
        report
        for report in validated
        if report.get("validation", {}).get("probe_status")
        == "side_aware_candidate_station_brep_edges_valid"
    ]
    suspect = [
        report
        for report in validated
        if report.get("validation", {}).get("probe_status")
        == "side_aware_candidate_station_brep_edges_suspect"
    ]
    unavailable = [
        report
        for report in validated
        if report.get("validation", {}).get("probe_status")
        == "side_aware_candidate_station_brep_validation_unavailable"
    ]
    return {
        "format_count": len(format_reports),
        "materialized_format_count": len(materialized),
        "validated_format_count": len(validated),
        "passed_format_count": len(passed),
        "suspect_format_count": len(suspect),
        "validation_unavailable_format_count": len(unavailable),
        "passed_formats": [str(report.get("format")) for report in passed],
        "suspect_formats": [str(report.get("format")) for report in suspect],
        "validation_unavailable_formats": [
            str(report.get("format")) for report in unavailable
        ],
    }


def _validation_status(validation: dict[str, Any]) -> str:
    status = validation.get("probe_status")
    return str(status) if status is not None else "not_run"


def _status(
    *,
    blockers: list[str],
    materialize_formats: bool,
    format_reports: list[dict[str, Any]],
    summary: dict[str, Any],
) -> ExportFormatBoundaryStatusType:
    if blockers:
        return "blocked"
    if not materialize_formats:
        return "export_format_boundary_source_only_ready_for_materialization"
    if not format_reports or int(summary.get("materialized_format_count") or 0) == 0:
        return "export_format_boundary_materialization_failed"
    if int(summary.get("validated_format_count") or 0) == 0:
        return "export_format_boundary_validation_unavailable"

    passed_formats = set(summary.get("passed_formats", []))
    suspect_formats = set(summary.get("suspect_formats", []))
    requested_formats = {str(report.get("format")) for report in format_reports}
    if passed_formats and passed_formats == requested_formats:
        return "export_format_boundary_all_formats_station_gate_valid"
    if "step" in suspect_formats and passed_formats.intersection({"brep", "egads"}):
        return "export_format_boundary_step_loss_suspected"
    if passed_formats:
        return "export_format_boundary_partial_recovery"
    if "step" in suspect_formats and int(
        summary.get("validation_unavailable_format_count") or 0
    ) > 0:
        return "export_format_boundary_step_suspect_non_step_validation_unavailable"
    if int(summary.get("suspect_format_count") or 0) > 0:
        return "export_format_boundary_rule_loft_metadata_suspect"
    return "export_format_boundary_validation_unavailable"


def _engineering_findings(
    *,
    status: ExportFormatBoundaryStatusType,
    summary: dict[str, Any],
    source_evidence: dict[str, Any],
) -> list[str]:
    if status == "blocked":
        return ["export_format_boundary_probe_blocked"]
    findings = ["export_format_boundary_probe_captured"]
    if source_evidence.get("opencsm_dump_supported_extensions"):
        findings.append("opencsm_dump_supports_step_brep_egads_extensions")
    if status == "export_format_boundary_step_loss_suspected":
        findings.append("step_serialization_or_step_import_metadata_loss_suspected")
    if status == "export_format_boundary_step_suspect_non_step_validation_unavailable":
        findings.append("step_export_station_metadata_gate_suspect")
        findings.append("non_step_format_station_gate_reader_unavailable")
    if status == "export_format_boundary_rule_loft_metadata_suspect":
        findings.append("all_importable_formats_failed_station_metadata_gate")
    if status in {
        "export_format_boundary_all_formats_station_gate_valid",
        "export_format_boundary_partial_recovery",
    }:
        findings.append("at_least_one_export_format_passed_station_metadata_gate")
    if int(summary.get("validation_unavailable_format_count") or 0) > 0:
        findings.append("some_export_format_validations_unavailable")
    return list(dict.fromkeys(findings))


def _blocking_reasons(
    *,
    status: ExportFormatBoundaryStatusType,
    blockers: list[str],
) -> list[str]:
    reasons = list(blockers)
    if status == "export_format_boundary_source_only_ready_for_materialization":
        reasons.append("export_format_boundary_materialization_not_run")
    if status == "export_format_boundary_materialization_failed":
        reasons.append("export_format_boundary_materialization_failed")
    if status == "export_format_boundary_validation_unavailable":
        reasons.append("export_format_boundary_validation_unavailable")
    if status == "export_format_boundary_step_loss_suspected":
        reasons.append("step_serialization_or_step_import_metadata_loss_suspected")
        reasons.append("recovered_non_step_format_mesh_handoff_not_run")
    if status == "export_format_boundary_step_suspect_non_step_validation_unavailable":
        reasons.append("step_export_station_metadata_gate_suspect")
        reasons.append("non_step_format_station_gate_reader_unavailable")
        reasons.append("side_aware_candidate_mesh_handoff_not_run")
    if status == "export_format_boundary_partial_recovery":
        reasons.append("recovered_format_mesh_handoff_not_run")
    if status == "export_format_boundary_rule_loft_metadata_suspect":
        reasons.append("export_format_boundary_all_importable_formats_failed_station_gate")
        reasons.append("side_aware_candidate_mesh_handoff_not_run")
    if status == "blocked" and not reasons:
        reasons.append("export_format_boundary_probe_blocked")
    return list(dict.fromkeys(reasons))


def _next_actions(status: ExportFormatBoundaryStatusType) -> list[str]:
    if status == "export_format_boundary_step_loss_suspected":
        return [
            "run_gmsh_handoff_on_recovered_brep_without_promoting_default",
            "trace_step_writer_or_step_reader_metadata_loss",
            "keep_step_route_blocked_until_station_metadata_gate_passes",
        ]
    if status == "export_format_boundary_step_suspect_non_step_validation_unavailable":
        return [
            "add_brep_capable_station_hotspot_reader_or_occ_import_gate",
            "rerun_format_boundary_probe_with_comparable_non_step_gate",
            "keep_mesh_handoff_blocked_until_non_step_gate_is_comparable",
        ]
    if status == "export_format_boundary_partial_recovery":
        return [
            "run_mesh_handoff_on_recovered_export_format_without_promoting_default",
            "compare_marker_ownership_on_recovered_format",
        ]
    if status == "export_format_boundary_rule_loft_metadata_suspect":
        return [
            "inspect_opencsm_egads_rule_loft_pcurve_generation",
            "avoid_more_simple_csm_opcode_sweeps",
            "do_not_run_mesh_handoff_until_station_metadata_gate_passes",
        ]
    if status == "export_format_boundary_all_formats_station_gate_valid":
        return [
            "run_side_aware_candidate_mesh_handoff_without_promoting_default",
            "verify_wall_farfield_force_marker_ownership_on_recovered_geometry",
        ]
    if status == "export_format_boundary_source_only_ready_for_materialization":
        return ["materialize_export_format_boundary_candidates"]
    if status == "export_format_boundary_materialization_failed":
        return ["inspect_export_format_boundary_ocsm_logs"]
    if status == "export_format_boundary_validation_unavailable":
        return ["restore_occt_or_gmsh_importers_for_format_boundary_validation"]
    return ["restore_export_format_boundary_inputs"]


def build_main_wing_station_seam_export_format_boundary_probe_report(
    *,
    profile_parametrization_audit_path: Path | None = None,
    export_metadata_source_audit_path: Path | None = None,
    formats: list[str] | None = None,
    materialize_formats: bool = False,
    materialization_root: Path | None = None,
    timeout_seconds: float = 120.0,
    target_upper_side_point_count: int | None = 30,
    target_lower_side_point_count: int | None = 30,
    external_src_root: Path | None = None,
    format_materializer: FormatMaterializer | None = None,
    format_validator: FormatValidator | None = None,
) -> MainWingStationSeamExportFormatBoundaryProbeReport:
    profile_path = (
        _default_profile_parametrization_audit_path()
        if profile_parametrization_audit_path is None
        else profile_parametrization_audit_path
    )
    source_audit_path = (
        _default_export_metadata_source_audit_path()
        if export_metadata_source_audit_path is None
        else export_metadata_source_audit_path
    )
    selected_formats = list(formats or DEFAULT_FORMATS)
    blockers: list[str] = []
    unknown_formats = [
        format_name
        for format_name in selected_formats
        if format_name not in FORMAT_EXPORT_FILENAMES
    ]
    blockers.extend(f"unknown_format:{format_name}" for format_name in unknown_formats)
    profile_payload = _load_json(profile_path, blockers, "profile_parametrization_audit")
    _load_json(source_audit_path, blockers, "export_metadata_source_audit")
    source_csm_path = _resolve_path(
        profile_payload.get("source_csm_path")
        if isinstance(profile_payload, dict)
        else None
    )
    if source_csm_path is None:
        blockers.append("source_csm_path_missing")
    elif not source_csm_path.exists():
        blockers.append("source_csm_missing")
    target_station_y_m = _float_list(
        profile_payload.get("target_station_y_m")
        if isinstance(profile_payload, dict)
        else []
    )
    if not target_station_y_m:
        blockers.append("target_station_y_missing")

    sections = _parse_csm_sections(source_csm_path, blockers) if source_csm_path else []
    side_summary: dict[str, Any] = {}
    format_reports: list[dict[str, Any]] = []
    if not blockers and source_csm_path is not None:
        upper_target, lower_target = _target_side_counts(
            sections,
            target_upper_side_point_count=target_upper_side_point_count,
            target_lower_side_point_count=target_lower_side_point_count,
        )
        side_sections, _, side_summary = _side_parametrized_sections(
            sections,
            upper_target_count=upper_target,
            lower_target_count=lower_target,
        )
        root = (
            _default_report_root()
            / "main_wing_station_seam_export_format_boundary_probe"
            / "artifacts"
            if materialization_root is None
            else materialization_root
        )
        materializer = format_materializer or _materialize_format_candidate
        validator = format_validator or _validate_format_candidate
        for format_name in selected_formats:
            export_filename = FORMAT_EXPORT_FILENAMES[format_name]
            out_dir = root / format_name
            csm_text = _build_candidate_csm(
                sections=side_sections,
                source_csm_path=source_csm_path,
                export_filename=export_filename,
            )
            materialization: dict[str, Any] = {
                "status": "not_requested",
                "candidate_csm_text_available": True,
                "export_filename": export_filename,
            }
            validation: dict[str, Any] = {}
            if materialize_formats:
                materialization = materializer(
                    format_name=format_name,
                    out_dir=out_dir,
                    csm_text=csm_text,
                    export_filename=export_filename,
                    timeout_seconds=timeout_seconds,
                )
                if materialization.get("status") == "materialized":
                    export_path = Path(str(materialization.get("export_path")))
                    validation = validator(
                        format_name=format_name,
                        export_path=export_path,
                        station_y_targets=target_station_y_m,
                    )
            format_reports.append(
                {
                    "format": format_name,
                    "export_filename": export_filename,
                    "materialization": materialization,
                    "validation_status": _validation_status(validation),
                    "validation": validation,
                }
            )
    summary = _format_summary(format_reports)
    source_evidence = _source_evidence(external_src_root)
    status = _status(
        blockers=blockers,
        materialize_formats=materialize_formats,
        format_reports=format_reports,
        summary=summary,
    )
    return MainWingStationSeamExportFormatBoundaryProbeReport(
        probe_status=status,
        profile_parametrization_audit_path=str(profile_path),
        export_metadata_source_audit_path=str(source_audit_path),
        source_csm_path=str(source_csm_path) if source_csm_path else None,
        materialize_formats=materialize_formats,
        formats=selected_formats,
        target_station_y_m=target_station_y_m,
        side_parametrization_summary=side_summary,
        format_reports=format_reports,
        format_summary=summary,
        source_evidence=source_evidence,
        engineering_findings=_engineering_findings(
            status=status,
            summary=summary,
            source_evidence=source_evidence,
        ),
        blocking_reasons=_blocking_reasons(status=status, blockers=blockers),
        next_actions=_next_actions(status),
        limitations=[
            "This probe changes only report-local side-aware CSM exports; it does not change provider defaults.",
            "STEP, BREP, and EGADS are export-format boundary diagnostics, not CFD-ready geometry claims.",
            "A passing station metadata gate still needs mesh handoff, marker ownership, SU2 handoff, solver, CL acceptance, and convergence gates.",
            "A solver smoke with CL < 1 at V=6.5 m/s is not an HPA engineering acceptance pass.",
        ],
    )


def write_main_wing_station_seam_export_format_boundary_probe_report(
    out_dir: Path,
    *,
    report: MainWingStationSeamExportFormatBoundaryProbeReport | None = None,
    profile_parametrization_audit_path: Path | None = None,
    export_metadata_source_audit_path: Path | None = None,
    formats: list[str] | None = None,
    materialize_formats: bool = False,
    materialization_root: Path | None = None,
    timeout_seconds: float = 120.0,
    target_upper_side_point_count: int | None = 30,
    target_lower_side_point_count: int | None = 30,
    external_src_root: Path | None = None,
    format_materializer: FormatMaterializer | None = None,
    format_validator: FormatValidator | None = None,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_station_seam_export_format_boundary_probe_report(
            profile_parametrization_audit_path=profile_parametrization_audit_path,
            export_metadata_source_audit_path=export_metadata_source_audit_path,
            formats=formats,
            materialize_formats=materialize_formats,
            materialization_root=materialization_root,
            timeout_seconds=timeout_seconds,
            target_upper_side_point_count=target_upper_side_point_count,
            target_lower_side_point_count=target_lower_side_point_count,
            external_src_root=external_src_root,
            format_materializer=format_materializer,
            format_validator=format_validator,
        )
    json_path = out_dir / "main_wing_station_seam_export_format_boundary_probe.v1.json"
    markdown_path = out_dir / "main_wing_station_seam_export_format_boundary_probe.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Main Wing Station Seam Export Format Boundary Probe v1",
        "",
        f"- probe_status: `{report.probe_status}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        f"- source_csm_path: `{report.source_csm_path}`",
        f"- formats: `{', '.join(report.formats)}`",
        f"- materialize_formats: `{report.materialize_formats}`",
        f"- target_station_y_m: `{json.dumps(report.target_station_y_m, ensure_ascii=False)}`",
        f"- format_summary: `{json.dumps(report.format_summary, ensure_ascii=False)}`",
        "",
        "## Format Reports",
        "",
    ]
    for format_report in report.format_reports:
        lines.append(f"- `{json.dumps(format_report, ensure_ascii=False)}`")
    lines.extend(["", "## Source Evidence", ""])
    for key, value in report.source_evidence.items():
        lines.append(f"- `{key}`: `{json.dumps(value, ensure_ascii=False)}`")
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
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
