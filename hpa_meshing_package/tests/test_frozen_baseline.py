from __future__ import annotations

import json
from pathlib import Path

import pytest

from hpa_meshing.frozen_baseline import evaluate_shell_v3_baseline_regression


def _write_shell_v3_baseline_artifacts(
    tmp_path: Path,
    *,
    manifest_surface_triangles: int = 109896,
    manifest_volume_elements: int = 132499,
    mesh_surface_triangles: int = 109896,
    mesh_volume_elements: int = 132499,
    ill_shaped_tets: int = 0,
    topology_suppression_applied: bool = False,
) -> Path:
    run_dir = tmp_path / "baseline_run"
    mesh_dir = run_dir / "artifacts" / "mesh"
    provider_dir = run_dir / "artifacts" / "providers" / "esp_rebuilt" / "esp_runtime"
    mesh_dir.mkdir(parents=True, exist_ok=True)
    provider_dir.mkdir(parents=True, exist_ok=True)

    (mesh_dir / "mesh.msh").write_text("$MeshFormat\n4.1 0 8\n$EndMeshFormat\n", encoding="utf-8")
    (mesh_dir / "marker_summary.json").write_text(
        json.dumps(
            {
                "aircraft": {
                    "exists": True,
                    "dimension": 2,
                    "physical_name": "aircraft",
                    "physical_tag": 2,
                    "entity_count": 32,
                    "element_count": mesh_surface_triangles - 6296,
                },
                "farfield": {
                    "exists": True,
                    "dimension": 2,
                    "physical_name": "farfield",
                    "physical_tag": 3,
                    "entity_count": 6,
                    "element_count": 6296,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (mesh_dir / "gmsh_log.txt").write_text(
        "Info    : No ill-shaped tets in the mesh :-)\n",
        encoding="utf-8",
    )
    (provider_dir / "topology_suppression_report.json").write_text(
        json.dumps(
            {
                "status": "captured",
                "applied": topology_suppression_applied,
                "suppressed_source_section_count": 0 if not topology_suppression_applied else 1,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    mesh_handoff = {
        "contract": "mesh_handoff.v1",
        "route_stage": "baseline",
        "backend": "gmsh",
        "backend_capability": "sheet_lifting_surface_meshing",
        "meshing_route": "gmsh_thin_sheet_surface",
        "geometry_family": "thin_sheet_lifting_surface",
        "geometry_source": "esp_rebuilt",
        "geometry_provider": "esp_rebuilt",
        "source_path": str(tmp_path / "blackcat_004_origin.vsp3"),
        "normalized_geometry_path": str(provider_dir / "normalized.stp"),
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
            "element_count": mesh_surface_triangles + mesh_volume_elements + 3229,
            "surface_element_count": mesh_surface_triangles,
            "volume_element_count": mesh_volume_elements,
        },
        "marker_summary": {
            "aircraft": {"exists": True},
            "farfield": {"exists": True},
        },
        "physical_groups": {
            "aircraft": {"exists": True, "entity_count": 32},
            "farfield": {"exists": True, "entity_count": 6},
            "fluid": {"exists": True, "entity_count": 1},
        },
        "artifacts": {
            "mesh": str(mesh_dir / "mesh.msh"),
            "mesh_metadata": str(mesh_dir / "mesh_metadata.json"),
            "marker_summary": str(mesh_dir / "marker_summary.json"),
            "gmsh_log": str(mesh_dir / "gmsh_log.txt"),
        },
        "provenance": {
            "provider": {
                "topology": {
                    "body_count": 1,
                    "labels_present": True,
                    "label_schema": "preserve_component_labels",
                }
            }
        },
        "unit_normalization": {},
        "quality_metrics": {
            "ill_shaped_tet_count": ill_shaped_tets,
            "min_gamma": 0.001737927861030737,
            "min_sicn": 0.0016000621569402871,
            "min_sige": 0.0493425151477202,
            "min_volume": 4.351387815989023e-07,
        },
    }
    (mesh_dir / "mesh_metadata.json").write_text(
        json.dumps(mesh_handoff, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "baseline_name": "shell_v3_quality_clean_baseline",
        "decision": "promote",
        "current_run": {
            "name": "main_wing_volume_smoke_shell_v3_seam_coalesce_verify",
            "run_dir": str(run_dir),
            "surface_triangle_count": manifest_surface_triangles,
            "volume_element_count": manifest_volume_elements,
            "nodes_created_per_boundary_node": 0.02422113844810016,
            "ill_shaped_tet_count": 0,
            "min_gamma": 0.001737927861030737,
            "gmsh_log_verdict": "No ill-shaped tets in the mesh",
            "topology_suppression_report": {
                "applied": False,
                "suppressed_source_section_count": 0,
            },
        },
        "artifacts": {
            "mesh_metadata_json": str(mesh_dir / "mesh_metadata.json"),
            "gmsh_log_txt": str(mesh_dir / "gmsh_log.txt"),
            "topology_suppression_report_json": str(provider_dir / "topology_suppression_report.json"),
        },
    }
    manifest_path = run_dir / "shell_v3_quality_clean_baseline_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (run_dir / "shell_v3_quality_clean_baseline_summary.md").write_text(
        "# shell_v3 quality clean baseline\n",
        encoding="utf-8",
    )
    return manifest_path


def test_evaluate_shell_v3_baseline_regression_passes_for_matching_artifacts(tmp_path: Path):
    manifest_path = _write_shell_v3_baseline_artifacts(tmp_path)

    report = evaluate_shell_v3_baseline_regression(manifest_path)

    assert report["status"] == "pass"
    assert report["checks"]["ill_shaped_tet_count"]["status"] == "pass"
    assert report["checks"]["surface_triangle_count"]["observed"]["relative_drift"] == pytest.approx(0.0)
    assert report["checks"]["volume_element_count"]["observed"]["relative_drift"] == pytest.approx(0.0)
    assert report["checks"]["gmsh_log"]["status"] == "pass"
    assert report["checks"]["topology_suppression_origin"]["status"] == "pass"


def test_evaluate_shell_v3_baseline_regression_fails_on_large_mesh_drift(tmp_path: Path):
    manifest_path = _write_shell_v3_baseline_artifacts(
        tmp_path,
        mesh_surface_triangles=125000,
        mesh_volume_elements=150000,
    )

    report = evaluate_shell_v3_baseline_regression(manifest_path)

    assert report["status"] == "fail"
    assert report["checks"]["surface_triangle_count"]["status"] == "fail"
    assert report["checks"]["volume_element_count"]["status"] == "fail"
