import pytest

from hpa_mdo.concept.config import RiggingDragConfig
from hpa_mdo.concept.mission_drag import compute_rigging_drag_cda_m2


def test_compute_rigging_drag_cda_returns_zero_when_disabled():
    cfg = RiggingDragConfig(
        enabled=False,
        wire_diameter_m=0.0020,
        total_exposed_length_m=24.0,
        drag_coefficient=1.10,
    )
    assert compute_rigging_drag_cda_m2(cfg) == pytest.approx(0.0)


def test_compute_rigging_drag_cda_returns_zero_when_length_is_zero():
    cfg = RiggingDragConfig(
        enabled=True,
        wire_diameter_m=0.0020,
        total_exposed_length_m=0.0,
        drag_coefficient=1.10,
    )
    assert compute_rigging_drag_cda_m2(cfg) == pytest.approx(0.0)


def test_compute_rigging_drag_cda_uses_cylinder_formula():
    cfg = RiggingDragConfig(
        enabled=True,
        wire_diameter_m=0.0020,
        total_exposed_length_m=24.0,
        drag_coefficient=1.10,
    )
    expected = 1.10 * 0.0020 * 24.0
    assert compute_rigging_drag_cda_m2(cfg) == pytest.approx(expected, rel=1e-12)


def test_compute_rigging_drag_cda_override_short_circuits_geometry():
    cfg = RiggingDragConfig(
        enabled=True,
        wire_diameter_m=0.0020,
        total_exposed_length_m=24.0,
        drag_coefficient=1.10,
        cda_override_m2=0.075,
    )
    assert compute_rigging_drag_cda_m2(cfg) == pytest.approx(0.075)


def test_compute_rigging_drag_cda_override_zero_returns_zero():
    cfg = RiggingDragConfig(
        enabled=True,
        wire_diameter_m=0.0020,
        total_exposed_length_m=24.0,
        drag_coefficient=1.10,
        cda_override_m2=0.0,
    )
    assert compute_rigging_drag_cda_m2(cfg) == pytest.approx(0.0)


def test_rigging_drag_config_rejects_negative_diameter():
    with pytest.raises(ValueError):
        RiggingDragConfig(
            wire_diameter_m=-0.001,
            total_exposed_length_m=10.0,
            drag_coefficient=1.10,
        )


def test_rigging_drag_config_rejects_negative_length():
    with pytest.raises(ValueError):
        RiggingDragConfig(
            wire_diameter_m=0.002,
            total_exposed_length_m=-1.0,
            drag_coefficient=1.10,
        )
