from __future__ import annotations

import pytest

from hpa_mdo.concept import airfoil_selection as airfoil_selection_module
from hpa_mdo.concept.airfoil_cst import CSTAirfoilTemplate
from hpa_mdo.concept.airfoil_selection import (
    _coarse_seed_candidates,
    _refinement_candidates,
    _select_scored_candidate_beam,
    _ZoneCandidateScore,
    _zone_queries_for_candidates,
    build_base_cst_template,
    select_best_zone_candidate,
    select_zone_airfoil_templates,
    select_zone_airfoil_templates_for_concepts,
)


def test_build_base_cst_template_preserves_seed_identity() -> None:
    coordinates = (
        (1.0, 0.0),
        (0.5, 0.06),
        (0.0, 0.0),
        (0.5, -0.04),
        (1.0, 0.0),
    )

    template = build_base_cst_template(
        zone_name="root",
        seed_name="fx76mp140",
        seed_coordinates=coordinates,
    )

    assert template.zone_name == "root"
    assert template.seed_name == "fx76mp140"
    assert len(template.upper_coefficients) == 5
    assert len(template.lower_coefficients) == 5


def test_select_best_zone_candidate_prefers_lower_drag_when_cl_is_usable() -> None:
    candidates = (
        CSTAirfoilTemplate(
            "root",
            (0.22, 0.28, 0.18, 0.10, 0.04),
            (-0.18, -0.14, -0.08, -0.03, -0.01),
            0.0015,
            seed_name="fx76mp140",
            candidate_role="base",
        ),
        CSTAirfoilTemplate(
            "root",
            (0.22, 0.30, 0.19, 0.10, 0.04),
            (-0.18, -0.14, -0.08, -0.03, -0.01),
            0.0015,
            seed_name="fx76mp140",
            candidate_role="thickness_up",
        ),
    )
    zone_points = [
        {"reynolds": 260000.0, "cl_target": 0.70, "cm_target": -0.10, "weight": 1.0},
    ]
    candidate_results = {
        "base": {"status": "ok", "mean_cd": 0.024, "usable_clmax": 1.18, "mean_cm": -0.12},
        "thickness_up": {
            "status": "ok",
            "mean_cd": 0.019,
            "usable_clmax": 1.16,
            "mean_cm": -0.11,
        },
    }

    selected = select_best_zone_candidate(candidates, zone_points, candidate_results)

    assert selected.template.candidate_role == "thickness_up"


def test_select_best_zone_candidate_prefers_thicker_candidate_when_margin_is_tight() -> None:
    candidates = (
        CSTAirfoilTemplate(
            "root",
            (0.04, 0.05, 0.03, 0.01),
            (-0.03, -0.04, -0.02, -0.01),
            0.0002,
            seed_name="fx76mp140",
            candidate_role="thin_low_drag",
        ),
        CSTAirfoilTemplate(
            "root",
            (0.20, 0.28, 0.18, 0.08),
            (-0.18, -0.16, -0.10, -0.04),
            0.0018,
            seed_name="fx76mp140",
            candidate_role="thick_safe",
        ),
    )
    zone_points = [
        {"reynolds": 260000.0, "chord_m": 1.32, "cl_target": 0.76, "cm_target": -0.11, "weight": 1.2},
        {"reynolds": 230000.0, "chord_m": 1.05, "cl_target": 0.70, "cm_target": -0.10, "weight": 0.8},
    ]
    candidate_results = {
        "thin_low_drag": {"status": "ok", "mean_cd": 0.016, "usable_clmax": 0.88, "mean_cm": -0.08},
        "thick_safe": {"status": "ok", "mean_cd": 0.020, "usable_clmax": 1.12, "mean_cm": -0.11},
    }

    selected = select_best_zone_candidate(
        candidates,
        zone_points,
        candidate_results,
        zone_min_tc_ratio=0.14,
    )

    assert selected.template.candidate_role == "thick_safe"
    assert selected.candidate_score > 0.0


def test_select_best_zone_candidate_uses_safe_clmax_not_raw_observed_clmax() -> None:
    candidates = (
        CSTAirfoilTemplate(
            "mid2",
            (0.18, 0.22, 0.14, 0.07, 0.03),
            (-0.12, -0.10, -0.05, -0.02, -0.005),
            0.0010,
            seed_name="clarkysm",
            candidate_role="thin_low_drag",
        ),
        CSTAirfoilTemplate(
            "mid2",
            (0.19, 0.24, 0.15, 0.08, 0.03),
            (-0.13, -0.11, -0.06, -0.02, -0.005),
            0.0011,
            seed_name="clarkysm",
            candidate_role="slightly_safer",
        ),
    )
    zone_points = [
        {"reynolds": 220000.0, "chord_m": 1.00, "cl_target": 0.75, "cm_target": -0.08, "weight": 1.0},
    ]
    candidate_results = {
        "thin_low_drag": {
            "status": "ok",
            "mean_cd": 0.017,
            "usable_clmax": 1.05,
            "mean_cm": -0.08,
        },
        "slightly_safer": {
            "status": "ok",
            "mean_cd": 0.020,
            "usable_clmax": 1.15,
            "mean_cm": -0.09,
        },
    }

    selected = select_best_zone_candidate(
        candidates,
        zone_points,
        candidate_results,
        zone_min_tc_ratio=0.10,
    )

    assert selected.template.candidate_role == "slightly_safer"


