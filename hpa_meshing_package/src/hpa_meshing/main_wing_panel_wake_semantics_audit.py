from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


AuditStatusType = Literal[
    "semantics_gap_observed",
    "insufficient_evidence",
    "no_semantics_gap_observed",
]


class MainWingPanelWakeSemanticsAuditReport(BaseModel):
    schema_version: Literal["main_wing_panel_wake_semantics_audit.v1"] = (
        "main_wing_panel_wake_semantics_audit.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_existing_artifacts"] = (
        "report_only_existing_artifacts"
    )
    production_default_changed: bool = False
    hpa_standard_velocity_mps: float = 6.5
    minimum_acceptable_cl: float = 1.0
    audit_status: AuditStatusType
    panel_wake_observed: Dict[str, Any] = Field(default_factory=dict)
    su2_semantics_observed: Dict[str, Any] = Field(default_factory=dict)
    normal_audit_observed: Dict[str, Any] = Field(default_factory=dict)
    engineering_findings: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def _default_report_root() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "reports"


def _default_runtime_cfg_path() -> Path:
    return (
        _default_report_root()
        / "main_wing_openvsp_reference_solver_smoke_probe_iter80"
        / "artifacts"
        / "source_su2"
        / "su2_runtime.cfg"
    )


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _reports(root: Path) -> dict[str, dict[str, Any] | None]:
    return {
        "panel": _load_json(
            root
            / "main_wing_vspaero_panel_reference_probe"
            / "main_wing_vspaero_panel_reference_probe.v1.json"
        ),
        "gap": _load_json(
            root
            / "main_wing_panel_su2_lift_gap_debug"
            / "main_wing_panel_su2_lift_gap_debug.v1.json"
        ),
        "normal": _load_json(
            root
            / "main_wing_su2_mesh_normal_audit"
            / "main_wing_su2_mesh_normal_audit.v1.json"
        ),
    }


def _parse_cfg(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"status": "unavailable", "path": None, "values": {}}
    values: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%") or "=" not in stripped:
            continue
        key, raw = stripped.split("=", 1)
        key = key.strip()
        raw = raw.strip()
        if raw.startswith("(") and raw.endswith(")"):
            values[key] = [
                item.strip()
                for item in raw[1:-1].split(",")
                if item.strip()
            ]
        else:
            values[key] = raw
    return {"status": "available", "path": str(path), "values": values}


def _cfg_float_list(values: dict[str, Any], key: str) -> list[float]:
    raw = values.get(key)
    if isinstance(raw, list):
        parsed = [_as_float(value) for value in raw]
        return [value for value in parsed if value is not None]
    if isinstance(raw, str):
        parsed = [_as_float(value) for value in re.split(r"[,\s]+", raw) if value]
        return [value for value in parsed if value is not None]
    return []


def _panel_wake_observed(panel: dict[str, Any] | None) -> dict[str, Any]:
    setup = panel.get("setup_reference", {}) if isinstance(panel, dict) else {}
    selected = panel.get("selected_case", {}) if isinstance(panel, dict) else {}
    cltot = _as_float(selected.get("CLtot")) if isinstance(selected, dict) else None
    cli = _as_float(selected.get("CLi")) if isinstance(selected, dict) else None
    inviscid_fraction = cli / cltot if cli is not None and cltot not in {None, 0.0} else None
    wake_iters = _as_float(setup.get("WakeIters")) if isinstance(setup, dict) else None
    wake_nodes = _as_float(setup.get("NumWakeNodes")) if isinstance(setup, dict) else None
    return {
        "status": "available" if isinstance(panel, dict) else "unavailable",
        "source_setup_path": (
            panel.get("source_setup_path") if isinstance(panel, dict) else None
        ),
        "velocity_mps": _as_float(setup.get("Vinf")) if isinstance(setup, dict) else None,
        "num_wake_nodes": wake_nodes,
        "wake_iters": wake_iters,
        "implicit_wake": (
            _as_float(setup.get("ImplicitWake")) if isinstance(setup, dict) else None
        ),
        "freeze_wake_at_iteration": (
            _as_float(setup.get("FreezeWakeAtIteration"))
            if isinstance(setup, dict)
            else None
        ),
        "clo": _as_float(selected.get("CLo")) if isinstance(selected, dict) else None,
        "clo_component_label": "viscous_or_other_surface_integration_component",
        "cli": cli,
        "cli_component_label": "inviscid_surface_integration_component",
        "cltot": cltot,
        "clwtot": (
            _as_float(selected.get("CLwtot")) if isinstance(selected, dict) else None
        ),
        "cliw": _as_float(selected.get("CLiw")) if isinstance(selected, dict) else None,
        "cliw_component_label": "wake_free_stream_induced_component",
        "inviscid_lift_fraction_of_cltot": inviscid_fraction,
        "wake_settings_present": (
            wake_nodes is not None and wake_nodes > 0 and wake_iters is not None
        ),
        "source_semantics": (
            "OpenVSP VSPAERO source writes CLtot=CLi+CLo and labels CLi "
            "as inviscid, CLo as viscous, and CLiw/CLwtot as wake/free-stream "
            "induced output."
        ),
        "interpretation": (
            "panel_lift_dominated_by_inviscid_component"
            if inviscid_fraction is not None and abs(inviscid_fraction) >= 0.8
            else None
        ),
    }


