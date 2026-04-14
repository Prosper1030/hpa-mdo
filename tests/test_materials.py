from __future__ import annotations

from pathlib import Path

import pytest

from hpa_mdo.core.materials import MaterialDB, PlyMaterial


REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "materials.yaml"


@pytest.fixture(scope="module")
def mat_db() -> MaterialDB:
    return MaterialDB(DB_PATH)


def test_get_known_ply_material_returns_expected_properties(mat_db: MaterialDB) -> None:
    ply = mat_db.get_ply("cfrp_ply_hm")

    assert isinstance(ply, PlyMaterial)
    assert ply.E1 == pytest.approx(230.0e9)
    assert ply.E2 == pytest.approx(8.0e9)
    assert ply.G12 == pytest.approx(5.0e9)
    assert ply.t_ply == pytest.approx(0.125e-3)
    assert ply.F1t == pytest.approx(2500.0e6)
    assert ply.F1c == pytest.approx(1500.0e6)
    assert ply.F2t == pytest.approx(50.0e6)
    assert ply.F2c == pytest.approx(200.0e6)
    assert ply.F6 == pytest.approx(100.0e6)


def test_get_carbon_t700_proxy_ply_material(mat_db: MaterialDB) -> None:
    ply = mat_db.get_ply("carbon_t700_proxy")

    assert isinstance(ply, PlyMaterial)
    assert ply.E1 == pytest.approx(135.0e9)
    assert ply.E2 == pytest.approx(10.0e9)
    assert ply.G12 == pytest.approx(5.0e9)
    assert ply.t_ply == pytest.approx(0.125e-3)
    assert ply.density == pytest.approx(1550.0)
    assert ply.F1t == pytest.approx(1500.0e6)
    assert ply.F1c == pytest.approx(1200.0e6)
    assert ply.F2t == pytest.approx(50.0e6)
    assert ply.F2c == pytest.approx(250.0e6)
    assert ply.F6 == pytest.approx(70.0e6)


@pytest.mark.parametrize(
    ("key", "expected_nu21"),
    [
        ("cfrp_ply_hm", 0.27 * 8.0e9 / 230.0e9),
        ("cfrp_ply_sm", 0.28 * 10.0e9 / 130.0e9),
    ],
)
def test_ply_material_nu21_is_derived_from_nu12_and_moduli(
    mat_db: MaterialDB,
    key: str,
    expected_nu21: float,
) -> None:
    ply = mat_db.get_ply(key)

    assert ply.nu21 == pytest.approx(expected_nu21)


def test_get_ply_rejects_isotropic_material_key(mat_db: MaterialDB) -> None:
    with pytest.raises(KeyError):
        mat_db.get_ply("carbon_fiber_hm")


def test_existing_isotropic_material_loading_is_unchanged(mat_db: MaterialDB) -> None:
    material = mat_db.get("carbon_fiber_hm")

    assert material.E == pytest.approx(230.0e9)
    assert material.G == pytest.approx(15.0e9)
    assert material.density == pytest.approx(1600.0)
