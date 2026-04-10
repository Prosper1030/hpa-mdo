from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
import sys

import pytest

from hpa_mdo.core.config import HPAConfig, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "blackcat_004.yaml"
sys.path.insert(0, str(REPO_ROOT))

from scripts.internal_dual_beam_analysis import main as internal_dual_beam_main  # noqa: E402

pytestmark = [pytest.mark.slow, pytest.mark.requires_vspaero]


@dataclass(frozen=True)
class InternalDualBeamMetrics:
    mass_kg: float
    main_tip_mm: float
    max_uz_mm: float
    rear_tip_mm: float
    max_uz_spar: str
    max_uz_node: int
    rear_main_tip_ratio: float


@dataclass(frozen=True)
class InternalDualBeamBaseline:
    cfg: HPAConfig
    report_text: str
    report_path: Path
    metrics: InternalDualBeamMetrics


def _extract_scalar(report_text: str, label: str) -> float:
    pattern = re.compile(rf"{re.escape(label)}\s*:\s*([+-]?\d+(?:\.\d+)?)")
    match = pattern.search(report_text)
    assert match is not None, f"Could not find metric '{label}' in report."
    return float(match.group(1))


def _parse_metrics(report_text: str) -> InternalDualBeamMetrics:
    main_tip_mm = _extract_scalar(report_text, "Tip deflection main (mm)")
    rear_tip_mm = _extract_scalar(report_text, "Tip deflection rear (mm)")
    max_uz_mm = _extract_scalar(report_text, "Max |UZ| anywhere (mm)")
    mass_kg = _extract_scalar(report_text, "Spar mass full-span")

    loc_match = re.search(
        r"Max \|UZ\| location\s*:\s*(main|rear)\s+node\s+(\d+)",
        report_text,
    )
    assert loc_match is not None, "Could not parse 'Max |UZ| location' from report."
    max_uz_spar = loc_match.group(1)
    max_uz_node = int(loc_match.group(2))

    return InternalDualBeamMetrics(
        mass_kg=mass_kg,
        main_tip_mm=main_tip_mm,
        max_uz_mm=max_uz_mm,
        rear_tip_mm=rear_tip_mm,
        max_uz_spar=max_uz_spar,
        max_uz_node=max_uz_node,
        rear_main_tip_ratio=rear_tip_mm / max(main_tip_mm, 1e-12),
    )


@pytest.fixture(scope="module")
def internal_dual_beam_baseline(tmp_path_factory: pytest.TempPathFactory) -> InternalDualBeamBaseline:
    cfg = load_config(CONFIG_PATH)
    missing_assets = [
        str(path)
        for path in (cfg.io.vsp_lod, cfg.io.vsp_polar)
        if path is not None and not Path(path).exists()
    ]
    if missing_assets:
        pytest.skip(
            "Missing VSPAero assets required for internal dual-beam regression test: "
            + ", ".join(missing_assets)
        )

    output_dir = tmp_path_factory.mktemp("internal_dual_beam_regression")
    exit_code = internal_dual_beam_main(
        [
            "--config",
            str(CONFIG_PATH),
            "--output-dir",
            str(output_dir),
            "--optimizer-method",
            "openmdao",
        ]
    )
    assert exit_code == 0

    report_path = output_dir / "dual_beam_internal_report.txt"
    assert report_path.exists(), f"Expected report was not created: {report_path}"
    report_text = report_path.read_text(encoding="utf-8")
    metrics = _parse_metrics(report_text)

    return InternalDualBeamBaseline(
        cfg=cfg,
        report_text=report_text,
        report_path=report_path,
        metrics=metrics,
    )


def test_internal_dual_beam_baseline_run_completes(
    internal_dual_beam_baseline: InternalDualBeamBaseline,
) -> None:
    report_text = internal_dual_beam_baseline.report_text
    assert "Internal Dual-Beam Analysis Report" in report_text
    assert "internal analysis-only dual-beam path (non-gating)" in report_text
    assert "No ANSYS comparison requested." in report_text


def test_internal_dual_beam_key_metrics_exist_and_are_finite(
    internal_dual_beam_baseline: InternalDualBeamBaseline,
) -> None:
    metrics = internal_dual_beam_baseline.metrics
    for value in (
        metrics.mass_kg,
        metrics.main_tip_mm,
        metrics.max_uz_mm,
        metrics.rear_tip_mm,
    ):
        assert math.isfinite(value)
        assert value > 0.0

    # Wide regression bands: catch broken behavior without overfitting decimals.
    assert 7.0 <= metrics.mass_kg <= 14.0
    assert 2000.0 <= metrics.main_tip_mm <= 4000.0
    assert 2200.0 <= metrics.max_uz_mm <= 4500.0
    assert 2200.0 <= metrics.rear_tip_mm <= 4500.0


def test_internal_dual_beam_preserves_rear_outboard_amplification(
    internal_dual_beam_baseline: InternalDualBeamBaseline,
) -> None:
    baseline = internal_dual_beam_baseline
    metrics = baseline.metrics

    assert metrics.max_uz_mm >= metrics.main_tip_mm
    assert metrics.max_uz_spar == "rear"
    assert metrics.max_uz_node >= int(0.75 * baseline.cfg.solver.n_beam_nodes)

    assert metrics.rear_tip_mm > metrics.main_tip_mm
    assert 1.08 <= metrics.rear_main_tip_ratio <= 1.40
