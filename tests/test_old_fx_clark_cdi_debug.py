from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "debug_old_fx_clark_cdi_reference.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "debug_old_fx_clark_cdi_reference",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_main_wing_only_avl_preserves_refs_and_removes_tail_surfaces() -> None:
    module = _load_script_module()
    text = module.extract_main_wing_only_avl_text(
        _REPO_ROOT / "data" / "blackcat_004_full.avl"
    )

    assert "#Sref  Cref  Bref" in text
    assert "35.175000000  1.130189765  33.000000000" in text
    assert "SURFACE\nMain Wing" in text
    assert "SURFACE\nElevator" not in text
    assert "SURFACE\nFin" not in text
    assert text.count("\nSECTION\n") == 6


def test_manual_e_uses_the_cdi_value_that_matches_the_drag_convention() -> None:
    module = _load_script_module()
    ar_ref = 33.0**2 / 35.175

    near_field_e = module.manual_e_cdi(1.1102304984748252, ar_ref, 0.0139441)
    trefftz_e = module.manual_e_cdi(1.10777, ar_ref, 0.0097724)

    assert near_field_e == pytest.approx(0.9088499168297887)
    assert trefftz_e == pytest.approx(1.2911, rel=5e-4)


def test_parse_avl_force_totals_reads_trefftz_cdi_and_reported_e() -> None:
    module = _load_script_module()
    totals = module.parse_avl_force_totals_extended(
        _REPO_ROOT
        / "output"
        / "baseline_comparisons"
        / "old_fx_clark_vs_phase7_pre_tier2"
        / "avl_run"
        / "concept_trim.ft"
    )

    assert totals["CLtot"] == pytest.approx(1.11023)
    assert totals["CDind"] == pytest.approx(0.0139441)
    assert totals["CLff"] == pytest.approx(1.10777)
    assert totals["CDff"] == pytest.approx(0.0097724)
    assert totals["e_reported"] == pytest.approx(1.2911)
