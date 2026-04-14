from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "blackcat_004.yaml"


def test_inverse_layup_tsai_wu_demo_writes_artifacts_with_supplied_envelope(tmp_path) -> None:
    summary_path = tmp_path / "inverse_summary.json"
    envelope_path = tmp_path / "strain_envelope.json"
    output_dir = tmp_path / "demo"
    selected = {
        "design_mm": {
            "main_t": [1.20, 1.10, 1.00, 0.95, 0.90, 0.85],
            "main_r": [35.0, 34.0, 33.0, 32.0, 31.0, 30.0],
            "rear_t": [0.90, 0.85, 0.80, 0.80, 0.80, 0.80],
            "rear_r": [22.0, 21.5, 21.0, 20.5, 20.0, 19.5],
        }
    }
    summary_path.write_text(
        json.dumps(
            {
                "config": str(CONFIG_PATH),
                "outcome": {"selected": selected},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    envelope_path.write_text(
        json.dumps(
            {
                "strain_envelope": {
                    "epsilon_x_absmax": [1.0e-4, 1.1e-4, 1.2e-4, 1.3e-4, 1.4e-4, 1.5e-4],
                    "kappa_absmax": [1.0e-3, 1.1e-3, 1.2e-3, 1.3e-3, 1.4e-3, 1.5e-3],
                    "torsion_rate_absmax": [
                        2.0e-3,
                        2.1e-3,
                        2.2e-3,
                        2.3e-3,
                        2.4e-3,
                        2.5e-3,
                    ],
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "inverse_layup_tsai_wu_demo.py"),
            "--summary",
            str(summary_path),
            "--strain-envelope",
            str(envelope_path),
            "--skip-structural-analysis",
            "--output-dir",
            str(output_dir),
        ],
        cwd=REPO_ROOT,
        check=True,
    )

    report_path = output_dir / "representative_layup_tsai_wu_report.txt"
    demo_summary_path = output_dir / "representative_layup_tsai_wu_summary.json"
    strain_path = output_dir / "openmdao_strain_envelope.json"

    report = report_path.read_text(encoding="utf-8")
    payload = json.loads(demo_summary_path.read_text(encoding="utf-8"))
    strain_payload = json.loads(strain_path.read_text(encoding="utf-8"))

    assert "Representative Inverse-Design -> Discrete Layup -> Tsai-Wu" in report
    assert "Tsai-Wu FI=" in report
    assert payload["manufacturing_gates_passed"] is True
    assert payload["spars"]["main_spar"]["manufacturing_gates"]["passed"] is True
    assert payload["spars"]["main_spar"]["segments"][0]["tsai_wu_summary"] is not None
    assert strain_payload["source"] == str(envelope_path.resolve())
