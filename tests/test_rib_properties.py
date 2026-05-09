from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hpa_mdo.core.config import load_config
from hpa_mdo.structure.rib_properties import (
    build_default_rib_catalog,
    default_material_sensitivity_family_keys,
    derive_warping_knockdown,
    derive_warping_knockdown_details,
    rib_family_material_basis,
)


def test_default_rib_catalog_has_machine_readable_contract() -> None:
    catalog = build_default_rib_catalog()

    assert catalog.default_family == "balsa_sheet_3mm"
    baseline = catalog.family(catalog.default_family)
    assert baseline.material == "balsa"
    assert baseline.thickness_m == pytest.approx(0.003)
    assert baseline.spacing_guidance.nominal_m == pytest.approx(0.30)
    assert baseline.stiffness_proxy.rotational_fixity_factor == pytest.approx(1.0)


def test_default_rib_catalog_includes_foam_only_material_sensitivity_families() -> None:
    catalog = build_default_rib_catalog()

    family_keys = default_material_sensitivity_family_keys(catalog)

    assert family_keys == (
        "balsa_sheet_3mm",
        "eps_hd_foam_cnc_10mm",
        "xps_high_compressive_cnc_10mm",
        "structural_foam_cnc_10mm",
    )
    assert catalog.family("balsa_sheet_3mm").material == "balsa"
    assert catalog.family("eps_hd_foam_cnc_10mm").material == "eps_hd_foam"
    assert catalog.family("xps_high_compressive_cnc_10mm").material == "xps_high_compressive_foam"
    assert catalog.family("structural_foam_cnc_10mm").material == "structural_foam_pvc_h60"

    for family_key in family_keys:
        basis = rib_family_material_basis(family_key, catalog=catalog)
        assert basis["density_kgpm3"] > 0.0
        assert basis["young_modulus_pa"] > 0.0
        assert basis["shear_modulus_pa"] > 0.0
        assert basis["compressive_or_shear_basis"]
        assert basis["trust_level"]
        assert basis["source_note"]
        assert basis["stiffness_proxy"]["construction_factor"] > 0.0

    assert not any("hybrid" in key or "balsa_cap" in key for key in family_keys)


def test_reference_family_reproduces_legacy_middle_knockdown() -> None:
    details = derive_warping_knockdown_details("balsa_sheet_3mm", 0.30)

    assert details.relative_stiffness == pytest.approx(1.0)
    assert details.spacing_factor == pytest.approx(1.0)
    assert details.warping_knockdown == pytest.approx(0.5)


def test_derived_knockdown_changes_monotonically_with_family_and_spacing() -> None:
    baseline = derive_warping_knockdown("balsa_sheet_3mm", 0.30)
    denser_spacing = derive_warping_knockdown("balsa_sheet_3mm", 0.24)
    softer_family = derive_warping_knockdown("foam_core_glass_cap_5mm", 0.30)
    stiffer_family = derive_warping_knockdown("capped_balsa_box_4mm", 0.30)

    assert denser_spacing > baseline
    assert softer_family < baseline
    assert stiffer_family > baseline


def test_foam_only_screening_families_do_not_silently_match_balsa_knockdown() -> None:
    baseline = derive_warping_knockdown("balsa_sheet_3mm", 0.30)

    assert derive_warping_knockdown("eps_hd_foam_cnc_10mm", 0.30) < baseline
    assert derive_warping_knockdown("xps_high_compressive_cnc_10mm", 0.30) < baseline
    assert derive_warping_knockdown("structural_foam_cnc_10mm", 0.30) < baseline


def test_load_config_preserves_explicit_legacy_warping_knockdown() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    cfg = load_config(repo_root / "configs" / "blackcat_004.yaml")

    assert cfg.safety.dual_spar_warping_knockdown == pytest.approx(0.5)


def test_load_config_can_derive_warping_knockdown_from_rib_section(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    payload["safety"].pop("dual_spar_warping_knockdown", None)
    payload["rib"] = {
        "family": "capped_balsa_box_4mm",
        "spacing_m": 0.28,
    }

    cfg_path = tmp_path / "rib_config.yaml"
    cfg_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    cfg = load_config(cfg_path)

    assert cfg.safety.dual_spar_warping_knockdown == pytest.approx(
        derive_warping_knockdown("capped_balsa_box_4mm", 0.28)
    )
