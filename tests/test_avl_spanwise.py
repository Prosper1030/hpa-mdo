from __future__ import annotations

from pathlib import Path
import textwrap

import numpy as np

from hpa_mdo.aero import (
    LoadMapper,
    build_spanwise_load_from_avl_strip_forces,
    load_candidate_avl_spanwise_artifact,
    parse_avl_strip_forces,
    write_candidate_avl_spanwise_artifact,
)


def _write_demo_avl(path: Path) -> Path:
    path.write_text(
        textwrap.dedent(
            """\
            Demo AVL Wing
            #Mach
            0.000000
            #IYsym  iZsym  Zsym
            0  0  0.000000
            #Sref  Cref  Bref
            6.000000  1.000000  4.000000
            #Xref  Yref  Zref
            0.000000  0.000000  0.000000
            #CDp
            0.000000
            SURFACE
            Wing
            12  1.0  4  -2.0
            YDUPLICATE
            0.0
            SECTION
            0.000000  0.000000  0.000000  1.400000  0.000000
            NACA
            2412
            SECTION
            0.000000  2.000000  0.100000  1.000000  0.000000
            NACA
            2412
            SECTION
            0.000000  4.000000  0.200000  0.600000  0.000000
            NACA
            2412
            SURFACE
            Elevator
            8  1.0  2  -2.0
            SECTION
            1.000000  0.000000  0.000000  0.500000  0.000000
            NACA
            0012
            SECTION
            1.000000  1.000000  0.000000  0.400000  0.000000
            NACA
            0012
            """
        ),
        encoding="utf-8",
    )
    return path


def _fs_text(*, cl_values: tuple[float, float, float]) -> str:
    cl1, cl2, cl3 = cl_values
    return textwrap.dedent(
        f"""\
         ---------------------------------------------------------------
         Surface and Strip Forces by surface

          Sref =   6.000       Cref =   1.000       Bref =   4.000
          Xref =  0.0000       Yref =   0.0000       Zref =   0.0000

          Surface # 1     Wing
             # Chordwise = 12   # Spanwise = 4     First strip = 1

         Strip Forces referred to Strip Area, Chord
            j     Xle      Yle      Zle      Chord    Area     c_cl     ai     cl_norm    cl       cd       cdv    cm_c/4     cm_LE   C.P.x/c
             1   0.0000   0.5000   0.0200   1.2500   0.6000   1.0000   0.0000   {cl1:.4f}   {cl1:.4f}   0.0200   0.0000  -0.0500  -0.1000    0.250
             2   0.0000   2.0000   0.1000   1.0000   0.5000   1.0000   0.0000   {cl2:.4f}   {cl2:.4f}   0.0210   0.0000  -0.0450  -0.0900    0.250
             3   0.0000   3.5000   0.1800   0.6500   0.4000   1.0000   0.0000   {cl3:.4f}   {cl3:.4f}   0.0230   0.0000  -0.0400  -0.0800    0.250

          Surface # 2     Wing (YDUP)
             # Chordwise = 12   # Spanwise = 4     First strip = 4

         Strip Forces referred to Strip Area, Chord
            j     Xle      Yle      Zle      Chord    Area     c_cl     ai     cl_norm    cl       cd       cdv    cm_c/4     cm_LE   C.P.x/c
             4   0.0000  -0.5000   0.0200   1.2500   0.6000   1.0000   0.0000   {cl1:.4f}   {cl1:.4f}   0.0200   0.0000  -0.0500   0.1000    0.250
             5   0.0000  -2.0000   0.1000   1.0000   0.5000   1.0000   0.0000   {cl2:.4f}   {cl2:.4f}   0.0210   0.0000  -0.0450   0.0900    0.250
             6   0.0000  -3.5000   0.1800   0.6500   0.4000   1.0000   0.0000   {cl3:.4f}   {cl3:.4f}   0.0230   0.0000  -0.0400   0.0800    0.250

          Surface # 3     Elevator
             # Chordwise = 8   # Spanwise = 2     First strip = 7

         Strip Forces referred to Strip Area, Chord
            j     Xle      Yle      Zle      Chord    Area     c_cl     ai     cl_norm    cl       cd       cdv    cm_c/4     cm_LE   C.P.x/c
             7   1.0000   0.6000   0.0000   0.4500   0.2000   1.0000   0.0000   0.5000   0.5000   0.0300   0.0000  -0.0200  -0.0400    0.250
         ---------------------------------------------------------------
        """
    )


