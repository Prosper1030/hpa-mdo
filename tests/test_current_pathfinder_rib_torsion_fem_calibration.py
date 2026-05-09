from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_FEM_SCRIPT_PATH = _REPO_ROOT / "scripts" / "current_pathfinder_rib_torsion_fem_calibration.py"
_SEARCH_SCRIPT_PATH = _REPO_ROOT / "scripts" / "current_pathfinder_rib_torsion_design_search.py"
_SEARCH_TEST_PATH = _REPO_ROOT / "tests" / "test_current_pathfinder_rib_torsion_design_search.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _search_summary() -> dict:
    search = _load_module(_SEARCH_SCRIPT_PATH, "current_pathfinder_rib_torsion_design_search")
    fixtures = _load_module(_SEARCH_TEST_PATH, "current_pathfinder_rib_torsion_search_fixtures")
    return search.build_rib_torsion_design_search(
        sensitivity_payload=fixtures._sensitivity_payload(),
        selected_closure_payload=fixtures._selected_closure_payload(),
    )


def _ccx_override_factors() -> dict[str, dict[str, float | str]]:
    return {
        "baseline_balsa_3mm": {"status": "completed", "fem_twist_deg": 3.256324},
        "selected_hybrid_10mm": {"status": "completed", "fem_twist_deg": 2.203642},
        "aggressive_plausible_hybrid": {"status": "completed", "fem_twist_deg": 0.758169},
        "lightweight_foam_core_reference": {"status": "completed", "fem_twist_deg": 3.323776},
    }


def test_fem_calibration_package_writes_feedback_and_calibrated_search(tmp_path: Path) -> None:
    fem = _load_module(_FEM_SCRIPT_PATH, "current_pathfinder_rib_torsion_fem_calibration")

    paths = fem.write_rib_torsion_fem_calibration_package(
        search_summary=_search_summary(),
        output_dir=tmp_path,
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
        calibrated_search_output_dir=tmp_path / "calibrated_search",
        run_calculix_smoke=False,
        run_calculix_local=False,
        calculix_result_overrides=_ccx_override_factors(),
    )

    payload = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
    rows = {row["sample_role"]: row for row in payload["calibration_results"]}
    assert {
        "baseline_balsa_3mm",
        "selected_hybrid_10mm",
        "aggressive_plausible_hybrid",
        "lightweight_foam_core_reference",
    } <= set(rows)

    selected = rows["selected_hybrid_10mm"]
    assert selected["source_case_id"].endswith("manufacturing_relaxed_0p36__carbon_face_collar_y2p328__rear75")
    assert selected["legacy_fast_vs_ccx_factor"] == pytest.approx(1.497702, rel=0.01)
    assert selected["legacy_factor_error_pct"] == pytest.approx(49.770177, rel=0.02)
    assert selected["revised_fast_model_bounded_twist_deg"] == pytest.approx(2.116301, rel=0.01)
    assert selected["revised_factor_error_pct"] < 5.0
    assert selected["local_load_path_risk"] in {"watch", "elevated_watch"}

    foam = rows["lightweight_foam_core_reference"]
    assert foam["structural_credit_policy"] == "shape_core_reference_only"
    assert foam["candidate_disposition"] == "downgrade_reference_only"

    update = json.loads(paths["calibration_update_json"].read_text(encoding="utf-8"))
    assert update["status"] == "fast_physics_alignment_diagnostic_ready"
    assert update["claim_boundary"] == "diagnostic_only_fast_physics_revision_not_final_FEM_truth"
    assert update["structural_candidate_max_revised_factor_error_pct"] < 5.0

    calibrated = json.loads(paths["calibrated_search_summary_json"].read_text(encoding="utf-8"))
    assert calibrated["selected_fast_candidate"]["fast_model_bounded_twist_deg"] < 3.0
    assert calibrated["fast_model_settings"]["physical_model_id"] == (
        "link_limited_torsion_cell_v2"
    )


