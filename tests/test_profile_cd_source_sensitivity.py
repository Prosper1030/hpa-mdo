from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "analyze_profile_cd_source_sensitivity.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "analyze_profile_cd_source_sensitivity",
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
    rank: int,
    proxy_cd: float,
    zone_cd: float | None,
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
        "rank": rank,
        "overall_rank": rank,
        "mission": mission,
    }


def _write_shadow(
    pool_dir: Path,
    rows: list[dict[str, object]],
    *,
    target: float = 0.017,
    boundary: float = 0.018,
    rescue: float = 0.020,
) -> None:
    summary = {
        "budget_thresholds": {
            "cd0_total_target": target,
            "cd0_total_boundary": boundary,
            "cd0_total_rescue": rescue,
        }
    }
    (pool_dir / "mission_drag_budget_shadow_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    fields = [
        "candidate_id",
        "cd0_total_est",
        "drag_budget_band",
        "cd0_wing_profile",
        "cda_nonwing_m2",
        "wing_area_m2",
    ]
    with (pool_dir / "mission_drag_budget_shadow.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_sensitivity_reads_zone_pool_and_writes_outputs(tmp_path: Path) -> None:
    module = _load_script_module()
    pool_path = _write_ranked_pool(
        tmp_path / "zone_run" / "concept_ranked_pool.json",
        [
            _candidate("zone-1", rank=1, proxy_cd=0.010, zone_cd=0.0105),
            _candidate("zone-2", rank=2, proxy_cd=0.010, zone_cd=0.0095),
        ],
    )
    _write_shadow(
        pool_path.parent,
        [
            {
                "candidate_id": "zone-1",
                "cd0_total_est": 0.014333,
                "drag_budget_band": "target",
                "cd0_wing_profile": 0.010,
                "cda_nonwing_m2": 0.13,
                "wing_area_m2": 30.0,
            },
            {
                "candidate_id": "zone-2",
                "cd0_total_est": 0.014333,
                "drag_budget_band": "target",
                "cd0_wing_profile": 0.010,
                "cda_nonwing_m2": 0.13,
                "wing_area_m2": 30.0,
            },
        ],
    )

    summary = module.run_sensitivity(
        ranked_pool_paths=[pool_path],
        output_dir=tmp_path / "comparison",
    )

    assert summary["overall"]["candidate_count"] == 2
    assert summary["overall"]["zone_available_count"] == 2
    assert summary["overall"]["band_change_count"] == 0
    assert summary["pools"][0]["top10_ratio_median"] == pytest.approx(1.0)

    csv_path = tmp_path / "comparison" / "profile_cd_source_sensitivity.csv"
    md_path = tmp_path / "comparison" / "profile_cd_source_sensitivity.md"
    assert csv_path.exists()
    assert md_path.exists()

    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8")))
    assert [row["candidate_id"] for row in rows] == ["zone-1", "zone-2"]
    assert rows[0]["sensitivity_status"] == "ok"
    assert rows[0]["drag_budget_band_if_zone"] == "target"

    report = md_path.read_text(encoding="utf-8")
    assert "Profile CD Source Sensitivity" in report
    assert "zone_run" in report
    assert "top 10 candidates" in report


def test_sensitivity_marks_old_pool_unavailable_without_crashing(tmp_path: Path) -> None:
    module = _load_script_module()
    pool_path = _write_ranked_pool(
        tmp_path / "old_run" / "concept_ranked_pool.json",
        [_candidate("old-1", rank=1, proxy_cd=0.010, zone_cd=None)],
    )

    summary = module.run_sensitivity(
        ranked_pool_paths=[pool_path],
        output_dir=tmp_path / "comparison",
    )

    assert summary["overall"]["candidate_count"] == 1
    assert summary["overall"]["zone_available_count"] == 0
    assert summary["overall"]["zone_unavailable_count"] == 1

    rows = list(
        csv.DictReader(
            (tmp_path / "comparison" / "profile_cd_source_sensitivity.csv").open(
                newline="",
                encoding="utf-8",
            )
        )
    )
    assert rows[0]["sensitivity_status"] == "zone_unavailable"
    assert rows[0]["band_sensitivity_status"] == "zone_unavailable"


def test_sensitivity_detects_target_to_boundary_band_change(tmp_path: Path) -> None:
    module = _load_script_module()
    pool_path = _write_ranked_pool(
        tmp_path / "band_run" / "concept_ranked_pool.json",
        [_candidate("band-1", rank=1, proxy_cd=0.010, zone_cd=0.013)],
    )
    _write_shadow(
        pool_path.parent,
        [
            {
                "candidate_id": "band-1",
                "cd0_total_est": 0.014333,
                "drag_budget_band": "target",
                "cd0_wing_profile": 0.010,
                "cda_nonwing_m2": 0.13,
                "wing_area_m2": 30.0,
            }
        ],
    )

    summary = module.run_sensitivity(
        ranked_pool_paths=[pool_path],
        output_dir=tmp_path / "comparison",
    )

    assert summary["overall"]["band_change_count"] == 1
    assert summary["overall"]["target_to_boundary_count"] == 1
    assert summary["overall"]["no_change_count"] == 0
    assert summary["band_change_candidates"][0]["candidate_id"] == "band-1"

    rows = list(
        csv.DictReader(
            (tmp_path / "comparison" / "profile_cd_source_sensitivity.csv").open(
                newline="",
                encoding="utf-8",
            )
        )
    )
    assert rows[0]["drag_budget_band"] == "target"
    assert rows[0]["drag_budget_band_if_zone"] == "boundary"
    assert rows[0]["band_change_direction"] == "target_to_boundary"
