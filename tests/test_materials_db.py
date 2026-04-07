from __future__ import annotations

from pathlib import Path

import pytest

from hpa_mdo.core.materials import MaterialDB


def test_load_materials_from_yaml():
    repo_root = Path(__file__).resolve().parents[1]
    db = MaterialDB(repo_root / "data" / "materials.yaml")
    materials = db.as_dict()

    assert isinstance(materials, dict)
    assert materials


def test_get_known_material_returns_correct_properties():
    repo_root = Path(__file__).resolve().parents[1]
    db = MaterialDB(repo_root / "data" / "materials.yaml")
    mat = db.get("carbon_fiber_hm")

    assert mat.E > 0
    assert mat.density > 0


def test_missing_key_raises_key_error():
    repo_root = Path(__file__).resolve().parents[1]
    db = MaterialDB(repo_root / "data" / "materials.yaml")

    with pytest.raises(KeyError):
        db.get("this_material_does_not_exist")


def test_materials_db_supports_contains():
    repo_root = Path(__file__).resolve().parents[1]
    db = MaterialDB(repo_root / "data" / "materials.yaml")

    assert "carbon_fiber_hm" in db
