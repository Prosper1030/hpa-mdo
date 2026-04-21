from __future__ import annotations

import json
import subprocess
from pathlib import Path

from hpa_meshing.schema import GeometryProviderRequest, GeometryTopologyMetadata


def _make_request(tmp_path: Path) -> GeometryProviderRequest:
    return GeometryProviderRequest(
        provider="esp_rebuilt",
        source_path=tmp_path / "model.vsp3",
        component="aircraft_assembly",
        staging_dir=tmp_path / "provider",
        geometry_family_hint="thin_sheet_aircraft_assembly",
        units_hint="m",
    )


def test_esp_rebuilt_reports_runtime_missing_as_failed(monkeypatch, tmp_path: Path):
    from hpa_meshing.providers.esp_rebuilt import materialize
    from hpa_meshing.providers.esp_runtime import EspRuntimeStatus

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_rebuilt.detect_esp_runtime",
        lambda: EspRuntimeStatus(
            available=False,
            binaries={"serveESP": None, "serveCSM": None, "ocsm": None},
            missing=["serveESP", "serveCSM", "ocsm"],
        ),
    )

    request = _make_request(tmp_path)
    result = materialize(request)

    assert result.status == "failed"
    assert result.provider == "esp_rebuilt"
    assert result.provenance["runtime"]["available"] is False
    assert "serveESP" in result.provenance["runtime"]["missing"]
    assert result.provenance.get("failure_code") == "esp_runtime_missing"


def test_esp_rebuilt_delegates_to_materialize_with_esp_when_runtime_available(
    monkeypatch, tmp_path: Path
):
    from hpa_meshing.providers import esp_rebuilt as provider_module
    from hpa_meshing.providers.esp_rebuilt import materialize
    from hpa_meshing.providers.esp_runtime import EspRuntimeStatus
    from hpa_meshing.providers.esp_pipeline import EspMaterializationResult

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_rebuilt.detect_esp_runtime",
        lambda: EspRuntimeStatus(
            available=True,
            binaries={
                "serveESP": "/opt/esp/bin/serveESP",
                "serveCSM": "/opt/esp/bin/serveCSM",
                "ocsm": "/opt/esp/bin/ocsm",
            },
            missing=[],
            batch_binary="/opt/esp/bin/serveCSM",
        ),
    )

    captured: dict = {}

    def fake_pipeline(
        *,
        source_path: Path,
        staging_dir: Path,
        component: str = "aircraft_assembly",
        batch_binary: str | None = None,
    ) -> EspMaterializationResult:
        captured["source_path"] = source_path
        captured["staging_dir"] = staging_dir
        captured["component"] = component
        captured["batch_binary"] = batch_binary
        return EspMaterializationResult(
            status="failed",
            normalized_geometry_path=None,
            topology_report_path=None,
            notes=["pipeline stub"],
            warnings=["materialization pipeline not implemented yet"],
            failure_code="esp_pipeline_unavailable",
        )

    monkeypatch.setattr(provider_module, "materialize_with_esp", fake_pipeline)

    request = _make_request(tmp_path)
    result = materialize(request)

    assert captured["source_path"] == request.source_path
    assert captured["staging_dir"] == request.staging_dir
    assert captured["component"] == request.component
    assert captured["batch_binary"] == "/opt/esp/bin/serveCSM"
    assert result.status == "failed"
    assert result.provenance.get("failure_code") == "esp_pipeline_unavailable"
    assert "materialization pipeline not implemented yet" in result.warnings


def test_esp_rebuilt_reports_pipeline_not_implemented_when_raised(
    monkeypatch, tmp_path: Path
):
    from hpa_meshing.providers import esp_rebuilt as provider_module
    from hpa_meshing.providers.esp_rebuilt import materialize
    from hpa_meshing.providers.esp_runtime import EspRuntimeStatus

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_rebuilt.detect_esp_runtime",
        lambda: EspRuntimeStatus(
            available=True,
            binaries={
                "serveESP": "/opt/esp/bin/serveESP",
                "serveCSM": "/opt/esp/bin/serveCSM",
                "ocsm": "/opt/esp/bin/ocsm",
            },
            missing=[],
            batch_binary="/opt/esp/bin/serveCSM",
        ),
    )

    def boom(**_):
        raise NotImplementedError("ESP/OpenCSM materialization is not implemented yet.")

    monkeypatch.setattr(provider_module, "materialize_with_esp", boom)

    request = _make_request(tmp_path)
    result = materialize(request)

    assert result.status == "failed"
    assert result.provenance.get("failure_code") == "esp_pipeline_not_implemented"


