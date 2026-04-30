from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from .fairing_solid_real_geometry_smoke import (
    build_fairing_solid_real_geometry_smoke_report,
)


ProbeStatusType = Literal[
    "mesh_handoff_pass",
    "mesh_handoff_blocked",
    "mesh_handoff_timeout",
    "unavailable",
]
MeshProbeStatusType = Literal["completed", "failed", "timeout", "not_evaluated"]
MeshHandoffStatusType = Literal["written", "missing", "not_evaluated"]
ProviderStatusType = Literal["materialized", "failed", "not_materialized", "unavailable"]
MarkerSummaryStatusType = Literal[
    "component_wall_and_farfield_present",
    "generic_wall_and_farfield_present",
    "missing_required_markers",
    "unavailable",
]
FairingForceMarkerStatusType = Literal[
    "component_specific_marker_present",
    "missing_component_specific_marker",
    "unavailable",
]


class FairingSolidRealMeshHandoffProbeReport(BaseModel):
    schema_version: Literal["fairing_solid_real_mesh_handoff_probe.v1"] = (
        "fairing_solid_real_mesh_handoff_probe.v1"
    )
    component: Literal["fairing_solid"] = "fairing_solid"
    source_fixture: Literal["hpa_fairing_best_design_vsp3", "custom_vsp3"] = (
        "hpa_fairing_best_design_vsp3"
    )
    geometry_provider: Literal["openvsp_surface_intersection"] = "openvsp_surface_intersection"
    geometry_family: Literal["closed_solid"] = "closed_solid"
    meshing_route: Literal["gmsh_closed_solid_volume"] = "gmsh_closed_solid_volume"
    execution_mode: Literal["real_provider_bounded_mesh_handoff_probe_no_su2"] = (
        "real_provider_bounded_mesh_handoff_probe_no_su2"
    )
    mesh_sizing_policy: Literal["coarse_real_geometry_probe_not_production_default"] = (
        "coarse_real_geometry_probe_not_production_default"
    )
    source_path: str
    case_dir: str
    no_su2_execution: bool = True
    no_bl_runtime: bool = True
    production_default_changed: bool = False
    probe_status: ProbeStatusType
    mesh_probe_status: MeshProbeStatusType
    mesh_handoff_status: MeshHandoffStatusType
    provider_status: ProviderStatusType
    marker_summary_status: MarkerSummaryStatusType = "unavailable"
    fairing_force_marker_status: FairingForceMarkerStatusType = "unavailable"
    bounded_probe_timeout_seconds: float
    failure_code: str | None = None
    error: str | None = None
    provider_surface_count: int | None = None
    provider_body_count: int | None = None
    provider_volume_count: int | None = None
    selected_geom_name: str | None = None
    selected_geom_type: str | None = None
    normalized_geometry_path: str | None = None
    mesh_metadata_path: str | None = None
    marker_summary_path: str | None = None
    gmsh_log_path: str | None = None
    mesh2d_watchdog_path: str | None = None
    mesh3d_watchdog_path: str | None = None
    mesh2d_watchdog_status: str | None = None
    mesh3d_watchdog_status: str | None = None
    mesh3d_timeout_phase_classification: str | None = None
    node_count: int | None = None
    element_count: int | None = None
    surface_element_count: int | None = None
    volume_element_count: int | None = None
    backend_rescale_applied: bool | None = None
    import_scale_to_units: float | None = None
    hpa_mdo_guarantees: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


def _default_source_path() -> Path:
    return Path(
        "/Volumes/Samsung SSD/HPA-Fairing-Optimization-Project/output/"
        "hpa_run_20260417_155036/vsp_models/best_design.vsp3"
    )


def _fixture_kind(source: Path) -> Literal["hpa_fairing_best_design_vsp3", "custom_vsp3"]:
    return (
        "hpa_fairing_best_design_vsp3"
        if source.resolve() == _default_source_path().resolve()
        else "custom_vsp3"
    )


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _marker_summary_status(marker_summary: dict[str, Any]) -> MarkerSummaryStatusType:
    fairing = marker_summary.get("fairing_solid")
    aircraft = marker_summary.get("aircraft")
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


