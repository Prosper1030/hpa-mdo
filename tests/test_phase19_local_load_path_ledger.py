from __future__ import annotations

from pathlib import Path

import pytest

from scripts.phase15_candidate_load_factor_buckling_check import CandidateReference
from scripts.phase19_local_load_path_ledger import (
    REQUIRED_LOCAL_LOAD_PATH_KEYS,
    build_local_load_path_ledger,
    wire_force_vector_n,
    write_local_load_path_ledger_package,
)


def _reference() -> CandidateReference:
    return CandidateReference(
        candidate_id="sample",
        reference_load_factor=2.0,
        failure_index=0.25 - 1.0,
        buckling_index=0.10 - 1.0,
        tip_deflection_m=1.0,
        tip_deflection_limit_m=1.65,
        twist_max_deg=0.2,
        twist_limit_deg=2.0,
        wire_tension_n=100.0,
        wire_allowable_n=250.0,
        root_reaction_fz_n=-80.0,
        root_bending_moment_n_m=1200.0,
        tube_allowable_stress_pa=1.0e9,
        young_pa=200.0e9,
        jig_main_tip_z_m=0.6,
        jig_rear_tip_z_m=0.4,
        loaded_main_tip_z_m=2.7,
        loaded_rear_tip_z_m=2.5,
        jig_min_z_m=0.04,
        loaded_min_z_m=0.08,
        fem_validated_max_load_factor=2.0,
        fem_tip_error_pct=3.74,
        fem_wire_reaction_error_pct=2.09,
        fem_root_reaction_error_pct=4.60,
        structured_shell_b2_error_pct=2.41,
        structured_shell_b5_torsion_error_pct=0.07,
    )


def _wire_rigging() -> list[dict[str, object]]:
    return [
        {
            "identifier": "wire-1",
            "attach_y_m": 2.0,
            "attach_point_loaded_m": [0.0, 3.0, 4.0],
            "anchor_point_m": [0.0, 0.0, 0.0],
            "tension_force_n": 100.0,
            "allowable_tension_n": 250.0,
        }
    ]


def _spar_rows() -> list[dict[str, str]]:
    return [
        {
            "Node": "1",
            "Y_Position_m": "0.0",
            "Main_FZ_N": "-10.0",
            "Rear_FZ_N": "-2.0",
            "Is_Joint": "0",
            "Is_Wire_Attach": "0",
        },
        {
            "Node": "2",
            "Y_Position_m": "1.0",
            "Main_FZ_N": "20.0",
            "Rear_FZ_N": "-4.0",
            "Is_Joint": "1",
            "Is_Wire_Attach": "0",
        },
        {
            "Node": "3",
            "Y_Position_m": "2.0",
            "Main_FZ_N": "30.0",
            "Rear_FZ_N": "-6.0",
            "Is_Joint": "0",
            "Is_Wire_Attach": "1",
        },
        {
            "Node": "4",
            "Y_Position_m": "3.0",
            "Main_FZ_N": "40.0",
            "Rear_FZ_N": "-8.0",
            "Is_Joint": "0",
            "Is_Wire_Attach": "0",
        },
    ]


def test_wire_force_vector_uses_loaded_attach_to_anchor_axis() -> None:
    fx, fy, fz = wire_force_vector_n(_wire_rigging()[0])

    assert fx == pytest.approx(0.0)
    assert fy == pytest.approx(-60.0)
    assert fz == pytest.approx(-80.0)


def test_local_load_path_ledger_lists_required_unclosed_detail_paths() -> None:
    ledger = build_local_load_path_ledger(
        _reference(),
        wire_rigging=_wire_rigging(),
        spar_rows=_spar_rows(),
    )

    assert [entry.key for entry in ledger.entries] == list(REQUIRED_LOCAL_LOAD_PATH_KEYS)
    by_key = {entry.key: entry for entry in ledger.entries}
    assert by_key["wire_attach_local_load_path"].status == "load_defined_detail_allowable_missing"
    assert by_key["root_joint"].primary_moment_n_m == pytest.approx(1200.0)
    assert by_key["wire_termination"].utilization == pytest.approx(0.4)
    assert by_key["rib_load_transfer"].max_effective_bay_m == pytest.approx(1.0)
    assert ledger.overall_status == "loads_defined_but_not_detail_signoff"


def test_write_local_load_path_ledger_package_creates_handoff_files(tmp_path: Path) -> None:
    outputs = write_local_load_path_ledger_package(
        tmp_path,
        _reference(),
        wire_rigging=_wire_rigging(),
        spar_rows=_spar_rows(),
    )

    assert {path.name for path in outputs} == {
        "local_load_path_ledger.csv",
        "local_load_path_ledger.json",
        "local_load_path_ledger.md",
    }
    report = (tmp_path / "local_load_path_ledger.md").read_text(encoding="utf-8")
    assert "root bending moment" in report
    assert "attach detail allowable is missing" in report
    assert "rib load-transfer stiffness is not proven" in report
