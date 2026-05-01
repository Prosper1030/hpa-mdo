import json
from pathlib import Path

from hpa_meshing.main_wing_station_seam_export_metadata_source_audit import (
    build_main_wing_station_seam_export_metadata_source_audit_report,
    write_main_wing_station_seam_export_metadata_source_audit_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_source(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _source_files(tmp_path: Path) -> dict[str, Path]:
    return {
        "provider": _write_source(
            tmp_path / "providers" / "esp_pipeline.py",
            "\n".join(
                [
                    "def _build_section_sketch_lines(section):",
                    "    opcode = 'linseg' if index == 1 else 'spline'",
                    "def _build_csm_script_from_rebuild_model(model, export_path):",
                    "    return '\\n'.join(['rule', 'ATTRIBUTE capsGroup $main_wing', 'DUMP !export_path 0 1'])",
                ]
            ),
        ),
        "side_aware": _write_source(
            tmp_path / "main_wing_station_seam_side_aware_parametrization_probe.py",
            "\n".join(
                [
                    "def _build_candidate_csm():",
                    "    lines = ['skbeg 0 0 0', 'linseg 1 0 0', 'spline 0 0 1', 'rule', 'DUMP !export_path 0 1']",
                ]
            ),
        ),
        "opcode_variant": _write_source(
            tmp_path / "main_wing_station_seam_side_aware_export_opcode_variant_probe.py",
            "DEFAULT_OPCODE_VARIANTS = ['upper_lower_spline_split', 'all_linseg']\n",
        ),
        "metadata_repair": _write_source(
            tmp_path / "main_wing_station_seam_side_aware_metadata_repair_probe.py",
            "from OCP.BRepLib import BRepLib\nfrom OCP.ShapeFix import ShapeFix_Edge\n",
        ),
        "projected_builder": _write_source(
            tmp_path / "main_wing_station_seam_side_aware_projected_pcurve_builder_probe.py",
            "from OCP.GeomProjLib import GeomProjLib\nfrom OCP.Geom2dAPI import Geom2dAPI_Interpolate\n",
        ),
    }


def _opcode_variant_report(path: Path) -> Path:
    return _write_json(
        path,
        {
            "opcode_variant_status": "side_aware_export_opcode_variant_not_recovered",
            "variant_summary": {
                "variant_count": 2,
                "materialized_variant_count": 2,
                "validated_variant_count": 1,
                "recovered_variant_count": 0,
                "surface_count_guard_skipped_count": 1,
                "best_station_edge_check_count": 10,
            },
            "engineering_findings": [
                "upper_lower_spline_split_still_pcurve_suspect",
                "all_linseg_surface_count_explosion_observed",
            ],
            "next_actions": [
                "inspect_export_pcurve_metadata_generation_instead_of_simple_opcode_variants"
            ],
        },
    )


def test_export_metadata_source_audit_captures_owned_vs_external_boundary(
    tmp_path: Path,
):
    report = build_main_wing_station_seam_export_metadata_source_audit_report(
        opcode_variant_probe_path=_opcode_variant_report(tmp_path / "opcode.json"),
        source_files=_source_files(tmp_path),
        external_src_root=tmp_path / "external-src",
    )

    assert (
        report.audit_status
        == "export_metadata_generation_source_boundary_captured"
    )
    assert report.production_default_changed is False
    assert report.source_boundary["hpa_mdo_controls"] == [
        "section_coordinates",
        "sketch_opcode_policy",
        "rule_grouping",
        "dump_invocation",
    ]
    assert "opencsm_rule_loft_pcurve_metadata" in (
        report.source_boundary["external_controls"]
    )
    assert report.current_negative_controls["recovered_variant_count"] == 0
    assert report.external_source_inventory["opencsm_or_egads_source_available"] is False
    assert "hpa_mdo_csm_generation_has_no_explicit_pcurve_metadata_api" in (
        report.engineering_findings
    )
    assert "export_pcurve_metadata_generation_not_owned_by_hpa_mdo" in (
        report.blocking_reasons
    )
    assert report.next_actions[0] == (
        "inspect_opencsm_egads_step_export_metadata_controls_or_add_owned_occ_export_path"
    )


def test_write_export_metadata_source_audit_report(tmp_path: Path):
    written = write_main_wing_station_seam_export_metadata_source_audit_report(
        tmp_path / "out",
        opcode_variant_probe_path=_opcode_variant_report(tmp_path / "opcode.json"),
        source_files=_source_files(tmp_path),
        external_src_root=tmp_path / "external-src",
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert (
        payload["schema_version"]
        == "main_wing_station_seam_export_metadata_source_audit.v1"
    )
    assert (
        payload["audit_status"]
        == "export_metadata_generation_source_boundary_captured"
    )
    assert "Export Metadata Source Audit v1" in markdown