def test_select_best_zone_candidate_honors_custom_stall_model_inputs() -> None:
    candidates = (
        CSTAirfoilTemplate(
            "mid2",
            (0.18, 0.22, 0.14, 0.07, 0.03),
            (-0.12, -0.10, -0.05, -0.02, -0.005),
            0.0010,
            seed_name="clarkysm",
            candidate_role="thin_low_drag",
        ),
        CSTAirfoilTemplate(
            "mid2",
            (0.19, 0.24, 0.15, 0.08, 0.03),
            (-0.13, -0.11, -0.06, -0.02, -0.005),
            0.0011,
            seed_name="clarkysm",
            candidate_role="slightly_safer",
        ),
    )
    zone_points = [
        {"reynolds": 220000.0, "chord_m": 1.00, "cl_target": 0.75, "cm_target": -0.08, "weight": 1.0},
    ]
    candidate_results = {
        "thin_low_drag": {
            "status": "ok",
            "mean_cd": 0.017,
            "usable_clmax": 1.05,
            "mean_cm": -0.08,
        },
        "slightly_safer": {
            "status": "ok",
            "mean_cd": 0.020,
            "usable_clmax": 1.15,
            "mean_cm": -0.09,
        },
    }

    selected = select_best_zone_candidate(
        candidates,
        zone_points,
        candidate_results,
        zone_min_tc_ratio=0.10,
        safe_clmax_scale=1.0,
        safe_clmax_delta=0.0,
        stall_utilization_limit=0.98,
    )

    assert selected.template.candidate_role == "thin_low_drag"
    assert selected.safe_clmax == pytest.approx(1.05)


def test_select_best_zone_candidate_uses_case_specific_launch_limit() -> None:
    candidates = (
        CSTAirfoilTemplate(
            "mid2",
            (0.18, 0.22, 0.14, 0.07, 0.03),
            (-0.12, -0.10, -0.05, -0.02, -0.005),
            0.0010,
            seed_name="clarkysm",
            candidate_role="low_drag_tight_launch",
        ),
        CSTAirfoilTemplate(
            "mid2",
            (0.19, 0.24, 0.15, 0.08, 0.03),
            (-0.13, -0.11, -0.06, -0.02, -0.005),
            0.0011,
            seed_name="clarkysm",
            candidate_role="slightly_draggier_launch_safe",
        ),
    )
    zone_points = [
        {
            "reynolds": 220000.0,
            "chord_m": 1.00,
            "cl_target": 0.70,
            "cm_target": -0.08,
            "weight": 0.5,
            "case_label": "reference_avl_case",
        },
        {
            "reynolds": 220000.0,
            "chord_m": 1.00,
            "cl_target": 0.86,
            "cm_target": -0.08,
            "weight": 1.5,
            "case_label": "launch_release_case",
        },
    ]
    candidate_results = {
        "low_drag_tight_launch": {
            "status": "ok",
            "mean_cd": 0.016,
            "usable_clmax": 1.12,
            "mean_cm": -0.08,
        },
        "slightly_draggier_launch_safe": {
            "status": "ok",
            "mean_cd": 0.019,
            "usable_clmax": 1.22,
            "mean_cm": -0.09,
        },
    }

    selected = select_best_zone_candidate(
        candidates,
        zone_points,
        candidate_results,
        zone_min_tc_ratio=0.10,
        safe_clmax_scale=1.0,
        safe_clmax_delta=0.0,
        launch_stall_utilization_limit=0.75,
        turn_stall_utilization_limit=0.85,
        local_stall_utilization_limit=0.80,
    )

    assert selected.template.candidate_role == "slightly_draggier_launch_safe"


def test_select_best_zone_candidate_applies_outer_span_safe_clmax_penalty() -> None:
    candidates = (
        CSTAirfoilTemplate(
            "tip",
            (0.18, 0.22, 0.14, 0.07, 0.03),
            (-0.12, -0.10, -0.05, -0.02, -0.005),
            0.0010,
            seed_name="clarkysm",
            candidate_role="tip_low_drag_tight",
        ),
        CSTAirfoilTemplate(
            "tip",
            (0.19, 0.24, 0.15, 0.08, 0.03),
            (-0.13, -0.11, -0.06, -0.02, -0.005),
            0.0011,
            seed_name="clarkysm",
            candidate_role="tip_safer_margin",
        ),
    )
    zone_points = [
        {
            "reynolds": 200000.0,
            "chord_m": 0.90,
            "cl_target": 0.90,
            "cm_target": -0.08,
            "weight": 1.0,
            "case_label": "turn_avl_case",
            "span_fraction": 0.92,
            "taper_ratio": 0.30,
            "washout_deg": 0.5,
        }
    ]
    candidate_results = {
        "tip_low_drag_tight": {
            "status": "ok",
            "mean_cd": 0.016,
            "usable_clmax": 1.20,
            "mean_cm": -0.08,
        },
        "tip_safer_margin": {
            "status": "ok",
            "mean_cd": 0.019,
            "usable_clmax": 1.28,
            "mean_cm": -0.09,
        },
    }

    selected = select_best_zone_candidate(
        candidates,
        zone_points,
        candidate_results,
        zone_min_tc_ratio=0.10,
        safe_clmax_scale=1.0,
        safe_clmax_delta=0.0,
        tip_3d_penalty_start_eta=0.55,
        tip_3d_penalty_max=0.05,
        tip_taper_penalty_weight=0.35,
        washout_relief_deg=2.0,
        washout_relief_max=0.01,
        launch_stall_utilization_limit=0.75,
        turn_stall_utilization_limit=0.85,
        local_stall_utilization_limit=0.80,
    )

    assert selected.template.candidate_role == "tip_safer_margin"


