from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


ReferencePolicyStatusType = Literal[
    "candidate_available",
    "reference_mismatch_observed",
    "missing",
    "invalid",
    "insufficient_evidence",
]
ReferenceEvidenceStatusType = Literal[
    "candidate_available",
    "missing",
    "invalid",
    "insufficient_evidence",
]
MarkerMappingStatusType = Literal[
    "compatible_mapping_required",
    "compatible",
    "missing",
    "unknown",
]


class FairingReferencePolicyEntry(BaseModel):
    ref_area: float | None = None
    ref_length: float | None = None
    velocity_mps: float | None = None
    density_kgpm3: float | None = None
    dynamic_viscosity_pas: float | None = None
    temperature_k: float | None = None
    wall_marker: str | None = None
    farfield_marker: str | None = None
    source_path: str | None = None
    source_kind: str | None = None
    warnings: List[str] = Field(default_factory=list)


class FairingSolidReferencePolicyProbeReport(BaseModel):
    schema_version: Literal["fairing_solid_reference_policy_probe.v1"] = (
        "fairing_solid_reference_policy_probe.v1"
    )
    component: Literal["fairing_solid"] = "fairing_solid"
    execution_mode: Literal["external_fairing_reference_policy_report_only"] = (
        "external_fairing_reference_policy_report_only"
    )
    source_project_root: str
    case_dir: str
    no_su2_execution: bool = True
    no_gmsh_execution: bool = True
    no_bl_runtime: bool = True
    production_default_changed: bool = False
    reference_policy_status: ReferencePolicyStatusType
    external_reference_status: ReferenceEvidenceStatusType
    hpa_current_reference_status: str | None = None
    marker_mapping_status: MarkerMappingStatusType = "unknown"
    external_fluid_config_path: str | None = None
    external_su2_cfg_path: str | None = None
    hpa_su2_probe_report_path: str | None = None
    hpa_runtime_cfg_path: str | None = None
    external_reference: FairingReferencePolicyEntry = Field(
        default_factory=FairingReferencePolicyEntry
    )
    hpa_current_reference: FairingReferencePolicyEntry = Field(
        default_factory=FairingReferencePolicyEntry
    )
    reference_mismatch_fields: List[str] = Field(default_factory=list)
    recommended_runtime_policy: str | None = None
    hpa_mdo_guarantees: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    error: str | None = None


def _default_external_project_root() -> Path:
    return Path("/Volumes/Samsung SSD/HPA-Fairing-Optimization-Project")


def _default_external_su2_cfg_path(root: Path) -> Path:
    preferred = root / "output" / "su2_converged_v7_best_cflsafe_v1" / "best_gene" / "su2_case.cfg"
    if preferred.exists():
        return preferred
    fallback = root / "output" / "su2_converged_v7_best_cflsafe_v1" / "best_gene" / "su2_runtime.cfg"
    if fallback.exists():
        return fallback
    candidates = sorted(root.glob("output/**/best_gene/su2_case.cfg"))
    return candidates[-1] if candidates else preferred


def _default_hpa_su2_probe_report_path() -> Path:
    return Path(
        "hpa_meshing_package/docs/reports/fairing_solid_real_su2_handoff_probe/"
        "fairing_solid_real_su2_handoff_probe.v1.json"
    )


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _cfg_value(cfg_text: str, key: str) -> str | None:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*?)\s*$", re.MULTILINE)
    match = pattern.search(cfg_text)
    return None if match is None else match.group(1).strip()


def _cfg_float(cfg_text: str, key: str) -> float | None:
    return _parse_float(_cfg_value(cfg_text, key))


def _cfg_vector_first_float(cfg_text: str, key: str) -> float | None:
    value = _cfg_value(cfg_text, key)
    if value is None:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?", value)
    return None if match is None else _parse_float(match.group(0))


def _cfg_marker(cfg_text: str, key: str) -> str | None:
    value = _cfg_value(cfg_text, key)
    if value is None:
        return None
    match = re.search(r"\(\s*([^,\s)]+)", value)
    return None if match is None else match.group(1).strip()


