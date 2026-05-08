from __future__ import annotations

import math

import numpy as np

from scripts.phase17_candidate_shell_buckling_tip_review import (
    CandidateStation,
    build_candidate_shell_mesh,
    build_constant_tube_shell_mesh,
    parse_buckling_factors,
    parse_root_reaction,
    wire_force_vector_n,
    worst_main_tube_station,
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
