from __future__ import annotations

from pathlib import Path

import pytest

from hpa_meshing.schema import GeometryProviderRequest


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
        ),
    )

    captured: dict = {}

    def fake_pipeline(*, source_path: Path, staging_dir: Path) -> EspMaterializationResult:
        captured["source_path"] = source_path
        captured["staging_dir"] = staging_dir
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
        ),
    )

    def boom(**_):
        raise NotImplementedError("ESP/OpenCSM materialization is not implemented yet.")

    monkeypatch.setattr(provider_module, "materialize_with_esp", boom)

    request = _make_request(tmp_path)
    result = materialize(request)

    assert result.status == "failed"
    assert result.provenance.get("failure_code") == "esp_pipeline_not_implemented"


def test_materialize_with_esp_default_raises_not_implemented(tmp_path: Path):
    from hpa_meshing.providers.esp_pipeline import materialize_with_esp

    with pytest.raises(NotImplementedError):
        materialize_with_esp(
            source_path=tmp_path / "model.vsp3",
            staging_dir=tmp_path / "stage",
        )
