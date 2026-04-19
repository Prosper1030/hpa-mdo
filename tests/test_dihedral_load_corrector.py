from __future__ import annotations

from pathlib import Path
import textwrap

import numpy as np

from hpa_mdo.aero.base import SpanwiseLoad
from hpa_mdo.aero.dihedral_load_corrector import (
    build_fixed_alpha_dihedral_corrected_case,
    load_fixed_alpha_dihedral_corrector_artifact,
    write_fixed_alpha_dihedral_corrector_artifact,
)


def _write_demo_avl(path: Path, *, tip_z: float) -> Path:
    path.write_text(
        textwrap.dedent(
            f"""\
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
            Main Wing
            12  1.0  4  -2.0
            YDUPLICATE
            0.0
            SECTION
            0.000000  0.000000  0.000000  1.400000  0.000000
            NACA
            2412
            SECTION
            0.000000  2.000000 {0.5 * tip_z:.6f}  1.000000  0.000000
            NACA
            2412
            SECTION
            0.000000  4.000000 {tip_z:.6f}  0.600000  0.000000
            NACA
            2412
            """
        ),
        encoding="utf-8",
    )
    return path


def _baseline_case() -> SpanwiseLoad:
    q = 0.5 * 1.225 * 6.5**2
    y = np.array([0.0, 1.0, 2.0, 3.0, 4.0], dtype=float)
    chord = np.array([1.4, 1.2, 1.0, 0.8, 0.6], dtype=float)
    cl = np.full_like(y, 1.0)
    cd = np.full_like(y, 0.02)
    cm = np.full_like(y, -0.05)
    return SpanwiseLoad(
        y=y,
        chord=chord,
        cl=cl,
        cd=cd,
        cm=cm,
        lift_per_span=q * chord * cl,
        drag_per_span=q * chord * cd,
        aoa_deg=0.0,
        velocity=6.5,
        dynamic_pressure=q,
    )


def test_fixed_alpha_dihedral_corrected_case_scales_lift_but_keeps_drag_and_moment(tmp_path: Path) -> None:
    baseline_avl = _write_demo_avl(tmp_path / "baseline.avl", tip_z=0.0)
    candidate_avl = _write_demo_avl(tmp_path / "candidate.avl", tip_z=2.0)
    baseline_case = _baseline_case()

    corrected_case, rows = build_fixed_alpha_dihedral_corrected_case(
        baseline_case=baseline_case,
        baseline_avl_path=baseline_avl,
        candidate_avl_path=candidate_avl,
    )

    expected_scale = np.cos(np.arctan2(1.0, 2.0)) ** 2
    np.testing.assert_allclose(corrected_case.lift_per_span[1:], baseline_case.lift_per_span[1:] * expected_scale)
    np.testing.assert_allclose(corrected_case.drag_per_span, baseline_case.drag_per_span)
    np.testing.assert_allclose(corrected_case.cm, baseline_case.cm)
    assert rows[-1]["candidate_gamma_deg"] > rows[-1]["baseline_gamma_deg"]
    assert rows[-1]["vertical_load_scale_factor"] < 1.0


def test_fixed_alpha_dihedral_corrector_artifact_roundtrip(tmp_path: Path) -> None:
    baseline_avl = _write_demo_avl(tmp_path / "baseline.avl", tip_z=0.0)
    candidate_avl = _write_demo_avl(tmp_path / "candidate.avl", tip_z=1.0)
    artifact_path = tmp_path / "candidate_fixed_alpha_loads.json"

    write_fixed_alpha_dihedral_corrector_artifact(
        artifact_path,
        baseline_case=_baseline_case(),
        baseline_avl_path=baseline_avl,
        candidate_avl_path=candidate_avl,
        requested_knobs={"target_shape_z_scale": 2.0, "dihedral_exponent": 1.0},
        fixed_design_alpha_deg=0.0,
        origin_vsp3_path=tmp_path / "origin.vsp3",
        baseline_output_dir=tmp_path / "origin_panel",
        baseline_lod_path=tmp_path / "origin_panel" / "origin.lod",
        baseline_polar_path=tmp_path / "origin_panel" / "origin.polar",
    )

    payload, cases = load_fixed_alpha_dihedral_corrector_artifact(artifact_path)

    assert payload["source_mode"] == "origin_vsp_fixed_alpha_corrector"
    assert payload["selected_cruise_aoa_source"] == "fixed_design_alpha"
    assert payload["correction_policy"]["drag_per_span"] == "preserve_origin_fixed_alpha_baseline"
    assert len(payload["correction_rows"]) == len(cases[0].y)
    assert payload["total_full_lift_n"] == 2.0 * payload["total_half_lift_n"]
    assert len(cases) == 1
