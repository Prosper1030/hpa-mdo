from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.aero.load_mapper import ConservativeLoadMapper, LoadMapper
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


def _nonuniform_spanwise_load() -> SpanwiseLoad:
    y = np.array([0.0, 0.35, 1.1, 1.85, 3.0, 4.0])
    chord = np.array([1.35, 1.26, 1.11, 0.96, 0.78, 0.58])
    cl = np.array([0.43, 0.64, 0.88, 0.78, 0.51, 0.18])
    cd = np.array([0.021, 0.023, 0.026, 0.025, 0.022, 0.02])
    cm = np.array([-0.065, -0.083, -0.097, -0.089, -0.061, -0.032])
    q = 31.0
    return SpanwiseLoad(
        y=y,
        chord=chord,
        cl=cl,
        cd=cd,
        cm=cm,
        lift_per_span=q * chord * cl,
        drag_per_span=q * chord * cd,
        aoa_deg=4.5,
        velocity=7.1,
        dynamic_pressure=q,
    )


def _integral(values: np.ndarray, y: np.ndarray) -> float:
    return float(np.trapezoid(np.asarray(values, dtype=float), np.asarray(y, dtype=float)))


def _root_bending(values: np.ndarray, y: np.ndarray) -> float:
    y_arr = np.asarray(y, dtype=float)
    return _integral(np.asarray(values, dtype=float) * y_arr, y_arr)


def _torque_per_span(load: SpanwiseLoad) -> np.ndarray:
    return load.dynamic_pressure * load.chord**2 * load.cm


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


def test_default_mapper_uses_linear_to_avoid_cubic_overshoot():
    y = np.linspace(0.0, 4.0, 5)
    load = SpanwiseLoad(
        y=y,
        chord=np.ones_like(y),
        cl=np.zeros_like(y),
        cd=np.zeros_like(y),
        cm=np.zeros_like(y),
        lift_per_span=np.array([0.0, 2.0, 0.0, 2.0, 0.0]),
        drag_per_span=np.zeros_like(y),
        aoa_deg=0.0,
        velocity=1.0,
        dynamic_pressure=1.0,
    )
    struct_y = np.linspace(0.0, 4.0, 9)

    default_total = float(
        np.trapezoid(LoadMapper().map_loads(load, struct_y)["lift_per_span"], struct_y)
    )
    cubic_total = float(
        np.trapezoid(
            LoadMapper(method="cubic").map_loads(load, struct_y)["lift_per_span"],
            struct_y,
        )
    )

    assert default_total == pytest.approx(4.0)
    assert cubic_total > default_total


def test_conservative_mapper_preserves_total_lift_on_nonuniform_grids():
    load = _nonuniform_spanwise_load()
    struct_y = np.linspace(0.0, 4.0, 6)
    mapper = ConservativeLoadMapper(method="linear")

    mapped = mapper.map_loads(load, struct_y)
    diagnostics = mapped["conservation_diagnostics"]

    source_total = _integral(load.lift_per_span, load.y)
    linear_total = _integral(
        LoadMapper(method="linear").map_loads(load, struct_y)["lift_per_span"],
        struct_y,
    )

    assert linear_total != pytest.approx(source_total, rel=1e-4)
    assert mapped["total_lift"] == pytest.approx(source_total, rel=1e-10, abs=1e-10)
    assert diagnostics["total_lift_source_n"] == pytest.approx(source_total)
    assert abs(diagnostics["total_lift_error_before_n"]) > 1.0e-3
    assert diagnostics["total_lift_after_n"] == pytest.approx(source_total)
    assert diagnostics["total_lift_error_after_n"] == pytest.approx(0.0, abs=1e-10)
    assert diagnostics["lift_sign_reversal_count"] == 0


def test_conservative_mapper_preserves_root_bending_moment():
    load = _nonuniform_spanwise_load()
    struct_y = np.linspace(0.0, 4.0, 6)
    mapper = ConservativeLoadMapper(method="linear")

    mapped = mapper.map_loads(load, struct_y)
    diagnostics = mapped["conservation_diagnostics"]

    source_root_moment = _root_bending(load.lift_per_span, load.y)
    mapped_root_moment = _root_bending(mapped["lift_per_span"], mapped["y"])

    assert mapped_root_moment == pytest.approx(source_root_moment, rel=1e-10, abs=1e-10)
    assert diagnostics["root_bending_moment_source_nm"] == pytest.approx(source_root_moment)
    assert abs(diagnostics["root_moment_error_before_nm"]) > 1.0e-3
    assert diagnostics["root_bending_moment_after_nm"] == pytest.approx(source_root_moment)
    assert diagnostics["root_moment_error_after_nm"] == pytest.approx(0.0, abs=1e-10)
    assert diagnostics["lift_correction_norm_npm"] > 0.0


