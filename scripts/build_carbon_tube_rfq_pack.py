#!/usr/bin/env python3
"""Build the Baseline A carbon tube RFQ screening pack.

This work-order pack is vendor-facing, but it is still a screening artifact:
it does not place orders, choose suppliers, release drawings, or change spar
dimensions. It exists to keep tube, splice, rib, station, and transport language
from being mixed silently during RFQ conversations.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from hpa_mdo.utils.baseline_a_rfq_spec import render_carbon_tube_rfq_spec


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "baseline_A_team_release"

GEOMETRY_FREEZE_JSON = DEFAULT_OUTPUT_DIR / "geometry_freeze.json"
GEOMETRY_DISCRETIZATION_CSV = (
    DEFAULT_OUTPUT_DIR
    / "manufacturable_geometry_audit"
    / "geometry_discretization_report.csv"
)
SMOOTHNESS_WARNING_JSON = (
    DEFAULT_OUTPUT_DIR
    / "manufacturable_geometry_audit"
    / "smoothness_warning.json"
)
MATERIALIZED_RIB_AUDIT_JSON = (
    REPO_ROOT
    / "output"
    / "current_pathfinder_materialized_rib_contract_audit"
    / "materialized_rib_contract_audit.json"
)
SPLICE_DESIGN_JSON = (
    REPO_ROOT
    / "output"
    / "current_pathfinder_spar_splice_design"
    / "splice_design_report.json"
)
P1_CLOSURE_JSON = (
    REPO_ROOT
    / "output"
    / "current_pathfinder_p1_load_path_mass_closure"
    / "p1_load_path_mass_closure.json"
)
CARBON_TUBE_CSV = REPO_ROOT / "data" / "carbon_tubes.csv"

SCHEMA_VERSION = "baseline_a_carbon_tube_rfq_pack_v1"
VERDICT = "carbon_tube_rfq_pack_draft_vendor_screening"


def build_rfq_context() -> dict[str, Any]:
    """Collect the current screening evidence for the RFQ pack."""
    geometry_freeze = _read_json(GEOMETRY_FREEZE_JSON)
    smoothness = _read_json(SMOOTHNESS_WARNING_JSON)
    materialized = _read_json(MATERIALIZED_RIB_AUDIT_JSON)
    splice = _read_json(SPLICE_DESIGN_JSON)
    p1 = _read_json(P1_CLOSURE_JSON)
    discretization = {
        row["finding_id"]: row
        for row in _read_csv_dicts(GEOMETRY_DISCRETIZATION_CSV)
    }
    tube_catalog = _read_csv_dicts(CARBON_TUBE_CSV)

    main_tube = _tube_catalog_row(tube_catalog, "CF-HM-100x98")
    rear_tube = _tube_catalog_row(tube_catalog, "CF-HM-80x78")

    rib_trace = _mapping_at(materialized, "station_bay_trace")
    selected_rib = _mapping_at(materialized, "selected_rib_basis")
    mass_integration = _mapping_at(p1, "mass_integration")
    local_load_path = _mapping_at(p1, "local_load_path")

    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": VERDICT,
        "authority_status": "blocks_release_procurement_only",
        "wo006_impact": "does_not_block_bounded_aero_calibration",
        "claim_boundary": (
            "Draft vendor-screening pack only; remaining mass/span/RFQ conflicts block "
            "release and procurement, but this does not block bounded WO-006 aero "
            "calibration. It is not purchase-ready, not supplier selection, not "
            "drawing release, and not final aircraft sign-off."
        ),
        "candidate_id": geometry_freeze["candidate_id"],
        "release_verdict": geometry_freeze["release_verdict"],
        "p1_verdict": p1["final_verdict"],
        "geometry_freeze": geometry_freeze,
        "smoothness_warning": smoothness,
        "discretization": discretization,
        "materialized": materialized,
        "splice": splice,
        "p1": p1,
        "main_tube": main_tube,
        "rear_tube": rear_tube,
        "rib_trace": rib_trace,
        "selected_rib": selected_rib,
        "mass_integration": mass_integration,
        "local_load_path": local_load_path,
        "sources": [
            str(GEOMETRY_FREEZE_JSON.relative_to(REPO_ROOT)),
            str(GEOMETRY_DISCRETIZATION_CSV.relative_to(REPO_ROOT)),
            str(SMOOTHNESS_WARNING_JSON.relative_to(REPO_ROOT)),
            str(MATERIALIZED_RIB_AUDIT_JSON.relative_to(REPO_ROOT)),
            str(SPLICE_DESIGN_JSON.relative_to(REPO_ROOT)),
            str(P1_CLOSURE_JSON.relative_to(REPO_ROOT)),
            str(CARBON_TUBE_CSV.relative_to(REPO_ROOT)),
        ],
    }


def write_carbon_tube_rfq_pack(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Path]:
    """Write all WO-005 RFQ pack artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    context = build_rfq_context()

    paths = {
        "front_door_spec": output_dir / "carbon_tube_rfq_spec.md",
        "rfq_pack": output_dir / "carbon_tube_rfq_pack.md",
        "station_manifest": output_dir / "controlled_station_span_splice_manifest.csv",
        "vendor_questionnaire": output_dir / "vendor_questionnaire.md",
        "risk_register": output_dir / "procurement_risk_register.json",
        "tolerance_requirements": output_dir / "tube_splice_tolerance_requirements.csv",
        "daily_review": output_dir / "rfq_daily_review.md",
    }

    _write_text(paths["front_door_spec"], _render_front_door_spec(context))
    _write_text(paths["rfq_pack"], _render_rfq_pack(context))
    _write_csv(paths["station_manifest"], _station_manifest_rows(context))
    _write_text(paths["vendor_questionnaire"], _render_vendor_questionnaire(context))
    _write_json(paths["risk_register"], _risk_register(context))
    _write_csv(paths["tolerance_requirements"], _tolerance_requirement_rows(context))
    _write_text(paths["daily_review"], _render_daily_review(context))
    return paths


