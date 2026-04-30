import json
import os
from pathlib import Path
import subprocess
import sys

from hpa_meshing.cli import build_parser


def test_parser_builds():
    parser = build_parser()
    assert parser.prog == "hpa-mesh"


def test_parser_supports_mesh_study_command():
    parser = build_parser()
    args = parser.parse_args(["mesh-study", "--config", "configs/demo.yaml"])
    assert args.command == "mesh-study"
    assert args.config == "configs/demo.yaml"


def test_parser_supports_baseline_freeze_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "baseline-freeze",
            "--baseline-manifest",
            "artifacts/baseline.json",
            "--out",
            "artifacts/regression.json",
        ]
    )
    assert args.command == "baseline-freeze"
    assert args.baseline_manifest == "artifacts/baseline.json"
    assert args.out == "artifacts/regression.json"


def test_parser_supports_baseline_cfd_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "baseline-cfd",
            "--baseline-manifest",
            "artifacts/baseline.json",
            "--out",
            "artifacts/su2_route",
        ]
    )
    assert args.command == "baseline-cfd"
    assert args.baseline_manifest == "artifacts/baseline.json"
    assert args.out == "artifacts/su2_route"


def test_parser_supports_shell_v3_refinement_study_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "shell-v3-refinement-study",
            "--baseline-manifest",
            "artifacts/baseline.json",
            "--out",
            "artifacts/refinement",
        ]
    )
    assert args.command == "shell-v3-refinement-study"
    assert args.baseline_manifest == "artifacts/baseline.json"
    assert args.out == "artifacts/refinement"


def test_parser_supports_shell_v4_half_wing_bl_mesh_macsafe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "shell-v4-half-wing-bl-mesh-macsafe",
            "--out",
            "artifacts/shell_v4",
            "--study-level",
            "BL_macsafe_upper",
            "--skip-su2",
            "--topology-compiler-plan-only",
            "--apply-bl-stageback-plus-truncation-focused",
            "--apply-bl-stage-with-termination-guard-8-to-7-focused",
            "--run-bl-candidate-sweep-focused",
        ]
    )
    assert args.command == "shell-v4-half-wing-bl-mesh-macsafe"
    assert args.out == "artifacts/shell_v4"
    assert args.study_level == "BL_macsafe_upper"
    assert args.skip_su2 is True
    assert args.topology_compiler_plan_only is True
    assert args.apply_bl_stageback_plus_truncation_focused is True
    assert args.apply_bl_stage_with_termination_guard_8_to_7_focused is True
    assert args.run_bl_candidate_sweep_focused is True

    default_args = parser.parse_args(
        [
            "shell-v4-half-wing-bl-mesh-macsafe",
            "--out",
            "artifacts/shell_v4",
        ]
    )
    assert default_args.apply_bl_stageback_plus_truncation_focused is False
    assert default_args.apply_bl_stage_with_termination_guard_8_to_7_focused is False
    assert default_args.run_bl_candidate_sweep_focused is False


def test_parser_supports_route_readiness_command():
    parser = build_parser()
    args = parser.parse_args(["route-readiness", "--out", "artifacts/route_readiness"])

    assert args.command == "route-readiness"
    assert args.out == "artifacts/route_readiness"


def test_parser_supports_component_family_smoke_matrix_command():
    parser = build_parser()
    args = parser.parse_args(
        ["component-family-smoke-matrix", "--out", "artifacts/route_smoke"]
    )

    assert args.command == "component-family-smoke-matrix"
    assert args.out == "artifacts/route_smoke"


def test_parser_supports_fairing_solid_mesh_handoff_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        ["fairing-solid-mesh-handoff-smoke", "--out", "artifacts/fairing_smoke"]
    )

    assert args.command == "fairing-solid-mesh-handoff-smoke"
    assert args.out == "artifacts/fairing_smoke"


def test_parser_supports_fairing_solid_real_geometry_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "fairing-solid-real-geometry-smoke",
            "--out",
            "artifacts/fairing_real_geometry_smoke",
            "--source",
            "fairing.vsp3",
        ]
    )

    assert args.command == "fairing-solid-real-geometry-smoke"
    assert args.out == "artifacts/fairing_real_geometry_smoke"
    assert args.source == "fairing.vsp3"


