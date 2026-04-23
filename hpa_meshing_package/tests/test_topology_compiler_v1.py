from __future__ import annotations

import json
from pathlib import Path

import pytest

from hpa_meshing.compiler.compiler_v1 import (
    compile_topology_family_v1,
    resolve_shell_role_policy_v1,
)
from hpa_meshing.compiler.motif_registry_v1 import MotifRegistryV1
from hpa_meshing.compiler.operator_library_v1 import OperatorLibraryV1
from hpa_meshing.compiler.pre_plc_audit_v1 import (
    PlanningBudgetRegionV1,
    PlanningBudgetSectionV1,
    PlanningBudgetingV1,
    PrePLCAuditConfigV1,
    PrePLCAuditObservedEvidenceV1,
    run_pre_plc_audit_v1,
)
from hpa_meshing.compiler.topology_ir_v1 import (
    LocalTopologyDescriptorsV1,
    SectionLineageV1,
    TopologyAdjacencyGraphV1,
    TopologyCurveV1,
    TopologyIRV1,
    TopologyLoopV1,
    TopologyPatchV1,
    TopologySeamAdjacencyV1,
    TopologyClosureAdjacencyV1,
    build_topology_ir_v1,
)


def _sample_topology_report() -> dict[str, object]:
    return {
        "representation": "brep_trimmed_step",
        "source_kind": "stp",
        "units": "m",
        "body_count": 1,
        "surface_count": 32,
        "volume_count": 1,
        "source_path": "/tmp/blackcat_004_origin.vsp3",
        "export_path": "/tmp/normalized.stp",
        "topology_lineage_report": {"artifact": "/tmp/topology_lineage_report.json"},
        "topology_suppression_report": {"artifact": "/tmp/topology_suppression_report.json"},
    }


def _truncation_connector_band_topology_report(
    selected_section_y_le_m: list[float],
) -> dict[str, object]:
    payload = _sample_topology_report()
    payload["compiler_context"] = {
        "truncation_connector_band": {
            "enabled": True,
            "root_y_le_m": 0.0,
            "connector_band_start_y_le_m": 14.992006138888888,
            "truncation_start_y_le_m": 14.998333333333333,
            "tip_y_le_m": 16.5,
            "selected_section_y_le_m": list(selected_section_y_le_m),
        }
    }
    return payload


def _sample_lineage_report() -> dict[str, object]:
    return {
        "status": "captured",
        "surface_count": 1,
        "surfaces": [
            {
                "component": "main_wing",
                "geom_id": "IPAWXFWPQF",
                "name": "Main Wing",
                "caps_group": "main_wing",
                "symmetric_xz": False,
                "source_section_count": 3,
                "rule_section_count": 3,
                "rule_sections": [
                    {
                        "rule_section_index": 0,
                        "source_section_index": 0,
                        "mirrored": False,
                        "side": "center_or_start",
                        "x_le": 0.0,
                        "y_le": 0.0,
                        "z_le": 0.0,
                        "chord": 1.30,
                        "twist_deg": 0.0,
                        "airfoil_source": "inline_coordinates",
                    },
                    {
                        "rule_section_index": 1,
                        "source_section_index": 1,
                        "mirrored": False,
                        "side": "right_span",
                        "x_le": 0.03,
                        "y_le": 7.5,
                        "z_le": 0.18,
                        "chord": 1.10,
                        "twist_deg": -0.5,
                        "airfoil_source": "inline_coordinates",
                    },
                    {
                        "rule_section_index": 2,
                        "source_section_index": 2,
                        "mirrored": False,
                        "side": "right_tip",
                        "x_le": 0.20,
                        "y_le": 16.5,
                        "z_le": 0.80,
                        "chord": 0.43,
                        "twist_deg": -1.0,
                        "airfoil_source": "inline_coordinates",
                    },
                ],
                "terminal_strip_candidates": [
                    {
                        "side": "right_tip",
                        "source_section_index": 2,
                        "mirrored": False,
                        "y_le": 16.5,
                        "chord": 0.43,
                        "profile_point_count": 56,
                        "seam_adjacent_edge_lengths_m": [0.0170, 0.0165],
                        "trailing_edge_gap_m": 0.00505,
                        "suppression_threshold_m": 0.00261,
                        "would_suppress": False,
                        "suppression_reason": "terminal_tip_te_edges_not_small_enough",
                    }
                ],
            }
        ],
        "notes": [],
    }


def _sample_suppression_report() -> dict[str, object]:
    return {
        "status": "captured",
        "applied": False,
        "surface_count": 1,
        "suppressed_source_section_count": 0,
        "surfaces": [
            {
                "component": "main_wing",
                "geom_id": "IPAWXFWPQF",
                "name": "Main Wing",
                "caps_group": "main_wing",
                "suppressed_source_section_indices": [],
                "suppressed_sections": [],
                "applied": False,
            }
        ],
        "notes": [],
    }


