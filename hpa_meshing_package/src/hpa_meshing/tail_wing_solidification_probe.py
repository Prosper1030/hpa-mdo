from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field

from .gmsh_runtime import GmshRuntimeError, load_gmsh
from .pipeline import validate_geometry_only
from .schema import MeshJobConfig
from .tail_wing_surface_mesh_probe import (
    _bbox_payload,
    _default_source_path,
    _fixture_kind,
    _json_write,
    _provider_payload,
    _text_write,
    _topology_payload,
)


SolidificationStatusType = Literal[
    "solidified",
    "no_volume_created",
    "geometry_unavailable",
    "unavailable",
]
ProviderStatusType = Literal["materialized", "failed", "not_materialized", "unavailable"]


class TailWingSolidificationAttempt(BaseModel):
    attempt_id: str
    tolerance: float
    sew_faces: bool
    make_solids: bool
    fix_small_edges: bool
    input_surface_count: int | None = None
    input_volume_count: int | None = None
    output_surface_count: int | None = None
    output_volume_count: int | None = None
    healed_entity_count: int | None = None
    error: str | None = None


class TailWingSolidificationProbeReport(BaseModel):
    schema_version: Literal["tail_wing_solidification_probe.v1"] = (
        "tail_wing_solidification_probe.v1"
    )
    component: Literal["tail_wing"] = "tail_wing"
    source_fixture: Literal["blackcat_004_origin_vsp3", "custom_vsp3"] = (
        "blackcat_004_origin_vsp3"
    )
    geometry_provider: Literal["esp_rebuilt"] = "esp_rebuilt"
    geometry_family: Literal["thin_sheet_lifting_surface"] = "thin_sheet_lifting_surface"
    execution_mode: Literal["real_provider_gmsh_heal_solidification_probe_no_su2"] = (
        "real_provider_gmsh_heal_solidification_probe_no_su2"
    )
    source_path: str
    case_dir: str
    no_su2_execution: bool = True
    no_bl_runtime: bool = True
    production_default_changed: bool = False
    solidification_status: SolidificationStatusType
    provider_status: ProviderStatusType
    provider_surface_count: int | None = None
    provider_body_count: int | None = None
    provider_volume_count: int | None = None
    best_output_surface_count: int | None = None
    best_output_volume_count: int | None = None
    normalized_geometry_path: str | None = None
    solidification_metadata_path: str | None = None
    gmsh_log_path: str | None = None
    recommended_next: Literal[
        "explicit_caps_or_baffle_volume_route_required",
        "solidification_candidate_available_for_volume_route",
        "not_evaluated",
    ] = "not_evaluated"
    attempts: List[TailWingSolidificationAttempt] = Field(default_factory=list)
    hpa_mdo_guarantees: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    error: str | None = None


def _provider_status_value(raw: Any) -> ProviderStatusType:
    if raw in {"materialized", "failed", "not_materialized"}:
        return raw
    return "unavailable"


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _heal_attempt_specs() -> list[dict[str, Any]]:
    return [
        {"tolerance": 1.0e-6, "fix_small_edges": True},
        {"tolerance": 1.0e-5, "fix_small_edges": True},
        {"tolerance": 1.0e-4, "fix_small_edges": True},
        {"tolerance": 1.0e-6, "fix_small_edges": False},
        {"tolerance": 1.0e-5, "fix_small_edges": False},
        {"tolerance": 1.0e-4, "fix_small_edges": False},
    ]


