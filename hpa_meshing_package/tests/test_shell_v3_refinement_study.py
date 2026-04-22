from __future__ import annotations

import json
from pathlib import Path

import pytest

from hpa_meshing.shell_v3_refinement_study import (
    _build_case_specs,
    _case_reynolds_number,
    _fixed_runtime,
    _reconstruct_provider_result,
    _study_summary_payload,
)


def _baseline_mesh_handoff(tmp_path: Path) -> dict:
    provider_dir = tmp_path / "artifacts" / "providers" / "esp_rebuilt" / "esp_runtime"
    mesh_dir = tmp_path / "artifacts" / "mesh"
    provider_dir.mkdir(parents=True, exist_ok=True)
    mesh_dir.mkdir(parents=True, exist_ok=True)

    normalized = provider_dir / "normalized.stp"
    normalized.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
    source = tmp_path / "blackcat_004_origin.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")

    payload = {
        "contract": "mesh_handoff.v1",
        "route_stage": "baseline",
        "backend": "gmsh",
        "backend_capability": "sheet_lifting_surface_meshing",
        "meshing_route": "gmsh_thin_sheet_surface",
        "geometry_family": "thin_sheet_lifting_surface",
        "geometry_source": "esp_rebuilt",
        "geometry_provider": "esp_rebuilt",
        "source_path": str(source),
        "normalized_geometry_path": str(normalized),
        "units": "m",
        "mesh_format": "msh",
        "body_bounds": {
            "x_min": 0.0,
            "x_max": 1.3023,
            "y_min": -16.5,
            "y_max": 16.5,
            "z_min": -0.06,
            "z_max": 0.84,
        },
        "farfield_bounds": {
            "x_min": -6.5,
            "x_max": 16.9,
            "y_min": -280.5,
            "y_max": 280.5,
            "z_min": -7.3,
            "z_max": 8.1,
        },
        "mesh_stats": {
            "mesh_dim": 3,
            "node_count": 56420,
            "element_count": 245624,
            "surface_element_count": 109896,
            "volume_element_count": 132499,
        },
        "mesh_field": {
            "near_body_size": 0.0434375,
            "farfield_size": 4.17,
            "distance_max": 0.434375,
            "edge_distance_max": 0.434375,
            "mesh_algorithm_2d": 6,
            "mesh_algorithm_3d": 1,
            "coarse_first_tetra": {
                "enabled": True,
                "surface_nodes_per_reference_length": 24.0,
                "edge_refinement_ratio": 1.0,
                "span_extreme_strip_floor_size": 0.12,
                "suspect_strip_floor_size": 0.08,
                "suspect_surface_algorithm": 5,
                "general_surface_algorithm": 5,
                "farfield_surface_algorithm": 5,
                "clamp_mesh_size_min_to_near_body": True,
            },
            "volume_smoke_decoupled": {
                "enabled": True,
                "base_far_volume_field": {"size": 12.0},
                "near_body_shell": {
                    "enabled": True,
                    "size_min": 0.0434375,
                    "size_max": 3.0,
                    "dist_max": 0.18,
                },
            },
        },
        "marker_summary": {
            "aircraft": {"exists": True, "physical_name": "aircraft"},
            "farfield": {"exists": True, "physical_name": "farfield"},
        },
        "physical_groups": {
            "aircraft": {"exists": True, "physical_name": "aircraft"},
            "farfield": {"exists": True, "physical_name": "farfield"},
            "fluid": {"exists": True, "physical_name": "fluid"},
        },
        "artifacts": {
            "mesh": str(mesh_dir / "mesh.msh"),
            "mesh_metadata": str(mesh_dir / "mesh_metadata.json"),
            "marker_summary": str(mesh_dir / "marker_summary.json"),
        },
        "provenance": {
            "provider": {
                "provider": "esp_rebuilt",
                "provider_stage": "experimental",
                "provider_status": "materialized",
                "topology": {
                    "representation": "brep_trimmed_step",
                    "source_kind": "stp",
                    "units": "m",
                    "bounds": {
                        "x_min": 0.0,
                        "x_max": 1.3023,
                        "y_min": -16.5,
                        "y_max": 16.5,
                        "z_min": -0.06,
                        "z_max": 0.84,
                    },
                    "import_bounds": {
                        "x_min": 0.0,
                        "x_max": 1302.3,
                        "y_min": -16500.0,
                        "y_max": 16500.0,
                        "z_min": -60.0,
                        "z_max": 840.0,
                    },
                    "import_scale_to_units": 0.001,
                    "backend_rescale_required": True,
                    "body_count": 1,
                    "surface_count": 32,
                    "volume_count": 1,
                    "labels_present": True,
                    "label_schema": "preserve_component_labels",
                    "normalization": {"units": "m"},
                    "notes": [
                        "gmsh_occ_import_requires_rescale_to_declared_units:scale=0.001",
                    ],
                },
                "provenance": {
                    "normalization": {
                        "source_units": "mm",
                        "target_units": "m",
                        "import_scale_to_units": 0.001,
                    },
                    "runtime": {"available": True},
                },
            }
        },
        "quality_metrics": {
            "ill_shaped_tet_count": 0,
        },
    }
    return payload


