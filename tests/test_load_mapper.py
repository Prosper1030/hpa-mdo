from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.aero.load_mapper import LoadMapper
from hpa_mdo.core.aircraft import Aircraft
from hpa_mdo.core.config import load_config


def _sample_spanwise_load(chord: np.ndarray | None = None) -> SpanwiseLoad:
    y = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    chord_vals = np.array([1.2, 1.1, 1.0, 0.9, 0.8]) if chord is None else chord
    cl = np.array([0.6, 0.62, 0.64, 0.66, 0.68])
    cd = np.array([0.02, 0.021, 0.022, 0.023, 0.024])
    cm = np.array([-0.08, -0.079, -0.078, -0.077, -0.076])
    q = 25.0
    lift = q * chord_vals * cl
    drag = q * chord_vals * cd
    return SpanwiseLoad(
        y=y,
        chord=chord_vals,
        cl=cl,
        cd=cd,
        cm=cm,
        lift_per_span=lift,
        drag_per_span=drag,
        aoa_deg=3.0,
        velocity=7.0,
        dynamic_pressure=q,
    )


def test_map_loads_raises_for_nan_input():
    bad = _sample_spanwise_load()
    bad.lift_per_span[2] = np.nan
    mapper = LoadMapper(method="linear")

    with pytest.raises(ValueError, match="NaN/Inf"):
        mapper.map_loads(bad, np.linspace(0.0, 4.0, 9))


def test_map_loads_raises_for_nonpositive_chord():
    bad = _sample_spanwise_load(chord=np.array([1.2, 1.1, 0.0, 0.9, 0.8]))
    mapper = LoadMapper(method="linear")

    with pytest.raises(ValueError, match="strictly positive"):
        mapper.map_loads(bad, np.linspace(0.0, 4.0, 9))


def test_map_loads_returns_finite_output_for_valid_data():
    load = _sample_spanwise_load()
    struct_y = np.linspace(0.0, 4.0, 9)
    mapper = LoadMapper(method="linear")

    mapped = mapper.map_loads(load, struct_y, scale_factor=1.5)

    assert mapped["y"].shape == struct_y.shape
    assert mapped["lift_per_span"].shape == struct_y.shape
    assert np.all(np.isfinite(mapped["lift_per_span"]))
    assert np.all(np.isfinite(mapped["torque_per_span"]))
    assert mapped["total_lift"] == pytest.approx(
        float(np.trapezoid(mapped["lift_per_span"], struct_y))
    )


def test_load_factor_applied_exactly_once():
    load = _sample_spanwise_load()
    struct_y = np.linspace(0.0, 4.0, 9)
    mapper = LoadMapper(method="linear")

    base = mapper.map_loads(load, struct_y, scale_factor=1.0)
    factored = mapper.map_loads(load, struct_y, scale_factor=2.0)

    ratio = factored["total_lift"] / base["total_lift"]
    assert ratio == pytest.approx(2.0, rel=0.01)


def test_chord_zero_raises_value_error():
    bad = _sample_spanwise_load(chord=np.array([1.2, 1.1, 0.0, 0.9, 0.8]))
    mapper = LoadMapper(method="linear")

    with pytest.raises(ValueError):
        mapper.map_loads(bad, np.linspace(0.0, 4.0, 9))


def test_nan_in_cl_raises_value_error():
    bad = _sample_spanwise_load()
    bad.cl[1] = np.nan
    mapper = LoadMapper(method="linear")

    with pytest.raises(ValueError):
        mapper.map_loads(bad, np.linspace(0.0, 4.0, 9))


def test_inf_in_lift_raises_value_error():
    bad = _sample_spanwise_load()
    bad.lift_per_span[2] = np.inf
    mapper = LoadMapper(method="linear")

    with pytest.raises(ValueError):
        mapper.map_loads(bad, np.linspace(0.0, 4.0, 9))


def test_non_monotonic_y_raises_value_error():
    y = np.array([0.0, 1.0, 0.5, 2.0])
    chord = np.array([1.2, 1.1, 1.0, 0.9])
    cl = np.array([0.6, 0.62, 0.64, 0.66])
    cd = np.array([0.02, 0.021, 0.022, 0.023])
    cm = np.array([-0.08, -0.079, -0.078, -0.077])
    q = 25.0
    load = SpanwiseLoad(
        y=y,
        chord=chord,
        cl=cl,
        cd=cd,
        cm=cm,
        lift_per_span=q * chord * cl,
        drag_per_span=q * chord * cd,
        aoa_deg=3.0,
        velocity=7.0,
        dynamic_pressure=q,
    )
    mapper = LoadMapper(method="linear")

    with pytest.raises(ValueError):
        mapper.map_loads(load, np.linspace(0.0, 2.0, 6))


def test_total_lift_integration_accuracy():
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(repo_root / "configs" / "blackcat_004.yaml")

    if cfg.io.vsp_lod is None or not cfg.io.vsp_lod.exists():
        pytest.skip(f"VSPAero .lod not found: {cfg.io.vsp_lod}")

    try:
        from hpa_mdo.aero.vsp_aero import VSPAeroParser
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"VSPAero parser unavailable: {exc}")

    parser = VSPAeroParser(cfg.io.vsp_lod, cfg.io.vsp_polar)
    cases = parser.parse()
    if not cases:
        pytest.skip("No VSPAero cases were parsed from .lod.")

    aircraft = Aircraft.from_config(cfg)
    mapper = LoadMapper()
    result = mapper.map_loads(
        cases[0],
        aircraft.wing.y,
        actual_velocity=cfg.flight.velocity,
        actual_density=cfg.flight.air_density,
    )
    integrated = float(np.trapezoid(result["lift_per_span"], result["y"]))
    if abs(result["total_lift"]) < 1e-12:
        pytest.skip("total_lift is too small for a stable relative-error check.")

    rel_err = abs(integrated - result["total_lift"]) / abs(result["total_lift"])
    assert rel_err < 0.05