def _render_front_door_spec(context: Mapping[str, Any]) -> str:
    main = context["main_tube"]
    rear = context["rear_tube"]
    splice = context["splice"]
    rib_trace = context["rib_trace"]
    stiffness_row = context["discretization"]["release_vs_selected_stiffness_rib_spacing"]
    return render_carbon_tube_rfq_spec(
        verdict=context["verdict"],
        half_span_m=splice["half_span_m"],
        panel_length_m=splice["panel_length_m"],
        rib_target_spacing_m=rib_trace["target_spacing_m"],
        full_wing_station_count=rib_trace["full_wing_station_count"],
        max_materialized_bay_m=rib_trace["max_materialized_bay_m"],
        current_pipeline_full_span_m=34.332286,
        current_pipeline_half_span_m=17.166143,
        main_outer_diameter_mm=main["outer_diameter_mm"],
        main_inner_diameter_mm=main["inner_diameter_mm"],
        main_wall_thickness_mm=main["wall_thickness_mm"],
        rear_outer_diameter_mm=rear["outer_diameter_mm"],
        rear_inner_diameter_mm=rear["inner_diameter_mm"],
        rear_wall_thickness_mm=rear["wall_thickness_mm"],
        stiffness_warning_text=stiffness_row["observed"],
    )


def _render_rfq_pack(context: Mapping[str, Any]) -> str:
    splice = context["splice"]
    geometry = context["geometry_freeze"]
    rib_trace = context["rib_trace"]
    selected_rib = context["selected_rib"]
    local = context["local_load_path"]
    mass = context["mass_integration"]
    warnings = context["smoothness_warning"]["warnings"]

    lines = [
        "# Baseline A Carbon Tube RFQ + Procurement Screening Pack",
        "",
        f"Verdict: `{context['verdict']}`",
        "",
        context["claim_boundary"],
        "",
        "## RFQ Use",
        "",
        "Keep this pack as a draft capability and quote-screening request. It does "
        "not block bounded WO-006 aero calibration, but every page must preserve "
        "the draft/vendor-screening boundary. Do not authorize production or "
        "procurement from this pack.",
        "",
        "## Controlled Station Convention For RFQ",
        "",
        "| Item | RFQ convention | Status |",
        "|---|---|---|",
        "| Half-wing station | Positive `y` from aircraft centerline/root, mirrored left/right | draft_vendor_screening |",
        f"| Local/splice screening extent | `{splice['half_span_m']:.3f} m` half-span, not procurement truth | conflict_blocked |",
        f"| Transport panel length | `{splice['panel_length_m']:.3f} m` maximum shipped/cut panel | screening_constraint |",
        "| Splice stations | `3 / 6 / 9 / 12 / 15 m` per half-wing | draft_vendor_screening |",
        f"| Release rib basis | `{rib_trace['target_spacing_m']:.2f} m` target; max materialized bay `{rib_trace['max_materialized_bay_m']:.6f} m` | controlled_for_rfq_language |",
        "| Airfoil/control/twist/transport station contracts | Not final drawing control | open |",
        "",
        "The draft station convention intentionally does not use the signed full-wing "
        "rib table as the vendor station origin. Materialized spar-joint ribs are "
        "reference hard-points until a drawing-controlled station schedule exists.",
        "",
        "## Tube And Spar Assumptions",
        "",
        "| Role | Basis | Full-wing quantity basis | Status |",
        "|---|---:|---:|---|",
        _tube_table_row("Main spar tube", context["main_tube"], "12 x <=3 m segments plus spare allowance open", "screening_reference"),
        _tube_table_row("Rear spar tube", context["rear_tube"], "12 x <=3 m segments plus spare allowance open", "screening_reference"),
        "| Main-spar internal spigot | OD approx spar ID - 0.2 mm clearance; 4D overlap each side | 10 joints full-wing on current main-spar splice screen | screening_reference |",
        "| Ferrule / shear dog | CFRP ferrule ring plus two shear dogs; removable pin never through CFRP spar | 10 joints full-wing on current main-spar splice screen | screening_reference |",
        "",
        "Quantity basis is only a draft estimate tied to the local/splice screening "
        "half-span. The outer aero/rib tip extension is not yet a tube purchase "
        "length control, and the 16.5 m reference is not procurement truth.",
        "",
        "## Splice Screening Table",
        "",
        "| y [m] | M [N*m] | V [N] | T [N*m] | spigot wall [mm] | overlap [mm] | governing margin | governs | RFQ read |",
        "|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for joint in splice["joints"]:
        rfq_read = (
            "critical warning; vendor tolerance/ovality/knockdown can consume margin"
            if joint["y_m"] == splice["worst_joint_y_m"]
            else "screening pass; still needs vendor fit data"
        )
        lines.append(
            "| {y:.1f} | {m:.1f} | {v:.1f} | {t:.3f} | {wall:.2f} | {overlap:.1f} | {margin:.3f} | {governs} | {read} |".format(
                y=joint["y_m"],
                m=joint["M_nm"],
                v=joint["V_n"],
                t=joint["T_nm"],
                wall=joint["spigot_wall_mm"],
                overlap=joint["spigot_overlap_mm"],
                margin=joint["governing_margin"],
                governs=joint["governs"],
                read=rfq_read,
            )
        )

    lines.extend(
        [
            "",
            "## Required WO-004 Carryover",
            "",
            "| Warning | RFQ handling |",
            "|---|---|",
        ]
    )
    for warning in warnings:
        lines.append(
            f"| `{warning['id']}` | {warning['engineering_read']} |"
        )

    lines.extend(
        [
            "",
            "## P1 And C04 Boundary",
            "",
            f"- P1 verdict remains `{context['p1_verdict']}`.",
            f"- C04 selected fix remains `{local['installed_fix_type']}` with screening governing margin `{local['installed_fix_governing_margin']}`.",
            f"- C04 original eccentric peel fail remains visible: margin `{local['baseline_c04_margin']}`.",
            f"- Splice mass already carried in mass ledger: `{mass['additional_masses_kg']['spar_splice_full_wing']} kg` full-wing screening estimate.",
            "- QPROP/XROTOR is independent and is not used to pass this RFQ or structural blocker.",
            "",
            "## Procurement Review Triggers",
            "",
            "- Vendor cannot quote or make the 100/98 main or 80/78 rear HM CFRP tube family with credible tolerance data.",
            "- Vendor tolerance, ovality, straightness, laminate, or wall-thickness data invalidates sleeve/spigot fit.",
            "- Vendor knockdowns or test data make the y=3 m splice negative after local detail review.",
            "- Vendor changes OD/wall/layup enough to move mass/CG or spar stiffness assumptions.",
            "- Vendor cannot support 3 m segment shipping, inspection, replacement, or certificate traceability.",
            "- Vendor surface prep is incompatible with ferrules, saddle rings, spigots, or adhesive/coupon plans.",
            "",
            "## Source Artifacts",
            "",
            *[f"- `{source}`" for source in context["sources"]],
            "",
            "## Engineering Verdict",
            "",
            "`carbon_tube_rfq_pack_draft_vendor_screening`: retained for vendor "
            "capability questions only inside the stated trust boundary. It is not "
            "ready for purchase authorization or final drawing release.",
            "",
            f"Candidate: `{geometry['candidate_id']}`",
            f"Selected rib/stiffness basis carried for release: `{selected_rib['basis_read']}`",
            "",
        ]
    )
    return "\n".join(lines)


def _render_vendor_questionnaire(context: Mapping[str, Any]) -> str:
    _ = context
    return "\n".join(
        [
            "# Carbon Tube Vendor Questionnaire",
            "",
            "Please answer as a capability and screening quote response only. Do not "
            "treat this as a purchase order or production drawing release.",
            "",
            "## Tube Family And Layup",
            "",
            "1. Can you supply or custom-build HM CFRP tubes near 100 mm OD / 98 mm ID and 80 mm OD / 78 mm ID in 3 m segments?",
            "2. What layup options are available for axial bending stiffness, hoop support, torsion, and local bearing/crush resistance?",
            "3. What fiber modulus class, resin system, cure process, glass transition temperature, and environmental limits are standard?",
            "4. Can you provide balanced/symmetric laminate details or a laminate stiffness matrix suitable for screening FEM?",
            "5. What mandrel sizes are available without custom tooling, and what custom mandrel lead time/cost applies?",
            "",
            "## Tolerance And Fit",
            "",
            "1. State OD, ID, wall-thickness, straightness, and ovality tolerance over a 3 m segment.",
            "2. State whether tolerances are measured before or after finish, sanding, clear coat, or post-cure.",
            "3. For internal spigots, what diametral clearance do you recommend for bonded/slip-fit CFRP tube-in-tube joints?",
            "4. Can you hold sleeve/spigot fit tightly enough for the y=3 m inboard splice where screening bending margin is zero?",
            "5. What local anti-ovalization, end-ring, or crush/bearing details do you recommend at spigot ends?",
            "",
            "## Surface Prep, Bond, And Finish",
            "",
            "1. What surface finish, peel-ply, abrasion, plasma/corona, primer, or cleaning process is compatible with structural bonding?",
            "2. Can the supplied tube accept bonded ferrules, saddle rings, spigots, and secondary clamp contact without coating removal problems?",
            "3. What adhesive systems have you qualified with this tube family?",
            "4. What minimum bond overlap, taper, fillet, and edge-prep practices do you recommend?",
            "",
            "## QA, Coupons, And Certificates",
            "",
            "1. Can you provide material certificates, batch traceability, mass-per-meter record, and dimensional inspection reports?",
            "2. Can you supply witness coupons or cut-off rings from the same batch for local compression, bearing, shear, and bond testing?",
            "3. What NDI or visual inspection is standard before shipment?",
            "4. What replacement policy applies if shipping damage, ovality, or delamination is detected?",
            "",
            "## Commercial And Logistics",
            "",
            "1. minimum order quantity for each tube family and any spigot/ferrule blanks.",
            "2. Lead time for stock and custom mandrel tubes.",
            "3. Maximum shippable tube length, packaging method, and damage-inspection procedure.",
            "4. Quote optional spare/reject allowance separately from the minimum full-wing screening quantity.",
            "",
            "## Required Deviations",
            "",
            "List every deviation from the RFQ basis. Mark whether it affects spar OD, "
            "wall, layup, mass, CG, 3 m shipping, splice fit, coupon data, or supplier lead time.",
            "",
        ]
    )


def _render_daily_review(context: Mapping[str, Any]) -> str:
    splice = context["splice"]
    rib_trace = context["rib_trace"]
    return "\n".join(
        [
            "# RFQ Daily Review",
            "",
            f"Verdict: `{context['verdict']}`",
            "",
            "The carbon tube RFQ pack remains draft/vendor-screening only. Remaining "
            "mass/span/RFQ conflicts block order placement and drawing release, not "
            "bounded WO-006 aero calibration.",
            "",
            "## What Is Draft Screening Only",
            "",
            "- Station convention: positive half-wing y from centerline/root, mirrored to both sides.",
            f"- Local/splice screening reference: `{splice['half_span_m']:.3f} m` half-span with `3.000 m` max transport panels; not procurement truth.",
            "- Draft splice station reference: `3 / 6 / 9 / 12 / 15 m` per half-wing.",
            f"- Release rib language: `0.30 m` physical rib station basis, `{rib_trace['full_wing_station_count']}` full-wing stations.",
            "",
            "## Main Warnings",
            "",
            "- y=3 m splice has zero screening bending margin; vendor fit/tolerance/knockdown data can force review.",
            "- 0.30 m rib station basis controls RFQ language; the relaxed 0.345 m stiffness label is not vendor drawing control.",
            "- Local/splice 16.5 m half-span and pipeline aero/rib extents around 17.17-17.32 m are not silently interchangeable.",
            "- Airfoil/control/twist/transport station contracts remain open drawing-control items.",
            "",
            "## Next Work Order",
            "",
            "WO-006 may proceed only as bounded aero calibration using 98.5 kg and current pipeline span authority.",
            "",
        ]
    )


def _station_manifest_rows(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    splice = context["splice"]
    discretization = context["discretization"]
    rib_trace = context["rib_trace"]
    mandatory = context["materialized"]["mandatory_rib_reason"]

    spar_joint_row = _mandatory_row(mandatory, "spar_joint")
    transport_missing = _mandatory_row(mandatory, "transport_joint")
    control_missing = _mandatory_row(mandatory, "control_station")
    airfoil_missing = _mandatory_row(mandatory, "airfoil_transition")
    twist_missing = _mandatory_row(mandatory, "twist_transition")

    rows: list[dict[str, Any]] = [
        {
            "manifest_id": "rfq_station_convention",
            "station_type": "convention",
            "rfq_y_m": "",
            "source_y_m": "",
            "side_basis": "positive_half_wing_mirrored",
            "status": "draft_vendor_screening_only",
            "source_artifact": "WO-005 controlled manifest",
            "rfq_language": "Draft only: use positive half-wing y from aircraft centerline/root; mirror to left/right.",
            "wo004_warning_carried": "prevents station convention mixing",
            "review_trigger": "Any vendor drawing with a different origin, sign, or station datum requires review.",
        },
        {
            "manifest_id": "structural_half_span_basis",
            "station_type": "span_extent",
            "rfq_y_m": f"{splice['half_span_m']:.6f}",
            "source_y_m": f"{splice['half_span_m']:.6f}",
            "side_basis": "positive_half_wing",
            "status": "local_splice_screening_not_procurement_truth",
            "source_artifact": "output/current_pathfinder_spar_splice_design/splice_design_report.json",
            "rfq_language": "Local/splice screening uses 16.5 m half-span and 3 m transport panels; not current pipeline half-span and not procurement truth.",
            "wo004_warning_carried": "span_extent_contract_mismatch",
            "review_trigger": "Any tube length/order basis that includes the outer aero/rib extension needs station-control review.",
        },
        {
            "manifest_id": "aero_half_span_reference",
            "station_type": "span_extent",
            "rfq_y_m": "reference_only",
            "source_y_m": "17.166143",
            "side_basis": "positive_half_wing",
            "status": "reference_not_rfq_tube_length_control",
            "source_artifact": "output/baseline_A_team_release/manufacturable_geometry_audit/geometry_discretization_report.csv",
            "rfq_language": "Aero production section tip is a reference extent, not the RFQ tube purchase extent.",
            "wo004_warning_carried": "span_extent_contract_mismatch",
            "review_trigger": "If vendor or shop treats this as spar tube length, update drawing control before RFQ proceeds.",
        },
        {
            "manifest_id": "materialized_rib_extent_reference",
            "station_type": "span_extent",
            "rfq_y_m": "reference_only",
            "source_y_m": "17.324041",
            "side_basis": "positive_half_wing",
            "status": "reference_not_rfq_tube_length_control",
            "source_artifact": "output/current_pathfinder_materialized_rib_contract_audit/materialized_rib_contract_audit.json",
            "rfq_language": "Materialized rib tip extent is a reference station trace, not RFQ tube length control.",
            "wo004_warning_carried": "span_extent_contract_mismatch",
            "review_trigger": "Outer 0.67-0.82 m per side must be classified before drawings or purchase release.",
        },
        {
            "manifest_id": "release_rib_spacing_basis",
            "station_type": "rib_spacing",
            "rfq_y_m": "",
            "source_y_m": f"{rib_trace['target_spacing_m']:.6f}",
            "side_basis": "full_wing_station_trace",
            "status": "draft_vendor_screening_language",
            "source_artifact": "output/current_pathfinder_materialized_rib_contract_audit/materialized_rib_contract_audit.json",
            "rfq_language": (
                f"Draft vendor-screening language uses 0.30 m physical ribs: "
                f"{rib_trace['full_wing_station_count']} stations, max bay "
                f"{rib_trace['max_materialized_bay_m']:.6f} m."
            ),
            "wo004_warning_carried": "release_vs_selected_stiffness_rib_spacing",
            "review_trigger": "Changing to relaxed stiffness spacing requires station, skin-sag, mass/CG, and local FEM review.",
        },
        {
            "manifest_id": "selected_stiffness_spacing_label",
            "station_type": "rib_spacing",
            "rfq_y_m": "not_controlled",
            "source_y_m": "0.345000",
            "side_basis": "stiffness_bookkeeping_reference",
            "status": "not_rfq_controlled_dimension",
            "source_artifact": "output/baseline_A_team_release/manufacturable_geometry_audit/geometry_discretization_report.csv",
            "rfq_language": discretization["release_vs_selected_stiffness_rib_spacing"]["observed"],
            "wo004_warning_carried": "release_vs_selected_stiffness_rib_spacing",
            "review_trigger": "If this label becomes a physical rib pitch, Baseline A station/rib/skin/coupon basis must be reviewed.",
        },
    ]

    for joint in splice["joints"]:
        nearest = _nearest_station(float(joint["y_m"]), spar_joint_row["y_m"].split(";"))
        rows.append(
            {
                "manifest_id": f"transport_splice_y{int(joint['y_m']):02d}",
                "station_type": "transport_splice",
                "rfq_y_m": f"{joint['y_m']:.6f}",
                "source_y_m": f"{joint['y_m']:.6f}",
                "side_basis": "positive_half_wing_mirrored",
                "status": "draft_vendor_screening_only",
                "source_artifact": "output/current_pathfinder_spar_splice_design/splice_design_report.json",
                "rfq_language": (
                    f"Transport splice at y={joint['y_m']:.1f} m; nearest materialized "
                    f"spar-joint rib y={nearest['station']:.6f} m, offset {nearest['delta']:.6f} m."
                ),
                "wo004_warning_carried": "splice_station_contract_mismatch",
                "review_trigger": "Do not move splice to a rib station or rib to a splice station without structural review.",
            }
        )

    rows.extend(
        [
            _missing_contract_row(transport_missing, "transport_station_contract_open"),
            _missing_contract_row(control_missing, "control_station_contract_open"),
            _missing_contract_row(airfoil_missing, "airfoil_transition_contract_open"),
            _missing_contract_row(twist_missing, "twist_transition_contract_open"),
        ]
    )
    return rows


def _tolerance_requirement_rows(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    main = context["main_tube"]
    rear = context["rear_tube"]
    splice = context["splice"]
    worst_joint = min(splice["joints"], key=lambda row: row["governing_margin"])
    spar_id_mm = float(main["inner_diameter_mm"])
    diametral_clearance_mm = 0.2
    spigot_od_mm = spar_id_mm - diametral_clearance_mm
    ferrule_od_mm = float(main["outer_diameter_mm"]) * 1.25

    return [
        _tol("main_spar_od_mm", "main_spar_tube", main["outer_diameter_mm"], "mm", "screening_reference", "Quote OD tolerance and measurement method.", "Cannot meet OD/tolerance forces spar fit and mass review."),
        _tol("main_spar_id_mm", "main_spar_tube", main["inner_diameter_mm"], "mm", "screening_reference", "Quote ID tolerance suitable for internal spigot fit.", "ID/ovality too loose forces splice fit review."),
        _tol("main_spar_wall_mm", "main_spar_tube", main["wall_thickness_mm"], "mm", "screening_reference", "Quote wall-thickness tolerance and minimum guaranteed wall.", "Lower wall or high variation forces spar margin/mass review."),
        _tol("main_spar_mass_per_m_kg", "main_spar_tube", main["mass_per_meter_kg"], "kg/m", "estimate_catalog", "Quote actual mass per meter and batch variation.", "Mass delta feeds mass/CG ledger review."),
        _tol("rear_spar_od_mm", "rear_spar_tube", rear["outer_diameter_mm"], "mm", "screening_reference", "Quote OD tolerance and measurement method.", "Cannot meet OD/tolerance forces rear-spar fit review."),
        _tol("rear_spar_id_mm", "rear_spar_tube", rear["inner_diameter_mm"], "mm", "screening_reference", "Quote ID tolerance and sleeve-fit recommendation.", "ID/ovality too loose forces rear-spar splice review."),
        _tol("rear_spar_wall_mm", "rear_spar_tube", rear["wall_thickness_mm"], "mm", "screening_reference", "Quote wall-thickness tolerance and minimum guaranteed wall.", "Lower wall or high variation forces rear-spar review."),
        _tol("rear_spar_mass_per_m_kg", "rear_spar_tube", rear["mass_per_meter_kg"], "kg/m", "estimate_catalog", "Quote actual mass per meter and batch variation.", "Mass delta feeds mass/CG ledger review."),
        _tol("max_shipping_segment_m", "logistics", splice["panel_length_m"], "m", "controlled_for_rfq_screening", "Confirm 3 m shipped/cut segment compatibility.", "If 3 m cannot be shipped, procurement and transport concept need review."),
        _tol("main_segment_quantity_basis", "quantity", 12, "segments", "screening_quantity_basis", "Quote 12 full-wing main-spar segments plus optional spare allowance separately.", "Different quantity basis requires station/length review."),
        _tol("rear_segment_quantity_basis", "quantity", 12, "segments", "screening_quantity_basis", "Quote 12 full-wing rear-spar segments plus optional spare allowance separately.", "Different quantity basis requires station/length review."),
        _tol("main_spigot_od_fit_mm", "splice_fit", f"{spigot_od_mm:.1f}", "mm", "screening_fit_assumption", "Confirm recommended spigot OD for 0.2 mm diametral clearance, or propose a tested alternative.", "Fit change affects y=3 m zero-margin splice review."),
        _tol("diametral_clearance_mm", "splice_fit", f"{diametral_clearance_mm:.1f}", "mm", "screening_fit_assumption", "Confirm bonded/slip-fit clearance for CFRP tube-in-tube joint.", "Clearance change affects sleeve fit, ovality, and bondline review."),
        _tol("spigot_wall_y3_mm", "splice_spigot", f"{worst_joint['spigot_wall_mm']:.2f}", "mm", "critical_screening_warning", "Confirm available wall and knockdowns for y=3 m inboard splice.", "Any knockdown can make the zero-margin splice negative."),
        _tol("spigot_wall_outboard_mm", "splice_spigot", "0.80", "mm", "screening_reference", "Confirm stock/custom spigot wall for outboard joints.", "If unavailable, mass and fit review required."),
        _tol("spigot_overlap_each_side_mm", "splice_spigot", f"{worst_joint['spigot_overlap_mm']:.1f}", "mm", "screening_reference", "Confirm 4D overlap each side is practical for bonding/inspection.", "Overlap reduction forces splice redesign review."),
        _tol("main_ferrule_od_mm", "ferrule_shear_dog", f"{ferrule_od_mm:.1f}", "mm", "screening_reference", "Confirm ferrule ring manufacturability at 1.25 x main spar OD.", "Ferrule geometry change affects torsion/shear-dog review."),
        _tol("ferrule_width_mm", "ferrule_shear_dog", "25.0", "mm", "screening_reference", "Confirm ferrule width, edge prep, and bond process.", "Width change affects torsion and local bearing review."),
        _tol("ferrule_wall_mm", "ferrule_shear_dog", "1.5", "mm", "screening_reference", "Confirm ferrule wall and local crush/bearing allowables.", "Wall change affects mass and torsion review."),
        _tol("straightness_tolerance", "dimensional_qa", "vendor_response_required", "mm_per_m", "open_vendor_response", "State straightness tolerance over each 3 m segment.", "Poor straightness affects alignment, sleeve fit, and wing jigging."),
        _tol("ovality_tolerance", "dimensional_qa", "vendor_response_required", "mm_or_percent", "open_vendor_response", "State ovality tolerance before and after finish.", "Poor ovality directly affects y=3 m sleeve margin."),
        _tol("surface_finish_bond_prep", "bond_prep", "vendor_response_required", "process", "open_vendor_response", "State supplied surface finish and structural bond-prep compatibility.", "Incompatible surface prep affects ferrules, spigots, and C04 saddle rings."),
        _tol("qa_coupon_certificate", "qa", "vendor_response_required", "artifact", "open_vendor_response", "Provide certificate, batch traceability, and same-batch coupon/cutoff options.", "No traceability/coupons limits procurement confidence."),
        _tol("lead_time_moq", "commercial", "vendor_response_required", "weeks_and_quantity", "open_vendor_response", "State MOQ, lead time, custom mandrel cost, and replacement policy.", "Commercial infeasibility may trigger procurement review."),
    ]


def _risk_register(context: Mapping[str, Any]) -> dict[str, Any]:
    splice = context["splice"]
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": VERDICT,
        "authority_status": context["authority_status"],
        "wo006_impact": context["wo006_impact"],
        "claim_boundary": context["claim_boundary"],
        "source_artifacts": context["sources"],
        "risk_register": [
            {
                "risk_id": "tube_family_unavailable",
                "severity": "review_required",
                "affected_review": ["spar_spec", "procurement", "baseline_A_reopen_watch"],
                "trigger": "Vendor cannot meet 100/98 main or 80/78 rear HM CFRP tube family with credible tolerance and layup data.",
                "engineering_read": "Tube family evidence is a screening assumption. A real supplier miss can invalidate spar stiffness, mass, splice fit, and procurement schedule.",
            },
            {
                "risk_id": "y3_splice_zero_margin_consumed",
                "severity": "high",
                "affected_review": ["spar_splice_detail", "coupon_local_test", "spar_spec"],
                "trigger": f"Any vendor knockdown, ovality, fit tolerance, or wall variation makes y={splice['worst_joint_y_m']:.1f} m splice margin negative.",
                "engineering_read": "The inboard splice only has zero screening bending margin after auto-sizing. This is the highest-priority vendor/detail question.",
            },
            {
                "risk_id": "sleeve_fit_tolerance_unknown",
                "severity": "review_required",
                "affected_review": ["splice_fit", "local_fem", "coupon_plan"],
                "trigger": "Vendor cannot state ID/OD/ovality/straightness tolerance or recommended diametral clearance for CFRP spigots.",
                "engineering_read": "Fit ambiguity can create contact peaks, bondline gaps, ovalization, and unmodeled local bearing.",
            },
            {
                "risk_id": "layup_or_modulus_change",
                "severity": "review_required",
                "affected_review": ["spar_spec", "mass_cg", "aeroelastic_closure"],
                "trigger": "Vendor proposes a layup, fiber modulus class, hoop fraction, or resin system materially different from the HM screening family.",
                "engineering_read": "Changing laminate can move EI/GJ, local buckling, torsion, mass, and managed CG.",
            },
            {
                "risk_id": "three_meter_logistics_fail",
                "severity": "procurement_review",
                "affected_review": ["transport", "procurement", "station_manifest"],
                "trigger": "Vendor cannot ship/protect/inspect 3 m segments or requires a different maximum length.",
                "engineering_read": "The splice design and release segmentation are built around the 3 m transport constraint.",
            },
            {
                "risk_id": "surface_prep_incompatible",
                "severity": "review_required",
                "affected_review": ["C04_coupon", "ferrule_spigot_bond", "manufacturing_test"],
                "trigger": "Vendor finish or coating is incompatible with structural bonding, ferrules, saddle rings, or spigots.",
                "engineering_read": "C04 and splice concepts depend on bond and contact repeatability, not only tube strength.",
            },
            {
                "risk_id": "station_convention_mixed",
                "severity": "dangerous_assumption",
                "affected_review": ["station_manifest", "drawing_control", "procurement"],
                "trigger": "Vendor or shop drawing mixes 3 m transport splice stations with materialized spar-joint rib stations or aero/rib tip extents.",
                "engineering_read": "This can put sleeves, hard ribs, or cut lengths in the wrong place without changing any software test.",
            },
            {
                "risk_id": "qa_traceability_missing",
                "severity": "procurement_review",
                "affected_review": ["coupon_plan", "supplier_screening", "procurement"],
                "trigger": "Vendor cannot provide certificates, batch traceability, dimensional report, same-batch coupons, or replacement policy.",
                "engineering_read": "No traceability means vendor data cannot close the current coupon/local FEM readiness boundary.",
            },
        ],
        "baseline_A_reopen_watch": [
            "Vendor evidence invalidates current main/rear spar OD, wall, tolerance, or splice-fit assumptions.",
            "Vendor mass or layup changes make managed CG 0.75 m or aeroelastic closure infeasible.",
            "y=3 m splice cannot be recovered by detail design, coupon, or local FEM without changing spar architecture.",
        ],
    }


def _tube_table_row(role: str, tube: Mapping[str, str], quantity: str, status: str) -> str:
    basis = (
        f"{tube['outer_diameter_mm']} mm OD / {tube['inner_diameter_mm']} mm ID / "
        f"{tube['wall_thickness_mm']} mm wall / {tube['mass_per_meter_kg']} kg/m"
    )
    return f"| {role} | {basis} | {quantity} | {status} |"


def _mandatory_row(rows: Iterable[Mapping[str, str]], contract_item: str) -> Mapping[str, str]:
    for row in rows:
        if row["contract_item"] == contract_item:
            return row
    raise KeyError(f"missing mandatory row {contract_item}")


def _missing_contract_row(row: Mapping[str, str], manifest_id: str) -> dict[str, Any]:
    return {
        "manifest_id": manifest_id,
        "station_type": row["contract_item"],
        "rfq_y_m": "open",
        "source_y_m": "",
        "side_basis": "not_controlled",
        "status": "missing_contract_not_drawing_control",
        "source_artifact": "output/current_pathfinder_materialized_rib_contract_audit/mandatory_rib_reason.csv",
        "rfq_language": row["engineering_read"],
        "wo004_warning_carried": "airfoil_control_transition_contracts_missing",
        "review_trigger": "Define station contract before shop drawings or physical station-dependent procurement.",
    }


def _nearest_station(target_y: float, station_tokens: Iterable[str]) -> dict[str, float]:
    stations = [abs(float(token)) for token in station_tokens if token]
    station = min(stations, key=lambda value: abs(value - target_y))
    return {"station": station, "delta": abs(station - target_y)}


def _tol(
    requirement_id: str,
    scope: str,
    nominal_value: Any,
    unit: str,
    evidence_status: str,
    rfq_requirement: str,
    review_trigger: str,
) -> dict[str, Any]:
    return {
        "requirement_id": requirement_id,
        "scope": scope,
        "nominal_value": nominal_value,
        "unit": unit,
        "evidence_status": evidence_status,
        "rfq_requirement": rfq_requirement,
        "review_trigger": review_trigger,
    }


def _tube_catalog_row(rows: Iterable[Mapping[str, str]], product: str) -> Mapping[str, str]:
    for row in rows:
        if row["product"] == product:
            return row
    raise KeyError(f"missing carbon tube product {product}")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError(f"Expected JSON object at {path}")
    return data


def _read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _mapping_at(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data[key]
    if not isinstance(value, Mapping):
        raise TypeError(f"Expected mapping at {key}")
    return value


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows for {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0].keys()),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for RFQ pack artifacts.",
    )
    args = parser.parse_args()
    paths = write_carbon_tube_rfq_pack(output_dir=args.output_dir)
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
