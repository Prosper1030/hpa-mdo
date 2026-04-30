from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from .main_wing_solver_budget_comparison import (
    MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5,
    build_main_wing_solver_budget_comparison_report,
)


DiagnosticStatusType = Literal[
    "insufficient_solver_evidence",
    "nonstandard_flow_observed",
    "lift_acceptance_passed",
    "lift_margin_observed_without_convergence",
    "lift_deficit_observed",
]


class MainWingLiftAcceptanceDiagnosticReport(BaseModel):
    schema_version: Literal["main_wing_lift_acceptance_diagnostic.v1"] = (
        "main_wing_lift_acceptance_diagnostic.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_existing_solver_smokes"] = (
        "report_only_existing_solver_smokes"
    )
    production_default_changed: bool = False
    hpa_standard_velocity_mps: float = 6.5
    minimum_acceptable_cl: float = MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5
    diagnostic_status: DiagnosticStatusType
    selected_solver_report: Dict[str, Any] = Field(default_factory=dict)
    panel_reference_observed: Dict[str, Any] = Field(default_factory=dict)
    flow_condition_observed: Dict[str, Any] = Field(default_factory=dict)
    reference_observed: Dict[str, Any] = Field(default_factory=dict)
    lift_metrics: Dict[str, Any] = Field(default_factory=dict)
    lift_gap_diagnostics: Dict[str, Any] = Field(default_factory=dict)
    root_cause_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    engineering_flags: List[str] = Field(default_factory=list)
    engineering_assessment: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    hpa_mdo_guarantees: List[str] = Field(default_factory=list)
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
            return candidate
    return candidates[0]


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _selected_solver_payload(
    report_root: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None, Path | None]:
    comparison = build_main_wing_solver_budget_comparison_report(report_root=report_root)
    selected = comparison.current_route_row
    report_path = _resolve_path(
        selected.get("report_path"),
        report_root=report_root,
    )
    return selected, _load_json(report_path), report_path


def _reference_gate_area_delta(report_root: Path) -> float | None:
    gate = _load_json(
        report_root
        / "main_wing_reference_geometry_gate"
        / "main_wing_reference_geometry_gate.v1.json"
    )
    checks = gate.get("checks", {}) if isinstance(gate, dict) else {}
    area_check = (
        checks.get("applied_ref_area_vs_openvsp_sref", {})
        if isinstance(checks, dict)
        else {}
    )
    observed = area_check.get("observed", {}) if isinstance(area_check, dict) else {}
    return _as_float(observed.get("relative_error"))


def _panel_reference_payload(report_root: Path) -> dict[str, Any] | None:
    return _load_json(
        report_root
        / "main_wing_vspaero_panel_reference_probe"
        / "main_wing_vspaero_panel_reference_probe.v1.json"
    )


def _surface_force_output_audit_payload(report_root: Path) -> dict[str, Any] | None:
    return _load_json(
        report_root
        / "main_wing_surface_force_output_audit"
        / "main_wing_surface_force_output_audit.v1.json"
    )


def _committed_su2_handoff_path(
    report_root: Path,
    *,
    reference_policy: Any,
) -> tuple[Path | None, str | None]:
    if reference_policy == "openvsp_geometry_derived":
        path = (
            report_root
            / "main_wing_openvsp_reference_su2_handoff_probe"
            / "artifacts"
            / "su2_handoff.json"
        )
        if path.exists():
            return path, "committed_openvsp_reference_su2_handoff_probe"
    if reference_policy == "declared_blackcat_full_span":
        probe_path = (
            report_root
            / "main_wing_real_su2_handoff_probe"
            / "main_wing_real_su2_handoff_probe.v1.json"
        )
        probe = _load_json(probe_path)
        path = _resolve_path(
            probe.get("su2_handoff_path") if isinstance(probe, dict) else None,
            report_root=report_root,
            anchor_path=probe_path,
        )
        if path is not None and path.exists():
            return path, "committed_declared_reference_su2_handoff_probe"
    return None, None


