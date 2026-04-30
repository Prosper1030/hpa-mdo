from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal

from pydantic import BaseModel, Field

from .adapters.gmsh_backend import (
    _bbox_for_entities,
    _boundary_surface_tags,
    _bounds_dict,
    _classify_outer_boundary_surfaces,
    _farfield_bounds,
    _mesh_stats,
)
from .gmsh_runtime import GmshRuntimeError, load_gmsh
from .pipeline import validate_geometry_only
from .schema import FarfieldConfig, MeshJobConfig
from .tail_wing_surface_mesh_probe import (
    _default_source_path,
    _fixture_kind,
    _json_write,
    _provider_payload,
    _text_write,
    _topology_payload,
)
from .tail_wing_solidification_probe import _provider_status_value


RouteProbeStatusType = Literal[
    "explicit_volume_route_candidate",
    "explicit_volume_route_blocked",
    "geometry_unavailable",
    "unavailable",
]
SurfaceLoopVolumeStatusType = Literal[
    "volume_created",
    "missing",
    "failed",
    "not_attempted",
    "unavailable",
]
SurfaceLoopFarfieldCutStatusType = Literal[
    "valid_fluid_boundary",
    "invalid_fluid_boundary",
    "failed",
    "not_attempted",
    "unavailable",
]
BaffleFragmentStatusType = Literal[
    "mesh_generated",
    "mesh_failed_plc",
    "mesh_failed",
    "topology_fragmented",
    "failed",
    "not_attempted",
    "unavailable",
]
MeshHandoffStatusType = Literal["not_written", "candidate_only", "unavailable"]
SU2VolumeHandoffStatusType = Literal["not_su2_ready", "candidate_only", "unavailable"]
ProviderStatusType = Literal["materialized", "failed", "not_materialized", "unavailable"]


class TailWingExplicitVolumeCandidate(BaseModel):
    candidate_id: str
    strategy: Literal["occ_surface_loop_add_volume", "occ_baffle_fragment"]
    status: str
    input_surface_count: int | None = None
    created_volume_count: int | None = None
    created_surface_count: int | None = None
    signed_volume: float | None = None
    orientation_status: Literal[
        "positive_signed_volume",
        "negative_signed_volume",
        "zero_or_missing_volume",
        "unknown",
    ] = "unknown"
    fluid_volume_count: int | None = None
    farfield_surface_count: int | None = None
    tail_surface_count: int | None = None
    mesh_status: Literal["mesh_generated", "mesh_failed", "not_attempted"] = "not_attempted"
    mesh_stats: Dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    artifacts: Dict[str, str | None] = Field(default_factory=dict)


class TailWingExplicitVolumeRouteProbeReport(BaseModel):
    schema_version: Literal["tail_wing_explicit_volume_route_probe.v1"] = (
        "tail_wing_explicit_volume_route_probe.v1"
    )
    component: Literal["tail_wing"] = "tail_wing"
    source_fixture: Literal["blackcat_004_origin_vsp3", "custom_vsp3"] = (
        "blackcat_004_origin_vsp3"
    )
    geometry_provider: Literal["esp_rebuilt"] = "esp_rebuilt"
    geometry_family: Literal["thin_sheet_lifting_surface"] = "thin_sheet_lifting_surface"
    execution_mode: Literal["real_provider_explicit_volume_route_probe_no_su2"] = (
        "real_provider_explicit_volume_route_probe_no_su2"
    )
    source_path: str
    case_dir: str
    no_su2_execution: bool = True
    no_bl_runtime: bool = True
    production_default_changed: bool = False
    route_probe_status: RouteProbeStatusType
    mesh_handoff_status: MeshHandoffStatusType
    su2_volume_handoff_status: SU2VolumeHandoffStatusType
    provider_status: ProviderStatusType
    provider_surface_count: int | None = None
    provider_body_count: int | None = None
    provider_volume_count: int | None = None
    normalized_geometry_path: str | None = None
    surface_loop_volume_status: SurfaceLoopVolumeStatusType = "not_attempted"
    surface_loop_farfield_cut_status: SurfaceLoopFarfieldCutStatusType = "not_attempted"
    surface_loop_signed_volume: float | None = None
    baffle_fragment_status: BaffleFragmentStatusType = "not_attempted"
    explicit_volume_metadata_path: str | None = None
    gmsh_log_path: str | None = None
    recommended_next: Literal[
        "promote_explicit_volume_candidate_to_mesh_handoff_smoke",
        "repair_explicit_volume_orientation_or_baffle_surface_ownership",
        "not_evaluated",
    ] = "not_evaluated"
    candidates: List[TailWingExplicitVolumeCandidate] = Field(default_factory=list)
    hpa_mdo_guarantees: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    error: str | None = None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _import_rescaled_tail_surfaces(
    gmsh: Any,
    *,
    normalized_geometry_path: Path,
    topology: dict[str, Any],
) -> list[int]:
    imported_entities = gmsh.model.occ.importShapes(str(normalized_geometry_path))
    gmsh.model.occ.synchronize()
    import_scale = topology.get("import_scale_to_units")
    scale = (
        float(import_scale)
        if isinstance(import_scale, (int, float)) and import_scale > 0
        else 1.0
    )
    if abs(scale - 1.0) > 1.0e-9:
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
    return [int(tag) for _, tag in gmsh.model.getEntities(2)]