def _truncation_connector_band_lineage_report(*, include_extra_pre_band_section: bool) -> dict[str, object]:
    rule_sections = [
        {
            "rule_section_index": 0,
            "source_section_index": 0,
            "mirrored": False,
            "side": "center_or_start",
            "x_le": 0.0,
            "y_le": 0.0,
            "z_le": 0.0,
            "chord": 1.30,
            "twist_deg": 0.0,
            "airfoil_source": "inline_coordinates",
        },
    ]
    if include_extra_pre_band_section:
        rule_sections.append(
            {
                "rule_section_index": 1,
                "source_section_index": 4,
                "mirrored": False,
                "side": "right_span",
                "x_le": 0.11822077170218112,
                "y_le": 13.5,
                "z_le": 0.5448734072648781,
                "chord": 0.83,
                "twist_deg": -0.3,
                "airfoil_source": "inline_coordinates",
            }
        )
    offset = len(rule_sections)
    rule_sections.extend(
        [
            {
                "rule_section_index": offset,
                "source_section_index": 5,
                "mirrored": False,
                "side": "right_span",
                "x_le": 0.17473981881820483,
                "y_le": 14.992006138888888,
                "z_le": 0.6726241298774025,
                "chord": 0.6335525250462963,
                "twist_deg": -0.8,
                "airfoil_source": "inline_coordinates",
            },
            {
                "rule_section_index": offset + 1,
                "source_section_index": 6,
                "mirrored": False,
                "side": "right_span",
                "x_le": 0.17497950080851096,
                "y_le": 14.998333333333333,
                "z_le": 0.6731658861351816,
                "chord": 0.6327194444444444,
                "twist_deg": -0.8,
                "airfoil_source": "inline_coordinates",
            },
            {
                "rule_section_index": offset + 2,
                "source_section_index": 7,
                "mirrored": False,
                "side": "right_tip",
                "x_le": 0.23186450072486597,
                "y_le": 16.5,
                "z_le": 0.8017437765268873,
                "chord": 0.435,
                "twist_deg": -1.0,
                "airfoil_source": "inline_coordinates",
            },
        ]
    )
    return {
        "status": "captured",
        "surface_count": 1,
        "surfaces": [
            {
                "component": "main_wing",
                "geom_id": "fixture_band",
                "name": "Fixture Band",
                "caps_group": "main_wing",
                "symmetric_xz": False,
                "source_section_count": len(rule_sections),
                "rule_section_count": len(rule_sections),
                "rule_sections": rule_sections,
                "terminal_strip_candidates": [],
            }
        ],
        "notes": [],
    }


def _build_minimal_ir() -> TopologyIRV1:
    return build_topology_ir_v1(
        topology_report=_sample_topology_report(),
        topology_lineage_report=_sample_lineage_report(),
        topology_suppression_report=_sample_suppression_report(),
        component="main_wing",
    )


def _build_truncation_connector_band_ir(*, include_extra_pre_band_section: bool) -> TopologyIRV1:
    selected_section_y_le_m = [0.0]
    if include_extra_pre_band_section:
        selected_section_y_le_m.append(13.5)
    selected_section_y_le_m.extend([14.992006138888888, 14.998333333333333, 16.5])
    return build_topology_ir_v1(
        topology_report=_truncation_connector_band_topology_report(selected_section_y_le_m),
        topology_lineage_report=_truncation_connector_band_lineage_report(
            include_extra_pre_band_section=include_extra_pre_band_section
        ),
        topology_suppression_report=_sample_suppression_report(),
        component="main_wing",
    )