def _attempt_solidification(
    *,
    normalized_geometry_path: Path,
    out_dir: Path,
    topology: dict[str, Any],
) -> Dict[str, Any]:
    try:
        gmsh = load_gmsh()
    except GmshRuntimeError as exc:
        raise RuntimeError(str(exc)) from exc

    solidification_dir = out_dir / "artifacts" / "solidification"
    solidification_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = solidification_dir / "solidification_metadata.json"
    gmsh_log_path = solidification_dir / "gmsh_log.txt"
    gmsh_initialized = False
    gmsh_logger_started = False
    attempts: list[dict[str, Any]] = []
    best_attempt: dict[str, Any] | None = None

    try:
        gmsh.initialize()
        gmsh_initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("tail_wing_solidification_probe")
        gmsh.logger.start()
        gmsh_logger_started = True

        for index, spec in enumerate(_heal_attempt_specs(), start=1):
            if index > 1:
                gmsh.clear()
                gmsh.model.add(f"tail_wing_solidification_probe_{index}")
            attempt: dict[str, Any] = {
                "attempt_id": f"gmsh_heal_make_solids_{index}",
                "tolerance": float(spec["tolerance"]),
                "sew_faces": True,
                "make_solids": True,
                "fix_small_edges": bool(spec["fix_small_edges"]),
            }
            try:
                imported_entities = gmsh.model.occ.importShapes(str(normalized_geometry_path))
                gmsh.model.occ.synchronize()
                import_scale = topology.get("import_scale_to_units")
                scale = (
                    float(import_scale)
                    if isinstance(import_scale, (int, float)) and import_scale > 0
                    else 1.0
                )
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
                input_surfaces = gmsh.model.getEntities(2)
                input_volumes = gmsh.model.getEntities(3)
                healed = gmsh.model.occ.healShapes(
                    imported_entities or input_surfaces,
                    tolerance=float(spec["tolerance"]),
                    fixDegenerated=True,
                    fixSmallEdges=bool(spec["fix_small_edges"]),
                    fixSmallFaces=True,
                    sewFaces=True,
                    makeSolids=True,
                )
                gmsh.model.occ.removeAllDuplicates()
                gmsh.model.occ.synchronize()
                output_surfaces = gmsh.model.getEntities(2)
                output_volumes = gmsh.model.getEntities(3)
                attempt.update(
                    {
                        "input_surface_count": len(input_surfaces),
                        "input_volume_count": len(input_volumes),
                        "output_surface_count": len(output_surfaces),
                        "output_volume_count": len(output_volumes),
                        "healed_entity_count": len(healed),
                    }
                )
                if best_attempt is None or int(attempt["output_volume_count"]) > int(
                    best_attempt.get("output_volume_count", 0) or 0
                ):
                    best_attempt = dict(attempt)
            except Exception as exc:
                attempt["error"] = str(exc)
            attempts.append(attempt)

        best_output_volume_count = int(best_attempt.get("output_volume_count", 0)) if best_attempt else 0
        metadata = {
            "schema_version": "tail_wing_solidification_probe_metadata.v1",
            "status": "solidified" if best_output_volume_count > 0 else "no_volume_created",
            "normalized_geometry_path": str(normalized_geometry_path),
            "provider_topology": topology,
            "attempts": attempts,
            "best_attempt": best_attempt,
            "surface_bounds": (
                _bbox_payload(gmsh, gmsh.model.getEntities(2))
                if best_attempt is not None
                else None
            ),
            "artifacts": {
                "solidification_metadata": str(metadata_path),
                "gmsh_log": str(gmsh_log_path),
            },
        }
        _json_write(metadata_path, metadata)
        return metadata
    except Exception as exc:
        metadata = {
            "schema_version": "tail_wing_solidification_probe_metadata.v1",
            "status": "failed",
            "error": str(exc),
            "normalized_geometry_path": str(normalized_geometry_path),
            "attempts": attempts,
            "best_attempt": best_attempt,
            "artifacts": {
                "solidification_metadata": str(metadata_path),
                "gmsh_log": str(gmsh_log_path),
            },
        }
        _json_write(metadata_path, metadata)
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


