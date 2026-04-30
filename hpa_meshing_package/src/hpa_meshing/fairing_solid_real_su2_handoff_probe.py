from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from .adapters.su2_backend import materialize_baseline_case
from .fairing_solid_real_mesh_handoff_probe import (
    FairingSolidRealMeshHandoffProbeReport,
    build_fairing_solid_real_mesh_handoff_probe_report,
    write_fairing_solid_real_mesh_handoff_probe_report,
)
from .schema import SU2RuntimeConfig


MaterializationStatusType = Literal[
    "su2_handoff_written",
    "blocked_before_su2_handoff",
    "failed",
    "unavailable",
]
SolverExecutionStatusType = Literal["not_run", "unexpected_run", "unknown"]
ConvergenceGateStatusType = Literal["not_run", "unexpected_present", "unknown"]
WallMarkerStatusType = Literal[
    "fairing_solid_marker_present",
    "generic_aircraft_wall_present",
    "missing",
    "unavailable",
]
ComponentForceOwnershipStatusType = Literal[
    "owned",
    "missing",
    "insufficient_evidence",
]


class FairingSolidRealSU2HandoffProbeReport(BaseModel):
    schema_version: Literal["fairing_solid_real_su2_handoff_probe.v1"] = (
        "fairing_solid_real_su2_handoff_probe.v1"
    )
    component: Literal["fairing_solid"] = "fairing_solid"
    source_fixture: Literal["hpa_fairing_best_design_vsp3", "custom_vsp3"] = (
        "hpa_fairing_best_design_vsp3"
    )
    geometry_provider: Literal["openvsp_surface_intersection"] = "openvsp_surface_intersection"
    geometry_family: Literal["closed_solid"] = "closed_solid"
    meshing_route: Literal["gmsh_closed_solid_volume"] = "gmsh_closed_solid_volume"
    execution_mode: Literal["real_mesh_handoff_su2_materialization_only_no_solver"] = (
        "real_mesh_handoff_su2_materialization_only_no_solver"
    )
    source_mesh_probe_schema: Literal["fairing_solid_real_mesh_handoff_probe.v1"] = (
        "fairing_solid_real_mesh_handoff_probe.v1"
    )
    source_path: str | None = None
    case_dir: str
    no_su2_execution: bool = True
    no_convergence_gate: bool = True
    no_bl_runtime: bool = True
    production_default_changed: bool = False
    materialization_status: MaterializationStatusType
    source_mesh_probe_status: str | None = None
    source_mesh_handoff_status: str | None = None
    provider_status: str | None = None
    marker_summary_status: str | None = None
    fairing_force_marker_status: str | None = None
    su2_contract: str | None = None
    input_mesh_contract: str | None = None
    solver_execution_status: SolverExecutionStatusType = "not_run"
    convergence_gate_status: ConvergenceGateStatusType = "not_run"
    run_status: str | None = None
    wall_marker_status: WallMarkerStatusType
    force_surface_scope: str | None = None
    component_force_ownership_status: ComponentForceOwnershipStatusType
    reference_geometry_status: str | None = None
    source_mesh_probe_path: str | None = None
    source_mesh_case_report_path: str | None = None
    input_mesh_artifact: str | None = None
    su2_handoff_path: str | None = None
    su2_mesh_path: str | None = None
    runtime_cfg_path: str | None = None
    history_path: str | None = None
    node_count: int | None = None
    element_count: int | None = None
    volume_element_count: int | None = None
    hpa_mdo_guarantees: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    error: str | None = None


