from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import yaml
import pytest

from hpa_mdo.concept import load_concept_config
from hpa_mdo.concept import pipeline as concept_pipeline
from hpa_mdo.concept.airfoil_worker import JuliaXFoilWorker
from hpa_mdo.concept.geometry import GeometryConcept, build_segment_plan
from hpa_mdo.concept.pipeline import run_birdman_concept_pipeline


def _first_ranked_record(summary: dict[str, object]) -> dict[str, object]:
    selected = summary.get("selected_concepts", [])
    if selected:
        return selected[0]
    fallback = summary.get("best_infeasible_concepts", [])
    assert fallback, "expected at least one selected or best infeasible concept"
    return fallback[0]


def _first_bundle_dir_from_summary(summary: dict[str, object]) -> Path:
    record = _first_ranked_record(summary)
    bundle_dir = record.get("bundle_dir")
    assert bundle_dir is not None, "expected first ranked concept to have a bundle_dir"
    return Path(bundle_dir)


def _worker_result_payload(query, *, sweep_point_count: int) -> dict[str, object]:
    sweep_summary = {
        "sweep_point_count": sweep_point_count,
        "converged_point_count": max(1, sweep_point_count - 1),
        "alpha_min_deg": -2.0,
        "alpha_max_deg": 8.0,
        "alpha_step_deg": 0.5 if sweep_point_count > 2 else None,
        "usable_polar_points": True,
        "cl_max_observed": 1.22,
        "alpha_at_cl_max_deg": 6.0,
        "last_converged_alpha_deg": 6.0,
        "clmax_is_lower_bound": query.analysis_mode == "screening_target_cl",
        "first_pass_observed_clmax_proxy": 1.22,
        "first_pass_observed_clmax_proxy_alpha_deg": 6.0,
        "first_pass_observed_clmax_proxy_cd": 0.023,
        "first_pass_observed_clmax_proxy_cdp": 0.017,
        "first_pass_observed_clmax_proxy_cm": -0.09,
        "first_pass_observed_clmax_proxy_index": 3,
        "first_pass_observed_clmax_proxy_at_sweep_edge": False,
    }
    payload = {
        "status": "ok",
        "template_id": query.template_id,
        "geometry_hash": query.geometry_hash,
        "analysis_mode": query.analysis_mode,
        "analysis_stage": query.analysis_stage,
        "polar_points": [
            {
                "cl_target": query.cl_samples[0],
                "cl": query.cl_samples[0],
                "cd": 0.020 if query.analysis_mode == "screening_target_cl" else 0.019,
                "cm": -0.09,
                "cdp": 0.014,
                "converged": True,
                "cl_error": 0.0,
            }
        ],
        "sweep_summary": sweep_summary,
    }
    if query.analysis_mode == "screening_target_cl":
        payload["screening_summary"] = {
            "target_cl_requested_count": len(query.cl_samples),
            "target_cl_converged_count": len(query.cl_samples),
            "fallback_used": False,
            "mini_sweep_fallback_count": 0,
            "screening_point_count": sweep_point_count,
            **sweep_summary,
        }
    return payload


