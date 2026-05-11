from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "current_pathfinder_rib_collar_joint_design_search.py"
_FREEZE_JSON = (
    _REPO_ROOT / "output" / "current_pathfinder_rib_local_detail_geometry_freeze"
    / "geometry_allowable_freeze.json"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "current_pathfinder_rib_collar_joint_design_search", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run(tmp_path: Path) -> tuple[dict, dict]:
    mod = _load_module()
    paths = mod.write_design_search_package(
        output_dir=tmp_path / "output",
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
    )
    summary = json.loads(paths["report_json"].read_text())
    return summary, paths


def test_all_outputs_written(tmp_path: Path) -> None:
    _, paths = _run(tmp_path)
    for key, p in paths.items():
        assert p.exists(), f"missing output: {key}"


def test_schema_version(tmp_path: Path) -> None:
    mod = _load_module()
    summary, _ = _run(tmp_path)
    assert summary["schema_version"] == mod.SCHEMA_VERSION


def test_baseline_peel_bond_fails(tmp_path: Path) -> None:
    summary, _ = _run(tmp_path)
    assert summary["baseline_margin_conservative"] < 0, (
        "Current 15 mm peel-bond design must fail (conservative model)"
    )
    assert summary["baseline_margin_theoretical_min"] < 0, (
        "Theoretical minimum bound must also fail — geometry is insufficient"
    )


def test_peel_bond_min_viable_bondline_large(tmp_path: Path) -> None:
    summary, _ = _run(tmp_path)
    mvb = summary["peel_bond_min_viable_bondline_mm"]
    assert mvb is not None
    assert mvb > 50, (
        f"Min viable bondline must be >> 15 mm (current); got {mvb} mm"
    )


def test_yoke_max_viable_r_eff_small(tmp_path: Path) -> None:
    summary, _ = _run(tmp_path)
    r_eff = summary["yoke_max_viable_r_eff_mm"]
    assert r_eff is not None
    assert r_eff < 20, (
        f"Viable r_eff must be < 20 mm (much less than current 50 mm); got {r_eff} mm"
    )


def test_friction_clamp_viable_at_mu015(tmp_path: Path) -> None:
    summary, _ = _run(tmp_path)
    min_nc = summary["friction_clamp_min_N_c_at_mu015"]
    assert min_nc is not None
    assert min_nc < 2000, (
        f"Friction clamp should be viable at N_c < 2000 N with mu=0.15; got {min_nc} N"
    )


def test_shear_key_viable_at_small_area(tmp_path: Path) -> None:
    summary, _ = _run(tmp_path)
    area = summary["shear_key_min_total_area_mm2"]
    assert area is not None
    assert area < 500, (
        f"Two shear keys should reach viable area < 500 mm² with tau_d=2 MPa; got {area} mm²"
    )


def test_recommended_design_positive_margin(tmp_path: Path) -> None:
    summary, _ = _run(tmp_path)
    gm = summary["recommended_governing_margin"]
    assert gm > 0, (
        f"Recommended design (split clamp + 3 mm yoke + shear keys) must have positive margin; got {gm}"
    )


def test_margin_functions_physics(tmp_path: Path) -> None:
    mod = _load_module()
    # Doubling clamp force should double friction margin (+ 1) roughly
    m1, _ = mod.margin_friction_clamp(2.384, 0.05, 0.15, 300.0, 0.085)
    m2, _ = mod.margin_friction_clamp(2.384, 0.05, 0.15, 600.0, 0.085)
    assert m2 > m1, "Higher clamp force must give higher margin"
    # Halving r_eff halves the peel demand → better margin
    mg1, _ = mod.margin_load_line_yoke(47.68, 0.010, 0.085, 0.015, 400.0)
    mg2, _ = mod.margin_load_line_yoke(47.68, 0.005, 0.085, 0.015, 400.0)
    assert mg2 > mg1, "Smaller r_eff must give better peel margin"


def test_sweep_csv_contains_all_modes(tmp_path: Path) -> None:
    _, paths = _run(tmp_path)
    import csv as _csv
    with open(paths["sweep_csv"], newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    modes = {r["mode"] for r in rows}
    for m in ("peel_bond", "load_line_yoke", "friction_clamp", "external_shear_key"):
        assert m in modes, f"mode {m} missing from sweep CSV"


def test_report_md_contains_recommendation(tmp_path: Path) -> None:
    _, paths = _run(tmp_path)
    md = paths["report_md"].read_text()
    assert "split clamp" in md.lower() or "clamp" in md.lower()
    assert "shear key" in md.lower()
    assert "yoke" in md.lower() or "r_eff" in md
