from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from .pipeline import run_job
from .schema import FarfieldConfig, MeshJobConfig


ProbeStatusType = Literal["mesh_handoff_pass", "mesh_handoff_blocked", "unavailable"]
MeshHandoffStatusType = Literal["written", "missing", "not_evaluated"]
ProviderStatusType = Literal["materialized", "failed", "not_materialized", "unavailable"]


class TailWingRealMeshHandoffProbeReport(BaseModel):
    schema_version: Literal["tail_wing_real_mesh_handoff_probe.v1"] = (
        "tail_wing_real_mesh_handoff_probe.v1"
    )
    component: Literal["tail_wing"] = "tail_wing"
    source_fixture: Literal["blackcat_004_origin_vsp3", "custom_vsp3"] = (
        "blackcat_004_origin_vsp3"
    )
    geometry_provider: Literal["esp_rebuilt"] = "esp_rebuilt"
    geometry_family: Literal["thin_sheet_lifting_surface"] = "thin_sheet_lifting_surface"
    meshing_route: Literal["gmsh_thin_sheet_surface"] = "gmsh_thin_sheet_surface"
    execution_mode: Literal["real_provider_mesh_handoff_probe_no_su2"] = (
        "real_provider_mesh_handoff_probe_no_su2"
    )
    source_path: str
    case_dir: str
    no_su2_execution: bool = True
    no_bl_runtime: bool = True
    production_default_changed: bool = False
    probe_status: ProbeStatusType
    mesh_handoff_status: MeshHandoffStatusType
    provider_status: ProviderStatusType
    failure_code: str | None = None
    error: str | None = None
    provider_surface_count: int | None = None
    provider_body_count: int | None = None
    provider_volume_count: int | None = None
    normalized_geometry_path: str | None = None
    mesh_metadata_path: str | None = None
    marker_summary_path: str | None = None
    gmsh_log_path: str | None = None
    hpa_mdo_guarantees: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def _default_source_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "blackcat_004_origin.vsp3"


def _fixture_kind(source: Path) -> Literal["blackcat_004_origin_vsp3", "custom_vsp3"]:
    return (
        "blackcat_004_origin_vsp3"
        if source.resolve() == _default_source_path().resolve()
        else "custom_vsp3"
    )


def _provider_payload(result: dict[str, Any]) -> dict[str, Any]:
    provider = result.get("provider")
    return provider if isinstance(provider, dict) else {}


def _mesh_payload(result: dict[str, Any]) -> dict[str, Any]:
    mesh = result.get("mesh")
    return mesh if isinstance(mesh, dict) else {}


