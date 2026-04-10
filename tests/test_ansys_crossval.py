from __future__ import annotations

from pathlib import Path
import re
import sys

import numpy as np
import pytest

from hpa_mdo.core.config import load_config
from hpa_mdo.core.materials import MaterialDB


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

    # APDL keypoints: 1..nn (main) and nn+1..2*nn (rear)
    keypoint_ids = []
    for line in apdl_lines:
        match = re.match(r"^K,(\d+),", line.strip())
        if match:
            keypoint_ids.append(int(match.group(1)))
    assert len(keypoint_ids) == 2 * nn
    assert sorted(keypoint_ids) == list(range(1, 2 * nn + 1))

    # APDL CTUBE sections should map 1:1 to elements for both spars.
    secdata_pairs = []
    for line in apdl_lines:
        match = re.match(
            r"^SECDATA,([+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?),"
            r"([+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)",
            line.strip(),
        )
        if match:
            secdata_pairs.append((float(match.group(1)), float(match.group(2))))
    assert len(secdata_pairs) == 2 * (nn - 1)

    expected_pairs = []
    for j in range(nn - 1):
        ro = 0.5 * (exporter.R_main[j] + exporter.R_main[j + 1])
        tw = 0.5 * (exporter.t_main[j] + exporter.t_main[j + 1])
        ri = max(ro - tw, 0.0)
        expected_pairs.append((ri, ro))
    for j in range(nn - 1):
        ro = 0.5 * (exporter.R_rear[j] + exporter.R_rear[j + 1])
        tw = 0.5 * (exporter.t_rear[j] + exporter.t_rear[j + 1])
        ri = max(ro - tw, 0.0)
        expected_pairs.append((ri, ro))

    np.testing.assert_allclose(secdata_pairs, expected_pairs, rtol=0.0, atol=1e-6)

    # Material cards in APDL should match data/materials.yaml values.
    mp_values: dict[tuple[str, int], float] = {}
    for line in apdl_lines:
        match = re.match(
            r"^MP,(EX|GXY|DENS|PRXY),(\d+),([+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)",
            line.strip(),
        )
        if match:
            mp_values[(match.group(1), int(match.group(2)))] = float(match.group(3))

    mat_db = MaterialDB()
    main_mat = mat_db.get(crossval_package.cfg.main_spar.material)
    rear_mat = mat_db.get(crossval_package.cfg.rear_spar.material)
    np.testing.assert_allclose(mp_values[("EX", 1)], main_mat.E, rtol=1e-12)
    np.testing.assert_allclose(mp_values[("GXY", 1)], main_mat.G, rtol=1e-12)
    np.testing.assert_allclose(mp_values[("DENS", 1)], main_mat.density, rtol=1e-12)
    np.testing.assert_allclose(mp_values[("EX", 2)], rear_mat.E, rtol=1e-12)
    np.testing.assert_allclose(mp_values[("GXY", 2)], rear_mat.G, rtol=1e-12)
    np.testing.assert_allclose(mp_values[("DENS", 2)], rear_mat.density, rtol=1e-12)

    # Root BC and wire constraints should exist on the expected nodes.
    assert any(line.strip().startswith("DK,1,ALL,0") for line in apdl_lines)
    assert any(line.strip().startswith(f"DK,{nn + 1},ALL,0") for line in apdl_lines)
    for wire_node in exporter.wire_nodes:
        assert any(line.strip().startswith(f"DK,{wire_node + 1},UZ,0") for line in apdl_lines)

    # BDF completeness: GRID/CBAR/PBARL counts.
    grid_count = sum(1 for line in bdf_lines if line.startswith("GRID,"))
    cbar_count = sum(1 for line in bdf_lines if line.startswith("CBAR,"))
    pbarl_count = sum(1 for line in bdf_lines if line.startswith("PBARL,"))
    assert grid_count == 2 * nn
    assert cbar_count == 2 * (nn - 1)
    assert pbarl_count == 2 * (nn - 1)


@pytest.mark.requires_vspaero
def test_apdl_force_equilibrium(crossval_package: CrossValidationPackage) -> None:
    """Sum of FK,*,FZ in APDL is approximately total lift (within 1%)."""
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
    expected_total_lift = float(crossval_package.export_loads["total_lift"])

    rel_err = abs(total_apdl_fz - expected_total_lift) / max(abs(expected_total_lift), 1.0)
    assert rel_err <= 0.01, (
        f"APDL force equilibrium mismatch: FK sum={total_apdl_fz:.6f} N, "
        f"expected total_lift={expected_total_lift:.6f} N, rel_err={rel_err:.6%}"
    )
