from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


GateStatusType = Literal["pass", "warn", "fail", "unavailable"]


class MainWingReferenceGeometryGateReport(BaseModel):
    schema_version: Literal["main_wing_reference_geometry_gate.v1"] = (
        "main_wing_reference_geometry_gate.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    execution_mode: Literal["reference_geometry_report_only_no_solver"] = (
        "reference_geometry_report_only_no_solver"
    )
    production_default_changed: bool = False
    reference_gate_status: GateStatusType
    source_fixture: str | None = None
    source_path: str | None = None
    source_geometry_report_path: str | None = None
    source_mesh_probe_report_path: str | None = None
    source_su2_probe_report_path: str | None = None
    su2_handoff_path: str | None = None
    observed_velocity_mps: float | None = None
    applied_reference: Dict[str, Any] = Field(default_factory=dict)
    derived_full_span_m: float | None = None
    geometry_bounds_span_y_m: float | None = None
    selected_geom_full_span_y_m: float | None = None
    selected_geom_chord_x_m: float | None = None
    geometry_bounds_chord_x_m: float | None = None
    checks: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    hpa_mdo_guarantees: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    error: str | None = None


def _default_report_root() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "reports"


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _resolve_payload_path(value: str | None, *, report_path: Path) -> Path | None:
    if value is None:
        return None
    raw = Path(value)
    if raw.is_absolute():
        return raw
    for root in [Path.cwd(), report_path.parent, *report_path.parents]:
        candidate = (root / raw).resolve()
        if candidate.exists():
            return candidate
    return (Path.cwd() / raw).resolve()


def _float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _bounds_span(bounds: dict[str, Any] | None, axis: str) -> float | None:
    if not isinstance(bounds, dict):
        return None
    lower = _float(bounds.get(f"{axis}_min"))
    upper = _float(bounds.get(f"{axis}_max"))
    if lower is None or upper is None:
        return None
    return upper - lower


def _check(
    status: GateStatusType,
    *,
    observed: dict[str, Any],
    expected: dict[str, Any],
    warnings: list[str] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "observed": observed,
        "expected": expected,
        "warnings": warnings or [],
        "notes": notes or [],
    }


def _overall_status(checks: dict[str, dict[str, Any]]) -> GateStatusType:
    statuses = [check.get("status") for check in checks.values()]
    if not statuses:
        return "unavailable"
    if "fail" in statuses or "unavailable" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def _relative_error(observed: float | None, expected: float | None) -> float | None:
    if observed is None or expected is None or abs(expected) <= 1.0e-12:
        return None
    return abs(observed - expected) / abs(expected)


def _reference_from_su2_handoff(su2_handoff: dict[str, Any]) -> dict[str, Any]:
    reference = su2_handoff.get("reference_geometry")
    if isinstance(reference, dict) and reference.get("ref_area") is not None:
        return reference
    runtime = su2_handoff.get("runtime", {})
    override = runtime.get("reference_override") if isinstance(runtime, dict) else None
    return override if isinstance(override, dict) else {}


def _runtime_reference_override(su2_handoff: dict[str, Any]) -> dict[str, Any]:
    runtime = su2_handoff.get("runtime", {})
    override = runtime.get("reference_override") if isinstance(runtime, dict) else None
    return override if isinstance(override, dict) else {}


def _unavailable_report(
    *,
    report_root: Path,
    reason: str,
    error: str | None = None,
) -> MainWingReferenceGeometryGateReport:
    return MainWingReferenceGeometryGateReport(
        reference_gate_status="unavailable",
        source_geometry_report_path=str(
            report_root
            / "main_wing_esp_rebuilt_geometry_smoke"
            / "main_wing_esp_rebuilt_geometry_smoke.v1.json"
        ),
        source_mesh_probe_report_path=str(
            report_root
            / "main_wing_real_mesh_handoff_probe"
            / "main_wing_real_mesh_handoff_probe.v1.json"
        ),
        source_su2_probe_report_path=str(
            report_root
            / "main_wing_real_su2_handoff_probe"
            / "main_wing_real_su2_handoff_probe.v1.json"
        ),
        hpa_mdo_guarantees=[
            "reference_geometry_not_promoted_to_pass",
            "production_default_unchanged",
        ],
        blocking_reasons=[reason],
        limitations=[
            "Reference geometry gate could not load enough source artifacts.",
            "No solver or convergence claim is made by this report-only gate.",
        ],
        error=error,
    )


