from pathlib import Path

from hpa_meshing.schema import (
    AutonomousRepairContext,
    AutonomousRepairActiveHotspotFamily,
    AutonomousRepairBaselineMetrics,
    BaselineConvergenceGate,
    Bounds3D,
    CandidateTopologyRepairReport,
    ConvergenceGateCheck,
    ConvergenceGateSection,
    GeometryProviderRequest,
    GeometryProviderResult,
    GeometryTopologyMetadata,
    MeshArtifactBundle,
    MeshHandoff,
    MeshJobConfig,
    MeshStudyCaseResult,
    MeshStudyComparison,
    MeshStudyReport,
    MeshStudyVerdict,
    SU2CaseArtifacts,
    SU2CaseHandoff,
    SU2ForceSurfaceMarkerGroup,
    SU2ForceSurfaceProvenance,
    SU2GateCheck,
    SU2HistorySummary,
    OverallConvergenceGate,
    SU2ReferenceGeometry,
    SU2ReferenceOverride,
    SU2ReferenceQuantityProvenance,
    SU2ProvenanceGates,
    SU2RuntimeConfig,
    SliverClusterBadTet,
    SliverClusterRecord,
    SliverClusterReport,
    SliverVolumePocketField,
    SliverVolumePocketPolicy,
    SliverVolumePocketVariant,
    TipTopologyDiagnostics,
    TipTopologyDiagnosticsClassification,
    TipTopologyDiagnosticsLineage,
    TipTopologyTerminalNeighborhoodDiagnostics,
    TipQualityBufferPolicy,
    TipQualityBufferVariant,
    UpstreamPairingNoGoSummary,
    UpstreamTopologyRepairCandidateSummary,
    UpstreamTopologyRepairSummary,
)


def test_schema_builds():
    cfg = MeshJobConfig(
        component="main_wing",
        geometry=Path("demo.step"),
        out_dir=Path("out/demo"),
    )
    assert cfg.component == "main_wing"


def test_schema_accepts_explicit_tail_component_names():
    cfg = MeshJobConfig(
        component="horizontal_tail",
        geometry=Path("demo.step"),
        out_dir=Path("out/demo"),
    )

    assert cfg.component == "horizontal_tail"


def test_schema_supports_mesh_study_contract_models(tmp_path: Path):
    case_dir = tmp_path / "coarse"
    report = MeshStudyReport(
        component="aircraft_assembly",
        geometry=tmp_path / "blackcat.vsp3",
        geometry_provider="openvsp_surface_intersection",
        cases=[
            MeshStudyCaseResult.model_validate(
                {
                    "preset": {
                        "name": "coarse",
                        "tier": "coarse",
                        "characteristic_length_policy": "body_max_span",
                        "near_body_factor": 0.11,
                        "farfield_factor": 0.45,
                        "near_body_size": 1.1,
                        "farfield_size": 4.5,
                        "runtime": {
                            "max_iterations": 40,
                            "cfl_number": 4.0,
                        },
                    },
                    "out_dir": case_dir,
                    "report_path": case_dir / "report.json",
                    "status": "success",
                    "mesh": {
                        "mesh_dim": 3,
                        "node_count": 1500,
                        "element_count": 8000,
                        "surface_element_count": 1400,
                        "volume_element_count": 6500,
                        "characteristic_length": 10.0,
                        "near_body_size": 1.1,
                        "farfield_size": 4.5,
                    },
                    "cfd": {
                        "case_name": "alpha_0_coarse",
                        "history_path": case_dir / "history.csv",
                        "final_iteration": 39,
                        "cl": 0.035,
                        "cd": 0.029,
                        "cm": -0.013,
                        "cm_axis": "CMy",
                    },
                    "overall_convergence_status": "warn",
                    "comparability_level": "run_only",
                }
            )
        ],
        comparison=MeshStudyComparison.model_validate(
            {
                "expected_case_count": 3,
                "completed_case_count": 1,
                "case_order": ["coarse", "medium", "fine"],
                "mesh_hierarchy": {
                    "status": "warn",
                    "observed": {"completed_case_count": 1},
                    "expected": {"completed_case_count": 3},
                    "warnings": ["study_not_complete"],
                    "notes": [],
                },
                "coefficient_spread": {
                    "all_cases": {
                        "status": "warn",
                        "observed": {"cl_relative_range": 0.0},
                        "expected": {"cl_relative_range": "<= 0.12"},
                        "warnings": [],
                        "notes": [],
                    }
                },
                "convergence_progress": {
                    "status": "warn",
                    "observed": {"fine_status": None},
                    "expected": {"fine_status": "pass"},
                    "warnings": ["fine_case_missing"],
                    "notes": [],
                },
            }
        ),
        verdict=MeshStudyVerdict(
            verdict="insufficient",
            comparability_level="not_comparable",
            blockers=["study_not_complete"],
        ),
    )

    assert report.contract == "mesh_study.v1"
    assert report.cases[0].mesh.volume_element_count == 6500
    assert report.verdict.verdict == "insufficient"


