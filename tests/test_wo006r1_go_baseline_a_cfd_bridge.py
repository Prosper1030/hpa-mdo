from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_wo006r1_go_baseline_a_cfd_bridge.py"


def _load_bridge_module():
    spec = importlib.util.spec_from_file_location("wo006r1_bridge", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_current_go_geometry_builds_mesh_native_spec_with_authority_basis():
    bridge = _load_bridge_module()
    geometry = bridge.load_current_go_geometry()

    assert geometry.case_name == "current_avl_compromise_conservative_closed"
    assert geometry.design_gross_mass_kg == 98.5
    assert geometry.full_span_m == 34.332286
    assert geometry.half_span_m == 17.166143
    assert geometry.reference.sref_full == 33.420059598
    assert geometry.base_half_station_count == 9
    assert geometry.spec.metadata["spanwise_subdivisions"] == 3
    assert geometry.spec.metadata["full_station_count"] == 49

    wing = bridge.build_current_go_wing_surface(geometry)

    assert wing.marker_counts()["wing_wall"] > 0
    assert wing.metadata["span_m"] == 34.332286
    assert wing.metadata["planform_area_m2"] == geometry.reference.sref_full


def test_route_decision_prefers_mesh_native_and_classifies_old_route():
    bridge = _load_bridge_module()
    geometry = bridge.load_current_go_geometry()
    decision = bridge.choose_route(geometry)

    assert decision["selected_route"] == "mesh_native_current_go_section_table"
    assert decision["rejected_primary_route"] == "current_vsp3_esp_rebuilt_step_brep_gmsh"
    assert decision["legacy_route_status"] == "blocked_reference_only"
    assert decision["mesh_native_reason"] == "current_go_section_table_and_airfoil_dat_available"
    assert decision["authority_basis"]["design_gross_mass_kg"] == 98.5
    assert decision["authority_basis"]["pipeline_full_span_m"] == 34.332286
