from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.direct_dual_beam_inverse_design import _refresh_iteration_converged  # noqa: E402


def test_refresh_iteration_converged_when_all_deltas_below_tolerances() -> None:
    iteration = SimpleNamespace(
        mass_delta_kg=0.02,
        lift_rms_delta_npm=0.5,
        torque_rms_delta_nmpm=0.2,
    )

    assert _refresh_iteration_converged(
        iteration,
        mass_tol_kg=0.05,
        lift_rms_tol_npm=1.0,
        torque_rms_tol_nmpm=0.5,
    )


def test_refresh_iteration_converged_rejects_missing_or_large_deltas() -> None:
    missing = SimpleNamespace(
        mass_delta_kg=None,
        lift_rms_delta_npm=0.1,
        torque_rms_delta_nmpm=0.1,
    )
    large = SimpleNamespace(
        mass_delta_kg=0.02,
        lift_rms_delta_npm=1.5,
        torque_rms_delta_nmpm=0.2,
    )

    assert not _refresh_iteration_converged(
        missing,
        mass_tol_kg=0.05,
        lift_rms_tol_npm=1.0,
        torque_rms_tol_nmpm=0.5,
    )
    assert not _refresh_iteration_converged(
        large,
        mass_tol_kg=0.05,
        lift_rms_tol_npm=1.0,
        torque_rms_tol_nmpm=0.5,
    )
