import json
from pathlib import Path

from hpa_meshing.main_wing_panel_wake_semantics_audit import (
    build_main_wing_panel_wake_semantics_audit_report,
    write_main_wing_panel_wake_semantics_audit_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _fixture_report_root(tmp_path: Path) -> Path:
    root = tmp_path / "reports"
    _write_json(
        root
        / "main_wing_vspaero_panel_reference_probe"
        / "main_wing_vspaero_panel_reference_probe.v1.json",
        {
            "panel_reference_status": "panel_reference_available",
            "source_setup_path": "output/panel/black_cat_004.vspaero",
            "setup_reference": {
                "Vinf": 6.5,
                "NumWakeNodes": 64.0,
                "WakeIters": 3.0,
                "ImplicitWake": 0.0,
                "FreezeWakeAtIteration": 10000.0,
            },
            "selected_case": {
                "CLo": -0.002747646367,
                "CLi": 1.29039314231,
                "CLtot": 1.287645495943,
                "CLwtot": 1.289971668181,
            },
        },
    )
    _write_json(
        root
        / "main_wing_panel_su2_lift_gap_debug"
        / "main_wing_panel_su2_lift_gap_debug.v1.json",
        {
            "debug_status": "gap_confirmed_debug_ready",
            "su2_force_breakdown": {
                "forces_breakdown_status": "available",
                "forces_breakdown_cl": 0.263162,
                "force_breakdown_marker_owned": True,
            },
            "boundary_condition_observed": {
                "solver": "INC_NAVIER_STOKES",
                "wall_boundary_condition": "euler",
            },
        },
    )
    _write_json(
        root
        / "main_wing_su2_mesh_normal_audit"
        / "main_wing_su2_mesh_normal_audit.v1.json",
        {
            "normal_audit_status": "pass",
            "engineering_findings": [
                "main_wing_surface_normals_mixed_upper_lower",
                "single_global_normal_flip_not_supported",
            ],
        },
    )
    return root


def test_panel_wake_semantics_audit_identifies_current_model_gap(tmp_path: Path):
    cfg_path = tmp_path / "su2_runtime.cfg"
    cfg_path.write_text(
        "\n".join(
            [
                "SOLVER= INC_NAVIER_STOKES",
                "INC_VELOCITY_INIT= ( 6.500000, 0.000000, 0.000000 )",
                "MARKER_EULER= ( main_wing )",
                "MARKER_MONITORING= ( main_wing )",
                "MARKER_FAR= ( farfield )",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_main_wing_panel_wake_semantics_audit_report(
        report_root=_fixture_report_root(tmp_path),
        runtime_cfg_path=cfg_path,
    )

    assert report.audit_status == "semantics_gap_observed"
    assert report.panel_wake_observed["num_wake_nodes"] == 64.0
    assert report.panel_wake_observed["inviscid_lift_fraction_of_cltot"] > 1.0
    assert report.panel_wake_observed["cli_component_label"] == (
        "inviscid_surface_integration_component"
    )
    assert report.panel_wake_observed["cliw_component_label"] == (
        "wake_free_stream_induced_component"
    )
    assert report.su2_semantics_observed["wall_boundary_condition"] == "euler"
    assert report.su2_semantics_observed["has_explicit_wake_model_keys"] is False
    assert "panel_lift_dominated_by_inviscid_component" in report.engineering_findings
    assert (
        "panel_lift_dominated_by_induced_wake_terms"
        not in report.engineering_findings
    )
    assert "single_global_normal_flip_not_supported" in report.engineering_findings
    assert report.next_actions[0] == (
        "audit_su2_thin_surface_geometry_closed_vs_lifting_surface_export"
    )


def test_write_panel_wake_semantics_audit_report(tmp_path: Path):
    cfg_path = tmp_path / "su2_runtime.cfg"
    cfg_path.write_text("SOLVER= INC_NAVIER_STOKES\nMARKER_EULER= ( main_wing )\n")

    written = write_main_wing_panel_wake_semantics_audit_report(
        tmp_path / "out",
        report_root=_fixture_report_root(tmp_path),
        runtime_cfg_path=cfg_path,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == "main_wing_panel_wake_semantics_audit.v1"
    assert payload["audit_status"] == "semantics_gap_observed"
    assert "Main Wing Panel Wake Semantics Audit v1" in markdown
