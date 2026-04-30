from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from hpa_meshing.adapters.gmsh_backend import apply_recipe
from hpa_meshing.adapters.su2_backend import (
    materialize_baseline_case,
    parse_history,
    parse_solver_log_quality_metrics,
    run_baseline_case,
)
from hpa_meshing.mesh.recipes import build_recipe
from hpa_meshing.pipeline import run_job
from hpa_meshing.schema import (
    GeometryClassification,
    GeometryHandle,
    GeometryProviderResult,
    GeometryTopologyMetadata,
    MeshHandoff,
    MeshJobConfig,
    SU2RuntimeConfig,
)


def _write_occ_box_step(tmp_path: Path, name: str = "box.step") -> Path:
    gmsh_bin = shutil.which("gmsh")
    if gmsh_bin is None:
        pytest.skip("gmsh CLI not available")

    tmp_path.mkdir(parents=True, exist_ok=True)
    geo_path = tmp_path / "box.geo"
    step_path = tmp_path / name
    geo_path.write_text(
        'SetFactory("OpenCASCADE");\n'
        "Box(1) = {0, 0, 0, 1, 0.2, 0.1};\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [gmsh_bin, str(geo_path), "-0", "-o", str(step_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return step_path


def _provider_result(source: Path, normalized: Path) -> GeometryProviderResult:
    return GeometryProviderResult(
        provider="openvsp_surface_intersection",
        provider_stage="v1",
        status="materialized",
        geometry_source="provider_generated",
        source_path=source,
        normalized_geometry_path=normalized,
        geometry_family_hint="thin_sheet_aircraft_assembly",
        topology=GeometryTopologyMetadata(
            representation="brep_trimmed_step",
            source_kind="stp",
            units="m",
            body_count=1,
            surface_count=6,
            volume_count=1,
            labels_present=True,
            label_schema="preserve_component_labels",
        ),
        provenance={
            "analysis": "SurfaceIntersection",
            "reference_geometry": {
                "ref_area": 35.175,
                "ref_length": 1.0425,
                "ref_origin_moment": {"x": 4.15, "y": 0.0, "z": 0.12},
                "area_method": "openvsp_reference_wing.sref",
                "length_method": "openvsp_reference_wing.cref",
                "moment_method": "openvsp_vspaero_settings.cg",
                "reference_wing_name": "Main Wing",
                "reference_wing_id": "IPAWXFWPQF",
                "settings": {
                    "sref": 35.175,
                    "bref": 33.0,
                    "cref": 1.0425,
                    "xcg": 4.15,
                    "ycg": 0.0,
                    "zcg": 0.12,
                    "ref_flag": 1.0,
                    "mac_flag": 0.0,
                },
                "wing_quantities": {
                    "sref": 35.175,
                    "bref": 33.0,
                    "cref": 1.0425,
                },
                "warnings": [],
            },
        },
    )


def _build_mesh_handoff(tmp_path: Path) -> MeshHandoff:
    normalized = _write_occ_box_step(tmp_path)
    source = tmp_path / "demo.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    provider_result = _provider_result(source, normalized)
    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=source,
        out_dir=tmp_path / "out",
        geometry_source="provider_generated",
        geometry_family="thin_sheet_aircraft_assembly",
        geometry_provider="openvsp_surface_intersection",
        global_min_size=0.5,
        global_max_size=2.0,
    )
    handle = GeometryHandle(
        source_path=source,
        path=normalized,
        exists=True,
        suffix=normalized.suffix.lower(),
        loader="provider:openvsp_surface_intersection",
        geometry_source="provider_generated",
        declared_family="thin_sheet_aircraft_assembly",
        component="aircraft_assembly",
        provider="openvsp_surface_intersection",
        provider_status="materialized",
        provider_result=provider_result,
    )
    classification = GeometryClassification(
        geometry_source="provider_generated",
        geometry_provider="openvsp_surface_intersection",
        declared_family="thin_sheet_aircraft_assembly",
        inferred_family=None,
        geometry_family="thin_sheet_aircraft_assembly",
        provenance="test",
        notes=[],
    )
    recipe = build_recipe(handle, classification, config)
    result = apply_recipe(recipe, handle, config)
    assert result["status"] == "success"
    return MeshHandoff.model_validate(result["mesh_handoff"])


def _build_fairing_solid_mesh_handoff(tmp_path: Path) -> MeshHandoff:
    geometry = _write_occ_box_step(tmp_path, "fairing_solid_box.step")
    config = MeshJobConfig(
        component="fairing_solid",
        geometry=geometry,
        out_dir=tmp_path / "fairing_out",
        geometry_source="direct_cad",
        global_min_size=0.5,
        global_max_size=2.0,
    )
    result = run_job(config)
    assert result["status"] == "success"
    assert result["mesh"]["marker_summary"]["fairing_solid"]["exists"] is True
    return MeshHandoff.model_validate(result["run"]["backend_result"]["mesh_handoff"])