def _logger_messages(gmsh: Any) -> list[str]:
    try:
        return [str(message) for message in gmsh.logger.get()]
    except Exception:
        return []


def _write_candidate_artifacts(
    *,
    artifact_dir: Path,
    metadata: Dict[str, Any],
    logger_messages: Iterable[str],
) -> Dict[str, str]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = artifact_dir / "metadata.json"
    log_path = artifact_dir / "gmsh_log.txt"
    _json_write(metadata_path, metadata)
    _text_write(log_path, list(logger_messages))
    return {"metadata": str(metadata_path), "gmsh_log": str(log_path)}


def _orientation_status(signed_volume: float | None) -> str:
    if signed_volume is None or abs(signed_volume) <= 1.0e-15:
        return "zero_or_missing_volume"
    if signed_volume > 0.0:
        return "positive_signed_volume"
    return "negative_signed_volume"


def _run_surface_loop_volume_candidate(
    *,
    normalized_geometry_path: Path,
    out_dir: Path,
    topology: dict[str, Any],
) -> TailWingExplicitVolumeCandidate:
    artifact_dir = out_dir / "artifacts" / "explicit_volume" / "surface_loop_volume"
    try:
        gmsh = load_gmsh()
    except GmshRuntimeError as exc:
        return TailWingExplicitVolumeCandidate(
            candidate_id="surface_loop_volume",
            strategy="occ_surface_loop_add_volume",
            status="unavailable",
            error=str(exc),
        )

    gmsh_initialized = False
    gmsh_logger_started = False
    metadata: Dict[str, Any] = {
        "schema_version": "tail_wing_explicit_volume_candidate.v1",
        "candidate_id": "surface_loop_volume",
        "strategy": "occ_surface_loop_add_volume",
        "status": "started",
        "normalized_geometry_path": str(normalized_geometry_path),
    }
    try:
        gmsh.initialize()
        gmsh_initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("tail_wing_surface_loop_volume_probe")
        gmsh.logger.start()
        gmsh_logger_started = True

        surface_tags = _import_rescaled_tail_surfaces(
            gmsh,
            normalized_geometry_path=normalized_geometry_path,
            topology=topology,
        )
        if not surface_tags:
            raise RuntimeError("normalized tail STEP did not import any OCC surfaces.")

        surface_loop = gmsh.model.occ.addSurfaceLoop(surface_tags, sewing=True)
        volume_tag = gmsh.model.occ.addVolume([surface_loop])
        gmsh.model.occ.synchronize()
        body_volume_tags = [int(tag) for _, tag in gmsh.model.getEntities(3)]
        signed_volume = float(gmsh.model.occ.getMass(3, int(volume_tag)))
        body_bounds = _bbox_for_entities(gmsh, [(3, int(volume_tag))])
        farfield_bounds = _farfield_bounds(
            *body_bounds,
            farfield=FarfieldConfig(
                upstream_factor=2.0,
                downstream_factor=3.0,
                lateral_factor=2.0,
                vertical_factor=2.0,
            ),
        )
        box_tag = gmsh.model.occ.addBox(
            farfield_bounds["x_min"],
            farfield_bounds["y_min"],
            farfield_bounds["z_min"],
            farfield_bounds["x_max"] - farfield_bounds["x_min"],
            farfield_bounds["y_max"] - farfield_bounds["y_min"],
            farfield_bounds["z_max"] - farfield_bounds["z_min"],
        )
        fluid_entities, _ = gmsh.model.occ.cut(
            [(3, box_tag)],
            [(3, int(volume_tag))],
            removeObject=True,
            removeTool=True,
        )
        gmsh.model.occ.synchronize()
        fluid_volume_tags = [int(tag) for dim, tag in fluid_entities if int(dim) == 3]
        boundary_surface_tags = _boundary_surface_tags(
            gmsh,
            [(3, int(tag)) for tag in fluid_volume_tags],
        )
        aircraft_surface_tags, farfield_surface_tags = _classify_outer_boundary_surfaces(
            gmsh,
            boundary_surface_tags,
            farfield_bounds,
        )
        valid_cut = bool(fluid_volume_tags and aircraft_surface_tags and farfield_surface_tags)
        metadata.update(
            {
                "status": "volume_created",
                "surface_loop_tag": int(surface_loop),
                "volume_tag": int(volume_tag),
                "input_surface_count": len(surface_tags),
                "created_volume_count": len(body_volume_tags),
                "created_surface_count": len(gmsh.model.getEntities(2)),
                "signed_volume": signed_volume,
                "orientation_status": _orientation_status(signed_volume),
                "body_bounds": _bounds_dict(*body_bounds),
                "farfield_bounds": farfield_bounds,
                "farfield_cut_status": (
                    "valid_fluid_boundary" if valid_cut else "invalid_fluid_boundary"
                ),
                "fluid_volume_count": len(fluid_volume_tags),
                "aircraft_surface_count": len(aircraft_surface_tags),
                "farfield_surface_count": len(farfield_surface_tags),
                "boundary_surface_count": len(boundary_surface_tags),
            }
        )
        artifacts = _write_candidate_artifacts(
            artifact_dir=artifact_dir,
            metadata=metadata,
            logger_messages=_logger_messages(gmsh),
        )
        return TailWingExplicitVolumeCandidate(
            candidate_id="surface_loop_volume",
            strategy="occ_surface_loop_add_volume",
            status="volume_created",
            input_surface_count=len(surface_tags),
            created_volume_count=len(body_volume_tags),
            created_surface_count=len(gmsh.model.getEntities(2)),
            signed_volume=signed_volume,
            orientation_status=_orientation_status(signed_volume),
            fluid_volume_count=len(fluid_volume_tags),
            farfield_surface_count=len(farfield_surface_tags),
            tail_surface_count=len(aircraft_surface_tags),
            error=None if valid_cut else "surface-loop volume did not produce a valid external-flow fluid boundary",
            artifacts=artifacts,
        )
    except Exception as exc:
        metadata.update({"status": "failed", "error": str(exc)})
        artifacts = _write_candidate_artifacts(
            artifact_dir=artifact_dir,
            metadata=metadata,
            logger_messages=_logger_messages(gmsh) if gmsh_initialized else [],
        )
        return TailWingExplicitVolumeCandidate(
            candidate_id="surface_loop_volume",
            strategy="occ_surface_loop_add_volume",
            status="failed",
            error=str(exc),
            artifacts=artifacts,
        )
    finally:
        if gmsh_initialized:
            if gmsh_logger_started:
                try:
                    gmsh.logger.stop()
                except Exception:
                    pass
            gmsh.finalize()


