from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from .adapters.su2_backend import materialize_baseline_case
from .schema import SU2RuntimeConfig
from .tail_wing_mesh_handoff_smoke import build_tail_wing_mesh_handoff_smoke_report


MaterializationStatusType = Literal["su2_handoff_written", "failed", "unavailable"]
SolverExecutionStatusType = Literal["not_run", "unexpected_run", "unknown"]
ConvergenceGateStatusType = Literal["not_run", "unexpected_present", "unknown"]
WallMarkerStatusType = Literal[
    "tail_wing_marker_present",
    "generic_aircraft_wall_present",
    "missing",
    "unavailable",
]
ComponentForceOwnershipStatusType = Literal[
    "owned",
    "missing",
    "insufficient_evidence",
]


class TailWingSU2HandoffSmokeReport(BaseModel):
    schema_version: Literal["tail_wing_su2_handoff_smoke.v1"] = (
        "tail_wing_su2_handoff_smoke.v1"
    )
    component: Literal["tail_wing"] = "tail_wing"
    geometry_family: Literal["thin_sheet_lifting_surface"] = "thin_sheet_lifting_surface"
    meshing_route: Literal["gmsh_thin_sheet_surface"] = "gmsh_thin_sheet_surface"
    execution_mode: Literal["su2_materialization_only_no_solver"] = (
        "su2_materialization_only_no_solver"
    )
    source_mesh_smoke_schema: Literal["tail_wing_mesh_handoff_smoke.v1"] = (
        "tail_wing_mesh_handoff_smoke.v1"
    )
    case_dir: str
    no_su2_execution: bool = True
    no_convergence_gate: bool = True
    production_default_changed: bool = False
    materialization_status: MaterializationStatusType
    su2_contract: str | None = None
    input_mesh_contract: str | None = None
    solver_execution_status: SolverExecutionStatusType = "not_run"
    convergence_gate_status: ConvergenceGateStatusType = "not_run"
    run_status: str | None = None
    wall_marker_status: WallMarkerStatusType
    force_surface_scope: str | None = None
    component_force_ownership_status: ComponentForceOwnershipStatusType
    reference_geometry_status: str | None = None
    source_mesh_smoke_path: str | None = None
    source_mesh_case_report_path: str | None = None
    input_mesh_artifact: str | None = None
    su2_handoff_path: str | None = None
    su2_mesh_path: str | None = None
    runtime_cfg_path: str | None = None
    history_path: str | None = None
    hpa_mdo_guarantees: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    error: str | None = None


def _load_mesh_handoff_from_case_report(case_report_path: Path) -> dict[str, Any]:
    payload = json.loads(case_report_path.read_text(encoding="utf-8"))
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


def _runtime_config() -> SU2RuntimeConfig:
    return SU2RuntimeConfig(
        enabled=True,
        case_name="alpha_0_materialization_smoke",
        max_iterations=12,
        reference_mode="user_declared",
        reference_override={
            "ref_area": 0.495,
            "ref_length": 0.55,
            "ref_origin_moment": {"x": 0.275, "y": 0.0, "z": 0.0},
            "source_label": "synthetic_tail_wing_slab_reference",
        },
    )


def _component_force_ownership(wall_marker: str | None) -> ComponentForceOwnershipStatusType:
    return "owned" if wall_marker == "tail_wing" else "missing"


def _wall_marker_status(wall_marker: str | None) -> WallMarkerStatusType:
    if wall_marker == "tail_wing":
        return "tail_wing_marker_present"
    if wall_marker == "aircraft":
        return "generic_aircraft_wall_present"
    if wall_marker:
        return "missing"
    return "unavailable"


