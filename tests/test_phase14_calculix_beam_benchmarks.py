from __future__ import annotations

from pathlib import Path

import csv

import scripts.phase14_calculix_beam_benchmarks as phase14_bench


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "blackcat_004.yaml"


def test_discover_solver_paths_uses_local_path_overlay() -> None:
    solver_paths = phase14_bench.discover_solver_paths(CONFIG_PATH)

    assert solver_paths.ccx_path is not None
    assert solver_paths.gmsh_path is not None
    assert Path(solver_paths.ccx_path).name == "ccx_2.23"


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
