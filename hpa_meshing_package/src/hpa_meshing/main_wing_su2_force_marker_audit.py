from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


AuditStatusType = Literal["pass", "warn", "blocked", "unavailable"]


class MainWingSU2ForceMarkerAuditReport(BaseModel):
    schema_version: Literal["main_wing_su2_force_marker_audit.v1"] = (
        "main_wing_su2_force_marker_audit.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_existing_su2_handoff"] = (
        "report_only_existing_su2_handoff"
    )
    production_default_changed: bool = False
    audit_status: AuditStatusType
    source_su2_probe_report_path: str | None = None
    su2_handoff_path: str | None = None
    runtime_cfg_path: str | None = None
    source_marker_summary_path: str | None = None
    marker_contract: Dict[str, Any] = Field(default_factory=dict)
    cfg_markers: Dict[str, Any] = Field(default_factory=dict)
    mesh_marker_summary: Dict[str, Any] = Field(default_factory=dict)
    flow_reference_observed: Dict[str, Any] = Field(default_factory=dict)
    checks: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    engineering_flags: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def _default_report_root() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "reports"


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _repo_root_from_report_root(report_root: Path) -> Path | None:
    try:
        return report_root.resolve().parents[2]
    except IndexError:
        return None


def _resolve_path(
    raw_path: Any,
    *,
    report_root: Path,
    anchor_path: Path | None = None,
) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path:
        return None
    path = Path(raw_path)
    candidates = [path]
    repo_root = _repo_root_from_report_root(report_root)
    if not path.is_absolute() and repo_root is not None:
        candidates.append(repo_root / path)
    if not path.is_absolute() and anchor_path is not None:
        candidates.append(anchor_path.parent / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def _default_source_probe_path(report_root: Path) -> Path:
    return (
        report_root
        / "main_wing_openvsp_reference_su2_handoff_probe"
        / "main_wing_openvsp_reference_su2_handoff_probe.v1.json"
    )


def _committed_handoff_path(source_probe_path: Path) -> Path:
    return source_probe_path.parent / "artifacts" / "su2_handoff.json"


def _committed_runtime_cfg_path(source_probe_path: Path) -> Path:
    return source_probe_path.parent / "artifacts" / "su2_runtime.cfg"


def _selected_handoff_path(
    source_probe: dict[str, Any] | None,
    *,
    report_root: Path,
    source_probe_path: Path,
) -> Path | None:
    committed = _committed_handoff_path(source_probe_path)
    if committed.exists():
        return committed.resolve()
    return _resolve_path(
        source_probe.get("su2_handoff_path") if isinstance(source_probe, dict) else None,
        report_root=report_root,
        anchor_path=source_probe_path,
    )


def _selected_runtime_cfg_path(
    handoff: dict[str, Any] | None,
    *,
    report_root: Path,
    source_probe_path: Path,
) -> Path | None:
    committed = _committed_runtime_cfg_path(source_probe_path)
    if committed.exists():
        return committed.resolve()
    return _resolve_path(
        handoff.get("runtime_cfg_path") if isinstance(handoff, dict) else None,
        report_root=report_root,
        anchor_path=source_probe_path,
    )


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _parse_runtime_cfg(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    parsed: dict[str, Any] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%") or "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        parsed[key] = value
    return parsed


def _cfg_tuple(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    stripped = value.strip()
    if stripped.startswith("(") and stripped.endswith(")"):
        stripped = stripped[1:-1]
    return [item.strip() for item in stripped.split(",") if item.strip()]


def _cfg_float(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", value)
    return _as_float(match.group(0)) if match else None


def _cfg_velocity_x(value: Any) -> float | None:
    values = _cfg_tuple(value)
    return _cfg_float(values[0]) if values else None


def _check(status: str, observed: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    return {"status": status, "observed": observed, "expected": expected}


def _mesh_marker_summary(
    handoff: dict[str, Any] | None,
    *,
    report_root: Path,
    source_probe_path: Path,
) -> tuple[dict[str, Any], Path | None]:
    provenance = handoff.get("provenance", {}) if isinstance(handoff, dict) else {}
    marker_path = _resolve_path(
        provenance.get("source_marker_summary") if isinstance(provenance, dict) else None,
        report_root=report_root,
        anchor_path=source_probe_path,
    )
    return _load_json(marker_path) or {}, marker_path


def build_main_wing_su2_force_marker_audit_report(
    *,
    report_root: Path | None = None,
    source_su2_probe_report_path: Path | None = None,
) -> MainWingSU2ForceMarkerAuditReport:
    root = _default_report_root() if report_root is None else report_root
    source_probe_path = (
        _default_source_probe_path(root)
        if source_su2_probe_report_path is None
        else source_su2_probe_report_path
    )
    source_probe = _load_json(source_probe_path)
    handoff_path = _selected_handoff_path(
        source_probe,
        report_root=root,
        source_probe_path=source_probe_path,
    )
    handoff = _load_json(handoff_path)
    runtime_cfg_path = _selected_runtime_cfg_path(
        handoff,
        report_root=root,
        source_probe_path=source_probe_path,
    )
    cfg = _parse_runtime_cfg(runtime_cfg_path)
    marker_summary, marker_summary_path = _mesh_marker_summary(
        handoff,
        report_root=root,
        source_probe_path=source_probe_path,
    )

    mesh_markers = handoff.get("mesh_markers", {}) if isinstance(handoff, dict) else {}
    force_provenance = (
        handoff.get("force_surface_provenance", {}) if isinstance(handoff, dict) else {}
    )
    reference = handoff.get("reference_geometry", {}) if isinstance(handoff, dict) else {}
    runtime = handoff.get("runtime", {}) if isinstance(handoff, dict) else {}
    flow_conditions = (
        runtime.get("flow_conditions", {}) if isinstance(runtime, dict) else {}
    )
    wall_marker = mesh_markers.get("wall") if isinstance(mesh_markers, dict) else None
    farfield_marker = (
        mesh_markers.get("farfield") if isinstance(mesh_markers, dict) else None
    )

    cfg_markers = {
        "MARKER_EULER": _cfg_tuple(cfg.get("MARKER_EULER")),
        "MARKER_MONITORING": _cfg_tuple(cfg.get("MARKER_MONITORING")),
        "MARKER_PLOTTING": _cfg_tuple(cfg.get("MARKER_PLOTTING")),
        "MARKER_FAR": _cfg_tuple(cfg.get("MARKER_FAR")),
    }
    marker_contract = {
        "wall_marker": wall_marker,
        "farfield_marker": farfield_marker,
        "monitoring_markers": (
            mesh_markers.get("monitoring", []) if isinstance(mesh_markers, dict) else []
        ),
        "plotting_markers": (
            mesh_markers.get("plotting", []) if isinstance(mesh_markers, dict) else []
        ),
        "euler_markers": (
            mesh_markers.get("euler", []) if isinstance(mesh_markers, dict) else []
        ),
        "force_surface_gate_status": (
            force_provenance.get("gate_status")
            if isinstance(force_provenance, dict)
            else None
        ),
        "force_surface_scope": (
            force_provenance.get("scope") if isinstance(force_provenance, dict) else None
        ),
    }

    main_wing_marker = (
        marker_summary.get(str(wall_marker), {}) if isinstance(marker_summary, dict) else {}
    )
    farfield_marker_summary = (
        marker_summary.get(str(farfield_marker), {})
        if isinstance(marker_summary, dict)
        else {}
    )
    reference_warnings = (
        reference.get("warnings", []) if isinstance(reference, dict) else []
    )
    flow_reference_observed = {
        "velocity_mps": (
            _as_float(flow_conditions.get("velocity_mps"))
            if isinstance(flow_conditions, dict)
            else None
        ),
        "cfg_velocity_x_mps": _cfg_velocity_x(cfg.get("INC_VELOCITY_INIT")),
        "ref_area_m2": _as_float(reference.get("ref_area")) if isinstance(reference, dict) else None,
        "cfg_ref_area_m2": _cfg_float(cfg.get("REF_AREA")),
        "ref_length_m": _as_float(reference.get("ref_length")) if isinstance(reference, dict) else None,
        "cfg_ref_length_m": _cfg_float(cfg.get("REF_LENGTH")),
        "wall_boundary_condition": (
            runtime.get("wall_boundary_condition") if isinstance(runtime, dict) else None
        ),
        "solver": runtime.get("solver") if isinstance(runtime, dict) else None,
    }

    checks: dict[str, dict[str, Any]] = {}
    force_surface_ok = (
        isinstance(force_provenance, dict)
        and force_provenance.get("gate_status") == "pass"
        and force_provenance.get("matches_wall_marker") is True
        and force_provenance.get("primary_group", {}).get("element_count", 0) > 0
    )
    checks["force_surface_provenance"] = _check(
        "pass" if force_surface_ok else "blocked",
        {
            "gate_status": force_provenance.get("gate_status")
            if isinstance(force_provenance, dict)
            else None,
            "matches_wall_marker": force_provenance.get("matches_wall_marker")
            if isinstance(force_provenance, dict)
            else None,
            "primary_group": force_provenance.get("primary_group", {})
            if isinstance(force_provenance, dict)
            else {},
        },
        {"gate_status": "pass", "matches_wall_marker": True, "element_count": "> 0"},
    )
    cfg_marker_ok = (
        wall_marker in cfg_markers["MARKER_EULER"]
        and wall_marker in cfg_markers["MARKER_MONITORING"]
        and wall_marker in cfg_markers["MARKER_PLOTTING"]
        and farfield_marker in cfg_markers["MARKER_FAR"]
    )
    checks["runtime_cfg_markers"] = _check(
        "pass" if cfg_marker_ok else "blocked",
        cfg_markers,
        {
            "MARKER_EULER": wall_marker,
            "MARKER_MONITORING": wall_marker,
            "MARKER_PLOTTING": wall_marker,
            "MARKER_FAR": farfield_marker,
        },
    )
    mesh_marker_ok = (
        main_wing_marker.get("exists") is True
        and main_wing_marker.get("element_count", 0) > 0
        and farfield_marker_summary.get("exists") is True
        and farfield_marker_summary.get("element_count", 0) > 0
    )
    checks["mesh_marker_counts"] = _check(
        "pass" if mesh_marker_ok else "blocked",
        {
            "wall_marker": main_wing_marker,
            "farfield_marker": farfield_marker_summary,
        },
        {"main_wing_elements": "> 0", "farfield_elements": "> 0"},
    )
    flow_reference_ok = (
        flow_reference_observed["velocity_mps"] == 6.5
        and flow_reference_observed["cfg_velocity_x_mps"] == 6.5
        and (flow_reference_observed["ref_area_m2"] or 0.0) > 0.0
        and flow_reference_observed["ref_area_m2"]
        == flow_reference_observed["cfg_ref_area_m2"]
        and flow_reference_observed["ref_length_m"]
        == flow_reference_observed["cfg_ref_length_m"]
    )
    checks["flow_reference_consistency"] = _check(
        "pass" if flow_reference_ok else "blocked",
        flow_reference_observed,
        {"velocity_mps": 6.5, "ref_area_matches_cfg": True, "ref_length_matches_cfg": True},
    )

    engineering_flags: list[str] = []
    blocking_reasons: list[str] = []
    for name, check in checks.items():
        if check["status"] == "blocked":
            blocking_reasons.append(f"{name}_blocked")
    if flow_reference_observed["wall_boundary_condition"] == "euler":
        engineering_flags.append("main_wing_solver_wall_bc_is_euler_smoke_not_viscous")
    if reference_warnings:
        engineering_flags.append("main_wing_reference_geometry_warn")
    if not blocking_reasons and engineering_flags:
        audit_status: AuditStatusType = "warn"
    elif blocking_reasons:
        audit_status = "blocked"
    else:
        audit_status = "pass"

    next_actions = []
    if "runtime_cfg_markers_blocked" in blocking_reasons:
        next_actions.append("repair_su2_marker_mapping_before_more_solver_runs")
    if "main_wing_solver_wall_bc_is_euler_smoke_not_viscous" in engineering_flags:
        next_actions.append("record_euler_wall_as_solver_smoke_scope_not_viscous_cfd")
    if "main_wing_reference_geometry_warn" in engineering_flags:
        next_actions.append("resolve_reference_moment_origin_before_force_claims")
    if audit_status in {"pass", "warn"}:
        next_actions.append("compare_surface_force_outputs_against_vspaero_panel_reference")

    return MainWingSU2ForceMarkerAuditReport(
        audit_status=audit_status,
        source_su2_probe_report_path=str(source_probe_path),
        su2_handoff_path=None if handoff_path is None else str(handoff_path),
        runtime_cfg_path=None if runtime_cfg_path is None else str(runtime_cfg_path),
        source_marker_summary_path=(
            None if marker_summary_path is None else str(marker_summary_path)
        ),
        marker_contract=marker_contract,
        cfg_markers=cfg_markers,
        mesh_marker_summary={
            "wall_marker": main_wing_marker,
            "farfield_marker": farfield_marker_summary,
        },
        flow_reference_observed=flow_reference_observed,
        checks=checks,
        engineering_flags=engineering_flags,
        blocking_reasons=blocking_reasons,
        next_actions=list(dict.fromkeys(next_actions)),
        limitations=[
            "This audit reads existing handoff/config/mesh-marker artifacts only and does not run SU2.",
            "Euler wall boundary conditions are valid smoke-route evidence, not viscous CFD readiness.",
            "A marker audit cannot prove coefficient correctness without surface force output comparison.",
        ],
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _render_markdown(report: MainWingSU2ForceMarkerAuditReport) -> str:
    lines = [
        "# Main Wing SU2 Force Marker Audit v1",
        "",
        "This report reads existing SU2 handoff artifacts only; it does not execute SU2.",
        "",
        f"- audit_status: `{report.audit_status}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        f"- su2_handoff_path: `{report.su2_handoff_path}`",
        f"- runtime_cfg_path: `{report.runtime_cfg_path}`",
        "",
        "## Checks",
        "",
        "| check | status |",
        "|---|---|",
    ]
    for name, check in report.checks.items():
        lines.append(f"| `{name}` | `{check.get('status')}` |")
    lines.extend(["", "## Flow Reference Observed", ""])
    for key, value in report.flow_reference_observed.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Engineering Flags", ""])
    lines.extend(f"- `{flag}`" for flag in report.engineering_flags)
    lines.extend(["", "## Blocking Reasons", ""])
    lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- `{action}`" for action in report.next_actions)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_main_wing_su2_force_marker_audit_report(
    out_dir: Path,
    *,
    report: MainWingSU2ForceMarkerAuditReport | None = None,
    report_root: Path | None = None,
    source_su2_probe_report_path: Path | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_su2_force_marker_audit_report(
            report_root=report_root,
            source_su2_probe_report_path=source_su2_probe_report_path,
        )
    json_path = out_dir / "main_wing_su2_force_marker_audit.v1.json"
    markdown_path = out_dir / "main_wing_su2_force_marker_audit.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
