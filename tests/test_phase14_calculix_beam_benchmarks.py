from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import csv
import numpy as np

import scripts.phase14_calculix_beam_benchmarks as phase14_bench
from hpa_mdo.structure.calculix_beam_export import cantilever_tip_deflection_uniform_load
from hpa_mdo.structure.spar_model import tube_Ixx


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "blackcat_004.yaml"


def test_discover_solver_paths_delegates_to_configured_discovery_helpers(
    monkeypatch,
) -> None:
    fake_cfg = SimpleNamespace()
    monkeypatch.setattr(phase14_bench, "load_config", lambda _path: fake_cfg)
    monkeypatch.setattr(
        phase14_bench,
        "find_ccx",
        lambda cfg: "/tmp/fake-solvers/ccx_2.23" if cfg is fake_cfg else None,
    )
    monkeypatch.setattr(
        phase14_bench,
        "find_gmsh",
        lambda cfg: "/tmp/fake-solvers/gmsh" if cfg is fake_cfg else None,
    )

    solver_paths = phase14_bench.discover_solver_paths(CONFIG_PATH)

    assert solver_paths.ccx_path is not None
    assert solver_paths.gmsh_path is not None
    assert Path(solver_paths.ccx_path).name == "ccx_2.23"
    assert Path(solver_paths.gmsh_path).name == "gmsh"


def test_runner_writes_skip_report_when_ccx_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(phase14_bench, "find_ccx", lambda _cfg: None)
    monkeypatch.setattr(
        phase14_bench,
        "find_gmsh",
        lambda _cfg: "/Volumes/Samsung SSD/homebrew-cellar/Cellar/gmsh/4.15.2/bin/gmsh",
    )

    result = phase14_bench.run_phase14_calculix_beam_benchmarks(
        config_path=CONFIG_PATH,
        output_dir=tmp_path / "round2_benchmarks",
    )

    assert result.solver_paths.ccx_path is None
    assert result.comparison_csv_path.exists()
    assert result.summary_md_path.exists()

    summary_text = result.summary_md_path.read_text(encoding="utf-8")
    assert "CalculiX not available" in summary_text
    assert "SKIP" in summary_text

    rows = list(csv.DictReader(result.comparison_csv_path.read_text(encoding="utf-8").splitlines()))
    assert rows
    assert {row["status"] for row in rows} == {"SKIP"}
    assert {row["benchmark_id"] for row in rows} >= {"B1", "B2", "B3", "B4", "B5"}
    assert {
        "status_reason",
        "root_reaction_fz_internal_n",
        "root_reaction_fz_calculix_n",
        "wire_reaction_fz_internal_n",
        "wire_reaction_fz_calculix_n",
        "total_reaction_fz_raw_n",
        "total_reaction_fz_corrected_n",
        "reaction_residual_n",
        "twist_proxy_internal_rad",
        "twist_proxy_calculix_rad",
        "twist_proxy_error_pct",
        "engineering_interpretation",
    }.issubset(rows[0].keys())


def test_piecewise_uniform_load_reference_matches_closed_form_for_constant_section() -> None:
    y_nodes_m = np.linspace(0.0, 10.0, 21)
    outer_radius_m = np.full(y_nodes_m.size - 1, 0.03)
    thickness_m = np.full(y_nodes_m.size - 1, 0.0015)
    uniform_load_npm = 8.0

    reference_tip_m = phase14_bench._piecewise_uniform_load_reference_tip_deflection(
        y_nodes_m=y_nodes_m,
        outer_radius_m=outer_radius_m,
        thickness_m=thickness_m,
        young_pa=135.0e9,
        uniform_load_npm=uniform_load_npm,
    )
    closed_form_tip_m = cantilever_tip_deflection_uniform_load(
        uniform_load_npm=uniform_load_npm,
        span_m=float(y_nodes_m[-1] - y_nodes_m[0]),
        young_pa=135.0e9,
        second_moment_m4=float(tube_Ixx(outer_radius_m[:1], thickness_m[:1])[0]),
    )

    assert abs(reference_tip_m - closed_form_tip_m) / closed_form_tip_m < 5.0e-4


def test_twist_proxy_from_tip_displacements_uses_rear_minus_main_over_spacing() -> None:
    assert phase14_bench._twist_proxy_from_tip_displacements(
        main_tip_uz_m=-0.0045,
        rear_tip_uz_m=-0.0038,
        chordwise_spacing_m=0.35,
    ) == (-0.0038 + 0.0045) / 0.35
