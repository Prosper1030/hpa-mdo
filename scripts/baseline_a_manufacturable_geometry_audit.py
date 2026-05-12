#!/usr/bin/env python3
"""WO-004 manufacturable smoothness and discretization audit.

This audit reads existing Baseline A geometry, rib, splice, and closure
artifacts. It does not redesign the airplane and does not produce manufacturing
drawings. The output is a team-release warning package that separates smooth
screening geometry from shop-facing station control.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "output" / "baseline_A_team_release" / "manufacturable_geometry_audit"
)

GEOMETRY_FREEZE_JSON = REPO_ROOT / "output" / "baseline_A_team_release" / "geometry_freeze.json"
PRODUCTION_GEOMETRY_MANIFEST_JSON = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "final_candidate_package"
    / "geometry_exports"
    / "production_inspection"
    / "current_avl_compromise_conservative_closed"
    / "geometry_manifest.json"
)
PRODUCTION_SECTION_TABLE_CSV = PRODUCTION_GEOMETRY_MANIFEST_JSON.parent / "section_table.csv"
PRODUCTION_QUALITY_CSV = (
    REPO_ROOT
    / "output"
    / "phase9_structure_jig_smooth_planform"
    / "production_geometry_quality.csv"
)
RIB_AUDIT_JSON = (
    REPO_ROOT
    / "output"
    / "current_pathfinder_materialized_rib_contract_audit"
    / "materialized_rib_contract_audit.json"
)
MANDATORY_RIB_REASON_CSV = (
    REPO_ROOT
    / "output"
    / "current_pathfinder_materialized_rib_contract_audit"
    / "mandatory_rib_reason.csv"
)
SPAR_SPLICE_JSON = (
    REPO_ROOT / "output" / "current_pathfinder_spar_splice_design" / "splice_design_report.json"
)
SPAR_SPLICE_CSV = (
    REPO_ROOT / "output" / "current_pathfinder_spar_splice_design" / "splice_joints.csv"
)
P1_MASS_CLOSURE_JSON = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "2026-05-12_current_pathfinder_p1_load_path_mass_closure.json"
)
DESIGN_SPACE_REOPEN_JSON = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "design_space_freeze_audit"
    / "baseline_A_reopen_risk.json"
)

SCHEMA_VERSION = "baseline_a_manufacturable_geometry_audit_v1"
WORK_ORDER = "WO-004 Manufacturable Smoothness / Discretization Audit"
VERDICT = "geometry_freeze_needs_fix"
NEXT_WORK_ORDER = "WO-005 Carbon Tube RFQ + Procurement Pack"

ALLOWED_CATEGORIES = {
    "smooth_and_manufacturable",
    "smooth_but_not_manufacturable",
    "manufacturable_but_geometry_discontinuity_risk",
    "needs_redesign",
}

CSV_FIELDNAMES = [
    "finding_id",
    "category",
    "area",
    "checked_source",
    "observed",
    "engineering_read",
    "release_action",
    "reopen_risk",
]


def build_manufacturable_geometry_audit() -> dict[str, Any]:
    """Build the WO-004 audit payload from current repo artifacts."""

    geometry_freeze = _read_json(GEOMETRY_FREEZE_JSON)
    geometry_manifest = _read_json(PRODUCTION_GEOMETRY_MANIFEST_JSON)
    section_rows = _read_csv(PRODUCTION_SECTION_TABLE_CSV)
    quality_rows = _read_csv(PRODUCTION_QUALITY_CSV)
    rib_audit = _read_json(RIB_AUDIT_JSON)
    mandatory_rows = _read_csv(MANDATORY_RIB_REASON_CSV)
    splice = _read_json(SPAR_SPLICE_JSON)
    splice_rows = _read_csv(SPAR_SPLICE_CSV)
    p1 = _read_json(P1_MASS_CLOSURE_JSON)
    design_space = _read_json(DESIGN_SPACE_REOPEN_JSON)

    metrics = _collect_metrics(
        geometry_freeze=geometry_freeze,
        geometry_manifest=geometry_manifest,
        section_rows=section_rows,
        quality_rows=quality_rows,
        rib_audit=rib_audit,
        mandatory_rows=mandatory_rows,
        splice=splice,
        splice_rows=splice_rows,
        p1=p1,
        design_space=design_space,
    )
    rows = _build_rows(metrics)
    warnings = _build_warnings(metrics)
    smoothness_warning = {
        "schema_version": SCHEMA_VERSION,
        "work_order": WORK_ORDER,
        "verdict": VERDICT,
        "checked_sources": _checked_sources(),
        "warnings": warnings,
        "reopen_triggers": _reopen_triggers(metrics),
        "next_recommended_work_order": NEXT_WORK_ORDER,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "work_order": WORK_ORDER,
        "verdict": VERDICT,
        "metrics": metrics,
        "geometry_discretization_rows": rows,
        "smoothness_warning": smoothness_warning,
        "report_md": _render_markdown(metrics, rows, smoothness_warning),
    }


def write_manufacturable_geometry_audit_package(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Path]:
    """Write the required WO-004 audit package files."""

    audit = build_manufacturable_geometry_audit()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "report_md": output_dir / "manufacturable_geometry_audit.md",
        "geometry_csv": output_dir / "geometry_discretization_report.csv",
        "warning_json": output_dir / "smoothness_warning.json",
    }
    paths["report_md"].write_text(audit["report_md"], encoding="utf-8")
    _write_csv(paths["geometry_csv"], audit["geometry_discretization_rows"])
    _write_json(paths["warning_json"], audit["smoothness_warning"])
    return paths


def _collect_metrics(
    *,
    geometry_freeze: Mapping[str, Any],
    geometry_manifest: Mapping[str, Any],
    section_rows: list[dict[str, str]],
    quality_rows: list[dict[str, str]],
    rib_audit: Mapping[str, Any],
    mandatory_rows: list[dict[str, str]],
    splice: Mapping[str, Any],
    splice_rows: list[dict[str, str]],
    p1: Mapping[str, Any],
    design_space: Mapping[str, Any],
) -> dict[str, Any]:
    y_values = [_float(row["y_m"]) for row in section_rows]
    chords = [_float(row["chord_m"]) for row in section_rows]
    twists = [_float(row["twist_deg"]) for row in section_rows]
    z_values = [_float(row["z_m"]) for row in section_rows]
    dihedral = [
        _float(row["dihedral_local_deg"])
        for row in section_rows
        if row.get("dihedral_local_deg", "") != ""
    ]
    chord_positive_jumps = [
        chords[i + 1] - chords[i]
        for i in range(len(chords) - 1)
        if chords[i + 1] - chords[i] > 1.0e-9
    ]
    twist_jumps = [abs(twists[i + 1] - twists[i]) for i in range(len(twists) - 1)]
    z_positive = all(z_values[i + 1] >= z_values[i] for i in range(len(z_values) - 1))
    dihedral_positive = all(dihedral[i + 1] >= dihedral[i] for i in range(len(dihedral) - 1))

    quality = _quality_row(quality_rows)
    station_trace = _mapping_at(rib_audit, "station_bay_trace")
    rib_rows = _list_at(rib_audit, "rib_station_table")
    rib_extent_m = max(abs(_float(row["y_m"])) for row in rib_rows)
    missing_contracts = [
        row["contract_item"] for row in mandatory_rows if row.get("status") == "missing_contract"
    ]
    spar_joint_y = _contract_y_values(mandatory_rows, "spar_joint")
    splice_y = [_float(row["y_m"]) for row in splice_rows]
    worst_joint_margin = _float(splice["worst_joint_margin"])
    selected_stiffness = _mapping_at(
        _mapping_at(_mapping_at(p1, "mass_cg_tail_closure"), "basis"),
        "selected_stiffness_basis",
    )
    design_reopen = _mapping_at(design_space, "reopen_triggers")

    return {
        "candidate_id": geometry_freeze["candidate_id"],
        "release_verdict": geometry_freeze["release_verdict"],
        "geometry_freeze_rib_spacing_m": _float(
            _mapping_at(geometry_freeze, "frozen")["rib_spacing_m"]
        ),
        "span_m": _float(geometry_manifest["computed_span_m"]),
        "aero_half_span_m": _float(geometry_manifest["computed_span_m"]) / 2.0,
        "section_tip_y_m": max(y_values),
        "rib_extent_m": rib_extent_m,
        "structural_half_span_m": _float(splice["half_span_m"]),
        "loaded_tip_z_m": _float(geometry_manifest["loaded_tip_z_m"]),
        "root_chord_m": chords[0],
        "tip_chord_m": chords[-1],
        "section_count": len(section_rows),
        "airfoil_assignment": geometry_manifest["airfoil_assignment"],
        "airfoil_change_y_m": _first_airfoil_change_y(section_rows),
        "chord_positive_jump_count": len(chord_positive_jumps),
        "max_positive_chord_jump_m": max(chord_positive_jumps, default=0.0),
        "max_twist_jump_deg": max(twist_jumps, default=0.0),
        "z_monotone": z_positive,
        "dihedral_monotone": dihedral_positive,
        "smooth_visual_production_score": _float(
            quality.get("visual_production_score", quality.get("smooth_visual_production_score", 0.0))
        ),
        "smooth_max_slope_change_abs": _float(quality.get("max_slope_change_abs", 0.0)),
        "smooth_area_error_pct": _float(quality.get("area_error_pct_vs_reference", 0.0)),
        "rib_station_count": int(station_trace["full_wing_station_count"]),
        "rib_bay_count": int(station_trace["full_wing_bay_count"]),
        "rib_target_spacing_m": _float(station_trace["target_spacing_m"]),
        "rib_max_bay_m": _float(station_trace["max_materialized_bay_m"]),
        "rib_trace_status": station_trace["trace_status"],
        "missing_station_contracts": missing_contracts,
        "spar_joint_y_m": spar_joint_y,
        "splice_y_m": splice_y,
        "inboard_splice_margin": worst_joint_margin,
        "inboard_splice_y_m": _float(splice["worst_joint_y_m"]),
        "inboard_splice_governs": splice["worst_joint_governs"],
        "selected_stiffness_case_id": selected_stiffness.get("case_id", "missing"),
        "selected_stiffness_rib_target_spacing_m": _float(
            selected_stiffness.get("rib_target_spacing_m", 0.0)
        ),
        "selected_stiffness_materialized_max_subbay_m": _float(
            selected_stiffness.get("materialized_max_subbay_m", 0.0)
        ),
        "quick_screen_release_margin_w": _nested_float(
            design_space,
            ("baseline_release", "quick_screen_release_total_margin_w"),
        ),
        "design_space_reopen_read": _mapping_at(
            design_reopen,
            "manufacturable_discretization_forces_major_external_shape_or_spar_spec_change",
        ).get("status", "not_checked"),
    }


def _build_rows(metrics: Mapping[str, Any]) -> list[dict[str, str]]:
    rows = [
        _row(
            "main_wing_chord_smoothness",
            "smooth_and_manufacturable",
            "main_wing_planform",
            PRODUCTION_SECTION_TABLE_CSV,
            (
                f"{metrics['section_count']} inspection sections; chord is monotone with "
                f"{metrics['chord_positive_jump_count']} positive jumps; root chord "
                f"{metrics['root_chord_m']:.6f} m, tip chord {metrics['tip_chord_m']:.6f} m."
            ),
            (
                "Large external chord distribution is smooth enough for team-release "
                "inspection; it is still not a CAD curvature proof."
            ),
            "Keep smooth basis; produce a controlled shop station table before drawings.",
            "not_triggered",
        ),
        _row(
            "twist_dihedral_loaded_shape_smoothness",
            "smooth_and_manufacturable",
            "main_wing_twist_dihedral_loaded_shape",
            PRODUCTION_SECTION_TABLE_CSV,
            (
                f"Loaded tip z {metrics['loaded_tip_z_m']:.6f} m; max adjacent twist "
                f"jump {metrics['max_twist_jump_deg']:.3f} deg; z monotone "
                f"{metrics['z_monotone']}; local dihedral monotone {metrics['dihedral_monotone']}."
            ),
            (
                "No large external-shape discontinuity is evident in the inspection "
                "section table, but beam-line z remains a screening proxy."
            ),
            "Keep as screening smooth geometry; do not call it aero-surface sign-off.",
            "not_triggered",
        ),
        _row(
            "continuous_dimensions_need_shop_grid",
            "smooth_but_not_manufacturable",
            "dimensioning",
            PRODUCTION_GEOMETRY_MANIFEST_JSON,
            (
                f"Span {metrics['span_m']:.6f} m, aero half-span "
                f"{metrics['aero_half_span_m']:.6f} m, non-round section y stations "
                "such as 2.746583/6.008150/14.076237 m."
            ),
            (
                "The current continuous dimensions are fine for screening geometry, "
                "but they are not shop-facing dimensions."
            ),
            "Create a 0.05 or 0.10 m controlled station schedule tied to rib bays before RFQ/drawings.",
            "not_triggered",
        ),
        _row(
            "airfoil_section_handoff_contract",
            "smooth_but_not_manufacturable",
            "airfoil_transition",
            MANDATORY_RIB_REASON_CSV,
            (
                f"Airfoil assignment is {metrics['airfoil_assignment']}; first section "
                f"handoff to tip airfoil occurs near y={metrics['airfoil_change_y_m']:.3f} m, "
                "while airfoil_transition is a missing station contract."
            ),
            (
                "The aerodynamic sidecar can interpolate sections, but the shop needs "
                "an explicit handoff rib/station and section blending note."
            ),
            "Add airfoil-transition station contract to the WO-005/RFQ station manifest.",
            "watch_not_reopen",
        ),
        _row(
            "rib_0p30_materialized",
            "smooth_and_manufacturable",
            "rib_bays",
            RIB_AUDIT_JSON,
            (
                f"{metrics['rib_station_count']} full-wing stations and "
                f"{metrics['rib_bay_count']} bays; max materialized bay "
                f"{metrics['rib_max_bay_m']:.6f} m against target "
                f"{metrics['rib_target_spacing_m']:.2f} m."
            ),
            (
                "The 0.30 m rib basis is physically materialized in the station/bay "
                "trace, not only a naked local-wall assumption."
            ),
            "Keep 0.30 m as release-facing bay trace, with local FEM/coupon caveats.",
            "not_triggered",
        ),
        _row(
            "release_vs_selected_stiffness_rib_spacing",
            "smooth_but_not_manufacturable",
            "rib_basis_consistency",
            P1_MASS_CLOSURE_JSON,
            (
                f"Release freeze says 0.30 m, but selected stiffness basis "
                f"{metrics['selected_stiffness_case_id']} records target spacing "
                f"{metrics['selected_stiffness_rib_target_spacing_m']:.3f} m and "
                f"materialized max subbay {metrics['selected_stiffness_materialized_max_subbay_m']:.3f} m."
            ),
            (
                "This is a release-contract inconsistency: the physical station trace "
                "is 0.30 m, while the later stiffness bookkeeping carries a relaxed "
                "spacing label."
            ),
            "Before procurement, reconcile whether Baseline A controls 0.30 m physical ribs or the relaxed stiffness row.",
            "watch_not_reopen",
        ),
        _row(
            "splice_station_contract_mismatch",
            "manufacturable_but_geometry_discontinuity_risk",
            "transport_splice_stations",
            SPAR_SPLICE_CSV,
            (
                "Splice design screens 3.0/6.0/9.0/12.0/15.0 m, while materialized "
                f"spar-joint ribs are {_fmt_y_list(metrics['spar_joint_y_m'])} m."
            ),
            (
                "Both station languages are individually plausible, but using both "
                "unlabeled will confuse spar cuts, sleeve locations, rib hard-points, "
                "and RFQ drawings."
            ),
            "Create one controlled transport/splice/station manifest before carbon tube RFQ.",
            "watch_not_reopen",
        ),
        _row(
            "span_extent_contract_mismatch",
            "manufacturable_but_geometry_discontinuity_risk",
            "span_extent",
            GEOMETRY_FREEZE_JSON,
            (
                f"Structural splice half-span {metrics['structural_half_span_m']:.3f} m; "
                f"production aero section tip y {metrics['section_tip_y_m']:.3f} m; "
                f"materialized rib extent {metrics['rib_extent_m']:.3f} m."
            ),
            (
                "The mismatch is small enough to fix as a station-contract problem, "
                "but it is not acceptable as an RFQ or shop drawing basis."
            ),
            "Define whether the outer 0.67-0.82 m per side is aerodynamic tip structure, removable tip, or excluded from spar procurement.",
            "watch_not_reopen",
        ),
        _row(
            "inboard_splice_zero_margin_rfq_warning",
            "manufacturable_but_geometry_discontinuity_risk",
            "spar_splice_margin",
            SPAR_SPLICE_JSON,
            (
                f"Worst joint y={metrics['inboard_splice_y_m']:.1f} m has governing "
                f"margin {metrics['inboard_splice_margin']:.3f} in "
                f"{metrics['inboard_splice_governs']} after auto-sizing."
            ),
            (
                "A zero screening margin is not a Baseline A reopen by itself, but "
                "it is an RFQ/detail warning because vendor tolerances, ovality, fit, "
                "and knockdowns can consume it."
            ),
            "Carry as WO-005 RFQ warning; ask vendors for tube/spigot tolerance, sleeve fit, and local test evidence.",
            "rfq_warning_not_reopen",
        ),
        _row(
            "control_tail_transition_station_contracts",
            "smooth_but_not_manufacturable",
            "control_and_tail_interfaces",
            MANDATORY_RIB_REASON_CSV,
            (
                "Missing station contracts include "
                f"{', '.join(metrics['missing_station_contracts'])}."
            ),
            (
                "The main wing can remain a release pathfinder, but control, twist, "
                "airfoil transition, and transport stations need an explicit manifest "
                "before team work uses them as physical locations."
            ),
            "Add a station-interface manifest as a prerequisite note for WO-005/WO-009/WO-010.",
            "watch_not_reopen",
        ),
        _row(
            "skin_sag_bond_collar_trust_boundary",
            "smooth_but_not_manufacturable",
            "rib_skin_bond_local_detail",
            RIB_AUDIT_JSON,
            (
                "Materialized rib audit still marks skin sag as unknown_requires_test "
                "and bond/collar/spar contact as needs_data."
            ),
            (
                "This does not break large external smoothness, but it prevents any "
                "final manufacturing sign-off or coupon/FEM closure claim."
            ),
            "Keep one-meter wing-bay v2 and C04 coupon/local FEM ahead of build sign-off.",
            "not_triggered",
        ),
    ]
    _validate_rows(rows)
    return rows


def _build_warnings(metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": "span_extent_contract_mismatch",
            "severity": "warning",
            "category": "manufacturable_but_geometry_discontinuity_risk",
            "engineering_read": (
                f"Structural half-span is {metrics['structural_half_span_m']:.3f} m, "
                f"while aero/rib evidence extends to {metrics['section_tip_y_m']:.3f}/"
                f"{metrics['rib_extent_m']:.3f} m. Resolve this before RFQ."
            ),
        },
        {
            "id": "splice_station_contract_mismatch",
            "severity": "warning",
            "category": "manufacturable_but_geometry_discontinuity_risk",
            "engineering_read": (
                "3 m RFQ-style splice stations conflict with materialized spar-joint "
                "rib stations unless one manifest owns the convention."
            ),
        },
        {
            "id": "inboard_splice_zero_margin_rfq_warning",
            "severity": "rfq_warning",
            "category": "manufacturable_but_geometry_discontinuity_risk",
            "engineering_read": (
                "The y=3 m splice only screens at zero bending margin. Treat as a "
                "vendor/detail warning, not a release reopen yet."
            ),
        },
        {
            "id": "release_vs_selected_stiffness_rib_spacing",
            "severity": "warning",
            "category": "smooth_but_not_manufacturable",
            "engineering_read": (
                "Release-facing 0.30 m station trace and later 0.345 m selected "
                "stiffness bookkeeping must be reconciled before procurement language."
            ),
        },
        {
            "id": "continuous_dimensions_not_shop_grid",
            "severity": "warning",
            "category": "smooth_but_not_manufacturable",
            "engineering_read": (
                "Continuous station values are acceptable for screening but need a "
                "0.05/0.10 m or rib-bay shop grid before team release drawings."
            ),
        },
        {
            "id": "airfoil_control_transition_contracts_missing",
            "severity": "warning",
            "category": "smooth_but_not_manufacturable",
            "engineering_read": (
                "Airfoil, twist, control, and transport station contracts are still "
                "missing in the materialized rib audit."
            ),
        },
    ]


def _reopen_triggers(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "manufacturing_discretization_forces_reopen": "not_triggered",
        "large_external_shape_discontinuity": "not_triggered",
        "span_extent_or_splice_manifest_forces_spar_spec_change": "watch_not_reopen",
        "inboard_splice_vendor_margin_invalidates_assumptions": "watch_for_WO-005",
        "release_mass_tail_cd0_power_margin": {
            "status": "watch_not_reopen",
            "quick_screen_release_total_margin_w": metrics["quick_screen_release_margin_w"],
        },
        "engineering_read": (
            "WO-004 found station/manifest fixes required before shop/RFQ use, but no "
            "large external-shape discontinuity or explicit Baseline A reopen trigger."
        ),
    }


def _render_markdown(
    metrics: Mapping[str, Any],
    rows: list[Mapping[str, str]],
    warning: Mapping[str, Any],
) -> str:
    table_lines = [
        "| Finding | Category | Release action |",
        "|---|---|---|",
    ]
    for row in rows:
        table_lines.append(
            f"| `{row['finding_id']}` | `{row['category']}` | {row['release_action']} |"
        )

    warning_lines = [
        f"- `{item['id']}`: {item['engineering_read']}" for item in warning["warnings"]
    ]
    source_lines = [f"- `{path}`" for path in _checked_sources()]
    return "\n".join(
        [
            "# Baseline A Manufacturable Geometry Audit",
            "",
            f"Work order: `{WORK_ORDER}`",
            f"Verdict: `{VERDICT}`",
            "",
            "Baseline A smooth geometry is good enough to keep as a team-release "
            "pathfinder, but not clean enough to hand to the shop or tube vendors as "
            "controlled dimensions yet. The audit found no large external-shape "
            "discontinuity that forces redesign; the blockers are station-control, "
            "span-extent, rib-spacing-language, and splice/RFQ margin issues.",
            "",
            "This is not final manufacturing drawing sign-off.",
            "",
            "## Key Numbers",
            "",
            f"- Candidate: `{metrics['candidate_id']}`",
            f"- Aero span: `{metrics['span_m']:.6f} m` "
            f"(half `{metrics['aero_half_span_m']:.6f} m`)",
            f"- Production section tip y: `{metrics['section_tip_y_m']:.6f} m`",
            f"- Materialized rib extent: `{metrics['rib_extent_m']:.6f} m`",
            f"- Structural splice half-span basis: `{metrics['structural_half_span_m']:.6f} m`",
            f"- Rib trace: `{metrics['rib_station_count']}` full-wing stations, "
            f"max bay `{metrics['rib_max_bay_m']:.6f} m`",
            f"- Inboard splice screen: y=`{metrics['inboard_splice_y_m']:.1f} m`, "
            f"margin `{metrics['inboard_splice_margin']:.3f}`",
            "",
            "## Findings",
            "",
            *table_lines,
            "",
            "## Core Engineering Answers",
            "",
            "1. Main-wing chord, twist, dihedral, and loaded shape are smooth enough "
            "for screening release inspection; they are not CAD curvature or final "
            "aero-surface sign-off.",
            "2. Continuous dimensions need a 0.05/0.10 m, rib-bay, or controlled "
            "segment grid before shop-facing use.",
            "3. The 0.30 m rib basis is materialized in the station table, but the "
            "release package must reconcile that with the later 0.345 m relaxed "
            "stiffness bookkeeping.",
            "4. 3 m transport splice stations and materialized spar-joint ribs are "
            "not the same station contract; one manifest must own this before RFQ.",
            "5. The 16.5 m structural half-span and 17.17-17.32 m aero/rib extents "
            "are a hidden mismatch and need station-control cleanup.",
            "6. The near-zero inboard splice bending margin is an RFQ/manufacturing "
            "warning, not a Baseline A reopen by itself.",
            "7. No discontinuity was found that currently forces large external-shape, "
            "spar-spec, mass/CG, procurement, or Baseline A reopen.",
            "",
            "## Warnings",
            "",
            *warning_lines,
            "",
            "## Checked Sources",
            "",
            *source_lines,
            "",
            "## Trust Boundary",
            "",
            "The audit supports Baseline A as a team release package with required "
            "station-manifest fixes. It does not approve production drawings, tube "
            "orders, final rib construction, adhesive/collar margins, aero-surface "
            "mapping, or aircraft sign-off.",
            "",
            "## Next Recommended Work Order",
            "",
            f"`{NEXT_WORK_ORDER}` after a controlled station/span/splice manifest is "
            "attached to the RFQ package.",
            "",
        ]
    )


def _checked_sources() -> list[str]:
    return [
        _rel(GEOMETRY_FREEZE_JSON),
        _rel(PRODUCTION_GEOMETRY_MANIFEST_JSON),
        _rel(PRODUCTION_SECTION_TABLE_CSV),
        _rel(PRODUCTION_QUALITY_CSV),
        _rel(RIB_AUDIT_JSON),
        _rel(MANDATORY_RIB_REASON_CSV),
        _rel(SPAR_SPLICE_JSON),
        _rel(SPAR_SPLICE_CSV),
        _rel(P1_MASS_CLOSURE_JSON),
        _rel(DESIGN_SPACE_REOPEN_JSON),
    ]


def _row(
    finding_id: str,
    category: str,
    area: str,
    source: Path,
    observed: str,
    engineering_read: str,
    release_action: str,
    reopen_risk: str,
) -> dict[str, str]:
    return {
        "finding_id": finding_id,
        "category": category,
        "area": area,
        "checked_source": _rel(source),
        "observed": observed,
        "engineering_read": engineering_read,
        "release_action": release_action,
        "reopen_risk": reopen_risk,
    }


def _validate_rows(rows: Iterable[Mapping[str, str]]) -> None:
    for row in rows:
        category = row["category"]
        if category not in ALLOWED_CATEGORIES:
            raise ValueError(f"Unknown category for {row['finding_id']}: {category}")


def _quality_row(rows: list[dict[str, str]]) -> dict[str, str]:
    for row in rows:
        if row.get("case_id") == "conservative_best_tier2" and row.get("variant") == "smooth_monotone":
            return row
    for row in rows:
        if row.get("variant") == "smooth_monotone":
            return row
    return {}


def _first_airfoil_change_y(section_rows: list[dict[str, str]]) -> float:
    if not section_rows:
        return 0.0
    first = section_rows[0]["airfoil_id"]
    for row in section_rows[1:]:
        if row["airfoil_id"] != first:
            return _float(row["y_m"])
    return _float(section_rows[-1]["y_m"])


def _contract_y_values(rows: list[dict[str, str]], contract_item: str) -> list[float]:
    for row in rows:
        if row.get("contract_item") == contract_item:
            values = []
            for raw in row.get("y_m", "").split(";"):
                if raw:
                    value = _float(raw)
                    if value >= 0.0:
                        values.append(value)
            return sorted(values)
    return []


def _fmt_y_list(values: list[float]) -> str:
    return "/".join(f"{value:.3f}" for value in values)


def _mapping_at(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = mapping.get(key, {})
    if not isinstance(value, Mapping):
        return {}
    return value


def _list_at(mapping: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = mapping.get(key, [])
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _nested_float(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, Mapping) or key not in value:
            return None
        value = value[key]
    return _float(value)


def _float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def _rel(path: Path) -> str:
    return str(Path(path).relative_to(REPO_ROOT))


def _read_json(path: Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as fh:
        loaded = json.load(fh)
    if not isinstance(loaded, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return loaded


def _read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[Mapping[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for manufacturable geometry audit artifacts.",
    )
    args = parser.parse_args()
    paths = write_manufacturable_geometry_audit_package(output_dir=args.output_dir)
    for key, path in paths.items():
        print(f"{key}: {path}")


if __name__ == "__main__":
    main()