def test_select_best_zone_candidate_uses_matched_polar_points_when_available() -> None:
    candidates = (
        CSTAirfoilTemplate(
            "root",
            (0.22, 0.28, 0.18, 0.10, 0.04),
            (-0.18, -0.14, -0.08, -0.03, -0.01),
            0.0015,
            seed_name="fx76mp140",
            candidate_role="weight_high_first",
        ),
        CSTAirfoilTemplate(
            "root",
            (0.22, 0.28, 0.18, 0.10, 0.04),
            (-0.18, -0.14, -0.08, -0.03, -0.01),
            0.0015,
            seed_name="fx76mp140",
            candidate_role="weight_high_second",
        ),
    )
    zone_points = [
        {"reynolds": 260000.0, "chord_m": 1.34, "cl_target": 0.70, "cm_target": -0.10, "weight": 2.0},
        {"reynolds": 230000.0, "chord_m": 0.92, "cl_target": 0.76, "cm_target": -0.11, "weight": 1.0},
    ]
    candidate_results = {
        "weight_high_first": {
            "status": "ok",
            "mean_cd": 0.0205,
            "mean_cm": -0.105,
            "usable_clmax": 1.08,
            "polar_points": [
                {"cl_target": 0.70, "cl": 0.70, "cd": 0.016, "cm": -0.10},
                {"cl_target": 0.76, "cl": 0.76, "cd": 0.025, "cm": -0.11},
            ],
        },
        "weight_high_second": {
            "status": "ok",
            "mean_cd": 0.0205,
            "mean_cm": -0.105,
            "usable_clmax": 1.08,
            "polar_points": [
                {"cl_target": 0.70, "cl": 0.70, "cd": 0.022, "cm": -0.10},
                {"cl_target": 0.76, "cl": 0.76, "cd": 0.019, "cm": -0.11},
            ],
        },
    }

    selected = select_best_zone_candidate(
        candidates,
        zone_points,
        candidate_results,
        zone_min_tc_ratio=0.14,
    )

    assert selected.template.candidate_role == "weight_high_first"


def test_select_zone_airfoil_templates_returns_selected_candidates_for_each_zone() -> None:
    class FakeWorker:
        def __init__(self):
            self.query_count_by_zone: dict[str, int] = {}
            self.analysis_modes_seen: set[str] = set()
            self.analysis_stages_seen: set[str] = set()
            self.call_count = 0

        def run_queries(self, queries):
            self.call_count += 1
            for query in queries:
                zone_name = query.template_id.split("-", 1)[0]
                zone_name = zone_name.split("__", 1)[-1]
                self.query_count_by_zone[zone_name] = self.query_count_by_zone.get(zone_name, 0) + 1
                self.analysis_modes_seen.add(query.analysis_mode)
                self.analysis_stages_seen.add(query.analysis_stage)
            results = []
            for query in queries:
                if query.template_id.endswith("thickness_up"):
                    mean_cd = 0.018
                    usable_clmax = 1.18
                else:
                    mean_cd = 0.024
                    usable_clmax = 1.20
                results.append(
                    {
                        "status": "ok",
                        "template_id": query.template_id,
                        "geometry_hash": query.geometry_hash,
                        "mean_cd": mean_cd,
                        "mean_cm": -0.10,
                        "usable_clmax": usable_clmax,
                    }
                )
            return list(reversed(results))

    worker = FakeWorker()
    seed_coordinates = (
        (1.0, 0.0),
        (0.5, 0.06),
        (0.0, 0.0),
        (0.5, -0.04),
        (1.0, 0.0),
    )
    selection = select_zone_airfoil_templates(
        zone_requirements={
            "root": {
                "points": [
                    {
                        "reynolds": 260000.0,
                        "cl_target": 0.70,
                        "cm_target": -0.10,
                        "weight": 1.0,
                    }
                ],
                "min_tc_ratio": 0.14,
            },
            "tip": {
                "points": [
                    {
                        "reynolds": 220000.0,
                        "cl_target": 0.55,
                        "cm_target": -0.08,
                        "weight": 1.0,
                    }
                ]
            },
        },
        seed_loader=lambda _seed_name: seed_coordinates,
        worker=worker,
        thickness_delta_levels=(-0.01, 0.0, 0.01),
        camber_delta_levels=(-0.008, 0.0, 0.008),
    )

    assert set(selection.selected_by_zone) == {"root", "tip"}
    assert selection.selected_by_zone["root"].template.candidate_role == "thickness_up"
    assert selection.selected_by_zone["tip"].template.candidate_role == "thickness_up"
    assert worker.query_count_by_zone["root"] < 9
    assert 0 < worker.query_count_by_zone["tip"] < 9
    assert worker.analysis_modes_seen == {"screening_target_cl"}
    assert worker.analysis_stages_seen == {"screening"}


