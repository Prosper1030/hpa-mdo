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
RELEASE_VERDICT = "baseline_A_release_system_ready"


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
        "p1_verdict": p1["final_verdict"],
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
            "updated_screening_mass_kg": mass["updated_total_mass_after_items_kg"],
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
            "Baseline A is a team release package for current pathfinder execution. "
            "It is not final aircraft sign-off.",
            "",
            "## Current Pathfinder",
            "",
            f"- Candidate: `{p1['candidate_id']}`",
            f"- P1 verdict: `{p1['final_verdict']}`",
            f"- C04 original peel margin: `{local['baseline_c04_margin']}`",
            f"- Installed C04 fix: `{local['installed_fix_type']}`",
            f"- Governing installed-fix margin: `{local['installed_fix_governing_margin']}`",
            f"- Updated screening mass: `{mass['updated_total_mass_after_items_kg']} kg`",
            f"- Managed CG: `{cg['final_screening_cg_x_m']} m`",
            f"- Required forward rebalance: `{cg['required_forward_rebalance_m']} m`",
            f"- Bounded physical twist: `{aero['conservative_bounded_physical_projection_max_abs_deg']} deg`",
            "",
            "## frozen / do not casually change",
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
            "Construction, structure, control, propulsion, and manufacturing teams may "
            "start assigned Baseline A work from this package. The allowed start is "
            "coupon/local FEM/RFQ/interface work, not unrestricted external-shape or "
            "aircraft sign-off work.",
            "",
        ]
    )


def _write_mass_budget(path: Path, context: Mapping[str, Any]) -> None:
    mass = _mapping_at(context, "mass")
    drag = _mapping_at(context, "drag_power")
    rows = [
        {
            "item": "source_screening_mass_before_integrated_items",
            "mass_kg": _fmt(mass["source_total_mass_after_items_kg"]),
            "status": "source_screening_basis",
            "basis": "selected hybrid closure before C04 fix and splice mass",
            "owner": "release_builder",
        },
        {
            "item": "rib_mass_delta",
            "mass_kg": _fmt(drag["rib_mass_delta_kg"]),
            "status": "charged_to_screening_read",
            "basis": "selected physical rib/torsion basis",
            "owner": "structures",
        },
        {
            "item": "tail_mass_delta",
            "mass_kg": _fmt(drag["tail_mass_delta_kg"]),
            "status": "charged_to_screening_read",
            "basis": "tail/CG/trim/stability screening",
            "owner": "controls",
        },
        {
            "item": "p1_c04_fix_full_wing",
            "mass_kg": _fmt(mass["additional_masses_kg"]["p1_c04_fix_full_wing"]),
            "status": "architecture_selected_needs_coupon_local_fem",
            "basis": "saddle ring yoke plus secondary clamp",
            "owner": "structures",
        },
        {
            "item": "spar_splice_full_wing",
            "mass_kg": _fmt(mass["additional_masses_kg"]["spar_splice_full_wing"]),
            "status": "screening_design_needs_rfq_detail",
            "basis": "3 m panel transport spar splice pack",
            "owner": "manufacturing",
        },
        {
            "item": "updated_screening_mass_basis",
            "mass_kg": _fmt(mass["updated_total_mass_after_items_kg"]),
            "status": "screening_basis_not_measured_weight",
            "basis": "P1 load-path mass closure report",
            "owner": "chief_engineering",
        },
    ]
    _write_csv(path, rows, ["item", "mass_kg", "status", "basis", "owner"])