def test_pipeline_writes_ranked_concept_summary(tmp_path: Path) -> None:
    factory_calls: list[dict[str, object]] = []
    loader_calls: list[tuple[str, int]] = []
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))

    class FakeWorker:
        backend_name = "test_stub"

        def run_queries(self, queries):
            return [
                {"status": "ok", "polar_points": [], "template_id": query.template_id}
                for query in queries
            ]

    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **kwargs: factory_calls.append(kwargs) or FakeWorker(),
        spanwise_loader=lambda concept, stations: loader_calls.append((concept.span_m, len(stations)))
        or {
            "root": {
                "points": [
                    {
                        "reynolds": 350000.0,
                        "cl_target": 0.75,
                        "cm_target": -0.10,
                        "weight": 1.0,
                    }
                ]
            },
            "mid1": {
                "points": [
                    {
                        "reynolds": 300000.0,
                        "cl_target": 0.72,
                        "cm_target": -0.09,
                        "weight": 1.0,
                    }
                ]
            },
            "mid2": {
                "points": [
                    {
                        "reynolds": 250000.0,
                        "cl_target": 0.68,
                        "cm_target": -0.08,
                        "weight": 1.0,
                    }
                ]
            },
            "tip": {
                "points": [
                    {
                        "reynolds": 200000.0,
                        "cl_target": 0.62,
                        "cm_target": -0.07,
                        "weight": 1.0,
                    }
                ]
            },
        },
    )

    assert result.summary_json_path.exists()
    assert 3 <= (
        len(result.selected_concept_dirs) + len(result.best_infeasible_concept_dirs)
    ) <= cfg.pipeline.keep_top_n
    assert factory_calls
    assert factory_calls[0]["project_dir"] == Path(__file__).resolve().parents[1]
    assert factory_calls[0]["cache_dir"] == tmp_path / "polar_db"
    assert len(loader_calls) == (
        len(result.selected_concept_dirs) + len(result.best_infeasible_concept_dirs)
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    first = _first_ranked_record(summary)
    assert summary["worker_backend"] == "test_stub"
    assert summary["worker_statuses"]
    assert all(status == "ok" for status in summary["worker_statuses"])
    assert first["worker_backend"] == "test_stub"
    assert first["worker_statuses"] == ["ok", "ok", "ok", "ok"]
    assert "launch" in first
    assert "turn" in first
    assert "trim" in first
    assert "local_stall" in first
    assert "spanwise_requirements" in first
    assert isinstance(first["launch"]["cl_required"], float)
    assert isinstance(first["turn"]["required_cl"], float)
    assert isinstance(first["trim"]["margin_deg"], float)
    assert isinstance(first["local_stall"]["min_margin"], float)


def test_pipeline_reruns_top_finalists_with_full_alpha_sweep(tmp_path: Path) -> None:
    config_payload = yaml.safe_load(
        Path("configs/birdman_upstream_concept_baseline.yaml").read_text(encoding="utf-8")
    )
    config_payload["pipeline"]["keep_top_n"] = 3
    config_payload["pipeline"]["finalist_full_sweep_top_l"] = 2
    config_path = tmp_path / "dual_track.yaml"
    config_path.write_text(yaml.safe_dump(config_payload, sort_keys=False), encoding="utf-8")

    class FakeWorker:
        backend_name = "dual_track_stub"

        def __init__(self):
            self.batches: list[list[tuple[str, str]]] = []

        def run_queries(self, queries):
            self.batches.append([(query.analysis_mode, query.analysis_stage) for query in queries])
            return [
                _worker_result_payload(
                    query,
                    sweep_point_count=(4 if query.analysis_mode == "screening_target_cl" else 21),
                )
                for query in queries
            ]

    fake_worker = FakeWorker()
    result = run_birdman_concept_pipeline(
        config_path=config_path,
        output_dir=tmp_path / "out",
        airfoil_worker_factory=lambda **_: fake_worker,
        spanwise_loader=lambda concept, stations: {
            "root": {
                "points": [
                    {"reynolds": 260000.0, "chord_m": 1.30, "cl_target": 0.70, "cm_target": -0.10, "weight": 1.0}
                ]
            },
            "mid1": {
                "points": [
                    {"reynolds": 240000.0, "chord_m": 1.15, "cl_target": 0.66, "cm_target": -0.09, "weight": 1.0}
                ]
            },
            "mid2": {
                "points": [
                    {"reynolds": 220000.0, "chord_m": 1.00, "cl_target": 0.62, "cm_target": -0.08, "weight": 1.0}
                ]
            },
            "tip": {
                "points": [
                    {"reynolds": 200000.0, "chord_m": 0.82, "cl_target": 0.58, "cm_target": -0.07, "weight": 1.0}
                ]
            },
        },
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    screening_batches = [
        batch for batch in fake_worker.batches if all(stage == "screening" for _, stage in batch)
    ]
    finalist_batches = [
        batch for batch in fake_worker.batches if all(stage == "finalist" for _, stage in batch)
    ]

    assert screening_batches
    assert len(finalist_batches) == 2
    assert all(all(mode == "full_alpha_sweep" for mode, _ in batch) for batch in finalist_batches)
    first = _first_ranked_record(summary)
    assert first["worker_fidelity"]["screening"]["worker_analysis_modes"]
    assert first["worker_fidelity"]["finalist"]["worker_analysis_modes"] == ["full_alpha_sweep"] * 4


def test_pipeline_summary_distinguishes_screening_and_finalist_worker_fidelity(
    tmp_path: Path,
) -> None:
    config_payload = yaml.safe_load(
        Path("configs/birdman_upstream_concept_baseline.yaml").read_text(encoding="utf-8")
    )
    config_payload["pipeline"]["keep_top_n"] = 3
    config_payload["pipeline"]["finalist_full_sweep_top_l"] = 1
    config_path = tmp_path / "dual_track_summary.yaml"
    config_path.write_text(yaml.safe_dump(config_payload, sort_keys=False), encoding="utf-8")

    class FakeWorker:
        backend_name = "dual_track_stub"

        def run_queries(self, queries):
            return [
                _worker_result_payload(
                    query,
                    sweep_point_count=(4 if query.analysis_mode == "screening_target_cl" else 21),
                )
                for query in queries
            ]

    result = run_birdman_concept_pipeline(
        config_path=config_path,
        output_dir=tmp_path / "out",
        airfoil_worker_factory=lambda **_: FakeWorker(),
        spanwise_loader=lambda concept, stations: {
            "root": {
                "points": [
                    {"reynolds": 260000.0, "chord_m": 1.30, "cl_target": 0.70, "cm_target": -0.10, "weight": 1.0}
                ]
            },
            "mid1": {
                "points": [
                    {"reynolds": 240000.0, "chord_m": 1.15, "cl_target": 0.66, "cm_target": -0.09, "weight": 1.0}
                ]
            },
            "mid2": {
                "points": [
                    {"reynolds": 220000.0, "chord_m": 1.00, "cl_target": 0.62, "cm_target": -0.08, "weight": 1.0}
                ]
            },
            "tip": {
                "points": [
                    {"reynolds": 200000.0, "chord_m": 0.82, "cl_target": 0.58, "cm_target": -0.07, "weight": 1.0}
                ]
            },
        },
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    first = _first_ranked_record(summary)

    assert first["worker_fidelity"]["screening"]["worker_analysis_stages"] == ["screening"] * 4
    assert first["worker_fidelity"]["finalist"]["worker_analysis_stages"] == ["finalist"] * 4
    bundle_dir = _first_bundle_dir_from_summary(summary)
    concept_summary = json.loads((bundle_dir / "concept_summary.json").read_text(encoding="utf-8"))
    assert concept_summary["worker_fidelity"]["screening"]["worker_analysis_modes"] == [
        "screening_target_cl"
    ] * 4
    assert concept_summary["worker_fidelity"]["finalist"]["worker_analysis_modes"] == [
        "full_alpha_sweep"
    ] * 4


def test_pipeline_batches_screening_candidate_selection_across_concepts(
    tmp_path: Path,
) -> None:
    config_payload = yaml.safe_load(
        Path("configs/birdman_upstream_concept_baseline.yaml").read_text(encoding="utf-8")
    )
    config_payload["pipeline"]["keep_top_n"] = 2
    config_payload["pipeline"]["finalist_full_sweep_top_l"] = 1
    config_path = tmp_path / "global_screening_batch.yaml"
    config_path.write_text(yaml.safe_dump(config_payload, sort_keys=False), encoding="utf-8")

    class FakeWorker:
        backend_name = "dual_track_stub"

        def __init__(self):
            self.batch_template_ids: list[tuple[str, ...]] = []

        def run_queries(self, queries):
            self.batch_template_ids.append(tuple(query.template_id for query in queries))
            return [
                _worker_result_payload(
                    query,
                    sweep_point_count=(4 if query.analysis_mode == "screening_target_cl" else 21),
                )
                for query in queries
            ]

    fake_worker = FakeWorker()
    run_birdman_concept_pipeline(
        config_path=config_path,
        output_dir=tmp_path / "out",
        airfoil_worker_factory=lambda **_: fake_worker,
        spanwise_loader=lambda concept, stations: {
            "root": {
                "points": [
                    {"reynolds": 260000.0, "chord_m": 1.30, "cl_target": 0.70, "cm_target": -0.10, "weight": 1.0}
                ]
            },
            "mid1": {
                "points": [
                    {"reynolds": 240000.0, "chord_m": 1.15, "cl_target": 0.66, "cm_target": -0.09, "weight": 1.0}
                ]
            },
            "mid2": {
                "points": [
                    {"reynolds": 220000.0, "chord_m": 1.00, "cl_target": 0.62, "cm_target": -0.08, "weight": 1.0}
                ]
            },
            "tip": {
                "points": [
                    {"reynolds": 200000.0, "chord_m": 0.82, "cl_target": 0.58, "cm_target": -0.07, "weight": 1.0}
                ]
            },
        },
    )

    first_batch = fake_worker.batch_template_ids[0]
    assert any(template_id.startswith("eval-01__") for template_id in first_batch)
    assert any(template_id.startswith("eval-02__") for template_id in first_batch)


def test_pipeline_records_spanwise_requirement_source_in_summary(tmp_path: Path) -> None:
    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {
                "backend_name": "test_stub",
                "run_queries": lambda self, queries: [
                    {"status": "stubbed_ok", "polar_points": [], "template_id": query.template_id}
                    for query in queries
                ],
            },
        )(),
        spanwise_loader=lambda concept, stations: {
            "root": {
                "source": "fallback_coarse_loader",
                "fallback_reason": "avl failed",
                "points": [
                    {
                        "reynolds": 350000.0,
                        "cl_target": 0.75,
                        "cm_target": -0.10,
                        "weight": 1.0,
                    }
                ],
            },
            "mid1": {"source": "fallback_coarse_loader", "fallback_reason": "avl failed", "points": []},
            "mid2": {"source": "fallback_coarse_loader", "fallback_reason": "avl failed", "points": []},
            "tip": {"source": "fallback_coarse_loader", "fallback_reason": "avl failed", "points": []},
        },
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    spanwise_summary = _first_ranked_record(summary)["spanwise_requirements"]

    assert spanwise_summary["unique_sources"] == ["fallback_coarse_loader"]
    assert spanwise_summary["fallback_detected"] is True
    assert spanwise_summary["fallback_reasons"] == ["avl failed"]


def test_pipeline_records_reference_condition_metadata_in_spanwise_summary(
    tmp_path: Path,
) -> None:
    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {
                "backend_name": "test_stub",
                "run_queries": lambda self, queries: [
                    {"status": "stubbed_ok", "polar_points": [], "template_id": query.template_id}
                    for query in queries
                ],
            },
        )(),
        spanwise_loader=lambda concept, stations: {
            "root": {
                "source": "avl_strip_forces",
                "reference_condition_policy": "mission_objective_multipoint_design_cases_v2",
                "reference_speed_mps": 6.5,
                "reference_gross_mass_kg": 105.0,
                "reference_speed_reason": "best_range_speed_mps",
                "mass_selection_reason": "min_best_range",
                "design_cases": [{"case_label": "reference_avl_case"}],
                "points": [
                    {
                        "reynolds": 350000.0,
                        "cl_target": 0.75,
                        "cm_target": -0.10,
                        "weight": 1.0,
                    }
                ],
            },
            "mid1": {
                "source": "avl_strip_forces",
                "reference_condition_policy": "mission_objective_multipoint_design_cases_v2",
                "reference_speed_mps": 6.5,
                "reference_gross_mass_kg": 105.0,
                "reference_speed_reason": "best_range_speed_mps",
                "mass_selection_reason": "min_best_range",
                "design_cases": [{"case_label": "reference_avl_case"}],
                "points": [],
            },
            "mid2": {
                "source": "avl_strip_forces",
                "reference_condition_policy": "mission_objective_multipoint_design_cases_v2",
                "reference_speed_mps": 6.5,
                "reference_gross_mass_kg": 105.0,
                "reference_speed_reason": "best_range_speed_mps",
                "mass_selection_reason": "min_best_range",
                "design_cases": [{"case_label": "reference_avl_case"}],
                "points": [],
            },
            "tip": {
                "source": "avl_strip_forces",
                "reference_condition_policy": "mission_objective_multipoint_design_cases_v2",
                "reference_speed_mps": 6.5,
                "reference_gross_mass_kg": 105.0,
                "reference_speed_reason": "best_range_speed_mps",
                "mass_selection_reason": "min_best_range",
                "design_cases": [{"case_label": "reference_avl_case"}],
                "points": [],
            },
        },
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    spanwise_summary = _first_ranked_record(summary)["spanwise_requirements"]

    assert spanwise_summary["reference_condition_policies"] == [
        "mission_objective_multipoint_design_cases_v2"
    ]
    assert spanwise_summary["reference_speeds_mps"] == [6.5]
    assert spanwise_summary["reference_gross_masses_kg"] == [105.0]
    assert spanwise_summary["reference_speed_reasons"] == ["best_range_speed_mps"]
    assert spanwise_summary["mass_selection_reasons"] == ["min_best_range"]
    assert spanwise_summary["design_case_labels"] == ["reference_avl_case"]


def test_fallback_selected_zone_candidate_applies_safe_clmax_model() -> None:
    selected = concept_pipeline._build_fallback_selected_zone_candidate(
        zone_name="root",
        seed_coordinates=(
            (1.0, 0.0),
            (0.5, 0.06),
            (0.0, 0.0),
            (0.5, -0.04),
            (1.0, 0.0),
        ),
        safe_clmax_scale=0.85,
        safe_clmax_delta=0.10,
    )

    assert selected.usable_clmax == pytest.approx(0.90)
    assert selected.safe_clmax == pytest.approx(0.665)


def test_pipeline_uses_cst_selected_airfoil_templates(tmp_path: Path) -> None:
    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {
                "backend_name": "test_stub",
                "run_queries": lambda self, queries: [
                    {
                        "status": "ok",
                        "template_id": query.template_id,
                        "geometry_hash": query.geometry_hash,
                        "polar_points": [
                            {
                                "cl_target": query.cl_samples[0],
                                "cl": query.cl_samples[0],
                                "cd": 0.020,
                                "cm": -0.10,
                                "converged": True,
                            }
                        ],
                        "sweep_summary": {
                            "cl_max_observed": 1.20,
                            "converged_point_count": 10,
                            "sweep_point_count": 10,
                        },
                    }
                    for query in queries
                ],
            },
        )(),
        spanwise_loader=lambda concept, stations: {
            "root": {
                "points": [
                    {
                        "reynolds": 260000.0,
                        "chord_m": 1.30,
                        "cl_target": 0.70,
                        "cm_target": -0.10,
                        "weight": 1.0,
                    }
                ]
            },
            "mid1": {
                "points": [
                    {
                        "reynolds": 240000.0,
                        "chord_m": 1.15,
                        "cl_target": 0.66,
                        "cm_target": -0.09,
                        "weight": 1.0,
                    }
                ]
            },
            "mid2": {
                "points": [
                    {
                        "reynolds": 220000.0,
                        "chord_m": 1.00,
                        "cl_target": 0.62,
                        "cm_target": -0.08,
                        "weight": 1.0,
                    }
                ]
            },
            "tip": {
                "points": [
                    {
                        "reynolds": 200000.0,
                        "chord_m": 0.82,
                        "cl_target": 0.58,
                        "cm_target": -0.07,
                        "weight": 1.0,
                    }
                ]
            },
        },
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    bundle = _first_bundle_dir_from_summary(summary)
    airfoil_templates = json.loads((bundle / "airfoil_templates.json").read_text(encoding="utf-8"))

    assert airfoil_templates["root"]["authority"] == "cst_candidate"
    assert "upper_coefficients" in airfoil_templates["root"]
    assert "lower_coefficients" in airfoil_templates["root"]
    assert "candidate_role" in airfoil_templates["root"]
    assert airfoil_templates["root"]["points"][0]["chord_m"] == pytest.approx(1.30)


