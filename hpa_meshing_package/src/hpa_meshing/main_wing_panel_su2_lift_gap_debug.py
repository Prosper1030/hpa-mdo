from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


DebugStatusType = Literal[
    "gap_confirmed_debug_ready",
    "insufficient_evidence",
    "no_gap_observed",
]


class MainWingPanelSU2LiftGapDebugReport(BaseModel):
    schema_version: Literal["main_wing_panel_su2_lift_gap_debug.v1"] = (
        "main_wing_panel_su2_lift_gap_debug.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_existing_artifacts"] = (
        "report_only_existing_artifacts"
    )
    production_default_changed: bool = False
    hpa_standard_velocity_mps: float = 6.5
    minimum_acceptable_cl: float = 1.0
    debug_status: DebugStatusType
    flow_reference_alignment: Dict[str, Any] = Field(default_factory=dict)
    panel_reference_decomposition: Dict[str, Any] = Field(default_factory=dict)
    su2_force_breakdown: Dict[str, Any] = Field(default_factory=dict)
    solver_state: Dict[str, Any] = Field(default_factory=dict)
    boundary_condition_observed: Dict[str, Any] = Field(default_factory=dict)
    mesh_quality_observed: Dict[str, Any] = Field(default_factory=dict)
    engineering_findings: List[str] = Field(default_factory=list)
    primary_hypotheses: List[Dict[str, Any]] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    hpa_mdo_guarantees: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def _default_report_root() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "reports"


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


def _relative_delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or abs(b) <= 1.0e-12:
        return None
    return abs(a - b) / abs(b)


def _reports(root: Path) -> dict[str, dict[str, Any] | None]:
    return {
        "panel": _load_json(
            root
            / "main_wing_vspaero_panel_reference_probe"
            / "main_wing_vspaero_panel_reference_probe.v1.json"
        ),
        "lift": _load_json(
            root
            / "main_wing_lift_acceptance_diagnostic"
            / "main_wing_lift_acceptance_diagnostic.v1.json"
        ),
        "surface_force": _load_json(
            root
            / "main_wing_surface_force_output_audit"
            / "main_wing_surface_force_output_audit.v1.json"
        ),
        "force_marker": _load_json(
            root
            / "main_wing_su2_force_marker_audit"
            / "main_wing_su2_force_marker_audit.v1.json"
        ),
        "solver": _load_json(
            root
            / "main_wing_openvsp_reference_solver_smoke_probe_iter80"
            / "main_wing_real_solver_smoke_probe.v1.json"
        ),
    }


def _panel_decomposition(panel: dict[str, Any] | None) -> dict[str, Any]:
    selected_case = panel.get("selected_case", {}) if isinstance(panel, dict) else {}
    cltot = _as_float(selected_case.get("CLtot")) if isinstance(selected_case, dict) else None
    cli = _as_float(selected_case.get("CLi")) if isinstance(selected_case, dict) else None
    clo = _as_float(selected_case.get("CLo")) if isinstance(selected_case, dict) else None
    decomposition = {
        "alpha_deg": (
            _as_float(selected_case.get("AoA")) if isinstance(selected_case, dict) else None
        ),
        "clo": clo,
        "clo_component_label": "viscous_or_other_surface_integration_component",
        "cli": cli,
        "cli_component_label": "inviscid_surface_integration_component",
        "cltot": cltot,
        "cdtot": (
            _as_float(selected_case.get("CDtot"))
            if isinstance(selected_case, dict)
            else None
        ),
        "cfztot": (
            _as_float(selected_case.get("CFztot"))
            if isinstance(selected_case, dict)
            else None
        ),
        "clwtot": (
            _as_float(selected_case.get("CLwtot"))
            if isinstance(selected_case, dict)
            else None
        ),
        "cliw": (
            _as_float(selected_case.get("CLiw"))
            if isinstance(selected_case, dict)
            else None
        ),
        "cliw_component_label": "wake_free_stream_induced_component",
        "source_semantics": (
            "OpenVSP VSPAERO source writes CLtot=CLi+CLo and labels CLi "
            "as inviscid, CLo as viscous, and CLiw/CLwtot as wake/free-stream "
            "induced output."
        ),
    }
    if cli is not None and cltot is not None and abs(cltot) > 1.0e-12:
        decomposition["inviscid_lift_fraction_of_cltot"] = cli / cltot
    if abs(decomposition.get("inviscid_lift_fraction_of_cltot", 0.0)) >= 0.8:
        decomposition["interpretation"] = "panel_lift_dominated_by_inviscid_component"
    return decomposition


