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

SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006w_te_base_pairing.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006w_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _block(*, sharp_te: bool):
    if sharp_te:
        loop = [
            (1.0, 0.0),
            (0.5, 0.04),
            (0.0, 0.0),
            (0.5, -0.04),
            (1.0, 0.0),
        ]
    else:
        loop = [
            (1.0, 0.05),
            (0.0, 0.05),
            (0.0, -0.05),
            (1.0, -0.05),
        ]
    stations = [
        Station(y=-0.5, airfoil_xz=loop, chord=1.0, twist_deg=0.0),
        Station(y=0.5, airfoil_xz=loop, chord=1.0, twist_deg=0.0),
    ]
    spec = WingSpec(
        stations=stations,
        side="full",
        te_rule="sharp" if sharp_te else "finite_thickness",
        tip_rule="planar_cap",
        root_rule="full",
        reference=Reference(sref_full=1.0, cref=1.0, bref_full=1.0),
    )
    return build_wing_boundary_layer_block(
        spec,
        BoundaryLayerBlockSpec(
            first_layer_height_m=0.01,
            growth_ratio=1.2,
            layer_count=2,
            te_wake_length_m=0.2,
        ),
    )


def test_sharp_te_base_faces_are_coincident_pairing_candidates() -> None:
    module = _load_module()
    block = _block(sharp_te=True)
    core_interface = build_boundary_layer_core_interface_surface(block)

    summary = module.summarize_te_base_pairing(block, core_interface)

    assert summary["te_base_face_count"] == 2
    assert summary["coincident_pair_count"] == 1
    assert summary["unpaired_te_base_face_count"] == 0
    assert summary["receiver_base_face_count"] == 1
    assert summary["max_receiver_base_area_m2"] == 0.0
    assert summary["te_base_pairing_status"] == "sharp_te_pairing_candidate"


def test_finite_te_base_faces_are_not_silently_stitched() -> None:
    module = _load_module()
    block = _block(sharp_te=False)
    core_interface = build_boundary_layer_core_interface_surface(block)

    summary = module.summarize_te_base_pairing(block, core_interface)

    assert summary["te_base_face_count"] == 2
    assert summary["coincident_pair_count"] == 0
    assert summary["unpaired_te_base_face_count"] == 2
    assert summary["max_receiver_base_area_m2"] > 0.0
    assert summary["te_base_pairing_status"] == "te_base_geometry_open"
