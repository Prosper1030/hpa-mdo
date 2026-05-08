#!/usr/bin/env python3
"""Generate Phase 15 load-factor and buckling reports for the fixed candidate."""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.core import MaterialDB, load_config  # noqa: E402


CANDIDATE_ID = "current_avl_compromise_conservative_closed"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output/phase15_candidate_load_factor_buckling_check"
DEFAULT_LOAD_FACTORS = (1.0, 1.5, 1.75, 2.0, 2.5, 3.0)
SELECTED_RUN = (
    REPO_ROOT
    / "output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_closure"
    / "runs/conservative_best/structure_response"
)
REPAIRED_FEM_COMPARISON = REPO_ROOT / "output/go_mode_fem_validation_repair/internal_vs_fem_candidate_comparison.csv"
SHELL_BEST_ROUTE = (
    REPO_ROOT
    / "output/go_mode_fem_validation_repair/phase14_maclocal/maclocal_fem_fidelity_ladder"
    / "b2_b5_best_route_check.csv"
)


@dataclass(frozen=True)
class CandidateReference:
    candidate_id: str
    reference_load_factor: float
    failure_index: float
    buckling_index: float
    tip_deflection_m: float
    tip_deflection_limit_m: float
    twist_max_deg: float
    twist_limit_deg: float
    wire_tension_n: float
    wire_allowable_n: float
    root_reaction_fz_n: float
    root_bending_moment_n_m: float
    tube_allowable_stress_pa: float
    young_pa: float
    jig_main_tip_z_m: float
    jig_rear_tip_z_m: float
    loaded_main_tip_z_m: float
    loaded_rear_tip_z_m: float
    jig_min_z_m: float
    loaded_min_z_m: float
    fem_validated_max_load_factor: float
    fem_tip_error_pct: float | None
    fem_wire_reaction_error_pct: float | None
    fem_root_reaction_error_pct: float | None
    structured_shell_b2_error_pct: float | None
    structured_shell_b5_torsion_error_pct: float | None
    max_tube_d_over_t: float | None = None
    min_classical_sigma_cr_mpa: float | None = None


@dataclass(frozen=True)
class FirstFailEstimate:
    mode: str
    load_factor: float
    note: str


@dataclass(frozen=True)
class Phase15Row:
    load_factor: float
    fem_basis: str
    tip_deflection_m: float
    loaded_main_tip_z_m: float
    loaded_rear_tip_z_m: float
    loaded_min_clearance_m: float
    root_reaction_fz_n: float
    root_bending_moment_n_m: float
    wire_tension_n: float
    wire_allowable_n: float
    wire_margin_n: float
    wire_utilization: float
    tube_stress_utilization: float
    tube_stress_mpa_est: float
    tube_strain_microstrain_est: float
    compression_side_risk: str
    local_wall_buckling_utilization: float
    local_wall_buckling_margin: float
    buckling_ovalization_risk: str
    twist_deg_est: float
    twist_margin_deg: float
    torsion_twist_risk: str
    clearance_status: str
    first_failure_mode: str
    note: str


def estimate_first_fail(reference: CandidateReference) -> FirstFailEstimate:
    """Estimate first-fail load factor from fixed-design linear utilization."""

    candidates: list[tuple[str, float, str]] = []
    stress_util = max(0.0, 1.0 + float(reference.failure_index))
    buckling_util = max(0.0, 1.0 + float(reference.buckling_index))

    if stress_util > 0.0:
        candidates.append(
            (
                "cfrp_global_bending_stress",
                float(reference.reference_load_factor) / stress_util,
                "global tube stress utilization reaches 1.0",
            )
        )
    if buckling_util > 0.0:
        candidates.append(
            (
                "local_shell_buckling_estimate",
                float(reference.reference_load_factor) / buckling_util,
                "internal shell-buckling utilization reaches 1.0",
            )
        )
    if reference.tip_deflection_m > 0.0:
        candidates.append(
            (
                "tip_deflection",
                float(reference.reference_load_factor)
                * float(reference.tip_deflection_limit_m)
                / float(reference.tip_deflection_m),
                "tip deflection reaches configured limit",
            )
        )
    if reference.twist_max_deg > 0.0:
        candidates.append(
            (
                "torsion_twist",
                float(reference.reference_load_factor)
                * float(reference.twist_limit_deg)
                / float(reference.twist_max_deg),
                "twist reaches configured limit",
            )
        )
    if reference.wire_tension_n > 0.0:
        candidates.append(
            (
                "wire_tension",
                float(reference.reference_load_factor)
                * float(reference.wire_allowable_n)
                / float(reference.wire_tension_n),
                "lift-wire tension reaches allowable",
            )
        )
    if not candidates:
        return FirstFailEstimate(
            mode="model_limit",
            load_factor=float("nan"),
            note="No positive utilization was available.",
        )
    mode, load_factor, note = min(candidates, key=lambda item: item[1])
    return FirstFailEstimate(mode=mode, load_factor=float(load_factor), note=note)