def _run_baffle_fragment_candidate(
    *,
    normalized_geometry_path: Path,
    out_dir: Path,
    topology: dict[str, Any],
) -> TailWingExplicitVolumeCandidate:
    artifact_dir = out_dir / "artifacts" / "explicit_volume" / "baffle_fragment"
    try:
        gmsh = load_gmsh()
    except GmshRuntimeError as exc:
        return TailWingExplicitVolumeCandidate(
            candidate_id="baffle_fragment_volume",
            strategy="occ_baffle_fragment",
            status="unavailable",
            error=str(exc),
        )

    gmsh_initialized = False
    gmsh_logger_started = False
    metadata: Dict[str, Any] = {
        "schema_version": "tail_wing_explicit_volume_candidate.v1",
        "candidate_id": "baffle_fragment_volume",
        "strategy": "occ_baffle_fragment",
        "status": "started",
        "normalized_geometry_path": str(normalized_geometry_path),
    }
    mesh_stats: Dict[str, Any] = {}
    mesh_status: Literal["mesh_generated", "mesh_failed", "not_attempted"] = "not_attempted"
    mesh_error: str | None = None
    try:
        gmsh.initialize()
        gmsh_initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("tail_wing_baffle_fragment_probe")
        gmsh.logger.start()
        gmsh_logger_started = True

        surface_tags = _import_rescaled_tail_surfaces(
            gmsh,
            normalized_geometry_path=normalized_geometry_path,
            topology=topology,
        )
        if not surface_tags:
            raise RuntimeError("normalized tail STEP did not import any OCC surfaces.")

        body_bounds = _bbox_for_entities(gmsh, [(2, int(tag)) for tag in surface_tags])
        farfield_bounds = _farfield_bounds(
            *body_bounds,
            farfield=FarfieldConfig(
                upstream_factor=2.0,
                downstream_factor=3.0,
                lateral_factor=2.0,
                vertical_factor=2.0,
            ),
        )
        box_tag = gmsh.model.occ.addBox(
            farfield_bounds["x_min"],
            farfield_bounds["y_min"],
            farfield_bounds["z_min"],
            farfield_bounds["x_max"] - farfield_bounds["x_min"],
            farfield_bounds["y_max"] - farfield_bounds["y_min"],
            farfield_bounds["z_max"] - farfield_bounds["z_min"],
        )
        gmsh.model.occ.fragment(
            [(3, box_tag)],
            [(2, int(tag)) for tag in surface_tags],
            removeObject=True,
            removeTool=True,
        )
        gmsh.model.occ.synchronize()
        fluid_volume_tags = [int(tag) for _, tag in gmsh.model.getEntities(3)]
        all_surface_tags = [int(tag) for _, tag in gmsh.model.getEntities(2)]
        boundary_surface_tags = _boundary_surface_tags(
            gmsh,
            [(3, int(tag)) for tag in fluid_volume_tags],
        )
        _, farfield_surface_tags = _classify_outer_boundary_surfaces(
            gmsh,
            boundary_surface_tags,
            farfield_bounds,
        )
        tail_surface_tags = [
            int(tag)
            for tag in all_surface_tags
            if int(tag) not in {int(farfield_tag) for farfield_tag in farfield_surface_tags}
        ]
        if fluid_volume_tags:
            fluid_group = gmsh.model.addPhysicalGroup(3, fluid_volume_tags)
            gmsh.model.setPhysicalName(3, fluid_group, "fluid")
        if tail_surface_tags:
            tail_group = gmsh.model.addPhysicalGroup(2, tail_surface_tags)
            gmsh.model.setPhysicalName(2, tail_group, "tail_wing")
        if farfield_surface_tags:
            farfield_group = gmsh.model.addPhysicalGroup(2, farfield_surface_tags)
            gmsh.model.setPhysicalName(2, farfield_group, "farfield")

        if fluid_volume_tags and tail_surface_tags and farfield_surface_tags:
            gmsh.model.mesh.setSize(gmsh.model.getEntities(0), 0.25)
            gmsh.option.setNumber("Mesh.MeshSizeMin", 0.08)
            gmsh.option.setNumber("Mesh.MeshSizeMax", 0.6)
            gmsh.option.setNumber("Mesh.Algorithm", 5)
            gmsh.option.setNumber("Mesh.Algorithm3D", 1)
            try:
                gmsh.model.mesh.generate(3)
                mesh_stats = {"mesh_dim": 3, **_mesh_stats(gmsh)}
                mesh_status = "mesh_generated"
            except Exception as exc:
                mesh_status = "mesh_failed"
                mesh_error = str(exc)

        status = "mesh_generated" if mesh_status == "mesh_generated" else "topology_fragmented"
        metadata.update(
            {
                "status": status,
                "input_surface_count": len(surface_tags),
                "created_volume_count": len(fluid_volume_tags),
                "created_surface_count": len(all_surface_tags),
                "fluid_volume_count": len(fluid_volume_tags),
                "tail_surface_count": len(tail_surface_tags),
                "farfield_surface_count": len(farfield_surface_tags),
                "body_bounds": _bounds_dict(*body_bounds),
                "farfield_bounds": farfield_bounds,
                "mesh_status": mesh_status,
                "mesh_stats": mesh_stats,
                "mesh_error": mesh_error,
            }
        )
        artifacts = _write_candidate_artifacts(
            artifact_dir=artifact_dir,
            metadata=metadata,
            logger_messages=_logger_messages(gmsh),
        )
        return TailWingExplicitVolumeCandidate(
            candidate_id="baffle_fragment_volume",
            strategy="occ_baffle_fragment",
            status=("mesh_failed_plc" if mesh_error and "PLC Error" in mesh_error else status),
            input_surface_count=len(surface_tags),
            created_volume_count=len(fluid_volume_tags),
            created_surface_count=len(all_surface_tags),
            fluid_volume_count=len(fluid_volume_tags),
            farfield_surface_count=len(farfield_surface_tags),
            tail_surface_count=len(tail_surface_tags),
            mesh_status=mesh_status,
            mesh_stats=mesh_stats,
            error=mesh_error,
            artifacts=artifacts,
        )
    except Exception as exc:
        metadata.update({"status": "failed", "error": str(exc)})
        artifacts = _write_candidate_artifacts(
            artifact_dir=artifact_dir,
            metadata=metadata,
            logger_messages=_logger_messages(gmsh) if gmsh_initialized else [],
        )
        return TailWingExplicitVolumeCandidate(
            candidate_id="baffle_fragment_volume",
            strategy="occ_baffle_fragment",
            status="failed",
            mesh_status=mesh_status,
            error=str(exc),
            artifacts=artifacts,
        )
    finally:
        if gmsh_initialized:
            if gmsh_logger_started:
                try:
                    gmsh.logger.stop()
                except Exception:
                    pass
            gmsh.finalize()