def test_pipeline_emits_all_required_mvp_artifacts(tmp_path: Path) -> None:
    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {
                "backend_name": "test_stub",
                "run_queries": lambda self, queries: [
                    {"status": "stubbed_ok", "polar_points": [], "template_id": query.template_id}
                    for query in queries
                ],
            },
        )(),
        spanwise_loader=lambda concept, stations: {
            "root": {"points": []},
            "mid1": {"points": []},
            "mid2": {"points": []},
            "tip": {"points": []},
        },
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    bundle = _first_bundle_dir_from_summary(summary)
    airfoil_templates = json.loads((bundle / "airfoil_templates.json").read_text(encoding="utf-8"))
    prop_assumption = json.loads((bundle / "prop_assumption.json").read_text(encoding="utf-8"))
    concept_summary = json.loads((bundle / "concept_summary.json").read_text(encoding="utf-8"))

    assert (bundle / "concept_config.yaml").exists()
    assert (bundle / "stations.csv").exists()
    assert (bundle / "airfoil_templates.json").exists()
    assert (bundle / "lofting_guides.json").exists()
    assert (bundle / "prop_assumption.json").exists()
    assert (bundle / "concept_summary.json").exists()
    assert set(airfoil_templates) == {"root", "mid1", "mid2", "tip"}
    assert all(payload["authority"] == "cst_candidate" for payload in airfoil_templates.values())
    assert all("template_id" in payload for payload in airfoil_templates.values())
    assert all("points" in payload for payload in airfoil_templates.values())
    assert airfoil_templates["root"]["seed_name"] == "fx76mp140"
    assert airfoil_templates["tip"]["seed_name"] == "clarkysm"
    assert len(airfoil_templates["root"]["coordinates"]) > 20
    assert len(airfoil_templates["tip"]["coordinates"]) > 20
    assert prop_assumption["blade_count"] == 2
    assert prop_assumption["diameter_m"] == 3.0
    assert prop_assumption["rpm_range"] == [100.0, 160.0]
    assert concept_summary["selected"] is False
    assert concept_summary["launch"]["status"] in {
        "ok",
        "launch_cl_insufficient",
        "trim_margin_insufficient",
    }
    assert concept_summary["turn"]["status"] in {
        "ok",
        "stall_utilization_exceeded",
        "trim_not_feasible",
    }
    assert concept_summary["trim"]["status"] in {"ok", "trim_margin_insufficient"}
    assert concept_summary["local_stall"]["status"] in {"ok", "stall_utilization_exceeded"}
    assert isinstance(concept_summary["launch"]["cl_required"], float)
    assert isinstance(concept_summary["turn"]["required_cl"], float)
    assert isinstance(concept_summary["trim"]["margin_deg"], float)
    assert isinstance(concept_summary["local_stall"]["min_margin"], float)