def test_esp_rebuilt_returns_normalized_geometry_when_pipeline_succeeds(
    monkeypatch, tmp_path: Path
):
    from hpa_meshing.providers import esp_rebuilt as provider_module
    from hpa_meshing.providers.esp_rebuilt import materialize
    from hpa_meshing.providers.esp_runtime import EspRuntimeStatus
    from hpa_meshing.providers.esp_pipeline import EspMaterializationResult

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_rebuilt.detect_esp_runtime",
        lambda: EspRuntimeStatus(
            available=True,
            binaries={
                "serveESP": "/opt/esp/bin/serveESP",
                "serveCSM": "/opt/esp/bin/serveCSM",
                "ocsm": "/opt/esp/bin/ocsm",
            },
            missing=[],
            batch_binary="/opt/esp/bin/serveCSM",
        ),
    )

    normalized = tmp_path / "normalized.stp"
    topology = tmp_path / "topology.json"
    command_log = tmp_path / "ocsm.log"
    script_path = tmp_path / "rebuild.csm"
    input_model = tmp_path / "model_copy.vsp3"
    normalized.write_text("ISO-10303-21;\n", encoding="utf-8")
    topology.write_text('{"surface_count": 38}\n', encoding="utf-8")
    command_log.write_text("ocsm output\n", encoding="utf-8")
    script_path.write_text("UDPRIM vsp3 filename $model.vsp3\n", encoding="utf-8")
    input_model.write_text("<vsp3/>\n", encoding="utf-8")

    monkeypatch.setattr(
        provider_module,
        "materialize_with_esp",
        lambda **_: EspMaterializationResult(
            status="success",
            normalized_geometry_path=normalized,
            topology_report_path=topology,
            topology=GeometryTopologyMetadata(
                representation="brep_trimmed_step",
                source_kind="stp",
                units="m",
                body_count=2,
                surface_count=38,
                volume_count=2,
            ),
            notes=["esp rebuild succeeded"],
            warnings=[],
            provider_version="esp129-macos-arm64",
            command_log_path=command_log,
            script_path=script_path,
            input_model_path=input_model,
        ),
    )

    request = _make_request(tmp_path)
    result = materialize(request)

    assert result.status == "materialized"
    assert result.normalized_geometry_path == normalized
    assert result.artifacts["normalized_geometry"] == normalized
    assert result.artifacts["topology_report"] == topology
    assert result.artifacts["command_log"] == command_log
    assert result.artifacts["esp_script"] == script_path
    assert result.artifacts["esp_input_model"] == input_model
    assert result.provider_version == "esp129-macos-arm64"
    assert result.topology.representation == "brep_trimmed_step"
    assert result.topology.surface_count == 38
    assert result.topology.body_count == 2
    assert "esp rebuild succeeded" in result.topology.notes


def test_materialize_with_esp_runs_ocsm_batch_and_collects_artifacts(tmp_path: Path):
    from hpa_meshing.providers.esp_pipeline import materialize_with_esp

    source = tmp_path / "source model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    staging = tmp_path / "provider with spaces"

    invocations: list[dict] = []

    def fake_runner(args, cwd):
        invocations.append({"args": list(args), "cwd": Path(cwd)})
        exported = Path(cwd) / "raw_dump.stp"
        exported.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="ocsm: build complete\n",
            stderr="",
        )

    result = materialize_with_esp(
        source_path=source,
        staging_dir=staging,
        runner=fake_runner,
        batch_binary="/opt/esp/bin/serveCSM",
    )

    assert result.status == "success"
    assert result.normalized_geometry_path is not None
    assert result.normalized_geometry_path.exists()
    assert result.script_path is not None
    assert result.script_path.exists()
    assert result.command_log_path is not None
    assert result.command_log_path.exists()
    assert result.topology_report_path is not None
    assert result.topology_report_path.exists()
    assert result.input_model_path is not None
    assert result.input_model_path.exists()
    assert result.input_model_path.read_text(encoding="utf-8") == "<vsp3/>"
    assert result.topology is not None
    assert invocations, "runner was not invoked"
    first_args = invocations[0]["args"]
    assert Path(first_args[0]).name in {"serveCSM", "ocsm"}
    script_arg = Path(first_args[-1])
    assert script_arg.is_absolute()
    assert " " not in str(script_arg)
    assert script_arg.name.endswith(".csm")
    assert result.script_path is not None
    assert script_arg.name == result.script_path.name
    assert "provider with spaces" in str(result.script_path)
    script_text = result.script_path.read_text(encoding="utf-8")
    assert "provider with spaces" not in script_text
    assert result.input_model_path.name in script_text
    assert "raw_dump.stp" in script_text
    assert "DUMP !export_path 0 1" in script_text
    assert result.artifacts["raw_geometry"].name == "raw_dump.stp"
    assert result.artifacts["normalization_report"].name == "normalization.json"
    topology_payload = json.loads(result.topology_report_path.read_text(encoding="utf-8"))
    assert topology_payload["export_exists"] is True
    assert "units" in topology_payload
    assert "body_count" in topology_payload
    assert "surface_count" in topology_payload
    assert "volume_count" in topology_payload
    assert "bounds" in topology_payload
    assert "import_scale_to_units" in topology_payload
    assert "backend_rescale_required" in topology_payload
    assert "runtime_exec_dir" in topology_payload


