from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

import numpy as np

from hpa_mdo.structure.calculix_beam_export import BeamMaterial
from hpa_mdo.structure.spar_model import tube_J
from scripts.phase14_maclocal_fem_package import (
    B2ComparisonInputs,
    B2TaperedShellHardeningRow,
    B5ShellTorsionHardeningRow,
    BestRouteCheckRow,
    ConstantTubeVerificationRow,
    FidelityLadderDecisionRow,
    Phase14ExpectedValue,
    RouteRuntimeRow,
    ShellBiasDiagnosisRow,
    SolidTubeProbeRow,
    TubeSolidMeshSpec,
    TubeShellMeshSpec,
    _build_parser,
    build_structured_tube_shell_mesh,
    build_structured_tube_solid_mesh,
    classify_b2_shell_agreement,
    classify_b5_shell_torsion_status,
    classify_constant_tube_status,
    classify_shell_bias_diagnosis,
    _distributed_vertical_loads_by_span_tributary,
    estimate_ring_twist_rad,
    tube_bending_tip_load_delta,
    tube_bending_uniform_load_delta,
    tip_torque_loads_for_ring,
    tube_torsion_theta,
    write_runtime_audit_artifacts,
    write_shell_bias_diagnosis_artifacts,
    write_solid_tube_probe_artifacts,
    write_apdl_windows_package,
    write_best_route_check_artifacts,
    write_fidelity_ladder_decision_artifacts,
    write_fidelity_ladder_final_report,
    write_b5_shell_torsion_hardening_csv,
    write_b5_shell_torsion_hardening_markdown,
    write_b2_tapered_shell_hardening_csv,
    write_b2_tapered_shell_hardening_markdown,
    write_constant_tube_markdown,
    write_constant_tube_verification_csv,
    write_tube_shell_geo,
)


def test_tube_torsion_theta_matches_closed_form() -> None:
    theta = tube_torsion_theta(
        torque_n_m=100.0,
        span_m=10.0,
        young_pa=135.0e9,
        poisson_ratio=0.3,
        outer_radius_m=0.03,
        thickness_m=0.0015,
    )

    expected = 100.0 * 10.0 / (
        (135.0e9 / (2.0 * 1.3))
        * float(tube_J(np.asarray([0.03]), np.asarray([0.0015]))[0])
    )
    assert theta == expected


def test_tube_bending_helpers_match_closed_form() -> None:
    tip = tube_bending_tip_load_delta(
        force_n=-80.0,
        span_m=10.0,
        young_pa=135.0e9,
        outer_radius_m=0.03,
        thickness_m=0.0015,
    )
    uniform = tube_bending_uniform_load_delta(
        q_n_per_m=-8.0,
        span_m=10.0,
        young_pa=135.0e9,
        outer_radius_m=0.03,
        thickness_m=0.0015,
    )
    second_moment = np.pi / 4.0 * (0.03**4 - (0.03 - 0.0015) ** 4)

    assert tip == -80.0 * 10.0**3 / (3.0 * 135.0e9 * second_moment)
    assert uniform == -8.0 * 10.0**4 / (8.0 * 135.0e9 * second_moment)


def test_build_structured_tube_shell_mesh_builds_quad_shell_elements() -> None:
    spec = TubeShellMeshSpec(
        name="constant_quad",
        span_m=2.0,
        root_outer_radius_m=0.03,
        tip_outer_radius_m=0.03,
        n_span=3,
        n_circumference=8,
        mesh_size_m=0.2,
    )

    nodes, elements = build_structured_tube_shell_mesh(spec)

    assert nodes.shape == (32, 4)
    assert len(elements) == 24
    assert {element.element_type for element in elements} == {"S4"}
    assert elements[0].node_ids == (1, 9, 10, 2)
    assert elements[-1].node_ids == (24, 32, 25, 17)


def test_constant_tube_verification_row_has_required_schema() -> None:
    fields = set(ConstantTubeVerificationRow.__dataclass_fields__)

    assert {
        "case_id",
        "mesh_id",
        "n_span",
        "n_circumference",
        "element_count",
        "load_or_torque",
        "theory_value",
        "fem_value",
        "error_pct",
        "reaction_or_moment_residual",
        "mesh_delta_vs_previous_pct",
        "mesh_delta_vs_finest_pct",
        "max_von_mises_pa",
        "status",
        "engineering_note",
    }.issubset(fields)


def test_build_parser_accepts_hardening_task() -> None:
    args = _build_parser().parse_args(["--task", "hardening"])

    assert args.task == "hardening"