def _lift_metrics(
    *,
    cl: float | None,
    velocity_mps: float | None,
    density_kgpm3: float | None,
    ref_area_m2: float | None,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "cl": cl,
        "minimum_acceptable_cl_exclusive": MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5,
    }
    if (
        cl is None
        or velocity_mps is None
        or density_kgpm3 is None
        or ref_area_m2 is None
    ):
        return metrics
    dynamic_pressure_pa = 0.5 * density_kgpm3 * velocity_mps * velocity_mps
    lift_at_minimum_cl_n = (
        dynamic_pressure_pa
        * ref_area_m2
        * MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5
    )
    observed_lift_n = dynamic_pressure_pa * ref_area_m2 * cl
    metrics.update(
        {
            "dynamic_pressure_pa": dynamic_pressure_pa,
            "reference_area_m2": ref_area_m2,
            "observed_lift_n": observed_lift_n,
            "lift_at_minimum_acceptable_cl_n": lift_at_minimum_cl_n,
            "observed_cl_to_minimum_ratio": (
                cl / MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5
            ),
            "cl_shortfall_to_minimum": (
                MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5 - cl
            ),
        }
    )
    return metrics


def _panel_reference_observed(payload: dict[str, Any] | None) -> dict[str, Any]:
    selected_case = payload.get("selected_case", {}) if isinstance(payload, dict) else {}
    setup_reference = payload.get("setup_reference", {}) if isinstance(payload, dict) else {}
    return {
        "panel_reference_status": (
            None if payload is None else payload.get("panel_reference_status")
        ),
        "alpha_deg": (
            _as_float(selected_case.get("AoA"))
            if isinstance(selected_case, dict)
            else None
        ),
        "cltot": (
            _as_float(selected_case.get("CLtot"))
            if isinstance(selected_case, dict)
            else None
        ),
        "cdtot": (
            _as_float(selected_case.get("CDtot"))
            if isinstance(selected_case, dict)
            else None
        ),
        "velocity_mps": (
            _as_float(setup_reference.get("Vinf"))
            if isinstance(setup_reference, dict)
            else None
        ),
        "lift_acceptance_status": (
            None if payload is None else payload.get("lift_acceptance_status")
        ),
    }


