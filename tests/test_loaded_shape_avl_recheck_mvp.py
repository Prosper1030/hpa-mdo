from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from hpa_mdo.aero.base import SpanwiseLoad
from scripts.loaded_shape_avl_recheck_mvp import (
    aero_warning_flags,
    interpolate_loaded_main_z_to_sections,
    local_cl_re_rows,
    rewrite_wing_section_z,
    spanload_comparison_rows,
)


def _minimal_avl(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "Demo",
                "#Mach",
                "0.0",
                "#IYsym  iZsym  Zsym",
                "1 0 0.0",
                "#Sref  Cref  Bref",
                "10.0 1.0 20.0",
                "#Xref  Yref  Zref",
                "0.25 0.0 0.0",
                "#CDp",
                "0.0",
                "SURFACE",
                "Wing",
                "8 1.0 12 1.0",
                "SECTION",
                "0.0 0.0 0.00 1.00 2.0",
                "AFILE",
                "root.dat",
                "SECTION",
                "0.0 5.0 0.10 0.80 1.0",
                "AFILE",
                "mid.dat",
                "SECTION",
                "0.0 10.0 0.20 0.60 0.0",
                "AFILE",
                "tip.dat",
                "SURFACE",
                "Tail",
                "4 1.0 6 1.0",
                "SECTION",
                "1.0 0.0 9.00 0.50 0.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_interpolate_loaded_main_z_removes_beam_root_offset() -> None:
    rows = [
        {"Y_Position_m": "0.0", "Main_Z_m": "0.25"},
        {"Y_Position_m": "10.0", "Main_Z_m": "1.25"},
    ]

    z_values = interpolate_loaded_main_z_to_sections(
        loaded_rows=rows,
        section_y_m=[0.0, 5.0, 10.0],
    )

    assert z_values == pytest.approx((0.0, 0.5, 1.0))


def test_rewrite_wing_section_z_updates_only_wing_sections(tmp_path: Path) -> None:
    source = _minimal_avl(tmp_path / "source.avl")
    output = tmp_path / "loaded.avl"

    rewrite_wing_section_z(
        source_avl=source,
        output_avl=output,
        section_z_m=[0.0, 0.5, 1.0],
    )

    text = output.read_text(encoding="utf-8")
    assert "0.000000000  0.000000000  0.000000000  1.000000000  2.000000000" in text
    assert "0.000000000  5.000000000  0.500000000  0.800000000  1.000000000" in text
    assert "0.000000000  10.000000000  1.000000000  0.600000000  0.000000000" in text
    assert "1.0 0.0 9.00 0.50 0.0" in text


def test_local_cl_re_rows_keep_stall_margin_diagnostic_non_gate() -> None:
    load = SpanwiseLoad(
        y=np.asarray([0.0, 5.0, 10.0]),
        chord=np.asarray([1.0, 0.8, 0.6]),
        cl=np.asarray([0.55, 0.85, 1.05]),
        cd=np.asarray([0.010, 0.011, 0.012]),
        cm=np.asarray([-0.05, -0.06, -0.07]),
        lift_per_span=np.asarray([10.0, 12.0, 8.0]),
        drag_per_span=np.asarray([0.20, 0.25, 0.30]),
        aoa_deg=1.25,
        velocity=6.0,
        dynamic_pressure=21.6,
    )

    rows = local_cl_re_rows(
        case_label="case",
        span_m=20.0,
        spanwise_load=load,
        density_kgpm3=1.2,
        dynamic_viscosity_pa_s=1.8e-5,
        diagnostic_section_cl_limit=1.2,
        geometry_z_basis="main_beam_loaded_shape_proxy",
    )

    assert rows[-1]["eta"] == pytest.approx(1.0)
    assert rows[-1]["reynolds"] == pytest.approx(1.2 * 6.0 * 0.6 / 1.8e-5)
    assert rows[-1]["stall_margin_cl"] == pytest.approx(0.15)
    assert rows[-1]["stall_margin_basis"] == "diagnostic_constant_section_cl_limit_not_gate"
    assert rows[-1]["geometry_z_basis"] == "main_beam_loaded_shape_proxy"


def test_spanload_comparison_rows_report_local_and_integral_deltas() -> None:
    pre = SpanwiseLoad(
        y=np.asarray([0.0, 5.0, 10.0]),
        chord=np.asarray([1.0, 0.8, 0.6]),
        cl=np.asarray([0.50, 0.80, 1.00]),
        cd=np.asarray([0.010, 0.011, 0.012]),
        cm=np.asarray([-0.05, -0.06, -0.07]),
        lift_per_span=np.asarray([10.0, 12.0, 8.0]),
        drag_per_span=np.asarray([0.20, 0.25, 0.30]),
        aoa_deg=0.5,
        velocity=6.0,
        dynamic_pressure=21.6,
    )
    loaded = SpanwiseLoad(
        y=np.asarray([0.0, 5.0, 10.0]),
        chord=np.asarray([1.0, 0.8, 0.6]),
        cl=np.asarray([0.45, 0.82, 1.05]),
        cd=np.asarray([0.010, 0.011, 0.012]),
        cm=np.asarray([-0.05, -0.06, -0.07]),
        lift_per_span=np.asarray([9.0, 13.0, 8.5]),
        drag_per_span=np.asarray([0.20, 0.25, 0.30]),
        aoa_deg=0.6,
        velocity=6.0,
        dynamic_pressure=21.6,
    )

    rows = spanload_comparison_rows(
        case_label="case",
        span_m=20.0,
        pre_structure_load=pre,
        loaded_shape_load=loaded,
    )

    assert rows[1]["delta_cl_loaded_minus_pre"] == pytest.approx(0.02)
    assert rows[1]["delta_lift_per_span_npm"] == pytest.approx(1.0)
    assert math.isfinite(float(rows[1]["bending_proxy_loaded_shape_m"]))
    assert rows[1]["comparison_basis"] == "pre_structure_avl_vs_loaded_shape_avl"


def test_aero_warning_flags_keep_screening_caveats_explicit() -> None:
    flags = aero_warning_flags(
        {
            "loaded_shape_e_CDi": 1.01,
            "stall_margin_min": -0.02,
            "geometry_z_basis": "main_beam_loaded_shape_spar_data_root_offset_removed_as_avl_section_z_proxy",
        }
    )

    assert "superunit_loaded_shape_e_cdi_check_reference_convention" in flags
    assert "negative_diagnostic_stall_margin_not_gate" in flags
    assert "beam_line_z_proxy_not_aero_surface_truth" in flags
