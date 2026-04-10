from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.ansys_compare_results import (  # noqa: E402
    AnsysMetrics,
    BaselineMetrics,
    _extract_mass_from_mac,
    build_report_text,
)


def _baseline(export_mode: str) -> BaselineMetrics:
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
        export_mode=export_mode,
    )


def test_equivalent_beam_report_gates_only_phase_i_metrics(tmp_path: Path) -> None:
    ansys = AnsysMetrics(
        tip_deflection_mm=102.0,
        max_uz_mm=113.0,
        max_vm_main_mpa=999.0,
        max_vm_rear_mpa=None,
        root_reaction_fz_n=503.0,
        max_twist_deg=None,
        total_spar_mass_kg=3.02,
    )

    report = build_report_text(
        _baseline("equivalent_beam"),
        ansys,
        threshold_pct=5.0,
        ansys_dir=tmp_path,
        rst_path=tmp_path / "file.rst",
    )

    assert "Phase I gate    : equivalent-beam validation metrics only" in report
    assert "Overall verdict: PASS" in report
    assert "Max Von Mises rear spar (MPa)" in report
    assert "N/A" in report
    assert "Stress note: ANSYS beam stress extraction is provisional here." in report
    assert "Python von Mises bug" in report


def test_equivalent_beam_report_fails_true_validation_gate(tmp_path: Path) -> None:
    ansys = AnsysMetrics(
        tip_deflection_mm=102.0,
        max_uz_mm=113.0,
        root_reaction_fz_n=520.0,
        total_spar_mass_kg=3.02,
    )

    report = build_report_text(
        _baseline("equivalent_beam"),
        ansys,
        threshold_pct=5.0,
        ansys_dir=tmp_path,
        rst_path=tmp_path / "file.rst",
    )

    assert "Overall verdict: FAIL" in report
    assert "Support reaction Fz (all supports)" in report
    assert "Equivalent nodal load mismatch" in report


def test_dual_spar_report_is_inspection_only(tmp_path: Path) -> None:
    ansys = AnsysMetrics(
        tip_deflection_mm=300.0,
        max_uz_mm=330.0,
        root_reaction_fz_n=700.0,
        total_spar_mass_kg=6.0,
    )

    report = build_report_text(
        _baseline("dual_spar"),
        ansys,
        threshold_pct=5.0,
        ansys_dir=tmp_path,
        rst_path=tmp_path / "file.rst",
    )

    assert "Phase I gate    : disabled" in report
    assert "Overall verdict: INFO ONLY" in report
    assert "not Phase I validation failures" in report


def test_apdl_mass_extraction_supports_equivalent_asec_sections(tmp_path: Path) -> None:
    mac_path = tmp_path / "spar_model.mac"
    mac_path.write_text(
        "\n".join(
            [
                "MP,DENS,1,10.0",
                "K,1, 0.0, 0.0, 0.0",
                "K,2, 0.0, 2.0, 0.0",
                "L,1,2",
                "SECTYPE,1,BEAM,ASEC",
                "SECDATA,1.00000000e-02,1.0e-04,0.0,1.0e-04,0.0,2.0e-04",
                "LSEL,S,LINE,,1",
                "LATT,1,,1,,,,1",
            ]
        ),
        encoding="utf-8",
    )

    assert _extract_mass_from_mac(mac_path) == 0.4
