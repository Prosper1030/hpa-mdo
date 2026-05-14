from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from hpa_meshing.mesh_native.near_wall_block import (
    BoundaryLayerBlockSpec,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.wing_surface import Reference, Station, WingSpec


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006r10_near_wall_core_closure.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006r10_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sharp_te_block(layer_count: int = 2):
    stations = [
        Station(
            y=-0.5,
            airfoil_xz=[
                (1.0, 0.0),
                (0.5, 0.05),
                (0.0, 0.05),
                (0.0, -0.05),
                (0.5, -0.05),
                (1.0, 0.0),
            ],
            chord=1.0,
            twist_deg=0.0,
        ),
        Station(
            y=0.5,
            airfoil_xz=[
                (1.0, 0.0),
                (0.5, 0.05),
                (0.0, 0.05),
                (0.0, -0.05),
                (0.5, -0.05),
                (1.0, 0.0),
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


def test_core_closure_gate_blocks_using_full_shell_as_core_interface() -> None:
    module = _load_module()
    block = _sharp_te_block(layer_count=2)
    candidate = module.build_near_wall_merged_volume_candidate(block)

    summary = module.summarize_near_wall_core_closure(block, candidate)
    probe = module.build_probe_summary(core_closure=summary)

    assert summary["status"] == "core_interface_closure_blocked"
    assert summary["full_boundary_topology"]["status"] == "watertight"
    assert summary["core_facing_topology"]["status"] == "not_watertight"
    assert summary["full_shell_core_interface_policy"]["status"] == "forbidden"
    assert "core_facing_surface_not_watertight" in summary["blockers"]
    assert "full_shell_contains_physical_wall_roles" in summary["blockers"]
    assert summary["can_generate_core_mesh"] is False
    assert probe["goal_status"] == "INCOMPLETE"
    assert probe["cfd_status"] == "mesh_ladder_incomplete"
    assert probe["coefficient_interpretable"] is False


def test_core_closure_probe_run_writes_artifacts(tmp_path: Path) -> None:
    module = _load_module()

    summary = module.run_probe(
        output_dir=tmp_path / "wo006r10",
        points_per_side=8,
        spanwise_subdivisions=1,
    )

    closure = summary["core_closure"]
    assert summary["verdict"] == "near_wall_core_interface_closure_blocked"
    assert closure["full_boundary_topology"]["status"] == "watertight"
    assert closure["core_facing_topology"]["bad_edge_count"] > 0
    assert closure["full_shell_core_interface_policy"]["status"] == "forbidden"
    assert "core_interface_not_materialized" in closure["blockers"]
    assert (tmp_path / "wo006r10" / "summary.json").exists()
    assert (tmp_path / "wo006r10" / "near_wall_core_closure_report.md").exists()
