"""Tests for discrete OD catalog snap utility."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hpa_mdo.utils.discrete_od import load_tube_catalog, snap_to_catalog


CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "tube_catalog.yaml"


def test_catalog_loads() -> None:
    catalog = load_tube_catalog(CATALOG_PATH)
    assert len(catalog) > 0
    assert all(isinstance(od, float) for od in catalog)
    assert catalog == sorted(catalog), "catalog must be sorted ascending"
    assert catalog[0] > 0.0


def test_snap_rounds_up_exact() -> None:
    catalog = [0.020, 0.025, 0.030, 0.035, 0.040]
    assert snap_to_catalog(0.025, catalog) == pytest.approx(0.025)


def test_snap_rounds_up_between() -> None:
    catalog = [0.020, 0.025, 0.030, 0.035, 0.040]
    result = snap_to_catalog(0.027, catalog)
    assert result == pytest.approx(0.030), f"Expected 0.030, got {result}"


def test_snap_never_rounds_down() -> None:
    catalog = [0.020, 0.025, 0.030, 0.035, 0.040]
    od_values = np.linspace(0.020, 0.040, 200)
    for od in od_values:
        snapped = snap_to_catalog(float(od), catalog)
        assert snapped >= od - 1e-9, (
            f"snap_to_catalog({od:.6f}) returned {snapped:.6f} which is smaller"
        )


def test_snap_clamps_at_max() -> None:
    catalog = [0.020, 0.025, 0.030]
    result = snap_to_catalog(0.050, catalog)
    assert result == pytest.approx(0.030)


def test_snap_with_real_catalog() -> None:
    """Verify no rounding-down occurs for any value between catalog extremes."""
    catalog = load_tube_catalog(CATALOG_PATH)
    test_ods = np.linspace(catalog[0], catalog[-1], 1000)
    for od in test_ods:
        snapped = snap_to_catalog(float(od), catalog)
        assert snapped >= od - 1e-9, (
            f"snap_to_catalog({od * 1000:.3f}mm) -> {snapped * 1000:.3f}mm is smaller"
        )
