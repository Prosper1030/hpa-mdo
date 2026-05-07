#!/usr/bin/env python3
"""Run the smooth Tier2 baseline through the canonical inverse-design route."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hpa_mdo.aero.avl_spanwise import write_candidate_avl_spanwise_artifact  # noqa: E402


OUTPUT_DIR = REPO_ROOT / "output" / "phase10_2_canonical_inverse_design_check"
SMOOTH_BASELINE_DIR = (
    REPO_ROOT / "output" / "final_candidate_validation" / "smooth_tier2_production_baseline"
)
SMOOTH_PROD_GEOM_DIR = (
    SMOOTH_BASELINE_DIR
    / "geometry_exports"
    / "production_inspection"
    / "smooth_tier2_production_baseline"
)
SMOOTH_AVL_RUN_DIR = SMOOTH_BASELINE_DIR / "avl_runs" / "smooth_tier2_production_baseline"
PHASE10_SIDECAR_DIR = REPO_ROOT / "output" / "phase10_dual_beam_jig_validation"
OLD_CANONICAL_DIR = (
    REPO_ROOT / "output" / "_archive_pre_2026_04_15" / "direct_dual_beam_inverse_design_refresh_smoke"
)
OLD_PRODUCTION_REPORT = (
    REPO_ROOT
    / "output"
    / "_archive_pre_2026_04_15"
    / "blackcat_004_dual_beam_production_check"
    / "ansys"
    / "crossval_report.txt"
)
SYNC_AERO_DIR = Path("/Volumes/Samsung SSD/SyncFile/Aerodynamics/black cat 004 wing only")
LEGACY_VSPAERO_LOD = SYNC_AERO_DIR / "blackcat 004 wing only_VSPGeom.lod"
LEGACY_VSPAERO_POLAR = SYNC_AERO_DIR / "blackcat 004 wing only_VSPGeom.polar"
SMOOTH_VELOCITY_MPS = 6.6
SMOOTH_RHO_KGPM3 = 1.18


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in keys})


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def fnum(value: Any, digits: int = 3) -> str:
    if value in (None, ""):
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.{digits}f}"


def smooth_section_rows() -> list[dict[str, str]]:
    return read_csv_rows(SMOOTH_PROD_GEOM_DIR / "section_table.csv")


def smooth_aero_summary_row() -> dict[str, str]:
    rows = read_csv_rows(SMOOTH_BASELINE_DIR / "aerodynamic_summary.csv")
    if not rows:
        raise ValueError("smooth aerodynamic_summary.csv is empty.")
    return rows[0]


def adapted_spar_segments(half_span_m: float) -> list[float]:
    base = [1.5, 3.0, 3.0, 3.0, 3.0]
    final = float(half_span_m) - sum(base)
    if final <= 1.0e-6:
        raise ValueError(f"Smooth half-span {half_span_m:.6f} is too short for blackcat joints.")
    return base + [final]


def build_smooth_canonical_config(output_dir: Path) -> tuple[Path, dict[str, Any]]:
    rows = smooth_section_rows()
    half_span = max(float(row["y_m"]) for row in rows)
    segments = adapted_spar_segments(half_span)
    root = rows[0]
    tip = rows[-1]

    base_config = yaml.safe_load((REPO_ROOT / "configs" / "blackcat_004.yaml").read_text()) or {}
    config = dict(base_config)
    config["project_name"] = "smooth_tier2_production_baseline canonical inverse-design check"
    config["flight"] = dict(config.get("flight", {}))
    config["flight"]["velocity"] = SMOOTH_VELOCITY_MPS
    config["flight"]["air_density"] = SMOOTH_RHO_KGPM3

    wing = dict(config.get("wing", {}))
    wing["span"] = float(2.0 * half_span)
    wing["root_chord"] = float(root["chord_m"])
    wing["tip_chord"] = float(tip["chord_m"])
    wing["airfoil_root"] = str(root["airfoil_id"])
    wing["airfoil_tip"] = str(tip["airfoil_id"])
    wing["chord_schedule"] = [[float(row["y_m"]), float(row["chord_m"])] for row in rows]
    wing["dihedral_schedule"] = [[float(row["y_m"]), float(row["z_m"])] for row in rows]
    wing["twist_schedule"] = [[float(row["y_m"]), float(row["twist_deg"])] for row in rows]
    config["wing"] = wing

    for spar_key in ("main_spar", "rear_spar"):
        spar = dict(config.get(spar_key, {}))
        spar["segments"] = segments
        config[spar_key] = spar

    io_cfg = dict(config.get("io", {}))
    io_cfg["vsp_model"] = str((SMOOTH_PROD_GEOM_DIR / "smooth_tier2_production_baseline.vsp3").resolve())
    io_cfg["vsp_lod"] = str(LEGACY_VSPAERO_LOD)
    io_cfg["vsp_polar"] = str(LEGACY_VSPAERO_POLAR)
    io_cfg["airfoil_dir"] = str((SMOOTH_PROD_GEOM_DIR / "airfoils").resolve())
    io_cfg["output_dir"] = str((output_dir / "smooth_tier2_config_io_output").resolve())
    config["io"] = io_cfg

    config_path = output_dir / "smooth_tier2_canonical_config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    manifest = {
        "config_path": str(config_path.resolve()),
        "half_span_m": half_span,
        "span_m": float(2.0 * half_span),
        "section_count": len(rows),
        "root_chord_m": float(root["chord_m"]),
        "tip_chord_m": float(tip["chord_m"]),
        "root_airfoil": str(root["airfoil_id"]),
        "tip_airfoil": str(tip["airfoil_id"]),
        "spar_segments_m": segments,
        "source_vsp_production_inspection": io_cfg["vsp_model"],
        "source_avl_production_inspection": str(
            (SMOOTH_PROD_GEOM_DIR / "smooth_tier2_production_baseline.avl").resolve()
        ),
        "legacy_vspaero_lod_for_structural_state_owner": str(LEGACY_VSPAERO_LOD),
        "legacy_vspaero_polar_for_structural_state_owner": str(LEGACY_VSPAERO_POLAR),
        "airfoil_dir": io_cfg["airfoil_dir"],
    }
    return config_path, manifest


def build_candidate_avl_artifact(output_dir: Path) -> Path:
    aero = smooth_aero_summary_row()
    artifact_path = output_dir / "smooth_tier2_candidate_avl_spanwise_loads.json"
    write_candidate_avl_spanwise_artifact(
        artifact_path,
        avl_path=SMOOTH_PROD_GEOM_DIR / "smooth_tier2_production_baseline.avl",
        candidate_output_dir=SMOOTH_AVL_RUN_DIR,
        requested_knobs={
            "target_shape_z_scale": 1.0,
            "dihedral_multiplier": 1.0,
            "dihedral_exponent": 1.0,
        },
        selected_cruise_aoa_deg=float(aero["alpha_at_CL_req"]),
        selected_cruise_aoa_source="smooth_tier2_avl_trim_alpha_at_CL_req",
        selected_load_state_owner="smooth_tier2_avl_trim_and_gates",
        velocity_mps=SMOOTH_VELOCITY_MPS,
        density_kgpm3=SMOOTH_RHO_KGPM3,
        load_case_specs=[
            {
                "aoa_deg": float(aero["alpha_at_CL_req"]),
                "fs_path": SMOOTH_AVL_RUN_DIR / "concept_spanwise.fs",
                "stdout_log_path": SMOOTH_AVL_RUN_DIR / "concept_spanwise_stdout.log",
            }
        ],
        trim_force_path=SMOOTH_AVL_RUN_DIR / "concept_trim.ft",
        trim_stdout_log_path=SMOOTH_AVL_RUN_DIR / "concept_trim_stdout.log",
        target_surface_names=("Wing",),
        notes=(
            "Phase 10.2 diagnostic artifact: smooth production AVL strip-force shape.",
            "The canonical direct script still aligns the structural selected load-state to the legacy blackcat VSPAero owner.",
        ),
    )
    return artifact_path


def run_canonical_inverse_design(
    *,
    output_dir: Path,
    config_path: Path,
    candidate_avl_json: Path,
) -> dict[str, Any]:
    run_dir = output_dir / "smooth_tier2_canonical_run"
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "direct_dual_beam_inverse_design.py"),
        "--config",
        str(config_path),
        "--design-report",
        str(OLD_PRODUCTION_REPORT),
        "--output-dir",
        str(run_dir),
        "--aero-source-mode",
        "candidate_avl_spanwise",
        "--candidate-avl-spanwise-loads-json",
        str(candidate_avl_json),
        "--no-ground-clearance-recovery",
        "--skip-local-refine",
        "--rib-zonewise-mode",
        "off",
    ]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    (output_dir / "smooth_tier2_inverse_design_command.txt").write_text(
        " ".join(command) + "\n",
        encoding="utf-8",
    )
    (output_dir / "smooth_tier2_inverse_design_stdout.log").write_text(
        completed.stdout,
        encoding="utf-8",
    )
    (output_dir / "smooth_tier2_inverse_design_stderr.log").write_text(
        completed.stderr,
        encoding="utf-8",
    )
    return {
        "command": command,
        "run_dir": run_dir,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def parse_canonical_summary(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "direct_dual_beam_inverse_design_refresh_summary.json"
    if not summary_path.exists():
        return {}
    summary = read_json(summary_path)
    final_iteration = (summary.get("iterations") or [{}])[-1]
    selected = final_iteration.get("selected") or {}
    artifacts = summary.get("artifacts") or {}
    return {
        "summary_path": str(summary_path.resolve()),
        "feasible": final_iteration.get("run_metrics", {}).get("feasible")
        if "run_metrics" in final_iteration
        else selected.get("overall_feasible"),
        "refresh_steps_requested": summary.get("refinement_definition", {}).get(
            "refresh_steps_requested"
        ),
        "refresh_steps_completed": summary.get("refinement_definition", {}).get(
            "refresh_steps_completed"
        ),
        "selected_source": selected.get("source"),
        "total_structural_mass_kg": selected.get("total_structural_mass_kg"),
        "tube_mass_kg": selected.get("tube_mass_kg"),
        "target_shape_error_max_m": selected.get("target_shape_error_max_m"),
        "loaded_shape_main_z_error_max_m": selected.get("loaded_shape_main_z_error_max_m"),
        "loaded_shape_twist_error_max_deg": selected.get("loaded_shape_twist_error_max_deg"),
        "jig_ground_clearance_min_m": selected.get("jig_ground_clearance_min_m"),
        "max_jig_vertical_prebend_m": selected.get("max_jig_vertical_prebend_m"),
        "equivalent_tip_deflection_m": selected.get("equivalent_tip_deflection_m"),
        "failures": "|".join(selected.get("failures") or []),
        "artifacts": artifacts,
    }


def old_blackcat_summary_row() -> dict[str, Any]:
    summary = read_json(OLD_CANONICAL_DIR / "direct_dual_beam_inverse_design_refresh_summary.json")
    final_iteration = (summary.get("iterations") or [{}])[-1]
    selected = final_iteration.get("selected") or {}
    return {
        "workflow": "old_blackcat_004_canonical_archive",
        "case_id": "blackcat_004",
        "entrypoint": "scripts/direct_dual_beam_inverse_design.py",
        "run_succeeded": True,
        "feasible": selected.get("overall_feasible"),
        "total_structural_mass_kg": selected.get("total_structural_mass_kg"),
        "tube_mass_kg": selected.get("tube_mass_kg"),
        "target_or_loaded_shape_error_max_m": selected.get("target_shape_error_max_m"),
        "jig_ground_clearance_min_m": selected.get("jig_ground_clearance_min_m"),
        "max_jig_vertical_prebend_m": selected.get("max_jig_vertical_prebend_m"),
        "tip_deflection_m": selected.get("equivalent_tip_deflection_m"),
        "moment_closure_residual_nm": "",
        "failures": "|".join(selected.get("failures") or []),
        "notes": "Archived validated blackcat-style canonical refresh smoke.",
    }


def sidecar_rows() -> list[dict[str, Any]]:
    path = PHASE10_SIDECAR_DIR / "dual_beam_validation_results.csv"
    if not path.exists():
        return []
    keep = {
        "proxy_selected_equal_CF_STD_100x98",
        "geometry_rule_main100_rear50",
    }
    rows: list[dict[str, Any]] = []
    for row in read_csv_rows(path):
        if row.get("case_id") != "smooth_tier2_production_baseline":
            continue
        if row.get("recipe_id") not in keep:
            continue
        rows.append(
            {
                "workflow": f"phase10_sidecar_{row.get('recipe_id')}",
                "case_id": row.get("case_id"),
                "entrypoint": "scripts/validate_smooth_tier2_dual_beam_structure.py",
                "run_succeeded": row.get("run_succeeded"),
                "feasible": row.get("feasibility_status"),
                "total_structural_mass_kg": row.get("total_structural_mass_full_kg"),
                "tube_mass_kg": row.get("spar_tube_mass_full_kg"),
                "target_or_loaded_shape_error_max_m": row.get(
                    "loaded_shape_main_z_max_abs_error_m"
                ),
                "jig_ground_clearance_min_m": row.get("jig_min_z_m"),
                "max_jig_vertical_prebend_m": row.get(
                    "manufacturing_max_abs_vertical_prebend_m"
                ),
                "tip_deflection_m": row.get("tip_deflection_main_m"),
                "moment_closure_residual_nm": row.get("moment_closure_residual_nm"),
                "failures": row.get("hard_failures"),
                "notes": "Direct dual-beam adapter; not the formal config/optimizer inverse-design workflow.",
            }
        )
    return rows


def smooth_canonical_row(run_status: Mapping[str, Any], summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "workflow": "smooth_tier2_canonical_candidate_avl_spanwise",
        "case_id": "smooth_tier2_production_baseline",
        "entrypoint": "scripts/direct_dual_beam_inverse_design.py",
        "run_succeeded": run_status.get("returncode") == 0,
        "feasible": summary.get("feasible", ""),
        "total_structural_mass_kg": summary.get("total_structural_mass_kg", ""),
        "tube_mass_kg": summary.get("tube_mass_kg", ""),
        "target_or_loaded_shape_error_max_m": summary.get(
            "loaded_shape_main_z_error_max_m",
            summary.get("target_shape_error_max_m", ""),
        ),
        "jig_ground_clearance_min_m": summary.get("jig_ground_clearance_min_m", ""),
        "max_jig_vertical_prebend_m": summary.get("max_jig_vertical_prebend_m", ""),
        "tip_deflection_m": summary.get("equivalent_tip_deflection_m", ""),
        "moment_closure_residual_nm": "",
        "failures": summary.get("failures", ""),
        "notes": "Canonical direct inverse-design route with smooth geometry schedules and candidate AVL spanwise lift-shape artifact.",
    }


def write_reports(
    *,
    output_dir: Path,
    config_manifest: Mapping[str, Any],
    candidate_avl_json: Path,
    run_status: Mapping[str, Any],
    smooth_summary: Mapping[str, Any],
    comparison_rows: Sequence[Mapping[str, Any]],
) -> None:
    docs = {
        "CURRENT_MAINLINE.md": "formal workflow and `scripts/direct_dual_beam_inverse_design.py` entrypoint",
        "README.md": "current production truth and high-level structural pipeline",
        "project_state.yaml": "active route/status ownership",
        "docs/NOW_NEXT_BLUEPRINT.md": "near-term route framing and sidecar-vs-mainline boundary",
    }
    write_text(
        output_dir / "mainline_workflow_summary.md",
        f"""
