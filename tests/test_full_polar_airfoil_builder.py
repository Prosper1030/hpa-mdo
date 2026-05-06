from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import importlib.util
from types import SimpleNamespace

from hpa_mdo.airfoils.database import AirfoilPolarPoint, AirfoilRecord


def test_full_polar_builder_dry_run_creates_archive(tmp_path: Path) -> None:
    screening_dir = tmp_path / "screening"
    screening_dir.mkdir()
    coordinate_dir = screening_dir / "coordinates"
    coordinate_dir.mkdir()
    coordinate_path = coordinate_dir / "cst_tip_demo.dat"
    coordinate_path.write_text("cst_tip_demo\n1.0 0.0\n0.0 0.0\n1.0 0.0\n", encoding="utf-8")
    database_payload = {
        "records": [
            {
                "airfoil_id": "cst_tip_demo",
                "name": "cst_tip_demo",
                "source": f"offline_cst_zone_nsga_xfoil_database_builder_v1:{coordinate_path}",
                "source_quality": "cst_xfoil_mission_grade_candidate",
                "zone_hint": "tip",
                "thickness_ratio": 0.12,
                "max_camber": 0.03,
                "alpha_L0_deg": -2.0,
                "cl_alpha_per_rad": 6.0,
                "cm_design": -0.04,
                "safe_clmax": 1.2,
                "usable_clmax": 1.4,
                "polar_points": [],
                "notes": "unit test screening record",
                "coordinate_path": str(coordinate_path),
            }
        ]
    }
    (screening_dir / "airfoil_database.json").write_text(
        json.dumps(database_payload),
        encoding="utf-8",
    )
    (screening_dir / "per_zone_top_k.csv").write_text(
        "zone_name,airfoil_id,rank_in_zone,source_quality\n"
        "tip,cst_tip_demo,1,cst_xfoil_mission_grade_candidate\n",
        encoding="utf-8",
    )
    envelope_payload = {
        "zone_envelope": [
            {
                "zone_name": "tip",
                "re_min": 250000.0,
                "re_p50": 300000.0,
                "re_max": 350000.0,
                "cl_min": 0.2,
                "cl_p50": 0.5,
                "cl_p90": 0.8,
                "cl_max": 0.8,
                "max_fourier_target_cl": 0.8,
            }
        ]
    }
    envelope_path = screening_dir / "zone_envelope.json"
    envelope_path.write_text(json.dumps(envelope_payload), encoding="utf-8")
    output_dir = tmp_path / "full_polar"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_full_polar_airfoil_db.py",
            "--screening-output-dir",
            str(screening_dir),
            "--zone-envelope-json",
            str(envelope_path),
            "--output-dir",
            str(output_dir),
            "--dry-run",
            "--top-k-per-zone",
            "1",
            "--pareto-per-zone",
            "0",
            "--roughness-modes",
            "clean",
            "--alpha-step-deg",
            "1.0",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert (output_dir / "airfoil_records.json").is_file()
    assert (output_dir / "airfoil_records.csv").is_file()
    assert (output_dir / "polar_points.csv").is_file()
    assert (output_dir / "full_polar_build_report.json").is_file()
    assert (output_dir / "quality_report.csv").is_file()
    assert "full_polar_build_report" in result.stdout

    report = json.loads((output_dir / "full_polar_build_report.json").read_text(encoding="utf-8"))
    assert report["record_count"] == 7
    assert report["source_quality_counts"]["full_polar_candidate_not_mission_grade"] == 7
    assert report["records"]["cst_tip_demo"]["mission_grade_allowed"] is False
    assert report["records"]["fx76mp140"]["screening_quality"] == "seed_reference_pending_full_polar"
    assert "prestall" in (output_dir / "polar_points.csv").read_text(encoding="utf-8")