def test_schema_supports_geometry_family_first_fields():
    cfg = MeshJobConfig(
        component="aircraft_assembly",
        geometry=Path("demo.step"),
        out_dir=Path("out/demo"),
        geometry_source="esp_rebuilt",
        geometry_family="thin_sheet_aircraft_assembly",
        meshing_route="gmsh_thin_sheet_aircraft_assembly",
        backend_capability="sheet_aircraft_assembly_meshing",
    )
    assert cfg.geometry_source == "esp_rebuilt"
    assert cfg.geometry_family == "thin_sheet_aircraft_assembly"
    assert cfg.meshing_route == "gmsh_thin_sheet_aircraft_assembly"
    assert cfg.backend_capability == "sheet_aircraft_assembly_meshing"


def test_schema_supports_tip_quality_buffer_policy_roundtrip():
    cfg = MeshJobConfig.model_validate(
        {
            "component": "main_wing",
            "geometry": "demo.vsp3",
            "out_dir": "out/demo",
            "geometry_source": "esp_rebuilt",
            "geometry_family": "thin_sheet_lifting_surface",
            "geometry_provider": "esp_rebuilt",
            "tip_quality_buffer_policy": {
                "enabled": True,
                "source_baseline": "shell_v2_strip_suppression",
                "target_surfaces": [30, 21, 31, 32],
                "optional_expanded_surfaces": [29, 20],
                "width_reference_m": 0.005055,
                "active_variant": "tipbuf_h6",
                "variants": [
                    {
                        "name": "tipbuf_h8",
                        "h_tip_m": 0.0404,
                        "dist_min_m": 0.0101,
                        "dist_max_m": 0.0505,
                    },
                    {
                        "name": "tipbuf_h6",
                        "h_tip_m": 0.0303,
                        "dist_min_m": 0.0101,
                        "dist_max_m": 0.0606,
                    },
                ],
                "stop_at_dist_max": True,
                "mesh_size_extend_from_boundary": 0,
                "mesh_size_from_points": 0,
                "mesh_size_from_curvature": 0,
            },
        }
    )

    assert cfg.tip_quality_buffer_policy is not None
    assert cfg.tip_quality_buffer_policy.enabled is True
    assert cfg.tip_quality_buffer_policy.active_variant == "tipbuf_h6"
    assert cfg.tip_quality_buffer_policy.target_surfaces == [30, 21, 31, 32]
    dumped = cfg.model_dump(mode="json")
    assert dumped["tip_quality_buffer_policy"]["variants"][1]["name"] == "tipbuf_h6"
    roundtrip = TipQualityBufferPolicy.model_validate(dumped["tip_quality_buffer_policy"])
    assert roundtrip.variants[0] == TipQualityBufferVariant(
        name="tipbuf_h8",
        h_tip_m=0.0404,
        dist_min_m=0.0101,
        dist_max_m=0.0505,
    )