def test_seed_airfoil_loader_accepts_headerless_selig_dat(tmp_path, monkeypatch) -> None:
    airfoil_dir = tmp_path / "airfoils"
    airfoil_dir.mkdir()
    (airfoil_dir / "headerless.dat").write_text(
        "\n".join(
            [
                "1.0 0.0",
                "0.5 0.05",
                "0.0 0.0",
                "0.5 -0.05",
                "1.0 0.0",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(concept_pipeline, "_airfoil_data_dir", lambda: airfoil_dir)
    concept_pipeline._load_seed_airfoil_coordinates.cache_clear()
    try:
        coordinates = concept_pipeline._load_seed_airfoil_coordinates("headerless")
    finally:
        concept_pipeline._load_seed_airfoil_coordinates.cache_clear()

    assert coordinates[0] == pytest.approx((1.0, 0.0))
    assert len(coordinates) == 5


def test_pipeline_uses_airfoil_derived_spanwise_values_when_available(
    tmp_path: Path,
) -> None:
    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {
                "backend_name": "test_stub",
                "run_queries": lambda self, queries: [
                    {
                        "status": "ok",
                        "template_id": query.template_id,
                        "polar_points": [
                            {
                                "cl_target": query.cl_samples[0],
                                "alpha_deg": 4.2,
                                "cl": query.cl_samples[0] + 0.001,
                                "cd": 0.021,
                                "cdp": 0.015,
                                "cm": -0.08,
                                "converged": True,
                                "cl_error": 0.001,
                            }
                        ],
                        "sweep_summary": {
                            "sweep_point_count": 41,
                            "converged_point_count": 30,
                            "alpha_min_deg": -4.0,
                            "alpha_max_deg": 16.0,
                            "alpha_step_deg": 0.5,
                            "usable_polar_points": True,
                            "cl_max_observed": 1.24,
                            "alpha_at_cl_max_deg": 12.0,
                            "last_converged_alpha_deg": 12.0,
                            "clmax_is_lower_bound": True,
                            "first_pass_observed_clmax_proxy": 1.24,
                            "first_pass_observed_clmax_proxy_alpha_deg": 12.0,
                            "first_pass_observed_clmax_proxy_cd": 0.028,
                            "first_pass_observed_clmax_proxy_cdp": 0.020,
                            "first_pass_observed_clmax_proxy_cm": -0.11,
                            "first_pass_observed_clmax_proxy_index": 32,
                            "first_pass_observed_clmax_proxy_at_sweep_edge": False,
                        },
                        "reynolds": query.reynolds,
                        "cl_samples": list(query.cl_samples),
                        "roughness_mode": query.roughness_mode,
                        "geometry_hash": query.geometry_hash,
                    }
                    for query in queries
                ],
            },
        )(),
        spanwise_loader=lambda concept, stations: {
            "root": {
                "points": [
                    {
                        "reynolds": 350000.0,
                        "cl_target": 0.66,
                        "cm_target": -0.04,
                        "weight": 1.0,
                        "station_y_m": 1.0,
                    }
                ]
            },
            "mid1": {
                "points": [
                    {
                        "reynolds": 300000.0,
                        "cl_target": 0.73,
                        "cm_target": -0.07,
                        "weight": 1.0,
                        "station_y_m": 5.0,
                    }
                ]
            },
            "mid2": {
                "points": [
                    {
                        "reynolds": 250000.0,
                        "cl_target": 0.79,
                        "cm_target": -0.09,
                        "weight": 1.0,
                        "station_y_m": 9.0,
                    }
                ]
            },
            "tip": {
                "points": [
                    {
                        "reynolds": 220000.0,
                        "cl_target": 0.87,
                        "cm_target": -0.13,
                        "weight": 1.0,
                        "station_y_m": 14.0,
                    }
                ]
            },
        },
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    first = _first_ranked_record(summary)

    assert first["launch"]["gross_mass_kg"] == pytest.approx(105.0)
    assert first["launch"]["cl_available_source"] == "airfoil_safe_lower_bound"
    assert first["turn"]["cl_max_source"] == "airfoil_safe_lower_bound"
    assert first["trim"]["representative_cm_source"] == "airfoil_near_target"
    assert first["local_stall"]["margin_source"] == "airfoil_safe_lower_bound"
    assert first["airfoil_feedback"]["applied"] is True
    assert first["airfoil_feedback"]["usable_worker_point_count"] == 4
    assert first["airfoil_feedback"]["mean_cd_effective"] == pytest.approx(0.021)
    assert first["airfoil_feedback"]["min_cl_max_effective"] == pytest.approx(1.24)
    assert first["airfoil_feedback"]["min_cl_max_safe"] == pytest.approx(0.9 * 1.24 - 0.05)
    assert first["turn"]["cl_level"] == pytest.approx(0.87)
    assert first["turn"]["limiting_station_y_m"] == pytest.approx(14.0)
    assert first["turn"]["tip_critical"] is True
    assert first["trim"]["representative_cm"] == pytest.approx(-0.08)
    assert first["trim"]["cm_rms"] == pytest.approx(0.0)
    assert first["launch"]["cl_available"] == pytest.approx(0.9 * 1.24 - 0.05)
    assert first["turn"]["stall_utilization"] == pytest.approx(
        first["turn"]["required_cl"] / first["turn"]["cl_max"]
    )


def test_turn_summary_rescales_reference_cl_targets_to_release_condition() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    concept = GeometryConcept(
        span_m=32.0,
        wing_area_m2=32.0,
        root_chord_m=1.0,
        tip_chord_m=1.0,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(8.0, 8.0),
    )

    turn = concept_pipeline._summarize_turn(
        cfg=cfg,
        concept=concept,
        station_points=[
            {
                "station_y_m": 4.0,
                "cl_target": 1.0,
                "cl_max_proxy": 1.2,
                "reference_speed_mps": 6.0,
                "reference_gross_mass_kg": 95.0,
            }
        ],
        trim_result=type("TrimResult", (), {"feasible": True})(),
    )

    cl_scale = (105.0 / 95.0) * (6.0 / 8.0) ** 2
    assert turn["status"] == "ok"
    assert turn["cl_level"] == pytest.approx(cl_scale)
    assert turn["required_cl"] == pytest.approx(cl_scale / 0.9659258262890683)
    assert turn["cl_scale_factor_min"] == pytest.approx(cl_scale)
    assert turn["cl_scale_factor_max"] == pytest.approx(cl_scale)
    assert turn["reference_speed_mps"] == pytest.approx(6.0)
    assert turn["reference_gross_mass_kg"] == pytest.approx(95.0)
    assert turn["evaluation_gross_mass_kg"] == pytest.approx(105.0)
    assert turn["stall_utilization"] == pytest.approx(turn["required_cl"] / turn["cl_max"])


def test_turn_summary_uses_explicit_turn_avl_case_without_rescaling() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    concept = GeometryConcept(
        span_m=32.0,
        wing_area_m2=32.0,
        root_chord_m=1.0,
        tip_chord_m=1.0,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(8.0, 8.0),
    )

    turn = concept_pipeline._summarize_turn(
        cfg=cfg,
        concept=concept,
        station_points=[
            {
                "station_y_m": 4.0,
                "cl_target": 0.98,
                "cl_max_safe": 1.20,
                "case_label": "turn_avl_case",
                "evaluation_speed_mps": 8.0,
                "evaluation_gross_mass_kg": 105.0,
                "load_factor": 1.0 / 0.9659258262890683,
                "reference_speed_mps": 6.0,
                "reference_gross_mass_kg": 95.0,
            }
        ],
        trim_result=type("TrimResult", (), {"feasible": True})(),
    )

    assert turn["evaluation_case"] == "turn_avl_case"
    assert turn["required_cl"] == pytest.approx(0.98)
    assert turn["cl_scale_factor_min"] == pytest.approx(1.0)
    assert turn["cl_scale_factor_max"] == pytest.approx(1.0)


def test_trim_summary_accounts_for_tail_area_and_balance() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    small_tail = GeometryConcept(
        span_m=32.0,
        wing_area_m2=32.0,
        root_chord_m=1.0,
        tip_chord_m=1.0,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=3.8,
        cg_xc=0.30,
        segment_lengths_m=(8.0, 8.0),
    )
    large_tail = GeometryConcept(
        span_m=32.0,
        wing_area_m2=32.0,
        root_chord_m=1.0,
        tip_chord_m=1.0,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=4.6,
        cg_xc=0.30,
        segment_lengths_m=(8.0, 8.0),
    )
    station_points = [
        {
            "station_y_m": 4.0,
            "cl_target": 0.82,
            "cm_target": -0.08,
            "cm_effective": -0.08,
            "cm_effective_source": "airfoil_near_target",
            "chord_m": 1.15,
            "weight": 1.0,
            "case_label": "reference_avl_case",
        },
        {
            "station_y_m": 12.0,
            "cl_target": 0.70,
            "cm_target": -0.09,
            "cm_effective": -0.09,
            "cm_effective_source": "airfoil_near_target",
            "chord_m": 0.95,
            "weight": 1.0,
            "case_label": "reference_avl_case",
        },
    ]

    small_summary, _ = concept_pipeline._summarize_trim(
        cfg=cfg,
        concept=small_tail,
        station_points=station_points,
    )
    large_summary, _ = concept_pipeline._summarize_trim(
        cfg=cfg,
        concept=large_tail,
        station_points=station_points,
    )

    assert small_summary["model"] == "tail_volume_balance"
    assert small_summary["representative_cm_source"] == "airfoil_near_target"
    assert small_summary["tail_area_ratio"] < large_summary["tail_area_ratio"]
    assert small_summary["tail_volume_coefficient"] < large_summary["tail_volume_coefficient"]
    assert abs(small_summary["tail_cl_required"]) > abs(large_summary["tail_cl_required"])
    assert small_summary["tail_utilization"] > large_summary["tail_utilization"]
    assert small_summary["margin_deg"] < large_summary["margin_deg"]


def test_mission_summary_includes_tail_trim_drag_penalty() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    concept = GeometryConcept(
        span_m=32.0,
        wing_area_m2=32.0,
        root_chord_m=1.0,
        tip_chord_m=1.0,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=4.2,
        cg_xc=0.30,
        segment_lengths_m=(8.0, 8.0),
    )
    station_points = [
        {
            "station_y_m": 4.0,
            "cl_target": 0.82,
            "cm_target": -0.08,
            "cm_effective": -0.08,
            "chord_m": 1.15,
            "weight": 1.0,
            "case_label": "reference_avl_case",
        }
    ]
    airfoil_feedback = {
        "mean_cd_effective": 0.021,
    }
    low_trim = concept_pipeline._build_concept_mission_summary(
        cfg=cfg,
        concept=concept,
        station_points=station_points,
        airfoil_feedback=airfoil_feedback,
        trim_summary={"tail_cl_required": 0.10},
        air_density_kg_per_m3=1.15,
    )
    high_trim = concept_pipeline._build_concept_mission_summary(
        cfg=cfg,
        concept=concept,
        station_points=station_points,
        airfoil_feedback=airfoil_feedback,
        trim_summary={"tail_cl_required": 0.45},
        air_density_kg_per_m3=1.15,
    )

    assert high_trim["trim_drag_cd_proxy"] > low_trim["trim_drag_cd_proxy"]
    assert max(high_trim["power_required_w"]) > max(low_trim["power_required_w"])
    assert high_trim["tail_cl_required_for_trim"] == pytest.approx(0.45)


def test_local_stall_summary_uses_worst_case_across_reference_mission_and_launch() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    concept = GeometryConcept(
        span_m=32.0,
        wing_area_m2=32.0,
        root_chord_m=1.0,
        tip_chord_m=1.0,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(8.0, 8.0),
    )

    local_stall = concept_pipeline._summarize_local_stall(
        cfg=cfg,
        concept=concept,
        station_points=[
            {
                "station_y_m": 4.0,
                "cl_target": 0.70,
                "cl_max_safe": 1.20,
                "cl_max_safe_source": "airfoil_safe_observed",
                "reference_speed_mps": 10.0,
                "reference_gross_mass_kg": 95.0,
            }
        ],
        mission_summary={
            "best_range_speed_mps": 9.0,
            "evaluated_gross_mass_kg": 100.0,
        },
    )

    launch_scale = (105.0 / 95.0) * (10.0 / 8.0) ** 2
    assert local_stall["evaluation_case"] == "launch_release_case"
    assert local_stall["evaluation_speed_mps"] == pytest.approx(8.0)
    assert local_stall["evaluation_gross_mass_kg"] == pytest.approx(105.0)
    assert local_stall["required_cl"] == pytest.approx(0.70 * launch_scale)
    assert local_stall["stall_utilization"] == pytest.approx(local_stall["required_cl"] / 1.20)
    assert {case["case_label"] for case in local_stall["case_results"]} == {
        "reference_avl_case",
        "mission_worst_case",
        "launch_release_case",
    }


def test_pipeline_reorders_selected_concepts_by_mission_ranking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    payload = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    payload["pipeline"]["keep_top_n"] = 3
    payload["output"]["export_candidate_bundle"] = False
    payload["stall_model"] = {
        "safe_clmax_scale": 1.0,
        "safe_clmax_delta": 0.0,
        "local_stall_utilization_limit": 0.98,
        "turn_utilization_limit": 0.98,
        "launch_utilization_limit": 0.95,
    }
    custom_cfg = tmp_path / "concept_ranked.yaml"
    custom_cfg.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    concept_worse = GeometryConcept(
        span_m=30.0,
        wing_area_m2=30.0,
        root_chord_m=1.5384615384615385,
        tip_chord_m=0.46153846153846156,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        dihedral_root_deg=0.0,
        dihedral_tip_deg=4.0,
        dihedral_exponent=1.0,
        tail_area_m2=4.6,
        cg_xc=0.30,
        segment_lengths_m=build_segment_plan(
            half_span_m=15.0,
            min_segment_length_m=1.0,
            max_segment_length_m=3.0,
        ),
    )
    concept_better = GeometryConcept(
        span_m=34.0,
        wing_area_m2=26.0,
        root_chord_m=1.1764705882352942,
        tip_chord_m=0.35294117647058826,
        twist_root_deg=2.0,
        twist_tip_deg=-2.0,
        dihedral_root_deg=0.0,
        dihedral_tip_deg=4.0,
        dihedral_exponent=1.0,
        tail_area_m2=3.8,
        cg_xc=0.30,
        segment_lengths_m=build_segment_plan(
            half_span_m=17.0,
            min_segment_length_m=1.0,
            max_segment_length_m=3.0,
        ),
    )
    concept_middle = GeometryConcept(
        span_m=32.0,
        wing_area_m2=28.0,
        root_chord_m=1.3461538461538463,
        tip_chord_m=0.4038461538461539,
        twist_root_deg=2.0,
        twist_tip_deg=-1.5,
        dihedral_root_deg=0.0,
        dihedral_tip_deg=4.0,
        dihedral_exponent=1.0,
        tail_area_m2=4.2,
        cg_xc=0.30,
        segment_lengths_m=build_segment_plan(
            half_span_m=16.0,
            min_segment_length_m=1.0,
            max_segment_length_m=3.0,
        ),
    )
    monkeypatch.setattr(
        concept_pipeline,
        "enumerate_geometry_concepts",
        lambda cfg: (concept_worse, concept_better, concept_middle),
    )

    result = run_birdman_concept_pipeline(
        config_path=custom_cfg,
        output_dir=tmp_path / "out",
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {
                "backend_name": "test_stub",
                "run_queries": lambda self, queries: [
                    {
                        "status": "ok",
                        "template_id": query.template_id,
                        "polar_points": [
                            {
                                "cl_target": query.cl_samples[0],
                                "alpha_deg": 3.5,
                                "cl": query.cl_samples[0],
                                "cd": 0.014,
                                "cdp": 0.010,
                                "cm": -0.02,
                                "converged": True,
                                "cl_error": 0.0,
                            }
                        ],
                        "sweep_summary": {
                            "sweep_point_count": 41,
                            "converged_point_count": 34,
                            "alpha_min_deg": -4.0,
                            "alpha_max_deg": 16.0,
                            "alpha_step_deg": 0.5,
                            "usable_polar_points": True,
                            "cl_max_observed": 1.35,
                            "alpha_at_cl_max_deg": 10.0,
                            "last_converged_alpha_deg": 10.0,
                            "clmax_is_lower_bound": False,
                            "first_pass_observed_clmax_proxy": 1.35,
                            "first_pass_observed_clmax_proxy_alpha_deg": 10.0,
                            "first_pass_observed_clmax_proxy_cd": 0.020,
                            "first_pass_observed_clmax_proxy_cdp": 0.012,
                            "first_pass_observed_clmax_proxy_cm": -0.02,
                            "first_pass_observed_clmax_proxy_index": 28,
                            "first_pass_observed_clmax_proxy_at_sweep_edge": False,
                        },
                    }
                    for query in queries
                ],
            },
        )(),
        spanwise_loader=lambda concept, stations: {
            "root": {
                "points": [
                    {
                        "reynolds": 320000.0,
                        "cl_target": 0.62,
                        "cm_target": -0.02,
                        "weight": 1.0,
                        "station_y_m": 1.0,
                    }
                ]
            },
            "mid1": {
                "points": [
                    {
                        "reynolds": 290000.0,
                        "cl_target": 0.64,
                        "cm_target": -0.02,
                        "weight": 1.0,
                        "station_y_m": 4.0,
                    }
                ]
            },
            "mid2": {
                "points": [
                    {
                        "reynolds": 260000.0,
                        "cl_target": 0.66,
                        "cm_target": -0.02,
                        "weight": 1.0,
                        "station_y_m": 8.0,
                    }
                ]
            },
            "tip": {
                "points": [
                    {
                        "reynolds": 220000.0,
                        "cl_target": 0.68,
                        "cm_target": -0.02,
                        "weight": 1.0,
                        "station_y_m": 13.0,
                    }
                ]
            },
        },
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))

    assert len(summary["selected_concepts"]) == 3
    assert summary["evaluation_scope"]["enumerated_concept_count"] == 3
    assert summary["evaluation_scope"]["evaluated_concept_count"] == 3
    assert summary["selected_concepts"][0]["enumeration_index"] == 2
    assert summary["selected_concepts"][0]["rank"] == 1
    assert summary["selected_concepts"][1]["rank"] == 2
    assert summary["selected_concepts"][0]["mission"]["mission_objective_mode"] == "max_range"
    assert "mission_score" in summary["selected_concepts"][0]["mission"]
    assert "ranking" in summary["selected_concepts"][0]
    assert summary["selected_concepts"][0]["ranking"]["score"] <= summary["selected_concepts"][1]["ranking"]["score"]