def _surface_loop_volume_status(
    candidate: TailWingExplicitVolumeCandidate,
) -> SurfaceLoopVolumeStatusType:
    if candidate.status == "unavailable":
        return "unavailable"
    if candidate.status == "failed":
        return "failed"
    if (candidate.created_volume_count or 0) > 0:
        return "volume_created"
    return "missing"


def _surface_loop_farfield_cut_status(
    candidate: TailWingExplicitVolumeCandidate,
) -> SurfaceLoopFarfieldCutStatusType:
    if candidate.status == "unavailable":
        return "unavailable"
    if candidate.status == "failed":
        return "failed"
    if (
        (candidate.fluid_volume_count or 0) > 0
        and (candidate.tail_surface_count or 0) > 0
        and (candidate.farfield_surface_count or 0) > 0
    ):
        return "valid_fluid_boundary"
    return "invalid_fluid_boundary"


def _baffle_fragment_status(
    candidate: TailWingExplicitVolumeCandidate,
) -> BaffleFragmentStatusType:
    if candidate.status == "unavailable":
        return "unavailable"
    if candidate.status == "failed":
        return "failed"
    if candidate.status == "mesh_failed_plc":
        return "mesh_failed_plc"
    if candidate.mesh_status == "mesh_generated":
        return "mesh_generated"
    if candidate.mesh_status == "mesh_failed":
        return "mesh_failed"
    return "topology_fragmented"