def test_schema_supports_sliver_cluster_report_roundtrip():
    report = SliverClusterReport.model_validate(
        {
            "baseline": "shell_v2_strip_suppression",
            "ill_shaped_tet_count": 5,
            "bad_tets": [
                {
                    "element_id": 220280,
                    "barycenter": [1.84, 14.49, 0.36],
                    "volume": 1.0e-4,
                    "gamma": 9.4e-4,
                    "minSICN": 8.1e-4,
                    "minSIGE": 0.45,
                    "min_edge": 0.0014,
                    "max_edge": 4.08,
                    "edge_ratio": 2872.0,
                    "nearest_surface": 30,
                    "distance_to_nearest_surface": 1.0126,
                    "nearest_hotspot_surface": 30,
                    "distance_to_surfaces_30_21_31_32": 1.0126,
                }
            ],
            "clusters": [
                {
                    "cluster_id": 0,
                    "tet_count": 3,
                    "center": [1.83, 14.55, 0.36],
                    "bbox_min": [1.82, 14.49, 0.35],
                    "bbox_max": [1.84, 14.58, 0.37],
                    "radius_m": 0.05,
                    "pca_eigenvalue_ratio": 12.0,
                    "classification": "elongated",
                    "recommended_field_type": "Cylinder",
                    "source_bad_tet_ids": [220280],
                }
            ],
        }
    )

    dumped = report.model_dump(mode="json")
    assert dumped["clusters"][0]["classification"] == "elongated"
    roundtrip = SliverClusterReport.model_validate(dumped)
    assert roundtrip.bad_tets[0] == SliverClusterBadTet(
        element_id=220280,
        barycenter=[1.84, 14.49, 0.36],
        volume=1.0e-4,
        gamma=9.4e-4,
        minSICN=8.1e-4,
        minSIGE=0.45,
        min_edge=0.0014,
        max_edge=4.08,
        edge_ratio=2872.0,
        nearest_surface=30,
        distance_to_nearest_surface=1.0126,
        nearest_hotspot_surface=30,
        distance_to_surfaces_30_21_31_32=1.0126,
    )
    assert roundtrip.clusters[0] == SliverClusterRecord(
        cluster_id=0,
        tet_count=3,
        center=[1.83, 14.55, 0.36],
        bbox_min=[1.82, 14.49, 0.35],
        bbox_max=[1.84, 14.58, 0.37],
        radius_m=0.05,
        pca_eigenvalue_ratio=12.0,
        classification="elongated",
        recommended_field_type="Cylinder",
        source_bad_tet_ids=[220280],
    )


def test_schema_supports_autonomous_repair_context_roundtrip():
    context = AutonomousRepairContext.model_validate(
        {
            "baseline": "shell_v2_strip_suppression",
            "mesh_only_no_go": True,
            "source_section_index": 5,
            "known_good_trim_count_per_side": 3,
            "bad_aggressive_trim": True,
            "baseline_metrics": {
                "surface_triangle_count": 107338,
                "volume_element_count": 129288,
                "nodes_created_per_boundary_node": 0.0260466156,
                "ill_shaped_tet_count": 5,
            },
            "active_hotspot_family": {
                "primary": ["tip-adjacent panel family"],
                "observed_surfaces": [30, 21],
                "legacy_surfaces": [31, 32],
            },
            "do_not_repeat": [
                "compound",
                "optimizer zoo",
                "surface tip buffer",
                "Ball/Cylinder pocket",
                "more aggressive trim",
            ],
        }
    )

    dumped = context.model_dump(mode="json")
    assert dumped["active_hotspot_family"]["observed_surfaces"] == [30, 21]
    roundtrip = AutonomousRepairContext.model_validate(dumped)
    assert roundtrip.baseline_metrics == AutonomousRepairBaselineMetrics(
        surface_triangle_count=107338,
        volume_element_count=129288,
        nodes_created_per_boundary_node=0.0260466156,
        ill_shaped_tet_count=5,
    )
    assert roundtrip.active_hotspot_family == AutonomousRepairActiveHotspotFamily(
        primary=["tip-adjacent panel family"],
        observed_surfaces=[30, 21],
        legacy_surfaces=[31, 32],
    )


