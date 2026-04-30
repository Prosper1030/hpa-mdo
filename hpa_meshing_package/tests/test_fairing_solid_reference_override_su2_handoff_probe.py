import json
from pathlib import Path
from types import SimpleNamespace

from hpa_meshing.fairing_solid_reference_override_su2_handoff_probe import (
    build_fairing_solid_reference_override_su2_handoff_probe_report,
    write_fairing_solid_reference_override_su2_handoff_probe_report,
)


def _write_reference_policy_probe(
    tmp_path: Path,
    *,
    external_reference_status: str = "candidate_available",
    marker_mapping_status: str = "compatible_mapping_required",
) -> Path:
    path = tmp_path / "fairing_solid_reference_policy_probe.v1.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "fairing_solid_reference_policy_probe.v1",
                "component": "fairing_solid",
                "reference_policy_status": "reference_mismatch_observed",
                "external_reference_status": external_reference_status,
                "marker_mapping_status": marker_mapping_status,
                "external_reference": {
                    "ref_area": 1.0,
                    "ref_length": 2.82880659,
                    "velocity_mps": 6.5,
                    "density_kgpm3": 1.225,
                    "dynamic_viscosity_pas": 1.7894e-5,
                    "temperature_k": 288.15,
                    "wall_marker": "fairing",
                    "farfield_marker": "farfield",
                    "source_path": "/tmp/external/su2_case.cfg",
                    "source_kind": "external_fairing_project_su2_policy",
                },
                "hpa_current_reference": {
                    "ref_area": 100.0,
                    "ref_length": 1.0,
                    "velocity_mps": 10.0,
                    "density_kgpm3": 1.225,
                    "dynamic_viscosity_pas": 1.789e-5,
                    "wall_marker": "fairing_solid",
                    "farfield_marker": "farfield",
                },
                "reference_mismatch_fields": ["ref_area", "ref_length", "velocity_mps"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_source_su2_probe(tmp_path: Path) -> Path:
    mesh_case = tmp_path / "real_mesh_probe"
    mesh_case.mkdir()
    (mesh_case / "report.json").write_text(
        json.dumps({"mesh_handoff": {"contract": "mesh_handoff.v1"}}) + "\n",
        encoding="utf-8",
    )
    su2_case = tmp_path / "source_su2_case"
    su2_case.mkdir()
    su2_handoff_path = su2_case / "su2_handoff.json"
    su2_handoff_path.write_text(
        json.dumps(
            {
                "contract": "su2_handoff.v1",
                "reference_geometry": {
                    "ref_origin_moment": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "warnings": ["geometry_derived_moment_origin_is_zero_vector"],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    path = tmp_path / "fairing_solid_real_su2_handoff_probe.v1.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "fairing_solid_real_su2_handoff_probe.v1",
                "component": "fairing_solid",
                "materialization_status": "su2_handoff_written",
                "source_mesh_case_report_path": str(mesh_case / "report.json"),
                "su2_handoff_path": str(su2_handoff_path),
                "component_force_ownership_status": "owned",
                "wall_marker_status": "fairing_solid_marker_present",
                "force_surface_scope": "component_subset",
                "reference_geometry_status": "warn",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _fake_case(case_root: Path):
    case_dir = case_root / "alpha_0_real_fairing_reference_override_probe"
    case_dir.mkdir(parents=True)
    contract_path = case_dir / "su2_handoff.json"
    su2_mesh = case_dir / "mesh.su2"
    runtime_cfg = case_dir / "su2_runtime.cfg"
    history = case_dir / "history.csv"
    contract_path.write_text('{"contract":"su2_handoff.v1"}\n', encoding="utf-8")
    su2_mesh.write_text("NDIME= 3\n", encoding="utf-8")
    runtime_cfg.write_text(
        "\n".join(
            [
                "REF_AREA= 1.000000",
                "REF_LENGTH= 2.828807",
                "INC_VELOCITY_INIT= ( 6.500000, 0.000000, 0.000000 )",
                "MARKER_MONITORING= ( fairing_solid )",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return SimpleNamespace(
        contract="su2_handoff.v1",
        provenance={"source_contract": "mesh_handoff.v1"},
        force_surface_provenance=SimpleNamespace(
            wall_marker="fairing_solid",
            scope="component_subset",
        ),
        convergence_gate=None,
        run_status="not_started",
        reference_geometry=SimpleNamespace(gate_status="warn"),
        input_mesh_artifact=Path("mesh.msh"),
        runtime_cfg_path=runtime_cfg,
        case_output_paths=SimpleNamespace(
            case_dir=case_dir,
            contract_path=contract_path,
            su2_mesh=su2_mesh,
            history=history,
        ),
    )


def test_reference_override_su2_handoff_probe_applies_external_policy(
    tmp_path: Path,
    monkeypatch,
):
    reference_policy_path = _write_reference_policy_probe(tmp_path)
    source_su2_probe_path = _write_source_su2_probe(tmp_path)

    def fake_materialize(mesh_handoff, runtime, case_root, source_root=None):
        assert mesh_handoff["contract"] == "mesh_handoff.v1"
        assert runtime.reference_mode == "user_declared"
        assert runtime.reference_override is not None
        assert runtime.reference_override.ref_area == 1.0
        assert runtime.reference_override.ref_length == 2.82880659
        assert runtime.reference_override.ref_origin_moment.x == 0.0
        assert (
            "borrowed_zero_moment_origin_from_source_su2_handoff"
            in runtime.reference_override.warnings
        )
        assert runtime.velocity_mps == 6.5
        assert runtime.density_kgpm3 == 1.225
        assert runtime.dynamic_viscosity_pas == 1.7894e-5
        return _fake_case(case_root)

    monkeypatch.setattr(
        "hpa_meshing.fairing_solid_reference_override_su2_handoff_probe.materialize_baseline_case",
        fake_materialize,
    )

    report = build_fairing_solid_reference_override_su2_handoff_probe_report(
        tmp_path / "override_probe",
        reference_policy_probe_path=reference_policy_path,
        source_su2_probe_report_path=source_su2_probe_path,
    )

    assert report.schema_version == "fairing_solid_reference_override_su2_handoff_probe.v1"
    assert report.materialization_status == "su2_handoff_written"
    assert report.reference_override_status == "applied_with_moment_origin_warning"
    assert report.reference_geometry_status == "warn"
    assert report.applied_reference.ref_area == 1.0
    assert report.applied_reference.ref_length == 2.82880659
    assert report.applied_reference.velocity_mps == 6.5
    assert report.marker_mapping_status == "mapped_external_fairing_to_fairing_solid"
    assert report.component_force_ownership_status == "owned"
    assert "hpa_current_reference_policy_mismatch" not in report.blocking_reasons
    assert "fairing_solver_not_run" in report.blocking_reasons
    assert "convergence_gate_not_run" in report.blocking_reasons
    assert "fairing_moment_origin_policy_incomplete_for_moment_coefficients" in report.blocking_reasons
    assert "external_fairing_reference_override_applied" in report.hpa_mdo_guarantees
    assert "production_default_unchanged" in report.hpa_mdo_guarantees


def test_reference_override_su2_handoff_probe_blocks_when_policy_is_insufficient(
    tmp_path: Path,
    monkeypatch,
):
    reference_policy_path = _write_reference_policy_probe(
        tmp_path,
        external_reference_status="insufficient_evidence",
    )
    source_su2_probe_path = _write_source_su2_probe(tmp_path)
    calls = []
    monkeypatch.setattr(
        "hpa_meshing.fairing_solid_reference_override_su2_handoff_probe.materialize_baseline_case",
        lambda *args, **kwargs: calls.append(args),
    )

    report = build_fairing_solid_reference_override_su2_handoff_probe_report(
        tmp_path / "override_probe",
        reference_policy_probe_path=reference_policy_path,
        source_su2_probe_report_path=source_su2_probe_path,
    )

    assert report.materialization_status == "blocked_before_reference_override"
    assert report.reference_override_status == "insufficient_evidence"
    assert report.su2_contract is None
    assert calls == []
    assert "external_fairing_reference_policy_insufficient" in report.blocking_reasons


def test_reference_override_su2_handoff_probe_writer_outputs_json_and_markdown(
    tmp_path: Path,
    monkeypatch,
):
    reference_policy_path = _write_reference_policy_probe(tmp_path)
    source_su2_probe_path = _write_source_su2_probe(tmp_path)
    monkeypatch.setattr(
        "hpa_meshing.fairing_solid_reference_override_su2_handoff_probe.materialize_baseline_case",
        lambda mesh_handoff, runtime, case_root, source_root=None: _fake_case(case_root),
    )

    paths = write_fairing_solid_reference_override_su2_handoff_probe_report(
        tmp_path / "override_probe",
        reference_policy_probe_path=reference_policy_path,
        source_su2_probe_report_path=source_su2_probe_path,
    )

    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")

    assert set(paths) == {"json", "markdown"}
    assert payload["materialization_status"] == "su2_handoff_written"
    assert payload["reference_override_status"] == "applied_with_moment_origin_warning"
    assert "fairing_solid reference override su2_handoff probe" in markdown