def build_tail_wing_solidification_probe_report(
    out_dir: Path,
    source_path: Path | None = None,
) -> TailWingSolidificationProbeReport:
    out_dir.mkdir(parents=True, exist_ok=True)
    source = _default_source_path() if source_path is None else source_path
    if not source.exists():
        return TailWingSolidificationProbeReport(
            source_fixture=_fixture_kind(source),
            source_path=str(source),
            case_dir=str(out_dir),
            solidification_status="unavailable",
            provider_status="unavailable",
            recommended_next="not_evaluated",
            blocking_reasons=[
                "tail_wing_source_vsp3_missing",
                "tail_solidification_probe_not_evaluated",
            ],
            limitations=[
                "The source VSP3 file was not available, so the solidification probe was not evaluated.",
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
    if geometry_result.get("status") != "success" or not isinstance(normalized_geometry, str):
        return TailWingSolidificationProbeReport(
            source_fixture=_fixture_kind(source),
            source_path=str(source),
            case_dir=str(out_dir),
            solidification_status="geometry_unavailable",
            provider_status=provider_status,
            provider_surface_count=_int_or_none(topology.get("surface_count")),
            provider_body_count=_int_or_none(topology.get("body_count")),
            provider_volume_count=_int_or_none(topology.get("volume_count")),
            recommended_next="not_evaluated",
            blocking_reasons=[
                "tail_esp_rebuilt_geometry_not_available_for_solidification_probe",
                "tail_volume_handoff_not_available",
            ],
            limitations=[
                "mesh_handoff.v1 is not emitted by the solidification probe.",
                "SU2_CFD was not executed.",
            ],
            error=str(geometry_result.get("failure_code") or geometry_result.get("error")),
        )

    solidification = _attempt_solidification(
        normalized_geometry_path=Path(normalized_geometry),
        out_dir=out_dir,
        topology=topology,
    )
    attempts = [
        TailWingSolidificationAttempt.model_validate(attempt)
        for attempt in solidification.get("attempts", [])
        if isinstance(attempt, dict)
    ]
    best_attempt = (
        solidification.get("best_attempt")
        if isinstance(solidification.get("best_attempt"), dict)
        else {}
    )
    best_output_volume_count = _int_or_none(best_attempt.get("output_volume_count")) or 0
    status: SolidificationStatusType = (
        "solidified"
        if best_output_volume_count > 0
        else "no_volume_created"
        if solidification.get("status") in {"solidified", "no_volume_created"}
        else "unavailable"
    )
    recommended_next = (
        "solidification_candidate_available_for_volume_route"
        if status == "solidified"
        else "explicit_caps_or_baffle_volume_route_required"
    )
    blocking_reasons = [
        "tail_surface_only_mesh_not_su2_volume_handoff",
        "tail_wing_solver_not_run",
        "convergence_gate_not_run",
    ]
    if status == "no_volume_created":
        blocking_reasons.insert(0, "tail_naive_gmsh_heal_solidification_no_volume")

    return TailWingSolidificationProbeReport(
        source_fixture=_fixture_kind(source),
        source_path=str(source),
        case_dir=str(out_dir / "artifacts" / "solidification"),
        solidification_status=status,
        provider_status=provider_status,
        provider_surface_count=_int_or_none(topology.get("surface_count")),
        provider_body_count=_int_or_none(topology.get("body_count")),
        provider_volume_count=_int_or_none(topology.get("volume_count")),
        best_output_surface_count=_int_or_none(best_attempt.get("output_surface_count")),
        best_output_volume_count=best_output_volume_count,
        normalized_geometry_path=normalized_geometry,
        solidification_metadata_path=(
            solidification.get("artifacts", {}).get("solidification_metadata")
            if isinstance(solidification.get("artifacts"), dict)
            else None
        ),
        gmsh_log_path=(
            solidification.get("artifacts", {}).get("gmsh_log")
            if isinstance(solidification.get("artifacts"), dict)
            else None
        ),
        recommended_next=recommended_next,
        attempts=attempts,
        hpa_mdo_guarantees=[
            "real_vsp3_source_consumed",
            "esp_rebuilt_tail_wing_geometry_materialized",
            "naive_gmsh_heal_make_solids_attempted",
            "mesh_handoff_not_emitted",
            "su2_volume_handoff_not_claimed",
            "production_default_unchanged",
        ],
        blocking_reasons=blocking_reasons,
        limitations=[
            "mesh_handoff.v1 is not emitted by the solidification probe.",
            "No farfield subtraction or volume mesh is attempted in this probe.",
            "Gmsh heal/sew/makeSolids is evidence only; it is not a production repair policy.",
            "SU2_CFD was not executed.",
            "convergence_gate.v1 was not emitted.",
        ],
        error=(
            solidification.get("error")
            if isinstance(solidification.get("error"), str)
            else None
        ),
    )


def _render_markdown(report: TailWingSolidificationProbeReport) -> str:
    lines = [
        "# tail_wing solidification probe v1",
        "",
        "This probe checks whether naive Gmsh heal/sew/makeSolids can turn the real ESP tail surfaces into OCC volumes.",
        "",
        f"- solidification_status: `{report.solidification_status}`",
        f"- provider_status: `{report.provider_status}`",
        f"- provider_surface_count: `{report.provider_surface_count}`",
        f"- provider_volume_count: `{report.provider_volume_count}`",
        f"- best_output_surface_count: `{report.best_output_surface_count}`",
        f"- best_output_volume_count: `{report.best_output_volume_count}`",
        f"- recommended_next: `{report.recommended_next}`",
        "",
        "## Blocking Reasons",
        "",
    ]
    lines.extend(f"- `{reason}`" for reason in report.blocking_reasons)
    lines.extend(["", "## Attempts", ""])
    for attempt in report.attempts:
        lines.append(
            "- "
            f"`{attempt.attempt_id}`: tolerance={attempt.tolerance}, "
            f"fix_small_edges={attempt.fix_small_edges}, "
            f"output_volume_count={attempt.output_volume_count}"
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    return "\n".join(lines).rstrip() + "\n"


def write_tail_wing_solidification_probe_report(
    out_dir: Path,
    report: TailWingSolidificationProbeReport | None = None,
    source_path: Path | None = None,
) -> Dict[str, Path]:
    if report is None:
        report = build_tail_wing_solidification_probe_report(
            out_dir,
            source_path=source_path,
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "tail_wing_solidification_probe.v1.json"
    markdown_path = out_dir / "tail_wing_solidification_probe.v1.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