def test_schema_supports_tip_topology_diagnostics_roundtrip():
    diagnostics = TipTopologyDiagnostics.model_validate(
        {
            "source_section_index": 5,
            "terminal_tip_neighborhood": {
                "section_point_count_before": 61,
                "section_point_count_after_v2": 56,
                "te_point_indices": [0, 1, 54, 55],
                "trim_count_per_side": 3,
                "terminal_bridge_m": 0.005055,
                "adjacent_bridge_lengths_m": [0.0291, 0.0291],
                "bridge_length_ratios": [0.17, 0.17],
                "panel_widths_m": [0.005055, 0.0291],
                "panel_lengths_m": [3.0, 3.0],
                "width_length_ratios": [0.0017, 0.0097],
                "consecutive_width_ratio_max": 5.76,
                "candidate_bad_panels": [
                    {
                        "panel_index": 0,
                        "width_m": 0.005055,
                        "length_m": 3.0,
                        "width_length_ratio": 0.001685,
                    }
                ],
            },
            "lineage": {
                "old_face_to_source_panel": {
                    "legacy_surface_30": "section5_tip_adjacent_right",
                },
                "source_panel_to_faces": {
                    "section5_tip_adjacent_right": [30],
                },
                "attributes": {
                    "section5_tip_adjacent_right": {"caps_group": "main_wing"},
                },
                "physical_groups": {
                    "section5_tip_adjacent_right": "aircraft",
                },
            },
            "classification": {
                "has_residual_sliver_sensitive_topology": True,
                "reason": [
                    "panel_width_below_threshold",
                    "width_length_ratio_below_threshold",
                ],
            },
        }
    )

    dumped = diagnostics.model_dump(mode="json")
    assert dumped["terminal_tip_neighborhood"]["section_point_count_after_v2"] == 56
    roundtrip = TipTopologyDiagnostics.model_validate(dumped)
    assert roundtrip.terminal_tip_neighborhood == TipTopologyTerminalNeighborhoodDiagnostics(
        section_point_count_before=61,
        section_point_count_after_v2=56,
        te_point_indices=[0, 1, 54, 55],
        trim_count_per_side=3,
        terminal_bridge_m=0.005055,
        adjacent_bridge_lengths_m=[0.0291, 0.0291],
        bridge_length_ratios=[0.17, 0.17],
        panel_widths_m=[0.005055, 0.0291],
        panel_lengths_m=[3.0, 3.0],
        width_length_ratios=[0.0017, 0.0097],
        consecutive_width_ratio_max=5.76,
        candidate_bad_panels=[{"panel_index": 0, "width_m": 0.005055, "length_m": 3.0, "width_length_ratio": 0.001685}],
    )
    assert roundtrip.lineage == TipTopologyDiagnosticsLineage(
        old_face_to_source_panel={"legacy_surface_30": "section5_tip_adjacent_right"},
        source_panel_to_faces={"section5_tip_adjacent_right": [30]},
        attributes={"section5_tip_adjacent_right": {"caps_group": "main_wing"}},
        physical_groups={"section5_tip_adjacent_right": "aircraft"},
    )
    assert roundtrip.classification == TipTopologyDiagnosticsClassification(
        has_residual_sliver_sensitive_topology=True,
        reason=["panel_width_below_threshold", "width_length_ratio_below_threshold"],
    )