def test_fem_calibration_package_contains_solver_skeleton_and_trust_boundary(
    tmp_path: Path,
) -> None:
    fem = _load_module(_FEM_SCRIPT_PATH, "current_pathfinder_rib_torsion_fem_calibration")

    paths = fem.write_rib_torsion_fem_calibration_package(
        search_summary=_search_summary(),
        output_dir=tmp_path,
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
        calibrated_search_output_dir=tmp_path / "calibrated_search",
        run_calculix_smoke=False,
        run_calculix_local=False,
        calculix_result_overrides=_ccx_override_factors(),
    )

    payload = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
    smoke = payload["calculix_smoke"]
    assert smoke["status"] == "not_requested"
    assert Path(smoke["deck_path"]).exists()
    assert "RIB_TORSION_EQUIV" in Path(smoke["deck_path"]).read_text(encoding="utf-8")

    report = paths["report_md"].read_text(encoding="utf-8")
    assert "not final sign-off" in report
    assert "bond/collar/tube-wall" in report


def test_calculix_local_frame_decks_materialize_rib_spar_load_path(
    tmp_path: Path,
) -> None:
    fem = _load_module(_FEM_SCRIPT_PATH, "current_pathfinder_rib_torsion_fem_calibration")

    paths = fem.write_rib_torsion_fem_calibration_package(
        search_summary=_search_summary(),
        output_dir=tmp_path,
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
        calibrated_search_output_dir=tmp_path / "calibrated_search",
        run_calculix_smoke=False,
        run_calculix_local=False,
        calculix_result_overrides=_ccx_override_factors(),
    )

    payload = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
    local_cases = payload["calculix_local_fem"]["cases"]
    assert len(local_cases) >= 4
    assert {
        "baseline_balsa_3mm",
        "selected_hybrid_10mm",
        "aggressive_plausible_hybrid",
        "lightweight_foam_core_reference",
    } <= {case["sample_role"] for case in local_cases}

    selected_case = next(
        case for case in local_cases if case["sample_role"] == "selected_hybrid_10mm"
    )
    deck = Path(selected_case["deck_path"]).read_text(encoding="utf-8")
    assert "TYPE=B31, ELSET=MAIN_SPAR" in deck
    assert "TYPE=B31, ELSET=REAR_SPAR" in deck
    assert "TYPE=B31, ELSET=TORQUE_ZONE_COLLAR" in deck
    assert "TYPE=B31, ELSET=RIB_SHEAR_TRANSFER" in deck
    assert "2.327757" in deck
    assert "21.202" in deck
    assert "23.839" in deck
    assert "*NODE PRINT, NSET=LOCAL_BAY_ENDS" in deck
    assert "RF" in deck
    assert "RIB_TORSION_EQUIV" not in deck


def test_ccx_audit_and_revised_physics_alignment_are_primary_feedback(
    tmp_path: Path,
) -> None:
    fem = _load_module(_FEM_SCRIPT_PATH, "current_pathfinder_rib_torsion_fem_calibration")

    paths = fem.write_rib_torsion_fem_calibration_package(
        search_summary=_search_summary(),
        output_dir=tmp_path,
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
        calibrated_search_output_dir=tmp_path / "calibrated_search",
        run_calculix_smoke=False,
        run_calculix_local=False,
        calculix_result_overrides=_ccx_override_factors(),
    )

    payload = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
    audit = payload["ccx_local_model_audit"]
    assert audit["status"] == "ccx_local_model_reasonable_for_fast_physics_alignment"
    assert audit["load_mapping"]["main_rear_force_couple_recovers_torque"] is True
    assert audit["boundary_condition"]["status"] == "local_bay_end_clamp_reasonable_for_screening"

    rows = {row["sample_role"]: row for row in payload["calibration_results"]}
    assert {row["solver"] for row in rows.values()} == {"calculix_ccx_local_frame_fem"}
    assert rows["selected_hybrid_10mm"]["python_local_torsion_link_factor"] > 1.0
    assert rows["selected_hybrid_10mm"]["revised_factor_error_pct"] < 5.0
    assert rows["aggressive_plausible_hybrid"]["revised_factor_error_pct"] < 5.0

    update = json.loads(paths["calibration_update_json"].read_text(encoding="utf-8"))
    assert update["verification_verdict"] == "fast_physical_model_verified_within_5pct"

    calibrated = json.loads(paths["calibrated_search_summary_json"].read_text(encoding="utf-8"))
    assert calibrated["selected_fast_candidate"]["fast_model_bounded_twist_deg"] < 3.0
