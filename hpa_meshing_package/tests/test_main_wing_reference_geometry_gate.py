import json
from pathlib import Path

from hpa_meshing.main_wing_reference_geometry_gate import (
    build_main_wing_reference_geometry_gate_report,
    write_main_wing_reference_geometry_gate_report,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _fixture_reports(tmp_path: Path) -> Path:
    root = tmp_path / "reports"
    _write_json(
        root
        / "main_wing_esp_rebuilt_geometry_smoke"
        / "main_wing_esp_rebuilt_geometry_smoke.v1.json",
        {
            "geometry_smoke_status": "geometry_smoke_pass",
            "source_path": "blackcat_004_origin.vsp3",
            "selected_geom_name": "Main Wing",
            "selected_geom_span_y": 16.47465195857948,
            "selected_geom_chord_x": 1.3023502084398801,
            "bounds": {
                "x_min": -0.001259312194113,
                "x_max": 1.302329269,
                "y_min": -16.5,
                "y_max": 16.5,
                "z_min": -0.0680367431158,
                "z_max": 0.835274708339,
            },
        },
    )
    _write_json(
        root
        / "main_wing_real_mesh_handoff_probe"
        / "main_wing_real_mesh_handoff_probe.v1.json",
        {
            "probe_status": "mesh_handoff_pass",
            "mesh_handoff_status": "written",
            "selected_geom_span_y": 16.47465195857948,
            "selected_geom_chord_x": 1.3023502084398801,
            "probe_global_min_size": 0.35,
            "probe_global_max_size": 1.4,
        },
    )
    su2_case = root / "main_wing_real_su2_handoff_probe" / "artifacts" / "su2_case"
    _write_json(
        su2_case / "su2_handoff.json",
        {
            "runtime": {
                "velocity_mps": 6.5,
                "reference_override": {
                    "ref_area": 34.65,
                    "ref_length": 1.05,
                    "ref_origin_moment": {"x": 0.2625, "y": 0.0, "z": 0.0},
                    "source_label": "blackcat_main_wing_full_span_reference",
                    "warnings": [
                        "coarse_real_geometry_probe_reference_not_production_certified"
                    ],
                },
            },
            "reference_geometry": {
                "ref_area": 34.65,
                "ref_length": 1.05,
                "ref_origin_moment": {"x": 0.2625, "y": 0.0, "z": 0.0},
                "gate_status": "warn",
            },
        },
    )
    _write_json(
        root
        / "main_wing_real_su2_handoff_probe"
        / "main_wing_real_su2_handoff_probe.v1.json",
        {
            "materialization_status": "su2_handoff_written",
            "su2_handoff_path": str(su2_case / "su2_handoff.json"),
            "reference_geometry_status": "warn",
            "observed_velocity_mps": 6.5,
        },
    )
    return root


def test_main_wing_reference_geometry_gate_records_warned_provenance(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(
        "hpa_meshing.main_wing_reference_geometry_gate._load_openvsp_reference_data",
        lambda source_path: {
            "ref_area": 35.175,
            "ref_length": 1.0425,
            "ref_origin_moment": {"x": 0.0, "y": 0.0, "z": 0.0},
            "area_method": "openvsp_reference_wing.sref",
            "length_method": "openvsp_reference_wing.cref",
            "moment_method": "openvsp_vspaero_settings.cg",
            "reference_wing_name": "Main Wing",
            "settings": {"sref": 35.175, "bref": 33.0, "cref": 1.0425},
            "wing_quantities": {"sref": 35.175, "bref": 33.0, "cref": 1.0425},
            "warnings": [],
        },
    )

    report = build_main_wing_reference_geometry_gate_report(
        report_root=_fixture_reports(tmp_path)
    )

    assert report.schema_version == "main_wing_reference_geometry_gate.v1"
    assert report.reference_gate_status == "warn"
    assert report.applied_reference["ref_area"] == 34.65
    assert report.applied_reference["ref_length"] == 1.05
    assert report.derived_full_span_m == 33.0
    assert report.geometry_bounds_span_y_m == 33.0
    assert report.openvsp_reference_status == "available"
    assert report.openvsp_reference["ref_length"] == 1.0425
    assert report.checks["declared_span_vs_bounds_y"]["status"] == "pass"
    assert report.checks["declared_span_vs_selected_geom_span"]["status"] == "pass"
    assert report.checks["ref_length_independent_source"]["status"] == "pass"
    assert report.checks["applied_ref_area_vs_openvsp_sref"]["status"] == "warn"
    assert report.checks["moment_origin_policy"]["status"] == "warn"
    assert "main_wing_reference_geometry_incomplete" in report.blocking_reasons
    assert "main_wing_reference_chord_not_independently_certified" not in report.blocking_reasons
    assert "main_wing_reference_area_differs_from_openvsp_sref" in report.blocking_reasons
    assert "declared_span_crosschecked_against_real_geometry_bounds" in report.hpa_mdo_guarantees
    assert "ref_length_crosschecked_against_openvsp_cref" in report.hpa_mdo_guarantees
    assert "reference_geometry_not_promoted_to_pass" in report.hpa_mdo_guarantees


def test_main_wing_reference_geometry_gate_blocks_without_su2_reference(
    tmp_path: Path,
):
    root = _fixture_reports(tmp_path)
    (root / "main_wing_real_su2_handoff_probe" / "main_wing_real_su2_handoff_probe.v1.json").unlink()

    report = build_main_wing_reference_geometry_gate_report(report_root=root)

    assert report.reference_gate_status == "unavailable"
    assert "main_wing_real_su2_handoff_reference_unavailable" in report.blocking_reasons


def test_main_wing_reference_geometry_gate_writer_outputs_json_and_markdown(
    tmp_path: Path,
):
    paths = write_main_wing_reference_geometry_gate_report(
        tmp_path / "out",
        report_root=_fixture_reports(tmp_path),
    )

    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")

    assert payload["reference_gate_status"] == "warn"
    assert "main_wing reference geometry gate" in markdown
    assert "main_wing_reference_geometry_incomplete" in markdown
