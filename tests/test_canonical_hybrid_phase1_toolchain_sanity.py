from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_canonical_hybrid_phase1_toolchain_sanity.py"
AIRFOIL_SCRIPT_PATH = REPO_ROOT / "scripts" / "run_wo006r8_basic_airfoil_bl_benchmark.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "run_canonical_hybrid_phase1_toolchain_sanity",
        SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_airfoil_module():
    spec = importlib.util.spec_from_file_location(
        "run_wo006r8_basic_airfoil_bl_benchmark",
        AIRFOIL_SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_dat_airfoil_loader_opens_duplicate_te_and_preserves_finite_te_gap(
    tmp_path: Path,
) -> None:
    airfoil = _load_airfoil_module()
    duplicate_te = tmp_path / "duplicate_te.dat"
    duplicate_te.write_text(
        "\n".join(
            [
                "closed",
                "1.0 0.0",
                "0.5 0.1",
                "0.0 0.0",
                "0.5 -0.1",
                "1.0 0.0",
            ]
        ),
        encoding="utf-8",
    )
    finite_te = tmp_path / "finite_te.dat"
    finite_te.write_text(
        "\n".join(
            [
                "finite",
                "1.0 0.01",
                "0.5 0.1",
                "0.0 0.0",
                "0.5 -0.1",
                "1.0 -0.01",
            ]
        ),
        encoding="utf-8",
    )

    closed_points = airfoil.load_dat_airfoil_loop(duplicate_te)
    finite_points = airfoil.load_dat_airfoil_loop(finite_te)

    assert len(closed_points) == 5
    assert closed_points[0] == pytest.approx((1.0, 0.001))
    assert closed_points[-1] == pytest.approx((1.0, -0.001))
    assert len(finite_points) == 5
    assert finite_points[0] == pytest.approx((1.0, 0.01))
    assert finite_points[-1] == pytest.approx((1.0, -0.01))
    assert airfoil.airfoil_loop_diagnostics(closed_points)["trailing_edge_gap_chord"] == pytest.approx(0.002)


def test_phase1_catalog_selects_naca_current_root_and_tip_sections() -> None:
    module = _load_module()

    specs = module.build_phase1_case_specs(module.DEFAULT_SECTION_TABLE_PATH)
    by_id = {spec.case_id: spec for spec in specs}

    assert set(by_id) == {"naca4412_2d", "current_root_dae31", "current_tip_cst"}
    assert by_id["naca4412_2d"].airfoil == "NACA4412"
    assert by_id["current_root_dae31"].section_role == "current_root"
    assert by_id["current_root_dae31"].airfoil_id == "dae31"
    assert by_id["current_tip_cst"].section_role == "current_tip"
    assert by_id["current_tip_cst"].airfoil_id.startswith("cst_tip_")
    assert by_id["current_root_dae31"].chord_m > by_id["current_tip_cst"].chord_m
    assert by_id["current_root_dae31"].airfoil_dat_path.is_file()
    assert by_id["current_tip_cst"].airfoil_dat_path.is_file()


def test_phase1_gate_requires_three_passed_stable_cases() -> None:
    module = _load_module()

    reports = [
        _fake_report("naca4412_2d", "naca4412_2d", 0.021, stable=True),
        _fake_report("current_root_dae31", "current_root", 0.030, stable=True),
        _fake_report("current_tip_cst", "current_tip", 0.040, stable=True),
    ]

    gate = module.evaluate_phase1_toolchain_gate(reports)

    assert gate["status"] == "pass"
    assert gate["release_status"] == "TOOLCHAIN_PASS"
    assert gate["blockers"] == []


def test_phase1_gate_blocks_missing_case_unstable_force_and_high_actual_cd() -> None:
    module = _load_module()

    reports = [
        _fake_report("naca4412_2d", "naca4412_2d", 0.021, stable=True),
        _fake_report("current_root_dae31", "current_root", 0.120, stable=True),
        _fake_report("current_tip_cst", "current_tip", 0.040, stable=False),
    ]

    gate = module.evaluate_phase1_toolchain_gate(reports)

    assert gate["status"] == "fail"
    assert gate["release_status"] is None
    assert "actual_section_cd_exceeds_0p1" in gate["blockers"]
    assert "case_force_window_not_stable" in gate["blockers"]


def test_phase1_manifest_update_records_report_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    specs = [
        module.Phase1CaseSpec(
            case_id="naca4412_2d",
            section_role="naca4412_2d",
            airfoil="NACA4412",
            airfoil_id="NACA4412",
            chord_m=1.0,
            alpha_deg=4.0,
            airfoil_dat_path=None,
            source_section_index=None,
        ),
        module.Phase1CaseSpec(
            case_id="current_root_dae31",
            section_role="current_root",
            airfoil="dae31",
            airfoil_id="dae31",
            chord_m=1.0,
            alpha_deg=4.0,
            airfoil_dat_path=tmp_path / "dae31.dat",
            source_section_index=0,
        ),
        module.Phase1CaseSpec(
            case_id="current_tip_cst",
            section_role="current_tip",
            airfoil="cst_tip",
            airfoil_id="cst_tip",
            chord_m=0.5,
            alpha_deg=4.0,
            airfoil_dat_path=tmp_path / "tip.dat",
            source_section_index=1,
        ),
    ]
    monkeypatch.setattr(module, "build_phase1_case_specs", lambda _path: specs)
    monkeypatch.setattr(module, "build_basic_airfoil_case", lambda **_kwargs: object())

    def fake_run_basic_airfoil_benchmark(_case, output_dir: Path, **_kwargs) -> dict:
        output_dir.mkdir(parents=True)
        report_path = output_dir / "basic_airfoil_bl_benchmark_report.json"
        report_path.write_text("{}\n", encoding="utf-8")
        cd = 0.021 if output_dir.name == "naca4412_2d" else 0.04
        report = _fake_report(output_dir.name, output_dir.name, cd, stable=True)
        report["report_path"] = str(report_path)
        return report

    monkeypatch.setattr(
        module,
        "run_basic_airfoil_benchmark",
        fake_run_basic_airfoil_benchmark,
    )
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        "passed_gate_statuses: []\nnext_required_gate_status: TOOLCHAIN_PASS\n",
        encoding="utf-8",
    )

    summary = module.run_phase1_toolchain_sanity(
        section_table_path=tmp_path / "section_table.csv",
        output_dir=tmp_path / "toolchain_sanity",
        run_su2=True,
        max_iterations=10,
        update_manifest=True,
        manifest_path=manifest_path,
    )

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    phase1 = manifest["phase1_toolchain_sanity"]
    assert manifest["passed_gate_statuses"] == ["TOOLCHAIN_PASS"]
    assert manifest["next_required_gate_status"] == "PRESSURE_SANITY_PASS"
    assert phase1["status"] == "TOOLCHAIN_PASS"
    assert phase1["report_path"] == summary["report_path"]
    assert len(phase1["case_report_paths"]) == 3


def _fake_report(case_id: str, role: str, cd: float, *, stable: bool) -> dict:
    return {
        "phase1_case_id": case_id,
        "phase1_section_role": role,
        "solver": {
            "run_status": "completed",
            "coefficient_sanity_gate": {
                "status": "pass",
                "final_coefficients": {"cl": 0.8, "cd": cd, "cmy": -0.02},
                "stable_window": {
                    "cl_relative_span": 0.005 if stable else 0.02,
                    "cd_relative_span": 0.005 if stable else 0.02,
                },
            },
        },
    }