def test_parser_supports_fairing_solid_real_mesh_handoff_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "fairing-solid-real-mesh-handoff-probe",
            "--out",
            "artifacts/fairing_real_mesh_probe",
            "--source",
            "fairing.vsp3",
            "--timeout-seconds",
            "30",
        ]
    )

    assert args.command == "fairing-solid-real-mesh-handoff-probe"
    assert args.out == "artifacts/fairing_real_mesh_probe"
    assert args.source == "fairing.vsp3"
    assert args.timeout_seconds == 30.0


def test_parser_supports_main_wing_mesh_handoff_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        ["main-wing-mesh-handoff-smoke", "--out", "artifacts/main_wing_smoke"]
    )

    assert args.command == "main-wing-mesh-handoff-smoke"
    assert args.out == "artifacts/main_wing_smoke"


def test_parser_supports_main_wing_esp_rebuilt_geometry_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-esp-rebuilt-geometry-smoke",
            "--out",
            "artifacts/main_wing_esp_geometry_smoke",
        ]
    )

    assert args.command == "main-wing-esp-rebuilt-geometry-smoke"
    assert args.out == "artifacts/main_wing_esp_geometry_smoke"


def test_parser_supports_main_wing_real_mesh_handoff_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-real-mesh-handoff-probe",
            "--out",
            "artifacts/main_wing_real_mesh_probe",
            "--global-min-size",
            "0.35",
            "--global-max-size",
            "1.4",
        ]
    )

    assert args.command == "main-wing-real-mesh-handoff-probe"
    assert args.out == "artifacts/main_wing_real_mesh_probe"
    assert args.global_min_size == 0.35
    assert args.global_max_size == 1.4


def test_parser_supports_main_wing_route_readiness_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-route-readiness",
            "--out",
            "artifacts/main_wing_route_readiness",
        ]
    )

    assert args.command == "main-wing-route-readiness"
    assert args.out == "artifacts/main_wing_route_readiness"


def test_parser_supports_main_wing_solver_budget_comparison_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-solver-budget-comparison",
            "--out",
            "artifacts/main_wing_solver_budget_comparison",
            "--report-root",
            "docs/reports",
        ]
    )

    assert args.command == "main-wing-solver-budget-comparison"
    assert args.out == "artifacts/main_wing_solver_budget_comparison"
    assert args.report_root == "docs/reports"


def test_parser_supports_main_wing_lift_acceptance_diagnostic_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-lift-acceptance-diagnostic",
            "--out",
            "artifacts/main_wing_lift_acceptance_diagnostic",
            "--report-root",
            "docs/reports",
        ]
    )

    assert args.command == "main-wing-lift-acceptance-diagnostic"
    assert args.out == "artifacts/main_wing_lift_acceptance_diagnostic"
    assert args.report_root == "docs/reports"


def test_parser_supports_main_wing_panel_su2_lift_gap_debug_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-panel-su2-lift-gap-debug",
            "--out",
            "artifacts/main_wing_panel_su2_lift_gap_debug",
            "--report-root",
            "docs/reports",
        ]
    )

    assert args.command == "main-wing-panel-su2-lift-gap-debug"
    assert args.out == "artifacts/main_wing_panel_su2_lift_gap_debug"
    assert args.report_root == "docs/reports"


def test_parser_supports_main_wing_su2_mesh_normal_audit_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-su2-mesh-normal-audit",
            "--out",
            "artifacts/main_wing_su2_mesh_normal_audit",
            "--mesh",
            "artifacts/main_wing/mesh.msh",
        ]
    )

    assert args.command == "main-wing-su2-mesh-normal-audit"
    assert args.out == "artifacts/main_wing_su2_mesh_normal_audit"
    assert args.mesh == "artifacts/main_wing/mesh.msh"


def test_parser_supports_main_wing_panel_wake_semantics_audit_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-panel-wake-semantics-audit",
            "--out",
            "artifacts/main_wing_panel_wake_semantics_audit",
            "--report-root",
            "docs/reports",
            "--runtime-cfg",
            "artifacts/source_su2/su2_runtime.cfg",
        ]
    )

    assert args.command == "main-wing-panel-wake-semantics-audit"
    assert args.out == "artifacts/main_wing_panel_wake_semantics_audit"
    assert args.report_root == "docs/reports"
    assert args.runtime_cfg == "artifacts/source_su2/su2_runtime.cfg"


def test_parser_supports_main_wing_su2_surface_topology_audit_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-su2-surface-topology-audit",
            "--out",
            "artifacts/main_wing_su2_surface_topology_audit",
            "--mesh",
            "artifacts/main_wing/mesh.msh",
            "--reference-area",
            "35.175",
        ]
    )

    assert args.command == "main-wing-su2-surface-topology-audit"
    assert args.out == "artifacts/main_wing_su2_surface_topology_audit"
    assert args.mesh == "artifacts/main_wing/mesh.msh"
    assert args.reference_area == 35.175