def test_build_parser_accepts_fidelity_ladder_task() -> None:
    args = _build_parser().parse_args(["--task", "fidelity-ladder"])

    assert args.task == "fidelity-ladder"


def test_write_runtime_audit_artifacts(tmp_path: Path) -> None:
    runtime_rows = [
        RouteRuntimeRow(
            route_id="beam_parity",
            route_label="beam parity run",
            runtime_s=2.9,
            status="PASS",
            output_artifact="beam/comparison_summary.md",
            engineering_note="B1/B3 remain the daily beam gate.",
        ),
        RouteRuntimeRow(
            route_id="structured_shell_constant",
            route_label="structured shell constant tube run",
            runtime_s=11.2,
            status="WARN",
            output_artifact="maclocal_fem_hardening/constant_tube_bending.csv",
            engineering_note="Stable but warning-grade stiffness bias.",
        ),
    ]
    bending_rows = [
        ConstantTubeVerificationRow(
            case_id="A1_constant_tube_tip_load",
            mesh_id="fine",
            n_span=96,
            n_circumference=96,
            element_count=9216,
            load_or_torque=-80.0,
            theory_value=-0.9825,
            fem_value=-0.9113,
            error_pct=7.25,
            reaction_or_moment_residual=0.0,
            mesh_delta_vs_previous_pct=0.12,
            mesh_delta_vs_finest_pct=0.0,
            max_von_mises_pa=1.98e8,
            status="WARN",
            engineering_note="outer-surface radius route",
        )
    ]
    torsion_rows = [
        ConstantTubeVerificationRow(
            case_id="A3_constant_tube_tip_torque",
            mesh_id="fine",
            n_span=96,
            n_circumference=96,
            element_count=9216,
            load_or_torque=100.0,
            theory_value=0.04679,
            fem_value=0.04341,
            error_pct=7.24,
            reaction_or_moment_residual=0.0,
            mesh_delta_vs_previous_pct=0.18,
            mesh_delta_vs_finest_pct=0.0,
            max_von_mises_pa=2.09e7,
            status="WARN",
            engineering_note="outer-surface radius route",
        )
    ]
    b2_rows = [
        B2TaperedShellHardeningRow(
            variant="structured_s4_root_ring_tributary_load",
            mesh_id="b2_structured_s4_fine",
            n_span=96,
            n_circumference=96,
            element_count=9216,
            tip_uz_avg_m=-0.17179,
            tip_uz_min_m=-0.17179,
            tip_uz_max_m=-0.17179,
            root_reaction_fz_n=80.0,
            reaction_residual_n=0.0,
            max_von_mises_pa=4.7e7,
            error_vs_internal_pct=4.42,
            error_vs_b32r_pipe_pct=7.07,
            mesh_delta_vs_previous_pct=0.41,
            mesh_delta_vs_finest_pct=0.0,
            status="PASS",
            engineering_note="structured S4 tapered route",
        )
    ]
    b5_rows = [
        B5ShellTorsionHardeningRow(
            variant="structured_s4_end_ring_tangential_root_ring",
            mesh_id="fine",
            n_span=96,
            n_circumference=96,
            applied_torque_n_m=100.0,
            recovered_torque_n_m=100.0,
            theory_theta_rad=0.04679,
            shell_theta_rad=0.04341,
            theta_error_pct=7.24,
            mesh_delta_vs_previous_pct=0.18,
            max_von_mises_pa=2.09e7,
            status="PASS",
            engineering_note="structured S4 torsion route",
        )
    ]

    artifacts = write_runtime_audit_artifacts(
        tmp_path,
        runtime_rows=runtime_rows,
        bending_rows=bending_rows,
        torsion_rows=torsion_rows,
        b2_rows=b2_rows,
        b5_rows=b5_rows,
    )

    csv_rows = list(csv.DictReader(artifacts["runtime_summary_csv"].read_text().splitlines()))
    assert csv_rows[0]["route_id"] == "beam_parity"
    assert csv_rows[1]["runtime_s"] == "11.2"
    md_text = artifacts["current_route_audit_md"].read_text(encoding="utf-8")
    assert "# Phase 14 Current FEM Route Audit" in md_text
    assert "structured shell constant tube run" in md_text
    assert "Constant tube shell bending" in md_text
    assert "B2 structured S4 tapered" in md_text


def test_shell_bias_diagnosis_row_has_required_schema() -> None:
    fields = set(ShellBiasDiagnosisRow.__dataclass_fields__)

    assert {
        "variant",
        "case_type",
        "element_type",
        "radius_convention",
        "root_bc",
        "load_method",
        "n_span",
        "n_circumference",
        "element_count",
        "theory_value",
        "fem_value",
        "error_pct",
        "mesh_delta_pct",
        "runtime_s",
        "status",
        "engineering_note",
    }.issubset(fields)


