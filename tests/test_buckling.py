from __future__ import annotations

import numpy as np
import openmdao.api as om

from hpa_mdo.structure.buckling import BucklingComp


def _build_prob(nn: int = 5, rear: bool = True) -> om.Problem:
    prob = om.Problem()
    prob.model.add_subsystem(
        "buckling",
        BucklingComp(
            n_nodes=nn,
            E_main=240e9,
            E_rear=240e9,
            rear_enabled=rear,
            knockdown_factor=0.65,
            bending_enhancement=1.3,
        ),
        promotes=["*"],
    )
    prob.setup(force_alloc_complex=True)
    return prob


def _set_common_inputs(prob: om.Problem, nn: int, main_r: float, main_t: float) -> None:
    ne = nn - 1
    prob["nodes"] = np.column_stack(
        [np.zeros(nn), np.linspace(0.0, 4.0, nn), np.zeros(nn)]
    )
    prob["main_r_elem"] = np.full(ne, main_r)
    prob["main_t_elem"] = np.full(ne, main_t)
    prob["rear_r_elem"] = np.full(ne, 0.04)
    prob["rear_t_elem"] = np.full(ne, main_t)


def _get_scalar(prob: om.Problem, name: str) -> float:
    return float(np.asarray(prob.get_val(name)).item())


def test_safe_design_gives_negative_buckling_index():
    """厚管、低曲率 -> buckling_index < 0."""
    prob = _build_prob(nn=5)
    nn = 5

    prob["disp"] = np.zeros((nn, 6))
    prob["disp"][:, 3] = np.linspace(0.0, 0.001, nn)
    _set_common_inputs(prob, nn, main_r=0.04, main_t=0.003)

    prob.run_model()

    assert _get_scalar(prob, "buckling_index") < 0.0


def test_unsafe_design_gives_positive_buckling_index():
    """薄管、高曲率 -> buckling_index > 0."""
    prob = _build_prob(nn=5)
    nn = 5

    prob["disp"] = np.zeros((nn, 6))
    prob["disp"][:, 3] = np.linspace(0.0, 0.4, nn)
    _set_common_inputs(prob, nn, main_r=0.04, main_t=0.0003)

    prob.run_model()

    assert _get_scalar(prob, "buckling_index") > 0.0


def test_buckling_comp_check_partials():
    """BucklingComp partials should match complex-step."""
    prob = _build_prob(nn=5)
    nn = 5

    prob["disp"] = np.zeros((nn, 6))
    prob["disp"][:, 3] = np.linspace(0.0, 0.01, nn)
    _set_common_inputs(prob, nn, main_r=0.04, main_t=0.001)
    prob["rear_r_elem"] = np.full(nn - 1, 0.035)
    prob["rear_t_elem"] = np.full(nn - 1, 0.001)

    prob.run_model()
    data = prob.check_partials(compact_print=True, method="cs", out_stream=None)

    for comp_data in data.values():
        for errs in comp_data.values():
            assert errs["abs error"][0] < 1e-5


def test_buckling_scales_with_bending_enhancement():
    """Higher bending enhancement should reduce buckling index."""

    def _run(beta: float) -> float:
        prob = om.Problem()
        prob.model.add_subsystem(
            "buckling",
            BucklingComp(
                n_nodes=5,
                E_main=240e9,
                E_rear=240e9,
                rear_enabled=True,
                knockdown_factor=0.65,
                bending_enhancement=beta,
            ),
            promotes=["*"],
        )
        prob.setup(force_alloc_complex=True)
        nn = 5
        ne = nn - 1
        prob["disp"] = np.zeros((nn, 6))
        prob["disp"][:, 3] = np.linspace(0.0, 0.05, nn)
        prob["nodes"] = np.column_stack(
            [np.zeros(nn), np.linspace(0.0, 4.0, nn), np.zeros(nn)]
        )
        prob["main_r_elem"] = np.full(ne, 0.04)
        prob["main_t_elem"] = np.full(ne, 0.001)
        prob["rear_r_elem"] = np.full(ne, 0.04)
        prob["rear_t_elem"] = np.full(ne, 0.001)
        prob.run_model()
        return _get_scalar(prob, "buckling_index")

    bi_low = _run(1.0)
    bi_high = _run(1.5)
    assert bi_high < bi_low
