from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal

from pydantic import BaseModel, Field

from .gmsh_runtime import GmshRuntimeError, load_gmsh
from .pipeline import validate_geometry_only
from .schema import MeshJobConfig


ProbeStatusType = Literal["surface_mesh_pass", "surface_mesh_fail", "unavailable"]
SurfaceMeshStatusType = Literal["written", "missing", "unavailable"]
MeshHandoffStatusType = Literal["not_written", "unavailable"]
SU2VolumeHandoffStatusType = Literal["not_su2_ready", "unavailable"]
ProviderStatusType = Literal["materialized", "failed", "not_materialized", "unavailable"]


class TailWingSurfaceMeshProbeReport(BaseModel):
    schema_version: Literal["tail_wing_surface_mesh_probe.v1"] = (
        "tail_wing_surface_mesh_probe.v1"
    )
    component: Literal["tail_wing"] = "tail_wing"
    source_fixture: Literal["blackcat_004_origin_vsp3", "custom_vsp3"] = (
        "blackcat_004_origin_vsp3"
    )
    geometry_provider: Literal["esp_rebuilt"] = "esp_rebuilt"
    geometry_family: Literal["thin_sheet_lifting_surface"] = "thin_sheet_lifting_surface"
    execution_mode: Literal["real_provider_surface_mesh_probe_no_volume_handoff"] = (
        "real_provider_surface_mesh_probe_no_volume_handoff"
    )
    source_path: str
    case_dir: str
    no_su2_execution: bool = True
    no_bl_runtime: bool = True
    production_default_changed: bool = False
    probe_status: ProbeStatusType
    surface_mesh_status: SurfaceMeshStatusType
    mesh_handoff_status: MeshHandoffStatusType = "not_written"
    su2_volume_handoff_status: SU2VolumeHandoffStatusType
    provider_status: ProviderStatusType
    provider_surface_count: int | None = None
    provider_body_count: int | None = None
    provider_volume_count: int | None = None
    imported_surface_count: int | None = None
    imported_curve_count: int | None = None
    imported_point_count: int | None = None
    surface_element_count: int | None = None
    volume_element_count: int | None = None
    node_count: int | None = None
    element_count: int | None = None
    normalized_geometry_path: str | None = None
    surface_mesh_path: str | None = None
    surface_mesh_metadata_path: str | None = None
    marker_summary_path: str | None = None
    gmsh_log_path: str | None = None
    error: str | None = None
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


def _topology_payload(provider: dict[str, Any]) -> dict[str, Any]:
    topology = provider.get("topology")
    return topology if isinstance(topology, dict) else {}


def _json_write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _text_write(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(str(line) for line in lines).rstrip() + "\n", encoding="utf-8")


def _count_elements_for_entities(gmsh: Any, dim: int, entity_tags: Iterable[int]) -> int:
    total = 0
    for entity_tag in entity_tags:
        _, element_tags_groups, _ = gmsh.model.mesh.getElements(dim, int(entity_tag))
        total += sum(len(tags) for tags in element_tags_groups)
    return total


def _mesh_stats(gmsh: Any) -> Dict[str, int]:
    node_tags, _, _ = gmsh.model.mesh.getNodes()
    all_types, all_element_tags, _ = gmsh.model.mesh.getElements()
    surface_types, surface_element_tags, _ = gmsh.model.mesh.getElements(2)
    volume_types, volume_element_tags, _ = gmsh.model.mesh.getElements(3)
    return {
        "node_count": len(node_tags),
        "element_count": sum(len(tags) for tags in all_element_tags),
        "surface_element_count": sum(len(tags) for tags in surface_element_tags),
        "volume_element_count": sum(len(tags) for tags in volume_element_tags),
        "element_type_count": len(all_types),
        "surface_element_type_count": len(surface_types),
        "volume_element_type_count": len(volume_types),
    }


