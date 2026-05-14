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


SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006y_span_cap_ownership.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006y_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _finite_te_block():
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
            layer_count=2,
            te_wake_length_m=0.2,
        ),
    )


def test_span_cap_probe_classifies_unmatched_tip_cap_faces() -> None:
    module = _load_module()
    block = _finite_te_block()
    core_interface = build_boundary_layer_core_interface_surface(block)

    summary = module.summarize_span_cap_ownership(block, core_interface)

    assert summary["bl_span_cap_face_count"] == 20
    assert summary["core_span_cap_face_count"] == 8
    assert summary["native_matched_span_cap_face_count"] == 0
    assert summary["wall_touching_span_cap_face_count"] == 6
    assert summary["outer_interface_touching_span_cap_face_count"] == 10
    assert summary["wake_touching_span_cap_face_count"] == 8
    assert summary["span_cap_status"] == "span_cap_ownership_blocked"


def test_span_cap_probe_does_not_promote_coefficients() -> None:
    module = _load_module()
    block = _finite_te_block()
    core_interface = build_boundary_layer_core_interface_surface(block)

    probe = module.build_probe_summary(
        module.summarize_span_cap_ownership(block, core_interface)
    )

    assert probe["verdict"] == "span_cap_ownership_blocked"
    assert probe["coefficient_interpretable"] is False
    assert probe["goal_status"] == "INCOMPLETE"
    assert probe["cfd_status"] == "mesh_ladder_incomplete"
