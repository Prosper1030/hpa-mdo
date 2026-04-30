from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from .main_wing_esp_rebuilt_geometry_smoke import (
    build_main_wing_esp_rebuilt_geometry_smoke_report,
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
ProbeProfileType = Literal["coarse_first_volume_insertion_probe_not_production_default"]
MeshFailureClassificationType = Literal["invalid_boundary_mesh_overlapping_facets"]


PROBE_PROFILE: ProbeProfileType = "coarse_first_volume_insertion_probe_not_production_default"


def _probe_metadata() -> dict[str, Any]:
    return {
        "probe_profile": PROBE_PROFILE,
        "reference_geometry": {
            "ref_area": 34.65,
            "ref_length": 1.05,
            "ref_origin_moment": {"x": 0.2625, "y": 0.0, "z": 0.0},
            "area_method": "blackcat_main_wing_full_span_reference",
            "length_method": "blackcat_main_wing_chord_reference",
            "moment_method": "quarter_chord_reference",
            "warnings": ["coarse_real_geometry_probe_not_production_default"],
        },
        "mesh2d_watchdog_timeout_sec": 8.0,
        "mesh3d_watchdog_timeout_sec": 8.0,
        "coarse_first_tetra_enabled": True,
    }


class MainWingRealMeshHandoffProbeReport(BaseModel):
    schema_version: Literal["main_wing_real_mesh_handoff_probe.v1"] = (
        "main_wing_real_mesh_handoff_probe.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    source_fixture: Literal["blackcat_004_origin_vsp3", "custom_vsp3"] = (
        "blackcat_004_origin_vsp3"
    )
    geometry_provider: Literal["esp_rebuilt"] = "esp_rebuilt"
    geometry_family: Literal["thin_sheet_lifting_surface"] = "thin_sheet_lifting_surface"
    meshing_route: Literal["gmsh_thin_sheet_surface"] = "gmsh_thin_sheet_surface"
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
    probe_profile: ProbeProfileType = PROBE_PROFILE
    coarse_first_tetra_enabled: bool = True
    probe_global_min_size: float = 0.2
    probe_global_max_size: float = 0.8
    probe_status: ProbeStatusType
    mesh_probe_status: MeshProbeStatusType
    mesh_handoff_status: MeshHandoffStatusType
    provider_status: ProviderStatusType
    marker_summary_status: MarkerSummaryStatusType = "unavailable"
    bounded_probe_timeout_seconds: float
    failure_code: str | None = None
    error: str | None = None
    provider_surface_count: int | None = None
    provider_body_count: int | None = None
    provider_volume_count: int | None = None
    selected_geom_name: str | None = None
    selected_geom_span_y: float | None = None
    selected_geom_chord_x: float | None = None
    normalized_geometry_path: str | None = None
    mesh_metadata_path: str | None = None
    marker_summary_path: str | None = None
    gmsh_log_path: str | None = None
    surface_patch_diagnostics_path: str | None = None
    surface_patch_diagnostics_status: Literal["available", "missing"] = "missing"
    surface_family_hint_counts: Dict[str, int] = Field(default_factory=dict)
    suspicious_surface_tags: List[int] = Field(default_factory=list)
    mesh2d_watchdog_path: str | None = None
    mesh3d_watchdog_path: str | None = None
    mesh2d_watchdog_status: str | None = None
    mesh3d_watchdog_status: str | None = None
    mesh3d_timeout_phase_classification: str | None = None
    mesh_failure_classification: MeshFailureClassificationType | None = None
    mesh3d_nodes_created_per_boundary_node: float | None = None
    mesh3d_iteration_count: int | None = None
    mesh3d_latest_worst_tet_radius: float | None = None
    node_count: int | None = None
    element_count: int | None = None
    surface_element_count: int | None = None
    volume_element_count: int | None = None
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


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _marker_summary_status(marker_summary: dict[str, Any]) -> MarkerSummaryStatusType:
    main_wing = marker_summary.get("main_wing")
    aircraft = marker_summary.get("aircraft")
    farfield = marker_summary.get("farfield")
    if (
        isinstance(main_wing, dict)
        and main_wing.get("exists") is True
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


def _mesh_failure_classification(
    *,
    failure_code: str | None,
    error: str | None,
) -> MeshFailureClassificationType | None:
    if failure_code == "gmsh_invalid_boundary_mesh":
        return "invalid_boundary_mesh_overlapping_facets"
    if isinstance(error, str) and "Invalid boundary mesh" in error and "overlapping facets" in error:
        return "invalid_boundary_mesh_overlapping_facets"
    return None


def _run_bounded_mesh_job(
    *,
    source_path: Path,
    case_dir: Path,
    timeout_seconds: float,
    global_min_size: float = 0.2,
    global_max_size: float = 0.8,
) -> dict[str, Any]:
    case_dir.mkdir(parents=True, exist_ok=True)
    payload_path = case_dir / "bounded_mesh_probe_payload.json"
    result_path = case_dir / "bounded_mesh_probe_result.json"
    payload = {
        "source_path": str(source_path),
        "case_dir": str(case_dir),
        "result_path": str(result_path),
        "metadata": _probe_metadata(),
        "global_min_size": float(global_min_size),
        "global_max_size": float(global_max_size),
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
        component="main_wing",
        geometry=Path(payload["source_path"]),
        out_dir=Path(payload["case_dir"]),
        geometry_source="esp_rebuilt",
        geometry_provider="esp_rebuilt",
        geometry_family="thin_sheet_lifting_surface",
        meshing_route="gmsh_thin_sheet_surface",
        mesh_dim=3,
        global_min_size=float(payload["global_min_size"]),
        global_max_size=float(payload["global_max_size"]),
        farfield=FarfieldConfig(
            upstream_factor=2.0,
            downstream_factor=3.0,
            lateral_factor=2.0,
            vertical_factor=2.0,
        ),
        metadata=payload["metadata"],
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


def build_main_wing_real_mesh_handoff_probe_report(
    out_dir: Path,
    source_path: Path | None = None,
    timeout_seconds: float = 45.0,
    global_min_size: float = 0.2,
    global_max_size: float = 0.8,
) -> MainWingRealMeshHandoffProbeReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    source = _default_source_path() if source_path is None else source_path
    if not source.exists():
        return MainWingRealMeshHandoffProbeReport(
            source_fixture=_fixture_kind(source),
            source_path=str(source),
            case_dir=str(out_dir),
            probe_status="unavailable",
            mesh_probe_status="not_evaluated",
            mesh_handoff_status="not_evaluated",
            provider_status="unavailable",
            bounded_probe_timeout_seconds=float(timeout_seconds),
            blocking_reasons=[
                "main_wing_source_vsp3_missing",
                "main_wing_real_geometry_mesh_handoff_not_evaluated",
            ],
            limitations=[
                "The source VSP3 file was not available, so the real main-wing mesh handoff probe was not evaluated.",
            ],
        )

    provider_report = build_main_wing_esp_rebuilt_geometry_smoke_report(
        out_dir / "artifacts" / "provider_geometry",
        source_path=source,
    )
    if provider_report.geometry_smoke_status != "geometry_smoke_pass":
        return MainWingRealMeshHandoffProbeReport(
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
            normalized_geometry_path=provider_report.normalized_geometry_path,
            blocking_reasons=[
                "main_wing_real_geometry_provider_not_materialized",
                "main_wing_real_geometry_mesh_handoff_not_evaluated",
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
        global_min_size=float(global_min_size),
        global_max_size=float(global_max_size),
    )
    result = mesh_run.get("result") if isinstance(mesh_run.get("result"), dict) else None
    mesh = _mesh_payload(result)
    marker_summary = (
        mesh.get("marker_summary") if isinstance(mesh.get("marker_summary"), dict) else {}
    )
    marker_status = (
        _marker_summary_status(marker_summary) if marker_summary else "unavailable"
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
        mesh_run.get("status") if mesh_run.get("status") in {"completed", "failed", "timeout"} else "failed"
    )
    if pass_status:
        probe_status: ProbeStatusType = "mesh_handoff_pass"
    elif mesh_probe_status == "timeout":
        probe_status = "mesh_handoff_timeout"
    else:
        probe_status = "mesh_handoff_blocked"

    blocking_reasons = ["main_wing_solver_not_run", "convergence_gate_not_run"]
    if probe_status == "mesh_handoff_timeout":
        blocking_reasons.insert(0, "main_wing_real_geometry_mesh_handoff_timeout")
    elif probe_status == "mesh_handoff_blocked":
        blocking_reasons.insert(0, "main_wing_real_geometry_mesh_handoff_blocked")

    mesh_dir = case_dir / "artifacts" / "mesh"
    mesh2d_watchdog = _safe_load_json(mesh_dir / "mesh2d_watchdog.json") or {}
    mesh3d_watchdog = _safe_load_json(mesh_dir / "mesh3d_watchdog.json") or {}
    surface_patch_diagnostics_path = mesh_dir / "surface_patch_diagnostics.json"
    surface_patch_diagnostics = _safe_load_json(surface_patch_diagnostics_path) or {}
    family_hint_counts = surface_patch_diagnostics.get("family_hint_counts")
    suspicious_surfaces = surface_patch_diagnostics.get("suspicious_surfaces")
    mesh3d_timeout_phase = mesh3d_watchdog.get("timeout_phase_classification")
    failure_code = (
        result.get("failure_code")
        if isinstance(result, dict) and isinstance(result.get("failure_code"), str)
        else None
    )
    error = (
        result.get("error")
        if isinstance(result, dict) and isinstance(result.get("error"), str)
        else mesh_run.get("error") if isinstance(mesh_run.get("error"), str) else None
    )
    mesh_failure_classification = _mesh_failure_classification(
        failure_code=failure_code,
        error=error,
    )
    if (
        probe_status == "mesh_handoff_timeout"
        and mesh3d_timeout_phase == "volume_insertion"
    ):
        blocking_reasons.insert(1, "main_wing_real_geometry_mesh3d_volume_insertion_timeout")
    if mesh_failure_classification == "invalid_boundary_mesh_overlapping_facets":
        blocking_reasons.insert(
            1,
            "main_wing_real_geometry_invalid_boundary_mesh_overlapping_facets",
        )

    hpa_mdo_guarantees = [
        "real_vsp3_source_consumed",
        "esp_rebuilt_main_wing_geometry_materialized",
        "bounded_mesh_probe_executed",
        "no_su2_execution",
        "production_default_unchanged",
    ]
    if pass_status:
        hpa_mdo_guarantees.extend(
            [
                "gmsh_route_invoked_for_real_main_wing_geometry",
                "mesh_handoff_v1_written_for_real_main_wing_probe",
            ]
        )

    return MainWingRealMeshHandoffProbeReport(
        source_fixture=_fixture_kind(source),
        source_path=str(source),
        case_dir=str(case_dir),
        probe_status=probe_status,
        mesh_probe_status=mesh_probe_status,
        mesh_handoff_status="written" if mesh_contract == "mesh_handoff.v1" else "missing",
        provider_status=provider_report.provider_status,
        marker_summary_status=marker_status,
        bounded_probe_timeout_seconds=float(timeout_seconds),
        probe_global_min_size=float(global_min_size),
        probe_global_max_size=float(global_max_size),
        failure_code=failure_code,
        error=error,
        provider_surface_count=provider_report.surface_count,
        provider_body_count=provider_report.body_count,
        provider_volume_count=provider_report.volume_count,
        selected_geom_name=provider_report.selected_geom_name,
        selected_geom_span_y=provider_report.selected_geom_span_y,
        selected_geom_chord_x=provider_report.selected_geom_chord_x,
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
        surface_patch_diagnostics_path=str(surface_patch_diagnostics_path),
        surface_patch_diagnostics_status=(
            "available" if surface_patch_diagnostics else "missing"
        ),
        surface_family_hint_counts=(
            {
                str(name): int(count)
                for name, count in family_hint_counts.items()
                if isinstance(count, int)
            }
            if isinstance(family_hint_counts, dict)
            else {}
        ),
        suspicious_surface_tags=(
            [
                int(entry["tag"])
                for entry in suspicious_surfaces[:12]
                if isinstance(entry, dict) and isinstance(entry.get("tag"), int)
            ]
            if isinstance(suspicious_surfaces, list)
            else []
        ),
        mesh2d_watchdog_path=str(mesh_dir / "mesh2d_watchdog.json"),
        mesh3d_watchdog_path=str(mesh_dir / "mesh3d_watchdog.json"),
        mesh2d_watchdog_status=(
            mesh2d_watchdog.get("status")
            if isinstance(mesh2d_watchdog.get("status"), str)
            else None
        ),
        mesh3d_watchdog_status=(
            mesh3d_watchdog.get("status")
            if isinstance(mesh3d_watchdog.get("status"), str)
            else None
        ),
        mesh3d_timeout_phase_classification=(
            mesh3d_timeout_phase if isinstance(mesh3d_timeout_phase, str) else None
        ),
        mesh_failure_classification=mesh_failure_classification,
        mesh3d_nodes_created_per_boundary_node=(
            float(mesh3d_watchdog["nodes_created_per_boundary_node"])
            if isinstance(mesh3d_watchdog.get("nodes_created_per_boundary_node"), (int, float))
            else None
        ),
        mesh3d_iteration_count=(
            int(mesh3d_watchdog["iteration_count"])
            if isinstance(mesh3d_watchdog.get("iteration_count"), int)
            else None
        ),
        mesh3d_latest_worst_tet_radius=(
            float(mesh3d_watchdog["latest_worst_tet_radius"])
            if isinstance(mesh3d_watchdog.get("latest_worst_tet_radius"), (int, float))
            else None
        ),
        node_count=mesh.get("node_count") if isinstance(mesh.get("node_count"), int) else None,
        element_count=(
            mesh.get("element_count") if isinstance(mesh.get("element_count"), int) else None
        ),
        surface_element_count=(
            mesh.get("surface_element_count")
            if isinstance(mesh.get("surface_element_count"), int)
            else None
        ),
        volume_element_count=(
            volume_element_count if isinstance(volume_element_count, int) else None
        ),
        hpa_mdo_guarantees=hpa_mdo_guarantees,
        blocking_reasons=blocking_reasons,
        limitations=[
            "This is a bounded coarse real-geometry probe, not production default sizing.",
            "It does not run BL runtime.",
            "It does not run SU2_CFD.",
            "convergence_gate.v1 was not emitted.",
            "A timeout or blocked mesh is evidence for meshing policy work, not a solver result.",
        ],
    )


def _render_markdown(report: MainWingRealMeshHandoffProbeReport) -> str:
    lines = [
        "# main_wing real mesh_handoff probe v1",
        "",
        "This probe tries the real ESP main-wing geometry against the current Gmsh handoff route.",
        "It runs in a bounded child process and does not run SU2.",
        "",
        f"- probe_status: `{report.probe_status}`",
        f"- mesh_probe_status: `{report.mesh_probe_status}`",
        f"- mesh_handoff_status: `{report.mesh_handoff_status}`",
        f"- provider_status: `{report.provider_status}`",
        f"- provider_surface_count: `{report.provider_surface_count}`",
        f"- provider_volume_count: `{report.provider_volume_count}`",
        f"- selected_geom_name: `{report.selected_geom_name}`",
        f"- marker_summary_status: `{report.marker_summary_status}`",
        f"- probe_profile: `{report.probe_profile}`",
        f"- coarse_first_tetra_enabled: `{report.coarse_first_tetra_enabled}`",
        f"- probe_global_min_size: `{report.probe_global_min_size}`",
        f"- probe_global_max_size: `{report.probe_global_max_size}`",
        f"- surface_patch_diagnostics_status: `{report.surface_patch_diagnostics_status}`",
        f"- surface_family_hint_counts: `{report.surface_family_hint_counts}`",
        f"- suspicious_surface_tags: `{report.suspicious_surface_tags}`",
        f"- volume_element_count: `{report.volume_element_count}`",
        f"- bounded_probe_timeout_seconds: `{report.bounded_probe_timeout_seconds}`",
        f"- mesh2d_watchdog_status: `{report.mesh2d_watchdog_status}`",
        f"- mesh3d_watchdog_status: `{report.mesh3d_watchdog_status}`",
        f"- mesh3d_timeout_phase_classification: `{report.mesh3d_timeout_phase_classification}`",
        f"- mesh_failure_classification: `{report.mesh_failure_classification}`",
        f"- mesh3d_nodes_created_per_boundary_node: `{report.mesh3d_nodes_created_per_boundary_node}`",
        f"- error: `{report.error}`",
        "",
        "## Blocking Reasons",
        "",
    ]
    lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_main_wing_real_mesh_handoff_probe_report(
    out_dir: Path,
    report: MainWingRealMeshHandoffProbeReport | None = None,
    source_path: Path | None = None,
    timeout_seconds: float = 45.0,
    global_min_size: float = 0.2,
    global_max_size: float = 0.8,
) -> Dict[str, Path]:
    if report is None:
        report = build_main_wing_real_mesh_handoff_probe_report(
            out_dir,
            source_path=source_path,
            timeout_seconds=timeout_seconds,
            global_min_size=global_min_size,
            global_max_size=global_max_size,
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "main_wing_real_mesh_handoff_probe.v1.json"
    markdown_path = out_dir / "main_wing_real_mesh_handoff_probe.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