def test_parser_supports_main_wing_su2_topology_defect_localization_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-su2-topology-defect-localization",
            "--out",
            "artifacts/main_wing_su2_topology_defect_localization",
            "--mesh",
            "artifacts/main_wing/mesh.msh",
        ]
    )

    assert args.command == "main-wing-su2-topology-defect-localization"
    assert args.out == "artifacts/main_wing_su2_topology_defect_localization"
    assert args.mesh == "artifacts/main_wing/mesh.msh"


def test_parser_supports_main_wing_openvsp_defect_station_audit_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-openvsp-defect-station-audit",
            "--out",
            "artifacts/main_wing_openvsp_defect_station_audit",
            "--defect-localization",
            "artifacts/main_wing/defects.json",
            "--topology-lineage",
            "artifacts/main_wing/topology_lineage_report.json",
            "--source-vsp3",
            "artifacts/main_wing/main_wing.vsp3",
        ]
    )

    assert args.command == "main-wing-openvsp-defect-station-audit"
    assert args.out == "artifacts/main_wing_openvsp_defect_station_audit"
    assert args.defect_localization == "artifacts/main_wing/defects.json"
    assert args.topology_lineage == "artifacts/main_wing/topology_lineage_report.json"
    assert args.source_vsp3 == "artifacts/main_wing/main_wing.vsp3"


def test_parser_supports_main_wing_gmsh_defect_entity_trace_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-gmsh-defect-entity-trace",
            "--out",
            "artifacts/main_wing_gmsh_defect_entity_trace",
            "--mesh",
            "artifacts/main_wing/mesh.msh",
            "--defect-localization",
            "artifacts/main_wing/defects.json",
            "--openvsp-station-audit",
            "artifacts/main_wing/station_audit.json",
            "--surface-patch-diagnostics",
            "artifacts/main_wing/surface_patch_diagnostics.json",
        ]
    )

    assert args.command == "main-wing-gmsh-defect-entity-trace"
    assert args.out == "artifacts/main_wing_gmsh_defect_entity_trace"
    assert args.mesh == "artifacts/main_wing/mesh.msh"
    assert args.defect_localization == "artifacts/main_wing/defects.json"
    assert args.openvsp_station_audit == "artifacts/main_wing/station_audit.json"
    assert args.surface_patch_diagnostics == (
        "artifacts/main_wing/surface_patch_diagnostics.json"
    )


def test_parser_supports_main_wing_gmsh_curve_station_rebuild_audit_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-gmsh-curve-station-rebuild-audit",
            "--out",
            "artifacts/main_wing_gmsh_curve_station_rebuild_audit",
            "--gmsh-defect-entity-trace",
            "artifacts/main_wing/entity_trace.json",
            "--source-vsp3",
            "artifacts/main_wing/main_wing.vsp3",
        ]
    )

    assert args.command == "main-wing-gmsh-curve-station-rebuild-audit"
    assert args.out == "artifacts/main_wing_gmsh_curve_station_rebuild_audit"
    assert args.gmsh_defect_entity_trace == "artifacts/main_wing/entity_trace.json"
    assert args.source_vsp3 == "artifacts/main_wing/main_wing.vsp3"


def test_parser_supports_main_wing_openvsp_section_station_topology_fixture_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-openvsp-section-station-topology-fixture",
            "--out",
            "artifacts/main_wing_openvsp_section_station_topology_fixture",
            "--gmsh-defect-entity-trace",
            "artifacts/main_wing/entity_trace.json",
            "--gmsh-curve-station-rebuild-audit",
            "artifacts/main_wing/curve_audit.json",
        ]
    )

    assert args.command == "main-wing-openvsp-section-station-topology-fixture"
    assert args.out == "artifacts/main_wing_openvsp_section_station_topology_fixture"
    assert args.gmsh_defect_entity_trace == "artifacts/main_wing/entity_trace.json"
    assert args.gmsh_curve_station_rebuild_audit == (
        "artifacts/main_wing/curve_audit.json"
    )