def _mesh_payload(result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    mesh = result.get("mesh")
    return mesh if isinstance(mesh, dict) else {}


def _run_bounded_mesh_job(
    *,
    source_path: Path,
    case_dir: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    case_dir.mkdir(parents=True, exist_ok=True)
    payload_path = case_dir / "bounded_mesh_probe_payload.json"
    result_path = case_dir / "bounded_mesh_probe_result.json"
    payload = {
        "source_path": str(source_path),
        "case_dir": str(case_dir),
        "result_path": str(result_path),
    }
    payload_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    code = r"""
import json
import sys
from pathlib import Path

from hpa_meshing.pipeline import run_job
from hpa_meshing.schema import FarfieldConfig, MeshJobConfig

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
result = run_job(
    MeshJobConfig(
        component="fairing_solid",
        geometry=Path(payload["source_path"]),
        out_dir=Path(payload["case_dir"]),
        geometry_source="provider_generated",
        geometry_provider="openvsp_surface_intersection",
        geometry_family="closed_solid",
        meshing_route="gmsh_closed_solid_volume",
        mesh_dim=3,
        global_min_size=0.2,
        global_max_size=0.7,
        farfield=FarfieldConfig(
            upstream_factor=2.0,
            downstream_factor=3.0,
            lateral_factor=2.0,
            vertical_factor=2.0,
        ),
        metadata={
            "reference_geometry": {
                "ref_area": 1.0,
                "ref_length": 1.0,
                "ref_origin_moment": {"x": 1.4, "y": 0.0, "z": 0.0},
                "area_method": "fairing_real_mesh_handoff_probe_placeholder_reference",
                "length_method": "fairing_real_mesh_handoff_probe_placeholder_reference",
                "moment_method": "fairing_mid_length_placeholder",
                "warnings": ["coarse_real_geometry_probe_not_production_default"],
            },
            "mesh2d_watchdog_timeout_sec": 15.0,
            "mesh3d_watchdog_timeout_sec": 15.0,
        },
    )
)
Path(payload["result_path"]).write_text(
    json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
    encoding="utf-8",
)
"""
    env = os.environ.copy()
    src_dir = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code, str(payload_path)],
            cwd=str(Path(__file__).resolve().parents[2]),
            env=env,
            capture_output=True,
            text=True,
            timeout=float(timeout_seconds),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "timeout_seconds": float(timeout_seconds),
            "result": _safe_load_json(result_path),
            "stdout": exc.stdout,
            "stderr": exc.stderr,
            "error": f"bounded_mesh_handoff_timeout_after_{float(timeout_seconds):.1f}s",
            "result_path": str(result_path),
        }
    result = _safe_load_json(result_path)
    return {
        "status": "completed" if completed.returncode == 0 else "failed",
        "timeout_seconds": float(timeout_seconds),
        "returncode": completed.returncode,
        "result": result,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "error": None if completed.returncode == 0 else completed.stderr or completed.stdout,
        "result_path": str(result_path),
    }


def _probe_status(
    *,
    pass_status: bool,
    mesh_probe_status: MeshProbeStatusType,
) -> ProbeStatusType:
    if pass_status:
        return "mesh_handoff_pass"
    if mesh_probe_status == "timeout":
        return "mesh_handoff_timeout"
    return "mesh_handoff_blocked"


def _blocking_reasons(
    *,
    probe_status: ProbeStatusType,
    mesh3d_timeout_phase: str | None,
) -> list[str]:
    reasons: list[str] = []
    if probe_status == "mesh_handoff_timeout":
        reasons.append("fairing_real_geometry_mesh_handoff_timeout")
        if mesh3d_timeout_phase == "volume_insertion":
            reasons.append("fairing_real_geometry_mesh3d_volume_insertion_timeout")
    elif probe_status == "mesh_handoff_blocked":
        reasons.append("fairing_real_geometry_mesh_handoff_blocked")
    reasons.extend(
        [
            "fairing_real_geometry_su2_handoff_not_run",
            "fairing_solver_not_run",
            "convergence_gate_not_run",
        ]
    )
    return reasons


