from __future__ import annotations

import pytest

from hpa_mdo.concept.airfoil_cst import (
    CSTAirfoilTemplate,
    build_bounded_candidate_family,
    generate_cst_coordinates,
    validate_cst_candidate_coordinates,
)


def test_generate_cst_coordinates_returns_closed_airfoil_coordinates() -> None:
    template = CSTAirfoilTemplate(
        zone_name="root",
        upper_coefficients=(0.22, 0.28, 0.18, 0.10, 0.04),
        lower_coefficients=(-0.18, -0.14, -0.08, -0.03, -0.01),
        te_thickness_m=0.0015,
    )

    coordinates = generate_cst_coordinates(template, point_count=81)

    assert len(coordinates) == 161
    assert coordinates[0][0] == pytest.approx(1.0)
    assert coordinates[-1][0] == pytest.approx(1.0)
    assert min(x for x, _ in coordinates) == pytest.approx(0.0)


def test_build_bounded_candidate_family_includes_base_candidate() -> None:
    template = CSTAirfoilTemplate(
        zone_name="mid1",
        upper_coefficients=(0.22, 0.28, 0.18, 0.10, 0.04),
        lower_coefficients=(-0.18, -0.14, -0.08, -0.03, -0.01),
        te_thickness_m=0.0015,
    )

    candidates = build_bounded_candidate_family(template)

    assert candidates[0].candidate_role == "base"
    assert candidates[0].upper_coefficients == template.upper_coefficients
    assert candidates[0].lower_coefficients == template.lower_coefficients
    assert len(candidates) >= 5


def test_validate_cst_candidate_coordinates_rejects_non_positive_thickness() -> None:
    bad_coordinates = (
        (1.0, 0.0),
        (0.5, 0.0),
        (0.0, 0.0),
        (0.5, 0.02),
        (1.0, 0.0),
    )

    outcome = validate_cst_candidate_coordinates(bad_coordinates)

    assert outcome.valid is False
    assert outcome.reason == "non_positive_thickness"
