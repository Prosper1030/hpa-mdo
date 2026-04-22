from __future__ import annotations

import json
from pathlib import Path

import pytest

from hpa_meshing.near_wall_baseline import _run_surface_frozen_candidate_job, run_shell_v3_near_wall_study
from hpa_meshing.schema import MeshJobConfig, SU2RuntimeConfig


def _write_baseline_inputs(tmp_path: Path) -> tuple[Path, Path]:
    run_dir = tmp_path / "baseline_run"
    mesh_dir = run_dir / "artifacts" / "mesh"
    provider_dir = run_dir / "artifacts" / "providers" / "esp_rebuilt" / "esp_runtime"
    mesh_dir.mkdir(parents=True, exist_ok=True)
    provider_dir.mkdir(parents=True, exist_ok=True)

    normalized = provider_dir / "normalized.stp"
    normalized.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
    (mesh_dir / "mesh.msh").write_text("$MeshFormat\n4.1 0 8\n$EndMeshFormat\n", encoding="utf-8")
    (mesh_dir / "gmsh_log.txt").write_text("Info    : No ill-shaped tets in the mesh :-)\n", encoding="utf-8")

    marker_summary = {
        "aircraft": {
            "exists": True,
            "physical_name": "aircraft",
            "physical_tag": 2,
            "entity_count": 32,
            "element_count": 103600,
        },
        "farfield": {
            "exists": True,
            "physical_name": "farfield",
            "physical_tag": 3,
            "entity_count": 6,
            "element_count": 6296,
        },
    }
    (mesh_dir / "marker_summary.json").write_text(json.dumps(marker_summary, indent=2) + "\n", encoding="utf-8")

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
            "surface_element_type_counts": {"2": 109896},
            "volume_element_type_counts": {"4": 132499},
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
        "quality_metrics": {
            "ill_shaped_tet_count": 0,
            "min_gamma": 0.0017,
            "min_sicn": 0.0016,
            "min_sige": 0.049,
            "min_volume": 4.35e-7,
        },
        "mesh_field": {
            "reference_length": 1.0425,
            "near_body_size": 0.0434375,
            "edge_size": 0.0434375,
            "farfield_size": 4.17,
            "distance_min": 0.0,
            "distance_max": 0.434375,
            "edge_distance_max": 0.434375,
            "mesh_algorithm_2d": 6,
            "mesh_algorithm_3d": 1,
            "volume_smoke_decoupled": {
                "enabled": True,
                "base_far_volume_field": {"size": 12.0},
                "near_body_shell": {
                    "enabled": True,
                    "size_min": 0.0434375,
                    "size_max": 3.0,
                    "dist_min": 0.0,
                    "dist_max": 0.18,
                    "stop_at_dist_max": True,
                },
            },
        },
    }
    (mesh_dir / "mesh_metadata.json").write_text(json.dumps(mesh_handoff, indent=2) + "\n", encoding="utf-8")
    (provider_dir / "topology_suppression_report.json").write_text(
        json.dumps({"status": "captured", "applied": False, "suppressed_source_section_count": 0}, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "baseline_name": "shell_v3_quality_clean_baseline",
        "decision": "promote",
        "current_run": {
            "name": "main_wing_volume_smoke_shell_v3_seam_coalesce_verify",
            "run_dir": str(run_dir),
            "surface_triangle_count": 109896,
            "volume_element_count": 132499,
            "ill_shaped_tet_count": 0,
        },
        "artifacts": {
            "mesh_metadata_json": str(mesh_dir / "mesh_metadata.json"),
            "gmsh_log_txt": str(mesh_dir / "gmsh_log.txt"),
            "topology_suppression_report_json": str(provider_dir / "topology_suppression_report.json"),
        },
    }
    manifest_path = run_dir / "shell_v3_quality_clean_baseline_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (run_dir / "shell_v3_quality_clean_baseline_summary.md").write_text("# baseline\n", encoding="utf-8")

    solver_summary = {
        "contract": "shell_v3_solver_smoke_summary.v1",
        "status": "success",
        "baseline_name": "shell_v3_quality_clean_baseline",
        "solver_smoke": {
            "status": "pass",
            "run_status": "completed",
            "final_iteration": 79,
            "final_coefficients": {
                "cl": 0.6470936249,
                "cd": 0.4024782194,
                "cm": -0.5235568231,
            },
        },
        "primary_limitation": {
            "category": "boundary_layer_treatment",
            "reason": "coarse tetra baseline still lacks boundary-layer treatment for trustworthy drag magnitude",
        },
        "run_result": {
            "runtime_cfg_path": str(tmp_path / "historical" / "su2_runtime.cfg"),
            "final_coefficients": {
                "cl": 0.6470936249,
                "cd": 0.4024782194,
                "cm": -0.5235568231,
                "cm_axis": "CMy",
            },
            "reference_geometry": {
                "ref_area": 35.175,
                "ref_length": 1.0425,
                "ref_origin_moment": {"x": 0.0, "y": 0.0, "z": 0.0},
            },
            "convergence_gate": {
                "iterative_gate": {
                    "status": "warn",
                    "checks": {
                        "residual_trend": {
                            "status": "warn",
                            "observed": {"median_log_drop": 0.01},
                        }
                    },
                }
            },
        },
    }
    solver_summary_path = tmp_path / "solver_smoke_summary.json"
    solver_summary_path.write_text(json.dumps(solver_summary, indent=2) + "\n", encoding="utf-8")
    return manifest_path, solver_summary_path


def test_run_shell_v3_near_wall_study_selects_medium_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manifest_path, solver_summary_path = _write_baseline_inputs(tmp_path)

    def _fake_run_baseline_case(mesh_handoff, runtime, case_root, source_root=None):
        case_dir = Path(case_root) / runtime.case_name
        case_dir.mkdir(parents=True, exist_ok=True)
        return {
            "contract": "su2_handoff.v1",
            "run_status": "completed",
            "solver_command": "SU2_CFD su2_runtime.cfg",
            "runtime_cfg_path": str(case_dir / "su2_runtime.cfg"),
            "history_path": str(case_dir / "history.csv"),
            "final_iteration": 80,
            "case_output_paths": {
                "case_dir": str(case_dir),
                "contract_path": str(case_dir / "su2_handoff.json"),
                "solver_log": str(case_dir / "solver.log"),
            },
            "final_coefficients": {
                "cl": 0.09,
                "cd": 0.312,
                "cm": -0.021,
                "cm_axis": "CMy",
            },
            "reference_geometry": {
                "ref_area": 35.175,
                "ref_length": 1.0425,
                "ref_origin_moment": {"x": 0.0, "y": 0.0, "z": 0.0},
            },
            "force_surface_provenance": {"wall_marker": "aircraft"},
            "provenance_gates": {
                "overall_status": "pass",
                "reference_quantities": {"status": "pass"},
                "force_surface": {"status": "pass"},
            },
            "convergence_gate": {
                "mesh_gate": {"status": "pass"},
                "iterative_gate": {
                    "status": "warn",
                    "checks": {
                        "residual_trend": {
                            "status": "warn",
                            "observed": {"median_log_drop": 0.12},
                        }
                    },
                },
                "overall_convergence_gate": {
                    "status": "warn",
                    "comparability_level": "run_only",
                    "warnings": [],
                },
            },
            "provenance": {},
            "notes": [],
        }

    def _fake_run_job(config):
        name = Path(config.out_dir).name
        lookup = {
            "conservative": (0.181, 182000, 164000, "warn", 0.18),
            "medium": (0.061, 233000, 228000, "warn", 0.16),
            "strong": (0.029, 1180000, 1100000, "fail", 0.02),
        }
        cd, node_count, volume_elements, iterative_status, residual_drop = lookup[name]
        return {
            "status": "success",
            "failure_code": None,
            "mesh": {
                "metadata_path": str(config.out_dir / "artifacts" / "mesh" / "mesh_metadata.json"),
                "mesh_artifact": str(config.out_dir / "artifacts" / "mesh" / "mesh.msh"),
                "node_count": node_count,
                "element_count": volume_elements + 110000,
                "surface_element_count": 109896,
                "volume_element_count": volume_elements,
            },
            "run": {
                "backend_result": {
                    "mesh_handoff": {
                        "artifacts": {
                            "mesh": str(config.out_dir / "artifacts" / "mesh" / "mesh.msh"),
                            "mesh_metadata": str(config.out_dir / "artifacts" / "mesh" / "mesh_metadata.json"),
                        },
                        "mesh_stats": {
                            "node_count": node_count,
                            "element_count": volume_elements + 110000,
                            "surface_element_count": 109896,
                            "volume_element_count": volume_elements,
                        },
                        "marker_summary": {
                            "aircraft": {"exists": True, "element_count": 103600},
                            "farfield": {"exists": True, "element_count": 6296},
                        },
                        "physical_groups": {
                            "aircraft": {"entity_count": 32},
                            "farfield": {"entity_count": 6},
                            "fluid": {"entity_count": 1},
                        },
                    }
                }
            },
            "quality": {"ok": True},
            "su2": {
                "run_status": "completed",
                "final_iteration": 80,
                "history_path": str(config.out_dir / "artifacts" / "su2" / name / "history.csv"),
                "runtime_cfg_path": str(config.out_dir / "artifacts" / "su2" / name / "su2_runtime.cfg"),
                "case_output_paths": {
                    "case_dir": str(config.out_dir / "artifacts" / "su2" / name),
                    "contract_path": str(config.out_dir / "artifacts" / "su2" / name / "su2_handoff.json"),
                    "solver_log": str(config.out_dir / "artifacts" / "su2" / name / "solver.log"),
                },
                "final_coefficients": {
                    "cl": 0.03,
                    "cd": cd,
                    "cm": -0.008,
                    "cm_axis": "CMy",
                },
                "reference_geometry": {
                    "ref_area": 35.175,
                    "ref_length": 1.0425,
                    "ref_origin_moment": {"x": 0.0, "y": 0.0, "z": 0.0},
                },
                "convergence_gate": {
                    "mesh_gate": {"status": "pass"},
                    "iterative_gate": {
                        "status": iterative_status,
                        "checks": {
                            "residual_trend": {
                                "status": iterative_status,
                                "observed": {"median_log_drop": residual_drop},
                            }
                        },
                    },
                    "overall_convergence_gate": {
                        "status": iterative_status,
                        "comparability_level": "run_only",
                        "warnings": [],
                    },
                },
                "provenance_gates": {
                    "overall_status": "pass",
                    "reference_quantities": {"status": "pass"},
                    "force_surface": {"status": "pass"},
                },
                "force_surface_provenance": {"wall_marker": "aircraft"},
                "provenance": {},
                "notes": [],
            },
        }

    monkeypatch.setattr("hpa_meshing.near_wall_baseline.run_baseline_case", _fake_run_baseline_case)
    monkeypatch.setattr("hpa_meshing.near_wall_baseline.run_job", _fake_run_job)
    monkeypatch.setattr(
        "hpa_meshing.near_wall_baseline.compute_wall_region_element_stats",
        lambda mesh_path, marker_name="aircraft": {
            "marker_name": marker_name,
            "aircraft_boundary_node_count": 55000,
            "wall_adjacent_volume_element_count": 98000,
            "wall_adjacent_volume_fraction": 0.42,
        },
    )

    result = run_shell_v3_near_wall_study(
        manifest_path,
        solver_summary_path=solver_summary_path,
        out_dir=tmp_path / "near_wall_study",
    )

    assert result["status"] == "success"
    assert result["result_kind"] == "shell_v3_near_wall_cfd_baseline_candidate"
    assert result["winner"]["candidate_name"] == "medium"

    capability = json.loads((tmp_path / "near_wall_study" / "near_wall_capability_report.json").read_text(encoding="utf-8"))
    assert capability["conclusion"] == "prism_layer_not_yet_feasible_use_refined_tetra_fallback"

    frozen = json.loads((tmp_path / "near_wall_study" / "frozen_cfd_context.json").read_text(encoding="utf-8"))
    assert frozen["formal_case_contract"]["velocity_mps"] == pytest.approx(6.5)
    assert frozen["formal_case_contract"]["reynolds_number_case_level"] == pytest.approx(463996.9955, rel=1e-6)


def test_run_shell_v3_near_wall_study_emits_no_go_when_all_candidates_fail_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    manifest_path, solver_summary_path = _write_baseline_inputs(tmp_path)

    monkeypatch.setattr(
        "hpa_meshing.near_wall_baseline.run_baseline_case",
        lambda mesh_handoff, runtime, case_root, source_root=None: {
            "contract": "su2_handoff.v1",
            "run_status": "completed",
            "solver_command": "SU2_CFD su2_runtime.cfg",
            "runtime_cfg_path": str(Path(case_root) / runtime.case_name / "su2_runtime.cfg"),
            "history_path": str(Path(case_root) / runtime.case_name / "history.csv"),
            "final_iteration": 80,
            "case_output_paths": {
                "case_dir": str(Path(case_root) / runtime.case_name),
                "contract_path": str(Path(case_root) / runtime.case_name / "su2_handoff.json"),
                "solver_log": str(Path(case_root) / runtime.case_name / "solver.log"),
            },
            "final_coefficients": {"cl": 0.09, "cd": 0.312, "cm": -0.021, "cm_axis": "CMy"},
            "reference_geometry": {"ref_area": 35.175, "ref_length": 1.0425, "ref_origin_moment": {"x": 0.0, "y": 0.0, "z": 0.0}},
            "force_surface_provenance": {"wall_marker": "aircraft"},
            "provenance_gates": {"overall_status": "pass", "reference_quantities": {"status": "pass"}, "force_surface": {"status": "pass"}},
            "convergence_gate": {
                "mesh_gate": {"status": "pass"},
                "iterative_gate": {"status": "warn", "checks": {"residual_trend": {"status": "warn", "observed": {"median_log_drop": 0.12}}}},
                "overall_convergence_gate": {"status": "warn", "comparability_level": "run_only", "warnings": []},
            },
            "provenance": {},
            "notes": [],
        },
    )
    monkeypatch.setattr(
        "hpa_meshing.near_wall_baseline.run_job",
        lambda config: {
            "status": "success",
            "failure_code": None,
            "mesh": {
                "metadata_path": str(config.out_dir / "artifacts" / "mesh" / "mesh_metadata.json"),
                "mesh_artifact": str(config.out_dir / "artifacts" / "mesh" / "mesh.msh"),
                "node_count": 600000,
                "element_count": 1200000,
                "surface_element_count": 109896,
                "volume_element_count": 1100000,
            },
            "run": {
                "backend_result": {
                    "mesh_handoff": {
                        "artifacts": {
                            "mesh": str(config.out_dir / "artifacts" / "mesh" / "mesh.msh"),
                            "mesh_metadata": str(config.out_dir / "artifacts" / "mesh" / "mesh_metadata.json"),
                        },
                        "mesh_stats": {
                            "node_count": 600000,
                            "element_count": 1200000,
                            "surface_element_count": 109896,
                            "volume_element_count": 1100000,
                        },
                    }
                }
            },
            "quality": {"ok": True},
            "su2": {
                "run_status": "completed",
                "final_iteration": 80,
                "history_path": str(config.out_dir / "artifacts" / "su2" / "history.csv"),
                "runtime_cfg_path": str(config.out_dir / "artifacts" / "su2" / "su2_runtime.cfg"),
                "case_output_paths": {
                    "case_dir": str(config.out_dir / "artifacts" / "su2"),
                    "contract_path": str(config.out_dir / "artifacts" / "su2" / "su2_handoff.json"),
                    "solver_log": str(config.out_dir / "artifacts" / "su2" / "solver.log"),
                },
                "final_coefficients": {"cl": 0.03, "cd": 0.29, "cm": -0.008, "cm_axis": "CMy"},
                "reference_geometry": {"ref_area": 35.175, "ref_length": 1.0425, "ref_origin_moment": {"x": 0.0, "y": 0.0, "z": 0.0}},
                "convergence_gate": {
                    "mesh_gate": {"status": "pass"},
                    "iterative_gate": {"status": "fail", "checks": {"residual_trend": {"status": "fail", "observed": {"median_log_drop": 0.01}}}},
                    "overall_convergence_gate": {"status": "fail", "comparability_level": "not_comparable", "warnings": []},
                },
                "provenance_gates": {"overall_status": "pass", "reference_quantities": {"status": "pass"}, "force_surface": {"status": "pass"}},
                "force_surface_provenance": {"wall_marker": "aircraft"},
                "provenance": {},
                "notes": [],
            },
        },
    )
    monkeypatch.setattr(
        "hpa_meshing.near_wall_baseline.compute_wall_region_element_stats",
        lambda mesh_path, marker_name="aircraft": {
            "marker_name": marker_name,
            "aircraft_boundary_node_count": 55000,
            "wall_adjacent_volume_element_count": 300000,
            "wall_adjacent_volume_fraction": 0.27,
        },
    )

    result = run_shell_v3_near_wall_study(
        manifest_path,
        solver_summary_path=solver_summary_path,
        out_dir=tmp_path / "near_wall_study",
    )

    assert result["status"] == "failed"
    assert result["result_kind"] == "near_wall_no_go_summary"
    assert (tmp_path / "near_wall_study" / "near_wall_no_go_summary.json").exists()


def test_run_shell_v3_near_wall_study_treats_zero_volume_mesh_as_mesh_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    manifest_path, solver_summary_path = _write_baseline_inputs(tmp_path)

    monkeypatch.setattr(
        "hpa_meshing.near_wall_baseline.run_baseline_case",
        lambda mesh_handoff, runtime, case_root, source_root=None: {
            "contract": "su2_handoff.v1",
            "run_status": "completed",
            "solver_command": "SU2_CFD su2_runtime.cfg",
            "runtime_cfg_path": str(Path(case_root) / runtime.case_name / "su2_runtime.cfg"),
            "history_path": str(Path(case_root) / runtime.case_name / "history.csv"),
            "final_iteration": 80,
            "case_output_paths": {
                "case_dir": str(Path(case_root) / runtime.case_name),
                "contract_path": str(Path(case_root) / runtime.case_name / "su2_handoff.json"),
                "solver_log": str(Path(case_root) / runtime.case_name / "solver.log"),
            },
            "final_coefficients": {"cl": 0.09, "cd": 0.312, "cm": -0.021, "cm_axis": "CMy"},
            "reference_geometry": {"ref_area": 35.175, "ref_length": 1.0425, "ref_origin_moment": {"x": 0.0, "y": 0.0, "z": 0.0}},
            "force_surface_provenance": {"wall_marker": "aircraft"},
            "provenance_gates": {"overall_status": "pass", "reference_quantities": {"status": "pass"}, "force_surface": {"status": "pass"}},
            "convergence_gate": {
                "mesh_gate": {"status": "pass"},
                "iterative_gate": {"status": "warn", "checks": {"residual_trend": {"status": "warn", "observed": {"median_log_drop": 0.12}}}},
                "overall_convergence_gate": {"status": "warn", "comparability_level": "run_only", "warnings": []},
            },
            "provenance": {},
            "notes": [],
        },
    )
    monkeypatch.setattr(
        "hpa_meshing.near_wall_baseline.run_job",
        lambda config: {
            "status": "failed",
            "failure_code": "surface_frozen_no_volume_elements",
            "mesh": {
                "metadata_path": str(config.out_dir / "artifacts" / "mesh" / "mesh_metadata.json"),
                "mesh_artifact": str(config.out_dir / "artifacts" / "mesh" / "mesh.msh"),
                "node_count": 54952,
                "element_count": 109937,
                "surface_element_count": 109896,
                "volume_element_count": 0,
            },
            "run": {"backend_result": {"mesh_handoff": {"artifacts": {"mesh": str(config.out_dir / "artifacts" / "mesh" / "mesh.msh"), "mesh_metadata": str(config.out_dir / "artifacts" / "mesh" / "mesh_metadata.json")}}}},
            "quality": {"ok": False},
            "su2": {
                "run_status": "failed",
                "final_iteration": None,
                "history_path": str(config.out_dir / "artifacts" / "su2" / "history.csv"),
                "runtime_cfg_path": str(config.out_dir / "artifacts" / "su2" / "su2_runtime.cfg"),
                "case_output_paths": {
                    "case_dir": str(config.out_dir / "artifacts" / "su2"),
                    "contract_path": str(config.out_dir / "artifacts" / "su2" / "su2_handoff.json"),
                    "solver_log": str(config.out_dir / "artifacts" / "su2" / "solver.log"),
                },
                "final_coefficients": {"cl": None, "cd": None, "cm": None, "cm_axis": None},
                "reference_geometry": {"ref_area": 35.175, "ref_length": 1.0425, "ref_origin_moment": {"x": 0.0, "y": 0.0, "z": 0.0}},
                "convergence_gate": {"mesh_gate": {"status": "fail"}, "iterative_gate": {"status": None, "checks": {}}, "overall_convergence_gate": {"status": "fail", "comparability_level": "not_comparable", "warnings": []}},
                "provenance_gates": {"overall_status": "fail"},
                "force_surface_provenance": {"wall_marker": "aircraft"},
                "provenance": {},
                "notes": [],
            },
        },
    )
    monkeypatch.setattr(
        "hpa_meshing.near_wall_baseline.compute_wall_region_element_stats",
        lambda mesh_path, marker_name="aircraft": {
            "marker_name": marker_name,
            "aircraft_boundary_node_count": 51802,
            "wall_adjacent_volume_element_count": 0,
            "wall_adjacent_volume_fraction": 0.0,
        },
    )

    result = run_shell_v3_near_wall_study(
        manifest_path,
        solver_summary_path=solver_summary_path,
        out_dir=tmp_path / "near_wall_study",
    )

    assert result["status"] == "failed"
    no_go = json.loads((tmp_path / "near_wall_study" / "near_wall_no_go_summary.json").read_text(encoding="utf-8"))
    for candidate in no_go["candidate_evaluations"]:
        assert candidate["selection"]["checks"]["mesh_generation_success"] is False
        assert candidate["mesh"]["volume_element_count"] == 0


def test_run_surface_frozen_candidate_job_skips_su2_for_zero_volume_mesh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    frozen_mesh_dir = tmp_path / "frozen" / "artifacts" / "mesh"
    frozen_mesh_dir.mkdir(parents=True, exist_ok=True)
    mesh_handoff_path = frozen_mesh_dir / "mesh_metadata.json"
    mesh_handoff_path.write_text(
        json.dumps(
            {
                "contract": "mesh_handoff.v1",
                "geometry_family": "thin_sheet_lifting_surface",
                "geometry_source": "esp_rebuilt",
                "geometry_provider": "esp_rebuilt",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    surface_mesh_path = frozen_mesh_dir / "surface_mesh_2d.msh"
    surface_mesh_path.write_text("$MeshFormat\n4.1 0 8\n$EndMeshFormat\n", encoding="utf-8")

    config = MeshJobConfig(
        component="main_wing",
        geometry=tmp_path / "normalized.stp",
        out_dir=tmp_path / "candidate",
        geometry_source="esp_rebuilt",
        geometry_family="thin_sheet_lifting_surface",
        geometry_provider="esp_rebuilt",
        units="m",
        mesh_dim=3,
        metadata={
            "_frozen_geometry": {
                "normalized_geometry_path": str(tmp_path / "normalized.stp"),
                "geometry_source": "esp_rebuilt",
                "geometry_provider": "esp_rebuilt",
            },
            "_frozen_mesh_handoff_path": str(mesh_handoff_path),
            "_frozen_surface_mesh_path": str(surface_mesh_path),
        },
        su2=SU2RuntimeConfig(enabled=True, case_name="zero-volume-check"),
    )

    monkeypatch.setattr(
        "hpa_meshing.near_wall_baseline._mesh_handoff_from_surface_frozen_regenerate",
        lambda config, frozen_mesh_handoff, surface_mesh_path: {
            "status": "success",
            "backend_result": {
                "mesh_handoff": {
                    "artifacts": {
                        "mesh": str(config.out_dir / "artifacts" / "mesh" / "mesh.msh"),
                        "mesh_metadata": str(config.out_dir / "artifacts" / "mesh" / "mesh_metadata.json"),
                    },
                    "mesh_stats": {
                        "mesh_dim": 3,
                        "node_count": 54952,
                        "element_count": 109937,
                        "surface_element_count": 109896,
                        "volume_element_count": 0,
                    },
                },
            },
        },
    )

    def _unexpected_su2(*args, **kwargs):
        raise AssertionError("SU2 should not run when the regenerated mesh has zero volume elements")

    monkeypatch.setattr("hpa_meshing.near_wall_baseline.run_baseline_case", _unexpected_su2)

    result = _run_surface_frozen_candidate_job(config)

    assert result["status"] == "failed"
    assert result["failure_code"] == "surface_frozen_no_volume_elements"
    assert result["mesh"]["volume_element_count"] == 0
    assert result["quality"]["ok"] is False