def _build_post_transition_boundary_recovery_ir() -> TopologyIRV1:
    split_y_le_m = 15.498888888888889
    return build_topology_ir_v1(
        topology_report={
            **_truncation_connector_band_topology_report(
                [0.0, 14.992006138888888, 14.998333333333333, split_y_le_m, 16.5]
            ),
            "compiler_context": {
                "truncation_connector_band": {
                    "enabled": True,
                    "root_y_le_m": 0.0,
                    "connector_band_start_y_le_m": 14.992006138888888,
                    "truncation_start_y_le_m": 14.998333333333333,
                    "tip_y_le_m": 16.5,
                    "selected_section_y_le_m": [
                        0.0,
                        14.992006138888888,
                        14.998333333333333,
                        split_y_le_m,
                        16.5,
                    ],
                    "post_band_transition_guard_y_le_m": split_y_le_m,
                }
            },
        },
        topology_lineage_report={
            **_truncation_connector_band_lineage_report(include_extra_pre_band_section=False),
            "surfaces": [
                {
                    **_truncation_connector_band_lineage_report(
                        include_extra_pre_band_section=False
                    )["surfaces"][0],
                    "rule_section_count": 5,
                    "rule_sections": [
                        {
                            "rule_section_index": 0,
                            "source_section_index": 0,
                            "mirrored": False,
                            "side": "center_or_start",
                            "x_le": 0.0,
                            "y_le": 0.0,
                            "z_le": 0.0,
                            "chord": 1.30,
                            "twist_deg": 0.0,
                            "airfoil_source": "inline_coordinates",
                        },
                        {
                            "rule_section_index": 1,
                            "source_section_index": 5,
                            "mirrored": False,
                            "side": "right_span",
                            "x_le": 0.17473981881820483,
                            "y_le": 14.992006138888888,
                            "z_le": 0.6726241298774025,
                            "chord": 0.6335525250462963,
                            "twist_deg": -0.8,
                            "airfoil_source": "inline_coordinates",
                        },
                        {
                            "rule_section_index": 2,
                            "source_section_index": 6,
                            "mirrored": False,
                            "side": "right_span",
                            "x_le": 0.17603530359784303,
                            "y_le": 14.998333333333333,
                            "z_le": 0.6738131383867332,
                            "chord": 0.6327103179012345,
                            "twist_deg": -0.8,
                            "airfoil_source": "inline_coordinates",
                        },
                        {
                            "rule_section_index": 3,
                            "source_section_index": 61,
                            "mirrored": False,
                            "side": "right_span",
                            "x_le": 0.19044519248441888,
                            "y_le": split_y_le_m,
                            "z_le": 0.7051985929463964,
                            "chord": 0.5552212664783951,
                            "twist_deg": -0.9,
                            "airfoil_source": "synthetic_tip_cut",
                        },
                        {
                            "rule_section_index": 4,
                            "source_section_index": 7,
                            "mirrored": False,
                            "side": "right_tip",
                            "x_le": 0.23222778233596357,
                            "y_le": 16.5,
                            "z_le": 0.776653890356024,
                            "chord": 0.43000000000000005,
                            "twist_deg": -1.0,
                            "airfoil_source": "inline_coordinates",
                        },
                    ],
                }
            ],
        },
        topology_suppression_report=_sample_suppression_report(),
        component="main_wing",
    )


def _build_collapsed_endcap_ir() -> TopologyIRV1:
    patches = []
    for index in range(3):
        patch_id = f"patch:endcap:{index}"
        patches.append(
            TopologyPatchV1(
                patch_id=patch_id,
                patch_kind="rule_section_strip",
                component="main_wing",
                label=f"collapsed endcap strip {index}",
                source_patch_family="tip_endcap_patch",
                curve_ids=[f"curve:{patch_id}:0", f"curve:{patch_id}:1", f"curve:{patch_id}:2", f"curve:{patch_id}:3"],
                loop_ids=[f"loop:{patch_id}"],
                corner_ids=[f"corner:{patch_id}:0", f"corner:{patch_id}:1", f"corner:{patch_id}:2", f"corner:{patch_id}:3"],
                section_lineage=SectionLineageV1(
                    source_section_indices=[index, index + 1],
                    rule_section_indices=[index, index + 1],
                    side_labels=["right_tip", "right_tip"],
                ),
                seam_adjacency=TopologySeamAdjacencyV1(
                    is_seam_adjacent=True,
                    seam_kind="trailing_edge_seam",
                    seam_curve_ids=[f"curve:{patch_id}:trailing"],
                ),
                closure_adjacency=TopologyClosureAdjacencyV1(
                    is_closure_adjacent=True,
                    closure_kind="tip_endcap",
                    closure_curve_ids=[f"curve:{patch_id}:tip"],
                ),
                local_descriptors=LocalTopologyDescriptorsV1(
                    collapse_indicators={
                        "collapsed_patch": True,
                        "tip_terminal_candidate": True,
                    },
                    extrusion_compatibility={
                        "status": "needs_fallback",
                        "reason": "collapsed_endcap_family",
                    },
                ),
            )
        )
    connector_patch = TopologyPatchV1(
        patch_id="patch:connector:0",
        patch_kind="rule_section_strip",
        component="main_wing",
        label="connector band strip",
        source_patch_family="truncation_connector_band",
        curve_ids=["curve:connector:0", "curve:connector:1", "curve:connector:2", "curve:connector:3"],
        loop_ids=["loop:connector:0"],
        corner_ids=["corner:connector:0", "corner:connector:1", "corner:connector:2", "corner:connector:3"],
        section_lineage=SectionLineageV1(
            source_section_indices=[6, 7],
            rule_section_indices=[6, 7],
            side_labels=["right_span", "right_tip"],
        ),
        seam_adjacency=TopologySeamAdjacencyV1(
            is_seam_adjacent=True,
            seam_kind="trailing_edge_seam",
            seam_curve_ids=["curve:connector:trailing"],
        ),
        closure_adjacency=TopologyClosureAdjacencyV1(
            is_closure_adjacent=True,
            closure_kind="tip_endcap",
            closure_curve_ids=["curve:connector:tip"],
        ),
        local_descriptors=LocalTopologyDescriptorsV1(
            collapse_indicators={"collapsed_patch": False},
            extrusion_compatibility={"status": "unknown"},
        ),
        tags=["truncation_connector_band"],
    )
    return TopologyIRV1(
        component="main_wing",
        geometry_source="esp_rebuilt",
        geometry_provider="esp_rebuilt",
        topology_counts={"patches": 4, "curves": 0, "loops": 0, "corners": 0},
        patches=[*patches, connector_patch],
        curves=[],
        loops=[],
        corners=[],
        adjacency_graph=TopologyAdjacencyGraphV1(edges=[]),
        notes=["synthetic collapsed endcap test fixture"],
    )