def build_main_wing_reference_geometry_gate_report(
    *,
    report_root: Path | None = None,
) -> MainWingReferenceGeometryGateReport:
    root = _default_report_root() if report_root is None else report_root
    geometry_path = (
        root
        / "main_wing_esp_rebuilt_geometry_smoke"
        / "main_wing_esp_rebuilt_geometry_smoke.v1.json"
    )
    mesh_probe_path = (
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json"
    )
    su2_probe_path = (
        root
        / "main_wing_real_su2_handoff_probe"
        / "main_wing_real_su2_handoff_probe.v1.json"
    )

    geometry = _load_json(geometry_path)
    mesh_probe = _load_json(mesh_probe_path)
    su2_probe = _load_json(su2_probe_path)
    if not isinstance(su2_probe, dict):
        return _unavailable_report(
            report_root=root,
            reason="main_wing_real_su2_handoff_reference_unavailable",
        )

    su2_handoff_path = _resolve_payload_path(
        su2_probe.get("su2_handoff_path"),
        report_path=su2_probe_path,
    )
    su2_handoff = _load_json(su2_handoff_path) if su2_handoff_path is not None else None
    if not isinstance(su2_handoff, dict):
        return _unavailable_report(
            report_root=root,
            reason="main_wing_real_su2_handoff_reference_unavailable",
            error=f"missing su2_handoff: {su2_probe.get('su2_handoff_path')}",
        )

    reference = _reference_from_su2_handoff(su2_handoff)
    override = _runtime_reference_override(su2_handoff)
    ref_area = _float(reference.get("ref_area"))
    ref_length = _float(reference.get("ref_length"))
    origin = reference.get("ref_origin_moment")
    runtime = su2_handoff.get("runtime", {})
    observed_velocity = (
        _float(runtime.get("velocity_mps")) if isinstance(runtime, dict) else None
    )
    if observed_velocity is None:
        observed_velocity = _float(su2_probe.get("observed_velocity_mps"))

    derived_full_span = (
        ref_area / ref_length
        if ref_area is not None and ref_length is not None and ref_length > 0.0
        else None
    )
    bounds = geometry.get("bounds") if isinstance(geometry, dict) else None
    bounds_span_y = _bounds_span(bounds, "y")
    bounds_chord_x = _bounds_span(bounds, "x")
    selected_span = (
        _float(geometry.get("selected_geom_span_y"))
        if isinstance(geometry, dict)
        else None
    )
    if selected_span is None and isinstance(mesh_probe, dict):
        selected_span = _float(mesh_probe.get("selected_geom_span_y"))
    selected_full_span = None if selected_span is None else 2.0 * selected_span
    selected_chord = (
        _float(geometry.get("selected_geom_chord_x"))
        if isinstance(geometry, dict)
        else None
    )
    if selected_chord is None and isinstance(mesh_probe, dict):
        selected_chord = _float(mesh_probe.get("selected_geom_chord_x"))

    checks: dict[str, dict[str, Any]] = {}
    positive_status: GateStatusType = (
        "pass"
        if ref_area is not None
        and ref_area > 0.0
        and ref_length is not None
        and ref_length > 0.0
        and isinstance(origin, dict)
        else "fail"
    )
    checks["positive_reference_values"] = _check(
        positive_status,
        observed={
            "ref_area": ref_area,
            "ref_length": ref_length,
            "ref_origin_moment": origin,
        },
        expected={
            "ref_area": "> 0",
            "ref_length": "> 0",
            "ref_origin_moment": "present",
        },
    )

    bounds_error = _relative_error(derived_full_span, bounds_span_y)
    bounds_status: GateStatusType = (
        "pass"
        if bounds_error is not None and bounds_error <= 0.01
        else "warn"
        if bounds_error is not None
        else "unavailable"
    )
    checks["declared_span_vs_bounds_y"] = _check(
        bounds_status,
        observed={
            "declared_span_from_ref_area_over_ref_length_m": derived_full_span,
            "geometry_bounds_span_y_m": bounds_span_y,
            "relative_error": bounds_error,
        },
        expected={"relative_error_max": 0.01},
    )

    selected_error = _relative_error(derived_full_span, selected_full_span)
    selected_status: GateStatusType = (
        "pass"
        if selected_error is not None and selected_error <= 0.01
        else "warn"
        if selected_error is not None
        else "unavailable"
    )
    checks["declared_span_vs_selected_geom_span"] = _check(
        selected_status,
        observed={
            "declared_span_from_ref_area_over_ref_length_m": derived_full_span,
            "selected_geom_full_span_y_m": selected_full_span,
            "relative_error": selected_error,
        },
        expected={"relative_error_max": 0.01},
    )

    chord_error = _relative_error(ref_length, selected_chord)
    checks["ref_length_independent_source"] = _check(
        "warn",
        observed={
            "ref_length_m": ref_length,
            "selected_geom_chord_x_m": selected_chord,
            "geometry_bounds_chord_x_m": bounds_chord_x,
            "ref_length_vs_selected_chord_relative_error": chord_error,
        },
        expected={
            "independent_aerodynamic_chord_source": True,
            "selected_geom_chord_x_is_not_certified_ref_chord": True,
        },
        warnings=["main_wing_reference_chord_not_independently_certified"],
        notes=[
            "The declared 1.05 m reference chord is plausible but not independently certified by the current geometry artifacts.",
            "The x-projection bounds include geometric projection effects and must not be treated as the reference chord by itself.",
        ],
    )

    override_warnings = override.get("warnings", []) if isinstance(override, dict) else []
    checks["moment_origin_policy"] = _check(
        "warn",
        observed={
            "ref_origin_moment": origin,
            "source_label": override.get("source_label") if isinstance(override, dict) else None,
            "override_warnings": override_warnings,
        },
        expected={
            "moment_origin_independent_source": True,
            "cg_or_aerodynamic_reference_policy": "documented",
        },
        warnings=["main_wing_moment_origin_not_certified"],
        notes=[
            "Quarter-chord moment origin is declared for this probe but not yet tied to an aircraft CG or approved aerodynamic reference policy.",
        ],
    )

    status = _overall_status(checks)
    blocking_reasons: list[str] = []
    if status != "pass":
        blocking_reasons.append("main_wing_reference_geometry_incomplete")
    if checks["ref_length_independent_source"]["status"] != "pass":
        blocking_reasons.append("main_wing_reference_chord_not_independently_certified")
    if checks["moment_origin_policy"]["status"] != "pass":
        blocking_reasons.append("main_wing_moment_origin_not_certified")

    hpa_mdo_guarantees = [
        "reference_geometry_gate_evaluated",
        "reference_geometry_not_promoted_to_pass",
        "production_default_unchanged",
    ]
    if checks["positive_reference_values"]["status"] == "pass":
        hpa_mdo_guarantees.append("ref_area_ref_length_and_origin_present")
    if checks["declared_span_vs_bounds_y"]["status"] == "pass":
        hpa_mdo_guarantees.append("declared_span_crosschecked_against_real_geometry_bounds")
    if observed_velocity == 6.5:
        hpa_mdo_guarantees.append("hpa_standard_flow_conditions_6p5_mps_observed")

    return MainWingReferenceGeometryGateReport(
        reference_gate_status=status,
        source_fixture=None if geometry is None else geometry.get("source_fixture"),
        source_path=None if geometry is None else geometry.get("source_path"),
        source_geometry_report_path=str(geometry_path),
        source_mesh_probe_report_path=str(mesh_probe_path),
        source_su2_probe_report_path=str(su2_probe_path),
        su2_handoff_path=None if su2_handoff_path is None else str(su2_handoff_path),
        observed_velocity_mps=observed_velocity,
        applied_reference={
            "ref_area": ref_area,
            "ref_length": ref_length,
            "ref_origin_moment": origin,
            "source_label": override.get("source_label") if isinstance(override, dict) else None,
        },
        derived_full_span_m=derived_full_span,
        geometry_bounds_span_y_m=bounds_span_y,
        selected_geom_full_span_y_m=selected_full_span,
        selected_geom_chord_x_m=selected_chord,
        geometry_bounds_chord_x_m=bounds_chord_x,
        checks=checks,
        hpa_mdo_guarantees=hpa_mdo_guarantees,
        blocking_reasons=blocking_reasons,
        limitations=[
            "This gate is report-only and does not change the SU2 runtime config.",
            "Span is cross-checked against real geometry bounds, but the reference chord is still user-declared.",
            "Moment origin is a declared quarter-chord probe policy, not a certified aircraft CG or aerodynamic-reference policy.",
            "A reference-geometry warn must remain a comparability blocker for solver/convergence results.",
        ],
    )


