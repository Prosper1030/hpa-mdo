from __future__ import annotations

from hpa_mdo.concept.airfoil_cst import CSTAirfoilTemplate
from hpa_mdo.concept.airfoil_selection import (
    build_base_cst_template,
    select_best_zone_candidate,
    select_zone_airfoil_templates,
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


def test_select_zone_airfoil_templates_returns_selected_candidates_for_each_zone() -> None:
    class FakeWorker:
        def run_queries(self, queries):
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
                        "mean_cd": mean_cd,
                        "mean_cm": -0.10,
                        "usable_clmax": usable_clmax,
                    }
                )
            return results

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
                ]
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
        worker=FakeWorker(),
    )

    assert set(selection.selected_by_zone) == {"root", "tip"}
    assert selection.selected_by_zone["root"].template.candidate_role == "thickness_up"
    assert selection.selected_by_zone["tip"].template.candidate_role == "thickness_up"
    assert len(selection.worker_results) == 10