def test_select_zone_airfoil_templates_can_use_seedless_sobol_candidates() -> None:
    class FakeWorker:
        def __init__(self):
            self.template_ids: list[str] = []

        def run_queries(self, queries):
            self.template_ids.extend(query.template_id for query in queries)
            results = []
            for query in queries:
                results.append(
                    {
                        "status": "ok",
                        "template_id": query.template_id,
                        "geometry_hash": query.geometry_hash,
                        "mean_cd": 0.020,
                        "mean_cm": -0.09,
                        "usable_clmax": 1.28,
                    }
                )
            return results

    def fail_seed_loader(seed_name: str) -> tuple[tuple[float, float], ...]:
        raise AssertionError(f"seed loader should not be called in seedless mode: {seed_name}")

    worker = FakeWorker()
    selection = select_zone_airfoil_templates(
        zone_requirements={
            "root": {
                "points": [
                    {
                        "reynolds": 260000.0,
                        "cl_target": 0.70,
                        "cm_target": -0.10,
                        "weight": 1.0,
                    }
                ],
                "min_tc_ratio": 0.14,
            },
        },
        seed_loader=fail_seed_loader,
        worker=worker,
        search_mode="seedless_sobol",
        seedless_sample_count=8,
        seedless_random_seed=11,
        coarse_to_fine_enabled=False,
        successive_halving_enabled=False,
    )

    assert set(selection.selected_by_zone) == {"root"}
    assert selection.selected_by_zone["root"].template.seed_name is None
    assert selection.selected_by_zone["root"].template.candidate_role.startswith("seedless_sobol_")
    assert worker.template_ids
    assert all(
        template_id.split("__", 1)[-1].startswith("root-seedless_sobol_")
        for template_id in worker.template_ids
    )


def test_select_zone_airfoil_templates_can_aggregate_robust_screening_conditions() -> None:
    class FakeWorker:
        def __init__(self):
            self.queries = []

        def run_queries(self, queries):
            self.queries.extend(queries)
            results = []
            for query in queries:
                rough_penalty = 0.08 if query.roughness_mode == "rough" else 0.0
                low_re_penalty = 0.05 if query.reynolds < 250000.0 else 0.0
                results.append(
                    {
                        "status": "ok",
                        "template_id": query.template_id,
                        "geometry_hash": query.geometry_hash,
                        "mean_cd": 0.020 + rough_penalty + low_re_penalty,
                        "mean_cm": -0.09 - rough_penalty,
                        "usable_clmax": 1.30 - rough_penalty - low_re_penalty,
                    }
                )
            return results

    worker = FakeWorker()
    seed_coordinates = (
        (1.0, 0.0),
        (0.5, 0.06),
        (0.0, 0.0),
        (0.5, -0.04),
        (1.0, 0.0),
    )

    selection = select_zone_airfoil_templates(
        zone_requirements={
            "root": {
                "points": [
                    {
                        "reynolds": 260000.0,
                        "cl_target": 0.70,
                        "cm_target": -0.10,
                        "weight": 1.0,
                    }
                ],
                "min_tc_ratio": 0.12,
            }
        },
        seed_loader=lambda _seed_name: seed_coordinates,
        worker=worker,
        thickness_delta_levels=(0.0,),
        camber_delta_levels=(0.0,),
        robust_evaluation_enabled=True,
        robust_reynolds_factors=(0.90, 1.10),
        robust_roughness_modes=("clean", "rough"),
        coarse_to_fine_enabled=False,
        successive_halving_enabled=False,
    )

    selected = selection.selected_by_zone["root"]
    assert len(worker.queries) == 4
    assert {query.roughness_mode for query in worker.queries} == {"clean", "rough"}
    assert {round(query.reynolds / 260000.0, 2) for query in worker.queries} == {0.90, 1.10}
    assert all("__robust_" in query.template_id for query in worker.queries)
    assert selected.mean_cd == pytest.approx(0.15)
    assert selected.mean_cm == pytest.approx(-0.17)
    assert selected.usable_clmax == pytest.approx(1.17)
    assert selected.safe_clmax < selected.usable_clmax
    assert all(result["candidate_role"] == "base" for result in selection.worker_results)


def test_select_scored_candidate_beam_can_use_constrained_pareto_diversity() -> None:
    low_drag = CSTAirfoilTemplate(
        "root",
        (0.22, 0.28, 0.18, 0.10, 0.04),
        (-0.18, -0.14, -0.08, -0.03, -0.01),
        0.0015,
        candidate_role="low_drag",
    )
    high_clmax = CSTAirfoilTemplate(
        "root",
        (0.22, 0.35, 0.24, 0.10, 0.04),
        (-0.18, -0.20, -0.12, -0.03, -0.01),
        0.0015,
        candidate_role="high_clmax",
    )
    middle = CSTAirfoilTemplate(
        "root",
        (0.22, 0.30, 0.20, 0.10, 0.04),
        (-0.18, -0.15, -0.09, -0.03, -0.01),
        0.0015,
        candidate_role="middle",
    )
    scored = (
        _ZoneCandidateScore(
            template=low_drag,
            feasibility_gate=0,
            candidate_score=0.10,
            mean_cd=0.0090,
            mean_cm=-0.10,
            usable_clmax=1.10,
            safe_clmax=0.95,
            robust_pass_rate=1.0,
            cm_penalty=0.0,
            cm_hard_violation=0.0,
        ),
        _ZoneCandidateScore(
            template=middle,
            feasibility_gate=0,
            candidate_score=0.22,
            mean_cd=0.0105,
            mean_cm=-0.12,
            usable_clmax=1.18,
            safe_clmax=1.05,
            robust_pass_rate=1.0,
            cm_penalty=0.0,
            cm_hard_violation=0.0,
        ),
        _ZoneCandidateScore(
            template=high_clmax,
            feasibility_gate=0,
            candidate_score=0.38,
            mean_cd=0.0150,
            mean_cm=-0.15,
            usable_clmax=1.55,
            safe_clmax=1.40,
            robust_pass_rate=1.0,
            cm_penalty=(0.15 - 0.12) ** 2,
            cm_hard_violation=0.0,
        ),
    )

    scalar_beam = _select_scored_candidate_beam(
        scored,
        beam_count=2,
        selection_strategy="scalar_score",
    )
    pareto_beam = _select_scored_candidate_beam(
        scored,
        beam_count=2,
        selection_strategy="constrained_pareto",
    )

    assert [candidate.candidate_role for candidate in scalar_beam] == ["low_drag", "middle"]
    assert {candidate.candidate_role for candidate in pareto_beam} == {"low_drag", "high_clmax"}