def test_conservative_mapper_preserves_total_torque_when_cm_contract_exists():
    load = _nonuniform_spanwise_load()
    struct_y = np.linspace(0.0, 4.0, 6)
    mapper = ConservativeLoadMapper(method="linear")

    mapped = mapper.map_loads(load, struct_y)
    diagnostics = mapped["conservation_diagnostics"]

    source_torque = _integral(_torque_per_span(load), load.y)
    mapped_torque = _integral(mapped["torque_per_span"], mapped["y"])

    assert mapped_torque == pytest.approx(source_torque, rel=1e-10, abs=1e-10)
    assert diagnostics["total_torque_source_nm"] == pytest.approx(source_torque)
    assert abs(diagnostics["torque_error_before_nm"]) > 1.0e-3
    assert diagnostics["total_torque_after_nm"] == pytest.approx(source_torque)
    assert diagnostics["torque_error_after_nm"] == pytest.approx(0.0, abs=1e-10)
    assert diagnostics["torque_sign_reversal_count"] == 0


@pytest.mark.parametrize(
    ("load", "struct_y", "message"),
    [
        (
            SpanwiseLoad(
                y=np.array([0.0, 1.0]),
                chord=np.array([1.0, 0.8]),
                cl=np.array([0.5, 0.4]),
                cd=np.array([0.02, 0.02]),
                cm=np.array([-0.08, -0.07]),
                lift_per_span=np.array([10.0, 8.0]),
                drag_per_span=np.array([0.4, 0.3]),
                aoa_deg=2.0,
                velocity=6.0,
                dynamic_pressure=22.0,
            ),
            np.array([0.0, 0.5, 1.0]),
            "at least 3 aero stations",
        ),
        (_sample_spanwise_load(), np.array([0.0, 1.0]), "at least 3 structural nodes"),
        (_sample_spanwise_load(), np.array([0.0, 1.0, 1.0, 2.0]), "strictly increasing"),
    ],
)
def test_conservative_mapper_rejects_degenerate_grids(load, struct_y, message):
    mapper = ConservativeLoadMapper(method="linear")

    with pytest.raises(ValueError, match=message):
        mapper.map_loads(load, struct_y)


def test_conservative_mapper_rejects_nan_like_linear_mapper():
    bad = _sample_spanwise_load()
    bad.cm[2] = np.nan
    mapper = ConservativeLoadMapper(method="linear")

    with pytest.raises(ValueError, match="NaN/Inf"):
        mapper.map_loads(bad, np.linspace(0.0, 4.0, 7))


def test_conservative_mapper_reports_large_projection_status():
    y = np.linspace(0.0, 4.0, 5)
    load = SpanwiseLoad(
        y=y,
        chord=np.ones_like(y),
        cl=np.array([4.0, 0.0, 4.0, 0.0, 4.0]),
        cd=np.zeros_like(y),
        cm=np.zeros_like(y),
        lift_per_span=np.array([100.0, 0.0, 100.0, 0.0, 100.0]),
        drag_per_span=np.zeros_like(y),
        aoa_deg=0.0,
        velocity=1.0,
        dynamic_pressure=25.0,
    )
    mapper = ConservativeLoadMapper(method="linear")

    diagnostics = mapper.map_loads(load, np.linspace(0.0, 4.0, 3))[
        "conservation_diagnostics"
    ]

    assert diagnostics["status"] == "conserved_with_large_correction"
    assert diagnostics["warnings"]
    assert diagnostics["correction_l2_norm"] > 0.25
    assert diagnostics["sign_reversal_count"] == 0


def test_linear_mapper_behavior_is_unchanged_by_conservative_mapper():
    load = _nonuniform_spanwise_load()
    struct_y = np.linspace(0.0, 4.0, 6)
    mapped = LoadMapper(method="linear").map_loads(load, struct_y)

    expected_lift = np.interp(struct_y, load.y, load.lift_per_span)

    assert "conservation_diagnostics" not in mapped
    assert mapped["lift_per_span"] == pytest.approx(expected_lift)
    assert mapped["total_lift"] == pytest.approx(_integral(expected_lift, struct_y))


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


def test_clip_bug_total_lift_matches_integration():
    """驗證當 struct_y 超出 aero y 範圍時，
    total_lift 與實際積分結果一致，不會被 clip 放大。"""
    # aero 資料只覆蓋 y in [0, 3.0]
    y_aero = np.linspace(0, 3.0, 6)
    chord = np.ones(6) * 1.0
    cl = np.ones(6) * 0.5  # 均勻升力
    load = SpanwiseLoad(
        y=y_aero,
        chord=chord,
        cl=cl,
        cd=np.zeros(6),
        cm=np.zeros(6),
        lift_per_span=np.ones(6) * 50,
        drag_per_span=np.zeros(6),
        aoa_deg=3.0,
        velocity=7.0,
        dynamic_pressure=25.0,
    )

    # 結構網格延伸到 y=5.0（超出 aero 範圍）
    struct_y = np.linspace(0, 5.0, 21)
    mapper = LoadMapper(method="linear")
    result = mapper.map_loads(load, struct_y, scale_factor=1.0)

    # 獨立積分驗證：只在 aero 有效範圍內積分
    valid_mask = struct_y <= y_aero[-1]
    valid_lift = result["lift_per_span"][valid_mask]
    valid_y = struct_y[valid_mask]
    expected = float(np.trapezoid(valid_lift, valid_y))

    # total_lift 不應該包含 clip 後的延伸段
    assert result["total_lift"] == pytest.approx(expected, rel=0.05), (
        f"LoadMapper clip bug: total_lift={result['total_lift']}, expected={expected}"
    )