def test_build_topology_ir_v1_from_esp_rebuilt_artifacts_creates_local_patch_graph():
    ir = _build_minimal_ir()

    assert ir.contract == "topology_ir.v1"
    assert ir.component == "main_wing"
    assert ir.geometry_provider == "esp_rebuilt"
    assert len(ir.patches) == 2
    assert len(ir.loops) == 2
    assert all(len(loop.curve_ids) == 4 for loop in ir.loops)
    assert {curve.curve_role for curve in ir.curves} >= {
        "section_boundary",
        "leading_edge_segment",
        "trailing_edge_segment",
    }
    root_adjacent_patch = next(
        patch for patch in ir.patches if patch.closure_adjacency.closure_kind == "symmetry_or_root"
    )
    tip_adjacent_patch = next(
        patch for patch in ir.patches if patch.closure_adjacency.closure_kind == "tip_endcap"
    )
    assert root_adjacent_patch.section_lineage.source_section_indices == [0, 1]
    assert tip_adjacent_patch.local_descriptors.collapse_indicators["tip_terminal_candidate"] is True
    assert tip_adjacent_patch.local_descriptors.extrusion_compatibility["status"] == "unknown"
    assert any(edge.relation_kind == "shared_section_curve" for edge in ir.adjacency_graph.edges)


def test_motif_registry_v1_detects_required_motifs_without_surface_id_patching():
    registry = MotifRegistryV1()
    base_matches = registry.detect(_build_minimal_ir()).matches
    base_kinds = {match.kind for match in base_matches}

    assert "ROOT_CLOSURE" in base_kinds
    assert "TRUNCATION_SEAM_REQUIRED_RING" in base_kinds

    collapsed_matches = registry.detect(_build_collapsed_endcap_ir()).matches
    collapsed_kinds = {match.kind for match in collapsed_matches}

    assert "TRIANGULAR_ENDCAP_COLLAPSED_3PATCH" in collapsed_kinds
    assert "TRUNCATION_CONNECTOR_BAND" in collapsed_kinds


def test_operator_library_v1_returns_explicit_skeleton_status_for_unimplemented_operator():
    ir = _build_minimal_ir()
    registry = MotifRegistryV1()
    library = OperatorLibraryV1()
    root_match = next(match for match in registry.detect(ir).matches if match.kind == "ROOT_CLOSURE")

    contract = library.describe("root_closure_from_bl_faces")
    result = library.execute("root_closure_from_bl_faces", root_match, ir)

    assert contract.implementation_status == "skeleton"
    assert "root_closure_plan" in contract.expected_artifact_keys
    assert result.status == "not_implemented"
    assert result.applied is False
    assert result.report_key == "root_closure_from_bl_faces"


def test_operator_library_v1_deterministically_rejects_unsupported_plc_risk_family():
    ir = _build_minimal_ir()
    registry = MotifRegistryV1()
    audit = run_pre_plc_audit_v1(
        ir.model_copy(
            update={
                "patches": [
                    patch.model_copy(
                        update={
                            "local_descriptors": patch.local_descriptors.model_copy(
                                update={"local_clearance_m": 1.0e-5}
                            )
                        }
                    )
                    for patch in ir.patches
                ]
            }
        ),
        config=PrePLCAuditConfigV1(first_layer_height_m=5.0e-5),
    )
    plc_match = next(
        match for match in registry.detect(ir, audit_report=audit).matches if match.kind == "VOLUME_ENTRY_PLC_RISK"
    )

    result = OperatorLibraryV1().execute("reject_unsupported_plc_risk_family", plc_match, ir, audit_report=audit)

    assert result.status == "rejected"
    assert result.applied is False
    assert result.report_key == "unsupported_plc_risk_family"
    assert result.details["blocking_check_kinds"] == ["local_clearance_vs_first_layer_height"]


def test_build_topology_ir_v1_classifies_truncation_connector_band_from_compiler_context():
    ir = _build_truncation_connector_band_ir(include_extra_pre_band_section=True)

    connector_patch = next(
        patch for patch in ir.patches if patch.source_patch_family == "truncation_connector_band"
    )

    assert connector_patch.local_descriptors.truncation_band_role["status"] == "classified"
    assert connector_patch.local_descriptors.truncation_band_role["role"] == "connector_band"
    assert connector_patch.metadata["truncation_start_y_le_m"] == pytest.approx(14.998333333333333)


