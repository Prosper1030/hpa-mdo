from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "audit_avl_induced_drag_credibility.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "audit_avl_induced_drag_credibility",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rewrite_lattice_changes_counts_without_dropping_sections() -> None:
    module = _load_script_module()
    source = _REPO_ROOT / "output" / "baseline_comparisons" / "old_fx_clark_vs_phase7_cdi_debug" / "old_main_wing_only.avl"

    text = module.rewrite_avl_lattice_text(source, nchord=8, nspan=16)

    assert "Main Wing\n8  1.0  16  -2.0" in text
    assert text.count("\nSECTION\n") == 6
    assert "SURFACE\nElevator" not in text


def test_manual_e_from_cdff_uses_reference_ar() -> None:
    module = _load_script_module()

    # AVL Trefftz e should be computed with the Trefftz-plane CLff paired to CDff.
    e = module.manual_e(1.10783, 33.0**2 / 35.175, 0.0128129)

    assert e == pytest.approx(0.9848161462139291)


def test_percent_delta_handles_zero_and_none() -> None:
    module = _load_script_module()

    assert module.percent_delta(1.01, 1.0) == pytest.approx(1.0)
    assert module.percent_delta(1.0, 0.0) is None
    assert module.percent_delta(None, 1.0) is None
