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
    parse_baseline_metrics,
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


def test_dual_beam_production_report_exposes_partitioned_reactions(tmp_path: Path) -> None:
    baseline = BaselineMetrics(
        tip_deflection_mm=2400.0,
        rear_tip_deflection_mm=3200.0,
        max_uz_mm=3200.0,
        max_vm_main_mpa=50.0,
        max_vm_rear_mpa=40.0,
        root_reaction_fz_n=820.0,
        root_main_reaction_fz_n=90.0,
        root_rear_reaction_fz_n=-120.0,
        wire_reaction_fz_n=-790.0,
        max_twist_deg=0.0,
        total_spar_mass_kg=9.45,
        tip_node=60,
        rear_tip_node=120,
        nodes_per_spar=60,
        wire_nodes=(28,),
        export_mode="dual_beam_production",
    )
    ansys = AnsysMetrics(
        tip_deflection_mm=2450.0,
        rear_tip_deflection_mm=3260.0,
        max_uz_mm=3260.0,
        root_reaction_fz_n=818.0,
        root_main_reaction_fz_n=88.0,
        root_rear_reaction_fz_n=-118.0,
        wire_reaction_fz_n=-788.0,
        total_spar_mass_kg=9.47,
        total_constrained_reaction_fz_n=-818.0,
        total_input_fz_n=818.0,
    )

    report = build_report_text(
        baseline,
        ansys,
        threshold_pct=5.0,
        ansys_dir=tmp_path,
        rst_path=tmp_path / "file.rst",
    )

    assert "Phase I gate    : disabled (dual-beam production ANSYS cross-check / inspection mode)" in report
    assert "Main tip deflection (mm)" in report
    assert "Rear tip deflection (mm)" in report
    assert "Root main reaction Fz (N)" in report
    assert "Wire reaction Fz total (N)" in report
    assert "Overall verdict: INFO ONLY" in report


def test_parse_production_baseline_metrics_reads_optional_partition_fields(tmp_path: Path) -> None:
    mac_path = tmp_path / "spar_model.mac"
    mac_path.write_text(
        "\n".join(
            [
                "! Nodes/spar  : 60",
                "DK,1,ALL,0",
                "DK,61,ALL,0",
                "DK,28,UZ,0",
            ]
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "crossval_report.txt"
    report_path.write_text(
        "\n".join(
            [
                "Export mode: dual_beam_production",
                "Main tip deflection (uz, y=tip)      2393.720 mm",
                "Rear tip deflection (uz, y=tip)      3228.430 mm",
                "Max uz anywhere                      3228.430 mm",
                "Max Von Mises (main spar)             10.000 MPa",
                "Max Von Mises (rear spar)             20.000 MPa",
                "Root main reaction Fz                 87.230 N",
                "Root rear reaction Fz               -116.270 N",
                "Wire reaction Fz total             -788.740 N",
                "Support reaction Fz all supports     817.783 N",
                "Max twist angle                        0.000 deg",
                "Spar tube mass (full-span)             9.454 kg",
                "  *GET,TIP_UZ,NODE,60,U,Z",
            ]
        ),
        encoding="utf-8",
    )

    baseline = parse_baseline_metrics(report_path, mac_path=mac_path)

    assert baseline.export_mode == "dual_beam_production"
    assert baseline.tip_deflection_mm == 2393.72
    assert baseline.rear_tip_deflection_mm == 3228.43
    assert baseline.root_main_reaction_fz_n == 87.23
    assert baseline.root_rear_reaction_fz_n == -116.27
    assert baseline.wire_reaction_fz_n == -788.74
    assert baseline.root_reaction_fz_n == 817.783
    assert baseline.rear_tip_node == 120
    assert baseline.wire_nodes == (28,)


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
