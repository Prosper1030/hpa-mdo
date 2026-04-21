from __future__ import annotations

import json
import math
import re
import uuid
from pathlib import Path

from ..gmsh_runtime import GmshRuntimeError, load_gmsh
from ..reference_geometry import load_openvsp_reference_data
from ..schema import (
    Bounds3D,
    GeometryProviderRequest,
    GeometryProviderResult,
    GeometryTopologyMetadata,
)


_LEN_UNIT_MAP = {
    "mm": "LEN_MM",
    "m": "LEN_M",
}
_IMPORT_SCALE_IDENTITY_TOL = 1.0e-6

_STEP_UNIT_PATTERN = re.compile(r"SI_UNIT\(\s*(\.[A-Z]+\.|[$])\s*,\s*\.METRE\.\s*\)")
_STEP_POINT_PATTERN = re.compile(
    r"CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*\(\s*([^)]+?)\s*\)\s*\)",
    re.MULTILINE | re.DOTALL,
)


def _load_openvsp():
    import openvsp as vsp  # type: ignore

    return vsp


def _bounds_from_extrema(mins: list[float], maxs: list[float]) -> Bounds3D:
    return Bounds3D(
        x_min=mins[0],
        x_max=maxs[0],
        y_min=mins[1],
        y_max=maxs[1],
        z_min=mins[2],
        z_max=maxs[2],
    )


def _bbox_for_entities(gmsh, dim_tags: list[tuple[int, int]]) -> Bounds3D | None:
    if not dim_tags:
        return None
    mins = [float("inf"), float("inf"), float("inf")]
    maxs = [float("-inf"), float("-inf"), float("-inf")]
    for dim, tag in dim_tags:
        x_min, y_min, z_min, x_max, y_max, z_max = gmsh.model.getBoundingBox(dim, tag)
        mins[0] = min(mins[0], float(x_min))
        mins[1] = min(mins[1], float(y_min))
        mins[2] = min(mins[2], float(z_min))
        maxs[0] = max(maxs[0], float(x_max))
        maxs[1] = max(maxs[1], float(y_max))
        maxs[2] = max(maxs[2], float(z_max))
    return _bounds_from_extrema(mins, maxs)


def _read_step_units_and_bounds(path: Path) -> tuple[str | None, Bounds3D | None]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    units = None
    match = _STEP_UNIT_PATTERN.search(text)
    if match is not None:
        prefix = match.group(1)
        if prefix in {".UNSET.", "$"}:
            units = "m"
        elif prefix == ".MILLI.":
            units = "mm"

    mins = [float("inf"), float("inf"), float("inf")]
    maxs = [float("-inf"), float("-inf"), float("-inf")]
    point_count = 0
    for raw_values in _STEP_POINT_PATTERN.findall(text):
        values = [part.strip() for part in raw_values.split(",")]
        if len(values) != 3:
            continue
        try:
            coords = [float(value) for value in values]
        except ValueError:
            continue
        point_count += 1
        mins[0] = min(mins[0], coords[0])
        mins[1] = min(mins[1], coords[1])
        mins[2] = min(mins[2], coords[2])
        maxs[0] = max(maxs[0], coords[0])
        maxs[1] = max(maxs[1], coords[1])
        maxs[2] = max(maxs[2], coords[2])

    bounds = _bounds_from_extrema(mins, maxs) if point_count else None
    return units, bounds


def _infer_import_scale(
    normalized_bounds: Bounds3D | None,
    import_bounds: Bounds3D | None,
) -> float | None:
    if normalized_bounds is None or import_bounds is None:
        return None

    ratios: list[float] = []
    spans = (
        (normalized_bounds.x_max - normalized_bounds.x_min, import_bounds.x_max - import_bounds.x_min),
        (normalized_bounds.y_max - normalized_bounds.y_min, import_bounds.y_max - import_bounds.y_min),
        (normalized_bounds.z_max - normalized_bounds.z_min, import_bounds.z_max - import_bounds.z_min),
    )
    for normalized_span, import_span in spans:
        if normalized_span <= 1e-12 or import_span <= 1e-12:
            continue
        ratios.append(normalized_span / import_span)

    if not ratios:
        return None

    scale = sum(ratios) / len(ratios)
    tolerance = max(abs(scale) * 0.02, 1e-9)
    if any(abs(ratio - scale) > tolerance for ratio in ratios):
        return None
    if not math.isfinite(scale) or scale <= 0.0:
        return None
    if abs(scale - 1.0) <= _IMPORT_SCALE_IDENTITY_TOL:
        return 1.0
    return scale


