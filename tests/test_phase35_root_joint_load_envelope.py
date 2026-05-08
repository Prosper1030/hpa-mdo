from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.phase35_root_joint_load_envelope import (
    build_root_joint_load_envelope,
    write_root_joint_load_envelope_package,
)


def _reference() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        root_reaction_fz_n=-20.0,
        root_bending_moment_n_m=1000.0,
    )


def test_root_joint_envelope_keeps_bending_moment_visible() -> None:
    envelope = build_root_joint_load_envelope(
        _reference(),
        detail_safety_factor=2.0,
        assumed_couple_arms_m=(0.1, 0.2),
    )

    assert envelope.overall_status == "root_joint_load_envelope_defined_not_signoff"
    assert envelope.design_root_force_n == pytest.approx(40.0)
    assert envelope.design_root_bending_moment_n_m == pytest.approx(2000.0)
    assert envelope.force_only_check_is_misleading is True
    by_key = {row.load_case_key: row for row in envelope.rows}
    assert by_key["root_vertical_reaction"].design_force_n == pytest.approx(40.0)
    assert by_key["root_bending_moment"].design_moment_n_m == pytest.approx(2000.0)
    assert by_key["moment_couple_arm_0p100m"].required_couple_force_n == pytest.approx(
        20000.0
    )
    assert by_key["moment_couple_arm_0p200m"].required_couple_force_n == pytest.approx(
        10000.0
    )
    assert "not root fitting signoff" in by_key["moment_couple_arm_0p100m"].engineering_note


def test_root_joint_envelope_rejects_invalid_assumptions() -> None:
    with pytest.raises(ValueError, match="detail_safety_factor"):
        build_root_joint_load_envelope(_reference(), detail_safety_factor=0.0)

    with pytest.raises(ValueError, match="assumed_couple_arms_m"):
        build_root_joint_load_envelope(_reference(), assumed_couple_arms_m=(0.1, 0.0))


def test_write_root_joint_envelope_package_creates_reports(tmp_path: Path) -> None:
    outputs = write_root_joint_load_envelope_package(tmp_path, _reference())

    assert {path.name for path in outputs} == {
        "root_joint_load_envelope.csv",
        "root_joint_load_envelope.json",
        "root_joint_load_envelope.md",
    }
    report = (tmp_path / "root_joint_load_envelope.md").read_text(encoding="utf-8")
    assert "root_joint_load_envelope_defined_not_signoff" in report
    assert "moment_couple_arm_0p100m" in report
    assert "force-only root check is misleading" in report
