from __future__ import annotations

import pytest

from hpa_mdo.concept.airfoil_cst import (
    CSTAirfoilTemplate,
    SeedlessCSTCoefficientBounds,
    SeedlessCSTConstraints,
    analyze_cst_geometry,
    build_bounded_candidate_family,
    build_seedless_cst_template,
    generate_cst_coordinates,
    sample_feasible_seedless_cst_sobol,
    sample_seedless_cst_latin_hypercube,
    sample_seedless_cst_sobol,
    validate_cst_candidate_coordinates,
    validate_seedless_cst_template,
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
    assert len(candidates) == 35


def test_build_bounded_candidate_family_accepts_configured_delta_levels() -> None:
    template = CSTAirfoilTemplate(
        zone_name="mid2",
        upper_coefficients=(0.22, 0.28, 0.18, 0.10, 0.04),
        lower_coefficients=(-0.18, -0.14, -0.08, -0.03, -0.01),
        te_thickness_m=0.0015,
    )

    candidates = build_bounded_candidate_family(
        template,
        thickness_delta_levels=(-0.01, 0.0, 0.01),
        camber_delta_levels=(-0.008, 0.0, 0.008),
    )

    assert len(candidates) == 9
    assert len({candidate.candidate_role for candidate in candidates}) == 9
    assert candidates[0].candidate_role == "base"


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


def test_validate_cst_candidate_coordinates_handles_asymmetric_leading_edge_split() -> None:
    coordinates = (
        (1.0, 0.0),
        (0.6666666666666667, 0.026233520365518792),
        (0.33333333333333337, 0.026233520365518792),
        (0.0, 0.0),
        (0.25, 0.0065635527911789586),
        (0.5, 0.01),
        (0.75, 0.006563552791178961),
        (1.0, 0.0),
    )

    outcome = validate_cst_candidate_coordinates(coordinates)

    assert outcome.valid is True
    assert outcome.reason == "ok"


def test_build_bounded_candidate_family_thickness_roles_modify_both_surfaces() -> None:
    template = CSTAirfoilTemplate(
        zone_name="tip",
        upper_coefficients=(0.22, 0.28, 0.18, 0.10, 0.04),
        lower_coefficients=(-0.18, -0.14, -0.08, -0.03, -0.01),
        te_thickness_m=0.0015,
    )

    candidates = {candidate.candidate_role: candidate for candidate in build_bounded_candidate_family(template)}

    thickness_up = candidates["thickness_up"]
    thickness_down = candidates["thickness_down"]

    assert thickness_up.upper_coefficients[1] > template.upper_coefficients[1]
    assert thickness_up.lower_coefficients[1] < template.lower_coefficients[1]
    assert thickness_down.upper_coefficients[1] < template.upper_coefficients[1]
    assert thickness_down.lower_coefficients[1] > template.lower_coefficients[1]


def test_build_seedless_cst_template_has_no_seed_airfoil_identity() -> None:
    template = build_seedless_cst_template(
        zone_name="root",
        upper_coefficients=(0.20, 0.30, 0.28, 0.20, 0.12, 0.06, 0.02),
        lower_coefficients=(-0.12, -0.16, -0.14, -0.10, -0.05, -0.02, -0.005),
        te_thickness_m=0.002,
        candidate_role="seedless_demo",
    )

    assert template.seed_name is None
    assert template.candidate_role == "seedless_demo"
    assert len(template.upper_coefficients) == 7
    assert len(template.lower_coefficients) == 7


def test_analyze_cst_geometry_reports_hpa_filter_metrics() -> None:
    template = build_seedless_cst_template(
        zone_name="mid1",
        upper_coefficients=(0.20, 0.30, 0.28, 0.20, 0.12, 0.06, 0.02),
        lower_coefficients=(-0.12, -0.16, -0.14, -0.10, -0.05, -0.02, -0.005),
        te_thickness_m=0.002,
    )

    metrics = analyze_cst_geometry(template)

    assert 0.10 <= metrics.max_thickness_ratio <= 0.16
    assert 0.25 <= metrics.max_thickness_x <= 0.45
    assert metrics.spar_depth_ratio_25_35 > 0.09
    assert metrics.te_thickness_ratio == pytest.approx(0.002)
    assert metrics.curvature_reversal_count >= 0


def test_validate_seedless_cst_template_rejects_unbuildable_geometry() -> None:
    too_thin = build_seedless_cst_template(
        zone_name="tip",
        upper_coefficients=(0.06, 0.07, 0.06, 0.04, 0.02, 0.01, 0.005),
        lower_coefficients=(-0.04, -0.04, -0.03, -0.02, -0.01, -0.005, -0.002),
        te_thickness_m=0.002,
    )

    outcome = validate_seedless_cst_template(
        too_thin,
        constraints=SeedlessCSTConstraints(min_thickness_ratio=0.10),
    )

    assert outcome.valid is False
    assert outcome.reason == "max_thickness_below_min"


def test_validate_seedless_cst_template_returns_invalid_for_high_resolution_self_intersection() -> None:
    template = CSTAirfoilTemplate(
        zone_name="mid2",
        upper_coefficients=(
            0.14608827389776707,
            0.31662274200469254,
            0.2670808409526944,
            0.2338538182524061,
            0.09547389090799169,
            0.10715972091003322,
            0.035616273034673185,
        ),
        lower_coefficients=(
            -0.05266490444540978,
            0.12822013805430377,
            -0.0958580852393061,
            0.23750671248227354,
            -0.036064939536154264,
            0.03092455722218658,
            0.09249738380541837,
        ),
        te_thickness_m=0.0010785854724235833,
        candidate_role="seedless_sobol_2026",
    )

    outcome = validate_seedless_cst_template(template)

    assert outcome.valid is False
    assert outcome.reason == "non_positive_thickness"


def test_sample_seedless_cst_latin_hypercube_returns_seed_free_candidates() -> None:
    bounds = SeedlessCSTCoefficientBounds(
        upper_min=(0.12, 0.16, 0.14, 0.10, 0.06, 0.03, 0.01),
        upper_max=(0.24, 0.34, 0.32, 0.24, 0.14, 0.08, 0.04),
        lower_min=(-0.18, -0.20, -0.18, -0.13, -0.07, -0.04, -0.02),
        lower_max=(-0.08, -0.10, -0.08, -0.05, -0.02, -0.01, -0.002),
        te_thickness_min=0.001,
        te_thickness_max=0.004,
    )

    first = sample_seedless_cst_latin_hypercube(
        zone_name="root",
        sample_count=8,
        bounds=bounds,
        random_seed=7,
    )
    second = sample_seedless_cst_latin_hypercube(
        zone_name="root",
        sample_count=8,
        bounds=bounds,
        random_seed=7,
    )

    assert len(first) == 8
    assert first == second
    assert all(candidate.seed_name is None for candidate in first)
    assert {candidate.candidate_role for candidate in first} == {
        f"seedless_lhs_{index:04d}" for index in range(8)
    }
    for candidate in first:
        assert all(
            lower <= value <= upper
            for value, lower, upper in zip(
                candidate.upper_coefficients,
                bounds.upper_min,
                bounds.upper_max,
                strict=True,
            )
        )


def test_sample_seedless_cst_sobol_returns_deterministic_seed_free_candidates() -> None:
    bounds = SeedlessCSTCoefficientBounds(
        upper_min=(0.12, 0.16, 0.14, 0.10, 0.06, 0.03, 0.01),
        upper_max=(0.24, 0.34, 0.32, 0.24, 0.14, 0.08, 0.04),
        lower_min=(-0.18, -0.20, -0.18, -0.13, -0.07, -0.04, -0.02),
        lower_max=(-0.08, -0.10, -0.08, -0.05, -0.02, -0.01, -0.002),
        te_thickness_min=0.001,
        te_thickness_max=0.004,
    )

    first = sample_seedless_cst_sobol(
        zone_name="root",
        sample_count=8,
        bounds=bounds,
        random_seed=7,
    )
    second = sample_seedless_cst_sobol(
        zone_name="root",
        sample_count=8,
        bounds=bounds,
        random_seed=7,
    )

    assert len(first) == 8
    assert first == second
    assert all(candidate.seed_name is None for candidate in first)
    assert {candidate.candidate_role for candidate in first} == {
        f"seedless_sobol_{index:04d}" for index in range(8)
    }
    for candidate in first:
        assert all(
            lower <= value <= upper
            for value, lower, upper in zip(
                candidate.upper_coefficients,
                bounds.upper_min,
                bounds.upper_max,
                strict=True,
            )
        )
        assert bounds.te_thickness_min <= candidate.te_thickness_m <= bounds.te_thickness_max


def test_sample_feasible_seedless_cst_sobol_applies_geometry_filter() -> None:
    bounds = SeedlessCSTCoefficientBounds(
        upper_min=(0.18, 0.26, 0.25, 0.18, 0.11, 0.05, 0.015),
        upper_max=(0.22, 0.32, 0.30, 0.22, 0.13, 0.07, 0.025),
        lower_min=(-0.14, -0.18, -0.15, -0.11, -0.06, -0.03, -0.010),
        lower_max=(-0.10, -0.14, -0.13, -0.09, -0.04, -0.015, -0.002),
        te_thickness_min=0.0015,
        te_thickness_max=0.0025,
    )
    constraints = SeedlessCSTConstraints(
        min_thickness_ratio=0.10,
        max_thickness_ratio=0.16,
        max_thickness_x_min=0.25,
        max_thickness_x_max=0.45,
        min_spar_depth_ratio_25_35=0.09,
    )

    candidates = sample_feasible_seedless_cst_sobol(
        zone_name="mid1",
        sample_count=4,
        bounds=bounds,
        constraints=constraints,
        random_seed=11,
    )

    assert len(candidates) == 4
    assert all(
        validate_seedless_cst_template(candidate, constraints=constraints).valid
        for candidate in candidates
    )