def test_parser_supports_main_wing_station_seam_repair_decision_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-station-seam-repair-decision",
            "--out",
            "artifacts/main_wing_station_seam_repair_decision",
            "--topology-fixture",
            "artifacts/main_wing/station_fixture.json",
            "--solver-report",
            "artifacts/main_wing/solver.json",
        ]
    )

    assert args.command == "main-wing-station-seam-repair-decision"
    assert args.out == "artifacts/main_wing_station_seam_repair_decision"
    assert args.topology_fixture == "artifacts/main_wing/station_fixture.json"
    assert args.solver_report == "artifacts/main_wing/solver.json"


def test_parser_supports_main_wing_station_seam_brep_hotspot_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-station-seam-brep-hotspot-probe",
            "--out",
            "artifacts/main_wing_station_seam_brep_hotspot_probe",
            "--topology-fixture",
            "artifacts/main_wing/station_fixture.json",
            "--real-mesh-probe-report",
            "artifacts/main_wing/mesh_probe.json",
            "--normalized-step",
            "artifacts/main_wing/normalized.stp",
            "--surface-patch-diagnostics",
            "artifacts/main_wing/surface_patch_diagnostics.json",
            "--curve-tags",
            "36",
            "50",
            "--surface-tags",
            "12",
            "13",
            "19",
            "20",
        ]
    )

    assert args.command == "main-wing-station-seam-brep-hotspot-probe"
    assert args.out == "artifacts/main_wing_station_seam_brep_hotspot_probe"
    assert args.topology_fixture == "artifacts/main_wing/station_fixture.json"
    assert args.real_mesh_probe_report == "artifacts/main_wing/mesh_probe.json"
    assert args.normalized_step == "artifacts/main_wing/normalized.stp"
    assert args.surface_patch_diagnostics == (
        "artifacts/main_wing/surface_patch_diagnostics.json"
    )
    assert args.curve_tags == [36, 50]
    assert args.surface_tags == [12, 13, 19, 20]


def test_parser_supports_main_wing_station_seam_profile_resample_brep_validation_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-station-seam-profile-resample-brep-validation-probe",
            "--out",
            "artifacts/main_wing_profile_resample_brep_validation",
            "--profile-resample-probe",
            "artifacts/main_wing/profile_resample.json",
            "--candidate-step",
            "artifacts/main_wing/candidate_raw_dump.stp",
            "--station-y-targets",
            "-10.5",
            "13.5",
            "--station-tolerance",
            "1e-4",
            "--scale-to-output-units",
            "1.0",
        ]
    )

    assert (
        args.command
        == "main-wing-station-seam-profile-resample-brep-validation-probe"
    )
    assert args.out == "artifacts/main_wing_profile_resample_brep_validation"
    assert args.profile_resample_probe == "artifacts/main_wing/profile_resample.json"
    assert args.candidate_step == "artifacts/main_wing/candidate_raw_dump.stp"
    assert args.station_y_targets == [-10.5, 13.5]
    assert args.station_tolerance == 1e-4
    assert args.scale_to_output_units == 1.0


def test_parser_supports_main_wing_station_seam_profile_resample_repair_feasibility_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-station-seam-profile-resample-repair-feasibility-probe",
            "--out",
            "artifacts/main_wing_profile_resample_repair_feasibility",
            "--brep-validation-probe",
            "artifacts/main_wing/profile_resample_brep_validation.json",
            "--tolerances",
            "1e-7",
            "1e-5",
            "--operations",
            "fix_same_parameter_edge",
            "remove_add_pcurve_then_same_parameter",
        ]
    )

    assert (
        args.command
        == "main-wing-station-seam-profile-resample-repair-feasibility-probe"
    )
    assert args.out == "artifacts/main_wing_profile_resample_repair_feasibility"
    assert args.brep_validation_probe == (
        "artifacts/main_wing/profile_resample_brep_validation.json"
    )
    assert args.tolerances == [1e-7, 1e-5]
    assert args.operations == [
        "fix_same_parameter_edge",
        "remove_add_pcurve_then_same_parameter",
    ]


def test_parser_supports_main_wing_station_seam_same_parameter_feasibility_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-station-seam-same-parameter-feasibility",
            "--out",
            "artifacts/main_wing_station_seam_same_parameter_feasibility",
            "--brep-hotspot-probe",
            "artifacts/main_wing/brep_hotspot.json",
            "--tolerances",
            "1e-7",
            "1e-5",
        ]
    )

    assert args.command == "main-wing-station-seam-same-parameter-feasibility"
    assert args.out == "artifacts/main_wing_station_seam_same_parameter_feasibility"
    assert args.brep_hotspot_probe == "artifacts/main_wing/brep_hotspot.json"
    assert args.tolerances == [1e-7, 1e-5]


