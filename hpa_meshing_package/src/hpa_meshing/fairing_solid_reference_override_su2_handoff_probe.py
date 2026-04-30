from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from .adapters.su2_backend import materialize_baseline_case
from .fairing_solid_real_su2_handoff_probe import (
    _load_mesh_handoff_from_case_report,
    _source_root_for_mesh_handoff,
)
from .schema import Point3D, SU2RuntimeConfig


MaterializationStatusType = Literal[
    "su2_handoff_written",
    "blocked_before_reference_override",
    "blocked_before_su2_handoff",
    "failed",
    "unavailable",
]
ReferenceOverrideStatusType = Literal[
    "applied",
    "applied_with_moment_origin_warning",
    "missing",
    "invalid",
    "insufficient_evidence",
]
MarkerMappingStatusType = Literal[
    "mapped_external_fairing_to_fairing_solid",
    "compatible",
    "missing",
    "unknown",
]
SolverExecutionStatusType = Literal["not_run", "unexpected_run", "unknown"]
ConvergenceGateStatusType = Literal["not_run", "unexpected_present", "unknown"]
ComponentForceOwnershipStatusType = Literal[
    "owned",
    "missing",
    "insufficient_evidence",
]


class FairingAppliedReferencePolicy(BaseModel):
    ref_area: float | None = None
    ref_length: float | None = None
    velocity_mps: float | None = None
    density_kgpm3: float | None = None
    dynamic_viscosity_pas: float | None = None
    temperature_k: float | None = None
    ref_origin_moment: Point3D | None = None
    source_path: str | None = None
    source_label: str | None = None


class FairingSolidReferenceOverrideSU2HandoffProbeReport(BaseModel):
    schema_version: Literal["fairing_solid_reference_override_su2_handoff_probe.v1"] = (
        "fairing_solid_reference_override_su2_handoff_probe.v1"
    )
    component: Literal["fairing_solid"] = "fairing_solid"
    execution_mode: Literal[
        "external_reference_override_su2_materialization_only_no_solver"
    ] = "external_reference_override_su2_materialization_only_no_solver"
    source_reference_policy_schema: Literal["fairing_solid_reference_policy_probe.v1"] = (
        "fairing_solid_reference_policy_probe.v1"
    )
    source_su2_probe_schema: Literal["fairing_solid_real_su2_handoff_probe.v1"] = (
        "fairing_solid_real_su2_handoff_probe.v1"
    )
    case_dir: str
    no_su2_execution: bool = True
    no_gmsh_execution: bool = False
    no_bl_runtime: bool = True
    production_default_changed: bool = False
    materialization_status: MaterializationStatusType
    reference_override_status: ReferenceOverrideStatusType
    marker_mapping_status: MarkerMappingStatusType = "unknown"
    source_reference_policy_status: str | None = None
    source_external_reference_status: str | None = None
    source_hpa_reference_status: str | None = None
    previous_reference: FairingAppliedReferencePolicy = Field(
        default_factory=FairingAppliedReferencePolicy
    )
    applied_reference: FairingAppliedReferencePolicy = Field(
        default_factory=FairingAppliedReferencePolicy
    )
    reference_mismatch_fields: List[str] = Field(default_factory=list)
    moment_origin_policy_status: str | None = None
    source_reference_policy_probe_path: str | None = None
    source_su2_probe_report_path: str | None = None
    source_mesh_case_report_path: str | None = None
    source_su2_handoff_path: str | None = None
    su2_contract: str | None = None
    input_mesh_contract: str | None = None
    solver_execution_status: SolverExecutionStatusType = "not_run"
    convergence_gate_status: ConvergenceGateStatusType = "not_run"
    run_status: str | None = None
    reference_geometry_status: str | None = None
    wall_marker_status: str | None = None
    force_surface_scope: str | None = None
    component_force_ownership_status: ComponentForceOwnershipStatusType = (
        "insufficient_evidence"
    )
    su2_handoff_path: str | None = None
    su2_mesh_path: str | None = None
    runtime_cfg_path: str | None = None
    history_path: str | None = None
    hpa_mdo_guarantees: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    error: str | None = None


def _default_reference_policy_probe_path() -> Path:
    return Path(
        "hpa_meshing_package/docs/reports/fairing_solid_reference_policy_probe/"
        "fairing_solid_reference_policy_probe.v1.json"
    )


