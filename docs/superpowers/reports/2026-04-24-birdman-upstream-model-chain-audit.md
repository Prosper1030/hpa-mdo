# Birdman Upstream Model Chain Audit

Date: 2026-04-24
Workspace: `/Volumes/Samsung SSD/hpa-mdo`

## Purpose

This report lists the current upstream Birdman concept-design chain from input
box to ranking, including the mathematical models, parameter ranges, gate
contracts, and current engineering risk points. It is meant to help decide
whether the design chain is fundamentally steering the aircraft toward the wrong
type of concept.

This is an audit only. It does not change configs, optimizer behavior, airfoil
family, tail model, mission objective, or quasi-3D/AVL coupling.

## Current Bottleneck Signal

The latest evidence is:

- Baseline top infeasible:
  `S = 34.83 m^2`, `W/S = 29.56 N/m^2`, `AR = 33.03`;
  fails launch, turn, local stall, and mission.
- `box_A` top:
  `S = 42.24 m^2`, `W/S = 24.38 N/m^2`, `AR = 29.77`;
  clears launch/turn, fails local stall and mission.
- promoted `box_B` top:
  `S = 48.60 m^2`, `W/S = 21.19 N/m^2`, `AR = 24.43`;
  almost exactly reaches the 6 m/s local-stall limit, but still misses mission
  range by about `23.77 km` at the 105 kg case.

Immediate engineering diagnosis:

- the search has reached the 6 m/s low-speed stall frontier;
- mission/endurance/power/mass sensitivity is now the next wall;
- the promoted `box_B` geometry looks more like a slow, large-area artifact than
  a high-efficiency Birdman / Light Eagle class concept.

## End-To-End Chain

1. Load YAML config into `BirdmanConceptConfig`.
2. Compute air density from temperature, humidity, and altitude.
3. Sample primary geometry variables:
   `span_m`, `wing_loading_target_Npm2`, `taper_ratio`, `tip_twist_deg`.
4. Randomly pair each primary sample with secondary discrete variables:
   tail area, root/tip dihedral, and dihedral exponent.
5. Derive wing area from design gross weight and wing loading:
   `S = W_design / (W/S)`.
6. Derive trapezoidal root/tip chords from `S`, span, and taper.
7. Reject geometry if hard constraints fail.
8. Build straight, linearly tapered/twisted/dihedral wing stations.
9. Run AVL-backed spanwise loader when available; otherwise use fallback coarse
   spanwise load model.
10. Split span into four zones: root, mid1, mid2, tip.
11. Select bounded CST airfoil candidate per zone using XFOIL worker metrics.
12. Re-evaluate selected airfoils at screening/finalist fidelity.
13. Apply safe local `CLmax` model to every station point.
14. Evaluate trim, launch, turn, mission, and local stall gates.
15. Build a ranking input from gate booleans, safety margin, mission score, and
   assembly penalty.
16. Rank concepts feasibility-first.
17. Export selected and best-infeasible concept records plus frontier summaries.

Important coupling:

- The 6 m/s slow case enters the chain before final ranking through the AVL
  design cases and again through the mission speed feasibility filter.
- `S = W/(W/S)` couples low wing loading directly to large area.
- Current gross mass does not increase when area increases.
- Airfoil selection, local stall, and mission feasible-speed filtering all
  reward surviving the low-speed stall gate.

## Config Parameter Ranges

Common environment:

| parameter | value |
| --- | ---: |
| temperature_c | 33.0 |
| relative_humidity | 80.0 |
| altitude_m | 0.0 |

Air density model:

`rho = p_dry/(R_dry T) + p_vapor/(R_vapor T)`, where pressure comes from a
tropospheric approximation and vapor pressure from a saturation-vapor formula.
The current runs use about `rho = 1.1357 kg/m^3`.

Common mass:

| parameter | value |
| --- | ---: |
| pilot_mass_kg | 60.0 |
| baseline_aircraft_mass_kg | 40.0 |
| gross_mass_sweep_kg | 95.0, 100.0, 105.0 |
| design_gross_mass_kg | 105.0 |

Mass model risk:

- `baseline_aircraft_mass_kg` is an input assumption, not a structural sizing
  result.
- `design_gross_mass_kg` is fixed while area changes.
- there is no wing structural mass feedback from span, area, AR, root chord,
  spar depth, material, or deflection.

Mission and rider:

