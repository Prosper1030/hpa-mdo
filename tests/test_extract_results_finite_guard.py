from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import openmdao.api as om
import pytest

from hpa_mdo.structure.oas_structural import _extract_results


class _FakeProb:
    def __init__(self, values: dict):
        self._values = values
        cfg = SimpleNamespace(rear_spar=SimpleNamespace(enabled=False))
        aircraft = SimpleNamespace(wing=SimpleNamespace(n_stations=3))
        self.model = SimpleNamespace(
            struct=SimpleNamespace(
                options={"cfg": cfg, "aircraft": aircraft},
                _case_names=("default",),
                _multi_case=False,
            )
        )

    def get_val(self, name: str):
        return self._values[name]


def _base_values() -> dict:
    return {
        "struct.mass.spar_mass_half": np.array([1.2]),
        "struct.mass.spar_mass_full": np.array([2.4]),
        "struct.mass.total_mass_full": np.array([3.6]),
        "struct.seg_mapper.main_t_seg": np.array([0.0011, 0.0012]),
        "struct.seg_mapper.main_r_seg": np.array([0.0210, 0.0220]),
        "struct.spar_props.EI_main": np.array([10.0, 9.0]),
        "struct.failure.failure": np.array([-0.1]),
        "struct.buckling.buckling_index": np.array([-0.2]),
        "struct.twist.twist_max_deg": np.array([0.3]),
        "struct.fem.disp": np.zeros((3, 6)),
        "struct.tip_defl.tip_deflection_m": np.array([0.1]),
        "struct.stress.vonmises_main": np.array([1.0e8, 8.0e7]),
    }


def test_extract_results_raises_on_nan_scalar():
    values = _base_values()
    values["struct.mass.total_mass_full"] = np.array([np.nan])
    prob = _FakeProb(values)

    with pytest.raises(om.AnalysisError, match="total_mass_full"):
        _extract_results(prob)


def test_extract_results_raises_on_nonfinite_array():
    values = _base_values()
    values["struct.fem.disp"] = np.array(
        [[0.0, 0.0, 0.0, 0.0, 0.0, 0.0], [np.inf, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0] * 6]
    )
    prob = _FakeProb(values)

    with pytest.raises(om.AnalysisError, match="struct.fem.disp"):
        _extract_results(prob)
