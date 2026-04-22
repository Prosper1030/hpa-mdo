from __future__ import annotations

import json
import subprocess
from pathlib import Path

from hpa_meshing.gmsh_runtime import load_gmsh
from hpa_meshing.providers.esp_pipeline import (
    _build_autonomous_repair_context,
    _build_autonomous_topology_base_config,
    _ComponentInputModel,
    _NativeRebuildModel,
    _NativeSectionRecord,
    _NativeSurfaceRecord,
    _VspWingCandidate,
    _apply_terminal_strip_suppression,
    _build_candidate_topology_repair_report,
    _build_topology_lineage_report,
    _build_tip_topology_diagnostics,
    _evaluate_topology_repair_candidate,
    _generate_bounded_tip_topology_repair_candidates,
    _geometry_filter_decision,
    _select_top_geometry_candidates,
    _select_topology_repair_winner,
    _build_upstream_pairing_no_go_summary,
    run_autonomous_tip_topology_repair_controller,
    _build_native_rebuild_model,
    _prepare_component_input_model,
    _select_component_candidate,
    _analyze_symmetry_touching_solids,
    _combine_union_groups_with_singletons,
    materialize_with_esp,
)
from hpa_meshing.providers.openvsp_surface_intersection import _probe_step_topology


def _write_boxes_step(path: Path, boxes: list[tuple[float, float, float, float, float, float]]) -> None:
    gmsh = load_gmsh()
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add(path.stem)
    for x, y, z, dx, dy, dz in boxes:
        gmsh.model.occ.addBox(x, y, z, dx, dy, dz)
    gmsh.model.occ.synchronize()
    gmsh.write(str(path))
    gmsh.finalize()


def _raw_symmetry_boxes() -> list[tuple[float, float, float, float, float, float]]:
    return [
        (0.0, -2.0, 0.0, 1.0, 2.0, 0.10),
        (0.0, 0.0, 0.0, 1.0, 2.0, 0.10),
        (3.0, -0.8, 0.0, 0.5, 0.8, 0.05),
        (3.0, 0.0, 0.0, 0.5, 0.8, 0.05),
        (4.5, -0.05, 0.0, 0.3, 0.10, 0.5),
    ]


def _unioned_boxes() -> list[tuple[float, float, float, float, float, float]]:
    return [
        (0.0, -2.0, 0.0, 1.0, 4.0, 0.10),
        (3.0, -0.8, 0.0, 0.5, 1.6, 0.05),
    ]


def _sample_airfoil_coords(scale: float = 1.0) -> tuple[tuple[float, float], ...]:
    return (
        (1.0, 0.0),
        (0.75, 0.035 * scale),
        (0.35, 0.055 * scale),
        (0.0, 0.0),
        (0.35, -0.040 * scale),
        (0.75, -0.018 * scale),
        (1.0, 0.0),
    )


def _sample_native_rebuild_model(source: Path) -> _NativeRebuildModel:
    return _NativeRebuildModel(
        source_path=source,
        surfaces=(
            _NativeSurfaceRecord(
                component="main_wing",
                geom_id="main",
                name="Main Wing",
                caps_group="main_wing",
                symmetric_xz=True,
                sections=(
                    _NativeSectionRecord(
                        x_le=0.0,
                        y_le=0.0,
                        z_le=0.0,
                        chord=1.30,
                        twist_deg=0.0,
                        airfoil_name="NACA 2412",
                        airfoil_source="inline_coordinates",
                        airfoil_coordinates=_sample_airfoil_coords(),
                        thickness_tc=0.12,
                        camber=0.02,
                        camber_loc=0.4,
                    ),
                    _NativeSectionRecord(
                        x_le=0.10,
                        y_le=16.5,
                        z_le=1.70,
                        chord=0.435,
                        twist_deg=0.0,
                        airfoil_name="NACA 2412",
                        airfoil_source="inline_coordinates",
                        airfoil_coordinates=_sample_airfoil_coords(0.8),
                        thickness_tc=0.12,
                        camber=0.02,
                        camber_loc=0.4,
                    ),
                ),
            ),
        ),
        notes=("unit-test-native-model",),
    )


def _sample_tip_strip_airfoil_coords() -> tuple[tuple[float, float], ...]:
    return (
        (1.0, 0.0),
        (0.995, 0.0015),
        (0.72, 0.032),
        (0.34, 0.048),
        (0.0, 0.0),
        (0.34, -0.034),
        (0.72, -0.020),
        (0.995, -0.0015),
        (1.0, 0.0),
    )


def _sample_tip_strip_candidate_model(source: Path) -> _NativeRebuildModel:
    return _NativeRebuildModel(
        source_path=source,
        surfaces=(
            _NativeSurfaceRecord(
                component="main_wing",
                geom_id="main",
                name="Main Wing",
                caps_group="main_wing",
                symmetric_xz=True,
                sections=(
                    _NativeSectionRecord(
                        x_le=0.0,
                        y_le=0.0,
                        z_le=0.0,
                        chord=1.30,
                        twist_deg=0.0,
                        airfoil_name="NACA 2412",
                        airfoil_source="inline_coordinates",
                        airfoil_coordinates=_sample_airfoil_coords(),
                        thickness_tc=0.12,
                        camber=0.02,
                        camber_loc=0.4,
                    ),
                    _NativeSectionRecord(
                        x_le=0.10,
                        y_le=16.5,
                        z_le=1.70,
                        chord=0.435,
                        twist_deg=0.0,
                        airfoil_name="NACA 2412",
                        airfoil_source="inline_coordinates",
                        airfoil_coordinates=_sample_tip_strip_airfoil_coords(),
                        thickness_tc=0.12,
                        camber=0.02,
                        camber_loc=0.4,
                    ),
                ),
            ),
        ),
        notes=("unit-test-tip-strip-model",),
    )