def _build_main_wing_mesh_handoff(tmp_path: Path) -> MeshHandoff:
    geometry = _write_occ_box_step(tmp_path, "main_wing_slab.step")
    config = MeshJobConfig(
        component="main_wing",
        geometry=geometry,
        out_dir=tmp_path / "main_wing_out",
        geometry_source="direct_cad",
        geometry_family="thin_sheet_lifting_surface",
        meshing_route="gmsh_thin_sheet_surface",
        mesh_dim=3,
        global_min_size=0.8,
        global_max_size=2.0,
        metadata={
            "reference_geometry": {
                "ref_area": 0.2,
                "ref_length": 1.0,
                "ref_origin_moment": {"x": 0.5, "y": 0.1, "z": 0.05},
                "area_method": "synthetic_main_wing_slab.area",
                "length_method": "synthetic_main_wing_slab.chord",
                "moment_method": "synthetic_main_wing_slab.centroid",
                "warnings": [],
            },
        },
    )
    result = run_job(config)
    assert result["status"] == "success"
    assert result["mesh"]["marker_summary"]["main_wing"]["exists"] is True
    return MeshHandoff.model_validate(result["run"]["backend_result"]["mesh_handoff"])


def test_materialize_baseline_case_writes_su2_handoff_and_runtime_cfg(tmp_path: Path):
    mesh_handoff = _build_mesh_handoff(tmp_path)
    runtime = SU2RuntimeConfig(enabled=True, max_iterations=12)

    case = materialize_baseline_case(
        mesh_handoff,
        runtime,
        tmp_path / "su2_case",
        source_root=Path.cwd(),
    )

    assert case.contract == "su2_handoff.v1"
    assert case.input_mesh_artifact.name == "mesh.msh"
    assert case.mesh_markers["wall"] == "aircraft"
    assert case.mesh_markers["farfield"] == "farfield"
    assert case.case_output_paths.su2_mesh.exists()
    assert case.runtime_cfg_path.exists()
    assert case.case_output_paths.contract_path.exists()
    assert case.reference_geometry.gate_status == "pass"
    assert case.reference_geometry.area_provenance.source_category == "geometry_derived"
    assert case.reference_geometry.length_provenance.method == "openvsp_reference_wing.cref"
    assert case.reference_geometry.ref_origin_moment.x == pytest.approx(4.15)
    assert case.force_surface_provenance.scope == "whole_aircraft_wall"
    assert case.force_surface_provenance.matches_entire_aircraft_wall is True
    assert case.force_surface_provenance.component_provenance == "geometry_labels_present_but_not_mapped"
    assert case.provenance_gates.overall_status == "pass"

    runtime_cfg = case.runtime_cfg_path.read_text(encoding="utf-8")
    assert "MESH_FILENAME= mesh.su2" in runtime_cfg
    assert "MARKER_EULER= ( aircraft )" in runtime_cfg
    assert "MARKER_MONITORING= ( aircraft )" in runtime_cfg
    assert "MARKER_PLOTTING= ( aircraft )" in runtime_cfg
    assert "MARKER_FAR= ( farfield )" in runtime_cfg
    assert "AOA= 0.000000" in runtime_cfg
    assert "INC_DENSITY_INIT= 1.225000" in runtime_cfg
    assert "INC_VELOCITY_INIT= ( 6.500000, 0.000000, 0.000000 )" in runtime_cfg
    assert "INC_TEMPERATURE_INIT= 288.150000" in runtime_cfg
    assert "MU_CONSTANT= 1.789400e-05" in runtime_cfg
    assert "REF_AREA=" in runtime_cfg
    assert "REF_LENGTH=" in runtime_cfg
    assert "WRT_FORCES_BREAKDOWN= YES" not in runtime_cfg
    assert "BREAKDOWN_FILENAME= forces_breakdown.dat" not in runtime_cfg

    payload = json.loads(case.case_output_paths.contract_path.read_text(encoding="utf-8"))
    assert payload["contract"] == "su2_handoff.v1"
    assert payload["run_status"] == "not_started"
    assert payload["reference_geometry"]["gate_status"] == "pass"
    assert payload["force_surface_provenance"]["scope"] == "whole_aircraft_wall"
    assert payload["provenance_gates"]["overall_status"] == "pass"


def test_materialize_baseline_case_can_request_forces_breakdown_output(
    tmp_path: Path,
):
    mesh_handoff = _build_mesh_handoff(tmp_path)
    runtime = SU2RuntimeConfig(
        enabled=True,
        max_iterations=12,
        write_forces_breakdown=True,
    )

    case = materialize_baseline_case(
        mesh_handoff,
        runtime,
        tmp_path / "su2_case",
        source_root=Path.cwd(),
    )

    runtime_cfg = case.runtime_cfg_path.read_text(encoding="utf-8")
    assert "BREAKDOWN_FILENAME= forces_breakdown.dat" in runtime_cfg
    assert "WRT_FORCES_BREAKDOWN= YES" in runtime_cfg
    assert case.case_output_paths.forces_breakdown_output == (
        case.case_output_paths.case_dir / "forces_breakdown.dat"
    )
    payload = json.loads(case.case_output_paths.contract_path.read_text(encoding="utf-8"))
    assert payload["runtime"]["write_forces_breakdown"] is True
    assert payload["case_output_paths"]["forces_breakdown_output"].endswith(
        "forces_breakdown.dat"
    )


