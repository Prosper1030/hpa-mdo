from __future__ import annotations

import numpy as np

from hpa_mdo.api._shared import json_safe


def test_json_safe_recurses_into_strain_envelope_dict() -> None:
    payload = {
        "strain_envelope": {
            "epsilon_x_absmax": np.array([1.0e-4, 2.0e-4]),
            "nested": (np.float64(0.5), np.int64(2)),
        }
    }

    safe = json_safe(payload)

    assert safe == {
        "strain_envelope": {
            "epsilon_x_absmax": [1.0e-4, 2.0e-4],
            "nested": [0.5, 2],
        }
    }