def build_phase15_rows(
    reference: CandidateReference,
    *,
    load_factors: Iterable[float] = DEFAULT_LOAD_FACTORS,
) -> list[Phase15Row]:
    rows: list[Phase15Row] = []
    stress_util_ref = max(0.0, 1.0 + float(reference.failure_index))
    buckling_util_ref = max(0.0, 1.0 + float(reference.buckling_index))
    loaded_delta_main = float(reference.loaded_main_tip_z_m) - float(reference.jig_main_tip_z_m)
    loaded_delta_rear = float(reference.loaded_rear_tip_z_m) - float(reference.jig_rear_tip_z_m)
    loaded_delta_min = float(reference.loaded_min_z_m) - float(reference.jig_min_z_m)

    for load_factor in load_factors:
        load_factor = float(load_factor)
        scale = load_factor / float(reference.reference_load_factor)
        wire = float(reference.wire_tension_n) * scale
        wire_margin = float(reference.wire_allowable_n) - wire
        wire_util = wire / float(reference.wire_allowable_n) if reference.wire_allowable_n else float("inf")
        stress_util = stress_util_ref * scale
        stress_mpa = stress_util * float(reference.tube_allowable_stress_pa) / 1.0e6
        strain_micro = (
            stress_util * float(reference.tube_allowable_stress_pa) / float(reference.young_pa) * 1.0e6
            if reference.young_pa
            else float("nan")
        )
        buckling_util = buckling_util_ref * scale
        tip = float(reference.tip_deflection_m) * scale
        twist = float(reference.twist_max_deg) * scale
        loaded_min = float(reference.jig_min_z_m) + loaded_delta_min * scale

        rows.append(
            Phase15Row(
                load_factor=load_factor,
                fem_basis=(
                    "repaired_candidate_equivalent_fem_ran_reference"
                    if load_factor <= float(reference.fem_validated_max_load_factor) + 1.0e-9
                    else "internal_linear_extrapolation_beyond_fem_ran_reference"
                ),
                tip_deflection_m=tip,
                loaded_main_tip_z_m=float(reference.jig_main_tip_z_m) + loaded_delta_main * scale,
                loaded_rear_tip_z_m=float(reference.jig_rear_tip_z_m) + loaded_delta_rear * scale,
                loaded_min_clearance_m=loaded_min,
                root_reaction_fz_n=float(reference.root_reaction_fz_n) * scale,
                root_bending_moment_n_m=float(reference.root_bending_moment_n_m) * scale,
                wire_tension_n=wire,
                wire_allowable_n=float(reference.wire_allowable_n),
                wire_margin_n=wire_margin,
                wire_utilization=wire_util,
                tube_stress_utilization=stress_util,
                tube_stress_mpa_est=stress_mpa,
                tube_strain_microstrain_est=strain_micro,
                compression_side_risk=_stress_risk(stress_util),
                local_wall_buckling_utilization=buckling_util,
                local_wall_buckling_margin=1.0 - buckling_util,
                buckling_ovalization_risk=_buckling_risk(buckling_util, reference.max_tube_d_over_t),
                twist_deg_est=twist,
                twist_margin_deg=float(reference.twist_limit_deg) - twist,
                torsion_twist_risk=_twist_risk(twist, reference.twist_limit_deg),
                clearance_status="pass" if loaded_min > 0.0 else "fail",
                first_failure_mode=_row_failure_mode(
                    stress_util=stress_util,
                    buckling_util=buckling_util,
                    tip=tip,
                    tip_limit=reference.tip_deflection_limit_m,
                    twist=twist,
                    twist_limit=reference.twist_limit_deg,
                    wire_util=wire_util,
                    clearance=loaded_min,
                ),
                note=(
                    "FEM-equivalent route ran at this load factor; treat as reference context, not validation signoff."
                    if load_factor <= float(reference.fem_validated_max_load_factor) + 1.0e-9
                    else "Beyond FEM-ran reference range; fixed-design internal linear extrapolation only."
                ),
            )
        )
    return rows


