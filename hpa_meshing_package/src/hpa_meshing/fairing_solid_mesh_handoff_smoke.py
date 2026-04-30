from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Literal

from pydantic import BaseModel, Field

from .pipeline import run_job
from .schema import MeshJobConfig


SmokeStatusType = Literal["mesh_handoff_pass", "mesh_handoff_fail", "unavailable"]
MeshHandoffStatusType = Literal["written", "missing", "unavailable"]
MarkerSummaryStatusType = Literal[
    "component_wall_and_farfield_present",
    "generic_wall_and_farfield_present",
    "missing_required_markers",
    "unavailable",
]
FairingForceMarkerStatusType = Literal[
    "missing_component_specific_marker",
    "component_specific_marker_present",
    "unavailable",
]
SU2PromotionStatusType = Literal[
    "blocked_before_su2_handoff",
    "not_evaluated",
]


class FairingSolidMeshHandoffSmokeReport(BaseModel):
    schema_version: Literal["fairing_solid_mesh_handoff_smoke.v1"] = (
        "fairing_solid_mesh_handoff_smoke.v1"
    )
    component: Literal["fairing_solid"] = "fairing_solid"
    geometry_family: Literal["closed_solid"] = "closed_solid"
    meshing_route: Literal["gmsh_closed_solid_volume"] = "gmsh_closed_solid_volume"
    execution_mode: Literal["real_gmsh_mesh_handoff_smoke"] = "real_gmsh_mesh_handoff_smoke"
    fixture_kind: Literal["synthetic_occ_box_closed_solid"] = "synthetic_occ_box_closed_solid"
    source_path: str | None = None
    case_dir: str
    no_su2_execution: bool = True
    no_bl_runtime: bool = True
    production_default_changed: bool = False
    smoke_status: SmokeStatusType
    mesh_handoff_status: MeshHandoffStatusType
    mesh_contract: str | None = None
    route_stage: str | None = None
    mesh_artifact: str | None = None
    mesh_metadata_path: str | None = None
    marker_summary_path: str | None = None
    marker_summary_status: MarkerSummaryStatusType
    fairing_force_marker_status: FairingForceMarkerStatusType
    su2_promotion_status: SU2PromotionStatusType = "blocked_before_su2_handoff"
    node_count: int | None = None
    element_count: int | None = None
    volume_element_count: int | None = None
    body_bounds: Dict[str, float] | None = None
    farfield_bounds: Dict[str, float] | None = None
    hpa_mdo_guarantees: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    run_status: str | None = None
    failure_code: str | None = None
    error: str | None = None


