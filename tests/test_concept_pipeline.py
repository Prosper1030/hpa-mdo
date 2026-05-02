from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import yaml
import pytest

from hpa_mdo.concept import load_concept_config
from hpa_mdo.concept import pipeline as concept_pipeline
from hpa_mdo.concept.airfoil_worker import (
    JuliaXFoilWorker,
    PolarQuery,
    geometry_hash_from_coordinates,
)
from hpa_mdo.concept.atmosphere import air_properties_from_environment
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


def test_openvsp_handoff_summary_reports_generated_vsp_paths(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "concept-01"
    bundle_dir.mkdir()
    script_path = bundle_dir / "concept_openvsp.vspscript"
    metadata_path = bundle_dir / "concept_openvsp_metadata.json"
    vsp3_path = bundle_dir / "concept_openvsp.vsp3"
    script_path.write_text("// vsp script\n", encoding="utf-8")
    vsp3_path.write_text("mock vsp3\n", encoding="utf-8")
    metadata_path.write_text(
        json.dumps(
            {
                "vsp3_build": {
                    "status": "written",
                    "path": str(vsp3_path),
                    "target_path": str(vsp3_path),
                }
            }
        ),
        encoding="utf-8",
    )

    summary = concept_pipeline._openvsp_handoff_summary(bundle_dir)

    assert summary == {
        "script_path": str(script_path),
        "metadata_path": str(metadata_path),
        "vsp3_path": str(vsp3_path),
        "vsp3_build_status": "written",
    }


def test_avl_oswald_efficiency_uses_cdi_formula_when_trim_totals_exist() -> None:
    concept = GeometryConcept(
        span_m=34.0,
        wing_area_m2=30.0,
        root_chord_m=1.3071895424836601,
        tip_chord_m=0.45751633986928103,
        twist_root_deg=2.0,
        twist_tip_deg=-2.0,
        dihedral_root_deg=1.0,
        dihedral_tip_deg=6.0,
        dihedral_exponent=1.5,
        tail_area_m2=3.0,
        cg_xc=0.30,
        segment_lengths_m=build_segment_plan(
            half_span_m=17.0,
            min_segment_length_m=1.0,
            max_segment_length_m=3.0,
        ),
    )
    station_points = [
        {
            "case_label": "reference_avl_case",
            "trim_cl": 0.90,
            "trim_cd_induced": 0.010,
            "trim_span_efficiency": 0.70,
        }
    ]

    summary = concept_pipeline._avl_oswald_efficiency_from_station_points(
        concept=concept,
        station_points=station_points,
    )

    expected_ar = 34.0**2 / 30.0
    assert summary is not None
    assert summary["efficiency"] == pytest.approx(0.90**2 / (3.141592653589793 * expected_ar * 0.010))
    assert summary["source"] == "avl_trim_force_totals_cdi_formula"
    assert summary["avl_reported_span_efficiency"] == pytest.approx(0.70)


def _load_concept_cli_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "birdman_upstream_concept_design.py"
    spec = importlib.util.spec_from_file_location("birdman_upstream_concept_design", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _load_fast_concept_payload() -> dict:
    payload = yaml.safe_load(
        Path("configs/birdman_upstream_concept_baseline.yaml").read_text(encoding="utf-8")
    )
    payload["geometry_family"]["sampling"]["sample_count"] = 6
    cst_search = payload.setdefault("cst_search", {})
    cst_search["seedless_sample_count"] = 32
    cst_search["seedless_max_oversample_factor"] = 8
    cst_search["robust_evaluation_enabled"] = False
    cst_search["nsga_generation_count"] = 1
    cst_search["nsga_offspring_count"] = 8
    cst_search["nsga_parent_count"] = 4
    cst_search["cma_es_enabled"] = False
    cst_search["cma_es_knee_count"] = 0
    cst_search["cma_es_iterations"] = 0
    return payload


def _write_fast_test_config(tmp_path: Path, *, filename: str = "fast_concept.yaml") -> Path:
    payload = _load_fast_concept_payload()
    config_path = tmp_path / filename
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return config_path


@pytest.mark.slow
def test_pipeline_writes_ranked_concept_summary(tmp_path: Path) -> None:
    factory_calls: list[dict[str, object]] = []
    loader_calls: list[tuple[str, int]] = []
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    config_path = _write_fast_test_config(tmp_path, filename="ranked_summary.yaml")

    class FakeWorker:
        backend_name = "test_stub"

        def run_queries(self, queries):
            return [
                {"status": "ok", "polar_points": [], "template_id": query.template_id}
                for query in queries
            ]

    result = run_birdman_concept_pipeline(
        config_path=config_path,
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
    assert 1 <= (
        len(result.selected_concept_dirs) + len(result.best_infeasible_concept_dirs)
    ) <= cfg.pipeline.keep_top_n
    assert factory_calls
    assert factory_calls[0]["project_dir"] == Path(__file__).resolve().parents[1]
    assert factory_calls[0]["cache_dir"] == tmp_path / "polar_db"
    assert factory_calls[0]["persistent_worker_count"] == 4
    assert factory_calls[0]["xfoil_max_iter"] == 40
    assert factory_calls[0]["xfoil_panel_count"] == 96

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    ranked_pool = json.loads((tmp_path / "concept_ranked_pool.json").read_text(encoding="utf-8"))
    frontier_summary = json.loads((tmp_path / "frontier_summary.json").read_text(encoding="utf-8"))
    first = _first_ranked_record(summary)
    assert len(loader_calls) == summary["evaluation_scope"]["evaluated_concept_count"]
    assert summary["worker_backend"] == "test_stub"
    assert summary["worker_statuses"]
    assert all(status == "ok" for status in summary["worker_statuses"])
    expected_air = air_properties_from_environment(
        temperature_c=33.0,
        relative_humidity_percent=80.0,
        altitude_m=0.0,
    )
    assert summary["environment_air_properties"]["density_kg_per_m3"] == pytest.approx(
        expected_air.density_kg_per_m3
    )
    assert summary["environment_air_properties"]["dynamic_viscosity_pa_s"] == pytest.approx(
        expected_air.dynamic_viscosity_pa_s
    )
    assert summary["artifact_trust"]["decision_grade"] is False
    assert summary["artifact_trust"]["decision_grade_status"] == "diagnostic_only"
    assert "stub_worker_detected" in summary["artifact_trust"]["not_decision_grade_reasons"]
    assert len(summary["artifact_trust"]["config_sha256"]) == 64
    assert ranked_pool["artifact_trust"]["decision_grade"] is False
    assert summary["polar_worker"]["persistent_worker_count"] == 4
    assert summary["polar_worker"]["cache_statistics"] is None
    assert len(ranked_pool["ranked_pool"]) == summary["evaluation_scope"]["evaluated_concept_count"]
    assert ranked_pool["ranked_pool"][0]["overall_rank"] == 1
    assert frontier_summary["counts"]["evaluated_count"] == summary["evaluation_scope"]["evaluated_concept_count"]
    assert "top_ranked" in frontier_summary["failure_gate_counts"]
    assert "top_ranked" in frontier_summary["geometry_subsets"]
    assert summary["evaluation_scope"]["selection_scope"] == "ranked_sampled_pool"
    assert summary["evaluation_scope"]["geometry_primary_variables"] == [
        "span_m",
        "mean_chord_m",
        "taper_ratio",
        "twist_mid_deg",
        "twist_outer_deg",
        "tip_twist_deg",
        "spanload_bias",
    ]
    assert (
        summary["evaluation_scope"]["geometry_sampling"]["accepted_concept_count"]
        == summary["evaluation_scope"]["enumerated_concept_count"]
    )
    assert first["worker_backend"] == "test_stub"
    assert first["artifact_trust"]["decision_grade"] is False
    assert "stub_worker_detected" in first["artifact_trust"]["not_decision_grade_reasons"]
    assert first["worker_statuses"] == ["ok", "ok", "ok", "ok"]
    assert first["wing_area_source"] == "derived_from_mean_chord_m"
    assert isinstance(first["wing_loading_target_Npm2"], float)
    assert isinstance(first["mean_aerodynamic_chord_m"], float)
    assert first["primary_variables"]["mean_chord_m"] == pytest.approx(
        first["wing_area_m2"] / first["span_m"]
    )
    assert isinstance(first["primary_variables"]["twist_mid_deg"], float)
    assert isinstance(first["primary_variables"]["twist_outer_deg"], float)
    assert isinstance(first["primary_variables"]["spanload_bias"], float)
    assert first["derived_geometry"]["wing_area_source"] == first["wing_area_source"]
    assert first["derived_geometry"]["wing_area_m2"] == pytest.approx(first["wing_area_m2"])
    assert first["derived_geometry"]["tail_area_source"] == "derived_from_tail_volume_coefficient"
    assert isinstance(first["derived_geometry"]["tail_volume_coefficient"], float)
    assert first["tail_area_m2"] == pytest.approx(
        first["derived_geometry"]["tail_volume_coefficient"]
        * first["wing_area_m2"]
        / cfg.tail_model.tail_arm_to_mac
    )
    assert len(first["derived_geometry"]["twist_control_points"]) == 4
    assert isinstance(first["derived_geometry"]["tip_deflection_m_at_design_mass"], float)
    assert isinstance(first["derived_geometry"]["effective_dihedral_deg_at_design_mass"], float)
    assert first["derived_geometry"]["tip_deflection_preferred_status"] in {
        "below_preferred",
        "within_preferred",
        "above_preferred",
    }
    assert "launch" in first
    assert "turn" in first
    assert "trim" in first
    assert "local_stall" in first
    assert "spanwise_requirements" in first
    assert first["mission"]["pilot_power_model"] == "csv_power_curve"
    assert ".csv" in first["mission"]["pilot_power_anchor"]
    assert first["mission"]["pilot_power_thermal_adjustment"]["enabled"] is True
    assert first["mission"]["pilot_power_thermal_adjustment"]["test_environment"][
        "temperature_c"
    ] == pytest.approx(26.0)
    assert first["mission"]["pilot_power_thermal_adjustment"]["target_environment"][
        "relative_humidity_percent"
    ] == pytest.approx(80.0)
    assert first["mission"]["pilot_power_thermal_adjustment"]["power_factor"] < 1.0
    assert first["mission"]["oswald_efficiency_source"] in {
        "spanload_shape_proxy_v1",
        "concept_geometry_proxy_v1",
    }
    assert first["mission"]["spanload_rms_error"] is None or isinstance(
        first["mission"]["spanload_rms_error"],
        float,
    )
    assert isinstance(first["launch"]["cl_required"], float)
    assert isinstance(first["turn"]["required_cl"], float)
    assert isinstance(first["trim"]["margin_deg"], float)
    assert isinstance(first["local_stall"]["min_margin"], float)


@pytest.mark.slow
def test_pipeline_reruns_top_finalists_with_full_alpha_sweep(tmp_path: Path) -> None:
    config_payload = _load_fast_concept_payload()
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


@pytest.mark.slow
def test_pipeline_summary_distinguishes_screening_and_finalist_worker_fidelity(
    tmp_path: Path,
) -> None:
    config_payload = _load_fast_concept_payload()
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


@pytest.mark.slow
def test_pipeline_reruns_finalists_with_post_airfoil_avl_reference_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_payload = _load_fast_concept_payload()
    config_payload["pipeline"]["keep_top_n"] = 3
    config_payload["pipeline"]["finalist_full_sweep_top_l"] = 1
    config_path = tmp_path / "post_airfoil_rerun.yaml"
    config_path.write_text(yaml.safe_dump(config_payload, sort_keys=False), encoding="utf-8")
    cfg = load_concept_config(config_path)
    rerun_calls: list[dict[str, object]] = []

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

    def base_loader(_concept, _stations):
        return {
            "root": {
                "source": "avl_strip_forces",
                "reference_speed_mps": 6.0,
                "reference_gross_mass_kg": 105.0,
                "reference_speed_reason": "proxy_reference_speed",
                "mass_selection_reason": "proxy_mass_case",
                "reference_condition_policy": "proxy_reference_policy",
                "design_cases": [],
                "points": [
                    {
                        "reynolds": 260000.0,
                        "chord_m": 1.30,
                        "cl_target": 0.54,
                        "cm_target": -0.10,
                        "weight": 1.0,
                        "case_label": "reference_avl_case",
                        "evaluation_speed_mps": 6.0,
                        "evaluation_gross_mass_kg": 105.0,
                    }
                ],
            },
            "mid1": {
                "points": [
                    {
                        "reynolds": 240000.0,
                        "chord_m": 1.15,
                        "cl_target": 0.50,
                        "cm_target": -0.09,
                        "weight": 1.0,
                        "case_label": "reference_avl_case",
                        "evaluation_speed_mps": 6.0,
                        "evaluation_gross_mass_kg": 105.0,
                    }
                ]
            },
            "mid2": {
                "points": [
                    {
                        "reynolds": 220000.0,
                        "chord_m": 1.00,
                        "cl_target": 0.46,
                        "cm_target": -0.08,
                        "weight": 1.0,
                        "case_label": "reference_avl_case",
                        "evaluation_speed_mps": 6.0,
                        "evaluation_gross_mass_kg": 105.0,
                    }
                ]
            },
            "tip": {
                "points": [
                    {
                        "reynolds": 200000.0,
                        "chord_m": 0.82,
                        "cl_target": 0.42,
                        "cm_target": -0.07,
                        "weight": 1.0,
                        "case_label": "reference_avl_case",
                        "evaluation_speed_mps": 6.0,
                        "evaluation_gross_mass_kg": 105.0,
                    }
                ]
            },
        }

    setattr(
        base_loader,
        "_birdman_avl_rerun_context",
        {
            "cfg": cfg,
            "working_root": tmp_path / "avl_rerun",
            "avl_binary": None,
        },
    )

    def fake_load_zone_requirements_from_avl(**kwargs):
        rerun_calls.append(kwargs)
        return {
            "root": {
                "source": "avl_strip_forces",
                "reference_speed_mps": float(kwargs["reference_condition_override"]["reference_speed_mps"]),
                "reference_gross_mass_kg": float(
                    kwargs["reference_condition_override"]["reference_gross_mass_kg"]
                ),
                "reference_speed_reason": str(
                    kwargs["reference_condition_override"]["reference_speed_reason"]
                ),
                "mass_selection_reason": str(
                    kwargs["reference_condition_override"]["mass_selection_reason"]
                ),
                "reference_condition_policy": "post_airfoil_feasible_reference_avl_rerun_v1",
                "design_cases": [
                    {
                        "case_label": "reference_avl_case",
                        "evaluation_speed_mps": float(
                            kwargs["reference_condition_override"]["reference_speed_mps"]
                        ),
                        "evaluation_gross_mass_kg": float(
                            kwargs["reference_condition_override"]["reference_gross_mass_kg"]
                        ),
                        "load_factor": 1.0,
                        "case_weight": 0.35,
                        "speed_reason": str(
                            kwargs["reference_condition_override"]["reference_speed_reason"]
                        ),
                        "mass_reason": str(
                            kwargs["reference_condition_override"]["mass_selection_reason"]
                        ),
                        "case_reason": "post_airfoil_finalist_reference_case",
                    }
                ],
                "points": [
                    {
                        "reynolds": 260000.0,
                        "chord_m": 1.30,
                        "cl_target": 0.50,
                        "cm_target": -0.10,
                        "weight": 1.0,
                        "case_label": "reference_avl_case",
                        "evaluation_speed_mps": float(
                            kwargs["reference_condition_override"]["reference_speed_mps"]
                        ),
                        "evaluation_gross_mass_kg": float(
                            kwargs["reference_condition_override"]["reference_gross_mass_kg"]
                        ),
                    }
                ],
            },
            "mid1": {"points": []},
            "mid2": {"points": []},
            "tip": {"points": []},
        }

    monkeypatch.setattr(
        concept_pipeline,
        "load_zone_requirements_from_avl",
        fake_load_zone_requirements_from_avl,
        raising=False,
    )
    monkeypatch.setattr(
        concept_pipeline,
        "_should_iterate_post_airfoil_avl_reference",
        lambda **_: False,
    )

    result = run_birdman_concept_pipeline(
        config_path=config_path,
        output_dir=tmp_path / "out",
        airfoil_worker_factory=lambda **_: FakeWorker(),
        spanwise_loader=base_loader,
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    first = _first_ranked_record(summary)

    assert len(rerun_calls) == 1
    assert rerun_calls[0]["case_tag"] == "finalist_post_airfoil_avl_rerun_iter01"
    assert rerun_calls[0]["reference_condition_override"] is not None
    assert set(rerun_calls[0]["airfoil_templates"]) == {"root", "mid1", "mid2", "tip"}
    assert first["spanwise_requirements"]["reference_condition_policies"] == [
        "post_airfoil_feasible_reference_avl_rerun_v1"
    ]


def test_should_iterate_post_airfoil_avl_reference_only_for_speed_mismatch() -> None:
    assert concept_pipeline._should_iterate_post_airfoil_avl_reference(
        consistency_audit={
            "rerun_recommended": True,
            "rerun_reasons": ["reference_speed_delta_exceeds_1mps"],
        },
        rerun_iteration_count=1,
    )
    assert not concept_pipeline._should_iterate_post_airfoil_avl_reference(
        consistency_audit={
            "rerun_recommended": True,
            "rerun_reasons": ["pre_avl_feasible_range_ratio_out_of_family"],
        },
        rerun_iteration_count=1,
    )
    assert not concept_pipeline._should_iterate_post_airfoil_avl_reference(
        consistency_audit={
            "rerun_recommended": True,
            "rerun_reasons": ["reference_speed_delta_exceeds_1mps"],
        },
        rerun_iteration_count=2,
    )


@pytest.mark.slow
def test_pipeline_can_take_second_post_airfoil_avl_rerun_when_reference_still_shifts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_payload = _load_fast_concept_payload()
    config_payload["pipeline"]["keep_top_n"] = 3
    config_payload["pipeline"]["finalist_full_sweep_top_l"] = 1
    config_path = tmp_path / "post_airfoil_rerun_iterative.yaml"
    config_path.write_text(yaml.safe_dump(config_payload, sort_keys=False), encoding="utf-8")
    cfg = load_concept_config(config_path)
    rerun_calls: list[dict[str, object]] = []

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

    def base_loader(_concept, _stations):
        return {
            "root": {
                "source": "avl_strip_forces",
                "reference_speed_mps": 6.0,
                "reference_gross_mass_kg": 105.0,
                "reference_speed_reason": "proxy_reference_speed",
                "mass_selection_reason": "proxy_mass_case",
                "reference_condition_policy": "proxy_reference_policy",
                "design_cases": [],
                "points": [
                    {
                        "reynolds": 260000.0,
                        "chord_m": 1.30,
                        "cl_target": 0.54,
                        "cm_target": -0.10,
                        "weight": 1.0,
                        "case_label": "reference_avl_case",
                        "evaluation_speed_mps": 6.0,
                        "evaluation_gross_mass_kg": 105.0,
                    }
                ],
            },
            "mid1": {"points": []},
            "mid2": {"points": []},
            "tip": {"points": []},
        }

    setattr(
        base_loader,
        "_birdman_avl_rerun_context",
        {
            "cfg": cfg,
            "working_root": tmp_path / "avl_rerun",
            "avl_binary": None,
        },
    )

    def fake_load_zone_requirements_from_avl(**kwargs):
        rerun_calls.append(kwargs)
        reference_speed_mps = float(kwargs["reference_condition_override"]["reference_speed_mps"])
        return {
            "root": {
                "source": "avl_strip_forces",
                "reference_speed_mps": reference_speed_mps,
                "reference_gross_mass_kg": float(
                    kwargs["reference_condition_override"]["reference_gross_mass_kg"]
                ),
                "reference_speed_reason": str(
                    kwargs["reference_condition_override"]["reference_speed_reason"]
                ),
                "mass_selection_reason": str(
                    kwargs["reference_condition_override"]["mass_selection_reason"]
                ),
                "reference_condition_policy": "post_airfoil_feasible_reference_avl_rerun_v1",
                "design_cases": [],
                "points": [
                    {
                        "reynolds": 260000.0,
                        "chord_m": 1.30,
                        "cl_target": 0.50 if len(rerun_calls) == 1 else 0.46,
                        "cm_target": -0.10,
                        "weight": 1.0,
                        "case_label": "reference_avl_case",
                        "evaluation_speed_mps": reference_speed_mps,
                        "evaluation_gross_mass_kg": float(
                            kwargs["reference_condition_override"]["reference_gross_mass_kg"]
                        ),
                    }
                ],
            },
            "mid1": {"points": []},
            "mid2": {"points": []},
            "tip": {"points": []},
        }

    monkeypatch.setattr(
        concept_pipeline,
        "load_zone_requirements_from_avl",
        fake_load_zone_requirements_from_avl,
        raising=False,
    )
    monkeypatch.setattr(
        concept_pipeline,
        "_should_iterate_post_airfoil_avl_reference",
        lambda **kwargs: int(kwargs["rerun_iteration_count"]) == 1,
    )

    run_birdman_concept_pipeline(
        config_path=config_path,
        output_dir=tmp_path / "out",
        airfoil_worker_factory=lambda **_: FakeWorker(),
        spanwise_loader=base_loader,
    )

    assert len(rerun_calls) == 2
    assert [call["case_tag"] for call in rerun_calls] == [
        "finalist_post_airfoil_avl_rerun_iter01",
        "finalist_post_airfoil_avl_rerun_iter02",
    ]


@pytest.mark.slow
def test_pipeline_falls_back_when_post_airfoil_rerun_has_no_feasible_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_payload = _load_fast_concept_payload()
    config_payload["pipeline"]["keep_top_n"] = 3
    config_payload["pipeline"]["finalist_full_sweep_top_l"] = 1
    config_path = tmp_path / "post_airfoil_rerun_fallback.yaml"
    config_path.write_text(yaml.safe_dump(config_payload, sort_keys=False), encoding="utf-8")
    cfg = load_concept_config(config_path)
    rerun_calls: list[dict[str, object]] = []

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

    def base_loader(_concept, _stations):
        return {
            "root": {
                "source": "avl_strip_forces",
                "reference_speed_mps": 6.0,
                "reference_gross_mass_kg": 105.0,
                "reference_speed_reason": "proxy_reference_speed",
                "mass_selection_reason": "proxy_mass_case",
                "reference_condition_policy": "proxy_reference_policy",
                "design_cases": [],
                "points": [
                    {
                        "reynolds": 260000.0,
                        "chord_m": 1.30,
                        "cl_target": 0.54,
                        "cm_target": -0.10,
                        "weight": 1.0,
                        "case_label": "reference_avl_case",
                        "evaluation_speed_mps": 6.0,
                        "evaluation_gross_mass_kg": 105.0,
                    }
                ],
            },
            "mid1": {"points": []},
            "mid2": {"points": []},
            "tip": {"points": []},
        }

    setattr(
        base_loader,
        "_birdman_avl_rerun_context",
        {
            "cfg": cfg,
            "working_root": tmp_path / "avl_rerun",
            "avl_binary": None,
        },
    )

    monkeypatch.setattr(
        concept_pipeline,
        "load_zone_requirements_from_avl",
        lambda **kwargs: rerun_calls.append(kwargs) or {"root": {"points": []}},
        raising=False,
    )
    monkeypatch.setattr(
        concept_pipeline,
        "_post_airfoil_reference_condition_override",
        lambda **_: None,
    )

    fake_worker = FakeWorker()
    result = run_birdman_concept_pipeline(
        config_path=config_path,
        output_dir=tmp_path / "out",
        airfoil_worker_factory=lambda **_: fake_worker,
        spanwise_loader=base_loader,
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    first = _first_ranked_record(summary)

    assert rerun_calls == []
    assert first["worker_fidelity"]["finalist"]["worker_analysis_modes"]
    assert all(
        mode == "full_alpha_sweep"
        for mode in first["worker_fidelity"]["finalist"]["worker_analysis_modes"]
    )
    assert fake_worker.batches


@pytest.mark.slow
def test_pipeline_batches_screening_candidate_selection_across_concepts(
    tmp_path: Path,
) -> None:
    config_payload = _load_fast_concept_payload()
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


@pytest.mark.slow
def test_pipeline_records_spanwise_requirement_source_in_summary(tmp_path: Path) -> None:
    config_path = _write_fast_test_config(tmp_path, filename="spanwise_source.yaml")
    result = run_birdman_concept_pipeline(
        config_path=config_path,
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


@pytest.mark.slow
def test_pipeline_records_reference_condition_metadata_in_spanwise_summary(
    tmp_path: Path,
) -> None:
    config_path = _write_fast_test_config(tmp_path, filename="reference_metadata.yaml")
    result = run_birdman_concept_pipeline(
        config_path=config_path,
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


def test_spanwise_summary_flags_reference_condition_consistency_mismatch() -> None:
    zone_requirements = {
        "root": {
            "source": "avl_strip_forces",
            "reference_condition_policy": "low_speed_primary_multipoint_design_cases_v4_feasible_reference_proxy",
            "reference_speed_filter_model": "pre_avl_local_stall_feasible_speed_proxy_v1",
            "reference_speed_mps": 10.0,
            "reference_gross_mass_kg": 105.0,
            "reference_speed_reason": "best_range_feasible_speed_mps",
            "mass_selection_reason": "min_best_range_feasible_m",
            "pre_avl_best_range_m": 19608.3,
            "pre_avl_best_range_feasible_m": 1205.95,
            "pre_avl_best_range_speed_mps": 6.0,
            "pre_avl_best_range_feasible_speed_mps": 10.0,
            "pre_avl_feasible_speed_set_mps": [9.5, 10.0],
            "design_cases": [{"case_label": "reference_avl_case"}],
            "points": [{"reynolds": 350000.0, "cl_target": 0.75, "cm_target": -0.10, "weight": 1.0}],
        },
        "mid1": {"source": "avl_strip_forces", "points": []},
        "mid2": {"source": "avl_strip_forces", "points": []},
        "tip": {"source": "avl_strip_forces", "points": []},
    }
    mission_summary = {
        "best_range_m": 16856.2,
        "best_range_speed_mps": 7.0,
        "best_range_unconstrained_m": 23882.5,
        "best_range_unconstrained_speed_mps": 6.0,
        "first_feasible_speed_mps": 7.0,
        "feasible_speed_set_mps": [7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0],
    }

    spanwise_summary = concept_pipeline._summarize_spanwise_requirements(
        zone_requirements,
        mission_summary,
    )

    assert spanwise_summary["reference_speed_filter_models"] == [
        "pre_avl_local_stall_feasible_speed_proxy_v1"
    ]
    audit = spanwise_summary["reference_condition_consistency_audit"]
    assert audit["pre_avl_reference_speed_mps"] == pytest.approx(10.0)
    assert audit["post_airfoil_first_feasible_speed_mps"] == pytest.approx(7.0)
    assert audit["reference_speed_in_post_airfoil_feasible_set"] is True
    assert audit["delta_reference_to_post_airfoil_first_feasible_mps"] == pytest.approx(3.0)
    assert audit["pre_avl_to_post_airfoil_feasible_range_ratio"] == pytest.approx(
        1205.95 / 16856.2
    )
    assert audit["rerun_recommended"] is True
    assert "reference_speed_delta_exceeds_1mps" in audit["rerun_reasons"]
    assert "pre_avl_feasible_range_ratio_out_of_family" in audit["rerun_reasons"]


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


@pytest.mark.slow
def test_pipeline_uses_cst_selected_airfoil_templates(tmp_path: Path) -> None:
    config_path = _write_fast_test_config(tmp_path, filename="cst_selected_templates.yaml")
    result = run_birdman_concept_pipeline(
        config_path=config_path,
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


@pytest.mark.slow
def test_pipeline_emits_all_required_mvp_artifacts(tmp_path: Path) -> None:
    config_path = _write_fast_test_config(tmp_path, filename="mvp_artifacts.yaml")
    result = run_birdman_concept_pipeline(
        config_path=config_path,
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
    assert concept_summary["local_stall"]["status"] in {
        "ok",
        "stall_utilization_exceeded",
        "beyond_safe_clmax",
        "beyond_raw_clmax",
    }
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


@pytest.mark.slow
def test_pipeline_uses_airfoil_derived_spanwise_values_when_available(
    tmp_path: Path,
) -> None:
    config_path = _write_fast_test_config(tmp_path, filename="airfoil_derived_spanwise.yaml")
    result = run_birdman_concept_pipeline(
        config_path=config_path,
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

    assert first["launch"]["gross_mass_kg"] == pytest.approx(first["mission"]["evaluated_gross_mass_kg"])
    assert first["launch"]["cl_available_source"] == "airfoil_safe_lower_bound"
    assert first["turn"]["cl_max_source"] == "airfoil_safe_lower_bound"
    assert first["trim"]["representative_cm_source"] == "airfoil_near_target"
    assert first["local_stall"]["margin_source"] == "airfoil_safe_lower_bound"
    assert first["airfoil_feedback"]["applied"] is True
    assert first["airfoil_feedback"]["usable_worker_point_count"] == 4
    assert first["airfoil_feedback"]["mean_cd_effective"] == pytest.approx(0.021)
    assert first["airfoil_feedback"]["min_cl_max_effective"] == pytest.approx(1.24)
    assert first["airfoil_feedback"]["safe_clmax_model"] == "safe_clmax_model_v2"
    assert first["airfoil_feedback"]["max_tip_3d_penalty"] > 0.0
    assert first["airfoil_feedback"]["min_cl_max_safe"] < first["airfoil_feedback"]["min_cl_max_effective"]
    assert first["turn"]["cl_level"] == pytest.approx(0.87)
    assert first["turn"]["limiting_station_y_m"] == pytest.approx(14.0)
    assert first["turn"]["tip_critical"] is True
    assert first["trim"]["representative_cm"] == pytest.approx(-0.08)
    assert first["trim"]["cm_rms"] == pytest.approx(0.0)
    assert first["launch"]["cl_available"] == pytest.approx(first["airfoil_feedback"]["min_cl_max_safe"])
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

    design_mass_kg = cfg.mass.design_gross_mass_kg
    cl_scale = (design_mass_kg / 95.0) * (6.0 / 8.0) ** 2
    assert turn["status"] == "ok"
    assert turn["cl_level"] == pytest.approx(cl_scale)
    assert turn["required_cl"] == pytest.approx(cl_scale / 0.9659258262890683)
    assert turn["cl_scale_factor_min"] == pytest.approx(cl_scale)
    assert turn["cl_scale_factor_max"] == pytest.approx(cl_scale)
    assert turn["reference_speed_mps"] == pytest.approx(6.0)
    assert turn["reference_gross_mass_kg"] == pytest.approx(95.0)
    assert turn["evaluation_gross_mass_kg"] == pytest.approx(design_mass_kg)
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


def test_mission_summary_emits_slow_speed_report_payload_when_configured() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    # Baseline carries slow_report_speeds_mps=[6.0]; assert that propagates.
    assert cfg.mission.slow_report_speeds_mps == (6.0,)
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
    summary = concept_pipeline._build_concept_mission_summary(
        cfg=cfg,
        concept=concept,
        station_points=station_points,
        airfoil_feedback={"mean_cd_effective": 0.021},
        trim_summary={"tail_cl_required": 0.10},
        air_density_kg_per_m3=1.15,
    )
    slow_report = summary["slow_speed_report"]
    assert slow_report["model"] == "slow_speed_drag_power_proxy_v1_report_only"
    assert slow_report["evaluation_gross_mass_kg"] > 0.0
    assert len(slow_report["speeds"]) == 1
    slow_entry = slow_report["speeds"][0]
    assert slow_entry["speed_mps"] == pytest.approx(6.0)
    # CL_required at 6 m/s should stay above the active cruise sweep window.
    cruise_min_speed_mps = float(min(summary["speed_sweep_window_mps"]))
    assert cruise_min_speed_mps >= 6.4
    assert slow_entry["cl_required"] > 0.0
    # Power required for the slow case should be a positive shaft power.
    assert slow_entry["shaft_power_required_w"] > 0.0
    # delta_v should be negative (slow speed < cruise best-range speed).
    if slow_entry["delta_v_from_best_range_mps"] is not None:
        assert slow_entry["delta_v_from_best_range_mps"] < 0.0


def test_mission_summary_pedal_power_exceeds_shaft_power_by_drivetrain_factor() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    assert cfg.drivetrain.efficiency < 1.0
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
    summary = concept_pipeline._build_concept_mission_summary(
        cfg=cfg,
        concept=concept,
        station_points=station_points,
        airfoil_feedback={"mean_cd_effective": 0.021},
        trim_summary={"tail_cl_required": 0.10},
        air_density_kg_per_m3=1.15,
    )
    assert summary["drivetrain_efficiency"] == pytest.approx(cfg.drivetrain.efficiency)
    propulsion_assumptions = summary["propulsion_efficiency_assumptions"]
    assert propulsion_assumptions["eta_prop_design"] == pytest.approx(0.86)
    assert propulsion_assumptions["eta_transmission"] == pytest.approx(0.96)
    assert propulsion_assumptions["eta_total_design"] == pytest.approx(0.86 * 0.96)
    assert propulsion_assumptions["prop_design_space"]["diameter_m"] == pytest.approx(
        cfg.prop.diameter_m
    )
    assert propulsion_assumptions["prop_design_space"]["rpm_min"] == pytest.approx(
        cfg.prop.rpm_min
    )
    assert propulsion_assumptions["prop_design_space"]["rpm_max"] == pytest.approx(
        cfg.prop.rpm_max
    )
    mass_case = summary["mass_cases"][0]
    shaft_list = list(mass_case["shaft_power_required_w_by_speed"])
    pedal_list = list(mass_case["pedal_power_required_w_by_speed"])
    assert len(shaft_list) == len(pedal_list)
    assert all(p > s > 0.0 for p, s in zip(pedal_list, shaft_list))
    expected_factor = 1.0 / cfg.drivetrain.efficiency
    for shaft_w, pedal_w in zip(shaft_list, pedal_list):
        assert pedal_w == pytest.approx(shaft_w * expected_factor, rel=1e-9)


def test_mission_summary_slow_speed_report_is_empty_when_no_speeds_configured() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    cfg.mission.slow_report_speeds_mps = ()
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
    summary = concept_pipeline._build_concept_mission_summary(
        cfg=cfg,
        concept=concept,
        station_points=station_points,
        airfoil_feedback={"mean_cd_effective": 0.021},
        trim_summary={"tail_cl_required": 0.10},
        air_density_kg_per_m3=1.15,
    )
    assert summary["slow_speed_report"]["speeds"] == []


def test_launch_summary_uses_vstall_primary_gate_and_tracks_ground_effect_sensitivity() -> None:
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

    launch, _, _ = concept_pipeline._summarize_launch(
        cfg=cfg,
        concept=concept,
        station_points=[
            {
                "station_y_m": 4.0,
                "cl_target": 0.82,
                "cl_max_safe": 1.15,
                "cl_max_safe_source": "airfoil_safe_observed",
                "case_label": "launch_release_case",
            }
        ],
        trim_result=type("TrimResult", (), {"feasible": True, "margin_deg": 3.0})(),
        air_density_kg_per_m3=1.15,
    )

    assert launch["model"] == "vstall_margin_primary_with_ground_effect_sensitivity"
    assert launch["ground_effect_applied"] is False
    assert launch["ground_effect_sensitivity_enabled"] is True
    assert launch["ground_effect_sensitivity_adjusted_cl_required"] < launch["cl_required"]
    assert launch["ground_effect_sensitivity_stall_utilization"] < launch["stall_utilization"]
    assert launch["ground_effect_sensitivity_status"] in {
        "ok",
        "launch_cl_insufficient",
        "launch_stall_utilization_exceeded",
        "trim_margin_insufficient",
    }


def test_mission_summary_filters_best_range_to_feasible_speeds() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    cfg.mission.objective_mode = "max_range"
    cfg.rigging_drag.enabled = False
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

    mission = concept_pipeline._build_concept_mission_summary(
        cfg=cfg,
        concept=concept,
        station_points=[
            {
                "station_y_m": 4.0,
                "chord_m": 1.0,
                "weight": 1.0,
                "cl_target": 0.60,
                "cm_target": -0.05,
                "cl_max_safe": 1.0,
                "cl_max_safe_source": "airfoil_safe_observed",
                "case_label": "reference_avl_case",
                "evaluation_speed_mps": 8.0,
                "evaluation_gross_mass_kg": 105.0,
                "reference_speed_mps": 8.0,
                "reference_gross_mass_kg": 105.0,
            }
        ],
        airfoil_feedback={},
        trim_summary={"tail_cl_required": 0.0},
        air_density_kg_per_m3=1.15,
    )

    assert mission["best_range_unconstrained_speed_mps"] == pytest.approx(6.4)
    assert mission["best_range_speed_mps"] == pytest.approx(7.0)
    assert mission["best_range_m"] < mission["best_range_unconstrained_m"]
    assert len(mission["power_margin_w_by_speed"]) == len(mission["power_required_w"])
    assert mission["best_power_margin_unconstrained_w"] == pytest.approx(
        max(mission["power_margin_w_by_speed"])
    )
    assert mission["best_power_margin_w"] is not None
    assert mission["feasible_speed_set_mps"] == pytest.approx([7.0, 7.2])
    assert mission["operating_point_status"] == "filtered_to_feasible_speeds"
    assert mission["delta_v_to_first_feasible_mps"] == pytest.approx(0.6)
    assert mission["worst_case_evaluated_gross_mass_kg"] == pytest.approx(106.0)
    assert mission["mass_cases"][-1]["feasible_speed_set_mps"] == pytest.approx([7.2])


def test_sizing_diagnostics_report_area_mass_closure_without_resizing_concept() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))
    concept = GeometryConcept(
        span_m=34.7,
        wing_area_m2=48.6,
        root_chord_m=48.6 / 34.7,
        tip_chord_m=48.6 / 34.7,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=4.0,
        cg_xc=0.30,
        segment_lengths_m=(8.675, 8.675),
        wing_loading_target_Npm2=21.187,
        design_gross_mass_kg=105.0,
    )

    diagnostics = concept_pipeline._sizing_diagnostics(cfg, concept)
    closure = diagnostics["area_mass_closure"]

    assert diagnostics["sizing_archetype"] == "low_speed_large_area_artifact_risk"
    assert closure["model"] == "area_mass_closure_v1_report_only"
    assert closure["model_authority"] == "unvalidated_first_order_accounting_proxy"
    assert "not_a_structural_sizing_authority" in closure["limitations"]
    assert closure["closed_wing_area_m2"] > concept.wing_area_m2
    assert closure["closed_gross_mass_kg"] > cfg.mass.design_gross_mass_kg
    assert closure["closed_aircraft_empty_mass_kg"] == pytest.approx(
        closure["closed_gross_mass_kg"] - cfg.mass.design_pilot_mass_kg
    )
    assert closure["aircraft_empty_mass_target_range_kg"] == pytest.approx([30.0, 42.0])
    assert closure["aircraft_empty_mass_within_target_range"] is False
    assert concept.wing_area_m2 == pytest.approx(48.6)


def test_mission_summary_uses_configured_mass_sweep_as_primary_cases() -> None:
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
        wing_loading_target_Npm2=32.0,
        design_gross_mass_kg=103.25,
    )

    mission = concept_pipeline._build_concept_mission_summary(
        cfg=cfg,
        concept=concept,
        station_points=[
            {
                "station_y_m": 4.0,
                "chord_m": 1.0,
                "weight": 1.0,
                "cl_target": 0.60,
                "cm_target": -0.05,
                "cl_max_safe": 1.0,
                "cl_max_safe_source": "airfoil_safe_observed",
                "case_label": "reference_avl_case",
                "evaluation_speed_mps": 8.0,
                "evaluation_gross_mass_kg": 103.25,
                "reference_speed_mps": 8.0,
                "reference_gross_mass_kg": 103.25,
            }
        ],
        airfoil_feedback={},
        trim_summary={"tail_cl_required": 0.0},
        air_density_kg_per_m3=1.15,
    )

    assert [case["gross_mass_kg"] for case in mission["mass_cases"]] == pytest.approx(
        [91.0, 98.5, 103.25, 106.0]
    )
    assert mission["evaluated_gross_mass_kg"] == pytest.approx(103.25)
    assert mission["primary_gross_mass_kg"] == pytest.approx(103.25)
    assert mission["worst_case_evaluated_gross_mass_kg"] == pytest.approx(106.0)


def test_mission_summary_reports_empty_feasible_speed_set_and_delta() -> None:
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

    mission = concept_pipeline._build_concept_mission_summary(
        cfg=cfg,
        concept=concept,
        station_points=[
            {
                "station_y_m": 4.0,
                "chord_m": 1.0,
                "weight": 1.0,
                "cl_target": 0.95,
                "cm_target": -0.05,
                "cl_max_safe": 0.50,
                "cl_max_safe_source": "airfoil_safe_observed",
                "case_label": "reference_avl_case",
                "evaluation_speed_mps": 8.0,
                "evaluation_gross_mass_kg": 105.0,
                "reference_speed_mps": 8.0,
                "reference_gross_mass_kg": 105.0,
            }
        ],
        airfoil_feedback={},
        trim_summary={"tail_cl_required": 0.0},
        air_density_kg_per_m3=1.15,
    )

    assert mission["feasible_speed_set_mps"] == []
    assert mission["best_range_speed_mps"] is None
    assert mission["best_range_m"] == pytest.approx(0.0)
    assert mission["operating_point_status"] == "no_feasible_speed_samples"
    assert mission["delta_v_to_first_feasible_mps"] > 0.0


def test_mission_summary_audit_marks_stall_as_dominant_limiter_when_no_feasible_speed_exists() -> None:
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

    mission = concept_pipeline._build_concept_mission_summary(
        cfg=cfg,
        concept=concept,
        station_points=[
            {
                "station_y_m": 4.0,
                "chord_m": 1.0,
                "weight": 1.0,
                "cl_target": 0.95,
                "cm_target": -0.05,
                "cl_max_safe": 0.50,
                "cl_max_safe_source": "airfoil_safe_observed",
                "case_label": "reference_avl_case",
                "evaluation_speed_mps": 8.0,
                "evaluation_gross_mass_kg": 105.0,
                "reference_speed_mps": 8.0,
                "reference_gross_mass_kg": 105.0,
            }
        ],
        airfoil_feedback={},
        trim_summary={"tail_cl_required": 0.0},
        air_density_kg_per_m3=1.15,
    )

    assert mission["limiter_audit"]["dominant_limiter"] == "stall_operating_point_unavailable"
    assert mission["limiter_audit"]["feasible_speed_count"] == 0
    assert mission["limiter_audit"]["best_feasible_speed_mps"] is None


def test_mission_summary_audit_marks_endurance_shortfall_when_feasible_speed_still_misses_range() -> None:
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

    mission = concept_pipeline._build_concept_mission_summary(
        cfg=cfg,
        concept=concept,
        station_points=[
            {
                "station_y_m": 4.0,
                "chord_m": 1.0,
                "weight": 1.0,
                "cl_target": 0.60,
                "cm_target": -0.05,
                "cl_max_safe": 1.0,
                "cl_max_safe_source": "airfoil_safe_observed",
                "case_label": "reference_avl_case",
                "evaluation_speed_mps": 8.0,
                "evaluation_gross_mass_kg": 105.0,
                "reference_speed_mps": 8.0,
                "reference_gross_mass_kg": 105.0,
            }
        ],
        airfoil_feedback={},
        trim_summary={"tail_cl_required": 0.0},
        air_density_kg_per_m3=1.15,
    )

    assert mission["limiter_audit"]["dominant_limiter"] == "endurance_shortfall_at_best_feasible_speed"
    assert mission["limiter_audit"]["feasible_speed_count"] > 0
    assert mission["limiter_audit"]["best_feasible_speed_mps"] == pytest.approx(
        mission["best_range_speed_mps"]
    )
    assert mission["limiter_audit"]["duration_margin_min"] < 0.0


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

    design_mass_kg = cfg.mass.design_gross_mass_kg
    launch_scale = (design_mass_kg / 95.0) * (10.0 / 8.0) ** 2
    assert local_stall["evaluation_case"] == "launch_release_case"
    assert local_stall["evaluation_speed_mps"] == pytest.approx(8.0)
    assert local_stall["evaluation_gross_mass_kg"] == pytest.approx(design_mass_kg)
    assert local_stall["required_cl"] == pytest.approx(0.70 * launch_scale)
    assert local_stall["stall_utilization"] == pytest.approx(local_stall["required_cl"] / 1.20)
    assert {case["case_label"] for case in local_stall["case_results"]} == {
        "reference_avl_case",
        "mission_worst_case",
        "launch_release_case",
    }


def test_local_stall_summary_reports_envelope_to_clear_limit() -> None:
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

    required_speed_mps = 8.0 * (local_stall["stall_utilization"] / local_stall["stall_utilization_limit"]) ** 0.5
    required_area_m2 = 32.0 * (
        local_stall["stall_utilization"] / local_stall["stall_utilization_limit"]
    )
    design_mass_kg = cfg.mass.design_gross_mass_kg
    required_gross_mass_kg = design_mass_kg * (
        local_stall["stall_utilization_limit"] / local_stall["stall_utilization"]
    )

    assert local_stall["required_speed_for_limit_mps"] == pytest.approx(required_speed_mps)
    assert local_stall["delta_speed_for_limit_mps"] == pytest.approx(required_speed_mps - 8.0)
    assert local_stall["required_wing_area_for_limit_m2"] == pytest.approx(required_area_m2)
    assert local_stall["delta_wing_area_for_limit_m2"] == pytest.approx(required_area_m2 - 32.0)
    assert local_stall["required_gross_mass_for_limit_kg"] == pytest.approx(required_gross_mass_kg)
    assert local_stall["delta_gross_mass_for_limit_kg"] == pytest.approx(
        required_gross_mass_kg - design_mass_kg
    )


def test_local_stall_summary_keeps_slow_case_report_only() -> None:
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
                "case_label": "reference_avl_case",
                "station_y_m": 4.0,
                "cl_target": 0.70,
                "cl_max_safe": 1.20,
                "cl_max_raw": 1.45,
                "reference_speed_mps": 7.5,
                "evaluation_speed_mps": 7.5,
                "reference_gross_mass_kg": 105.0,
                "evaluation_gross_mass_kg": 105.0,
            },
            {
                "case_label": "slow_avl_case",
                "station_y_m": 4.0,
                "cl_target": 1.30,
                "cl_max_safe": 1.20,
                "cl_max_raw": 1.45,
                "reference_speed_mps": 7.5,
                "evaluation_speed_mps": 6.0,
                "reference_gross_mass_kg": 105.0,
                "evaluation_gross_mass_kg": 105.0,
            },
        ],
        mission_summary={
            "best_range_speed_mps": 7.5,
            "evaluated_gross_mass_kg": 105.0,
        },
    )

    slow_case = next(
        case for case in local_stall["case_results"] if case["case_label"] == "slow_avl_case"
    )
    assert local_stall["feasible"] is True
    assert local_stall["evaluation_case"] == "reference_avl_case"
    assert local_stall["worst_report_case"] == "slow_avl_case"
    assert slow_case["case_role"] == "slow_speed_sensitivity"
    assert slow_case["gate_enforced"] is False
    assert slow_case["report_only"] is True
    assert slow_case["feasible"] is False
    assert slow_case["hard_gate_feasible"] is True
    assert slow_case["status"] == "beyond_safe_clmax"


def test_turn_summary_marks_fixed_bank_case_as_screening_only() -> None:
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

    assert turn["gate_role"] == "screening_only"
    assert turn["gate_model"] == "fixed_bank_screening"


@pytest.mark.slow
def test_pipeline_reorders_selected_concepts_by_mission_ranking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    payload = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    payload["pipeline"]["keep_top_n"] = 3
    payload["output"]["export_candidate_bundle"] = False
    payload["mission"]["target_distance_km"] = 1.0
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
    monkeypatch.setattr(
        concept_pipeline,
        "_concept_safety_margin",
        lambda **_: 0.20,
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
    assert summary["evaluation_scope"]["selection_scope"] == "ranked_sampled_pool"
    assert summary["selected_concepts"][0]["enumeration_index"] == 2
    assert summary["selected_concepts"][0]["rank"] == 1
    assert summary["selected_concepts"][1]["rank"] == 2
    assert (
        summary["selected_concepts"][0]["mission"]["mission_objective_mode"]
        == "fixed_range_best_time"
    )
    assert "mission_score" in summary["selected_concepts"][0]["mission"]
    assert "ranking" in summary["selected_concepts"][0]
    assert summary["selected_concepts"][0]["ranking"]["selection_scope"] == "ranked_sampled_pool"
    assert summary["selected_concepts"][0]["ranking"]["score"] <= summary["selected_concepts"][1]["ranking"]["score"]


@pytest.mark.slow
def test_pipeline_excludes_safety_infeasible_concepts_from_selected_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    payload = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    payload["pipeline"]["keep_top_n"] = 2
    payload["output"]["export_candidate_bundle"] = False
    payload["mission"]["target_distance_km"] = 0.1
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


@pytest.mark.slow
def test_pipeline_selected_summary_requires_full_feasibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    payload = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    payload["pipeline"]["keep_top_n"] = 2
    payload["output"]["export_candidate_bundle"] = False
    payload["mission"]["target_distance_km"] = 200.0
    payload["stall_model"] = {
        "safe_clmax_scale": 1.0,
        "safe_clmax_delta": 0.0,
        "local_stall_utilization_limit": 0.98,
        "turn_utilization_limit": 0.98,
        "launch_utilization_limit": 0.98,
    }
    custom_cfg = tmp_path / "concept_full_feasibility.yaml"
    custom_cfg.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    concept_a = GeometryConcept(
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
    concept_b = GeometryConcept(
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
    monkeypatch.setattr(
        concept_pipeline,
        "enumerate_geometry_concepts",
        lambda cfg: (concept_a, concept_b, concept_b),
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
                                "cd": 0.018,
                                "cm": -0.02,
                                "converged": True,
                            }
                        ],
                        "sweep_summary": {
                            "cl_max_observed": 1.40,
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
                        "reynolds": 320000.0,
                        "cl_target": 0.45,
                        "cm_target": -0.02,
                        "weight": 1.0,
                        "station_y_m": 2.0,
                    }
                ]
            },
            "mid1": {"points": []},
            "mid2": {"points": []},
            "tip": {"points": []},
        },
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))

    assert summary["selected_concepts"] == []
    assert len(summary["best_infeasible_concepts"]) == 2
    assert all(
        item["mission"]["mission_feasible"] is False for item in summary["best_infeasible_concepts"]
    )
    assert summary["evaluation_scope"]["selected_concept_count"] == 0
    assert summary["evaluation_scope"]["best_infeasible_count"] == 2
    assert result.selected_concept_dirs == ()
    assert result.best_infeasible_concept_dirs == ()


@pytest.mark.slow
def test_pipeline_falls_back_cleanly_when_spanwise_points_are_unavailable(
    tmp_path: Path,
) -> None:
    worker_call_lengths: list[int] = []
    config_path = _write_fast_test_config(tmp_path, filename="fallback_spanwise.yaml")

    result = run_birdman_concept_pipeline(
        config_path=config_path,
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
    assert first["local_stall"]["status"] in {
        "ok",
        "stall_utilization_exceeded",
        "beyond_safe_clmax",
        "beyond_raw_clmax",
    }


@pytest.mark.slow
def test_pipeline_default_worker_factory_uses_stubbed_ok_statuses(tmp_path: Path) -> None:
    config_path = _write_fast_test_config(tmp_path, filename="default_worker.yaml")
    result = run_birdman_concept_pipeline(
        config_path=config_path,
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


@pytest.mark.slow
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


@pytest.mark.slow
def test_pipeline_rejects_real_backend_selection_results_without_usable_metrics(
    tmp_path: Path,
) -> None:
    config_path = _write_fast_test_config(tmp_path, filename="real_backend_guard.yaml")
    with pytest.raises(RuntimeError, match="unusable metrics"):
        run_birdman_concept_pipeline(
            config_path=config_path,
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


@pytest.mark.slow
def test_pipeline_rejects_duplicate_selection_template_ids(tmp_path: Path) -> None:
    config_path = _write_fast_test_config(tmp_path, filename="duplicate_template_ids.yaml")
    with pytest.raises(RuntimeError, match="duplicate template_id"):
        run_birdman_concept_pipeline(
            config_path=config_path,
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


@pytest.mark.slow
def test_cli_smoke_writes_summary(tmp_path: Path) -> None:
    output_dir = tmp_path / "smoke"
    config_path = _write_fast_test_config(tmp_path, filename="cli_smoke.yaml")
    subprocess.run(
        [
            "./.venv/bin/python",
            "scripts/birdman_upstream_concept_design.py",
            "--config",
            str(config_path),
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
@pytest.mark.slow
def test_cli_smoke_can_use_real_julia_worker(tmp_path: Path) -> None:
    output_dir = tmp_path / "smoke_julia"
    config_path = _write_fast_test_config(tmp_path, filename="cli_smoke_julia.yaml")
    subprocess.run(
        [
            "./.venv/bin/python",
            "scripts/birdman_upstream_concept_design.py",
            "--config",
            str(config_path),
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


@pytest.mark.slow
def test_real_worker_backend_surfaces_as_julia_xfoil_without_running_julia(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    factory_calls: list[dict[str, object]] = []
    config_path = _write_fast_test_config(tmp_path, filename="real_worker_backend.yaml")

    result = run_birdman_concept_pipeline(
        config_path=config_path,
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


@pytest.mark.slow
def test_pipeline_closes_worker_when_supported(tmp_path: Path) -> None:
    closed = {"value": 0}
    config_path = _write_fast_test_config(tmp_path, filename="closable_worker.yaml")

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
        config_path=config_path,
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **_: _ClosableWorker(),
        spanwise_loader=lambda concept, stations: {"root": {"points": []}},
    )

    assert result.summary_json_path.is_file()
    assert closed["value"] == 1


@pytest.mark.slow
def test_pipeline_respects_yaml_controls_for_station_count_prop_and_vsp_exports(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    payload = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    payload["pipeline"]["stations_per_half"] = 9
    payload["pipeline"]["keep_top_n"] = 3
    payload["geometry_family"]["sampling"]["sample_count"] = 8
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
    assert (first_bundle / "concept_openvsp.vsp3").exists()
    assert ranked_records[0]["openvsp_handoff"]["script_path"] == str(
        first_bundle / "concept_openvsp.vspscript"
    )
    assert ranked_records[0]["openvsp_handoff"]["vsp3_build_status"] == "written"
    assert ranked_records[0]["openvsp_handoff"]["vsp3_path"] == str(
        first_bundle / "concept_openvsp.vsp3"
    )
    assert (third_bundle / "concept_openvsp.vspscript").exists() is False
    assert ranked_records[2]["openvsp_handoff"] is None


@pytest.mark.slow
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


@pytest.mark.slow
def test_pipeline_writes_dihedral_geometry_into_bundle_and_vsp_preview(tmp_path: Path) -> None:
    payload = yaml.safe_load(
        Path("configs/birdman_upstream_concept_baseline.yaml").read_text(encoding="utf-8")
    )
    payload["geometry_family"]["sampling"]["sample_count"] = 6
    payload["geometry_family"]["dihedral_root_deg_candidates"] = [0.0]
    payload["geometry_family"]["dihedral_tip_deg_candidates"] = [4.0]
    payload["geometry_family"]["dihedral_exponent_candidates"] = [1.0]
    config_path = tmp_path / "dihedral_bundle.yaml"
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    result = run_birdman_concept_pipeline(
        config_path=config_path,
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


def test_cli_stubbed_worker_returns_scoreable_polar_results() -> None:
    coordinates = ((1.0, 0.0), (0.5, 0.08), (0.0, 0.0), (0.5, -0.05), (1.0, 0.0))
    query = PolarQuery(
        template_id="root-nsga2_g01_child_0000-01",
        reynolds=260000.0,
        cl_samples=(0.55, 0.75),
        roughness_mode="clean",
        geometry_hash=geometry_hash_from_coordinates(coordinates),
        coordinates=coordinates,
    )

    cli_module = _load_concept_cli_module()
    worker = cli_module._cli_airfoil_worker_factory()
    result = worker.run_queries([query])[0]

    assert result["status"] == "stubbed_ok"
    assert result["mean_cd"] < 0.0120
    assert result["usable_clmax"] > 1.35
    assert result["polar_points"] == [
        pytest.approx({"cl": 0.55, "cd": 0.010545, "cm": -0.055}),
        pytest.approx({"cl": 0.75, "cd": 0.010505, "cm": -0.055}),
    ]
