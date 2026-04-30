from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5 = 1.0

PanelReferenceStatusType = Literal[
    "panel_reference_available",
    "panel_reference_missing",
    "panel_reference_nonstandard_flow",
]
LiftAcceptanceStatusType = Literal["pass", "fail", "not_evaluated"]
HPAFlowStatusType = Literal[
    "hpa_standard_6p5_observed",
    "legacy_or_nonstandard_velocity_observed",
    "unavailable",
]


class MainWingVSPAeroPanelReferenceProbeReport(BaseModel):
    schema_version: Literal["main_wing_vspaero_panel_reference_probe.v1"] = (
        "main_wing_vspaero_panel_reference_probe.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_scope: Literal["report_only_existing_vspaero_panel_artifacts"] = (
        "report_only_existing_vspaero_panel_artifacts"
    )
    production_default_changed: bool = False
    panel_reference_status: PanelReferenceStatusType
    source_polar_path: str
    source_setup_path: str | None = None
    hpa_standard_velocity_mps: float = 6.5
    hpa_standard_flow_status: HPAFlowStatusType = "unavailable"
    minimum_acceptable_cl: float = MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5
    lift_acceptance_status: LiftAcceptanceStatusType = "not_evaluated"
    selected_case: Dict[str, Any] = Field(default_factory=dict)
    setup_reference: Dict[str, Any] = Field(default_factory=dict)
    su2_smoke_comparison: Dict[str, Any] = Field(default_factory=dict)
    engineering_assessment: List[str] = Field(default_factory=list)
    engineering_flags: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    hpa_mdo_guarantees: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    error: str | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_polar_path() -> Path:
    return (
        _repo_root()
        / "output"
        / "dihedral_sweep_fixed_alpha_smoke_rerun"
        / "origin_vsp_panel_fixed_alpha_baseline"
        / "black_cat_004.polar"
    )


def _default_setup_path(polar_path: Path) -> Path:
    return polar_path.with_suffix(".vspaero")