def test_schema_supports_candidate_topology_repair_report_roundtrip():
    report = CandidateTopologyRepairReport.model_validate(
        {
            "candidate_name": "section5_pairing_smooth_v0",
            "repair_type": "pairing_smooth",
            "source_section_index": 5,
            "changes": {
                "paired_section_indices": [4, 5],
                "paired_profile_point_count": 56,
            },
            "old_face_to_new_face_map": {
                "legacy_surface_30": "section5_tip_adjacent_right_paired",
                "legacy_surface_21": "section5_tip_adjacent_left_paired",
            },
            "attribute_remap": {
                "section5_tip_adjacent_right_paired": {"caps_group": "main_wing"},
            },
            "physical_group_remap": {
                "section5_tip_adjacent_right_paired": "aircraft",
            },
            "expected_effect": "smooth section4-section5 pairing near the terminal tip TE neighborhood",
            "risk": "may move the hotspot into an adjacent healthy panel if the pairing is too aggressive",
            "geometry_score": 4.5,
            "geometry_filter_passed": True,
        }
    )

    dumped = report.model_dump(mode="json")
    assert dumped["old_face_to_new_face_map"]["legacy_surface_30"] == "section5_tip_adjacent_right_paired"
    roundtrip = CandidateTopologyRepairReport.model_validate(dumped)
    assert roundtrip.candidate_name == "section5_pairing_smooth_v0"
    assert roundtrip.geometry_filter_passed is True


def test_schema_supports_upstream_topology_summary_and_no_go_roundtrip():
    summary = UpstreamTopologyRepairSummary.model_validate(
        {
            "baseline": "shell_v2_strip_suppression",
            "controller_version": "source_section5_tip_topology_repair_v0",
            "mesh_only_no_go_confirmed": True,
            "candidates": [
                {
                    "name": "diagnostic_noop_v2_control",
                    "repair_type": "noop_control",
                    "geometry_filter_passed": True,
                    "ran_3d": True,
                    "surface_triangle_count": 107338,
                    "volume_element_count": 129288,
                    "ill_shaped_tet_count": 5,
                    "nodes_created_per_boundary_node": 0.0260466156,
                    "brep_valid_default": True,
                    "brep_valid_exact": True,
                    "physical_groups_preserved": True,
                    "old_face_to_new_face_map_path": "control_map.json",
                    "failure_reason": "ill_shaped_tets_present",
                }
            ],
            "winner": None,
            "baseline_promoted": False,
            "recommended_next": "manual review of rule-loft section pairing or geometry construction contract",
        }
    )

    dumped = summary.model_dump(mode="json")
    assert dumped["candidates"][0]["ran_3d"] is True
    roundtrip = UpstreamTopologyRepairSummary.model_validate(dumped)
    assert roundtrip.candidates[0] == UpstreamTopologyRepairCandidateSummary(
        name="diagnostic_noop_v2_control",
        repair_type="noop_control",
        geometry_filter_passed=True,
        ran_3d=True,
        surface_triangle_count=107338,
        volume_element_count=129288,
        ill_shaped_tet_count=5,
        nodes_created_per_boundary_node=0.0260466156,
        brep_valid_default=True,
        brep_valid_exact=True,
        physical_groups_preserved=True,
        old_face_to_new_face_map_path="control_map.json",
        failure_reason="ill_shaped_tets_present",
    )

    no_go = UpstreamPairingNoGoSummary.model_validate(
        {
            "reason": "bounded upstream pairing/coalescing candidates did not clear residual slivers",
            "confirmed_no_go": [
                "compound",
                "optimizer",
                "surface tip buffer",
                "Ball/Cylinder volume pocket",
                "more aggressive trim",
            ],
            "source_section_index": 5,
            "next_required_action": "manual review of rule-loft section pairing or geometry construction contract",
            "minimum_information_for_manual_review": [
                "tip_topology_diagnostics.json",
                "candidate_topology_repair_report.json",
                "old_face_to_new_face_map",
            ],
        }
    )
    assert no_go.source_section_index == 5


