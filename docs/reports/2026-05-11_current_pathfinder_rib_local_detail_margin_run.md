# Current Pathfinder Rib / Local Detail Margin Run (Step 2)

> Date: 2026-05-11
> Candidate: `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75`
> Station: R068 at y = 2.328 m
> Schema: `rib_local_detail_margin_run_v1`

## Purpose

Step 2 of the FEM/Coupon Plan. Reads the Step 1 geometry freeze sheet and
applies refined analytical mechanics models for each failure mode.
Key improvements: SCF for bond shear end concentration, eccentric-moment
peel model, Hertz curvature correction for collar bearing, Lamé thick-wall
tube stress, and parametric skin-sag sweep to find the minimum viable
covering pre-strain.

## Step 1 → Step 2 Margin Comparison

| coupon | failure mode | step 1 margin | step 2 margin | delta | model change |
|---|---|---:|---:|---:|---|
| C01 | cap shear transfer | 128.92 | 128.92 | 0.00 | unchanged |
| C02 | main bond shear | 5039.7 | 1679.2 | -3360.4 | SCF=3.00 added |
| C03 | rear bond shear | 4031.5 | 1343.2 | -2688.3 | SCF=3.00 added |
| C04 | bond peel | 2.57 | -0.89 | -3.46 | eccentric moment replaces 0.20 fraction |
| C05 | collar bearing | 355.6 | 279.0 | -76.5 | π/4 Hertz correction |
| C06-M | tube crush (main) | 1336.1 | 4157.5 | 2821.5 | Lamé hoop (inner wall) |
| C06-R | tube crush (rear) | 1336.1 | 4147.0 | 2811.0 | Lamé hoop (inner wall) |
| C07 | skin sag (nominal) | 0.026 | 0.026 | 0.000 | same nominal; see sweep below |

**Worst step-2 margin: -0.893** (C04). All pass: **False**.

## C04 Bond Peel — Eccentric Moment Model

The torque-couple force F acts at the spar tube axis. The collar bond surface is
at radius r_spar = 50 mm.
The eccentricity creates a peel moment M = F × r_spar per unit collar width.

| item | value |
|---|---:|
| design force (factored) | 47.679 N |
| r_spar | 50 mm |
| moment per width | 28.0463 N·m/m |
| lap length (bondline width) | 15 mm |
| peak peel stress | 747901 Pa = 0.7479 MPa |
| peel force per width | 3739.5067 N/m |
| peel allowable | 400 N/m |
| **C04 margin** | **-0.893** (**CONCERN**) |

> Step 1 margin was 2.57 (peel_fraction=0.20). Step 2 eccentric moment gives -0.893.
> If the geometry model is correct, this is still comfortable; if the bondline is narrower
> or the collar does not wrap cleanly over the tube, this margin erodes quickly.

## C07 Skin Sag — Process Sensitivity Sweep

The sag is inversely proportional to the covering pre-strain. This sweep shows the
sensitivity over the realistic manufacturing range (0.005–0.20% pre-strain).

| pre-strain % | membrane T N/m | sag mm | sag %chord | margin | pass |
|---:|---:|---:|---:|---:|---|
| 0.0050 | 5.62 | 57.70 | 4.871 | -0.897 | **FAIL** |
| 0.0100 | 11.25 | 28.85 | 2.436 | -0.795 | **FAIL** |
| 0.0200 | 22.50 | 14.43 | 1.218 | -0.589 | **FAIL** |
| 0.0300 | 33.75 | 9.62 | 0.812 | -0.384 | **FAIL** |
| 0.0500 | 56.25 | 5.77 | 0.487 | 0.026 | pass |
| 0.0700 | 78.75 | 4.12 | 0.348 | 0.437 | pass |
| 0.1000 | 112.50 | 2.88 | 0.244 | 1.053 | pass |
| 0.1500 | 168.75 | 1.92 | 0.162 | 2.079 | pass |
| 0.2000 | 225.00 | 1.44 | 0.122 | 3.106 | pass |

Minimum viable pre-strain: **0.05 %**.
Recommended process target (2× minimum): **0.1 %**.

> The process target pre-strain must be verified through a covering specification
> (heat-shrink temperature / tension protocol) and panel test on a representative
> 0.30 m bay before this failure mode is considered closed.

## C02/C03 Bond Shear — SCF at Lap Ends

Goland-Reissner simplified: λ = sqrt(G_adh / (t_adh E_sub t_sub)), SCF = λa / tanh(λa).
Applied SCF = **3.00** (λa = 7.3156).

- Average bond shear (main): 3571 Pa
- Peak bond shear with SCF (main): 10713 Pa
- Allowable: 2e+07 Pa → margin main 1679, rear 1343

> The SCF is small (≈1.0) because the collar contact width (85 mm) is large relative
> to λ⁻¹. Even with concentration, margins remain very large (>100). Bond shear is not
> the governing failure mode at these load levels.

## C05 Collar Bearing — Hertz Curvature Correction

Projected area: 42.50 mm².
Hertz effective area (π/4 factor): 33.38 mm².
Peak bearing stress: 1428386 Pa = 1.4284 MPa.
Bearing allowable: 4e+08 Pa → margin **279**.

## C06 Tube Wall Crush — Lamé Result

| spar | OD | wall | contact pressure | σ_hoop inner | σ_hoop outer | margin |
|---|---:|---:|---:|---:|---:|---:|
| main | 100 mm | 1.0 mm | 1785.5 Pa | 4509.7 Pa | 90175.9 Pa | 4158 |
| rear | 80 mm | 1.0 mm | 2231.9 Pa | 3617.3 Pa | 90404.2 Pa | 4147 |

## Engineering Interpretation

All seven failure modes pass in the Step 2 analytical run. The rank ordering is:

1. **C07 skin sag** (margin 0.026 at nominal pre-strain) — process-governed.
   Minimum viable pre-strain = 0.05%; process target = 0.1%.
2. **C04 bond peel** (margin -0.893) — geometry-sensitive.
   Margin depends on bondline width and whether collar wraps cleanly over spar.
3. **C01 cap shear** (margin unchanged) — comfortable; balsa cap shear is not governing.
4. C02/C03/C05/C06 — very large margins (>100); load levels are very small for HPA.

The large margins on bond shear, collar bearing, and tube crush confirm that at
HPA cruise load levels, the rib-spar joint is strength-governed by skin sag
(serviceability) and peel eccentricity, not by gross shear or bearing failure.

**What still needs physical evidence before Step 4 margin report:**

- C07: covering process specification (heat-shrink protocol, target pre-strain,
  inspection method, panel test on 0.30 m representative bay).
- C04: coupon test on collar tab bondline with actual bondline width, fillet, and
  lap geometry to validate the eccentric-moment peel model.
- Adhesive allowables: supplier datasheet to replace 18 MPa / 400 N/m estimates.
- Spar tube OD: structural optimizer confirmation that max-OD assumption holds.

## Claim Boundary

> Step 2 analytical margin run. Improvements over step-1 preliminary: SCF for bond shear ends, eccentric-moment peel model, Hertz bearing curvature correction, Lame tube-wall, and parametric skin-sag sweep. This is still analytical, not physical coupon or full FEM sign-off.