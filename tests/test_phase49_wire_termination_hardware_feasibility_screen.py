from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.phase49_wire_termination_hardware_feasibility_screen import (
    build_wire_termination_hardware_feasibility_screen,
    write_wire_termination_hardware_feasibility_screen_package,
)


def _sensitivity() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        overall_status="termination_efficiency_sensitivity_defined_not_signoff",
        required_allowable_load_n=6000.0,
        body_allowable_margin_n=-1000.0,
        rows=(
            SimpleNamespace(
                termination_efficiency=0.6,
                required_minimum_breaking_load_n=10000.0,
            ),
            SimpleNamespace(
                termination_efficiency=0.8,
                required_minimum_breaking_load_n=7500.0,
            ),
        ),
    )


def test_wire_termination_hardware_screen_requires_selected_hardware() -> None:
    screen = build_wire_termination_hardware_feasibility_screen(
        _sensitivity(),
        termination_hardware=(),
    )

    assert screen.overall_status == "wire_termination_hardware_feasibility_not_closed"
    assert screen.required_allowable_load_n == pytest.approx(6000.0)
    assert screen.required_mbl_at_eta_0p60_n == pytest.approx(10000.0)
    assert screen.hardware_count == 1
    assert screen.missing_input_hardware_count == 1
    row = screen.rows[0]
    assert row.hardware_id == "wire_termination_hardware_input_required"
    assert row.status == "hardware_selection_and_allowables_missing"
    assert not row.closes_wire_termination_margin
    assert "selected termination hardware" in row.engineering_note


def test_wire_termination_hardware_screen_checks_effective_and_local_allowables() -> None:
    screen = build_wire_termination_hardware_feasibility_screen(
        _sensitivity(),
        termination_hardware=(
            {
                "hardware_id": "swage-a",
                "minimum_breaking_load_n": "13000",
                "termination_efficiency": "0.60",
                "derate_factor": "0.90",
                "end_anchor_or_pin_allowable_load_n": "7200",
                "fixture_allowable_load_n": "7600",
                "bend_creep_abrasion_allowable_load_n": "7000",
                "evidence_type": "vendor_datasheet",
                "source": "vendor sheet",
            },
        ),
    )

    assert screen.overall_status == "wire_termination_hardware_inputs_pass_not_fem_signoff"
    assert screen.positive_input_hardware_count == 1
    row = screen.rows[0]
    assert row.status == "hardware_positive_input_check_only"
    assert row.effective_termination_load_n == pytest.approx(7020.0)
    assert row.effective_termination_margin_n == pytest.approx(1020.0)
    assert row.minimum_breaking_load_margin_n == pytest.approx(3000.0)
    assert row.end_anchor_or_pin_margin_n == pytest.approx(1200.0)
    assert row.fixture_margin_n == pytest.approx(1600.0)
    assert row.bend_creep_abrasion_margin_n == pytest.approx(1000.0)
    assert row.worst_margin_n == pytest.approx(1000.0)
    assert not row.closes_wire_termination_margin
    assert "not wire termination signoff" in row.engineering_note


def test_wire_termination_hardware_screen_flags_negative_and_traceability_gaps() -> None:
    screen = build_wire_termination_hardware_feasibility_screen(
        _sensitivity(),
        termination_hardware=(
            {
                "hardware_id": "weak-swage",
                "minimum_breaking_load_n": "9000",
                "termination_efficiency": "0.60",
                "derate_factor": "0.90",
                "end_anchor_or_pin_allowable_load_n": "6200",
                "fixture_allowable_load_n": "5800",
                "bend_creep_abrasion_allowable_load_n": "6100",
                "evidence_type": "vendor_datasheet",
                "source": "vendor sheet",
            },
            {
                "hardware_id": "no-source",
                "minimum_breaking_load_n": "13000",
                "termination_efficiency": "0.60",
                "derate_factor": "0.90",
                "end_anchor_or_pin_allowable_load_n": "7200",
                "fixture_allowable_load_n": "7600",
                "bend_creep_abrasion_allowable_load_n": "7000",
                "evidence_type": "vendor_datasheet",
                "source": "",
            },
        ),
    )

    by_id = {row.hardware_id: row for row in screen.rows}
    assert screen.overall_status == "wire_termination_hardware_feasibility_not_closed"
    assert screen.negative_margin_hardware_count == 1
    assert by_id["weak-swage"].status == "margin_negative"
    assert by_id["weak-swage"].fixture_margin_n == pytest.approx(-200.0)
    assert by_id["no-source"].status == "hardware_traceability_missing"
    assert by_id["no-source"].traceability_status == "source_missing"


def test_wire_termination_hardware_screen_requires_explicit_derate() -> None:
    screen = build_wire_termination_hardware_feasibility_screen(
        _sensitivity(),
        termination_hardware=(
            {
                "hardware_id": "swage-missing-derate",
                "minimum_breaking_load_n": "13000",
                "termination_efficiency": "0.60",
                "end_anchor_or_pin_allowable_load_n": "7200",
                "fixture_allowable_load_n": "7600",
                "bend_creep_abrasion_allowable_load_n": "7000",
                "evidence_type": "vendor_datasheet",
                "source": "vendor sheet",
            },
        ),
    )

    row = screen.rows[0]
    assert screen.overall_status == "wire_termination_hardware_feasibility_not_closed"
    assert row.status == "hardware_allowables_missing"
    assert row.derate_factor is None
    assert row.effective_termination_load_n is None
    assert row.effective_termination_margin_n is None


def test_wire_termination_hardware_screen_rejects_invalid_efficiency() -> None:
    with pytest.raises(ValueError, match="termination_efficiency"):
        build_wire_termination_hardware_feasibility_screen(
            _sensitivity(),
            termination_hardware=(
                {
                    "hardware_id": "bad-eff",
                    "minimum_breaking_load_n": "13000",
                    "termination_efficiency": "0.0",
                },
            ),
        )


def test_write_wire_termination_hardware_feasibility_screen_package_creates_reports(
    tmp_path: Path,
) -> None:
    outputs = write_wire_termination_hardware_feasibility_screen_package(
        tmp_path,
        _sensitivity(),
        termination_hardware=(),
    )

    assert {path.name for path in outputs} == {
        "wire_termination_hardware_inputs_template.csv",
        "wire_termination_hardware_feasibility_screen.csv",
        "wire_termination_hardware_feasibility_screen.json",
        "wire_termination_hardware_feasibility_screen.md",
    }
    report = (tmp_path / "wire_termination_hardware_feasibility_screen.md").read_text(
        encoding="utf-8"
    )
    assert "Wire Termination Hardware Feasibility Screen" in report
    assert "wire_termination_hardware_feasibility_not_closed" in report
    assert "not wire termination signoff" in report
