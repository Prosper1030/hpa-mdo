from pathlib import Path

import scripts.birdman_avl_e_sanity_benchmark as benchmark
from hpa_mdo.concept.config import load_concept_config


def test_benchmark_suite_defines_contract_and_current_cases() -> None:
    cfg = load_concept_config(Path("configs/birdman_upstream_concept_baseline.yaml"))

    cases = benchmark.build_benchmark_cases(cfg)

    assert [case["case_id"] for case in cases] == [
        "near_elliptic_uniform_airfoil",
        "hpa_taper_uniform_airfoil",
        "current_inverse_chord_mixed_seed_airfoils",
    ]
    assert cases[0]["expected_e_cdi_min"] == 0.95
    assert cases[1]["expected_e_cdi_min"] == 0.88
    assert cases[0]["airfoil_policy"] == "uniform_fx76mp140_contract_isolation"
    assert cases[2]["airfoil_policy"] == "mixed_seed_airfoils_current_optimizer_path"


def test_contract_gate_stops_only_when_reference_benchmarks_are_low() -> None:
    report = {
        "benchmarks": [
            {"case_id": "near_elliptic_uniform_airfoil", "avl_e_cdi": 0.96, "expected_e_cdi_min": 0.95},
            {"case_id": "hpa_taper_uniform_airfoil", "avl_e_cdi": 0.89, "expected_e_cdi_min": 0.88},
            {"case_id": "current_inverse_chord_mixed_seed_airfoils", "avl_e_cdi": 0.80, "expected_e_cdi_min": None},
        ],
    }

    status = benchmark.contract_gate_status(report)

    assert status["contract_benchmarks_pass"] is True
    assert status["halt_optimizer_until_avl_contract_fixed"] is False


def test_contract_gate_flags_low_reference_benchmark() -> None:
    report = {
        "benchmarks": [
            {"case_id": "near_elliptic_uniform_airfoil", "avl_e_cdi": 0.81, "expected_e_cdi_min": 0.95},
            {"case_id": "hpa_taper_uniform_airfoil", "avl_e_cdi": 0.90, "expected_e_cdi_min": 0.88},
        ],
    }

    status = benchmark.contract_gate_status(report)

    assert status["contract_benchmarks_pass"] is False
    assert status["halt_optimizer_until_avl_contract_fixed"] is True
    assert status["failures"][0]["case_id"] == "near_elliptic_uniform_airfoil"