def test_materialize_baseline_case_consumes_fairing_solid_marker_without_running_su2(tmp_path: Path):
    mesh_handoff = _build_fairing_solid_mesh_handoff(tmp_path)
    runtime = SU2RuntimeConfig(
        enabled=True,
        max_iterations=12,
        reference_mode="user_declared",
        reference_override={
            "ref_area": 0.24,
            "ref_length": 1.0,
            "ref_origin_moment": {"x": 0.5, "y": 0.12, "z": 0.09},
            "source_label": "synthetic_fairing_box_reference",
        },
    )

    case = materialize_baseline_case(
        mesh_handoff,
        runtime,
        tmp_path / "fairing_su2_case",
        source_root=Path.cwd(),
    )

    assert case.contract == "su2_handoff.v1"
    assert case.run_status == "not_started"
    assert case.mesh_markers["wall"] == "fairing_solid"
    assert case.mesh_markers["monitoring"] == ["fairing_solid"]
    assert case.mesh_markers["plotting"] == ["fairing_solid"]
    assert case.mesh_markers["euler"] == ["fairing_solid"]
    assert case.case_output_paths.su2_mesh.exists()
    assert case.case_output_paths.history.exists() is False
    assert case.reference_geometry.gate_status == "pass"
    assert case.force_surface_provenance.scope == "component_subset"
    assert case.force_surface_provenance.matches_wall_marker is True
    assert case.force_surface_provenance.matches_entire_aircraft_wall is False
    assert case.force_surface_provenance.component_provenance == "component_groups_mapped"
    assert case.force_surface_provenance.primary_group is not None
    assert case.force_surface_provenance.primary_group.marker_name == "fairing_solid"
    assert case.provenance_gates.overall_status == "pass"

    runtime_cfg = case.runtime_cfg_path.read_text(encoding="utf-8")
    assert "MARKER_EULER= ( fairing_solid )" in runtime_cfg
    assert "MARKER_MONITORING= ( fairing_solid )" in runtime_cfg
    assert "MARKER_PLOTTING= ( fairing_solid )" in runtime_cfg
    assert "MARKER_EULER= ( aircraft )" not in runtime_cfg

    payload = json.loads(case.case_output_paths.contract_path.read_text(encoding="utf-8"))
    assert payload["run_status"] == "not_started"
    assert payload["mesh_markers"]["wall"] == "fairing_solid"
    assert payload["force_surface_provenance"]["scope"] == "component_subset"


def test_materialize_baseline_case_preserves_user_declared_reference_warnings(tmp_path: Path):
    mesh_handoff = _build_fairing_solid_mesh_handoff(tmp_path)
    runtime = SU2RuntimeConfig(
        enabled=True,
        max_iterations=12,
        reference_mode="user_declared",
        reference_override={
            "ref_area": 1.0,
            "ref_length": 2.82880659,
            "ref_origin_moment": {"x": 0.0, "y": 0.0, "z": 0.0},
            "source_label": "external_fairing_project_reference_policy",
            "warnings": ["borrowed_zero_moment_origin_from_source_su2_handoff"],
        },
    )

    case = materialize_baseline_case(
        mesh_handoff,
        runtime,
        tmp_path / "fairing_su2_case",
        source_root=Path.cwd(),
    )

    assert case.reference_geometry.gate_status == "warn"
    assert case.provenance_gates.reference_quantities.status == "warn"
    assert (
        "borrowed_zero_moment_origin_from_source_su2_handoff"
        in case.reference_geometry.warnings
    )

    payload = json.loads(case.case_output_paths.contract_path.read_text(encoding="utf-8"))
    assert payload["reference_geometry"]["gate_status"] == "warn"
    assert (
        "borrowed_zero_moment_origin_from_source_su2_handoff"
        in payload["reference_geometry"]["warnings"]
    )


def test_materialize_baseline_case_consumes_main_wing_marker_without_running_su2(tmp_path: Path):
    mesh_handoff = _build_main_wing_mesh_handoff(tmp_path)
    runtime = SU2RuntimeConfig(
        enabled=True,
        max_iterations=12,
        reference_mode="user_declared",
        reference_override={
            "ref_area": 0.2,
            "ref_length": 1.0,
            "ref_origin_moment": {"x": 0.5, "y": 0.1, "z": 0.05},
            "source_label": "synthetic_main_wing_slab_reference",
        },
    )

    case = materialize_baseline_case(
        mesh_handoff,
        runtime,
        tmp_path / "main_wing_su2_case",
        source_root=Path.cwd(),
    )

    assert case.contract == "su2_handoff.v1"
    assert case.run_status == "not_started"
    assert case.mesh_markers["wall"] == "main_wing"
    assert case.mesh_markers["monitoring"] == ["main_wing"]
    assert case.mesh_markers["plotting"] == ["main_wing"]
    assert case.mesh_markers["euler"] == ["main_wing"]
    assert case.case_output_paths.su2_mesh.exists()
    assert case.case_output_paths.history.exists() is False
    assert case.reference_geometry.gate_status == "pass"
    assert case.force_surface_provenance.scope == "component_subset"
    assert case.force_surface_provenance.matches_wall_marker is True
    assert case.force_surface_provenance.matches_entire_aircraft_wall is False
    assert case.force_surface_provenance.component_provenance == "component_groups_mapped"
    assert case.force_surface_provenance.primary_group is not None
    assert case.force_surface_provenance.primary_group.marker_name == "main_wing"
    assert case.provenance_gates.overall_status == "pass"

    runtime_cfg = case.runtime_cfg_path.read_text(encoding="utf-8")
    assert "MARKER_EULER= ( main_wing )" in runtime_cfg
    assert "MARKER_MONITORING= ( main_wing )" in runtime_cfg
    assert "MARKER_PLOTTING= ( main_wing )" in runtime_cfg
    assert "MARKER_EULER= ( aircraft )" not in runtime_cfg

    payload = json.loads(case.case_output_paths.contract_path.read_text(encoding="utf-8"))
    assert payload["run_status"] == "not_started"
    assert payload["mesh_markers"]["wall"] == "main_wing"
    assert payload["force_surface_provenance"]["scope"] == "component_subset"


