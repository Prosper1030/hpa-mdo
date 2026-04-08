from __future__ import annotations

"""Analytic partial derivatives for DualSparPropertiesComp.

Uses ``check_partials(method="cs")`` to verify analytic derivatives against
complex-step. Operating points are chosen strictly in the clip interior.
"""

import numpy as np
import openmdao.api as om
import pytest

from hpa_mdo.structure.oas_structural import DualSparPropertiesComp

NE = 4


def _build_prob(rear: bool, warping_knockdown: float = 1.0) -> om.Problem:
    z_m = np.array([0.05, 0.04, 0.03, 0.02])
    z_r = np.array([-0.02, -0.02, -0.01, -0.01])
    d = np.array([0.12, 0.18, 0.22, 0.25])

    prob = om.Problem()
    prob.model.add_subsystem(
        "spar",
        DualSparPropertiesComp(
            n_elements=NE,
            z_main=z_m,
            z_rear=z_r,
            d_chord=d,
            E_main=240e9,
            G_main=90e9,
            rho_main=1600.0,
            E_rear=200e9,
            G_rear=75e9,
            rho_rear=1550.0,
            rear_enabled=rear,
            warping_knockdown=warping_knockdown,
        ),
        promotes=["*"],
    )
    prob.setup(force_alloc_complex=True)
    return prob


def _set_interior_inputs(prob: om.Problem, rear: bool) -> None:
    prob.set_val("main_t_elem", np.full(NE, 0.0012))
    prob.set_val("main_r_elem", np.full(NE, 0.025))
    if rear:
        prob.set_val("rear_t_elem", np.full(NE, 0.0010))
        prob.set_val("rear_r_elem", np.full(NE, 0.020))


def _abs_error(errs: dict) -> float:
    abs_err = errs["abs error"][0]
    return 0.0 if abs_err is None else float(abs_err)


@pytest.mark.parametrize("rear", [True, False])
def test_analytic_partials_match_cs(rear: bool) -> None:
    """All analytic partials should match complex-step within 1e-5 abs."""
    prob = _build_prob(rear)
    _set_interior_inputs(prob, rear)
    prob.run_model()

    data = prob.check_partials(compact_print=True, method="cs", out_stream=None)

    for comp_data in data.values():
        for (out, inp), errs in comp_data.items():
            abs_err = _abs_error(errs)
            assert abs_err < 1e-5, (
                f"Partial [{out}, {inp}] abs error {abs_err:.3e} > 1e-5"
            )


def test_sparsity_is_diagonal() -> None:
    """Every declared sub-Jacobian entry should use diagonal rows/cols."""
    prob = _build_prob(rear=True)
    _set_interior_inputs(prob, rear=True)
    prob.run_model()

    expected = np.arange(NE)
    input_names = {"spar.main_t_elem", "spar.main_r_elem", "spar.rear_t_elem", "spar.rear_r_elem"}
    for key, meta in prob.model.spar._subjacs_info.items():
        if key[1] not in input_names:
            continue
        np.testing.assert_array_equal(meta["rows"], expected)
        np.testing.assert_array_equal(meta["cols"], expected)


def test_warping_knockdown_reduces_dual_spar_gj() -> None:
    """Lower rigid-rib warping knockdown should reduce torsional stiffness."""
    prob_rigid = _build_prob(rear=True, warping_knockdown=1.0)
    _set_interior_inputs(prob_rigid, rear=True)
    prob_rigid.run_model()

    prob_flexible = _build_prob(rear=True, warping_knockdown=0.25)
    _set_interior_inputs(prob_flexible, rear=True)
    prob_flexible.run_model()

    gj_rigid = prob_rigid.get_val("GJ")
    gj_flexible = prob_flexible.get_val("GJ")
    np.testing.assert_array_less(gj_flexible, gj_rigid)