# Mainline Workflow Summary

Read sources:

{chr(10).join(f"- `{path}`: {note}" for path, note in docs.items())}

The formal structural route is:

`requested cruise shape -> inverse design -> jig shape -> realizable loaded shape -> wire / clearance / manufacturing / CFRP checks`.

The canonical executable entrypoint is `scripts/direct_dual_beam_inverse_design.py`. In canonical mode it builds a config-owned `Aircraft`, maps aero loads, runs the dual-beam production kernel through the inverse-design evaluator, writes target/jig/loaded shape CSVs, and exports STEP geometry when the CAD backend is available.

For this Phase 10.2 check I used the current canonical script, not the Phase 10 sidecar. The aero source mode is `candidate_avl_spanwise`, which lets the smooth production AVL strip-force distribution provide the spanwise lift-shape evidence while the direct script still preserves the legacy blackcat VSPAero load-state owner required by the formal route.
""",
    )

    write_text(
        output_dir / "old_blackcat_jig_setup_audit.md",
        f"""
# Old Blackcat Jig Setup Audit

- canonical entrypoint: `scripts/direct_dual_beam_inverse_design.py`
- config: `configs/blackcat_004.yaml`
- repo VSP input: `data/blackcat_004_origin.vsp3`
- production baseline report used by archive: `{OLD_PRODUCTION_REPORT}`
- legacy VSPAero LOD used for structural load-state ownership: `{LEGACY_VSPAERO_LOD}`
- legacy VSPAero polar: `{LEGACY_VSPAERO_POLAR}`
- archived canonical output: `{OLD_CANONICAL_DIR}`
- archived report: `{OLD_CANONICAL_DIR / 'direct_dual_beam_inverse_design_refresh_report.txt'}`
- archived summary JSON: `{OLD_CANONICAL_DIR / 'direct_dual_beam_inverse_design_refresh_summary.json'}`
- archived STEP artifacts: `{OLD_CANONICAL_DIR / 'jig_shape.step'}` and the loaded-shape CSV/STEP outputs reported by the summary

