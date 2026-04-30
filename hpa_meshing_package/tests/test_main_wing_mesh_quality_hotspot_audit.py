import json
from pathlib import Path

import pytest

from hpa_meshing.main_wing_mesh_quality_hotspot_audit import (
    build_main_wing_mesh_quality_hotspot_audit_report,
    write_main_wing_mesh_quality_hotspot_audit_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _quality_fixture(tmp_path: Path) -> dict[str, Path]:
    mesh_handoff = _write_json(
        tmp_path / "mesh_handoff.json",
        {
            "mesh_quality_status": "warn",
            "mesh_quality_advisory_flags": [
                "gmsh_ill_shaped_tets_present",
                "gmsh_min_gamma_below_1e_minus_4",
            ],
        },
    )
    mesh_metadata = _write_json(
        tmp_path / "mesh_metadata.json",
        {
            "quality_metrics": {
                "tetrahedron_count": 100,
                "ill_shaped_tet_count": 3,
                "min_gamma": 1.0e-6,
                "gamma_percentiles": {"p01": 0.12},
                "worst_20_tets": [
                    {
                        "element_id": 10,
                        "barycenter": [5.0, 40.0, 2.0],
                        "gamma": 1.0e-6,
                        "min_sicn": 1.0e-4,
                        "min_sige": 2.0e-4,
                        "volume": 1.0e-4,
                        "nearest_surface": {
                            "surface_tag": 35,
                            "physical_name": "farfield",
                            "distance": 1.0e-4,
                        },
                        "tetra_edge_length_min": 0.6,
                        "tetra_edge_length_max": 1.6,
                    },
                    {
                        "element_id": 11,
                        "barycenter": [0.95, 12.65, 0.44],
                        "gamma": 9.0e-4,
                        "min_sicn": 8.0e-4,
                        "min_sige": 9.0e-4,
                        "volume": 2.0e-4,
                        "nearest_surface": {
                            "surface_tag": 19,
                            "physical_name": "main_wing",
                            "distance": 1.5e-3,
                        },
                        "tetra_edge_length_min": 0.013,
                        "tetra_edge_length_max": 0.33,
                    },
                    {
                        "element_id": 12,
                        "barycenter": [0.99, 12.70, 0.29],
                        "gamma": 0.008,
                        "min_sicn": 0.01,
                        "min_sige": 0.02,
                        "volume": 3.0e-4,
                        "nearest_surface": {
                            "surface_tag": 29,
                            "physical_name": "main_wing",
                            "distance": 2.0e-3,
                        },
                        "tetra_edge_length_min": 0.02,
                        "tetra_edge_length_max": 0.35,
                    },
                ],
            }
        },
    )
    hotspot_patch = _write_json(
        tmp_path / "hotspot_patch_report.json",
        {
            "status": "captured",
            "selected_surface_tags": [35, 19],
            "surface_reports": [
                {
                    "surface_id": 35,
                    "surface_role": "farfield",
                    "family_hints": [],
                    "worst_tets_near_this_surface": {
                        "count": 1,
                        "min_gamma": 1.0e-6,
                    },
                },
                {
                    "surface_id": 19,
                    "surface_role": "aircraft",
                    "family_hints": [],
                    "worst_tets_near_this_surface": {
                        "count": 1,
                        "min_gamma": 9.0e-4,
                    },
                },
            ],
        },
    )
    surface_patch = _write_json(
        tmp_path / "surface_patch_diagnostics.json",
        {
            "surface_records": [
                {
                    "tag": 19,
                    "surface_role": "aircraft",
                    "bbox": {"y_min": 10.5, "y_max": 13.5},
                    "curve_tags": [27, 48, 49, 50],
                    "short_curve_tags": [],
                    "family_hints": [],
                    "suspect_score": 2.1,
                },
                {
                    "tag": 29,
                    "surface_role": "aircraft",
                    "bbox": {"y_min": 10.5, "y_max": 13.5},
                    "curve_tags": [26, 49, 61, 62],
                    "short_curve_tags": [61, 62],
                    "family_hints": [
                        "tiny_face_candidate",
                        "short_curve_candidate",
                        "high_aspect_strip_candidate",
                    ],
                    "suspect_score": 23.1,
                },
            ]
        },
    )
    defect_trace = _write_json(
        tmp_path / "gmsh_defect_entity_trace.json",
        {
            "trace_status": "defect_edges_traced_to_gmsh_entities",
            "trace_summary": {
                "involved_surface_entity_tags": [12, 19],
                "candidate_curve_tags": [50],
            },
        },
    )
    return {
        "mesh_handoff": mesh_handoff,
        "mesh_metadata": mesh_metadata,
        "hotspot_patch": hotspot_patch,
        "surface_patch": surface_patch,
        "defect_trace": defect_trace,
    }


def test_mesh_quality_hotspot_audit_partitions_worst_tets_and_station_overlap(
    tmp_path: Path,
):
    paths = _quality_fixture(tmp_path)

    report = build_main_wing_mesh_quality_hotspot_audit_report(
        mesh_handoff_report_path=paths["mesh_handoff"],
        mesh_metadata_path=paths["mesh_metadata"],
        hotspot_patch_report_path=paths["hotspot_patch"],
        surface_patch_diagnostics_path=paths["surface_patch"],
        gmsh_defect_entity_trace_path=paths["defect_trace"],
    )

    assert report.hotspot_status == "mesh_quality_hotspots_localized"
    assert report.quality_summary["ill_shaped_tet_count"] == 3
    assert report.quality_summary["min_gamma"] == pytest.approx(1.0e-6)
    assert report.worst_tet_sample_partition["by_nearest_physical_name"] == {
        "farfield": 1,
        "main_wing": 2,
    }
    assert report.station_seam_overlap_observed["overlap_surface_tags"] == [19]
    assert report.station_seam_overlap_observed["candidate_curve_tags"] == [50]
    surface_19 = next(
        item for item in report.hotspot_surface_summaries if item["surface_tag"] == 19
    )
    assert surface_19["surface_role"] == "aircraft"
    assert surface_19["sample_worst_tet_count"] == 1
    surface_29 = next(
        item for item in report.hotspot_surface_summaries if item["surface_tag"] == 29
    )
    assert "short_curve_candidate" in surface_29["family_hints"]
    assert "main_wing_near_surface_quality_hotspots_present" in report.engineering_findings
    assert (
        "main_wing_quality_hotspot_overlaps_station_seam_trace"
        in report.engineering_findings
    )
    assert report.next_actions[0] == (
        "repair_station_seam_export_before_solver_iteration_budget"
    )


def test_write_mesh_quality_hotspot_audit_report(tmp_path: Path):
    paths = _quality_fixture(tmp_path)

    written = write_main_wing_mesh_quality_hotspot_audit_report(
        tmp_path / "out",
        mesh_handoff_report_path=paths["mesh_handoff"],
        mesh_metadata_path=paths["mesh_metadata"],
        hotspot_patch_report_path=paths["hotspot_patch"],
        surface_patch_diagnostics_path=paths["surface_patch"],
        gmsh_defect_entity_trace_path=paths["defect_trace"],
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == "main_wing_mesh_quality_hotspot_audit.v1"
    assert payload["hotspot_status"] == "mesh_quality_hotspots_localized"
    assert "Main Wing Mesh Quality Hotspot Audit v1" in markdown
