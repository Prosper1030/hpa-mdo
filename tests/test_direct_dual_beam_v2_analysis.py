from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.direct_dual_beam_v2 import DirectV2Candidate  # noqa: E402
from scripts.direct_dual_beam_v2_solution_analysis import (  # noqa: E402
    build_segment_delta_rows,
    build_variable_leverage_rows,
    VariableProbeRow,
)


class _DummyMat:
    def __init__(self, density: float):
        self.density = density


class _DummyMaterials:
    def get(self, key: str):
        return _DummyMat(1000.0 if key == "main" else 500.0)


class _DummyCfg:
    class _Spar:
        def __init__(self, material: str):
            self.material = material

    def __init__(self):
        self.main_spar = self._Spar("main")
        self.rear_spar = self._Spar("rear")

    def spar_segment_lengths(self, _spar_cfg):
        return [1.5, 3.0]


def _candidate(
    *,
    z: np.ndarray,
    main_t: np.ndarray,
    main_r: np.ndarray,
    rear_t: np.ndarray,
    rear_r: np.ndarray,
    mass_kg: float,
    psi_m: float,
) -> DirectV2Candidate:
    return DirectV2Candidate(
        z=np.asarray(z, dtype=float),
        source="test",
        message="ok",
        eval_wall_time_s=0.0,
        main_plateau_scale=1.0,
        main_taper_fill=0.0,
        rear_radius_scale=1.0,
        rear_outboard_fraction=0.0,
        wall_thickness_fraction=0.0,
        main_t_seg_m=np.asarray(main_t, dtype=float),
        main_r_seg_m=np.asarray(main_r, dtype=float),
        rear_t_seg_m=np.asarray(rear_t, dtype=float),
        rear_r_seg_m=np.asarray(rear_r, dtype=float),
        tube_mass_kg=mass_kg,
        total_structural_mass_kg=mass_kg,
        raw_main_tip_m=1.0,
        raw_rear_tip_m=2.0,
        raw_max_uz_m=2.0,
        raw_max_location="rear node 60",
        psi_u_all_m=psi_m,
        psi_u_rear_m=psi_m,
        psi_u_rear_outboard_m=psi_m,
        dual_displacement_limit_m=2.5,
        equivalent_failure_index=-0.1,
        equivalent_buckling_index=-0.2,
        equivalent_tip_deflection_m=1.0,
        equivalent_twist_max_deg=0.1,
        equivalent_failure_passed=True,
        equivalent_buckling_passed=True,
        equivalent_tip_passed=True,
        equivalent_twist_passed=True,
        geometry_validity_succeeded=True,
        analysis_succeeded=True,
        overall_hard_feasible=True,
        overall_optimizer_candidate_feasible=True,
        hard_failures=(),
        candidate_failures=(),
        hard_margins={"x": 1.0},
        hard_violation_score=0.0,
        candidate_excess_m=0.0,
    )


def test_build_segment_delta_rows_sums_to_total_mass_delta() -> None:
    cfg = _DummyCfg()
    materials = _DummyMaterials()
    baseline = _candidate(
        z=np.zeros(5),
        main_t=np.array([0.001, 0.001]),
        main_r=np.array([0.030, 0.020]),
        rear_t=np.array([0.001, 0.001]),
        rear_r=np.array([0.010, 0.010]),
        mass_kg=0.0,
        psi_m=3.0,
    )
    selected = _candidate(
        z=np.zeros(5),
        main_t=np.array([0.001, 0.001]),
        main_r=np.array([0.032, 0.022]),
        rear_t=np.array([0.001, 0.0015]),
        rear_r=np.array([0.010, 0.010]),
        mass_kg=0.0,
        psi_m=2.0,
    )

    rows, totals = build_segment_delta_rows(
        baseline=baseline,
        selected=selected,
        cfg=cfg,
        materials_db=materials,
    )

    row_total = sum(row.delta_mass_kg for row in rows)
    assert len(rows) == 4
    assert row_total == totals["tube_delta_mass_kg"]
    assert totals["main_delta_mass_kg"] > 0.0
    assert totals["rear_delta_mass_kg"] > 0.0


def test_build_variable_leverage_rows_uses_plus_and_minus_two_percent_probes() -> None:
    selected = _candidate(
        z=np.array([0.67, 0.00, 0.33, 0.00, 0.00]),
        main_t=np.array([0.001, 0.001]),
        main_r=np.array([0.030, 0.020]),
        rear_t=np.array([0.001, 0.001]),
        rear_r=np.array([0.010, 0.010]),
        mass_kg=10.0,
        psi_m=2.5,
    )
    probes = (
        VariableProbeRow(
            variable="main_plateau_scale",
            delta_z=-0.02,
            new_z=(0.65, 0.0, 0.33, 0.0, 0.0),
            mass_kg=9.9,
            delta_mass_kg=-0.1,
            psi_u_all_mm=2510.0,
            delta_psi_u_all_mm=10.0,
            raw_main_tip_mm=1800.0,
            raw_rear_tip_mm=2500.0,
            hard_feasible=True,
            candidate_feasible=False,
        ),
        VariableProbeRow(
            variable="main_plateau_scale",
            delta_z=0.02,
            new_z=(0.69, 0.0, 0.33, 0.0, 0.0),
            mass_kg=10.1,
            delta_mass_kg=0.1,
            psi_u_all_mm=2490.0,
            delta_psi_u_all_mm=-10.0,
            raw_main_tip_mm=1780.0,
            raw_rear_tip_mm=2480.0,
            hard_feasible=True,
            candidate_feasible=True,
        ),
    )

    leverage = build_variable_leverage_rows(selected=selected, probe_rows=probes)
    row = next(entry for entry in leverage if entry.variable == "main_plateau_scale")

    assert row.positive_step == 0.02
    assert row.negative_step == -0.02
    assert row.positive_mm_per_kg == 100.0
    assert row.negative_candidate_feasible is False