The exact old shell command is not stored in the report artifact. The archive records the script, config path, design report path, baseline cruise AoA, two refresh steps, selected source `coarse_grid`, and final feasible status.

Resolved old setup:

- span/chord source: `configs/blackcat_004.yaml` plus `data/blackcat_004_origin.vsp3`
- structural segments: `[1.5, 3.0, 3.0, 3.0, 3.0, 3.0]`
- joint y stations: `[1.5, 4.5, 7.5, 10.5, 13.5]`
- lift wire: one Dyneema SK75 cable, `diameter=2.5e-3 m`, attach `y=7.5 m`, fuselage anchor `z=-1.5 m`
- main spar station: `0.25c`
- rear spar station: `0.70c`
- selected old canonical tube design: main thickness `[8, 8, 8, 8, 8, 8] mm`, main radius `[30.635, 30.635, 30.635, 30.635, 22.975, 15.0] mm`; rear thickness `[8, 8, 8, 8, 8, 8] mm`, rear radius `[10, 10, 10, 10, 10, 10] mm`
- selected old canonical mass: `77.932 kg` total structural, `75.432 kg` tube
- selected old canonical jig clearance: `32.535 mm`
- selected old canonical max jig prebend: `102.862 mm`

Output artifacts include `target_loaded_shape_spar_data.csv`, `jig_shape_spar_data.csv`, `jig_shape.step`, the refresh report, and the refresh summary JSON in the archived directory above.
""",
    )

    write_text(
        output_dir / "phase10_sidecar_vs_canonical.md",
        """