def test_pipeline_excludes_safety_infeasible_concepts_from_selected_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    payload = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    payload["pipeline"]["keep_top_n"] = 2
    payload["output"]["export_candidate_bundle"] = False
    custom_cfg = tmp_path / "concept_safety_split.yaml"
    custom_cfg.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    safe_concept = GeometryConcept(
        span_m=30.0,
        wing_area_m2=60.0,
        root_chord_m=2.0,
        tip_chord_m=2.0,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(7.5, 7.5),
    )
    unsafe_concept = GeometryConcept(
        span_m=32.0,
        wing_area_m2=64.0,
        root_chord_m=2.0,
        tip_chord_m=2.0,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(8.0, 8.0),
    )
    backup_infeasible = GeometryConcept(
        span_m=34.0,
        wing_area_m2=68.0,
        root_chord_m=2.0,
        tip_chord_m=2.0,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(8.5, 8.5),
    )
    monkeypatch.setattr(
        concept_pipeline,
        "enumerate_geometry_concepts",
        lambda cfg: (safe_concept, unsafe_concept, backup_infeasible),
    )

    result = run_birdman_concept_pipeline(
        config_path=custom_cfg,
        output_dir=tmp_path / "out",
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {
                "backend_name": "test_stub",
                "run_queries": lambda self, queries: [
                    {
                        "status": "ok",
                        "template_id": query.template_id,
                        "polar_points": [
                            {
                                "cl_target": query.cl_samples[0],
                                "cl": query.cl_samples[0],
                                "cd": 0.020,
                                "cm": -0.02,
                                "converged": True,
                            }
                        ],
                        "sweep_summary": {
                            "cl_max_observed": 1.35 if query.reynolds >= 300000.0 else 1.05,
                            "converged_point_count": 10,
                            "sweep_point_count": 10,
                        },
                    }
                    for query in queries
                ],
            },
        )(),
        spanwise_loader=lambda concept, stations: {
            "root": {
                "points": [
                    {
                        "reynolds": 300000.0 if concept.span_m == 30.0 else 180000.0,
                        "cl_target": 0.60 if concept.span_m == 30.0 else (1.30 if concept.span_m == 32.0 else 1.35),
                        "cm_target": -0.02,
                        "weight": 1.0,
                        "station_y_m": 13.0,
                    }
                ]
            },
            "mid1": {"points": []},
            "mid2": {"points": []},
            "tip": {"points": []},
        },
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))

    assert [item["enumeration_index"] for item in summary["selected_concepts"]] == [1]
    assert summary["selected_concepts"][0]["local_stall"]["feasible"] is True
    assert [item["enumeration_index"] for item in summary["best_infeasible_concepts"]] == [2]
    assert summary["best_infeasible_concepts"][0]["local_stall"]["feasible"] is False
    assert summary["evaluation_scope"]["selected_concept_count"] == 1
    assert summary["evaluation_scope"]["best_infeasible_count"] == 1
    assert result.selected_concept_dirs == ()
    assert result.best_infeasible_concept_dirs == ()


