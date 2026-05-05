from __future__ import annotations

import math
from pathlib import Path

import pytest

from hpa_mdo.concept.avl_loader import write_concept_wing_only_avl
from hpa_mdo.concept.geometry import GeometryConcept, WingStation
from hpa_mdo.concept.loaded_shape import (
    apply_loaded_shape_to_stations,
    build_loaded_wing_shape,
)


def _concept() -> GeometryConcept:
    return GeometryConcept(
        span_m=20.0,
        wing_area_m2=20.0,
        root_chord_m=1.2,
        tip_chord_m=0.8,
        twist_root_deg=2.0,
        twist_tip_deg=-1.0,
        tail_area_m2=3.0,
        cg_xc=0.30,
        segment_lengths_m=(5.0, 5.0),
        dihedral_root_deg=0.0,
        dihedral_tip_deg=0.0,
    )


def test_zero_loaded_dihedral_gives_flat_loaded_shape() -> None:
    shape = build_loaded_wing_shape(
        span_m=20.0,
        eta=(0.0, 0.5, 1.0),
        loaded_tip_dihedral_deg=0.0,
        loaded_shape_mode="flat",
    )

    assert shape.loaded_shape_mode == "flat"
    assert shape.loaded_tip_z_m == pytest.approx(0.0)
    assert all(z == pytest.approx(0.0) for z in shape.z_loaded_m)


def test_linear_loaded_dihedral_gives_expected_tip_z() -> None:
    shape = build_loaded_wing_shape(
        span_m=20.0,
        eta=(0.0, 0.5, 1.0),
        loaded_tip_dihedral_deg=5.0,
        loaded_shape_mode="linear_dihedral",
    )

    expected_tip_z = 10.0 * math.tan(math.radians(5.0))
    assert shape.loaded_tip_z_m == pytest.approx(expected_tip_z)
    assert shape.z_loaded_m[-1] == pytest.approx(expected_tip_z)
    assert shape.loaded_tip_dihedral_deg == pytest.approx(5.0)


def test_avl_writer_uses_nonzero_section_z_for_loaded_shape(tmp_path: Path) -> None:
    concept = _concept()
    stations = (
        WingStation(y_m=0.0, chord_m=1.2, twist_deg=2.0, dihedral_deg=0.0),
        WingStation(y_m=5.0, chord_m=1.0, twist_deg=0.5, dihedral_deg=0.0),
        WingStation(y_m=10.0, chord_m=0.8, twist_deg=-1.0, dihedral_deg=0.0),
    )
    shape = build_loaded_wing_shape(
        span_m=20.0,
        eta=(0.0, 0.5, 1.0),
        loaded_tip_dihedral_deg=4.0,
        loaded_shape_mode="linear_dihedral",
    )
    loaded_stations = apply_loaded_shape_to_stations(stations, shape)

    avl_path = write_concept_wing_only_avl(
        concept=concept,
        stations=loaded_stations,
        output_path=tmp_path / "loaded.avl",
    )

    section_lines = [
        line
        for line in avl_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("0.000000000")
    ]
    z_values = [float(line.split()[2]) for line in section_lines]
    assert z_values[0] == pytest.approx(0.0)
    assert z_values[-1] > 0.0
    assert z_values[-1] == pytest.approx(shape.loaded_tip_z_m)