| parameter | value |
| --- | ---: |
| objective_mode | max_range |
| target_distance_km | 42.195 |
| configured rider_model | fake_anchor_curve |
| active rider curve | `data/pilot_power_curves/current_pilot_power_curve.csv` |
| speed_sweep_min_mps | 6.0 |
| speed_sweep_max_mps | 10.0 |
| speed_sweep_points | 9 |

Because `rider_power_curve_csv` is provided, the active model is the CSV power
curve, not the fake anchor curve. Current CSV anchors:

| value | number |
| --- | ---: |
| max_power_w | 645.0 |
| min_power_w | 185.0 |
| power at 30 min | 254.0 W |
| duration at 210 W | 121.7 min |
| duration at 220 W | 82.0 min |
| duration at 230 W | 52.0 min |
| duration at 240 W | 36.5 min |

This is why small power changes near `210..240 W` create huge mission-range
changes. At 6 m/s, the 42.195 km target requires about `117.2 min`, so the
aircraft must be close to `~211 W` or less to pass.

Launch:

| parameter | value |
| --- | ---: |
| mode | restrained_pre_spin |
| release_speed_mps | 8.0 |
| release_rpm | 140.0 |
| min_trim_margin_deg | 2.0 |
| platform_height_m | 10.0 |
| runup_length_m | 10.0 |
| use_ground_effect | true |

Launch model risk:

- primary launch gate currently does not apply ground effect;
- ground effect is reported only as sensitivity;
- launch acceleration, prop spin-up, platform kinematics, and run-up energy are
  not modeled.

Stall model:

| parameter | value |
| --- | ---: |
| safe_clmax_scale | 0.90 |
| safe_clmax_delta | 0.05 |
| tip_3d_penalty_start_eta | 0.55 |
| tip_3d_penalty_max | 0.04 |
| tip_taper_penalty_weight | 0.35 |
| washout_relief_deg | 2.0 |
| washout_relief_max | 0.02 |
| local_stall_utilization_limit | 0.80 |
| turn_utilization_limit | 0.85 |
| launch_utilization_limit | 0.75 |

Propulsion:

| parameter | value |
| --- | ---: |
| blade_count | 2 |
| diameter_m | 3.0 |
| rpm_min | 100.0 |
| rpm_max | 160.0 |
| position_mode | between_wing_and_tail |
| internal design_efficiency | 0.83 |

Prop efficiency model:

`eta = 0.83 * max(0.70, 1 - 0.015 |V - 8.5|) * max(0.75, 1 - 0.0004 |Pshaft - 280|)`,
clamped to `[0.50, 0.90]`.

Turn:

| parameter | value |
| --- | ---: |
| required_bank_angle_deg | 15.0 |
| load factor | `1/cos(15 deg) = 1.0353` |

Tail / trim:

| parameter | value |
| --- | ---: |
| wing_ac_xc | 0.25 |
| cg_xc | 0.30 fixed in geometry |
| tail_arm_to_mac | 4.0 |
| tail_dynamic_pressure_ratio | 0.90 |
| tail_efficiency | 0.90 |
| tail_cl_limit_abs | 0.80 |
| tail_aspect_ratio | 5.0 |
| tail_oswald_efficiency | 0.85 |
| body_cm_offset | 0.0 |
| cm_spread_factor | 0.50 |

Geometry ranges:

| box | sample_count | span_m | W/S_Npm2 | taper_ratio | tip_twist_deg | wing_area_m2 hard range | AR hard range |
| --- | ---: | --- | --- | --- | --- | --- | --- |
| baseline | 48 | 30..36 | 26..34 | 0.24..0.40 | -3.0..-0.5 | 28..42 | 24..36 |
| box_A | 64 | 30..36 | 22..34 | 0.24..0.40 | -3.0..-0.5 | 28..48 | 24..36 |
| box_B | 72 | 30..36 | 19..34 | 0.24..0.40 | -3.0..-0.5 | 28..54 | 24..36 |

Actual sampled-run overrides used in the latest diagnosis:

| run | sample_count | config source | output |
| --- | ---: | --- | --- |
| baseline smoke | 8 | `.tmp/birdman_upstream_smoke.yaml` | `.tmp/birdman_upstream_smoke_out` |
| box_A exploratory | 16 | `.tmp/birdman_frontier_configs/box_a_explore16.yaml` | `output/birdman_upstream_frontier_box_a_explore16_20260424` |
| box_B exploratory | 16 | `.tmp/birdman_frontier_configs/box_b_explore16.yaml` | `output/birdman_upstream_frontier_box_b_explore16_20260424` |
| box_B promoted | 24 | `.tmp/birdman_frontier_configs/box_b_promote24.yaml` | `output/birdman_upstream_frontier_box_b_promote24_20260424` |