def test_parser_supports_main_wing_station_seam_shape_fix_feasibility_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-station-seam-shape-fix-feasibility",
            "--out",
            "artifacts/main_wing_station_seam_shape_fix_feasibility",
            "--same-parameter-feasibility",
            "artifacts/main_wing/same_parameter.json",
            "--tolerances",
            "1e-7",
            "1e-5",
            "--operations",
            "fix_same_parameter_edge",
            "remove_add_pcurve_then_same_parameter",
        ]
    )

    assert args.command == "main-wing-station-seam-shape-fix-feasibility"
    assert args.out == "artifacts/main_wing_station_seam_shape_fix_feasibility"
    assert args.same_parameter_feasibility == (
        "artifacts/main_wing/same_parameter.json"
    )
    assert args.tolerances == [1e-7, 1e-5]
    assert args.operations == [
        "fix_same_parameter_edge",
        "remove_add_pcurve_then_same_parameter",
    ]


def test_parser_supports_main_wing_station_seam_export_source_audit_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-station-seam-export-source-audit",
            "--out",
            "artifacts/main_wing_station_seam_export_source_audit",
            "--shape-fix-feasibility",
            "artifacts/main_wing/shape_fix.json",
            "--topology-fixture",
            "artifacts/main_wing/station_fixture.json",
            "--rebuild-csm",
            "artifacts/main_wing/rebuild.csm",
            "--topology-lineage",
            "artifacts/main_wing/topology_lineage_report.json",
        ]
    )

    assert args.command == "main-wing-station-seam-export-source-audit"
    assert args.out == "artifacts/main_wing_station_seam_export_source_audit"
    assert args.shape_fix_feasibility == "artifacts/main_wing/shape_fix.json"
    assert args.topology_fixture == "artifacts/main_wing/station_fixture.json"
    assert args.rebuild_csm == "artifacts/main_wing/rebuild.csm"
    assert args.topology_lineage == "artifacts/main_wing/topology_lineage_report.json"


def test_parser_supports_main_wing_station_seam_export_strategy_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-station-seam-export-strategy-probe",
            "--out",
            "artifacts/main_wing_station_seam_export_strategy_probe",
            "--export-source-audit",
            "artifacts/main_wing/export_source_audit.json",
            "--materialize-candidates",
            "--timeout-seconds",
            "12.5",
        ]
    )

    assert args.command == "main-wing-station-seam-export-strategy-probe"
    assert args.out == "artifacts/main_wing_station_seam_export_strategy_probe"
    assert args.export_source_audit == "artifacts/main_wing/export_source_audit.json"
    assert args.materialize_candidates is True
    assert args.timeout_seconds == 12.5


def test_parser_supports_main_wing_station_seam_internal_cap_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-station-seam-internal-cap-probe",
            "--out",
            "artifacts/main_wing_station_seam_internal_cap_probe",
            "--export-strategy-probe",
            "artifacts/main_wing/export_strategy_probe.json",
            "--station-plane-tolerance",
            "1e-4",
        ]
    )

    assert args.command == "main-wing-station-seam-internal-cap-probe"
    assert args.out == "artifacts/main_wing_station_seam_internal_cap_probe"
    assert args.export_strategy_probe == "artifacts/main_wing/export_strategy_probe.json"
    assert args.station_plane_tolerance == 1e-4


def test_parser_supports_main_wing_station_seam_profile_resample_strategy_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-station-seam-profile-resample-strategy-probe",
            "--out",
            "artifacts/main_wing_station_seam_profile_resample_strategy_probe",
            "--export-source-audit",
            "artifacts/main_wing/export_source_audit.json",
            "--materialize-candidate",
            "--target-profile-point-count",
            "59",
            "--timeout-seconds",
            "12.5",
        ]
    )

    assert args.command == "main-wing-station-seam-profile-resample-strategy-probe"
    assert args.out == "artifacts/main_wing_station_seam_profile_resample_strategy_probe"
    assert args.export_source_audit == "artifacts/main_wing/export_source_audit.json"
    assert args.materialize_candidate is True
    assert args.target_profile_point_count == 59
    assert args.timeout_seconds == 12.5


