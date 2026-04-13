from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.pareto_front_phase9c import (  # noqa: E402
    ParetoDesignPoint,
    build_pareto_frontier,
    dominates,
    select_representatives,
)


def _point(
    *,
    layout: str,
    wire_count: int,
    mult: float,
    mass: float,
    ld: float,
    damping: float,
) -> ParetoDesignPoint:
    return ParetoDesignPoint(
        source_name="test",
        layout=layout,
        wire_count=wire_count,
        dihedral_multiplier=mult,
        total_mass_kg=mass,
        ld_ratio=ld,
        dutch_roll_damping=damping,
        aoa_trim_deg=11.0,
        min_jig_clearance_mm=1.0,
        wire_margin_n=1000.0,
        equivalent_tip_deflection_m=1.0,
        cd_total_est=0.03,
        corrected_for_wire_drag=False,
        source_summary_path="test.csv",
        summary_json_path=None,
    )


def test_dominates_requires_one_strictly_better_dimension() -> None:
    lhs = _point(layout="single", wire_count=1, mult=4.0, mass=12.0, ld=40.0, damping=5.8)
    rhs = _point(layout="dual", wire_count=2, mult=4.0, mass=13.0, ld=39.0, damping=5.7)

    assert dominates(lhs, rhs)
    assert not dominates(rhs, lhs)


def test_build_pareto_frontier_filters_dominated_points() -> None:
    frontier = build_pareto_frontier(
        (
            _point(layout="single", wire_count=1, mult=4.0, mass=12.0, ld=40.0, damping=5.8),
            _point(layout="single", wire_count=1, mult=5.0, mass=12.0, ld=39.0, damping=5.7),
            _point(layout="dual", wire_count=2, mult=1.0, mass=20.0, ld=37.0, damping=5.95),
        )
    )

    assert [point.label for point in frontier] == ["single x4.000", "dual x1.000"]


def test_select_representatives_picks_expected_roles() -> None:
    frontier = (
        _point(layout="single", wire_count=1, mult=4.0, mass=12.0, ld=40.0, damping=5.80),
        _point(layout="single", wire_count=1, mult=2.0, mass=16.0, ld=40.6, damping=5.90),
        _point(layout="single", wire_count=1, mult=1.0, mass=24.0, ld=41.0, damping=5.95),
    )

    reps = select_representatives(frontier)

    assert reps.mass_first.label == "single x4.000"
    assert reps.aero_first.label == "single x1.000"
    assert reps.stability_first.label == "single x1.000"
    assert reps.balanced.label == "single x2.000"
