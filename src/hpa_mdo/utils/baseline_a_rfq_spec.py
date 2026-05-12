"""Shared Baseline A carbon tube RFQ front-door spec renderer."""

from __future__ import annotations


def render_carbon_tube_rfq_spec(
    *,
    verdict: str,
    half_span_m: float,
    panel_length_m: float,
    rib_target_spacing_m: float,
    full_wing_station_count: int,
    max_materialized_bay_m: float,
    current_pipeline_full_span_m: float,
    current_pipeline_half_span_m: float,
    main_outer_diameter_mm: float,
    main_inner_diameter_mm: float,
    main_wall_thickness_mm: float,
    rear_outer_diameter_mm: float,
    rear_inner_diameter_mm: float,
    rear_wall_thickness_mm: float,
    stiffness_warning_text: str,
) -> str:
    """Render the single-source RFQ front-door spec used by both generators."""
    return "\n".join(
        [
            "# Carbon Tube RFQ Spec",
            "",
            f"Verdict: `{verdict}`",
            "",
            "This is a draft vendor-screening RFQ spec under data-authority repair. "
            "It is not purchase-ready, not final supplier selection, not production "
            "drawing control, and not final aircraft sign-off.",
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
            "- Use positive half-wing `y` from aircraft centerline/root for draft "
            "vendor-screening language; mirror to both sides.",
            f"- Local/splice screening reference: `{half_span_m:.3f} m` half-span, "
            f"not current pipeline half-span and not procurement truth; "
            f"`{panel_length_m:.3f} m` remains a transport-panel screening constraint.",
            "- Draft splice station reference: y = `3 / 6 / 9 / 12 / 15 m` "
            "on each half-wing.",
            f"- Materialized rib basis for release language: `{rib_target_spacing_m:.2f} m` "
            f"target with `{full_wing_station_count}` full-wing stations and max bay "
            f"`{max_materialized_bay_m:.6f} m`.",
            "- Current pipeline span evidence is "
            f"`{current_pipeline_full_span_m:.6f} m` full span / "
            f"`{current_pipeline_half_span_m:.6f} m` half-span unless replaced by "
            "newer authority.",
            "",
            "## Requested Tube Families",
            "",
            f"- Main spar screening reference: {main_outer_diameter_mm} mm OD / "
            f"{main_inner_diameter_mm} mm ID HM CFRP tube family, "
            f"{main_wall_thickness_mm} mm wall.",
            f"- Rear spar screening reference: {rear_outer_diameter_mm} mm OD / "
            f"{rear_inner_diameter_mm} mm ID HM CFRP tube family, "
            f"{rear_wall_thickness_mm} mm wall.",
            "- Splice spigot family: internal CFRP spigot, 4D overlap each side, "
            "ferrule/shear-dog concept.",
            "- Inboard y=3 m splice warning: 1.02 mm screening spigot wall with "
            "zero bending margin.",
            "",
            "## WO-004 Warning Resolved For RFQ Language",
            "",
            "- Keep draft vendor questions tied to the 0.30 m physical rib station trace. "
            "The relaxed stiffness row remains a non-RFQ bookkeeping/reference issue: "
            f"{stiffness_warning_text}",
            "- Do not mix 3 m transport splice stations with materialized spar-joint "
            "rib stations.",
            "- Do not treat continuous smooth geometry dimensions as shop-grid dimensions.",
            "- Do not treat airfoil/control/transition/transport station contracts as final "
            "drawing control.",
            "",
            "## Change-Control Boundary",
            "",
            "Vendor answers that move spar OD/wall, laminate/modulus, tube mass, CG, "
            "splice fit, sleeve/ferrule assumptions, coupon allowables, or 3 m "
            "transport feasibility must return through Baseline A change control.",
            "",
        ]
    )
