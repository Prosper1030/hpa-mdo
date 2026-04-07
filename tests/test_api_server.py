from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hpa_mdo.api.server import app


client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_materials_returns_list() -> None:
    response = client.get("/materials")

    assert response.status_code == 200
    materials = response.json()
    assert len(materials) > 0
    assert "carbon_fiber_hm" in materials


def test_optimize_missing_config_returns_error() -> None:
    response = client.post(
        "/optimize",
        json={"config_yaml_path": "/nonexistent/path.yaml"},
    )

    assert response.status_code in {400, 422, 500}
    assert response.json()["val_weight"] == 99999


@pytest.mark.slow
def test_optimize_valid_config_returns_result() -> None:
    response = client.post(
        "/optimize",
        json={"config_yaml_path": "configs/blackcat_004.yaml"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "val_weight" in payload
    assert payload["val_weight"] != 99999


def test_export_missing_config_returns_error() -> None:
    response = client.post(
        "/export",
        json={
            "config_yaml_path": "/bad/path.yaml",
            "output_dir": "/tmp",
            "formats": ["csv"],
        },
    )

    assert response.json()["val_weight"] == 99999
