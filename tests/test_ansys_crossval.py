from __future__ import annotations

from pathlib import Path
import re
import sys

import numpy as np
import pytest

from hpa_mdo.core.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "blackcat_004.yaml"
sys.path.insert(0, str(REPO_ROOT))

from scripts.ansys_crossval import (  # noqa: E402
    CrossValidationPackage,
    generate_cross_validation_package,
)


def _extract_metric_value(report_text: str, metric_label: str, unit: str) -> float:
    pattern = re.compile(
        rf"{re.escape(metric_label)}\s+([+-]?\d+(?:\.\d+)?)\s+{re.escape(unit)}"
    )
    match = pattern.search(report_text)
    assert match is not None, f"Could not find metric '{metric_label}' in report."
    return float(match.group(1))


@pytest.fixture(scope="module")
def crossval_package(tmp_path_factory: pytest.TempPathFactory) -> CrossValidationPackage:
    cfg = load_config(CONFIG_PATH)
    missing_assets = [
        str(path)
        for path in (cfg.io.vsp_lod, cfg.io.vsp_polar)
        if path is not None and not Path(path).exists()
    ]
    if missing_assets:
        pytest.skip(
            "Missing VSPAero test assets required for ANSYS cross-validation: "
            + ", ".join(missing_assets)
        )

    output_dir = tmp_path_factory.mktemp("ansys_crossval")
    return generate_cross_validation_package(
        config_path=CONFIG_PATH,
        output_dir=output_dir,
        n_beam_nodes=20,
        optimizer_maxiter=60,
    )


@pytest.mark.requires_vspaero
def test_crossval_report_generation(crossval_package: CrossValidationPackage) -> None:
    ansys_dir = crossval_package.ansys_dir
    apdl_path = ansys_dir / "spar_model.mac"
    bdf_path = ansys_dir / "spar_model.bdf"
    csv_path = ansys_dir / "spar_data.csv"
    report_path = ansys_dir / "crossval_report.txt"

    for path in (apdl_path, bdf_path, csv_path, report_path):
        assert path.exists(), f"Expected output file was not created: {path}"

    report_text = report_path.read_text(encoding="utf-8")
    required_metrics = [
        "Export mode: equivalent_beam",
        "equivalent-beam validation mode",
        "Phase I gate: YES",
        "Tip deflection (uz, y=",
        "Max uz anywhere",
        "Max Von Mises (main spar)",
        "Max Von Mises (rear spar)",
        "Root reaction Fz",
        "Max twist angle",
        "Spar tube mass (full-span)",
    ]
    for metric in required_metrics:
        assert metric in report_text

    tip_deflection_mm = _extract_metric_value(report_text, "Tip deflection (uz, y=16.5m)", "mm")
    max_vm_main_mpa = _extract_metric_value(report_text, "Max Von Mises (main spar)", "MPa")
    mass_full_kg = _extract_metric_value(report_text, "Spar tube mass (full-span)", "kg")

    assert 0.0 < tip_deflection_mm < 5000.0
    assert 0.0 < max_vm_main_mpa < 2000.0
    assert abs(mass_full_kg - crossval_package.result.spar_mass_full_kg) <= 0.01

    apdl_lines = apdl_path.read_text(encoding="utf-8").splitlines()
    bdf_lines = bdf_path.read_text(encoding="utf-8").splitlines()
    exporter = crossval_package.exporter
    nn = exporter.nn
    assert exporter.mode == "equivalent_beam"

    # APDL keypoints: 1..nn for the single equivalent FEM beam.
    keypoint_ids = []
    for line in apdl_lines:
        match = re.match(r"^K,(\d+),", line.strip())
        if match:
            keypoint_ids.append(int(match.group(1)))
    assert len(keypoint_ids) == nn
    assert sorted(keypoint_ids) == list(range(1, nn + 1))

    # APDL ASEC sections should map 1:1 to equivalent FEM elements.
    secdata_rows = []
    for line in apdl_lines:
        match = re.match(
            r"^SECDATA,([+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?),"
            r"([+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?),"
            r"([+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?),"
            r"([+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?),"
            r"([+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?),"
            r"([+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)",
            line.strip(),
        )
        if match:
            secdata_rows.append(tuple(float(match.group(i)) for i in range(1, 7)))
    assert len(secdata_rows) == nn - 1

    expected_rows = []
    section = exporter.equivalent_section
    for j in range(nn - 1):
        expected_rows.append(
            (
                section.A_equiv[j],
                section.Iy_equiv[j],
                0.0,
                section.Iz_equiv[j],
                0.0,
                section.J_equiv[j],
            )
        )

    np.testing.assert_allclose(secdata_rows, expected_rows, rtol=0.0, atol=1e-10)

    # Equivalent material cards should match the back-computed internal FEM E/G.
    mp_values: dict[tuple[str, int], float] = {}
    for line in apdl_lines:
        match = re.match(
            r"^MP,(EX|GXY|DENS|PRXY),(\d+),([+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)",
            line.strip(),
        )
        if match:
            mp_values[(match.group(1), int(match.group(2)))] = float(match.group(3))

    assert len({mat_id for _, mat_id in mp_values}) == nn - 1
    np.testing.assert_allclose(mp_values[("EX", 1)], exporter.equivalent_E[0], rtol=1e-6)
    np.testing.assert_allclose(mp_values[("GXY", 1)], exporter.equivalent_G[0], rtol=1e-6)
    np.testing.assert_allclose(
        mp_values[("DENS", 1)], exporter.equivalent_density[0], rtol=1e-6
    )

    # Root BC and wire constraints should exist on the equivalent beam nodes.
    assert any(line.strip().startswith("DK,1,ALL,0") for line in apdl_lines)
    assert not any(line.strip().startswith(f"DK,{nn + 1},ALL,0") for line in apdl_lines)
    for wire_node in exporter.wire_nodes:
        assert any(line.strip().startswith(f"DK,{wire_node + 1},UZ,0") for line in apdl_lines)

    # BDF completeness: GRID/CBAR/PBAR counts for equivalent beam.
    grid_count = sum(1 for line in bdf_lines if line.startswith("GRID,"))
    cbar_count = sum(1 for line in bdf_lines if line.startswith("CBAR,"))
    pbar_count = sum(1 for line in bdf_lines if line.startswith("PBAR,"))
    assert grid_count == nn
    assert cbar_count == nn - 1
    assert pbar_count == nn - 1


@pytest.mark.requires_vspaero
def test_apdl_force_equilibrium(crossval_package: CrossValidationPackage) -> None:
    """Sum of equivalent FK,*,FZ loads matches internal FEM nodal load total."""
    apdl_text = crossval_package.apdl_path.read_text(encoding="utf-8")
    fz_values = []
    for line in apdl_text.splitlines():
        match = re.match(
            r"^FK,\s*\d+\s*,\s*FZ,\s*([+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)",
            line.strip(),
        )
        if match:
            fz_values.append(float(match.group(1)))

    assert fz_values, "No FK,*,FZ loads found in generated APDL macro."
    total_apdl_fz = float(np.sum(fz_values))
    expected_total_fz = float(crossval_package.exporter.equivalent_total_fz_n)

    rel_err = abs(total_apdl_fz - expected_total_fz) / max(abs(expected_total_fz), 1.0)
    assert rel_err <= 0.01, (
        f"APDL force equilibrium mismatch: FK sum={total_apdl_fz:.6f} N, "
        f"expected total Fz={expected_total_fz:.6f} N, rel_err={rel_err:.6%}"
    )
