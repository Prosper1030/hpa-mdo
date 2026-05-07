from __future__ import annotations

from pathlib import Path

import numpy as np

from hpa_mdo.structure.calculix_beam_export import BeamMaterial, build_single_pipe_cantilever_spec
from scripts.phase14_calculix_solution_hunt import write_single_beam_apdl_truth_deck


def test_write_single_beam_apdl_truth_deck_contains_beam188_ctube_and_loads(tmp_path: Path) -> None:
    material = BeamMaterial(
        name="MAIN",
        young_pa=135.0e9,
        poisson_ratio=0.3,
        density_kgpm3=1600.0,
    )
    y_nodes_m = np.array([0.0, 2.0, 5.0], dtype=float)
    outer_radius_m = np.array([0.04, 0.03], dtype=float)
    thickness_m = np.array([0.002, 0.0015], dtype=float)
    nodal_fz_n = np.array([0.0, -10.0, -5.0], dtype=float)
    nodal_my_nm = np.array([0.0, 0.0, 12.5], dtype=float)

    spec = build_single_pipe_cantilever_spec(
        name="b2_truth_probe",
        y_nodes_m=y_nodes_m,
        outer_radius_m=outer_radius_m,
        thickness_m=thickness_m,
        material=material,
        nodal_fz_n=nodal_fz_n,
        nodal_my_nm=nodal_my_nm,
    )

    out_path = write_single_beam_apdl_truth_deck(spec, tmp_path / "b2_tapered_tube.apdl")
    text = out_path.read_text(encoding="utf-8")

    assert "ET,1,BEAM188" in text
    assert "SECTYPE,1,BEAM,CTUBE" in text
    assert "SECTYPE,2,BEAM,CTUBE" in text
    assert "SECDATA,3.800000000e-02,4.000000000e-02" in text
    assert "SECDATA,2.850000000e-02,3.000000000e-02" in text
    assert "DK,1,ALL,0" in text
    assert "FK,2,FZ,-1.000000000e+01" in text
    assert "FK,3,FZ,-5.000000000e+00" in text
    assert "FK,3,MY,1.250000000e+01" in text
    assert "*GET,TIP_UZ,NODE,3,U,Z" in text