def test_materialize_baseline_case_defaults_to_four_su2_threads(tmp_path: Path):
    mesh_handoff = _build_mesh_handoff(tmp_path)
    runtime = SU2RuntimeConfig(enabled=True, max_iterations=12)

    case = materialize_baseline_case(
        mesh_handoff,
        runtime,
        tmp_path / "su2_case",
        source_root=Path.cwd(),
    )

    assert case.solver_command == ["SU2_CFD", "-t", "4", "su2_runtime.cfg"]


def test_materialize_baseline_case_supports_mpi_launch_mode_with_four_core_budget(tmp_path: Path):
    mesh_handoff = _build_mesh_handoff(tmp_path)
    runtime = SU2RuntimeConfig(enabled=True, max_iterations=12, parallel_mode="mpi")

    case = materialize_baseline_case(
        mesh_handoff,
        runtime,
        tmp_path / "su2_case",
        source_root=Path.cwd(),
    )

    assert case.solver_command == ["mpirun", "-np", "4", "SU2_CFD", "-t", "1", "su2_runtime.cfg"]


def test_materialize_baseline_case_prefers_geometry_derived_reference_when_available(
    tmp_path: Path,
    monkeypatch,
):
    mesh_handoff = _build_mesh_handoff(tmp_path)
    runtime = SU2RuntimeConfig(enabled=True, max_iterations=12, reference_mode="auto")

    monkeypatch.setattr(
        "hpa_meshing.adapters.su2_backend._load_vsp_reference_data",
        lambda source_path: {
            "ref_area": 35.175,
            "ref_length": 1.0425,
            "ref_origin_moment": {"x": 4.15, "y": 0.0, "z": 0.12},
            "area_method": "openvsp_reference_wing.sref",
            "length_method": "openvsp_reference_wing.cref",
            "moment_method": "openvsp_vspaero_settings.cg",
            "reference_wing_name": "Main Wing",
            "reference_wing_id": "IPAWXFWPQF",
            "settings": {
                "sref": 35.175,
                "bref": 33.0,
                "cref": 1.0425,
                "xcg": 4.15,
                "ycg": 0.0,
                "zcg": 0.12,
                "ref_flag": 1.0,
                "mac_flag": 0.0,
            },
        },
    )

    case = materialize_baseline_case(
        mesh_handoff,
        runtime,
        tmp_path / "su2_case",
        source_root=Path.cwd(),
    )

    assert case.reference_geometry.ref_area == pytest.approx(35.175)
    assert case.reference_geometry.ref_length == pytest.approx(1.0425)
    assert case.reference_geometry.area_provenance.source_category == "geometry_derived"
    assert case.reference_geometry.area_provenance.method == "openvsp_reference_wing.sref"
    assert case.reference_geometry.moment_origin_provenance.method == "openvsp_vspaero_settings.cg"
    assert case.reference_geometry.gate_status == "pass"
    assert case.provenance_gates.reference_quantities.status == "pass"
    assert case.provenance["reference_source_path"] == str(mesh_handoff.source_path)

    runtime_cfg = case.runtime_cfg_path.read_text(encoding="utf-8")
    assert "REF_AREA= 35.175000" in runtime_cfg
    assert "REF_LENGTH= 1.042500" in runtime_cfg


def test_materialize_baseline_case_warns_when_geometry_derived_moment_origin_is_zero_vector(
    tmp_path: Path,
):
    mesh_handoff = _build_mesh_handoff(tmp_path)
    runtime = SU2RuntimeConfig(enabled=True, max_iterations=12, reference_mode="auto")
    mesh_handoff.provenance["provider"]["provenance"]["reference_geometry"]["ref_origin_moment"] = {
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
    }
    mesh_handoff.provenance["provider"]["provenance"]["reference_geometry"]["settings"]["xcg"] = 0.0
    mesh_handoff.provenance["provider"]["provenance"]["reference_geometry"]["settings"]["ycg"] = 0.0
    mesh_handoff.provenance["provider"]["provenance"]["reference_geometry"]["settings"]["zcg"] = 0.0

    case = materialize_baseline_case(
        mesh_handoff,
        runtime,
        tmp_path / "su2_case",
        source_root=Path.cwd(),
    )

    assert case.reference_geometry.gate_status == "warn"
    assert "geometry_derived_moment_origin_is_zero_vector" in case.reference_geometry.warnings
    assert case.provenance_gates.reference_quantities.status == "warn"
    runtime_cfg = case.runtime_cfg_path.read_text(encoding="utf-8")
    assert "REF_ORIGIN_MOMENT_X= 0.000000" in runtime_cfg
    assert "REF_ORIGIN_MOMENT_Y= 0.000000" in runtime_cfg
    assert "REF_ORIGIN_MOMENT_Z= 0.000000" in runtime_cfg