def test_truncation_connector_band_operator_regularizes_single_extra_pre_band_support_family():
    ir = _build_truncation_connector_band_ir(include_extra_pre_band_section=True)
    registry = MotifRegistryV1()
    library = OperatorLibraryV1()

    band_match = next(
        match for match in registry.detect(ir).matches if match.kind == "TRUNCATION_CONNECTOR_BAND"
    )
    result = library.execute("regularize_truncation_connector_band", band_match, ir)

    assert result.status == "applied"
    assert result.applied is True
    plan = result.details["regularization_plan"]
    assert plan["applicable"] is True
    assert plan["drop_section_y_le_m"] == [pytest.approx(13.5)]
    assert plan["keep_section_y_le_m"] == pytest.approx(
        [0.0, 14.992006138888888, 14.998333333333333, 16.5]
    )
    assert plan["limitation"] == "v1_only_regularizes_one_extra_pre_band_support_section"


def test_truncation_connector_band_operator_rejects_already_canonical_fixture():
    ir = _build_truncation_connector_band_ir(include_extra_pre_band_section=False)
    registry = MotifRegistryV1()
    library = OperatorLibraryV1()

    band_match = next(
        match for match in registry.detect(ir).matches if match.kind == "TRUNCATION_CONNECTOR_BAND"
    )
    result = library.execute("regularize_truncation_connector_band", band_match, ir)

    assert result.status == "rejected"
    assert result.applied is False
    plan = result.details["regularization_plan"]
    assert plan["applicable"] is False
    assert plan["reject_reasons"] == ["already_canonical_connector_band_family"]


def test_post_band_transition_split_operator_targets_canonical_segment_facet_family():
    ir = _build_truncation_connector_band_ir(include_extra_pre_band_section=False)
    audit = run_pre_plc_audit_v1(
        ir,
        config=PrePLCAuditConfigV1(
            observed_evidence=[
                PrePLCAuditObservedEvidenceV1(
                    fixture_id="shell_v4_pre_plc::root_last3_segment_facet",
                    check_kind="segment_facet_intersection_risk",
                    error_text="PLC Error:  A segment and a facet intersect at point",
                    selected_section_y_le_m=[0.0, 14.992006138888888, 14.998333333333333, 16.5],
                )
            ]
        ),
    )
    registry = MotifRegistryV1()
    library = OperatorLibraryV1()

    match = next(
        match
        for match in registry.detect(ir, audit_report=audit).matches
        if match.kind == "CANONICAL_CONNECTOR_BAND_POST_TRANSITION"
    )
    result = library.execute("prototype_split_post_band_transition", match, ir, audit_report=audit)

    assert match.entity_ids == [
        "patch:fixture_band:0:1",
        "patch:fixture_band:1:2",
        "patch:fixture_band:2:3",
    ]
    assert match.predicate_evidence["pre_band_support_patch_count"] == 0
    assert match.predicate_evidence["blocking_topology_check_kinds"] == ["segment_facet_intersection_risk"]
    assert result.status == "applied"
    assert result.applied is True
    plan = result.details["transition_split_plan"]
    assert plan["applicable"] is True
    assert plan["split_fraction"] == pytest.approx(1.0 / 3.0)
    assert plan["proposed_split_y_le_m"] == pytest.approx(15.498888888888889)
    assert plan["transition_span_m"] == pytest.approx(1.5016666666666665)
    assert plan["blocking_topology_check_kinds"] == ["segment_facet_intersection_risk"]


def test_post_transition_boundary_recovery_error_2_family_is_structured():
    ir = _build_post_transition_boundary_recovery_ir()
    audit = run_pre_plc_audit_v1(
        ir,
        config=PrePLCAuditConfigV1(
            observed_evidence=[
                PrePLCAuditObservedEvidenceV1(
                    fixture_id="shell_v4_pre_plc::root_last3_post_transition_error2",
                    check_kind="boundary_recovery_error_2_risk",
                    error_text="Error   : Could not recover boundary mesh: error 2",
                    selected_section_y_le_m=[
                        0.0,
                        14.992006138888888,
                        14.998333333333333,
                        15.498888888888889,
                        16.5,
                    ],
                )
            ]
        ),
    )
    registry = MotifRegistryV1()
    library = OperatorLibraryV1()

    match = next(
        match
        for match in registry.detect(ir, audit_report=audit).matches
        if match.kind == "POST_BAND_TRANSITION_BOUNDARY_RECOVERY"
    )
    assert match.admissible_operators == ["prototype_regularize_post_transition_boundary_recovery"]
    result = library.execute(
        "prototype_regularize_post_transition_boundary_recovery",
        match,
        ir,
        audit_report=audit,
    )

    assert audit.blocking_topology_check_kinds == ["boundary_recovery_error_2_risk"]
    assert match.predicate_evidence["geometry_contact_locus_kind"] == "post_band_transition_guard_to_tip"
    assert match.predicate_evidence["transition_guard_patch_count"] == 1
    assert match.predicate_evidence["transition_terminal_patch_count"] == 1
    assert result.status == "applied"
    assert result.applied is True
    plan = result.details["boundary_recovery_regularization_plan"]
    assert plan["applicable"] is True
    assert plan["blocking_topology_check_kinds"] == ["boundary_recovery_error_2_risk"]
    assert plan["geometry_contact_locus_kind"] == "post_band_transition_guard_to_tip"
    assert plan["transition_guard_patch_ids"] == ["patch:fixture_band:2:3"]
    assert plan["transition_terminal_patch_ids"] == ["patch:fixture_band:3:4"]
    assert plan["mutation_kind"] == "insert_transition_terminal_relief_section"
    assert plan["acts_on_interval_role"] == "post_band_transition_guard_to_tip_terminal"
    assert plan["proposed_relief_y_le_m"] == pytest.approx(15.9)
    assert plan["contact_locus_span_m_after"] < plan["contact_locus_span_m_before"]