def test_schema_supports_sliver_volume_pocket_policy_roundtrip():
    cfg = MeshJobConfig.model_validate(
        {
            "component": "main_wing",
            "geometry": "demo.vsp3",
            "out_dir": "out/demo",
            "geometry_source": "esp_rebuilt",
            "geometry_family": "thin_sheet_lifting_surface",
            "geometry_provider": "esp_rebuilt",
            "sliver_volume_pocket_policy": {
                "enabled": True,
                "source_baseline": "shell_v2_strip_suppression",
                "cluster_report_path": "artifacts/mesh/sliver_cluster_report.json",
                "active_variant": "sliver_ball_mid",
                "variants": [
                    {
                        "name": "sliver_ball_mid",
                        "field_type": "Ball",
                        "pockets": [
                            {
                                "cluster_id": 0,
                                "source_bad_tet_ids": [220280, 220281],
                                "center": [1.83, 14.55, 0.36],
                                "radius": 0.5,
                                "thickness": 0.25,
                                "VIn": 0.06,
                                "VOut": 1e22,
                            }
                        ],
                    }
                ],
                "mesh_size_extend_from_boundary": 0,
                "mesh_size_from_points": 0,
                "mesh_size_from_curvature": 0,
            },
        }
    )

    assert cfg.sliver_volume_pocket_policy is not None
    assert cfg.sliver_volume_pocket_policy.enabled is True
    assert cfg.sliver_volume_pocket_policy.active_variant == "sliver_ball_mid"
    dumped = cfg.model_dump(mode="json")
    assert dumped["sliver_volume_pocket_policy"]["variants"][0]["pockets"][0]["VOut"] == 1e22
    roundtrip = SliverVolumePocketPolicy.model_validate(dumped["sliver_volume_pocket_policy"])
    assert roundtrip.variants[0] == SliverVolumePocketVariant(
        name="sliver_ball_mid",
        field_type="Ball",
        pockets=[
            SliverVolumePocketField(
                cluster_id=0,
                source_bad_tet_ids=[220280, 220281],
                center=[1.83, 14.55, 0.36],
                radius=0.5,
                thickness=0.25,
                VIn=0.06,
                VOut=1e22,
            )
        ],
    )


def test_schema_supports_provider_contract_models(tmp_path: Path):
    source = tmp_path / "blackcat.vsp3"
    staging_dir = tmp_path / "out" / "providers" / "openvsp_surface_intersection"
    normalized = staging_dir / "normalized.stp"

    request = GeometryProviderRequest(
        provider="openvsp_surface_intersection",
        source_path=source,
        component="aircraft_assembly",
        staging_dir=staging_dir,
        geometry_family_hint="thin_sheet_aircraft_assembly",
    )
    result = GeometryProviderResult(
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
            labels_present=True,
            label_schema="component/name",
        ),
        artifacts={"topology_report": staging_dir / "topology.json"},
        provenance={"analysis": "SurfaceIntersection"},
    )

    assert request.provider == "openvsp_surface_intersection"
    assert request.geometry_family_hint == "thin_sheet_aircraft_assembly"
    assert result.status == "materialized"
    assert result.topology.volume_count == 3


def test_schema_supports_experimental_provider_not_materialized(tmp_path: Path):
    source = tmp_path / "blackcat.vsp3"

    result = GeometryProviderResult(
        provider="esp_rebuilt",
        provider_stage="experimental",
        status="not_materialized",
        geometry_source="esp_rebuilt",
        source_path=source,
        geometry_family_hint="thin_sheet_aircraft_assembly",
        topology=GeometryTopologyMetadata(
            representation="provider_deferred",
            source_kind="vsp3",
            units=None,
        ),
        provenance={"status": "experimental_not_materialized"},
    )

    assert result.provider == "esp_rebuilt"
    assert result.provider_stage == "experimental"
    assert result.normalized_geometry_path is None