def _flow_reference_alignment(
    panel: dict[str, Any] | None,
    lift: dict[str, Any] | None,
    force_marker: dict[str, Any] | None,
) -> dict[str, Any]:
    setup = panel.get("setup_reference", {}) if isinstance(panel, dict) else {}
    flow = lift.get("flow_condition_observed", {}) if isinstance(lift, dict) else {}
    reference = lift.get("reference_observed", {}) if isinstance(lift, dict) else {}
    checks = force_marker.get("checks", {}) if isinstance(force_marker, dict) else {}
    flow_consistency = (
        checks.get("flow_reference_consistency", {})
        if isinstance(checks, dict)
        else {}
    )
    force_observed = (
        flow_consistency.get("observed", {})
        if isinstance(flow_consistency, dict)
        else {}
    )
    panel_sref = _as_float(setup.get("Sref")) if isinstance(setup, dict) else None
    panel_cref = _as_float(setup.get("Cref")) if isinstance(setup, dict) else None
    panel_vinf = _as_float(setup.get("Vinf")) if isinstance(setup, dict) else None
    panel_rho = _as_float(setup.get("Rho")) if isinstance(setup, dict) else None
    su2_ref_area = _as_float(reference.get("ref_area_m2")) if isinstance(reference, dict) else None
    su2_ref_length = (
        _as_float(reference.get("ref_length_m")) if isinstance(reference, dict) else None
    )
    su2_velocity = _as_float(flow.get("velocity_mps")) if isinstance(flow, dict) else None
    su2_density = _as_float(flow.get("density_kgpm3")) if isinstance(flow, dict) else None
    area_delta = _relative_delta(panel_sref, su2_ref_area)
    length_delta = _relative_delta(panel_cref, su2_ref_length)
    velocity_delta = _relative_delta(panel_vinf, su2_velocity)
    density_delta = _relative_delta(panel_rho, su2_density)
    status = (
        "pass"
        if all(
            value is not None and value <= 1.0e-9
            for value in (area_delta, length_delta, velocity_delta, density_delta)
        )
        else "warn"
    )
    return {
        "status": status,
        "panel_sref_m2": panel_sref,
        "su2_ref_area_m2": su2_ref_area,
        "ref_area_relative_delta": area_delta,
        "panel_cref_m": panel_cref,
        "su2_ref_length_m": su2_ref_length,
        "ref_length_relative_delta": length_delta,
        "panel_velocity_mps": panel_vinf,
        "su2_velocity_mps": su2_velocity,
        "velocity_relative_delta": velocity_delta,
        "panel_density_kgpm3": panel_rho,
        "su2_density_kgpm3": su2_density,
        "density_relative_delta": density_delta,
        "force_marker_flow_reference_status": (
            flow_consistency.get("status") if isinstance(flow_consistency, dict) else None
        ),
        "force_marker_flow_reference_observed": force_observed,
    }