def test_materialize_with_esp_rewrites_mislabeled_mm_export_to_meter_units(
    monkeypatch, tmp_path: Path
):
    from hpa_meshing.providers import esp_pipeline
    from hpa_meshing.providers.esp_pipeline import materialize_with_esp

    source = tmp_path / "source model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    staging = tmp_path / "provider"

    monkeypatch.setattr(
        esp_pipeline,
        "load_openvsp_reference_data",
        lambda _: {"ref_length": 1.0425},
    )

    def fake_runner(args, cwd):
        exported = Path(cwd) / "raw_dump.stp"
        exported.write_text(
            "\n".join(
                [
                    "ISO-10303-21;",
                    "HEADER;",
                    "ENDSEC;",
                    "DATA;",
                    "#1 = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );",
                    "#2 = CARTESIAN_POINT('',(0.,0.,0.));",
                    "#3 = CARTESIAN_POINT('',(5.7,16.47465195858,1.7));",
                    "#4 = CARTESIAN_POINT('',(-0.00002156555057324,-16.47465195858,-0.7));",
                    "ENDSEC;",
                    "END-ISO-10303-21;",
                ]
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="ocsm: build complete\n",
            stderr="",
        )

    result = materialize_with_esp(
        source_path=source,
        staging_dir=staging,
        runner=fake_runner,
        batch_binary="/opt/esp/bin/serveCSM",
    )

    assert result.status == "success"
    assert result.normalized_geometry_path is not None
    step_text = result.normalized_geometry_path.read_text(encoding="utf-8")
    assert "SI_UNIT(.MILLI.,.METRE.)" not in step_text
    assert "SI_UNIT(.UNSET.,.METRE.)" in step_text
    assert result.topology is not None
    assert result.topology.units == "m"
    assert any(note.startswith("rewrote_step_length_units:mm_to_m") for note in result.notes)


def test_materialize_with_esp_reports_failed_when_runner_returns_nonzero(
    tmp_path: Path,
):
    from hpa_meshing.providers.esp_pipeline import materialize_with_esp

    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    staging = tmp_path / "provider"

    def fake_runner(args, cwd):
        return subprocess.CompletedProcess(
            args=args,
            returncode=3,
            stdout="",
            stderr="ocsm: UDPRIM vsp3 import failed\n",
        )

    result = materialize_with_esp(
        source_path=source,
        staging_dir=staging,
        runner=fake_runner,
        batch_binary="/opt/esp/bin/serveCSM",
    )

    assert result.status == "failed"
    assert result.failure_code in {
        "esp_ocsm_batch_failed",
        "esp_export_missing",
    }
    assert result.command_log_path is not None
    assert result.command_log_path.exists()


def test_materialize_with_esp_reports_missing_binary_when_path_empty(tmp_path: Path):
    from hpa_meshing.providers import esp_pipeline
    from hpa_meshing.providers.esp_pipeline import materialize_with_esp

    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    staging = tmp_path / "provider"

    original_which = esp_pipeline.shutil.which
    try:
        esp_pipeline.shutil.which = lambda _: None  # type: ignore[assignment]
        result = materialize_with_esp(source_path=source, staging_dir=staging)
    finally:
        esp_pipeline.shutil.which = original_which  # type: ignore[assignment]

    assert result.status == "failed"
    assert result.failure_code == "esp_batch_binary_missing"
    assert result.command_log_path is not None
    assert result.command_log_path.exists()
