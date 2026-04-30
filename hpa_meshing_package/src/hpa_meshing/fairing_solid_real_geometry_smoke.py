from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from .pipeline import validate_geometry_only
from .schema import MeshJobConfig


GeometrySmokeStatusType = Literal["geometry_smoke_pass", "geometry_smoke_fail", "unavailable"]
ProviderStatusType = Literal["materialized", "not_materialized", "failed", "unavailable"]
ValidationStatusType = Literal["success", "failed", "not_run"]
HandoffStatusType = Literal["not_run"]
PromotionStatusType = Literal["blocked_before_real_geometry_mesh_handoff", "not_evaluated"]
GmshTopologyProbeStatusType = Literal["observed", "missing", "unavailable"]


class FairingSolidRealGeometrySmokeReport(BaseModel):
    schema_version: Literal["fairing_solid_real_geometry_smoke.v1"] = (
        "fairing_solid_real_geometry_smoke.v1"
    )
    component: Literal["fairing_solid"] = "fairing_solid"
    source_fixture: Literal["hpa_fairing_best_design_vsp3", "custom_vsp3"] = (
        "hpa_fairing_best_design_vsp3"
    )
    geometry_provider: Literal["openvsp_surface_intersection"] = "openvsp_surface_intersection"
    geometry_family: Literal["closed_solid"] = "closed_solid"
    execution_mode: Literal["provider_geometry_only_no_mesh_no_su2"] = (
        "provider_geometry_only_no_mesh_no_su2"
    )
    source_path: str
    case_dir: str
    no_gmsh_meshing_execution: bool = True
    gmsh_topology_probe_status: GmshTopologyProbeStatusType
    no_su2_execution: bool = True
    no_bl_runtime: bool = True
    production_default_changed: bool = False
    geometry_smoke_status: GeometrySmokeStatusType
    provider_status: ProviderStatusType
    validation_status: ValidationStatusType
    mesh_handoff_status: HandoffStatusType = "not_run"
    su2_handoff_status: HandoffStatusType = "not_run"
    convergence_gate_status: HandoffStatusType = "not_run"
    promotion_status: PromotionStatusType = "blocked_before_real_geometry_mesh_handoff"
    normalized_geometry_path: str | None = None
    topology_report_path: str | None = None
    provider_log_path: str | None = None
    selected_geom_id: str | None = None
    selected_geom_name: str | None = None
    selected_geom_type: str | None = None
    source_geom_count: int | None = None
    fairing_candidate_count: int | None = None
    body_count: int | None = None
    surface_count: int | None = None
    volume_count: int | None = None
    units: str | None = None
    bounds: Dict[str, float] | None = None
    import_bounds: Dict[str, float] | None = None
    import_scale_to_units: float | None = None
    backend_rescale_required: bool | None = None
    topology_notes: List[str] = Field(default_factory=list)
    hpa_mdo_guarantees: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    error: str | None = None


def _load_openvsp():
    import openvsp as vsp  # type: ignore

    return vsp


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


def _artifact_path(provider: dict[str, Any], key: str) -> str | None:
    artifacts = provider.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    value = artifacts.get(key)
    return value if isinstance(value, str) else None


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _float_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _is_fairing_candidate(geom: dict[str, str]) -> bool:
    name = geom.get("name", "").lower()
    type_name = geom.get("type_name", "").lower()
    return (
        type_name == "fuselage"
        or "fairing" in name
        or "fuselage" in name
        or name == "best_design"
    )


def _inspect_openvsp_geometries(source: Path) -> dict[str, Any]:
    vsp = _load_openvsp()
    vsp.ClearVSPModel()
    vsp.ReadVSPFile(str(source))
    if hasattr(vsp, "Update"):
        vsp.Update()

    geometries: list[dict[str, str]] = []
    for geom_id in list(vsp.FindGeoms()):
        geometries.append(
            {
                "geom_id": str(geom_id),
                "name": str(vsp.GetGeomName(geom_id) or ""),
                "type_name": str(vsp.GetGeomTypeName(geom_id) or ""),
            }
        )

    candidates = [geom for geom in geometries if _is_fairing_candidate(geom)]
    selected = next(
        (geom for geom in candidates if geom.get("type_name", "").lower() == "fuselage"),
        candidates[0] if candidates else None,
    )
    return {
        "geometries": geometries,
        "selected_geom": selected,
        "fairing_candidate_count": len(candidates),
    }


def _topology_probe_status(topology: dict[str, Any]) -> GmshTopologyProbeStatusType:
    if not topology:
        return "unavailable"
    if all(isinstance(topology.get(key), int) for key in ("body_count", "surface_count", "volume_count")):
        return "observed"
    return "missing"