def test_pre_plc_audit_v1_reports_required_checks_and_fails_clearance_guard():
    ir = _build_minimal_ir().model_copy(
        update={
            "patches": [
                patch.model_copy(
                    update={
                        "local_descriptors": patch.local_descriptors.model_copy(
                            update={"local_clearance_m": 1.0e-5 if index == 1 else 1.2e-4}
                        )
                    }
                )
                for index, patch in enumerate(_build_minimal_ir().patches)
            ]
        }
    )
    report = run_pre_plc_audit_v1(ir, config=PrePLCAuditConfigV1(first_layer_height_m=5.0e-5))
    checks = {check.kind: check for check in report.checks}

    assert report.contract == "pre_plc_audit.v1"
    assert set(checks) == {
        "segment_facet_intersection_risk",
        "facet_facet_overlap_risk",
        "boundary_recovery_error_2_risk",
        "extrusion_self_contact_risk",
        "degenerated_prism_risk",
        "local_clearance_vs_first_layer_height",
        "manifold_loop_consistency",
    }
    assert checks["local_clearance_vs_first_layer_height"].status == "fail"
    assert checks["local_clearance_vs_first_layer_height"].implemented is True
    assert checks["manifold_loop_consistency"].status == "pass"
    assert checks["segment_facet_intersection_risk"].status == "not_evaluated"
    assert checks["segment_facet_intersection_risk"].assessment == "placeholder"
    assert report.bl_clearance_compatibility.verdict == "unsupported"


def test_pre_plc_audit_v1_distinguishes_observed_inferred_placeholder_and_unsupported_checks():
    ir = _build_minimal_ir().model_copy(
        update={
            "patches": [
                patch.model_copy(
                    update={
                        "local_descriptors": patch.local_descriptors.model_copy(
                            update={"local_clearance_m": 1.0e-5 if index == 1 else 1.2e-4}
                        )
                    }
                )
                for index, patch in enumerate(_build_minimal_ir().patches)
            ]
        }
    )
    report = run_pre_plc_audit_v1(
        ir,
        config=PrePLCAuditConfigV1(
            total_boundary_layer_thickness_m=5.0e-5,
            observed_evidence=[
                PrePLCAuditObservedEvidenceV1(
                    fixture_id="shell_v4_pre_plc::root_last3_segment_facet",
                    check_kind="segment_facet_intersection_risk",
                    error_text="PLC Error:  A segment and a facet intersect at point",
                    selected_section_y_le_m=[0.0, 14.992006, 14.998333, 16.5],
                ),
                PrePLCAuditObservedEvidenceV1(
                    fixture_id="shell_v4_pre_plc::root_last4_overlap",
                    check_kind="facet_facet_overlap_risk",
                    error_text="Invalid boundary mesh (overlapping facets) on surface 30 surface 34",
                    selected_section_y_le_m=[0.0, 13.5, 14.992006, 14.998333, 16.5],
                ),
            ],
        ),
    )
    checks = {check.kind: check for check in report.checks}

    assert checks["segment_facet_intersection_risk"].assessment == "observed"
    assert checks["segment_facet_intersection_risk"].status == "fail"
    assert checks["facet_facet_overlap_risk"].assessment == "observed"
    assert checks["facet_facet_overlap_risk"].status == "fail"
    assert checks["extrusion_self_contact_risk"].assessment == "inferred"
    assert checks["extrusion_self_contact_risk"].status == "fail"
    assert checks["degenerated_prism_risk"].assessment == "placeholder"
    assert checks["degenerated_prism_risk"].status == "not_evaluated"
    assert checks["local_clearance_vs_first_layer_height"].assessment == "unsupported"
    assert checks["local_clearance_vs_first_layer_height"].status == "not_evaluated"
    assert report.bl_clearance_compatibility.total_bl_thickness_m == pytest.approx(5.0e-5)
    assert report.bl_clearance_compatibility.min_local_clearance_m == pytest.approx(1.0e-5)
    assert report.bl_clearance_compatibility.clearance_to_thickness_ratio == pytest.approx(0.2)
    assert report.bl_clearance_compatibility.verdict == "insufficient_clearance"
    assert report.summary.observed_topology_fail_count == 2
    assert report.summary.bl_compatibility_fail_count == 1
    assert report.blocking_topology_check_kinds == [
        "segment_facet_intersection_risk",
        "facet_facet_overlap_risk",
    ]
    assert report.blocking_bl_compatibility_check_kinds == ["extrusion_self_contact_risk"]
    assert report.planning_policy.status == "fail"
    assert report.planning_policy.verdict == "blocked_by_bl_compatibility"
    assert report.planning_policy.blocking_kind == "bl_compatibility_policy_fail"
    assert report.planning_policy_fail_kinds == ["bl_clearance_incompatibility"]
    assert report.summary.planning_policy_fail_count == 1


