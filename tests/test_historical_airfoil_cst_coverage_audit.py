from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.audit_historical_airfoil_cst_coverage import (
    CSTFitResult,
    check_bounds,
    fit_cst_airfoil,
    generate_fit_coordinates,
    parse_dat_coordinates,
)
from hpa_mdo.concept.airfoil_cst import (
    SeedlessCSTCoefficientBounds,
    build_seedless_cst_template,
    validate_seedless_cst_template,
)
from hpa_mdo.concept.airfoil_selection import (
    _OUTBOARD_SEEDLESS_CST_BOUNDS,
    _ROOT_SEEDLESS_CST_BOUNDS,
    _seedless_constraints_for_zone,
)

AUDIT_JSON_PATH = Path("docs/research/historical_airfoil_cst_coverage/fit_results.json")


def _historical_fit_result(airfoil: str, degree: int = 6) -> CSTFitResult:
    rows = json.loads(AUDIT_JSON_PATH.read_text(encoding="utf-8"))
    row = next(
        item
        for item in rows
        if item["airfoil"] == airfoil and int(item["degree"]) == degree
    )
    return CSTFitResult(
        degree=int(row["degree"]),
        upper_coefficients=tuple(float(value) for value in row["upper_coefficients"]),
        lower_coefficients=tuple(float(value) for value in row["lower_coefficients"]),
        te_thickness=float(row["te_thickness"]),
        rms_error_percent_chord=float(row["rms_error_percent_chord"]),
        max_error_percent_chord=float(row["max_error_percent_chord"]),
    )


def _assert_bounds_cover(airfoil: str, bounds: SeedlessCSTCoefficientBounds) -> None:
    fit = _historical_fit_result(airfoil)
    outcome = check_bounds(fit, bounds)
    assert outcome.fits is True, f"{airfoil}: " + "; ".join(outcome.exceedances)


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


@pytest.mark.parametrize(
    "airfoil",
    ("FX 76-MP-140", "DAE11", "DAE21", "DAE31", "DAE41"),
)
def test_historical_n6_fits_stay_inside_geometry_error_gate(airfoil: str) -> None:
    fit = _historical_fit_result(airfoil)

    assert fit.max_error_percent_chord < 0.2


@pytest.mark.parametrize("airfoil", ("FX 76-MP-140", "DAE11", "DAE21"))
def test_root_seedless_bounds_cover_historical_root_family(airfoil: str) -> None:
    _assert_bounds_cover(airfoil, _ROOT_SEEDLESS_CST_BOUNDS)


@pytest.mark.parametrize("airfoil", ("DAE21", "DAE31", "DAE41"))
def test_outboard_seedless_bounds_cover_historical_outboard_family(airfoil: str) -> None:
    _assert_bounds_cover(airfoil, _OUTBOARD_SEEDLESS_CST_BOUNDS)


def test_seedless_search_constraints_allow_historical_near_sharp_te() -> None:
    fit = _historical_fit_result("DAE21")
    template = build_seedless_cst_template(
        zone_name="mid2",
        upper_coefficients=fit.upper_coefficients,
        lower_coefficients=fit.lower_coefficients,
        te_thickness_m=max(fit.te_thickness, 1.0e-9),
    )

    outcome = validate_seedless_cst_template(
        template,
        constraints=_seedless_constraints_for_zone(
            zone_min_tc_ratio=0.10,
            seedless_te_thickness_min=0.0,
        ),
    )

    assert outcome.valid is True, outcome.reason