def test_classify_shell_bias_diagnosis_uses_bending_and_torsion() -> None:
    rows = [
        ShellBiasDiagnosisRow(
            variant="midsurface_reference",
            case_type="constant_tip_load",
            element_type="S4",
            radius_convention="midsurface",
            root_bc="root_ring",
            load_method="tip_ring",
            n_span=96,
            n_circumference=96,
            element_count=9216,
            theory_value=-1.0,
            fem_value=-0.98,
            error_pct=2.0,
            mesh_delta_pct=0.2,
            runtime_s=1.0,
            status="PASS",
            engineering_note="bending pass",
        ),
        ShellBiasDiagnosisRow(
            variant="midsurface_reference",
            case_type="constant_tip_torque",
            element_type="S4",
            radius_convention="midsurface",
            root_bc="root_ring",
            load_method="tip_torque_ring",
            n_span=96,
            n_circumference=96,
            element_count=9216,
            theory_value=0.04,
            fem_value=0.039,
            error_pct=2.5,
            mesh_delta_pct=0.2,
            runtime_s=1.0,
            status="PASS",
            engineering_note="torsion pass",
        ),
    ]

    assert classify_shell_bias_diagnosis(rows) == "PASS"
    assert classify_shell_bias_diagnosis([replace(row, error_pct=7.0, status="WARN") for row in rows]) == "WARN"
    assert classify_shell_bias_diagnosis([replace(row, error_pct=15.0, status="FAIL") for row in rows]) == "FAIL"


def test_write_shell_bias_diagnosis_artifacts(tmp_path: Path) -> None:
    rows = [
        ShellBiasDiagnosisRow(
            variant="midsurface_reference",
            case_type="constant_tip_load",
            element_type="S4",
            radius_convention="mesh radius is tube mid-surface",
            root_bc="root ring all DOF",
            load_method="tip ring equal FZ",
            n_span=96,
            n_circumference=96,
            element_count=9216,
            theory_value=-0.9825,
            fem_value=-0.980,
            error_pct=0.25,
            mesh_delta_pct=0.1,
            runtime_s=1.2,
            status="PASS",
            engineering_note="mid-surface convention removes artificial radius offset",
        )
    ]

    artifacts = write_shell_bias_diagnosis_artifacts(
        tmp_path,
        rows=rows,
        exact_i_m4=1.2e-7,
        thin_wall_i_m4=1.18e-7,
        exact_j_m4=2.4e-7,
        thin_wall_j_m4=2.36e-7,
    )

    csv_rows = list(csv.DictReader(artifacts["shell_bias_diagnosis_csv"].read_text().splitlines()))
    assert csv_rows[0]["variant"] == "midsurface_reference"
    md_text = artifacts["shell_bias_diagnosis_md"].read_text(encoding="utf-8")
    assert "# Phase 14 Structured Shell Bias Diagnosis" in md_text
    assert "mid-surface convention" in md_text
    assert "exact tube I" in md_text


def test_build_structured_tube_solid_mesh_builds_hex_elements() -> None:
    spec = TubeSolidMeshSpec(
        name="solid_tiny",
        span_m=2.0,
        outer_radius_m=0.03,
        thickness_m=0.003,
        n_span=2,
        n_circumference=6,
        n_thickness=2,
        element_type="C3D8R",
    )

    nodes, elements = build_structured_tube_solid_mesh(spec)

    assert nodes.shape == (54, 4)
    assert len(elements) == 24
    assert {element.element_type for element in elements} == {"C3D8R"}
    assert len(elements[0].node_ids) == 8
    radii = np.hypot(nodes[:, 1], nodes[:, 3])
    assert abs(float(np.min(radii)) - 0.027) < 1.0e-12
    assert abs(float(np.max(radii)) - 0.03) < 1.0e-12


def test_solid_tube_probe_row_has_required_schema() -> None:
    fields = set(SolidTubeProbeRow.__dataclass_fields__)

    assert {
        "case_id",
        "mesh_id",
        "element_type",
        "n_span",
        "n_circumference",
        "n_thickness",
        "node_count",
        "element_count",
        "theory_value",
        "fem_value",
        "error_pct",
        "reaction_residual",
        "runtime_s",
        "max_von_mises_pa",
        "status",
        "engineering_note",
    }.issubset(fields)