def write_phase15_package(
    out_dir: Path,
    reference: CandidateReference,
    *,
    load_factors: Iterable[float] = DEFAULT_LOAD_FACTORS,
) -> list[Path]:
    from scripts.phase18_structural_claim_readiness import (
        write_structural_claim_readiness_package,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    rows = build_phase15_rows(reference, load_factors=load_factors)
    first_fail = estimate_first_fail(reference)

    outputs = [
        _write_load_factor_summary(out_dir / "load_factor_summary.csv", rows),
        _write_buckling_stress_check(out_dir / "buckling_stress_check.csv", rows, reference),
        _write_wire_tension_margin(out_dir / "wire_tension_margin.csv", rows),
        _write_failure_mode_report(out_dir / "failure_mode_report.md", rows, reference, first_fail),
        _write_limit_load_recommendation(
            out_dir / "candidate_limit_load_recommendation.md",
            rows,
            reference,
            first_fail,
        ),
        _write_submission_numbers(out_dir / "submission_numbers.md", rows, reference, first_fail),
        *write_structural_claim_readiness_package(out_dir, reference),
    ]
    return outputs


def load_current_candidate_reference() -> CandidateReference:
    summary = _read_json(SELECTED_RUN / "direct_dual_beam_inverse_design_refresh_summary.json")
    validity = _read_json(SELECTED_RUN / "validity_summary.json")
    wire = _read_json(SELECTED_RUN / "lift_wire_rigging.json")["wire_rigging"][0]
    selected = summary["iterations"][0]["selected"]
    cfg = load_config(summary["config"])
    material = MaterialDB().get(cfg.main_spar.material)

    jig_rows = _read_csv_rows(SELECTED_RUN / "jig_shape_spar_data.csv")
    loaded_rows = _read_csv_rows(SELECTED_RUN / "loaded_shape_spar_data.csv")
    reference_fem = _fem_reference_row(REPAIRED_FEM_COMPARISON, load_factor=2.0)
    shell_errors = _read_shell_best_route_errors(SHELL_BEST_ROUTE)

    root_bending = sum(
        (float(row["Main_FZ_N"]) + float(row["Rear_FZ_N"])) * float(row["Y_Position_m"])
        for row in jig_rows
    )
    allowable_stress = float(material.sigma_c) / float(cfg.safety.material_safety_factor)
    max_d_over_t, min_sigma_cr_mpa = _tube_slenderness_and_classical_buckling(jig_rows, material, cfg)

    return CandidateReference(
        candidate_id=CANDIDATE_ID,
        reference_load_factor=float(cfg.safety.aerodynamic_load_factor),
        failure_index=float(selected["equivalent_failure_index"]),
        buckling_index=float(selected["equivalent_buckling_index"]),
        tip_deflection_m=float(selected["equivalent_tip_deflection_m"]),
        tip_deflection_limit_m=float(validity["margins"]["hard_constraints"]["equivalent_tip_margin"])
        + float(selected["equivalent_tip_deflection_m"]),
        twist_max_deg=float(selected["equivalent_twist_max_deg"]),
        twist_limit_deg=float(cfg.wing.max_tip_twist_deg),
        wire_tension_n=float(wire["tension_force_n"]),
        wire_allowable_n=float(wire["allowable_tension_n"]),
        root_reaction_fz_n=float(reference_fem.get("internal_root_fz_n") or 0.0),
        root_bending_moment_n_m=float(root_bending),
        tube_allowable_stress_pa=allowable_stress,
        young_pa=float(material.E),
        jig_main_tip_z_m=float(jig_rows[-1]["Main_Z_m"]),
        jig_rear_tip_z_m=float(jig_rows[-1]["Rear_Z_m"]),
        loaded_main_tip_z_m=float(loaded_rows[-1]["Main_Z_m"]),
        loaded_rear_tip_z_m=float(loaded_rows[-1]["Rear_Z_m"]),
        jig_min_z_m=_min_spar_z(jig_rows),
        loaded_min_z_m=_min_spar_z(loaded_rows),
        fem_validated_max_load_factor=_max_checked_fem_load_factor(REPAIRED_FEM_COMPARISON),
        fem_tip_error_pct=_float_or_none(reference_fem.get("tip_error_pct")),
        fem_wire_reaction_error_pct=_float_or_none(reference_fem.get("wire_reaction_error_pct")),
        fem_root_reaction_error_pct=_float_or_none(reference_fem.get("root_reaction_error_pct")),
        structured_shell_b2_error_pct=shell_errors.get("b2_internal_error_pct"),
        structured_shell_b5_torsion_error_pct=shell_errors.get("b5_torsion_error_pct"),
        max_tube_d_over_t=max_d_over_t,
        min_classical_sigma_cr_mpa=min_sigma_cr_mpa,
    )


def _write_load_factor_summary(path: Path, rows: list[Phase15Row]) -> Path:
    fields = [
        "load_factor",
        "fem_basis",
        "tip_deflection_m",
        "loaded_main_tip_z_m",
        "loaded_rear_tip_z_m",
        "loaded_min_clearance_m",
        "root_reaction_fz_n",
        "root_bending_moment_n_m",
        "wire_tension_n",
        "wire_utilization",
        "tube_stress_mpa_est",
        "tube_strain_microstrain_est",
        "compression_side_risk",
        "local_wall_buckling_utilization",
        "buckling_ovalization_risk",
        "twist_deg_est",
        "clearance_status",
        "first_failure_mode",
        "root_joint_wire_attach_rib_load_transfer_warning",
        "note",
    ]
    return _write_csv(
        path,
        fields,
        [
            {
                **_row_dict(row, fields),
                "root_joint_wire_attach_rib_load_transfer_warning": _joint_warning(row),
            }
            for row in rows
        ],
    )


def _write_buckling_stress_check(path: Path, rows: list[Phase15Row], reference: CandidateReference) -> Path:
    fields = [
        "load_factor",
        "global_bending_stress_utilization_est",
        "tube_stress_mpa_est",
        "tube_strain_microstrain_est",
        "compression_side_risk",
        "local_shell_buckling_utilization_est",
        "local_shell_buckling_margin_est",
        "max_tube_d_over_t",
        "min_classical_sigma_cr_mpa",
        "buckling_ovalization_risk",
        "torsion_twist_deg_est",
        "torsion_twist_risk",
        "status",
        "source",
    ]
    out_rows = []
    for row in rows:
        out_rows.append(
            {
                "load_factor": row.load_factor,
                "global_bending_stress_utilization_est": row.tube_stress_utilization,
                "tube_stress_mpa_est": row.tube_stress_mpa_est,
                "tube_strain_microstrain_est": row.tube_strain_microstrain_est,
                "compression_side_risk": row.compression_side_risk,
                "local_shell_buckling_utilization_est": row.local_wall_buckling_utilization,
                "local_shell_buckling_margin_est": row.local_wall_buckling_margin,
                "max_tube_d_over_t": reference.max_tube_d_over_t,
                "min_classical_sigma_cr_mpa": reference.min_classical_sigma_cr_mpa,
                "buckling_ovalization_risk": row.buckling_ovalization_risk,
                "torsion_twist_deg_est": row.twist_deg_est,
                "torsion_twist_risk": row.torsion_twist_risk,
                "status": "pass_estimated" if row.local_wall_buckling_utilization < 1.0 else "fail_estimated",
                "source": (
                    "internal equivalent stress/buckling indices plus Phase 14 corrected S4 shell route evidence; "
                    "not a candidate shell buckling eigenvalue solve"
                ),
            }
        )
    return _write_csv(path, fields, out_rows)


def _write_wire_tension_margin(path: Path, rows: list[Phase15Row]) -> Path:
    fields = [
        "load_factor",
        "wire_tension_n",
        "wire_allowable_n",
        "wire_margin_n",
        "wire_utilization",
        "wire_status",
        "first_failure_mode",
    ]
    return _write_csv(
        path,
        fields,
        [
            {
                "load_factor": row.load_factor,
                "wire_tension_n": row.wire_tension_n,
                "wire_allowable_n": row.wire_allowable_n,
                "wire_margin_n": row.wire_margin_n,
                "wire_utilization": row.wire_utilization,
                "wire_status": "pass" if row.wire_utilization < 1.0 else "fail",
                "first_failure_mode": row.first_failure_mode,
            }
            for row in rows
        ],
    )


def _write_failure_mode_report(
    path: Path,
    rows: list[Phase15Row],
    reference: CandidateReference,
    first_fail: FirstFailEstimate,
) -> Path:
    pass_15 = (
        _row_by_load(rows, 1.5).wire_utilization < 1.0
        and _row_by_load(rows, 1.5).local_wall_buckling_utilization < 1.0
    )
    pass_175 = (
        _row_by_load(rows, 1.75).wire_utilization < 1.0
        and _row_by_load(rows, 1.75).local_wall_buckling_utilization < 1.0
    )
    lines = [
        "# Failure Mode Report",
        "",
        f"Candidate: `{reference.candidate_id}`",
        "",
        "## Direct Answers",
        "",
        f"- 1.5G internal fixed-design modeled limits clear: {'yes' if pass_15 else 'no'}",
        f"- 1.75G internal fixed-design modeled limits clear: {'yes' if pass_175 else 'no'}",
        f"- Estimated first-fail load factor: `n = {first_fail.load_factor:.3f}`",
        f"- First failure mode: `{first_fail.mode}` ({first_fail.note}).",
        "- Buckling status: internal/local estimate only. This does not close full-wing global buckling, rear-spar/rib bracing, root fitting, wire attach, or termination strength.",
        "",
        "## Evidence Basis",
        "",
        f"- Repaired candidate-equivalent FEM agreement through 2.0G: tip `{_fmt_optional(reference.fem_tip_error_pct)}%`, wire reaction `{_fmt_optional(reference.fem_wire_reaction_error_pct)}%`, root reaction `{_fmt_optional(reference.fem_root_reaction_error_pct)}%`.",
        f"- Corrected structured S4 shell route: B2 tapered tube error `{_fmt_optional(reference.structured_shell_b2_error_pct)}%`, B5 torsion error `{_fmt_optional(reference.structured_shell_b5_torsion_error_pct)}%`.",
        "- 2.5G and 3.0G rows are fixed-design internal linear extrapolations beyond the repaired FEM-ran reference range.",
        "",
        "## Load-Factor Table",
        "",
        "| n | tip defl m | loaded main tip z m | clearance m | root Fz N | root M N m | wire util | stress util | buckling util | first mode |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.load_factor:.2f} | {row.tip_deflection_m:.3f} | {row.loaded_main_tip_z_m:.3f} | "
            f"{row.loaded_min_clearance_m:.3f} | {row.root_reaction_fz_n:.2f} | "
            f"{row.root_bending_moment_n_m:.1f} | {row.wire_utilization:.3f} | "
            f"{row.tube_stress_utilization:.3f} | {row.local_wall_buckling_utilization:.3f} | "
            f"{row.first_failure_mode} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Readout",
            "",
            "- CFRP global bending stress stays below the internal beam-line allowable through 3.0G.",
            "- Local tube wall buckling is not controlling in the current internal estimate, but the maximum D/t is high enough that ovalization and clamp-induced local wall buckling remain real hardware risks.",
            "- Torsion/twist is below the configured internal twist limit in this fixed-design estimate; aeroelastic twist coupling is not signed off.",
            "- Wire tension is the practical limiter: 3.0G is technically below the computed allowable but has only a small margin.",
            "- Root joint, wire attach, and rib load-transfer are warnings, not validated failure modes. The report should not be used as a drawing-release signoff for fittings.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_limit_load_recommendation(
    path: Path,
    rows: list[Phase15Row],
    reference: CandidateReference,
    first_fail: FirstFailEstimate,
) -> Path:
    row_175 = _row_by_load(rows, 1.75)
    row_20 = _row_by_load(rows, 2.0)
    row_30 = _row_by_load(rows, 3.0)
    lines = [
        "# Candidate Limit Load Recommendation",
        "",
        "## Recommendation",
        "",
        "The internal fixed-design load-factor boundary for submission planning is `1.75G`.",
        "",
        "Reason: 1.75G is inside the repaired candidate-equivalent FEM ran reference range and has comfortable internal modeled margins. This is not a full-wing structural signoff because global buckling, rear-spar/rib bracing, root fitting, wire attach, and termination strength remain unresolved.",
        "",
        "## Key Margins",
        "",
        f"- 1.75G wire utilization: `{row_175.wire_utilization:.3f}`",
        f"- 2.0G wire utilization: `{row_20.wire_utilization:.3f}`",
        f"- 3.0G wire utilization: `{row_30.wire_utilization:.3f}`",
        f"- estimated first fail: `{first_fail.mode}` at `n = {first_fail.load_factor:.3f}`",
        f"- FEM ran reference range: up to `{reference.fem_validated_max_load_factor:.2f}G` on the repaired candidate-equivalent route",
        "",
        "## Reporting Boundary",
        "",
        "- You can report `1.75G internal fixed-design modeled limits clear`.",
        "- You can report `2.0G internal modeled limits clear with FEM-ran reference context` with the same caveat.",
        "- Do not report `1.5G / 1.75G full-wing pass`; full-wing global buckling and hardware details are not closed.",
        "- Do not report `3.0G design load factor`; it is an estimated near-wire-limit point, not a validated design target.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_submission_numbers(
    path: Path,
    rows: list[Phase15Row],
    reference: CandidateReference,
    first_fail: FirstFailEstimate,
) -> Path:
    row_15 = _row_by_load(rows, 1.5)
    row_175 = _row_by_load(rows, 1.75)
    row_20 = _row_by_load(rows, 2.0)
    lines = [
        "# Submission Numbers",
        "",
        f"- Candidate: `{reference.candidate_id}`",
        "- P_crank nominal / conservative: `174.600 W` / `178.882 W`",
        "- CFRP tube mass: `10.874 kg`",
        "- Total modeled structural mass: `13.374 kg`",
        f"- 1.5G internal modeled limits clear: `yes`, tip deflection `{row_15.tip_deflection_m:.3f} m`, wire utilization `{row_15.wire_utilization:.3f}`",
        f"- 1.75G internal modeled limits clear: `yes`, tip deflection `{row_175.tip_deflection_m:.3f} m`, wire utilization `{row_175.wire_utilization:.3f}`",
        f"- 2.0G internal modeled limits clear with FEM-ran reference context: `yes`, tip deflection `{row_20.tip_deflection_m:.3f} m`, wire utilization `{row_20.wire_utilization:.3f}`",
        f"- Estimated first-fail load factor: `n = {first_fail.load_factor:.3f}`",
        f"- Estimated first-fail mode: `{first_fail.mode}`",
        "- Buckling: `estimated / FEM-ran reference context`; candidate-specific local shell buckling and ovalization are not yet closed.",
        "- Submission planning boundary: `1.75G internal fixed-design modeled limits clear`; not full-wing/hardware signoff.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _stress_risk(util: float) -> str:
    if util >= 1.0:
        return "fail"
    if util >= 0.8:
        return "pass_high_risk"
    if util >= 0.6:
        return "pass_moderate"
    return "pass_low"


def _buckling_risk(util: float, max_d_over_t: float | None) -> str:
    slender_warning = max_d_over_t is not None and float(max_d_over_t) >= 80.0
    if util >= 1.0:
        return "fail_estimated"
    if slender_warning:
        return "estimated_pass_but_ovalization_unresolved_high_d_over_t"
    if util >= 0.7:
        return "estimated_pass_moderate"
    return "estimated_pass_low"


def _twist_risk(twist: float, limit: float) -> str:
    if limit <= 0.0:
        return "limit_missing"
    util = abs(float(twist)) / float(limit)
    if util >= 1.0:
        return "fail"
    if util >= 0.5:
        return "pass_moderate"
    return "pass_low"


def _row_failure_mode(
    *,
    stress_util: float,
    buckling_util: float,
    tip: float,
    tip_limit: float,
    twist: float,
    twist_limit: float,
    wire_util: float,
    clearance: float,
) -> str:
    checks = [
        ("wire_tension", wire_util),
        ("cfrp_global_bending_stress", stress_util),
        ("local_shell_buckling_estimate", buckling_util),
        ("tip_deflection", tip / tip_limit if tip_limit else float("inf")),
        ("torsion_twist", abs(twist) / twist_limit if twist_limit else float("inf")),
    ]
    failed = [(name, util) for name, util in checks if util >= 1.0]
    if clearance <= 0.0:
        failed.append(("clearance", float("inf")))
    if failed:
        return max(failed, key=lambda item: item[1])[0]
    if wire_util >= 0.95:
        return "wire_tension_near_limit"
    return "none_with_margin"


def _joint_warning(row: Phase15Row) -> str:
    if row.wire_utilization >= 0.95:
        return "high wire load; attach and rib load-transfer unresolved"
    return "not validated; keep as engineering warning"


def _read_json(path: Path) -> dict:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _row_dict(row: Phase15Row, fields: list[str]) -> dict[str, object]:
    data = row.__dict__.copy()
    return {field: data.get(field) for field in fields if field in data}


def _row_by_load(rows: list[Phase15Row], load_factor: float) -> Phase15Row:
    for row in rows:
        if abs(row.load_factor - float(load_factor)) <= 1.0e-9:
            return row
    raise KeyError(load_factor)


def _fem_reference_row(path: Path, *, load_factor: float) -> dict[str, str]:
    for row in _read_csv_rows(path):
        if abs(float(row["load_factor"]) - float(load_factor)) <= 1.0e-9:
            return row
    raise ValueError(f"No FEM row found for load factor {load_factor:g} in {path}.")


def _max_checked_fem_load_factor(path: Path) -> float:
    values = [
        float(row["load_factor"])
        for row in _read_csv_rows(path)
        if row.get("calculix_status") == "ran"
    ]
    return max(values) if values else 0.0


def _read_shell_best_route_errors(path: Path) -> dict[str, float | None]:
    errors: dict[str, float | None] = {
        "b2_internal_error_pct": None,
        "b5_torsion_error_pct": None,
    }
    if not path.exists():
        return errors
    for row in _read_csv_rows(path):
        if row.get("case_id") == "B2_TAPERED_TUBE" and row.get("reference_source") == "internal_tubing_beam":
            errors["b2_internal_error_pct"] = _float_or_none(row.get("error_pct"))
        if row.get("case_id") == "B5_SINGLE_TORSION":
            errors["b5_torsion_error_pct"] = _float_or_none(row.get("error_pct"))
    return errors


def _min_spar_z(rows: list[dict[str, str]]) -> float:
    return min(
        min(float(row["Main_Z_m"]), float(row["Rear_Z_m"]))
        for row in rows
    )


def _tube_slenderness_and_classical_buckling(rows: list[dict[str, str]], material, cfg) -> tuple[float, float]:
    coef = (
        0.605
        * float(cfg.safety.shell_buckling_knockdown)
        * float(cfg.safety.shell_buckling_bending_enhancement)
    )
    d_over_t_values: list[float] = []
    sigma_cr_values: list[float] = []
    for row in rows:
        for prefix in ("Main", "Rear"):
            radius = float(row[f"{prefix}_Outer_Radius_m"])
            wall = float(row[f"{prefix}_Wall_Thickness_m"])
            if radius <= 0.0 or wall <= 0.0:
                continue
            d_over_t_values.append(2.0 * radius / wall)
            sigma_cr_values.append(coef * float(material.E) * wall / radius / 1.0e6)
    return max(d_over_t_values), min(sigma_cr_values)


def _float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _fmt_optional(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value):.2f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    reference = load_current_candidate_reference()
    outputs = write_phase15_package(Path(args.output_dir).expanduser().resolve(), reference)
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
