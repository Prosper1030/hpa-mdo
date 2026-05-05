from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "compare_profile_cd_sources.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "compare_profile_cd_sources",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_ranked_pool(path: Path, candidates: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"config_path": "fake.yaml", "ranked_pool": candidates}, indent=2),
        encoding="utf-8",
    )
    return path


def _candidate(
    concept_id: str,
    *,
    proxy_cd: float,
    zone_cd: float | None,
    mean_cd_effective: float | None = 0.014,
) -> dict:
    mission = {
        "profile_cd_proxy": proxy_cd,
        "profile_cd_proxy_source": "cruise_station_points_cd_effective",
        "profile_cd_proxy_quality": "mission_budget_candidate",
    }
    if zone_cd is not None:
        mission.update(
            {
                "profile_cd_zone_chord_weighted": zone_cd,
                "profile_cd_zone_source": "zone_chord_weighted_seed_library",
                "profile_cd_zone_quality": "diagnostic_seed_library_estimate",
                "profile_cd_zone_vs_proxy_delta": zone_cd - proxy_cd,
                "profile_cd_zone_vs_proxy_ratio": zone_cd / proxy_cd,
            }
        )
    return {
        "concept_id": concept_id,
        "overall_rank": int(concept_id.rsplit("-", 1)[-1]),
        "airfoil_feedback": {"mean_cd_effective": mean_cd_effective},
        "mission": mission,
    }


def test_comparison_reads_zone_diagnostic_pool_and_writes_outputs(tmp_path: Path) -> None:
    module = _load_script_module()
    pool_path = _write_ranked_pool(
        tmp_path / "zone_run" / "concept_ranked_pool.json",
        [
            _candidate("zone-1", proxy_cd=0.010, zone_cd=0.011),
            _candidate("zone-2", proxy_cd=0.020, zone_cd=0.018),
            _candidate("zone-3", proxy_cd=0.015, zone_cd=0.018),
        ],
    )

    summary = module.run_comparison(
        ranked_pool_paths=[pool_path],
        output_dir=tmp_path / "comparison",
    )

    assert summary["overall"]["candidate_count"] == 3
    assert summary["overall"]["zone_available_count"] == 3
    assert summary["overall"]["zone_unavailable_count"] == 0
    assert summary["overall"]["zone_proxy_ratio_min"] == pytest.approx(0.9)
    assert summary["overall"]["zone_proxy_ratio_median"] == pytest.approx(1.1)
    assert summary["overall"]["zone_proxy_ratio_max"] == pytest.approx(1.2)

    csv_path = tmp_path / "comparison" / "profile_cd_source_comparison.csv"
    md_path = tmp_path / "comparison" / "profile_cd_source_comparison.md"
    assert csv_path.exists()
    assert md_path.exists()

    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8")))
    assert len(rows) == 3
    assert rows[0]["pool_name"] == "zone_run"
    assert rows[0]["profile_cd_zone_quality"] == "diagnostic_seed_library_estimate"
    assert rows[0]["mean_cd_effective"] == "0.014"

    report = md_path.read_text(encoding="utf-8")
    assert "Diagnostic comparison only" in report
    assert "zone_run" in report
    assert "0.9 / 1.1 / 1.2" in report


def test_comparison_marks_old_ranked_pool_zone_unavailable(tmp_path: Path) -> None:
    module = _load_script_module()
    old_candidate = _candidate("old-1", proxy_cd=0.012, zone_cd=None)
    old_candidate["mission"].pop("profile_cd_proxy_quality")
    pool_path = _write_ranked_pool(
        tmp_path / "old_run" / "concept_ranked_pool.json",
        [old_candidate],
    )

    summary = module.run_comparison(
        ranked_pool_paths=[pool_path],
        output_dir=tmp_path / "comparison",
    )

    assert summary["overall"]["zone_available_count"] == 0
    assert summary["overall"]["zone_unavailable_count"] == 1
    assert summary["pools"][0]["needs_rerun_for_zone_diagnostic"] is True
    assert summary["pools"][0]["profile_cd_zone_quality_counts"] == {"zone_unavailable": 1}

    csv_path = tmp_path / "comparison" / "profile_cd_source_comparison.csv"
    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8")))
    assert rows[0]["profile_cd_zone_quality"] == "zone_unavailable"
    assert rows[0]["needs_rerun_for_zone_diagnostic"] == "True"

    report = (tmp_path / "comparison" / "profile_cd_source_comparison.md").read_text(
        encoding="utf-8"
    )
    assert "需要重新跑 pipeline 才能取得 zone diagnostic" in report
    assert "old_run" in report