def test_write_solid_tube_probe_artifacts(tmp_path: Path) -> None:
    rows = [
        SolidTubeProbeRow(
            case_id="C1_solid_constant_tube_tip_load",
            mesh_id="medium",
            element_type="C3D8R",
            n_span=32,
            n_circumference=32,
            n_thickness=2,
            node_count=3267,
            element_count=2048,
            theory_value=-0.9825,
            fem_value=-0.90,
            error_pct=8.4,
            reaction_residual=0.0,
            runtime_s=3.2,
            max_von_mises_pa=1.0e8,
            status="WARN",
            engineering_note="solid route runs but is not better than mid-surface shell",
        )
    ]

    artifacts = write_solid_tube_probe_artifacts(tmp_path, rows=rows)

    csv_rows = list(csv.DictReader(artifacts["solid_tube_probe_csv"].read_text().splitlines()))
    assert csv_rows[0]["element_type"] == "C3D8R"
    md_text = artifacts["solid_tube_probe_md"].read_text(encoding="utf-8")
    assert "# Phase 14 Solid Tube FEM Probe" in md_text
    assert "not automatically higher fidelity" in md_text


def test_fidelity_ladder_decision_row_has_required_schema() -> None:
    fields = set(FidelityLadderDecisionRow.__dataclass_fields__)

    assert {
        "route",
        "global_bending_accuracy",
        "global_torsion_accuracy",
        "reaction_closure",
        "runtime",
        "mesh_convergence_behavior",
        "thin_wall_suitability",
        "local_stress_usefulness",
        "buckling_usefulness",
        "implementation_maturity",
        "mac_local_automation_readiness",
        "recommended_role",
    }.issubset(fields)


def test_write_fidelity_ladder_decision_artifacts(tmp_path: Path) -> None:
    rows = [
        FidelityLadderDecisionRow(
            route="structured shell current best",
            global_bending_accuracy="0.06% constant tip-load error",
            global_torsion_accuracy="0.07% constant torsion error",
            reaction_closure="closed",
            runtime="seconds",
            mesh_convergence_behavior="stable",
            thin_wall_suitability="best current Mac-local thin-wall route",
            local_stress_usefulness="diagnostic",
            buckling_usefulness="future diagnostic",
            implementation_maturity="automated",
            mac_local_automation_readiness="ready",
            recommended_role="design diagnostic",
        )
    ]

    artifacts = write_fidelity_ladder_decision_artifacts(
        tmp_path,
        rows=rows,
        decision_summary="Use the simplest model that is accurate enough.",
    )

    csv_rows = list(csv.DictReader(artifacts["fidelity_ladder_comparison_csv"].read_text().splitlines()))
    assert csv_rows[0]["route"] == "structured shell current best"
    md_text = artifacts["fidelity_ladder_decision_md"].read_text(encoding="utf-8")
    assert "# Phase 14 FEM Fidelity Ladder Decision" in md_text
    assert "simplest model" in md_text
    assert "design diagnostic" in md_text


def test_best_route_check_row_has_required_schema() -> None:
    fields = set(BestRouteCheckRow.__dataclass_fields__)

    assert {
        "case_id",
        "route",
        "metric",
        "reference_source",
        "reference_value",
        "fem_value",
        "error_pct",
        "mesh_id",
        "element_count",
        "runtime_s",
        "status",
        "engineering_note",
    }.issubset(fields)


def test_write_best_route_and_final_report_artifacts(tmp_path: Path) -> None:
    rows = [
        BestRouteCheckRow(
            case_id="B2_TAPERED_TUBE",
            route="best_midsurface_s4_shell",
            metric="tip_uz_m",
            reference_source="internal_tubing_beam",
            reference_value=-0.1797,
            fem_value=-0.184,
            error_pct=2.4,
            mesh_id="b2_best_midsurface_s4_fine",
            element_count=9216,
            runtime_s=1.5,
            status="PASS",
            engineering_note="within 5% of internal tubing model",
        ),
        BestRouteCheckRow(
            case_id="B5_SINGLE_TORSION",
            route="best_midsurface_s4_shell",
            metric="theta_rad",
            reference_source="closed_form_TL_over_GJ",
            reference_value=0.04679,
            fem_value=0.04682,
            error_pct=0.07,
            mesh_id="b5_best_midsurface_s4_fine",
            element_count=9216,
            runtime_s=1.4,
            status="PASS",
            engineering_note="within 5% of torsion theory",
        ),
    ]

    best_artifacts = write_best_route_check_artifacts(tmp_path, rows=rows)
    report_path = write_fidelity_ladder_final_report(
        tmp_path,
        best_route_rows=rows,
        decision_summary="Corrected shell is the best current Mac-local diagnostic.",
        apdl_runner="output/phase14_dual_beam_calibration/apdl_windows_package/run_all_phase14.mac",
    )

    csv_rows = list(csv.DictReader(best_artifacts["b2_b5_best_route_check_csv"].read_text().splitlines()))
    assert csv_rows[0]["case_id"] == "B2_TAPERED_TUBE"
    assert "B2 tapered tube" in best_artifacts["b2_b5_best_route_check_md"].read_text(encoding="utf-8")
    report_text = report_path.read_text(encoding="utf-8")
    assert "One-paragraph answer" in report_text
    assert "APDL" in report_text