def test_pre_plc_audit_v1_surfaces_budgeting_recommendations_separately():
    ir = _build_minimal_ir().model_copy(
        update={
            "patches": [
                patch.model_copy(
                    update={
                        "local_descriptors": patch.local_descriptors.model_copy(
                            update={"local_clearance_m": 1.0e-5 if index == 1 else 1.2e-4}
                        )
                    }
                )
                for index, patch in enumerate(_build_minimal_ir().patches)
            ]
        }
    )
    budgeting = PlanningBudgetingV1(
        status="available",
        total_bl_thickness_m=5.0e-5,
        section_budgets=[
            PlanningBudgetSectionV1(
                section_id="section_y:15.400000",
                span_y_m=15.4,
                region_kind="tip_truncation_candidate_zone",
                sample_count=19,
                triggered_sample_count=11,
                min_local_half_thickness_m=1.5e-5,
                min_clearance_to_thickness_ratio=0.3,
                min_available_budget_ratio=0.24,
                min_required_scale_for_tip_clearance=0.22,
                min_predicted_bl_top_clearance_m=0.0,
                clearance_pressure=0.76,
                recommended_action_kinds=[
                    "shrink_total_thickness",
                    "split_region_budget",
                    "truncate_tip_zone",
                ],
            )
        ],
        region_budgets=[
            PlanningBudgetRegionV1(
                region_id="region:tip_truncation_candidate_zone",
                region_kind="tip_truncation_candidate_zone",
                section_ids=["section_y:15.400000"],
                section_count=1,
                span_y_range_m={"min": 15.4, "max": 15.4},
                min_clearance_to_thickness_ratio=0.3,
                min_available_budget_ratio=0.24,
                peak_clearance_pressure=0.76,
                recommended_action_kinds=[
                    "shrink_total_thickness",
                    "split_region_budget",
                    "truncate_tip_zone",
                ],
            )
        ],
        tightest_section_ids=["section_y:15.400000"],
        tightest_region_ids=["region:tip_truncation_candidate_zone"],
        recommendation_kinds=[
            "shrink_total_thickness",
            "split_region_budget",
            "truncate_tip_zone",
        ],
    )

    report = run_pre_plc_audit_v1(
        ir,
        config=PrePLCAuditConfigV1(
            total_boundary_layer_thickness_m=5.0e-5,
            planning_budgeting=budgeting,
        ),
    )

    assert report.blocking_bl_compatibility_check_kinds == ["extrusion_self_contact_risk"]
    assert report.planning_policy_fail_kinds == ["bl_clearance_incompatibility"]
    assert report.planning_policy_recommendation_kinds == [
        "shrink_total_thickness",
        "split_region_budget",
        "truncate_tip_zone",
    ]
    assert report.planning_policy.recommendation_kinds == [
        "shrink_total_thickness",
        "split_region_budget",
        "truncate_tip_zone",
    ]
    assert report.planning_budgeting.tightest_section_ids == ["section_y:15.400000"]
    assert report.summary.planning_policy_recommendation_count == 3


