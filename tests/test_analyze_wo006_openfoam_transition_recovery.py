from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/analyze_wo006_openfoam_transition_recovery.py"
SPEC = importlib.util.spec_from_file_location("wo006_openfoam_transition_recovery", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def scalar_field(values: list[str], boundary_value: str = "0") -> str:
    body = "\n".join(values)
    return f"""FoamFile
{{
    class volScalarField;
}}
internalField nonuniform List<scalar>
{len(values)}
(
{body}
)
;
boundaryField
{{
    wall
    {{
        type fixedValue;
        value uniform {boundary_value};
    }}
}}
"""


def test_scalar_field_summary_is_strict_and_reports_gamma_bins(tmp_path: Path) -> None:
    field = tmp_path / "gammaInt"
    field.write_text(scalar_field(["0.05", "0.5", "0.95"]))
    row = module.summarize_field(field, "gammaInt", expected_cells=3)
    assert row["finite"] is True
    assert row["count_ok"] is True
    assert row["min"] == pytest.approx(0.05)
    assert row["mean"] == pytest.approx(0.5)
    assert row["max"] == pytest.approx(0.95)
    assert row["pct_lt_0p1"] == pytest.approx(100 / 3)
    assert row["pct_0p1_to_0p9"] == pytest.approx(100 / 3)
    assert row["pct_gt_0p9"] == pytest.approx(100 / 3)


def test_field_summary_detects_nonfinite_boundary_token(tmp_path: Path) -> None:
    field = tmp_path / "k"
    field.write_text(scalar_field(["0.1", "0.2"], boundary_value="nan"))
    row = module.summarize_field(field, "k", expected_cells=2)
    assert row["nonfinite_tokens"] == 1
    assert row["finite"] is False


def test_vector_field_summary_reports_magnitude_and_components(tmp_path: Path) -> None:
    field = tmp_path / "U"
    field.write_text(
        """internalField nonuniform List<vector>
2
(
(3 4 0)
(0 0 2)
)
;
boundaryField {}
"""
    )
    row = module.summarize_field(field, "U", expected_cells=2)
    assert row["finite"] is True
    assert row["min"] == pytest.approx(2.0)
    assert row["max"] == pytest.approx(5.0)
    assert row["x_min"] == pytest.approx(0.0)
    assert row["x_max"] == pytest.approx(3.0)


def test_force_gate_requires_latest_checkpoint_and_reports_component_slopes() -> None:
    rows = []
    for index in range(100):
        rows.append(
            {
                "time": 2001.0 + index,
                "CD_total": 0.03,
                "CD_pressure": 0.022 + index * 1e-6,
                "CD_viscous": 0.008 - index * 1e-6,
                "CL": 1.16,
                "CmPitch": -0.13,
            }
        )
    gate = module.force_gate(rows, latest_time=2100.0)
    assert gate["formal_gate_pass"] is True
    assert gate["CD_pressure_linear_slope_per_iteration"] == pytest.approx(1e-6)
    assert gate["CD_viscous_linear_slope_per_iteration"] == pytest.approx(-1e-6)
    assert math.isclose(gate["max_abs_CD_component_closure_error"], 0.0, abs_tol=1e-12)

    gate = module.force_gate(rows, latest_time=2101.0)
    assert gate["formal_gate_pass"] is False


def test_solver_log_summary_separates_finite_completion_from_bounding(tmp_path: Path) -> None:
    log = tmp_path / "log.simpleFoam_sst_2000_to_2050.txt"
    log.write_text(
        """Time = 2001
smoothSolver:  Solving for Ux, Initial residual = 0.002, Final residual = 1e-05, No Iterations 2
time step continuity errors : sum local = 4e-07, global = -2e-07, cumulative = -0.0045
bounding omega, min: -3 max: 4 average: 1
bounding k, min: -0.1 max: 0.2 average: 0.01
End
"""
    )
    row = module.summarize_solver_log(log)
    assert row["ended_normally"] is True
    assert row["numeric_values_finite"] is True
    assert row["nonfinite_tokens"] == 0
    assert row["initial_residual_max"] == pytest.approx(0.002)
    assert row["continuity_global_max_abs"] == pytest.approx(2e-7)
    assert row["omega_bounding_count"] == 1
    assert row["k_bounding_count"] == 1


def test_yplus_summary_requires_face_counts_and_reports_percentages(tmp_path: Path) -> None:
    patches = {}
    blocks = []
    for index, name in enumerate(module.YPLUS_PATCHES):
        patches[name] = module.mesh_tools.PatchInfo(name, "wall", 4, index * 4)
        blocks.append(
            f"""{name}
{{
    type calculated;
    value nonuniform List<scalar>
4
(
0.5
1
4
25
)
;
}}
"""
        )
    field = tmp_path / "yPlus"
    field.write_text("boundaryField\n{\n" + "".join(blocks) + "}\n")
    rows = module.yplus_rows(field, patches, "wall_function_default")
    assert len(rows) == len(module.YPLUS_PATCHES)
    assert all(row["finite"] for row in rows)
    assert all(row["faces"] == row["expected_faces"] == 4 for row in rows)
    assert rows[0]["pct_lt_1"] == pytest.approx(25.0)
    assert rows[0]["pct_lt_5"] == pytest.approx(75.0)
    assert rows[0]["pct_gt_20"] == pytest.approx(25.0)
