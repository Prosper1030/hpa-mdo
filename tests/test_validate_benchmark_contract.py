from __future__ import annotations

from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.validate_benchmark_contract import main  # noqa: E402


def _write_ai_json(path: Path, *, full_mass_kg: float, deflection_m: float, twist_deg: float) -> None:
    path.write_text(
        (
            "{\n"
            f'  "discrete_full_wing_mass_kg": {full_mass_kg},\n'
            '  "structural_recheck": {\n'
            f'    "tip_deflection_m": {deflection_m},\n'
            f'    "twist_max_deg": {twist_deg}\n'
            "  }\n"
            "}\n"
        ),
        encoding="utf-8",
    )


def _write_inp(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "*NODE",
                "1, 0, 0, 0",
                "2, 1000, 0, 0",
                "3, 0, 1000, 0",
                "*ELEMENT, TYPE=S3, ELSET=EALL",
                "1, 1, 2, 3",
                "*MATERIAL, NAME=MAT",
                "*DENSITY",
                "1.0e-6",
                "*SHELL SECTION, ELSET=EALL, MATERIAL=MAT",
                "10.0",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_dat(path: Path, *, total_fz_n: float) -> None:
    path.write_text(
        "\n".join(
            [
                "",
                " total force (fx,fy,fz) for set HPA_SUPPORT_ALL and time  0.1000000E+01",
                "",
                f"       0.000000E+00  0.000000E+00 {total_fz_n:.6E}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_frd(
    path: Path,
    *,
    main_uz_mm: float,
    rear_uz_mm: float,
) -> None:
    path.write_text(
        "\n".join(
            [
                "    2C",
                " -1      1 0.000000E+00 1.000000E+03 0.000000E+00",
                " -1      2 1.000000E+03 1.000000E+03 0.000000E+00",
                " -3",
                " -4  DISP        4    1",
                " -5  D1          1    2    1    0",
                " -5  D2          1    2    2    0",
                " -5  D3          1    2    3    0",
                " -5  ALL         1    2    0    0    1ALL",
                f" -1      1 0.000000E+00 0.000000E+00 {main_uz_mm:.6E}",
                f" -1      2 0.000000E+00 0.000000E+00 {rear_uz_mm:.6E}",
                " -3",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_validate_benchmark_contract_pass(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ai_json = tmp_path / "ai.json"
    inp_path = tmp_path / "case.inp"
    dat_path = tmp_path / "case.dat"
    frd_path = tmp_path / "case.frd"

    _write_ai_json(ai_json, full_mass_kg=10.0, deflection_m=0.02, twist_deg=1.0)
    _write_inp(inp_path)
    _write_dat(dat_path, total_fz_n=-100.0)
    _write_frd(frd_path, main_uz_mm=20.5, rear_uz_mm=37.955)

    exit_code = main(
        [
            "--ai-json",
            str(ai_json),
            "--ccx-inp",
            str(inp_path),
            "--ccx-dat",
            str(dat_path),
            "--ccx-frd",
            str(frd_path),
            "--reaction-reference-n",
            "100.0",
            "--main-tip-probe",
            "0.0,1.0,0.0",
            "--rear-tip-probe",
            "1.0,1.0,0.0",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "**OVERALL: PASS**" in captured.out


def test_validate_benchmark_contract_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ai_json = tmp_path / "ai.json"
    inp_path = tmp_path / "case.inp"
    dat_path = tmp_path / "case.dat"
    frd_path = tmp_path / "case.frd"
    load_csv = tmp_path / "loads.csv"

    _write_ai_json(ai_json, full_mass_kg=10.0, deflection_m=0.02, twist_deg=1.0)
    _write_inp(inp_path)
    _write_dat(dat_path, total_fz_n=-110.0)
    _write_frd(frd_path, main_uz_mm=25.0, rear_uz_mm=60.0)
    load_csv.write_text(
        "\n".join(
            [
                "y_m,main_x_m,main_z_m,main_fz_n,rear_x_m,rear_z_m,rear_fz_n",
                "1.0,0.0,0.0,60.0,1.0,0.0,40.0",
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--ai-json",
            str(ai_json),
            "--ccx-inp",
            str(inp_path),
            "--ccx-dat",
            str(dat_path),
            "--ccx-frd",
            str(frd_path),
            "--load-csv",
            str(load_csv),
            "--main-tip-probe",
            "0.0,1.0,0.0",
            "--rear-tip-probe",
            "1.0,1.0,0.0",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "FAIL" in captured.out
    assert "**OVERALL: FAIL**" in captured.out