def _external_reference_from_sources(
    *,
    fluid_config_path: Path,
    su2_cfg_path: Path,
) -> FairingReferencePolicyEntry:
    fluid = _safe_load_json(fluid_config_path) or {}
    cfg_text = su2_cfg_path.read_text(encoding="utf-8") if su2_cfg_path.exists() else ""
    flow = fluid.get("flow_conditions", {}) if isinstance(fluid.get("flow_conditions"), dict) else {}
    reference = (
        fluid.get("reference_values", {})
        if isinstance(fluid.get("reference_values"), dict)
        else {}
    )
    sref = reference.get("Sref", {}) if isinstance(reference.get("Sref"), dict) else {}
    velocity = flow.get("velocity", {}) if isinstance(flow.get("velocity"), dict) else {}
    density = flow.get("density", {}) if isinstance(flow.get("density"), dict) else {}
    viscosity = flow.get("viscosity", {}) if isinstance(flow.get("viscosity"), dict) else {}
    temperature = flow.get("temperature", {}) if isinstance(flow.get("temperature"), dict) else {}

    return FairingReferencePolicyEntry(
        ref_area=_cfg_float(cfg_text, "REF_AREA") or _parse_float(sref.get("value")),
        ref_length=_cfg_float(cfg_text, "REF_LENGTH"),
        velocity_mps=(
            _cfg_float(cfg_text, "REF_VELOCITY")
            or _cfg_vector_first_float(cfg_text, "INC_VELOCITY_INIT")
            or _parse_float(velocity.get("value"))
        ),
        density_kgpm3=_cfg_float(cfg_text, "INC_DENSITY_INIT")
        or _parse_float(density.get("value")),
        dynamic_viscosity_pas=_cfg_float(cfg_text, "MU_CONSTANT")
        or _cfg_float(cfg_text, "REF_VISCOSITY")
        or _parse_float(viscosity.get("value")),
        temperature_k=(
            _cfg_float(cfg_text, "INC_TEMPERATURE_INIT")
            or (
                _parse_float(temperature.get("value")) + 273.15
                if _parse_float(temperature.get("value")) is not None
                else None
            )
        ),
        wall_marker=_cfg_marker(cfg_text, "MARKER_MONITORING"),
        farfield_marker=_cfg_marker(cfg_text, "MARKER_FAR"),
        source_path=str(su2_cfg_path) if su2_cfg_path.exists() else str(fluid_config_path),
        source_kind="external_fairing_project_su2_policy",
    )


def _hpa_reference_from_probe(probe_report_path: Path | None) -> tuple[str | None, Path | None, FairingReferencePolicyEntry]:
    if probe_report_path is None or not probe_report_path.exists():
        return None, None, FairingReferencePolicyEntry()
    payload = _safe_load_json(probe_report_path) or {}
    runtime_cfg_value = payload.get("runtime_cfg_path")
    runtime_cfg_path = (
        _resolve_report_relative_path(Path(runtime_cfg_value), probe_report_path)
        if isinstance(runtime_cfg_value, str)
        else None
    )
    cfg_text = ""
    if runtime_cfg_path is not None and runtime_cfg_path.exists():
        cfg_text = runtime_cfg_path.read_text(encoding="utf-8")
    return (
        payload.get("reference_geometry_status")
        if isinstance(payload.get("reference_geometry_status"), str)
        else None,
        runtime_cfg_path,
        FairingReferencePolicyEntry(
            ref_area=_cfg_float(cfg_text, "REF_AREA"),
            ref_length=_cfg_float(cfg_text, "REF_LENGTH"),
            velocity_mps=_cfg_vector_first_float(cfg_text, "INC_VELOCITY_INIT"),
            density_kgpm3=_cfg_float(cfg_text, "INC_DENSITY_INIT"),
            dynamic_viscosity_pas=_cfg_float(cfg_text, "MU_CONSTANT"),
            wall_marker=_cfg_marker(cfg_text, "MARKER_MONITORING"),
            farfield_marker=_cfg_marker(cfg_text, "MARKER_FAR"),
            source_path=str(runtime_cfg_path) if runtime_cfg_path is not None else None,
            source_kind="hpa_mdo_real_su2_handoff_probe_runtime_cfg",
        ),
    )


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