def _probe_step_topology(path: Path, staging_dir: Path) -> GeometryTopologyMetadata:
    declared_units, step_bounds = _read_step_units_and_bounds(path)
    notes: list[str] = []
    if step_bounds is None:
        notes.append("step_cartesian_bounds_unavailable")

    try:
        gmsh = load_gmsh()
    except GmshRuntimeError:
        return GeometryTopologyMetadata(
            representation="brep_trimmed_step",
            source_kind=path.suffix.lstrip(".") or "unknown",
            units=declared_units,
            bounds=step_bounds,
            notes=["gmsh_python_api_not_available_for_topology_probe"],
        )

    gmsh_initialized = False
    try:
        gmsh.initialize()
        gmsh_initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(f"probe_{uuid.uuid4().hex}")
        imported_entities = gmsh.model.occ.importShapes(str(path))
        gmsh.model.occ.synchronize()
        volume_entities = [entity for entity in imported_entities if entity[0] == 3]
        if not volume_entities:
            volume_entities = gmsh.model.getEntities(3)
        surface_entities = gmsh.model.getEntities(2)
        import_bounds = _bbox_for_entities(gmsh, volume_entities or surface_entities)
        import_scale = _infer_import_scale(step_bounds, import_bounds)
        backend_rescale_required = bool(
            import_scale is not None and abs(import_scale - 1.0) > _IMPORT_SCALE_IDENTITY_TOL
        )
        if backend_rescale_required:
            notes.append(
                f"gmsh_occ_import_requires_rescale_to_declared_units:scale={import_scale:.12g}"
            )
        return GeometryTopologyMetadata(
            representation="brep_trimmed_step",
            source_kind=path.suffix.lstrip(".") or "unknown",
            units=declared_units,
            bounds=step_bounds,
            import_bounds=import_bounds,
            import_scale_to_units=import_scale,
            backend_rescale_required=backend_rescale_required,
            body_count=len(volume_entities),
            surface_count=len(surface_entities),
            volume_count=len(volume_entities),
            labels_present=True,
            label_schema="preserve_component_labels",
            notes=notes,
        )
    except Exception as exc:
        return GeometryTopologyMetadata(
            representation="brep_trimmed_step",
            source_kind=path.suffix.lstrip(".") or "unknown",
            units=declared_units,
            bounds=step_bounds,
            notes=[*notes, f"gmsh_probe_error={exc}"],
        )
    finally:
        if gmsh_initialized:
            gmsh.finalize()


def _apply_units_hint(vsp, request: GeometryProviderRequest) -> None:
    if request.units_hint == "auto":
        return
    enum_name = _LEN_UNIT_MAP.get(request.units_hint)
    if enum_name is None:
        return
    vsp.SetIntAnalysisInput(
        "SurfaceIntersection",
        "CADLenUnit",
        (getattr(vsp, enum_name),),
    )


def materialize(request: GeometryProviderRequest) -> GeometryProviderResult:
    request.staging_dir.mkdir(parents=True, exist_ok=True)
    normalized_path = request.staging_dir / "normalized.stp"
    topology_report = request.staging_dir / "topology.json"
    provider_log = request.staging_dir / "provider_log.json"

    vsp = _load_openvsp()
    vsp.ClearVSPModel()
    vsp.ReadVSPFile(str(request.source_path))
    vsp.Update()
    vsp.SetAnalysisInputDefaults("SurfaceIntersection")
    vsp.SetIntAnalysisInput("SurfaceIntersection", "STEPFileFlag", (1,))
    vsp.SetStringAnalysisInput(
        "SurfaceIntersection",
        "STEPFileName",
        (str(normalized_path),),
    )
    vsp.SetIntAnalysisInput("SurfaceIntersection", "IGESFileFlag", (0,))
    vsp.SetIntAnalysisInput("SurfaceIntersection", "P3DFileFlag", (0,))
    vsp.SetIntAnalysisInput("SurfaceIntersection", "SRFFileFlag", (0,))
    vsp.SetIntAnalysisInput("SurfaceIntersection", "CURVFileFlag", (0,))
    _apply_units_hint(vsp, request)
    analysis_result = vsp.ExecAnalysis("SurfaceIntersection")

    topology = _probe_step_topology(normalized_path, request.staging_dir)
    reference_geometry = load_openvsp_reference_data(request.source_path)
    if request.units_hint != "auto":
        if topology.units is None:
            topology.units = request.units_hint
            topology.notes.append(f"units_fallback_from_request={request.units_hint}")
        elif topology.units != request.units_hint:
            topology.notes.append(
                f"units_hint_mismatch:request={request.units_hint},step={topology.units}"
            )

    topology_report.write_text(
        json.dumps(topology.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    provider_log.write_text(
        json.dumps(
            {
                "provider": "openvsp_surface_intersection",
                "provider_stage": "v1",
                "analysis": "SurfaceIntersection",
                "analysis_result": analysis_result,
                "source_path": str(request.source_path),
                "normalized_geometry_path": str(normalized_path),
                    "target_representation": request.target_representation,
                    "units_hint": request.units_hint,
                    "label_policy": request.label_policy,
                    "topology": topology.model_dump(mode="json"),
                    "reference_geometry": reference_geometry,
                },
                ensure_ascii=False,
                indent=2,
            ),
        encoding="utf-8",
    )

    return GeometryProviderResult(
        provider="openvsp_surface_intersection",
        provider_stage="v1",
        status="materialized",
        geometry_source="provider_generated",
        source_path=request.source_path,
        normalized_geometry_path=normalized_path,
        geometry_family_hint=request.geometry_family_hint,
        provider_version="openvsp-runtime",
        topology=topology,
        artifacts={
            "normalized_geometry": normalized_path,
            "topology_report": topology_report,
            "provider_log": provider_log,
        },
        provenance={
            "analysis": "SurfaceIntersection",
            "analysis_result": analysis_result,
            "target_representation": request.target_representation,
            "label_policy": request.label_policy,
            "topology": topology.model_dump(mode="json"),
            "reference_geometry": reference_geometry,
        },
        notes=[
            "normalized via OpenVSP SurfaceIntersection trimmed STEP export",
            "normalized geometry contract expects downstream lengths in topology.units",
        ],
    )
