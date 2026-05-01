from __future__ import annotations

import pytest

from hpa_mdo.concept.benchmarks import load_hpa_reference_benchmarks


def test_loads_daedalus_and_light_eagle_reference_benchmarks() -> None:
    benchmarks = load_hpa_reference_benchmarks()

    daedalus = benchmarks["daedalus_88"]
    assert daedalus["geometry"]["span_m"]["value"] == pytest.approx(34.0)
    assert daedalus["geometry"]["wing_area_m2"]["value"] == pytest.approx(31.0)
    assert daedalus["derived"]["aspect_ratio"] == pytest.approx(34.0**2 / 31.0)
    assert daedalus["derived"]["wing_loading_Npm2"] == pytest.approx(
        105.4 * 9.80665 / 31.0
    )
    assert daedalus["benchmark_use"] == "mission_context_reference_only"
    assert "calibration_targets" not in daedalus
    assert daedalus["reference_comparison_bands"]["pilot_power_w"]["advisory_relative_error"] <= 0.15
    assert "fail_relative_error" not in daedalus["reference_comparison_bands"]["pilot_power_w"]
    assert any("mit.edu" in source["url"] for source in daedalus["sources"])

    light_eagle = benchmarks["light_eagle"]
    assert light_eagle["benchmark_use"] == "mission_context_reference_only"
    assert "calibration_targets" not in light_eagle
    assert light_eagle["geometry"]["aspect_ratio"]["value"] == pytest.approx(39.4)
    assert light_eagle["mission"]["design_airspeed_mps"]["value"] == pytest.approx(7.8)
    assert any("nasa.gov" in source["url"] for source in light_eagle["sources"])