def test_pipeline_falls_back_cleanly_when_spanwise_points_are_unavailable(
    tmp_path: Path,
) -> None:
    worker_call_lengths: list[int] = []

    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {
                "backend_name": "test_stub",
                "run_queries": lambda self, queries: worker_call_lengths.append(len(queries))
                or [],
            },
        )(),
        spanwise_loader=lambda concept, stations: {
            "root": {"points": []},
            "mid1": {"points": []},
            "mid2": {"points": []},
            "tip": {"points": []},
        },
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    first = _first_ranked_record(summary)

    assert worker_call_lengths
    assert all(length == 0 for length in worker_call_lengths)
    assert first["worker_result_count"] == 0
    assert first["worker_statuses"] == []
    assert first["airfoil_feedback"]["applied"] is False
    assert first["airfoil_feedback"]["mode"] == "geometry_proxy"
    assert isinstance(first["launch"]["cl_available"], float)
    assert isinstance(first["turn"]["cl_max"], float)
    assert isinstance(first["turn"]["load_factor"], float)
    assert isinstance(first["trim"]["margin_deg"], float)
    assert isinstance(first["trim"]["cm_rms"], float)
    assert isinstance(first["local_stall"]["min_margin"], float)
    assert isinstance(first["local_stall"]["required_cl"], float)
    assert first["launch"]["cl_available_source"] == "geometry_safe_proxy"
    assert first["turn"]["cl_max_source"] == "geometry_safe_proxy"
    assert first["trim"]["representative_cm_source"] == "zone_target_proxy"
    assert first["local_stall"]["margin_source"] == "geometry_safe_proxy"
    assert first["launch"]["status"] in {
        "ok",
        "launch_cl_insufficient",
        "trim_margin_insufficient",
    }
    assert first["turn"]["status"] in {
        "ok",
        "stall_utilization_exceeded",
        "trim_not_feasible",
    }
    assert first["trim"]["status"] in {"ok", "trim_margin_insufficient"}
    assert first["local_stall"]["status"] in {"ok", "stall_utilization_exceeded"}


