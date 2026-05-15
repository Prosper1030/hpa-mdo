from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_wo006_structured_hexa_verification.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "run_wo006_structured_hexa_verification",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_artificial_rectangular_wing_generates_all_hex_closed_shell() -> None:
    module = _load_module()

    geometry = module.build_artificial_rectangular_wing_geometry(
        n_span=4,
        n_perimeter=16,
    )
    surface = module.build_structured_body_surface(geometry)
    config = module.StructuredHexaConfig(
        case_id="unit",
        n_span=4,
        n_perimeter=16,
        radial_layers=4,
        near_wall_layers=2,
        first_layer_height_m=5.0e-5,
        near_wall_growth=1.2,
        farfield_chords=3.0,
        normal_smoothing_iterations=1,
    )

    mesh = module.build_structured_hexa_mesh(surface, config, cref_m=1.0)
    quality = module.audit_structured_hexa_mesh(mesh)

    assert mesh.cell_count == len(surface.faces) * config.radial_layers
    assert quality["status"] == "pass"
    assert quality["cell_type_counts"] == {"hex": mesh.cell_count}
    assert quality["non_positive_volume_count"] == 0
    assert quality["missing_boundary_patch_count"] == 0
    assert quality["nonmanifold_face_count"] == 0
    assert quality["first_layer_height_m"] == config.first_layer_height_m
    assert mesh.boundary_face_counts["wing_upper"] > 0
    assert mesh.boundary_face_counts["wing_lower"] > 0
    assert mesh.boundary_face_counts["tip_left"] > 0
    assert mesh.boundary_face_counts["tip_right"] > 0
    assert mesh.boundary_face_counts["farfield"] == len(surface.faces)


def test_poly_mesh_writer_preserves_patch_order_and_owner_counts(tmp_path: Path) -> None:
    module = _load_module()
    geometry = module.build_artificial_rectangular_wing_geometry(
        n_span=2,
        n_perimeter=16,
    )
    surface = module.build_structured_body_surface(geometry)
    config = module.StructuredHexaConfig(
        case_id="unit",
        n_span=2,
        n_perimeter=16,
        radial_layers=2,
        near_wall_layers=1,
        first_layer_height_m=5.0e-5,
        near_wall_growth=1.2,
        farfield_chords=2.0,
        normal_smoothing_iterations=0,
    )
    mesh = module.build_structured_hexa_mesh(surface, config, cref_m=1.0)

    module.write_openfoam_poly_mesh(tmp_path / "constant" / "polyMesh", mesh)

    boundary = (tmp_path / "constant" / "polyMesh" / "boundary").read_text(
        encoding="utf-8"
    )
    owner = (tmp_path / "constant" / "polyMesh" / "owner").read_text(encoding="utf-8")
    neighbour = (tmp_path / "constant" / "polyMesh" / "neighbour").read_text(
        encoding="utf-8"
    )

    for patch in module.BOUNDARY_PATCH_ORDER:
        assert f"\n    {patch}\n" in boundary
    assert f"\n{mesh.face_count}\n(" in owner
    assert f"\n{mesh.internal_face_count}\n(" in neighbour


def test_openfoam_case_writer_includes_mesh_quality_dict(tmp_path: Path) -> None:
    module = _load_module()
    geometry = module.build_artificial_rectangular_wing_geometry(
        n_span=2,
        n_perimeter=16,
    )
    surface = module.build_structured_body_surface(geometry)
    config = module.StructuredHexaConfig(
        case_id="unit",
        n_span=2,
        n_perimeter=16,
        radial_layers=2,
        near_wall_layers=1,
        first_layer_height_m=5.0e-5,
        near_wall_growth=1.2,
        farfield_chords=2.0,
        normal_smoothing_iterations=0,
    )
    mesh = module.build_structured_hexa_mesh(surface, config, cref_m=1.0)
    quality = module.audit_structured_hexa_mesh(mesh)

    module.write_openfoam_case(
        tmp_path,
        mesh=mesh,
        geometry=geometry,
        config=config,
        custom_quality=quality,
        max_iterations=1,
    )

    assert (tmp_path / "system" / "meshQualityDict").exists()