def _su2_force_breakdown(
    lift: dict[str, Any] | None,
    surface_force: dict[str, Any] | None,
) -> dict[str, Any]:
    lift_gap = lift.get("lift_gap_diagnostics", {}) if isinstance(lift, dict) else {}
    force = (
        surface_force.get("force_breakdown_observed", {})
        if isinstance(surface_force, dict)
        else {}
    )
    return {
        "forces_breakdown_status": (
            force.get("status") if isinstance(force, dict) else None
        ),
        "surface_names": force.get("surface_names", []) if isinstance(force, dict) else [],
        "forces_breakdown_cl": _as_float(lift_gap.get("forces_breakdown_cl"))
        or _as_float(
            force.get("total_coefficients", {}).get("cl")
            if isinstance(force.get("total_coefficients"), dict)
            else None
        ),
        "selected_su2_cl": _as_float(lift_gap.get("selected_su2_cl")),
        "vspaero_panel_cl": _as_float(lift_gap.get("vspaero_panel_cl")),
        "panel_to_force_breakdown_cl_ratio": _as_float(
            lift_gap.get("panel_to_force_breakdown_cl_ratio")
        )
        or _as_float(force.get("panel_to_force_breakdown_cl_ratio"))
        if isinstance(force, dict)
        else None,
        "force_breakdown_marker_owned": lift_gap.get("force_breakdown_marker_owned"),
        "force_breakdown_matches_history_cl": lift_gap.get(
            "force_breakdown_matches_history_cl"
        ),
        "history_cl_delta_abs": _as_float(force.get("history_cl_delta_abs"))
        if isinstance(force, dict)
        else None,
    }


def _solver_state(solver: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "solver_execution_status": (
            None if solver is None else solver.get("solver_execution_status")
        ),
        "run_status": None if solver is None else solver.get("run_status"),
        "convergence_gate_status": (
            None if solver is None else solver.get("convergence_gate_status")
        ),
        "convergence_comparability_level": (
            None if solver is None else solver.get("convergence_comparability_level")
        ),
        "runtime_max_iterations": (
            None if solver is None else solver.get("runtime_max_iterations")
        ),
        "final_iteration": None if solver is None else solver.get("final_iteration"),
        "final_coefficients": (
            {} if solver is None else solver.get("final_coefficients", {})
        ),
    }


def _boundary_condition(force_marker: dict[str, Any] | None) -> dict[str, Any]:
    checks = force_marker.get("checks", {}) if isinstance(force_marker, dict) else {}
    flow_check = (
        checks.get("flow_reference_consistency", {})
        if isinstance(checks, dict)
        else {}
    )
    observed = flow_check.get("observed", {}) if isinstance(flow_check, dict) else {}
    return {
        "solver": observed.get("solver") if isinstance(observed, dict) else None,
        "wall_boundary_condition": (
            observed.get("wall_boundary_condition") if isinstance(observed, dict) else None
        ),
        "engineering_flags": (
            [] if force_marker is None else force_marker.get("engineering_flags", [])
        ),
    }


def _mesh_quality(solver: dict[str, Any] | None) -> dict[str, Any]:
    quality = solver.get("solver_log_quality_metrics", {}) if isinstance(solver, dict) else {}
    dual = (
        quality.get("dual_control_volume_quality", {})
        if isinstance(quality, dict)
        else {}
    )
    face_ar = (
        _as_float(dual.get("cv_face_area_aspect_ratio", {}).get("max"))
        if isinstance(dual.get("cv_face_area_aspect_ratio"), dict)
        else None
    )
    cv_ratio = (
        _as_float(dual.get("cv_sub_volume_ratio", {}).get("max"))
        if isinstance(dual.get("cv_sub_volume_ratio"), dict)
        else None
    )
    return {
        "max_cv_face_area_aspect_ratio": face_ar,
        "max_cv_sub_volume_ratio": cv_ratio,
        "mesh_quality_pathology_present": (
            (face_ar is not None and face_ar >= 100.0)
            or (cv_ratio is not None and cv_ratio >= 1000.0)
        ),
    }


def _debug_status(force: dict[str, Any]) -> DebugStatusType:
    panel_cl = _as_float(force.get("vspaero_panel_cl"))
    su2_cl = _as_float(force.get("forces_breakdown_cl") or force.get("selected_su2_cl"))
    if panel_cl is None or su2_cl is None:
        return "insufficient_evidence"
    if panel_cl > 1.0 and su2_cl <= 1.0:
        return "gap_confirmed_debug_ready"
    return "no_gap_observed"


