from __future__ import annotations

from pathlib import Path

from scripts.phase40_existing_fem_evidence_triage import (
    build_existing_fem_evidence_triage,
    read_candidate_static_summary_csv,
    read_hifi_structural_check_json,
    write_existing_fem_evidence_triage_package,
)


def test_existing_fem_triage_does_not_promote_equivalent_static_or_limited_buckle(
    tmp_path: Path,
) -> None:
    static_csv = tmp_path / "fem_load_factor_summary.csv"
    static_csv.write_text(
        "\n".join(
            [
                "load_factor,route,calculix_status,tip_error_pct,root_reaction_error_pct,wire_reaction_error_pct,total_support_error_pct,calculix_deck",
                "1.50,calculix_b32r_offset_rigid_springa_linearized_wire,ran,3.74,4.60,2.09,2.01,/tmp/lf_1p50.inp",
                "1.75,calculix_b32r_offset_rigid_springa_linearized_wire,ran,3.74,4.60,2.09,2.01,/tmp/lf_1p75.inp",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    hifi_json = tmp_path / "structural_check.json"
    hifi_json.write_text(
        """{
  "overall_comparability": "LIMITED",
  "buckle": {
    "comparability": "LIMITED",
    "message": "BUCKLE run completed, but no reference buckling index was available.",
    "artifact_path": "/tmp/spar_jig_shape_buckle.frd",
    "log_path": "/tmp/spar_jig_shape_buckle.log"
  },
  "mesh_diagnostics": {"analysis_reality": "shell_plus_beam"}
}
""",
        encoding="utf-8",
    )

    triage = build_existing_fem_evidence_triage(
        "sample",
        candidate_static_rows=read_candidate_static_summary_csv(static_csv),
        hifi_structural_checks=(read_hifi_structural_check_json(hifi_json, case_id="hifi-limited"),),
    )

    assert triage.overall_status == "existing_fem_evidence_does_not_close_goal"
    by_case = {row.case_id: row for row in triage.rows}
    assert by_case["candidate_equivalent_static_reference"].status == (
        "equivalent_static_reference_not_global_buckling"
    )
    assert by_case["candidate_equivalent_static_reference"].claim_load_factor_coverage == "1.50;1.75"
    assert by_case["hifi-limited"].status == "limited_hifi_buckle_not_phase30_closure"
    assert by_case["hifi-limited"].model_scope == "shell_plus_beam"
    assert all(not row.closes_full_wing_buckling_claim for row in triage.rows)
    assert all(not row.closes_local_detail_hardware for row in triage.rows)


def test_write_existing_fem_evidence_triage_package_creates_handoff_files(tmp_path: Path) -> None:
    outputs = write_existing_fem_evidence_triage_package(
        tmp_path,
        "sample",
        candidate_static_rows=(),
        hifi_structural_checks=(),
    )

    assert {path.name for path in outputs} == {
        "existing_fem_evidence_triage.csv",
        "existing_fem_evidence_triage.json",
        "existing_fem_evidence_triage.md",
    }
    report = (tmp_path / "existing_fem_evidence_triage.md").read_text(encoding="utf-8")
    assert "does not close" in report
    assert "full-wing global buckling" in report
