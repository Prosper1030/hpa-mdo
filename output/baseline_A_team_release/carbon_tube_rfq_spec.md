# Carbon Tube RFQ Spec

Verdict: `carbon_tube_rfq_pack_draft_vendor_screening`

This is a draft vendor-screening RFQ spec under data-authority repair. It is not purchase-ready, not final supplier selection, not production drawing control, and not final aircraft sign-off.

## Pack Files

- `carbon_tube_rfq_pack.md`: readable RFQ package and engineering boundary.
- `controlled_station_span_splice_manifest.csv`: one RFQ station/span convention.
- `vendor_questionnaire.md`: supplier response questions.
- `procurement_risk_register.json`: review and reopen triggers.
- `tube_splice_tolerance_requirements.csv`: tube/splice/tolerance request table.
- `rfq_daily_review.md`: one-page review summary.

## Draft Vendor-Screening Convention

- Use positive half-wing `y` from aircraft centerline/root for draft vendor-screening language; mirror to both sides.
- Local/splice screening reference: `16.500 m` half-span, not current pipeline half-span and not procurement truth; `3.000 m` remains a transport-panel screening constraint.
- Draft splice station reference: y = `3 / 6 / 9 / 12 / 15 m` on each half-wing.
- Materialized rib basis for release language: `0.30 m` target with `121` full-wing stations and max bay `0.297063 m`.
- Current pipeline span evidence is `34.332286 m` full span / `17.166143 m` half-span unless replaced by newer authority.

## Requested Tube Families

- Main spar screening reference: 100.0 mm OD / 98.0 mm ID HM CFRP tube family, 1.0 mm wall.
- Rear spar screening reference: 80.0 mm OD / 78.0 mm ID HM CFRP tube family, 1.0 mm wall.
- Splice spigot family: internal CFRP spigot, 4D overlap each side, ferrule/shear-dog concept.
- Inboard y=3 m splice warning: 1.02 mm screening spigot wall with zero bending margin.

## WO-004 Warning Resolved For RFQ Language

- Keep draft vendor questions tied to the 0.30 m physical rib station trace. The relaxed stiffness row remains a non-RFQ bookkeeping/reference issue: Release freeze says 0.30 m, but selected stiffness basis closure_rerun_eps_balsa_cap_hybrid_10mm__t10p0mm__manufacturing_relaxed_0p36__carbon_face_collar_y2p328__rear75_fast_design_loop_v1 records target spacing 0.345 m and materialized max subbay 0.345 m.
- Do not mix 3 m transport splice stations with materialized spar-joint rib stations.
- Do not treat continuous smooth geometry dimensions as shop-grid dimensions.
- Do not treat airfoil/control/transition/transport station contracts as final drawing control.

## Change-Control Boundary

Vendor answers that move spar OD/wall, laminate/modulus, tube mass, CG, splice fit, sleeve/ferrule assumptions, coupon allowables, or 3 m transport feasibility must return through Baseline A change control.
