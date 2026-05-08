from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.phase23_detail_sizing_requirements import (
    build_detail_sizing_requirements,
    write_detail_sizing_requirements_package,
)


def _ledger() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        entries=(
            SimpleNamespace(
                key="wire_attach_local_load_path",
                title="Wire attach local load path",
                primary_load_n=3000.0,
                primary_moment_n_m=None,
                utilization=None,
                evidence="attach load vector known",
            ),
            SimpleNamespace(
                key="root_joint",
                title="Root joint",
                primary_load_n=10.0,
                primary_moment_n_m=5000.0,
                utilization=None,
                evidence="root loads known",
            ),
            SimpleNamespace(
                key="wire_termination",
                title="Wire termination",
                primary_load_n=3000.0,
                primary_moment_n_m=None,
                utilization=0.60,
                evidence="wire body utilization known",
            ),
        ),
    )


def test_detail_sizing_requirements_convert_service_loads_to_required_ratings() -> None:
    requirements = build_detail_sizing_requirements(
        _ledger(),
        detail_safety_factor=2.0,
        termination_efficiency=0.60,
    )

    assert requirements.overall_status == "requirements_only_not_margin_signoff"
    by_key = {row.key: row for row in requirements.rows}
    assert by_key["wire_attach_local_load_path"].required_allowable_load_n == pytest.approx(6000.0)
    assert by_key["root_joint"].required_allowable_moment_n_m == pytest.approx(10000.0)
    assert by_key["wire_termination"].required_minimum_breaking_load_n == pytest.approx(10000.0)
    assert by_key["wire_termination"].body_allowable_n == pytest.approx(5000.0)
    assert by_key["wire_termination"].body_allowable_margin_n == pytest.approx(-1000.0)
    assert by_key["wire_termination"].body_allowable_meets_required_load is False
    assert all(row.status == "requirement_defined_hardware_margin_missing" for row in requirements.rows)


def test_detail_sizing_requirements_reject_invalid_efficiency() -> None:
    with pytest.raises(ValueError, match="termination_efficiency"):
        build_detail_sizing_requirements(_ledger(), termination_efficiency=0.0)


def test_write_detail_sizing_requirements_package_creates_handoff_files(tmp_path: Path) -> None:
    outputs = write_detail_sizing_requirements_package(
        tmp_path,
        _ledger(),
        detail_safety_factor=2.0,
        termination_efficiency=0.60,
    )

    assert {path.name for path in outputs} == {
        "detail_sizing_requirements.csv",
        "detail_sizing_requirements.json",
        "detail_sizing_requirements.md",
    }
    report = (tmp_path / "detail_sizing_requirements.md").read_text(encoding="utf-8")
    assert "requirements only" in report
    assert "wire termination required MBL" in report
    assert "not a hardware margin signoff" in report
