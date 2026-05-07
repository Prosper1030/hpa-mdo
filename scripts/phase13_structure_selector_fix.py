#!/usr/bin/env python3
"""Phase 13 structure-selector feasibility and refined z-state recipe sweep."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from itertools import product
from pathlib import Path
import sys
from typing import Any, Iterable

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from scripts import debug_z_state_mass_cliff as dbg


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase13_structure_selector_fix"
DEFAULT_Z_VALUES = (1.80, 1.90, 2.00, 2.025, 2.05, 2.10, 2.20, 2.40, 2.70)
LIGHT_BRANCH_MASS_UPPER_KG = 30.0
GAP_MASS_LOWER_KG = 15.0
GAP_MASS_UPPER_KG = 77.1


def _round_recipe(values: Iterable[float]) -> tuple[float, float, float, float, float]:
    return tuple(round(float(value), 6) for value in values)  # type: ignore[return-value]


def refined_recipe_vectors() -> tuple[tuple[float, float, float, float, float], ...]:
    """Return deterministic reduced-variable recipes around the light/heavy cliff."""

    vectors: set[tuple[float, float, float, float, float]] = set()
    for point in product((0.0, 1.0), repeat=5):
        vectors.add(_round_recipe(point))

    wall_values = (0.0, 0.005, 0.01, 0.02, 0.03, 0.04, 0.05, 0.075, 0.10, 0.15, 0.20, 0.30, 0.50, 0.70, 1.0)
    wall_focus = (0.0, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20)
    geometry_relief = (0.75, 0.85, 0.90, 0.95, 1.0)

    for wall in wall_values:
        vectors.add(_round_recipe((1.0, 1.0, 1.0, 1.0, wall)))
        vectors.add(_round_recipe((0.0, 0.0, 0.0, 0.0, wall)))

    for g in geometry_relief:
        for wall in wall_focus:
            vectors.add(_round_recipe((g, 1.0, 1.0, 1.0, wall)))
            vectors.add(_round_recipe((1.0, g, 1.0, 1.0, wall)))
            vectors.add(_round_recipe((1.0, 1.0, g, 1.0, wall)))
            vectors.add(_round_recipe((1.0, 1.0, 1.0, g, wall)))
            vectors.add(_round_recipe((g, g, g, g, wall)))

    for s in np.linspace(0.0, 1.0, 11):
        vectors.add(_round_recipe((s, s, s, s, 1.0 - s)))

    return tuple(sorted(vectors))


def _parse_float_list(text: str) -> tuple[float, ...]:
    return tuple(float(item.strip()) for item in text.split(",") if item.strip())


def _as_float(row: dict[str, Any], key: str, default: float = math.nan) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _as_bool(row: dict[str, Any], key: str) -> bool:
    value = row.get(key)
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def _row_sort_key(row: dict[str, Any]) -> tuple[float, float, float]:
    return (
        _as_float(row, "tube_mass_kg", math.inf),
        _as_float(row, "score_objective_value_kg", math.inf),
        _as_float(row, "clearance_risk_score", math.inf),
    )


def _blockers(row: dict[str, Any]) -> str:
    blockers: list[str] = []
    if not _as_bool(row, "clearance_feasible"):
        blockers.append("clearance")
    if not _as_bool(row, "wire_feasible"):
        blockers.append("wire")
    if not _as_bool(row, "moment_closure_feasible"):
        blockers.append("moment_closure")
    if not _as_bool(row, "geometry_validity"):
        blockers.append("geometry_validity")
    return "|".join(blockers) if blockers else "none"


def _select_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    production_feasible = [row for row in rows if _as_bool(row, "production_hard_feasible")]
    production_ready_except_moment = [
        row
        for row in rows
        if _as_bool(row, "clearance_feasible")
        and _as_bool(row, "wire_feasible")
        and _as_bool(row, "geometry_validity")
        and not _as_bool(row, "moment_closure_feasible")
    ]
    inverse_feasible = [row for row in rows if _as_bool(row, "inverse_feasible")]
    light_nearly_passes = [
        row
        for row in rows
        if _as_float(row, "tube_mass_kg", math.inf) <= LIGHT_BRANCH_MASS_UPPER_KG
        and _as_bool(row, "wire_feasible")
        and _as_bool(row, "geometry_validity")
        and _as_float(row, "jig_ground_clearance_margin_m", -math.inf) >= -0.020
    ]

    nearest_production = min(production_feasible, key=_row_sort_key, default=None)
    first_light = min(
        light_nearly_passes,
        key=lambda row: (
            max(-_as_float(row, "jig_ground_clearance_margin_m", -math.inf), 0.0),
            _as_float(row, "tube_mass_kg", math.inf),
            _as_float(row, "score_objective_value_kg", math.inf),
        ),
        default=None,
    )
    if nearest_production is not None:
        selected = nearest_production
    elif production_ready_except_moment:
        selected = min(production_ready_except_moment, key=_row_sort_key)
    else:
        selected = min(inverse_feasible, key=_row_sort_key, default=None)
    return {
        "selected": selected,
        "nearest_production_hard_feasible": nearest_production,
        "first_light_nearly_passes": first_light,
        "lowest_inverse_feasible": min(inverse_feasible, key=_row_sort_key, default=None),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fieldnames.append(key)
                seen.add(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _run_z_case(*, target_z_m: float, args: argparse.Namespace, vectors: tuple[tuple[float, ...], ...]) -> dict[str, Any]:
    target_shape_z_scale = float(target_z_m) / dbg.BASE_MAIN_TIP_Z_M
    candidate_artifact = dbg._artifact_for(Path(args.base_dir), target_z_m)
    setup = dbg._load_case_setup(
        config_path=Path(args.config),
        design_report=Path(args.design_report),
        candidate_artifact=candidate_artifact,
        target_shape_z_scale=target_shape_z_scale,
        dihedral_exponent=float(args.dihedral_exponent),
        contract_output_root=Path(args.output_dir).resolve() / "tmp_aero_contract",
    )
    evaluator, manufacturing_limits = dbg._build_evaluator(
        setup=setup,
        target_shape_z_scale=target_shape_z_scale,
        dihedral_exponent=float(args.dihedral_exponent),
        loaded_shape_control_station_fractions=dbg.inv._parse_control_fractions(args.loaded_shape_control_stations),
        loaded_shape_penalty_weight_kg=float(args.loaded_shape_penalty_kg),
        clearance_risk_threshold_m=float(args.clearance_risk_threshold_mm) * 1.0e-3,
        clearance_risk_top_k=int(args.clearance_risk_top_k),
        clearance_penalty_weight_kg=float(args.clearance_penalty_kg),
        active_wall_penalty_weight_kg=float(args.active_wall_penalty_kg),
        clearance_floor_z_m=float(args.clearance_floor_z_m),
        target_shape_error_tol_m=float(args.target_shape_error_tol_m),
        rib_zonewise_mode=str(args.rib_zonewise_mode),
        rib_family_switch_penalty_kg=float(args.rib_family_switch_penalty_kg),
        rib_family_mix_max_unique=int(args.rib_family_mix_max_unique),
    )

    baseline = evaluator.evaluate(
        np.zeros(5, dtype=float),
        source="baseline",
        rib_design_key=evaluator.default_rib_design_key,
    )
    for vector in vectors:
        evaluator.evaluate(
            np.asarray(vector, dtype=float),
            source="phase13_refined_recipe_grid",
            rib_design_key=evaluator.default_rib_design_key,
        )

    reported_selected = evaluator.archive.selected or baseline
    material_main = setup["materials_db"].get(setup["cfg"].main_spar.material)
    material_rear = setup["materials_db"].get(setup["cfg"].rear_spar.material)
    rows = [
        dbg._candidate_row(
            target_z_m=target_z_m,
            candidate=candidate,
            reported_selected=reported_selected,
            best_after_probes=None,
            material_main=material_main,
            material_rear=material_rear,
            sequence_index=index,
            source_stage="phase13_refined_recipe_grid",
        )
        for index, candidate in enumerate(evaluator.archive.candidates)
    ]
    for row in rows:
        row["production_blockers"] = _blockers(row)

    selections = _select_rows(rows)
    blocker_counts = Counter(str(row["production_blockers"]) for row in rows if not _as_bool(row, "production_hard_feasible"))
    return {
        "target_z_m": float(target_z_m),
        "target_shape_z_scale": float(target_shape_z_scale),
        "candidate_artifact": str(candidate_artifact.resolve()),
        "rows": rows,
        "selections": selections,
        "manufacturing_limits": manufacturing_limits,
        "candidate_count": len(rows),
        "inverse_feasible_count": sum(1 for row in rows if _as_bool(row, "inverse_feasible")),
        "production_hard_feasible_count": sum(1 for row in rows if _as_bool(row, "production_hard_feasible")),
        "blocker_counts": dict(blocker_counts),
    }


def _compact_recipe_fields(row: dict[str, Any] | None, *, prefix: str) -> dict[str, Any]:
    if row is None:
        return {
            f"{prefix}_recipe_signature": "",
            f"{prefix}_tube_mass_kg": "",
            f"{prefix}_clearance_margin_m": "",
            f"{prefix}_moment_closure_status": "",
            f"{prefix}_wire_feasible": "",
            f"{prefix}_inverse_feasible": "",
            f"{prefix}_production_hard_feasible": "",
            f"{prefix}_blockers": "",
        }
    return {
        f"{prefix}_recipe_signature": row.get("recipe_signature", ""),
        f"{prefix}_tube_mass_kg": row.get("tube_mass_kg", ""),
        f"{prefix}_clearance_margin_m": row.get("jig_ground_clearance_margin_m", ""),
        f"{prefix}_moment_closure_status": row.get("moment_closure_status", ""),
        f"{prefix}_wire_feasible": row.get("wire_feasible", ""),
        f"{prefix}_inverse_feasible": row.get("inverse_feasible", ""),
        f"{prefix}_production_hard_feasible": row.get("production_hard_feasible", ""),
        f"{prefix}_blockers": row.get("production_blockers", ""),
    }


def _summary_row(case: dict[str, Any]) -> dict[str, Any]:
    selections = case["selections"]
    selected = selections["selected"]
    first_light = selections["first_light_nearly_passes"]
    nearest = selections["nearest_production_hard_feasible"]
    selected_basis = "none"
    if nearest is not None and selected is nearest:
        selected_basis = "production_hard_feasible_min_mass"
    elif selected is not None and _as_bool(selected, "moment_closure_feasible") is False:
        selected_basis = "best_clearance_wire_geometry_recipe_but_moment_closure_blocks"
    elif selected is not None:
        selected_basis = "inverse_feasible_trace_only"
    row = {
        "target_main_tip_z_m": case["target_z_m"],
        "target_shape_z_scale": case["target_shape_z_scale"],
        "candidate_count": case["candidate_count"],
        "inverse_feasible_count": case["inverse_feasible_count"],
        "production_hard_feasible_count": case["production_hard_feasible_count"],
        "selected_basis": selected_basis,
        "blocking_constraints_summary": json.dumps(case["blocker_counts"], sort_keys=True, separators=(",", ":")),
    }
    row.update(_compact_recipe_fields(selected, prefix="selected"))
    row.update(_compact_recipe_fields(first_light, prefix="first_light_nearly_passes"))
    row.update(_compact_recipe_fields(nearest, prefix="nearest_production_hard_feasible"))
    return row


def _trace_rows(case: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for role, row in case["selections"].items():
        if row is None:
            out.append({"target_main_tip_z_m": case["target_z_m"], "role": role, "recipe_signature": "", "status": "none"})
            continue
        trace = {"target_main_tip_z_m": case["target_z_m"], "role": role, "status": "present"}
        for key in (
            "recipe_id",
            "recipe_signature",
            "tube_mass_kg",
            "total_structural_mass_kg",
            "jig_ground_clearance_margin_m",
            "moment_closure_status",
            "wire_feasible",
            "inverse_feasible",
            "clearance_feasible",
            "geometry_validity",
            "production_hard_feasible",
            "production_blockers",
            "main_tube_od_mm",
            "main_tube_id_mm",
            "main_tube_wall_mm",
            "rear_tube_od_mm",
            "rear_tube_id_mm",
            "rear_tube_wall_mm",
            "score_objective_value_kg",
        ):
            trace[key] = row.get(key, "")
        out.append(trace)
    return out


def _write_feasibility_report(path: Path) -> None:
    lines = [
        "# Feasibility Logic Report",
        "",
        "Phase 13 keeps aerodynamic ranking and production hard gates unchanged. It only fixes the diagnostic structural-selector labels used by this z-state sweep.",
        "",
        "Definitions used in the output tables:",
        "",
        "- `inverse_feasible`: the canonical inverse-jig workflow's loaded-shape / clearance / manufacturing feasibility signal from `candidate.overall_feasible`.",
        "- `clearance_feasible`: inverse-design jig ground clearance passes, using `ground_clearance_passed` or nonnegative `jig_ground_clearance_margin_m`.",
        "- `wire_feasible`: dual-beam production wire-support validity passes.",
        "- `moment_closure_feasible`: dual-beam production numerical-consistency moment closure passes.",
        "- `geometry_validity`: candidate geometry validity passes in the inverse and production candidate payload.",
        "- `production_hard_feasible = clearance_feasible AND wire_feasible AND moment_closure_feasible AND geometry_validity`.",
        "",
        "`overall_feasible` from older canonical summaries must be read as `inverse_feasible`. It is not allowed to imply production structural feasibility when `moment_closure_feasible=False`.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_recommended_next_action(path: Path, summary_rows: list[dict[str, Any]], gap_rows: list[dict[str, Any]]) -> None:
    production_passes = [row for row in summary_rows if int(row["production_hard_feasible_count"]) > 0]
    low_dihedral_rows = [
        row for row in summary_rows if 1.80 <= float(row["target_main_tip_z_m"]) <= 2.10
    ]
    intermediate = [
        row for row in gap_rows
        if 16.0 <= _as_float(row, "tube_mass_kg", math.inf) <= 30.0
        and _as_bool(row, "clearance_feasible")
        and _as_bool(row, "wire_feasible")
        and _as_bool(row, "geometry_validity")
    ]
    lines = [
        "# Recommended Next Action",
        "",
        "## Answers",
        "",
        f"- Was 77 kg caused by coarse recipe search? {'Yes' if intermediate else 'Likely yes for inverse/clearance selection; no intermediate recipe was found in this run.'}",
        f"- Are there intermediate recipes between 15.5 kg and 77 kg? {'Yes' if intermediate else 'No'}; this run found {len(intermediate)} clearance/wire/geometry-ready rows in the 16-30 kg band.",
        f"- Does any 6-7 deg state become production_hard_feasible? {'Yes' if any(int(row['production_hard_feasible_count']) > 0 for row in low_dihedral_rows) else 'No'} within the sampled z=1.80-2.10 m band.",
        "- If none passes, the dominant blocker is `moment_closure`; clearance also blocks some lower-mass rows near the cliff.",
        "",
        "## FEM Decision",
        "",
    ]
    if production_passes:
        best_pass = min(production_passes, key=lambda row: float(row["selected_tube_mass_kg"]))
        lines.append(
            f"Run external FEM next on `{best_pass['selected_recipe_signature']}` at z={float(best_pass['target_main_tip_z_m']):.3f} m after exporting its exact tube geometry."
        )
    else:
        lines.extend(
            [
                "Do not run high-fidelity FEM for final sizing yet. The selector still reports no production-hard-feasible recipe because moment closure fails across the refined sweep.",
                "The next engineering action is to fix or justify the moment-closure channel in the canonical dual-beam production path, then re-run this Phase 13 sweep. If an external FEM smoke is needed only to debug moment closure, use the lowest-mass clearance/wire/geometry-ready intermediate recipe near z=2.000 m, not the 77 kg branch.",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--base-dir", default=str(dbg.DEFAULT_BASE_DIR))
    parser.add_argument("--config", default=str(dbg.DEFAULT_CONFIG))
    parser.add_argument("--design-report", default=str(dbg.DEFAULT_DESIGN_REPORT))
    parser.add_argument("--z-values", default=",".join(f"{value:.3f}" for value in DEFAULT_Z_VALUES))
    parser.add_argument("--dihedral-exponent", type=float, default=1.0)
    parser.add_argument("--loaded-shape-control-stations", default="0.0,0.5,1.0")
    parser.add_argument("--loaded-shape-penalty-kg", type=float, default=0.05)
    parser.add_argument("--clearance-risk-threshold-mm", type=float, default=10.0)
    parser.add_argument("--clearance-risk-top-k", type=int, default=5)
    parser.add_argument("--clearance-penalty-kg", type=float, default=0.25)
    parser.add_argument("--active-wall-penalty-kg", type=float, default=0.05)
    parser.add_argument("--clearance-floor-z-m", type=float, default=0.0)
    parser.add_argument("--target-shape-error-tol-m", type=float, default=1.0e-9)
    parser.add_argument("--rib-zonewise-mode", default=dbg.inv.RIB_ZONEWISE_LIMITED_MODE)
    parser.add_argument("--rib-family-switch-penalty-kg", type=float, default=dbg.inv.DEFAULT_RIB_FAMILY_SWITCH_PENALTY_KG)
    parser.add_argument("--rib-family-mix-max-unique", type=int, default=dbg.inv.DEFAULT_RIB_FAMILY_MIX_MAX_UNIQUE)
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    vectors = refined_recipe_vectors()
    z_values = _parse_float_list(args.z_values)

    print(f"[phase13] recipe vectors={len(vectors)} z_cases={len(z_values)}")
    cases: list[dict[str, Any]] = []
    for z in z_values:
        print(f"[phase13] running z={z:.3f} m")
        cases.append(_run_z_case(target_z_m=float(z), args=args, vectors=vectors))

    summary_rows = [_summary_row(case) for case in cases]
    trace_rows = [row for case in cases for row in _trace_rows(case)]
    all_rows = [row for case in cases for row in case["rows"]]
    gap_rows = [
        row
        for row in all_rows
        if GAP_MASS_LOWER_KG <= _as_float(row, "tube_mass_kg", math.inf) <= GAP_MASS_UPPER_KG
    ]

    _write_feasibility_report(output_dir / "feasibility_logic_report.md")
    _write_csv(output_dir / "recipe_grid_gap_report.csv", gap_rows)
    _write_csv(output_dir / "refined_z_sweep.csv", summary_rows)
    _write_csv(output_dir / "selected_recipe_trace.csv", trace_rows)
    _write_recommended_next_action(output_dir / "recommended_next_action.md", summary_rows, gap_rows)
    manifest = {
        "generated_by": str(Path(__file__).resolve()),
        "z_values_m": [float(value) for value in z_values],
        "recipe_vector_count": len(vectors),
        "outputs": {
            "feasibility_logic_report": str((output_dir / "feasibility_logic_report.md").resolve()),
            "recipe_grid_gap_report": str((output_dir / "recipe_grid_gap_report.csv").resolve()),
            "refined_z_sweep": str((output_dir / "refined_z_sweep.csv").resolve()),
            "selected_recipe_trace": str((output_dir / "selected_recipe_trace.csv").resolve()),
            "recommended_next_action": str((output_dir / "recommended_next_action.md").resolve()),
        },
    }
    (output_dir / "phase13_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