def _su2_semantics_observed(
    *,
    cfg: dict[str, Any],
    gap: dict[str, Any] | None,
) -> dict[str, Any]:
    values = cfg.get("values", {}) if isinstance(cfg.get("values"), dict) else {}
    boundary = gap.get("boundary_condition_observed", {}) if isinstance(gap, dict) else {}
    force = gap.get("su2_force_breakdown", {}) if isinstance(gap, dict) else {}
    euler_markers = values.get("MARKER_EULER", [])
    if isinstance(euler_markers, str):
        euler_markers = [euler_markers]
    wake_keys = [key for key in values if "WAKE" in key.upper()]
    velocity_vector = _cfg_float_list(values, "INC_VELOCITY_INIT")
    return {
        "status": cfg.get("status", "unavailable"),
        "runtime_cfg_path": cfg.get("path"),
        "solver": values.get("SOLVER") or boundary.get("solver"),
        "velocity_vector_mps": velocity_vector,
        "wall_boundary_condition": (
            "euler"
            if "main_wing" in euler_markers
            else boundary.get("wall_boundary_condition")
        ),
        "euler_markers": euler_markers,
        "monitoring_markers": values.get("MARKER_MONITORING", []),
        "wake_related_cfg_keys": wake_keys,
        "has_explicit_wake_model_keys": bool(wake_keys),
        "forces_breakdown_status": force.get("forces_breakdown_status")
        if isinstance(force, dict)
        else None,
        "forces_breakdown_cl": (
            _as_float(force.get("forces_breakdown_cl"))
            if isinstance(force, dict)
            else None
        ),
        "force_breakdown_marker_owned": (
            force.get("force_breakdown_marker_owned")
            if isinstance(force, dict)
            else None
        ),
    }


def _normal_audit_observed(normal: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "normal_audit_status": (
            None if normal is None else normal.get("normal_audit_status")
        ),
        "engineering_findings": (
            [] if normal is None else normal.get("engineering_findings", [])
        ),
    }


def _audit_status(
    *,
    panel: dict[str, Any],
    su2: dict[str, Any],
    normal: dict[str, Any],
) -> AuditStatusType:
    inviscid_fraction = _as_float(panel.get("inviscid_lift_fraction_of_cltot"))
    panel_cl = _as_float(panel.get("cltot"))
    su2_cl = _as_float(su2.get("forces_breakdown_cl"))
    normal_findings = normal.get("engineering_findings", [])
    required_values = [inviscid_fraction, panel_cl, su2_cl]
    if any(value is None for value in required_values):
        return "insufficient_evidence"
    if (
        abs(inviscid_fraction or 0.0) >= 0.8
        and (panel_cl or 0.0) > 1.0
        and (su2_cl or 0.0) <= 1.0
        and su2.get("wall_boundary_condition") == "euler"
        and "single_global_normal_flip_not_supported" in normal_findings
    ):
        return "semantics_gap_observed"
    return "no_semantics_gap_observed"


