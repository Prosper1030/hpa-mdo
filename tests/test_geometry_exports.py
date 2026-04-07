from __future__ import annotations

import numpy as np

from hpa_mdo.structure.spar_model import compute_dual_spar_section
from hpa_mdo.utils.cad_export import load_tube_paths


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