def test_select_scored_candidate_beam_pareto_rejects_cm_hard_violations() -> None:
    feasible = CSTAirfoilTemplate(
        "root",
        (0.22, 0.28, 0.18, 0.10, 0.04),
        (-0.18, -0.14, -0.08, -0.03, -0.01),
        0.0015,
        candidate_role="feasible",
    )
    cm_violator = CSTAirfoilTemplate(
        "root",
        (0.22, 0.30, 0.20, 0.10, 0.04),
        (-0.18, -0.15, -0.09, -0.03, -0.01),
        0.0015,
        candidate_role="cm_violator",
    )
    scored = (
        _ZoneCandidateScore(
            template=feasible,
            feasibility_gate=0,
            candidate_score=0.30,
            mean_cd=0.012,
            mean_cm=-0.11,
            usable_clmax=1.20,
            safe_clmax=1.10,
            robust_pass_rate=1.0,
            cm_penalty=0.0,
            cm_hard_violation=0.0,
        ),
        _ZoneCandidateScore(
            template=cm_violator,
            feasibility_gate=1,
            candidate_score=0.05,
            mean_cd=0.010,
            mean_cm=-0.20,
            usable_clmax=1.25,
            safe_clmax=1.15,
            robust_pass_rate=1.0,
            cm_penalty=(0.20 - 0.12) ** 2,
            cm_hard_violation=0.04,
        ),
    )

    pareto_beam = _select_scored_candidate_beam(
        scored,
        beam_count=1,
        selection_strategy="constrained_pareto",
    )
    assert [candidate.candidate_role for candidate in pareto_beam] == ["feasible"]


def test_select_zone_airfoil_templates_seedless_can_run_nsga_generation() -> None:
    class FakeWorker:
        def __init__(self):
            self.template_ids: list[str] = []

        def run_queries(self, queries):
            self.template_ids.extend(query.template_id for query in queries)
            results = []
            for query in queries:
                is_child = "nsga2_g01_child" in query.template_id
                results.append(
                    {
                        "status": "ok",
                        "template_id": query.template_id,
                        "geometry_hash": query.geometry_hash,
                        "mean_cd": 0.019 if is_child else 0.022,
                        "mean_cm": -0.10,
                        "usable_clmax": 1.30 if is_child else 1.22,
                    }
                )
            return results

    worker = FakeWorker()
    selection = select_zone_airfoil_templates(
        zone_requirements={
            "root": {
                "points": [
                    {
                        "reynolds": 260000.0,
                        "cl_target": 0.70,
                        "cm_target": -0.10,
                        "weight": 1.0,
                    }
                ],
                "min_tc_ratio": 0.14,
            }
        },
        seed_loader=lambda _seed_name: (),
        worker=worker,
        search_mode="seedless_sobol",
        seedless_sample_count=8,
        seedless_random_seed=17,
        nsga_generation_count=1,
        nsga_offspring_count=2,
        nsga_parent_count=4,
        nsga_random_seed=23,
        coarse_to_fine_enabled=False,
        successive_halving_enabled=False,
    )

    assert any("nsga2_g01_child" in template_id for template_id in worker.template_ids)
    assert selection.selected_by_zone["root"].template.candidate_role.startswith("nsga2_g01_child")


def test_select_zone_airfoil_templates_seedless_runs_cma_es_knee_refinement() -> None:
    class FakeWorker:
        def __init__(self):
            self.template_ids: list[str] = []

        def run_queries(self, queries):
            self.template_ids.extend(query.template_id for query in queries)
            results = []
            for query in queries:
                is_cma = "cma_k" in query.template_id
                results.append(
                    {
                        "status": "ok",
                        "template_id": query.template_id,
                        "geometry_hash": query.geometry_hash,
                        "mean_cd": 0.018 if is_cma else 0.022,
                        "mean_cm": -0.10,
                        "usable_clmax": 1.32 if is_cma else 1.24,
                    }
                )
            return results

    worker = FakeWorker()
    selection = select_zone_airfoil_templates(
        zone_requirements={
            "root": {
                "points": [
                    {
                        "reynolds": 260000.0,
                        "cl_target": 0.70,
                        "cm_target": -0.10,
                        "weight": 1.0,
                    }
                ],
                "min_tc_ratio": 0.14,
            }
        },
        seed_loader=lambda _seed_name: (),
        worker=worker,
        search_mode="seedless_sobol",
        selection_strategy="constrained_pareto",
        seedless_sample_count=8,
        seedless_random_seed=17,
        nsga_generation_count=0,
        nsga_offspring_count=0,
        cma_es_enabled=True,
        cma_es_knee_count=2,
        cma_es_iterations=2,
        cma_es_population_lambda=4,
        cma_es_sigma_init=0.05,
        cma_es_random_seed=29,
        pareto_knee_count=2,
        coarse_to_fine_enabled=False,
        successive_halving_enabled=False,
    )

    assert any("cma_k" in template_id for template_id in worker.template_ids)
    selected_role = selection.selected_by_zone["root"].template.candidate_role
    assert selected_role.startswith("cma_k")