Other geometry constants / discrete candidates:

| parameter | value |
| --- | --- |
| sampling mode | latin_hypercube |
| sampling seed | 42 |
| sampling scramble | true |
| twist_root_deg | 2.0 |
| tail_area_candidates_m2 | 3.8, 4.2, 4.6 |
| dihedral_root_deg_candidates | 0.0, 1.0, 2.0 |
| dihedral_tip_deg_candidates | 4.0, 6.0, 8.0 |
| dihedral_exponent_candidates | 1.0, 1.5, 2.0 |
| cg_xc | 0.30 fixed |

Hard geometry constraints:

| constraint | value |
| --- | ---: |
| root_chord_min_m | 1.20 |
| tip_chord_min_m | 0.30 |
| segment_min_chord_m | 0.32 |
| root_zone_min_tc_ratio | 0.14 |
| root_zone_spar_depth_fraction | 0.62 |
| root_zone_required_spar_depth_m | 0.10 |
| segment_length_m | 1.0..3.0 |
| stations_per_half | 7 |
| keep_top_n | 8 |
| finalist_full_sweep_top_l | 4 |

CST / airfoil search:

| parameter | value |
| --- | --- |
| root/mid1 seed | FX 76-MP-140 |
| mid2/tip seed | Clark Y smoothed |
| thickness_delta_levels | -0.022, -0.018, -0.014, -0.010, -0.006, 0.0, 0.006, 0.010, 0.014, 0.018, 0.022 |
| camber_delta_levels | -0.016, -0.012, -0.008, -0.004, 0.0, 0.004, 0.008, 0.012, 0.016 |
| coarse_to_fine_enabled | true |
| coarse_thickness_stride | 3 |
| coarse_camber_stride | 2 |
| coarse_keep_top_k | 3 |
| refine_neighbor_radius | 1 |
| successive_halving_enabled | true |
| successive_halving_rounds | 2 |
| successive_halving_beam_width | 6 |
| XFOIL roughness_mode | clean |

Zone definitions:

| zone | eta range | min_tc_ratio |
| --- | --- | ---: |
| root | 0.00..0.25 | 0.14 |
| mid1 | 0.25..0.55 | 0.10 |
| mid2 | 0.55..0.80 | 0.10 |
| tip | 0.80..1.00 | 0.10 |

## Geometry Model

Primary sampled variables:

- `b = span_m`
- `W/S = wing_loading_target_Npm2`
- `lambda = taper_ratio = c_tip/c_root`
- `twist_tip_deg`

Derived quantities:

- `W_design = design_gross_mass_kg * g`
- `S = W_design / (W/S)`
- `c_root = 2 S / (b (1 + lambda))`
- `c_tip = lambda c_root`
- `AR = b^2 / S`
- `MAC = (2/3) c_root (1 + lambda + lambda^2)/(1 + lambda)`

Station model:

- half-span is segmented into equal segments no longer than `3 m`;
- chord, twist, and dihedral vary linearly/progressively along span;
- no non-linear planform, no swept wing, no structural deflection, no aeroelastic
  twist, and no wing mass model.

Engineering concern:

- This is currently a sizing-oriented trapezoid generator, not an aircraft
  weight/structure/aero co-design model.
- Reducing `W/S` automatically buys more wing area at fixed weight.

## AVL / Spanwise Load Model

AVL model:

- wing-only;
- symmetric half-wing;
- `Sref = wing_area_m2`, `Cref = MAC`, `Bref = span_m`;
- section airfoils come from seed or selected CST zone airfoils;
- no explicit tail, body, propwash, wire/strut drag, or structural deformation.

Design cases passed to AVL:

| case | speed | mass | load factor | weight |
| --- | ---: | ---: | ---: | ---: |
| reference_avl_case | selected from mission proxy | selected mass case | 1.0 | 0.35 |
| slow_avl_case | 6.0 m/s | 105 kg | 1.0 | 1.75 |
| launch_release_case | 8.0 m/s | 105 kg | 1.0 | 2.00 |
| turn_avl_case | 8.0 m/s | 105 kg | 1.0353 | 2.25 |

