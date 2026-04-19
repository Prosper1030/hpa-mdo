from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from hpa_mdo.aero.aswing_exporter import export_aswing, parse_avl
from hpa_mdo.core import MaterialDB, load_config


REPO_ROOT = Path(__file__).resolve().parents[1]
AVL_PATH = REPO_ROOT / "data" / "blackcat_004_full.avl"
CONFIG_PATH = REPO_ROOT / "configs" / "blackcat_004.yaml"
MATERIALS_PATH = REPO_ROOT / "data" / "materials.yaml"


def test_parse_avl_reads_full_aircraft_geometry() -> None:
    model = parse_avl(AVL_PATH)

    assert model.title == "Black Cat 004"
    assert model.sref == pytest.approx(35.175)
    assert model.cref == pytest.approx(1.130189765)
    assert model.bref == pytest.approx(33.0)
    assert [surface.name for surface in model.surfaces] == ["Main Wing", "Elevator", "Fin"]

    wing = model.surfaces[0]
    assert wing.symmetric is True
    assert len(wing.sections) == 6
    assert [section.y for section in wing.sections] == pytest.approx(
        [0.0, 4.5, 7.5, 10.5, 13.5, 16.5]
    )
    assert wing.sections[-1].z == pytest.approx(0.810978837)
    assert wing.sections[0].ainc == pytest.approx(0.0)
    assert wing.sections[0].airfoil == "INLINE_AIRFOIL"
    assert wing.sections[-1].airfoil == "INLINE_AIRFOIL"

    elevator = model.surfaces[1]
    assert elevator.sections[0].controls == ("elevator",)
    assert elevator.sections[-1].y == pytest.approx(1.5)
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
    assert "Name\nBlack Cat 004 - ASWING seed\nEnd" in text
    assert "Units\nL 1.0 m\nT 1.0 s\nF 1.0 N\nEnd" in text
    assert "# Sref Cref Bref\n35.175 1.13018976 33" in text
    assert "! load_case default: aero_scale=2 nz=2 V=6.5 rho=1.225" in text
    assert "Weight\n# Nbeam t Xp Yp Zp Mg CDA Vol Hx Hy Hz" in text
    assert "Strut\n# Nbeam t Xp Yp Zp Xw Yw Zw dL EAw" in text
    assert "1 7.5 0 7.5 0.183234319 0.0 0.0 -1.5 0.0" in text
    assert "1 -7.5 0 -7.5 0.183234319 0.0 0.0 -1.5 0.0" in text

    assert "Beam 1 Main Wing" in text
    assert "0 1.3 0 0 0 0.25" in text
    assert "16.5 0.435 0 16.5 0.810978837 0.25" in text
    assert "# t EIcc EInn GJ" in text
    assert "# t EA mg" in text

    assert "Beam 2 Elevator" in text
    assert "# t dCLdF2 dCMdF2" in text
    assert "Beam 3 Fin" in text
    assert "-0.7 0.7 5 0 -0.7 0.3" in text
    assert "# t dCLdF3 dCMdF3" in text


def test_export_aswing_preserves_multiple_generic_wing_controls(tmp_path: Path) -> None:
    avl_path = tmp_path / "wing_controls.avl"
    avl_path.write_text(
        textwrap.dedent(
            """\
            Wing Controls Demo
            #Mach
            0.000000
            #IYsym  iZsym  Zsym
            0  0  0.000000
            #Sref  Cref  Bref
            30.000000000  1.000000000  20.000000000
            #Xref  Yref  Zref
            0.250000000  0.000000000  0.000000000
            #CDp
            0.000000
            #
            SURFACE
            Wing
            12  1.0  30  -2.0
            #
            COMPONENT
            1
            YDUPLICATE
            0.0
            #
            SECTION
            0.000000000  0.000000000  0.000000000  1.300000000  0.000000000
            NACA
            2412
            #
            SECTION
            0.000000000  6.000000000  0.200000000  0.900000000  0.000000000
            NACA
            2412
            CONTROL
            flap  1.0  0.700000  0.0 0.0 0.0  1.0
            #
            SECTION
            0.000000000  10.000000000  0.500000000  0.600000000  0.000000000
            NACA
            2412
            CONTROL
            aileron  1.0  0.750000  0.0 0.0 0.0  -1.0
            #
            """
        ),
        encoding="utf-8",
    )
    cfg = load_config(CONFIG_PATH, local_paths_path=tmp_path / "missing_local_paths.yaml")
    output_path = tmp_path / "wing_controls.asw"

    export_aswing(
        avl_path,
        cfg,
        output_path,
        materials_db=MaterialDB(MATERIALS_PATH),
    )

    text = output_path.read_text(encoding="utf-8")
    assert "Beam 1 Wing" in text
    assert "# t dCLdF1 dCMdF1" in text
    assert "# t dCLdF4 dCMdF4" in text


def test_parse_avl_accepts_inline_airfoil_sections(tmp_path: Path) -> None:
    avl_path = tmp_path / "inline.avl"
    avl_path.write_text(
        textwrap.dedent(
            """\
            Inline Airfoil Demo
            #Mach
            0.000000
            #IYsym  iZsym  Zsym
            0  0  0.000000
            #Sref  Cref  Bref
            10.000000000  1.000000000  8.000000000
            #Xref  Yref  Zref
            0.250000000  0.000000000  0.000000000
            #CDp
            0.000000
            #
            SURFACE
            Wing
            12  1.0  30  -2.0
            #
            SECTION
            0.000000000  0.000000000  0.000000000  1.200000000  0.000000000
            AIRFOIL
            1.0 0.0
            0.5 0.08
            0.0 0.0
            0.5 -0.04
            1.0 0.0
            #
            SECTION
            0.000000000  4.000000000  0.200000000  0.600000000  0.000000000
            AIRFOIL
            1.0 0.0
            0.5 0.06
            0.0 0.0
            0.5 -0.03
            1.0 0.0
            #
            """
        ),
        encoding="utf-8",
    )

    model = parse_avl(avl_path)

    assert model.title == "Inline Airfoil Demo"
    assert len(model.surfaces) == 1
    assert len(model.surfaces[0].sections) == 2
    assert model.surfaces[0].sections[0].airfoil == "INLINE_AIRFOIL"