def _lift_gap_diagnostics(
    *,
    solver_cl: float | None,
    panel_reference: dict[str, Any],
    surface_force_audit: dict[str, Any] | None,
) -> dict[str, Any]:
    panel_cl = _as_float(panel_reference.get("cltot"))
    diagnostics: dict[str, Any] = {
        "selected_su2_cl": solver_cl,
        "vspaero_panel_cl": panel_cl,
        "minimum_acceptable_cl": MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5,
    }
    force_breakdown = (
        surface_force_audit.get("force_breakdown_observed", {})
        if isinstance(surface_force_audit, dict)
        else {}
    )
    checks = (
        surface_force_audit.get("checks", {})
        if isinstance(surface_force_audit, dict)
        else {}
    )
    force_total = (
        force_breakdown.get("total_coefficients", {})
        if isinstance(force_breakdown, dict)
        else {}
    )
    force_surfaces = (
        force_breakdown.get("surface_coefficients", {})
        if isinstance(force_breakdown, dict)
        else {}
    )
    main_wing_surface = (
        force_surfaces.get("main_wing", {}) if isinstance(force_surfaces, dict) else {}
    )
    force_cl = _as_float(
        main_wing_surface.get("cl")
        if isinstance(main_wing_surface, dict)
        else None
    )
    if force_cl is None:
        force_cl = _as_float(force_total.get("cl") if isinstance(force_total, dict) else None)
    surface_names = (
        force_breakdown.get("surface_names", [])
        if isinstance(force_breakdown, dict)
        else []
    )
    marker_check = checks.get("forces_breakdown_marker_owned", {}) if isinstance(checks, dict) else {}
    history_check = (
        checks.get("forces_breakdown_matches_history_cl", {})
        if isinstance(checks, dict)
        else {}
    )
    history_delta = (
        _as_float(force_breakdown.get("history_cl_delta_abs"))
        if isinstance(force_breakdown, dict)
        else None
    )
    marker_owned = (
        marker_check.get("status") == "pass"
        if isinstance(marker_check, dict) and marker_check
        else surface_names == ["main_wing"]
    )
    history_matches = (
        history_check.get("status") == "pass"
        if isinstance(history_check, dict) and history_check
        else history_delta is not None and history_delta <= 1.0e-6
    )
    force_status = (
        force_breakdown.get("status")
        if isinstance(force_breakdown, dict)
        else None
    )
    if force_status is not None:
        diagnostics.update(
            {
                "forces_breakdown_status": force_status,
                "forces_breakdown_surface_names": surface_names,
                "forces_breakdown_cl": force_cl,
                "force_breakdown_marker_owned": marker_owned,
                "force_breakdown_matches_history_cl": history_matches,
                "force_breakdown_history_cl_delta_abs": history_delta,
            }
        )
    if panel_cl is not None and force_cl is not None:
        diagnostics["panel_to_force_breakdown_cl_ratio"] = (
            panel_cl / force_cl if abs(force_cl) > 1.0e-12 else None
        )
        diagnostics["force_breakdown_vs_panel_status"] = (
            "panel_supports_expected_lift_force_breakdown_low"
            if panel_cl > MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5
            and force_cl <= MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5
            else "panel_and_force_breakdown_same_lift_gate_side"
        )
    if solver_cl is None or panel_cl is None:
        diagnostics["panel_vs_su2_status"] = "insufficient_evidence"
        return diagnostics
    diagnostics.update(
        {
            "cl_delta_panel_minus_su2": panel_cl - solver_cl,
            "panel_to_su2_cl_ratio": (
                panel_cl / solver_cl if abs(solver_cl) > 1.0e-12 else None
            ),
            "panel_reference_passes_cl_gate": (
                panel_cl > MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5
            ),
            "su2_smoke_passes_cl_gate": (
                solver_cl > MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5
            ),
        }
    )
    diagnostics["panel_vs_su2_status"] = (
        "panel_supports_expected_lift_su2_low"
        if diagnostics["panel_reference_passes_cl_gate"]
        and not diagnostics["su2_smoke_passes_cl_gate"]
        else "panel_and_su2_same_lift_gate_side"
    )
    return diagnostics


def _diagnostic_status(
    *,
    cl: float | None,
    velocity_mps: float | None,
    convergence_gate_status: Any,
) -> DiagnosticStatusType:
    if cl is None:
        return "insufficient_solver_evidence"
    if velocity_mps is None or abs(velocity_mps - 6.5) > 1.0e-9:
        return "nonstandard_flow_observed"
    if cl > MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5:
        return (
            "lift_acceptance_passed"
            if convergence_gate_status == "pass"
            else "lift_margin_observed_without_convergence"
        )
    return "lift_deficit_observed"


