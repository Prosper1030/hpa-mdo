from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.phase36_wire_termination_efficiency_sensitivity import (
    build_wire_termination_efficiency_sensitivity,
    write_wire_termination_efficiency_sensitivity_package,
)


def _requirements() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        rows=(
            SimpleNamespace(
                key="wire_termination",
                title="Wire termination",
                service_load_n=3000.0,
                required_allowable_load_n=6000.0,
                body_allowable_n=5000.0,
                body_allowable_margin_n=-1000.0,
                required_minimum_breaking_load_n=10000.0,
            ),
        ),
    )


def test_wire_termination_efficiency_sensitivity_back_calculates_required_mbl() -> None:
    sensitivity = build_wire_termination_efficiency_sensitivity(
        _requirements(),
        termination_efficiencies=(0.5, 0.6, 0.8),
    )

    assert sensitivity.overall_status == "termination_efficiency_sensitivity_defined_not_signoff"
    assert sensitivity.body_allowable_margin_n == pytest.approx(-1000.0)
    by_eff = {row.termination_efficiency: row for row in sensitivity.rows}
    assert by_eff[0.5].required_minimum_breaking_load_n == pytest.approx(12000.0)
    assert by_eff[0.6].required_minimum_breaking_load_n == pytest.approx(10000.0)
    assert by_eff[0.8].required_minimum_breaking_load_n == pytest.approx(7500.0)
    assert all(row.status == "termination_mbl_requirement_only" for row in sensitivity.rows)
    assert "not termination signoff" in by_eff[0.6].engineering_note


def test_wire_termination_efficiency_sensitivity_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="termination_efficiencies"):
        build_wire_termination_efficiency_sensitivity(
            _requirements(),
            termination_efficiencies=(0.6, 0.0),
        )

    with pytest.raises(ValueError, match="wire_termination"):
        build_wire_termination_efficiency_sensitivity(
            SimpleNamespace(candidate_id="sample", rows=()),
        )


def test_write_wire_termination_efficiency_sensitivity_package_creates_reports(
    tmp_path: Path,
) -> None:
    outputs = write_wire_termination_efficiency_sensitivity_package(
        tmp_path,
        _requirements(),
    )

    assert {path.name for path in outputs} == {
        "wire_termination_efficiency_sensitivity.csv",
        "wire_termination_efficiency_sensitivity.json",
        "wire_termination_efficiency_sensitivity.md",
    }
    report = (tmp_path / "wire_termination_efficiency_sensitivity.md").read_text(
        encoding="utf-8"
    )
    assert "termination_efficiency_sensitivity_defined_not_signoff" in report
    assert "0.60" in report
    assert "not termination signoff" in report
