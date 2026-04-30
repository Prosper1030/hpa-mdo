import json
from pathlib import Path

from hpa_meshing.main_wing_su2_force_marker_audit import (
    build_main_wing_su2_force_marker_audit_report,
    write_main_wing_su2_force_marker_audit_report,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _write_fixture(tmp_path: Path) -> Path:
    report_root = tmp_path / "docs" / "reports"
    probe_dir = report_root / "main_wing_openvsp_reference_su2_handoff_probe"
    marker_summary = _write_json(
        tmp_path / "mesh" / "marker_summary.json",
        {
            "main_wing": {"exists": True, "dimension": 2, "element_count": 2424},
            "farfield": {"exists": True, "dimension": 2, "element_count": 5376},
        },
    )
    _write_json(
        probe_dir / "main_wing_openvsp_reference_su2_handoff_probe.v1.json",
        {
            "materialization_status": "su2_handoff_written",
            "su2_handoff_path": "tmp/run/su2_handoff.json",
        },
    )
    _write_json(
        probe_dir / "artifacts" / "su2_handoff.json",
        {
            "mesh_markers": {
                "wall": "main_wing",
                "farfield": "farfield",
                "monitoring": ["main_wing"],
                "plotting": ["main_wing"],
                "euler": ["main_wing"],
            },
            "force_surface_provenance": {
                "gate_status": "pass",
                "wall_marker": "main_wing",
                "monitoring_markers": ["main_wing"],
                "plotting_markers": ["main_wing"],
                "euler_markers": ["main_wing"],
                "primary_group": {"element_count": 2424},
                "matches_wall_marker": True,
                "scope": "component_subset",
            },
            "runtime": {
                "velocity_mps": 6.5,
                "solver": "INC_NAVIER_STOKES",
                "wall_boundary_condition": "euler",
                "flow_conditions": {"velocity_mps": 6.5},
            },
            "reference_geometry": {
                "ref_area": 35.175,
                "ref_length": 1.0425,
                "warnings": ["geometry_derived_moment_origin_is_zero_vector"],
            },
            "runtime_cfg_path": "tmp/run/su2_runtime.cfg",
            "provenance": {"source_marker_summary": str(marker_summary)},
        },
    )
    cfg_path = probe_dir / "artifacts" / "su2_runtime.cfg"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        "\n".join(
            [
                "INC_VELOCITY_INIT= ( 6.500000, 0.000000, 0.000000 )",
                "REF_AREA= 35.175000",
                "REF_LENGTH= 1.042500",
                "MARKER_EULER= ( main_wing )",
                "MARKER_MONITORING= ( main_wing )",
                "MARKER_PLOTTING= ( main_wing )",
                "MARKER_FAR= ( farfield )",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return report_root


def test_main_wing_su2_force_marker_audit_records_marker_contract(tmp_path: Path):
    report_root = _write_fixture(tmp_path)

    report = build_main_wing_su2_force_marker_audit_report(report_root=report_root)

    assert report.audit_status == "warn"
    assert report.checks["force_surface_provenance"]["status"] == "pass"
    assert report.checks["runtime_cfg_markers"]["status"] == "pass"
    assert report.checks["mesh_marker_counts"]["status"] == "pass"
    assert report.marker_contract["wall_marker"] == "main_wing"
    assert report.cfg_markers["MARKER_MONITORING"] == ["main_wing"]
    assert report.flow_reference_observed["velocity_mps"] == 6.5
    assert "main_wing_solver_wall_bc_is_euler_smoke_not_viscous" in (
        report.engineering_flags
    )
    assert "main_wing_reference_geometry_warn" in report.engineering_flags
    assert not report.blocking_reasons


def test_write_main_wing_su2_force_marker_audit_report(tmp_path: Path):
    report_root = _write_fixture(tmp_path)
    out_dir = tmp_path / "audit"

    written = write_main_wing_su2_force_marker_audit_report(
        out_dir,
        report_root=report_root,
    )

    payload = json.loads(written["json"].read_text(encoding="utf-8"))
    markdown = written["markdown"].read_text(encoding="utf-8")
    assert payload["schema_version"] == "main_wing_su2_force_marker_audit.v1"
    assert payload["audit_status"] == "warn"
    assert "Main Wing SU2 Force Marker Audit v1" in markdown
