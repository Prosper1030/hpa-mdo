from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts.phase43_existing_detail_allowable_evidence_triage import (
    build_existing_detail_allowable_evidence_triage,
    write_existing_detail_allowable_evidence_triage_package,
)


def _local_detail_check() -> SimpleNamespace:
    return SimpleNamespace(
        rows=(
            SimpleNamespace(
                parent_key="wire_attach_local_load_path",
                status="subcomponent_allowable_missing",
                required_allowable_load_n=6048.0,
                required_allowable_moment_n_m=None,
                worst_margin=None,
            ),
            SimpleNamespace(
                parent_key="wire_attach_local_load_path",
                status="subcomponent_allowable_missing",
                required_allowable_load_n=6048.0,
                required_allowable_moment_n_m=None,
                worst_margin=None,
            ),
            SimpleNamespace(
                parent_key="root_joint",
                status="subcomponent_moment_allowable_missing",
                required_allowable_load_n=18.3,
                required_allowable_moment_n_m=10833.2,
                worst_margin=None,
            ),
            SimpleNamespace(
                parent_key="wire_termination",
                status="subcomponent_allowable_missing",
                required_allowable_load_n=6048.0,
                required_minimum_breaking_load_n=10080.0,
                worst_margin=None,
            ),
        )
    )


def _rib_bracing_check() -> SimpleNamespace:
    return SimpleNamespace(
        required_link_force_n=934.5,
        rows=(
            SimpleNamespace(status="rib_stiffness_or_allowable_missing"),
            SimpleNamespace(status="rib_allowable_missing"),
            SimpleNamespace(status="rib_station_coverage_missing"),
        ),
    )


def _termination_sensitivity() -> SimpleNamespace:
    return SimpleNamespace(
        rows=(
            SimpleNamespace(
                termination_efficiency=0.6,
                required_minimum_breaking_load_n=10080.0,
            ),
            SimpleNamespace(
                termination_efficiency=0.4,
                required_minimum_breaking_load_n=15120.0,
            ),
        )
    )


def test_phase43_reports_force_and_moment_margins_separately() -> None:
    triage = build_existing_detail_allowable_evidence_triage(
        "sample",
        material_catalog={},
        tube_catalog_rows=(),
        rib_catalog={"families": {}},
        local_detail_subcomponent_check=SimpleNamespace(
            rows=(
                SimpleNamespace(
                    parent_key="root_joint",
                    status="margin_negative",
                    load_margin_n=50.0,
                    moment_margin_n_m=-200.0,
                    mbl_margin_n=None,
                    effective_termination_load_margin_n=None,
                ),
            )
        ),
        rib_bracing_margin_check=_rib_bracing_check(),
        wire_termination_efficiency_sensitivity=_termination_sensitivity(),
    )

    root = {row.blocker_key: row for row in triage.rows}["root_joint"]

    assert root.worst_force_like_margin_n == 50.0
    assert root.worst_moment_margin_n_m == -200.0


def test_phase43_separates_material_catalogs_from_local_hardware_margins() -> None:
    triage = build_existing_detail_allowable_evidence_triage(
        "sample",
        material_catalog={
            "dyneema_sk75": {"tensile_strength": 3500.0e6},
            "piano_wire_swpb": {"tensile_strength": 2000.0e6},
            "titanium_6al4v": {"tensile_strength": 950.0e6},
        },
        tube_catalog_rows=({"product": "CCH070062"},),
        rib_catalog={"families": {"balsa_sheet_3mm": {}, "capped_balsa_box_4mm": {}}},
        local_detail_subcomponent_check=_local_detail_check(),
        rib_bracing_margin_check=_rib_bracing_check(),
        wire_termination_efficiency_sensitivity=_termination_sensitivity(),
    )

    assert triage.overall_status == "existing_detail_allowables_do_not_close_goal"
    assert triage.closing_evidence_count == 0
    by_key = {row.blocker_key: row for row in triage.rows}
    assert by_key["wire_attach_local_load_path"].status == (
        "local_subcomponent_allowables_missing"
    )
    assert by_key["wire_attach_local_load_path"].missing_allowable_rows == 2
    assert "attach ring/lug/bond/insert/tube-wall" in by_key[
        "wire_attach_local_load_path"
    ].missing_for_margin
    assert by_key["root_joint"].status == "local_subcomponent_allowables_missing"
    assert by_key["root_joint"].moment_allowable_gap_rows == 1
    assert "10833.2000 N*m" in by_key["root_joint"].demand_summary
    assert by_key["wire_termination"].status == (
        "material_body_strength_not_termination_allowable"
    )
    assert "dyneema_sk75;piano_wire_swpb" in by_key[
        "wire_termination"
    ].catalog_summary
    assert "eta 0.60 MBL=10080.0000 N" in by_key[
        "wire_termination"
    ].demand_summary
    assert by_key["rib_load_transfer"].status == "rib_catalog_proxy_not_margin"
    assert by_key["rib_spacing_assumption"].status == "rib_catalog_proxy_not_margin"
    assert by_key["rib_spacing_assumption"].station_coverage_gap_rows == 1
    assert all(not row.closes_engineering_margin for row in triage.rows)


def test_phase43_writes_handoff_files(tmp_path: Path) -> None:
    outputs = write_existing_detail_allowable_evidence_triage_package(
        tmp_path,
        "sample",
        material_catalog={"dyneema_sk75": {}, "piano_wire_swpb": {}},
        tube_catalog_rows=(),
        rib_catalog={"families": {"balsa_sheet_3mm": {}}},
        local_detail_subcomponent_check=_local_detail_check(),
        rib_bracing_margin_check=_rib_bracing_check(),
        wire_termination_efficiency_sensitivity=_termination_sensitivity(),
    )

    assert {path.name for path in outputs} == {
        "existing_detail_allowable_evidence_triage.csv",
        "existing_detail_allowable_evidence_triage.json",
        "existing_detail_allowable_evidence_triage.md",
    }
    payload = json.loads(
        (tmp_path / "existing_detail_allowable_evidence_triage.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["overall_status"] == "existing_detail_allowables_do_not_close_goal"
    report = (tmp_path / "existing_detail_allowable_evidence_triage.md").read_text(
        encoding="utf-8"
    )
    assert "cannot close local hardware margins" in report