def _engineering_findings(
    *,
    status: AuditStatusType,
    panel: dict[str, Any],
    su2: dict[str, Any],
    normal: dict[str, Any],
) -> list[str]:
    findings: list[str] = []
    if status == "semantics_gap_observed":
        findings.append("panel_su2_semantics_gap_observed")
    if panel.get("interpretation") == "panel_lift_dominated_by_inviscid_component":
        findings.append("panel_lift_dominated_by_inviscid_component")
    if (
        su2.get("wall_boundary_condition") == "euler"
        and su2.get("has_explicit_wake_model_keys") is False
    ):
        findings.append("su2_euler_wall_no_explicit_wake_model_keys_observed")
    if su2.get("force_breakdown_marker_owned") is True:
        findings.append("force_breakdown_marker_owned")
    normal_findings = normal.get("engineering_findings", [])
    if "single_global_normal_flip_not_supported" in normal_findings:
        findings.append("single_global_normal_flip_not_supported")
    if status == "semantics_gap_observed":
        findings.append("thin_sheet_wall_not_yet_bridged_to_panel_lifting_surface_semantics")
    return list(dict.fromkeys(findings))


def _next_actions(findings: list[str]) -> list[str]:
    if "thin_sheet_wall_not_yet_bridged_to_panel_lifting_surface_semantics" in findings:
        return [
            "audit_su2_thin_surface_geometry_closed_vs_lifting_surface_export",
            "compare_vspaero_degengeom_lifting_surface_against_su2_surface_entities",
            "decide_main_wing_product_route_lifting_surface_vs_closed_thickness_cfd_geometry",
        ]
    return ["rerun_panel_wake_semantics_audit_after_required_artifacts_exist"]


def build_main_wing_panel_wake_semantics_audit_report(
    *,
    report_root: Path | None = None,
    runtime_cfg_path: Path | None = None,
) -> MainWingPanelWakeSemanticsAuditReport:
    root = _default_report_root() if report_root is None else report_root
    cfg_path = _default_runtime_cfg_path() if runtime_cfg_path is None else runtime_cfg_path
    loaded = _reports(root)
    panel = _panel_wake_observed(loaded["panel"])
    su2 = _su2_semantics_observed(cfg=_parse_cfg(cfg_path), gap=loaded["gap"])
    normal = _normal_audit_observed(loaded["normal"])
    status = _audit_status(panel=panel, su2=su2, normal=normal)
    findings = _engineering_findings(status=status, panel=panel, su2=su2, normal=normal)
    return MainWingPanelWakeSemanticsAuditReport(
        audit_status=status,
        panel_wake_observed=panel,
        su2_semantics_observed=su2,
        normal_audit_observed=normal,
        engineering_findings=findings,
        next_actions=_next_actions(findings),
        limitations=[
            "This report reads existing artifacts only; it does not execute VSPAERO, Gmsh, or SU2.",
            "Observed VSPAERO panel terms are lower-order sanity evidence, not high-fidelity CFD truth.",
            "Do not describe the VSPAERO CLi column as a wake-induced term; source evidence labels it as inviscid.",
            "The semantics gap is a route-risk gate; it does not prove the final root cause by itself.",
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


def _render_markdown(report: MainWingPanelWakeSemanticsAuditReport) -> str:
    lines = [
        "# Main Wing Panel Wake Semantics Audit v1",
        "",
        "This report reads existing artifacts only; it does not execute VSPAERO, Gmsh, or SU2.",
        "",
        f"- audit_status: `{report.audit_status}`",
        f"- hpa_standard_velocity_mps: `{report.hpa_standard_velocity_mps}`",
        f"- minimum_acceptable_cl: `{report.minimum_acceptable_cl}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Panel Wake Observed",
        "",
    ]
    for key, value in report.panel_wake_observed.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## SU2 Semantics Observed", ""])
    for key, value in report.su2_semantics_observed.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Normal Audit Observed", ""])
    for key, value in report.normal_audit_observed.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Engineering Findings", ""])
    lines.extend(f"- `{finding}`" for finding in report.engineering_findings)
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- `{action}`" for action in report.next_actions)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_main_wing_panel_wake_semantics_audit_report(
    out_dir: Path,
    *,
    report: MainWingPanelWakeSemanticsAuditReport | None = None,
    report_root: Path | None = None,
    runtime_cfg_path: Path | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_panel_wake_semantics_audit_report(
            report_root=report_root,
            runtime_cfg_path=runtime_cfg_path,
        )
    json_path = out_dir / "main_wing_panel_wake_semantics_audit.v1.json"
    markdown_path = out_dir / "main_wing_panel_wake_semantics_audit.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