def test_pipeline_default_worker_factory_uses_stubbed_ok_statuses(tmp_path: Path) -> None:
    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        spanwise_loader=lambda concept, stations: {
            "root": {
                "points": [
                    {
                        "reynolds": 350000.0,
                        "cl_target": 0.75,
                        "cm_target": -0.10,
                        "weight": 1.0,
                    }
                ]
            },
            "mid1": {"points": []},
            "mid2": {"points": []},
            "tip": {"points": []},
        },
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    assert summary["worker_backend"] == "python_stubbed"
    assert summary["worker_statuses"]
    assert all(status == "stubbed_ok" for status in summary["worker_statuses"])
    assert all(
        item["worker_statuses"] == ["stubbed_ok"]
        for item in summary["selected_concepts"]
    )
    assert all("launch" in item and "turn" in item for item in summary["selected_concepts"])


def test_pipeline_rejects_altitude_outside_tropospheric_density_range(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    payload = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    payload["environment"]["altitude_m"] = 12000.0

    custom_cfg = tmp_path / "concept_high_altitude.yaml"
    custom_cfg.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="environment.altitude_m"):
        run_birdman_concept_pipeline(
            config_path=custom_cfg,
            output_dir=tmp_path / "out",
            airfoil_worker_factory=lambda **_: type(
                "FakeWorker",
                (),
                {
                    "backend_name": "test_stub",
                    "run_queries": lambda self, queries: [
                        {"status": "ok", "polar_points": [], "template_id": query.template_id}
                        for query in queries
                    ],
                },
            )(),
            spanwise_loader=lambda concept, stations: {"root": {"points": []}},
        )


def test_pipeline_rejects_real_backend_selection_results_without_usable_metrics(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="unusable metrics"):
        run_birdman_concept_pipeline(
            config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
            output_dir=tmp_path,
            airfoil_worker_factory=lambda **_: type(
                "FakeWorker",
                (),
                {
                    "backend_name": "realish_backend",
                    "run_queries": lambda self, queries: [
                        {"status": "ok", "polar_points": [], "template_id": query.template_id}
                        for query in queries
                    ],
                },
            )(),
            spanwise_loader=lambda concept, stations: {
                "root": {
                    "points": [
                        {
                            "reynolds": 350000.0,
                            "cl_target": 0.75,
                            "cm_target": -0.10,
                            "weight": 1.0,
                        }
                    ]
                }
            },
        )


def test_pipeline_rejects_duplicate_selection_template_ids(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="duplicate template_id"):
        run_birdman_concept_pipeline(
            config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
            output_dir=tmp_path,
            airfoil_worker_factory=lambda **_: type(
                "FakeWorker",
                (),
                {
                    "backend_name": "test_stub",
                    "run_queries": lambda self, queries: [
                        {
                            "status": "ok",
                            "template_id": queries[0].template_id,
                            "geometry_hash": query.geometry_hash,
                            "mean_cd": 0.020,
                            "mean_cm": -0.10,
                            "usable_clmax": 1.20,
                        }
                        for query in queries
                    ],
                },
            )(),
            spanwise_loader=lambda concept, stations: {
                "root": {
                    "points": [
                        {
                            "reynolds": 350000.0,
                            "cl_target": 0.75,
                            "cm_target": -0.10,
                            "weight": 1.0,
                        }
                    ]
                }
            },
        )


