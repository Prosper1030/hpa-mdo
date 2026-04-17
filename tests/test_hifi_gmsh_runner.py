from __future__ import annotations

from pathlib import Path
import shutil

from hpa_mdo.core import load_config
from hpa_mdo.hifi import gmsh_runner
from hpa_mdo.hifi.gmsh_runner import (
    collect_mesh_diagnostics,
    NamedPoint,
    annotate_inp_with_named_points,
    find_gmsh,
    inp_element_count,
    load_mesh_diagnostics,
    mesh_diagnostics_sidecar_path,
    mesh_step_to_inp,
    parse_nset_from_inp,
    step_length_scale_m_per_unit,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "blackcat_004.yaml"


def _cfg(tmp_path: Path):
    return load_config(CONFIG_PATH, local_paths_path=tmp_path / "missing_local_paths.yaml")


def test_find_gmsh_returns_none_when_disabled(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.hi_fidelity.gmsh.enabled = False
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/gmsh")

    assert find_gmsh(cfg) is None


def test_find_gmsh_uses_configured_binary(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    gmsh = tmp_path / "gmsh"
    gmsh.write_text("#!/bin/sh\n", encoding="utf-8")
    cfg.hi_fidelity.gmsh.enabled = True
    cfg.hi_fidelity.gmsh.binary = str(gmsh)

    assert find_gmsh(cfg) == str(gmsh.resolve())


def test_mesh_step_skips_gracefully_when_gmsh_missing(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.hi_fidelity.gmsh.enabled = True
    monkeypatch.setattr(gmsh_runner, "find_gmsh", lambda _cfg: None)

    result = mesh_step_to_inp(tmp_path / "missing.step", tmp_path / "out.inp", cfg)

    assert result is None


def test_mesh_step_invokes_gmsh_cli(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.hi_fidelity.gmsh.enabled = True
    cfg.hi_fidelity.gmsh.mesh_size_m = 0.123
    step_path = tmp_path / "part.step"
    out_path = tmp_path / "mesh.inp"
    step_path.write_text("STEP", encoding="utf-8")
    monkeypatch.setattr(gmsh_runner, "find_gmsh", lambda _cfg: "/opt/bin/gmsh")

    def fake_run(cmd, **kwargs):
        out_path.write_text("*NODE\n", encoding="utf-8")
        assert cmd == [
            "/opt/bin/gmsh",
            str(step_path),
            "-3",
            "-format",
            "inp",
            "-order",
            "1",
            "-clmax",
            "0.123",
            "-o",
            str(out_path),
        ]
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["timeout"] == 600
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(gmsh_runner.subprocess, "run", fake_run)

    assert mesh_step_to_inp(step_path, out_path, cfg) == out_path


STEP_MM = """ISO-10303-21;
HEADER;
ENDSEC;
DATA;
#24 = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );
ENDSEC;
END-ISO-10303-21;
"""

_SAMPLE_INP_MM = """\
*HEADING
test
*NODE
1, 0.0, 0.0, 0.0
2, 0.0, 1500.0, 0.0
3, 0.0, 4500.0, 0.0
4, 0.0, 16500.0, 0.0
*ELEMENT, TYPE=C3D4, ELSET=EALL
1, 1, 2, 3, 4
"""


def test_step_length_scale_reads_millimetre_units(tmp_path: Path) -> None:
    step = tmp_path / "part.step"
    step.write_text(STEP_MM, encoding="utf-8")

    assert step_length_scale_m_per_unit(step) == 1.0e-3


def test_mesh_step_scales_clmax_and_named_points_for_mm_step(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.hi_fidelity.gmsh.enabled = True
    cfg.hi_fidelity.gmsh.mesh_size_m = 0.05
    cfg.hi_fidelity.gmsh.point_tol_m = 1.0e-3
    step_path = tmp_path / "part.step"
    out_path = tmp_path / "mesh.inp"
    step_path.write_text(STEP_MM, encoding="utf-8")
    monkeypatch.setattr(gmsh_runner, "find_gmsh", lambda _cfg: "/opt/bin/gmsh")

    def fake_run(cmd, **kwargs):
        out_path.write_text(_SAMPLE_INP_MM, encoding="utf-8")
        assert cmd == [
            "/opt/bin/gmsh",
            str(step_path),
            "-3",
            "-format",
            "inp",
            "-order",
            "1",
            "-clmax",
            "50.0",
            "-o",
            str(out_path),
        ]
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(gmsh_runner.subprocess, "run", fake_run)

    assert (
        mesh_step_to_inp(
            step_path,
            out_path,
            cfg,
            named_points=[NamedPoint("TIP", (0.0, 16.5, 0.0))],
        )
        == out_path
    )
    nsets = parse_nset_from_inp(out_path)
    assert nsets.get("TIP") == [4]


def test_mesh_step_accepts_partial_mesh_when_gmsh_writes_elements(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.hi_fidelity.gmsh.enabled = True
    step_path = tmp_path / "part.step"
    out_path = tmp_path / "mesh.inp"
    step_path.write_text("STEP", encoding="utf-8")
    monkeypatch.setattr(gmsh_runner, "find_gmsh", lambda _cfg: "/opt/bin/gmsh")

    def fake_run(cmd, **kwargs):
        out_path.write_text(_SAMPLE_INP, encoding="utf-8")
        return type("Result", (), {"returncode": 1, "stdout": "warn", "stderr": "warn"})()

    monkeypatch.setattr(gmsh_runner.subprocess, "run", fake_run)

    assert mesh_step_to_inp(step_path, out_path, cfg) == out_path
    assert inp_element_count(out_path) == 1


# --- NamedPoint / NSET annotation ---------------------------------------


_SAMPLE_INP = """\
*HEADING
test
*NODE
1, 0.0, 0.0, 0.0
2, 0.0, 1.5, 0.0
3, 0.0, 4.5, 0.0
4, 0.0, 16.5, 0.0
*ELEMENT, TYPE=C3D4, ELSET=EALL
1, 1, 2, 3, 4
"""

_OFFSET_SPANWISE_INP = """\
*HEADING
offset-spanwise
*NODE
1, 250.0, 0.000001, 30.0
2, 260.0, 0.0000015, 32.0
3, 300.0, 1500.0, 40.0
4, 120.0, 7500.0, 450.0
5, 90.0, 16500.0, 900.0
*ELEMENT, TYPE=C3D4, ELSET=EALL
1, 1, 2, 4, 5
"""

_SURFACE_MESH_WITH_DUPLICATE_FACETS = """\
*NODE
1, 0.0, 0.0, 0.0
2, 1.0, 0.0, 0.0
3, 0.0, 1.0, 0.0
4, 0.0, 0.0, 1.0
*ELEMENT, TYPE=CPS3, ELSET=SURF
10, 1, 2, 3
11, 3, 2, 1
12, 1, 3, 4
"""

_GMSH_PROBE_LOG = """\
Info    : 98 triangles are equivalent
Warning : 4 elements remain invalid in surface 24
Warning : Invalid boundary mesh (overlapping facets) on surface 99 surface 99
Warning : No elements in volume 1 2
Info    : Found two duplicated facets.
"""


def test_annotate_inp_writes_nset_blocks(tmp_path: Path) -> None:
    inp = tmp_path / "mesh.inp"
    inp.write_text(_SAMPLE_INP, encoding="utf-8")

    written = annotate_inp_with_named_points(
        inp,
        [
            NamedPoint("ROOT", (0.0, 0.0, 0.0)),
            NamedPoint("TIP", (0.0, 16.5, 0.0)),
            NamedPoint("WIRE_1", (0.0, 1.5, 0.0)),
        ],
        default_tol_m=1.0e-3,
    )
    assert written == ["ROOT", "TIP", "WIRE_1"]

    text = inp.read_text(encoding="utf-8")
    assert "*NSET, NSET=ROOT" in text
    assert "*NSET, NSET=TIP" in text
    assert "*NSET, NSET=WIRE_1" in text
    # NSET blocks must sit before the first *ELEMENT block so CalculiX
    # parses them in the part section.
    assert text.index("*NSET, NSET=ROOT") < text.index("*ELEMENT")

    nsets = parse_nset_from_inp(inp)
    assert nsets["ROOT"] == [1]
    assert nsets["TIP"] == [4]
    assert nsets["WIRE_1"] == [2]


def test_annotate_inp_skips_out_of_tolerance(tmp_path: Path, capsys) -> None:
    inp = tmp_path / "mesh.inp"
    inp.write_text(_SAMPLE_INP, encoding="utf-8")

    written = annotate_inp_with_named_points(
        inp,
        [NamedPoint("MISSING", (10.0, 0.0, 0.0), tol_m=1.0e-3)],
        default_tol_m=1.0e-3,
    )
    assert written == []
    captured = capsys.readouterr()
    assert "NamedPoint 'MISSING' unmatched" in captured.out
    assert "*NSET, NSET=MISSING" not in inp.read_text(encoding="utf-8")


def test_annotate_inp_supports_spanwise_matching_modes(tmp_path: Path) -> None:
    inp = tmp_path / "offset_mesh.inp"
    inp.write_text(_OFFSET_SPANWISE_INP, encoding="utf-8")

    written = annotate_inp_with_named_points(
        inp,
        [
            NamedPoint("ROOT", (0.0, 0.0, 0.0), match_mode="spanwise_plane_y"),
            NamedPoint("WIRE_1", (0.0, 7500.0, 0.0), match_mode="nearest_spanwise_y"),
            NamedPoint("TIP", (0.0, 16500.0, 0.0), match_mode="nearest_spanwise_y"),
        ],
        default_tol_m=1.0,
    )

    assert written == ["ROOT", "WIRE_1", "TIP"]
    nsets = parse_nset_from_inp(inp)
    assert nsets["ROOT"] == [1, 2]
    assert nsets["WIRE_1"] == [4]
    assert nsets["TIP"] == [5]


def test_mesh_step_annotates_named_points(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.hi_fidelity.gmsh.enabled = True
    cfg.hi_fidelity.gmsh.mesh_size_m = 0.05
    cfg.hi_fidelity.gmsh.point_tol_m = 1.0e-3
    step_path = tmp_path / "part.step"
    out_path = tmp_path / "mesh.inp"
    step_path.write_text("STEP", encoding="utf-8")
    monkeypatch.setattr(gmsh_runner, "find_gmsh", lambda _cfg: "/opt/bin/gmsh")

    def fake_run(cmd, **kwargs):
        out_path.write_text(_SAMPLE_INP, encoding="utf-8")
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(gmsh_runner.subprocess, "run", fake_run)

    assert (
        mesh_step_to_inp(
            step_path,
            out_path,
            cfg,
            named_points=[
                NamedPoint("ROOT", (0.0, 0.0, 0.0)),
                NamedPoint("TIP", (0.0, 16.5, 0.0)),
            ],
        )
        == out_path
    )
    nsets = parse_nset_from_inp(out_path)
    assert nsets.get("ROOT") == [1]
    assert nsets.get("TIP") == [4]


def test_collect_mesh_diagnostics_parses_gmsh_log_and_duplicate_facets(tmp_path: Path) -> None:
    inp = tmp_path / "surface.inp"
    inp.write_text(_SURFACE_MESH_WITH_DUPLICATE_FACETS, encoding="utf-8")

    diagnostics = collect_mesh_diagnostics(
        inp,
        gmsh_returncode=1,
        gmsh_stdout=_GMSH_PROBE_LOG,
    )

    assert diagnostics.element_count == 3
    assert diagnostics.gmsh_returncode == 1
    assert diagnostics.duplicate_shell_facets == 1
    assert diagnostics.overlapping_boundary_mesh_count == 1
    assert diagnostics.no_elements_in_volume_count == 1
    assert diagnostics.equivalent_triangles_count == 98
    assert diagnostics.invalid_surface_elements_count == 4
    assert diagnostics.duplicate_boundary_facets_count == 2
    assert diagnostics.issue_hints == (
        "overlapping_boundary_mesh x1",
        "no_elements_in_volume x1",
        "duplicate_boundary_facets x2",
        "invalid_surface_elements x4",
        "equivalent_triangles x98",
        "duplicate_shell_facets x1",
    )


def test_mesh_step_writes_mesh_diagnostics_sidecar(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.hi_fidelity.gmsh.enabled = True
    step_path = tmp_path / "part.step"
    out_path = tmp_path / "mesh.inp"
    step_path.write_text("STEP", encoding="utf-8")
    monkeypatch.setattr(gmsh_runner, "find_gmsh", lambda _cfg: "/opt/bin/gmsh")

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_text(_SURFACE_MESH_WITH_DUPLICATE_FACETS, encoding="utf-8")
        return type(
            "Result",
            (),
            {
                "returncode": 1,
                "stdout": _GMSH_PROBE_LOG,
                "stderr": "",
            },
        )()

    monkeypatch.setattr(gmsh_runner.subprocess, "run", fake_run)

    assert mesh_step_to_inp(step_path, out_path, cfg) == out_path
    sidecar = mesh_diagnostics_sidecar_path(out_path)
    assert sidecar.exists()

    diagnostics = load_mesh_diagnostics(out_path)
    assert diagnostics is not None
    assert diagnostics.diagnostics_path == sidecar.resolve()
    assert diagnostics.duplicate_shell_facets == 1
    assert diagnostics.overlapping_boundary_mesh_count == 1
    assert diagnostics.attempt_count == 2
    assert diagnostics.mesh_size_m == cfg.hi_fidelity.gmsh.mesh_size_m


def test_mesh_step_retries_once_with_coarser_mesh_on_surface_blockers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    cfg.hi_fidelity.gmsh.enabled = True
    cfg.hi_fidelity.gmsh.mesh_size_m = 0.05
    step_path = tmp_path / "part.step"
    out_path = tmp_path / "mesh.inp"
    step_path.write_text("STEP", encoding="utf-8")
    monkeypatch.setattr(gmsh_runner, "find_gmsh", lambda _cfg: "/opt/bin/gmsh")

    clmax_values: list[str] = []

    def fake_run(cmd, **kwargs):
        clmax_values.append(cmd[8])
        candidate_out = Path(cmd[-1])
        if len(clmax_values) == 1:
            candidate_out.write_text(_SURFACE_MESH_WITH_DUPLICATE_FACETS, encoding="utf-8")
            return type(
                "Result",
                (),
                {
                    "returncode": 1,
                    "stdout": _GMSH_PROBE_LOG,
                    "stderr": "",
                },
            )()

        candidate_out.write_text(_SAMPLE_INP, encoding="utf-8")
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(gmsh_runner.subprocess, "run", fake_run)

    assert mesh_step_to_inp(step_path, out_path, cfg) == out_path
    assert clmax_values == ["0.05", "0.1"]
    assert out_path.exists()
    assert not (tmp_path / "mesh.attempt2.inp").exists()

    diagnostics = load_mesh_diagnostics(out_path)
    assert diagnostics is not None
    assert diagnostics.gmsh_returncode == 0
    assert diagnostics.mesh_size_m == 0.1
    assert diagnostics.attempt_index == 2
    assert diagnostics.attempt_count == 2
