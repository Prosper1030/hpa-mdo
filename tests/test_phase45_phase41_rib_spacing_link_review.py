from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts.phase45_phase41_rib_spacing_link_review import (
    build_phase41_rib_spacing_link_review,
    write_phase41_rib_spacing_link_review_package,
)


def _model() -> SimpleNamespace:
    return SimpleNamespace(
        y_nodes_m=(0.0, 0.25, 0.50, 0.75, 1.0),
        joint_node_indices=(2,),
        dense_link_node_indices=(1, 3),
        wire_node_indices=(),
    )


def _phase41_evidence(link_node_count: int = 3) -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        rows=(
            SimpleNamespace(
                case_id="braced_subassembly_1p50g_buckle",
                claim_load_factor=1.5,
                link_node_count=link_node_count,
                includes_finite_ribs=True,
                phase30_closure_status="reference_load_review_missing",
            ),
        ),
    )


def _spacing_requirements(target_bay_m: float = 0.30) -> SimpleNamespace:
    return SimpleNamespace(
        target_bay_m=target_bay_m,
        max_recommended_subbay_m=0.25,
        recommended_station_count=5,
        total_added_bracing_stations=3,
        overall_status="layout_requirement_only_not_stiffness_signoff",
    )


def test_phase45_confirms_model_link_spacing_meets_nominal_but_not_signoff() -> None:
    review = build_phase41_rib_spacing_link_review(
        _phase41_evidence(),
        spacing_requirements=_spacing_requirements(),
        model=_model(),
    )

    assert review.overall_status == (
        "phase41_rib_spacing_model_matches_nominal_not_physical_signoff"
    )
    assert review.row_count == 1
    assert review.nominal_spacing_met_count == 1
    assert review.physical_signoff_count == 0
    row = review.rows[0]
    assert row.status == "phase41_link_spacing_matches_nominal_not_physical_signoff"
    assert row.model_link_node_count == 3
    assert row.phase41_link_node_count == 3
    assert row.model_bracing_station_count == 5
    assert row.recommended_station_count == 5
    assert row.model_link_count_matches_phase41 is True
    assert row.max_model_link_subbay_m == 0.25
    assert row.link_spacing_margin_m == 0.05
    assert "does not prove physical rib stiffness" in row.engineering_read


def test_phase45_flags_link_count_mismatch() -> None:
    review = build_phase41_rib_spacing_link_review(
        _phase41_evidence(link_node_count=2),
        spacing_requirements=_spacing_requirements(),
        model=_model(),
    )

    assert review.overall_status == "phase41_rib_spacing_model_review_required"
    assert review.rows[0].status == "phase41_link_count_mismatch_review_required"
    assert review.rows[0].model_link_count_matches_phase41 is False


def test_phase45_writes_handoff_files(tmp_path: Path) -> None:
    outputs = write_phase41_rib_spacing_link_review_package(
        tmp_path / "out",
        _phase41_evidence(),
        spacing_requirements=_spacing_requirements(),
        model=_model(),
    )

    assert {path.name for path in outputs} == {
        "phase41_rib_spacing_link_review.csv",
        "phase41_rib_spacing_link_review.json",
        "phase41_rib_spacing_link_review.md",
    }
    payload = json.loads(
        (tmp_path / "out" / "phase41_rib_spacing_link_review.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["overall_status"] == (
        "phase41_rib_spacing_model_matches_nominal_not_physical_signoff"
    )
    report = (tmp_path / "out" / "phase41_rib_spacing_link_review.md").read_text(
        encoding="utf-8"
    )
    assert "not physical rib stiffness or attachment signoff" in report