def _runtime_config() -> SU2RuntimeConfig:
    return SU2RuntimeConfig(
        enabled=True,
        case_name="alpha_0_real_fairing_materialization_probe",
        max_iterations=12,
        reference_mode="geometry_derived",
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_mesh_handoff_from_case_report(case_report_path: Path) -> dict[str, Any]:
    payload = _load_json(case_report_path)
    run_payload = payload.get("run", {})
    if isinstance(run_payload, dict):
        backend_result = run_payload.get("backend_result", {})
        if isinstance(backend_result, dict):
            mesh_handoff = backend_result.get("mesh_handoff")
            if isinstance(mesh_handoff, dict):
                return mesh_handoff
    mesh_handoff = payload.get("mesh_handoff")
    if isinstance(mesh_handoff, dict):
        return mesh_handoff
    raise ValueError(f"mesh_handoff not found in case report: {case_report_path}")


def _mesh_case_report_path(
    mesh_probe: FairingSolidRealMeshHandoffProbeReport,
    mesh_probe_path: Path,
) -> Path:
    direct = Path(mesh_probe.case_dir) / "report.json"
    if direct.exists():
        return direct
    sibling_artifact = mesh_probe_path.parent / "artifacts" / "real_mesh_probe" / "report.json"
    if sibling_artifact.exists():
        return sibling_artifact
    return direct


def _source_root_for_mesh_handoff(
    mesh_handoff: dict[str, Any],
    mesh_probe_path: Path,
) -> Path:
    artifacts = mesh_handoff.get("artifacts", {})
    mesh_path = artifacts.get("mesh") if isinstance(artifacts, dict) else None
    if not isinstance(mesh_path, str):
        return Path.cwd()
    mesh_artifact = Path(mesh_path)
    if mesh_artifact.is_absolute():
        return Path.cwd()
    for candidate in [Path.cwd(), mesh_probe_path.parent, *mesh_probe_path.parents]:
        if (candidate / mesh_artifact).exists():
            return candidate
    return Path.cwd()


def _load_mesh_probe_report(path: Path) -> FairingSolidRealMeshHandoffProbeReport:
    return FairingSolidRealMeshHandoffProbeReport.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def _materialized_mesh_probe(
    out_dir: Path,
    *,
    source_path: Path | None,
    timeout_seconds: float,
    source_mesh_probe_report_path: Path | None,
) -> tuple[FairingSolidRealMeshHandoffProbeReport, Path]:
    if source_mesh_probe_report_path is not None:
        path = source_mesh_probe_report_path
        return _load_mesh_probe_report(path), path

    mesh_probe_dir = out_dir / "artifacts" / "real_mesh_handoff"
    report = build_fairing_solid_real_mesh_handoff_probe_report(
        mesh_probe_dir,
        source_path=source_path,
        timeout_seconds=timeout_seconds,
    )
    paths = write_fairing_solid_real_mesh_handoff_probe_report(
        mesh_probe_dir,
        report=report,
    )
    return report, paths["json"]


def _component_force_ownership(wall_marker: str | None) -> ComponentForceOwnershipStatusType:
    return "owned" if wall_marker == "fairing_solid" else "missing"


def _wall_marker_status(wall_marker: str | None) -> WallMarkerStatusType:
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
    mesh_probe: FairingSolidRealMeshHandoffProbeReport | None,
    mesh_probe_path: Path | None,
    materialization_status: MaterializationStatusType,
    blocking_reasons: list[str],
    limitations: list[str],
    error: str | None = None,
) -> FairingSolidRealSU2HandoffProbeReport:
    return FairingSolidRealSU2HandoffProbeReport(
        source_fixture=(
            "hpa_fairing_best_design_vsp3"
            if mesh_probe is None
            else mesh_probe.source_fixture
        ),
        source_path=None if mesh_probe is None else mesh_probe.source_path,
        case_dir=str(out_dir),
        materialization_status=materialization_status,
        source_mesh_probe_status=None if mesh_probe is None else mesh_probe.probe_status,
        source_mesh_handoff_status=None
        if mesh_probe is None
        else mesh_probe.mesh_handoff_status,
        provider_status=None if mesh_probe is None else mesh_probe.provider_status,
        marker_summary_status=None
        if mesh_probe is None
        else mesh_probe.marker_summary_status,
        fairing_force_marker_status=None
        if mesh_probe is None
        else mesh_probe.fairing_force_marker_status,
        wall_marker_status="unavailable",
        component_force_ownership_status="insufficient_evidence",
        source_mesh_probe_path=None if mesh_probe_path is None else str(mesh_probe_path),
        source_mesh_case_report_path=None
        if mesh_probe is None
        else str(_mesh_case_report_path(mesh_probe, mesh_probe_path or Path("."))),
        node_count=None if mesh_probe is None else mesh_probe.node_count,
        element_count=None if mesh_probe is None else mesh_probe.element_count,
        volume_element_count=None if mesh_probe is None else mesh_probe.volume_element_count,
        blocking_reasons=blocking_reasons,
        limitations=limitations,
        error=error,
    )