def test_materialize_baseline_case_accepts_user_declared_reference_override(tmp_path: Path):
    mesh_handoff = _build_mesh_handoff(tmp_path)
    runtime = SU2RuntimeConfig(
        enabled=True,
        max_iterations=12,
        reference_mode="user_declared",
        reference_override={
            "ref_area": 28.6275,
            "ref_length": 0.8675,
            "ref_origin_moment": {"x": 0.25, "y": 0.0, "z": -0.1},
            "source_label": "unit_test_manual_reference",
        },
    )

    case = materialize_baseline_case(
        mesh_handoff,
        runtime,
        tmp_path / "su2_case",
        source_root=Path.cwd(),
    )

    assert case.reference_geometry.ref_area == pytest.approx(28.6275)
    assert case.reference_geometry.ref_length == pytest.approx(0.8675)
    assert case.reference_geometry.ref_origin_moment.x == pytest.approx(0.25)
    assert case.reference_geometry.area_provenance.source_category == "user_declared"
    assert case.reference_geometry.gate_status == "pass"
    assert case.provenance_gates.reference_quantities.status == "pass"


def test_materialize_baseline_case_supports_adiabatic_no_slip_wall(tmp_path: Path):
    mesh_handoff = _build_mesh_handoff(tmp_path)
    runtime = SU2RuntimeConfig(
        enabled=True,
        max_iterations=12,
        wall_boundary_condition="adiabatic_no_slip",
    )

    case = materialize_baseline_case(
        mesh_handoff,
        runtime,
        tmp_path / "su2_case",
        source_root=Path.cwd(),
    )

    runtime_cfg = case.runtime_cfg_path.read_text(encoding="utf-8")
    assert "MARKER_HEATFLUX= ( aircraft, 0.0 )" in runtime_cfg
    assert "MARKER_EULER= ( aircraft )" not in runtime_cfg


def test_materialize_baseline_case_supports_dimensional_case_contract(tmp_path: Path):
    mesh_handoff = _build_mesh_handoff(tmp_path)
    runtime = SU2RuntimeConfig(
        enabled=True,
        max_iterations=12,
        velocity_mps=6.5,
        density_kgpm3=1.225,
        temperature_k=288.15,
        dynamic_viscosity_pas=1.789e-5,
        wall_boundary_condition="adiabatic_no_slip",
        reference_mode="user_declared",
        reference_override={
            "ref_area": 35.175,
            "ref_length": 1.0425,
            "ref_origin_moment": {"x": 0.0, "y": 0.0, "z": 0.0},
            "source_label": "unit_test_fixed_contract",
        },
        inc_nondim="DIMENSIONAL",
        fluid_model="CONSTANT_DENSITY",
        inc_density_model="CONSTANT",
    )

    case = materialize_baseline_case(
        mesh_handoff,
        runtime,
        tmp_path / "su2_case",
        source_root=Path.cwd(),
    )

    runtime_cfg = case.runtime_cfg_path.read_text(encoding="utf-8")
    assert "SOLVER= INC_NAVIER_STOKES" in runtime_cfg
    assert "INC_NONDIM= DIMENSIONAL" in runtime_cfg
    assert "INC_DENSITY_MODEL= CONSTANT" in runtime_cfg
    assert "FLUID_MODEL= CONSTANT_DENSITY" in runtime_cfg
    assert "INC_DENSITY_INIT= 1.225000" in runtime_cfg
    assert "INC_VELOCITY_INIT= ( 6.500000, 0.000000, 0.000000 )" in runtime_cfg
    assert "INC_TEMPERATURE_INIT= 288.150000" in runtime_cfg
    assert "MU_CONSTANT= 1.789000e-05" in runtime_cfg
    assert "MARKER_HEATFLUX= ( aircraft, 0.0 )" in runtime_cfg
    assert "MARKER_FAR= ( farfield )" in runtime_cfg
    assert "REF_AREA= 35.175000" in runtime_cfg
    assert "REF_LENGTH= 1.042500" in runtime_cfg
    assert "KIND_TURB_MODEL= NONE" in runtime_cfg
    assert "AOA= 0.000000" in runtime_cfg
    assert "SIDESLIP_ANGLE= 0.000000" in runtime_cfg


