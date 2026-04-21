from pathlib import Path

from hpa_meshing.geometry.loader import load_geometry
from hpa_meshing.geometry.validator import (
    classify_geometry_family,
    validate_component_geometry,
)
from hpa_meshing.mesh.recipes import build_recipe
from hpa_meshing.schema import (
    GeometryHandle,
    GeometryProviderResult,
    GeometryTopologyMetadata,
    MeshJobConfig,
)


def _write_step(tmp_path: Path, name: str = "demo.step") -> Path:
    path = tmp_path / name
    path.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
    return path


def test_geometry_classifier_reports_explicit_family_and_source(tmp_path: Path):
    geometry = _write_step(tmp_path, "assembly.step")
    cfg = MeshJobConfig(
        component="aircraft_assembly",
        geometry=geometry,
        out_dir=tmp_path / "out",
        geometry_source="esp_rebuilt",
        geometry_family="thin_sheet_aircraft_assembly",
    )

    handle = load_geometry(cfg.geometry, cfg)
    classification = classify_geometry_family(handle, cfg)

    assert classification.geometry_source == "esp_rebuilt"
    assert classification.geometry_family == "thin_sheet_aircraft_assembly"
    assert classification.provenance == "config.geometry_family"


def test_validator_rejects_component_family_mismatch(tmp_path: Path):
    geometry = _write_step(tmp_path, "wing.step")
    cfg = MeshJobConfig(
        component="main_wing",
        geometry=geometry,
        out_dir=tmp_path / "out",
        geometry_family="closed_solid",
    )

    handle = load_geometry(cfg.geometry, cfg)
    classification = classify_geometry_family(handle, cfg)
    validation = validate_component_geometry(handle, classification, cfg)

    assert validation.ok is False
    assert validation.failure_code == "geometry_family_component_mismatch"


def test_recipe_dispatch_is_shared_by_family_not_component(tmp_path: Path):
    geometry = _write_step(tmp_path, "lifting_surface.step")

    wing_cfg = MeshJobConfig(
        component="main_wing",
        geometry=geometry,
        out_dir=tmp_path / "wing-out",
    )
    tail_cfg = MeshJobConfig(
        component="tail_wing",
        geometry=geometry,
        out_dir=tmp_path / "tail-out",
    )

    wing_recipe = build_recipe(
        load_geometry(wing_cfg.geometry, wing_cfg),
        classify_geometry_family(load_geometry(wing_cfg.geometry, wing_cfg), wing_cfg),
        wing_cfg,
    )
    tail_recipe = build_recipe(
        load_geometry(tail_cfg.geometry, tail_cfg),
        classify_geometry_family(load_geometry(tail_cfg.geometry, tail_cfg), tail_cfg),
        tail_cfg,
    )

    assert wing_recipe.geometry_family == "thin_sheet_lifting_surface"
    assert tail_recipe.geometry_family == "thin_sheet_lifting_surface"
    assert wing_recipe.meshing_route == "gmsh_thin_sheet_surface"
    assert tail_recipe.meshing_route == "gmsh_thin_sheet_surface"
    assert wing_recipe.backend_capability == "sheet_lifting_surface_meshing"
    assert tail_recipe.backend_capability == "sheet_lifting_surface_meshing"


def test_geometry_classifier_prefers_provider_family_hint(tmp_path: Path):
    source = tmp_path / "assembly.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    normalized = _write_step(tmp_path, "assembly_trimmed.stp")
    cfg = MeshJobConfig(
        component="aircraft_assembly",
        geometry=source,
        out_dir=tmp_path / "out",
        geometry_provider="openvsp_surface_intersection",
    )

    provider_result = GeometryProviderResult(
        provider="openvsp_surface_intersection",
        provider_stage="v1",
        status="materialized",
        geometry_source="provider_generated",
        source_path=source,
        normalized_geometry_path=normalized,
        geometry_family_hint="thin_sheet_aircraft_assembly",
        topology=GeometryTopologyMetadata(
            representation="brep_trimmed_step",
            source_kind="vsp3",
            units="m",
            body_count=3,
            surface_count=38,
            volume_count=3,
        ),
        provenance={"analysis": "SurfaceIntersection"},
    )
    handle = GeometryHandle(
        source_path=source,
        path=normalized,
        exists=True,
        suffix=normalized.suffix.lower(),
        loader="provider:openvsp_surface_intersection",
        geometry_source="provider_generated",
        component="aircraft_assembly",
        provider="openvsp_surface_intersection",
        provider_status="materialized",
        provider_result=provider_result,
    )

    classification = classify_geometry_family(handle, cfg)

    assert classification.geometry_family == "thin_sheet_aircraft_assembly"
    assert classification.provenance == "provider.geometry_family_hint"
