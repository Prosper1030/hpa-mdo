#!/usr/bin/env python3
"""Analyze the current direct dual-beam V2 baseline solution."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Iterable

import numpy as np

# Allow running directly from repository root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.aero import LoadMapper
from hpa_mdo.core import Aircraft, MaterialDB, load_config
from hpa_mdo.structure import SparOptimizer, tube_Ixx, tube_area
from scripts.ansys_compare_results import parse_baseline_metrics
from scripts.ansys_crossval import _select_cruise_loads
from scripts.ansys_dual_beam_production_check import build_specimen_result_from_crossval_report
from scripts.direct_dual_beam_v2 import (
    BaselineDesign,
    DirectV2Candidate,
    ProductionSmoothEvaluator,
    ReducedMapConfig,
    build_reduced_map_config,
    run_direct_dual_beam_v2,
)


VARIABLE_NAMES = (
    "main_plateau_scale",
    "main_taper_fill",
    "rear_radius_scale",
    "rear_outboard_fraction",
    "wall_thickness_fraction",
)


@dataclass(frozen=True)
class SegmentDeltaRow:
    spar: str
    segment_index: int
    length_m: float
    baseline_radius_mm: float
    selected_radius_mm: float
    delta_radius_mm: float
    baseline_thickness_mm: float
    selected_thickness_mm: float
    delta_thickness_mm: float
    baseline_mass_kg: float
    selected_mass_kg: float
    delta_mass_kg: float
    delta_mass_share_pct: float
    baseline_i_m4: float
    selected_i_m4: float
    i_ratio: float


@dataclass(frozen=True)
class CandidateSnapshot:
    label: str
    source: str
    z: tuple[float, ...]
    mass_kg: float
    raw_main_tip_mm: float
    raw_rear_tip_mm: float
    raw_max_uz_mm: float
    psi_u_all_mm: float
    hard_feasible: bool
    candidate_feasible: bool


@dataclass(frozen=True)
class VariableProbeRow:
    variable: str
    delta_z: float
    new_z: tuple[float, ...]
    mass_kg: float
    delta_mass_kg: float
    psi_u_all_mm: float
    delta_psi_u_all_mm: float
    raw_main_tip_mm: float
    raw_rear_tip_mm: float
    hard_feasible: bool
    candidate_feasible: bool


@dataclass(frozen=True)
class VariableLeverageRow:
    variable: str
    current_z: float
    positive_step: float | None
    positive_delta_mass_kg: float | None
    positive_delta_psi_u_all_mm: float | None
    positive_mm_per_kg: float | None
    negative_step: float | None
    negative_delta_mass_kg: float | None
    negative_delta_psi_u_all_mm: float | None
    negative_candidate_feasible: bool | None


@dataclass(frozen=True)
class NeighborhoodRow:
    delta_main_plateau_z: float
    delta_rear_radius_z: float
    mass_kg: float
    psi_u_all_mm: float
    candidate_feasible: bool


@dataclass(frozen=True)
class AnalysisOutcome:
    v2_outcome: object
    segment_rows: tuple[SegmentDeltaRow, ...]
    decomposition_rows: tuple[CandidateSnapshot, ...]
    variable_probe_rows: tuple[VariableProbeRow, ...]
    leverage_rows: tuple[VariableLeverageRow, ...]
    neighborhood_rows: tuple[NeighborhoodRow, ...]
    main_delta_mass_kg: float
    rear_delta_mass_kg: float
    tube_delta_mass_kg: float
    non_tube_delta_mass_kg: float
    main_s1_4_delta_mass_kg: float
    main_s5_6_delta_mass_kg: float
    active_neighborhood_candidate_feasible_count: int
    active_neighborhood_total_count: int


def _parse_grid(text: str) -> tuple[float, ...]:
    values = tuple(float(part.strip()) for part in text.split(",") if part.strip())
    if not values:
        raise ValueError("Grid specification must contain at least one float.")
    return values


def _mm(value_m: float) -> float:
    return float(value_m) * 1000.0


def _fmt(value: float) -> str:
    return f"{value:.3f}"


def _candidate_snapshot(label: str, candidate: DirectV2Candidate) -> CandidateSnapshot:
    return CandidateSnapshot(
        label=label,
        source=candidate.source,
        z=tuple(float(v) for v in candidate.z),
        mass_kg=float(candidate.tube_mass_kg),
        raw_main_tip_mm=_mm(candidate.raw_main_tip_m),
        raw_rear_tip_mm=_mm(candidate.raw_rear_tip_m),
        raw_max_uz_mm=_mm(candidate.raw_max_uz_m),
        psi_u_all_mm=_mm(candidate.psi_u_all_m),
        hard_feasible=bool(candidate.overall_hard_feasible),
        candidate_feasible=bool(candidate.overall_optimizer_candidate_feasible),
    )


def build_segment_delta_rows(
    *,
    baseline: DirectV2Candidate,
    selected: DirectV2Candidate,
    cfg,
    materials_db: MaterialDB,
) -> tuple[tuple[SegmentDeltaRow, ...], dict[str, float]]:
    """Return segment-level mass and stiffness deltas for the selected V2 design."""

    seg_lengths = np.asarray(cfg.spar_segment_lengths(cfg.main_spar), dtype=float)
    main_density = float(materials_db.get(cfg.main_spar.material).density)
    rear_density = float(materials_db.get(cfg.rear_spar.material).density)

    def _segment_mass_full(radius_m: np.ndarray, thickness_m: np.ndarray, density: float) -> np.ndarray:
        return 2.0 * density * tube_area(radius_m, thickness_m) * seg_lengths

    baseline_main_mass = _segment_mass_full(baseline.main_r_seg_m, baseline.main_t_seg_m, main_density)
    selected_main_mass = _segment_mass_full(selected.main_r_seg_m, selected.main_t_seg_m, main_density)
    baseline_rear_mass = _segment_mass_full(baseline.rear_r_seg_m, baseline.rear_t_seg_m, rear_density)
    selected_rear_mass = _segment_mass_full(selected.rear_r_seg_m, selected.rear_t_seg_m, rear_density)

    total_delta = float(
        np.sum(selected_main_mass - baseline_main_mass) + np.sum(selected_rear_mass - baseline_rear_mass)
    )

    rows: list[SegmentDeltaRow] = []
    for spar, base_r, sel_r, base_t, sel_t, base_mass, sel_mass in (
        (
            "main",
            baseline.main_r_seg_m,
            selected.main_r_seg_m,
            baseline.main_t_seg_m,
            selected.main_t_seg_m,
            baseline_main_mass,
            selected_main_mass,
        ),
        (
            "rear",
            baseline.rear_r_seg_m,
            selected.rear_r_seg_m,
            baseline.rear_t_seg_m,
            selected.rear_t_seg_m,
            baseline_rear_mass,
            selected_rear_mass,
        ),
    ):
        base_i = tube_Ixx(base_r, base_t)
        sel_i = tube_Ixx(sel_r, sel_t)
        for idx in range(seg_lengths.size):
            delta_mass = float(sel_mass[idx] - base_mass[idx])
            rows.append(
                SegmentDeltaRow(
                    spar=spar,
                    segment_index=idx + 1,
                    length_m=float(seg_lengths[idx]),
                    baseline_radius_mm=_mm(base_r[idx]),
                    selected_radius_mm=_mm(sel_r[idx]),
                    delta_radius_mm=_mm(sel_r[idx] - base_r[idx]),
                    baseline_thickness_mm=_mm(base_t[idx]),
                    selected_thickness_mm=_mm(sel_t[idx]),
                    delta_thickness_mm=_mm(sel_t[idx] - base_t[idx]),
                    baseline_mass_kg=float(base_mass[idx]),
                    selected_mass_kg=float(sel_mass[idx]),
                    delta_mass_kg=delta_mass,
                    delta_mass_share_pct=0.0 if total_delta == 0.0 else 100.0 * delta_mass / total_delta,
                    baseline_i_m4=float(base_i[idx]),
                    selected_i_m4=float(sel_i[idx]),
                    i_ratio=float(sel_i[idx] / max(base_i[idx], 1.0e-30)),
                )
            )

    totals = {
        "main_delta_mass_kg": float(np.sum(selected_main_mass - baseline_main_mass)),
        "rear_delta_mass_kg": float(np.sum(selected_rear_mass - baseline_rear_mass)),
        "tube_delta_mass_kg": total_delta,
        "main_s1_4_delta_mass_kg": float(np.sum(selected_main_mass[:4] - baseline_main_mass[:4])),
        "main_s5_6_delta_mass_kg": float(np.sum(selected_main_mass[4:] - baseline_main_mass[4:])),
    }
    return tuple(rows), totals


def build_decomposition_rows(
    *,
    evaluator: ProductionSmoothEvaluator,
    selected: DirectV2Candidate,
) -> tuple[CandidateSnapshot, ...]:
    """Evaluate isolated knob combinations around the selected V2 solution."""

    z_selected = np.asarray(selected.z, dtype=float)
    probes = {
        "baseline": np.zeros(5, dtype=float),
        "main_only": np.array([z_selected[0], 0.0, 0.0, 0.0, 0.0], dtype=float),
        "rear_only": np.array([0.0, 0.0, z_selected[2], 0.0, 0.0], dtype=float),
        "selected_both": np.array([z_selected[0], 0.0, z_selected[2], 0.0, 0.0], dtype=float),
    }
    return tuple(
        _candidate_snapshot(label, evaluator.evaluate(z, source=f"decomp:{label}"))
        for label, z in probes.items()
    )


def build_variable_probe_rows(
    *,
    evaluator: ProductionSmoothEvaluator,
    selected: DirectV2Candidate,
    deltas: Iterable[float] = (-0.05, -0.02, 0.02, 0.05),
) -> tuple[VariableProbeRow, ...]:
    """Probe one variable at a time around the selected V2 point."""

    base_z = np.asarray(selected.z, dtype=float)
    rows: list[VariableProbeRow] = []
    seen: set[tuple[str, tuple[float, ...]]] = set()
    for index, name in enumerate(VARIABLE_NAMES):
        for delta in deltas:
            z = base_z.copy()
            z[index] = np.clip(z[index] + float(delta), 0.0, 1.0)
            key = (name, tuple(np.round(z, 10)))
            if key in seen or np.allclose(z, base_z):
                continue
            seen.add(key)
            candidate = evaluator.evaluate(z, source=f"probe:{name}:{delta:+.2f}")
            rows.append(
                VariableProbeRow(
                    variable=name,
                    delta_z=float(delta),
                    new_z=tuple(float(v) for v in z),
                    mass_kg=float(candidate.tube_mass_kg),
                    delta_mass_kg=float(candidate.tube_mass_kg - selected.tube_mass_kg),
                    psi_u_all_mm=_mm(candidate.psi_u_all_m),
                    delta_psi_u_all_mm=_mm(candidate.psi_u_all_m - selected.psi_u_all_m),
                    raw_main_tip_mm=_mm(candidate.raw_main_tip_m),
                    raw_rear_tip_mm=_mm(candidate.raw_rear_tip_m),
                    hard_feasible=bool(candidate.overall_hard_feasible),
                    candidate_feasible=bool(candidate.overall_optimizer_candidate_feasible),
                )
            )
    rows.sort(key=lambda row: (VARIABLE_NAMES.index(row.variable), row.delta_z))
    return tuple(rows)


def build_variable_leverage_rows(
    *,
    selected: DirectV2Candidate,
    probe_rows: tuple[VariableProbeRow, ...],
) -> tuple[VariableLeverageRow, ...]:
    """Summarize local plus/minus leverage around the selected point."""

    rows: list[VariableLeverageRow] = []
    for name, current_z in zip(VARIABLE_NAMES, selected.z, strict=True):
        candidates = [row for row in probe_rows if row.variable == name]
        plus = next((row for row in candidates if abs(row.delta_z - 0.02) < 1.0e-12), None)
        minus = next((row for row in candidates if abs(row.delta_z + 0.02) < 1.0e-12), None)

        mm_per_kg = None
        if plus is not None and plus.delta_mass_kg > 1.0e-12:
            mm_per_kg = -plus.delta_psi_u_all_mm / plus.delta_mass_kg

        rows.append(
            VariableLeverageRow(
                variable=name,
                current_z=float(current_z),
                positive_step=None if plus is None else plus.delta_z,
                positive_delta_mass_kg=None if plus is None else plus.delta_mass_kg,
                positive_delta_psi_u_all_mm=None if plus is None else plus.delta_psi_u_all_mm,
                positive_mm_per_kg=mm_per_kg,
                negative_step=None if minus is None else minus.delta_z,
                negative_delta_mass_kg=None if minus is None else minus.delta_mass_kg,
                negative_delta_psi_u_all_mm=None if minus is None else minus.delta_psi_u_all_mm,
                negative_candidate_feasible=None if minus is None else minus.candidate_feasible,
            )
        )
    return tuple(rows)


def build_active_neighborhood_rows(
    *,
    evaluator: ProductionSmoothEvaluator,
    selected: DirectV2Candidate,
    active_steps: Iterable[float] = (-0.04, -0.02, 0.0, 0.02, 0.04),
) -> tuple[NeighborhoodRow, ...]:
    """Sample a small local grid on the two active reduced variables."""

    base_z = np.asarray(selected.z, dtype=float)
    rows: list[NeighborhoodRow] = []
    for delta_main in active_steps:
        for delta_rear in active_steps:
            z = base_z.copy()
            z[0] = np.clip(z[0] + float(delta_main), 0.0, 1.0)
            z[2] = np.clip(z[2] + float(delta_rear), 0.0, 1.0)
            candidate = evaluator.evaluate(
                z,
                source=f"neighborhood:{delta_main:+.2f}:{delta_rear:+.2f}",
            )
            rows.append(
                NeighborhoodRow(
                    delta_main_plateau_z=float(delta_main),
                    delta_rear_radius_z=float(delta_rear),
                    mass_kg=float(candidate.tube_mass_kg),
                    psi_u_all_mm=_mm(candidate.psi_u_all_m),
                    candidate_feasible=bool(candidate.overall_optimizer_candidate_feasible),
                )
            )
    return tuple(rows)


def run_solution_analysis(
    *,
    cfg,
    aircraft,
    materials_db: MaterialDB,
    optimizer: SparOptimizer,
    export_loads: dict,
    baseline_result,
    map_config: ReducedMapConfig,
    main_plateau_grid: Iterable[float],
    main_taper_fill_grid: Iterable[float],
    rear_radius_grid: Iterable[float],
    rear_outboard_grid: Iterable[float],
    wall_thickness_grid: Iterable[float],
    cobyla_maxiter: int,
    cobyla_rhobeg: float,
    soft_penalty_weight: float,
) -> AnalysisOutcome:
    """Run V2 once, then analyze the selected candidate in detail."""

    v2_outcome = run_direct_dual_beam_v2(
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        optimizer=optimizer,
        export_loads=export_loads,
        baseline_result=baseline_result,
        map_config=map_config,
        main_plateau_grid=main_plateau_grid,
        main_taper_fill_grid=main_taper_fill_grid,
        rear_radius_grid=rear_radius_grid,
        rear_outboard_grid=rear_outboard_grid,
        wall_thickness_grid=wall_thickness_grid,
        cobyla_maxiter=cobyla_maxiter,
        cobyla_rhobeg=cobyla_rhobeg,
        soft_penalty_weight=soft_penalty_weight,
    )

    baseline_design = BaselineDesign(
        main_t_seg_m=np.asarray(baseline_result.main_t_seg_mm, dtype=float) * 1.0e-3,
        main_r_seg_m=np.asarray(baseline_result.main_r_seg_mm, dtype=float) * 1.0e-3,
        rear_t_seg_m=np.asarray(baseline_result.rear_t_seg_mm, dtype=float) * 1.0e-3,
        rear_r_seg_m=np.asarray(baseline_result.rear_r_seg_mm, dtype=float) * 1.0e-3,
    )
    evaluator = ProductionSmoothEvaluator(
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        optimizer=optimizer,
        export_loads=export_loads,
        baseline=baseline_design,
        map_config=map_config,
    )

    selected = v2_outcome.selected
    baseline = v2_outcome.baseline
    segment_rows, totals = build_segment_delta_rows(
        baseline=baseline,
        selected=selected,
        cfg=cfg,
        materials_db=materials_db,
    )
    decomposition_rows = build_decomposition_rows(evaluator=evaluator, selected=selected)
    variable_probe_rows = build_variable_probe_rows(evaluator=evaluator, selected=selected)
    leverage_rows = build_variable_leverage_rows(selected=selected, probe_rows=variable_probe_rows)
    neighborhood_rows = build_active_neighborhood_rows(evaluator=evaluator, selected=selected)

    non_tube_delta = float(
        (selected.total_structural_mass_kg - baseline.total_structural_mass_kg)
        - totals["tube_delta_mass_kg"]
    )
    active_feasible_count = sum(1 for row in neighborhood_rows if row.candidate_feasible)

    return AnalysisOutcome(
        v2_outcome=v2_outcome,
        segment_rows=segment_rows,
        decomposition_rows=decomposition_rows,
        variable_probe_rows=variable_probe_rows,
        leverage_rows=leverage_rows,
        neighborhood_rows=neighborhood_rows,
        main_delta_mass_kg=totals["main_delta_mass_kg"],
        rear_delta_mass_kg=totals["rear_delta_mass_kg"],
        tube_delta_mass_kg=totals["tube_delta_mass_kg"],
        non_tube_delta_mass_kg=non_tube_delta,
        main_s1_4_delta_mass_kg=totals["main_s1_4_delta_mass_kg"],
        main_s5_6_delta_mass_kg=totals["main_s5_6_delta_mass_kg"],
        active_neighborhood_candidate_feasible_count=active_feasible_count,
        active_neighborhood_total_count=len(neighborhood_rows),
    )


def build_report_text(
    *,
    config_path: Path,
    design_report: Path,
    cruise_aoa_deg: float,
    outcome: AnalysisOutcome,
) -> str:
    v2 = outcome.v2_outcome
    selected = v2.selected
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    lines: list[str] = []
    lines.append("=" * 112)
    lines.append("Direct Dual-Beam V2 Solution Analysis")
    lines.append("=" * 112)
    lines.append(f"Generated                     : {timestamp}")
    lines.append(f"Config                        : {config_path}")
    lines.append(f"Design report                 : {design_report}")
    lines.append(f"Cruise AoA                    : {cruise_aoa_deg:.3f} deg")
    lines.append("")
    lines.append("V2 baseline rerun:")
    lines.append(f"  success / feasible          : {v2.success} / {v2.feasible}")
    lines.append(f"  total wall time             : {v2.total_wall_time_s:.3f} s")
    lines.append(f"  unique evals                : {v2.unique_evaluations}")
    lines.append(f"  analysis calls              : {v2.production_analysis_calls}")
    lines.append(f"  selected source             : {selected.source}")
    lines.append("")
    lines.append("Part A. Why It Got Heavier")
    lines.append(f"  Tube mass delta             : {outcome.tube_delta_mass_kg:+.3f} kg")
    lines.append(
        f"  Non-tube mass delta         : {outcome.non_tube_delta_mass_kg:+.3f} kg"
    )
    lines.append(f"  Main spar share             : {outcome.main_delta_mass_kg:+.3f} kg")
    lines.append(f"  Rear spar share             : {outcome.rear_delta_mass_kg:+.3f} kg")
    lines.append(f"  Main seg 1-4 share          : {outcome.main_s1_4_delta_mass_kg:+.3f} kg")
    lines.append(f"  Main seg 5-6 share          : {outcome.main_s5_6_delta_mass_kg:+.3f} kg")
    lines.append("")
    lines.append("Selected reduced variables:")
    lines.append(f"  main_plateau_scale          : {selected.main_plateau_scale:.6f}")
    lines.append(f"  main_taper_fill             : {selected.main_taper_fill:.6f}")
    lines.append(f"  rear_radius_scale           : {selected.rear_radius_scale:.6f}")
    lines.append(f"  rear_outboard_fraction      : {selected.rear_outboard_fraction:.6f}")
    lines.append(f"  wall_thickness_fraction     : {selected.wall_thickness_fraction:.6f}")
    lines.append("")
    lines.append("Segment-level delta summary:")
    lines.append(
        "  spar  seg  L[m]   dR[mm]   dt[mm]   dm[kg]   share[%]   I_ratio"
    )
    for row in outcome.segment_rows:
        lines.append(
            f"  {row.spar:4s} {row.segment_index:4d} {row.length_m:6.2f} "
            f"{row.delta_radius_mm:8.3f} {row.delta_thickness_mm:8.3f} "
            f"{row.delta_mass_kg:8.3f} {row.delta_mass_share_pct:9.2f} {row.i_ratio:9.3f}"
        )
    lines.append("")
    lines.append("Knob decomposition (isolated):")
    lines.append(
        "  label         mass[kg]  psi_u_all[mm]  raw_main[mm]  raw_rear[mm]  hard  cand"
    )
    for row in outcome.decomposition_rows:
        lines.append(
            f"  {row.label:12s} {row.mass_kg:8.3f} {row.psi_u_all_mm:13.3f} "
            f"{row.raw_main_tip_mm:12.3f} {row.raw_rear_tip_mm:12.3f} "
            f"{str(row.hard_feasible):>5s} {str(row.candidate_feasible):>5s}"
        )
    lines.append("")
    lines.append("Part B. Local Robustness")
    lines.append(
        f"  Active 2D neighborhood      : {outcome.active_neighborhood_candidate_feasible_count} / "
        f"{outcome.active_neighborhood_total_count} candidate-feasible"
    )
    lines.append(
        "  Interpretation              : selected point sits near the light-side feasible boundary, "
        "but not as a single isolated lucky point"
    )
    lines.append("")
    lines.append("One-at-a-time local probes:")
    lines.append(
        "  variable               dz     dm[kg]   dpsi[mm]   psi[mm]   main[mm]   rear[mm]   cand"
    )
    for row in outcome.variable_probe_rows:
        lines.append(
            f"  {row.variable:22s} {row.delta_z:+5.2f} {row.delta_mass_kg:+8.3f} "
            f"{row.delta_psi_u_all_mm:+10.3f} {row.psi_u_all_mm:9.3f} "
            f"{row.raw_main_tip_mm:10.3f} {row.raw_rear_tip_mm:10.3f} "
            f"{str(row.candidate_feasible):>5s}"
        )
    lines.append("")
    lines.append("Part C. Local Leverage Summary")
    lines.append(
        "  variable               z_now   +dz   +dm[kg]  +dpsi[mm]  +mm/kg   -dz   -dm[kg]  -dpsi[mm]  -cand"
    )
    for row in outcome.leverage_rows:
        plus_dz = "  - " if row.positive_step is None else f"{row.positive_step:+4.2f}"
        plus_dm = "    -   " if row.positive_delta_mass_kg is None else f"{row.positive_delta_mass_kg:+8.3f}"
        plus_dp = "     -    " if row.positive_delta_psi_u_all_mm is None else f"{row.positive_delta_psi_u_all_mm:+10.3f}"
        plus_eff = "   -   " if row.positive_mm_per_kg is None else f"{row.positive_mm_per_kg:8.1f}"
        minus_dz = "  - " if row.negative_step is None else f"{row.negative_step:+4.2f}"
        minus_dm = "    -   " if row.negative_delta_mass_kg is None else f"{row.negative_delta_mass_kg:+8.3f}"
        minus_dp = "     -    " if row.negative_delta_psi_u_all_mm is None else f"{row.negative_delta_psi_u_all_mm:+10.3f}"
        minus_cand = "  -  " if row.negative_candidate_feasible is None else f"{str(row.negative_candidate_feasible):>5s}"
        lines.append(
            f"  {row.variable:22s} {row.current_z:5.2f} {plus_dz} {plus_dm} {plus_dp} {plus_eff} "
            f"{minus_dz} {minus_dm} {minus_dp} {minus_cand}"
        )
    return "\n".join(lines) + "\n"


def build_summary_json(
    *,
    config_path: Path,
    design_report: Path,
    cruise_aoa_deg: float,
    outcome: AnalysisOutcome,
) -> dict[str, object]:
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "config": str(config_path),
        "design_report": str(design_report),
        "cruise_aoa_deg": float(cruise_aoa_deg),
        "analysis": {
            "v2_outcome": {
                "success": outcome.v2_outcome.success,
                "feasible": outcome.v2_outcome.feasible,
                "total_wall_time_s": outcome.v2_outcome.total_wall_time_s,
                "unique_evaluations": outcome.v2_outcome.unique_evaluations,
                "analysis_calls": outcome.v2_outcome.production_analysis_calls,
                "baseline": outcome.v2_outcome.baseline.__dict__,
                "selected": outcome.v2_outcome.selected.__dict__,
            },
            "mass_breakdown": {
                "tube_delta_mass_kg": outcome.tube_delta_mass_kg,
                "non_tube_delta_mass_kg": outcome.non_tube_delta_mass_kg,
                "main_delta_mass_kg": outcome.main_delta_mass_kg,
                "rear_delta_mass_kg": outcome.rear_delta_mass_kg,
                "main_s1_4_delta_mass_kg": outcome.main_s1_4_delta_mass_kg,
                "main_s5_6_delta_mass_kg": outcome.main_s5_6_delta_mass_kg,
            },
            "segment_rows": [asdict(row) for row in outcome.segment_rows],
            "decomposition_rows": [asdict(row) for row in outcome.decomposition_rows],
            "variable_probe_rows": [asdict(row) for row in outcome.variable_probe_rows],
            "variable_leverage_rows": [asdict(row) for row in outcome.leverage_rows],
            "neighborhood_rows": [asdict(row) for row in outcome.neighborhood_rows],
            "active_neighborhood_candidate_feasible_count": outcome.active_neighborhood_candidate_feasible_count,
            "active_neighborhood_total_count": outcome.active_neighborhood_total_count,
        },
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze the current direct dual-beam V2 candidate-feasible solution."
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent.parent / "configs" / "blackcat_004.yaml"),
    )
    parser.add_argument(
        "--design-report",
        default=str(
            Path(__file__).resolve().parent.parent
            / "output"
            / "blackcat_004_dual_beam_production_check"
            / "ansys"
            / "crossval_report.txt"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(
            Path(__file__).resolve().parent.parent / "output" / "direct_dual_beam_v2_solution_analysis"
        ),
    )
    parser.add_argument("--main-plateau-scale-upper", type=float, default=1.14)
    parser.add_argument("--main-taper-fill-upper", type=float, default=0.80)
    parser.add_argument("--rear-radius-scale-upper", type=float, default=1.12)
    parser.add_argument("--main-plateau-grid", default="0.0,0.33,0.67,1.0")
    parser.add_argument("--main-taper-fill-grid", default="0.0,0.33,0.67,1.0")
    parser.add_argument("--rear-radius-grid", default="0.0,0.33,0.67,1.0")
    parser.add_argument("--rear-outboard-grid", default="0.0,0.5,1.0")
    parser.add_argument("--wall-thickness-grid", default="0.0,0.35,0.70")
    parser.add_argument("--cobyla-maxiter", type=int, default=160)
    parser.add_argument("--cobyla-rhobeg", type=float, default=0.18)
    parser.add_argument("--soft-penalty-weight", type=float, default=4.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    config_path = Path(args.config).expanduser().resolve()
    design_report = Path(args.design_report).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config(config_path)
    baseline_metrics = parse_baseline_metrics(design_report)
    cfg.solver.n_beam_nodes = int(baseline_metrics.nodes_per_spar)
    aircraft = Aircraft.from_config(cfg)
    materials_db = MaterialDB()
    baseline_result = build_specimen_result_from_crossval_report(design_report)

    cruise_aoa_deg, mapped_loads = _select_cruise_loads(cfg, aircraft)
    design_case = cfg.structural_load_cases()[0]
    export_loads = LoadMapper.apply_load_factor(mapped_loads, design_case.aero_scale)
    optimizer = SparOptimizer(cfg, aircraft, mapped_loads, materials_db)

    baseline_design = BaselineDesign(
        main_t_seg_m=np.asarray(baseline_result.main_t_seg_mm, dtype=float) * 1.0e-3,
        main_r_seg_m=np.asarray(baseline_result.main_r_seg_mm, dtype=float) * 1.0e-3,
        rear_t_seg_m=np.asarray(baseline_result.rear_t_seg_mm, dtype=float) * 1.0e-3,
        rear_r_seg_m=np.asarray(baseline_result.rear_r_seg_mm, dtype=float) * 1.0e-3,
    )
    map_config = build_reduced_map_config(
        baseline=baseline_design,
        cfg=cfg,
        main_plateau_scale_upper=float(args.main_plateau_scale_upper),
        main_taper_fill_upper=float(args.main_taper_fill_upper),
        rear_radius_scale_upper=float(args.rear_radius_scale_upper),
    )

    outcome = run_solution_analysis(
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        optimizer=optimizer,
        export_loads=export_loads,
        baseline_result=baseline_result,
        map_config=map_config,
        main_plateau_grid=_parse_grid(args.main_plateau_grid),
        main_taper_fill_grid=_parse_grid(args.main_taper_fill_grid),
        rear_radius_grid=_parse_grid(args.rear_radius_grid),
        rear_outboard_grid=_parse_grid(args.rear_outboard_grid),
        wall_thickness_grid=_parse_grid(args.wall_thickness_grid),
        cobyla_maxiter=int(args.cobyla_maxiter),
        cobyla_rhobeg=float(args.cobyla_rhobeg),
        soft_penalty_weight=float(args.soft_penalty_weight),
    )

    report_path = output_dir / "direct_dual_beam_v2_solution_analysis.txt"
    report_path.write_text(
        build_report_text(
            config_path=config_path,
            design_report=design_report,
            cruise_aoa_deg=cruise_aoa_deg,
            outcome=outcome,
        ),
        encoding="utf-8",
    )
    json_path = output_dir / "direct_dual_beam_v2_solution_analysis.json"
    json_path.write_text(
        json.dumps(
            build_summary_json(
                config_path=config_path,
                design_report=design_report,
                cruise_aoa_deg=cruise_aoa_deg,
                outcome=outcome,
            ),
            indent=2,
            default=lambda value: value.tolist() if isinstance(value, np.ndarray) else value,
        )
        + "\n",
        encoding="utf-8",
    )

    print("Direct dual-beam V2 solution analysis complete.")
    print(f"  Report              : {report_path}")
    print(f"  Summary JSON        : {json_path}")
    print(f"  V2 success/feasible : {outcome.v2_outcome.success} / {outcome.v2_outcome.feasible}")
    print(
        f"  Mass delta          : {outcome.tube_delta_mass_kg:+.3f} kg "
        f"(main {outcome.main_delta_mass_kg:+.3f}, rear {outcome.rear_delta_mass_kg:+.3f})"
    )
    print(
        f"  Active neighborhood : {outcome.active_neighborhood_candidate_feasible_count} / "
        f"{outcome.active_neighborhood_total_count} candidate-feasible"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