# Phase 10 Sidecar vs Canonical

| item | old canonical blackcat workflow | Phase 10 sidecar |
|---|---|---|
| entrypoint | `scripts/direct_dual_beam_inverse_design.py` | `scripts/validate_smooth_tier2_dual_beam_structure.py` |
| target loaded shape source | config-owned aircraft geometry / beam nodes | production section table adapter |
| inverse jig solver | yes, through `build_frozen_load_inverse_design_from_mainline()` inside direct inverse-design evaluator | yes, called directly after a forward recipe check |
| wire rigging model | config lift-wire settings, pretension converted to unstretched length by builder | hardcoded one-wire adapter, `WIRE_PRETENSION_N = 0.0` |
| dual-beam model | config/optimizer builder path into `dual_beam_production` | directly assembled `DualBeamMainlineModel` |
| tube / spar recipe | reduced-map design variables seeded from blackcat crossval report | diagnostic catalog/recipe list such as equal `CF-STD-100x98` or synthetic split tubes |
| load source | legacy VSPAero owner, optionally candidate-owned aero contracts | AVL `.fs` lift plus adapter torque convention |
| CFRP / layup path | direct script/rib/structural candidate contract path | not a candidate-owned CFRP sizing path |
| clearance/manufacturing | formal inverse-design feasibility report | inverse-jig checks with adapter assumptions |
| output artifacts | target/jig/loaded CSV, STEP, diagnostics, wire rigging, aero contract | sidecar CSV/markdown reports only |

