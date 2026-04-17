from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import numpy as np

from hpa_mdo.core import load_config
from hpa_mdo.hifi import calculix_runner
from hpa_mdo.hifi.calculix_runner import (
    find_ccx,
    prepare_buckle_inp,
    prepare_static_inp,
    root_boundary_from_mesh,
    run_static,
    tip_node_from_mesh,
)
from hpa_mdo.hifi.frd_parser import parse_buckle_eigenvalues, parse_displacement
from hpa_mdo.hifi.frd_parser import parse_nodal_coordinates


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "blackcat_004.yaml"


MESH_TEXT = """*NODE
1, 0.0, 0.0, 0.0
2, 0.0, 1.0, 0.0
3, 0.1, 1.0, 0.0
4, 0.0, 0.0, 0.1
*ELEMENT, TYPE=C3D4
10, 1, 2, 3, 4
"""

MIXED_SURFACE_LINE_MESH = """*NODE
1, 0.0, 0.0, 0.0
2, 1.0, 0.0, 0.0
3, 0.0, 1.0, 0.0
4, 0.0, 2.0, 0.0
*ELEMENT, TYPE=CPS3
10, 1, 2, 3
*ELEMENT, TYPE=T3D2
20, 3, 4
"""

MIXED_SURFACE_WITH_DUPLICATE_FACETS = """*NODE
1, 0.0, 0.0, 0.0
2, 1.0, 0.0, 0.0
3, 0.0, 1.0, 0.0
4, 0.0, 2.0, 0.0
*ELEMENT, TYPE=CPS3
10, 1, 2, 3
11, 3, 2, 1
12, 2, 3, 4
*ELEMENT, TYPE=T3D2
20, 3, 4
"""

MIXED_SURFACE_WITH_INCONSISTENT_NORMALS = """*NODE
1, 0.0, 0.0, 0.0
2, 1.0, 0.0, 0.0
3, 0.0, 1.0, 0.0
4, 1.0, 1.0, 0.0
*ELEMENT, TYPE=CPS3
10, 1, 2, 3
11, 2, 3, 4
*ELEMENT, TYPE=T3D2
20, 3, 4
"""

MIXED_SURFACE_WITH_SLIVER_TRIANGLE = """*NODE
1, 0.0, 0.0, 0.0
2, 100.0, 0.0, 0.0
3, 50.0, 0.001, 0.0
4, 0.0, 10.0, 0.0
5, 10.0, 0.0, 0.0
6, 10.0, 10.0, 0.0
*ELEMENT, TYPE=CPS3
10, 1, 2, 3
11, 4, 5, 6
"""


def _cfg(tmp_path: Path):
    return load_config(CONFIG_PATH, local_paths_path=tmp_path / "missing_local_paths.yaml")


