from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "probe_wo006ab_bl_core_topology_accounting_gate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006ab_probe", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_accounting_summary_ready_still_blocks_final_handoff_and_cfd() -> None:
    module = _load_module()

    summary = module.build_probe_summary(
        topology_accounting={
            "status": "topology_accounting_ready_geometry_mesh_pending",
            "wall_surface_status": "watertight",
            "wake_accounting_pass": True,
            "tip_receiver_accounting_pass": True,
            "outer_interface_accounting_pass": True,
            "blockers": ["final_merged_mesh_missing"],
        }
    )

    assert summary["verdict"] == "topology_accounting_ready_not_handoff"
    assert summary["goal_status"] == "INCOMPLETE"
    assert summary["cfd_status"] == "mesh_ladder_incomplete"
    assert summary["coefficient_interpretable"] is False
    assert "medium/fine CFD ladder readiness" in summary["blocked_claims"]


def test_accounting_gate_run_writes_combined_topology_artifacts(tmp_path: Path) -> None:
    module = _load_module()

    summary = module.run_probe(
        output_dir=tmp_path / "wo006ab",
        points_per_side=8,
        spanwise_subdivisions=1,
    )

    assert summary["verdict"] == "topology_accounting_ready_not_handoff"
    accounting = summary["topology_accounting"]
    assert accounting["wall_surface_status"] == "watertight"
    assert accounting["wake_accounting_pass"] is True
    assert accounting["tip_receiver_accounting_pass"] is True
    assert accounting["outer_interface_accounting_pass"] is True
    assert "final_merged_mesh_missing" in accounting["blockers"]
    assert (tmp_path / "wo006ab" / "summary.json").exists()
    assert (tmp_path / "wo006ab" / "topology_accounting_report.md").exists()
