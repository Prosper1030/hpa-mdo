from __future__ import annotations

import argparse
from pathlib import Path
import json
import yaml

from .schema import MeshJobConfig, BatchManifest
from .component_family_smoke_matrix import (
    build_component_family_route_smoke_matrix,
    write_component_family_route_smoke_matrix_report,
)
from .fairing_solid_mesh_handoff_smoke import (
    build_fairing_solid_mesh_handoff_smoke_report,
    write_fairing_solid_mesh_handoff_smoke_report,
)
from .fairing_solid_real_geometry_smoke import (
    build_fairing_solid_real_geometry_smoke_report,
    write_fairing_solid_real_geometry_smoke_report,
)
from .fairing_solid_real_mesh_handoff_probe import (
    build_fairing_solid_real_mesh_handoff_probe_report,
    write_fairing_solid_real_mesh_handoff_probe_report,
)
from .fairing_solid_real_su2_handoff_probe import (
    build_fairing_solid_real_su2_handoff_probe_report,
    write_fairing_solid_real_su2_handoff_probe_report,
)
from .fairing_solid_reference_policy_probe import (
    build_fairing_solid_reference_policy_probe_report,
    write_fairing_solid_reference_policy_probe_report,
)
from .fairing_solid_reference_override_su2_handoff_probe import (
    build_fairing_solid_reference_override_su2_handoff_probe_report,
    write_fairing_solid_reference_override_su2_handoff_probe_report,
)
from .fairing_solid_su2_handoff_smoke import (
    build_fairing_solid_su2_handoff_smoke_report,
    write_fairing_solid_su2_handoff_smoke_report,
)
from .main_wing_mesh_handoff_smoke import (
    build_main_wing_mesh_handoff_smoke_report,
    write_main_wing_mesh_handoff_smoke_report,
)
from .main_wing_real_mesh_handoff_probe import (
    build_main_wing_real_mesh_handoff_probe_report,
    write_main_wing_real_mesh_handoff_probe_report,
)
from .main_wing_real_su2_handoff_probe import (
    build_main_wing_real_su2_handoff_probe_report,
    write_main_wing_real_su2_handoff_probe_report,
)
from .main_wing_real_solver_smoke_probe import (
    build_main_wing_real_solver_smoke_probe_report,
    write_main_wing_real_solver_smoke_probe_report,
)
from .main_wing_reference_geometry_gate import (
    build_main_wing_reference_geometry_gate_report,
    write_main_wing_reference_geometry_gate_report,
)
from .main_wing_su2_handoff_smoke import (
    build_main_wing_su2_handoff_smoke_report,
    write_main_wing_su2_handoff_smoke_report,
)
from .main_wing_route_readiness import (
    build_main_wing_route_readiness_report,
    write_main_wing_route_readiness_report,
)
from .main_wing_solver_budget_comparison import (
    build_main_wing_solver_budget_comparison_report,
    write_main_wing_solver_budget_comparison_report,
)
from .main_wing_lift_acceptance_diagnostic import (
    build_main_wing_lift_acceptance_diagnostic_report,
    write_main_wing_lift_acceptance_diagnostic_report,
)
from .main_wing_panel_su2_lift_gap_debug import (
    build_main_wing_panel_su2_lift_gap_debug_report,
    write_main_wing_panel_su2_lift_gap_debug_report,
)
from .main_wing_panel_wake_semantics_audit import (
    build_main_wing_panel_wake_semantics_audit_report,
    write_main_wing_panel_wake_semantics_audit_report,
)
from .main_wing_mesh_quality_hotspot_audit import (
    build_main_wing_mesh_quality_hotspot_audit_report,
    write_main_wing_mesh_quality_hotspot_audit_report,
)
from .main_wing_su2_mesh_normal_audit import (
    build_main_wing_su2_mesh_normal_audit_report,
    write_main_wing_su2_mesh_normal_audit_report,
)
from .main_wing_su2_surface_topology_audit import (
    build_main_wing_su2_surface_topology_audit_report,
    write_main_wing_su2_surface_topology_audit_report,
)
from .main_wing_su2_topology_defect_localization import (
    build_main_wing_su2_topology_defect_localization_report,
    write_main_wing_su2_topology_defect_localization_report,
)
from .main_wing_openvsp_defect_station_audit import (
    build_main_wing_openvsp_defect_station_audit_report,
    write_main_wing_openvsp_defect_station_audit_report,
)
from .main_wing_gmsh_defect_entity_trace import (
    build_main_wing_gmsh_defect_entity_trace_report,
    write_main_wing_gmsh_defect_entity_trace_report,
)
from .main_wing_gmsh_curve_station_rebuild_audit import (
    build_main_wing_gmsh_curve_station_rebuild_audit_report,
    write_main_wing_gmsh_curve_station_rebuild_audit_report,
)
from .main_wing_openvsp_section_station_topology_fixture import (
    build_main_wing_openvsp_section_station_topology_fixture_report,
    write_main_wing_openvsp_section_station_topology_fixture_report,
)
from .main_wing_station_seam_repair_decision import (
    build_main_wing_station_seam_repair_decision_report,
    write_main_wing_station_seam_repair_decision_report,
)
from .main_wing_station_seam_brep_hotspot_probe import (
    build_main_wing_station_seam_brep_hotspot_probe_report,
    write_main_wing_station_seam_brep_hotspot_probe_report,
)
from .main_wing_station_seam_same_parameter_feasibility import (
    build_main_wing_station_seam_same_parameter_feasibility_report,
    write_main_wing_station_seam_same_parameter_feasibility_report,
)
from .main_wing_station_seam_shape_fix_feasibility import (
    build_main_wing_station_seam_shape_fix_feasibility_report,
    write_main_wing_station_seam_shape_fix_feasibility_report,
)
from .main_wing_station_seam_export_source_audit import (
    build_main_wing_station_seam_export_source_audit_report,
    write_main_wing_station_seam_export_source_audit_report,
)
from .main_wing_station_seam_export_strategy_probe import (
    build_main_wing_station_seam_export_strategy_probe_report,
    write_main_wing_station_seam_export_strategy_probe_report,
)
from .main_wing_station_seam_internal_cap_probe import (
    build_main_wing_station_seam_internal_cap_probe_report,
    write_main_wing_station_seam_internal_cap_probe_report,
)
from .main_wing_station_seam_profile_resample_strategy_probe import (
    build_main_wing_station_seam_profile_resample_strategy_probe_report,
    write_main_wing_station_seam_profile_resample_strategy_probe_report,
)
from .main_wing_station_seam_profile_resample_brep_validation_probe import (
    build_main_wing_station_seam_profile_resample_brep_validation_probe_report,
    write_main_wing_station_seam_profile_resample_brep_validation_probe_report,
)
from .main_wing_station_seam_profile_resample_repair_feasibility_probe import (
    build_main_wing_station_seam_profile_resample_repair_feasibility_probe_report,
    write_main_wing_station_seam_profile_resample_repair_feasibility_probe_report,
)
from .main_wing_station_seam_profile_parametrization_audit import (
    build_main_wing_station_seam_profile_parametrization_audit_report,
    write_main_wing_station_seam_profile_parametrization_audit_report,
)
from .main_wing_su2_force_marker_audit import (
    build_main_wing_su2_force_marker_audit_report,
    write_main_wing_su2_force_marker_audit_report,
)
from .main_wing_surface_force_output_audit import (
    build_main_wing_surface_force_output_audit_report,
    write_main_wing_surface_force_output_audit_report,
)
from .main_wing_vspaero_panel_reference_probe import (
    build_main_wing_vspaero_panel_reference_probe_report,
    write_main_wing_vspaero_panel_reference_probe_report,
)
from .main_wing_geometry_provenance_probe import (
    build_main_wing_geometry_provenance_probe_report,
    write_main_wing_geometry_provenance_probe_report,
)
from .main_wing_esp_rebuilt_geometry_smoke import (
    build_main_wing_esp_rebuilt_geometry_smoke_report,
    write_main_wing_esp_rebuilt_geometry_smoke_report,
)
from .tail_wing_mesh_handoff_smoke import (
    build_tail_wing_mesh_handoff_smoke_report,
    write_tail_wing_mesh_handoff_smoke_report,
)
from .tail_wing_su2_handoff_smoke import (
    build_tail_wing_su2_handoff_smoke_report,
    write_tail_wing_su2_handoff_smoke_report,
)
from .tail_wing_esp_rebuilt_geometry_smoke import (
    build_tail_wing_esp_rebuilt_geometry_smoke_report,
    write_tail_wing_esp_rebuilt_geometry_smoke_report,
)
from .tail_wing_real_mesh_handoff_probe import (
    build_tail_wing_real_mesh_handoff_probe_report,
    write_tail_wing_real_mesh_handoff_probe_report,
)
from .tail_wing_surface_mesh_probe import (
    build_tail_wing_surface_mesh_probe_report,
    write_tail_wing_surface_mesh_probe_report,
)
from .tail_wing_solidification_probe import (
    build_tail_wing_solidification_probe_report,
    write_tail_wing_solidification_probe_report,
)
from .tail_wing_explicit_volume_route_probe import (
    build_tail_wing_explicit_volume_route_probe_report,
    write_tail_wing_explicit_volume_route_probe_report,
)
from .frozen_baseline import evaluate_shell_v3_baseline_regression, run_shell_v3_baseline_cfd
from .pipeline import run_job, validate_geometry_only
from .mesh_study import run_mesh_study
from .route_readiness import (
    build_component_family_route_readiness,
    write_component_family_route_readiness_report,
)
from .shell_v3_refinement_study import run_shell_v3_refinement_study
from .shell_v4_half_wing_bl_mesh_macsafe import (
    _default_real_main_wing_source_path,
    _run_shell_v4_bl_candidate_parameter_sweep_focused,
    run_shell_v4_half_wing_bl_mesh_macsafe,
)