def _physical_group_summary(gmsh: Any, dim: int, physical_tag: int) -> Dict[str, Any]:
    entity_tags = [int(tag) for tag in gmsh.model.getEntitiesForPhysicalGroup(dim, physical_tag)]
    return {
        "exists": True,
        "dimension": int(dim),
        "physical_name": gmsh.model.getPhysicalName(int(dim), int(physical_tag)),
        "physical_tag": int(physical_tag),
        "entity_count": len(entity_tags),
        "entities": entity_tags,
        "element_count": _count_elements_for_entities(gmsh, dim, entity_tags),
    }


def _bbox_payload(gmsh: Any, dim_tags: Iterable[tuple[int, int]]) -> Dict[str, float] | None:
    mins = [float("inf"), float("inf"), float("inf")]
    maxs = [float("-inf"), float("-inf"), float("-inf")]
    saw_entity = False
    for dim, tag in dim_tags:
        saw_entity = True
        x_min, y_min, z_min, x_max, y_max, z_max = gmsh.model.getBoundingBox(dim, tag)
        mins[0] = min(mins[0], float(x_min))
        mins[1] = min(mins[1], float(y_min))
        mins[2] = min(mins[2], float(z_min))
        maxs[0] = max(maxs[0], float(x_max))
        maxs[1] = max(maxs[1], float(y_max))
        maxs[2] = max(maxs[2], float(z_max))
    if not saw_entity:
        return None
    return {
        "x_min": mins[0],
        "x_max": maxs[0],
        "y_min": mins[1],
        "y_max": maxs[1],
        "z_min": mins[2],
        "z_max": maxs[2],
    }


