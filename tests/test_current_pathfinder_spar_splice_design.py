from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "current_pathfinder_spar_splice_design.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "current_pathfinder_spar_splice_design", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run(tmp_path: Path) -> tuple[dict, dict]:
    mod = _load_module()
    paths = mod.write_splice_design_package(
        output_dir=tmp_path / "output",
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
        joints_csv=tmp_path / "joints.csv",
    )
    return json.loads(paths["report_json"].read_text()), paths


def test_all_outputs_written(tmp_path: Path) -> None:
    _, paths = _run(tmp_path)
    for key, p in paths.items():
        assert p.exists(), f"missing output: {key}"


def test_schema_version(tmp_path: Path) -> None:
    mod = _load_module()
    result, _ = _run(tmp_path)
    assert result["schema_version"] == mod.SCHEMA_VERSION


def test_correct_number_of_joints(tmp_path: Path) -> None:
    result, _ = _run(tmp_path)
    # half span 17.3 m at 3 m panels → 5 splice locations (3,6,9,12,15 m)
    assert result["n_splice_joints_per_half"] == 5
    assert result["n_splice_joints_full_wing"] == 10


def test_all_joints_pass(tmp_path: Path) -> None:
    result, _ = _run(tmp_path)
    assert result["all_pass"] is True, (
        f"All splice joints must pass after auto-sizing; "
        f"worst margin {result['worst_joint_margin']:.3f} at y={result['worst_joint_y_m']} m"
    )


def test_inner_joints_have_larger_margins(tmp_path: Path) -> None:
    result, _ = _run(tmp_path)
    joints = sorted(result["joints"], key=lambda j: j["y_m"])
    # Bending moment decreases outboard → inner joint worst margin
    root_bend = joints[0]["margin_bending"]
    tip_bend = joints[-1]["margin_bending"]
    assert tip_bend > root_bend, "Outboard joint must have larger bending margin"


def test_inboard_joint_needs_thicker_spigot(tmp_path: Path) -> None:
    result, _ = _run(tmp_path)
    joints = sorted(result["joints"], key=lambda j: j["y_m"])
    # y=3m carries the most bending; should require more than 0.8 mm default wall
    inboard_wall = joints[0]["spigot_wall_mm"]
    outboard_wall = joints[-1]["spigot_wall_mm"]
    mod = _load_module()
    default_wall_mm = mod.SPIGOT_WALL_M * 1000
    assert inboard_wall > default_wall_mm, (
        f"Inboard joint (y=3m) must be thicker than {default_wall_mm:.1f} mm; "
        f"got {inboard_wall:.2f} mm"
    )
    assert outboard_wall == default_wall_mm, (
        f"Outboard joint should use default wall {default_wall_mm:.1f} mm"
    )


def test_total_mass_in_expected_range(tmp_path: Path) -> None:
    result, _ = _run(tmp_path)
    kg = result["total_splice_mass_full_wing_kg"]
    assert 2.0 < kg < 6.0, (
        f"Total splice mass should be 2–6 kg (HPA literature range); got {kg:.2f} kg"
    )


def test_torsion_margins_large(tmp_path: Path) -> None:
    result, _ = _run(tmp_path)
    for j in result["joints"]:
        assert j["margin_torsion"] > 5.0, (
            f"Torsion is small vs bearing capacity; margin should be >> 1; "
            f"got {j['margin_torsion']:.2f} at y={j['y_m']} m"
        )


def test_joints_csv_has_all_stations(tmp_path: Path) -> None:
    import csv as _csv
    _, paths = _run(tmp_path)
    with open(paths["joints_csv"], newline="", encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))
    ys = {float(r["y_m"]) for r in rows}
    for expected_y in [3.0, 6.0, 9.0, 12.0, 15.0]:
        assert expected_y in ys, f"splice at y={expected_y} m missing from CSV"


def test_report_md_has_weight_table(tmp_path: Path) -> None:
    _, paths = _run(tmp_path)
    md = paths["report_md"].read_text()
    assert "kg" in md
    assert "splice" in md.lower()
    assert "bending" in md.lower() or "bend" in md.lower()


def test_splice_load_physics(tmp_path: Path) -> None:
    mod = _load_module()
    result, _ = _run(tmp_path)
    joints = sorted(result["joints"], key=lambda j: j["y_m"])
    # Bending moment must decrease from root to tip
    moments = [j["M_nm"] for j in joints]
    assert moments == sorted(moments, reverse=True), (
        "Bending moment must decrease monotonically from inboard to outboard"
    )


def test_spigot_design_functions(tmp_path: Path) -> None:
    mod = _load_module()
    load = mod.SpliceLoad(y_m=3.0, M_nm=4000.0, V_n=500.0, T_nm=30.0)
    spigot = mod._design_spigot(load, spar_od_m=0.100, spar_wall_m=0.001)
    assert spigot.passes, "Spigot should pass after auto-sizing"
    assert spigot.overlap_each_side_m == pytest.approx(0.400, rel=1e-3), (
        "4D overlap: 4 × 0.1 m = 0.4 m"
    )


def test_ferrule_design_functions(tmp_path: Path) -> None:
    mod = _load_module()
    load = mod.SpliceLoad(y_m=3.0, M_nm=4000.0, V_n=500.0, T_nm=30.0)
    ferrule = mod._design_ferrule(load, spar_od_m=0.100)
    assert ferrule.passes
    assert ferrule.margin_torsion > 0


import pytest  # noqa: E402
