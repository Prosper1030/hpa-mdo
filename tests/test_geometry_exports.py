from __future__ import annotations

from pathlib import Path
import numpy as np
from types import SimpleNamespace

from hpa_mdo.structure.spar_model import compute_dual_spar_section
from hpa_mdo.utils.cad_export import (
    TubePath,
    TubeProfile,
    _apply_deformed_nodes,
    _export_cadquery_step_model,
    compute_deformed_nodes,
    load_tube_paths,
)


def test_compute_dual_spar_section_returns_finite_chordwise_stiffness():
    section = compute_dual_spar_section(
        R_main=np.array([0.03, 0.028]),
        t_main=np.array([0.001, 0.0012]),
        R_rear=np.array([0.02, 0.018]),
        t_rear=np.array([0.001, 0.001]),
        z_main=np.array([0.0, 0.0]),
        z_rear=np.array([0.01, 0.01]),
        d_chord=np.array([0.4, 0.35]),
        E_main=230e9,
        G_main=15e9,
        rho_main=1600.0,
        E_rear=230e9,
        G_rear=15e9,
        rho_rear=1600.0,
    )

    assert np.all(np.isfinite(section.Iz_equiv))
    assert np.all(section.EI_chord > 0.0)


def test_load_tube_paths_supports_dual_spar_csv(tmp_path):
    csv_path = tmp_path / "spar_data.csv"
    csv_path.write_text(
        "Node,Y_Position_m,"
        "Main_X_m,Main_Z_m,Main_Outer_Radius_m,Main_Wall_Thickness_m,"
        "Rear_X_m,Rear_Z_m,Rear_Outer_Radius_m,Rear_Wall_Thickness_m,"
        "Lift_Per_Span_N_m,Torque_Per_Span_Nm_m,Is_Joint,Is_Wire_Attach\n"
        "1,0.0,0.2,0.0,0.05,0.001,0.7,0.0,0.03,0.001,100.0,5.0,0,0\n"
        "2,1.0,0.2,0.1,0.045,0.001,0.7,0.1,0.025,0.001,90.0,4.0,1,0\n",
        encoding="utf-8",
    )

    tube_paths = load_tube_paths(csv_path)

    assert [path.name for path in tube_paths] == ["main_spar", "rear_spar"]
    assert len(tube_paths[0].profiles) == 2
    assert tube_paths[0].profiles[0].outer_radius_mm == 50.0
    assert tube_paths[1].profiles[1].inner_radius_mm == 24.0


def test_compute_deformed_nodes_adds_translational_displacements():
    result = SimpleNamespace(
        nodes=np.array([[0.2, 0.0, 0.0], [0.2, 1.0, 0.1]], dtype=float),
        disp=np.array(
            [
                [0.001, 0.005, 0.003, 0.0, 0.0, 0.0],
                [-0.002, 0.006, -0.003, 0.0, 0.0, 0.0],
            ],
            dtype=float,
        ),
    )

    deformed = compute_deformed_nodes(result)
    expected = np.array([[0.201, 0.005, 0.003], [0.198, 1.006, 0.097]], dtype=float)
    assert np.allclose(deformed, expected)


def test_apply_deformed_nodes_shifts_all_paths_by_same_node_deltas():
    main_profiles = [
        TubeProfile(200.0, 0.0, 0.0, outer_radius_mm=50.0, inner_radius_mm=49.0),
        TubeProfile(200.0, 1000.0, 100.0, outer_radius_mm=45.0, inner_radius_mm=44.0),
    ]
    rear_profiles = [
        TubeProfile(700.0, 0.0, 0.0, outer_radius_mm=30.0, inner_radius_mm=29.0),
        TubeProfile(700.0, 1000.0, 100.0, outer_radius_mm=25.0, inner_radius_mm=24.0),
    ]
    tube_paths = [
        TubePath(name="main_spar", profiles=main_profiles),
        TubePath(name="rear_spar", profiles=rear_profiles),
    ]

    deformed_nodes = np.array([[0.201, 0.005, 0.003], [0.198, 1.006, 0.097]], dtype=float)
    shifted = _apply_deformed_nodes(tube_paths, deformed_nodes)

    # Node deltas [mm]: [+1,+5,+3], [-2,+6,-3]
    assert shifted[0].profiles[0].x_mm == 201.0
    assert shifted[0].profiles[1].x_mm == 198.0
    assert shifted[1].profiles[0].x_mm == 701.0
    assert shifted[1].profiles[1].x_mm == 698.0

    assert shifted[1].profiles[1].y_mm == 1006.0
    assert shifted[1].profiles[1].z_mm == 97.0

    # Tube section geometry is unchanged.
    assert shifted[1].profiles[1].outer_radius_mm == 25.0
    assert shifted[1].profiles[1].inner_radius_mm == 24.0


def test_export_cadquery_step_model_forces_step_type_for_stp_suffix(monkeypatch):
    export_call = {}

    class FakeExporters:
        @staticmethod
        def export(model, path, exportType=None):
            export_call["model"] = model
            export_call["path"] = path
            export_call["exportType"] = exportType

    class FakeCadQuery:
        exporters = FakeExporters()

    monkeypatch.setitem(__import__("sys").modules, "cadquery", FakeCadQuery())

    model = object()
    _export_cadquery_step_model(model, Path("dual_beam.stp"))

    assert export_call == {
        "model": model,
        "path": "dual_beam.stp",
        "exportType": "STEP",
    }