def test_parser_supports_main_wing_su2_force_marker_audit_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-su2-force-marker-audit",
            "--out",
            "artifacts/main_wing_su2_force_marker_audit",
            "--report-root",
            "docs/reports",
            "--source-su2-probe-report",
            "docs/reports/main_wing_openvsp_reference_su2_handoff_probe/main_wing_openvsp_reference_su2_handoff_probe.v1.json",
        ]
    )

    assert args.command == "main-wing-su2-force-marker-audit"
    assert args.out == "artifacts/main_wing_su2_force_marker_audit"
    assert args.report_root == "docs/reports"
    assert args.source_su2_probe_report.endswith(
        "main_wing_openvsp_reference_su2_handoff_probe.v1.json"
    )


def test_parser_supports_main_wing_surface_force_output_audit_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-surface-force-output-audit",
            "--out",
            "artifacts/main_wing_surface_force_output_audit",
            "--report-root",
            "docs/reports",
            "--solver-report",
            "docs/reports/main_wing_openvsp_reference_solver_smoke_probe_iter80/main_wing_real_solver_smoke_probe.v1.json",
            "--panel-reference-report",
            "docs/reports/main_wing_vspaero_panel_reference_probe/main_wing_vspaero_panel_reference_probe.v1.json",
        ]
    )

    assert args.command == "main-wing-surface-force-output-audit"
    assert args.out == "artifacts/main_wing_surface_force_output_audit"
    assert args.report_root == "docs/reports"
    assert args.solver_report.endswith("main_wing_real_solver_smoke_probe.v1.json")
    assert args.panel_reference_report.endswith(
        "main_wing_vspaero_panel_reference_probe.v1.json"
    )


def test_parser_supports_main_wing_vspaero_panel_reference_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-vspaero-panel-reference-probe",
            "--out",
            "artifacts/main_wing_vspaero_panel_reference_probe",
            "--polar",
            "output/panel/black_cat_004.polar",
            "--setup",
            "output/panel/black_cat_004.vspaero",
            "--lift-diagnostic-report",
            "docs/reports/main_wing_lift_acceptance_diagnostic/main_wing_lift_acceptance_diagnostic.v1.json",
        ]
    )

    assert args.command == "main-wing-vspaero-panel-reference-probe"
    assert args.out == "artifacts/main_wing_vspaero_panel_reference_probe"
    assert args.polar == "output/panel/black_cat_004.polar"
    assert args.setup == "output/panel/black_cat_004.vspaero"
    assert args.lift_diagnostic_report.endswith(
        "main_wing_lift_acceptance_diagnostic.v1.json"
    )


def test_parser_supports_main_wing_geometry_provenance_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-geometry-provenance-probe",
            "--out",
            "artifacts/main_wing_geometry_provenance_probe",
            "--source",
            "data/blackcat_004_origin.vsp3",
        ]
    )

    assert args.command == "main-wing-geometry-provenance-probe"
    assert args.out == "artifacts/main_wing_geometry_provenance_probe"
    assert args.source == "data/blackcat_004_origin.vsp3"


def test_parser_supports_main_wing_real_su2_handoff_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-real-su2-handoff-probe",
            "--out",
            "artifacts/main_wing_real_su2_probe",
            "--source-mesh-probe-report",
            "artifacts/main_wing_real_mesh_probe/main_wing_real_mesh_handoff_probe.v1.json",
            "--max-iterations",
            "40",
            "--reference-policy",
            "openvsp_geometry_derived",
        ]
    )

    assert args.command == "main-wing-real-su2-handoff-probe"
    assert args.out == "artifacts/main_wing_real_su2_probe"
    assert args.source_mesh_probe_report == (
        "artifacts/main_wing_real_mesh_probe/main_wing_real_mesh_handoff_probe.v1.json"
    )
    assert args.max_iterations == 40
    assert args.reference_policy == "openvsp_geometry_derived"


def test_parser_supports_main_wing_real_solver_smoke_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-real-solver-smoke-probe",
            "--out",
            "artifacts/main_wing_real_solver_probe",
            "--source-su2-probe-report",
            "artifacts/main_wing_real_su2_probe/main_wing_real_su2_handoff_probe.v1.json",
            "--timeout-seconds",
            "30",
        ]
    )

    assert args.command == "main-wing-real-solver-smoke-probe"
    assert args.out == "artifacts/main_wing_real_solver_probe"
    assert args.source_su2_probe_report == (
        "artifacts/main_wing_real_su2_probe/main_wing_real_su2_handoff_probe.v1.json"
    )
    assert args.timeout_seconds == 30.0


