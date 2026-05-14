from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "diagnose_wo006j_drag_source.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("diagnose_wo006j_drag_source", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["diagnose_wo006j_drag_source"] = module
    spec.loader.exec_module(module)
    return module


def test_parse_forces_breakdown_extracts_pressure_and_friction() -> None:
    module = _load_module()

    parsed = module.parse_forces_breakdown_text(
        """
Total CL:       0.725355 | Pressure (  102%):    0.740778 | Friction (   -2%):   -0.015423 | Momentum (    0%):    0.000000
Total CD:       0.641937 | Pressure (   76%):    0.492328 | Friction (   23%):    0.149609 | Momentum (    0%):    0.000000
Surface name: wing_wall
Total CD    (  100%):    0.641937 | Pressure (   76%):    0.492328 | Friction (   23%):    0.149609 | Momentum (    0%):    0.000000
"""
    )

    assert parsed["cd"]["total"] == pytest.approx(0.641937)
    assert parsed["cd"]["pressure"] == pytest.approx(0.492328)
    assert parsed["cd"]["friction"] == pytest.approx(0.149609)
    assert parsed["surface_coefficients"]["wing_wall"]["cd"]["pressure"] == pytest.approx(0.492328)


def test_pressure_integration_matches_single_forward_facing_plate(tmp_path: Path) -> None:
    module = _load_module()
    mesh_path = tmp_path / "mesh.su2"
    surface_path = tmp_path / "surface.csv"
    mesh_path.write_text(
        "\n".join(
            [
                "NDIME= 3",
                "NELEM= 0",
                "NPOIN= 4",
                "0.0 0.0 0.0 0",
                "0.0 1.0 0.0 1",
                "0.0 1.0 1.0 2",
                "0.0 0.0 1.0 3",
                "NMARK= 1",
                "MARKER_TAG= wing_wall",
                "MARKER_ELEMS= 2",
                "5 0 1 2",
                "5 0 2 3",
                "",
            ]
        )
    )
    surface_path.write_text(
        "\n".join(
            [
                '"PointID","x","y","z","Pressure"',
                "0,0.0,0.0,0.0,10.0",
                "1,0.0,1.0,0.0,10.0",
                "2,0.0,1.0,1.0,10.0",
                "3,0.0,0.0,1.0,10.0",
                "",
            ]
        )
    )

    mesh = module.read_su2_wall_triangles(mesh_path, marker="wing_wall")
    result = module.integrate_pressure_source(
        mesh=mesh,
        surface_csv_path=surface_path,
        ref_force=10.0,
        ref_area=1.0,
    )

    assert result["integrated_pressure_coefficients_from_surface_csv"]["cd"] == pytest.approx(-1.0)
    assert result["pressure_cd_by_normal_role"]["x_forward_or_aft_facing"] == pytest.approx(-1.0)
    assert result["geometry_surface_metrics"]["abs_projected_area_x_m2"] == pytest.approx(1.0)
    assert result["geometry_surface_metrics"][
        "closed_surface_one_sided_x_projected_area_estimate_m2"
    ] == pytest.approx(0.5)