The sidecar used the real dual-beam kernel, but it did not use the same formal config/optimizer/inverse-design path as the old blackcat setup.
""",
    )

    command_text = " ".join(str(part) for part in run_status.get("command", []))
    write_text(
        output_dir / "smooth_tier2_inverse_design_input_manifest.md",
        f"""
# Smooth Tier2 Inverse-Design Input Manifest

- generated canonical config: `{config_manifest['config_path']}`
- candidate AVL spanwise artifact: `{candidate_avl_json.resolve()}`
- production inspection VSP: `{config_manifest['source_vsp_production_inspection']}`
- production inspection AVL: `{config_manifest['source_avl_production_inspection']}`
- source section count: `{config_manifest['section_count']}`
- span: `{fnum(config_manifest['span_m'], 6)} m`
- root/tip chord: `{fnum(config_manifest['root_chord_m'], 6)} m` / `{fnum(config_manifest['tip_chord_m'], 6)} m`
- airfoil assignment endpoints: `{config_manifest['root_airfoil']}` -> `{config_manifest['tip_airfoil']}`
- adapted spar segments: `{config_manifest['spar_segments_m']}`
- legacy blackcat load-state owner LOD: `{config_manifest['legacy_vspaero_lod_for_structural_state_owner']}`
- legacy blackcat load-state owner polar: `{config_manifest['legacy_vspaero_polar_for_structural_state_owner']}`

