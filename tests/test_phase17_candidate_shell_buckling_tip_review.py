from __future__ import annotations

import math

import numpy as np

from scripts import phase17_candidate_shell_buckling_tip_review as phase17
from scripts.phase15_candidate_load_factor_buckling_check import CandidateReference
from scripts.phase17_candidate_shell_buckling_tip_review import (
    CandidateStation,
    LocalWallCouponRow,
    ShellBucklingRow,
    TipLimitReviewRow,
    build_candidate_shell_mesh,
    build_constant_tube_shell_mesh,
    parse_buckling_factors,
    parse_root_reaction,
    write_shell_buckle_inp,
    write_local_wall_coupon_buckle_inp,
    wire_force_vector_n,
    worst_main_tube_station,
)


def _reference() -> CandidateReference:
    return CandidateReference(
        candidate_id="sample",
        reference_load_factor=2.0,
        failure_index=0.25 - 1.0,
        buckling_index=0.10 - 1.0,
        tip_deflection_m=1.0,
        tip_deflection_limit_m=1.65,
        twist_max_deg=0.2,
        twist_limit_deg=2.0,
        wire_tension_n=3000.0,
        wire_allowable_n=6000.0,
        root_reaction_fz_n=-10.0,
        root_bending_moment_n_m=1000.0,
        tube_allowable_stress_pa=1.0e9,
        young_pa=200.0e9,
        jig_main_tip_z_m=0.6,
        jig_rear_tip_z_m=0.4,
        loaded_main_tip_z_m=2.7,
        loaded_rear_tip_z_m=2.5,
        jig_min_z_m=0.04,
        loaded_min_z_m=0.08,
        fem_validated_max_load_factor=2.0,
        fem_tip_error_pct=3.74,
        fem_wire_reaction_error_pct=2.09,
        fem_root_reaction_error_pct=4.60,
        structured_shell_b2_error_pct=2.41,
        structured_shell_b5_torsion_error_pct=0.07,
    )


def test_parse_buckling_factors_from_calculix_dat() -> None:
    dat = """
                        S T E P       1

     B U C K L I N G   F A C T O R   O U T P U T

 MODE NO       BUCKLING
                FACTOR

      1   0.4815456E+02
      2   0.1063175E+03
"""
    assert parse_buckling_factors(dat) == [48.15456, 106.3175]


def test_parse_root_reaction_from_static_dat() -> None:
    dat = """
 total force (fx,fy,fz) for set ROOT and time  0.1000000E+01

       -6.214976E-05 -9.647233E-07  7.999938E+01
"""
    root = parse_root_reaction(dat)
    assert root == (-6.214976e-05, -9.647233e-07, 79.99938)


def test_wire_force_vector_matches_vertical_component() -> None:
    rigging = {
        "attach_point_loaded_m": [0.25375616055950073, 7.555827721682913, 0.5394806231937227],
        "anchor_point_m": [0.25390285933987433, 0.0, -1.5],
        "tension_force_n": 3024.0856954921524,
    }
    fx, fy, fz = wire_force_vector_n(rigging)
    assert math.isclose(fx, 0.0567, abs_tol=1.0e-3)
    assert math.isclose(fy, -2919.53, rel_tol=1.0e-4)
    assert math.isclose(fz, -788.062, rel_tol=1.0e-4)


def test_candidate_shell_mesh_uses_midsurface_radius() -> None:
    stations = [
        CandidateStation(1, 0.0, 0.0, 0.0, 0.03, 0.002, 10.0, False),
        CandidateStation(2, 1.0, 0.0, 0.0, 0.02, 0.002, 5.0, False),
    ]
    nodes, elements, thickness, y_values = build_candidate_shell_mesh(
        stations,
        n_span=2,
        n_circumference=12,
    )
    assert nodes.shape == (36, 4)
    assert len(elements) == 24
    assert np.allclose(thickness, [0.002, 0.002, 0.002])
    assert np.allclose(y_values, [0.0, 0.5, 1.0])
    # First node sits at outer radius minus half wall thickness.
    assert math.isclose(nodes[0, 1], 0.029, rel_tol=1.0e-12)


def test_constant_tube_coupon_mesh_counts_and_radius() -> None:
    nodes, elements = build_constant_tube_shell_mesh(
        outer_radius_m=0.03,
        wall_thickness_m=0.002,
        length_m=1.5,
        n_span=3,
        n_circumference=12,
    )
    assert nodes.shape == (48, 4)
    assert len(elements) == 36
    assert math.isclose(nodes[0, 1], 0.029, rel_tol=1.0e-12)
    assert math.isclose(nodes[-1, 2], 1.5, rel_tol=1.0e-12)


def test_worst_main_tube_station_uses_largest_d_over_t() -> None:
    stations = [
        CandidateStation(1, 0.0, 0.0, 0.0, 0.02, 0.002, 0.0, False),
        CandidateStation(2, 1.0, 0.0, 0.0, 0.03, 0.001, 0.0, False),
    ]
    assert worst_main_tube_station(stations).node == 2