def test_topology_compiler_v1_artifacts_and_shell_role_policies_stay_separated(tmp_path: Path):
    shell_v3_policy = resolve_shell_role_policy_v1("shell_v3")
    shell_v4_policy = resolve_shell_role_policy_v1("shell_v4")

    assert shell_v3_policy.allows_near_wall_mainline is False
    assert shell_v3_policy.allows_geometry_baseline_mutation is False
    assert shell_v4_policy.allows_near_wall_mainline is True
    assert shell_v4_policy.is_frozen_geometry_baseline is False

    result = compile_topology_family_v1(
        topology_report=_sample_topology_report(),
        topology_lineage_report=_sample_lineage_report(),
        topology_suppression_report=_sample_suppression_report(),
        component="main_wing",
        shell_role="shell_v4",
        out_dir=tmp_path,
        audit_config=PrePLCAuditConfigV1(first_layer_height_m=5.0e-5),
    )

    assert result.contract == "topology_compiler.v1"
    assert result.shell_role_policy.role_name == "shell_v4_active_bl_validation"
    assert result.operator_plan.execution_gate == "plan_only"
    assert Path(result.artifacts.topology_ir).exists()
    assert Path(result.artifacts.pre_plc_audit).exists()
    assert Path(result.artifacts.motif_registry).exists()
    assert Path(result.artifacts.operator_plan).exists()

    summary = json.loads((tmp_path / "topology_compiler_summary.v1.json").read_text(encoding="utf-8"))
    assert summary["shell_role_policy"]["role_name"] == "shell_v4_active_bl_validation"
    assert summary["artifacts"]["topology_ir"].endswith("topology_ir.v1.json")
    assert summary["artifacts"]["summary"].endswith("topology_compiler_summary.v1.json")
    assert summary["pre_plc_audit"]["bl_clearance_compatibility"]["verdict"] == "unsupported"


def test_topology_compiler_summary_surfaces_bl_planning_policy_separately(tmp_path: Path):
    result = compile_topology_family_v1(
        topology_report=_sample_topology_report(),
        topology_lineage_report=_sample_lineage_report(),
        topology_suppression_report=_sample_suppression_report(),
        component="main_wing",
        shell_role="shell_v4",
        out_dir=tmp_path,
        audit_config=PrePLCAuditConfigV1(
            total_boundary_layer_thickness_m=0.03617304985338917,
            planning_budgeting=PlanningBudgetingV1(
                status="available",
                total_bl_thickness_m=0.03617304985338917,
                section_budgets=[
                    PlanningBudgetSectionV1(
                        section_id="section_y:15.400000",
                        span_y_m=15.4,
                        region_kind="tip_truncation_candidate_zone",
                        sample_count=19,
                        triggered_sample_count=11,
                        min_local_half_thickness_m=0.01,
                        min_clearance_to_thickness_ratio=0.28,
                        min_available_budget_ratio=0.24,
                        min_required_scale_for_tip_clearance=0.22,
                        min_predicted_bl_top_clearance_m=0.0,
                        clearance_pressure=0.76,
                        recommended_action_kinds=[
                            "shrink_total_thickness",
                            "truncate_tip_zone",
                        ],
                    )
                ],
                region_budgets=[
                    PlanningBudgetRegionV1(
                        region_id="region:tip_truncation_candidate_zone",
                        region_kind="tip_truncation_candidate_zone",
                        section_ids=["section_y:15.400000"],
                        section_count=1,
                        span_y_range_m={"min": 15.4, "max": 15.4},
                        min_clearance_to_thickness_ratio=0.28,
                        min_available_budget_ratio=0.24,
                        peak_clearance_pressure=0.76,
                        recommended_action_kinds=[
                            "shrink_total_thickness",
                            "truncate_tip_zone",
                        ],
                    )
                ],
                tightest_section_ids=["section_y:15.400000"],
                tightest_region_ids=["region:tip_truncation_candidate_zone"],
                recommendation_kinds=[
                    "shrink_total_thickness",
                    "truncate_tip_zone",
                ],
            ),
            observed_evidence=[
                PrePLCAuditObservedEvidenceV1(
                    fixture_id="shell_v4_pre_plc::root_last3_segment_facet",
                    check_kind="segment_facet_intersection_risk",
                    error_text="PLC Error:  A segment and a facet intersect at point",
                    selected_section_y_le_m=[0.0, 14.992006138888888, 14.998333333333333, 16.5],
                )
            ],
        ),
    )

    summary = json.loads((tmp_path / "topology_compiler_summary.v1.json").read_text(encoding="utf-8"))

    assert result.pre_plc_audit.blocking_topology_check_kinds == ["segment_facet_intersection_risk"]
    assert result.pre_plc_audit.blocking_bl_compatibility_check_kinds == ["extrusion_self_contact_risk"]
    assert result.pre_plc_audit.planning_policy_fail_kinds == ["bl_clearance_incompatibility"]
    assert result.pre_plc_audit.planning_policy.verdict == "blocked_by_bl_compatibility"
    assert summary["pre_plc_audit"]["blocking_topology_check_kinds"] == ["segment_facet_intersection_risk"]
    assert summary["pre_plc_audit"]["blocking_bl_compatibility_check_kinds"] == ["extrusion_self_contact_risk"]
    assert summary["pre_plc_audit"]["planning_policy_fail_kinds"] == ["bl_clearance_incompatibility"]
    assert summary["pre_plc_audit"]["planning_policy_recommendation_kinds"] == [
        "shrink_total_thickness",
        "truncate_tip_zone",
    ]
    assert summary["pre_plc_audit"]["planning_policy"]["blocking_kind"] == "bl_compatibility_policy_fail"
    assert summary["pre_plc_audit"]["planning_budgeting"]["tightest_region_ids"] == [
        "region:tip_truncation_candidate_zone"
    ]