Case CL required:

`CL_required = mass * g * load_factor / (0.5 rho V^2 S)`.

Major concern:

- The low-speed heavy-mass cases dominate the spanwise load and airfoil-selection
  targets.
- The reference cruise case has lower weight than slow/launch/turn cases.
- This can steer airfoil and geometry toward "survive 6 m/s" rather than
  "maximize efficient 7.5..8 m/s long-distance cruise."

## Airfoil / CST / XFOIL Model

CST surfaces:

- class function: `C(x) = x^0.5 (1 - x)^1.0`;
- shape function: Bernstein polynomial over upper/lower coefficients;
- coordinates use cosine-spaced x-locations;
- thickness/camber deltas are applied to fixed basis vectors.

Airfoil selection score per zone:

- drag penalty from profile power proxy;
- trim penalty from moment proxy;
- stall penalty from worst-case and weighted stall violation;
- margin penalty if stall margin is below `0.08`;
- thickness penalty if `t/c` is below zone minimum;
- spar penalty if depth at `x/c = 0.30` is below required depth;
- infeasible guard if stall or structure proxy is violated.

Selected-zone feasibility requires:

- safe `CLmax >= 0`;
- worst-case stall margin `>= 0`;
- candidate thickness ratio `>= zone_min_tc_ratio`;
- spar depth ratio `>= max(0.06, 0.75 * zone_min_tc_ratio)`.

Engineering concerns:

- The airfoil family is tightly bounded around two seed families.
- XFOIL queries are clean-surface and low-Re sensitive.
- The zone score uses the same low-speed heavy cases that are currently driving
  the oversized-wing behavior.
- This is good for current controlled experiments, but not enough to declare a
  real optimum.

## Safe Local CLmax Model

Raw `CLmax` is taken from XFOIL when available, otherwise geometry proxy.

Source adjustment:

- geometry proxy: `safe_scale = 0.90 - 0.02`, `safe_delta = 0.05 + 0.02`;
- airfoil observed: `safe_scale = 0.90 + 0.02`, `safe_delta = 0.05 - 0.01`;
- otherwise use configured scale/delta.

Tip penalty:

- active when `eta > 0.55`;
- smoothstep span progress;
- taper severity: clamp(`(0.40 - taper_ratio)/0.20`, `0..1`);
- penalty = smoothstep * `tip_3d_penalty_max` plus taper penalty minus washout
  relief.

Safe local CLmax:

`CLmax_safe = max(0.10, scale * CLmax_raw - delta - tip_penalty)`.

Engineering concern:

- This is a handcrafted safe-margin model, not a validated 3D stall model.
- It is currently the model that makes `box_B` converge to exactly the 6 m/s
  low-speed boundary.

## Launch Gate

Launch dynamic pressure:

`q = 0.5 rho V_release^2`, with `V_release = 8 m/s`.

Required CL:

`CL_required = max(gross_mass_sweep) * g / (q S)`.

Gate:

- choose limiting station `CL_available`;
- `stall_utilization = CL_required / CL_available`;
- pass only if `CL_available >= CL_required`;
- pass only if utilization `<= 0.75`;
- pass only if trim margin `>= 2 deg`.

Ground-effect sensitivity:

- `height_ratio = platform_height / span`;
- `drag_factor = max(0.82, 1 - 0.6 exp(-8 height_ratio))`;
- reported separately, not primary pass/fail.

Engineering concern:

- Launch does not model acceleration, run-up, energy height, or prop transient;
  it is a CL/trim check at a fixed release speed.

## Turn Gate

Load factor:

`n = 1/cos(bank_angle) = 1.0353` for `15 deg`.

Gate:

- station `CL_required = CL_target * n`, unless pre-scaled by AVL case;
- `stall_utilization = CL_required / CLmax_safe`;
- pass if trim is feasible and utilization `<= 0.85`.

Engineering concern:

- This is a fixed-bank screening gate, not a route-level turn performance model.
- It is currently not the dominant blocker after box expansion.

## Trim Model

Weighted wing moment and CL:

- `wing_cl` = station weighted mean CL;
- `wing_cm_airfoil` = station weighted mean CM;
- moment weights use chord-squared-like weighting for CM.

Tail balance:

- `CM_wing_total = CM_airfoil + CL_wing (x_ac - x_cg) + CM_body`;
- `V_tail = (S_tail/S_wing) * (tail_arm/MAC) * q_tail_ratio * tail_efficiency`;
- `CL_tail_required = -CM_wing_total / V_tail`;
- include spread term from CM RMS;
- `tail_utilization = effective_tail_CL / tail_CL_limit`;
- trim margin = `6 deg * (CL_limit - effective_CL_tail)/CL_limit`.

Gate:

- pass if trim margin `>= 2 deg`.

Engineering concern:

- Tail is a force/moment balance proxy only.
- There is no elevator sizing, tail stall, tail structural mass, tail drag polar,
  static margin sweep, or dynamic stability closure.
- Trim is currently not the main bottleneck.

## Mission / Power / Drag Model

Speed sweep:

`V = 6.0, 6.5, 7.0, ..., 10.0 m/s`.

For each gross mass and speed:

- `W = mass * g`;
- `q = 0.5 rho V^2`;
- `CL = W / (q S)`;
- `CD_i = CL^2 / (pi AR e)`;
- `e = clamp(0.88 - 0.012 dihedral_delta - 0.008 twist_delta, 0.68, 0.92)`;
- `CD_misc = 0.0035 + 0.20 * (S_tail/S_wing) * CD_profile`;
- `CD_tail_trim = q_tail_ratio * (S_tail/S_wing) * CL_tail^2 / (pi AR_tail e_tail)`;
- `CD_total = CD_profile + CD_i + CD_misc + CD_tail_trim`;
- `D = q S CD_total`;
- `P_shaft = D V / eta_prop`, iterated three times because `eta_prop` depends
  on speed and shaft power.

Mission objective:

- rider curve gives duration available at required shaft power;
- `range = V * duration`;
- for `max_range`, mission score is `-best_range_m`;
- target pass if best range `>= 42.195 km`.

Mission feasible-speed filter:

- before scoring feasible range, each speed is filtered through local-stall
  feasibility;
- if no speed survives the stall filter, feasible range is forced to zero.

Engineering concerns:

- The mission optimum is strongly tied to the local-stall speed filter.
- The mission drag model uses a profile/induced proxy, not a full drag buildup.
- Prop efficiency is a coarse proxy, not a design-optimized propeller map.
- The rider curve is extremely steep around current power values, so small drag
  errors move mission range dramatically.
- The 6 m/s point can become both a stall-sizing point and the best-range speed,
  which can push the concept toward a slow Gossamer-like archetype.

## Local Stall Gate

For each local-stall case:

- station CL is either already case-specific from AVL or scaled from reference:
  `CL_scaled = CL_ref * (mass_eval/mass_ref) * (V_ref/V_eval)^2`;
- station margin: `CLmax_safe - CL_required`;
- station utilization: `CL_required / CLmax_safe`;
- worst station is the minimum margin / maximum utilization case.

Top-level local stall result picks the worst case by:

- maximum stall utilization;
- then maximum required CL.

The key diagnostic quantities:

- `required_speed_for_limit = V_eval * sqrt(utilization / limit)`;
- `required_wing_area_for_limit = S * utilization / limit`;
- `required_gross_mass_for_limit = mass_eval * limit / utilization`.

Engineering concern:

- This gate is currently the strongest geometric sizing driver.
- Because `required_wing_area_for_limit` directly rewards lower `W/S`, the
  optimizer can solve the gate by simply making the wing larger while keeping
  mass fixed.

## Ranking Model

Candidate booleans:

- launch feasible;
- turn feasible;
- trim feasible;
- local stall feasible;
- mission feasible.

Safety feasible:

`launch AND turn AND trim AND local_stall`.

Fully feasible:

`safety_feasible AND mission_feasible`.

Safety margin:

minimum of:

- launch utilization margin;
- turn utilization margin;
- local-stall utilization margin;
- trim margin normalized by `10 deg`.

Combined feasibility margin:

`min(safety_margin, mission_margin_km)`.

Score:

`score = 1000 * failed_gate_count + mission_component - 100 * combined_margin + assembly_penalty`.

Sort order:

1. fully feasible first;
2. lower failed gate count;
3. higher combined feasibility margin;
4. better mission component;
5. lower assembly penalty;
6. concept ID.

Engineering concern:

- `combined_feasibility_margin` mixes dimensionless safety margin with mission
  margin in kilometers. This is useful as a pragmatic sorter, but it is not a
  physically clean scalar objective.