def test_parse_history_extracts_final_coefficients(tmp_path: Path):
    history_path = tmp_path / "history.csv"
    history_path.write_text(
        (
            '"Time_Iter","Inner_Iter","CD","CL","CMy","CMz"\n'
            '0,0,0.025,0.11,-0.006,0.002\n'
            '0,1,0.024,0.12,-0.004,0.001\n'
        ),
        encoding="utf-8",
    )

    parsed = parse_history(history_path)

    assert parsed["history_path"] == str(history_path)
    assert parsed["final_iteration"] == 1
    assert parsed["cd"] == pytest.approx(0.024)
    assert parsed["cl"] == pytest.approx(0.12)
    assert parsed["cm"] == pytest.approx(-0.004)
    assert parsed["cm_axis"] == "CMy"


def test_parse_solver_log_quality_metrics_extracts_preprocessing_values(tmp_path: Path):
    solver_log = tmp_path / "solver.log"
    solver_log.write_text(
        "\n".join(
            [
                "Compute the surface curvature.",
                "Max K: 1768.33. Mean K: 23.2247. Standard deviation K: 107.701.",
                "+--------------------------------------------------------------+",
                "|           Mesh Quality Metric|        Minimum|        Maximum|",
                "+--------------------------------------------------------------+",
                "|    Orthogonality Angle (deg.)|         31.473|        84.6248|",
                "|     CV Face Area Aspect Ratio|         1.2135|        377.909|",
                "|           CV Sub-Volume Ratio|        1.00013|        13256.1|",
                "+--------------------------------------------------------------+",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = parse_solver_log_quality_metrics(solver_log)

    assert metrics["surface_curvature"]["max"] == pytest.approx(1768.33)
    assert metrics["surface_curvature"]["mean"] == pytest.approx(23.2247)
    assert metrics["surface_curvature"]["std"] == pytest.approx(107.701)
    dual_quality = metrics["dual_control_volume_quality"]
    assert dual_quality["orthogonality_angle_deg"]["min"] == pytest.approx(31.473)
    assert dual_quality["orthogonality_angle_deg"]["max"] == pytest.approx(84.6248)
    assert dual_quality["cv_face_area_aspect_ratio"]["max"] == pytest.approx(377.909)
    assert dual_quality["cv_sub_volume_ratio"]["max"] == pytest.approx(13256.1)


def test_run_baseline_case_invokes_solver_and_updates_contract(tmp_path: Path, monkeypatch):
    mesh_handoff = _build_mesh_handoff(tmp_path)
    runtime = SU2RuntimeConfig(enabled=True, max_iterations=5)
    calls: list[dict[str, object]] = []

    def _fake_run(command, cwd=None, stdout=None, stderr=None, text=None, check=None, env=None):
        case_dir = Path(cwd)
        calls.append({"command": list(command), "cwd": str(case_dir), "omp_num_threads": None if env is None else env.get("OMP_NUM_THREADS")})
        (case_dir / "history.csv").write_text(
            '"Time_Iter","Inner_Iter","CD","CL","CMy"\n0,0,0.021,0.13,-0.005\n',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("hpa_meshing.adapters.su2_backend.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("hpa_meshing.adapters.su2_backend.subprocess.run", _fake_run)

    result = run_baseline_case(
        mesh_handoff,
        runtime,
        tmp_path / "su2_case",
        source_root=Path.cwd(),
    )

    assert calls
    assert calls[0]["command"] == ["SU2_CFD", "-t", "4", "su2_runtime.cfg"]
    assert calls[0]["omp_num_threads"] == "4"
    assert Path(calls[0]["cwd"]) == tmp_path / "su2_case" / runtime.case_name
    assert result["run_status"] == "completed"
    assert result["solver_command"] == "SU2_CFD -t 4 su2_runtime.cfg"
    assert result["final_coefficients"]["cl"] == pytest.approx(0.13)
    assert result["final_coefficients"]["cd"] == pytest.approx(0.021)
    assert result["final_coefficients"]["cm"] == pytest.approx(-0.005)
    assert result["reference_geometry"]["gate_status"] in {"pass", "warn"}
    assert result["force_surface_provenance"]["scope"] == "whole_aircraft_wall"
    assert result["provenance_gates"]["reference_quantities"]["status"] in {"pass", "warn"}
    assert result["convergence_gate"]["mesh_gate"]["status"] == "pass"
    assert result["convergence_gate"]["iterative_gate"]["status"] == "fail"
    assert result["convergence_gate"]["overall_convergence_gate"]["comparability_level"] == "not_comparable"

    payload = json.loads(Path(result["case_output_paths"]["contract_path"]).read_text(encoding="utf-8"))
    assert payload["run_status"] == "completed"
    assert payload["history"]["cl"] == pytest.approx(0.13)
    assert payload["convergence_gate"]["mesh_gate"]["status"] == "pass"


def test_run_baseline_case_invokes_mpi_launcher_with_one_thread_per_rank(tmp_path: Path, monkeypatch):
    mesh_handoff = _build_mesh_handoff(tmp_path)
    runtime = SU2RuntimeConfig(enabled=True, max_iterations=5, parallel_mode="mpi")
    calls: list[dict[str, object]] = []

    def _fake_run(command, cwd=None, stdout=None, stderr=None, text=None, check=None, env=None):
        case_dir = Path(cwd)
        calls.append({"command": list(command), "cwd": str(case_dir), "omp_num_threads": None if env is None else env.get("OMP_NUM_THREADS")})
        (case_dir / "history.csv").write_text(
            '"Time_Iter","Inner_Iter","CD","CL","CMy"\n0,0,0.021,0.13,-0.005\n',
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("hpa_meshing.adapters.su2_backend.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("hpa_meshing.adapters.su2_backend.subprocess.run", _fake_run)

    result = run_baseline_case(
        mesh_handoff,
        runtime,
        tmp_path / "su2_case",
        source_root=Path.cwd(),
    )

    assert calls
    assert calls[0]["command"] == ["mpirun", "-np", "4", "SU2_CFD", "-t", "1", "su2_runtime.cfg"]
    assert calls[0]["omp_num_threads"] == "1"
    assert result["run_status"] == "completed"
    assert result["solver_command"] == "mpirun -np 4 SU2_CFD -t 1 su2_runtime.cfg"


def test_run_baseline_case_fails_clearly_when_solver_missing(tmp_path: Path, monkeypatch):
    mesh_handoff = _build_mesh_handoff(tmp_path)
    runtime = SU2RuntimeConfig(enabled=True)

    monkeypatch.setattr("hpa_meshing.adapters.su2_backend.shutil.which", lambda name: None)

    result = run_baseline_case(
        mesh_handoff,
        runtime,
        tmp_path / "su2_case",
        source_root=Path.cwd(),
    )

    assert result["run_status"] == "failed"
    assert result["failure_code"] == "solver_not_found"
    assert "SU2_CFD" in result["error"]


def test_run_baseline_case_fails_clearly_when_mpi_launcher_missing(tmp_path: Path, monkeypatch):
    mesh_handoff = _build_mesh_handoff(tmp_path)
    runtime = SU2RuntimeConfig(enabled=True, parallel_mode="mpi")

    monkeypatch.setattr(
        "hpa_meshing.adapters.su2_backend.shutil.which",
        lambda name: None if name == "mpirun" else f"/usr/bin/{name}",
    )

    result = run_baseline_case(
        mesh_handoff,
        runtime,
        tmp_path / "su2_case",
        source_root=Path.cwd(),
    )

    assert result["run_status"] == "failed"
    assert result["failure_code"] == "launcher_not_found"
    assert "mpirun" in result["error"]


def test_run_job_surfaces_su2_baseline_report(tmp_path: Path, monkeypatch):
    from hpa_meshing import pipeline as mesh_pipeline

    geometry = tmp_path / "assembly.vsp3"
    geometry.write_text("<vsp3/>", encoding="utf-8")
    normalized = _write_occ_box_step(tmp_path / "provider", "normalized.stp")
    provider_result = _provider_result(geometry, normalized)

    def _fake_su2_run(mesh_handoff, runtime, case_root, source_root=None):
        case_dir = Path(case_root) / runtime.case_name
        case_dir.mkdir(parents=True, exist_ok=True)
        history = case_dir / "history.csv"
        history.write_text(
            '"Time_Iter","Inner_Iter","CD","CL","CMy"\n0,2,0.031,0.19,-0.008\n',
            encoding="utf-8",
        )
        return {
            "contract": "su2_handoff.v1",
            "run_status": "completed",
            "solver_command": "SU2_CFD -t 4 su2_runtime.cfg",
            "runtime_cfg_path": str(case_dir / "su2_runtime.cfg"),
            "history_path": str(history),
            "case_output_paths": {
                "case_dir": str(case_dir),
                "contract_path": str(case_dir / "su2_handoff.json"),
            },
            "final_coefficients": {
                "cl": 0.19,
                "cd": 0.031,
                "cm": -0.008,
                "cm_axis": "CMy",
            },
            "reference_geometry": {
                "ref_area": 35.175,
                "ref_length": 1.0425,
                "ref_origin_moment": {"x": 0.0, "y": 0.0, "z": 0.0},
                "area_provenance": {
                    "source_category": "geometry_derived",
                    "method": "openvsp_reference_wing.sref",
                    "confidence": "high",
                },
                "length_provenance": {
                    "source_category": "geometry_derived",
                    "method": "openvsp_reference_wing.cref",
                    "confidence": "high",
                },
                "moment_origin_provenance": {
                    "source_category": "geometry_derived",
                    "method": "openvsp_vspaero_settings.cg",
                    "confidence": "medium",
                },
                "gate_status": "pass",
                "confidence": "high",
                "warnings": [],
                "notes": [],
            },
            "force_surface_provenance": {
                "gate_status": "pass",
                "confidence": "medium",
                "source_kind": "mesh_physical_group",
                "wall_marker": "aircraft",
                "monitoring_markers": ["aircraft"],
                "plotting_markers": ["aircraft"],
                "euler_markers": ["aircraft"],
                "source_groups": [
                    {
                        "marker_name": "aircraft",
                        "physical_name": "aircraft",
                        "physical_tag": 2,
                        "dimension": 2,
                        "entity_count": 38,
                        "element_count": 180,
                    }
                ],
                "primary_group": {
                    "marker_name": "aircraft",
                    "physical_name": "aircraft",
                    "physical_tag": 2,
                    "dimension": 2,
                    "entity_count": 38,
                    "element_count": 180,
                },
                "matches_wall_marker": True,
                "matches_entire_aircraft_wall": True,
                "scope": "whole_aircraft_wall",
                "body_count": 3,
                "component_labels_present_in_geometry": True,
                "component_provenance": "geometry_labels_present_but_not_mapped",
                "warnings": [],
                "notes": [],
            },
            "provenance_gates": {
                "overall_status": "pass",
                "reference_quantities": {"status": "pass", "confidence": "high", "warnings": [], "notes": []},
                "force_surface": {"status": "pass", "confidence": "medium", "warnings": [], "notes": []},
            },
            "convergence_gate": {
                "contract": "convergence_gate.v1",
                "mesh_gate": {
                    "status": "pass",
                    "confidence": "high",
                    "checks": {
                        "mesh_handoff_complete": {
                            "status": "pass",
                            "observed": {"route_stage": "baseline"},
                            "expected": {"route_stage": "baseline"},
                            "warnings": [],
                            "notes": [],
                        }
                    },
                    "warnings": [],
                    "notes": [],
                },
                "iterative_gate": {
                    "status": "pass",
                    "confidence": "high",
                    "checks": {
                        "coefficient_stability": {
                            "status": "pass",
                            "observed": {"tail_window": 10},
                            "expected": {"tail_window": 10},
                            "warnings": [],
                            "notes": [],
                        }
                    },
                    "warnings": [],
                    "notes": [],
                },
                "overall_convergence_gate": {
                    "status": "pass",
                    "confidence": "high",
                    "comparability_level": "preliminary_compare",
                    "checks": {
                        "mesh_gate": {
                            "status": "pass",
                            "observed": {"status": "pass"},
                            "expected": {"status": "pass"},
                            "warnings": [],
                            "notes": [],
                        }
                    },
                    "warnings": [],
                    "notes": [],
                },
            },
            "provenance": {"source_contract": "mesh_handoff.v1"},
            "notes": ["baseline test stub"],
        }

    monkeypatch.setattr(mesh_pipeline, "run_baseline_case", _fake_su2_run)
    monkeypatch.setattr(
        "hpa_meshing.geometry.loader.materialize_geometry_with_provider",
        lambda path, config: provider_result,
    )

    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=geometry,
        out_dir=tmp_path / "out",
        geometry_provider="openvsp_surface_intersection",
        global_min_size=0.5,
        global_max_size=2.0,
        su2=SU2RuntimeConfig(enabled=True),
    )

    result = run_job(config)

    assert result["status"] == "success"
    assert result["su2"]["run_status"] == "completed"
    assert result["su2"]["solver_command"] == "SU2_CFD -t 4 su2_runtime.cfg"
    assert result["su2"]["final_coefficients"]["cl"] == pytest.approx(0.19)
    assert result["su2"]["reference_geometry"]["area_provenance"]["source_category"] == "geometry_derived"
    assert result["su2"]["force_surface_provenance"]["scope"] == "whole_aircraft_wall"
    assert result["su2"]["provenance_gates"]["overall_status"] == "pass"
    assert result["su2"]["convergence_gate"]["overall_convergence_gate"]["status"] == "pass"

    report = json.loads((config.out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["su2"]["history_path"].endswith("history.csv")
    assert report["su2"]["final_coefficients"]["cm"] == pytest.approx(-0.008)
    assert report["su2"]["reference_geometry"]["length_provenance"]["method"] == "openvsp_reference_wing.cref"
    assert report["su2"]["force_surface_provenance"]["primary_group"]["physical_name"] == "aircraft"
    assert report["su2"]["convergence_gate"]["mesh_gate"]["status"] == "pass"


def test_package_native_su2_smoke(tmp_path: Path):
    if os.environ.get("HPA_MESHING_ENABLE_PACKAGE_SMOKE") != "1":
        pytest.skip("set HPA_MESHING_ENABLE_PACKAGE_SMOKE=1 to run the package-native SU2 smoke")
    data_path = Path(__file__).resolve().parents[2] / "data" / "blackcat_004_origin.vsp3"
    if shutil.which("SU2_CFD") is None:
        pytest.skip("SU2_CFD not available on PATH")
    if not data_path.exists():
        pytest.skip("blackcat_004_origin.vsp3 not available")
    try:
        import openvsp  # type: ignore  # noqa: F401
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"openvsp python bindings not available: {exc}")

    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=data_path,
        out_dir=tmp_path / "smoke",
        geometry_provider="openvsp_surface_intersection",
        global_min_size=0.5,
        global_max_size=2.0,
        su2=SU2RuntimeConfig(enabled=True, max_iterations=5),
    )

    result = run_job(config)

    assert result["status"] == "success"
    assert result["mesh"]["contract"] == "mesh_handoff.v1"
    assert result["su2"]["run_status"] == "completed"
    assert Path(result["su2"]["runtime_cfg_path"]).exists()
    assert Path(result["su2"]["history_path"]).exists()
    assert result["su2"]["final_coefficients"]["cl"] is not None
    assert result["su2"]["final_coefficients"]["cd"] is not None