def test_parser_supports_main_wing_reference_geometry_gate_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-reference-geometry-gate",
            "--out",
            "artifacts/main_wing_reference_geometry_gate",
            "--report-root",
            "docs/reports",
            "--source-su2-probe-report",
            "docs/reports/main_wing_openvsp_reference_su2_handoff_probe/main_wing_openvsp_reference_su2_handoff_probe.v1.json",
        ]
    )

    assert args.command == "main-wing-reference-geometry-gate"
    assert args.out == "artifacts/main_wing_reference_geometry_gate"
    assert args.report_root == "docs/reports"
    assert args.source_su2_probe_report.endswith(
        "main_wing_openvsp_reference_su2_handoff_probe.v1.json"
    )


def test_parser_supports_tail_wing_mesh_handoff_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        ["tail-wing-mesh-handoff-smoke", "--out", "artifacts/tail_wing_smoke"]
    )

    assert args.command == "tail-wing-mesh-handoff-smoke"
    assert args.out == "artifacts/tail_wing_smoke"


def test_parser_supports_tail_wing_su2_handoff_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        ["tail-wing-su2-handoff-smoke", "--out", "artifacts/tail_wing_su2_smoke"]
    )

    assert args.command == "tail-wing-su2-handoff-smoke"
    assert args.out == "artifacts/tail_wing_su2_smoke"


def test_parser_supports_tail_wing_esp_rebuilt_geometry_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "tail-wing-esp-rebuilt-geometry-smoke",
            "--out",
            "artifacts/tail_wing_esp_geometry_smoke",
        ]
    )

    assert args.command == "tail-wing-esp-rebuilt-geometry-smoke"
    assert args.out == "artifacts/tail_wing_esp_geometry_smoke"


def test_parser_supports_tail_wing_real_mesh_handoff_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "tail-wing-real-mesh-handoff-probe",
            "--out",
            "artifacts/tail_wing_real_mesh_probe",
        ]
    )

    assert args.command == "tail-wing-real-mesh-handoff-probe"
    assert args.out == "artifacts/tail_wing_real_mesh_probe"


def test_parser_supports_tail_wing_surface_mesh_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "tail-wing-surface-mesh-probe",
            "--out",
            "artifacts/tail_wing_surface_mesh_probe",
        ]
    )

    assert args.command == "tail-wing-surface-mesh-probe"
    assert args.out == "artifacts/tail_wing_surface_mesh_probe"


def test_parser_supports_tail_wing_solidification_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "tail-wing-solidification-probe",
            "--out",
            "artifacts/tail_wing_solidification_probe",
        ]
    )

    assert args.command == "tail-wing-solidification-probe"
    assert args.out == "artifacts/tail_wing_solidification_probe"


def test_parser_supports_tail_wing_explicit_volume_route_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "tail-wing-explicit-volume-route-probe",
            "--out",
            "artifacts/tail_wing_explicit_volume_route_probe",
        ]
    )

    assert args.command == "tail-wing-explicit-volume-route-probe"
    assert args.out == "artifacts/tail_wing_explicit_volume_route_probe"


def test_parser_supports_main_wing_su2_handoff_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        ["main-wing-su2-handoff-smoke", "--out", "artifacts/main_wing_su2_smoke"]
    )

    assert args.command == "main-wing-su2-handoff-smoke"
    assert args.out == "artifacts/main_wing_su2_smoke"


def test_parser_supports_fairing_solid_su2_handoff_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "fairing-solid-su2-handoff-smoke",
            "--out",
            "artifacts/fairing_su2_smoke",
        ]
    )

    assert args.command == "fairing-solid-su2-handoff-smoke"
    assert args.out == "artifacts/fairing_su2_smoke"


def test_parser_supports_fairing_solid_real_su2_handoff_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "fairing-solid-real-su2-handoff-probe",
            "--out",
            "artifacts/fairing_real_su2_probe",
            "--source",
            "fairing.vsp3",
            "--timeout-seconds",
            "30",
            "--source-mesh-probe-report",
            "artifacts/fairing_real_mesh_probe.v1.json",
        ]
    )

    assert args.command == "fairing-solid-real-su2-handoff-probe"
    assert args.out == "artifacts/fairing_real_su2_probe"
    assert args.source == "fairing.vsp3"
    assert args.timeout_seconds == 30.0
    assert args.source_mesh_probe_report == "artifacts/fairing_real_mesh_probe.v1.json"