- The sort is feasibility-first, so a concept that barely fixes a gate may rank
  above a concept that is more physically plausible but fails one more screen.
- This is acceptable for screening, but dangerous if interpreted as true
  optimum design.

## Current Fundamental Design Risks

### 1. The design target may be wrong

The current line is behaving as if 6 m/s ultra-low-speed flight is a primary
design goal. For a long-distance high-efficiency Birdman concept, the likely
target family is closer to:

- `7.5..8.0 m/s`;
- `S ~= 28..34 m^2` for about 105 kg all-up mass;
- `AR ~= 35..40`;
- `W/S ~= 30..38 N/m^2`.

The current promoted top concept is:

- `S ~= 48.6 m^2`;
- `AR ~= 24.4`;
- `W/S ~= 21.2 N/m^2`;
- `best_range_speed = 6.0 m/s`.

This is a strong sign that the chain is steering toward a slow large-area
aircraft, not a high-efficiency Birdman archetype.

### 2. Fixed gross mass is probably invalid once area changes

The model lets the search buy stall margin by increasing area while keeping
`design_gross_mass_kg = 105 kg`. A real large-area wing should increase:

- spar/tube mass;
- rib/skin mass;
- wire/strut mass if used;
- joint mass;
- deflection/clearance constraints;
- handling and launch risk.

Without this feedback, the optimizer will overvalue large area.

### 3. The 6 m/s slow case is over-coupled

The 6 m/s case appears in:

- AVL design cases;
- airfoil selection targets;
- local-stall gate;
- mission speed feasibility filter;
- best-range selection when the aircraft becomes slow enough.

This repeated coupling can create a self-reinforcing design loop:

`lower W/S -> larger S -> 6 m/s stall improves -> speed filter admits 6 m/s -> ranking sees fewer failed gates -> top concepts drift larger/slower`.

### 4. Mission failure says "do not keep increasing area"

The promoted `box_B` top is nearly stall-feasible at 6 m/s but still far from
mission pass at 105 kg. That means the next problem is not area upper bound.
It is the combination of:

- mass;
- speed target;
- drag/power model;
- rider endurance curve;
- prop efficiency;
- and structural feedback.

### 5. The current ranking is a screening heuristic, not a design optimum

The ranking is useful for finding promising samples. It should not be read as:

- global optimum;
- physics-complete optimum;
- validated HPA concept;
- proof that `S ~= 49 m^2` is right.

## What Is Probably Sound

- The new primary variables are better than chord-first sampling for sizing
  studies.
- The `S = W/(W/S)` calculation is mathematically correct.
- The output contracts are traceable: failures, margins, speed filter, mission
  limiter, and geometry are visible.
- Trim being explicit is an improvement over hidden trim assumptions.
- The current chain is good enough to expose that the low-speed gate and mission
  model are fighting each other.

## What Is Probably Fundamentally Wrong Or Incomplete

Highest priority issues:

- treating 6 m/s as a primary sizing condition for a long-distance Birdman
  concept;
- holding gross mass fixed while increasing wing area;
- ranking designs before adding even a lightweight structural mass/deflection
  feedback;
- using a coarse prop/mission power proxy in a regime where 10 W can change
  endurance by tens of minutes;
- interpreting feasibility-first sampled ranking as an optimum.

Medium priority issues:

- AVL wing-only loading without tail/body/propwash/elasticity;
- safe local `CLmax` model is handcrafted and may over-control geometry;
- tail model lacks elevator/tail stall/weight;
- launch model lacks dynamic launch mechanics;
- turn model is screening-only;
- airfoil selection uses clean XFOIL and a bounded family.

## Recommended Evaluation Order

Do not expand the area box first. Instead:

1. Decide whether the concept should be sized around `6 m/s` or around
   `7.5..8.0 m/s`.
2. Add a report-only structural mass sensitivity:
   run current top concepts with gross mass increased as a function of area/span.
3. Re-score existing pools under the mass sensitivity without resampling.
4. Add a report-only mission sensitivity:
   compare required duration and available duration at `6, 7, 7.5, 8 m/s`.
5. Only after that decide whether to alter gates, objective, or physics fidelity.

If the goal is high-efficiency long-distance Birdman, the current conclusion is:
the pipeline is probably biased toward the wrong aircraft archetype because the
6 m/s local-stall gate is too deeply coupled into the design chain.