def test_find_ccx_returns_none_when_disabled(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.hi_fidelity.calculix.enabled = False
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/ccx")

    assert find_ccx(cfg) is None


def test_prepare_static_inp_appends_calculix_blocks(tmp_path: Path) -> None:
    mesh = tmp_path / "mesh.inp"
    out = tmp_path / "static.inp"
    mesh.write_text(MESH_TEXT, encoding="utf-8")

    result = prepare_static_inp(
        mesh,
        out,
        {"E": 230e9, "nu": 0.27, "rho": 1600.0},
        (1, (1, 2, 3)),
        [(2, 3, -100.0)],
    )

    text = result.read_text(encoding="utf-8")
    assert "*NODE\n1, 0.0, 0.0, 0.0" in text
    assert "*ELEMENT, TYPE=C3D4\n10, 1, 2, 3, 4" in text
    assert "*ELSET, ELSET=EALL\n10" in text
    assert "*MATERIAL, NAME=HPA_MATERIAL" in text
    assert "*ELASTIC\n2.3e+11, 0.27" in text
    assert "*DENSITY\n1600" in text
    assert "*SOLID SECTION, ELSET=EALL, MATERIAL=HPA_MATERIAL" in text
    assert "*BOUNDARY\n1, 1, 1, 0.0\n1, 2, 2, 0.0\n1, 3, 3, 0.0" in text
    assert "*STEP, NAME=cruise\n*STATIC\n1.0, 1.0" in text
    assert "*CLOAD\n2, 3, -100" in text
    assert "*NODE FILE, OUTPUT=3D\nU\n*END STEP" in text


def test_prepare_buckle_inp_appends_static_and_buckle_steps(tmp_path: Path) -> None:
    mesh = tmp_path / "mesh.inp"
    out = tmp_path / "buckle.inp"
    mesh.write_text(MESH_TEXT, encoding="utf-8")

    result = prepare_buckle_inp(
        mesh,
        out,
        {"E": 230e9, "nu": 0.27, "rho": 1600.0},
        [(1, (1, 2, 3)), (4, (1, 2, 3))],
        [(2, 3, -50.0)],
        n_modes=3,
    )

    text = result.read_text(encoding="utf-8")
    assert "*ELSET, ELSET=EALL\n10" in text
    assert "*MATERIAL, NAME=HPA_MATERIAL" in text
    assert "*STEP, NAME=reference_static\n*STATIC\n1.0, 1.0" in text
    assert "*CLOAD\n2, 3, -50" in text
    assert "*END STEP\n*STEP, NAME=buckle\n*BUCKLE\n3" in text
    assert "*NODE FILE, OUTPUT=3D\nU\n*END STEP" in text


def test_prepare_static_inp_filters_line_elements_and_adds_surface_thickness(tmp_path: Path) -> None:
    mesh = tmp_path / "mixed_mesh.inp"
    out = tmp_path / "static_surface.inp"
    mesh.write_text(MIXED_SURFACE_LINE_MESH, encoding="utf-8")

    result = prepare_static_inp(
        mesh,
        out,
        {"E": 230e9, "nu": 0.27, "rho": 1600.0},
        (1, (1, 2, 3)),
        [(3, 3, -10.0)],
        section_thickness=0.8,
    )

    text = result.read_text(encoding="utf-8")
    assert "*ELEMENT, TYPE=S3" in text
    assert "*ELEMENT, TYPE=CPS3" not in text
    assert "*ELEMENT, TYPE=T3D2" not in text
    assert "*ELSET, ELSET=EALL\n10" in text
    assert "*SHELL SECTION, ELSET=EALL, MATERIAL=HPA_MATERIAL\n0.8" in text


def test_prepare_static_inp_deduplicates_duplicate_surface_facets(tmp_path: Path) -> None:
    mesh = tmp_path / "duplicate_surface_mesh.inp"
    out = tmp_path / "static_surface_deduped.inp"
    mesh.write_text(MIXED_SURFACE_WITH_DUPLICATE_FACETS, encoding="utf-8")

    result = prepare_static_inp(
        mesh,
        out,
        {"E": 230e9, "nu": 0.27, "rho": 1600.0},
        (1, (1, 2, 3)),
        [(3, 3, -10.0)],
        section_thickness=0.8,
    )

    text = result.read_text(encoding="utf-8")
    assert "*ELSET, ELSET=EALL\n10, 12" in text
    assert "11, 3, 2, 1" not in text
    assert text.count("10, 1, 2, 3") == 1
    assert text.count("12, 2, 4, 3") == 1


def test_prepare_static_inp_reorients_inconsistent_shell_normals(tmp_path: Path) -> None:
    mesh = tmp_path / "inconsistent_surface_mesh.inp"
    out = tmp_path / "static_surface_reoriented.inp"
    mesh.write_text(MIXED_SURFACE_WITH_INCONSISTENT_NORMALS, encoding="utf-8")

    result = prepare_static_inp(
        mesh,
        out,
        {"E": 230e9, "nu": 0.27, "rho": 1600.0},
        (1, (1, 2, 3)),
        [(3, 3, -10.0)],
        section_thickness=0.8,
    )

    text = result.read_text(encoding="utf-8")
    assert "*ELEMENT, TYPE=S3" in text
    assert "10, 1, 2, 3" in text
    assert "11, 2, 4, 3" in text
    assert "11, 2, 3, 4" not in text


def test_prepare_static_inp_filters_extreme_sliver_shells(tmp_path: Path) -> None:
    mesh = tmp_path / "sliver_surface_mesh.inp"
    out = tmp_path / "static_surface_sliver_filtered.inp"
    mesh.write_text(MIXED_SURFACE_WITH_SLIVER_TRIANGLE, encoding="utf-8")

    result = prepare_static_inp(
        mesh,
        out,
        {"E": 230e9, "nu": 0.27, "rho": 1600.0},
        (4, (1, 2, 3)),
        [(6, 3, -10.0)],
        section_thickness=0.8,
    )

    text = result.read_text(encoding="utf-8")
    assert "** HPA_MDO_FILTERED_LOW_QUALITY_SHELLS count=1" in text
    assert "*ELSET, ELSET=EALL\n11" in text
    assert "10, 1, 2, 3" not in text
    assert "11, 4, 5, 6" in text


def test_root_boundary_and_tip_node_from_mesh(tmp_path: Path) -> None:
    mesh = tmp_path / "mesh.inp"
    mesh.write_text(MESH_TEXT, encoding="utf-8")

    assert root_boundary_from_mesh(mesh) == [(1, (1, 2, 3)), (4, (1, 2, 3))]
    assert tip_node_from_mesh(mesh) == 2


MESH_WITH_NSETS = """*NODE
1, 0.0, 0.0, 0.0
2, 0.0, 1.0, 0.0
3, 0.1, 1.0, 0.0
4, 0.0, 0.0, 0.1
*NSET, NSET=ROOT
1
*NSET, NSET=TIP
3
*ELEMENT, TYPE=C3D4
10, 1, 2, 3, 4
"""


def test_root_boundary_prefers_nset(tmp_path: Path) -> None:
    mesh = tmp_path / "mesh.inp"
    mesh.write_text(MESH_WITH_NSETS, encoding="utf-8")

    # NSET=ROOT is authoritative — only node 1 is clamped, ignoring the
    # two nodes that happen to sit at y=0 in the coordinate heuristic.
    assert root_boundary_from_mesh(mesh) == [(1, (1, 2, 3))]
    # NSET=TIP picks node 3 rather than the y-max heuristic (node 2 or 3).
    assert tip_node_from_mesh(mesh) == 3


MESH_FULL_SPAN_NO_NSET = """*NODE
1, 0.0, -16.5, 0.0
2, 0.0, 0.0, 0.0
3, 0.0, 16.5, 0.0
4, 0.0, 0.0, 0.1
*ELEMENT, TYPE=C3D4
10, 1, 2, 3, 4
"""


MESH_ROOT_CLUSTER_NO_NSET = """*NODE
1, 0.0, 100.0, 0.0
2, 0.0, 100.000002, 0.0
3, 0.0, 99.999998, 0.0
4, 0.0, 200.0, 0.0
*ELEMENT, TYPE=C3D4
10, 1, 2, 3, 4
"""


def test_root_boundary_fallback_uses_symmetry_plane_for_full_span_mesh(tmp_path: Path) -> None:
    mesh = tmp_path / "mesh_full_span.inp"
    mesh.write_text(MESH_FULL_SPAN_NO_NSET, encoding="utf-8")

    assert root_boundary_from_mesh(mesh) == [(2, (1, 2, 3)), (4, (1, 2, 3))]


def test_root_boundary_fallback_expands_to_root_plane_cluster(tmp_path: Path) -> None:
    mesh = tmp_path / "mesh_root_cluster.inp"
    mesh.write_text(MESH_ROOT_CLUSTER_NO_NSET, encoding="utf-8")

    assert root_boundary_from_mesh(mesh) == [(1, (1, 2, 3)), (2, (1, 2, 3)), (3, (1, 2, 3))]


def test_run_static_skips_gracefully_when_ccx_missing(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.hi_fidelity.calculix.enabled = True
    monkeypatch.setattr(calculix_runner, "find_ccx", lambda _cfg: None)

    result = run_static(tmp_path / "missing.inp", cfg)

    assert result["returncode"] is None
    assert "ccx not found" in result["error"]


def test_run_static_persists_combined_solver_log(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.hi_fidelity.calculix.enabled = True
    inp = tmp_path / "case.inp"
    inp.write_text("*HEADING\nstub\n", encoding="utf-8")

    def fake_subprocess_run(cmd, cwd, capture_output, text, timeout, check):
        assert cmd == ["/usr/local/bin/ccx", "case"]
        assert cwd == tmp_path
        assert capture_output is True
        assert text is True
        assert timeout == 1200
        assert check is False
        inp.with_suffix(".frd").write_text("frd", encoding="utf-8")
        inp.with_suffix(".dat").write_text("dat", encoding="utf-8")
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="solver stdout\n",
            stderr="solver stderr\n",
        )

    monkeypatch.setattr(calculix_runner, "find_ccx", lambda _cfg: "/usr/local/bin/ccx")
    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    result = run_static(inp, cfg)

    log_text = inp.with_suffix(".log").read_text(encoding="utf-8")
    assert result["log"] == inp.with_suffix(".log")
    assert "===== ccx stdout =====" in log_text
    assert "solver stdout" in log_text
    assert "===== ccx stderr =====" in log_text
    assert "solver stderr" in log_text


def test_parse_displacement_reads_last_disp_block(tmp_path: Path) -> None:
    frd = tmp_path / "case.frd"
    frd.write_text(
        """
 -4  DISP        4    1
 -1         1  1.00000E-03  2.00000E-03 -3.00000E-03
 -3
 -4  DISP        4    2
 -1         1  4.00000E-03  5.00000E-03 -6.00000E-03
 -1         2  7.00000E-03  8.00000E-03 -9.00000E-03
 -3
""",
        encoding="utf-8",
    )

    disp = parse_displacement(frd)

    assert disp.shape == (2, 4)
    np.testing.assert_allclose(
        disp,
        np.asarray(
            [
                [1.0, 4.0e-3, 5.0e-3, -6.0e-3],
                [2.0, 7.0e-3, 8.0e-3, -9.0e-3],
            ]
        ),
    )


def test_parse_nodal_coordinates_reads_first_coordinate_block(tmp_path: Path) -> None:
    frd = tmp_path / "case.frd"
    frd.write_text(
        """
    2C                         2                                     1
 -1         101  1.00000E+00  2.00000E+00  3.00000E+00
 -1         102  4.00000E+00  5.00000E+00  6.00000E+00
 -3
 -4  DISP        4    1
 -1         101  7.00000E-03  8.00000E-03  9.00000E-03
 -3
""",
        encoding="utf-8",
    )

    coords = parse_nodal_coordinates(frd)

    assert coords.shape == (2, 4)
    np.testing.assert_allclose(
        coords,
        np.asarray(
            [
                [101.0, 1.0, 2.0, 3.0],
                [102.0, 4.0, 5.0, 6.0],
            ]
        ),
    )


def test_parse_buckle_eigenvalues_reads_dat_table(tmp_path: Path) -> None:
    dat = tmp_path / "case.dat"
    dat.write_text(
        """
 E I G E N V A L U E   O U T P U T

 MODE NO    EIGENVALUE
       1    1.234500E+00
       2    2.500000E+00
 eigenvalue number 3 = 3.750000D+00
""",
        encoding="utf-8",
    )

    assert parse_buckle_eigenvalues(dat) == [1.2345, 2.5, 3.75]


def test_parse_buckle_eigenvalues_reads_buckling_factor_table(tmp_path: Path) -> None:
    dat = tmp_path / "buckle.dat"
    dat.write_text(
        """
                        S T E P       2


     B U C K L I N G   F A C T O R   O U T P U T

 MODE NO       BUCKLING
                FACTOR

      1   0.9805800E+00
      2   0.9838427E+00
      3   0.9866255E+00
""",
        encoding="utf-8",
    )

    assert parse_buckle_eigenvalues(dat) == [0.98058, 0.9838427, 0.9866255]