def _engineering_flags(
    *,
    status: DiagnosticStatusType,
    alpha_deg: float | None,
    selected_row: dict[str, Any],
    reference_geometry_status: Any,
    reference_area_delta: float | None,
    lift_gap: dict[str, Any],
) -> list[str]:
    flags: list[str] = []
    if status == "lift_deficit_observed":
        flags.append("main_wing_cl_below_expected_lift")
    if status == "nonstandard_flow_observed":
        flags.append("nonstandard_flow_condition")
    if alpha_deg is not None and abs(alpha_deg) <= 1.0e-9:
        flags.append("alpha_zero_operating_lift_not_demonstrated")
    if selected_row.get("convergence_gate_status") != "pass":
        flags.append("solver_not_converged")
    if reference_geometry_status in {"warn", "fail"}:
        flags.append(f"reference_geometry_{reference_geometry_status}")
    advisory_flags = selected_row.get("advisory_flags", [])
    if any(str(flag).startswith("mesh_quality_") for flag in advisory_flags):
        flags.append("mesh_quality_warning_present")
    if reference_area_delta is not None and reference_area_delta <= 0.03:
        flags.append("reference_area_delta_too_small_to_explain_lift_deficit")
    if lift_gap.get("panel_vs_su2_status") == "panel_supports_expected_lift_su2_low":
        flags.append("vspaero_panel_cl_gt_one_while_su2_low")
    ratio = _as_float(lift_gap.get("panel_to_su2_cl_ratio"))
    if ratio is not None and ratio >= 4.0:
        flags.append("panel_to_su2_cl_ratio_above_four")
    force_cl = _as_float(lift_gap.get("forces_breakdown_cl"))
    if (
        lift_gap.get("forces_breakdown_status") == "available"
        and force_cl is not None
        and force_cl <= MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5
    ):
        flags.append("force_breakdown_confirms_low_main_wing_cl")
    if lift_gap.get("force_breakdown_marker_owned") is True:
        flags.append("main_wing_force_breakdown_marker_owned")
    if lift_gap.get("force_breakdown_matches_history_cl") is True:
        flags.append("force_breakdown_matches_solver_history_cl")
    force_ratio = _as_float(lift_gap.get("panel_to_force_breakdown_cl_ratio"))
    if force_ratio is not None and force_ratio >= 4.0:
        flags.append("panel_to_force_breakdown_cl_ratio_above_four")
    return list(dict.fromkeys(flags))