def _engineering_findings(
    *,
    status: DebugStatusType,
    flow: dict[str, Any],
    panel: dict[str, Any],
    force: dict[str, Any],
    solver: dict[str, Any],
    boundary: dict[str, Any],
    mesh: dict[str, Any],
) -> list[str]:
    findings: list[str] = []
    if status == "gap_confirmed_debug_ready":
        findings.append("panel_su2_lift_gap_confirmed")
    if flow.get("status") == "pass":
        findings.append("reference_normalization_not_primary_cause")
    if panel.get("interpretation") == "panel_lift_dominated_by_inviscid_component":
        findings.append("panel_lift_dominated_by_inviscid_component")
    if force.get("force_breakdown_marker_owned") is True:
        findings.append("force_marker_ownership_not_primary_cause")
    if force.get("force_breakdown_matches_history_cl") is True:
        findings.append("su2_force_breakdown_confirms_main_wing_low_cl")
    if boundary.get("wall_boundary_condition") == "euler":
        findings.append("su2_wall_bc_is_euler_smoke")
    if mesh.get("mesh_quality_pathology_present") is True:
        findings.append("mesh_quality_pathology_present")
    if solver.get("convergence_gate_status") != "pass":
        findings.append("solver_not_converged")
    return list(dict.fromkeys(findings))


def _hypotheses(findings: list[str]) -> list[dict[str, Any]]:
    hypotheses: list[dict[str, Any]] = []
    if {
        "panel_su2_lift_gap_confirmed",
        "panel_lift_dominated_by_inviscid_component",
        "su2_wall_bc_is_euler_smoke",
    }.issubset(findings):
        hypotheses.append(
            {
                "hypothesis": "panel_su2_lifting_surface_semantics_or_geometry_mismatch",
                "priority": "high",
                "evidence": [
                    "Panel CL is dominated by the inviscid surface-integration component.",
                    "SU2 force breakdown confirms low CL on the main_wing marker.",
                    "Current SU2 smoke uses an Euler wall on the thin-sheet main-wing route.",
                ],
                "next_gate": "compare_openvsp_panel_geometry_against_su2_mesh_normals_incidence_and_lifting_surface_semantics",
            }
        )
    if "mesh_quality_pathology_present" in findings:
        hypotheses.append(
            {
                "hypothesis": "mesh_quality_or_dual_control_volume_pathology",
                "priority": "high",
                "evidence": ["SU2 preprocessing reports high dual-volume quality ratios."],
                "next_gate": "localize_bad_dual_volume_cells_before_larger_solver_budget",
            }
        )
    if "solver_not_converged" in findings:
        hypotheses.append(
            {
                "hypothesis": "solver_state_not_converged",
                "priority": "medium",
                "evidence": ["The selected smoke is solver-executed but convergence-gate failed."],
                "next_gate": "use_source_backed_iteration_budget_only_after_geometry_and_mesh_debug",
            }
        )
    if "reference_normalization_not_primary_cause" in findings:
        hypotheses.append(
            {
                "hypothesis": "reference_normalization_unlikely_primary_cause",
                "priority": "low",
                "evidence": ["Panel and SU2 use matching Sref/Cref/V/rho in the observed artifacts."],
                "next_gate": "keep_reference_warning_visible_but_do_not_prioritize_area_normalization",
            }
        )
    return hypotheses


def _next_actions(findings: list[str]) -> list[str]:
    actions: list[str] = []
    if "panel_lift_dominated_by_inviscid_component" in findings:
        actions.append(
            "compare_openvsp_panel_geometry_against_su2_mesh_normals_incidence_and_lifting_surface_semantics"
        )
        actions.append("inspect_thin_sheet_wall_bc_against_vspaero_degengeom_lifting_surface_assumption")
    if "mesh_quality_pathology_present" in findings:
        actions.append("localize_main_wing_su2_mesh_quality_hotspots_before_iteration_sweep")
    if "solver_not_converged" in findings:
        actions.append("defer_convergence_claim_until_source_backed_iteration_budget")
    if not actions:
        actions.append("rerun_lift_gap_debug_after_required_artifacts_exist")
    return list(dict.fromkeys(actions))


