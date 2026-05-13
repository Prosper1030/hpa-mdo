from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "run_wo006_su2_baseline_validation.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "run_wo006_su2_baseline_validation", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_authority_table(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "authority_id,engineering_topic,important_number,unit,authority_class,source_lane,allowed_use,disallowed_use,may_appear_in_readme_current_mainline_release_docs,may_be_used_for_procurement,may_affect_baseline_A_reopen,trust_upgrade_requirement",
                "design_gross_mass_98p5,mass / CG / rebalance,98.5,kg,user_authority,latest explicit user instruction,Current design gross mass standard until the user explicitly changes it.,Do not overwrite with P1 aggregate.,yes,no,yes,Only user instruction can replace it.",
                "pipeline_full_span_34p332286,span / half-span / station / rib spacing,34.332286,m,current_pipeline_truth,current pipeline AVL/geometry manifests,Current pipeline full-span evidence unless superseded.,Do not replace with local splice data.,yes,no,yes,Promoted geometry manifest.",
                "pipeline_half_span_17p166143,span / half-span / station / rib spacing,17.166143,m,current_pipeline_truth,current pipeline AVL/geometry manifests,Current pipeline half-span evidence unless superseded.,Do not replace with 16.5 m.,yes,no,yes,Promoted geometry manifest.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_model_inputs(root: Path) -> dict[str, Path]:
    geometry = root / "geometry_manifest.json"
    geometry.write_text(
        json.dumps(
            {
                "case_name": "current_avl_compromise_conservative_closed",
                "Bref": 34.332286,
                "Sref": 33.420059598,
                "Cref": 1.003721543,
                "computed_span_m": 34.332286,
                "loaded_tip_z_m": 2.62856087,
                "source_geometry": "sidecar_avl_loaded_shape",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    selected = root / "tier2_loaded_shape_selected_avl_recheck.csv"
    selected.write_text(
        "\n".join(
            [
                "selected_role,status,alpha_deg,CL,CDi,e_CDi,profile_cd,CD0_total,CD_total,P_crank,P_crank_conservative,actual_query_quality,profile_source_quality",
                "conservative_best,selected_assignment_avl_rerun_ok,0.18015,1.16853,0.0127613,0.9564,0.009368851143241826,0.013258730502038055,0.026020030502038057,174.60027944116567,178.8818396527458,actual_loaded_shape_query_pass,full_polar_mission_grade_candidate",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    closure = root / "aero_structure_closure_summary.csv"
    closure.write_text(
        "\n".join(
            [
                "selected_role,closure_status,selected_profile_cd,selected_P_crank,selected_P_crank_conservative,structure_trust_label",
                "conservative_best,closed_for_screening,0.009368851143241826,174.60027944116567,178.8818396527458,daily_screening_not_final_truth",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {"geometry": geometry, "selected": selected, "closure": closure}


def test_blocked_current_pathfinder_mesh_writes_needs_fix_artifacts(tmp_path: Path) -> None:
    mod = _load_module()
    model = _write_model_inputs(tmp_path)
    authority = tmp_path / "data_authority_table.csv"
    _write_authority_table(authority)
    mesh_probe = tmp_path / "mesh_probe.json"
    mesh_probe.write_text(
        json.dumps(
            {
                "probe_status": "mesh_handoff_blocked",
                "mesh_handoff_status": "missing",
                "source_fixture": "custom_vsp3",
                "source_path": "current_avl_compromise_conservative_closed.vsp3",
                "provider_status": "materialized",
                "marker_summary_status": "component_wall_and_farfield_present",
                "probe_global_min_size": 0.5,
                "probe_global_max_size": 1.5,
                "failure_code": "gmsh_boundary_parametrization_topology",
                "error": "Wrong topology of boundary mesh for parametrization",
                "volume_element_count": 0,
                "blocking_reasons": [
                    "main_wing_real_geometry_mesh_handoff_blocked",
                    "main_wing_real_geometry_boundary_parametrization_topology_failed",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    su2_probe = tmp_path / "su2_probe.json"
    su2_probe.write_text(
        json.dumps(
            {
                "materialization_status": "blocked_before_su2_handoff",
                "source_mesh_handoff_status": "missing",
                "su2_contract": None,
                "volume_element_count": 0,
                "blocking_reasons": [
                    "main_wing_real_mesh_handoff_not_available",
                    "main_wing_real_su2_handoff_not_materialized",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = mod.build_wo006_artifacts(
        output_dir=tmp_path / "wo006",
        authority_table_path=authority,
        geometry_manifest_path=model["geometry"],
        selected_avl_recheck_path=model["selected"],
        closure_summary_path=model["closure"],
        mesh_probe_paths=[mesh_probe],
        su2_handoff_probe_path=su2_probe,
        solver_report_paths=[],
    )

    assert result["verdict"] == "su2_baseline_needs_fix"
    assert result["reopen_risk"]["reopen_trigger_status"] == "not_evaluated"
    assert result["data_authority"]["design_gross_mass_kg"] == 98.5
    assert result["data_authority"]["pipeline_full_span_m"] == 34.332286
    assert result["data_authority"]["pipeline_half_span_m"] == 17.166143

    for name in (
        "su2_baseline_validation.md",
        "su2_case_manifest.json",
        "aero_model_delta_table.csv",
        "baseline_A_reopen_risk_from_su2.json",
    ):
        assert (tmp_path / "wo006" / name).exists()

    rows = list(csv.DictReader((tmp_path / "wo006" / "aero_model_delta_table.csv").open()))
    current = {row["model_or_case"]: row for row in rows}
    assert current["current_pathfinder_su2"]["status"] == "su2_unavailable_mesh_blocked"
    assert current["fourier_avl_trace"]["status"] == "not_promoted_current_trace"
    assert "not release truth" in (tmp_path / "wo006" / "su2_baseline_validation.md").read_text(
        encoding="utf-8"
    )


def test_su2_cd_delta_above_trigger_becomes_reopen_risk(tmp_path: Path) -> None:
    mod = _load_module()
    model = _write_model_inputs(tmp_path)
    authority = tmp_path / "data_authority_table.csv"
    _write_authority_table(authority)
    solver_report = tmp_path / "solver_report.json"
    solver_report.write_text(
        json.dumps(
            {
                "solver_execution_status": "solver_executed",
                "convergence_gate_status": "pass",
                "convergence_comparability_level": "calibration_smoke",
                "run_status": "solver_executed_and_converged",
                "final_iteration": 119,
                "observed_velocity_mps": 6.5,
                "runtime_max_iterations": 120,
                "volume_element_count": 123456,
                "final_coefficients": {"cl": 1.17, "cd": 0.035, "cm": -0.1},
                "blocking_reasons": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = mod.build_wo006_artifacts(
        output_dir=tmp_path / "wo006",
        authority_table_path=authority,
        geometry_manifest_path=model["geometry"],
        selected_avl_recheck_path=model["selected"],
        closure_summary_path=model["closure"],
        mesh_probe_paths=[],
        su2_handoff_probe_path=None,
        solver_report_paths=[solver_report],
    )

    assert result["verdict"] == "su2_baseline_reopen_risk"
    assert result["reopen_risk"]["reopen_trigger_status"] == "exceeded"
    assert result["reopen_risk"]["max_drag_or_power_delta_pct"] > 8.0
