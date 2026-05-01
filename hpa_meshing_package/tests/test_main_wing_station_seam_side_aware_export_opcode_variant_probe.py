import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_side_aware_export_opcode_variant_probe import (
    build_main_wing_station_seam_side_aware_export_opcode_variant_probe_report,
    write_main_wing_station_seam_side_aware_export_opcode_variant_probe_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_audit(path: Path, source_csm: Path) -> Path:
    source_csm.parent.mkdir(parents=True, exist_ok=True)
    source_csm.write_text(
        "\n".join(
            [
                "skbeg 1 -1 0",
                "   linseg 0.5 -1 0.1",
                "   spline 0 -1 0",
                "   spline 0.5 -1 -0.1",
                "   linseg 1 -1 0",
                "skend",
                "skbeg 1 0 0",
                "   linseg 0.5 0 0.1",
                "   spline 0 0 0",
                "   spline 0.5 0 -0.1",
                "   linseg 1 0 0",
                "skend",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return _write_json(
        path,
        {
            "schema_version": "main_wing_station_seam_profile_parametrization_audit.v1",
            "source_csm_path": str(source_csm),
            "target_station_y_m": [-1.0, 0.0],
        },
    )


def _materializer(**kwargs):
    variant = kwargs["variant"]
    out_dir = kwargs["out_dir"]
    step_path = out_dir / "candidate_raw_dump.stp"
    csm_path = out_dir / "candidate.csm"
    return {
        "status": "materialized",
        "csm_path": str(csm_path),
        "step_path": str(step_path),
        "topology": {
            "body_count": 1,
            "volume_count": 1,
            "surface_count": 582 if variant == "all_linseg" else 52,
            "bbox": [0.0, -1.0, -0.1, 1.0, 0.0, 0.1],
        },
        "materialization_skipped_for_test_override": True,
    }


def _validator(**kwargs):
    assert kwargs["candidate_step_path"].name == "candidate_raw_dump.stp"
    return {
        "probe_status": "side_aware_candidate_station_brep_edges_suspect",
        "hotspot_summary": {
            "station_edge_check_count": 10,
            "face_check_count": 20,
            "shape_valid_exact": True,
        },
        "blocking_reasons": [
            "side_aware_candidate_station_brep_pcurve_checks_suspect",
            "side_aware_candidate_mesh_handoff_not_run",
        ],
        "engineering_findings": [
            "side_aware_station_edge_pcurve_consistency_checks_are_suspect"
        ],
    }


def _recovered_validator(**_kwargs):
    return {
        "probe_status": "side_aware_candidate_station_brep_edges_valid",
        "hotspot_summary": {
            "station_edge_check_count": 6,
            "face_check_count": 12,
            "shape_valid_exact": True,
        },
        "blocking_reasons": ["side_aware_candidate_mesh_handoff_not_run"],
        "engineering_findings": [
            "side_aware_station_edges_are_valid_and_pcurve_consistent"
        ],
    }


def test_opcode_variant_probe_records_split_negative_control_and_surface_guard(
    tmp_path: Path,
):
    audit_path = _write_audit(tmp_path / "audit.json", tmp_path / "source.csm")

    report = build_main_wing_station_seam_side_aware_export_opcode_variant_probe_report(
        profile_parametrization_audit_path=audit_path,
        materialize_variants=True,
        materialization_root=tmp_path / "variants",
        variant_materializer=_materializer,
        variant_validator=_validator,
    )

    assert (
        report.opcode_variant_status
        == "side_aware_export_opcode_variant_not_recovered"
    )
    assert report.production_default_changed is False
    assert report.variant_summary["variant_count"] == 2
    assert report.variant_summary["validated_variant_count"] == 1
    assert report.variant_summary["surface_count_guard_skipped_count"] == 1
    assert report.variant_summary["best_station_edge_check_count"] == 10
    assert "upper_lower_spline_split_still_pcurve_suspect" in (
        report.engineering_findings
    )
    assert "all_linseg_surface_count_explosion_observed" in (
        report.engineering_findings
    )
    assert "side_aware_export_opcode_variants_not_recovered" in (
        report.blocking_reasons
    )
    assert report.next_actions[0] == (
        "inspect_export_pcurve_metadata_generation_instead_of_simple_opcode_variants"
    )


def test_opcode_variant_probe_reports_recovered_if_variant_brep_gate_passes(
    tmp_path: Path,
):
    audit_path = _write_audit(tmp_path / "audit.json", tmp_path / "source.csm")

    report = build_main_wing_station_seam_side_aware_export_opcode_variant_probe_report(
        profile_parametrization_audit_path=audit_path,
        variants=["upper_lower_spline_split"],
        materialize_variants=True,
        materialization_root=tmp_path / "variants",
        variant_materializer=_materializer,
        variant_validator=_recovered_validator,
    )

    assert (
        report.opcode_variant_status
        == "side_aware_export_opcode_variant_recovered"
    )
    assert report.variant_summary["recovered_variant_count"] == 1
    assert "rerun_projected_pcurve_builder_on_recovered_opcode_variant" in (
        report.next_actions
    )


def test_write_opcode_variant_probe_report(tmp_path: Path):
    audit_path = _write_audit(tmp_path / "audit.json", tmp_path / "source.csm")

    written = write_main_wing_station_seam_side_aware_export_opcode_variant_probe_report(
        tmp_path / "out",
        profile_parametrization_audit_path=audit_path,
        materialize_variants=True,
        materialization_root=tmp_path / "variants",
        variant_materializer=_materializer,
        variant_validator=_validator,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert (
        payload["schema_version"]
        == "main_wing_station_seam_side_aware_export_opcode_variant_probe.v1"
    )
    assert (
        payload["opcode_variant_status"]
        == "side_aware_export_opcode_variant_not_recovered"
    )
    assert "Export Opcode Variant Probe v1" in markdown