def build_main_wing_panel_su2_lift_gap_debug_report(
    *,
    report_root: Path | None = None,
) -> MainWingPanelSU2LiftGapDebugReport:
    root = _default_report_root() if report_root is None else report_root
    loaded = _reports(root)
    panel = _panel_decomposition(loaded["panel"])
    flow = _flow_reference_alignment(loaded["panel"], loaded["lift"], loaded["force_marker"])
    force = _su2_force_breakdown(loaded["lift"], loaded["surface_force"])
    solver = _solver_state(loaded["solver"])
    boundary = _boundary_condition(loaded["force_marker"])
    mesh = _mesh_quality(loaded["solver"])
    status = _debug_status(force)
    findings = _engineering_findings(
        status=status,
        flow=flow,
        panel=panel,
        force=force,
        solver=solver,
        boundary=boundary,
        mesh=mesh,
    )
    return MainWingPanelSU2LiftGapDebugReport(
        debug_status=status,
        flow_reference_alignment=flow,
        panel_reference_decomposition=panel,
        su2_force_breakdown=force,
        solver_state=solver,
        boundary_condition_observed=boundary,
        mesh_quality_observed=mesh,
        engineering_findings=findings,
        primary_hypotheses=_hypotheses(findings),
        next_actions=_next_actions(findings),
        hpa_mdo_guarantees=[
            "report_only_no_solver_execution",
            "production_default_unchanged",
            "hpa_standard_flow_conditions_6p5_mps_checked",
            "main_wing_cl_gt_one_required_for_acceptance",
        ],
        limitations=[
            "This report ranks debug hypotheses from existing artifacts; it is not a CFD convergence result.",
            "VSPAERO panel evidence is a lower-order sanity baseline, not high-fidelity CFD truth.",
            "Do not describe the VSPAERO CLi column as a wake-induced term; source evidence labels it as inviscid.",
            "Solver execution remains separate from convergence.",
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


def _render_markdown(report: MainWingPanelSU2LiftGapDebugReport) -> str:
    lines = [
        "# Main Wing Panel/SU2 Lift Gap Debug v1",
        "",
        "This report reads existing artifacts only; it does not execute SU2.",
        "",
        f"- debug_status: `{report.debug_status}`",
        f"- hpa_standard_velocity_mps: `{report.hpa_standard_velocity_mps}`",
        f"- minimum_acceptable_cl: `{report.minimum_acceptable_cl}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Flow Reference Alignment",
        "",
    ]
    for key, value in report.flow_reference_alignment.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Panel Reference Decomposition", ""])
    for key, value in report.panel_reference_decomposition.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## SU2 Force Breakdown", ""])
    for key, value in report.su2_force_breakdown.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Boundary And Mesh", ""])
    for key, value in report.boundary_condition_observed.items():
        lines.append(f"- `boundary.{key}`: `{_fmt(value)}`")
    for key, value in report.mesh_quality_observed.items():
        lines.append(f"- `mesh.{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Engineering Findings", ""])
    lines.extend(f"- `{finding}`" for finding in report.engineering_findings)
    lines.extend(["", "## Primary Hypotheses", ""])
    for hypothesis in report.primary_hypotheses:
        lines.append(f"- `{hypothesis.get('hypothesis')}`: `{hypothesis.get('priority')}`")
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- `{action}`" for action in report.next_actions)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_main_wing_panel_su2_lift_gap_debug_report(
    out_dir: Path,
    *,
    report: MainWingPanelSU2LiftGapDebugReport | None = None,
    report_root: Path | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_panel_su2_lift_gap_debug_report(report_root=report_root)
    json_path = out_dir / "main_wing_panel_su2_lift_gap_debug.v1.json"
    markdown_path = out_dir / "main_wing_panel_su2_lift_gap_debug.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
