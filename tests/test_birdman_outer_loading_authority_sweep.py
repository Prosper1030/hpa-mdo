from pathlib import Path

import math
import pytest

import scripts.birdman_outer_loading_authority_sweep as sweep
import scripts.birdman_spanload_design_smoke as spanload_smoke
from hpa_mdo.concept.config import load_concept_config
from hpa_mdo.concept.geometry import WingStation


CONFIG_PATH = Path("configs/birdman_upstream_concept_baseline.yaml")
SAMPLE_1476_DIR = Path(
    "output/birdman_mission_coupled_medium_search_20260503/top_candidate_exports/rank_01_sample_1476"
)


def _baseline_stations() -> tuple[WingStation, ...]:
    return tuple(
        WingStation(y_m=float(y), chord_m=float(c), twist_deg=float(t), dihedral_deg=float(d))
        for y, c, t, d in (
            (0.0, 1.45, 2.0, 1.0),
            (2.778, 1.205, 1.088, 1.8),
            (6.077, 1.058, 1.223, 2.75),
            (9.029, 0.997, 1.981, 3.6),
            (12.155, 0.927, 1.981, 4.5),
            (14.239, 0.878, 1.488, 5.1),
            (15.628, 0.823, 0.884, 5.5),
            (16.496, 0.706, 0.507, 5.75),
            (17.364, 0.706, 0.355, 6.0),
        )
    )


def test_outer_smooth_bump_zeros_outside_window() -> None:
    assert sweep.outer_smooth_bump(0.0) == 0.0
    assert sweep.outer_smooth_bump(0.50) == 0.0
    assert sweep.outer_smooth_bump(sweep.OUTER_BUMP_LO_ETA) == 0.0
    assert sweep.outer_smooth_bump(sweep.OUTER_BUMP_HI_ETA) == 0.0
    assert sweep.outer_smooth_bump(1.0) == 0.0


def test_outer_smooth_bump_peaks_at_one_in_centre() -> None:
    peak = sweep.outer_smooth_bump(sweep.OUTER_BUMP_PEAK_ETA)
    assert math.isclose(peak, 1.0, rel_tol=1.0e-12)


def test_outer_smooth_bump_is_smooth_and_non_negative() -> None:
    grid = [eta / 200.0 for eta in range(0, 201)]
    values = [sweep.outer_smooth_bump(eta) for eta in grid]
    assert all(value >= 0.0 for value in values)
    max_jump = max(abs(b - a) for a, b in zip(values[:-1], values[1:]))
    assert max_jump < 0.10


def test_apply_outer_ainc_bump_only_changes_outer_twist() -> None:
    stations = _baseline_stations()
    bumped = sweep.apply_outer_ainc_bump(stations=stations, amplitude_deg=2.0)
    half_span = stations[-1].y_m
    for original, new in zip(stations, bumped, strict=True):
        eta = original.y_m / half_span
        delta = new.twist_deg - original.twist_deg
        if eta <= sweep.OUTER_BUMP_LO_ETA + 1.0e-9 or eta >= sweep.OUTER_BUMP_HI_ETA - 1.0e-9:
            assert math.isclose(delta, 0.0, abs_tol=1.0e-9)
        else:
            assert delta >= -1.0e-9
            assert delta <= 2.0 + 1.0e-9
        assert math.isclose(original.chord_m, new.chord_m, rel_tol=1.0e-12)


def test_apply_outer_chord_redistribution_preserves_total_area() -> None:
    stations = _baseline_stations()
    original_area = spanload_smoke._integrate_station_chords(stations)
    for amplitude in (0.10, 0.20, 0.30, 0.40):
        redistributed = sweep.apply_outer_chord_redistribution(
            stations=stations, amplitude=float(amplitude)
        )
        new_area = spanload_smoke._integrate_station_chords(redistributed)
        assert math.isclose(original_area, new_area, rel_tol=1.0e-9, abs_tol=1.0e-9), (
            f"amplitude={amplitude}: area changed from {original_area} to {new_area}"
        )