def _write_occ_box_step_fixture(out_dir: Path) -> Path:
    gmsh_bin = shutil.which("gmsh")
    if gmsh_bin is None:
        raise RuntimeError("gmsh CLI not available")

    fixture_dir = out_dir / "artifacts" / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    geo_path = fixture_dir / "fairing_solid_box.geo"
    step_path = fixture_dir / "fairing_solid_box.step"
    geo_path.write_text(
        'SetFactory("OpenCASCADE");\n'
        "Box(1) = {0, 0, 0, 1.0, 0.24, 0.18};\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [gmsh_bin, str(geo_path), "-0", "-o", str(step_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not step_path.exists():
        raise RuntimeError((completed.stderr or completed.stdout or "gmsh STEP export failed").strip())
    return step_path


def _marker_summary_status(marker_summary: Dict[str, object]) -> MarkerSummaryStatusType:
    aircraft = marker_summary.get("aircraft")
    fairing = marker_summary.get("fairing_solid")
    farfield = marker_summary.get("farfield")
    if (
        isinstance(fairing, dict)
        and fairing.get("exists") is True
        and isinstance(farfield, dict)
        and farfield.get("exists") is True
    ):
        return "component_wall_and_farfield_present"
    if (
        isinstance(aircraft, dict)
        and aircraft.get("exists") is True
        and isinstance(farfield, dict)
        and farfield.get("exists") is True
    ):
        return "generic_wall_and_farfield_present"
    return "missing_required_markers"


def build_fairing_solid_mesh_handoff_smoke_report(
    out_dir: Path,
) -> FairingSolidMeshHandoffSmokeReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        fixture_path = _write_occ_box_step_fixture(out_dir)
    except Exception as exc:
        return FairingSolidMeshHandoffSmokeReport(
            case_dir=str(out_dir),
            smoke_status="unavailable",
            mesh_handoff_status="unavailable",
            marker_summary_status="unavailable",
            fairing_force_marker_status="unavailable",
            su2_promotion_status="not_evaluated",
            blocking_reasons=["gmsh_fixture_export_unavailable"],
            limitations=[
                "Gmsh fixture export did not complete, so the real route smoke was not evaluated.",
            ],
            error=str(exc),
        )

    case_dir = out_dir / "artifacts" / "cases" / "fairing_solid"
    result = run_job(
        MeshJobConfig(
            component="fairing_solid",
            geometry=fixture_path,
            out_dir=case_dir,
            geometry_source="direct_cad",
            global_min_size=0.5,
            global_max_size=2.0,
        )
    )
    mesh = result.get("mesh", {}) if isinstance(result.get("mesh"), dict) else {}
    marker_summary = (
        mesh.get("marker_summary", {}) if isinstance(mesh.get("marker_summary"), dict) else {}
    )
    mesh_contract = mesh.get("contract")
    volume_element_count = mesh.get("volume_element_count")
    marker_status = _marker_summary_status(marker_summary)
    pass_status = (
        result.get("status") == "success"
        and mesh_contract == "mesh_handoff.v1"
        and marker_status == "component_wall_and_farfield_present"
        and isinstance(volume_element_count, int)
        and volume_element_count > 0
    )
    fairing_force_marker_status: FairingForceMarkerStatusType = (
        "component_specific_marker_present"
        if marker_status == "component_wall_and_farfield_present"
        else "missing_component_specific_marker"
    )

    return FairingSolidMeshHandoffSmokeReport(
        source_path=str(fixture_path),
        case_dir=str(case_dir),
        smoke_status="mesh_handoff_pass" if pass_status else "mesh_handoff_fail",
        mesh_handoff_status="written" if mesh_contract == "mesh_handoff.v1" else "missing",
        mesh_contract=mesh_contract if isinstance(mesh_contract, str) else None,
        route_stage=mesh.get("route_stage") if isinstance(mesh.get("route_stage"), str) else None,
        mesh_artifact=mesh.get("mesh_artifact") if isinstance(mesh.get("mesh_artifact"), str) else None,
        mesh_metadata_path=mesh.get("metadata_path") if isinstance(mesh.get("metadata_path"), str) else None,
        marker_summary_path=(
            mesh.get("marker_summary_path")
            if isinstance(mesh.get("marker_summary_path"), str)
            else None
        ),
        marker_summary_status=marker_status,
        fairing_force_marker_status=fairing_force_marker_status,
        node_count=mesh.get("node_count") if isinstance(mesh.get("node_count"), int) else None,
        element_count=(
            mesh.get("element_count") if isinstance(mesh.get("element_count"), int) else None
        ),
        volume_element_count=volume_element_count if isinstance(volume_element_count, int) else None,
        body_bounds=mesh.get("body_bounds") if isinstance(mesh.get("body_bounds"), dict) else None,
        farfield_bounds=(
            mesh.get("farfield_bounds") if isinstance(mesh.get("farfield_bounds"), dict) else None
        ),
        hpa_mdo_guarantees=[
            "closed_solid_direct_cad_fixture_loaded",
            "gmsh_closed_solid_volume_dispatched",
            "mesh_handoff_v1_written",
            "fairing_wall_and_farfield_markers_present",
            "fairing_specific_force_marker_present",
        ]
        if pass_status
        else [
            "closed_solid_direct_cad_fixture_loaded",
            "gmsh_closed_solid_volume_dispatched",
        ],
        blocking_reasons=[
            "fairing_su2_handoff_not_materialized",
            "convergence_gate_not_run",
        ]
        if fairing_force_marker_status == "component_specific_marker_present"
        else [
            "fairing_component_specific_force_marker_missing",
            "su2_handoff_not_run",
            "convergence_gate_not_run",
        ],
        limitations=[
            "Synthetic OCC box fixture is a route smoke fixture, not fairing aerodynamic geometry.",
            "The fairing-specific marker is mesh-handoff evidence only; SU2 handoff has not consumed it yet.",
            "SU2_CFD was not executed.",
            "convergence_gate.v1 was not emitted.",
            "Production defaults were not changed.",
        ],
        run_status=result.get("status") if isinstance(result.get("status"), str) else None,
        failure_code=(
            result.get("failure_code") if isinstance(result.get("failure_code"), str) else None
        ),
        error=result.get("error") if isinstance(result.get("error"), str) else None,
    )


def _render_markdown(report: FairingSolidMeshHandoffSmokeReport) -> str:
    lines = [
        "# fairing_solid mesh_handoff smoke v1",
        "",
        "This is a real Gmsh mesh-handoff smoke for the closed-solid fairing route.",
        "It does not run SU2, BL runtime, or production defaults.",
        "",
        f"- component: `{report.component}`",
        f"- meshing_route: `{report.meshing_route}`",
        f"- smoke_status: `{report.smoke_status}`",
        f"- mesh_handoff_status: `{report.mesh_handoff_status}`",
        f"- mesh_contract: `{report.mesh_contract}`",
        f"- marker_summary_status: `{report.marker_summary_status}`",
        f"- fairing_force_marker_status: `{report.fairing_force_marker_status}`",
        f"- su2_promotion_status: `{report.su2_promotion_status}`",
        f"- volume_element_count: `{report.volume_element_count}`",
        "",
        "## Blocking Reasons",
        "",
    ]
    lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_fairing_solid_mesh_handoff_smoke_report(
    out_dir: Path,
    report: FairingSolidMeshHandoffSmokeReport | None = None,
) -> Dict[str, Path]:
    if report is None:
        report = build_fairing_solid_mesh_handoff_smoke_report(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "fairing_solid_mesh_handoff_smoke.v1.json"
    markdown_path = out_dir / "fairing_solid_mesh_handoff_smoke.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
