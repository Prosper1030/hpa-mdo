from __future__ import annotations

from pathlib import Path

import pytest

from scripts.audit_historical_airfoil_cst_coverage import (
    check_bounds,
    fit_cst_airfoil,
    generate_fit_coordinates,
    parse_dat_coordinates,
)
from hpa_mdo.concept.airfoil_cst import SeedlessCSTCoefficientBounds


def test_fit_cst_airfoil_recovers_synthetic_current_cst_shape() -> None:
    upper = (0.18, 0.28, 0.26, 0.18, 0.10, 0.05, 0.015)
    lower = (-0.12, -0.16, -0.14, -0.09, -0.04, -0.015, -0.004)
    coordinates = generate_fit_coordinates(
        upper_coefficients=upper,
        lower_coefficients=lower,
        te_thickness=0.002,
        point_count=81,
    )

    result = fit_cst_airfoil(coordinates, degree=6)

    assert result.rms_error_percent_chord < 1.0e-10
    assert result.max_error_percent_chord < 1.0e-9
    assert result.upper_coefficients == pytest.approx(upper)
    assert result.lower_coefficients == pytest.approx(lower)
    assert result.te_thickness == pytest.approx(0.002)


def test_check_bounds_reports_degree_mismatch_for_non_current_bounds() -> None:
    bounds = SeedlessCSTCoefficientBounds(
        upper_min=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        upper_max=(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
        lower_min=(-1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0),
        lower_max=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        te_thickness_min=0.0,
        te_thickness_max=0.01,
    )

    result = fit_cst_airfoil(
        generate_fit_coordinates(
            upper_coefficients=(0.18, 0.28, 0.22, 0.12, 0.03),
            lower_coefficients=(-0.12, -0.16, -0.10, -0.03, -0.004),
            te_thickness=0.002,
            point_count=41,
        ),
        degree=4,
    )

    outcome = check_bounds(result, bounds)

    assert outcome.fits is None
    assert outcome.exceedances == ("degree_mismatch: fit has 5 coefficients, bounds have 7",)


def test_fit_cst_airfoil_keeps_trailing_edge_thickness_non_negative() -> None:
    coordinates = parse_dat_coordinates(
        Path("docs/research/historical_airfoil_cst_coverage/airfoils/dae41.dat")
    )

    result = fit_cst_airfoil(coordinates, degree=6)

    assert result.te_thickness >= 0.0
