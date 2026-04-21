from __future__ import annotations

from pathlib import Path


def test_detect_esp_runtime_reports_missing_binaries(monkeypatch):
    from hpa_meshing.providers.esp_runtime import detect_esp_runtime

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_runtime.shutil.which",
        lambda _: None,
    )

    runtime = detect_esp_runtime()

    assert runtime.available is False
    assert runtime.binaries["serveESP"] is None
    assert runtime.binaries["serveCSM"] is None
    assert runtime.binaries["ocsm"] is None
    assert "serveESP" in runtime.missing
    assert "serveCSM" in runtime.missing
    assert "ocsm" in runtime.missing


def test_detect_esp_runtime_collects_binary_paths(monkeypatch, tmp_path: Path):
    from hpa_meshing.providers.esp_runtime import detect_esp_runtime

    fake_root = tmp_path / "esp" / "bin"
    fake_root.mkdir(parents=True)
    fake_serve = fake_root / "serveESP"
    fake_csm = fake_root / "serveCSM"
    fake_ocsm = fake_root / "ocsm"
    for path in (fake_serve, fake_csm, fake_ocsm):
        path.write_text("#!/bin/sh\n", encoding="utf-8")

    name_to_path = {
        "serveESP": str(fake_serve),
        "serveCSM": str(fake_csm),
        "ocsm": str(fake_ocsm),
    }
    monkeypatch.setattr(
        "hpa_meshing.providers.esp_runtime.shutil.which",
        lambda name: name_to_path.get(name),
    )

    runtime = detect_esp_runtime()

    assert runtime.available is True
    assert runtime.binaries["serveESP"] == str(fake_serve)
    assert runtime.binaries["serveCSM"] == str(fake_csm)
    assert runtime.binaries["ocsm"] == str(fake_ocsm)
    assert runtime.missing == []


def test_detect_esp_runtime_partial_missing_lists_gaps(monkeypatch, tmp_path: Path):
    from hpa_meshing.providers.esp_runtime import detect_esp_runtime

    fake_serve = tmp_path / "serveESP"
    fake_serve.write_text("#!/bin/sh\n", encoding="utf-8")

    name_to_path = {
        "serveESP": str(fake_serve),
        "serveCSM": None,
        "ocsm": None,
    }
    monkeypatch.setattr(
        "hpa_meshing.providers.esp_runtime.shutil.which",
        lambda name: name_to_path.get(name),
    )

    runtime = detect_esp_runtime()

    assert runtime.available is False
    assert runtime.binaries["serveESP"] == str(fake_serve)
    assert runtime.missing == ["serveCSM", "ocsm"]


def test_esp_runtime_status_serializes_to_dict(monkeypatch):
    from hpa_meshing.providers.esp_runtime import detect_esp_runtime

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_runtime.shutil.which",
        lambda _: None,
    )

    payload = detect_esp_runtime().to_dict()

    assert payload["available"] is False
    assert set(payload["binaries"].keys()) == {"serveESP", "serveCSM", "ocsm"}
    assert set(payload["missing"]) == {"serveESP", "serveCSM", "ocsm"}