def test_write_constant_tube_artifacts_include_required_columns(tmp_path: Path) -> None:
    rows = [
        ConstantTubeVerificationRow(
            case_id="A1_constant_tube_tip_load",
            mesh_id="coarse",
            n_span=32,
            n_circumference=32,
            element_count=1024,
            load_or_torque=-80.0,
            theory_value=-0.1,
            fem_value=-0.102,
            error_pct=2.0,
            reaction_or_moment_residual=0.0,
            mesh_delta_vs_previous_pct=None,
            mesh_delta_vs_finest_pct=1.0,
            max_von_mises_pa=1000.0,
            status="PASS",
            engineering_note="closed form agreement",
        )
    ]

    csv_path = tmp_path / "constant_tube_bending.csv"
    md_path = tmp_path / "constant_tube_bending.md"
    write_constant_tube_verification_csv(csv_path, rows)
    write_constant_tube_markdown(
        md_path,
        title="Constant Tube Bending",
        rows=rows,
        engineering_summary="Daily gate candidate.",
    )

    csv_rows = list(csv.DictReader(csv_path.read_text().splitlines()))
    assert csv_rows[0]["case_id"] == "A1_constant_tube_tip_load"
    assert csv_rows[0]["mesh_delta_vs_finest_pct"] == "1.0"
    md_text = md_path.read_text(encoding="utf-8")
    assert "# Constant Tube Bending" in md_text
    assert "reaction_or_moment_residual" in md_text
    assert "Daily gate candidate." in md_text


def test_b5_shell_torsion_hardening_row_has_required_schema() -> None:
    fields = set(B5ShellTorsionHardeningRow.__dataclass_fields__)

    assert {
        "variant",
        "mesh_id",
        "n_span",
        "n_circumference",
        "applied_torque_n_m",
        "recovered_torque_n_m",
        "theory_theta_rad",
        "shell_theta_rad",
        "theta_error_pct",
        "mesh_delta_vs_previous_pct",
        "max_von_mises_pa",
        "status",
        "engineering_note",
    }.issubset(fields)


def test_classify_b5_shell_torsion_status_uses_theta_convergence_and_torque() -> None:
    assert classify_b5_shell_torsion_status(
        applied_torque_n_m=100.0,
        recovered_torque_n_m=100.001,
        theta_error_pct=7.0,
        mesh_delta_vs_previous_pct=1.5,
    ) == "PASS"
    assert classify_b5_shell_torsion_status(
        applied_torque_n_m=100.0,
        recovered_torque_n_m=100.001,
        theta_error_pct=18.0,
        mesh_delta_vs_previous_pct=1.5,
    ) == "WARN"
    assert classify_b5_shell_torsion_status(
        applied_torque_n_m=100.0,
        recovered_torque_n_m=100.001,
        theta_error_pct=76.0,
        mesh_delta_vs_previous_pct=1.5,
    ) == "FAIL"
    assert classify_b5_shell_torsion_status(
        applied_torque_n_m=100.0,
        recovered_torque_n_m=80.0,
        theta_error_pct=7.0,
        mesh_delta_vs_previous_pct=1.5,
    ) == "FAIL"


def test_write_b5_shell_torsion_hardening_artifacts(tmp_path: Path) -> None:
    rows = [
        B5ShellTorsionHardeningRow(
            variant="structured_s4_ring_torque",
            mesh_id="fine",
            n_span=96,
            n_circumference=96,
            applied_torque_n_m=100.0,
            recovered_torque_n_m=100.0,
            theory_theta_rad=0.046792,
            shell_theta_rad=0.043406,
            theta_error_pct=7.24,
            mesh_delta_vs_previous_pct=0.18,
            max_von_mises_pa=2.1e7,
            status="PASS",
            engineering_note="ring twist",
        )
    ]

    csv_path = tmp_path / "b5_shell_torsion_hardening.csv"
    md_path = tmp_path / "b5_shell_torsion_hardening.md"
    write_b5_shell_torsion_hardening_csv(csv_path, rows)
    write_b5_shell_torsion_hardening_markdown(
        md_path,
        rows=rows,
        engineering_summary="Ring-based torsion route improved the old shell result.",
    )

    csv_rows = list(csv.DictReader(csv_path.read_text().splitlines()))
    assert csv_rows[0]["variant"] == "structured_s4_ring_torque"
    assert csv_rows[0]["theta_error_pct"] == "7.24"
    md_text = md_path.read_text(encoding="utf-8")
    assert "# B5 Shell Torsion Hardening" in md_text
    assert "recovered_torque_n_m" in md_text
    assert "Ring-based torsion route improved" in md_text