def test_schema_supports_mesh_handoff_contract_models(tmp_path: Path):
    mesh_dir = tmp_path / "out" / "mesh"
    handoff = MeshHandoff(
        route_stage="baseline",
        backend="gmsh",
        backend_capability="sheet_aircraft_assembly_meshing",
        meshing_route="gmsh_thin_sheet_aircraft_assembly",
        geometry_family="thin_sheet_aircraft_assembly",
        geometry_source="provider_generated",
        geometry_provider="openvsp_surface_intersection",
        source_path=tmp_path / "blackcat.vsp3",
        normalized_geometry_path=tmp_path / "normalized.stp",
        units="m",
        mesh_format="msh",
        body_bounds=Bounds3D(x_min=0.0, x_max=5.7, y_min=-16.4, y_max=16.4, z_min=-0.7, z_max=1.7),
        farfield_bounds=Bounds3D(
            x_min=-28.5,
            x_max=74.1,
            y_min=-280.0,
            y_max=280.0,
            z_min=-19.9,
            z_max=20.9,
        ),
        mesh_stats={"node_count": 123, "element_count": 456},
        marker_summary={"aircraft": {"exists": True}},
        physical_groups={"fluid": {"exists": True}},
        artifacts=MeshArtifactBundle(
            mesh=mesh_dir / "mesh.msh",
            mesh_metadata=mesh_dir / "mesh_metadata.json",
            marker_summary=mesh_dir / "marker_summary.json",
        ),
        provenance={"route_provenance": "geometry_family_registry"},
    )

    assert handoff.contract == "mesh_handoff.v1"
    assert handoff.artifacts.mesh.name == "mesh.msh"
    assert handoff.body_bounds.x_max == 5.7


def test_schema_supports_selectable_su2_parallel_modes():
    runtime = SU2RuntimeConfig(enabled=True, parallel_mode="mpi")

    assert runtime.parallel_mode == "mpi"
    assert runtime.cpu_threads == 4
    assert runtime.mpi_ranks == 4
    assert runtime.mpi_launcher == "mpirun"


