from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.phase50_wire_attach_detail_feasibility_screen import (
    build_wire_attach_detail_feasibility_screen,
    write_wire_attach_detail_feasibility_screen_package,
)


def _decomposition(*, local_moment: float | None = 200.0) -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        overall_status=(
            "wire_attach_force_and_local_moment_defined_not_signoff"
            if local_moment is not None
            else "wire_attach_force_components_only_local_moment_missing"
        ),
        max_resultant_design_load_n=6000.0,
        max_resultant_design_local_moment_n_m=local_moment,
        rows=(
            SimpleNamespace(component_key="resultant_xyz", design_load_n=6000.0),
            SimpleNamespace(component_key="spanwise_y", design_load_n=5800.0),
            SimpleNamespace(component_key="vertical_z", design_load_n=1500.0),
            SimpleNamespace(component_key="transverse_xz", design_load_n=1800.0),
        ),
    )


def test_wire_attach_detail_screen_requires_geometry_and_allowables() -> None:
    screen = build_wire_attach_detail_feasibility_screen(
        _decomposition(local_moment=None),
        attach_detail_concepts=(),
    )

    assert screen.overall_status == "wire_attach_detail_feasibility_not_closed"
    assert screen.required_resultant_load_n == pytest.approx(6000.0)
    assert screen.required_local_moment_n_m is None
    assert screen.local_moment_status == "attach_eccentricity_missing"
    assert screen.concept_count == 1
    assert screen.missing_input_concept_count == 1
    row = screen.rows[0]
    assert row.concept_id == "wire_attach_detail_concept_input_required"
    assert row.status == "detail_geometry_and_allowables_missing"
    assert not row.closes_wire_attach_margin
    assert "attach eccentricity" in row.engineering_note


def test_wire_attach_detail_screen_checks_force_and_local_moment_paths() -> None:
    screen = build_wire_attach_detail_feasibility_screen(
        _decomposition(local_moment=200.0),
        attach_detail_concepts=(
            {
                "concept_id": "attach-a",
                "attach_ring_or_lug_allowable_load_n": "7200",
                "bonded_load_path_allowable_load_n": "7000",
                "insert_pullout_bearing_allowable_load_n": "6800",
                "local_tube_wall_crushing_allowable_load_n": "2400",
                "local_moment_allowable_n_m": "260",
                "evidence_type": "hand_calc",
                "source": "concept sizing sheet",
            },
        ),
    )

    assert screen.overall_status == "wire_attach_detail_inputs_pass_not_fem_signoff"
    assert screen.positive_input_concept_count == 1
    row = screen.rows[0]
    assert row.status == "detail_positive_input_check_only"
    assert row.attach_ring_or_lug_margin_n == pytest.approx(1200.0)
    assert row.bonded_load_path_margin_n == pytest.approx(1000.0)
    assert row.insert_pullout_bearing_margin_n == pytest.approx(1000.0)
    assert row.local_tube_wall_crushing_margin_n == pytest.approx(600.0)
    assert row.local_moment_margin_n_m == pytest.approx(60.0)
    assert row.worst_margin_n_equivalent == pytest.approx(600.0)
    assert not row.closes_wire_attach_margin
    assert "not wire-attach local FEM signoff" in row.engineering_note


def test_wire_attach_detail_screen_requires_local_moment_when_eccentricity_missing() -> None:
    screen = build_wire_attach_detail_feasibility_screen(
        _decomposition(local_moment=None),
        attach_detail_concepts=(
            {
                "concept_id": "force-only-attach",
                "attach_ring_or_lug_allowable_load_n": "7200",
                "bonded_load_path_allowable_load_n": "7000",
                "insert_pullout_bearing_allowable_load_n": "6800",
                "local_tube_wall_crushing_allowable_load_n": "2400",
                "evidence_type": "hand_calc",
                "source": "concept sizing sheet",
            },
        ),
    )

    row = screen.rows[0]
    assert screen.overall_status == "wire_attach_detail_feasibility_not_closed"
    assert row.status == "attach_eccentricity_missing"
    assert row.local_moment_margin_n_m is None


def test_wire_attach_detail_screen_flags_negative_and_traceability_gaps() -> None:
    screen = build_wire_attach_detail_feasibility_screen(
        _decomposition(local_moment=200.0),
        attach_detail_concepts=(
            {
                "concept_id": "weak-attach",
                "attach_ring_or_lug_allowable_load_n": "6200",
                "bonded_load_path_allowable_load_n": "5900",
                "insert_pullout_bearing_allowable_load_n": "6100",
                "local_tube_wall_crushing_allowable_load_n": "1700",
                "local_moment_allowable_n_m": "190",
                "evidence_type": "hand_calc",
                "source": "concept sizing sheet",
            },
            {
                "concept_id": "no-source",
                "attach_ring_or_lug_allowable_load_n": "7200",
                "bonded_load_path_allowable_load_n": "7000",
                "insert_pullout_bearing_allowable_load_n": "6800",
                "local_tube_wall_crushing_allowable_load_n": "2400",
                "local_moment_allowable_n_m": "260",
                "evidence_type": "hand_calc",
                "source": "",
            },
        ),
    )

    by_id = {row.concept_id: row for row in screen.rows}
    assert screen.overall_status == "wire_attach_detail_feasibility_not_closed"
    assert screen.negative_margin_concept_count == 1
    assert by_id["weak-attach"].status == "margin_negative"
    assert by_id["weak-attach"].local_tube_wall_crushing_margin_n == pytest.approx(-100.0)
    assert by_id["no-source"].status == "detail_traceability_missing"
    assert by_id["no-source"].traceability_status == "source_missing"


def test_write_wire_attach_detail_feasibility_screen_package_creates_reports(
    tmp_path: Path,
) -> None:
    outputs = write_wire_attach_detail_feasibility_screen_package(
        tmp_path,
        _decomposition(local_moment=None),
        attach_detail_concepts=(),
    )

    assert {path.name for path in outputs} == {
        "wire_attach_detail_inputs_template.csv",
        "wire_attach_detail_feasibility_screen.csv",
        "wire_attach_detail_feasibility_screen.json",
        "wire_attach_detail_feasibility_screen.md",
    }
    report = (tmp_path / "wire_attach_detail_feasibility_screen.md").read_text(
        encoding="utf-8"
    )
    assert "Wire Attach Detail Feasibility Screen" in report
    assert "wire_attach_detail_feasibility_not_closed" in report
    assert "not wire-attach local FEM signoff" in report