def test_b2_tapered_shell_hardening_row_has_required_schema() -> None:
    fields = set(B2TaperedShellHardeningRow.__dataclass_fields__)

    assert {
        "variant",
        "mesh_id",
        "n_span",
        "n_circumference",
        "element_count",
        "tip_uz_avg_m",
        "tip_uz_min_m",
        "tip_uz_max_m",
        "root_reaction_fz_n",
        "reaction_residual_n",
        "max_von_mises_pa",
        "error_vs_internal_pct",
        "error_vs_b32r_pipe_pct",
        "mesh_delta_vs_previous_pct",
        "mesh_delta_vs_finest_pct",
        "status",
        "engineering_note",
    }.issubset(fields)


def test_distributed_vertical_loads_by_span_tributary_preserve_total_load() -> None:
    spec = TubeShellMeshSpec(
        name="load_check",
        span_m=3.0,
        root_outer_radius_m=0.03,
        tip_outer_radius_m=0.02,
        n_span=3,
        n_circumference=8,
        mesh_size_m=0.2,
    )
    nodes, _elements = build_structured_tube_shell_mesh(spec)
    root_nodes = set(int(row[0]) for row in nodes if row[2] == 0.0)

    loads = _distributed_vertical_loads_by_span_tributary(
        nodes=nodes,
        root_nodes=root_nodes,
        total_fz_n=-80.0,
    )

    assert abs(sum(value for _node_id, dof, value in loads if dof == 3) + 80.0) < 1.0e-10
    assert all(node_id not in root_nodes for node_id, _dof, _value in loads)


def test_write_b2_tapered_shell_hardening_artifacts(tmp_path: Path) -> None:
    rows = [
        B2TaperedShellHardeningRow(
            variant="structured_s4_root_ring_tributary_load",
            mesh_id="fine",
            n_span=96,
            n_circumference=96,
            element_count=9216,
            tip_uz_avg_m=-0.158,
            tip_uz_min_m=-0.159,
            tip_uz_max_m=-0.157,
            root_reaction_fz_n=80.0,
            reaction_residual_n=0.0,
            max_von_mises_pa=2.0e8,
            error_vs_internal_pct=12.0,
            error_vs_b32r_pipe_pct=1.5,
            mesh_delta_vs_previous_pct=1.0,
            mesh_delta_vs_finest_pct=0.0,
            status="PASS",
            engineering_note="structured route",
        )
    ]

    csv_path = tmp_path / "b2_tapered_shell_hardening.csv"
    md_path = tmp_path / "b2_tapered_shell_hardening.md"
    write_b2_tapered_shell_hardening_csv(csv_path, rows)
    write_b2_tapered_shell_hardening_markdown(md_path, rows)

    csv_rows = list(csv.DictReader(csv_path.read_text().splitlines()))
    assert csv_rows[0]["tip_uz_avg_m"] == "-0.158"
    md_text = md_path.read_text(encoding="utf-8")
    assert "# B2 Tapered Shell Hardening" in md_text
    assert "tip_uz_min_m" in md_text
    assert "structured route" in md_text


def test_classify_constant_tube_status_uses_error_convergence_and_equilibrium() -> None:
    assert classify_constant_tube_status(
        theory_value=1.0,
        fem_value=1.03,
        error_pct=3.0,
        mesh_delta_vs_finest_pct=4.0,
        reaction_or_moment_residual=1.0e-5,
        load_or_torque=100.0,
    ) == "PASS"
    assert classify_constant_tube_status(
        theory_value=1.0,
        fem_value=1.08,
        error_pct=8.0,
        mesh_delta_vs_finest_pct=12.0,
        reaction_or_moment_residual=1.0e-5,
        load_or_torque=100.0,
    ) == "WARN"
    assert classify_constant_tube_status(
        theory_value=1.0,
        fem_value=-0.2,
        error_pct=120.0,
        mesh_delta_vs_finest_pct=50.0,
        reaction_or_moment_residual=20.0,
        load_or_torque=100.0,
    ) == "FAIL"


