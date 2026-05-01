from pathlib import Path

import pytest

from hpa_meshing.mesh_native.blackcat import load_blackcat_main_wing_spec_from_vsp
from hpa_meshing.mesh_native.near_wall_block import (
    BoundaryLayerBlockSpec,
    build_airfoil_boundary_layer_block,
    build_wing_boundary_layer_block,
    split_airfoil_wall_loop,
)
from hpa_meshing.mesh_native.wing_surface import Station


REPO_ROOT = Path(__file__).resolve().parents[2]
AVL_PATH = REPO_ROOT / "data" / "blackcat_004_full.avl"
VSP_PATH = REPO_ROOT / "data" / "blackcat_004_origin.vsp3"


def _finite_te_station() -> Station:
    return Station(
        y=0.0,
        airfoil_xz=[
            (1.0, 0.05),
            (0.0, 0.05),
            (0.0, -0.05),
            (1.0, -0.05),
        ],
        chord=1.0,
        twist_deg=0.0,
    )


def test_split_airfoil_wall_loop_restores_vsp_sharp_te_lower_terminal():
    pytest.importorskip("openvsp")
    spec = load_blackcat_main_wing_spec_from_vsp(
        VSP_PATH,
        reference_avl_path=AVL_PATH,
        points_per_side=12,
    )
    root_station = min(spec.stations, key=lambda station: abs(station.y))

    split = split_airfoil_wall_loop(root_station.airfoil_xz)

    assert split.leading_edge_index == 11
    assert split.upper_path[0] == pytest.approx((1.0, 0.0))
    assert split.upper_path[-1] == pytest.approx((0.0, 0.0))
    assert split.lower_path[0] == pytest.approx((0.0, 0.0))
    assert split.lower_path[-1] == pytest.approx((1.0, 0.0))
    assert split.added_lower_trailing_edge is True


def test_vsp_main_wing_airfoil_bl_block_has_positive_cells_and_owned_te_connector():
    pytest.importorskip("openvsp")
    spec = load_blackcat_main_wing_spec_from_vsp(
        VSP_PATH,
        reference_avl_path=AVL_PATH,
        points_per_side=12,
    )
    root_station = min(spec.stations, key=lambda station: abs(station.y))

    block = build_airfoil_boundary_layer_block(
        root_station,
        BoundaryLayerBlockSpec(
            first_layer_height_m=5.0e-5,
            growth_ratio=1.18,
            layer_count=16,
        ),
    )

    assert block.marker_counts()["boundary_layer"] == 352
    assert block.marker_counts()["trailing_edge_connector"] == 32
    assert block.metadata["te_cap_extrusion_cells"] == 0
    assert block.metadata["added_lower_trailing_edge"] is True
    assert block.metadata["first_layer_height_m"] == pytest.approx(5.0e-5)
    assert block.quality["non_positive_area_count"] == 0
    assert block.quality["min_area_m2"] > 0.0
    assert block.quality["min_first_layer_height_m"] == pytest.approx(5.0e-5, rel=0.05)


def test_finite_te_airfoil_bl_block_preserves_distinct_te_wall_nodes():
    block = build_airfoil_boundary_layer_block(
        _finite_te_station(),
        BoundaryLayerBlockSpec(
            first_layer_height_m=1.0e-3,
            growth_ratio=1.2,
            layer_count=8,
        ),
    )

    assert block.metadata["added_lower_trailing_edge"] is False
    assert block.metadata["sharp_trailing_edge"] is False
    assert block.metadata["te_cap_extrusion_cells"] == 0
    assert block.marker_counts()["trailing_edge_connector"] == 16
    assert block.quality["non_positive_area_count"] == 0
    assert block.wall_nodes.upper_te != block.wall_nodes.lower_te


def test_vsp_main_wing_bl_block_connects_spanwise_stations_with_positive_volumes():
    pytest.importorskip("openvsp")
    spec = load_blackcat_main_wing_spec_from_vsp(
        VSP_PATH,
        reference_avl_path=AVL_PATH,
        points_per_side=12,
    )

    block = build_wing_boundary_layer_block(
        spec,
        BoundaryLayerBlockSpec(
            first_layer_height_m=5.0e-5,
            growth_ratio=1.18,
            layer_count=8,
        ),
    )

    assert block.metadata["station_count"] == 11
    assert block.metadata["section_cell_count"] == 192
    assert len(block.cells) == 1920
    assert block.marker_counts()["boundary_layer"] == 1760
    assert block.marker_counts()["trailing_edge_connector"] == 160
    assert block.boundary_marker_counts()["wing_wall"] == 220
    assert block.boundary_marker_counts()["bl_outer_interface"] == 240
    assert block.boundary_marker_counts()["wake_cut"] == 180
    assert block.boundary_marker_counts()["span_cap"] == 384
    assert block.quality["unowned_boundary_face_count"] == 0
    assert block.quality["non_positive_volume_count"] == 0
    assert block.quality["min_estimated_volume_m3"] > 0.0
    assert block.quality["min_span_interval_m"] > 0.0