def _entry_complete(entry: FairingReferencePolicyEntry) -> bool:
    return (
        entry.ref_area is not None
        and entry.ref_area > 0.0
        and entry.ref_length is not None
        and entry.ref_length > 0.0
        and entry.velocity_mps is not None
        and entry.velocity_mps > 0.0
        and entry.density_kgpm3 is not None
        and entry.density_kgpm3 > 0.0
        and entry.dynamic_viscosity_pas is not None
        and entry.dynamic_viscosity_pas > 0.0
    )


def _different(a: float | None, b: float | None, *, relative_tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    scale = max(abs(a), abs(b), 1.0)
    return abs(a - b) > relative_tol * scale


def _mismatch_fields(
    external: FairingReferencePolicyEntry,
    hpa: FairingReferencePolicyEntry,
) -> list[str]:
    fields = []
    for name in [
        "ref_area",
        "ref_length",
        "velocity_mps",
        "density_kgpm3",
        "dynamic_viscosity_pas",
    ]:
        if _different(getattr(external, name), getattr(hpa, name)):
            fields.append(name)
    return fields


def _marker_mapping_status(
    external: FairingReferencePolicyEntry,
    hpa: FairingReferencePolicyEntry,
) -> MarkerMappingStatusType:
    if external.wall_marker is None or hpa.wall_marker is None:
        return "missing"
    if external.wall_marker == hpa.wall_marker:
        return "compatible"
    if external.wall_marker == "fairing" and hpa.wall_marker == "fairing_solid":
        return "compatible_mapping_required"
    return "unknown"


def build_fairing_solid_reference_policy_probe_report(
    out_dir: Path,
    external_project_root: Path | None = None,
    external_su2_cfg_path: Path | None = None,
    hpa_su2_probe_report_path: Path | None = None,
) -> FairingSolidReferencePolicyProbeReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    root = _default_external_project_root() if external_project_root is None else external_project_root
    hpa_probe_path = (
        _default_hpa_su2_probe_report_path()
        if hpa_su2_probe_report_path is None
        else hpa_su2_probe_report_path
    )
    if not root.exists():
        return FairingSolidReferencePolicyProbeReport(
            source_project_root=str(root),
            case_dir=str(out_dir),
            reference_policy_status="missing",
            external_reference_status="missing",
            hpa_su2_probe_report_path=str(hpa_probe_path) if hpa_probe_path is not None else None,
            blocking_reasons=[
                "external_fairing_project_missing",
                "fairing_reference_policy_candidate_missing",
            ],
            limitations=[
                "The external fairing project root was not available, so no fairing reference policy candidate could be extracted.",
            ],
        )

    fluid_config_path = root / "config" / "fluid_conditions.json"
    su2_cfg_path = _default_external_su2_cfg_path(root) if external_su2_cfg_path is None else external_su2_cfg_path
    external_reference = _external_reference_from_sources(
        fluid_config_path=fluid_config_path,
        su2_cfg_path=su2_cfg_path,
    )
    external_status: ReferenceEvidenceStatusType = (
        "candidate_available" if _entry_complete(external_reference) else "insufficient_evidence"
    )
    hpa_status, hpa_runtime_cfg_path, hpa_reference = _hpa_reference_from_probe(hpa_probe_path)
    mismatches = _mismatch_fields(external_reference, hpa_reference)
    marker_status = _marker_mapping_status(external_reference, hpa_reference)

    if external_status != "candidate_available":
        policy_status: ReferencePolicyStatusType = "insufficient_evidence"
    elif mismatches:
        policy_status = "reference_mismatch_observed"
    else:
        policy_status = "candidate_available"

    blocking_reasons: list[str] = []
    if external_status != "candidate_available":
        blocking_reasons.append("external_fairing_reference_policy_insufficient")
    if mismatches:
        blocking_reasons.append("hpa_current_reference_policy_mismatch")
    if hpa_status in {"warn", "fail"}:
        blocking_reasons.append(f"hpa_current_reference_geometry_{hpa_status}")
    blocking_reasons.extend(["solver_not_run", "convergence_gate_not_run"])

    guarantees = [
        "external_fairing_project_inspected",
        "no_su2_execution",
        "no_gmsh_execution",
        "production_default_unchanged",
    ]
    if external_status == "candidate_available":
        guarantees.append("external_fairing_reference_policy_candidate_available")
    if hpa_probe_path is not None and hpa_probe_path.exists():
        guarantees.append("hpa_real_fairing_su2_handoff_probe_compared")

    return FairingSolidReferencePolicyProbeReport(
        source_project_root=str(root),
        case_dir=str(out_dir),
        reference_policy_status=policy_status,
        external_reference_status=external_status,
        hpa_current_reference_status=hpa_status,
        marker_mapping_status=marker_status,
        external_fluid_config_path=str(fluid_config_path) if fluid_config_path.exists() else None,
        external_su2_cfg_path=str(su2_cfg_path) if su2_cfg_path.exists() else None,
        hpa_su2_probe_report_path=str(hpa_probe_path) if hpa_probe_path is not None else None,
        hpa_runtime_cfg_path=str(hpa_runtime_cfg_path) if hpa_runtime_cfg_path is not None else None,
        external_reference=external_reference,
        hpa_current_reference=hpa_reference,
        reference_mismatch_fields=mismatches,
        recommended_runtime_policy=(
            "create_explicit_fairing_reference_override_from_external_policy_before_solver_smoke"
            if external_status == "candidate_available"
            else None
        ),
        hpa_mdo_guarantees=guarantees,
        blocking_reasons=blocking_reasons,
        limitations=[
            "This is report-only evidence; it does not apply the external fairing reference policy to hpa-mdo runtime defaults.",
            "The external fairing marker `fairing` must be explicitly mapped to hpa-mdo marker `fairing_solid` before runtime use.",
            "Solver and convergence evidence remain absent in this hpa-mdo probe.",
        ],
    )


def _render_markdown(report: FairingSolidReferencePolicyProbeReport) -> str:
    lines = [
        "# fairing_solid reference policy probe v1",
        "",
        "This report compares external fairing project reference policy evidence with the current hpa-mdo real fairing SU2 handoff probe.",
        "",
        f"- reference_policy_status: `{report.reference_policy_status}`",
        f"- external_reference_status: `{report.external_reference_status}`",
        f"- hpa_current_reference_status: `{report.hpa_current_reference_status}`",
        f"- marker_mapping_status: `{report.marker_mapping_status}`",
        f"- external_ref_area: `{report.external_reference.ref_area}`",
        f"- external_ref_length: `{report.external_reference.ref_length}`",
        f"- external_velocity_mps: `{report.external_reference.velocity_mps}`",
        f"- hpa_ref_area: `{report.hpa_current_reference.ref_area}`",
        f"- hpa_ref_length: `{report.hpa_current_reference.ref_length}`",
        f"- hpa_velocity_mps: `{report.hpa_current_reference.velocity_mps}`",
        f"- reference_mismatch_fields: `{', '.join(report.reference_mismatch_fields)}`",
        "",
        "## Blocking Reasons",
        "",
    ]
    lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_fairing_solid_reference_policy_probe_report(
    out_dir: Path,
    report: FairingSolidReferencePolicyProbeReport | None = None,
    external_project_root: Path | None = None,
    external_su2_cfg_path: Path | None = None,
    hpa_su2_probe_report_path: Path | None = None,
) -> Dict[str, Path]:
    if report is None:
        report = build_fairing_solid_reference_policy_probe_report(
            out_dir,
            external_project_root=external_project_root,
            external_su2_cfg_path=external_su2_cfg_path,
            hpa_su2_probe_report_path=hpa_su2_probe_report_path,
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "fairing_solid_reference_policy_probe.v1.json"
    markdown_path = out_dir / "fairing_solid_reference_policy_probe.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