def test_parser_supports_fairing_solid_reference_policy_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "fairing-solid-reference-policy-probe",
            "--out",
            "artifacts/fairing_reference_policy",
            "--external-project-root",
            "/tmp/fairing",
            "--external-su2-cfg",
            "/tmp/fairing/su2_case.cfg",
            "--hpa-su2-probe-report",
            "artifacts/hpa_probe.json",
        ]
    )

    assert args.command == "fairing-solid-reference-policy-probe"
    assert args.out == "artifacts/fairing_reference_policy"
    assert args.external_project_root == "/tmp/fairing"
    assert args.external_su2_cfg == "/tmp/fairing/su2_case.cfg"
    assert args.hpa_su2_probe_report == "artifacts/hpa_probe.json"


def test_parser_supports_fairing_solid_reference_override_su2_handoff_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "fairing-solid-reference-override-su2-handoff-probe",
            "--out",
            "artifacts/fairing_reference_override_su2",
            "--reference-policy-probe",
            "artifacts/fairing_reference_policy.v1.json",
            "--source-su2-probe-report",
            "artifacts/fairing_real_su2_probe.v1.json",
        ]
    )

    assert args.command == "fairing-solid-reference-override-su2-handoff-probe"
    assert args.out == "artifacts/fairing_reference_override_su2"
    assert args.reference_policy_probe == "artifacts/fairing_reference_policy.v1.json"
    assert args.source_su2_probe_report == "artifacts/fairing_real_su2_probe.v1.json"


def test_python_m_cli_runs_validate_geometry(tmp_path: Path):
    geometry = tmp_path / "wing.step"
    geometry.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    package_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hpa_meshing.cli",
            "validate-geometry",
            "--component",
            "main_wing",
            "--geometry",
            str(geometry),
            "--out",
            str(out_dir),
        ],
        cwd=package_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["geometry_family"] == "thin_sheet_lifting_surface"
    assert (out_dir / "report.json").exists()


def test_python_m_cli_reports_experimental_provider_status(tmp_path: Path):
    geometry = tmp_path / "assembly.vsp3"
    geometry.write_text("<vsp3/>", encoding="utf-8")
    out_dir = tmp_path / "out"
    runtime_free_path = tmp_path / "bin"
    runtime_free_path.mkdir()
    package_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    env["PATH"] = str(runtime_free_path)
    env.pop("ESP_ROOT", None)
    env.pop("CASROOT", None)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hpa_meshing.cli",
            "validate-geometry",
            "--component",
            "aircraft_assembly",
            "--geometry",
            str(geometry),
            "--geometry-provider",
            "esp_rebuilt",
            "--out",
            str(out_dir),
        ],
        cwd=package_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["failure_code"] == "geometry_provider_not_materialized"
    assert payload["geometry_provider"] == "esp_rebuilt"
    assert payload["provider"]["provider_stage"] == "experimental"
    assert payload["provider"]["status"] == "failed"
    assert payload["provider"]["provenance"]["failure_code"] == "esp_runtime_missing"
    assert payload["provider"]["provenance"]["runtime"]["available"] is False


def test_python_m_cli_writes_route_readiness_report(tmp_path: Path):
    out_dir = tmp_path / "readiness"
    package_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hpa_meshing.cli",
            "route-readiness",
            "--out",
            str(out_dir),
        ],
        cwd=package_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["primary_decision"] == "switch_to_component_family_route_architecture"
    assert (out_dir / "component_family_route_readiness.v1.json").exists()
    assert (out_dir / "component_family_route_readiness.v1.md").exists()


def test_python_m_cli_writes_component_family_smoke_matrix_report(tmp_path: Path):
    out_dir = tmp_path / "smoke"
    package_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hpa_meshing.cli",
            "component-family-smoke-matrix",
            "--out",
            str(out_dir),
        ],
        cwd=package_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["execution_mode"] == "pre_mesh_dispatch_smoke"
    assert payload["no_gmsh_execution"] is True
    assert (out_dir / "component_family_route_smoke_matrix.v1.json").exists()
    assert (out_dir / "component_family_route_smoke_matrix.v1.md").exists()


def test_python_m_cli_writes_main_wing_solver_budget_comparison_report(
    tmp_path: Path,
):
    out_dir = tmp_path / "solver_budget_comparison"
    package_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hpa_meshing.cli",
            "main-wing-solver-budget-comparison",
            "--out",
            str(out_dir),
        ],
        cwd=package_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "main_wing_solver_budget_comparison.v1"
    assert payload["hpa_standard_flow_status"] == "hpa_standard_6p5_observed"
    assert (out_dir / "main_wing_solver_budget_comparison.v1.json").exists()
    assert (out_dir / "main_wing_solver_budget_comparison.v1.md").exists()