def build_tail_wing_su2_handoff_smoke_report(
    out_dir: Path,
) -> TailWingSU2HandoffSmokeReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    mesh_smoke_dir = out_dir / "artifacts" / "mesh_handoff"
    try:
        mesh_smoke = build_tail_wing_mesh_handoff_smoke_report(mesh_smoke_dir)
        mesh_case_report = Path(mesh_smoke.case_dir) / "report.json"
        if mesh_smoke.smoke_status != "mesh_handoff_pass":
            return TailWingSU2HandoffSmokeReport(
                case_dir=str(out_dir),
                materialization_status="unavailable",
                wall_marker_status="unavailable",
                component_force_ownership_status="insufficient_evidence",
                source_mesh_smoke_path=str(
                    mesh_smoke_dir / "tail_wing_mesh_handoff_smoke.v1.json"
                ),
                source_mesh_case_report_path=str(mesh_case_report),
                blocking_reasons=[
                    "tail_wing_mesh_handoff_not_available",
                    "su2_handoff_not_materialized",
                ],
                limitations=[
                    "The upstream tail-wing mesh handoff smoke did not pass.",
                ],
                error=mesh_smoke.error,
            )

        mesh_handoff = _load_mesh_handoff_from_case_report(mesh_case_report)
        case = materialize_baseline_case(
            mesh_handoff,
            _runtime_config(),
            out_dir / "artifacts" / "su2",
            source_root=Path.cwd(),
        )
    except Exception as exc:
        return TailWingSU2HandoffSmokeReport(
            case_dir=str(out_dir),
            materialization_status="failed",
            wall_marker_status="unavailable",
            component_force_ownership_status="insufficient_evidence",
            blocking_reasons=[
                "tail_wing_su2_handoff_materialization_failed",
            ],
            limitations=[
                "SU2 handoff materialization failed before a solver run could be considered.",
            ],
            error=str(exc),
        )

    force_surface = case.force_surface_provenance
    wall_marker = None if force_surface is None else force_surface.wall_marker
    component_force_status = _component_force_ownership(wall_marker)
    convergence_gate_present = case.convergence_gate is not None

    blocking_reasons = [
        "su2_solver_not_run",
        "convergence_gate_not_run",
        "synthetic_fixture_not_real_aerodynamic_tail_geometry",
        "real_tail_wing_geometry_not_used",
    ]
    if component_force_status != "owned":
        blocking_reasons.insert(0, "tail_wing_component_force_marker_missing")

    return TailWingSU2HandoffSmokeReport(
        case_dir=str(case.case_output_paths.case_dir),
        materialization_status="su2_handoff_written",
        su2_contract=case.contract,
        input_mesh_contract=case.provenance.get("source_contract"),
        solver_execution_status="not_run",
        convergence_gate_status="unexpected_present" if convergence_gate_present else "not_run",
        run_status=case.run_status,
        wall_marker_status=_wall_marker_status(wall_marker),
        force_surface_scope=None if force_surface is None else force_surface.scope,
        component_force_ownership_status=component_force_status,
        reference_geometry_status=case.reference_geometry.gate_status,
        source_mesh_smoke_path=str(mesh_smoke_dir / "tail_wing_mesh_handoff_smoke.v1.json"),
        source_mesh_case_report_path=str(mesh_case_report),
        input_mesh_artifact=str(case.input_mesh_artifact),
        su2_handoff_path=str(case.case_output_paths.contract_path),
        su2_mesh_path=str(case.case_output_paths.su2_mesh),
        runtime_cfg_path=str(case.runtime_cfg_path),
        history_path=str(case.case_output_paths.history),
        hpa_mdo_guarantees=[
            "mesh_handoff_v1_consumed",
            "su2_handoff_v1_written",
            "runtime_cfg_written",
            "su2_mesh_written",
            "tail_wing_force_marker_owned",
            "solver_not_executed",
            "production_default_unchanged",
        ],
        blocking_reasons=blocking_reasons,
        limitations=[
            "This smoke materializes an SU2 case only; it does not run SU2_CFD.",
            "convergence_gate.v1 is not emitted because no solver history exists.",
            "The input mesh is a synthetic thin closed-solid tail slab, not real aerodynamic tail geometry.",
            "The handoff uses a component-owned tail_wing wall marker, but the geometry is still synthetic.",
            "Production defaults were not changed.",
        ],
    )


def _render_markdown(report: TailWingSU2HandoffSmokeReport) -> str:
    lines = [
        "# tail_wing su2_handoff smoke v1",
        "",
        "This is an SU2 handoff materialization smoke for the tail-wing route.",
        "It writes the SU2 case artifacts without executing SU2_CFD.",
        "",
        f"- component: `{report.component}`",
        f"- materialization_status: `{report.materialization_status}`",
        f"- su2_contract: `{report.su2_contract}`",
        f"- input_mesh_contract: `{report.input_mesh_contract}`",
        f"- solver_execution_status: `{report.solver_execution_status}`",
        f"- convergence_gate_status: `{report.convergence_gate_status}`",
        f"- wall_marker_status: `{report.wall_marker_status}`",
        f"- force_surface_scope: `{report.force_surface_scope}`",
        f"- component_force_ownership_status: `{report.component_force_ownership_status}`",
        "",
        "## Blocking Reasons",
        "",
    ]
    lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_tail_wing_su2_handoff_smoke_report(
    out_dir: Path,
    report: TailWingSU2HandoffSmokeReport | None = None,
) -> Dict[str, Path]:
    if report is None:
        report = build_tail_wing_su2_handoff_smoke_report(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "tail_wing_su2_handoff_smoke.v1.json"
    markdown_path = out_dir / "tail_wing_su2_handoff_smoke.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