def _default_lift_diagnostic_path() -> Path:
    return (
        _repo_root()
        / "hpa_meshing_package"
        / "docs"
        / "reports"
        / "main_wing_lift_acceptance_diagnostic"
        / "main_wing_lift_acceptance_diagnostic.v1.json"
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


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _parse_key_value_setup(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    parsed: dict[str, Any] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = _as_float(raw_value.strip().split()[0])
        parsed[key] = value if value is not None else raw_value.strip()
    return parsed


def _looks_like_polar_header(tokens: list[str]) -> bool:
    lowered = {token.lower() for token in tokens}
    return "aoa" in lowered and "cltot" in lowered and "cdtot" in lowered


def _parse_polar_first_case(path: Path) -> dict[str, Any]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    for index, line in enumerate(lines):
        tokens = line.split()
        if not _looks_like_polar_header(tokens):
            continue
        header = tokens
        for data_line in lines[index + 1 :]:
            values = data_line.split()
            if len(values) != len(header):
                continue
            numeric = [_as_float(value) for value in values]
            if any(value is None for value in numeric):
                continue
            return dict(zip(header, numeric))
    raise ValueError(f"Could not find VSPAERO polar case in {path}")


def _flow_status(velocity_mps: float | None) -> HPAFlowStatusType:
    if velocity_mps is None:
        return "unavailable"
    if abs(velocity_mps - 6.5) <= 1.0e-9:
        return "hpa_standard_6p5_observed"
    return "legacy_or_nonstandard_velocity_observed"


def _lift_acceptance(cl: float | None, velocity_mps: float | None) -> LiftAcceptanceStatusType:
    if cl is None or velocity_mps is None or abs(velocity_mps - 6.5) > 1.0e-9:
        return "not_evaluated"
    return "pass" if cl > MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5 else "fail"


def _su2_comparison(
    *,
    panel_cl: float | None,
    lift_diagnostic_report: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(lift_diagnostic_report, dict):
        return {
            "status": "not_available",
            "reason": "main_wing_lift_acceptance_diagnostic_missing",
        }
    metrics = lift_diagnostic_report.get("lift_metrics", {})
    selected = lift_diagnostic_report.get("selected_solver_report", {})
    su2_cl = _as_float(metrics.get("cl") if isinstance(metrics, dict) else None)
    if panel_cl is None or su2_cl is None:
        return {
            "status": "not_available",
            "reason": "panel_or_su2_cl_missing",
        }
    return {
        "status": "available",
        "panel_reference_cl": panel_cl,
        "selected_su2_smoke_cl": su2_cl,
        "cl_delta_panel_minus_su2": panel_cl - su2_cl,
        "panel_to_su2_cl_ratio": panel_cl / su2_cl if abs(su2_cl) > 1.0e-12 else None,
        "selected_su2_runtime_max_iterations": (
            selected.get("runtime_max_iterations") if isinstance(selected, dict) else None
        ),
        "selected_su2_report_path": (
            selected.get("report_path") if isinstance(selected, dict) else None
        ),
        "interpretation": (
            "panel_reference_supports_cl_gt_one_gate_current_su2_smoke_low_lift"
        ),
    }


def _assessment(
    *,
    status: PanelReferenceStatusType,
    cl: float | None,
    velocity_mps: float | None,
    alpha_deg: float | None,
    comparison: dict[str, Any],
) -> list[str]:
    assessment = [
        "This probe reads existing VSPAERO panel-mode artifacts only and does not run VSPAERO, Gmsh, or SU2.",
        "VSPAERO panel evidence is a lower-order aerodynamic reference, not high-fidelity CFD convergence.",
    ]
    if status == "panel_reference_available" and cl is not None:
        assessment.append(
            f"The selected panel-mode reference reports CL={cl:.6g} at alpha={alpha_deg:.6g} deg and V={velocity_mps:.6g} m/s."
        )
        if cl > MIN_MAIN_WING_ACCEPTABLE_CL_AT_HPA_6P5:
            assessment.append(
                "This supports treating CL <= 1.0 as an HPA operating-point blocker, not as an arbitrary software threshold."
            )
    if comparison.get("status") == "available":
        assessment.append(
            "The current SU2 smoke CL is far below the panel-mode reference; that gap should be treated as route/trim/mesh/reference risk until isolated."
        )
    return assessment


def _flags(
    *,
    hpa_flow_status: HPAFlowStatusType,
    lift_acceptance_status: LiftAcceptanceStatusType,
    comparison: dict[str, Any],
) -> list[str]:
    flags: list[str] = []
    if hpa_flow_status != "hpa_standard_6p5_observed":
        flags.append("vspaero_panel_reference_nonstandard_flow")
    if lift_acceptance_status == "pass":
        flags.append("vspaero_panel_reference_cl_gt_one")
    elif lift_acceptance_status == "fail":
        flags.append("vspaero_panel_reference_cl_below_expected_lift")
    if comparison.get("status") == "available":
        flags.append("su2_smoke_below_vspaero_panel_reference")
    return flags


def build_main_wing_vspaero_panel_reference_probe_report(
    *,
    polar_path: Path | None = None,
    setup_path: Path | None = None,
    lift_diagnostic_path: Path | None = None,
) -> MainWingVSPAeroPanelReferenceProbeReport:
    polar = _default_polar_path() if polar_path is None else polar_path
    setup = _default_setup_path(polar) if setup_path is None else setup_path
    lift_path = (
        _default_lift_diagnostic_path()
        if lift_diagnostic_path is None
        else lift_diagnostic_path
    )
    try:
        selected_case = _parse_polar_first_case(polar)
    except Exception as exc:
        return MainWingVSPAeroPanelReferenceProbeReport(
            panel_reference_status="panel_reference_missing",
            source_polar_path=str(polar),
            source_setup_path=str(setup) if setup is not None else None,
            error=str(exc),
            hpa_mdo_guarantees=[
                "report_only_no_solver_execution",
                "production_default_unchanged",
            ],
            limitations=["VSPAERO panel polar evidence could not be parsed."],
        )
    setup_reference = _parse_key_value_setup(setup)
    velocity = _as_float(setup_reference.get("Vinf"))
    if velocity is None:
        velocity = _as_float(selected_case.get("Vinf"))
    alpha = _as_float(selected_case.get("AoA"))
    cl = _as_float(selected_case.get("CLtot"))
    hpa_flow_status = _flow_status(velocity)
    lift_status = _lift_acceptance(cl, velocity)
    panel_status: PanelReferenceStatusType = (
        "panel_reference_available"
        if hpa_flow_status == "hpa_standard_6p5_observed"
        else "panel_reference_nonstandard_flow"
    )
    lift_diagnostic = _load_json(lift_path)
    comparison = _su2_comparison(
        panel_cl=cl,
        lift_diagnostic_report=lift_diagnostic,
    )
    flags = _flags(
        hpa_flow_status=hpa_flow_status,
        lift_acceptance_status=lift_status,
        comparison=comparison,
    )
    return MainWingVSPAeroPanelReferenceProbeReport(
        panel_reference_status=panel_status,
        source_polar_path=str(polar),
        source_setup_path=str(setup) if setup is not None else None,
        hpa_standard_flow_status=hpa_flow_status,
        lift_acceptance_status=lift_status,
        selected_case=selected_case,
        setup_reference=setup_reference,
        su2_smoke_comparison=comparison,
        engineering_assessment=_assessment(
            status=panel_status,
            cl=cl,
            velocity_mps=velocity,
            alpha_deg=alpha,
            comparison=comparison,
        ),
        engineering_flags=flags,
        next_actions=[
            "use_vspaero_panel_reference_as_sanity_baseline_not_cfd_truth",
            "keep_main_wing_cl_gt_one_acceptance_gate_for_hpa_operating_point",
            "separate_su2_low_lift_gap_into_alpha_trim_mesh_quality_and_reference_checks",
        ],
        hpa_mdo_guarantees=[
            "report_only_no_solver_execution",
            "production_default_unchanged",
            "hpa_standard_flow_conditions_6p5_mps_checked",
            "vspaero_panel_reference_not_promoted_to_su2_convergence",
        ],
        limitations=[
            "The selected VSPAERO panel artifact is lower-order aerodynamic reference evidence, not SU2 convergence evidence.",
            "This probe reads integrated polar coefficients and does not certify force-marker ownership for a SU2 mesh.",
            "A panel-vs-SU2 CL gap identifies route risk; it does not by itself identify whether alpha, trim, mesh quality, or reference geometry is the root cause.",
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


def _render_markdown(report: MainWingVSPAeroPanelReferenceProbeReport) -> str:
    lines = [
        "# Main Wing VSPAERO Panel Reference Probe v1",
        "",
        "This report reads existing VSPAERO panel-mode artifacts only; it does not run VSPAERO, Gmsh, or SU2.",
        "",
        f"- panel_reference_status: `{report.panel_reference_status}`",
        f"- hpa_standard_flow_status: `{report.hpa_standard_flow_status}`",
        f"- lift_acceptance_status: `{report.lift_acceptance_status}`",
        f"- minimum_acceptable_cl: `{report.minimum_acceptable_cl}`",
        f"- source_polar_path: `{report.source_polar_path}`",
        f"- source_setup_path: `{_fmt(report.source_setup_path)}`",
        "",
        "## Selected Case",
        "",
        f"- AoA: `{_fmt(report.selected_case.get('AoA'))}`",
        f"- CLtot: `{_fmt(report.selected_case.get('CLtot'))}`",
        f"- CDtot: `{_fmt(report.selected_case.get('CDtot'))}`",
        f"- L/D: `{_fmt(report.selected_case.get('L/D'))}`",
        f"- Vinf: `{_fmt(report.setup_reference.get('Vinf'))}`",
        f"- Sref: `{_fmt(report.setup_reference.get('Sref'))}`",
        "",
        "## SU2 Smoke Comparison",
        "",
        f"- comparison: `{_fmt(report.su2_smoke_comparison)}`",
        "",
        "## Engineering Assessment",
        "",
    ]
    lines.extend(f"- {item}" for item in report.engineering_assessment)
    lines.extend(["", "## Engineering Flags", ""])
    lines.extend(f"- `{flag}`" for flag in report.engineering_flags)
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- `{action}`" for action in report.next_actions)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_main_wing_vspaero_panel_reference_probe_report(
    out_dir: Path,
    *,
    report: MainWingVSPAeroPanelReferenceProbeReport | None = None,
    polar_path: Path | None = None,
    setup_path: Path | None = None,
    lift_diagnostic_path: Path | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if report is None:
        report = build_main_wing_vspaero_panel_reference_probe_report(
            polar_path=polar_path,
            setup_path=setup_path,
            lift_diagnostic_path=lift_diagnostic_path,
        )
    json_path = out_dir / "main_wing_vspaero_panel_reference_probe.v1.json"
    markdown_path = out_dir / "main_wing_vspaero_panel_reference_probe.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
