#!/usr/bin/env python3
"""Sweep smooth Tier2 baseline target-Z states against the spar tube mass line."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hpa_mdo.aero.avl_spanwise import write_candidate_avl_spanwise_artifact  # noqa: E402
from scripts.run_phase10_2_canonical_inverse_design_check import (  # noqa: E402
    SMOOTH_AVL_RUN_DIR,
    SMOOTH_PROD_GEOM_DIR,
    SMOOTH_RHO_KGPM3,
    SMOOTH_VELOCITY_MPS,
    build_smooth_canonical_config,
    smooth_aero_summary_row,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase10_3_smooth_z_state_mass_sweep"
DEFAULT_DESIGN_REPORT = REPO_ROOT / "output" / "blackcat_004" / "ansys" / "crossval_report.txt"
FALLBACK_DESIGN_REPORT = (
    REPO_ROOT
    / "output"
    / "_archive_pre_2026_04_15"
    / "blackcat_004_dual_beam_production_check"
    / "ansys"
    / "crossval_report.txt"
)
PHASE10_BASE_TARGET_CSV = (
    REPO_ROOT
    / "output"
    / "phase10_2_canonical_inverse_design_check"
    / "smooth_tier2_canonical_run"
    / "target_loaded_shape_spar_data.csv"
)
SPAR_TUBE_MASS_LINE_KG = 11.7534


def _float(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _target_tip_from_csv(path: Path) -> tuple[float, float]:
    rows = _read_csv_rows(path)
    if not rows:
        raise ValueError(f"Target shape CSV is empty: {path}")
    tip = rows[-1]
    return _float(tip["Main_Z_m"]), _float(tip["Rear_Z_m"])


def _tip_z_from_shape_dict(shape: Mapping[str, Any]) -> tuple[float, float]:
    main_nodes = shape.get("main_nodes_m") or []
    rear_nodes = shape.get("rear_nodes_m") or []
    main_tip = main_nodes[-1] if main_nodes else [float("nan"), float("nan"), float("nan")]
    rear_tip = rear_nodes[-1] if rear_nodes else [float("nan"), float("nan"), float("nan")]
    return _float(main_tip[2]), _float(rear_tip[2])


def _root_z_from_shape_dict(shape: Mapping[str, Any]) -> tuple[float, float]:
    main_nodes = shape.get("main_nodes_m") or []
    rear_nodes = shape.get("rear_nodes_m") or []
    main_root = main_nodes[0] if main_nodes else [float("nan"), float("nan"), float("nan")]
    rear_root = rear_nodes[0] if rear_nodes else [float("nan"), float("nan"), float("nan")]
    return _float(main_root[2]), _float(rear_root[2])


def _base_main_tip_z_m() -> float:
    if PHASE10_BASE_TARGET_CSV.exists():
        phase10_summary = PHASE10_BASE_TARGET_CSV.with_name(
            "direct_dual_beam_inverse_design_refresh_summary.json"
        )
        if phase10_summary.exists():
            summary = _read_json(phase10_summary)
            selected = ((summary.get("iterations") or [{}])[-1].get("selected") or {})
            main_tip_z, _ = _tip_z_from_shape_dict(selected.get("target_loaded_shape") or {})
            if main_tip_z == main_tip_z:
                return main_tip_z
        return _target_tip_from_csv(PHASE10_BASE_TARGET_CSV)[0]
    rows = _read_csv_rows(SMOOTH_PROD_GEOM_DIR / "section_table.csv")
    if not rows:
        raise ValueError("Smooth section table is empty.")
    return _float(rows[-1]["z_m"])


def _parse_target_tips(text: str) -> list[float]:
    values = [_float(part.strip()) for part in text.split(",") if part.strip()]
    values = [value for value in values if value == value and value > 0.0]
    if not values:
        raise ValueError("--target-main-tip-z-m must contain at least one positive value.")
    return sorted(set(round(value, 6) for value in values))


def _case_label(target_main_tip_z_m: float) -> str:
    return f"target_main_tip_z_{target_main_tip_z_m:.3f}m".replace(".", "p")


def _write_candidate_avl_artifact(
    *,
    artifact_path: Path,
    target_shape_z_scale: float,
    dihedral_exponent: float,
) -> None:
    aero = smooth_aero_summary_row()
    write_candidate_avl_spanwise_artifact(
        artifact_path,
        avl_path=SMOOTH_PROD_GEOM_DIR / "smooth_tier2_production_baseline.avl",
        candidate_output_dir=SMOOTH_AVL_RUN_DIR,
        requested_knobs={
            "target_shape_z_scale": float(target_shape_z_scale),
            "dihedral_multiplier": float(target_shape_z_scale),
            "dihedral_exponent": float(dihedral_exponent),
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
            "Phase 10.3 z-state sweep artifact: smooth production AVL strip-force shape is held fixed.",
            "The sweep reports actual target loaded-Z coordinates; target_shape_z_scale is only the generator knob.",
        ),
    )


def _run_case(
    *,
    output_dir: Path,
    config_path: Path,
    design_report: Path,
    target_main_tip_z_m: float,
    base_main_tip_z_m: float,
    dihedral_exponent: float,
    rerun: bool,
) -> dict[str, Any]:
    label = _case_label(target_main_tip_z_m)
    case_dir = output_dir / "runs" / label
    summary_path = case_dir / "direct_dual_beam_inverse_design_refresh_summary.json"
    target_shape_z_scale = float(target_main_tip_z_m) / max(float(base_main_tip_z_m), 1.0e-9)
    artifact_path = output_dir / "candidate_avl_artifacts" / f"{label}.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    _write_candidate_avl_artifact(
        artifact_path=artifact_path,
        target_shape_z_scale=target_shape_z_scale,
        dihedral_exponent=dihedral_exponent,
    )

    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "direct_dual_beam_inverse_design.py"),
        "--config",
        str(config_path),
        "--design-report",
        str(design_report),
        "--output-dir",
        str(case_dir),
        "--aero-source-mode",
        "candidate_avl_spanwise",
        "--candidate-avl-spanwise-loads-json",
        str(artifact_path),
        "--target-shape-z-scale",
        f"{target_shape_z_scale:.12g}",
        "--dihedral-exponent",
        f"{float(dihedral_exponent):.12g}",
        "--refresh-steps",
        "0",
        "--skip-local-refine",
        "--skip-step-export",
        "--no-ground-clearance-recovery",
        "--main-plateau-grid",
        "0.0,1.0",
        "--main-taper-fill-grid",
        "0.0,1.0",
        "--rear-radius-grid",
        "0.0,1.0",
        "--rear-outboard-grid",
        "0.0,1.0",
        "--wall-thickness-grid",
        "0.0,1.0",
        "--cobyla-maxiter",
        "40",
        "--rib-zonewise-mode",
        "limited_zonewise",
    ]
    if rerun or not summary_path.exists():
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "command.txt").write_text(" ".join(command) + "\n", encoding="utf-8")
        (case_dir / "stdout.log").write_text(completed.stdout, encoding="utf-8")
        (case_dir / "stderr.log").write_text(completed.stderr, encoding="utf-8")
        returncode = completed.returncode
    else:
        returncode = 0

    row: dict[str, Any] = {
        "case_label": label,
        "requested_target_main_tip_z_m": float(target_main_tip_z_m),
        "target_shape_z_scale_generator": float(target_shape_z_scale),
        "dihedral_exponent": float(dihedral_exponent),
        "returncode": int(returncode),
        "summary_path": str(summary_path.resolve()) if summary_path.exists() else "",
        "case_dir": str(case_dir.resolve()),
        "candidate_avl_artifact": str(artifact_path.resolve()),
        "design_report": str(design_report.resolve()),
    }
    if not summary_path.exists():
        row["run_succeeded"] = False
        row["message"] = "summary_not_written"
        return row

    summary = _read_json(summary_path)
    final_iteration = (summary.get("iterations") or [{}])[-1]
    selected = final_iteration.get("selected") or {}
    run_metrics = final_iteration.get("run_metrics") or {}
    row.update(
        {
            "run_succeeded": True,
            "overall_feasible": bool(selected.get("overall_feasible")),
            "tube_mass_kg": selected.get("tube_mass_kg"),
            "total_structural_mass_kg": selected.get("total_structural_mass_kg"),
            "tube_mass_margin_vs_11p7534_kg": SPAR_TUBE_MASS_LINE_KG
            - _float(selected.get("tube_mass_kg")),
            "passes_11p7534_tube_mass_line": _float(selected.get("tube_mass_kg"))
            <= SPAR_TUBE_MASS_LINE_KG,
            "jig_ground_clearance_min_m": selected.get("jig_ground_clearance_min_m"),
            "max_jig_vertical_prebend_m": selected.get("max_jig_vertical_prebend_m"),
            "max_jig_vertical_curvature_per_m": selected.get("max_jig_vertical_curvature_per_m"),
            "equivalent_tip_deflection_m": selected.get("equivalent_tip_deflection_m"),
            "equivalent_twist_max_deg": selected.get("equivalent_twist_max_deg"),
            "equivalent_failure_index": selected.get("equivalent_failure_index"),
            "equivalent_buckling_index": selected.get("equivalent_buckling_index"),
            "loaded_shape_main_z_error_max_m": selected.get("loaded_shape_main_z_error_max_m"),
            "target_shape_error_max_m": selected.get("target_shape_error_max_m"),
            "selected_source": selected.get("source"),
            "failures": "|".join(str(item) for item in (selected.get("failures") or [])),
            "coarse_candidate_count": final_iteration.get("outcome", {}).get(
                "coarse_candidate_count",
                run_metrics.get("coarse_candidate_count", ""),
            ),
            "coarse_feasible_count": final_iteration.get("outcome", {}).get(
                "coarse_feasible_count",
                run_metrics.get("coarse_feasible_count", ""),
            ),
            "rib_design_key": (selected.get("rib_design") or {}).get("design_key"),
            "rib_effective_knockdown": (selected.get("rib_design") or {}).get(
                "effective_warping_knockdown"
            ),
            "message": selected.get("message", ""),
        }
    )
    design_mm = selected.get("design_mm") or {}
    for key in ("main_r", "main_t", "rear_r", "rear_t"):
        if key in design_mm:
            row[f"{key}_mm"] = json.dumps(design_mm[key], separators=(",", ":"))

    target_shape = selected.get("target_loaded_shape") or {}
    target_main_tip_z, target_rear_tip_z = _tip_z_from_shape_dict(target_shape)
    target_root_main_z, target_root_rear_z = _root_z_from_shape_dict(target_shape)
    if target_main_tip_z == target_main_tip_z:
        row["actual_target_main_tip_z_m"] = target_main_tip_z
        row["actual_target_rear_tip_z_m"] = target_rear_tip_z
        row["actual_target_root_main_z_m"] = target_root_main_z
        row["actual_target_root_rear_z_m"] = target_root_rear_z

    target_csv = case_dir / "target_loaded_shape_spar_data.csv"
    jig_csv = case_dir / "jig_shape_spar_data.csv"
    if target_csv.exists():
        main_tip_z, rear_tip_z = _target_tip_from_csv(target_csv)
        target_rows = _read_csv_rows(target_csv)
        row["export_csv_target_main_tip_z_m"] = main_tip_z
        row["export_csv_target_rear_tip_z_m"] = rear_tip_z
        row["export_csv_target_root_main_z_m"] = _float(target_rows[0]["Main_Z_m"])
        row["export_csv_target_root_rear_z_m"] = _float(target_rows[0]["Rear_Z_m"])
    if jig_csv.exists():
        jig_rows = _read_csv_rows(jig_csv)
        row["jig_main_tip_z_m"] = _float(jig_rows[-1]["Main_Z_m"])
        row["jig_rear_tip_z_m"] = _float(jig_rows[-1]["Rear_Z_m"])
    return row


def _augment_with_bisection(
    rows: list[dict[str, Any]],
    *,
    max_extra: int,
) -> list[float]:
    good_rows = [
        row
        for row in rows
        if row.get("run_succeeded")
        and _float(row.get("tube_mass_kg")) == _float(row.get("tube_mass_kg"))
    ]
    good_rows.sort(key=lambda row: _float(row["actual_target_main_tip_z_m"]))
    for lower, upper in zip(good_rows[:-1], good_rows[1:]):
        lower_pass = bool(lower.get("passes_11p7534_tube_mass_line"))
        upper_pass = bool(upper.get("passes_11p7534_tube_mass_line"))
        if lower_pass == upper_pass:
            continue
        lo = _float(lower["requested_target_main_tip_z_m"])
        hi = _float(upper["requested_target_main_tip_z_m"])
        extras: list[float] = []
        for _ in range(max(0, int(max_extra))):
            mid = round(0.5 * (lo + hi), 6)
            if mid <= min(lo, hi) or mid >= max(lo, hi):
                break
            extras.append(mid)
            lo = mid
        return extras
    return []


def _write_report(output_dir: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    sorted_rows = sorted(rows, key=lambda row: _float(row.get("actual_target_main_tip_z_m", row.get("requested_target_main_tip_z_m"))))
    pass_rows = [
        row for row in sorted_rows if bool(row.get("passes_11p7534_tube_mass_line"))
    ]
    best_pass = min(pass_rows, key=lambda row: _float(row.get("actual_target_main_tip_z_m"))) if pass_rows else None
    practical_pass_10mm = min(
        (
            row
            for row in pass_rows
            if _float(row.get("jig_ground_clearance_min_m")) >= 0.010
        ),
        key=lambda row: _float(row.get("actual_target_main_tip_z_m")),
        default=None,
    )
    practical_pass_20mm = min(
        (
            row
            for row in pass_rows
            if _float(row.get("jig_ground_clearance_min_m")) >= 0.020
        ),
        key=lambda row: _float(row.get("actual_target_main_tip_z_m")),
        default=None,
    )
    lightest = min(
        (row for row in sorted_rows if row.get("run_succeeded")),
        key=lambda row: _float(row.get("tube_mass_kg")),
        default=None,
    )
    lines = [
        "# Smooth Baseline Z-State Mass Sweep",
        "",
        "This diagnostic holds the smooth Tier2 production planform and AVL spanload fixed, then varies the requested loaded beam-line Z state. The reported threshold is based on actual target spar-tip Z coordinates; the scale column is only the generator knob used by the canonical script.",
        "",
        f"- spar tube mass line: {SPAR_TUBE_MASS_LINE_KG:.4f} kg",
        "- aero source: candidate_avl_spanwise from smooth_tier2_production_baseline",
        "- structural search: canonical direct_dual_beam_inverse_design.py, refresh_steps=0, skip_local_refine, skip_step_export, limited_zonewise ribs, no ground-clearance recovery",
        "- z-state source of truth: selected.target_loaded_shape in each summary JSON; the per-case target_loaded_shape_spar_data.csv export is retained as a legacy artifact and may show the unscaled base geometry in this diagnostic",
        "",
    ]
    if best_pass is None:
        lines.append("No sampled Z state passed the 11.7534 kg spar-tube line.")
    else:
        lines.extend(
            [
                "First sampled pass of the 11.7534 kg spar-tube line:",
                f"- target main tip z: {_float(best_pass.get('actual_target_main_tip_z_m')):.3f} m",
                f"- target rear tip z: {_float(best_pass.get('actual_target_rear_tip_z_m')):.3f} m",
                f"- tube mass: {_float(best_pass.get('tube_mass_kg')):.3f} kg",
                f"- total structural mass: {_float(best_pass.get('total_structural_mass_kg')):.3f} kg",
                f"- jig clearance min: {_float(best_pass.get('jig_ground_clearance_min_m')) * 1000.0:.1f} mm",
                f"- max jig prebend: {_float(best_pass.get('max_jig_vertical_prebend_m')):.3f} m",
                f"- equivalent tip deflection: {_float(best_pass.get('equivalent_tip_deflection_m')):.3f} m",
                "",
            ]
        )
        if practical_pass_10mm is not None:
            lines.extend(
                [
                    "First sampled pass with at least 10 mm jig clearance:",
                    f"- target main tip z: {_float(practical_pass_10mm.get('actual_target_main_tip_z_m')):.3f} m",
                    f"- tube mass: {_float(practical_pass_10mm.get('tube_mass_kg')):.3f} kg",
                    f"- jig clearance min: {_float(practical_pass_10mm.get('jig_ground_clearance_min_m')) * 1000.0:.1f} mm",
                    "",
                ]
            )
        if practical_pass_20mm is not None:
            lines.extend(
                [
                    "First sampled pass with at least 20 mm jig clearance:",
                    f"- target main tip z: {_float(practical_pass_20mm.get('actual_target_main_tip_z_m')):.3f} m",
                    f"- tube mass: {_float(practical_pass_20mm.get('tube_mass_kg')):.3f} kg",
                    f"- jig clearance min: {_float(practical_pass_20mm.get('jig_ground_clearance_min_m')) * 1000.0:.1f} mm",
                    "",
                ]
            )
    if lightest is not None:
        lines.extend(
            [
                "Lightest sampled state:",
                f"- target main tip z: {_float(lightest.get('actual_target_main_tip_z_m')):.3f} m",
                f"- tube mass: {_float(lightest.get('tube_mass_kg')):.3f} kg",
                f"- selected main wall mm: {lightest.get('main_t_mm', '')}",
                f"- selected rear wall mm: {lightest.get('rear_t_mm', '')}",
                "",
            ]
        )
    lines.extend(
        [
            "Engineering read:",
            "- The previous high-mass smooth result was not a proof that the new design is structurally heavy; it was a low-Z requested-shape state.",
            "- Passing the old spar-tube mass line requires enough requested loaded Z for the inverse jig to accept larger elastic recovery while maintaining clearance and manufacturing limits.",
            "- These rows are still a diagnostic sweep, not a final structural gate change.",
        ]
    )
    (output_dir / "z_state_mass_sweep_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Find what smooth-baseline loaded-Z state can recover the old 11 kg spar tube line."
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--target-main-tip-z-m",
        default="1.065,1.5,2.0,2.5,3.0,3.25,3.5,3.75,4.0,4.25",
        help="Comma-separated requested main-spar target tip Z states [m].",
    )
    parser.add_argument("--dihedral-exponent", type=float, default=1.0)
    parser.add_argument("--bisect-extra", type=int, default=3)
    parser.add_argument("--rerun", action="store_true")
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path, manifest = build_smooth_canonical_config(output_dir)
    base_tip_z = _base_main_tip_z_m()
    design_report = DEFAULT_DESIGN_REPORT if DEFAULT_DESIGN_REPORT.exists() else FALLBACK_DESIGN_REPORT
    if not design_report.exists():
        raise FileNotFoundError(f"No design report found: {DEFAULT_DESIGN_REPORT} or {FALLBACK_DESIGN_REPORT}")

    rows: list[dict[str, Any]] = []
    targets = _parse_target_tips(str(args.target_main_tip_z_m))
    for target in targets:
        print(f"[z-state] running target main tip z={target:.3f} m")
        rows.append(
            _run_case(
                output_dir=output_dir,
                config_path=config_path,
                design_report=design_report,
                target_main_tip_z_m=target,
                base_main_tip_z_m=base_tip_z,
                dihedral_exponent=float(args.dihedral_exponent),
                rerun=bool(args.rerun),
            )
        )

    extra_targets = _augment_with_bisection(rows, max_extra=int(args.bisect_extra))
    for target in extra_targets:
        print(f"[z-state] refining target main tip z={target:.3f} m")
        rows.append(
            _run_case(
                output_dir=output_dir,
                config_path=config_path,
                design_report=design_report,
                target_main_tip_z_m=target,
                base_main_tip_z_m=base_tip_z,
                dihedral_exponent=float(args.dihedral_exponent),
                rerun=bool(args.rerun),
            )
        )

    rows = sorted(
        rows,
        key=lambda row: _float(row.get("actual_target_main_tip_z_m", row.get("requested_target_main_tip_z_m"))),
    )
    _write_csv(output_dir / "z_state_mass_sweep.csv", rows)
    manifest.update(
        {
            "workflow": "smooth_tier2_z_state_to_spar_mass_line_sweep",
            "base_main_tip_z_m": base_tip_z,
            "spar_tube_mass_line_kg": SPAR_TUBE_MASS_LINE_KG,
            "design_report": str(design_report.resolve()),
            "target_main_tip_z_m_requested": targets,
            "dihedral_exponent": float(args.dihedral_exponent),
            "notes": [
                "target_shape_z_scale is used only as a generator for actual target loaded-Z states.",
                "candidate AVL spanload is held fixed to isolate structural Z-state sensitivity.",
                "actual_target_* columns are parsed from selected.target_loaded_shape in the summary JSON because the legacy target_loaded_shape_spar_data.csv export can remain unscaled.",
            ],
        }
    )
    (output_dir / "z_state_sweep_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_report(output_dir, rows)
    print(f"Wrote {output_dir / 'z_state_mass_sweep.csv'}")
    print(f"Wrote {output_dir / 'z_state_mass_sweep_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
