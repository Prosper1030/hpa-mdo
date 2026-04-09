"""Regression tests for Phase II material library expansion.

Verifies that every newly added material can be loaded by MaterialDB
and exposes non-None density and Young's modulus. Does NOT test any
optimizer behaviour - purely a DB integrity check.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from hpa_mdo.core.materials import MaterialDB

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "materials.yaml"

# All material keys added in Phase II Milestone II-1.
# Do NOT include keys from the original 7 - those are tested elsewhere.
NEW_MATERIAL_KEYS: List[str] = [
    "rohacell_31",
    "rohacell_51",
    "kevlar_49_ud",
    "eglass_ud",
    "dyneema_sk75",
    "titanium_6al4v",
    "cfrp_prepreg_t700",
    "eglass_woven",
]


@pytest.fixture(scope="module")
def mat_db() -> MaterialDB:
    return MaterialDB(path=DB_PATH)


@pytest.mark.parametrize("key", NEW_MATERIAL_KEYS)
def test_new_material_loadable(mat_db: MaterialDB, key: str) -> None:
    """Each new material key must be present in the DB."""
    assert key in mat_db, (
        f"Material '{key}' not found in {DB_PATH}. "
        f"Available keys: {sorted(mat_db.keys())}"
    )


@pytest.mark.parametrize("key", NEW_MATERIAL_KEYS)
def test_new_material_density_not_none(mat_db: MaterialDB, key: str) -> None:
    mat = mat_db.get(key)
    assert mat.density is not None and mat.density > 0, (
        f"Material '{key}' has invalid density: {mat.density}"
    )


@pytest.mark.parametrize("key", NEW_MATERIAL_KEYS)
def test_new_material_E_not_none(mat_db: MaterialDB, key: str) -> None:
    mat = mat_db.get(key)
    assert mat.E is not None and mat.E > 0, (
        f"Material '{key}' has invalid Young's modulus: {mat.E}"
    )


def test_dyneema_is_tension_only(mat_db: MaterialDB) -> None:
    """Dyneema SK75 must carry tension_only flag."""
    mat = mat_db.get("dyneema_sk75")
    assert mat.tension_only is True, (
        "dyneema_sk75 must have tension_only=True; "
        f"got tension_only={mat.tension_only}"
    )


def test_dyneema_no_compressive_strength(mat_db: MaterialDB) -> None:
    """Dyneema SK75 has no compressive strength - compressive_strength must be None."""
    mat = mat_db.get("dyneema_sk75")
    assert mat.compressive_strength is None, (
        f"dyneema_sk75 compressive_strength should be None, got {mat.compressive_strength}"
    )


def test_eglass_woven_has_shear_strength(mat_db: MaterialDB) -> None:
    """E-glass woven fabric must expose a non-None shear_strength."""
    mat = mat_db.get("eglass_woven")
    assert mat.shear_strength is not None and mat.shear_strength > 0, (
        f"eglass_woven shear_strength should be a positive float, got {mat.shear_strength}"
    )


def test_original_materials_untouched(mat_db: MaterialDB) -> None:
    """Regression guard: original 7 materials must still load with correct E values."""
    expected = {
        "carbon_fiber_hm": 230.0e9,
        "carbon_fiber_std": 135.0e9,
        "carbon_fiber_im": 175.0e9,
        "aluminum_6061_t6": 68.9e9,
        "steel_4130": 205.0e9,
        "balsa": 3.4e9,
        "kevlar_49": 112.0e9,
    }
    for key, e_expected in expected.items():
        mat = mat_db.get(key)
        assert abs(mat.E - e_expected) / e_expected < 1e-6, (
            f"Original material '{key}' E changed: expected {e_expected:.3e}, "
            f"got {mat.E:.3e}. Do NOT modify existing material entries."
        )