def _root_cause_candidates(
    *,
    flags: list[str],
    selected_row: dict[str, Any],
    reference_area_delta: float | None,
    lift_gap: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if (
        "force_breakdown_confirms_low_main_wing_cl" in flags
        and "main_wing_force_breakdown_marker_owned" in flags
    ):
        candidates.append(
            {
                "candidate": "panel_su2_lift_gap_confirmed_on_main_wing_force_breakdown",
                "priority": "high",
                "evidence": [
                    "Retained SU2 forces_breakdown.dat reports the low CL on the main_wing marker.",
                    "Forces breakdown CL matches the solver-history CL within the audit tolerance.",
                    "VSPAERO panel reference remains above CL=1 at the same nominal setup.",
                ],
                "next_gate": "debug_panel_su2_lift_gap_from_retained_force_breakdown",
            }
        )
    if "vspaero_panel_cl_gt_one_while_su2_low" in flags:
        candidates.append(
            {
                "candidate": "su2_route_lift_deficit_not_explained_by_operating_alpha_alone",
                "priority": "high",
                "evidence": [
                    "VSPAERO panel reference is above CL=1 at the same alpha=0 setup.",
                    "Current selected SU2 smoke remains below CL=1.",
                ],
                "next_gate": "compare_su2_boundary_markers_force_integration_and_reference_policy_against_panel_baseline",
            }
        )
    if selected_row.get("convergence_gate_status") != "pass":
        candidates.append(
            {
                "candidate": "solver_not_converged",
                "priority": "high",
                "evidence": [
                    f"convergence_gate_status={selected_row.get('convergence_gate_status')}",
                    f"runtime_max_iterations={selected_row.get('runtime_max_iterations')}",
                ],
                "next_gate": "use_source_backed_iteration_budget_before_convergence_claim",
            }
        )
    advisory_flags = selected_row.get("advisory_flags", [])
    if any(str(flag).startswith("mesh_quality_") for flag in advisory_flags):
        candidates.append(
            {
                "candidate": "mesh_quality_or_dual_control_volume_pathology",
                "priority": "high",
                "evidence": [
                    str(flag)
                    for flag in advisory_flags
                    if str(flag).startswith("mesh_quality_")
                ],
                "next_gate": "inspect_mesh_quality_and_boundary_condition_localization_before_more_iterations",
            }
        )
    if reference_area_delta is not None:
        candidates.append(
            {
                "candidate": "reference_area_normalization",
                "priority": "low" if reference_area_delta <= 0.03 else "medium",
                "evidence": [
                    f"declared_vs_openvsp_area_relative_error={reference_area_delta:.6g}",
                    f"panel_to_su2_cl_ratio={_as_float(lift_gap.get('panel_to_su2_cl_ratio'))}",
                ],
                "next_gate": "keep_reference_area_warning_visible_but_do_not_treat_it_as_primary_lift_gap_cause",
            }
        )
    return candidates


def _engineering_assessment(
    *,
    status: DiagnosticStatusType,
    cl: float | None,
    alpha_deg: float | None,
    reference_area_delta: float | None,
    flags: list[str],
    lift_gap: dict[str, Any],
) -> list[str]:
    assessment = [
        "This diagnostic reads existing solver-smoke artifacts only and does not execute SU2.",
        "Main-wing convergence acceptance at the HPA standard flow requires CL > 1.0.",
    ]
    if status == "lift_deficit_observed" and cl is not None:
        assessment.append(
            f"The selected current-route solver smoke ends at CL={cl:.6g}, "
            "which is below the required main-wing lift margin."
        )
    if alpha_deg is not None and abs(alpha_deg) <= 1.0e-9:
        assessment.append(
            "The selected SU2 handoff is an alpha=0 case, so it is a route smoke point, "
            "not proof that the operational trim/angle condition can carry the aircraft."
        )
    if reference_area_delta is not None and reference_area_delta <= 0.03:
        assessment.append(
            "The declared-vs-OpenVSP reference-area delta is only warn-level; by itself "
            "it is far too small to explain a CL below 1."
        )
    if "mesh_quality_warning_present" in flags:
        assessment.append(
            "Mesh-quality warnings remain relevant for convergence and coefficient trust, "
            "but the low-lift finding should first be separated from alpha/trim provenance."
        )
    if "vspaero_panel_cl_gt_one_while_su2_low" in flags:
        assessment.append(
            "Because the VSPAERO panel baseline is already above CL=1 at the same nominal "
            "alpha=0 condition, alpha=0 alone is not a satisfactory explanation for the "
            "current SU2 CL deficit."
        )
    if "force_breakdown_confirms_low_main_wing_cl" in flags:
        assessment.append(
            "Retained SU2 forces_breakdown.dat confirms the low CL on the force-integrated "
            "main_wing marker, so the next debug step should compare panel/SU2 geometry, "
            "boundary-condition semantics, mesh quality, and solver state rather than rerun "
            "blindly for more iterations."
        )
    ratio = _as_float(lift_gap.get("panel_to_su2_cl_ratio"))
    if ratio is not None and ratio >= 4.0:
        assessment.append(
            f"The panel/SU2 CL ratio is about {ratio:.3g}x, so force-marker ownership, "
            "boundary conditions, mesh quality, and solver state should be checked before "
            "spending a larger run as a convergence test."
        )
    return assessment


def _next_actions(flags: list[str]) -> list[str]:
    actions: list[str] = []
    if "force_breakdown_confirms_low_main_wing_cl" in flags:
        actions.append("debug_panel_su2_lift_gap_from_retained_force_breakdown")
    if "main_wing_cl_below_expected_lift" in flags:
        actions.append(
            "run_bounded_main_wing_alpha_trim_sanity_probe_without_changing_default"
        )
        actions.append("extract_openvsp_main_wing_incidence_twist_camber_provenance")
    if "vspaero_panel_cl_gt_one_while_su2_low" in flags:
        actions.append("audit_su2_force_markers_bc_and_reference_against_vspaero_panel")
    if "mesh_quality_warning_present" in flags:
        actions.append("inspect_main_wing_mesh_quality_before_larger_solver_budget")
    if "reference_geometry_warn" in flags or "reference_geometry_fail" in flags:
        actions.append("resolve_reference_moment_origin_before_final_force_claims")
    if not actions:
        actions.append("rerun_lift_diagnostic_after_next_solver_smoke")
    return actions


def build_main_wing_lift_acceptance_diagnostic_report(
    *,
    report_root: Path | None = None,
) -> MainWingLiftAcceptanceDiagnosticReport:
    root = _default_report_root() if report_root is None else report_root
    selected_row, solver_payload, solver_report_path = _selected_solver_payload(root)
    panel_payload = _panel_reference_payload(root)
    surface_force_audit = _surface_force_output_audit_payload(root)
    panel_reference = _panel_reference_observed(panel_payload)
    coeffs = selected_row.get("final_coefficients", {})
    cl = _as_float(coeffs.get("cl")) if isinstance(coeffs, dict) else None
    solver_report_handoff_path = _resolve_path(
        solver_payload.get("su2_handoff_path") if isinstance(solver_payload, dict) else None,
        report_root=root,
        anchor_path=solver_report_path,
    )
    committed_handoff_path, handoff_path_source = _committed_su2_handoff_path(
        root,
        reference_policy=selected_row.get("reference_policy"),
    )
    solver_handoff_path = committed_handoff_path or solver_report_handoff_path
    if handoff_path_source is None and solver_handoff_path is not None:
        handoff_path_source = "solver_report_su2_handoff_path"
    handoff = _load_json(solver_handoff_path)
    runtime = handoff.get("runtime", {}) if isinstance(handoff, dict) else {}
    flow_conditions = (
        runtime.get("flow_conditions", {}) if isinstance(runtime, dict) else {}
    )
    reference = handoff.get("reference_geometry", {}) if isinstance(handoff, dict) else {}

    velocity_mps = _as_float(
        flow_conditions.get("velocity_mps")
        if isinstance(flow_conditions, dict)
        else None
    )
    if velocity_mps is None:
        velocity_mps = _as_float(selected_row.get("observed_velocity_mps"))
    density_kgpm3 = _as_float(
        flow_conditions.get("density_kgpm3")
        if isinstance(flow_conditions, dict)
        else None
    )
    if density_kgpm3 is None and isinstance(runtime, dict):
        density_kgpm3 = _as_float(runtime.get("density_kgpm3"))
    alpha_deg = _as_float(runtime.get("alpha_deg")) if isinstance(runtime, dict) else None
    ref_area_m2 = _as_float(reference.get("ref_area")) if isinstance(reference, dict) else None
    ref_length_m = _as_float(reference.get("ref_length")) if isinstance(reference, dict) else None
    reference_area_delta = _reference_gate_area_delta(root)
    final_iteration = selected_row.get("final_iteration")
    if final_iteration is None and isinstance(solver_payload, dict):
        final_iteration = solver_payload.get("final_iteration")
    reference_geometry_status = selected_row.get("reference_geometry_status")
    if reference_geometry_status is None and isinstance(solver_payload, dict):
        reference_geometry_status = solver_payload.get("reference_geometry_status")
    status = _diagnostic_status(
        cl=cl,
        velocity_mps=velocity_mps,
        convergence_gate_status=selected_row.get("convergence_gate_status"),
    )
    lift_gap = _lift_gap_diagnostics(
        solver_cl=cl,
        panel_reference=panel_reference,
        surface_force_audit=surface_force_audit,
    )
    flags = _engineering_flags(
        status=status,
        alpha_deg=alpha_deg,
        selected_row=selected_row,
        reference_geometry_status=reference_geometry_status,
        reference_area_delta=reference_area_delta,
        lift_gap=lift_gap,
    )
    root_cause_candidates = _root_cause_candidates(
        flags=flags,
        selected_row=selected_row,
        reference_area_delta=reference_area_delta,
        lift_gap=lift_gap,
    )
    return MainWingLiftAcceptanceDiagnosticReport(
        diagnostic_status=status,
        selected_solver_report={
            "report_path": None if solver_report_path is None else str(solver_report_path),
            "reference_policy": selected_row.get("reference_policy"),
            "runtime_max_iterations": selected_row.get("runtime_max_iterations"),
            "final_iteration": final_iteration,
            "convergence_gate_status": selected_row.get("convergence_gate_status"),
            "convergence_comparability_level": selected_row.get(
                "convergence_comparability_level"
            ),
            "coefficient_stability_status": selected_row.get(
                "coefficient_stability_status"
            ),
            "final_coefficients": coeffs if isinstance(coeffs, dict) else {},
            "su2_handoff_path": None if solver_handoff_path is None else str(solver_handoff_path),
            "su2_handoff_path_source": handoff_path_source,
            "solver_report_su2_handoff_path": (
                None
                if solver_report_handoff_path is None
                else str(solver_report_handoff_path)
            ),
        },
        panel_reference_observed=panel_reference,
        flow_condition_observed={
            "velocity_mps": velocity_mps,
            "density_kgpm3": density_kgpm3,
            "alpha_deg": alpha_deg,
            "flow_conditions_source_label": (
                flow_conditions.get("source_label")
                if isinstance(flow_conditions, dict)
                else None
            ),
        },
        reference_observed={
            "ref_area_m2": ref_area_m2,
            "ref_length_m": ref_length_m,
            "reference_geometry_status": reference_geometry_status,
            "declared_vs_openvsp_area_relative_error": reference_area_delta,
        },
        lift_metrics=_lift_metrics(
            cl=cl,
            velocity_mps=velocity_mps,
            density_kgpm3=density_kgpm3,
            ref_area_m2=ref_area_m2,
        ),
        lift_gap_diagnostics=lift_gap,
        root_cause_candidates=root_cause_candidates,
        engineering_flags=flags,
        engineering_assessment=_engineering_assessment(
            status=status,
            cl=cl,
            alpha_deg=alpha_deg,
            reference_area_delta=reference_area_delta,
            flags=flags,
            lift_gap=lift_gap,
        ),
        next_actions=_next_actions(flags),
        hpa_mdo_guarantees=[
            "report_only_no_solver_execution",
            "production_default_unchanged",
            "hpa_standard_flow_conditions_6p5_mps_checked",
            "main_wing_cl_gt_one_required_for_acceptance",
        ],
        limitations=[
            "This diagnostic cannot identify a converged lift curve without a bounded alpha or trim sweep.",
            "A low alpha=0 CL does not prove the aircraft cannot trim; it proves this route point cannot be accepted as converged main-wing evidence.",
            "Reference and mesh-quality warnings still need separate closure before CFD promotion.",
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


def _render_markdown(report: MainWingLiftAcceptanceDiagnosticReport) -> str:
    lines = [
        "# Main Wing Lift Acceptance Diagnostic v1",
        "",
        "This report reads existing solver-smoke artifacts only; it does not execute SU2.",
        "",
        f"- diagnostic_status: `{report.diagnostic_status}`",
        f"- hpa_standard_velocity_mps: `{report.hpa_standard_velocity_mps}`",
        f"- minimum_acceptable_cl: `{report.minimum_acceptable_cl}`",
        f"- production_default_changed: `{report.production_default_changed}`",
        "",
        "## Selected Solver Report",
        "",
    ]
    for key, value in report.selected_solver_report.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Panel Reference", ""])
    for key, value in report.panel_reference_observed.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Flow And Reference", ""])
    for key, value in report.flow_condition_observed.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    for key, value in report.reference_observed.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Lift Metrics", ""])
    for key, value in report.lift_metrics.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Lift Gap Diagnostics", ""])
    for key, value in report.lift_gap_diagnostics.items():
        lines.append(f"- `{key}`: `{_fmt(value)}`")
    lines.extend(["", "## Root Cause Candidates", ""])
    for candidate in report.root_cause_candidates:
        lines.append(f"- `{candidate.get('candidate')}`: `{candidate.get('priority')}`")
    lines.extend(["", "## Engineering Flags", ""])
    lines.extend(f"- `{flag}`" for flag in report.engineering_flags)
    lines.extend(["", "## Engineering Assessment", ""])
    lines.extend(f"- {item}" for item in report.engineering_assessment)
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- `{item}`" for item in report.next_actions)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_main_wing_lift_acceptance_diagnostic_report(
    out_dir: Path,
    *,
    report: MainWingLiftAcceptanceDiagnosticReport | None = None,
    report_root: Path | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_lift_acceptance_diagnostic_report(
            report_root=report_root
        )
    json_path = out_dir / "main_wing_lift_acceptance_diagnostic.v1.json"
    markdown_path = out_dir / "main_wing_lift_acceptance_diagnostic.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