def _generate_surface_mesh(
    *,
    normalized_geometry_path: Path,
    out_dir: Path,
    topology: dict[str, Any],
    component_marker: str,
) -> Dict[str, Any]:
    try:
        gmsh = load_gmsh()
    except GmshRuntimeError as exc:
        raise RuntimeError(str(exc)) from exc

    mesh_dir = out_dir / "artifacts" / "surface_mesh"
    mesh_dir.mkdir(parents=True, exist_ok=True)
    mesh_path = mesh_dir / "tail_wing_surface_mesh.msh"
    metadata_path = mesh_dir / "surface_mesh_metadata.json"
    marker_summary_path = mesh_dir / "marker_summary.json"
    gmsh_log_path = mesh_dir / "gmsh_log.txt"

    gmsh_initialized = False
    gmsh_logger_started = False
    metadata: Dict[str, Any] = {
        "status": "started",
        "route_stage": "surface_only_lifting_surface_probe",
        "normalized_geometry_path": str(normalized_geometry_path),
        "surface_mesh": str(mesh_path),
    }
    try:
        gmsh.initialize()
        gmsh_initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.model.add("tail_wing_surface_mesh_probe")
        gmsh.logger.start()
        gmsh_logger_started = True

        imported_entities = gmsh.model.occ.importShapes(str(normalized_geometry_path))
        gmsh.model.occ.synchronize()
        import_scale = topology.get("import_scale_to_units")
        scale = float(import_scale) if isinstance(import_scale, (int, float)) and import_scale > 0 else 1.0
        if abs(scale - 1.0) > 1e-9:
            gmsh.model.occ.dilate(
                imported_entities,
                0.0,
                0.0,
                0.0,
                scale,
                scale,
                scale,
            )
            gmsh.model.occ.synchronize()

        surface_tags = [int(tag) for _, tag in gmsh.model.getEntities(2)]
        curve_tags = [int(tag) for _, tag in gmsh.model.getEntities(1)]
        point_entities = gmsh.model.getEntities(0)
        if not surface_tags:
            raise RuntimeError("normalized tail STEP did not import any OCC surfaces.")
        if point_entities:
            gmsh.model.mesh.setSize(point_entities, 0.08)

        surface_group = gmsh.model.addPhysicalGroup(2, surface_tags)
        gmsh.model.setPhysicalName(2, surface_group, component_marker)
        gmsh.model.mesh.generate(2)
        gmsh.write(str(mesh_path))

        stats = _mesh_stats(gmsh)
        marker_summary = {
            component_marker: _physical_group_summary(gmsh, 2, surface_group),
        }
        metadata.update(
            {
                "status": "success",
                "mesh_contract": None,
                "surface_mesh_status": "written",
                "mesh_handoff_status": "not_written",
                "su2_volume_handoff_status": "not_su2_ready",
                "entity_counts": {
                    "surface_count": len(surface_tags),
                    "curve_count": len(curve_tags),
                    "point_count": len(point_entities),
                    "volume_count": len(gmsh.model.getEntities(3)),
                },
                "surface_bounds": _bbox_payload(gmsh, [(2, tag) for tag in surface_tags]),
                "surface_tags": surface_tags,
                "curve_tags": curve_tags,
                "mesh": {
                    "format": "msh",
                    "mesh_dim": 2,
                    **stats,
                },
                "marker_summary": marker_summary,
                "artifacts": {
                    "surface_mesh": str(mesh_path),
                    "surface_mesh_metadata": str(metadata_path),
                    "marker_summary": str(marker_summary_path),
                    "gmsh_log": str(gmsh_log_path),
                },
                "limitations": [
                    "surface mesh only",
                    "no farfield volume",
                    "no external-flow volume mesh",
                    "mesh_handoff.v1 not emitted",
                ],
            }
        )
        _json_write(metadata_path, metadata)
        _json_write(marker_summary_path, marker_summary)
        return metadata
    except Exception as exc:
        metadata.update(
            {
                "status": "failed",
                "error": str(exc),
                "artifacts": {
                    "surface_mesh": str(mesh_path) if mesh_path.exists() else None,
                    "surface_mesh_metadata": str(metadata_path),
                    "marker_summary": str(marker_summary_path),
                    "gmsh_log": str(gmsh_log_path),
                },
            }
        )
        _json_write(metadata_path, metadata)
        _json_write(marker_summary_path, {})
        return metadata
    finally:
        if gmsh_initialized:
            if gmsh_logger_started:
                try:
                    _text_write(gmsh_log_path, [str(message) for message in gmsh.logger.get()])
                except Exception:
                    pass
                try:
                    gmsh.logger.stop()
                except Exception:
                    pass
            gmsh.finalize()