def _default_source_su2_probe_report_path() -> Path:
    return Path(
        "hpa_meshing_package/docs/reports/fairing_solid_real_su2_handoff_probe/"
        "fairing_solid_real_su2_handoff_probe.v1.json"
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_report_relative_path(path: Path, report_path: Path) -> Path:
    if path.is_absolute() or path.exists():
        return path
    for candidate_root in [Path.cwd(), Path.cwd().parent, report_path.parent, *report_path.parents]:
        candidate = candidate_root / path
        if candidate.exists():
            return candidate
    parts = path.parts
    if parts and parts[0] == Path.cwd().name:
        stripped = Path(*parts[1:])
        if stripped.exists():
            return stripped
    return path


def _nested_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _float_value(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive(value: float | None) -> bool:
    return value is not None and value > 0.0


def _external_reference_complete(external: dict[str, Any]) -> bool:
    return all(
        _positive(_float_value(external, field))
        for field in [
            "ref_area",
            "ref_length",
            "velocity_mps",
            "density_kgpm3",
            "dynamic_viscosity_pas",
        ]
    )


def _entry_from_payload(payload: dict[str, Any]) -> FairingAppliedReferencePolicy:
    return FairingAppliedReferencePolicy(
        ref_area=_float_value(payload, "ref_area"),
        ref_length=_float_value(payload, "ref_length"),
        velocity_mps=_float_value(payload, "velocity_mps"),
        density_kgpm3=_float_value(payload, "density_kgpm3"),
        dynamic_viscosity_pas=_float_value(payload, "dynamic_viscosity_pas"),
        temperature_k=_float_value(payload, "temperature_k"),
        source_path=payload.get("source_path") if isinstance(payload.get("source_path"), str) else None,
        source_label=payload.get("source_kind") if isinstance(payload.get("source_kind"), str) else None,
    )


def _marker_mapping_status(
    external_reference: dict[str, Any],
    hpa_reference: dict[str, Any],
    source_status: str | None,
) -> MarkerMappingStatusType:
    if source_status == "compatible_mapping_required":
        return "mapped_external_fairing_to_fairing_solid"
    external_marker = external_reference.get("wall_marker")
    hpa_marker = hpa_reference.get("wall_marker")
    if not isinstance(external_marker, str) or not isinstance(hpa_marker, str):
        return "missing"
    if external_marker == hpa_marker:
        return "compatible"
    if external_marker == "fairing" and hpa_marker == "fairing_solid":
        return "mapped_external_fairing_to_fairing_solid"
    return "unknown"


def _source_su2_handoff_path(
    source_su2_probe: dict[str, Any],
    source_su2_probe_path: Path,
) -> Path | None:
    value = source_su2_probe.get("su2_handoff_path")
    if not isinstance(value, str):
        return None
    return _resolve_report_relative_path(Path(value), source_su2_probe_path)


def _source_mesh_case_report_path(
    source_su2_probe: dict[str, Any],
    source_su2_probe_path: Path,
) -> Path | None:
    value = source_su2_probe.get("source_mesh_case_report_path")
    if not isinstance(value, str):
        return None
    return _resolve_report_relative_path(Path(value), source_su2_probe_path)


def _reference_origin_from_source(
    source_su2_handoff_path: Path | None,
) -> tuple[Point3D, str, list[str]]:
    if source_su2_handoff_path is None or not source_su2_handoff_path.exists():
        return (
            Point3D(x=0.0, y=0.0, z=0.0),
            "fallback_zero_origin",
            ["source_su2_handoff_reference_origin_missing"],
        )
    payload = _load_json(source_su2_handoff_path)
    reference = _nested_dict(payload, "reference_geometry")
    origin_payload = _nested_dict(reference, "ref_origin_moment")
    origin = Point3D(
        x=_float_value(origin_payload, "x") or 0.0,
        y=_float_value(origin_payload, "y") or 0.0,
        z=_float_value(origin_payload, "z") or 0.0,
    )
    warnings = [
        str(warning)
        for warning in reference.get("warnings", [])
        if isinstance(warning, str)
    ]
    if origin.x == 0.0 and origin.y == 0.0 and origin.z == 0.0:
        warnings.append("borrowed_zero_moment_origin_from_source_su2_handoff")
        return origin, "borrowed_zero_origin_for_drag_only", warnings
    return origin, "borrowed_source_su2_handoff_origin", warnings


def _component_force_ownership(wall_marker: str | None) -> ComponentForceOwnershipStatusType:
    return "owned" if wall_marker == "fairing_solid" else "missing"


def _wall_marker_status(wall_marker: str | None) -> str:
    if wall_marker == "fairing_solid":
        return "fairing_solid_marker_present"
    if wall_marker == "aircraft":
        return "generic_aircraft_wall_present"
    if wall_marker:
        return "missing"
    return "unavailable"


def _blocked_report(
    *,
    out_dir: Path,
    reference_policy_probe_path: Path | None,
    source_su2_probe_report_path: Path | None,
    materialization_status: MaterializationStatusType,
    reference_override_status: ReferenceOverrideStatusType,
    blocking_reasons: list[str],
    limitations: list[str],
    reference_policy_payload: dict[str, Any] | None = None,
    source_su2_probe_payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> FairingSolidReferenceOverrideSU2HandoffProbeReport:
    reference_policy_payload = reference_policy_payload or {}
    source_su2_probe_payload = source_su2_probe_payload or {}
    external_reference = _nested_dict(reference_policy_payload, "external_reference")
    hpa_reference = _nested_dict(reference_policy_payload, "hpa_current_reference")
    return FairingSolidReferenceOverrideSU2HandoffProbeReport(
        case_dir=str(out_dir),
        materialization_status=materialization_status,
        reference_override_status=reference_override_status,
        marker_mapping_status=_marker_mapping_status(
            external_reference,
            hpa_reference,
            reference_policy_payload.get("marker_mapping_status")
            if isinstance(reference_policy_payload.get("marker_mapping_status"), str)
            else None,
        ),
        source_reference_policy_status=reference_policy_payload.get("reference_policy_status")
        if isinstance(reference_policy_payload.get("reference_policy_status"), str)
        else None,
        source_external_reference_status=reference_policy_payload.get("external_reference_status")
        if isinstance(reference_policy_payload.get("external_reference_status"), str)
        else None,
        source_hpa_reference_status=reference_policy_payload.get("hpa_current_reference_status")
        if isinstance(reference_policy_payload.get("hpa_current_reference_status"), str)
        else None,
        previous_reference=_entry_from_payload(hpa_reference),
        applied_reference=_entry_from_payload(external_reference),
        reference_mismatch_fields=[
            str(field)
            for field in reference_policy_payload.get("reference_mismatch_fields", [])
            if isinstance(field, str)
        ],
        source_reference_policy_probe_path=None
        if reference_policy_probe_path is None
        else str(reference_policy_probe_path),
        source_su2_probe_report_path=None
        if source_su2_probe_report_path is None
        else str(source_su2_probe_report_path),
        source_mesh_case_report_path=source_su2_probe_payload.get("source_mesh_case_report_path")
        if isinstance(source_su2_probe_payload.get("source_mesh_case_report_path"), str)
        else None,
        source_su2_handoff_path=source_su2_probe_payload.get("su2_handoff_path")
        if isinstance(source_su2_probe_payload.get("su2_handoff_path"), str)
        else None,
        blocking_reasons=blocking_reasons,
        limitations=limitations,
        error=error,
    )


def _runtime_config(
    external_reference: dict[str, Any],
    origin: Point3D,
    origin_warnings: list[str],
) -> SU2RuntimeConfig:
    return SU2RuntimeConfig(
        enabled=True,
        case_name="alpha_0_real_fairing_reference_override_probe",
        max_iterations=12,
        reference_mode="user_declared",
        velocity_mps=float(external_reference["velocity_mps"]),
        density_kgpm3=float(external_reference["density_kgpm3"]),
        dynamic_viscosity_pas=float(external_reference["dynamic_viscosity_pas"]),
        temperature_k=float(external_reference.get("temperature_k") or 288.15),
        reference_override={
            "ref_area": float(external_reference["ref_area"]),
            "ref_length": float(external_reference["ref_length"]),
            "ref_origin_moment": origin.model_dump(mode="json"),
            "source_label": "external_fairing_project_reference_policy",
            "source_path": external_reference.get("source_path"),
            "warnings": origin_warnings,
            "notes": [
                "REF_AREA, REF_LENGTH, velocity, density, and viscosity were extracted from the neighboring fairing project policy.",
                "The moment origin is borrowed from the previous hpa-mdo fairing SU2 handoff unless a dedicated fairing moment policy exists.",
            ],
        },
    )


def build_fairing_solid_reference_override_su2_handoff_probe_report(
    out_dir: Path,
    reference_policy_probe_path: Path | None = None,
    source_su2_probe_report_path: Path | None = None,
) -> FairingSolidReferenceOverrideSU2HandoffProbeReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    reference_policy_path = (
        _default_reference_policy_probe_path()
        if reference_policy_probe_path is None
        else reference_policy_probe_path
    )
    source_su2_probe_path = (
        _default_source_su2_probe_report_path()
        if source_su2_probe_report_path is None
        else source_su2_probe_report_path
    )

    try:
        reference_policy = _load_json(reference_policy_path)
    except Exception as exc:
        return _blocked_report(
            out_dir=out_dir,
            reference_policy_probe_path=reference_policy_path,
            source_su2_probe_report_path=source_su2_probe_path,
            materialization_status="unavailable",
            reference_override_status="missing",
            blocking_reasons=[
                "fairing_reference_policy_probe_unavailable",
                "fairing_reference_override_not_applied",
            ],
            limitations=[
                "The fairing reference policy probe report could not be loaded.",
            ],
            error=str(exc),
        )

    external_reference = _nested_dict(reference_policy, "external_reference")
    hpa_reference = _nested_dict(reference_policy, "hpa_current_reference")
    external_status = reference_policy.get("external_reference_status")
    marker_status = _marker_mapping_status(
        external_reference,
        hpa_reference,
        reference_policy.get("marker_mapping_status")
        if isinstance(reference_policy.get("marker_mapping_status"), str)
        else None,
    )
    if external_status != "candidate_available" or not _external_reference_complete(external_reference):
        return _blocked_report(
            out_dir=out_dir,
            reference_policy_probe_path=reference_policy_path,
            source_su2_probe_report_path=source_su2_probe_path,
            materialization_status="blocked_before_reference_override",
            reference_override_status="insufficient_evidence",
            reference_policy_payload=reference_policy,
            blocking_reasons=[
                "external_fairing_reference_policy_insufficient",
                "fairing_reference_override_not_applied",
            ],
            limitations=[
                "A complete external fairing reference policy is required before materializing a user_declared SU2 override.",
            ],
        )
    if marker_status not in {"mapped_external_fairing_to_fairing_solid", "compatible"}:
        return _blocked_report(
            out_dir=out_dir,
            reference_policy_probe_path=reference_policy_path,
            source_su2_probe_report_path=source_su2_probe_path,
            materialization_status="blocked_before_reference_override",
            reference_override_status="invalid",
            reference_policy_payload=reference_policy,
            blocking_reasons=[
                "fairing_reference_marker_mapping_invalid",
                "fairing_reference_override_not_applied",
            ],
            limitations=[
                "The external fairing wall marker must map to the hpa-mdo fairing_solid marker before runtime use.",
            ],
        )

    try:
        source_su2_probe = _load_json(source_su2_probe_path)
    except Exception as exc:
        return _blocked_report(
            out_dir=out_dir,
            reference_policy_probe_path=reference_policy_path,
            source_su2_probe_report_path=source_su2_probe_path,
            materialization_status="unavailable",
            reference_override_status="applied",
            reference_policy_payload=reference_policy,
            blocking_reasons=[
                "fairing_real_su2_handoff_probe_unavailable",
                "fairing_reference_override_su2_handoff_not_materialized",
            ],
            limitations=[
                "A real fairing SU2 handoff probe is required so the override can reuse the owned fairing mesh handoff.",
            ],
            error=str(exc),
        )
    if source_su2_probe.get("materialization_status") != "su2_handoff_written":
        return _blocked_report(
            out_dir=out_dir,
            reference_policy_probe_path=reference_policy_path,
            source_su2_probe_report_path=source_su2_probe_path,
            materialization_status="blocked_before_su2_handoff",
            reference_override_status="applied",
            reference_policy_payload=reference_policy,
            source_su2_probe_payload=source_su2_probe,
            blocking_reasons=[
                "fairing_real_su2_handoff_not_available",
                "fairing_reference_override_su2_handoff_not_materialized",
            ],
            limitations=[
                "The upstream real fairing SU2 handoff probe did not materialize a reusable SU2 handoff.",
            ],
        )

    mesh_case_report = _source_mesh_case_report_path(source_su2_probe, source_su2_probe_path)
    if mesh_case_report is None or not mesh_case_report.exists():
        return _blocked_report(
            out_dir=out_dir,
            reference_policy_probe_path=reference_policy_path,
            source_su2_probe_report_path=source_su2_probe_path,
            materialization_status="blocked_before_su2_handoff",
            reference_override_status="applied",
            reference_policy_payload=reference_policy,
            source_su2_probe_payload=source_su2_probe,
            blocking_reasons=[
                "fairing_real_mesh_case_report_missing",
                "fairing_reference_override_su2_handoff_not_materialized",
            ],
            limitations=[
                "The source mesh_handoff.v1 case report is required to materialize a corrected SU2 handoff.",
            ],
        )

    source_su2_handoff = _source_su2_handoff_path(source_su2_probe, source_su2_probe_path)
    origin, moment_policy_status, origin_warnings = _reference_origin_from_source(source_su2_handoff)
    reference_override_status: ReferenceOverrideStatusType = (
        "applied_with_moment_origin_warning"
        if moment_policy_status == "borrowed_zero_origin_for_drag_only"
        else "applied"
    )

    try:
        mesh_handoff = _load_mesh_handoff_from_case_report(mesh_case_report)
        case = materialize_baseline_case(
            mesh_handoff,
            _runtime_config(external_reference, origin, origin_warnings),
            out_dir / "artifacts" / "su2",
            source_root=_source_root_for_mesh_handoff(mesh_handoff, source_su2_probe_path),
        )
    except Exception as exc:
        return _blocked_report(
            out_dir=out_dir,
            reference_policy_probe_path=reference_policy_path,
            source_su2_probe_report_path=source_su2_probe_path,
            materialization_status="failed",
            reference_override_status=reference_override_status,
            reference_policy_payload=reference_policy,
            source_su2_probe_payload=source_su2_probe,
            blocking_reasons=[
                "fairing_reference_override_su2_handoff_materialization_failed",
            ],
            limitations=[
                "SU2 handoff materialization failed before any solver run could be considered.",
            ],
            error=str(exc),
        )

    force_surface = case.force_surface_provenance
    wall_marker = None if force_surface is None else force_surface.wall_marker
    component_force_status = _component_force_ownership(wall_marker)
    convergence_gate_present = case.convergence_gate is not None
    blocking_reasons = [
        "fairing_solver_not_run",
        "convergence_gate_not_run",
    ]
    if reference_override_status == "applied_with_moment_origin_warning":
        blocking_reasons.append("fairing_moment_origin_policy_incomplete_for_moment_coefficients")
    if component_force_status != "owned":
        blocking_reasons.insert(0, "fairing_solid_component_force_marker_missing")

    guarantees = [
        "external_fairing_reference_override_applied",
        "su2_handoff_v1_written_with_user_declared_reference",
        "runtime_cfg_written",
        "su2_mesh_written",
        "solver_not_executed",
        "convergence_gate_not_emitted",
        "production_default_unchanged",
    ]
    if component_force_status == "owned":
        guarantees.append("fairing_solid_force_marker_owned")
    if marker_status == "mapped_external_fairing_to_fairing_solid":
        guarantees.append("external_fairing_marker_mapped_to_fairing_solid")

    applied_reference = _entry_from_payload(external_reference)
    applied_reference.ref_origin_moment = origin
    applied_reference.source_label = "external_fairing_project_reference_policy"

    return FairingSolidReferenceOverrideSU2HandoffProbeReport(
        case_dir=str(case.case_output_paths.case_dir),
        materialization_status="su2_handoff_written",
        reference_override_status=reference_override_status,
        marker_mapping_status=marker_status,
        source_reference_policy_status=reference_policy.get("reference_policy_status")
        if isinstance(reference_policy.get("reference_policy_status"), str)
        else None,
        source_external_reference_status=reference_policy.get("external_reference_status")
        if isinstance(reference_policy.get("external_reference_status"), str)
        else None,
        source_hpa_reference_status=reference_policy.get("hpa_current_reference_status")
        if isinstance(reference_policy.get("hpa_current_reference_status"), str)
        else None,
        previous_reference=_entry_from_payload(hpa_reference),
        applied_reference=applied_reference,
        reference_mismatch_fields=[
            str(field)
            for field in reference_policy.get("reference_mismatch_fields", [])
            if isinstance(field, str)
        ],
        moment_origin_policy_status=moment_policy_status,
        source_reference_policy_probe_path=str(reference_policy_path),
        source_su2_probe_report_path=str(source_su2_probe_path),
        source_mesh_case_report_path=str(mesh_case_report),
        source_su2_handoff_path=None if source_su2_handoff is None else str(source_su2_handoff),
        su2_contract=case.contract,
        input_mesh_contract=case.provenance.get("source_contract"),
        solver_execution_status="not_run",
        convergence_gate_status="unexpected_present" if convergence_gate_present else "not_run",
        run_status=case.run_status,
        reference_geometry_status=case.reference_geometry.gate_status,
        wall_marker_status=_wall_marker_status(wall_marker),
        force_surface_scope=None if force_surface is None else force_surface.scope,
        component_force_ownership_status=component_force_status,
        su2_handoff_path=str(case.case_output_paths.contract_path),
        su2_mesh_path=str(case.case_output_paths.su2_mesh),
        runtime_cfg_path=str(case.runtime_cfg_path),
        history_path=str(case.case_output_paths.history),
        hpa_mdo_guarantees=guarantees,
        blocking_reasons=blocking_reasons,
        limitations=[
            "This probe materializes an SU2 handoff with an explicit external fairing reference override; it does not run SU2_CFD.",
            "The external fairing marker is mapped to the hpa-mdo fairing_solid marker, not used as a new mesh marker.",
            "Moment-origin policy remains incomplete when the source origin is zero; drag coefficients may be reference-policy corrected, but moment coefficients are not promoted.",
            "Production defaults were not changed.",
            *origin_warnings,
        ],
    )


def _render_markdown(report: FairingSolidReferenceOverrideSU2HandoffProbeReport) -> str:
    lines = [
        "# fairing_solid reference override su2_handoff probe v1",
        "",
        "This probe materializes an SU2 handoff with the neighboring fairing project reference policy, without executing SU2_CFD.",
        "",
        f"- materialization_status: `{report.materialization_status}`",
        f"- reference_override_status: `{report.reference_override_status}`",
        f"- marker_mapping_status: `{report.marker_mapping_status}`",
        f"- reference_geometry_status: `{report.reference_geometry_status}`",
        f"- component_force_ownership_status: `{report.component_force_ownership_status}`",
        f"- applied_ref_area: `{report.applied_reference.ref_area}`",
        f"- applied_ref_length: `{report.applied_reference.ref_length}`",
        f"- applied_velocity_mps: `{report.applied_reference.velocity_mps}`",
        f"- moment_origin_policy_status: `{report.moment_origin_policy_status}`",
        f"- solver_execution_status: `{report.solver_execution_status}`",
        f"- convergence_gate_status: `{report.convergence_gate_status}`",
        f"- error: `{report.error}`",
        "",
        "## Blocking Reasons",
        "",
    ]
    lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    lines.extend(["", "## HPA-MDO Guarantees", ""])
    lines.extend(f"- `{guarantee}`" for guarantee in report.hpa_mdo_guarantees)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_fairing_solid_reference_override_su2_handoff_probe_report(
    out_dir: Path,
    report: FairingSolidReferenceOverrideSU2HandoffProbeReport | None = None,
    reference_policy_probe_path: Path | None = None,
    source_su2_probe_report_path: Path | None = None,
) -> Dict[str, Path]:
    if report is None:
        report = build_fairing_solid_reference_override_su2_handoff_probe_report(
            out_dir,
            reference_policy_probe_path=reference_policy_probe_path,
            source_su2_probe_report_path=source_su2_probe_report_path,
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "fairing_solid_reference_override_su2_handoff_probe.v1.json"
    markdown_path = out_dir / "fairing_solid_reference_override_su2_handoff_probe.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