def test_select_zone_airfoil_templates_for_concepts_batches_across_multiple_concepts() -> None:
    class FakeWorker:
        def __init__(self):
            self.call_count = 0
            self.batch_template_ids: list[tuple[str, ...]] = []

        def run_queries(self, queries):
            self.call_count += 1
            self.batch_template_ids.append(tuple(query.template_id for query in queries))
            results = []
            for query in queries:
                if query.template_id.endswith("thickness_up"):
                    mean_cd = 0.018
                    usable_clmax = 1.18
                else:
                    mean_cd = 0.024
                    usable_clmax = 1.20
                results.append(
                    {
                        "status": "ok",
                        "template_id": query.template_id,
                        "geometry_hash": query.geometry_hash,
                        "mean_cd": mean_cd,
                        "mean_cm": -0.10,
                        "usable_clmax": usable_clmax,
                    }
                )
            return results

    worker = FakeWorker()
    seed_coordinates = (
        (1.0, 0.0),
        (0.5, 0.06),
        (0.0, 0.0),
        (0.5, -0.04),
        (1.0, 0.0),
    )
    selection_by_concept = select_zone_airfoil_templates_for_concepts(
        concept_zone_requirements={
            "eval-01": {
                "root": {
                    "points": [
                        {
                            "reynolds": 260000.0,
                            "cl_target": 0.70,
                            "cm_target": -0.10,
                            "weight": 1.0,
                        }
                    ],
                    "min_tc_ratio": 0.14,
                },
                "tip": {
                    "points": [
                        {
                            "reynolds": 200000.0,
                            "cl_target": 0.58,
                            "cm_target": -0.07,
                            "weight": 1.0,
                        }
                    ],
                    "min_tc_ratio": 0.10,
                },
            },
            "eval-02": {
                "root": {
                    "points": [
                        {
                            "reynolds": 255000.0,
                            "cl_target": 0.68,
                            "cm_target": -0.09,
                            "weight": 1.0,
                        }
                    ],
                    "min_tc_ratio": 0.14,
                },
                "tip": {
                    "points": [
                        {
                            "reynolds": 195000.0,
                            "cl_target": 0.56,
                            "cm_target": -0.06,
                            "weight": 1.0,
                        }
                    ],
                    "min_tc_ratio": 0.10,
                },
            },
        },
        seed_loader=lambda _: seed_coordinates,
        worker=worker,
    )

    assert set(selection_by_concept) == {"eval-01", "eval-02"}
    assert selection_by_concept["eval-01"].selected_by_zone["root"].template.candidate_role == "thickness_up"
    assert selection_by_concept["eval-02"].selected_by_zone["tip"].template.candidate_role == "thickness_up"
    assert worker.call_count == 2
    assert any(template_id.startswith("eval-01__") for template_id in worker.batch_template_ids[0])
    assert any(template_id.startswith("eval-02__") for template_id in worker.batch_template_ids[0])
    assert all(
        result["concept_id"] in {"eval-01", "eval-02"}
        for batch in selection_by_concept.values()
        for result in batch.worker_results
    )


def test_select_zone_airfoil_templates_supports_successive_halving_multi_stage_refinement() -> None:
    class FakeWorker:
        def __init__(self):
            self.call_count = 0
            self.template_ids: list[str] = []

        def run_queries(self, queries):
            self.call_count += 1
            self.template_ids.extend(query.template_id for query in queries)
            results = []
            for query in queries:
                role = query.template_id.split("-", 1)[1]
                if role == "base":
                    mean_cd = 0.020
                    usable_clmax = 1.16
                elif role == "t01_c05":
                    mean_cd = 0.018
                    usable_clmax = 1.18
                else:
                    mean_cd = 0.024
                    usable_clmax = 1.10
                results.append(
                    {
                        "status": "ok",
                        "template_id": query.template_id,
                        "geometry_hash": query.geometry_hash,
                        "mean_cd": mean_cd,
                        "mean_cm": -0.10,
                        "usable_clmax": usable_clmax,
                    }
                )
            return results

    worker = FakeWorker()
    seed_coordinates = (
        (1.0, 0.0),
        (0.5, 0.06),
        (0.0, 0.0),
        (0.5, -0.04),
        (1.0, 0.0),
    )
    selection = select_zone_airfoil_templates(
        zone_requirements={
            "root": {
                "points": [
                    {
                        "reynolds": 260000.0,
                        "cl_target": 0.70,
                        "cm_target": -0.10,
                        "weight": 1.0,
                    }
                ],
                "min_tc_ratio": 0.12,
            }
        },
        seed_loader=lambda _seed_name: seed_coordinates,
        worker=worker,
        thickness_delta_levels=(-0.01, 0.0, 0.01),
        camber_delta_levels=(-0.016, -0.012, -0.008, 0.0, 0.008, 0.012, 0.016),
        coarse_to_fine_enabled=True,
        coarse_thickness_stride=2,
        coarse_camber_stride=3,
        coarse_keep_top_k=1,
        refine_neighbor_radius=1,
        successive_halving_enabled=True,
        successive_halving_rounds=2,
        successive_halving_beam_width=2,
    )

    assert selection.selected_by_zone["root"].template.candidate_role == "t01_c05"
    assert worker.call_count == 3
    assert any(template_id.endswith("t01_c05") for template_id in worker.template_ids)


