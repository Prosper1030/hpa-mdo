from __future__ import annotations

from pathlib import Path

import pytest

from scripts.phase34_wire_attach_load_decomposition import (
    build_wire_attach_load_decomposition,
    write_wire_attach_load_decomposition_package,
)


def _wire_rigging() -> list[dict[str, object]]:
    return [
        {
            "identifier": "wire-a",
            "attach_point_loaded_m": [0.0, 0.0, 0.0],
            "anchor_point_m": [0.0, -3.0, -4.0],
            "tension_force_n": 10.0,
        }
    ]


def test_wire_attach_decomposition_turns_vector_into_component_design_loads() -> None:
    decomposition = build_wire_attach_load_decomposition(
        "sample",
        wire_rigging=_wire_rigging(),
        detail_safety_factor=2.0,
    )

    assert decomposition.overall_status == "wire_attach_load_components_defined_not_signoff"
    assert decomposition.max_resultant_service_load_n == pytest.approx(10.0)
    assert decomposition.max_resultant_design_load_n == pytest.approx(20.0)
    by_component = {row.component_key: row for row in decomposition.rows}
    assert by_component["resultant_xyz"].service_load_n == pytest.approx(10.0)
    assert by_component["spanwise_y"].service_load_n == pytest.approx(6.0)
    assert by_component["vertical_z"].design_load_n == pytest.approx(16.0)
    assert by_component["transverse_xz"].service_load_n == pytest.approx(8.0)
    assert by_component["transverse_xz"].applicable_subcomponents == (
        "attach_ring_or_lug;insert_pullout_bearing;local_tube_wall_crushing;bonded_load_path"
    )
    assert "not local FEM signoff" in by_component["spanwise_y"].engineering_note


def test_wire_attach_decomposition_rejects_empty_or_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="At least one wire rigging row"):
        build_wire_attach_load_decomposition("sample", wire_rigging=())

    with pytest.raises(ValueError, match="detail_safety_factor"):
        build_wire_attach_load_decomposition(
            "sample",
            wire_rigging=_wire_rigging(),
            detail_safety_factor=0.0,
        )


def test_write_wire_attach_decomposition_package_creates_reports(tmp_path: Path) -> None:
    outputs = write_wire_attach_load_decomposition_package(
        tmp_path,
        "sample",
        wire_rigging=_wire_rigging(),
    )

    assert {path.name for path in outputs} == {
        "wire_attach_load_decomposition.csv",
        "wire_attach_load_decomposition.json",
        "wire_attach_load_decomposition.md",
    }
    report = (tmp_path / "wire_attach_load_decomposition.md").read_text(encoding="utf-8")
    assert "wire_attach_load_components_defined_not_signoff" in report
    assert "transverse_xz" in report
    assert "not local FEM signoff" in report
