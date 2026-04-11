from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import export_dual_beam_step as dual_beam_step  # noqa: E402


def _selection_dict() -> dict[str, object]:
    return {
        "source": "catalog_grid",
        "message": "analysis complete",
        "analysis_succeeded": True,
        "tube_mass_kg": 10.281877336101518,
        "total_structural_mass_kg": 12.781877336101518,
        "raw_main_tip_m": 1.7763218073465168,
        "dual_displacement_limit_m": 2.5,
        "equivalent_failure_index": -0.56070592902846,
        "equivalent_buckling_index": -0.8166643405526651,
        "equivalent_tip_deflection_m": 1.8402987464349119,
        "equivalent_twist_max_deg": 0.2067055317368323,
        "design_mm": {
            "main_t": [0.8, 0.8, 0.8, 0.8, 0.8, 0.8],
            "main_r": [33.585, 33.585, 33.585, 33.585, 25.925, 17.95],
            "rear_t": [0.8, 0.8, 0.8, 0.8, 0.821, 0.86],
            "rear_r": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
        },
    }


def test_build_opt_result_from_summary_selection_reconstructs_segment_arrays() -> None:
    result = dual_beam_step.build_opt_result_from_summary_selection(
        _selection_dict(),
        selection_name="selected",
    )

    assert result.success is True
    assert result.main_t_seg_mm.tolist() == [0.8, 0.8, 0.8, 0.8, 0.8, 0.8]
    assert result.main_r_seg_mm.tolist() == [33.585, 33.585, 33.585, 33.585, 25.925, 17.95]
    assert result.rear_t_seg_mm.tolist() == [0.8, 0.8, 0.8, 0.8, 0.821, 0.86]
    assert result.rear_r_seg_mm.tolist() == [10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
    assert result.tip_deflection_m == 1.8402987464349119
    assert result.max_tip_deflection_m == 2.5
    assert "reconstructed from selected" in result.message


def test_load_dual_beam_step_selection_reads_summary_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    design_report_path = tmp_path / "crossval_report.txt"
    config_path.write_text("dummy: true\n", encoding="utf-8")
    design_report_path.write_text("dummy\n", encoding="utf-8")
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "config": str(config_path),
                "design_report": str(design_report_path),
                "outcome": {"selected": _selection_dict()},
            }
        ),
        encoding="utf-8",
    )

    selection = dual_beam_step.load_dual_beam_step_selection(summary_path)

    assert selection.summary_path == summary_path.resolve()
    assert selection.config_path == config_path.resolve()
    assert selection.design_report_path == design_report_path.resolve()
    assert selection.selection_name == "selected"
    assert selection.selection_source == "catalog_grid"


def test_export_dual_beam_step_uses_existing_csv_to_step_pipeline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    design_report_path = tmp_path / "crossval_report.txt"
    summary_path = tmp_path / "summary.json"
    step_path = tmp_path / "dual_beam.stp"

    config_path.write_text("dummy: true\n", encoding="utf-8")
    design_report_path.write_text("dummy\n", encoding="utf-8")
    summary_path.write_text(
        json.dumps(
            {
                "config": str(config_path),
                "design_report": str(design_report_path),
                "outcome": {"selected": _selection_dict()},
            }
        ),
        encoding="utf-8",
    )

    cfg = SimpleNamespace(
        solver=SimpleNamespace(n_beam_nodes=None),
        structural_load_cases=lambda: [SimpleNamespace(aero_scale=1.25)],
    )
    monkeypatch.setattr(dual_beam_step, "load_config", lambda path: cfg)
    monkeypatch.setattr(
        dual_beam_step,
        "parse_baseline_metrics",
        lambda path: SimpleNamespace(nodes_per_spar=60),
    )
    monkeypatch.setattr(
        dual_beam_step,
        "Aircraft",
        SimpleNamespace(from_config=lambda loaded_cfg: ("aircraft", loaded_cfg.solver.n_beam_nodes)),
    )
    monkeypatch.setattr(dual_beam_step, "MaterialDB", lambda: "materials_db")
    monkeypatch.setattr(
        dual_beam_step,
        "_select_cruise_loads",
        lambda loaded_cfg, aircraft: (0.0, {"lift_per_span": np.array([1.0]), "torque_per_span": np.array([2.0])}),
    )
    monkeypatch.setattr(
        dual_beam_step,
        "LoadMapper",
        SimpleNamespace(apply_load_factor=lambda loads, scale: {"scaled": loads, "scale": scale}),
    )

    captured: dict[str, object] = {}

    class DummyExporter:
        def __init__(self, cfg_arg, aircraft_arg, opt_result_arg, export_loads_arg, materials_db_arg, *, mode):
            captured["cfg"] = cfg_arg
            captured["aircraft"] = aircraft_arg
            captured["opt_result"] = opt_result_arg
            captured["export_loads"] = export_loads_arg
            captured["materials_db"] = materials_db_arg
            captured["mode"] = mode

        def write_workbench_csv(self, path):
            csv_path = Path(path)
            csv_path.write_text("stub\n", encoding="utf-8")
            captured["csv_path"] = csv_path
            return csv_path

    monkeypatch.setattr(dual_beam_step, "ANSYSExporter", DummyExporter)

    def _fake_export_step_from_csv(csv_path, step_file, *, engine):
        captured["step_csv_path"] = Path(csv_path)
        captured["step_path"] = Path(step_file)
        captured["engine"] = engine
        Path(step_file).write_text("step\n", encoding="utf-8")
        return "cadquery"

    monkeypatch.setattr(dual_beam_step, "export_step_from_csv", _fake_export_step_from_csv)

    step_output, csv_output, engine_name, selection = dual_beam_step.export_dual_beam_step(
        summary_path,
        step_path,
        engine="auto",
    )

    assert cfg.solver.n_beam_nodes == 60
    assert captured["mode"] == "dual_beam_production"
    assert captured["aircraft"] == ("aircraft", 60)
    assert captured["export_loads"] == {
        "scaled": {"lift_per_span": np.array([1.0]), "torque_per_span": np.array([2.0])},
        "scale": 1.25,
    }
    assert captured["csv_path"] == step_path.with_name("dual_beam_spar_data.csv")
    assert captured["step_csv_path"] == csv_output
    assert captured["step_path"] == step_output
    assert engine_name == "cadquery"
    assert selection.opt_result.main_r_seg_mm.tolist()[0] == 33.585
    assert step_output.read_text(encoding="utf-8") == "step\n"