def build_tail_wing_surface_mesh_probe_report(
    out_dir: Path,
    source_path: Path | None = None,
) -> TailWingSurfaceMeshProbeReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    source = _default_source_path() if source_path is None else source_path
    if not source.exists():
        return TailWingSurfaceMeshProbeReport(
            source_fixture=_fixture_kind(source),
            source_path=str(source),
            case_dir=str(out_dir),
            probe_status="unavailable",
            surface_mesh_status="unavailable",
            mesh_handoff_status="unavailable",
            su2_volume_handoff_status="unavailable",
            provider_status="unavailable",
            blocking_reasons=[
                "tail_wing_source_vsp3_missing",
                "tail_surface_mesh_probe_not_evaluated",
            ],
            limitations=[
                "The source VSP3 file was not available, so the surface mesh probe was not evaluated.",
            ],
        )

    geometry_case_dir = out_dir / "artifacts" / "geometry"
    geometry_result = validate_geometry_only(
        MeshJobConfig(
            component="tail_wing",
            geometry=source,
            out_dir=geometry_case_dir,
            geometry_source="esp_rebuilt",
            geometry_provider="esp_rebuilt",
            geometry_family="thin_sheet_lifting_surface",
        )
    )
    provider = _provider_payload(geometry_result)
    topology = _topology_payload(provider)
    provider_status = provider.get("status")
    normalized_geometry = geometry_result.get("normalized_geometry")
    if geometry_result.get("status") != "success" or not isinstance(normalized_geometry, str):
        return TailWingSurfaceMeshProbeReport(
            source_fixture=_fixture_kind(source),
            source_path=str(source),
            case_dir=str(out_dir),
            probe_status="surface_mesh_fail",
            surface_mesh_status="missing",
            su2_volume_handoff_status="not_su2_ready",
            provider_status=(
                provider_status
                if provider_status in {"materialized", "failed", "not_materialized"}
                else "unavailable"
            ),
            provider_surface_count=(
                topology.get("surface_count") if isinstance(topology.get("surface_count"), int) else None
            ),
            provider_body_count=(
                topology.get("body_count") if isinstance(topology.get("body_count"), int) else None
            ),
            provider_volume_count=(
                topology.get("volume_count") if isinstance(topology.get("volume_count"), int) else None
            ),
            error=str(geometry_result.get("failure_code") or geometry_result.get("error")),
            blocking_reasons=[
                "tail_esp_rebuilt_geometry_not_available_for_surface_mesh_probe",
                "tail_surface_only_mesh_not_su2_volume_handoff",
            ],
            limitations=[
                "mesh_handoff.v1 is not emitted by the surface-only probe.",
                "SU2_CFD was not executed.",
            ],
        )

    surface_mesh_result = _generate_surface_mesh(
        normalized_geometry_path=Path(normalized_geometry),
        out_dir=out_dir,
        topology=topology,
        component_marker="tail_wing",
    )
    mesh_payload = (
        surface_mesh_result.get("mesh") if isinstance(surface_mesh_result.get("mesh"), dict) else {}
    )
    entity_counts = (
        surface_mesh_result.get("entity_counts")
        if isinstance(surface_mesh_result.get("entity_counts"), dict)
        else {}
    )
    artifacts = (
        surface_mesh_result.get("artifacts")
        if isinstance(surface_mesh_result.get("artifacts"), dict)
        else {}
    )
    marker_summary = (
        surface_mesh_result.get("marker_summary")
        if isinstance(surface_mesh_result.get("marker_summary"), dict)
        else {}
    )
    tail_marker = marker_summary.get("tail_wing") if isinstance(marker_summary, dict) else None
    surface_mesh_pass = (
        surface_mesh_result.get("status") == "success"
        and isinstance(mesh_payload.get("surface_element_count"), int)
        and int(mesh_payload["surface_element_count"]) > 0
        and isinstance(tail_marker, dict)
        and tail_marker.get("exists") is True
    )
    guarantees = [
        "real_vsp3_source_consumed",
        "esp_rebuilt_tail_wing_geometry_materialized",
        "mesh_handoff_not_emitted",
        "su2_volume_handoff_not_claimed",
        "production_default_unchanged",
    ]
    if surface_mesh_pass:
        guarantees.extend(
            [
                "real_tail_surface_mesh_generated",
                "tail_wing_surface_marker_present",
            ]
        )

    return TailWingSurfaceMeshProbeReport(
        source_fixture=_fixture_kind(source),
        source_path=str(source),
        case_dir=str(out_dir / "artifacts" / "surface_mesh"),
        probe_status="surface_mesh_pass" if surface_mesh_pass else "surface_mesh_fail",
        surface_mesh_status="written" if surface_mesh_pass else "missing",
        su2_volume_handoff_status="not_su2_ready",
        provider_status=(
            provider_status
            if provider_status in {"materialized", "failed", "not_materialized"}
            else "unavailable"
        ),
        provider_surface_count=(
            topology.get("surface_count") if isinstance(topology.get("surface_count"), int) else None
        ),
        provider_body_count=(
            topology.get("body_count") if isinstance(topology.get("body_count"), int) else None
        ),
        provider_volume_count=(
            topology.get("volume_count") if isinstance(topology.get("volume_count"), int) else None
        ),
        imported_surface_count=(
            entity_counts.get("surface_count") if isinstance(entity_counts.get("surface_count"), int) else None
        ),
        imported_curve_count=(
            entity_counts.get("curve_count") if isinstance(entity_counts.get("curve_count"), int) else None
        ),
        imported_point_count=(
            entity_counts.get("point_count") if isinstance(entity_counts.get("point_count"), int) else None
        ),
        surface_element_count=(
            mesh_payload.get("surface_element_count")
            if isinstance(mesh_payload.get("surface_element_count"), int)
            else None
        ),
        volume_element_count=(
            mesh_payload.get("volume_element_count")
            if isinstance(mesh_payload.get("volume_element_count"), int)
            else None
        ),
        node_count=(
            mesh_payload.get("node_count") if isinstance(mesh_payload.get("node_count"), int) else None
        ),
        element_count=(
            mesh_payload.get("element_count") if isinstance(mesh_payload.get("element_count"), int) else None
        ),
        normalized_geometry_path=normalized_geometry,
        surface_mesh_path=(
            artifacts.get("surface_mesh") if isinstance(artifacts.get("surface_mesh"), str) else None
        ),
        surface_mesh_metadata_path=(
            artifacts.get("surface_mesh_metadata")
            if isinstance(artifacts.get("surface_mesh_metadata"), str)
            else None
        ),
        marker_summary_path=(
            artifacts.get("marker_summary")
            if isinstance(artifacts.get("marker_summary"), str)
            else None
        ),
        gmsh_log_path=(
            artifacts.get("gmsh_log") if isinstance(artifacts.get("gmsh_log"), str) else None
        ),
        error=(
            surface_mesh_result.get("error")
            if isinstance(surface_mesh_result.get("error"), str)
            else None
        ),
        hpa_mdo_guarantees=guarantees,
        blocking_reasons=[
            "surface_only_tail_mesh_not_external_flow_volume_handoff",
            "tail_surface_only_mesh_not_su2_volume_handoff",
            "tail_wing_solver_not_run",
            "convergence_gate_not_run",
        ],
        limitations=[
            "mesh_handoff.v1 is not emitted by the surface-only probe.",
            "The probe has a tail_wing surface marker but no farfield volume marker.",
            "A zero-thickness surface mesh is not an external-flow SU2 volume mesh.",
            "Provider solidification/capping or a baffle-volume route is still required before SU2_CFD.",
            "SU2_CFD was not executed.",
            "convergence_gate.v1 was not emitted.",
        ],
    )


