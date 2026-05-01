from pathlib import Path

import pytest

from hpa_meshing.mesh_native.su2_structured import (
    audit_su2_case_markers,
    parse_su2_marker_summary,
    write_structured_box_shell_su2_case,
    write_structured_box_shell_su2,
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