def build_fairing_solid_real_mesh_handoff_probe_report(
    out_dir: Path,
    source_path: Path | None = None,
    timeout_seconds: float = 60.0,
) -> FairingSolidRealMeshHandoffProbeReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    source = _default_source_path() if source_path is None else source_path
    if not source.exists():
        return FairingSolidRealMeshHandoffProbeReport(
            source_fixture=_fixture_kind(source),
            source_path=str(source),
            case_dir=str(out_dir),
            probe_status="unavailable",
            mesh_probe_status="not_evaluated",
            mesh_handoff_status="not_evaluated",
            provider_status="unavailable",
            bounded_probe_timeout_seconds=float(timeout_seconds),
            blocking_reasons=[
                "fairing_real_source_vsp3_missing",
                "fairing_real_geometry_mesh_handoff_not_evaluated",
            ],
            limitations=[
                "The fairing VSP3 source file was not available, so the real fairing mesh handoff probe was not evaluated.",
            ],
        )

    provider_report = build_fairing_solid_real_geometry_smoke_report(
        out_dir / "artifacts" / "provider_geometry",
        source_path=source,
    )
    if provider_report.geometry_smoke_status != "geometry_smoke_pass":
        return FairingSolidRealMeshHandoffProbeReport(
            source_fixture=_fixture_kind(source),
            source_path=str(source),
            case_dir=str(out_dir),
            probe_status="unavailable",
            mesh_probe_status="not_evaluated",
            mesh_handoff_status="not_evaluated",
            provider_status=provider_report.provider_status,
            bounded_probe_timeout_seconds=float(timeout_seconds),
            provider_surface_count=provider_report.surface_count,
            provider_body_count=provider_report.body_count,
            provider_volume_count=provider_report.volume_count,
            selected_geom_name=provider_report.selected_geom_name,
            selected_geom_type=provider_report.selected_geom_type,
            normalized_geometry_path=provider_report.normalized_geometry_path,
            blocking_reasons=[
                "fairing_real_geometry_provider_not_materialized",
                "fairing_real_geometry_mesh_handoff_not_evaluated",
            ],
            limitations=[
                "Provider geometry did not pass, so the bounded Gmsh handoff probe was not run.",
            ],
            error=provider_report.error,
        )

    case_dir = out_dir / "artifacts" / "real_mesh_probe"
    mesh_run = _run_bounded_mesh_job(
        source_path=source,
        case_dir=case_dir,
        timeout_seconds=float(timeout_seconds),
    )
    result = mesh_run.get("result") if isinstance(mesh_run.get("result"), dict) else None
    mesh = _mesh_payload(result)
    marker_summary = (
        mesh.get("marker_summary") if isinstance(mesh.get("marker_summary"), dict) else {}
    )
    marker_status = (
        _marker_summary_status(marker_summary) if marker_summary else "unavailable"
    )
    fairing_force_marker_status: FairingForceMarkerStatusType = (
        "component_specific_marker_present"
        if marker_status == "component_wall_and_farfield_present"
        else "missing_component_specific_marker"
        if marker_status != "unavailable"
        else "unavailable"
    )
    mesh_contract = mesh.get("contract")
    volume_element_count = mesh.get("volume_element_count")
    pass_status = (
        isinstance(result, dict)
        and result.get("status") == "success"
        and mesh_contract == "mesh_handoff.v1"
        and marker_status == "component_wall_and_farfield_present"
        and isinstance(volume_element_count, int)
        and volume_element_count > 0
    )
    mesh_probe_status: MeshProbeStatusType = (
        mesh_run.get("status")
        if mesh_run.get("status") in {"completed", "failed", "timeout"}
        else "failed"
    )
    probe_status = _probe_status(
        pass_status=pass_status,
        mesh_probe_status=mesh_probe_status,
    )
    mesh_handoff_status: MeshHandoffStatusType = (
        "written" if mesh_contract == "mesh_handoff.v1" else "missing"
    )
    mesh_dir = case_dir / "artifacts" / "mesh"
    mesh2d_watchdog = _safe_load_json(mesh_dir / "mesh2d_watchdog.json") or {}
    mesh3d_watchdog = _safe_load_json(mesh_dir / "mesh3d_watchdog.json") or {}
    mesh3d_timeout_phase = (
        mesh3d_watchdog.get("timeout_phase_classification")
        if isinstance(mesh3d_watchdog.get("timeout_phase_classification"), str)
        else None
    )
    unit_normalization = (
        mesh.get("unit_normalization")
        if isinstance(mesh.get("unit_normalization"), dict)
        else {}
    )
    hpa_mdo_guarantees = [
        "real_fairing_vsp3_source_consumed",
        "openvsp_surface_intersection_fairing_step_materialized",
        "fairing_closed_solid_topology_observed",
        "bounded_mesh_probe_executed",
        "no_su2_execution",
        "production_default_unchanged",
    ]
    if pass_status:
        hpa_mdo_guarantees.extend(
            [
                "gmsh_route_invoked_for_real_fairing_geometry",
                "mesh_handoff_v1_written_for_real_fairing_probe",
                "fairing_specific_force_marker_present",
            ]
        )

    return FairingSolidRealMeshHandoffProbeReport(
        source_fixture=_fixture_kind(source),
        source_path=str(source),
        case_dir=str(case_dir),
        probe_status=probe_status,
        mesh_probe_status=mesh_probe_status,
        mesh_handoff_status=mesh_handoff_status,
        provider_status=provider_report.provider_status,
        marker_summary_status=marker_status,
        fairing_force_marker_status=fairing_force_marker_status,
        bounded_probe_timeout_seconds=float(timeout_seconds),
        failure_code=(
            result.get("failure_code") if isinstance(result, dict) and isinstance(result.get("failure_code"), str) else None
        ),
        error=mesh_run.get("error") if isinstance(mesh_run.get("error"), str) else None,
        provider_surface_count=provider_report.surface_count,
        provider_body_count=provider_report.body_count,
        provider_volume_count=provider_report.volume_count,
        selected_geom_name=provider_report.selected_geom_name,
        selected_geom_type=provider_report.selected_geom_type,
        normalized_geometry_path=provider_report.normalized_geometry_path,
        mesh_metadata_path=(
            mesh.get("metadata_path") if isinstance(mesh.get("metadata_path"), str) else None
        ),
        marker_summary_path=(
            mesh.get("marker_summary_path")
            if isinstance(mesh.get("marker_summary_path"), str)
            else None
        ),
        gmsh_log_path=str(mesh_dir / "gmsh_log.txt"),
        mesh2d_watchdog_path=str(mesh_dir / "mesh2d_watchdog.json"),
        mesh3d_watchdog_path=str(mesh_dir / "mesh3d_watchdog.json"),
        mesh2d_watchdog_status=(
            mesh2d_watchdog.get("status") if isinstance(mesh2d_watchdog.get("status"), str) else None
        ),
        mesh3d_watchdog_status=(
            mesh3d_watchdog.get("status") if isinstance(mesh3d_watchdog.get("status"), str) else None
        ),
        mesh3d_timeout_phase_classification=mesh3d_timeout_phase,
        node_count=mesh.get("node_count") if isinstance(mesh.get("node_count"), int) else None,
        element_count=(
            mesh.get("element_count") if isinstance(mesh.get("element_count"), int) else None
        ),
        surface_element_count=(
            mesh.get("surface_element_count")
            if isinstance(mesh.get("surface_element_count"), int)
            else None
        ),
        volume_element_count=volume_element_count if isinstance(volume_element_count, int) else None,
        backend_rescale_applied=(
            unit_normalization.get("backend_rescale_applied")
            if isinstance(unit_normalization.get("backend_rescale_applied"), bool)
            else None
        ),
        import_scale_to_units=(
            float(unit_normalization["import_scale_to_units"])
            if isinstance(unit_normalization.get("import_scale_to_units"), (int, float))
            else None
        ),
        hpa_mdo_guarantees=hpa_mdo_guarantees,
        blocking_reasons=_blocking_reasons(
            probe_status=probe_status,
            mesh3d_timeout_phase=mesh3d_timeout_phase,
        ),
        limitations=[
            "This is a bounded coarse real-geometry probe, not production default sizing.",
            "It does not run BL runtime.",
            "It does not run SU2_CFD.",
            "convergence_gate.v1 was not emitted.",
            "A mesh handoff pass is not solver credibility without SU2 and convergence evidence.",
        ],
    )


