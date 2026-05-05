from __future__ import annotations

import json
from pathlib import Path

from hpa_mdo.airfoils.cst_database_builder import (
    CSTZoneSearchConfig,
    build_cst_zone_airfoil_database,
    load_zone_envelopes_from_artifact,
    zone_work_points_from_envelope,
)
from hpa_mdo.airfoils.database import AirfoilQuery


class _FakeWorker:
    backend_name = "julia_xfoil"

    def __init__(self, *, bad_cd: bool = False, status: str = "ok") -> None:
        self.bad_cd = bool(bad_cd)
        self.status = str(status)
        self.queries = []

    def run_queries(self, queries):
        self.queries.extend(queries)
        results = []
        for query in queries:
            points = []
            for cl in query.cl_samples:
                cl_value = float(cl)
                points.append(
                    {
                        "alpha_deg": -2.0 + 8.0 * cl_value,
                        "cl": cl_value,
                        "cd": -0.002 if self.bad_cd else 0.012 + 0.004 * abs(cl_value - 0.8),
                        "cm": -0.07,
                        "converged": self.status == "ok",
                    }
                )
            results.append(
                {
                    "template_id": query.template_id,
                    "reynolds": query.reynolds,
                    "cl_samples": list(query.cl_samples),
                    "roughness_mode": query.roughness_mode,
                    "geometry_hash": query.geometry_hash,
                    "analysis_mode": query.analysis_mode,
                    "analysis_stage": query.analysis_stage,
                    "status": self.status,
                    "polar_points": points,
                    "sweep_summary": {
                        "converged_point_count": len(points) if self.status == "ok" else 0,
                        "sweep_point_count": len(points),
                        "cl_max_observed": max(query.cl_samples) if points else None,
                    },
                }
            )
        return results


class _DryRunWorker(_FakeWorker):
    backend_name = "dry_run_xfoil_surrogate"


def _zone_envelope_path(tmp_path: Path) -> Path:
    path = tmp_path / "zone_envelope.json"
    path.write_text(
        json.dumps(
            {
                "zone_envelope": [
                    {
                        "zone_name": "tip",
                        "eta_min": 0.8,
                        "eta_max": 1.0,
                        "re_min": 180000.0,
                        "re_p50": 220000.0,
                        "re_max": 260000.0,
                        "cl_min": 0.55,
                        "cl_p50": 0.70,
                        "cl_p90": 0.82,
                        "cl_max": 0.88,
                        "current_airfoil_id": "clarkysm",
                        "current_stall_margin": 0.12,
                        "current_profile_cd_estimate": 0.018,
                        "source": "loaded_dihedral_avl",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def _small_config(**overrides) -> CSTZoneSearchConfig:
    values = {
        "population_size_per_zone": 4,
        "generations": 1,
        "nsga_parent_count": 2,
        "coarse_score_count": 2,
        "robust_score_count": 1,
        "top_k_per_zone": 1,
        "re_robustness_factors": (0.82, 1.0, 1.18),
        "roughness_modes": ("clean",),
        "panel_count": 80,
        "xfoil_max_iter": 20,
        "convergence_pass_rate_threshold": 0.80,
        "random_seed": 3,
    }
    values.update(overrides)
    return CSTZoneSearchConfig(**values)


def test_zone_work_points_cover_envelope_extremes(tmp_path: Path) -> None:
    envelopes = load_zone_envelopes_from_artifact(_zone_envelope_path(tmp_path))

    points = zone_work_points_from_envelope(envelopes[0])

    cls = {round(point["cl_target"], 2) for point in points}
    assert {0.55, 0.70, 0.82, 0.88}.issubset(cls)
    assert all(point["source"] == "loaded_dihedral_avl" for point in points)


def test_cst_builder_writes_quality_labeled_database_and_lookup(tmp_path: Path) -> None:
    result = build_cst_zone_airfoil_database(
        zone_envelope_path=_zone_envelope_path(tmp_path),
        output_dir=tmp_path / "build",
        config=_small_config(),
        worker=_FakeWorker(),
    )

    assert result.paths["airfoil_database_json"].is_file()
    assert result.paths["per_zone_top_k_csv"].is_file()
    assert result.paths["coverage_report_csv"].is_file()
    assert result.report["zones"]["tip"]["initial_population_count"] == 4
    assert result.report["zones"]["tip"]["xfoil_evaluated_candidate_count"] >= 1

    record = next(iter(result.airfoil_database.records.values()))
    assert record.source_quality == "cst_xfoil_mission_grade_candidate"
    query = result.airfoil_database.lookup(
        AirfoilQuery(record.airfoil_id, Re=220000.0, cl=0.70, roughness_mode="clean")
    )
    assert query.cd > 0.0


def test_bad_cst_polar_does_not_upgrade_to_mission_grade(tmp_path: Path) -> None:
    result = build_cst_zone_airfoil_database(
        zone_envelope_path=_zone_envelope_path(tmp_path),
        output_dir=tmp_path / "build",
        config=_small_config(),
        worker=_FakeWorker(bad_cd=True),
    )

    qualities = {record.source_quality for record in result.airfoil_database.records.values()}
    assert qualities == {"cst_xfoil_failed_not_mission_grade"}
    assert result.report["source_quality_counts"]["cst_xfoil_failed_not_mission_grade"] >= 1


def test_dry_run_cst_worker_never_upgrades_to_mission_grade(tmp_path: Path) -> None:
    result = build_cst_zone_airfoil_database(
        zone_envelope_path=_zone_envelope_path(tmp_path),
        output_dir=tmp_path / "build",
        config=_small_config(),
        worker=_DryRunWorker(),
    )

    qualities = {record.source_quality for record in result.airfoil_database.records.values()}
    assert "cst_xfoil_mission_grade_candidate" not in qualities
    assert qualities == {"cst_xfoil_candidate_not_mission_grade"}


def test_nsga_generations_create_offspring_after_sobol_initial_population(tmp_path: Path) -> None:
    result = build_cst_zone_airfoil_database(
        zone_envelope_path=_zone_envelope_path(tmp_path),
        output_dir=tmp_path / "build",
        config=_small_config(generations=2, nsga_parent_count=2),
        worker=_FakeWorker(),
    )

    zone_report = result.report["zones"]["tip"]
    assert zone_report["search_mode"] == "nsga2_seedless_sobol_initial_population"
    assert len(zone_report["generation_summaries"]) == 2
    assert zone_report["evaluated_candidate_count"] >= 5
    assert any(
        "nsga2_g01_child" in airfoil_id
        for airfoil_id in result.airfoil_database.records
    )