def build_tail_wing_real_mesh_handoff_probe_report(
    out_dir: Path,
    source_path: Path | None = None,
) -> TailWingRealMeshHandoffProbeReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    source = _default_source_path() if source_path is None else source_path
    if not source.exists():
        return TailWingRealMeshHandoffProbeReport(
            source_fixture=_fixture_kind(source),
            source_path=str(source),
            case_dir=str(out_dir),
            probe_status="unavailable",
            mesh_handoff_status="not_evaluated",
            provider_status="unavailable",
            blocking_reasons=[
                "tail_wing_source_vsp3_missing",
                "tail_real_geometry_mesh_handoff_not_evaluated",
            ],
            limitations=[
                "The source VSP3 file was not available, so the real tail mesh handoff probe was not evaluated.",
            ],
        )

    result = run_job(
        MeshJobConfig(
            component="tail_wing",
            geometry=source,
            out_dir=out_dir / "artifacts" / "real_mesh_probe",
            geometry_source="esp_rebuilt",
            geometry_provider="esp_rebuilt",
            geometry_family="thin_sheet_lifting_surface",
            meshing_route="gmsh_thin_sheet_surface",
            mesh_dim=3,
            global_min_size=0.08,
            global_max_size=0.3,
            farfield=FarfieldConfig(
                upstream_factor=2.0,
                downstream_factor=3.0,
                lateral_factor=2.0,
                vertical_factor=2.0,
            ),
            metadata={
                "reference_geometry": {
                    "ref_area": 2.4,
                    "ref_length": 0.8,
                    "ref_origin_moment": {"x": 4.4, "y": 0.0, "z": 0.0},
                    "area_method": "blackcat_tail_rough_planform",
                    "length_method": "blackcat_tail_chord",
                    "moment_method": "blackcat_tail_mid_chord",
                    "warnings": ["rough_reference_for_mesh_handoff_probe_only"],
                },
            },
        )
    )
    provider = _provider_payload(result)
    topology = provider.get("topology") if isinstance(provider.get("topology"), dict) else {}
    mesh = _mesh_payload(result)
    mesh_contract = mesh.get("contract")
    error = result.get("error") if isinstance(result.get("error"), str) else None
    surface_only_blocker = (
        topology.get("volume_count") == 0
        and error is not None
        and "did not import any OCC volumes" in error
    )
    probe_status: ProbeStatusType = (
        "mesh_handoff_pass"
        if result.get("status") == "success" and mesh_contract == "mesh_handoff.v1"
        else "mesh_handoff_blocked"
    )
    mesh_handoff_status: MeshHandoffStatusType = (
        "written" if mesh_contract == "mesh_handoff.v1" else "missing"
    )

    blocking_reasons = [
        "tail_wing_solver_not_run",
        "convergence_gate_not_run",
    ]
    if surface_only_blocker:
        blocking_reasons.insert(0, "real_tail_geometry_surface_only_no_occ_volume")
    elif probe_status != "mesh_handoff_pass":
        blocking_reasons.insert(0, "tail_real_geometry_mesh_handoff_failed")

    return TailWingRealMeshHandoffProbeReport(
        source_fixture=_fixture_kind(source),
        source_path=str(source),
        case_dir=str(out_dir / "artifacts" / "real_mesh_probe"),
        probe_status=probe_status,
        mesh_handoff_status=mesh_handoff_status,
        provider_status=(
            provider.get("status") if provider.get("status") in {"materialized", "failed", "not_materialized"} else "unavailable"
        ),
        failure_code=(
            result.get("failure_code") if isinstance(result.get("failure_code"), str) else None
        ),
        error=error,
        provider_surface_count=(
            topology.get("surface_count") if isinstance(topology.get("surface_count"), int) else None
        ),
        provider_body_count=(
            topology.get("body_count") if isinstance(topology.get("body_count"), int) else None
        ),
        provider_volume_count=(
            topology.get("volume_count") if isinstance(topology.get("volume_count"), int) else None
        ),
        normalized_geometry_path=(
            result.get("normalized_geometry")
            if isinstance(result.get("normalized_geometry"), str)
            else None
        ),
        mesh_metadata_path=(
            mesh.get("metadata_path") if isinstance(mesh.get("metadata_path"), str) else None
        ),
        marker_summary_path=(
            mesh.get("marker_summary_path")
            if isinstance(mesh.get("marker_summary_path"), str)
            else None
        ),
        gmsh_log_path=str(out_dir / "artifacts" / "real_mesh_probe" / "artifacts" / "mesh" / "gmsh_log.txt"),
        hpa_mdo_guarantees=[
            "real_vsp3_source_consumed",
            "esp_rebuilt_tail_wing_geometry_materialized",
            "gmsh_route_invoked_for_real_tail_geometry",
            "surface_only_volume_blocker_recorded",
            "no_su2_execution",
            "production_default_unchanged",
        ],
        blocking_reasons=blocking_reasons,
        limitations=[
            "synthetic_tail_slab_is_not_real_tail_mesh_evidence",
            "Real ESP tail geometry currently materializes as surface-only STEP evidence.",
            "The current gmsh_thin_sheet_surface backend expects OCC volumes for its external-flow route.",
            "mesh_handoff.v1 is not emitted for the real tail geometry in this probe.",
            "SU2_CFD was not executed.",
            "convergence_gate.v1 was not emitted.",
        ],
    )


def _render_markdown(report: TailWingRealMeshHandoffProbeReport) -> str:
    lines = [
        "# tail_wing real mesh_handoff probe v1",
        "",
        "This probe tries the real ESP tail geometry against the current Gmsh handoff route.",
        "It records the surface_only blocker without running SU2.",
        "",
        f"- probe_status: `{report.probe_status}`",
        f"- mesh_handoff_status: `{report.mesh_handoff_status}`",
        f"- failure_code: `{report.failure_code}`",
        f"- provider_status: `{report.provider_status}`",
        f"- provider_surface_count: `{report.provider_surface_count}`",
        f"- provider_volume_count: `{report.provider_volume_count}`",
        f"- error: `{report.error}`",
        "",
        "## Blocking Reasons",
        "",
    ]
    lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_tail_wing_real_mesh_handoff_probe_report(
    out_dir: Path,
    report: TailWingRealMeshHandoffProbeReport | None = None,
    source_path: Path | None = None,
) -> Dict[str, Path]:
    if report is None:
        report = build_tail_wing_real_mesh_handoff_probe_report(
            out_dir,
            source_path=source_path,
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "tail_wing_real_mesh_handoff_probe.v1.json"
    markdown_path = out_dir / "tail_wing_real_mesh_handoff_probe.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
