"""Golden / unit tests for ``hpa_mdo.aero.avl_stability_parser``."""

from __future__ import annotations

import math
import textwrap
from pathlib import Path

import pytest

from hpa_mdo.aero.avl_stability_parser import (
    parse_control_mapping_from_avl,
    parse_st_text,
)


# A trimmed-down snapshot that mirrors real AVL output — including the
# ``elevator d01 rudder d02`` column header that the parser must use to
# build the control-index mapping.
GOLDEN_ST = textwrap.dedent(
    """\
     ---------------------------------------------------------------
     Vortex Lattice Output -- Total Forces

     Configuration: Black Cat 004 full aircraft

      Sref =  30.690       Cref =  1.0058       Bref =  33.000
      Xref = 0.25146       Yref =  0.0000       Zref =  0.0000

     Standard axis orientation,  X fwd, Z down

     Run case:  -unnamed-

      Alpha =  10.98762     pb/2V =  -0.00000     p'b/2V =  -0.00000
      Beta  =   0.00000     qc/2V =   0.00000
      Mach  =     0.000     rb/2V =  -0.00000     r'b/2V =  -0.00000

      CXtot =   0.21849     Cltot =  -0.00000     Cl'tot =  -0.00000
      CYtot =  -0.00000     Cmtot =  -0.23110
      CZtot =  -1.21585     Cntot =  -0.00000     Cn'tot =  -0.00000

      CLtot =   1.23521
      CDtot =   0.01726

       elevator        =   0.00000
       rudder          =   0.00000

     Stability-axis derivatives...

                                 alpha                beta
                      ----------------    ----------------
     z' force CL |    CLa =   5.348051    CLb =  -0.000000
     y  force CY |    CYa =  -0.000000    CYb =  -0.245064
     x' mom.  Cl'|    Cla =  -0.000000    Clb =  -0.140542
     y  mom.  Cm |    Cma =  -1.454684    Cmb =  -0.000000
     z' mom.  Cn'|    Cna =  -0.000000    Cnb =   0.004441

                         roll rate  p'      pitch rate  q'        yaw rate  r'
                      ----------------    ----------------    ----------------
     z' force CL |    CLp =  -0.000000    CLq =   5.926507    CLr =  -0.000000
     y  force CY |    CYp =  -0.206636    CYq =  -0.000000    CYr =   0.174724
     x' mom.  Cl'|    Clp =  -0.600380    Clq =   0.000000    Clr =   0.286591
     y  mom.  Cm |    Cmp =  -0.000000    Cmq =  -9.370290    Cmr =   0.000000
     z' mom.  Cn'|    Cnp =  -0.127626    Cnq =  -0.000000    Cnr =  -0.013729

                      elevator     d01     rudder       d02
                      ----------------    ----------------
     z' force CL |   CLd01 =   0.003295   CLd02 =   0.000000
     y  force CY |   CYd01 =  -0.000000   CYd02 =  -0.002123
     x' mom.  Cl'|   Cld01 =   0.000000   Cld02 =  -0.000024
     y  mom.  Cm |   Cmd01 =  -0.012331   Cmd02 =  -0.000000
     z' mom.  Cn'|   Cnd01 =  -0.000000   Cnd02 =   0.000328
    """
)


def test_golden_trim_and_reference_fields():
    d = parse_st_text(GOLDEN_ST)
    assert d.alpha_trim_deg == pytest.approx(10.98762, abs=1e-6)
    assert d.beta_trim_deg == pytest.approx(0.0, abs=1e-9)
    assert d.CL_trim == pytest.approx(1.23521, abs=1e-6)
    assert d.CD_trim == pytest.approx(0.01726, abs=1e-6)
    assert d.Cm_trim == pytest.approx(-0.23110, abs=1e-6)
    assert d.Sref == pytest.approx(30.690, abs=1e-6)
    assert d.bref == pytest.approx(33.000, abs=1e-6)
    assert d.cref == pytest.approx(1.0058, abs=1e-6)
    assert d.Xref == pytest.approx(0.25146, abs=1e-6)
    assert d.mach == pytest.approx(0.0, abs=1e-9)