def test_buckle_deck_repeats_loads_inside_buckle_step(tmp_path) -> None:
    nodes, elements = build_constant_tube_shell_mesh(
        outer_radius_m=0.03,
        wall_thickness_m=0.002,
        length_m=0.2,
        n_span=2,
        n_circumference=12,
    )
    deck = write_local_wall_coupon_buckle_inp(
        tmp_path / "coupon.inp",
        nodes=nodes,
        elements=elements,
        material_name="MAT",
        young_pa=230.0e9,
        poisson_ratio=0.27,
        density_kgpm3=1600.0,
        wall_thickness_m=0.002,
        n_circumference=12,
        axial_force_n=100.0,
    )

    text = deck.read_text(encoding="utf-8")
    buckle_step = text.split("*STEP, NAME=local_wall_buckle", maxsplit=1)[1]
    assert "*BUCKLE" in buckle_step
    assert "*CLOAD" in buckle_step
    assert "25, 2," in buckle_step


def test_candidate_shell_deck_repeats_loads_inside_buckle_step(tmp_path) -> None:
    stations = [
        CandidateStation(1, 0.0, 0.0, 0.0, 0.03, 0.002, 10.0, False),
        CandidateStation(2, 1.0, 0.0, 0.0, 0.03, 0.002, 5.0, False),
    ]
    nodes, elements, thickness, _ = build_candidate_shell_mesh(
        stations,
        n_span=2,
        n_circumference=12,
    )
    deck = write_shell_buckle_inp(
        tmp_path / "candidate.inp",
        nodes=nodes,
        elements=elements,
        thickness_by_ring_m=thickness,
        material_name="MAT",
        young_pa=230.0e9,
        poisson_ratio=0.27,
        density_kgpm3=1600.0,
        n_span=2,
        n_circumference=12,
        loads=[(1, 3, 10.0), (13, 3, 5.0)],
    )

    text = deck.read_text(encoding="utf-8")
    buckle_step = text.split("*STEP, NAME=buckle_from_reference_2g", maxsplit=1)[1]
    assert "*BUCKLE" in buckle_step
    assert "*CLOAD" in buckle_step
    assert "1, 3, 10" in buckle_step
    assert "13, 3, 5" in buckle_step


def test_shell_buckling_report_keeps_local_wall_coupon_conditional(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(phase17, "load_current_candidate_reference", _reference)
    shell_rows = [
        ShellBucklingRow(
            mesh_id="coarse",
            n_span=60,
            n_circumference=48,
            node_count=2928,
            element_count=2880,
            reference_load_factor=2.0,
            reference_load_main_fz_n=100.0,
            reference_wire_fx_n=0.0,
            reference_wire_fy_n=-100.0,
            reference_wire_fz_n=-20.0,
            static_root_rf_x_n=0.0,
            static_root_rf_y_n=100.0,
            static_root_rf_z_n=120.0,
            first_positive_buckle_factor=0.8,
            shell_buckle_load_factor=1.6,
            utilization_at_3g=1.875,
            utilization_at_4g=2.5,
            runtime_s=1.0,
            ccx_returncode=0,
            status="GLOBAL_BRACING_FAIL_DIRECTIONAL",
            deck_path="deck.inp",
            dat_path="deck.dat",
            log_path="deck.log",
            note="global bracing unresolved",
        )
    ]
    coupon_rows = [
        LocalWallCouponRow(
            mesh_id="coupon_rib_bay_0p30m",
            length_m=0.30,
            outer_radius_m=0.03,
            wall_thickness_m=0.001,
            d_over_t=60.0,
            n_span=64,
            n_circumference=96,
            element_count=6144,
            reference_load_factor=2.0,
            reference_compressive_stress_mpa=50.0,
            reference_axial_force_n=100.0,
            first_positive_buckle_factor=2.5,
            shell_critical_stress_mpa=125.0,
            shell_buckle_load_factor=5.0,
            classical_knockdown_sigma_cr_mpa=120.0,
            classical_knockdown_buckle_load_factor=4.8,
            ccx_to_classical_critical_stress_ratio=1.04,
            ccx_vs_classical_critical_stress_delta_pct=4.0,
            internal_estimate_buckle_load_factor=20.0,
            utilization_at_3g=0.6,
            runtime_s=1.0,
            ccx_returncode=0,
            status="PASS_DIRECTIONAL",
            deck_path="coupon.inp",
            dat_path="coupon.dat",
            log_path="coupon.log",
            note="conditional coupon check",
        )
    ]
    tip_rows = [
        TipLimitReviewRow(
            raw_tip_limit_m=2.50,
            effective_tip_limit_m=2.55,
            limit_to_halfspan_ratio=0.149,
            deflection_limit_load_factor=3.3,
            active_first_limiter_with_6kn_wire="tip_deflection",
            engineering_use="current conservative submission/design gate",
        )
    ]

    phase17.write_reports(tmp_path, shell_rows, coupon_rows, tip_rows)

    report = (tmp_path / "candidate_shell_buckling_report.md").read_text(encoding="utf-8")
    assert "conditional" in report
    assert "assumed rib-bay bracing" in report
    assert "validated" not in report
