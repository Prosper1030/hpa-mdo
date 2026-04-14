from __future__ import annotations

from pathlib import Path

import pytest

from hpa_mdo.aero.aswing_exporter import export_aswing, parse_avl
from hpa_mdo.core import MaterialDB, load_config


REPO_ROOT = Path(__file__).resolve().parents[1]
AVL_PATH = REPO_ROOT / "data" / "blackcat_004_full.avl"
CONFIG_PATH = REPO_ROOT / "configs" / "blackcat_004.yaml"
MATERIALS_PATH = REPO_ROOT / "data" / "materials.yaml"


def test_parse_avl_reads_full_aircraft_geometry() -> None:
    model = parse_avl(AVL_PATH)

    assert model.title == "Black Cat 004 full aircraft"
    assert model.sref == pytest.approx(30.69)
    assert model.cref == pytest.approx(1.005842294)
    assert model.bref == pytest.approx(33.0)
    assert [surface.name for surface in model.surfaces] == ["Wing", "Elevator", "Fin"]

    wing = model.surfaces[0]
    assert wing.symmetric is True
    assert len(wing.sections) == 7
    assert [section.y for section in wing.sections] == pytest.approx(
        [0.0, 1.5, 4.5, 7.5, 10.5, 13.5, 16.5]
    )
    assert wing.sections[-1].z == pytest.approx(1.73)
    assert wing.sections[-1].airfoil == "NACA 2412"

    elevator = model.surfaces[1]
    assert elevator.sections[0].controls == ("elevator",)
    fin = model.surfaces[2]
    assert fin.symmetric is False
    assert [section.z for section in fin.sections] == pytest.approx([-0.7, 1.7])
    assert fin.sections[0].controls == ("rudder",)


def test_export_aswing_writes_seed_blocks(tmp_path: Path) -> None:
    cfg = load_config(CONFIG_PATH, local_paths_path=tmp_path / "missing_local_paths.yaml")
    output_path = tmp_path / "blackcat_004_full.asw"

    export_aswing(
        AVL_PATH,
        cfg,
        output_path,
        materials_db=MaterialDB(MATERIALS_PATH),
    )

    text = output_path.read_text(encoding="utf-8")
    assert "Name\nBlack Cat 004 full aircraft - ASWING seed\nEnd" in text
    assert "Units\nL 1.0 m\nT 1.0 s\nF 1.0 N\nEnd" in text
    assert "# Sref Cref Bref\n30.69 1.00584229 33" in text
    assert "! load_case default: aero_scale=2 nz=2 V=6.5 rho=1.225" in text
    assert "Weight\n# Nbeam t Xp Yp Zp Mg CDA Vol Hx Hy Hz" in text
    assert "Strut\n# Nbeam t Xp Yp Zp Xw Yw Zw dL EAw" in text
    assert "1 7.5 0 7.5 0.38 0.0 0.0 -1.5 0.0" in text
    assert "1 -7.5 0 -7.5 0.38 0.0 0.0 -1.5 0.0" in text

    assert "Beam 1 Wing" in text
    assert "0 1.39 0 0 0 0.25" in text
    assert "16.5 0.47 0 16.5 1.73 0.25" in text
    assert "# t EIcc EInn GJ" in text
    assert "# t EA mg" in text

    assert "Beam 2 Elevator" in text
    assert "# t dCLdF2 dCMdF2" in text
    assert "Beam 3 Fin" in text
    assert "-0.7 0.7 5 0 -0.7 0.3" in text
    assert "# t dCLdF3 dCMdF3" in text