Config adaptations:

- `wing.chord_schedule` is taken from the smooth production section table.
- `wing.dihedral_schedule` is taken from the smooth loaded `z_m` section table and now enters the dual-beam builder as explicit loaded z.
- `wing.twist_schedule` is taken from the smooth production section table and applied as relative rear-spar z offset.
- Blackcat tube/wire/joint conventions are reused where possible. The final spar segment is lengthened to close the smooth half-span while preserving the old `y=7.5 m` wire joint.
- The run uses the smooth AVL strip-force shape but preserves legacy blackcat VSPAero structural state ownership because that is how `candidate_avl_spanwise` is defined in the canonical script.

Command:

```bash
{command_text}
```
""",
    )

    artifacts = smooth_summary.get("artifacts") or {}
    artifact_lines = []
    for label, key in (
        ("target CSV", "target_shape_csv"),
        ("jig CSV", "jig_shape_csv"),
        ("loaded CSV", "loaded_shape_csv"),
        ("deflection CSV", "deflection_csv"),
        ("jig STEP", "jig_step_path"),
        ("loaded STEP", "loaded_step_path"),
        ("diagnostics JSON", "diagnostics_json"),
        ("validity JSON", "validity_summary_json"),
        ("wire rigging JSON", "wire_rigging_json"),
        ("aero contract JSON", "aero_contract_json"),
    ):
        value = artifacts.get(key)
        artifact_lines.append(f"- {label}: `{value or 'not written'}`")

    write_text(
        output_dir / "smooth_tier2_inverse_design_run_report.md",
        f"""
# Smooth Tier2 Inverse-Design Run Report