def test_schema_supports_su2_handoff_contract_models(tmp_path: Path):
    case_dir = tmp_path / "out" / "su2"
    runtime = SU2RuntimeConfig(
        enabled=True,
        alpha_deg=0.0,
        max_iterations=25,
        reference_mode="user_declared",
        reference_override=SU2ReferenceOverride(
            ref_area=12.0,
            ref_length=3.5,
            ref_origin_moment={"x": 1.0, "y": 0.0, "z": 0.1},
            source_label="manual_test_reference",
        ),
    )
    handoff = SU2CaseHandoff(
        geometry_family="thin_sheet_aircraft_assembly",
        units="m",
        input_mesh_artifact=tmp_path / "mesh.msh",
        mesh_markers={
            "wall": "aircraft",
            "farfield": "farfield",
            "monitoring": ["aircraft"],
            "plotting": ["aircraft"],
            "euler": ["aircraft"],
        },
        reference_geometry=SU2ReferenceGeometry(
            ref_area=12.0,
            ref_length=3.5,
            ref_origin_moment={"x": 1.0, "y": 0.0, "z": 0.1},
            area_provenance=SU2ReferenceQuantityProvenance(
                source_category="user_declared",
                method="runtime.reference_override.ref_area",
                confidence="high",
                source_path=tmp_path / "manual_reference.json",
            ),
            length_provenance=SU2ReferenceQuantityProvenance(
                source_category="user_declared",
                method="runtime.reference_override.ref_length",
                confidence="high",
                source_path=tmp_path / "manual_reference.json",
            ),
            moment_origin_provenance=SU2ReferenceQuantityProvenance(
                source_category="user_declared",
                method="runtime.reference_override.ref_origin_moment",
                confidence="high",
                source_path=tmp_path / "manual_reference.json",
            ),
            gate_status="pass",
            confidence="high",
            notes=["baseline envelope-derived references"],
        ),
        runtime=runtime,
        runtime_cfg_path=case_dir / "su2_runtime.cfg",
        case_output_paths=SU2CaseArtifacts(
            case_dir=case_dir,
            su2_mesh=case_dir / "mesh.su2",
            history=case_dir / "history.csv",
            solver_log=case_dir / "solver.log",
            surface_output=case_dir / "surface.csv",
            restart_output=case_dir / "restart.csv",
            volume_output=case_dir / "vol_solution.vtk",
            contract_path=case_dir / "su2_handoff.json",
        ),
        history=SU2HistorySummary(
            history_path=case_dir / "history.csv",
            final_iteration=24,
            cl=0.12,
            cd=0.03,
            cm=-0.004,
            cm_axis="CMy",
            source_columns={"cl": "CL", "cd": "CD", "cm": "CMy"},
        ),
        run_status="completed",
        solver_command=["SU2_CFD", "su2_runtime.cfg"],
        force_surface_provenance=SU2ForceSurfaceProvenance(
            gate_status="pass",
            confidence="medium",
            source_kind="mesh_physical_group",
            wall_marker="aircraft",
            monitoring_markers=["aircraft"],
            plotting_markers=["aircraft"],
            euler_markers=["aircraft"],
            source_groups=[
                SU2ForceSurfaceMarkerGroup(
                    marker_name="aircraft",
                    physical_name="aircraft",
                    physical_tag=2,
                    dimension=2,
                    entity_count=38,
                    element_count=180,
                ),
            ],
            primary_group=SU2ForceSurfaceMarkerGroup(
                marker_name="aircraft",
                physical_name="aircraft",
                physical_tag=2,
                dimension=2,
                entity_count=38,
                element_count=180,
            ),
            matches_wall_marker=True,
            matches_entire_aircraft_wall=True,
            scope="whole_aircraft_wall",
            body_count=3,
            component_labels_present_in_geometry=True,
            component_label_schema="preserve_component_labels",
            component_provenance="geometry_labels_present_but_not_mapped",
        ),
        provenance_gates=SU2ProvenanceGates(
            overall_status="pass",
            reference_quantities=SU2GateCheck(
                status="pass",
                confidence="high",
            ),
            force_surface=SU2GateCheck(
                status="pass",
                confidence="medium",
            ),
        ),
        convergence_gate=BaselineConvergenceGate(
            mesh_gate=ConvergenceGateSection(
                status="pass",
                confidence="high",
                checks={
                    "mesh_handoff_complete": ConvergenceGateCheck(
                        status="pass",
                        observed={"contract": "mesh_handoff.v1"},
                        expected={"contract": "mesh_handoff.v1"},
                    )
                },
            ),
            iterative_gate=ConvergenceGateSection(
                status="warn",
                confidence="medium",
                checks={
                    "residual_trend": ConvergenceGateCheck(
                        status="warn",
                        observed={"median_log_drop": 0.2},
                        expected={"minimum_median_log_drop": 0.5},
                    )
                },
                warnings=["residual trend remains mixed"],
            ),
            overall_convergence_gate=OverallConvergenceGate(
                status="warn",
                confidence="medium",
                comparability_level="run_only",
                checks={
                    "mesh_gate": ConvergenceGateCheck(
                        status="pass",
                        observed={"status": "pass"},
                        expected={"status": "pass"},
                    ),
                    "iterative_gate": ConvergenceGateCheck(
                        status="warn",
                        observed={"status": "warn"},
                        expected={"status": "pass"},
                    ),
                },
                warnings=["iterative convergence still needs caution"],
            ),
        ),
        provenance={"source_contract": "mesh_handoff.v1"},
        notes=["package-native baseline case"],
    )

    assert handoff.contract == "su2_handoff.v1"
    assert handoff.runtime.enabled is True
    assert handoff.runtime.alpha_deg == 0.0
    assert handoff.case_output_paths.contract_path.name == "su2_handoff.json"
    assert handoff.history.cm_axis == "CMy"
    assert handoff.mesh_markers["wall"] == "aircraft"
    assert handoff.reference_geometry.area_provenance.source_category == "user_declared"
    assert handoff.force_surface_provenance.scope == "whole_aircraft_wall"
    assert handoff.provenance_gates.overall_status == "pass"
    assert handoff.convergence_gate.overall_convergence_gate.comparability_level == "run_only"
