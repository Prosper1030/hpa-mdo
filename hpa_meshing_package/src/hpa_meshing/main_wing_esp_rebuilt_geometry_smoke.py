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


class MainWingESPRebuiltGeometrySmokeReport(BaseModel):
    schema_version: Literal["main_wing_esp_rebuilt_geometry_smoke.v1"] = (
        "main_wing_esp_rebuilt_geometry_smoke.v1"
    )
    component: Literal["main_wing"] = "main_wing"
    source_fixture: Literal["blackcat_004_origin_vsp3", "custom_vsp3"] = (
        "blackcat_004_origin_vsp3"
    )
    geometry_provider: Literal["esp_rebuilt"] = "esp_rebuilt"
    geometry_family: Literal["thin_sheet_lifting_surface"] = "thin_sheet_lifting_surface"
    execution_mode: Literal["provider_geometry_only_no_gmsh_no_su2"] = (
        "provider_geometry_only_no_gmsh_no_su2"
    )
    source_path: str
    case_dir: str
    no_gmsh_execution: bool = True
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
    component_selection_report_path: str | None = None
    component_input_model_path: str | None = None
    effective_component: str | None = None
    selected_geom_id: str | None = None
    selected_geom_name: str | None = None
    selected_geom_span_y: float | None = None
    selected_geom_chord_x: float | None = None
    body_count: int | None = None
    surface_count: int | None = None
    volume_count: int | None = None
    bounds: Dict[str, float] | None = None
    hpa_mdo_guarantees: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    error: str | None = None


def _default_source_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "blackcat_004_origin.vsp3"


def _fixture_kind(source: Path) -> Literal["blackcat_004_origin_vsp3", "custom_vsp3"]:
    return (
        "blackcat_004_origin_vsp3"
        if source.resolve() == _default_source_path().resolve()
        else "custom_vsp3"
    )


def _artifact_path(provider: dict[str, Any], key: str) -> str | None:
    artifacts = provider.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    value = artifacts.get(key)
    return value if isinstance(value, str) else None


def _selected_geom(selection: dict[str, Any]) -> dict[str, Any]:
    selected = selection.get("selected_geom")
    return selected if isinstance(selected, dict) else {}


