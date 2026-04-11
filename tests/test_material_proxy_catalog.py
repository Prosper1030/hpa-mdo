from __future__ import annotations

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from hpa_mdo.core.materials import MaterialDB  # noqa: E402
from hpa_mdo.structure.material_proxy_catalog import (  # noqa: E402
    build_default_material_proxy_catalog,
    resolve_catalog_property_rows,
)


def _resolved_catalog():
    catalog = build_default_material_proxy_catalog()
    materials_db = MaterialDB(REPO_ROOT / "data" / "materials.yaml")
    resolved = resolve_catalog_property_rows(
        catalog=catalog,
        materials_db=materials_db,
        safety_factor=1.5,
    )
    return catalog, resolved


def test_catalog_marks_only_main_and_rear_outboard_as_candidate_ready() -> None:
    catalog, _ = _resolved_catalog()

    assert catalog.axis_info("main_spar_family").promotion_state == "candidate_ready"
    assert catalog.axis_info("rear_outboard_reinforcement_pkg").promotion_state == "candidate_ready"
    assert catalog.axis_info("rear_spar_family").promotion_state == "screening_only"


def test_catalog_exposes_buckling_aware_rules_on_promoted_packages() -> None:
    catalog, _ = _resolved_catalog()

    main_light_ud = catalog.get_package("main_spar_family", "main_light_ud")
    balanced_sleeve = catalog.get_package("rear_outboard_reinforcement_pkg", "ob_balanced_sleeve")
    torsion_patch = catalog.get_package("rear_outboard_reinforcement_pkg", "ob_torsion_patch")

    assert main_light_ud.buckling_rules.minimum_hoop_fraction == pytest.approx(0.10)
    assert main_light_ud.buckling_rules.forbid_outer_pure_axial is True
    assert main_light_ud.buckling_rules.conservative_allowable_knockdown == pytest.approx(0.93)

    assert balanced_sleeve.buckling_rules.allowed_region == "rear_seg5_6_outboard_non_joint_only"
    assert balanced_sleeve.buckling_rules.local_buckling_reserve == "high"
    assert balanced_sleeve.buckling_rules.equivalent_gate_credit == "production_local_only"

    assert torsion_patch.buckling_rules.allowed_region == "rear_seg5_6_outboard_non_joint_only"
    assert torsion_patch.buckling_rules.forbid_outer_pure_axial is True


def test_resolved_property_rows_match_phase31_preliminary_values() -> None:
    _, resolved = _resolved_catalog()

    main_light_ud = next(
        row for row in resolved["main_spar_family"] if row.package.key == "main_light_ud"
    )
    balanced_sleeve = next(
        row
        for row in resolved["rear_outboard_reinforcement_pkg"]
        if row.package.key == "ob_balanced_sleeve"
    )

    assert main_light_ud.effective_properties.E_eff_pa == pytest.approx(239.2e9)
    assert main_light_ud.effective_properties.G_eff_pa == pytest.approx(14.25e9)
    assert main_light_ud.effective_properties.density_eff_kgpm3 == pytest.approx(1560.0)
    assert main_light_ud.effective_properties.allowable_eff_pa == pytest.approx(930.0e6)

    assert balanced_sleeve.effective_properties.E_eff_pa == pytest.approx(243.8e9)
    assert balanced_sleeve.effective_properties.G_eff_pa == pytest.approx(18.6e9)
    assert balanced_sleeve.effective_properties.density_eff_kgpm3 == pytest.approx(1728.0)
    assert balanced_sleeve.effective_properties.allowable_eff_pa == pytest.approx(1017.6e6)
