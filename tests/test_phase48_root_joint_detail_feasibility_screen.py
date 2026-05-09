from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.phase48_root_joint_detail_feasibility_screen import (
    build_root_joint_detail_feasibility_screen,
    write_root_joint_detail_feasibility_screen_package,
)


def _root_envelope() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        overall_status="root_joint_load_envelope_defined_not_signoff",
        design_root_bending_moment_n_m=10000.0,
        rows=(
            SimpleNamespace(
                load_case_key="moment_couple_arm_0p100m",
                required_couple_force_n=100000.0,
            ),
            SimpleNamespace(
                load_case_key="moment_couple_arm_0p050m",
                required_couple_force_n=200000.0,
            ),
        ),
    )


def test_root_joint_detail_screen_requires_geometry_and_allowables() -> None:
    screen = build_root_joint_detail_feasibility_screen(
        _root_envelope(),
        root_joint_concepts=(),
    )

    assert screen.overall_status == "root_joint_detail_feasibility_not_closed"
    assert screen.design_root_bending_moment_n_m == pytest.approx(10000.0)
    assert screen.envelope_worst_couple_force_n == pytest.approx(200000.0)
    assert screen.envelope_worst_couple_case == "moment_couple_arm_0p050m"
    assert screen.concept_count == 1
    assert screen.missing_input_concept_count == 1
    row = screen.rows[0]
    assert row.concept_id == "root_joint_concept_input_required"
    assert row.status == "concept_geometry_and_allowables_missing"
    assert row.required_couple_force_n == pytest.approx(200000.0)
    assert not row.closes_root_joint_margin
    assert "actual root fitting geometry" in row.engineering_note


def test_root_joint_detail_screen_checks_each_local_load_path_leg() -> None:
    screen = build_root_joint_detail_feasibility_screen(
        _root_envelope(),
        root_joint_concepts=(
            {
                "concept_id": "root-clamp-a",
                "effective_couple_arm_m": "0.05",
                "fitting_or_clamp_allowable_force_n": "250000",
                "bonded_joint_allowable_force_n": "230000",
                "insert_allowable_force_n": "240000",
                "tube_wall_bearing_allowable_force_n": "220000",
                "evidence_type": "hand_calc",
                "source": "concept sizing sheet",
            },
        ),
    )

    assert screen.overall_status == "root_joint_concept_inputs_pass_not_fem_signoff"
    assert screen.positive_input_concept_count == 1
    assert screen.negative_margin_concept_count == 0
    row = screen.rows[0]
    assert row.status == "concept_positive_input_check_only"
    assert row.required_couple_force_n == pytest.approx(200000.0)
    assert row.fitting_or_clamp_margin_n == pytest.approx(50000.0)
    assert row.bonded_joint_margin_n == pytest.approx(30000.0)
    assert row.insert_margin_n == pytest.approx(40000.0)
    assert row.tube_wall_bearing_margin_n == pytest.approx(20000.0)
    assert row.worst_margin_n == pytest.approx(20000.0)
    assert not row.closes_root_joint_margin
    assert "not root-joint FEM signoff" in row.engineering_note


def test_root_joint_detail_screen_flags_negative_and_untraceable_concepts() -> None:
    screen = build_root_joint_detail_feasibility_screen(
        _root_envelope(),
        root_joint_concepts=(
            {
                "concept_id": "root-clamp-weak",
                "effective_couple_arm_m": "0.10",
                "fitting_or_clamp_allowable_force_n": "120000",
                "bonded_joint_allowable_force_n": "90000",
                "insert_allowable_force_n": "130000",
                "tube_wall_bearing_allowable_force_n": "140000",
                "evidence_type": "hand_calc",
                "source": "concept sizing sheet",
            },
            {
                "concept_id": "root-clamp-no-source",
                "effective_couple_arm_m": "0.05",
                "fitting_or_clamp_allowable_force_n": "250000",
                "bonded_joint_allowable_force_n": "230000",
                "insert_allowable_force_n": "240000",
                "tube_wall_bearing_allowable_force_n": "220000",
                "evidence_type": "hand_calc",
                "source": "",
            },
        ),
    )

    by_id = {row.concept_id: row for row in screen.rows}
    assert screen.overall_status == "root_joint_detail_feasibility_not_closed"
    assert screen.negative_margin_concept_count == 1
    assert by_id["root-clamp-weak"].status == "margin_negative"
    assert by_id["root-clamp-weak"].bonded_joint_margin_n == pytest.approx(-10000.0)
    assert by_id["root-clamp-no-source"].status == "concept_traceability_missing"
    assert by_id["root-clamp-no-source"].traceability_status == "source_missing"


def test_root_joint_detail_screen_rejects_invalid_couple_arm() -> None:
    with pytest.raises(ValueError, match="effective_couple_arm_m"):
        build_root_joint_detail_feasibility_screen(
            _root_envelope(),
            root_joint_concepts=(
                {
                    "concept_id": "bad-arm",
                    "effective_couple_arm_m": "0",
                },
            ),
        )


def test_write_root_joint_detail_feasibility_screen_package_creates_reports(
    tmp_path: Path,
) -> None:
    outputs = write_root_joint_detail_feasibility_screen_package(
        tmp_path,
        _root_envelope(),
        root_joint_concepts=(),
    )

    assert {path.name for path in outputs} == {
        "root_joint_detail_feasibility_screen.csv",
        "root_joint_detail_feasibility_screen.json",
        "root_joint_detail_feasibility_screen.md",
        "root_joint_detail_concept_inputs_template.csv",
    }
    report = (tmp_path / "root_joint_detail_feasibility_screen.md").read_text(
        encoding="utf-8"
    )
    assert "Root Joint Detail Feasibility Screen" in report
    assert "root_joint_detail_feasibility_not_closed" in report
    assert "not root-joint FEM signoff" in report