def test_comparison_reports_ratio_outliers(tmp_path: Path) -> None:
    module = _load_script_module()
    pool_path = _write_ranked_pool(
        tmp_path / "outlier_run" / "concept_ranked_pool.json",
        [
            _candidate("outlier-1", proxy_cd=0.010, zone_cd=0.007),
            _candidate("outlier-2", proxy_cd=0.010, zone_cd=0.013),
        ],
    )

    summary = module.run_comparison(
        ranked_pool_paths=[pool_path],
        output_dir=tmp_path / "comparison",
    )

    assert summary["overall"]["ratio_outlier_count"] == 2
    assert [row["candidate_id"] for row in summary["ratio_outliers"]] == [
        "outlier-1",
        "outlier-2",
    ]
    report = (tmp_path / "comparison" / "profile_cd_source_comparison.md").read_text(
        encoding="utf-8"
    )
    assert "outlier-1" in report
    assert "outlier-2" in report


def test_comparison_reports_ratio_watchlist_outside_0p9_1p1(tmp_path: Path) -> None:
    module = _load_script_module()
    pool_path = _write_ranked_pool(
        tmp_path / "watchlist_run" / "concept_ranked_pool.json",
        [
            _candidate("watch-1", proxy_cd=0.010, zone_cd=0.0085),
            _candidate("watch-2", proxy_cd=0.010, zone_cd=0.0102),
            _candidate("watch-3", proxy_cd=0.010, zone_cd=0.0115),
        ],
    )

    summary = module.run_comparison(
        ranked_pool_paths=[pool_path],
        output_dir=tmp_path / "comparison",
    )

    assert summary["overall"]["ratio_outlier_count"] == 0
    assert summary["overall"]["ratio_outlier_0p9_1p1_count"] == 2
    assert [row["candidate_id"] for row in summary["ratio_outliers_0p9_1p1"]] == [
        "watch-1",
        "watch-3",
    ]

    csv_path = tmp_path / "comparison" / "profile_cd_source_comparison.csv"
    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8")))
    assert rows[0]["ratio_outside_0p9_1p1"] == "True"
    assert rows[1]["ratio_outside_0p9_1p1"] == "False"
    assert rows[2]["ratio_outside_0p9_1p1"] == "True"

    report = (tmp_path / "comparison" / "profile_cd_source_comparison.md").read_text(
        encoding="utf-8"
    )
    assert "Ratio Watchlist 0.9~1.1" in report
    assert "watch-1" in report
    assert "watch-3" in report


def test_comparison_cli_discovers_ranked_pools_and_writes_outputs(tmp_path: Path) -> None:
    module = _load_script_module()
    output_root = tmp_path / "output"
    _write_ranked_pool(
        output_root / "run_a" / "concept_ranked_pool.json",
        [_candidate("run-1", proxy_cd=0.010, zone_cd=0.0105)],
    )
    _write_ranked_pool(
        output_root / "run_b" / "concept_ranked_pool.json",
        [_candidate("run-2", proxy_cd=0.011, zone_cd=None)],
    )

    found = module.discover_ranked_pool_paths(output_root=output_root)
    assert [path.parent.name for path in found] == ["run_a", "run_b"]

    summary = module.run_comparison(
        ranked_pool_paths=found,
        output_dir=tmp_path / "comparison",
    )

    assert summary["overall"]["pool_count"] == 2
    assert (tmp_path / "comparison" / "profile_cd_source_comparison.csv").exists()
    assert (tmp_path / "comparison" / "profile_cd_source_comparison.md").exists()