def build_tail_wing_explicit_volume_route_probe_report(
    out_dir: Path,
    source_path: Path | None = None,
) -> TailWingExplicitVolumeRouteProbeReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    source = _default_source_path() if source_path is None else source_path
    if not source.exists():
        return TailWingExplicitVolumeRouteProbeReport(
            source_fixture=_fixture_kind(source),
            source_path=str(source),
            case_dir=str(out_dir),
            route_probe_status="unavailable",
            mesh_handoff_status="unavailable",
            su2_volume_handoff_status="unavailable",
            provider_status="unavailable",
            blocking_reasons=[
                "tail_wing_source_vsp3_missing",
                "tail_explicit_volume_route_probe_not_evaluated",
            ],
            limitations=[
                "The source VSP3 file was not available, so explicit volume routes were not evaluated.",
            ],
        )

    geometry_result = validate_geometry_only(
        MeshJobConfig(
            component="tail_wing",
            geometry=source,
            out_dir=out_dir / "artifacts" / "geometry",
            geometry_source="esp_rebuilt",
            geometry_provider="esp_rebuilt",
            geometry_family="thin_sheet_lifting_surface",
        )
    )
    provider = _provider_payload(geometry_result)
    topology = _topology_payload(provider)
    provider_status = _provider_status_value(provider.get("status"))
    normalized_geometry = geometry_result.get("normalized_geometry")
    normalized_geometry_path = Path(normalized_geometry) if isinstance(normalized_geometry, str) else None

    if (
        geometry_result.get("status") != "success"
        or provider_status != "materialized"
        or normalized_geometry_path is None
        or not normalized_geometry_path.exists()
    ):
        return TailWingExplicitVolumeRouteProbeReport(
            source_fixture=_fixture_kind(source),
            source_path=str(source),
            case_dir=str(out_dir),
            route_probe_status="geometry_unavailable",
            mesh_handoff_status="unavailable",
            su2_volume_handoff_status="unavailable",
            provider_status=provider_status,
            provider_surface_count=_int_or_none(topology.get("surface_count")),
            provider_body_count=_int_or_none(topology.get("body_count")),
            provider_volume_count=_int_or_none(topology.get("volume_count")),
            normalized_geometry_path=str(normalized_geometry_path) if normalized_geometry_path else None,
            blocking_reasons=[
                "tail_wing_provider_geometry_unavailable",
                "tail_explicit_volume_route_probe_not_evaluated",
            ],
            limitations=[
                "The ESP-rebuilt tail geometry did not materialize, so explicit volume routes were not evaluated.",
            ],
            error=geometry_result.get("error") if isinstance(geometry_result.get("error"), str) else None,
        )

    surface_loop_candidate = _run_surface_loop_volume_candidate(
        normalized_geometry_path=normalized_geometry_path,
        out_dir=out_dir,
        topology=topology,
    )
    baffle_candidate = _run_baffle_fragment_candidate(
        normalized_geometry_path=normalized_geometry_path,
        out_dir=out_dir,
        topology=topology,
    )

    surface_loop_status = _surface_loop_volume_status(surface_loop_candidate)
    farfield_cut_status = _surface_loop_farfield_cut_status(surface_loop_candidate)
    baffle_status = _baffle_fragment_status(baffle_candidate)
    pass_candidate = (
        farfield_cut_status == "valid_fluid_boundary"
        or baffle_status == "mesh_generated"
    )
    blocking_reasons: list[str] = []
    if farfield_cut_status != "valid_fluid_boundary":
        blocking_reasons.append("tail_explicit_surface_loop_volume_not_valid_external_flow_handoff")
    if baffle_status == "mesh_failed_plc":
        blocking_reasons.append("tail_baffle_fragment_mesh_failed_plc")
    elif baffle_status != "mesh_generated":
        blocking_reasons.append("tail_baffle_fragment_volume_not_mesh_handoff_ready")
    blocking_reasons.extend(["tail_wing_solver_not_run", "convergence_gate_not_run"])

    metadata = {
        "schema_version": "tail_wing_explicit_volume_route_probe_metadata.v1",
        "status": "explicit_volume_route_candidate" if pass_candidate else "explicit_volume_route_blocked",
        "source_path": str(source),
        "normalized_geometry_path": str(normalized_geometry_path),
        "provider_topology": topology,
        "candidates": [
            surface_loop_candidate.model_dump(mode="json"),
            baffle_candidate.model_dump(mode="json"),
        ],
        "blocking_reasons": blocking_reasons,
    }
    metadata_path = out_dir / "artifacts" / "explicit_volume" / "metadata.json"
    _json_write(metadata_path, metadata)

    return TailWingExplicitVolumeRouteProbeReport(
        source_fixture=_fixture_kind(source),
        source_path=str(source),
        case_dir=str(out_dir),
        route_probe_status=(
            "explicit_volume_route_candidate" if pass_candidate else "explicit_volume_route_blocked"
        ),
        mesh_handoff_status="candidate_only" if pass_candidate else "not_written",
        su2_volume_handoff_status="candidate_only" if pass_candidate else "not_su2_ready",
        provider_status=provider_status,
        provider_surface_count=_int_or_none(topology.get("surface_count")),
        provider_body_count=_int_or_none(topology.get("body_count")),
        provider_volume_count=_int_or_none(topology.get("volume_count")),
        normalized_geometry_path=str(normalized_geometry_path),
        surface_loop_volume_status=surface_loop_status,
        surface_loop_farfield_cut_status=farfield_cut_status,
        surface_loop_signed_volume=surface_loop_candidate.signed_volume,
        baffle_fragment_status=baffle_status,
        explicit_volume_metadata_path=str(metadata_path),
        gmsh_log_path=baffle_candidate.artifacts.get("gmsh_log"),
        recommended_next=(
            "promote_explicit_volume_candidate_to_mesh_handoff_smoke"
            if pass_candidate
            else "repair_explicit_volume_orientation_or_baffle_surface_ownership"
        ),
        candidates=[surface_loop_candidate, baffle_candidate],
        hpa_mdo_guarantees=[
            "real_vsp3_source_consumed",
            "esp_rebuilt_tail_wing_geometry_materialized",
            "explicit_occ_surface_loop_add_volume_attempted",
            "baffle_fragment_volume_attempted",
            "mesh_handoff_not_emitted",
            "su2_volume_handoff_not_claimed",
            "production_default_unchanged",
        ],
        blocking_reasons=blocking_reasons,
        limitations=[
            "This is a report-only route probe and does not emit mesh_handoff.v1.",
            "The existing production default route is unchanged.",
            "A Gmsh volume tag alone is not treated as a valid external-flow handoff.",
            "SU2_CFD was not executed.",
            "convergence_gate.v1 was not emitted.",
        ],
    )