def _render_markdown(report: FairingSolidRealMeshHandoffProbeReport) -> str:
    lines = [
        "# fairing_solid real mesh_handoff probe v1",
        "",
        "This probe tries the real fairing geometry against the current Gmsh closed-solid handoff route.",
        "It records handoff, timeout, or blocker evidence without running SU2.",
        "",
        f"- probe_status: `{report.probe_status}`",
        f"- mesh_probe_status: `{report.mesh_probe_status}`",
        f"- mesh_handoff_status: `{report.mesh_handoff_status}`",
        f"- provider_status: `{report.provider_status}`",
        f"- marker_summary_status: `{report.marker_summary_status}`",
        f"- fairing_force_marker_status: `{report.fairing_force_marker_status}`",
        f"- provider_volume_count: `{report.provider_volume_count}`",
        f"- volume_element_count: `{report.volume_element_count}`",
        f"- backend_rescale_applied: `{report.backend_rescale_applied}`",
        f"- error: `{report.error}`",
        "",
        "## Blocking Reasons",
        "",
    ]
    lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_fairing_solid_real_mesh_handoff_probe_report(
    out_dir: Path,
    report: FairingSolidRealMeshHandoffProbeReport | None = None,
    source_path: Path | None = None,
    timeout_seconds: float = 60.0,
) -> Dict[str, Path]:
    if report is None:
        report = build_fairing_solid_real_mesh_handoff_probe_report(
            out_dir,
            source_path=source_path,
            timeout_seconds=timeout_seconds,
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "fairing_solid_real_mesh_handoff_probe.v1.json"
    markdown_path = out_dir / "fairing_solid_real_mesh_handoff_probe.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