def build_main_wing_esp_rebuilt_geometry_smoke_report(
    out_dir: Path,
    source_path: Path | None = None,
) -> MainWingESPRebuiltGeometrySmokeReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    source = _default_source_path() if source_path is None else source_path
    fixture_kind = _fixture_kind(source)
    if not source.exists():
        return MainWingESPRebuiltGeometrySmokeReport(
            source_fixture=fixture_kind,
            source_path=str(source),
            case_dir=str(out_dir),
            geometry_smoke_status="unavailable",
            provider_status="unavailable",
            validation_status="not_run",
            promotion_status="not_evaluated",
            blocking_reasons=[
                "main_wing_source_vsp3_missing",
                "main_wing_real_geometry_mesh_handoff_not_run",
            ],
            limitations=[
                "The source VSP3 file was not available, so provider geometry was not evaluated.",
            ],
        )

    validation_dir = out_dir / "artifacts" / "geometry_validation"
    try:
        result = validate_geometry_only(
            MeshJobConfig(
                component="main_wing",
                geometry=source,
                out_dir=validation_dir,
                geometry_provider="esp_rebuilt",
                geometry_family="thin_sheet_lifting_surface",
            )
        )
    except Exception as exc:
        return MainWingESPRebuiltGeometrySmokeReport(
            source_fixture=fixture_kind,
            source_path=str(source),
            case_dir=str(validation_dir),
            geometry_smoke_status="geometry_smoke_fail",
            provider_status="failed",
            validation_status="failed",
            blocking_reasons=[
                "main_wing_esp_rebuilt_geometry_smoke_failed",
                "main_wing_real_geometry_mesh_handoff_not_run",
            ],
            limitations=[
                "ESP rebuilt provider geometry failed before Gmsh or SU2 could be considered.",
            ],
            error=str(exc),
        )

    provider = result.get("provider") if isinstance(result.get("provider"), dict) else {}
    topology = provider.get("topology") if isinstance(provider.get("topology"), dict) else {}
    provenance = (
        provider.get("provenance") if isinstance(provider.get("provenance"), dict) else {}
    )
    selection = (
        provenance.get("component_selection")
        if isinstance(provenance.get("component_selection"), dict)
        else {}
    )
    selected = _selected_geom(selection)
    normalized_geometry_path = result.get("normalized_geometry")
    normalized_exists = (
        isinstance(normalized_geometry_path, str)
        and Path(normalized_geometry_path).exists()
    )
    surface_count = topology.get("surface_count")
    volume_count = topology.get("volume_count")
    pass_status = (
        result.get("status") == "success"
        and provider.get("status") == "materialized"
        and selection.get("effective_component") == "main_wing"
        and normalized_exists
        and isinstance(surface_count, int)
        and surface_count > 0
        and isinstance(volume_count, int)
        and volume_count > 0
    )

    return MainWingESPRebuiltGeometrySmokeReport(
        source_fixture=fixture_kind,
        source_path=str(source),
        case_dir=str(validation_dir),
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
        component_selection_report_path=_artifact_path(provider, "component_selection_report"),
        component_input_model_path=_artifact_path(provider, "component_input_model"),
        effective_component=(
            selection.get("effective_component")
            if isinstance(selection.get("effective_component"), str)
            else None
        ),
        selected_geom_id=(
            selected.get("geom_id") if isinstance(selected.get("geom_id"), str) else None
        ),
        selected_geom_name=(
            selected.get("name") if isinstance(selected.get("name"), str) else None
        ),
        selected_geom_span_y=(
            float(selected["span_y"]) if isinstance(selected.get("span_y"), (int, float)) else None
        ),
        selected_geom_chord_x=(
            float(selected["chord_x"]) if isinstance(selected.get("chord_x"), (int, float)) else None
        ),
        body_count=topology.get("body_count") if isinstance(topology.get("body_count"), int) else None,
        surface_count=surface_count if isinstance(surface_count, int) else None,
        volume_count=volume_count if isinstance(volume_count, int) else None,
        bounds=topology.get("bounds") if isinstance(topology.get("bounds"), dict) else None,
        hpa_mdo_guarantees=[
            "real_vsp3_source_consumed",
            "esp_rebuilt_main_wing_geometry_materialized",
            "main_wing_selected_from_vsp_source",
            "normalized_step_written",
            "no_gmsh_execution",
            "no_su2_execution",
            "production_default_unchanged",
        ]
        if pass_status
        else [
            "real_vsp3_source_consumed",
        ],
        blocking_reasons=[
            "main_wing_real_geometry_mesh_handoff_not_run",
            "main_wing_solver_not_run",
            "convergence_gate_not_run",
        ],
        limitations=[
            "This smoke materializes provider geometry only; it does not run Gmsh.",
            "mesh_handoff.v1 is not emitted for the real main-wing geometry.",
            "SU2_CFD was not executed.",
            "convergence_gate.v1 was not emitted.",
            "The normalized main-wing geometry is not solver credibility evidence by itself.",
            "Production defaults were not changed.",
        ],
    )


def _render_markdown(report: MainWingESPRebuiltGeometrySmokeReport) -> str:
    lines = [
        "# main_wing esp_rebuilt geometry smoke v1",
        "",
        "This is a provider-geometry smoke for the main-wing route.",
        "It validates VSP/ESP materialization without running Gmsh or SU2.",
        "",
        f"- component: `{report.component}`",
        f"- geometry_smoke_status: `{report.geometry_smoke_status}`",
        f"- provider_status: `{report.provider_status}`",
        f"- validation_status: `{report.validation_status}`",
        f"- effective_component: `{report.effective_component}`",
        f"- selected_geom_name: `{report.selected_geom_name}`",
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


def write_main_wing_esp_rebuilt_geometry_smoke_report(
    out_dir: Path,
    report: MainWingESPRebuiltGeometrySmokeReport | None = None,
    source_path: Path | None = None,
) -> Dict[str, Path]:
    if report is None:
        report = build_main_wing_esp_rebuilt_geometry_smoke_report(
            out_dir,
            source_path=source_path,
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "main_wing_esp_rebuilt_geometry_smoke.v1.json"
    markdown_path = out_dir / "main_wing_esp_rebuilt_geometry_smoke.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