def _load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def cmd_run(args: argparse.Namespace) -> int:
    raw = _load_yaml(Path(args.config))
    raw["component"] = args.component or raw.get("component")
    raw["geometry"] = args.geometry or raw.get("geometry")
    raw["geometry_provider"] = args.geometry_provider or raw.get("geometry_provider")
    raw["out_dir"] = args.out or raw.get("out_dir")
    config = MeshJobConfig.model_validate(raw)
    result = run_job(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 2


def cmd_validate_geometry(args: argparse.Namespace) -> int:
    raw = _load_yaml(Path(args.config)) if args.config else {}
    raw["component"] = args.component or raw.get("component")
    raw["geometry"] = args.geometry or raw.get("geometry")
    raw["geometry_provider"] = args.geometry_provider or raw.get("geometry_provider")
    raw["out_dir"] = args.out or raw.get("out_dir", "out/validate")
    config = MeshJobConfig.model_validate(raw)
    result = validate_geometry_only(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 2


def cmd_batch(args: argparse.Namespace) -> int:
    raw = _load_yaml(Path(args.manifest))
    manifest = BatchManifest.model_validate(raw)
    results = [run_job(job) for job in manifest.jobs]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(r.get("status") == "success" for r in results) else 2


def cmd_mesh_study(args: argparse.Namespace) -> int:
    raw = _load_yaml(Path(args.config))
    raw["component"] = args.component or raw.get("component")
    raw["geometry"] = args.geometry or raw.get("geometry")
    raw["geometry_provider"] = args.geometry_provider or raw.get("geometry_provider")
    raw["out_dir"] = args.out or raw.get("out_dir")
    config = MeshJobConfig.model_validate(raw)
    result = run_mesh_study(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("verdict", {}).get("verdict") != "insufficient" else 2


def cmd_baseline_freeze(args: argparse.Namespace) -> int:
    result = evaluate_shell_v3_baseline_regression(
        Path(args.baseline_manifest),
        mesh_handoff_path=None if args.mesh_handoff is None else Path(args.mesh_handoff),
    )
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "pass" else 2


def cmd_baseline_cfd(args: argparse.Namespace) -> int:
    result = run_shell_v3_baseline_cfd(
        Path(args.baseline_manifest),
        out_dir=Path(args.out),
        mesh_handoff_path=None if args.mesh_handoff is None else Path(args.mesh_handoff),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 2


def cmd_shell_v3_refinement_study(args: argparse.Namespace) -> int:
    result = run_shell_v3_refinement_study(
        Path(args.baseline_manifest),
        out_dir=Path(args.out),
        mesh_handoff_path=None if args.mesh_handoff is None else Path(args.mesh_handoff),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 2


def cmd_shell_v4_half_wing_bl_mesh_macsafe(args: argparse.Namespace) -> int:
    if args.run_bl_candidate_sweep_focused:
        result = _run_shell_v4_bl_candidate_parameter_sweep_focused(
            out_dir=Path(args.out),
            source_path=_default_real_main_wing_source_path(),
            component="main_wing",
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") == "written" else 2

    result = run_shell_v4_half_wing_bl_mesh_macsafe(
        out_dir=Path(args.out),
        study_level=args.study_level,
        run_su2=not args.skip_su2,
        allow_swap_risk=args.allow_swap_risk,
        topology_compiler_gate="plan_only" if args.topology_compiler_plan_only else "off",
        bl_candidate_apply_gate=(
            "stage_with_termination_guard_8_to_7_focused"
            if args.apply_bl_stage_with_termination_guard_8_to_7_focused
            else "stageback_plus_truncation_focused"
            if args.apply_bl_stageback_plus_truncation_focused
            else "off"
        ),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 2


def cmd_route_readiness(args: argparse.Namespace) -> int:
    write_component_family_route_readiness_report(Path(args.out))
    report = build_component_family_route_readiness()
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


def cmd_component_family_smoke_matrix(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    write_component_family_route_smoke_matrix_report(out_dir)
    report = build_component_family_route_smoke_matrix(out_dir)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.report_status == "completed" else 2


def cmd_fairing_solid_mesh_handoff_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report = build_fairing_solid_mesh_handoff_smoke_report(out_dir)
    write_fairing_solid_mesh_handoff_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.smoke_status == "mesh_handoff_pass" else 2


def cmd_fairing_solid_real_geometry_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_fairing_solid_real_geometry_smoke_report(
        out_dir,
        source_path=source_path,
    )
    write_fairing_solid_real_geometry_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.geometry_smoke_status == "geometry_smoke_pass" else 2


def cmd_fairing_solid_real_mesh_handoff_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_fairing_solid_real_mesh_handoff_probe_report(
        out_dir,
        source_path=source_path,
        timeout_seconds=float(args.timeout_seconds),
    )
    write_fairing_solid_real_mesh_handoff_probe_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.probe_status in {
        "mesh_handoff_pass",
        "mesh_handoff_blocked",
        "mesh_handoff_timeout",
    } else 2


def cmd_fairing_solid_su2_handoff_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report = build_fairing_solid_su2_handoff_smoke_report(out_dir)
    write_fairing_solid_su2_handoff_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.materialization_status == "su2_handoff_written" else 2


def cmd_fairing_solid_real_su2_handoff_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    source_mesh_probe_report_path = (
        None
        if args.source_mesh_probe_report is None
        else Path(args.source_mesh_probe_report)
    )
    report = build_fairing_solid_real_su2_handoff_probe_report(
        out_dir,
        source_path=source_path,
        timeout_seconds=float(args.timeout_seconds),
        source_mesh_probe_report_path=source_mesh_probe_report_path,
    )
    write_fairing_solid_real_su2_handoff_probe_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.materialization_status == "su2_handoff_written" else 2


def cmd_fairing_solid_reference_policy_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    external_project_root = (
        None if args.external_project_root is None else Path(args.external_project_root)
    )
    external_su2_cfg_path = (
        None if args.external_su2_cfg is None else Path(args.external_su2_cfg)
    )
    hpa_su2_probe_report_path = (
        None if args.hpa_su2_probe_report is None else Path(args.hpa_su2_probe_report)
    )
    report = build_fairing_solid_reference_policy_probe_report(
        out_dir,
        external_project_root=external_project_root,
        external_su2_cfg_path=external_su2_cfg_path,
        hpa_su2_probe_report_path=hpa_su2_probe_report_path,
    )
    write_fairing_solid_reference_policy_probe_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.reference_policy_status in {
        "candidate_available",
        "reference_mismatch_observed",
    } else 2


def cmd_fairing_solid_reference_override_su2_handoff_probe(
    args: argparse.Namespace,
) -> int:
    out_dir = Path(args.out)
    reference_policy_probe_path = (
        None
        if args.reference_policy_probe is None
        else Path(args.reference_policy_probe)
    )
    source_su2_probe_report_path = (
        None
        if args.source_su2_probe_report is None
        else Path(args.source_su2_probe_report)
    )
    report = build_fairing_solid_reference_override_su2_handoff_probe_report(
        out_dir,
        reference_policy_probe_path=reference_policy_probe_path,
        source_su2_probe_report_path=source_su2_probe_report_path,
    )
    write_fairing_solid_reference_override_su2_handoff_probe_report(
        out_dir,
        report=report,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.materialization_status == "su2_handoff_written" else 2


def cmd_main_wing_mesh_handoff_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report = build_main_wing_mesh_handoff_smoke_report(out_dir)
    write_main_wing_mesh_handoff_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.smoke_status == "mesh_handoff_pass" else 2


def cmd_main_wing_esp_rebuilt_geometry_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_main_wing_esp_rebuilt_geometry_smoke_report(
        out_dir,
        source_path=source_path,
    )
    write_main_wing_esp_rebuilt_geometry_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.geometry_smoke_status == "geometry_smoke_pass" else 2


def cmd_main_wing_real_mesh_handoff_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_main_wing_real_mesh_handoff_probe_report(
        out_dir,
        source_path=source_path,
        timeout_seconds=float(args.timeout_seconds),
        global_min_size=float(args.global_min_size),
        global_max_size=float(args.global_max_size),
    )
    write_main_wing_real_mesh_handoff_probe_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.probe_status in {"mesh_handoff_pass", "mesh_handoff_blocked", "mesh_handoff_timeout"} else 2


def cmd_main_wing_route_readiness(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report = build_main_wing_route_readiness_report()
    write_main_wing_route_readiness_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


def cmd_main_wing_solver_budget_comparison(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report_root = None if args.report_root is None else Path(args.report_root)
    report = build_main_wing_solver_budget_comparison_report(report_root=report_root)
    write_main_wing_solver_budget_comparison_report(
        out_dir,
        report=report,
        report_root=report_root,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


def cmd_main_wing_lift_acceptance_diagnostic(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report_root = None if args.report_root is None else Path(args.report_root)
    report = build_main_wing_lift_acceptance_diagnostic_report(report_root=report_root)
    write_main_wing_lift_acceptance_diagnostic_report(
        out_dir,
        report=report,
        report_root=report_root,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


def cmd_main_wing_panel_su2_lift_gap_debug(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report_root = None if args.report_root is None else Path(args.report_root)
    report = build_main_wing_panel_su2_lift_gap_debug_report(report_root=report_root)
    write_main_wing_panel_su2_lift_gap_debug_report(
        out_dir,
        report=report,
        report_root=report_root,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.debug_status != "insufficient_evidence" else 2


def cmd_main_wing_su2_mesh_normal_audit(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    mesh_path = None if args.mesh is None else Path(args.mesh)
    report = build_main_wing_su2_mesh_normal_audit_report(mesh_path=mesh_path)
    write_main_wing_su2_mesh_normal_audit_report(
        out_dir,
        report=report,
        mesh_path=mesh_path,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.normal_audit_status == "pass" else 2


def cmd_main_wing_panel_wake_semantics_audit(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report_root = None if args.report_root is None else Path(args.report_root)
    runtime_cfg_path = None if args.runtime_cfg is None else Path(args.runtime_cfg)
    report = build_main_wing_panel_wake_semantics_audit_report(
        report_root=report_root,
        runtime_cfg_path=runtime_cfg_path,
    )
    write_main_wing_panel_wake_semantics_audit_report(
        out_dir,
        report=report,
        report_root=report_root,
        runtime_cfg_path=runtime_cfg_path,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.audit_status != "insufficient_evidence" else 2


def cmd_main_wing_su2_surface_topology_audit(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    mesh_path = None if args.mesh is None else Path(args.mesh)
    report_root = None if args.report_root is None else Path(args.report_root)
    report = build_main_wing_su2_surface_topology_audit_report(
        mesh_path=mesh_path,
        report_root=report_root,
        reference_area_m2=args.reference_area,
    )
    write_main_wing_su2_surface_topology_audit_report(
        out_dir,
        report=report,
        mesh_path=mesh_path,
        report_root=report_root,
        reference_area_m2=args.reference_area,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.audit_status != "blocked" else 2


def cmd_main_wing_mesh_quality_hotspot_audit(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    mesh_handoff_report_path = (
        None
        if args.mesh_handoff_report is None
        else Path(args.mesh_handoff_report)
    )
    mesh_metadata_path = (
        None if args.mesh_metadata is None else Path(args.mesh_metadata)
    )
    hotspot_patch_report_path = (
        None
        if args.hotspot_patch_report is None
        else Path(args.hotspot_patch_report)
    )
    surface_patch_diagnostics_path = (
        None
        if args.surface_patch_diagnostics is None
        else Path(args.surface_patch_diagnostics)
    )
    gmsh_defect_entity_trace_path = (
        None
        if args.gmsh_defect_entity_trace is None
        else Path(args.gmsh_defect_entity_trace)
    )
    report = build_main_wing_mesh_quality_hotspot_audit_report(
        mesh_handoff_report_path=mesh_handoff_report_path,
        mesh_metadata_path=mesh_metadata_path,
        hotspot_patch_report_path=hotspot_patch_report_path,
        surface_patch_diagnostics_path=surface_patch_diagnostics_path,
        gmsh_defect_entity_trace_path=gmsh_defect_entity_trace_path,
    )
    write_main_wing_mesh_quality_hotspot_audit_report(
        out_dir,
        report=report,
        mesh_handoff_report_path=mesh_handoff_report_path,
        mesh_metadata_path=mesh_metadata_path,
        hotspot_patch_report_path=hotspot_patch_report_path,
        surface_patch_diagnostics_path=surface_patch_diagnostics_path,
        gmsh_defect_entity_trace_path=gmsh_defect_entity_trace_path,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.hotspot_status != "blocked" else 2


def cmd_main_wing_su2_topology_defect_localization(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    mesh_path = None if args.mesh is None else Path(args.mesh)
    report = build_main_wing_su2_topology_defect_localization_report(
        mesh_path=mesh_path,
    )
    write_main_wing_su2_topology_defect_localization_report(
        out_dir,
        report=report,
        mesh_path=mesh_path,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.localization_status != "blocked" else 2


def cmd_main_wing_openvsp_defect_station_audit(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    defect_localization_path = (
        None if args.defect_localization is None else Path(args.defect_localization)
    )
    topology_lineage_path = (
        None if args.topology_lineage is None else Path(args.topology_lineage)
    )
    source_vsp3_path = None if args.source_vsp3 is None else Path(args.source_vsp3)
    report = build_main_wing_openvsp_defect_station_audit_report(
        defect_localization_path=defect_localization_path,
        topology_lineage_path=topology_lineage_path,
        source_vsp3_path=source_vsp3_path,
    )
    write_main_wing_openvsp_defect_station_audit_report(
        out_dir,
        report=report,
        defect_localization_path=defect_localization_path,
        topology_lineage_path=topology_lineage_path,
        source_vsp3_path=source_vsp3_path,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.station_alignment_status != "blocked" else 2


def cmd_main_wing_gmsh_defect_entity_trace(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    mesh_path = None if args.mesh is None else Path(args.mesh)
    defect_localization_path = (
        None if args.defect_localization is None else Path(args.defect_localization)
    )
    openvsp_station_audit_path = (
        None if args.openvsp_station_audit is None else Path(args.openvsp_station_audit)
    )
    surface_patch_diagnostics_path = (
        None
        if args.surface_patch_diagnostics is None
        else Path(args.surface_patch_diagnostics)
    )
    report = build_main_wing_gmsh_defect_entity_trace_report(
        mesh_path=mesh_path,
        defect_localization_path=defect_localization_path,
        openvsp_station_audit_path=openvsp_station_audit_path,
        surface_patch_diagnostics_path=surface_patch_diagnostics_path,
    )
    write_main_wing_gmsh_defect_entity_trace_report(
        out_dir,
        report=report,
        mesh_path=mesh_path,
        defect_localization_path=defect_localization_path,
        openvsp_station_audit_path=openvsp_station_audit_path,
        surface_patch_diagnostics_path=surface_patch_diagnostics_path,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.trace_status != "blocked" else 2


def cmd_main_wing_gmsh_curve_station_rebuild_audit(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    gmsh_defect_entity_trace_path = (
        None
        if args.gmsh_defect_entity_trace is None
        else Path(args.gmsh_defect_entity_trace)
    )
    source_vsp3_path = None if args.source_vsp3 is None else Path(args.source_vsp3)
    report = build_main_wing_gmsh_curve_station_rebuild_audit_report(
        gmsh_defect_entity_trace_path=gmsh_defect_entity_trace_path,
        source_vsp3_path=source_vsp3_path,
    )
    write_main_wing_gmsh_curve_station_rebuild_audit_report(
        out_dir,
        report=report,
        gmsh_defect_entity_trace_path=gmsh_defect_entity_trace_path,
        source_vsp3_path=source_vsp3_path,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.curve_station_rebuild_status != "blocked" else 2


def cmd_main_wing_openvsp_section_station_topology_fixture(
    args: argparse.Namespace,
) -> int:
    out_dir = Path(args.out)
    gmsh_defect_entity_trace_path = (
        None
        if args.gmsh_defect_entity_trace is None
        else Path(args.gmsh_defect_entity_trace)
    )
    gmsh_curve_station_rebuild_audit_path = (
        None
        if args.gmsh_curve_station_rebuild_audit is None
        else Path(args.gmsh_curve_station_rebuild_audit)
    )
    report = build_main_wing_openvsp_section_station_topology_fixture_report(
        gmsh_defect_entity_trace_path=gmsh_defect_entity_trace_path,
        gmsh_curve_station_rebuild_audit_path=gmsh_curve_station_rebuild_audit_path,
    )
    write_main_wing_openvsp_section_station_topology_fixture_report(
        out_dir,
        report=report,
        gmsh_defect_entity_trace_path=gmsh_defect_entity_trace_path,
        gmsh_curve_station_rebuild_audit_path=gmsh_curve_station_rebuild_audit_path,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.topology_fixture_status != "blocked" else 2


def cmd_main_wing_station_seam_repair_decision(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    topology_fixture_path = (
        None if args.topology_fixture is None else Path(args.topology_fixture)
    )
    solver_report_path = None if args.solver_report is None else Path(args.solver_report)
    report = build_main_wing_station_seam_repair_decision_report(
        topology_fixture_path=topology_fixture_path,
        solver_report_path=solver_report_path,
    )
    write_main_wing_station_seam_repair_decision_report(
        out_dir,
        report=report,
        topology_fixture_path=topology_fixture_path,
        solver_report_path=solver_report_path,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.repair_decision_status != "blocked" else 2


def cmd_main_wing_station_seam_brep_hotspot_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    topology_fixture_path = (
        None if args.topology_fixture is None else Path(args.topology_fixture)
    )
    real_mesh_probe_report_path = (
        None
        if args.real_mesh_probe_report is None
        else Path(args.real_mesh_probe_report)
    )
    normalized_step_path = (
        None if args.normalized_step is None else Path(args.normalized_step)
    )
    surface_patch_diagnostics_path = (
        None
        if args.surface_patch_diagnostics is None
        else Path(args.surface_patch_diagnostics)
    )
    report = build_main_wing_station_seam_brep_hotspot_probe_report(
        topology_fixture_path=topology_fixture_path,
        real_mesh_probe_report_path=real_mesh_probe_report_path,
        normalized_step_path=normalized_step_path,
        surface_patch_diagnostics_path=surface_patch_diagnostics_path,
        requested_curve_tags=args.curve_tags,
        requested_surface_tags=args.surface_tags,
    )
    write_main_wing_station_seam_brep_hotspot_probe_report(
        out_dir,
        report=report,
        topology_fixture_path=topology_fixture_path,
        real_mesh_probe_report_path=real_mesh_probe_report_path,
        normalized_step_path=normalized_step_path,
        surface_patch_diagnostics_path=surface_patch_diagnostics_path,
        requested_curve_tags=args.curve_tags,
        requested_surface_tags=args.surface_tags,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.probe_status not in {"blocked", "unavailable"} else 2


def cmd_main_wing_station_seam_same_parameter_feasibility(
    args: argparse.Namespace,
) -> int:
    out_dir = Path(args.out)
    brep_hotspot_probe_path = (
        None if args.brep_hotspot_probe is None else Path(args.brep_hotspot_probe)
    )
    report = build_main_wing_station_seam_same_parameter_feasibility_report(
        brep_hotspot_probe_path=brep_hotspot_probe_path,
        tolerances=args.tolerances,
    )
    write_main_wing_station_seam_same_parameter_feasibility_report(
        out_dir,
        report=report,
        brep_hotspot_probe_path=brep_hotspot_probe_path,
        tolerances=args.tolerances,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.feasibility_status != "blocked" else 2


def cmd_main_wing_station_seam_profile_resample_brep_validation_probe(
    args: argparse.Namespace,
) -> int:
    out_dir = Path(args.out)
    profile_resample_probe_path = (
        None
        if args.profile_resample_probe is None
        else Path(args.profile_resample_probe)
    )
    candidate_step_path = (
        None if args.candidate_step is None else Path(args.candidate_step)
    )
    report = (
        build_main_wing_station_seam_profile_resample_brep_validation_probe_report(
            profile_resample_probe_path=profile_resample_probe_path,
            candidate_step_path=candidate_step_path,
            station_y_targets=args.station_y_targets,
            station_tolerance_m=args.station_tolerance,
            scale_to_output_units=args.scale_to_output_units,
        )
    )
    write_main_wing_station_seam_profile_resample_brep_validation_probe_report(
        out_dir,
        report=report,
        profile_resample_probe_path=profile_resample_probe_path,
        candidate_step_path=candidate_step_path,
        station_y_targets=args.station_y_targets,
        station_tolerance_m=args.station_tolerance,
        scale_to_output_units=args.scale_to_output_units,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.probe_status != "blocked" else 2


def cmd_main_wing_station_seam_profile_resample_repair_feasibility_probe(
    args: argparse.Namespace,
) -> int:
    out_dir = Path(args.out)
    brep_validation_probe_path = (
        None
        if args.brep_validation_probe is None
        else Path(args.brep_validation_probe)
    )
    report = (
        build_main_wing_station_seam_profile_resample_repair_feasibility_probe_report(
            brep_validation_probe_path=brep_validation_probe_path,
            tolerances=args.tolerances,
            operations=args.operations,
        )
    )
    write_main_wing_station_seam_profile_resample_repair_feasibility_probe_report(
        out_dir,
        report=report,
        brep_validation_probe_path=brep_validation_probe_path,
        tolerances=args.tolerances,
        operations=args.operations,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.feasibility_status != "blocked" else 2


def cmd_main_wing_station_seam_profile_parametrization_audit(
    args: argparse.Namespace,
) -> int:
    out_dir = Path(args.out)
    profile_resample_probe_path = (
        None
        if args.profile_resample_probe is None
        else Path(args.profile_resample_probe)
    )
    brep_validation_probe_path = (
        None
        if args.brep_validation_probe is None
        else Path(args.brep_validation_probe)
    )
    report = build_main_wing_station_seam_profile_parametrization_audit_report(
        profile_resample_probe_path=profile_resample_probe_path,
        brep_validation_probe_path=brep_validation_probe_path,
        station_tolerance_m=args.station_tolerance,
        match_tolerance=args.match_tolerance,
    )
    write_main_wing_station_seam_profile_parametrization_audit_report(
        out_dir,
        report=report,
        profile_resample_probe_path=profile_resample_probe_path,
        brep_validation_probe_path=brep_validation_probe_path,
        station_tolerance_m=args.station_tolerance,
        match_tolerance=args.match_tolerance,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.audit_status != "blocked" else 2


def cmd_main_wing_station_seam_shape_fix_feasibility(
    args: argparse.Namespace,
) -> int:
    out_dir = Path(args.out)
    same_parameter_feasibility_path = (
        None
        if args.same_parameter_feasibility is None
        else Path(args.same_parameter_feasibility)
    )
    report = build_main_wing_station_seam_shape_fix_feasibility_report(
        same_parameter_feasibility_path=same_parameter_feasibility_path,
        tolerances=args.tolerances,
        operations=args.operations,
    )
    write_main_wing_station_seam_shape_fix_feasibility_report(
        out_dir,
        report=report,
        same_parameter_feasibility_path=same_parameter_feasibility_path,
        tolerances=args.tolerances,
        operations=args.operations,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.feasibility_status != "blocked" else 2


def cmd_main_wing_station_seam_export_source_audit(
    args: argparse.Namespace,
) -> int:
    out_dir = Path(args.out)
    shape_fix_feasibility_path = (
        None if args.shape_fix_feasibility is None else Path(args.shape_fix_feasibility)
    )
    topology_fixture_path = (
        None if args.topology_fixture is None else Path(args.topology_fixture)
    )
    rebuild_csm_path = None if args.rebuild_csm is None else Path(args.rebuild_csm)
    topology_lineage_path = (
        None if args.topology_lineage is None else Path(args.topology_lineage)
    )
    report = build_main_wing_station_seam_export_source_audit_report(
        shape_fix_feasibility_path=shape_fix_feasibility_path,
        topology_fixture_path=topology_fixture_path,
        rebuild_csm_path=rebuild_csm_path,
        topology_lineage_path=topology_lineage_path,
    )
    write_main_wing_station_seam_export_source_audit_report(
        out_dir,
        report=report,
        shape_fix_feasibility_path=shape_fix_feasibility_path,
        topology_fixture_path=topology_fixture_path,
        rebuild_csm_path=rebuild_csm_path,
        topology_lineage_path=topology_lineage_path,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.audit_status != "blocked" else 2


def cmd_main_wing_station_seam_export_strategy_probe(
    args: argparse.Namespace,
) -> int:
    out_dir = Path(args.out)
    export_source_audit_path = (
        None if args.export_source_audit is None else Path(args.export_source_audit)
    )
    report = build_main_wing_station_seam_export_strategy_probe_report(
        export_source_audit_path=export_source_audit_path,
        materialization_requested=args.materialize_candidates,
        materialization_root=out_dir,
        timeout_seconds=args.timeout_seconds,
    )
    write_main_wing_station_seam_export_strategy_probe_report(
        out_dir,
        report=report,
        export_source_audit_path=export_source_audit_path,
        materialization_requested=args.materialize_candidates,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.probe_status != "blocked" else 2


def cmd_main_wing_station_seam_internal_cap_probe(
    args: argparse.Namespace,
) -> int:
    out_dir = Path(args.out)
    export_strategy_probe_path = (
        None if args.export_strategy_probe is None else Path(args.export_strategy_probe)
    )
    report = build_main_wing_station_seam_internal_cap_probe_report(
        export_strategy_probe_path=export_strategy_probe_path,
        station_plane_tolerance=args.station_plane_tolerance,
    )
    write_main_wing_station_seam_internal_cap_probe_report(
        out_dir,
        report=report,
        export_strategy_probe_path=export_strategy_probe_path,
        station_plane_tolerance=args.station_plane_tolerance,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.probe_status != "blocked" else 2


def cmd_main_wing_station_seam_profile_resample_strategy_probe(
    args: argparse.Namespace,
) -> int:
    out_dir = Path(args.out)
    export_source_audit_path = (
        None if args.export_source_audit is None else Path(args.export_source_audit)
    )
    report = build_main_wing_station_seam_profile_resample_strategy_probe_report(
        export_source_audit_path=export_source_audit_path,
        materialization_requested=args.materialize_candidate,
        materialization_root=out_dir,
        timeout_seconds=args.timeout_seconds,
        target_profile_point_count=args.target_profile_point_count,
    )
    write_main_wing_station_seam_profile_resample_strategy_probe_report(
        out_dir,
        report=report,
        export_source_audit_path=export_source_audit_path,
        materialization_requested=args.materialize_candidate,
        timeout_seconds=args.timeout_seconds,
        target_profile_point_count=args.target_profile_point_count,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.probe_status != "blocked" else 2


def cmd_main_wing_su2_force_marker_audit(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report_root = None if args.report_root is None else Path(args.report_root)
    source_su2_probe_report_path = (
        None
        if args.source_su2_probe_report is None
        else Path(args.source_su2_probe_report)
    )
    report = build_main_wing_su2_force_marker_audit_report(
        report_root=report_root,
        source_su2_probe_report_path=source_su2_probe_report_path,
    )
    write_main_wing_su2_force_marker_audit_report(
        out_dir,
        report=report,
        report_root=report_root,
        source_su2_probe_report_path=source_su2_probe_report_path,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.audit_status in {"pass", "warn"} else 2


def cmd_main_wing_surface_force_output_audit(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report_root = None if args.report_root is None else Path(args.report_root)
    solver_report_path = None if args.solver_report is None else Path(args.solver_report)
    panel_reference_report_path = (
        None
        if args.panel_reference_report is None
        else Path(args.panel_reference_report)
    )
    report = build_main_wing_surface_force_output_audit_report(
        report_root=report_root,
        solver_report_path=solver_report_path,
        panel_reference_report_path=panel_reference_report_path,
    )
    write_main_wing_surface_force_output_audit_report(
        out_dir,
        report=report,
        report_root=report_root,
        solver_report_path=solver_report_path,
        panel_reference_report_path=panel_reference_report_path,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.audit_status in {"pass", "warn"} else 2


def cmd_main_wing_vspaero_panel_reference_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    polar_path = None if args.polar is None else Path(args.polar)
    setup_path = None if args.setup is None else Path(args.setup)
    lift_diagnostic_path = (
        None if args.lift_diagnostic_report is None else Path(args.lift_diagnostic_report)
    )
    report = build_main_wing_vspaero_panel_reference_probe_report(
        polar_path=polar_path,
        setup_path=setup_path,
        lift_diagnostic_path=lift_diagnostic_path,
    )
    write_main_wing_vspaero_panel_reference_probe_report(
        out_dir,
        report=report,
        polar_path=polar_path,
        setup_path=setup_path,
        lift_diagnostic_path=lift_diagnostic_path,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.panel_reference_status == "panel_reference_available" else 2


def cmd_main_wing_geometry_provenance_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_main_wing_geometry_provenance_probe_report(source_path=source_path)
    write_main_wing_geometry_provenance_probe_report(
        out_dir,
        report=report,
        source_path=source_path,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.geometry_provenance_status == "provenance_available" else 2


def cmd_main_wing_real_su2_handoff_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    source_mesh_probe_report_path = (
        None
        if args.source_mesh_probe_report is None
        else Path(args.source_mesh_probe_report)
    )
    report = build_main_wing_real_su2_handoff_probe_report(
        out_dir,
        source_path=source_path,
        timeout_seconds=float(args.timeout_seconds),
        source_mesh_probe_report_path=source_mesh_probe_report_path,
        max_iterations=int(args.max_iterations),
        reference_policy=args.reference_policy,
    )
    write_main_wing_real_su2_handoff_probe_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.materialization_status == "su2_handoff_written" else 2


def cmd_main_wing_real_solver_smoke_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_su2_probe_report_path = (
        None if args.source_su2_probe_report is None else Path(args.source_su2_probe_report)
    )
    report = build_main_wing_real_solver_smoke_probe_report(
        out_dir,
        source_su2_probe_report_path=source_su2_probe_report_path,
        timeout_seconds=float(args.timeout_seconds),
    )
    write_main_wing_real_solver_smoke_probe_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.solver_execution_status in {
        "solver_executed",
        "solver_failed",
        "solver_timeout",
        "solver_unavailable",
    } else 2


def cmd_main_wing_reference_geometry_gate(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report_root = None if args.report_root is None else Path(args.report_root)
    source_su2_probe_report_path = (
        None
        if args.source_su2_probe_report is None
        else Path(args.source_su2_probe_report)
    )
    report = build_main_wing_reference_geometry_gate_report(
        report_root=report_root,
        source_su2_probe_report_path=source_su2_probe_report_path,
    )
    write_main_wing_reference_geometry_gate_report(
        out_dir,
        report=report,
        report_root=report_root,
        source_su2_probe_report_path=source_su2_probe_report_path,
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.reference_gate_status in {"pass", "warn"} else 2


def cmd_tail_wing_mesh_handoff_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report = build_tail_wing_mesh_handoff_smoke_report(out_dir)
    write_tail_wing_mesh_handoff_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.smoke_status == "mesh_handoff_pass" else 2


def cmd_tail_wing_su2_handoff_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report = build_tail_wing_su2_handoff_smoke_report(out_dir)
    write_tail_wing_su2_handoff_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.materialization_status == "su2_handoff_written" else 2


def cmd_tail_wing_esp_rebuilt_geometry_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_tail_wing_esp_rebuilt_geometry_smoke_report(
        out_dir,
        source_path=source_path,
    )
    write_tail_wing_esp_rebuilt_geometry_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.geometry_smoke_status == "geometry_smoke_pass" else 2


def cmd_tail_wing_real_mesh_handoff_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_tail_wing_real_mesh_handoff_probe_report(
        out_dir,
        source_path=source_path,
    )
    write_tail_wing_real_mesh_handoff_probe_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.probe_status in {"mesh_handoff_pass", "mesh_handoff_blocked"} else 2


def cmd_tail_wing_surface_mesh_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_tail_wing_surface_mesh_probe_report(
        out_dir,
        source_path=source_path,
    )
    write_tail_wing_surface_mesh_probe_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.probe_status == "surface_mesh_pass" else 2


def cmd_tail_wing_solidification_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_tail_wing_solidification_probe_report(
        out_dir,
        source_path=source_path,
    )
    write_tail_wing_solidification_probe_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.solidification_status in {"solidified", "no_volume_created"} else 2


def cmd_tail_wing_explicit_volume_route_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_tail_wing_explicit_volume_route_probe_report(
        out_dir,
        source_path=source_path,
    )
    write_tail_wing_explicit_volume_route_probe_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.route_probe_status in {
        "explicit_volume_route_candidate",
        "explicit_volume_route_blocked",
    } else 2


def cmd_main_wing_su2_handoff_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report = build_main_wing_su2_handoff_smoke_report(out_dir)
    write_main_wing_su2_handoff_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.materialization_status == "su2_handoff_written" else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hpa-mesh")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run")
    run.add_argument("--component", type=str)
    run.add_argument("--geometry", type=str)
    run.add_argument("--geometry-provider", type=str)
    run.add_argument("--config", type=str, required=True)
    run.add_argument("--out", type=str)
    run.set_defaults(func=cmd_run)

    val = sub.add_parser("validate-geometry")
    val.add_argument("--component", type=str, required=True)
    val.add_argument("--geometry", type=str, required=True)
    val.add_argument("--geometry-provider", type=str)
    val.add_argument("--config", type=str)
    val.add_argument("--out", type=str)
    val.set_defaults(func=cmd_validate_geometry)

    batch = sub.add_parser("batch")
    batch.add_argument("--manifest", type=str, required=True)
    batch.set_defaults(func=cmd_batch)

    mesh_study = sub.add_parser("mesh-study")
    mesh_study.add_argument("--component", type=str)
    mesh_study.add_argument("--geometry", type=str)
    mesh_study.add_argument("--geometry-provider", type=str)
    mesh_study.add_argument("--config", type=str, required=True)
    mesh_study.add_argument("--out", type=str)
    mesh_study.set_defaults(func=cmd_mesh_study)

    baseline_freeze = sub.add_parser("baseline-freeze")
    baseline_freeze.add_argument("--baseline-manifest", type=str, required=True)
    baseline_freeze.add_argument("--mesh-handoff", type=str)
    baseline_freeze.add_argument("--out", type=str)
    baseline_freeze.set_defaults(func=cmd_baseline_freeze)

    baseline_cfd = sub.add_parser("baseline-cfd")
    baseline_cfd.add_argument("--baseline-manifest", type=str, required=True)
    baseline_cfd.add_argument("--mesh-handoff", type=str)
    baseline_cfd.add_argument("--out", type=str, required=True)
    baseline_cfd.set_defaults(func=cmd_baseline_cfd)

    refinement = sub.add_parser("shell-v3-refinement-study")
    refinement.add_argument("--baseline-manifest", type=str, required=True)
    refinement.add_argument("--mesh-handoff", type=str)
    refinement.add_argument("--out", type=str, required=True)
    refinement.set_defaults(func=cmd_shell_v3_refinement_study)

    shell_v4 = sub.add_parser("shell-v4-half-wing-bl-mesh-macsafe")
    shell_v4.add_argument("--out", type=str, required=True)
    shell_v4.add_argument(
        "--study-level",
        type=str,
        default="BL_macsafe_baseline",
        choices=["BL_macsafe_baseline", "BL_macsafe_upper"],
    )
    shell_v4.add_argument("--skip-su2", action="store_true")
    shell_v4.add_argument("--allow-swap-risk", action="store_true")
    shell_v4.add_argument("--topology-compiler-plan-only", action="store_true")
    shell_v4.add_argument("--apply-bl-stageback-plus-truncation-focused", action="store_true")
    shell_v4.add_argument("--apply-bl-stage-with-termination-guard-8-to-7-focused", action="store_true")
    shell_v4.add_argument("--run-bl-candidate-sweep-focused", action="store_true")
    shell_v4.set_defaults(func=cmd_shell_v4_half_wing_bl_mesh_macsafe)

    readiness = sub.add_parser("route-readiness")
    readiness.add_argument("--out", type=str, required=True)
    readiness.set_defaults(func=cmd_route_readiness)

    smoke_matrix = sub.add_parser("component-family-smoke-matrix")
    smoke_matrix.add_argument("--out", type=str, required=True)
    smoke_matrix.set_defaults(func=cmd_component_family_smoke_matrix)

    fairing_smoke = sub.add_parser("fairing-solid-mesh-handoff-smoke")
    fairing_smoke.add_argument("--out", type=str, required=True)
    fairing_smoke.set_defaults(func=cmd_fairing_solid_mesh_handoff_smoke)

    fairing_real_geometry_smoke = sub.add_parser("fairing-solid-real-geometry-smoke")
    fairing_real_geometry_smoke.add_argument("--out", type=str, required=True)
    fairing_real_geometry_smoke.add_argument("--source", type=str)
    fairing_real_geometry_smoke.set_defaults(func=cmd_fairing_solid_real_geometry_smoke)

    fairing_real_mesh_probe = sub.add_parser("fairing-solid-real-mesh-handoff-probe")
    fairing_real_mesh_probe.add_argument("--out", type=str, required=True)
    fairing_real_mesh_probe.add_argument("--source", type=str)
    fairing_real_mesh_probe.add_argument("--timeout-seconds", type=float, default=60.0)
    fairing_real_mesh_probe.set_defaults(func=cmd_fairing_solid_real_mesh_handoff_probe)

    fairing_su2_smoke = sub.add_parser("fairing-solid-su2-handoff-smoke")
    fairing_su2_smoke.add_argument("--out", type=str, required=True)
    fairing_su2_smoke.set_defaults(func=cmd_fairing_solid_su2_handoff_smoke)

    fairing_real_su2_probe = sub.add_parser("fairing-solid-real-su2-handoff-probe")
    fairing_real_su2_probe.add_argument("--out", type=str, required=True)
    fairing_real_su2_probe.add_argument("--source", type=str)
    fairing_real_su2_probe.add_argument("--timeout-seconds", type=float, default=60.0)
    fairing_real_su2_probe.add_argument("--source-mesh-probe-report", type=str)
    fairing_real_su2_probe.set_defaults(func=cmd_fairing_solid_real_su2_handoff_probe)

    fairing_reference_policy_probe = sub.add_parser(
        "fairing-solid-reference-policy-probe"
    )
    fairing_reference_policy_probe.add_argument("--out", type=str, required=True)
    fairing_reference_policy_probe.add_argument("--external-project-root", type=str)
    fairing_reference_policy_probe.add_argument("--external-su2-cfg", type=str)
    fairing_reference_policy_probe.add_argument("--hpa-su2-probe-report", type=str)
    fairing_reference_policy_probe.set_defaults(
        func=cmd_fairing_solid_reference_policy_probe
    )

    fairing_reference_override_su2_probe = sub.add_parser(
        "fairing-solid-reference-override-su2-handoff-probe"
    )
    fairing_reference_override_su2_probe.add_argument("--out", type=str, required=True)
    fairing_reference_override_su2_probe.add_argument(
        "--reference-policy-probe",
        type=str,
    )
    fairing_reference_override_su2_probe.add_argument(
        "--source-su2-probe-report",
        type=str,
    )
    fairing_reference_override_su2_probe.set_defaults(
        func=cmd_fairing_solid_reference_override_su2_handoff_probe
    )

    main_wing_smoke = sub.add_parser("main-wing-mesh-handoff-smoke")
    main_wing_smoke.add_argument("--out", type=str, required=True)
    main_wing_smoke.set_defaults(func=cmd_main_wing_mesh_handoff_smoke)

    main_wing_esp_geometry_smoke = sub.add_parser("main-wing-esp-rebuilt-geometry-smoke")
    main_wing_esp_geometry_smoke.add_argument("--out", type=str, required=True)
    main_wing_esp_geometry_smoke.add_argument("--source", type=str)
    main_wing_esp_geometry_smoke.set_defaults(func=cmd_main_wing_esp_rebuilt_geometry_smoke)

    main_wing_real_mesh_probe = sub.add_parser("main-wing-real-mesh-handoff-probe")
    main_wing_real_mesh_probe.add_argument("--out", type=str, required=True)
    main_wing_real_mesh_probe.add_argument("--source", type=str)
    main_wing_real_mesh_probe.add_argument("--timeout-seconds", type=float, default=45.0)
    main_wing_real_mesh_probe.add_argument("--global-min-size", type=float, default=0.2)
    main_wing_real_mesh_probe.add_argument("--global-max-size", type=float, default=0.8)
    main_wing_real_mesh_probe.set_defaults(func=cmd_main_wing_real_mesh_handoff_probe)

    main_wing_route_readiness = sub.add_parser("main-wing-route-readiness")
    main_wing_route_readiness.add_argument("--out", type=str, required=True)
    main_wing_route_readiness.set_defaults(func=cmd_main_wing_route_readiness)

    main_wing_solver_budget_comparison = sub.add_parser(
        "main-wing-solver-budget-comparison"
    )
    main_wing_solver_budget_comparison.add_argument("--out", type=str, required=True)
    main_wing_solver_budget_comparison.add_argument("--report-root", type=str)
    main_wing_solver_budget_comparison.set_defaults(
        func=cmd_main_wing_solver_budget_comparison
    )

    main_wing_lift_acceptance = sub.add_parser(
        "main-wing-lift-acceptance-diagnostic"
    )
    main_wing_lift_acceptance.add_argument("--out", type=str, required=True)
    main_wing_lift_acceptance.add_argument("--report-root", type=str)
    main_wing_lift_acceptance.set_defaults(
        func=cmd_main_wing_lift_acceptance_diagnostic
    )

    main_wing_panel_su2_lift_gap_debug = sub.add_parser(
        "main-wing-panel-su2-lift-gap-debug"
    )
    main_wing_panel_su2_lift_gap_debug.add_argument("--out", type=str, required=True)
    main_wing_panel_su2_lift_gap_debug.add_argument("--report-root", type=str)
    main_wing_panel_su2_lift_gap_debug.set_defaults(
        func=cmd_main_wing_panel_su2_lift_gap_debug
    )

    main_wing_su2_mesh_normal_audit = sub.add_parser(
        "main-wing-su2-mesh-normal-audit"
    )
    main_wing_su2_mesh_normal_audit.add_argument("--out", type=str, required=True)
    main_wing_su2_mesh_normal_audit.add_argument("--mesh", type=str)
    main_wing_su2_mesh_normal_audit.set_defaults(
        func=cmd_main_wing_su2_mesh_normal_audit
    )

    main_wing_panel_wake_semantics_audit = sub.add_parser(
        "main-wing-panel-wake-semantics-audit"
    )
    main_wing_panel_wake_semantics_audit.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_panel_wake_semantics_audit.add_argument("--report-root", type=str)
    main_wing_panel_wake_semantics_audit.add_argument("--runtime-cfg", type=str)
    main_wing_panel_wake_semantics_audit.set_defaults(
        func=cmd_main_wing_panel_wake_semantics_audit
    )

    main_wing_su2_surface_topology_audit = sub.add_parser(
        "main-wing-su2-surface-topology-audit"
    )
    main_wing_su2_surface_topology_audit.add_argument("--out", type=str, required=True)
    main_wing_su2_surface_topology_audit.add_argument("--mesh", type=str)
    main_wing_su2_surface_topology_audit.add_argument("--report-root", type=str)
    main_wing_su2_surface_topology_audit.add_argument(
        "--reference-area",
        type=float,
    )
    main_wing_su2_surface_topology_audit.set_defaults(
        func=cmd_main_wing_su2_surface_topology_audit
    )

    main_wing_mesh_quality_hotspot_audit = sub.add_parser(
        "main-wing-mesh-quality-hotspot-audit"
    )
    main_wing_mesh_quality_hotspot_audit.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_mesh_quality_hotspot_audit.add_argument(
        "--mesh-handoff-report",
        type=str,
    )
    main_wing_mesh_quality_hotspot_audit.add_argument(
        "--mesh-metadata",
        type=str,
    )
    main_wing_mesh_quality_hotspot_audit.add_argument(
        "--hotspot-patch-report",
        type=str,
    )
    main_wing_mesh_quality_hotspot_audit.add_argument(
        "--surface-patch-diagnostics",
        type=str,
    )
    main_wing_mesh_quality_hotspot_audit.add_argument(
        "--gmsh-defect-entity-trace",
        type=str,
    )
    main_wing_mesh_quality_hotspot_audit.set_defaults(
        func=cmd_main_wing_mesh_quality_hotspot_audit
    )

    main_wing_su2_topology_defect_localization = sub.add_parser(
        "main-wing-su2-topology-defect-localization"
    )
    main_wing_su2_topology_defect_localization.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_su2_topology_defect_localization.add_argument("--mesh", type=str)
    main_wing_su2_topology_defect_localization.set_defaults(
        func=cmd_main_wing_su2_topology_defect_localization
    )

    main_wing_openvsp_defect_station_audit = sub.add_parser(
        "main-wing-openvsp-defect-station-audit"
    )
    main_wing_openvsp_defect_station_audit.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_openvsp_defect_station_audit.add_argument(
        "--defect-localization",
        type=str,
    )
    main_wing_openvsp_defect_station_audit.add_argument(
        "--topology-lineage",
        type=str,
    )
    main_wing_openvsp_defect_station_audit.add_argument("--source-vsp3", type=str)
    main_wing_openvsp_defect_station_audit.set_defaults(
        func=cmd_main_wing_openvsp_defect_station_audit
    )

    main_wing_gmsh_defect_entity_trace = sub.add_parser(
        "main-wing-gmsh-defect-entity-trace"
    )
    main_wing_gmsh_defect_entity_trace.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_gmsh_defect_entity_trace.add_argument("--mesh", type=str)
    main_wing_gmsh_defect_entity_trace.add_argument(
        "--defect-localization",
        type=str,
    )
    main_wing_gmsh_defect_entity_trace.add_argument(
        "--openvsp-station-audit",
        type=str,
    )
    main_wing_gmsh_defect_entity_trace.add_argument(
        "--surface-patch-diagnostics",
        type=str,
    )
    main_wing_gmsh_defect_entity_trace.set_defaults(
        func=cmd_main_wing_gmsh_defect_entity_trace
    )

    main_wing_gmsh_curve_station_rebuild_audit = sub.add_parser(
        "main-wing-gmsh-curve-station-rebuild-audit"
    )
    main_wing_gmsh_curve_station_rebuild_audit.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_gmsh_curve_station_rebuild_audit.add_argument(
        "--gmsh-defect-entity-trace",
        type=str,
    )
    main_wing_gmsh_curve_station_rebuild_audit.add_argument("--source-vsp3", type=str)
    main_wing_gmsh_curve_station_rebuild_audit.set_defaults(
        func=cmd_main_wing_gmsh_curve_station_rebuild_audit
    )

    main_wing_openvsp_section_station_topology_fixture = sub.add_parser(
        "main-wing-openvsp-section-station-topology-fixture"
    )
    main_wing_openvsp_section_station_topology_fixture.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_openvsp_section_station_topology_fixture.add_argument(
        "--gmsh-defect-entity-trace",
        type=str,
    )
    main_wing_openvsp_section_station_topology_fixture.add_argument(
        "--gmsh-curve-station-rebuild-audit",
        type=str,
    )
    main_wing_openvsp_section_station_topology_fixture.set_defaults(
        func=cmd_main_wing_openvsp_section_station_topology_fixture
    )

    main_wing_station_seam_repair_decision = sub.add_parser(
        "main-wing-station-seam-repair-decision"
    )
    main_wing_station_seam_repair_decision.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_station_seam_repair_decision.add_argument(
        "--topology-fixture",
        type=str,
    )
    main_wing_station_seam_repair_decision.add_argument("--solver-report", type=str)
    main_wing_station_seam_repair_decision.set_defaults(
        func=cmd_main_wing_station_seam_repair_decision
    )

    main_wing_station_seam_brep_hotspot_probe = sub.add_parser(
        "main-wing-station-seam-brep-hotspot-probe"
    )
    main_wing_station_seam_brep_hotspot_probe.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_station_seam_brep_hotspot_probe.add_argument(
        "--topology-fixture",
        type=str,
    )
    main_wing_station_seam_brep_hotspot_probe.add_argument(
        "--real-mesh-probe-report",
        type=str,
    )
    main_wing_station_seam_brep_hotspot_probe.add_argument(
        "--normalized-step",
        type=str,
    )
    main_wing_station_seam_brep_hotspot_probe.add_argument(
        "--surface-patch-diagnostics",
        type=str,
    )
    main_wing_station_seam_brep_hotspot_probe.add_argument(
        "--curve-tags",
        nargs="+",
        type=int,
    )
    main_wing_station_seam_brep_hotspot_probe.add_argument(
        "--surface-tags",
        nargs="+",
        type=int,
    )
    main_wing_station_seam_brep_hotspot_probe.set_defaults(
        func=cmd_main_wing_station_seam_brep_hotspot_probe
    )

    main_wing_station_seam_same_parameter_feasibility = sub.add_parser(
        "main-wing-station-seam-same-parameter-feasibility"
    )
    main_wing_station_seam_same_parameter_feasibility.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_station_seam_same_parameter_feasibility.add_argument(
        "--brep-hotspot-probe",
        type=str,
    )
    main_wing_station_seam_same_parameter_feasibility.add_argument(
        "--tolerances",
        nargs="+",
        type=float,
    )
    main_wing_station_seam_same_parameter_feasibility.set_defaults(
        func=cmd_main_wing_station_seam_same_parameter_feasibility
    )

    main_wing_station_seam_shape_fix_feasibility = sub.add_parser(
        "main-wing-station-seam-shape-fix-feasibility"
    )
    main_wing_station_seam_shape_fix_feasibility.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_station_seam_shape_fix_feasibility.add_argument(
        "--same-parameter-feasibility",
        type=str,
    )
    main_wing_station_seam_shape_fix_feasibility.add_argument(
        "--tolerances",
        nargs="+",
        type=float,
    )
    main_wing_station_seam_shape_fix_feasibility.add_argument(
        "--operations",
        nargs="+",
        type=str,
    )
    main_wing_station_seam_shape_fix_feasibility.set_defaults(
        func=cmd_main_wing_station_seam_shape_fix_feasibility
    )

    main_wing_station_seam_export_source_audit = sub.add_parser(
        "main-wing-station-seam-export-source-audit"
    )
    main_wing_station_seam_export_source_audit.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_station_seam_export_source_audit.add_argument(
        "--shape-fix-feasibility",
        type=str,
    )
    main_wing_station_seam_export_source_audit.add_argument(
        "--topology-fixture",
        type=str,
    )
    main_wing_station_seam_export_source_audit.add_argument(
        "--rebuild-csm",
        type=str,
    )
    main_wing_station_seam_export_source_audit.add_argument(
        "--topology-lineage",
        type=str,
    )
    main_wing_station_seam_export_source_audit.set_defaults(
        func=cmd_main_wing_station_seam_export_source_audit
    )

    main_wing_station_seam_export_strategy_probe = sub.add_parser(
        "main-wing-station-seam-export-strategy-probe"
    )
    main_wing_station_seam_export_strategy_probe.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_station_seam_export_strategy_probe.add_argument(
        "--export-source-audit",
        type=str,
    )
    main_wing_station_seam_export_strategy_probe.add_argument(
        "--materialize-candidates",
        action="store_true",
    )
    main_wing_station_seam_export_strategy_probe.add_argument(
        "--timeout-seconds",
        type=float,
        default=90.0,
    )
    main_wing_station_seam_export_strategy_probe.set_defaults(
        func=cmd_main_wing_station_seam_export_strategy_probe
    )

    main_wing_station_seam_internal_cap_probe = sub.add_parser(
        "main-wing-station-seam-internal-cap-probe"
    )
    main_wing_station_seam_internal_cap_probe.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_station_seam_internal_cap_probe.add_argument(
        "--export-strategy-probe",
        type=str,
    )
    main_wing_station_seam_internal_cap_probe.add_argument(
        "--station-plane-tolerance",
        type=float,
        default=1.0e-4,
    )
    main_wing_station_seam_internal_cap_probe.set_defaults(
        func=cmd_main_wing_station_seam_internal_cap_probe
    )

    main_wing_station_seam_profile_resample_strategy_probe = sub.add_parser(
        "main-wing-station-seam-profile-resample-strategy-probe"
    )
    main_wing_station_seam_profile_resample_strategy_probe.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_station_seam_profile_resample_strategy_probe.add_argument(
        "--export-source-audit",
        type=str,
    )
    main_wing_station_seam_profile_resample_strategy_probe.add_argument(
        "--materialize-candidate",
        action="store_true",
    )
    main_wing_station_seam_profile_resample_strategy_probe.add_argument(
        "--target-profile-point-count",
        type=int,
    )
    main_wing_station_seam_profile_resample_strategy_probe.add_argument(
        "--timeout-seconds",
        type=float,
        default=90.0,
    )
    main_wing_station_seam_profile_resample_strategy_probe.set_defaults(
        func=cmd_main_wing_station_seam_profile_resample_strategy_probe
    )

    main_wing_station_seam_profile_resample_brep_validation_probe = sub.add_parser(
        "main-wing-station-seam-profile-resample-brep-validation-probe"
    )
    main_wing_station_seam_profile_resample_brep_validation_probe.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_station_seam_profile_resample_brep_validation_probe.add_argument(
        "--profile-resample-probe",
        type=str,
    )
    main_wing_station_seam_profile_resample_brep_validation_probe.add_argument(
        "--candidate-step",
        type=str,
    )
    main_wing_station_seam_profile_resample_brep_validation_probe.add_argument(
        "--station-y-targets",
        nargs="+",
        type=float,
    )
    main_wing_station_seam_profile_resample_brep_validation_probe.add_argument(
        "--station-tolerance",
        type=float,
        default=1.0e-4,
    )
    main_wing_station_seam_profile_resample_brep_validation_probe.add_argument(
        "--scale-to-output-units",
        type=float,
        default=1.0,
    )
    main_wing_station_seam_profile_resample_brep_validation_probe.set_defaults(
        func=cmd_main_wing_station_seam_profile_resample_brep_validation_probe
    )

    main_wing_station_seam_profile_resample_repair_feasibility_probe = (
        sub.add_parser(
            "main-wing-station-seam-profile-resample-repair-feasibility-probe"
        )
    )
    main_wing_station_seam_profile_resample_repair_feasibility_probe.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_station_seam_profile_resample_repair_feasibility_probe.add_argument(
        "--brep-validation-probe",
        type=str,
    )
    main_wing_station_seam_profile_resample_repair_feasibility_probe.add_argument(
        "--tolerances",
        nargs="+",
        type=float,
    )
    main_wing_station_seam_profile_resample_repair_feasibility_probe.add_argument(
        "--operations",
        nargs="+",
        type=str,
    )
    main_wing_station_seam_profile_resample_repair_feasibility_probe.set_defaults(
        func=cmd_main_wing_station_seam_profile_resample_repair_feasibility_probe
    )

    main_wing_station_seam_profile_parametrization_audit = sub.add_parser(
        "main-wing-station-seam-profile-parametrization-audit"
    )
    main_wing_station_seam_profile_parametrization_audit.add_argument(
        "--out",
        type=str,
        required=True,
    )
    main_wing_station_seam_profile_parametrization_audit.add_argument(
        "--profile-resample-probe",
        type=str,
    )
    main_wing_station_seam_profile_parametrization_audit.add_argument(
        "--brep-validation-probe",
        type=str,
    )
    main_wing_station_seam_profile_parametrization_audit.add_argument(
        "--station-tolerance",
        type=float,
        default=1.0e-4,
    )
    main_wing_station_seam_profile_parametrization_audit.add_argument(
        "--match-tolerance",
        type=float,
        default=0.03,
    )
    main_wing_station_seam_profile_parametrization_audit.set_defaults(
        func=cmd_main_wing_station_seam_profile_parametrization_audit
    )

    main_wing_su2_force_marker_audit = sub.add_parser(
        "main-wing-su2-force-marker-audit"
    )
    main_wing_su2_force_marker_audit.add_argument("--out", type=str, required=True)
    main_wing_su2_force_marker_audit.add_argument("--report-root", type=str)
    main_wing_su2_force_marker_audit.add_argument("--source-su2-probe-report", type=str)
    main_wing_su2_force_marker_audit.set_defaults(
        func=cmd_main_wing_su2_force_marker_audit
    )

    main_wing_surface_force_output_audit = sub.add_parser(
        "main-wing-surface-force-output-audit"
    )
    main_wing_surface_force_output_audit.add_argument("--out", type=str, required=True)
    main_wing_surface_force_output_audit.add_argument("--report-root", type=str)
    main_wing_surface_force_output_audit.add_argument("--solver-report", type=str)
    main_wing_surface_force_output_audit.add_argument(
        "--panel-reference-report",
        type=str,
    )
    main_wing_surface_force_output_audit.set_defaults(
        func=cmd_main_wing_surface_force_output_audit
    )

    main_wing_vspaero_panel_reference = sub.add_parser(
        "main-wing-vspaero-panel-reference-probe"
    )
    main_wing_vspaero_panel_reference.add_argument("--out", type=str, required=True)
    main_wing_vspaero_panel_reference.add_argument("--polar", type=str)
    main_wing_vspaero_panel_reference.add_argument("--setup", type=str)
    main_wing_vspaero_panel_reference.add_argument(
        "--lift-diagnostic-report",
        type=str,
    )
    main_wing_vspaero_panel_reference.set_defaults(
        func=cmd_main_wing_vspaero_panel_reference_probe
    )

    main_wing_geometry_provenance = sub.add_parser(
        "main-wing-geometry-provenance-probe"
    )
    main_wing_geometry_provenance.add_argument("--out", type=str, required=True)
    main_wing_geometry_provenance.add_argument("--source", type=str)
    main_wing_geometry_provenance.set_defaults(
        func=cmd_main_wing_geometry_provenance_probe
    )

    main_wing_real_su2_probe = sub.add_parser("main-wing-real-su2-handoff-probe")
    main_wing_real_su2_probe.add_argument("--out", type=str, required=True)
    main_wing_real_su2_probe.add_argument("--source", type=str)
    main_wing_real_su2_probe.add_argument("--timeout-seconds", type=float, default=45.0)
    main_wing_real_su2_probe.add_argument("--max-iterations", type=int, default=12)
    main_wing_real_su2_probe.add_argument(
        "--reference-policy",
        choices=["declared_blackcat_full_span", "openvsp_geometry_derived"],
        default="declared_blackcat_full_span",
    )
    main_wing_real_su2_probe.add_argument("--source-mesh-probe-report", type=str)
    main_wing_real_su2_probe.set_defaults(func=cmd_main_wing_real_su2_handoff_probe)

    main_wing_real_solver_probe = sub.add_parser("main-wing-real-solver-smoke-probe")
    main_wing_real_solver_probe.add_argument("--out", type=str, required=True)
    main_wing_real_solver_probe.add_argument("--source-su2-probe-report", type=str)
    main_wing_real_solver_probe.add_argument("--timeout-seconds", type=float, default=120.0)
    main_wing_real_solver_probe.set_defaults(func=cmd_main_wing_real_solver_smoke_probe)

    main_wing_reference_gate = sub.add_parser("main-wing-reference-geometry-gate")
    main_wing_reference_gate.add_argument("--out", type=str, required=True)
    main_wing_reference_gate.add_argument("--report-root", type=str)
    main_wing_reference_gate.add_argument("--source-su2-probe-report", type=str)
    main_wing_reference_gate.set_defaults(func=cmd_main_wing_reference_geometry_gate)

    tail_wing_smoke = sub.add_parser("tail-wing-mesh-handoff-smoke")
    tail_wing_smoke.add_argument("--out", type=str, required=True)
    tail_wing_smoke.set_defaults(func=cmd_tail_wing_mesh_handoff_smoke)

    tail_wing_su2_smoke = sub.add_parser("tail-wing-su2-handoff-smoke")
    tail_wing_su2_smoke.add_argument("--out", type=str, required=True)
    tail_wing_su2_smoke.set_defaults(func=cmd_tail_wing_su2_handoff_smoke)

    tail_wing_esp_geometry_smoke = sub.add_parser("tail-wing-esp-rebuilt-geometry-smoke")
    tail_wing_esp_geometry_smoke.add_argument("--out", type=str, required=True)
    tail_wing_esp_geometry_smoke.add_argument("--source", type=str)
    tail_wing_esp_geometry_smoke.set_defaults(func=cmd_tail_wing_esp_rebuilt_geometry_smoke)

    tail_wing_real_mesh_probe = sub.add_parser("tail-wing-real-mesh-handoff-probe")
    tail_wing_real_mesh_probe.add_argument("--out", type=str, required=True)
    tail_wing_real_mesh_probe.add_argument("--source", type=str)
    tail_wing_real_mesh_probe.set_defaults(func=cmd_tail_wing_real_mesh_handoff_probe)

    tail_wing_surface_mesh_probe = sub.add_parser("tail-wing-surface-mesh-probe")
    tail_wing_surface_mesh_probe.add_argument("--out", type=str, required=True)
    tail_wing_surface_mesh_probe.add_argument("--source", type=str)
    tail_wing_surface_mesh_probe.set_defaults(func=cmd_tail_wing_surface_mesh_probe)

    tail_wing_solidification_probe = sub.add_parser("tail-wing-solidification-probe")
    tail_wing_solidification_probe.add_argument("--out", type=str, required=True)
    tail_wing_solidification_probe.add_argument("--source", type=str)
    tail_wing_solidification_probe.set_defaults(func=cmd_tail_wing_solidification_probe)

    tail_wing_explicit_volume_route_probe = sub.add_parser(
        "tail-wing-explicit-volume-route-probe"
    )
    tail_wing_explicit_volume_route_probe.add_argument("--out", type=str, required=True)
    tail_wing_explicit_volume_route_probe.add_argument("--source", type=str)
    tail_wing_explicit_volume_route_probe.set_defaults(
        func=cmd_tail_wing_explicit_volume_route_probe
    )

    main_wing_su2_smoke = sub.add_parser("main-wing-su2-handoff-smoke")
    main_wing_su2_smoke.add_argument("--out", type=str, required=True)
    main_wing_su2_smoke.set_defaults(func=cmd_main_wing_su2_handoff_smoke)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