def test_select_zone_airfoil_templates_falls_back_to_all_valid_candidates_when_prescreen_eliminates_everything() -> None:
    class FakeWorker:
        def __init__(self):
            self.query_count = 0

        def run_queries(self, queries):
            self.query_count = len(queries)
            return [
                {
                    "status": "ok",
                    "template_id": query.template_id,
                    "geometry_hash": query.geometry_hash,
                    "mean_cd": 0.020,
                    "mean_cm": -0.10,
                    "usable_clmax": 1.10,
                }
                for query in queries
            ]

    worker = FakeWorker()
    seed_coordinates = (
        (1.0, 0.0),
        (0.5, 0.06),
        (0.0, 0.0),
        (0.5, -0.04),
        (1.0, 0.0),
    )
    selection = select_zone_airfoil_templates(
        zone_requirements={
            "root": {
                "points": [
                    {
                        "reynolds": 260000.0,
                        "cl_target": 0.70,
                        "cm_target": -0.10,
                        "weight": 1.0,
                    }
                ],
                "min_tc_ratio": 0.25,
            }
        },
        seed_loader=lambda _seed_name: seed_coordinates,
        worker=worker,
        thickness_delta_levels=(-0.01, 0.0, 0.01),
        camber_delta_levels=(-0.008, 0.0, 0.008),
    )

    assert set(selection.selected_by_zone) == {"root"}
    assert worker.query_count == 9


def test_select_zone_airfoil_templates_uses_coarse_to_fine_refinement_to_recover_non_coarse_best() -> None:
    class FakeWorker:
        def __init__(self):
            self.query_count = 0
            self.template_ids: list[str] = []
            self.call_count = 0

        def run_queries(self, queries):
            self.call_count += 1
            self.query_count += len(queries)
            self.template_ids.extend(query.template_id for query in queries)
            results = []
            for query in queries:
                role = query.template_id.split("-", 1)[1]
                if role == "t01_c04":
                    mean_cd = 0.017
                    usable_clmax = 1.28
                elif role == "t00_c04":
                    mean_cd = 0.019
                    usable_clmax = 1.18
                else:
                    mean_cd = 0.024
                    usable_clmax = 1.10
                results.append(
                    {
                        "status": "ok",
                        "template_id": query.template_id,
                        "geometry_hash": query.geometry_hash,
                        "mean_cd": mean_cd,
                        "mean_cm": -0.10,
                        "usable_clmax": usable_clmax,
                    }
                )
            return results

    worker = FakeWorker()
    seed_coordinates = (
        (1.0, 0.0),
        (0.5, 0.06),
        (0.0, 0.0),
        (0.5, -0.04),
        (1.0, 0.0),
    )
    selection = select_zone_airfoil_templates(
        zone_requirements={
            "root": {
                "points": [
                    {
                        "reynolds": 260000.0,
                        "cl_target": 0.70,
                        "cm_target": -0.10,
                        "weight": 1.0,
                    }
                ],
                "min_tc_ratio": 0.12,
            }
        },
        seed_loader=lambda _seed_name: seed_coordinates,
        worker=worker,
        thickness_delta_levels=(-0.01, 0.0, 0.01),
        camber_delta_levels=(-0.012, -0.008, 0.0, 0.008, 0.012),
        coarse_to_fine_enabled=True,
        coarse_thickness_stride=2,
        coarse_camber_stride=2,
        coarse_keep_top_k=1,
        refine_neighbor_radius=1,
        successive_halving_enabled=False,
    )

    assert selection.selected_by_zone["root"].template.candidate_role == "t01_c04"
    assert worker.query_count < 15
    assert worker.call_count == 2
    assert any(template_id.endswith("t01_c04") for template_id in worker.template_ids)