def _cg_summary(context: Mapping[str, Any]) -> dict[str, Any]:
    cg = _mapping_at(context, "cg")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": cg["status"],
        "cg_range_m": cg["cg_range_x_m"],
        "managed_final_cg_m": cg["final_screening_cg_x_m"],
        "uncompensated_cg_m": cg["uncompensated_cg_x_m"],
        "uncompensated_cg_status": cg["uncompensated_cg_status"],
        "required_forward_rebalance_m": cg["required_forward_rebalance_m"],
        "forward_rebalance_limit_m": cg["forward_rebalance_limit_m"],
        "rebalance_mass_kg": cg["forward_rebalance_mass_kg"],
        "claim_boundary": (
            "Managed CG is a screening closure row. It is not measured aircraft CG "
            "and not approval to accept the uncompensated mass state."
        ),
    }


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
            "item": "updated_screening_mass",
            "value": _fmt(drag["total_screening_mass_after_integrated_items_kg"]),
            "unit": "kg",
            "status": "charged_to_screening_read",
            "basis": "mass integrated P1 closure",
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
            "Baseline A allows the shop-facing team to start test articles and RFQs.",
            "",
            "## Start Now",
            "",
            "- C04 saddle/yoke/clamp coupon.",
            "- C04 local FEM and coupon correlation package.",
            "- 1 m wing-bay v2 with rib/collar/skin-sag evidence.",
            "- Carbon tube RFQ for main/rear spar and splice-fit tolerances.",
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
            "This is an RFQ screening spec, not a released production drawing.",
            "",
            "## Requested Tube Families",
            "",
            "- Main spar reference: 100 mm OD / 98 mm ID HM CFRP tube family.",
            "- Rear spar reference: 80 mm OD / 78 mm ID HM CFRP tube family.",
            "- Splice spigot family: internal CFRP spigot, 4D overlap each side.",
            "- Inboard splice wall reference: 1.02 mm screening wall at the highest-load station.",
            "",
            "## Vendor Questions",
            "",
            "- OD/ID tolerance, straightness, and ovality over 3 m shipped segments.",
            "- Layup schedule, fiber modulus class, resin system, cure temperature, and QA coupons.",
            "- Bond surface preparation compatibility for saddle rings, ferrules, and spigots.",
            "- Minimum order length, shipping limit, damage inspection, and replacement policy.",
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
            "## frozen / do not casually change",
            "",
            "- Candidate identity and Phase J pathfinder narrative.",
            "- Selected rib/torsion basis and 0.30 m physical rib spacing.",
            "- Managed CG row and rejection of uncompensated CG.",
            "",
            "## controlled / can change with review",
            "",
            "- Saddle/yoke/clamp local detail.",
            "- Carbon tube RFQ details and splice implementation.",
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
    queue = [
        (
            "WO-001",
            "design-space freeze audit",
            "Confirm Baseline A external-shape and mission bounds are frozen enough for team work.",
        ),
        (
            "WO-002",
            "manufacturable discretization/smoothness audit",
            "Check station spacing, rib bays, tube segmentation, and smoothness for shop handoff.",
        ),
        (
            "WO-003",
            "mass/CG/margin ledger",
            "Keep a single append-only ledger for mass, CG, and governing margins.",
        ),
        (
            "WO-004",
            "main-wing SU2 baseline validation",
            "Queue a bounded CFD baseline; do not use it as current structural-blocker truth.",
        ),
        (
            "WO-005",
            "QPROP/XROTOR propulsion interface",
            "Translate independent propulsion results into reviewed thrust/torque/mass interfaces.",
        ),
        (
            "WO-006",
            "turn/stall competition gate",
            "Define competition maneuver and stall evidence gates before expanding search.",
        ),
        (
            "WO-007",
            "control derivative matrix and tail motor authority",
            "Build controls-facing derivative and actuator authority matrix.",
        ),
        (
            "WO-008",
            "tailboom/vertical strut first-order model",
            "Add first-order structural load path model for tailboom and vertical strut.",
        ),
        (
            "WO-009",
            "airfoil database CST/NSGA background lane",
            "Run as background database improvement, not as Baseline A blocker.",
        ),
        (
            "WO-010",
            "report/CAD/export automation",
            "Automate reports and export bundles after release package semantics are stable.",
        ),
    ]
    lines = [
        "# Team Work Packages",
        "",
        "Do not implement SU2/NSGA/propeller optimization in this release-builder task.",
        "",
        "## Priority Queue",
        "",
    ]
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
            "/goal",
            "In /Volumes/Samsung SSD/hpa-mdo, execute WO-001 design-space freeze audit.",
            "Read README.md, CURRENT_MAINLINE.md, output/baseline_A_team_release/, "
            "and docs/AI_WORK_ORDER_PROTOCOL.md first. Do not edit physics code unless "
            "the audit finds a release-blocking inconsistency. Verify whether Baseline A "
            "external shape, selected rib/torsion basis, managed CG, mass basis, and "
            "reopen triggers are internally consistent. Output pass/needs_fix/"
            "dangerous_assumption/reopen_risk, update docs only if needed, run relevant "
            "tests/ruff/git diff --check, and commit only this work order.",
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
        "Tube RFQ cannot meet main/rear spar OD, wall, tolerance, or splice-fit assumptions.",
        "Qualified aero-surface mapping invalidates the current direct stress-test warning read.",
        "Tail trim/stability or control authority fails at managed CG.",
        "Main-wing SU2 baseline changes drag/power enough to invalidate mission margins.",
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
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


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