def test_apply_outer_chord_redistribution_grows_outer_chord() -> None:
    stations = _baseline_stations()
    redistributed = sweep.apply_outer_chord_redistribution(stations=stations, amplitude=0.30)
    half_span = stations[-1].y_m
    for original, new in zip(stations, redistributed, strict=True):
        eta = original.y_m / half_span
        if sweep.OUTER_BUMP_LO_ETA + 1.0e-3 < eta < sweep.OUTER_BUMP_HI_ETA - 1.0e-3:
            assert new.chord_m >= original.chord_m
        elif eta <= 0.5:
            # Inner stations carry the area compensation, so their chord shrinks.
            assert new.chord_m <= original.chord_m + 1.0e-9


def test_apply_outer_target_taper_pulls_a3_more_negative() -> None:
    new_a3, new_a5 = sweep.apply_outer_target_taper(
        a3_over_a1=-0.03, a5_over_a1=0.0, outer_taper_fraction=0.5
    )
    assert new_a3 < -0.03
    assert new_a3 >= -0.5
    assert new_a5 > 0.0
    assert new_a5 <= 0.5


def test_apply_outer_target_taper_zero_fraction_is_passthrough() -> None:
    new_a3, new_a5 = sweep.apply_outer_target_taper(
        a3_over_a1=-0.03, a5_over_a1=0.01, outer_taper_fraction=0.0
    )
    assert math.isclose(new_a3, -0.03, abs_tol=1.0e-12)
    assert math.isclose(new_a5, 0.01, abs_tol=1.0e-12)


def test_compute_outer_loading_diagnostic_handles_eta_window_tolerance() -> None:
    # Synthetic table with eta values that are slightly off the requested window
    # boundary, mimicking the float-precision issue from y_m / half_span_m.
    table = [
        {"eta": 0.0, "avl_circulation_norm": 1.0, "target_circulation_norm": 1.0},
        {"eta": 0.6999999, "avl_circulation_norm": 0.5, "target_circulation_norm": 0.7},
        {"eta": 0.82, "avl_circulation_norm": 0.3, "target_circulation_norm": 0.5},
        {"eta": 0.9000001, "avl_circulation_norm": 0.2, "target_circulation_norm": 0.4},
        {"eta": 0.95, "avl_circulation_norm": 0.15, "target_circulation_norm": 0.28},
    ]
    diagnostic = sweep.compute_outer_loading_diagnostic(
        station_table=table,
        stations=_baseline_stations(),
        eta_windows=[(0.70, 0.95)],
        diagnostic_etas=[0.70, 0.85, 0.95],
    )
    windows = diagnostic["outer_ratio_windows"]
    assert len(windows) == 1
    assert windows[0]["samples"] == 4
    assert windows[0]["outer_ratio_min"] is not None


def test_load_baseline_from_export_returns_consistent_geometry() -> None:
    if not SAMPLE_1476_DIR.exists():
        pytest.skip("Saved sample 1476 export is not present in this checkout.")
    cfg = load_concept_config(CONFIG_PATH)
    baseline = sweep.load_baseline_from_export(cfg=cfg, export_dir=SAMPLE_1476_DIR)
    concept = baseline["concept"]
    stations = baseline["stations"]
    assert baseline["baseline_sample_index"] == 1476
    assert math.isclose(concept.span_m, 2.0 * stations[-1].y_m, rel_tol=1.0e-3)
    assert concept.planform_parameterization == "spanload_inverse_chord"
    integrated_area = spanload_smoke._integrate_station_chords(stations)
    assert math.isclose(integrated_area, concept.wing_area_m2, rel_tol=2.0e-2)
    assert all(zone in baseline["zone_airfoil_paths"] for zone in ("root", "mid1", "mid2", "tip"))