def test_build_topology_lineage_report_identifies_terminal_tip_strip_candidates(tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")

    report = _build_topology_lineage_report(_sample_tip_strip_candidate_model(source))

    assert report["status"] == "captured"
    assert report["surface_count"] == 1
    surface = report["surfaces"][0]
    candidates = surface["terminal_strip_candidates"]
    assert [candidate["side"] for candidate in candidates] == ["left_tip", "right_tip"]
    assert all(candidate["would_suppress"] is True for candidate in candidates)
    assert all(candidate["source_section_index"] == 1 for candidate in candidates)
    assert all(candidate["seam_adjacent_edge_lengths_m"][0] < 0.003 for candidate in candidates)
    assert all(candidate["seam_adjacent_edge_lengths_m"][1] < 0.003 for candidate in candidates)


def test_apply_terminal_strip_suppression_rewrites_tip_candidate_section(tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    model = _sample_tip_strip_candidate_model(source)

    suppressed_model, report = _apply_terminal_strip_suppression(model)

    assert report["applied"] is True
    surface_report = report["surfaces"][0]
    assert surface_report["suppressed_source_section_indices"] == [1]
    original_coords = model.surfaces[0].sections[1].airfoil_coordinates
    suppressed_coords = suppressed_model.surfaces[0].sections[1].airfoil_coordinates
    assert len(suppressed_coords) < len(original_coords)
    assert suppressed_coords[0] != original_coords[0]
    assert suppressed_coords[-1] == suppressed_coords[0]
    assert surface_report["suppressed_sections"][0]["trim_count_per_side"] >= 1
    assert (
        surface_report["suppressed_sections"][0]["bridge_length_m"]
        >= surface_report["suppressed_sections"][0]["suppression_threshold_m"]
    )


def test_build_autonomous_repair_context_reports_missing_artifacts():
    context = _build_autonomous_repair_context(
        artifacts={
            "mesh_metadata": {"mesh": {"surface_element_count": 107338, "volume_element_count": 129288}, "quality_metrics": {"ill_shaped_tet_count": 5}, "mesh3d_watchdog": {"nodes_created_per_boundary_node": 0.0260466156}},
            "topology_suppression_report": {"surfaces": [{"suppressed_sections": [{"trim_count_per_side": 3}]}]},
        }
    )

    assert context["mesh_only_no_go"] is True
    assert "topology_lineage_report" in context["missing_artifacts"]


def test_build_tip_topology_diagnostics_flags_residual_sliver_sensitive_topology(tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    model = _sample_tip_strip_candidate_model(source)
    suppressed_model, suppression_report = _apply_terminal_strip_suppression(model)
    lineage_report = _build_topology_lineage_report(suppressed_model)

    diagnostics = _build_tip_topology_diagnostics(
        rebuild_model=suppressed_model,
        topology_lineage_report=lineage_report,
        topology_suppression_report=suppression_report,
        hotspot_patch_report={
            "surface_reports": [
                {"surface_id": 30, "worst_tets_near_this_surface": {"count": 4}},
                {"surface_id": 21, "worst_tets_near_this_surface": {"count": 1}},
            ]
        },
        active_hotspot_family={
            "primary": ["tip-adjacent panel family"],
            "observed_surfaces": [30, 21],
            "legacy_surfaces": [31, 32],
        },
    )

    assert diagnostics["source_section_index"] == 1
    assert diagnostics["classification"]["has_residual_sliver_sensitive_topology"] is True
    assert diagnostics["terminal_tip_neighborhood"]["trim_count_per_side"] >= 1
    assert diagnostics["terminal_tip_neighborhood"]["candidate_bad_panels"]


def test_generate_bounded_tip_topology_repair_candidates_skips_egads_when_unavailable(tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    model = _sample_tip_strip_candidate_model(source)
    suppressed_model, suppression_report = _apply_terminal_strip_suppression(model)
    lineage_report = _build_topology_lineage_report(suppressed_model)
    diagnostics = _build_tip_topology_diagnostics(
        rebuild_model=suppressed_model,
        topology_lineage_report=lineage_report,
        topology_suppression_report=suppression_report,
        hotspot_patch_report={"surface_reports": []},
        active_hotspot_family={
            "primary": ["tip-adjacent panel family"],
            "observed_surfaces": [30, 21],
            "legacy_surfaces": [31, 32],
        },
    )

    candidates = _generate_bounded_tip_topology_repair_candidates(
        baseline_rebuild_model=suppressed_model,
        diagnostics=diagnostics,
        egads_effective_topology_available=False,
    )

    candidate_names = [candidate["candidate_name"] for candidate in candidates]
    assert candidate_names == [
        "section5_pairing_smooth_v0",
        "section5_te_pair_coalesce_v0",
        "terminal_tip_cap_rebuild_v0",
        "diagnostic_noop_v2_control",
    ]
    assert all(candidate["old_face_to_new_face_map"] for candidate in candidates)


def test_geometry_filter_rejects_missing_face_map_and_lost_groups():
    decision = _geometry_filter_decision(
        candidate_report={
            "candidate_name": "section5_pairing_smooth_v0",
            "old_face_to_new_face_map": {},
        },
        brep_hotspot_report={"shape_valid_default": True, "shape_valid_exact": True},
        provider_metadata={"physical_groups_preserved": False, "physical_group_remap": {}},
        candidate_hotspot_patch_report_2d={"surface_reports": []},
        mesh_metadata={"status": "success", "mesh": {"surface_element_count": 107338}},
        baseline_reference={"surface_triangle_count": 107338, "tip_surface_min_gamma": 0.03},
    )

    assert decision["passed"] is False
    assert "old_face_to_new_face_map_missing" in decision["hard_reject_reasons"]
    assert "physical_groups_lost_without_remap" in decision["hard_reject_reasons"]


def test_geometry_filter_rejects_invalid_brep_and_generate2_failure():
    decision = _geometry_filter_decision(
        candidate_report={
            "candidate_name": "section5_pairing_smooth_v0",
            "old_face_to_new_face_map": {"legacy_surface_30": {"repaired_panel_family": "tip"}},
        },
        brep_hotspot_report={"shape_valid_default": False, "shape_valid_exact": False},
        provider_metadata={
            "physical_groups_preserved": True,
            "physical_group_remap": {},
            "tip_topology_diagnostics": {
                "terminal_tip_neighborhood": {
                    "width_length_ratios": [0.006],
                    "panel_widths_m": [0.0052],
                    "consecutive_width_ratio_max": 2.0,
                    "candidate_bad_panels": [],
                },
                "classification": {"has_residual_sliver_sensitive_topology": False},
            },
        },
        candidate_hotspot_patch_report_2d={"surface_reports": []},
        mesh_metadata={"status": "failed", "mesh": {"surface_element_count": 107338}},
        baseline_reference={
            "surface_triangle_count": 107338,
            "tip_surface_min_gamma": 0.03,
            "min_width_length_ratio": 0.005,
            "min_panel_width_m": 0.005055,
            "max_consecutive_width_ratio": 2.5,
        },
    )

    assert decision["passed"] is False
    assert "generate_2d_failed" in decision["hard_reject_reasons"]
    assert "brep_invalid_default" in decision["hard_reject_reasons"]
    assert "brep_invalid_exact" in decision["hard_reject_reasons"]


def test_geometry_filter_accepts_surface_mesh_only_probe_as_generate2_returned():
    decision = _geometry_filter_decision(
        candidate_report={
            "candidate_name": "section5_pairing_smooth_v0",
            "old_face_to_new_face_map": {"legacy_surface_30": {"repaired_panel_family": "tip"}},
        },
        brep_hotspot_report={"shape_valid_default": True, "shape_valid_exact": True},
        provider_metadata={
            "physical_groups_preserved": True,
            "physical_group_remap": {},
            "tip_topology_diagnostics": {
                "terminal_tip_neighborhood": {
                    "width_length_ratios": [0.006],
                    "panel_widths_m": [0.0052],
                    "consecutive_width_ratio_max": 2.0,
                    "candidate_bad_panels": [],
                },
                "classification": {"has_residual_sliver_sensitive_topology": False},
            },
        },
        candidate_hotspot_patch_report_2d={"surface_reports": []},
        mesh_metadata={
            "status": "surface_mesh_only",
            "mesh": {"surface_element_count": 107100, "volume_element_count": 0},
        },
        baseline_reference={
            "surface_triangle_count": 107338,
            "tip_surface_min_gamma": 0.03,
            "min_width_length_ratio": 0.005,
            "min_panel_width_m": 0.005055,
            "max_consecutive_width_ratio": 2.5,
        },
    )

    assert decision["generate_2d_returned"] is True
    assert "generate_2d_failed" not in decision["hard_reject_reasons"]


def test_select_top_geometry_candidates_only_keeps_two_best():
    selected = _select_top_geometry_candidates(
        [
            {"candidate_name": "a", "geometry_filter_passed": True, "geometry_score": 7.0},
            {"candidate_name": "b", "geometry_filter_passed": True, "geometry_score": 5.0},
            {"candidate_name": "c", "geometry_filter_passed": True, "geometry_score": 6.0},
            {"candidate_name": "d", "geometry_filter_passed": False, "geometry_score": 9.0},
        ]
    )

    assert [entry["candidate_name"] for entry in selected] == ["a", "c"]


def test_select_topology_repair_winner_requires_quality_clean_pass():
    winner = _select_topology_repair_winner(
        [
            {
                "name": "section5_pairing_smooth_v0",
                "generate_2d_returned": True,
                "generate_3d_returned": True,
                "brep_valid_default": True,
                "brep_valid_exact": True,
                "physical_groups_preserved": True,
                "surface_triangle_count": 107200,
                "volume_element_count": 129000,
                "nodes_created_per_boundary_node": 0.03,
                "timeout_phase_classification": "optimization",
                "ill_shaped_tet_count": 1,
                "min_volume": 1.0e-9,
                "minSICN": 1.0e-3,
                "minSIGE": 0.01,
                "geometry_delta_m": 1.0e-4,
            }
        ]
    )
    assert winner is None


def test_select_topology_repair_winner_prefers_lowest_volume_then_surface_count():
    winner = _select_topology_repair_winner(
        [
            {
                "name": "candidate_a",
                "generate_2d_returned": True,
                "generate_3d_returned": True,
                "brep_valid_default": True,
                "brep_valid_exact": True,
                "physical_groups_preserved": True,
                "surface_triangle_count": 108000,
                "volume_element_count": 128500,
                "nodes_created_per_boundary_node": 0.03,
                "timeout_phase_classification": "optimization",
                "ill_shaped_tet_count": 0,
                "min_volume": 1.0e-9,
                "minSICN": 0.01,
                "minSIGE": 0.02,
                "geometry_delta_m": 1.0e-4,
                "physical_group_remap": {},
            },
            {
                "name": "candidate_b",
                "generate_2d_returned": True,
                "generate_3d_returned": True,
                "brep_valid_default": True,
                "brep_valid_exact": True,
                "physical_groups_preserved": True,
                "surface_triangle_count": 107500,
                "volume_element_count": 127900,
                "nodes_created_per_boundary_node": 0.03,
                "timeout_phase_classification": "optimization",
                "ill_shaped_tet_count": 0,
                "min_volume": 1.0e-9,
                "minSICN": 0.01,
                "minSIGE": 0.02,
                "geometry_delta_m": 2.0e-4,
                "physical_group_remap": {},
            },
        ]
    )

    assert winner is not None
    assert winner["name"] == "candidate_b"


def test_evaluate_topology_repair_candidate_records_bounded_3d_timeout(monkeypatch, tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    candidate_dir = tmp_path / "candidate"
    watchdog_path = candidate_dir / "mesh_3d" / "artifacts" / "mesh" / "mesh3d_watchdog.json"
    watchdog_path.parent.mkdir(parents=True, exist_ok=True)
    watchdog_path.write_text(
        json.dumps(
            {
                "timeout_phase_classification": "optimization",
                "meshing_stage_at_timeout": "optimization",
                "nodes_created_per_boundary_node": 0.03,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    candidate = {
        "candidate_name": "section5_pairing_smooth_v0",
        "repair_type": "pairing_smooth",
        "report": {
            "candidate_name": "section5_pairing_smooth_v0",
            "repair_type": "pairing_smooth",
            "changes": {"max_geometry_delta_m": 1.0e-4},
            "old_face_to_new_face_map": {"legacy_surface_30": {"repaired_panel_family": "tip"}},
            "physical_group_remap": {},
        },
    }
    existing_evaluation = {
        "name": "section5_pairing_smooth_v0",
        "repair_type": "pairing_smooth",
        "geometry_filter_passed": True,
        "geometry_score": 9.0,
        "hard_reject_reasons": [],
        "ran_3d": False,
        "generate_2d_returned": True,
        "generate_3d_returned": False,
        "surface_triangle_count": 107338,
        "volume_element_count": None,
        "ill_shaped_tet_count": None,
        "nodes_created_per_boundary_node": None,
        "brep_valid_default": True,
        "brep_valid_exact": True,
        "physical_groups_preserved": True,
        "physical_group_remap": {},
        "old_face_to_new_face_map_path": str(candidate_dir / "old_face_to_new_face_map.json"),
        "failure_reason": "",
        "timeout_phase_classification": None,
        "min_volume": None,
        "minSICN": None,
        "minSIGE": None,
        "geometry_delta_m": 1.0e-4,
        "artifacts": {},
        "_provider_result": object(),
        "_handle": object(),
        "_mesh2d": {"mesh": {"surface_element_count": 107338}},
        "_tip_focus_surface_tags": [30, 21],
    }

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._execute_mesh_run_bounded",
        lambda **_: {
            "status": "timeout",
            "mesh_metadata": None,
            "artifacts": {"mesh3d_watchdog": str(watchdog_path)},
            "error": "bounded_mesh_timeout_after_90.0s",
        },
    )
    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._collect_candidate_sliver_cluster_report",
        lambda **kwargs: {
            "baseline": kwargs["baseline"],
            "ill_shaped_tet_count": 0,
            "bad_tets": [],
            "clusters": [],
        },
    )

    evaluation = _evaluate_topology_repair_candidate(
        candidate=candidate,
        source_path=source,
        component="main_wing",
        base_config=_build_autonomous_topology_base_config(
            source_path=source,
            out_dir=tmp_path / "mesh_base",
            baseline_report={
                "component": "main_wing",
                "geometry_source": "esp_rebuilt",
                "geometry_provider": "esp_rebuilt",
                "geometry_family": "thin_sheet_lifting_surface",
                "run": {
                    "backend_result": {
                        "provenance": {
                            "mesh_field": {
                                "mesh_algorithm_2d": 6,
                                "mesh_algorithm_3d": 1,
                            }
                        }
                    }
                },
            },
        ),
        candidate_dir=candidate_dir,
        source_section_index=5,
        baseline_reference={},
        baseline_artifacts={"autonomous_repair_context": {"baseline": "shell_v2_strip_suppression"}},
        topology_suppression_report={},
        run_3d=True,
        existing_evaluation=existing_evaluation,
    )

    assert evaluation["ran_3d"] is True
    assert evaluation["generate_3d_returned"] is False
    assert evaluation["timeout_phase_classification"] == "optimization"
    assert evaluation["failure_reason"] == "generate_3d_timeout_optimization"
    assert evaluation["artifacts"]["mesh3d_watchdog"] == str(watchdog_path)


def test_evaluate_topology_repair_candidate_preserves_geometry_report_fields_on_3d_rerun(tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    report_path = candidate_dir / "candidate_topology_repair_report.json"
    report_path.write_text(
        json.dumps(
            {
                "candidate_name": "section5_pairing_smooth_v0",
                "repair_type": "pairing_smooth",
                "geometry_filter_passed": True,
                "geometry_score": 9.0,
                "hard_reject_reasons": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    _evaluate_topology_repair_candidate(
        candidate={
            "candidate_name": "section5_pairing_smooth_v0",
            "repair_type": "pairing_smooth",
            "report": {
                "candidate_name": "section5_pairing_smooth_v0",
                "repair_type": "pairing_smooth",
                "changes": {"max_geometry_delta_m": 1.0e-4},
                "old_face_to_new_face_map": {"legacy_surface_30": {"repaired_panel_family": "tip"}},
                "physical_group_remap": {},
            },
        },
        source_path=source,
        component="main_wing",
        base_config=_build_autonomous_topology_base_config(
            source_path=source,
            out_dir=tmp_path / "mesh_base",
            baseline_report={
                "component": "main_wing",
                "geometry_source": "esp_rebuilt",
                "geometry_provider": "esp_rebuilt",
                "geometry_family": "thin_sheet_lifting_surface",
                "run": {"backend_result": {"provenance": {"mesh_field": {}}}},
            },
        ),
        candidate_dir=candidate_dir,
        source_section_index=5,
        baseline_reference={},
        baseline_artifacts={"autonomous_repair_context": {"baseline": "shell_v2_strip_suppression"}},
        topology_suppression_report={},
        run_3d=False,
        existing_evaluation={
            "name": "section5_pairing_smooth_v0",
            "repair_type": "pairing_smooth",
            "geometry_filter_passed": True,
            "geometry_score": 9.0,
            "hard_reject_reasons": [],
            "ran_3d": False,
            "generate_2d_returned": True,
            "generate_3d_returned": False,
            "surface_triangle_count": 107338,
            "volume_element_count": None,
            "ill_shaped_tet_count": None,
            "nodes_created_per_boundary_node": None,
            "brep_valid_default": True,
            "brep_valid_exact": True,
            "physical_groups_preserved": True,
            "physical_group_remap": {},
            "old_face_to_new_face_map_path": str(candidate_dir / "old_face_to_new_face_map.json"),
            "failure_reason": "",
            "timeout_phase_classification": None,
            "min_volume": None,
            "minSICN": None,
            "minSIGE": None,
            "geometry_delta_m": 1.0e-4,
            "artifacts": {},
            "_provider_result": object(),
            "_handle": object(),
            "_mesh2d": {"mesh": {"surface_element_count": 107338}},
            "_tip_focus_surface_tags": [30, 21],
        },
    )

    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["geometry_filter_passed"] is True
    assert persisted["geometry_score"] == 9.0


def test_evaluate_topology_repair_candidate_reclassifies_bounded_timeout_after_tetra_creation(
    monkeypatch,
    tmp_path: Path,
):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    candidate_dir = tmp_path / "candidate"
    watchdog_path = candidate_dir / "mesh_3d" / "artifacts" / "mesh" / "mesh3d_watchdog.json"
    watchdog_path.parent.mkdir(parents=True, exist_ok=True)
    watchdog_path.write_text(
        json.dumps(
            {
                "timeout_phase_classification": "volume_insertion",
                "logger_tail": [
                    "Info: 3D refinement terminated (54971 nodes total):",
                    "Info:  - 132219 tetrahedra created in 1.10035 sec. (120160 tets/s)",
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._execute_mesh_run_bounded",
        lambda **_: {
            "status": "timeout",
            "mesh_metadata": None,
            "artifacts": {"mesh3d_watchdog": str(watchdog_path)},
            "error": "bounded_mesh_timeout_after_90.0s",
        },
    )
    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._collect_candidate_sliver_cluster_report",
        lambda **kwargs: {
            "baseline": kwargs["baseline"],
            "ill_shaped_tet_count": 0,
            "bad_tets": [],
            "clusters": [],
        },
    )

    evaluation = _evaluate_topology_repair_candidate(
        candidate={
            "candidate_name": "section5_te_pair_coalesce_v0",
            "repair_type": "te_pair_coalesce",
            "report": {
                "candidate_name": "section5_te_pair_coalesce_v0",
                "repair_type": "te_pair_coalesce",
                "changes": {"max_geometry_delta_m": 2.0e-4},
                "old_face_to_new_face_map": {"legacy_surface_21": {"repaired_panel_family": "tip"}},
                "physical_group_remap": {},
            },
        },
        source_path=source,
        component="main_wing",
        base_config=_build_autonomous_topology_base_config(
            source_path=source,
            out_dir=tmp_path / "mesh_base",
            baseline_report={
                "component": "main_wing",
                "geometry_source": "esp_rebuilt",
                "geometry_provider": "esp_rebuilt",
                "geometry_family": "thin_sheet_lifting_surface",
                "run": {"backend_result": {"provenance": {"mesh_field": {}}}},
            },
        ),
        candidate_dir=candidate_dir,
        source_section_index=5,
        baseline_reference={},
        baseline_artifacts={"autonomous_repair_context": {"baseline": "shell_v2_strip_suppression"}},
        topology_suppression_report={},
        run_3d=True,
        existing_evaluation={
            "name": "section5_te_pair_coalesce_v0",
            "repair_type": "te_pair_coalesce",
            "geometry_filter_passed": True,
            "geometry_score": 9.0,
            "hard_reject_reasons": [],
            "ran_3d": False,
            "generate_2d_returned": True,
            "generate_3d_returned": False,
            "surface_triangle_count": 107338,
            "volume_element_count": None,
            "ill_shaped_tet_count": None,
            "nodes_created_per_boundary_node": None,
            "brep_valid_default": True,
            "brep_valid_exact": True,
            "physical_groups_preserved": True,
            "physical_group_remap": {},
            "old_face_to_new_face_map_path": str(candidate_dir / "old_face_to_new_face_map.json"),
            "failure_reason": "",
            "timeout_phase_classification": None,
            "min_volume": None,
            "minSICN": None,
            "minSIGE": None,
            "geometry_delta_m": 2.0e-4,
            "artifacts": {},
            "_provider_result": object(),
            "_handle": object(),
            "_mesh2d": {"mesh": {"surface_element_count": 107338}},
            "_tip_focus_surface_tags": [30, 21],
        },
    )

    assert evaluation["timeout_phase_classification"] == "optimization"
    assert evaluation["failure_reason"] == "generate_3d_timeout_optimization"


def test_build_upstream_pairing_no_go_summary_records_minimum_failure_package():
    summary = _build_upstream_pairing_no_go_summary()

    assert summary["source_section_index"] == 5
    assert "surface tip buffer" in summary["confirmed_no_go"]
    assert "tip_topology_diagnostics.json" in summary["minimum_information_for_manual_review"]


def test_run_autonomous_tip_topology_repair_controller_stops_on_missing_artifacts(tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")

    result = run_autonomous_tip_topology_repair_controller(
        source_path=source,
        out_dir=tmp_path / "controller_out",
        baseline_run_dir=tmp_path / "missing_baseline",
        sliver_run_dir=tmp_path / "missing_sliver",
    )

    assert result["status"] == "failed"
    context_path = tmp_path / "controller_out" / "autonomous_repair_context.json"
    payload = json.loads(context_path.read_text(encoding="utf-8"))
    assert "topology_lineage_report" in payload["missing_artifacts"]
    assert result["missing_artifacts"]


def test_run_autonomous_tip_topology_repair_controller_records_no_go_when_no_candidate_passes(
    monkeypatch,
    tmp_path: Path,
):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    baseline_dir = tmp_path / "baseline_run"
    sliver_dir = tmp_path / "sliver_run"
    baseline_mesh_dir = baseline_dir / "artifacts" / "mesh"
    baseline_provider_dir = baseline_dir / "artifacts" / "providers" / "esp_rebuilt" / "esp_runtime"
    baseline_mesh_dir.mkdir(parents=True, exist_ok=True)
    baseline_provider_dir.mkdir(parents=True, exist_ok=True)
    sliver_dir.mkdir(parents=True, exist_ok=True)
    (baseline_dir / "report.json").write_text(
        json.dumps(
            {
                "component": "main_wing",
                "geometry_source": "esp_rebuilt",
                "geometry_provider": "esp_rebuilt",
                "geometry_family": "thin_sheet_lifting_surface",
                "provider": {
                    "provider": "esp_rebuilt",
                    "provider_stage": "experimental",
                    "status": "materialized",
                    "geometry_source": "esp_rebuilt",
                    "source_path": str(source),
                    "normalized_geometry_path": str(source.with_suffix(".step")),
                    "geometry_family_hint": "thin_sheet_lifting_surface",
                    "provider_version": "test",
                    "topology": {
                        "representation": "brep_trimmed_step",
                        "source_kind": "stp",
                        "units": "m",
                        "body_count": 1,
                        "surface_count": 32,
                        "volume_count": 1,
                        "labels_present": True,
                        "label_schema": "preserve_component_labels",
                        "normalization": {"applied": False},
                        "notes": [],
                    },
                    "artifacts": {},
                    "provenance": {},
                    "warnings": [],
                    "notes": [],
                },
                "run": {
                    "backend_result": {
                        "provenance": {
                            "mesh_field": {
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
                                "mesh_algorithm_2d": 6,
                                "mesh_algorithm_3d": 1,
                                "distance_max": 0.434375,
                                "edge_distance_max": 0.434375,
                                "volume_smoke_decoupled": {
                                    "enabled": True,
                                    "base_far_volume_field": {"size": 12.0},
                                    "near_body_shell": {
                                        "enabled": True,
                                        "dist_min": 0.0,
                                        "dist_max": 0.18,
                                        "size_max": 3.0,
                                        "stop_at_dist_max": True,
                                    },
                                },
                            }
                        }
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (baseline_provider_dir / "topology_lineage_report.json").write_text(
        json.dumps({"surfaces": [{"terminal_strip_candidates": [{"source_section_index": 5, "would_suppress": True}]}]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (baseline_provider_dir / "topology_suppression_report.json").write_text(
        json.dumps({"surfaces": [{"suppressed_sections": [{"source_section_index": 5, "trim_count_per_side": 3, "before_profile_point_count": 61, "bridge_length_m": 0.005055}]}]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (baseline_mesh_dir / "hotspot_patch_report.json").write_text(
        json.dumps({"surface_reports": [{"surface_id": 30, "worst_tets_near_this_surface": {"count": 4}}, {"surface_id": 21, "worst_tets_near_this_surface": {"count": 1}}]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (baseline_mesh_dir / "brep_hotspot_report.json").write_text(
        json.dumps({"shape_valid_default": True, "shape_valid_exact": True}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (baseline_mesh_dir / "mesh_metadata.json").write_text(
        json.dumps(
            {
                "mesh": {"surface_element_count": 107338, "volume_element_count": 129288},
                "quality_metrics": {"ill_shaped_tet_count": 5},
                "mesh3d_watchdog": {"nodes_created_per_boundary_node": 0.0260466156},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (baseline_mesh_dir / "surface_patch_diagnostics.json").write_text(
        json.dumps({"surface_records": [], "curve_records": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (baseline_mesh_dir / "surface_mesh_2d.msh").write_text("$MeshFormat\n4.1 0 8\n$EndMeshFormat\n", encoding="utf-8")
    (baseline_mesh_dir / "mesh3d_watchdog.json").write_text(
        json.dumps({"nodes_created_per_boundary_node": 0.0260466156}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (sliver_dir / "sliver_cluster_report.json").write_text(
        json.dumps({"baseline": "shell_v2_strip_suppression", "ill_shaped_tet_count": 5, "bad_tets": [], "clusters": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (sliver_dir / "sliver_volume_pocket_summary.json").write_text(
        json.dumps({"baseline": "shell_v2_strip_suppression", "winner": None, "mesh_only_no_go": True}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (sliver_dir / "rule_loft_pairing_repair_spec.json").write_text(
        json.dumps({"source_section_index": 5, "bad_aggressive_probe": {"effect": "spread"}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    model = _sample_tip_strip_candidate_model(source)
    suppressed_model, suppression_report = _apply_terminal_strip_suppression(model)
    diagnostics = _build_tip_topology_diagnostics(
        rebuild_model=suppressed_model,
        topology_lineage_report=_build_topology_lineage_report(suppressed_model),
        topology_suppression_report=suppression_report,
        hotspot_patch_report={"surface_reports": []},
        active_hotspot_family={
            "primary": ["tip-adjacent panel family"],
            "observed_surfaces": [30, 21],
            "legacy_surfaces": [31, 32],
        },
    )

    candidate_control = _generate_bounded_tip_topology_repair_candidates(
        baseline_rebuild_model=suppressed_model,
        diagnostics=diagnostics,
        egads_effective_topology_available=False,
    )[-1]
    candidate_probe = _generate_bounded_tip_topology_repair_candidates(
        baseline_rebuild_model=suppressed_model,
        diagnostics=diagnostics,
        egads_effective_topology_available=False,
    )[0]

    def fake_prepare_component_input_model(**kwargs):
        assert kwargs["artifact_dir"].exists()
        return _ComponentInputModel(
            input_model_path=source,
            notes=[],
            provenance={"requested_component": "main_wing"},
            artifacts={},
        )

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._prepare_component_input_model",
        fake_prepare_component_input_model,
    )
    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._build_native_rebuild_model",
        lambda **_: model,
    )

    def fake_generate_candidates(**_kwargs):
        return [candidate_probe, candidate_control]

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._generate_bounded_tip_topology_repair_candidates",
        fake_generate_candidates,
    )

    def fake_evaluate_candidate(*, candidate, **_kwargs):
        name = candidate["candidate_name"]
        summary = {
            "name": name,
            "repair_type": candidate["repair_type"],
            "geometry_filter_passed": True,
            "geometry_score": 9.0 if name == "section5_pairing_smooth_v0" else 8.0,
            "ran_3d": True,
            "generate_2d_returned": True,
            "generate_3d_returned": True,
            "surface_triangle_count": 107338,
            "volume_element_count": 129288 if name == "diagnostic_noop_v2_control" else 129100,
            "ill_shaped_tet_count": 5 if name == "diagnostic_noop_v2_control" else 3,
            "nodes_created_per_boundary_node": 0.0260466156,
            "brep_valid_default": True,
            "brep_valid_exact": True,
            "physical_groups_preserved": True,
            "physical_group_remap": candidate["report"]["physical_group_remap"],
            "old_face_to_new_face_map_path": str(tmp_path / f"{name}_map.json"),
            "failure_reason": "ill_shaped_tets_present",
            "timeout_phase_classification": "optimization",
            "min_volume": 1.0e-9,
            "minSICN": 1.0e-3,
            "minSIGE": 1.0e-2,
            "geometry_delta_m": float(candidate["report"]["changes"].get("max_geometry_delta_m", 0.0) or 0.0),
            "artifacts": {},
        }
        Path(summary["old_face_to_new_face_map_path"]).write_text(
            json.dumps(candidate["old_face_to_new_face_map"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return summary

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._evaluate_topology_repair_candidate",
        fake_evaluate_candidate,
    )

    result = run_autonomous_tip_topology_repair_controller(
        source_path=source,
        out_dir=tmp_path / "controller_out",
        baseline_run_dir=baseline_dir,
        sliver_run_dir=sliver_dir,
    )

    assert result["status"] == "failed"
    summary = json.loads((tmp_path / "controller_out" / "upstream_topology_repair_summary.json").read_text(encoding="utf-8"))
    no_go = json.loads((tmp_path / "controller_out" / "upstream_pairing_no_go_summary.json").read_text(encoding="utf-8"))
    assert summary["baseline_promoted"] is False
    assert summary["winner"] is None
    assert no_go["source_section_index"] == 5


def test_analyze_symmetry_touching_solids_detects_groups_and_preserves_singleton(tmp_path: Path):
    raw_path = tmp_path / "raw.step"
    _write_boxes_step(raw_path, _raw_symmetry_boxes())

    analysis = _analyze_symmetry_touching_solids(raw_path)

    assert analysis.body_count == 5
    assert len(analysis.touching_groups) == 2
    assert analysis.singleton_body_tags == [5]
    assert analysis.grouped_body_tags == [1, 2, 3, 4]
    assert len(analysis.duplicate_face_pairs) >= 2
    assert len(analysis.internal_cap_face_tags) >= 4


def test_combine_union_groups_with_singletons_produces_clean_external_geometry(tmp_path: Path):
    raw_path = tmp_path / "raw.step"
    union_path = tmp_path / "unioned.step"
    combined_path = tmp_path / "combined.step"
    _write_boxes_step(raw_path, _raw_symmetry_boxes())
    _write_boxes_step(union_path, _unioned_boxes())

    raw_topology = _probe_step_topology(raw_path, tmp_path)
    union_topology = _probe_step_topology(union_path, tmp_path)

    _combine_union_groups_with_singletons(
        raw_step_path=raw_path,
        raw_topology=raw_topology,
        singleton_body_tags=[5],
        union_step_path=union_path,
        union_topology=union_topology,
        output_path=combined_path,
    )

    final_analysis = _analyze_symmetry_touching_solids(combined_path)
    final_topology = _probe_step_topology(combined_path, tmp_path)

    assert final_topology.body_count == 3
    assert final_topology.surface_count == 18
    assert final_analysis.touching_groups == []
    assert final_analysis.duplicate_face_pairs == []
    assert final_analysis.internal_cap_face_tags == []


def test_materialize_with_esp_reports_normalization_before_after_counts(monkeypatch, tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    staging = tmp_path / "provider"
    raw_template = tmp_path / "raw_template.step"
    union_template = tmp_path / "union_template.step"
    _write_boxes_step(raw_template, _raw_symmetry_boxes())
    _write_boxes_step(union_template, _unioned_boxes())

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline.load_openvsp_reference_data",
        lambda _: {"ref_length": 1.0},
    )
    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._build_native_rebuild_model",
        lambda **_: _sample_native_rebuild_model(source),
    )

    def fake_runner(args, cwd):
        script_name = Path(args[-1]).name
        if script_name == "rebuild.csm":
            target = Path(cwd) / "raw_dump.stp"
            target.write_bytes(raw_template.read_bytes())
        elif script_name == "union_groups.csm":
            target = Path(cwd) / "union_groups.step"
            target.write_bytes(union_template.read_bytes())
        else:
            raise AssertionError(f"unexpected script {script_name}")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{script_name} ok\n", stderr="")

    result = materialize_with_esp(
        source_path=source,
        staging_dir=staging,
        runner=fake_runner,
        batch_binary="/opt/esp/bin/serveCSM",
    )

    assert result.status == "success"
    assert result.topology is not None
    normalization = result.topology.normalization
    assert normalization["applied"] is True
    assert normalization["raw_counts"]["body_count"] == 5
    assert normalization["normalized_counts"]["body_count"] == 3
    assert normalization["raw_analysis"]["grouped_body_tags"] == [1, 2, 3, 4]
    assert normalization["raw_analysis"]["singleton_body_tags"] == [5]
    assert normalization["raw_analysis"]["internal_cap_face_count"] >= 4
    assert normalization["final_analysis"]["touching_groups"] == []
    assert normalization["final_analysis"]["duplicate_interface_face_pair_count"] == 0


def test_materialize_with_esp_uses_component_subset_in_union_script(monkeypatch, tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    staging = tmp_path / "provider"
    subset_path = staging / "esp_runtime" / "main_wing.vsp3"
    raw_template = tmp_path / "raw_template.step"
    union_template = tmp_path / "union_template.step"
    _write_boxes_step(raw_template, _raw_symmetry_boxes())
    _write_boxes_step(union_template, _unioned_boxes())

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._prepare_component_input_model",
        lambda **_: _ComponentInputModel(
            input_model_path=subset_path,
            notes=["component_subset_exported=main_wing"],
            provenance={"requested_component": "main_wing"},
            artifacts={},
        ),
    )
    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline.load_openvsp_reference_data",
        lambda _: {"ref_length": 1.0},
    )
    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._build_native_rebuild_model",
        lambda **_: _sample_native_rebuild_model(subset_path),
    )

    def fake_runner(args, cwd):
        script_name = Path(args[-1]).name
        if script_name == "rebuild.csm":
            (Path(cwd) / "raw_dump.stp").write_bytes(raw_template.read_bytes())
        elif script_name == "union_groups.csm":
            union_script_text = (staging / "esp_runtime" / "union_groups.csm").read_text(encoding="utf-8")
            assert "UDPRIM vsp3" not in union_script_text
            assert "rule" in union_script_text.lower()
            assert "main_wing" in union_script_text
            (Path(cwd) / "union_groups.step").write_bytes(union_template.read_bytes())
        else:
            raise AssertionError(f"unexpected script {script_name}")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{script_name} ok\n", stderr="")

    result = materialize_with_esp(
        source_path=source,
        staging_dir=staging,
        component="main_wing",
        runner=fake_runner,
        batch_binary="/opt/esp/bin/serveCSM",
    )

    assert result.status == "success"


def test_analyze_symmetry_touching_solids_does_not_fuse_non_mirrored_touching_boxes(tmp_path: Path):
    raw_path = tmp_path / "touching_but_not_mirrored.step"
    _write_boxes_step(
        raw_path,
        [
            (0.0, 0.0, 0.0, 1.0, 1.0, 0.10),
            (1.0, 0.2, 0.0, 0.5, 0.6, 0.10),
            (3.0, -0.5, 0.0, 0.4, 1.0, 0.10),
        ],
    )

    analysis = _analyze_symmetry_touching_solids(raw_path)

    assert analysis.touching_groups == []
    assert analysis.grouped_body_tags == []
    assert analysis.singleton_body_tags == [1, 2, 3]


def test_select_component_candidate_distinguishes_main_horizontal_and_vertical_tail():
    candidates = [
        _VspWingCandidate(
            geom_id="main",
            name="Main Wing",
            type_name="Wing",
            normalized_name="mainwing",
            is_symmetric_xz=True,
            x_location=0.0,
            x_rotation_deg=0.0,
            bbox_min=(0.0, 0.0, -0.05),
            bbox_max=(1.3, 16.5, 0.83),
        ),
        _VspWingCandidate(
            geom_id="htail",
            name="Elevator",
            type_name="Wing",
            normalized_name="elevator",
            is_symmetric_xz=True,
            x_location=4.0,
            x_rotation_deg=0.0,
            bbox_min=(4.0, 0.0, -0.04),
            bbox_max=(4.8, 1.5, 0.04),
        ),
        _VspWingCandidate(
            geom_id="vtail",
            name="Fin",
            type_name="Wing",
            normalized_name="fin",
            is_symmetric_xz=False,
            x_location=5.0,
            x_rotation_deg=90.0,
            bbox_min=(5.0, -0.03, -0.7),
            bbox_max=(5.7, 0.03, 1.7),
        ),
    ]

    assert _select_component_candidate("main_wing", candidates).geom_id == "main"
    assert _select_component_candidate("horizontal_tail", candidates).geom_id == "htail"
    assert _select_component_candidate("tail_wing", candidates).geom_id == "htail"
    assert _select_component_candidate("vertical_tail", candidates).geom_id == "vtail"


class _FakePoint:
    def __init__(self, x: float, y: float, z: float):
        self.x = x
        self.y = y
        self.z = z


class _FakeOpenVsp:
    SET_ALL = 0
    SYM_XZ = 2
    NO_END_CAP = 0
    FLAT_END_CAP = 1
    ROUND_END_CAP = 2
    EDGE_END_CAP = 3
    SHARP_END_CAP = 4
    POINT_END_CAP = 5
    ROUND_EXT_END_CAP_NONE = 6
    ROUND_EXT_END_CAP_LE = 7
    ROUND_EXT_END_CAP_TE = 8
    ROUND_EXT_END_CAP_BOTH = 9

    def __init__(self) -> None:
        self._geom_data = {
            "main": {
                "name": "Main Wing",
                "type_name": "Wing",
                "bbox_min": (0.0, 0.0, -0.05),
                "bbox_max": (1.3, 16.5, 0.83),
                "parms": {
                    ("Sym", "Sym_Planar_Flag"): float(self.SYM_XZ),
                    ("XForm", "X_Location"): 0.0,
                    ("XForm", "X_Rotation"): 0.0,
                },
                "xsecs": [
                    {
                        "shape": 12,
                        "params": {
                            "Root_Chord": 1.0,
                            "Tip_Chord": 1.3,
                            "Sweep": 0.0,
                            "Dihedral": 0.0,
                            "Twist": 0.0,
                            "ThickChord": 0.1409,
                            "SectTess_U": 6.0,
                            "TE_Close_Thick": 0.0,
                            "TE_Close_Thick_Chord": 0.0,
                            "LE_Cap_Type": float(self.FLAT_END_CAP),
                            "TE_Cap_Type": float(self.FLAT_END_CAP),
                        },
                    },
                    {
                        "shape": 12,
                        "params": {
                            "Root_Chord": 0.83,
                            "Tip_Chord": 0.435,
                            "Sweep": 1.91,
                            "Dihedral": 5.0,
                            "Twist": 0.0,
                            "ThickChord": 0.1173,
                            "SectTess_U": 15.0,
                            "TE_Close_Thick": 0.0,
                            "TE_Close_Thick_Chord": 0.0,
                            "LE_Cap_Type": float(self.FLAT_END_CAP),
                            "TE_Cap_Type": float(self.ROUND_EXT_END_CAP_TE),
                        },
                    },
                ],
            },
            "htail": {
                "name": "Elevator",
                "type_name": "Wing",
                "bbox_min": (4.0, 0.0, -0.04),
                "bbox_max": (4.8, 1.5, 0.04),
                "parms": {
                    ("Sym", "Sym_Planar_Flag"): float(self.SYM_XZ),
                    ("XForm", "X_Location"): 4.0,
                    ("XForm", "X_Rotation"): 0.0,
                },
                "xsecs": [
                    {
                        "shape": 7,
                        "params": {
                            "Root_Chord": 1.0,
                            "Tip_Chord": 0.8,
                            "Sweep": 0.0,
                            "Dihedral": 0.0,
                            "Twist": 0.0,
                            "ThickChord": 0.09,
                            "SectTess_U": 6.0,
                            "TE_Close_Thick": 0.0,
                            "TE_Close_Thick_Chord": 0.0,
                            "LE_Cap_Type": float(self.FLAT_END_CAP),
                            "TE_Cap_Type": float(self.FLAT_END_CAP),
                        },
                    }
                ],
            },
        }
        self._geom_ids = list(self._geom_data)

    def ClearVSPModel(self) -> None:
        self._geom_ids = list(self._geom_data)

    def ReadVSPFile(self, _path: str) -> None:
        self._geom_ids = list(self._geom_data)

    def Update(self) -> None:
        return None

    def FindGeoms(self):
        return list(self._geom_ids)

    def GetGeomTypeName(self, geom_id: str) -> str:
        return self._geom_data[geom_id]["type_name"]

    def GetGeomName(self, geom_id: str) -> str:
        return self._geom_data[geom_id]["name"]

    def GetGeomBBoxMin(self, geom_id: str) -> _FakePoint:
        return _FakePoint(*self._geom_data[geom_id]["bbox_min"])

    def GetGeomBBoxMax(self, geom_id: str) -> _FakePoint:
        return _FakePoint(*self._geom_data[geom_id]["bbox_max"])

    def FindParm(self, geom_id: str, parm_name: str, group: str):
        if (group, parm_name) in self._geom_data[geom_id]["parms"]:
            return ("geom", geom_id, group, parm_name)
        return ""

    def GetParmVal(self, parm_ref):
        if parm_ref and parm_ref[0] == "geom":
            _, geom_id, group, parm_name = parm_ref
            return self._geom_data[geom_id]["parms"][(group, parm_name)]
        if parm_ref and parm_ref[0] == "xsec":
            _, geom_id, index, parm_name = parm_ref
            return self._geom_data[geom_id]["xsecs"][index]["params"][parm_name]
        raise KeyError(parm_ref)

    def GetGeomChildren(self, _geom_id: str):
        return []

    def GetXSecSurf(self, geom_id: str, _index: int):
        return geom_id

    def GetNumXSec(self, xsec_surf: str) -> int:
        return len(self._geom_data[xsec_surf]["xsecs"])

    def GetXSec(self, xsec_surf: str, index: int):
        return (xsec_surf, index)

    def GetXSecShape(self, xsec_ref) -> int:
        geom_id, index = xsec_ref
        return self._geom_data[geom_id]["xsecs"][index]["shape"]

    def GetXSecParm(self, xsec_ref, parm_name: str):
        geom_id, index = xsec_ref
        if parm_name in self._geom_data[geom_id]["xsecs"][index]["params"]:
            return ("xsec", geom_id, index, parm_name)
        return ""

    def DeleteGeomVec(self, delete_ids):
        self._geom_ids = [geom_id for geom_id in self._geom_ids if geom_id not in set(delete_ids)]

    def WriteVSPFile(self, path: str, _set_index: int) -> None:
        Path(path).write_text("<vsp3/>", encoding="utf-8")


def test_prepare_component_input_model_writes_wing_component_report(monkeypatch, tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._load_openvsp",
        lambda: _FakeOpenVsp(),
    )

    result = _prepare_component_input_model(
        source_path=source,
        artifact_dir=artifact_dir,
        component="main_wing",
    )

    wing_report_path = result.artifacts["wing_component_report"]
    wing_report = json.loads(wing_report_path.read_text(encoding="utf-8"))
    assert wing_report["selected_geom_id"] == "main"
    selected = next(item for item in wing_report["candidates"] if item["geom_id"] == "main")
    terminal = selected["section_report"]["terminal_section"]
    assert terminal["params"]["Tip_Chord"] == 0.435
    assert terminal["params"]["LE_Cap_Type_Name"] == "FLAT_END_CAP"
    assert terminal["params"]["TE_Cap_Type_Name"] == "ROUND_EXT_END_CAP_TE"


class _FakeAirfoilPoint:
    def __init__(self, x: float, y: float, z: float):
        self.x = x
        self.y = y
        self.z = z


class _FakeNativeOpenVsp(_FakeOpenVsp):
    XS_FOUR_SERIES = 7
    XS_FILE_AIRFOIL = 1

    def __init__(self) -> None:
        super().__init__()
        self._geom_data["main"]["parms"].update(
            {
                ("XForm", "Y_Location"): 0.0,
                ("XForm", "Z_Location"): 0.0,
                ("XForm", "Y_Rotation"): 0.0,
                ("XForm", "Z_Rotation"): 0.0,
            }
        )
        self._geom_data["main"]["xsecs"] = [
            {
                "shape": self.XS_FOUR_SERIES,
                "params": {
                    "Root_Chord": 1.30,
                    "Tip_Chord": 1.30,
                    "Sweep": 0.0,
                    "Sweep_Location": 0.25,
                    "Span": 0.0,
                    "Dihedral": 0.0,
                    "Twist": 0.0,
                    "ThickChord": 0.1409,
                    "Camber": 0.02,
                    "CamberLoc": 0.4,
                },
            },
            {
                "shape": self.XS_FOUR_SERIES,
                "params": {
                    "Root_Chord": 1.30,
                    "Tip_Chord": 0.435,
                    "Sweep": 1.91,
                    "Sweep_Location": 0.25,
                    "Span": 16.5,
                    "Dihedral": 5.0,
                    "Twist": 0.0,
                    "ThickChord": 0.1173,
                    "Camber": 0.02,
                    "CamberLoc": 0.4,
                },
            },
        ]
        self._geom_data["htail"]["parms"].update(
            {
                ("XForm", "Y_Location"): 0.0,
                ("XForm", "Z_Location"): 0.0,
                ("XForm", "Y_Rotation"): 0.0,
                ("XForm", "Z_Rotation"): 0.0,
            }
        )
        self._geom_data["htail"]["xsecs"] = [
            {
                "shape": self.XS_FOUR_SERIES,
                "params": {
                    "Root_Chord": 0.8,
                    "Tip_Chord": 0.8,
                    "Sweep": 0.0,
                    "Sweep_Location": 0.25,
                    "Span": 0.0,
                    "Dihedral": 0.0,
                    "Twist": 0.0,
                    "ThickChord": 0.09,
                    "Camber": 0.0,
                    "CamberLoc": 0.4,
                },
            },
            {
                "shape": self.XS_FOUR_SERIES,
                "params": {
                    "Root_Chord": 0.8,
                    "Tip_Chord": 0.7,
                    "Sweep": 4.0,
                    "Sweep_Location": 0.25,
                    "Span": 1.5,
                    "Dihedral": 0.0,
                    "Twist": 0.0,
                    "ThickChord": 0.09,
                    "Camber": 0.0,
                    "CamberLoc": 0.4,
                },
            },
        ]
        self._geom_data["fin"] = {
            "name": "Fin",
            "type_name": "Wing",
            "bbox_min": (5.0, -0.03, -0.7),
            "bbox_max": (5.7, 0.03, 1.7),
            "parms": {
                ("Sym", "Sym_Planar_Flag"): 0.0,
                ("XForm", "X_Location"): 5.0,
                ("XForm", "Y_Location"): 0.0,
                ("XForm", "Z_Location"): -0.7,
                ("XForm", "X_Rotation"): 90.0,
                ("XForm", "Y_Rotation"): 0.0,
                ("XForm", "Z_Rotation"): 0.0,
            },
            "xsecs": [
                {
                    "shape": self.XS_FOUR_SERIES,
                    "params": {
                        "Root_Chord": 0.7,
                        "Tip_Chord": 0.7,
                        "Sweep": 0.0,
                        "Sweep_Location": 0.25,
                        "Span": 0.0,
                        "Dihedral": 0.0,
                        "Twist": 0.0,
                        "ThickChord": 0.09,
                        "Camber": 0.0,
                        "CamberLoc": 0.4,
                    },
                },
                {
                    "shape": self.XS_FOUR_SERIES,
                    "params": {
                        "Root_Chord": 0.7,
                        "Tip_Chord": 0.5,
                        "Sweep": 5.0,
                        "Sweep_Location": 0.25,
                        "Span": 2.4,
                        "Dihedral": 0.0,
                        "Twist": 0.0,
                        "ThickChord": 0.09,
                        "Camber": 0.0,
                        "CamberLoc": 0.4,
                    },
                },
            ],
        }
        self._geom_ids = list(self._geom_data)

    def GetAirfoilUpperPnts(self, xsec_ref):
        geom_id, index = xsec_ref
        chord = self._geom_data[geom_id]["xsecs"][index]["params"].get("Tip_Chord", 1.0)
        return [
            _FakeAirfoilPoint(1.0 * chord, 0.0, 0.0),
            _FakeAirfoilPoint(0.6 * chord, 0.0, 0.05 * chord),
            _FakeAirfoilPoint(0.0, 0.0, 0.0),
        ]

    def GetAirfoilLowerPnts(self, xsec_ref):
        geom_id, index = xsec_ref
        chord = self._geom_data[geom_id]["xsecs"][index]["params"].get("Tip_Chord", 1.0)
        return [
            _FakeAirfoilPoint(0.0, 0.0, 0.0),
            _FakeAirfoilPoint(0.6 * chord, 0.0, -0.04 * chord),
            _FakeAirfoilPoint(1.0 * chord, 0.0, 0.0),
        ]


def test_build_native_rebuild_model_extracts_canonical_surfaces(monkeypatch, tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._load_openvsp",
        lambda: _FakeNativeOpenVsp(),
    )

    model = _build_native_rebuild_model(
        source_path=source,
        component="aircraft_assembly",
    )

    components = [surface.component for surface in model.surfaces]
    assert components == ["main_wing", "horizontal_tail", "vertical_tail"]

    main_wing = model.surfaces[0]
    assert main_wing.symmetric_xz is True
    assert len(main_wing.sections) == 2
    assert main_wing.sections[1].y_le == 16.5
    assert len(main_wing.sections[0].airfoil_coordinates) >= 5

    vertical_tail = model.surfaces[2]
    assert vertical_tail.symmetric_xz is False
    assert vertical_tail.sections[-1].z_le > vertical_tail.sections[0].z_le


def test_materialize_with_esp_writes_native_rule_loft_script(monkeypatch, tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    staging = tmp_path / "provider"

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._build_native_rebuild_model",
        lambda **_: _sample_native_rebuild_model(source),
    )

    def fake_runner(args, cwd):
        exported = Path(cwd) / "raw_dump.stp"
        exported.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="serveCSM ok\n", stderr="")

    result = materialize_with_esp(
        source_path=source,
        staging_dir=staging,
        runner=fake_runner,
        batch_binary="/opt/esp/bin/serveCSM",
    )

    assert result.status == "success"
    script_text = result.script_path.read_text(encoding="utf-8")
    assert "UDPRIM vsp3" not in script_text
    assert "rule" in script_text.lower()
    assert "ATTRIBUTE _name $main_wing" in script_text
    assert "ATTRIBUTE capsGroup $main_wing" in script_text


def test_materialize_with_esp_writes_topology_lineage_report(monkeypatch, tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    staging = tmp_path / "provider"

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._build_native_rebuild_model",
        lambda **_: _sample_tip_strip_candidate_model(source),
    )

    def fake_runner(args, cwd):
        exported = Path(cwd) / "raw_dump.stp"
        exported.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="serveCSM ok\n", stderr="")

    result = materialize_with_esp(
        source_path=source,
        staging_dir=staging,
        runner=fake_runner,
        batch_binary="/opt/esp/bin/serveCSM",
    )

    assert result.status == "success"
    lineage_path = result.artifacts["topology_lineage_report"]
    payload = json.loads(lineage_path.read_text(encoding="utf-8"))
    assert payload["status"] == "captured"
    candidates = payload["surfaces"][0]["terminal_strip_candidates"]
    assert [candidate["side"] for candidate in candidates] == ["left_tip", "right_tip"]
    assert all(candidate["would_suppress"] is True for candidate in candidates)


def test_materialize_with_esp_writes_topology_suppression_report(monkeypatch, tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    staging = tmp_path / "provider"

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._build_native_rebuild_model",
        lambda **_: _sample_tip_strip_candidate_model(source),
    )

    def fake_runner(args, cwd):
        exported = Path(cwd) / "raw_dump.stp"
        exported.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="serveCSM ok\n", stderr="")

    result = materialize_with_esp(
        source_path=source,
        staging_dir=staging,
        runner=fake_runner,
        batch_binary="/opt/esp/bin/serveCSM",
    )

    assert result.status == "success"
    suppression_path = result.artifacts["topology_suppression_report"]
    payload = json.loads(suppression_path.read_text(encoding="utf-8"))
    assert payload["applied"] is True
    assert payload["surfaces"][0]["suppressed_source_section_indices"] == [1]
