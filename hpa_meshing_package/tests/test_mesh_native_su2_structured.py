from pathlib import Path
import shutil

import pytest

from hpa_meshing.mesh_native.su2_structured import (
    audit_su2_case_markers,
    parse_su2_marker_summary,
    run_structured_box_shell_su2_smoke,
    write_wing_boundary_layer_block_su2,
    write_wing_boundary_layer_block_su2_case,
    write_structured_box_shell_su2_case,
    write_structured_box_shell_su2,
)
from hpa_meshing.mesh_native.near_wall_block import (
    BoundaryLayerBlockSpec,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.wing_surface import (
    Face,
    Reference,
    Station,
    SurfaceMesh,
    WingSpec,
    build_farfield_box_surface,
    build_wing_surface,
)


def _rect_loop():
    return [
        (1.0, 0.05),
        (0.0, 0.05),
        (0.0, -0.05),
        (1.0, -0.05),
    ]


def _wing_and_farfield():
    wing = build_wing_surface(
        WingSpec(
            stations=[
                Station(y=0.0, airfoil_xz=_rect_loop(), chord=1.0, twist_deg=0.0),
                Station(y=1.0, airfoil_xz=_rect_loop(), chord=1.0, twist_deg=0.0),
                Station(y=2.0, airfoil_xz=_rect_loop(), chord=1.0, twist_deg=0.0),
            ],
            side="full",
            te_rule="finite_thickness",
            tip_rule="planar_cap",
            root_rule="wall_cap",
            reference=Reference(sref_full=2.0, cref=1.0, bref_full=2.0),
        )
    )
    return wing, build_farfield_box_surface(wing)


def test_structured_box_shell_su2_writer_preserves_volume_and_markers(tmp_path: Path):
    wing, farfield = _wing_and_farfield()
    out_path = tmp_path / "mesh_native_box_shell.su2"

    report = write_structured_box_shell_su2(wing, farfield, out_path)

    assert out_path.exists()
    assert report["route"] == "mesh_native_structured_box_shell_smoke"
    assert report["node_count"] == 64
    assert report["volume_element_count"] == 26
    assert report["marker_summary"] == {
        "farfield": {"element_count": 54, "element_type_counts": {"9": 54}},
        "wing_wall": {"element_count": 6, "element_type_counts": {"9": 6}},
    }
    assert report["caveats"] == [
        "wing boundary is represented by the wing bounding box for SU2 smoke only",
        "not valid for aerodynamic coefficient interpretation",
    ]

    text = out_path.read_text(encoding="utf-8")
    assert "NDIME= 3" in text
    assert "NELEM= 26" in text
    assert "NPOIN= 64" in text
    assert "NMARK= 2" in text
    assert "MARKER_TAG= wing_wall" in text
    assert "MARKER_TAG= farfield" in text

    parsed = parse_su2_marker_summary(out_path)
    assert parsed["ndime"] == 3
    assert parsed["nelem"] == 26
    assert parsed["npoin"] == 64
    assert parsed["nmark"] == 2
    assert parsed["markers"] == report["marker_summary"]


def test_wing_boundary_layer_block_su2_writer_preserves_hexes_and_boundary_markers(
    tmp_path: Path,
):
    wing = WingSpec(
        stations=[
            Station(y=0.0, airfoil_xz=_rect_loop(), chord=1.0, twist_deg=0.0),
            Station(y=1.0, airfoil_xz=_rect_loop(), chord=0.8, twist_deg=2.0),
            Station(y=2.0, airfoil_xz=_rect_loop(), chord=0.6, twist_deg=4.0),
        ],
        side="full",
        te_rule="finite_thickness",
        tip_rule="planar_cap",
        root_rule="wall_cap",
        reference=Reference(sref_full=1.6, cref=0.8, bref_full=2.0),
    )
    block = build_wing_boundary_layer_block(
        wing,
        BoundaryLayerBlockSpec(
            first_layer_height_m=1.0e-3,
            growth_ratio=1.2,
            layer_count=3,
        ),
    )
    out_path = tmp_path / "wing_bl_block.su2"

    report = write_wing_boundary_layer_block_su2(block, out_path)

    assert report["route"] == "mesh_native_wing_boundary_layer_block_su2"
    assert report["node_count"] == len(block.vertices)
    assert report["volume_element_count"] == len(block.cells)
    assert report["marker_summary"] == {
        marker: {"element_count": count, "element_type_counts": {"9": count}}
        for marker, count in block.boundary_marker_counts().items()
    }
    assert "not a complete farfield CFD domain" in report["caveats"][0]

    parsed = parse_su2_marker_summary(out_path)
    assert parsed["ndime"] == 3
    assert parsed["nelem"] == len(block.cells)
    assert parsed["npoin"] == len(block.vertices)
    assert parsed["markers"] == report["marker_summary"]


def test_wing_boundary_layer_block_case_assigns_all_smoke_markers(tmp_path: Path):
    wing = WingSpec(
        stations=[
            Station(y=0.0, airfoil_xz=_rect_loop(), chord=1.0, twist_deg=0.0),
            Station(y=1.0, airfoil_xz=_rect_loop(), chord=0.8, twist_deg=2.0),
            Station(y=2.0, airfoil_xz=_rect_loop(), chord=0.6, twist_deg=4.0),
        ],
        side="full",
        te_rule="finite_thickness",
        tip_rule="planar_cap",
        root_rule="wall_cap",
        reference=Reference(sref_full=1.6, cref=0.8, bref_full=2.0),
    )
    block = build_wing_boundary_layer_block(
        wing,
        BoundaryLayerBlockSpec(
            first_layer_height_m=1.0e-3,
            growth_ratio=1.2,
            layer_count=3,
        ),
    )

    report = write_wing_boundary_layer_block_su2_case(
        block,
        tmp_path / "wing_bl_case",
        ref_area=1.6,
        ref_length=0.8,
        max_iterations=1,
    )

    assert report["marker_audit"]["status"] == "pass"
    assert report["marker_audit"]["boundary_condition_markers"] == {
        "MARKER_EULER": ["wing_wall"],
        "MARKER_FAR": ["bl_outer_interface", "wake_cut", "span_cap"],
    }
    assert report["engineering_assessment"]["aero_coefficients_interpretable"] is False
    cfg_text = Path(report["runtime_cfg_path"]).read_text(encoding="utf-8")
    assert "SOLVER= INC_EULER" in cfg_text
    assert "MARKER_FAR= ( bl_outer_interface, wake_cut, span_cap )" in cfg_text


def test_structured_box_shell_su2_writer_requires_enclosing_farfield(tmp_path: Path):
    wing, _ = _wing_and_farfield()
    tight_farfield = SurfaceMesh(
        vertices=[
            (0.25, 0.25, -0.01),
            (0.75, 0.25, -0.01),
            (0.75, 0.75, -0.01),
            (0.25, 0.75, -0.01),
            (0.25, 0.25, 0.01),
            (0.75, 0.25, 0.01),
            (0.75, 0.75, 0.01),
            (0.25, 0.75, 0.01),
        ],
        faces=[Face(nodes=(0, 1, 2, 3), marker="farfield")],
    )

    with pytest.raises(ValueError, match="Farfield bounds must strictly enclose wing bounds"):
        write_structured_box_shell_su2(wing, tight_farfield, tmp_path / "bad.su2")


def test_structured_box_shell_case_writes_solver_config_and_marker_audit(tmp_path: Path):
    wing, farfield = _wing_and_farfield()
    case_dir = tmp_path / "su2_case"

    report = write_structured_box_shell_su2_case(
        wing,
        farfield,
        case_dir,
        ref_area=2.0,
        ref_length=1.0,
        velocity_mps=6.5,
        max_iterations=3,
    )

    mesh_path = case_dir / "mesh.su2"
    cfg_path = case_dir / "su2_runtime.cfg"
    report_path = case_dir / "mesh_native_su2_smoke_report.json"

    assert Path(report["mesh_path"]) == mesh_path
    assert Path(report["runtime_cfg_path"]) == cfg_path
    assert Path(report["report_path"]) == report_path
    assert mesh_path.exists()
    assert cfg_path.exists()
    assert report_path.exists()
    assert report["marker_audit"]["status"] == "pass"
    assert report["marker_audit"]["boundary_condition_markers"] == {
        "MARKER_EULER": ["wing_wall"],
        "MARKER_FAR": ["farfield"],
    }

    cfg_text = cfg_path.read_text(encoding="utf-8")
    assert "SOLVER= INC_EULER" in cfg_text
    assert "MESH_FILENAME= mesh.su2" in cfg_text
    assert "MARKER_EULER= ( wing_wall )" in cfg_text
    assert "MARKER_FAR= ( farfield )" in cfg_text
    assert "REF_AREA= 2.000000" in cfg_text
    assert "REF_LENGTH= 1.000000" in cfg_text
    assert "INC_VELOCITY_INIT= ( 6.500000, 0.000000, 0.000000 )" in cfg_text
    assert "ITER= 3" in cfg_text

    assert audit_su2_case_markers(mesh_path, cfg_path)["status"] == "pass"


def test_structured_box_shell_case_rejects_zero_reference_area(tmp_path: Path):
    wing, farfield = _wing_and_farfield()

    with pytest.raises(ValueError, match="ref_area must be positive"):
        write_structured_box_shell_su2_case(
            wing,
            farfield,
            tmp_path / "bad_case",
            ref_area=0.0,
            ref_length=1.0,
        )


def test_structured_box_shell_su2_solver_smoke_runs_when_su2_is_available(tmp_path: Path):
    solver = shutil.which("SU2_CFD")
    if solver is None:
        pytest.skip("SU2_CFD not available")

    wing, farfield = _wing_and_farfield()
    report = run_structured_box_shell_su2_smoke(
        wing,
        farfield,
        tmp_path / "solver_case",
        ref_area=2.0,
        ref_length=1.0,
        max_iterations=3,
        solver_command=solver,
        threads=1,
    )

    assert report["run_status"] == "completed"
    assert report["returncode"] == 0
    assert report["marker_audit"]["status"] == "pass"
    assert Path(report["history_path"]).exists()
    assert Path(report["solver_log_path"]).exists()
    assert report["history"]["final_iteration"] == 2
    assert report["history"]["final_coefficients"]["cl"] is not None
    assert report["history"]["final_coefficients"]["cd"] is not None
    assert report["engineering_assessment"] == {
        "solver_readability": "pass",
        "marker_ownership": "pass",
        "aero_coefficients_interpretable": False,
        "reason": "bounding_box_obstacle_26_hexa_smoke_mesh",
    }
