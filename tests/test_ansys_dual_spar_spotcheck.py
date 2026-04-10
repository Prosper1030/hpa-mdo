from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.ansys_compare_results import AnsysMetrics, BaselineMetrics  # noqa: E402
from scripts.ansys_dual_spar_spotcheck import (  # noqa: E402
    CONSISTENT,
    MODEL_FORM_RISK,
    NOTICEABLE,
    _build_rows,
    _overall_classification,
    build_spotcheck_report,
)


def _baseline() -> BaselineMetrics:
    return BaselineMetrics(
        tip_deflection_mm=100.0,
        max_uz_mm=110.0,
        max_vm_main_mpa=50.0,
        max_vm_rear_mpa=40.0,
        root_reaction_fz_n=500.0,
        max_twist_deg=1.0,
        total_spar_mass_kg=3.0,
        tip_node=10,
        nodes_per_spar=10,
        export_mode="dual_spar",
    )


def test_dual_spar_spotcheck_classifies_consistent_response(tmp_path: Path) -> None:
    ansys = AnsysMetrics(
        tip_deflection_mm=103.0,
        max_uz_mm=113.0,
        root_reaction_fz_n=504.0,
        total_spar_mass_kg=3.02,
    )

    rows = _build_rows(_baseline(), ansys)
    assert _overall_classification(rows) == CONSISTENT

    report = build_spotcheck_report(
        _baseline(),
        ansys,
        ansys_dir=tmp_path,
        rst_path=tmp_path / "file.rst",
    )
    assert "Phase I gate    : disabled for this workflow" in report
    assert "Overall model-form assessment: CONSISTENT" in report
    assert "Stress remains provisional/non-gating" in report
    assert "PASS" not in report
    assert "FAIL" not in report


def test_dual_spar_spotcheck_classifies_noticeable_discrepancy() -> None:
    ansys = AnsysMetrics(
        tip_deflection_mm=108.0,
        max_uz_mm=118.0,
        root_reaction_fz_n=504.0,
        total_spar_mass_kg=3.02,
    )

    assert _overall_classification(_build_rows(_baseline(), ansys)) == NOTICEABLE


def test_dual_spar_spotcheck_classifies_model_form_risk() -> None:
    ansys = AnsysMetrics(
        tip_deflection_mm=125.0,
        max_uz_mm=140.0,
        root_reaction_fz_n=530.0,
        total_spar_mass_kg=3.02,
    )

    assert _overall_classification(_build_rows(_baseline(), ansys)) == MODEL_FORM_RISK
