from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys



_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "current_pathfinder_rib_local_detail_margin_run.py"
_FREEZE_JSON = (
    _REPO_ROOT / "output" / "current_pathfinder_rib_local_detail_geometry_freeze"
    / "geometry_allowable_freeze.json"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "current_pathfinder_rib_local_detail_margin_run", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run(tmp_path: Path) -> dict:
    mod = _load_module()
    paths = mod.write_margin_run_package(
        output_dir=tmp_path / "output",
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
    )
    return json.loads(paths["report_json"].read_text()), paths


def test_all_outputs_written(tmp_path: Path) -> None:
    _, paths = _run(tmp_path)
    for key, p in paths.items():
        assert p.exists(), f"missing output: {key}"


def test_schema_version(tmp_path: Path) -> None:
    mod = _load_module()
    report, _ = _run(tmp_path)
    assert report["schema_version"] == mod.SCHEMA_VERSION


def test_c04_is_critical_blocker(tmp_path: Path) -> None:
    report, _ = _run(tmp_path)
    assert report["all_pass"] is False, (
        "Step 2 eccentric moment model should reveal C04 peel concern; "
        "all_pass=True would mean the critical finding was missed."
    )
    assert report["worst_coupon"] == "C04", (
        f"C04 bond peel should be identified as worst coupon; got {report['worst_coupon']}"
    )
    assert report["worst_margin"] < 0, (
        "C04 margin should be negative per eccentric moment model"
    )


def test_verdict_reflects_concern(tmp_path: Path) -> None:
    report, _ = _run(tmp_path)
    assert "concern" in report["verdict"], (
        f"Verdict should reflect C04 concern; got {report['verdict']}"
    )


def test_c07_min_viable_prestrain_derived(tmp_path: Path) -> None:
    report, _ = _run(tmp_path)
    mvp = report["c07_min_viable_prestrain_pct"]
    target = report["c07_process_target_prestrain_pct"]
    assert mvp is not None, "min viable pre-strain should be found in sweep"
    assert target is not None
    assert target >= mvp, "process target must be >= min viable"


def test_sag_sweep_csv_has_pass_and_fail_rows(tmp_path: Path) -> None:
    _, paths = _run(tmp_path)
    import csv as _csv
    with open(paths["sag_sweep_csv"], newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    passing = [r for r in rows if r["passes"] == "True"]
    failing = [r for r in rows if r["passes"] == "False"]
    assert len(passing) > 0, "no passing pre-strain rows in sweep"
    assert len(failing) > 0, "no failing pre-strain rows in sweep (expected low end to fail)"


def test_c04_peel_eccentric_margin_negative_flags_concern(tmp_path: Path) -> None:
    report, _ = _run(tmp_path)
    margin = report["c04_eccentric_moment_margin"]
    assert margin < 0.5, (
        "C04 eccentric moment margin should be < 0.5 to flag the peel concern; "
        "if it's large the eccentricity model may not be applied correctly."
    )


def test_c04_eccentric_margin_differs_from_step1(tmp_path: Path) -> None:
    report, _ = _run(tmp_path)
    step1_margin = 2.57
    step2_margin = report["c04_eccentric_moment_margin"]
    assert abs(step2_margin - step1_margin) > 0.01, (
        "Step 2 C04 margin should differ from step-1 fraction model"
    )


def test_c02_scf_reduces_margin_vs_uniform(tmp_path: Path) -> None:
    mod = _load_module()
    freeze = json.loads(_FREEZE_JSON.read_text())
    result = mod._run_all_margins(freeze)
    c02 = result["C02_C03_bond_shear"]
    assert c02["scf_applied"] > 1.0, "SCF should be > 1"
    assert c02["C02_margin"] < c02["avg_shear_main_pa"] * 0 + 999999


def test_run_json_all_coupons_present(tmp_path: Path) -> None:
    _, paths = _run(tmp_path)
    run = json.loads(paths["run_json"].read_text())
    for key in ("C01_cap_shear", "C02_C03_bond_shear", "C04_bond_peel",
                "C05_collar_bearing", "C06_tube_crush", "C07_skin_sag"):
        assert key in run, f"missing result key: {key}"


def test_margins_csv_rows(tmp_path: Path) -> None:
    _, paths = _run(tmp_path)
    import csv as _csv
    with open(paths["margins_csv"], newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    coupons = {r["coupon"] for r in rows}
    for c in ("C01", "C02", "C03", "C04", "C05", "C06_main", "C06_rear", "C07"):
        assert c in coupons, f"coupon {c} missing from margins CSV"


def test_report_md_contains_sweep_table(tmp_path: Path) -> None:
    _, paths = _run(tmp_path)
    md = paths["report_md"].read_text()
    assert "pre-strain" in md.lower()
    assert "min_viable_prestrain" in md or "Minimum viable" in md


def test_c07_nonlinear_sag_less_than_linear(tmp_path: Path) -> None:
    mod = _load_module()
    freeze = json.loads(_FREEZE_JSON.read_text())
    result = mod._run_all_margins(freeze)
    c07 = result["C07_skin_sag"]
    sag_lin = c07["nominal_sag_m"]
    sag_nl = c07["nominal_sag_nonlinear_m"]
    assert sag_nl < sag_lin, (
        "Nonlinear sag must be smaller than linear (geometric strain stiffens membrane)"
    )
    assert c07["nominal_margin_nonlinear"] > c07["nominal_margin"], (
        "Nonlinear margin must be larger than linear margin"
    )


def test_c04_theoretical_min_bondline_derived(tmp_path: Path) -> None:
    report, _ = _run(tmp_path)
    assert "c04_theoretical_min_margin" in report, (
        "Theoretical minimum margin (geometry-only lower bound) must be in report JSON"
    )
    assert report["c04_theoretical_min_margin"] < 0, (
        "Theoretical min margin must be negative: 15 mm bondline is geometrically insufficient"
    )
    assert "c04_min_bondline_for_pass_mm" in report
    assert report["c04_min_bondline_for_pass_mm"] > 50, (
        "Minimum bondline to pass must be >> current 15 mm (expect ~70 mm)"
    )