def test_full_polar_builder_selects_phase8_manifest_tier_and_preserves_labels(
    tmp_path: Path,
) -> None:
    screening_dir = tmp_path / "screening"
    screening_dir.mkdir()
    coordinate_dir = screening_dir / "coordinates"
    coordinate_dir.mkdir()
    selected_path = coordinate_dir / "cst_tip_selected.dat"
    skipped_path = coordinate_dir / "cst_tip_skipped.dat"
    selected_path.write_text("cst_tip_selected\n1.0 0.0\n0.0 0.0\n1.0 0.0\n", encoding="utf-8")
    skipped_path.write_text("cst_tip_skipped\n1.0 0.0\n0.0 0.0\n1.0 0.0\n", encoding="utf-8")
    database_payload = {
        "records": [
            {
                "airfoil_id": "cst_tip_selected",
                "name": "cst_tip_selected",
                "source": f"offline_cst_zone_nsga_xfoil_database_builder_v1:{selected_path}",
                "source_quality": "cst_xfoil_mission_grade_candidate",
                "zone_hint": "tip",
                "thickness_ratio": 0.12,
                "max_camber": 0.03,
                "alpha_L0_deg": -2.0,
                "cl_alpha_per_rad": 6.0,
                "cm_design": -0.04,
                "safe_clmax": 1.2,
                "usable_clmax": 1.4,
                "polar_points": [],
                "notes": "selected",
                "coordinate_path": str(selected_path),
            },
            {
                "airfoil_id": "cst_tip_skipped",
                "name": "cst_tip_skipped",
                "source": f"offline_cst_zone_nsga_xfoil_database_builder_v1:{skipped_path}",
                "source_quality": "cst_xfoil_mission_grade_candidate",
                "zone_hint": "tip",
                "thickness_ratio": 0.12,
                "max_camber": 0.03,
                "alpha_L0_deg": -2.0,
                "cl_alpha_per_rad": 6.0,
                "cm_design": -0.04,
                "safe_clmax": 1.2,
                "usable_clmax": 1.4,
                "polar_points": [],
                "notes": "skipped",
                "coordinate_path": str(skipped_path),
            },
        ]
    }
    (screening_dir / "airfoil_database.json").write_text(json.dumps(database_payload), encoding="utf-8")
    manifest_path = tmp_path / "full_alpha_candidate_manifest.csv"
    manifest_path.write_text(
        "airfoil_id,zone,tier2_recommended_reusable,screening_quality,archive_source_quality,"
        "actual_sidecar_query_quality,inclusion_reason,coordinate_path\n"
        f"cst_tip_selected,tip,true,target_cl_screening_pass,archive_label,actual_label,"
        f"screening_pass_candidate,{selected_path}\n"
        f"cst_tip_skipped,tip,false,target_cl_screening_pass,,,tier3_only,{skipped_path}\n",
        encoding="utf-8",
    )
    envelope_path = _write_tip_envelope(screening_dir)
    output_dir = tmp_path / "full_polar"

    subprocess.run(
        [
            sys.executable,
            "scripts/build_full_polar_airfoil_db.py",
            "--screening-output-dir",
            str(screening_dir),
            "--zone-envelope-json",
            str(envelope_path),
            "--candidate-manifest-csv",
            str(manifest_path),
            "--manifest-tier-flag",
            "tier2_recommended_reusable",
            "--output-dir",
            str(output_dir),
            "--dry-run",
            "--roughness-modes",
            "clean",
            "--alpha-step-deg",
            "2.0",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    report = json.loads((output_dir / "build_report.json").read_text(encoding="utf-8"))
    assert "cst_tip_selected" in report["records"]
    assert "cst_tip_skipped" not in report["records"]
    selected = report["records"]["cst_tip_selected"]
    assert selected["screening_quality"] == "target_cl_screening_pass"
    assert selected["archive_source_quality"] == "archive_label"
    assert selected["actual_sidecar_query_quality"] == "actual_label"
    assert selected["inclusion_reason"] == "screening_pass_candidate"
    assert report["records"]["dae31"]["screening_quality"] == "seed_reference_pending_full_polar"


def test_full_polar_builder_resume_skips_completed_manifest_candidate(tmp_path: Path) -> None:
    screening_dir = tmp_path / "screening"
    screening_dir.mkdir()
    coordinate_dir = screening_dir / "coordinates"
    coordinate_dir.mkdir()
    coordinate_path = coordinate_dir / "cst_tip_resume.dat"
    coordinate_path.write_text("cst_tip_resume\n1.0 0.0\n0.0 0.0\n1.0 0.0\n", encoding="utf-8")
    (screening_dir / "airfoil_database.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "airfoil_id": "cst_tip_resume",
                        "name": "cst_tip_resume",
                        "source": f"offline_cst_zone_nsga_xfoil_database_builder_v1:{coordinate_path}",
                        "source_quality": "cst_xfoil_mission_grade_candidate",
                        "zone_hint": "tip",
                        "thickness_ratio": 0.12,
                        "max_camber": 0.03,
                        "alpha_L0_deg": -2.0,
                        "cl_alpha_per_rad": 6.0,
                        "cm_design": -0.04,
                        "safe_clmax": 1.2,
                        "usable_clmax": 1.4,
                        "polar_points": [],
                        "notes": "resume",
                        "coordinate_path": str(coordinate_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.csv"
    manifest_path.write_text(
        "airfoil_id,zone,tier2_recommended_reusable,screening_quality,coordinate_path\n"
        f"cst_tip_resume,tip,true,target_cl_screening_pass,{coordinate_path}\n",
        encoding="utf-8",
    )
    envelope_path = _write_tip_envelope(screening_dir)
    output_dir = tmp_path / "full_polar"
    command = [
        sys.executable,
        "scripts/build_full_polar_airfoil_db.py",
        "--screening-output-dir",
        str(screening_dir),
        "--zone-envelope-json",
        str(envelope_path),
        "--candidate-manifest-csv",
        str(manifest_path),
        "--manifest-tier-flag",
        "tier2_recommended_reusable",
        "--output-dir",
        str(output_dir),
        "--dry-run",
        "--no-seed-airfoils",
        "--roughness-modes",
        "clean",
        "--alpha-step-deg",
        "3.0",
    ]
    subprocess.run(command, check=True, text=True, capture_output=True)
    second = subprocess.run(command + ["--resume"], check=True, text=True, capture_output=True)

    report = json.loads((output_dir / "build_report.json").read_text(encoding="utf-8"))
    assert report["record_count"] == 1
    assert second.stdout.count("[full-polar] skipping completed cst_tip_resume") == 1


def test_real_full_polar_queries_stop_after_clmax_to_avoid_poststall_grind(
    tmp_path: Path,
) -> None:
    module = _load_full_polar_builder_module()
    coordinate_path = tmp_path / "cst_tip_fast_stop.dat"
    coordinate_path.write_text("cst_tip_fast_stop\n1.0 0.0\n0.0 0.0\n1.0 0.0\n", encoding="utf-8")
    candidate = module.Candidate(
        airfoil_id="cst_tip_fast_stop",
        name="cst_tip_fast_stop",
        zone_origin="tip",
        coordinate_path=coordinate_path,
        screening_source_quality="target_cl_screening_pass",
        source="unit-test",
        thickness_ratio=0.12,
        max_camber=0.03,
        cm_design=-0.04,
        safe_clmax_screening=1.2,
        usable_clmax_screening=1.4,
    )
    state = module.BuildState(
        records=[],
        polar_rows=[],
        quality_rows=[],
        coverage_rows=[],
        gap_rows=[],
        record_reports={},
    )
    captured_queries = []

    class CapturingWorker:
        backend_name = "julia_xfoil_test_double"

        def run_queries(self, queries):
            captured_queries.extend(queries)
            return [module._dry_run_full_polar_result(query) for query in queries]

    module._evaluate_candidate(
        candidate=candidate,
        zone_envelopes={
            "tip": {
                "re_min": 250000.0,
                "re_p50": 300000.0,
                "re_max": 350000.0,
                "cl_min": 0.2,
                "cl_p50": 0.5,
                "cl_p90": 0.8,
                "cl_max": 0.8,
            }
        },
        roughness_modes=("clean",),
        alpha_samples=(-6.0, -5.5, -5.0),
        backend="julia",
        worker=CapturingWorker(),
        xfoil_max_iter=40,
        panel_count=96,
        convergence_threshold=0.8,
        state=state,
    )

    assert captured_queries
    assert all(getattr(query, "stop_after_clmax", None) is True for query in captured_queries)


def test_lightweight_checkpoint_is_resume_safe_without_heavy_rank_outputs(
    tmp_path: Path,
) -> None:
    module = _load_full_polar_builder_module()
    output_dir = tmp_path / "checkpoint"
    record = AirfoilRecord(
        airfoil_id="cst_tip_checkpoint",
        name="cst_tip_checkpoint",
        source="unit-test",
        source_quality="full_polar_mission_grade_candidate",
        zone_hint="tip",
        thickness_ratio=0.12,
        max_camber=0.03,
        alpha_L0_deg=-2.0,
        cl_alpha_per_rad=6.0,
        cm_design=-0.04,
        safe_clmax=1.2,
        usable_clmax=1.4,
        polar_points=(
            AirfoilPolarPoint(
                Re=300000.0,
                cl=0.5,
                cd=0.01,
                cm=-0.04,
                alpha_deg=2.0,
                roughness_mode="clean",
            ),
        ),
        notes="checkpoint test",
        coordinate_path="airfoils/cst_tip_checkpoint.dat",
    )
    polar_row = {
        "airfoil_id": "cst_tip_checkpoint",
        "Re": 300000.0,
        "cl": 0.5,
        "cd": 0.01,
        "cm": -0.04,
        "alpha_deg": 2.0,
        "roughness_mode": "clean",
        "converged": True,
        "branch_label": "prestall",
    }
    state = module.BuildState(
        records=[record],
        polar_rows=[polar_row],
        quality_rows=[
            {
                "airfoil_id": "cst_tip_checkpoint",
                "source_quality": "full_polar_mission_grade_candidate",
                "issues": "",
            }
        ],
        coverage_rows=[],
        gap_rows=[],
        record_reports={
            "cst_tip_checkpoint": {
                "source_quality": "full_polar_mission_grade_candidate",
                "screening_quality": "target_cl_screening_pass",
            }
        },
    )
    args = SimpleNamespace(dry_run=False, backend="julia")

    module._write_checkpoint_artifacts(
        state=state,
        output_dir=output_dir,
        args=args,
    )

    records_payload = json.loads((output_dir / "airfoil_records.json").read_text(encoding="utf-8"))
    assert records_payload["records"][0]["polar_points"] == {"count": 1}
    assert (output_dir / "polar_points.csv").is_file()
    assert not (output_dir / "per_zone_pareto.csv").exists()
    report = json.loads((output_dir / "build_report.json").read_text(encoding="utf-8"))
    assert report["checkpoint_artifact_mode"] == "resume_safe_lightweight"
    assert report["record_count"] == 1

    reloaded = module._load_existing_state(output_dir)
    assert [record.airfoil_id for record in reloaded.records] == ["cst_tip_checkpoint"]
    assert len(reloaded.records[0].polar_points) == 1
    assert reloaded.record_reports["cst_tip_checkpoint"]["screening_quality"] == "target_cl_screening_pass"


def _write_tip_envelope(screening_dir: Path) -> Path:
    envelope_payload = {
        "zone_envelope": [
            {
                "zone_name": "tip",
                "re_min": 250000.0,
                "re_p50": 300000.0,
                "re_max": 350000.0,
                "cl_min": 0.2,
                "cl_p50": 0.5,
                "cl_p90": 0.8,
                "cl_max": 0.8,
                "max_fourier_target_cl": 0.8,
            }
        ]
    }
    envelope_path = screening_dir / "zone_envelope.json"
    envelope_path.write_text(json.dumps(envelope_payload), encoding="utf-8")
    return envelope_path


def _load_full_polar_builder_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "build_full_polar_airfoil_db.py"
    spec = importlib.util.spec_from_file_location("build_full_polar_airfoil_db", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