def test_select_zone_airfoil_templates_for_concepts_reuses_seedless_candidate_pool(
    monkeypatch,
) -> None:
    seedless_calls: list[tuple[str, float, int, int | None, int]] = []
    prescreen_calls: list[float] = []
    template = CSTAirfoilTemplate(
        "root",
        (0.22, 0.28, 0.18, 0.10, 0.04),
        (-0.18, -0.14, -0.08, -0.03, -0.01),
        0.0015,
        candidate_role="seedless_sobol_0000",
    )

    def fake_seedless_zone_candidates(
        *,
        zone_name,
        zone_min_tc_ratio,
        sample_count,
        random_seed,
        max_oversample_factor,
    ):
        seedless_calls.append(
            (
                zone_name,
                zone_min_tc_ratio,
                sample_count,
                random_seed,
                max_oversample_factor,
            )
        )
        return (template,)

    class FakeWorker:
        def run_queries(self, queries):
            return [
                {
                    "status": "ok",
                    "template_id": query.template_id,
                    "geometry_hash": query.geometry_hash,
                    "mean_cd": 0.020,
                    "mean_cm": -0.09,
                    "usable_clmax": 1.30,
                }
                for query in queries
            ]

    monkeypatch.setattr(
        airfoil_selection_module,
        "_seedless_zone_candidates",
        fake_seedless_zone_candidates,
    )
    original_prescreen = airfoil_selection_module._prescreen_zone_candidates

    def counting_prescreen(candidates, *, zone_points, zone_min_tc_ratio):
        prescreen_calls.append(float(zone_min_tc_ratio))
        return original_prescreen(
            candidates,
            zone_points=zone_points,
            zone_min_tc_ratio=zone_min_tc_ratio,
        )

    monkeypatch.setattr(
        airfoil_selection_module,
        "_prescreen_zone_candidates",
        counting_prescreen,
    )

    batches = select_zone_airfoil_templates_for_concepts(
        concept_zone_requirements={
            "eval-01": {
                "root": {
                    "points": [
                        {
                            "reynolds": 260000.0,
                            "cl_target": 0.70,
                            "cm_target": -0.10,
                            "weight": 1.0,
                        }
                    ],
                    "min_tc_ratio": 0.12,
                }
            },
            "eval-02": {
                "root": {
                    "points": [
                        {
                            "reynolds": 255000.0,
                            "cl_target": 0.72,
                            "cm_target": -0.10,
                            "weight": 1.0,
                        }
                    ],
                    "min_tc_ratio": 0.12,
                }
            },
        },
        seed_loader=lambda seed_name: pytest.fail(f"unexpected seed load: {seed_name}"),
        worker=FakeWorker(),
        search_mode="seedless_sobol",
        seedless_sample_count=8,
        seedless_random_seed=17,
        seedless_max_oversample_factor=4,
        coarse_to_fine_enabled=False,
        successive_halving_enabled=False,
    )

    assert set(batches) == {"eval-01", "eval-02"}
    assert seedless_calls == [("root", 0.12, 8, 17, 4)]
    assert prescreen_calls == [0.12]


def test_select_zone_airfoil_templates_for_concepts_emits_progress_events() -> None:
    events: list[dict[str, object]] = []

    class FakeWorker:
        def run_queries(self, queries):
            return [
                {
                    "status": "ok",
                    "template_id": query.template_id,
                    "geometry_hash": query.geometry_hash,
                    "mean_cd": 0.020,
                    "mean_cm": -0.09,
                    "usable_clmax": 1.30,
                }
                for query in queries
            ]

    seed_coordinates = (
        (1.0, 0.0),
        (0.5, 0.06),
        (0.0, 0.0),
        (0.5, -0.04),
        (1.0, 0.0),
    )

    select_zone_airfoil_templates_for_concepts(
        concept_zone_requirements={
            "eval-01": {
                "root": {
                    "points": [
                        {
                            "reynolds": 260000.0,
                            "cl_target": 0.70,
                            "cm_target": -0.10,
                            "weight": 1.0,
                        }
                    ],
                    "min_tc_ratio": 0.12,
                }
            }
        },
        seed_loader=lambda _seed_name: seed_coordinates,
        worker=FakeWorker(),
        thickness_delta_levels=(0.0,),
        camber_delta_levels=(0.0,),
        coarse_to_fine_enabled=False,
        successive_halving_enabled=False,
        progress_callback=events.append,
    )

    event_names = [str(event["event"]) for event in events]
    assert event_names[0] == "airfoil_selection_start"
    assert "airfoil_candidate_preparation_done" in event_names
    assert "airfoil_worker_batch_start" in event_names
    assert "airfoil_worker_batch_done" in event_names


def test_seedless_coarse_candidates_downsample_indexless_pool() -> None:
    candidates = tuple(
        CSTAirfoilTemplate(
            "root",
            (0.22, 0.28, 0.18, 0.10, 0.04),
            (-0.18, -0.14, -0.08, -0.03, -0.01),
            0.0015,
            candidate_role=f"seedless_sobol_{index:04d}",
        )
        for index in range(64)
    )

    coarse = _coarse_seed_candidates(
        candidates,
        thickness_stride=2,
        camber_stride=2,
    )

    assert 1 < len(coarse) < len(candidates)
    assert coarse[0].candidate_role == "seedless_sobol_0000"
    assert coarse[-1].candidate_role == "seedless_sobol_0063"


def test_seedless_refinement_without_grid_indices_keeps_existing_beam() -> None:
    candidates = tuple(
        CSTAirfoilTemplate(
            "root",
            (0.22, 0.28, 0.18, 0.10, 0.04),
            (-0.18, -0.14, -0.08, -0.03, -0.01),
            0.0015,
            candidate_role=f"seedless_sobol_{index:04d}",
        )
        for index in range(16)
    )
    seed_candidates = (candidates[2], candidates[9])

    refined = _refinement_candidates(
        candidates,
        seed_candidates=seed_candidates,
        neighbor_radius=1,
    )

    assert refined == seed_candidates


def test_zone_queries_quantize_reynolds_and_cl_samples_for_cache_reuse() -> None:
    candidate = CSTAirfoilTemplate(
        "root",
        (0.22, 0.28, 0.18, 0.10, 0.04),
        (-0.18, -0.14, -0.08, -0.03, -0.01),
        0.0015,
        candidate_role="seedless_sobol_0000",
    )

    queries, _ = _zone_queries_for_candidates(
        zone_name="eval-01__root",
        candidates=(candidate,),
        zone_points=[
            {"reynolds": 262340.0, "cl_target": 0.704, "weight": 1.0},
            {"reynolds": 263210.0, "cl_target": 0.706, "weight": 1.0},
        ],
    )

    assert len(queries) == 1
    assert queries[0].reynolds == pytest.approx(265000.0)
    assert queries[0].cl_samples == (0.70, 0.71)
