from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hpa_mdo.core.config import load_config
from hpa_mdo.structure.rib_properties import (
    build_default_rib_catalog,
    derive_warping_knockdown,
    derive_warping_knockdown_details,
)


def test_default_rib_catalog_has_machine_readable_contract() -> None:
    catalog = build_default_rib_catalog()

    assert catalog.default_family == "balsa_sheet_3mm"
    baseline = catalog.family(catalog.default_family)
    assert baseline.material == "balsa"
    assert baseline.thickness_m == pytest.approx(0.003)
    assert baseline.spacing_guidance.nominal_m == pytest.approx(0.30)
    assert baseline.stiffness_proxy.rotational_fixity_factor == pytest.approx(1.0)


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