def test_parse_avl_strip_forces_selects_positive_main_wing_only(tmp_path: Path) -> None:
    fs_path = tmp_path / "candidate.fs"
    fs_path.write_text(_fs_text(cl_values=(0.82, 0.90, 0.74)), encoding="utf-8")

    parsed = parse_avl_strip_forces(fs_path)

    assert parsed["reference_values"]["sref_m2"] == 6.0
    assert len(parsed["strips"]) == 3
    assert [strip["strip_index"] for strip in parsed["strips"]] == [1, 2, 3]
    assert all(strip["y_le_m"] > 0.0 for strip in parsed["strips"])


def test_build_spanwise_load_from_avl_strip_forces_pads_root_and_tip(tmp_path: Path) -> None:
    avl_path = _write_demo_avl(tmp_path / "candidate.avl")
    fs_path = tmp_path / "candidate.fs"
    fs_path.write_text(_fs_text(cl_values=(0.82, 0.90, 0.74)), encoding="utf-8")

    load = build_spanwise_load_from_avl_strip_forces(
        fs_path=fs_path,
        avl_path=avl_path,
        aoa_deg=11.5,
        velocity_mps=6.5,
        density_kgpm3=1.225,
    )

    np.testing.assert_allclose(load.y, np.array([0.0, 0.5, 2.0, 3.5, 4.0]))
    np.testing.assert_allclose(load.chord, np.array([1.4, 1.25, 1.0, 0.65, 0.6]))
    assert np.all(np.diff(load.y) > 0.0)
    assert np.all(load.chord > 0.0)
    q = 0.5 * 1.225 * 6.5**2
    np.testing.assert_allclose(load.lift_per_span, q * load.chord * load.cl)
    np.testing.assert_allclose(load.drag_per_span, q * load.chord * load.cd)


def test_candidate_avl_spanwise_artifact_roundtrip_maps_full_beam_span(tmp_path: Path) -> None:
    avl_path = _write_demo_avl(tmp_path / "candidate.avl")
    fs_lo = tmp_path / "aoa_10p0.fs"
    fs_hi = tmp_path / "aoa_12p0.fs"
    fs_lo.write_text(_fs_text(cl_values=(0.76, 0.84, 0.70)), encoding="utf-8")
    fs_hi.write_text(_fs_text(cl_values=(0.88, 0.96, 0.78)), encoding="utf-8")
    artifact_path = tmp_path / "candidate_avl_spanwise.json"

    write_candidate_avl_spanwise_artifact(
        artifact_path,
        avl_path=avl_path,
        candidate_output_dir=tmp_path,
        requested_knobs={"target_shape_z_scale": 4.0, "dihedral_exponent": 2.2},
        selected_cruise_aoa_deg=12.0,
        velocity_mps=6.5,
        density_kgpm3=1.225,
        load_case_specs=[
            {"aoa_deg": 10.0, "fs_path": fs_lo, "stdout_log_path": tmp_path / "aoa_10p0.log"},
            {"aoa_deg": 12.0, "fs_path": fs_hi, "stdout_log_path": tmp_path / "aoa_12p0.log"},
        ],
        trim_force_path=tmp_path / "trim.ft",
        trim_stdout_log_path=tmp_path / "trim_stdout.log",
    )

    payload, cases = load_candidate_avl_spanwise_artifact(artifact_path)

    assert payload["selected_cruise_aoa_deg"] == 12.0
    assert payload["selected_cruise_aoa_source"] == "outer_loop_avl_trim"
    assert payload["selected_load_state_owner"] == "outer_loop_avl_trim_and_gates"
    assert payload["boundary_padding"] == "nearest_strip_coefficients_with_avl_root_tip_chord"
    assert [round(case.aoa_deg, 3) for case in cases] == [10.0, 12.0]

    mapper = LoadMapper()
    mapped = mapper.map_loads(
        cases[1],
        np.array([0.0, 1.0, 2.0, 3.0, 4.0], dtype=float),
        actual_velocity=6.5,
        actual_density=1.225,
    )

    assert mapped["lift_per_span"][0] > 0.0
    assert mapped["lift_per_span"][-1] > 0.0
    assert mapped["chord"][0] == 1.4
    assert mapped["chord"][-1] == 0.6
