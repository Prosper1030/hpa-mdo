# Current Pathfinder Rib Collar Joint — Design Search (C04 Fix)

> Date: 2026-05-11
> Candidate: `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75`
> Station: R068 at y = 2.328 m
> Schema: `rib_collar_joint_design_search_v1`

## Problem Statement

The Step 2 analytical margin run showed that the current peel-bond collar design
(15 mm bondline, peel allowable 400 N/m) fails
with margin -0.893 (conservative) and -0.786
(theoretical minimum — geometry-only lower bound, independent of stress distribution).
Even under the best possible stress distribution, the bondline needs ≥ 70 mm.

**Root cause**: the rib couple force F acts at the spar tube axis. The collar
bond surface is at radius r = 50 mm. This eccentricity creates
a peel moment M = F×r = 47.68×50 mm
= 2.384 N·m that the 15 mm bondline cannot resist in peel.

## Load Inputs (from Step 1 freeze sheet)

| parameter | value |
|---|---:|
| Factored couple force F | 47.679 N |
| Spar OD radius R | 50 mm |
| Collar contact width L | 85 mm |
| Required anti-rotation torque M_req | 2.3839 N·m |
| Moment per unit collar width m | 28.046 N |

## Mode 1: Peel Bond (current design — sweep bondline width)

Minimum viable bondline (linear model): **110.0 mm**.
Recommended (1.5×): **165.0 mm**, margin 0.57.
Current bondline is 15 mm. Widening to 105 mm requires a major geometry change
and still leaves the bondline working in its weakest mode (peel).

| bondline mm | peel demand N/m | margin | pass |
|---:|---:|---:|---|
| 5 | 8414 | -0.95 | ✗ |
| 25 | 1683 | -0.76 | ✗ |
| 45 | 935 | -0.57 | ✗ |
| 65 | 647 | -0.38 | ✗ |
| 85 | 495 | -0.19 | ✗ |
| 105 | 401 | -0.00 | ✗ |
| 125 | 337 | 0.19 | ✓ |
| 145 | 290 | 0.38 | ✓ |
| 165 | 255 | 0.57 | ✓ |
| 185 | 227 | 0.76 | ✓ |

## Mode 2: Load-Line Yoke (reduce eccentricity)

Route the rib reaction force through a clevis/yoke so it acts close to the
tube centreline. Reducing r_eff from 50 mm to a small value eliminates most
of the peel moment while keeping the bondline in the joint.

Maximum viable r_eff (linear model, a=15 mm): **1.0 mm**.
Recommended r_eff (0.67× max): **0.7 mm**,
margin 9.64.

| r_eff mm | m_eff N | peel demand N/m | margin | pass |
|---:|---:|---:|---:|---|
| 1 | 0.561 | 56 | 6.13 | ✓ |
| 6 | 3.366 | 337 | 0.19 | ✓ |
| 11 | 6.170 | 617 | -0.35 | ✗ |
| 16 | 8.975 | 897 | -0.55 | ✗ |
| 21 | 11.779 | 1178 | -0.66 | ✗ |
| 26 | 14.584 | 1458 | -0.73 | ✗ |
| 31 | 17.389 | 1739 | -0.77 | ✗ |
| 36 | 20.193 | 2019 | -0.80 | ✗ |
| 41 | 22.998 | 2300 | -0.83 | ✗ |
| 46 | 25.803 | 2580 | -0.84 | ✗ |
| 51 | 28.607 | 2861 | -0.86 | ✗ |

## Mode 3: Friction Clamp (split clamp collar)

A split clamp (two half-shells with through-bolts) grips the spar OD.
Clamp force N_c generates friction torque M = μ × N_c × R.
Contact pressure on CFRP tube is checked separately.

| μ | Min N_c [N] | Recommended N_c [N] | Margin at rec. |
|---:|---:|---:|---:|
| 0.10 | 500 | 1000.0 | 1.097 |
| 0.15 | 400 | 800.0 | 1.517 |
| 0.20 | 300 | 600.0 | 1.517 |
| 0.25 | 200 | 400.0 | 1.097 |

> Contact pressure at N_c=600 N over half-circumference contact:
> p = 600 / (π × 50mm × 85mm)
> = 44938 Pa — very low, not governing.

## Mode 4: External Shear Key

Two bonded anti-rotation blocks on the spar OD transmit the rib torque via
**adhesive shear** (not peel). Design shear allowable: τ_d = 2 MPa
(conservative knockdown from ~18 MPa to account for peel concentration at key ends;
key edges must be tapered or wrapped with carbon tow).

Minimum viable total bonded area: **50 mm²**.
Recommended (2× minimum): **100.0 mm²**
= **50 mm²** per key (2 keys),
margin **3.6**.

Example: each key = 10 mm × 15 mm = 150 mm², two keys = 300 mm².

## Recommended Design

**split clamp + 3 mm yoke + two 10×15 mm external shear keys**

| load path | governing margin | primary |
|---|---:|---|
| Residual peel (yoke r_eff=3 mm, conservative) | 0.78 | ✓ |
| Friction clamp (μ=0.15, N_c=600 N) | 0.89 | check |
| External shear key (2×150 mm², τ_d=2 MPa) | 12.8 | backup |

**Governing margin: 0.78** (each path checked independently).

Notes:
- Each load path is checked independently (conservative; no load sharing assumed)
- Governing margin is the minimum across all three paths
- mu=0.15 is conservative for CFRP-on-CFRP with surface finish; measure on coupon
- tau_d=2 MPa includes knockdown for peel concentration at key ends; taper key edges
- Yoke r_eff=3 mm requires clevis/saddle bracket with bore close to tube OD

## Design Search Summary

| mode | minimum viable geometry | current geometry | verdict |
|---|---|---|---|
| peel bond | 110.0 mm bondline | 15 mm | ✗ needs 7× increase |
| yoke | r_eff ≤ 1.0 mm | r=50 mm | ✓ achievable with clevis/saddle |
| friction clamp (μ=0.15) | N_c ≥ 400 N | none | ✓ achievable with M3–M4 bolts |
| external shear key | ≥ 50 mm² total | none | ✓ two small blocks suffice |

## What Needs Physical Verification

1. **μ coupon**: friction coefficient for CFRP-on-CFRP (or on liner material)
   with realistic clamp pressure and surface finish — do not assume μ=0.15 without test.
2. **Shear key bond coupon**: verify τ_d ≥ 2 MPa for the actual key geometry with
   tapered edges. Check that key-end peel does not drive failure before shear.
3. **Yoke geometry**: confirm that a clevis/saddle bracket can be manufactured
   with the rib web such that the effective force line passes within 3 mm of the
   tube centreline under assembly tolerances.
4. **Clamp repeatability**: verify that bolt preload after repeated assembly /
   disassembly maintains the required N_c (use torque wrench, calibrated fastener).