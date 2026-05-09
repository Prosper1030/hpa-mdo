from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


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


def test_fem_calibration_package_writes_feedback_and_calibrated_search(tmp_path: Path) -> None:
    fem = _load_module(_FEM_SCRIPT_PATH, "current_pathfinder_rib_torsion_fem_calibration")

    paths = fem.write_rib_torsion_fem_calibration_package(
        search_summary=_search_summary(),
        output_dir=tmp_path,
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
        calibrated_search_output_dir=tmp_path / "calibrated_search",
        run_calculix_smoke=False,
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
    assert selected["fast_vs_fem_bias"] == "fast_optimistic"
    assert selected["twist_factor"] > 1.0
    assert selected["bounded_twist_after_calibration_deg"] < 3.0
    assert selected["local_load_path_risk"] in {"watch", "elevated_watch"}

    foam = rows["lightweight_foam_core_reference"]
    assert foam["structural_credit_policy"] == "shape_core_reference_only"
    assert foam["candidate_disposition"] == "downgrade_reference_only"

    update = json.loads(paths["calibration_update_json"].read_text(encoding="utf-8"))
    assert update["status"] == "calibration_update_ready_for_fast_loop"
    assert update["claim_boundary"] == "calibration_correction_for_search_only_not_final_FEM_truth"
    assert update["family_correction_factors"]["eps_balsa_cap_hybrid_10mm"]["twist_factor"] > 1.0

    calibrated = json.loads(paths["calibrated_search_summary_json"].read_text(encoding="utf-8"))
    assert calibrated["selected_fast_candidate"]["fast_model_bounded_twist_deg"] < 3.0
    assert calibrated["applied_calibration_update"]["schema_version"] == (
        "rib_torsion_fast_model_calibration_update_v1"
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
    )

    payload = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
    smoke = payload["calculix_smoke"]
    assert smoke["status"] == "not_requested"
    assert Path(smoke["deck_path"]).exists()
    assert "RIB_TORSION_EQUIV" in Path(smoke["deck_path"]).read_text(encoding="utf-8")

    report = paths["report_md"].read_text(encoding="utf-8")
    assert "not final sign-off" in report
    assert "bond/collar/tube-wall" in report