def test_cli_smoke_writes_summary(tmp_path: Path) -> None:
    output_dir = tmp_path / "smoke"
    subprocess.run(
        [
            "../../.venv/bin/python",
            "scripts/birdman_upstream_concept_design.py",
            "--config",
            "configs/birdman_upstream_concept_baseline.yaml",
            "--output-dir",
            str(output_dir),
            "--worker-mode",
            "stubbed",
        ],
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    summary = json.loads((output_dir / "concept_summary.json").read_text(encoding="utf-8"))
    assert summary["worker_backend"] == "cli_stubbed"
    assert summary["selected_concepts"] or summary["best_infeasible_concepts"]


@pytest.mark.skipif(shutil.which("julia") is None, reason="Julia runtime not available")
def test_cli_smoke_can_use_real_julia_worker(tmp_path: Path) -> None:
    output_dir = tmp_path / "smoke_julia"
    subprocess.run(
        [
            "../../.venv/bin/python",
            "scripts/birdman_upstream_concept_design.py",
            "--config",
            "configs/birdman_upstream_concept_baseline.yaml",
            "--output-dir",
            str(output_dir),
            "--worker-mode",
            "julia",
        ],
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    summary = json.loads((output_dir / "concept_summary.json").read_text(encoding="utf-8"))
    assert summary["worker_backend"] == "julia_xfoil"
    assert summary["selected_concepts"] or summary["best_infeasible_concepts"]
    assert all(status in {"ok", "mini_sweep_fallback"} for status in summary["worker_statuses"])


def test_real_worker_backend_surfaces_as_julia_xfoil_without_running_julia(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    factory_calls: list[dict[str, object]] = []

    result = run_birdman_concept_pipeline(
        config_path=repo_root / "configs" / "birdman_upstream_concept_baseline.yaml",
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **kwargs: factory_calls.append(kwargs)
        or JuliaXFoilWorker(**kwargs),
        spanwise_loader=lambda concept, stations: {"root": {"points": []}},
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    assert factory_calls[0]["project_dir"] == repo_root
    assert summary["worker_backend"] == "julia_xfoil"
    assert all(item["worker_backend"] == "julia_xfoil" for item in summary["selected_concepts"])
    assert summary["worker_statuses"] == []


def test_pipeline_closes_worker_when_supported(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    closed = {"value": 0}

    class _ClosableWorker:
        backend_name = "test_stub"

        def run_queries(self, queries):
            return [
                {
                    "status": "ok",
                    "polar_points": [],
                    "template_id": query.template_id,
                    "reynolds": query.reynolds,
                    "cl_samples": list(query.cl_samples),
                    "roughness_mode": query.roughness_mode,
                    "geometry_hash": query.geometry_hash,
                }
                for query in queries
            ]

        def close(self):
            closed["value"] += 1

    result = run_birdman_concept_pipeline(
        config_path=repo_root / "configs" / "birdman_upstream_concept_baseline.yaml",
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **_: _ClosableWorker(),
        spanwise_loader=lambda concept, stations: {"root": {"points": []}},
    )

    assert result.summary_json_path.is_file()
    assert closed["value"] == 1


def test_pipeline_respects_yaml_controls_for_station_count_prop_and_vsp_exports(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    payload = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    payload["pipeline"]["stations_per_half"] = 9
    payload["pipeline"]["keep_top_n"] = 3
    payload["output"]["export_vsp"] = True
    payload["output"]["export_vsp_for_top_n"] = 2
    payload["prop"]["blade_count"] = 3
    payload["prop"]["diameter_m"] = 3.4
    payload["prop"]["rpm_min"] = 90.0
    payload["prop"]["rpm_max"] = 155.0

    custom_cfg = tmp_path / "concept.yaml"
    custom_cfg.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    result = run_birdman_concept_pipeline(
        config_path=custom_cfg,
        output_dir=tmp_path / "out",
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {
                "backend_name": "test_stub",
                "run_queries": lambda self, queries: [
                    {"status": "ok", "polar_points": [], "template_id": query.template_id}
                    for query in queries
                ],
            },
        )(),
        spanwise_loader=lambda concept, stations: {
            "root": {
                "points": [
                    {
                        "reynolds": 350000.0,
                        "cl_target": 0.75,
                        "cm_target": -0.10,
                        "weight": 1.0,
                    }
                ]
            },
            "mid1": {"points": []},
            "mid2": {"points": []},
            "tip": {"points": []},
        },
    )

    assert len(result.selected_concept_dirs) + len(result.best_infeasible_concept_dirs) == 3

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    ranked_records = summary["selected_concepts"] + summary["best_infeasible_concepts"]
    first_bundle = Path(ranked_records[0]["bundle_dir"])
    third_bundle = Path(ranked_records[2]["bundle_dir"])

    stations_csv = (first_bundle / "stations.csv").read_text(encoding="utf-8").strip().splitlines()
    assert len(stations_csv) == 10  # header + 9 stations
    assert stations_csv[0].split(",") == ["y_m", "chord_m", "twist_deg", "dihedral_deg"]

    prop_assumption = json.loads((first_bundle / "prop_assumption.json").read_text(encoding="utf-8"))
    assert prop_assumption["blade_count"] == 3
    assert prop_assumption["diameter_m"] == 3.4
    assert prop_assumption["rpm_range"] == [90.0, 155.0]

    assert (first_bundle / "concept_openvsp.vspscript").exists()
    assert (first_bundle / "concept_openvsp_metadata.json").exists()
    assert (third_bundle / "concept_openvsp.vspscript").exists() is False


def test_pipeline_skips_bundle_exports_when_candidate_bundle_output_is_disabled(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    payload = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    payload["output"]["export_candidate_bundle"] = False
    payload["output"]["export_vsp"] = False
    payload["output"]["export_vsp_for_top_n"] = 0

    custom_cfg = tmp_path / "concept_no_bundle.yaml"
    custom_cfg.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    result = run_birdman_concept_pipeline(
        config_path=custom_cfg,
        output_dir=tmp_path / "out",
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {
                "backend_name": "test_stub",
                "run_queries": lambda self, queries: [
                    {"status": "ok", "polar_points": [], "template_id": query.template_id}
                    for query in queries
                ],
            },
        )(),
        spanwise_loader=lambda concept, stations: {"root": {"points": []}},
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))

    assert result.selected_concept_dirs == ()
    assert not (tmp_path / "out" / "selected_concepts").exists()
    assert summary["selected_concepts"] or summary["best_infeasible_concepts"]
    assert all(item["bundle_dir"] is None for item in summary["selected_concepts"])
    assert all(item["bundle_dir"] is None for item in summary["best_infeasible_concepts"])


def test_pipeline_writes_dihedral_geometry_into_bundle_and_vsp_preview(tmp_path: Path) -> None:
    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {
                "backend_name": "test_stub",
                "run_queries": lambda self, queries: [],
            },
        )(),
        spanwise_loader=lambda concept, stations: {"root": {"points": []}},
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    bundle = _first_bundle_dir_from_summary(summary)
    concept_cfg = yaml.safe_load((bundle / "concept_config.yaml").read_text(encoding="utf-8"))
    stations_csv = (bundle / "stations.csv").read_text(encoding="utf-8")

    assert concept_cfg["geometry"]["dihedral_root_deg"] == 0.0
    assert concept_cfg["geometry"]["dihedral_tip_deg"] == 4.0
    assert concept_cfg["geometry"]["dihedral_exponent"] == 1.0
    assert "dihedral_deg" in stations_csv.splitlines()[0]