def test_golden_longitudinal_derivatives():
    d = parse_st_text(GOLDEN_ST)
    assert d.CL_alpha == pytest.approx(5.348051, abs=1e-6)
    assert d.Cm_alpha == pytest.approx(-1.454684, abs=1e-6)
    assert d.CL_q == pytest.approx(5.926507, abs=1e-6)
    assert d.Cm_q == pytest.approx(-9.370290, abs=1e-6)


def test_golden_lateral_directional_derivatives():
    d = parse_st_text(GOLDEN_ST)
    assert d.CY_beta == pytest.approx(-0.245064, abs=1e-6)
    assert d.Cl_beta == pytest.approx(-0.140542, abs=1e-6)
    assert d.Cn_beta == pytest.approx(0.004441, abs=1e-6)
    assert d.Cl_p == pytest.approx(-0.600380, abs=1e-6)
    assert d.Cn_r == pytest.approx(-0.013729, abs=1e-6)
    assert d.CY_r == pytest.approx(0.174724, abs=1e-6)


def test_golden_control_mapping_and_derivatives():
    d = parse_st_text(GOLDEN_ST)
    assert d.control_mapping == {"elevator": 1, "rudder": 2}
    # Elevator → d1 → CLd01, Cmd01
    assert d.CL_de == pytest.approx(0.003295, abs=1e-6)
    assert d.Cm_de == pytest.approx(-0.012331, abs=1e-6)
    # Rudder → d2 → Cnd02
    assert d.Cn_dr == pytest.approx(0.000328, abs=1e-6)
    assert d.Cl_dr == pytest.approx(-0.000024, abs=1e-6)
    # No aileron declared → stays NaN
    assert math.isnan(d.Cl_da)
    assert math.isnan(d.Cn_da)
    assert math.isnan(d.CY_da)


def test_missing_fields_do_not_raise():
    # Empty text: every derivative is NaN, no exception.
    d = parse_st_text("")
    assert math.isnan(d.CL_alpha)
    assert math.isnan(d.Cm_alpha)
    assert math.isnan(d.alpha_trim_deg)
    assert d.control_mapping == {}


def test_negative_glued_values_are_parsed():
    # AVL pitfall: a very large negative number eats the space before it.
    # Example: "Cma =  -1.454684    Cmb = -10.123456"  — no space between.
    text = " Cma =   0.04321   Cmb =-10.123456"
    d = parse_st_text(text)
    assert d.Cm_alpha == pytest.approx(0.04321, abs=1e-6)
    # Cmb is not a field on the dataclass but should live in raw_derivatives.
    assert d.raw_derivatives.get("Cmb") == pytest.approx(-10.123456, abs=1e-6)


def test_control_mapping_override_wins():
    # Explicit override beats whatever the .st header says.
    d = parse_st_text(GOLDEN_ST, control_mapping_override={"rudder": 1, "elevator": 2})
    # Now rudder is d1 so Cn_dr should be pulled from Cnd01 (which is 0).
    assert d.Cn_dr == pytest.approx(0.0, abs=1e-6)
    # And elevator is d2 so Cm_de comes from Cmd02 (0.0 in the golden).
    assert d.Cm_de == pytest.approx(0.0, abs=1e-6)


def test_control_mapping_from_avl(tmp_path: Path):
    avl = tmp_path / "toy.avl"
    avl.write_text(
        textwrap.dedent(
            """\
            # toy geometry
            SURFACE
            Elevator
            SECTION
            CONTROL
            elevator  1.0  0.0  0.0  0.0  0.0  1.0
            SECTION
            CONTROL
            elevator  1.0  0.0  0.0  0.0  0.0  1.0
            SURFACE
            Fin
            SECTION
            CONTROL
            rudder  1.0  0.0  0.0  0.0  1.0  1.0
            """
        ),
        encoding="utf-8",
    )
    mapping = parse_control_mapping_from_avl(avl)
    assert mapping == {"elevator": 1, "rudder": 2}
