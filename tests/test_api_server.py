from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

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
    payload = response.json()
    assert payload["error_code"] is None
    materials = payload["materials"]
    assert len(materials) > 0
    assert "carbon_fiber_hm" in materials


def test_optimize_missing_config_returns_error() -> None:
    response = client.post(
        "/optimize",
        json={"config_yaml_path": "/nonexistent/path.yaml"},
    )

    assert response.status_code in {400, 422, 500}
    assert response.json()["val_weight"] == 99999


@patch("hpa_mdo.api.server._run_pipeline", side_effect=RuntimeError("forced fail"))
def test_optimize_failure_returns_val_weight_99999(_mock_run_pipeline) -> None:
    response = client.post(
        "/optimize",
        json={"config_yaml_path": "configs/blackcat_004.yaml", "aoa_deg": 3.0},
    )

    assert response.status_code == 500
    payload = response.json()
    assert payload["val_weight"] == 99999
    assert payload["error_code"] == "SOLVER_DIVERGED"


@patch("hpa_mdo.structure.optimizer.SparOptimizer.optimize")
def test_optimize_valid_config_returns_result(mock_optimize) -> None:
    mock_optimize.return_value = SimpleNamespace(
        success=True,
        message="mocked optimize",
        spar_mass_half_kg=5.93,
        spar_mass_full_kg=11.86,
        total_mass_full_kg=14.35,
        max_stress_main_Pa=3.70e8,
        max_stress_rear_Pa=5.34e8,
        allowable_stress_main_Pa=1.667e9,
        allowable_stress_rear_Pa=1.667e9,
        failure_index=-0.67,
        buckling_index=-0.85,
        tip_deflection_m=2.41,
        twist_max_deg=0.33,
        main_t_seg_mm=[1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        rear_t_seg_mm=[1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    )

    response = client.post(
        "/optimize",
        json={"config_yaml_path": "configs/blackcat_004.yaml"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["error_code"] is None
    assert payload["success"] is True
    assert "failure_index" in payload
    assert payload["total_mass_full_kg"] == 14.35
    mock_optimize.assert_called_once_with(method="scipy")


def test_export_missing_config_returns_error() -> None:
    response = client.post(
        "/export",
        json={
            "config_yaml_path": "/bad/path.yaml",
            "output_dir": "/tmp",
            "formats": ["csv"],
        },
    )

    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == "EXPORT_FAIL"
    assert "error" in payload


@patch("hpa_mdo.api.server._run_pipeline", side_effect=RuntimeError("forced fail"))
def test_analyze_failure_returns_val_weight_99999(_mock_run_pipeline) -> None:
    response = client.post(
        "/analyze",
        json={
            "config_yaml_path": "configs/blackcat_004.yaml",
            "main_t_mm": [1.0, 1.0],
            "rear_t_mm": [1.0, 1.0],
            "aoa_deg": 3.0,
        },
    )

    assert response.status_code == 500
    payload = response.json()
    assert payload["val_weight"] == 99999
    assert payload["error_code"] == "SOLVER_DIVERGED"