def _render_markdown(report: TailWingExplicitVolumeRouteProbeReport) -> str:
    lines = [
        "# Tail Wing Explicit Volume Route Probe v1",
        "",
        f"- route_probe_status: `{report.route_probe_status}`",
        f"- mesh_handoff_status: `{report.mesh_handoff_status}`",
        f"- su2_volume_handoff_status: `{report.su2_volume_handoff_status}`",
        f"- provider_status: `{report.provider_status}`",
        f"- provider_surface_count: `{report.provider_surface_count}`",
        f"- provider_volume_count: `{report.provider_volume_count}`",
        f"- surface_loop_volume_status: `{report.surface_loop_volume_status}`",
        f"- surface_loop_farfield_cut_status: `{report.surface_loop_farfield_cut_status}`",
        f"- surface_loop_signed_volume: `{report.surface_loop_signed_volume}`",
        f"- baffle_fragment_status: `{report.baffle_fragment_status}`",
        f"- recommended_next: `{report.recommended_next}`",
        "",
        "## Candidates",
        "",
        "| candidate | strategy | status | volumes | farfield surfaces | tail surfaces | mesh |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for candidate in report.candidates:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{candidate.candidate_id}`",
                    f"`{candidate.strategy}`",
                    f"`{candidate.status}`",
                    f"`{candidate.created_volume_count}`",
                    f"`{candidate.farfield_surface_count}`",
                    f"`{candidate.tail_surface_count}`",
                    f"`{candidate.mesh_status}`",
                ]
            )
            + " |"
        )

    lines.extend(["", "## Blocking Reasons", ""])
    lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    lines.extend(["", "## Guarantees", ""])
    lines.extend(f"- `{guarantee}`" for guarantee in report.hpa_mdo_guarantees)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_tail_wing_explicit_volume_route_probe_report(
    out_dir: Path,
    source_path: Path | None = None,
    *,
    report: TailWingExplicitVolumeRouteProbeReport | None = None,
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = report or build_tail_wing_explicit_volume_route_probe_report(
        out_dir,
        source_path=source_path,
    )
    json_path = out_dir / "tail_wing_explicit_volume_route_probe.v1.json"
    markdown_path = out_dir / "tail_wing_explicit_volume_route_probe.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
