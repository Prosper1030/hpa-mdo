from pathlib import Path

from hpa_meshing.schema import MeshJobConfig
from hpa_meshing.fallback.policy import run_with_fallback_stub


def test_fallback_stub_runs():
    cfg = MeshJobConfig(
        component="fairing_solid",
        geometry=Path("demo.step"),
        out_dir=Path("out/demo"),
    )
    res = run_with_fallback_stub({"name": "demo"}, cfg)
    assert res["status"] == "success"