def test_tip_torque_loads_for_ring_are_self_equilibrated() -> None:
    theta = np.linspace(0.0, 2.0 * np.pi, 16, endpoint=False)
    nodes = np.column_stack(
        (
            np.arange(1, theta.size + 1, dtype=float),
            0.03 * np.cos(theta),
            np.full(theta.size, 10.0),
            0.03 * np.sin(theta),
        )
    )

    loads = tip_torque_loads_for_ring(nodes, torque_n_m=42.0)

    assert abs(sum(load.force_x_n for load in loads)) < 1.0e-12
    assert abs(sum(load.force_z_n for load in loads)) < 1.0e-12
    torque = sum(load.z_m * load.force_x_n - load.x_m * load.force_z_n for load in loads)
    assert abs(torque - 42.0) < 1.0e-10


def test_estimate_ring_twist_rad_recovers_known_rotation() -> None:
    angles = np.linspace(0.0, 2.0 * np.pi, 32, endpoint=False)
    radius = 0.03
    theta = 0.017
    nodes = np.column_stack(
        (
            np.arange(1, angles.size + 1, dtype=float),
            radius * np.cos(angles),
            np.full(angles.size, 10.0),
            radius * np.sin(angles),
        )
    )
    deformed_x = nodes[:, 1] * np.cos(theta) + nodes[:, 3] * np.sin(theta)
    deformed_z = -nodes[:, 1] * np.sin(theta) + nodes[:, 3] * np.cos(theta)
    displacements = np.column_stack(
        (
            nodes[:, 0],
            deformed_x - nodes[:, 1],
            np.zeros(angles.size),
            deformed_z - nodes[:, 3],
        )
    )

    assert abs(estimate_ring_twist_rad(nodes=nodes, displacements=displacements) - theta) < 1.0e-8


def test_estimate_ring_twist_rad_ignores_pure_translation() -> None:
    angles = np.linspace(0.0, 2.0 * np.pi, 24, endpoint=False)
    nodes = np.column_stack(
        (
            np.arange(1, angles.size + 1, dtype=float),
            0.03 * np.cos(angles),
            np.full(angles.size, 10.0),
            0.03 * np.sin(angles),
        )
    )
    displacements = np.column_stack(
        (
            nodes[:, 0],
            np.full(angles.size, 0.002),
            np.full(angles.size, -0.001),
            np.full(angles.size, -0.003),
        )
    )

    assert abs(estimate_ring_twist_rad(nodes=nodes, displacements=displacements)) < 1.0e-10


def test_estimate_ring_twist_rad_is_stable_with_small_noise() -> None:
    rng = np.random.default_rng(14)
    angles = np.linspace(0.0, 2.0 * np.pi, 64, endpoint=False)
    radius = 0.03
    theta = 0.012
    nodes = np.column_stack(
        (
            np.arange(1, angles.size + 1, dtype=float),
            radius * np.cos(angles),
            np.full(angles.size, 10.0),
            radius * np.sin(angles),
        )
    )
    deformed_x = nodes[:, 1] * np.cos(theta) + nodes[:, 3] * np.sin(theta)
    deformed_z = -nodes[:, 1] * np.sin(theta) + nodes[:, 3] * np.cos(theta)
    displacements = np.column_stack(
        (
            nodes[:, 0],
            deformed_x - nodes[:, 1] + rng.normal(0.0, 2.0e-6, angles.size),
            rng.normal(0.0, 2.0e-6, angles.size),
            deformed_z - nodes[:, 3] + rng.normal(0.0, 2.0e-6, angles.size),
        )
    )

    assert abs(estimate_ring_twist_rad(nodes=nodes, displacements=displacements) - theta) < 2.5e-4


def test_classify_b2_shell_agreement_chooses_nearest_reference() -> None:
    assert (
        classify_b2_shell_agreement(
            B2ComparisonInputs(
                internal_tip_uz_m=-0.102,
                calculix_pipe_tip_uz_m=-0.086,
                shell_tip_uz_m=-0.099,
            )
        ).closer_to
        == "internal_beam"
    )
    assert (
        classify_b2_shell_agreement(
            B2ComparisonInputs(
                internal_tip_uz_m=-0.102,
                calculix_pipe_tip_uz_m=-0.086,
                shell_tip_uz_m=-0.088,
            )
        ).closer_to
        == "calculix_b32r_pipe"
    )