def _bounds_dict(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    bounds: dict[str, float] = {}
    for key, raw in value.items():
        if not isinstance(raw, (int, float)):
            return None
        bounds[str(key)] = float(raw)
    return bounds


def _pass_status(
    *,
    result: dict[str, Any],
    provider: dict[str, Any],
    topology: dict[str, Any],
    selected_geom: dict[str, Any] | None,
    normalized_geometry_path: str | None,
) -> bool:
    normalized_exists = (
        isinstance(normalized_geometry_path, str)
        and Path(normalized_geometry_path).exists()
    )
    return (
        result.get("status") == "success"
        and provider.get("status") == "materialized"
        and selected_geom is not None
        and selected_geom.get("type_name") == "Fuselage"
        and normalized_exists
        and isinstance(topology.get("body_count"), int)
        and topology["body_count"] > 0
        and isinstance(topology.get("surface_count"), int)
        and topology["surface_count"] > 0
        and isinstance(topology.get("volume_count"), int)
        and topology["volume_count"] > 0
    )


def _blocking_reasons_for_failure(
    *,
    provider: dict[str, Any],
    topology: dict[str, Any],
    selected_geom: dict[str, Any] | None,
) -> list[str]:
    reasons: list[str] = []
    if selected_geom is None:
        reasons.append("fairing_real_geometry_candidate_missing")
    if provider.get("status") != "materialized":
        reasons.append("fairing_surface_intersection_provider_not_materialized")
    if not (
        isinstance(topology.get("volume_count"), int)
        and topology.get("volume_count", 0) > 0
    ):
        reasons.append("fairing_closed_solid_topology_missing")
    reasons.extend(
        [
            "fairing_real_geometry_mesh_handoff_not_run",
            "fairing_solver_not_run",
            "convergence_gate_not_run",
        ]
    )
    return reasons


def build_fairing_solid_real_geometry_smoke_report(
    out_dir: Path,
    source_path: Path | None = None,
) -> FairingSolidRealGeometrySmokeReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    source = _default_source_path() if source_path is None else source_path
    fixture_kind = _fixture_kind(source)
    if not source.exists():
        return FairingSolidRealGeometrySmokeReport(
            source_fixture=fixture_kind,
            source_path=str(source),
            case_dir=str(out_dir),
            gmsh_topology_probe_status="unavailable",
            geometry_smoke_status="unavailable",
            provider_status="unavailable",
            validation_status="not_run",
            promotion_status="not_evaluated",
            blocking_reasons=[
                "fairing_real_source_vsp3_missing",
                "fairing_real_geometry_mesh_handoff_not_run",
            ],
            limitations=[
                "The fairing VSP3 source file was not available, so provider geometry was not evaluated.",
            ],
        )

    try:
        inventory = _inspect_openvsp_geometries(source)
    except Exception as exc:
        return FairingSolidRealGeometrySmokeReport(
            source_fixture=fixture_kind,
            source_path=str(source),
            case_dir=str(out_dir),
            gmsh_topology_probe_status="unavailable",
            geometry_smoke_status="geometry_smoke_fail",
            provider_status="unavailable",
            validation_status="not_run",
            promotion_status="not_evaluated",
            blocking_reasons=[
                "fairing_real_geometry_inventory_failed",
                "fairing_real_geometry_mesh_handoff_not_run",
            ],
            limitations=[
                "OpenVSP geometry inventory failed before provider materialization could be evaluated.",
            ],
            error=str(exc),
        )

    validation_dir = out_dir / "artifacts" / "geometry_validation"
    try:
        result = validate_geometry_only(
            MeshJobConfig(
                component="fairing_solid",
                geometry=source,
                out_dir=validation_dir,
                geometry_provider="openvsp_surface_intersection",
                geometry_family="closed_solid",
            )
        )
    except Exception as exc:
        selected_geom = _dict_or_none(inventory.get("selected_geom"))
        return FairingSolidRealGeometrySmokeReport(
            source_fixture=fixture_kind,
            source_path=str(source),
            case_dir=str(validation_dir),
            gmsh_topology_probe_status="unavailable",
            geometry_smoke_status="geometry_smoke_fail",
            provider_status="failed",
            validation_status="failed",
            selected_geom_id=(
                selected_geom.get("geom_id") if selected_geom is not None else None
            ),
            selected_geom_name=(
                selected_geom.get("name") if selected_geom is not None else None
            ),
            selected_geom_type=(
                selected_geom.get("type_name") if selected_geom is not None else None
            ),
            source_geom_count=len(inventory.get("geometries", [])),
            fairing_candidate_count=_int_or_none(inventory.get("fairing_candidate_count")),
            blocking_reasons=[
                "fairing_surface_intersection_provider_failed",
                "fairing_real_geometry_mesh_handoff_not_run",
            ],
            limitations=[
                "OpenVSP SurfaceIntersection failed before real fairing mesh handoff could be considered.",
            ],
            error=str(exc),
        )

    provider = result.get("provider") if isinstance(result.get("provider"), dict) else {}
    topology = provider.get("topology") if isinstance(provider.get("topology"), dict) else {}
    selected_geom = _dict_or_none(inventory.get("selected_geom"))
    normalized_geometry_path = result.get("normalized_geometry")
    pass_status = _pass_status(
        result=result,
        provider=provider,
        topology=topology,
        selected_geom=selected_geom,
        normalized_geometry_path=(
            normalized_geometry_path if isinstance(normalized_geometry_path, str) else None
        ),
    )
    topology_probe_status = _topology_probe_status(topology)
    blocking_reasons = (
        [
            "fairing_real_geometry_mesh_handoff_not_run",
            "fairing_solver_not_run",
            "convergence_gate_not_run",
        ]
        if pass_status
        else _blocking_reasons_for_failure(
            provider=provider,
            topology=topology,
            selected_geom=selected_geom,
        )
    )

    return FairingSolidRealGeometrySmokeReport(
        source_fixture=fixture_kind,
        source_path=str(source),
        case_dir=str(validation_dir),
        gmsh_topology_probe_status=topology_probe_status,
        geometry_smoke_status="geometry_smoke_pass" if pass_status else "geometry_smoke_fail",
        provider_status=(
            provider.get("status")
            if provider.get("status") in {"materialized", "failed"}
            else "unavailable"
        ),
        validation_status=(
            result.get("status") if result.get("status") in {"success", "failed"} else "not_run"
        ),
        normalized_geometry_path=(
            normalized_geometry_path if isinstance(normalized_geometry_path, str) else None
        ),
        topology_report_path=_artifact_path(provider, "topology_report"),
        provider_log_path=_artifact_path(provider, "provider_log"),
        selected_geom_id=(
            selected_geom.get("geom_id") if selected_geom is not None else None
        ),
        selected_geom_name=(
            selected_geom.get("name") if selected_geom is not None else None
        ),
        selected_geom_type=(
            selected_geom.get("type_name") if selected_geom is not None else None
        ),
        source_geom_count=len(inventory.get("geometries", [])),
        fairing_candidate_count=_int_or_none(inventory.get("fairing_candidate_count")),
        body_count=_int_or_none(topology.get("body_count")),
        surface_count=_int_or_none(topology.get("surface_count")),
        volume_count=_int_or_none(topology.get("volume_count")),
        units=topology.get("units") if isinstance(topology.get("units"), str) else None,
        bounds=_bounds_dict(topology.get("bounds")),
        import_bounds=_bounds_dict(topology.get("import_bounds")),
        import_scale_to_units=_float_or_none(topology.get("import_scale_to_units")),
        backend_rescale_required=_bool_or_none(topology.get("backend_rescale_required")),
        topology_notes=(
            list(topology.get("notes"))
            if isinstance(topology.get("notes"), list)
            else []
        ),
        hpa_mdo_guarantees=[
            "real_fairing_vsp3_source_consumed",
            "openvsp_fuselage_fairing_selected",
            "openvsp_surface_intersection_fairing_step_materialized",
            "fairing_closed_solid_topology_observed",
            "no_gmsh_meshing_execution",
            "no_su2_execution",
            "production_default_unchanged",
        ]
        if pass_status
        else [
            "real_fairing_vsp3_source_consumed",
        ],
        blocking_reasons=blocking_reasons,
        limitations=[
            "This smoke materializes provider geometry only; it does not run Gmsh meshing.",
            "The provider may use Gmsh OCC import only as a topology probe.",
            "mesh_handoff.v1 is not emitted for the real fairing geometry.",
            "SU2_CFD was not executed.",
            "convergence_gate.v1 was not emitted.",
            "The normalized fairing geometry is not solver credibility evidence by itself.",
            "Production defaults were not changed.",
        ],
    )


def _render_markdown(report: FairingSolidRealGeometrySmokeReport) -> str:
    lines = [
        "# fairing_solid real geometry smoke v1",
        "",
        "This is a provider-geometry smoke for the real fairing route.",
        "It validates VSP materialization without running Gmsh meshing or SU2.",
        "",
        f"- component: `{report.component}`",
        f"- geometry_smoke_status: `{report.geometry_smoke_status}`",
        f"- provider_status: `{report.provider_status}`",
        f"- validation_status: `{report.validation_status}`",
        f"- geometry_provider: `{report.geometry_provider}`",
        f"- selected_geom_name: `{report.selected_geom_name}`",
        f"- selected_geom_type: `{report.selected_geom_type}`",
        f"- gmsh_topology_probe_status: `{report.gmsh_topology_probe_status}`",
        f"- body_count: `{report.body_count}`",
        f"- surface_count: `{report.surface_count}`",
        f"- volume_count: `{report.volume_count}`",
        f"- mesh_handoff_status: `{report.mesh_handoff_status}`",
        f"- su2_handoff_status: `{report.su2_handoff_status}`",
        "",
        "## Blocking Reasons",
        "",
    ]
    lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_fairing_solid_real_geometry_smoke_report(
    out_dir: Path,
    report: FairingSolidRealGeometrySmokeReport | None = None,
    source_path: Path | None = None,
) -> Dict[str, Path]:
    if report is None:
        report = build_fairing_solid_real_geometry_smoke_report(
            out_dir,
            source_path=source_path,
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "fairing_solid_real_geometry_smoke.v1.json"
    markdown_path = out_dir / "fairing_solid_real_geometry_smoke.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
