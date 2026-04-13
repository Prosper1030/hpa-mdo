from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.core import MaterialDB  # noqa: E402
from scripts.vendor_tube_catalog_phase9d import (  # noqa: E402
    TubeProduct,
    TubeRequirement,
    select_best_vendor_tube,
    synthesize_hypothetical_products,
)


def test_synthesize_hypothetical_products_skips_existing_rows() -> None:
    materials_db = MaterialDB()
    base = (
        TubeProduct(
            vendor="generic",
            product="CF-HM-40x38",
            material_key="carbon_fiber_hm",
            outer_diameter_mm=40.0,
            inner_diameter_mm=38.0,
            wall_thickness_mm=1.0,
            length_mm=3000,
            mass_per_meter_kg=0.195,
            price_per_meter_usd=42.0,
            note="base row",
            hypothetical=False,
        ),
    )

    synthetic = synthesize_hypothetical_products(
        base_products=base,
        materials_db=materials_db,
        material_keys=("carbon_fiber_hm",),
        outer_diameter_grid_mm=(40.0, 45.0),
        wall_thickness_grid_mm=(1.0,),
    )

    assert len(synthetic) == 1
    assert synthetic[0].outer_diameter_mm == 45.0
    assert synthetic[0].hypothetical is True


def test_select_best_vendor_tube_prefers_lightest_feasible_match() -> None:
    requirement = TubeRequirement(
        design_role="mass_first",
        design_label="mass_first: single x5.000",
        spar="main",
        segment_index=1,
        material_key="carbon_fiber_hm",
        segment_length_m=3.0,
        full_wing_required_length_m=6.0,
        required_outer_diameter_mm=61.0,
        required_wall_thickness_mm=1.2,
        required_mass_per_meter_kg=0.7,
        continuous_full_wing_mass_kg=4.2,
    )
    products = (
        TubeProduct(
            vendor="generic_hypothetical",
            product="A",
            material_key="carbon_fiber_hm",
            outer_diameter_mm=65.0,
            inner_diameter_mm=61.0,
            wall_thickness_mm=2.0,
            length_mm=3000,
            mass_per_meter_kg=0.610,
            price_per_meter_usd=70.0,
            note="",
            hypothetical=True,
        ),
        TubeProduct(
            vendor="generic_hypothetical",
            product="B",
            material_key="carbon_fiber_hm",
            outer_diameter_mm=70.0,
            inner_diameter_mm=66.0,
            wall_thickness_mm=2.0,
            length_mm=3000,
            mass_per_meter_kg=0.720,
            price_per_meter_usd=68.0,
            note="",
            hypothetical=True,
        ),
    )

    match = select_best_vendor_tube(requirement, products)

    assert match.product.product == "A"
    assert match.procurement_pieces_full_wing == 2


def test_select_best_vendor_tube_rejects_short_stock() -> None:
    requirement = TubeRequirement(
        design_role="balanced",
        design_label="balanced: single x2.000",
        spar="rear",
        segment_index=1,
        material_key="carbon_fiber_hm",
        segment_length_m=3.0,
        full_wing_required_length_m=6.0,
        required_outer_diameter_mm=25.0,
        required_wall_thickness_mm=4.0,
        required_mass_per_meter_kg=0.5,
        continuous_full_wing_mass_kg=3.0,
    )
    products = (
        TubeProduct(
            vendor="generic_hypothetical",
            product="short",
            material_key="carbon_fiber_hm",
            outer_diameter_mm=25.0,
            inner_diameter_mm=15.0,
            wall_thickness_mm=5.0,
            length_mm=2000,
            mass_per_meter_kg=0.4,
            price_per_meter_usd=30.0,
            note="",
            hypothetical=True,
        ),
    )

    try:
        select_best_vendor_tube(requirement, products)
    except ValueError as exc:
        assert "No vendor product satisfies" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected ValueError for too-short stock length.")