def build_fairing_solid_real_su2_handoff_probe_report(
    out_dir: Path,
    source_path: Path | None = None,
    timeout_seconds: float = 60.0,
    source_mesh_probe_report_path: Path | None = None,
) -> FairingSolidRealSU2HandoffProbeReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        mesh_probe, mesh_probe_path = _materialized_mesh_probe(
            out_dir,
            source_path=source_path,
            timeout_seconds=timeout_seconds,
            source_mesh_probe_report_path=source_mesh_probe_report_path,
        )
    except Exception as exc:
        return _blocked_report(
            out_dir=out_dir,
            mesh_probe=None,
            mesh_probe_path=source_mesh_probe_report_path,
            materialization_status="unavailable",
            blocking_reasons=[
                "fairing_real_mesh_probe_report_unavailable",
                "fairing_real_su2_handoff_not_materialized",
            ],
            limitations=[
                "The upstream real fairing mesh probe report could not be loaded or generated.",
            ],
            error=str(exc),
        )

    mesh_case_report = _mesh_case_report_path(mesh_probe, mesh_probe_path)
    if (
        mesh_probe.probe_status != "mesh_handoff_pass"
        or mesh_probe.mesh_handoff_status != "written"
    ):
        return _blocked_report(
            out_dir=out_dir,
            mesh_probe=mesh_probe,
            mesh_probe_path=mesh_probe_path,
            materialization_status="blocked_before_su2_handoff",
            blocking_reasons=[
                "fairing_real_mesh_handoff_not_available",
                "fairing_real_su2_handoff_not_materialized",
            ],
            limitations=[
                "The upstream real fairing mesh handoff probe did not provide a written mesh_handoff.v1.",
            ],
            error=mesh_probe.error,
        )

    try:
        mesh_handoff = _load_mesh_handoff_from_case_report(mesh_case_report)
        case = materialize_baseline_case(
            mesh_handoff,
            _runtime_config(),
            out_dir / "artifacts" / "su2",
            source_root=_source_root_for_mesh_handoff(mesh_handoff, mesh_probe_path),
        )
    except Exception as exc:
        return _blocked_report(
            out_dir=out_dir,
            mesh_probe=mesh_probe,
            mesh_probe_path=mesh_probe_path,
            materialization_status="failed",
            blocking_reasons=[
                "fairing_real_su2_handoff_materialization_failed",
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
    reference_status = case.reference_geometry.gate_status

    blocking_reasons = [
        "fairing_solver_not_run",
        "convergence_gate_not_run",
    ]
    if reference_status in {"warn", "fail"}:
        blocking_reasons.append(f"fairing_real_reference_geometry_{reference_status}")
    if component_force_status != "owned":
        blocking_reasons.insert(0, "fairing_solid_component_force_marker_missing")

    hpa_mdo_guarantees = [
        "real_fairing_mesh_handoff_v1_consumed",
        "su2_handoff_v1_written_for_real_fairing",
        "runtime_cfg_written",
        "su2_mesh_written",
        "solver_not_executed",
        "convergence_gate_not_emitted",
        "production_default_unchanged",
    ]
    if component_force_status == "owned":
        hpa_mdo_guarantees.append("fairing_solid_force_marker_owned")

    return FairingSolidRealSU2HandoffProbeReport(
        source_fixture=mesh_probe.source_fixture,
        source_path=mesh_probe.source_path,
        case_dir=str(case.case_output_paths.case_dir),
        materialization_status="su2_handoff_written",
        source_mesh_probe_status=mesh_probe.probe_status,
        source_mesh_handoff_status=mesh_probe.mesh_handoff_status,
        provider_status=mesh_probe.provider_status,
        marker_summary_status=mesh_probe.marker_summary_status,
        fairing_force_marker_status=mesh_probe.fairing_force_marker_status,
        su2_contract=case.contract,
        input_mesh_contract=case.provenance.get("source_contract"),
        solver_execution_status="not_run",
        convergence_gate_status="unexpected_present" if convergence_gate_present else "not_run",
        run_status=case.run_status,
        wall_marker_status=_wall_marker_status(wall_marker),
        force_surface_scope=None if force_surface is None else force_surface.scope,
        component_force_ownership_status=component_force_status,
        reference_geometry_status=reference_status,
        source_mesh_probe_path=str(mesh_probe_path),
        source_mesh_case_report_path=str(mesh_case_report),
        input_mesh_artifact=str(case.input_mesh_artifact),
        su2_handoff_path=str(case.case_output_paths.contract_path),
        su2_mesh_path=str(case.case_output_paths.su2_mesh),
        runtime_cfg_path=str(case.runtime_cfg_path),
        history_path=str(case.case_output_paths.history),
        node_count=mesh_probe.node_count,
        element_count=mesh_probe.element_count,
        volume_element_count=mesh_probe.volume_element_count,
        hpa_mdo_guarantees=hpa_mdo_guarantees,
        blocking_reasons=blocking_reasons,
        limitations=[
            "This probe materializes an SU2 case from the real fairing mesh handoff only; it does not run SU2_CFD.",
            "convergence_gate.v1 is not emitted because no solver history exists.",
            "Reference geometry is taken from real fairing provider metadata when available; warn/fail remains a blocker for credibility.",
            "The upstream mesh is a coarse bounded probe, not production default sizing.",
            "Production defaults were not changed.",
        ],
    )


def _render_markdown(report: FairingSolidRealSU2HandoffProbeReport) -> str:
    lines = [
        "# fairing_solid real su2_handoff probe v1",
        "",
        "This probe materializes an SU2 case from the real fairing mesh handoff without executing SU2_CFD.",
        "",
        f"- materialization_status: `{report.materialization_status}`",
        f"- source_mesh_probe_status: `{report.source_mesh_probe_status}`",
        f"- source_mesh_handoff_status: `{report.source_mesh_handoff_status}`",
        f"- su2_contract: `{report.su2_contract}`",
        f"- input_mesh_contract: `{report.input_mesh_contract}`",
        f"- solver_execution_status: `{report.solver_execution_status}`",
        f"- convergence_gate_status: `{report.convergence_gate_status}`",
        f"- wall_marker_status: `{report.wall_marker_status}`",
        f"- force_surface_scope: `{report.force_surface_scope}`",
        f"- component_force_ownership_status: `{report.component_force_ownership_status}`",
        f"- reference_geometry_status: `{report.reference_geometry_status}`",
        f"- volume_element_count: `{report.volume_element_count}`",
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


def write_fairing_solid_real_su2_handoff_probe_report(
    out_dir: Path,
    report: FairingSolidRealSU2HandoffProbeReport | None = None,
    source_path: Path | None = None,
    timeout_seconds: float = 60.0,
    source_mesh_probe_report_path: Path | None = None,
) -> Dict[str, Path]:
    if report is None:
        report = build_fairing_solid_real_su2_handoff_probe_report(
            out_dir,
            source_path=source_path,
            timeout_seconds=timeout_seconds,
            source_mesh_probe_report_path=source_mesh_probe_report_path,
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "fairing_solid_real_su2_handoff_probe.v1.json"
    markdown_path = out_dir / "fairing_solid_real_su2_handoff_probe.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