def _render_markdown(report: MainWingReferenceGeometryGateReport) -> str:
    lines = [
        "# main_wing reference geometry gate v1",
        "",
        "This report checks the provenance of the reference quantities used by the real main-wing SU2 handoff.",
        "",
        f"- reference_gate_status: `{report.reference_gate_status}`",
        f"- observed_velocity_mps: `{report.observed_velocity_mps}`",
        f"- ref_area: `{report.applied_reference.get('ref_area')}`",
        f"- ref_length: `{report.applied_reference.get('ref_length')}`",
        f"- derived_full_span_m: `{report.derived_full_span_m}`",
        f"- geometry_bounds_span_y_m: `{report.geometry_bounds_span_y_m}`",
        f"- selected_geom_full_span_y_m: `{report.selected_geom_full_span_y_m}`",
        f"- selected_geom_chord_x_m: `{report.selected_geom_chord_x_m}`",
        f"- geometry_bounds_chord_x_m: `{report.geometry_bounds_chord_x_m}`",
        "",
        "## Checks",
        "",
        "| check | status |",
        "|---|---|",
    ]
    for name, check in report.checks.items():
        lines.append(f"| `{name}` | `{check.get('status')}` |")
    lines.extend(["", "## Blocking Reasons", ""])
    lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    lines.extend(["", "## HPA-MDO Guarantees", ""])
    lines.extend(f"- `{guarantee}`" for guarantee in report.hpa_mdo_guarantees)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_main_wing_reference_geometry_gate_report(
    out_dir: Path,
    report: MainWingReferenceGeometryGateReport | None = None,
    *,
    report_root: Path | None = None,
) -> Dict[str, Path]:
    if report is None:
        report = build_main_wing_reference_geometry_gate_report(report_root=report_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "main_wing_reference_geometry_gate.v1.json"
    markdown_path = out_dir / "main_wing_reference_geometry_gate.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
