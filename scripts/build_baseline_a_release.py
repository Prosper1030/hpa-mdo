#!/usr/bin/env python3
"""Build the Baseline A team release package.

This builder freezes the current pathfinder screening state into a team-facing
release bundle. It intentionally does not run SU2, NSGA, propeller optimization,
random disturbance simulation, or CAD automation. Those lanes are queued as
work orders because Baseline A is a team release package, not final aircraft
sign-off.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_P1_SUMMARY_JSON = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "2026-05-12_current_pathfinder_p1_load_path_mass_closure.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "baseline_A_team_release"

SCHEMA_VERSION = "baseline_a_team_release_v1"
LEDGER_SCHEMA_VERSION = "baseline_a_mass_cg_margin_ledger_v1"
RELEASE_VERDICT = "baseline_A_data_authority_repair_in_progress"
LEDGER_VERDICT = "mass_cg_authority_repair_needed"
DESIGN_GROSS_MASS_AUTHORITY_KG = 98.5
CONFIDENCE_LEVELS = {"estimate", "quoted", "measured", "frozen"}


def build_baseline_a_release(
    p1_summary_json: Path = DEFAULT_P1_SUMMARY_JSON,
) -> dict[str, Any]:
    p1 = _read_json(p1_summary_json)
    local = _mapping_at(p1, "local_load_path")
    mass = _mapping_at(p1, "mass_integration")
    closure = _mapping_at(p1, "mass_cg_tail_closure")
    cg = _mapping_at(closure, "cg_management")
    trim = _mapping_at(closure, "trim_static_directional")
    aero = _mapping_at(closure, "aeroelastic_effects")
    drag_power = _mapping_at(closure, "mass_drag_power")
    propulsion = _mapping_at(p1, "propulsion_lane_policy")

    geometry_freeze = _geometry_freeze(
        p1=p1,
        local=local,
        mass=mass,
        cg=cg,
        closure=closure,
        aero=aero,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "release_id": "baseline_A_team_release",
        "release_verdict": RELEASE_VERDICT,
        "source_artifact": str(p1_summary_json),
        "p1": p1,
        "local": local,
        "mass": mass,
        "closure": closure,
        "cg": cg,
        "trim": trim,
        "aero": aero,
        "drag_power": drag_power,
        "propulsion": propulsion,
        "geometry_freeze": geometry_freeze,
    }


def write_baseline_a_release_package(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    p1_summary_json: Path = DEFAULT_P1_SUMMARY_JSON,
) -> dict[str, Path]:
    context = build_baseline_a_release(p1_summary_json=p1_summary_json)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "release_md": output_dir / "baseline_A_team_release.md",
        "geometry_freeze": output_dir / "geometry_freeze.json",
        "mass_budget": output_dir / "mass_budget.csv",
        "cg_summary": output_dir / "cg_summary.json",
        "margin_budget": output_dir / "margin_budget.md",
        "daily_review_summary": output_dir / "mass_cg_margin_daily_review.md",
        "drag_power_budget": output_dir / "drag_power_budget.csv",
        "tail_trim_stability": output_dir / "tail_trim_stability_summary.json",
        "structure_pack": output_dir / "structure_interface_pack.md",
        "control_pack": output_dir / "control_interface_pack.md",
        "propulsion_pack": output_dir / "propulsion_interface_pack.md",
        "manufacturing_plan": output_dir / "manufacturing_test_plan.md",
        "carbon_tube_rfq": output_dir / "carbon_tube_rfq_spec.md",
        "change_control": output_dir / "change_control_rules.md",
        "team_work_packages": output_dir / "team_work_packages.md",
    }

    _write_text(paths["release_md"], _render_release_markdown(context))
    _write_json(paths["geometry_freeze"], context["geometry_freeze"])
    _write_mass_budget(paths["mass_budget"], context)
    _write_json(paths["cg_summary"], _cg_summary(context))
    _write_text(paths["margin_budget"], _render_margin_budget(context))
    _write_text(paths["daily_review_summary"], _render_daily_review_summary(context))
    _write_drag_power_budget(paths["drag_power_budget"], context)
    _write_json(paths["tail_trim_stability"], _tail_trim_summary(context))
    _write_text(paths["structure_pack"], _render_structure_pack(context))
    _write_text(paths["control_pack"], _render_control_pack(context))
    _write_text(paths["propulsion_pack"], _render_propulsion_pack(context))
    _write_text(paths["manufacturing_plan"], _render_manufacturing_plan(context))
    _write_text(paths["carbon_tube_rfq"], _render_carbon_tube_rfq(context))
    _write_text(paths["change_control"], _render_change_control_rules(context))
    _write_text(paths["team_work_packages"], _render_team_work_packages(context))
    return paths


def _geometry_freeze(
    *,
    p1: Mapping[str, Any],
    local: Mapping[str, Any],
    mass: Mapping[str, Any],
    cg: Mapping[str, Any],
    closure: Mapping[str, Any],
    aero: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "release_id": "baseline_A_team_release",
        "release_verdict": RELEASE_VERDICT,
        "candidate_id": p1["candidate_id"],
        "current_pathfinder_role": "Baseline A team release pathfinder, not final aircraft",
        "data_authority_status": "under_repair",
        "p1_verdict": p1["final_verdict"],
        "authority": {
            "design_gross_mass_authority_kg": DESIGN_GROSS_MASS_AUTHORITY_KG,
            "suspect_p1_screening_aggregate_kg": mass[
                "updated_total_mass_after_items_kg"
            ],
            "current_pipeline_full_span_evidence_m": 34.332286,
            "current_pipeline_half_span_evidence_m": 17.166143,
            "local_splice_screening_half_span_m": 16.5,
            "wo006_status": "paused_until_data_authority_restored",
            "wo005_status": "draft_vendor_screening_only",
        },
        "frozen": {
            "phase_j_pipeline": (
                "Mission contract -> Fourier-AVL -> smooth geometry -> loaded-Z -> "
                "AVL recheck -> Tier2 airfoil -> aero-structure closure -> FEM/APDL"
            ),
            "candidate_id": p1["candidate_id"],
            "rib_spacing_m": 0.30,
            "rib_station_basis": "0.30 m physical stations/bays materialized",
            "selected_rib_torsion_basis": p1["candidate_id"],
            "fast_rib_torsion_model": "link_limited_torsion_cell_v2",
            "managed_final_cg_m": cg["final_screening_cg_x_m"],
        },
        "controlled": {
            "c04_fix": local["installed_fix_type"],
            "c04_architecture_status": "architecture_selected_needs_coupon_local_fem",
            "c04_fix_mass_kg": mass["additional_masses_kg"]["p1_c04_fix_full_wing"],
            "spar_splice_mass_kg": mass["additional_masses_kg"]["spar_splice_full_wing"],
            "tail_trim_stability_basis": closure["trim_static_directional"]["status"],
            "direct_spar_pair_stress_test": "conservative_mapping_warning_not_signoff",
        },
        "open_validation": {
            "p1_local_load_path": "coupon/local FEM required before build sign-off",
            "c04_coupon": "saddle/yoke/clamp coupon plus lug-foot shear and clamp retention",
            "one_meter_wing_bay_v2": "rib/collar/skin-sag bay test on physical spacing",
            "carbon_tube_rfq": "vendor tube capability, tolerances, laminate, and splice fit",
            "qualified_aero_surface_mapping": "direct spar-pair stress-test is not final",
        },
        "reopen_triggers": _reopen_triggers(),
        "screening_numbers": {
            "baseline_c04_peel_margin": local["baseline_c04_margin"],
            "installed_fix_governing_margin": local["installed_fix_governing_margin"],
            "suspect_p1_screening_aggregate_mass_kg": mass[
                "updated_total_mass_after_items_kg"
            ],
            "required_forward_rebalance_m": cg["required_forward_rebalance_m"],
            "bounded_physical_twist_deg": aero[
                "conservative_bounded_physical_projection_max_abs_deg"
            ],
            "direct_spar_pair_rotation_deg": aero["direct_spar_pair_rotation_max_abs_deg"],
        },
        "claim_boundary": (
            "Baseline A is a team release package and screening pathfinder. It is "
            "not final aircraft sign-off, not adhesive sign-off, not laminate "
            "sign-off, and not manufacturing sign-off."
        ),
    }


def _render_release_markdown(context: Mapping[str, Any]) -> str:
    p1 = _mapping_at(context, "p1")
    local = _mapping_at(context, "local")
    mass = _mapping_at(context, "mass")
    cg = _mapping_at(context, "cg")
    aero = _mapping_at(context, "aero")
    return "\n".join(
        [
            "# Baseline A team release",
            "",
            f"Verdict: `{context['release_verdict']}`",
            "",
            "Baseline A is under data-authority repair. This package is retained as "
            "screening evidence and task coordination material; it is not current "
            "release authority and not final aircraft sign-off.",
            "",
            "## Data Authority Repair Gate",
            "",
            f"- Current design gross mass authority: `{DESIGN_GROSS_MASS_AUTHORITY_KG} kg`.",
            f"- Suspect P1 screening aggregate: `{mass['updated_total_mass_after_items_kg']} kg` "
            "(not current design mass truth).",
            "- Current pipeline span evidence: `34.332286 m` full span / `17.166143 m` half-span.",
            "- Local/splice screening half-span: `16.5 m`, not procurement truth.",
            "- WO-005 RFQ pack remains draft/vendor-screening only.",
            "- WO-006 SU2 is paused until data authority is restored.",
            "",
            "## Current Pathfinder",
            "",
            f"- Candidate: `{p1['candidate_id']}`",
            f"- P1 verdict: `{p1['final_verdict']}`",
            f"- C04 original peel margin: `{local['baseline_c04_margin']}`",
            f"- Installed C04 fix: `{local['installed_fix_type']}`",
            f"- Governing installed-fix margin: `{local['installed_fix_governing_margin']}`",
            f"- Suspect P1 screening aggregate: `{mass['updated_total_mass_after_items_kg']} kg`",
            f"- Managed CG: `{cg['final_screening_cg_x_m']} m`",
            f"- Required forward rebalance: `{cg['required_forward_rebalance_m']} m`",
            f"- Bounded physical twist: `{aero['conservative_bounded_physical_projection_max_abs_deg']} deg`",
            "- Ledger artifacts: `mass_budget.csv`, `cg_summary.json`, "
            "`margin_budget.md`, `mass_cg_margin_daily_review.md`",
            "",
            "## authority-controlled / do not casually change",
            "",
            "- Phase J pathfinder narrative and candidate identity.",
            "- Selected rib/torsion basis: 10 mm EPS-balsa hybrid, uniform 0.30 m, "
            "carbon face collar at y=2.328 m, rear75.",
            "- Managed CG row at 0.75 m for screening closure.",
            "- C04 baseline fail evidence remains part of the release record.",
            "",
            "## controlled / can change with review",
            "",
            "- C04 saddle-ring/yoke plus secondary clamp details.",
            "- 3 m spar splice sizing and carbon tube RFQ tolerances.",
            "- Mass/CG ledger and any rebalance action.",
            "- Tail trim/stability assumptions and control authority margins.",
            "",
            "## open validation / assigned to team",
            "",
            "- Coupon tests for saddle/yoke/clamp and adhesive/lug-foot shear.",
            "- C04 local FEM with shell/solid adhesive and clamp contact.",
            "- 1 m wing-bay v2 build with skin sag and rib/collar load path evidence.",
            "- Carbon tube RFQ and vendor tolerance check.",
            "- Qualified aero-surface mapping for the direct spar-pair stress-test warning.",
            "",
            "## reopen trigger / would force major redesign",
            "",
            *[f"- {item}" for item in _reopen_triggers()],
            "",
            "## Team Start Authorization",
            "",
            "Teams may use this package only for bounded screening, coupon/local FEM "
            "planning, interface review, and draft vendor questions. It does not "
            "authorize RFQ purchase action, shop drawing release, SU2 release claims, "
            "or aircraft sign-off work.",
            "",
        ]
    )


def _mass_ledger_rows(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    cg = _mapping_at(context, "cg")
    local = _mapping_at(context, "local")
    drag_power = _mapping_at(context, "drag_power")
    source = str(context["source_artifact"])
    mass_items = {str(item["name"]): item for item in cg["mass_items"]}
    rows = [
        _mass_ledger_row(
            item="base_aircraft_pilot_screening_mass",
            component_name="Base aircraft, pilot, cockpit, and legacy screening aggregate",
            mass_kg=cg["base_mass_kg"],
            x_m=cg["base_cg_x_m"],
            owner="chief_engineering",
            source_artifact=source,
            source_assumption=(
                "P1 cg_management base_mass_kg and base_cg_x_m aggregate the pre-ledger "
                "screening aircraft/pilot basis."
            ),
            confidence="estimate",
            affects_cg=True,
            affects_drag=False,
            affects_power=True,
            affects_structure=True,
            status="screening_aggregate_not_measured_weight",
            notes="Kept as a single aggregate until measured component manifests exist.",
            trust_boundary="Screening mass basis, not measured weight and balance.",
        ),
        _mass_ledger_row(
            item="selected_tail_screening_delta",
            component_name="All-moving tail screening mass delta",
            mass_kg=mass_items["selected_tail_screening_delta"]["mass_kg"],
            x_m=mass_items["selected_tail_screening_delta"]["x_m"],
            owner="controls",
            source_artifact=source,
            source_assumption="Tail/CG/trim/stability screening delta charged to Baseline A.",
            confidence="estimate",
            affects_cg=True,
            affects_drag=True,
            affects_power=True,
            affects_structure=True,
            status="charged_to_screening_read",
            notes=(
                f"Carries tail CD0 increment {_fmt(drag_power['tail_cd0_increment'])} and "
                f"profile power increment {_fmt(drag_power['tail_profile_power_increment_w'])} W."
            ),
            trust_boundary="Tail screening placeholder, not tailboom or hardware sign-off.",
        ),
        _mass_ledger_row(
            item="fast_design_loop_selected_rib_pack",
            component_name="Selected hybrid rib/torsion pack",
            mass_kg=mass_items["fast_design_loop_selected_rib_pack"]["mass_kg"],
            x_m=mass_items["fast_design_loop_selected_rib_pack"]["x_m"],
            owner="structures",
            source_artifact=source,
            source_assumption=(
                "Fast design-loop selected rib pack on 0.30 m materialized rib/station basis."
            ),
            confidence="estimate",
            affects_cg=True,
            affects_drag=False,
            affects_power=True,
            affects_structure=True,
            status="charged_to_screening_read",
            notes="EPS/balsa hybrid rib pack remains a screening structural basis.",
            trust_boundary="Needs local FEM/coupon and manufacturing evidence before build sign-off.",
        ),
        _mass_ledger_row(
            item="p1_c04_saddle_ring_yoke_clamp_pair",
            component_name="P1 C04 saddle-ring/yoke plus secondary clamp fix",
            mass_kg=mass_items["p1_c04_saddle_ring_yoke_clamp_pair"]["mass_kg"],
            x_m=mass_items["p1_c04_saddle_ring_yoke_clamp_pair"]["x_m"],
            owner="structures",
            source_artifact=source,
            source_assumption="recommended_c04_fix() analytical screening mass.",
            confidence="estimate",
            affects_cg=True,
            affects_drag=False,
            affects_power=True,
            affects_structure=True,
            status="architecture_selected_needs_coupon_local_fem",
            notes=(
                f"Original C04 peel path remains fail evidence at margin "
                f"{_fmt(local['baseline_c04_margin'])}."
            ),
            trust_boundary="Architecture-selected fix, not coupon/local FEM sign-off.",
        ),
        _mass_ledger_row(
            item="spar_splice_transport_joint_pack",
            component_name="3 m transport spar splice pack",
            mass_kg=mass_items["spar_splice_transport_joint_pack"]["mass_kg"],
            x_m=mass_items["spar_splice_transport_joint_pack"]["x_m"],
            owner="manufacturing",
            source_artifact=source,
            source_assumption="3 m spar splice screening design mass for full wing.",
            confidence="estimate",
            affects_cg=True,
            affects_drag=False,
            affects_power=True,
            affects_structure=True,
            status="screening_design_needs_rfq_detail",
            notes="Supplier quote and fit/tolerance checks are still open.",
            trust_boundary="Screening splice design, not released production drawing.",
        ),
    ]
    _validate_confidence_levels(rows)
    return rows


def _mass_ledger_row(
    *,
    item: str,
    component_name: str,
    mass_kg: Any,
    x_m: Any,
    owner: str,
    source_artifact: str,
    source_assumption: str,
    confidence: str,
    affects_cg: bool,
    affects_drag: bool,
    affects_power: bool,
    affects_structure: bool,
    status: str,
    notes: str,
    trust_boundary: str,
    y_m: Any = "",
    z_m: Any = "",
) -> dict[str, Any]:
    return {
        "item": item,
        "component_name": component_name,
        "mass_kg": _fmt(mass_kg),
        "x_m": _fmt(x_m),
        "y_m": _fmt(y_m),
        "z_m": _fmt(z_m),
        "owner": owner,
        "source_artifact": source_artifact,
        "source_assumption": source_assumption,
        "confidence": confidence,
        "affects_cg": _yes_no(affects_cg),
        "affects_drag": _yes_no(affects_drag),
        "affects_power": _yes_no(affects_power),
        "affects_structure": _yes_no(affects_structure),
        "status": status,
        "notes": notes,
        "trust_boundary": trust_boundary,
    }


def _validate_confidence_levels(rows: list[Mapping[str, Any]]) -> None:
    unknown = sorted({str(row["confidence"]) for row in rows} - CONFIDENCE_LEVELS)
    if unknown:
        raise ValueError(f"Unknown confidence levels: {', '.join(unknown)}")


def _ledger_gross_mass_kg(rows: list[Mapping[str, Any]]) -> float:
    return sum(float(row["mass_kg"]) for row in rows if row["mass_kg"] != "")


def _ledger_cg_x_m(rows: list[Mapping[str, Any]]) -> float:
    cg_rows = [
        row
        for row in rows
        if row["affects_cg"] == "yes" and row["mass_kg"] != "" and row["x_m"] != ""
    ]
    mass = _ledger_gross_mass_kg(cg_rows)
    return sum(float(row["mass_kg"]) * float(row["x_m"]) for row in cg_rows) / mass


def _confidence_summary(rows: list[Mapping[str, Any]]) -> dict[str, int]:
    summary = {level: 0 for level in sorted(CONFIDENCE_LEVELS)}
    for row in rows:
        summary[str(row["confidence"])] += 1
    return summary


def _write_mass_budget(path: Path, context: Mapping[str, Any]) -> None:
    rows = _mass_ledger_rows(context)
    fieldnames = [
        "item",
        "component_name",
        "mass_kg",
        "x_m",
        "y_m",
        "z_m",
        "owner",
        "source_artifact",
        "source_assumption",
        "confidence",
        "affects_cg",
        "affects_drag",
        "affects_power",
        "affects_structure",
        "status",
        "notes",
        "trust_boundary",
    ]
    _write_csv(path, rows, fieldnames)


def _cg_summary(context: Mapping[str, Any]) -> dict[str, Any]:
    cg = _mapping_at(context, "cg")
    trim = _mapping_at(context, "trim")
    propulsion = _mapping_at(context, "propulsion")
    rows = _mass_ledger_rows(context)
    suspect_screening_aggregate_kg = _ledger_gross_mass_kg(rows)
    uncompensated_cg_m = _ledger_cg_x_m(rows)
    source_mass = float(cg["total_mass_after_items_kg"])
    source_uncompensated_cg = float(cg["uncompensated_cg_x_m"])
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "verdict": LEDGER_VERDICT,
        "status": cg["status"],
        "cg_range_m": cg["cg_range_x_m"],
        "design_gross_mass_authority_kg": DESIGN_GROSS_MASS_AUTHORITY_KG,
        "suspect_p1_screening_aggregate_kg": _round6(suspect_screening_aggregate_kg),
        "source_suspect_screening_aggregate_kg": cg["total_mass_after_items_kg"],
        "screening_aggregate_minus_design_authority_kg": _round6(
            suspect_screening_aggregate_kg - DESIGN_GROSS_MASS_AUTHORITY_KG
        ),
        "mass_balance_delta_kg": _round6(suspect_screening_aggregate_kg - source_mass),
        "computed_uncompensated_cg_m": _round6(uncompensated_cg_m),
        "source_uncompensated_cg_m": cg["uncompensated_cg_x_m"],
        "uncompensated_cg_delta_m": _round6(uncompensated_cg_m - source_uncompensated_cg),
        "managed_final_cg_m": cg["final_screening_cg_x_m"],
        "uncompensated_cg_m": cg["uncompensated_cg_x_m"],
        "uncompensated_cg_status": cg["uncompensated_cg_status"],
        "required_forward_rebalance_m": cg["required_forward_rebalance_m"],
        "forward_rebalance_limit_m": cg["forward_rebalance_limit_m"],
        "rebalance_mass_kg": cg["forward_rebalance_mass_kg"],
        "static_margin": trim["static_margin"],
        "tail_trim_status": trim["status"],
        "confidence_summary": _confidence_summary(rows),
        "qprop_xrotor_policy": {
            "role": propulsion["qprop_xrotor_role"],
            "used_in_structural_blocker_verdict": propulsion[
                "used_in_structural_blocker_verdict"
            ],
        },
        "missing_data_preventing_higher_confidence": [
            "measured component weights and measured aircraft CG",
            "full y/z component locations for inertia and lateral/vertical balance",
            "supplier-quoted spar splice, tube, clamp, and saddle/yoke masses",
            "coupon/local FEM evidence for C04 saddle/yoke/clamp and C07 skin sag",
            "independent QPROP/XROTOR propulsion margin feed-in",
        ],
        "claim_boundary": (
            "Design gross mass authority remains 98.5 kg. The 106.828608 kg-like "
            "P1 aggregate is suspect screening evidence, not current design mass truth. "
            "Managed CG is a screening closure row, not measured aircraft CG and not "
            "approval to accept the uncompensated mass state."
        ),
    }


def _render_margin_budget(context: Mapping[str, Any]) -> str:
    local = _mapping_at(context, "local")
    trim = _mapping_at(context, "trim")
    aero = _mapping_at(context, "aero")
    drag_power = _mapping_at(context, "drag_power")
    cg_summary = _cg_summary(context)
    rows = _mass_ledger_rows(context)
    component_lines = [
        "| Component | kg | x m | confidence | CG | drag | power | structure |",
        "|---|---:|---:|---|---|---|---|---|",
    ]
    for row in rows:
        component_lines.append(
            "| "
            f"{row['item']} | {row['mass_kg']} | {row['x_m']} | {row['confidence']} | "
            f"{row['affects_cg']} | {row['affects_drag']} | {row['affects_power']} | "
            f"{row['affects_structure']} |"
        )

    missing_lines = [
        f"- {item}" for item in cg_summary["missing_data_preventing_higher_confidence"]
    ]
    return "\n".join(
        [
            "# Baseline A Mass / CG / Margin Budget",
            "",
            f"Verdict: `{LEDGER_VERDICT}`",
            "",
            "This ledger is a screening evidence surface under data-authority repair. "
            "It is not measured aircraft weight and balance, not current design mass "
            "truth, and not final aircraft sign-off.",
            "",
            "## Mass and CG",
            "",
            "| Quantity | Value | Status |",
            "|---|---:|---|",
            f"| Design gross mass authority | {_fmt(cg_summary['design_gross_mass_authority_kg'])} kg | user authority |",
            f"| Suspect P1 screening aggregate | {_fmt(cg_summary['suspect_p1_screening_aggregate_kg'])} kg | screening aggregate, not design truth |",
            f"| Aggregate minus design authority | {_fmt(cg_summary['screening_aggregate_minus_design_authority_kg'])} kg | conflict to reconcile |",
            (
                f"| Computed uncompensated CG | {_fmt(cg_summary['computed_uncompensated_cg_m'])} m "
                f"| {cg_summary['uncompensated_cg_status']} |"
            ),
            (
                f"| Managed screening CG | {_fmt(cg_summary['managed_final_cg_m'])} m | "
                f"{cg_summary['status']} |"
            ),
            (
                "| Required forward rebalance | "
                f"{_fmt(cg_summary['required_forward_rebalance_m'])} m on "
                f"{_fmt(cg_summary['rebalance_mass_kg'])} kg equivalent mass | screening |"
            ),
            "",
            "## Component Ledger",
            "",
            *component_lines,
            "",
            "## Margin Summary",
            "",
            "| Gate | Current value | Read |",
            "|---|---:|---|",
            (
                f"| C04 original eccentric peel | {_fmt(local['baseline_c04_margin'])} | "
                "fail evidence retained |"
            ),
            (
                f"| Installed saddle/yoke/clamp governing margin | "
                f"{_fmt(local['installed_fix_governing_margin'])} | "
                "screening pass, coupon/local FEM required |"
            ),
            (
                f"| Saddle-ring yoke adhesive shear margin | {_fmt(local['saddle_ring_yoke_margin'])} | "
                "not governing in fast model |"
            ),
            (
                f"| Static margin at managed CG | {_fmt(trim['static_margin'])} | "
                f"tail trim/stability `{trim['status']}` |"
            ),
            (
                f"| Bounded physical twist | "
                f"{_fmt(aero['conservative_bounded_physical_projection_max_abs_deg'])} deg | "
                f"below {_fmt(aero['elastic_twist_screening_bound_deg'])} deg screening bound |"
            ),
            (
                f"| Direct spar-pair stress-test | "
                f"{_fmt(aero['direct_spar_pair_rotation_max_abs_deg'])} deg | "
                "conservative mapping warning, not aero-surface sign-off |"
            ),
            (
                f"| Root bending ratio | "
                f"{_fmt(aero['root_bending_moment_ratio_loaded_vs_baseline'])} | "
                "inside screening relaxation bounds |"
            ),
            (
                f"| Structural hardware mass delta | "
                f"{_fmt(drag_power['structural_hardware_mass_delta_kg'])} kg | "
                "C04 fix plus splice pack charged |"
            ),
            "",
            "## Drag and Power Summary",
            "",
            "| Quantity | Value | Read |",
            "|---|---:|---|",
            (
                f"| Tail CD0 increment | {_fmt(drag_power['tail_cd0_increment'])} | "
                "screening drag placeholder |"
            ),
            (
                f"| Tail profile power increment | "
                f"{_fmt(drag_power['tail_profile_power_increment_w'])} W | "
                "screening power charge |"
            ),
            (
                "| QPROP/XROTOR propulsion margin | not mixed | "
                "independent propulsion lane, not structural blocker truth |"
            ),
            "",
            "## Missing Data Preventing Higher Confidence",
            "",
            *missing_lines,
            "",
            "## Trust Boundary",
            "",
            "All current component masses are `estimate` confidence. Do not promote them to "
            "`quoted`, `measured`, or `frozen` until supplier, scale, or configuration-control "
            "evidence exists. The managed CG row is allowed for screening closure; the "
            "uncompensated CG row is rejected.",
            "",
        ]
    )


def _render_daily_review_summary(context: Mapping[str, Any]) -> str:
    local = _mapping_at(context, "local")
    trim = _mapping_at(context, "trim")
    aero = _mapping_at(context, "aero")
    drag_power = _mapping_at(context, "drag_power")
    cg_summary = _cg_summary(context)
    return "\n".join(
        [
            "# Baseline A Mass / CG / Margin Daily Review",
            "",
            f"Ledger verdict: `{LEDGER_VERDICT}`",
            "",
            "| Review item | Current read | 30-minute decision |",
            "|---|---|---|",
            (
                f"| Design mass authority | {_fmt(cg_summary['design_gross_mass_authority_kg'])} kg | "
                "Use as current design gross mass unless user changes it |"
            ),
            (
                f"| Suspect P1 screening aggregate | {_fmt(cg_summary['suspect_p1_screening_aggregate_kg'])} kg | "
                "Do not use as current design mass truth |"
            ),
            (
                f"| Managed CG | {_fmt(cg_summary['managed_final_cg_m'])} m | "
                "Accepted screening row |"
            ),
            (
                f"| Uncompensated CG | {_fmt(cg_summary['uncompensated_cg_m'])} m | "
                "Rejected; keep rebalance requirement visible |"
            ),
            (
                f"| Rebalance | {_fmt(cg_summary['required_forward_rebalance_m'])} m forward "
                f"on {_fmt(cg_summary['rebalance_mass_kg'])} kg | Inside screening limit |"
            ),
            (
                f"| C04 original peel | margin {_fmt(local['baseline_c04_margin'])} | "
                "Fail evidence must stay visible |"
            ),
            (
                f"| C04 installed fix | governing margin "
                f"{_fmt(local['installed_fix_governing_margin'])} | "
                "Proceed to coupon/local FEM, not build sign-off |"
            ),
            (
                f"| Static margin | {_fmt(trim['static_margin'])} | "
                f"Tail trim/stability `{trim['status']}` at managed CG |"
            ),
            (
                f"| Bounded twist | "
                f"{_fmt(aero['conservative_bounded_physical_projection_max_abs_deg'])} deg | "
                "Screening pass; direct stress-test remains warning |"
            ),
            (
                f"| Tail power charge | {_fmt(drag_power['tail_profile_power_increment_w'])} W | "
                "Power budget placeholder, not QPROP/XROTOR result |"
            ),
            (
                "| QPROP/XROTOR | independent lane | "
                "Do not use it to pass/fail C04 or rib blockers |"
            ),
            "",
            "Next review focus: data-authority repair for mass, span, station, and "
            "RFQ channel wording. WO-005 remains draft-only and WO-006 remains paused.",
            "",
        ]
    )


def _write_drag_power_budget(path: Path, context: Mapping[str, Any]) -> None:
    drag = _mapping_at(context, "drag_power")
    rows = [
        {
            "item": "velocity",
            "value": _fmt(drag["velocity_mps"]),
            "unit": "m/s",
            "status": "screening_basis",
            "basis": "current tail-aware closure",
        },
        {
            "item": "tail_cd0_increment",
            "value": _fmt(drag["tail_cd0_increment"]),
            "unit": "CD0",
            "status": "screening_basis",
            "basis": "tail drag placeholder",
        },
        {
            "item": "tail_profile_power_increment",
            "value": _fmt(drag["tail_profile_power_increment_w"]),
            "unit": "W",
            "status": "screening_basis",
            "basis": "tail profile power increment",
        },
        {
            "item": "suspect_p1_screening_aggregate",
            "value": _fmt(drag["total_screening_mass_after_integrated_items_kg"]),
            "unit": "kg",
            "status": "suspect_screening_aggregate_not_design_truth",
            "basis": "mass integrated P1 closure; design mass authority is 98.5 kg",
        },
        {
            "item": "qprop_xrotor_lane",
            "value": "independent",
            "unit": "policy",
            "status": "not_structural_blocker_gate",
            "basis": "propulsion lane is queued separately",
        },
    ]
    _write_csv(path, rows, ["item", "value", "unit", "status", "basis"])


def _tail_trim_summary(context: Mapping[str, Any]) -> dict[str, Any]:
    trim = dict(_mapping_at(context, "trim"))
    trim["schema_version"] = SCHEMA_VERSION
    trim["claim_boundary"] = (
        "Tail trim/stability remains inside screening bounds at managed CG. "
        "This is not tailboom, hinge, servo, motor authority, or flight-dynamics sign-off."
    )
    trim["open_validation"] = [
        "control derivative matrix",
        "tail motor authority",
        "tailboom and vertical strut first-order model",
        "all-moving tail pivot and hardware detail",
    ]
    return trim


def _render_structure_pack(context: Mapping[str, Any]) -> str:
    local = _mapping_at(context, "local")
    mass = _mapping_at(context, "mass")
    return "\n".join(
        [
            "# Structure Interface Pack",
            "",
            "P1 is ready for coupon/local FEM, not final build.",
            "",
            "## Current Structural Read",
            "",
            f"- C04 original peel path fails: margin `{local['baseline_c04_margin']}`.",
            f"- Selected fix: `{local['installed_fix_type']}`.",
            f"- Installed surrogate pass, governing clamp margin `{local['installed_fix_governing_margin']}`.",
            f"- C04 fix mass: `{mass['additional_masses_kg']['p1_c04_fix_full_wing']} kg`.",
            f"- Spar splice mass: `{mass['additional_masses_kg']['spar_splice_full_wing']} kg`.",
            "",
            "## Assigned Work",
            "",
            "- Build saddle/yoke/clamp coupon matrix and coupon FEM correlation.",
            "- Run C04 local FEM with adhesive, lug bearing, clamp preload, and tube wall contact.",
            "- Build 1 m wing-bay v2 to check rib/collar load path and skin sag.",
            "- Keep direct spar-pair stress-test as a conservative mapping warning until "
            "aero-surface mapping is qualified.",
            "",
            "## Engineering Caveat",
            "",
            "The C04 fix removes the eccentric peel load path in the screening model. "
            "It does not prove adhesive durability, tube-wall ovalization, local buckling, "
            "or shop repeatability.",
            "",
        ]
    )


def _render_control_pack(context: Mapping[str, Any]) -> str:
    trim = _mapping_at(context, "trim")
    cg = _mapping_at(context, "cg")
    return "\n".join(
        [
            "# Control Interface Pack",
            "",
            "Baseline A keeps all-moving H-tail/V-tail in the current screening closure.",
            "",
            "## Current Screening Basis",
            "",
            f"- Managed CG: `{cg['final_screening_cg_x_m']} m`.",
            f"- Tail trim/stability status: `{trim['status']}`.",
            f"- H-tail required deflection: `{trim['delta_H_required_deg']} deg`.",
            f"- Static margin: `{trim['static_margin']}`.",
            f"- C_n_beta: `{trim['C_n_beta']}`.",
            "",
            "## Open Work",
            "",
            "- Build a control derivative matrix from the current full-aircraft basis.",
            "- Check tail motor/servo authority and rate margin.",
            "- Add tailboom and vertical strut first-order load/stiffness model.",
            "- Preserve the rule that uncompensated CG is rejected.",
            "",
        ]
    )


def _render_propulsion_pack(context: Mapping[str, Any]) -> str:
    propulsion = _mapping_at(context, "propulsion")
    return "\n".join(
        [
            "# Propulsion Interface Pack",
            "",
            "QPROP/XROTOR is an independent propulsion lane.",
            "",
            "It may size propeller and drivetrain interfaces for Baseline A, but it is "
            "not used to pass the P1 structural blocker and not used to change the "
            "current structural release verdict.",
            "",
            "## Boundary",
            "",
            f"- Current role: `{propulsion['qprop_xrotor_role']}`.",
            f"- Used in structural blocker verdict: `{propulsion['used_in_structural_blocker_verdict']}`.",
            "",
            "## Next Work",
            "",
            "- Define propeller interface load cases for the control/structure teams.",
            "- Keep prop optimization out of this release-builder task.",
            "- Feed only reviewed thrust, torque, mass, and CG deltas back into change control.",
            "",
        ]
    )


def _render_manufacturing_plan(context: Mapping[str, Any]) -> str:
    mass = _mapping_at(context, "mass")
    return "\n".join(
        [
            "# Manufacturing Test Plan",
            "",
            "Baseline A is under data-authority repair. The shop-facing team may plan "
            "test articles and draft vendor questions, but this is not a purchase or "
            "drawing-release authorization.",
            "",
            "## Start Now",
            "",
            "- C04 saddle/yoke/clamp coupon.",
            "- C04 local FEM and coupon correlation package.",
            "- 1 m wing-bay v2 with rib/collar/skin-sag evidence.",
            "- Draft carbon tube vendor screening using `carbon_tube_rfq_pack.md` and "
            "`controlled_station_span_splice_manifest.csv`.",
            "",
            "## Do Not Claim Yet",
            "",
            "- Final adhesive sign-off.",
            "- Final aircraft sign-off.",
            "- Full-wing buckling closure.",
            "- Production drawing release.",
            "",
            "## Mass To Carry",
            "",
            f"- C04 fix: `{mass['additional_masses_kg']['p1_c04_fix_full_wing']} kg`.",
            f"- 3 m spar-splice pack: `{mass['additional_masses_kg']['spar_splice_full_wing']} kg`.",
            "",
        ]
    )


def _render_carbon_tube_rfq(context: Mapping[str, Any]) -> str:
    _ = context
    return "\n".join(
        [
            "# Carbon Tube RFQ Spec",
            "",
            "Verdict: `carbon_tube_rfq_pack_draft_vendor_screening`",
            "",
            "This is a draft vendor-screening spec under data-authority repair. It is "
            "not purchase-ready, not final supplier selection, not production drawing "
            "control, and not final aircraft sign-off.",
            "",
            "## Pack Files",
            "",
            "- `carbon_tube_rfq_pack.md`: readable RFQ package and engineering boundary.",
            "- `controlled_station_span_splice_manifest.csv`: one RFQ station/span convention.",
            "- `vendor_questionnaire.md`: supplier response questions.",
            "- `procurement_risk_register.json`: review and reopen triggers.",
            "- `tube_splice_tolerance_requirements.csv`: tube/splice/tolerance request table.",
            "- `rfq_daily_review.md`: one-page review summary.",
            "",
            "## Draft Vendor-Screening Convention",
            "",
            "- Use positive half-wing `y` from aircraft centerline/root for draft vendor-screening language; mirror to both sides.",
            "- Local/splice screening reference: `16.500 m` half-span, not current pipeline half-span and not procurement truth.",
            "- Draft splice station reference: y = `3 / 6 / 9 / 12 / 15 m` on each half-wing.",
            "- Materialized rib basis for screening language: `0.30 m` physical rib station trace.",
            "- Current pipeline span evidence remains `34.332286 m` full span / `17.166143 m` half-span unless replaced by newer authority.",
            "",
            "## Requested Tube Families",
            "",
            "- Main spar reference: 100 mm OD / 98 mm ID HM CFRP tube family.",
            "- Rear spar reference: 80 mm OD / 78 mm ID HM CFRP tube family.",
            "- Splice spigot family: internal CFRP spigot, 4D overlap each side.",
            "- Inboard y=3 m splice warning: 1.02 mm screening spigot wall with zero bending margin.",
            "",
            "## WO-004 Warning Resolved For RFQ Language",
            "",
            "- Keep draft vendor questions tied to the 0.30 m physical rib station trace. The relaxed 0.345 m stiffness label is not vendor drawing control.",
            "- Do not mix 3 m transport splice stations with materialized spar-joint rib stations.",
            "- Do not treat continuous smooth geometry dimensions as shop-grid dimensions.",
            "- Do not treat airfoil/control/transition/transport station contracts as final drawing control.",
            "",
            "## Change-Control Boundary",
            "",
            "Tube family changes that move spar OD/wall, weight, CG, splice concept, or "
            "coupon allowables must return through Baseline A change control.",
            "",
        ]
    )


def _render_change_control_rules(context: Mapping[str, Any]) -> str:
    _ = context
    return "\n".join(
        [
            "# Change Control Rules",
            "",
            "Only decisions that affect large external shape, main/rear spar specification, "
            "weight/CG, procurement, or Baseline A reopen require user decision.",
            "",
            "## authority-controlled / do not casually change",
            "",
            "- Candidate identity and Phase J pathfinder narrative.",
            "- Selected rib/torsion basis and 0.30 m physical rib spacing.",
            "- Managed CG row and rejection of uncompensated CG.",
            "",
            "## controlled / can change with review",
            "",
            "- Saddle/yoke/clamp local detail.",
            "- Carbon tube draft vendor-screening details and splice implementation.",
            "- Tail/control interface assumptions.",
            "- Mass ledger updates.",
            "",
            "## open validation / assigned to team",
            "",
            "- Coupon/local FEM evidence.",
            "- 1 m wing-bay v2 evidence.",
            "- Control derivative matrix and tail motor authority.",
            "- QPROP/XROTOR propulsion interface.",
            "",
            "## reopen trigger / would force major redesign",
            "",
            *[f"- {item}" for item in _reopen_triggers()],
            "",
        ]
    )


def _render_team_work_packages(context: Mapping[str, Any]) -> str:
    _ = context
    completed = [
        (
            "WO-003",
            "design-space freeze audit",
            "Completed as Stage-0 screening; authority repair now supersedes freeze/release claims.",
        ),
        (
            "WO-004",
            "manufacturable discretization/smoothness audit",
            "Completed with verdict `geometry_freeze_needs_fix`; no large external-shape reopen, "
            "but station/span/splice authority must be reconciled before RFQ/shop use.",
        ),
        (
            "WO-005",
            "carbon tube RFQ + procurement pack",
            "Downgraded to draft/vendor-screening only; mass/span authority repair is required "
            "before procurement or drawing-control use.",
        ),
    ]
    queue = [
        (
            "WO-006",
            "main-wing SU2 baseline validation",
            "WO-006 remains paused until data authority is restored; do not run SU2 for release claims yet.",
        ),
        (
            "WO-007",
            "QPROP/XROTOR propulsion interface",
            "Translate independent propulsion results into reviewed thrust/torque/mass interfaces.",
        ),
        (
            "WO-008",
            "turn/stall competition gate",
            "Define competition maneuver and stall evidence gates before expanding search.",
        ),
        (
            "WO-009",
            "control derivative matrix and tail motor authority",
            "Build controls-facing derivative and actuator authority matrix.",
        ),
        (
            "WO-011",
            "tailboom/vertical strut first-order model",
            "Add first-order structural load path model for tailboom and vertical strut.",
        ),
        (
            "WO-012",
            "airfoil database CST/NSGA background lane",
            "Run as background database improvement, not as Baseline A blocker.",
        ),
        (
            "WO-013",
            "report/CAD/export automation",
            "Automate reports and export bundles after release package semantics are stable.",
        ),
    ]
    lines = [
        "# Team Work Packages",
        "",
        "Do not implement SU2/NSGA/propeller optimization in this release-builder task.",
        "",
        "## Completed Work Orders",
        "",
    ]
    for work_id, title, read in completed:
        lines.extend(
            [
                f"### {work_id}: {title}",
                "",
                f"- Completion read: {read}",
                "",
            ]
        )

    lines.extend(
        [
            "## Priority Queue",
            "",
        ]
    )
    for work_id, title, objective in queue:
        lines.extend(
            [
                f"### {work_id}: {title}",
                "",
                f"- Objective: {objective}",
                "- Required output: verdict, changed files, verification, engineering caveats, "
                "and reviewer prompt.",
                "- Decision gate: ask user only if large external shape, main/rear spar spec, "
                "weight/CG, procurement, or Baseline A reopen is affected.",
                "",
            ]
        )

    lines.extend(
        [
            "## Next Recommended Codex Goal",
            "",
            "```text",
            "/goal In /Volumes/Samsung SSD/hpa-mdo, keep WO-006 paused and execute the next data-authority repair item.",
            "Read README.md, CURRENT_MAINLINE.md, docs/reports/baseline_A_data_authority_audit.md, "
            "docs/reports/baseline_A_data_authority_conflict_register.md, and "
            "output/baseline_A_team_release/data_authority_table.csv first. Do not run SU2, "
            "QPROP, XROTOR, prop optimization, or procurement actions. Repair the next "
            "blocking mass/span/station authority issue, update tests and generated wording, "
            "run the data-authority checker, and commit only that work order.",
            "```",
            "",
            "## Reviewer Prompt",
            "",
            "Review the finished work order as代理總工程師. Check whether it preserves "
            "Baseline A as a team release, not final aircraft sign-off; whether it avoids "
            "mixing QPROP/XROTOR into structural blocker truth; and whether any finding "
            "requires user decision.",
            "",
        ]
    )
    return "\n".join(lines)


def _reopen_triggers() -> list[str]:
    return [
        "C04 saddle/yoke/clamp coupon or local FEM shows negative governing margin.",
        "Updated mass/CG cannot hold managed CG 0.75 m within rebalance limit.",
        "Tube vendor-screening evidence cannot meet main/rear spar OD, wall, tolerance, or splice-fit assumptions after authority repair.",
        "Qualified aero-surface mapping invalidates the current direct stress-test warning read after authority repair.",
        "Tail trim/stability or control authority fails at managed CG.",
        "Main-wing SU2 remains paused until data authority is restored; later SU2 baseline changes drag/power enough to invalidate mission margins.",
        "Manufacturing discretization forces large external-shape or spar-spec change.",
    ]


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError(f"Expected object JSON at {path}")
    return data


def _mapping_at(data: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    value: Any = data
    for key in keys:
        value = value[key]
    if not isinstance(value, Mapping):
        raise TypeError(f"Expected mapping at {'.'.join(keys)}")
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _fmt(value: Any) -> str:
    if value == "":
        return ""
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _round6(value: float) -> float:
    return round(value, 6)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for the Baseline A team release package.",
    )
    parser.add_argument(
        "--p1-summary-json",
        type=Path,
        default=DEFAULT_P1_SUMMARY_JSON,
        help="P1 load-path mass closure JSON source.",
    )
    args = parser.parse_args(argv)
    paths = write_baseline_a_release_package(
        output_dir=args.output_dir,
        p1_summary_json=args.p1_summary_json,
    )
    print(f"{RELEASE_VERDICT}: wrote {len(paths)} files to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