- command return code: `{run_status.get('returncode')}`
- canonical run directory: `{run_status.get('run_dir')}`
- summary JSON: `{smooth_summary.get('summary_path', 'not written')}`
- feasible: `{smooth_summary.get('feasible', 'n/a')}`
- selected source: `{smooth_summary.get('selected_source', 'n/a')}`
- total structural mass: `{fnum(smooth_summary.get('total_structural_mass_kg'))} kg`
- tube mass: `{fnum(smooth_summary.get('tube_mass_kg'))} kg`
- loaded-shape main-z max error: `{fnum(smooth_summary.get('loaded_shape_main_z_error_max_m'), 6)} m`
- loaded-shape twist max error: `{fnum(smooth_summary.get('loaded_shape_twist_error_max_deg'), 6)} deg`
- jig ground clearance min: `{fnum(smooth_summary.get('jig_ground_clearance_min_m'), 6)} m`
- max jig prebend: `{fnum(smooth_summary.get('max_jig_vertical_prebend_m'), 6)} m`
- failures: `{smooth_summary.get('failures') or 'none'}`

Artifacts:

{chr(10).join(artifact_lines)}

If the run failed before writing a summary, inspect `{output_dir / 'smooth_tier2_inverse_design_stdout.log'}` and `{output_dir / 'smooth_tier2_inverse_design_stderr.log'}`. This report keeps the failure as diagnostic evidence and does not alter aerodynamic ranking or hard gates.
""",
    )

    canonical = next(
        (row for row in comparison_rows if row.get("workflow") == "smooth_tier2_canonical_candidate_avl_spanwise"),
        {},
    )
    canonical_feasible = canonical.get("feasible")
    canonical_failures = canonical.get("failures") or "none"
    write_text(
        output_dir / "recommended_next_steps.md",
        f"""
# Recommended Next Steps

## Answers

- Did Phase 10 sidecar use the same path as old blackcat jig-shape workflow? No. It used the real dual-beam kernel, but through a direct adapter and recipe screen, not the formal config/optimizer inverse-design route.
- What differed? The target-shape source, structural config ownership, tube recipe path, wire pretension source, load-state ownership, and output artifact contract all differed.
- Can `smooth_tier2_production_baseline` run through the canonical inverse-design workflow? `{run_status.get('returncode') == 0}`.
- Does it pass, fail, or need config adaptation? Canonical result feasible field: `{canonical_feasible}`; failures: `{canonical_failures}`. It required config adaptation to carry smooth chord/z/twist schedules and to preserve the old blackcat wire joint layout over the longer half-span.
- Is `moment_closure` a true structural blocker or sidecar adapter artifact? It is not proven as a production structural blocker from Phase 10 alone. The sidecar `moment_closure` failure is adapter-path evidence because the canonical direct route does not expose the same moment-closure diagnostic in the same way and uses a different load-state/torque ownership path.

## Engineering Recommendation

Treat the smooth aerodynamic baseline as aerodynamically current but structurally pending until the canonical direct run is reviewed with candidate-owned structural settings. The next structural action is to turn the smooth baseline config generated here into a reviewed candidate-owned structural config: spar tube/layup design, rib contract, wire anchor geometry, pretension, and a torque convention tied to AVL/airfoil moment data. Then rerun the canonical route with full artifact review before promoting any structural feasibility claim.
""",
    )


def run(output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path, config_manifest = build_smooth_canonical_config(output_dir)
    candidate_avl_json = build_candidate_avl_artifact(output_dir)
    run_status = run_canonical_inverse_design(
        output_dir=output_dir,
        config_path=config_path,
        candidate_avl_json=candidate_avl_json,
    )
    smooth_summary = parse_canonical_summary(Path(run_status["run_dir"]))
    comparison_rows = [
        old_blackcat_summary_row(),
        *sidecar_rows(),
        smooth_canonical_row(run_status, smooth_summary),
    ]
    write_csv(output_dir / "canonical_vs_sidecar_results.csv", comparison_rows)
    write_reports(
        output_dir=output_dir,
        config_manifest=config_manifest,
        candidate_avl_json=candidate_avl_json,
        run_status=run_status,
        smooth_summary=smooth_summary,
        comparison_rows=comparison_rows,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Output directory for Phase 10.2 canonical inverse-design check.",
    )
    args = parser.parse_args(argv)
    return run(args.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
