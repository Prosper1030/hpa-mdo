from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
if str(HPA_MESHING_SRC) not in sys.path:
    sys.path.insert(0, str(HPA_MESHING_SRC))

from hpa_meshing.mesh_native.near_wall_block import (  # noqa: E402
    BoundaryLayerBlockSpec,
    build_boundary_layer_core_interface_surface,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.wing_surface import Reference, Station, WingSpec  # noqa: E402


SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006v_wake_receiver_topology.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006v_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _simple_block(layer_count: int = 2):
    stations = [
        Station(
            y=-0.5,
            airfoil_xz=[
                (1.0, 0.05),
                (0.0, 0.05),
                (0.0, -0.05),
                (1.0, -0.05),
            ],
            chord=1.0,
            twist_deg=0.0,
        ),
        Station(
            y=0.5,
            airfoil_xz=[
                (1.0, 0.05),
                (0.0, 0.05),
                (0.0, -0.05),
                (1.0, -0.05),
            ],
            chord=1.0,
            twist_deg=0.0,
        ),
    ]
    spec = WingSpec(
        stations=stations,
        side="full",
        te_rule="finite_thickness",
        tip_rule="planar_cap",
        root_rule="full",
        reference=Reference(sref_full=1.0, cref=1.0, bref_full=1.0),
    )
    return build_wing_boundary_layer_block(
        spec,
        BoundaryLayerBlockSpec(
            first_layer_height_m=0.01,
            growth_ratio=1.2,
            layer_count=layer_count,
            te_wake_length_m=0.2,
        ),
    )


def test_wake_receiver_matches_layer_wake_faces_and_core_outer_wake_face() -> None:
    module = _load_module()
    block = _simple_block(layer_count=2)
    core_interface = build_boundary_layer_core_interface_surface(block)

    summary = module.summarize_wake_receiver_topology(block, core_interface)

    assert summary["receiver_cell_count"] == 2
    assert summary["bl_wake_cut_boundary_face_count"] == 6
    assert summary["matched_bl_wake_cut_face_count"] == 4
    assert summary["remaining_bl_wake_cut_face_count"] == 2
    assert summary["remaining_bl_wake_cut_wall_touching_face_count"] == 2
    assert summary["matched_core_wake_cut_face_count"] == 1
    assert summary["remaining_receiver_base_face_count"] == 1
    assert summary["wake_receiver_status"] == "partial_te_base_blocked"


def test_wake_receiver_summary_does_not_promote_partial_te_base_to_cfd() -> None:
    module = _load_module()
    block = _simple_block(layer_count=3)
    core_interface = build_boundary_layer_core_interface_surface(block)

    probe = module.build_probe_summary(
        module.summarize_wake_receiver_topology(block, core_interface)
    )

    assert probe["verdict"] == "wake_receiver_partial_te_base_blocked"
    assert probe["coefficient_interpretable"] is False
    assert probe["goal_status"] == "INCOMPLETE"
    assert probe["cfd_status"] == "mesh_ladder_incomplete"