def test_fixed_runtime_uses_requested_dimensional_contract():
    runtime = _fixed_runtime("medium")

    assert runtime.velocity_mps == pytest.approx(6.5)
    assert runtime.density_kgpm3 == pytest.approx(1.225)
    assert runtime.temperature_k == pytest.approx(288.15)
    assert runtime.dynamic_viscosity_pas == pytest.approx(1.789e-5)
    assert runtime.solver == "INC_NAVIER_STOKES"
    assert runtime.wall_boundary_condition == "adiabatic_no_slip"
    assert runtime.inc_nondim == "DIMENSIONAL"
    assert runtime.inc_density_model == "CONSTANT"
    assert runtime.fluid_model == "CONSTANT_DENSITY"
    assert runtime.reference_mode == "user_declared"
    assert runtime.reference_override.ref_area == pytest.approx(35.175)
    assert runtime.reference_override.ref_length == pytest.approx(1.0425)


def test_reconstruct_provider_result_uses_frozen_provider_topology(tmp_path: Path):
    mesh_handoff = _baseline_mesh_handoff(tmp_path)

    provider_result = _reconstruct_provider_result(mesh_handoff)

    assert provider_result.provider == "esp_rebuilt"
    assert provider_result.status == "materialized"
    assert provider_result.geometry_family_hint == "thin_sheet_lifting_surface"
    assert provider_result.topology.import_scale_to_units == pytest.approx(0.001)
    assert provider_result.topology.backend_rescale_required is True
    assert provider_result.normalized_geometry_path == Path(mesh_handoff["normalized_geometry_path"])


def test_build_case_specs_returns_only_coarse_medium_fine(tmp_path: Path):
    mesh_handoff = _baseline_mesh_handoff(tmp_path)

    specs = _build_case_specs(mesh_handoff)

    assert [spec["name"] for spec in specs] == ["coarse", "medium", "fine"]
    assert specs[0]["reuse_frozen_mesh"] is True
    assert specs[1]["reuse_frozen_mesh"] is False
    assert specs[2]["reuse_frozen_mesh"] is False
    assert specs[1]["scale"] < specs[0]["scale"]
    assert specs[2]["scale"] < specs[1]["scale"]
    assert specs[2]["surface_near_body_size"] < specs[1]["surface_near_body_size"]


def test_study_summary_payload_reports_three_cases_and_case_level_reynolds(tmp_path: Path):
    out_dir = tmp_path / "study"
    out_dir.mkdir(parents=True, exist_ok=True)
    case_summaries = [
        {
            "case_name": "coarse",
            "mesh": {"volume_element_count": 132499},
            "su2": {"coefficients": {"cd": 0.36}},
        },
        {
            "case_name": "medium",
            "mesh": {"volume_element_count": 166100},
            "su2": {"coefficients": {"cd": 0.31}},
        },
        {
            "case_name": "fine",
            "mesh": {"volume_element_count": 208400},
            "su2": {"coefficients": {"cd": 0.29}},
        },
    ]

    payload = _study_summary_payload(
        baseline_manifest_path=tmp_path / "baseline.json",
        baseline_mesh_metadata_path=tmp_path / "mesh_metadata.json",
        out_dir=out_dir,
        case_summaries=case_summaries,
    )

    assert payload["contract"] == "shell_v3_mesh_refinement_summary.v1"
    assert [case["case_name"] for case in payload["cases"]] == ["coarse", "medium", "fine"]
    assert payload["case_level_reynolds_number"] == pytest.approx(_case_reynolds_number())
    assert "not a local chord Reynolds number" in payload["case_level_reynolds_number_note"]
    assert payload["conclusion"]["drag_trend"]["best_cd_case"] == "fine"
    assert json.loads((out_dir / "mesh_refinement_summary.json").read_text(encoding="utf-8"))["contract"] == (
        "shell_v3_mesh_refinement_summary.v1"
    )