def test_write_tube_shell_geo_builds_closed_gmsh_surface(tmp_path: Path) -> None:
    spec = TubeShellMeshSpec(
        name="tiny_taper",
        span_m=2.0,
        root_outer_radius_m=0.04,
        tip_outer_radius_m=0.03,
        n_span=2,
        n_circumference=6,
        mesh_size_m=0.2,
    )

    geo_path = write_tube_shell_geo(spec, tmp_path / "tiny_taper.geo")
    text = geo_path.read_text(encoding="utf-8")

    assert text.count("Point(") == 18
    assert text.count("Plane Surface(") == 24
    assert 'Physical Surface("TUBE_SHELL")' in text
    assert "0.04, 0, 0" in text
    assert "0.03, 2, 0" in text


def test_write_apdl_windows_package_creates_nonexpert_runner(tmp_path: Path) -> None:
    material = BeamMaterial(
        name="MAIN",
        young_pa=135.0e9,
        poisson_ratio=0.3,
        density_kgpm3=1600.0,
    )
    expected_values = [
        Phase14ExpectedValue(
            case_id="B2_TAPERED_TUBE",
            metric="tip_uz_m",
            value=-0.1,
            source="mac_internal_beam",
            tolerance_pct=10.0,
            note="Regression reference for APDL handoff.",
        ),
        Phase14ExpectedValue(
            case_id="B5_SINGLE_TORSION",
            metric="theta_rad",
            value=0.01,
            source="theta_equals_tl_over_gj",
            tolerance_pct=10.0,
            note="Closed-form torsion reference.",
        ),
    ]

    package = write_apdl_windows_package(
        output_dir=tmp_path / "apdl_windows_package",
        material=material,
        expected_values=expected_values,
    )

    required = {
        "run_all_phase14.mac",
        "phase14_b2_tapered_tube.mac",
        "phase14_b5_single_torsion.mac",
        "phase14_b5_dual_direct_my.mac",
        "phase14_b5_dual_force_couple.mac",
        "README_windows_run.md",
        "expected_values.csv",
    }
    assert required.issubset({path.name for path in package.files})

    runner = (package.directory / "run_all_phase14.mac").read_text(encoding="utf-8")
    assert "phase14_apdl_results,csv" in runner
    assert "*VWRITE,H1,H2,H3,H4,H5,H6,H7,H8,H9,H10,H11,H12,H13,H14,H15,H16" in runner
    assert "/INPUT,phase14_b2_tapered_tube,mac" in runner
    assert "/INPUT,phase14_b5_single_torsion,mac" in runner
    assert "/INPUT,phase14_b5_dual_direct_my,mac" in runner
    assert "/INPUT,phase14_b5_dual_force_couple,mac" in runner

    b2_deck = (package.directory / "phase14_b2_tapered_tube.mac").read_text(encoding="utf-8")
    b5_deck = (package.directory / "phase14_b5_single_torsion.mac").read_text(encoding="utf-8")
    dual_deck = (package.directory / "phase14_b5_dual_force_couple.mac").read_text(encoding="utf-8")
    assert "BEAM188" in b2_deck
    assert "CTUBE" in b2_deck
    assert "*CFOPEN,phase14_apdl_results,csv,,APPEND" in b2_deck
    assert "ETABLE,VM_I,SMISC,31" in b2_deck
    assert "ETABLE,SEQV,S,EQV" not in b2_deck
    assert "CASEID='B2_TAPER'" in b2_deck
    assert "CASEID='B5_TORS'" in b5_deck
    assert "MY" in b5_deck
    assert "CASEID='B5_COUP'" in dual_deck
    assert "ROUTE='DUAL_FC'" in dual_deck
    assert "N,103" in dual_deck
    assert "K,103" not in dual_deck
    assert "E,102,103" in dual_deck
    assert "CE,NEXT,0,3,UX,1,103,UX,-1" in dual_deck
    assert "ROOT_TORQUE=MAIN_ROOT_MY+REAR_ROOT_MY-3.500000000e-01*REAR_ROOT_RFZ" in dual_deck
    assert "*VWRITE,CASEID,ROUTE,STATUS,MAIN_TIP_UZ,0,TOTAL_ROOT_FZ,ROOT_TORQUE,MAXSEQV,NOTE" in dual_deck

    readme = (package.directory / "README_windows_run.md").read_text(encoding="utf-8")
    assert "set working directory" in readme.lower()
    assert "run_all_phase14.mac" in readme
    assert "phase14_apdl_results.csv" in readme

    rows = list(csv.DictReader((package.directory / "expected_values.csv").read_text().splitlines()))
    assert {row["case_id"] for row in rows} == {"B2_TAPERED_TUBE", "B5_SINGLE_TORSION"}