def _render_markdown(report: TailWingSurfaceMeshProbeReport) -> str:
    lines = [
        "# tail_wing surface mesh probe v1",
        "",
        "This probe meshes the real ESP tail surfaces without claiming a volume handoff.",
        "",
        f"- probe_status: `{report.probe_status}`",
        f"- surface_mesh_status: `{report.surface_mesh_status}`",
        f"- mesh_handoff_status: `{report.mesh_handoff_status}`",
        f"- su2_volume_handoff_status: `{report.su2_volume_handoff_status}`",
        f"- provider_status: `{report.provider_status}`",
        f"- provider_surface_count: `{report.provider_surface_count}`",
        f"- provider_volume_count: `{report.provider_volume_count}`",
        f"- imported_surface_count: `{report.imported_surface_count}`",
        f"- surface_element_count: `{report.surface_element_count}`",
        f"- volume_element_count: `{report.volume_element_count}`",
        "",
        "## Blocking Reasons",
        "",
    ]
    lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_tail_wing_surface_mesh_probe_report(
    out_dir: Path,
    report: TailWingSurfaceMeshProbeReport | None = None,
    source_path: Path | None = None,
) -> Dict[str, Path]:
    if report is None:
        report = build_tail_wing_surface_mesh_probe_report(
            out_dir,
            source_path=source_path,
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "tail_wing_surface_mesh_probe.v1.json"
    markdown_path = out_dir / "tail_wing_surface_mesh_probe.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
