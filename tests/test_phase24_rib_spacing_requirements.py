from __future__ import annotations

from pathlib import Path

import pytest

from scripts.phase24_rib_spacing_requirements import (
    build_rib_spacing_requirements,
    write_rib_spacing_requirements_package,
)


def _spar_rows() -> list[dict[str, str]]:
    return [
        {
            "Y_Position_m": "0.00",
            "Is_Joint": "0",
            "Is_Wire_Attach": "0",
            "Main_FZ_N": "-2.0",
            "Rear_FZ_N": "-1.0",
        },
        {
            "Y_Position_m": "0.50",
            "Is_Joint": "1",
            "Is_Wire_Attach": "0",
            "Main_FZ_N": "-6.0",
            "Rear_FZ_N": "-2.0",
        },
        {
            "Y_Position_m": "0.90",
            "Is_Joint": "0",
            "Is_Wire_Attach": "1",
            "Main_FZ_N": "-8.0",
            "Rear_FZ_N": "-4.0",
        },
        {
            "Y_Position_m": "1.25",
            "Is_Joint": "0",
            "Is_Wire_Attach": "0",
            "Main_FZ_N": "-4.0",
            "Rear_FZ_N": "-1.0",
        },
    ]


def _wire_rigging() -> list[dict[str, object]]:
    return [{"attach_y_m": 0.90}]


def test_rib_spacing_requirements_split_mandatory_bays_to_nominal_spacing() -> None:
    requirements = build_rib_spacing_requirements(
        "sample",
        spar_rows=_spar_rows(),
        wire_rigging=_wire_rigging(),
        target_bay_m=0.30,
    )

    assert requirements.overall_status == "layout_requirement_only_not_stiffness_signoff"
    assert requirements.current_max_bay_m == pytest.approx(0.50)
    assert requirements.total_added_bracing_stations == 3
    assert requirements.recommended_station_count == 7
    assert requirements.max_recommended_subbay_m <= 0.30
    assert [row.required_intermediate_stations for row in requirements.rows] == [1, 1, 1]
    assert requirements.rows[0].recommended_intermediate_y_m == pytest.approx((0.25,))
    assert requirements.rows[1].bay_vertical_load_scale_n == pytest.approx(12.0)
    assert all(row.status == "requires_added_physical_bracing" for row in requirements.rows)


def test_rib_spacing_requirements_reject_invalid_target_spacing() -> None:
    with pytest.raises(ValueError, match="target_bay_m"):
        build_rib_spacing_requirements("sample", spar_rows=_spar_rows(), target_bay_m=0.0)


def test_write_rib_spacing_requirements_package_creates_handoff_files(tmp_path: Path) -> None:
    outputs = write_rib_spacing_requirements_package(
        tmp_path,
        "sample",
        spar_rows=_spar_rows(),
        wire_rigging=_wire_rigging(),
        target_bay_m=0.30,
    )

    assert {path.name for path in outputs} == {
        "rib_spacing_requirements.csv",
        "rib_spacing_requirements.json",
        "rib_spacing_requirements.md",
    }
    report = (tmp_path / "rib_spacing_requirements.md").read_text(encoding="utf-8")
    assert "layout requirement only" in report
    assert "not a rib stiffness signoff" in report
    assert "0.300 m target bay" in report
