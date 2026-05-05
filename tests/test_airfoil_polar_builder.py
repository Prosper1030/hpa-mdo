from __future__ import annotations

from pathlib import Path

from hpa_mdo.airfoils.database import AirfoilQuery, default_airfoil_database
from hpa_mdo.airfoils.polar_builder import (
    PolarBuildConfig,
    build_seed_airfoil_database,
    load_airfoil_database_artifact,
    seed_airfoil_specs,
    write_polar_build_artifacts,
)


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
                cd = -0.001 if self.bad_cd else 0.010 + 0.003 * abs(float(cl) - 0.7)
                points.append(
                    {
                        "alpha_deg": -2.0 + 8.5 * float(cl),
                        "cl": float(cl),
                        "cd": cd,
                        "cm": -0.055,
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


def _small_config(**overrides) -> PolarBuildConfig:
    values = {
        "re_grid": (200_000.0,),
        "cl_grid": (0.4, 0.8, 1.2),
        "roughness_modes": ("clean", "rough"),
        "re_robustness_factors": (1.0,),
        "xfoil_max_iter": 40,
        "panel_count": 96,
        "timeout_s": 15.0,
        "convergence_pass_rate_threshold": 0.80,
    }
    values.update(overrides)
    return PolarBuildConfig(**values)


def test_dry_run_builder_creates_valid_records_but_keeps_not_mission_grade(
    tmp_path: Path,
) -> None:
    result = build_seed_airfoil_database(
        config=_small_config(roughness_modes=("clean",)),
        airfoil_specs={"fx76mp140": seed_airfoil_specs()["fx76mp140"]},
        backend="dry_run",
        cache_dir=tmp_path / "cache",
    )

    database = result.airfoil_database
    record = database.records["fx76mp140"]
    assert "not_mission_grade" in record.source_quality
    query = database.lookup(AirfoilQuery("fx76mp140", Re=200_000.0, cl=0.8))
    assert query.cd > 0.0
    assert query.source_quality == record.source_quality

    artifact_paths = write_polar_build_artifacts(result, tmp_path / "seed_airfoils")
    assert artifact_paths["airfoil_database_json"].is_file()
    assert artifact_paths["airfoil_database_csv"].is_file()
    assert artifact_paths["build_report_json"].is_file()
    assert artifact_paths["build_report_md"].is_file()


def test_worker_records_upgrade_to_mission_grade_only_when_quality_checks_pass(
    tmp_path: Path,
) -> None:
    result = build_seed_airfoil_database(
        config=_small_config(),
        airfoil_specs={"clarkysm": seed_airfoil_specs()["clarkysm"]},
        backend="worker",
        worker=_FakeWorker(),
        cache_dir=tmp_path / "cache",
    )
    assert result.airfoil_database.records["clarkysm"].source_quality == (
        "xfoil_mission_grade_candidate"
    )

    failed = build_seed_airfoil_database(
        config=_small_config(),
        airfoil_specs={"clarkysm": seed_airfoil_specs()["clarkysm"]},
        backend="worker",
        worker=_FakeWorker(bad_cd=True),
        cache_dir=tmp_path / "cache_bad",
    )
    assert failed.airfoil_database.records["clarkysm"].source_quality == (
        "xfoil_incomplete_not_mission_grade"
    )


def test_lookup_uses_generated_roughness_mode(tmp_path: Path) -> None:
    class _RoughWorker(_FakeWorker):
        def run_queries(self, queries):
            results = super().run_queries(queries)
            for result in results:
                if result["roughness_mode"] == "rough":
                    for point in result["polar_points"]:
                        point["cd"] += 0.005
            return results

    result = build_seed_airfoil_database(
        config=_small_config(),
        airfoil_specs={"dae31": seed_airfoil_specs()["dae31"]},
        backend="worker",
        worker=_RoughWorker(),
        cache_dir=tmp_path / "cache",
    )

    database = result.airfoil_database
    clean = database.lookup(
        AirfoilQuery("dae31", Re=200_000.0, cl=0.8, roughness_mode="clean")
    )
    rough = database.lookup(
        AirfoilQuery("dae31", Re=200_000.0, cl=0.8, roughness_mode="rough")
    )
    assert rough.cd > clean.cd


def test_load_airfoil_database_artifact_merges_mission_grade_records(
    tmp_path: Path,
) -> None:
    result = build_seed_airfoil_database(
        config=_small_config(roughness_modes=("clean",)),
        airfoil_specs={"clarkysm": seed_airfoil_specs()["clarkysm"]},
        backend="worker",
        worker=_FakeWorker(),
        cache_dir=tmp_path / "cache",
    )
    artifact_paths = write_polar_build_artifacts(result, tmp_path / "seed_airfoils")

    merged = load_airfoil_database_artifact(
        artifact_paths["airfoil_database_json"],
        fallback_database=default_airfoil_database(),
    )

    assert merged.records["clarkysm"].source_quality == "xfoil_generated_clean_only"
    assert "not_mission_grade" in merged.records["fx76mp140"].source_quality


def test_failed_polar_build_remains_not_mission_grade(tmp_path: Path) -> None:
    result = build_seed_airfoil_database(
        config=_small_config(),
        airfoil_specs={"dae11": seed_airfoil_specs()["dae11"]},
        backend="worker",
        worker=_FakeWorker(status="analysis_failed"),
        cache_dir=tmp_path / "cache",
    )

    record = result.airfoil_database.records["dae11"]
    assert record.source_quality == "xfoil_incomplete_not_mission_grade"
    assert result.report["airfoils"]["dae11"]["quality_passed"] is False
