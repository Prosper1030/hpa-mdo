# Birdman Upstream Concept Line GPT Pro Review Packet

Date: 2026-05-02

Route name: `birdman-upstream-concept`

Chinese name: Birdman 上游概念外型線

Purpose of this packet: provide a self-contained pseudocode and physics summary for GPT Pro. GPT Pro should be able to review the route without repository access.

## Executive Summary

This route is an upstream human-powered-aircraft concept screening loop. It starts from environment, rider power, mass closure, span, wing loading, taper, twist, tail area, dihedral, and segmentation. It then builds spanwise stations, asks an AVL-backed loader for spanwise lift/trim cases, searches CST airfoils, evaluates selected airfoils through Julia/XFoil, applies conservative local `CLmax` corrections, evaluates launch/turn/trim/local-stall/mission gates, ranks concepts, and writes summary and handoff bundles.

Engineering status: it is real enough to diagnose concept failures, but not yet decision-grade. The latest available real Julia/XFoil artifact reports no fully feasible selected concept. Best infeasible concept is roughly:

- span `b = 35.99 m`
- wing area `S = 38.09 m2`
- aspect ratio `AR = 34.01`
- gross mass from mass closure `m = 106.2 kg`
- first feasible mission speed `7.0 m/s`
- best feasible range `16.1 km`
- target range `42.195 km`
- main failures: local stall and mission endurance/range

Important caveat: the current YAML baseline and the latest artifact are not perfectly aligned. Current baseline config says mission sweep is `7.0..10.0 m/s` with 7 points and `6.0 m/s` as slow report. The latest artifact says speed window `6.0..10.0 m/s` with 9 points. Treat artifact metrics as evidence, not as a guaranteed current-run truth until rerun with a config hash.

## Current Baseline Inputs

Config file: `configs/birdman_upstream_concept_baseline.yaml`

Current baseline values relevant to physics:

- Environment: `33 C`, `80% RH`, sea level.
- Pilot mass: `60 kg`.
- Mass closure:
  - enabled
  - fixed non-wing aircraft mass: `24 kg`
  - estimated tube system: enabled
  - tube root OD `0.070 m`, tip OD `0.035 m`
  - tube root wall `0.0007 m`, tip wall `0.0004 m`
  - tube material density `1600 kg/m3`
  - 2 spars per wing, 2 wings
  - rib/skin areal density `0.20 kg/m2`
  - fittings `1.5 kg`, wire terminals `0.6 kg`, system margin `2.0 kg`
  - hard gross-mass max `107 kg`
- Mission:
  - objective `max_range`
  - target distance `42.195 km`
  - rider power CSV: `data/pilot_power_curves/current_pilot_power_curve.csv`
  - anchor duration `30 min`, anchor power from current CSV about `254 W`
  - current baseline speed sweep `7.0..10.0 m/s`, 7 points
  - slow report speed `[6.0] m/s`
- Launch:
  - restrained pre-spin
  - release speed `8.0 m/s`
  - platform height `10 m`
  - release RPM `140`
  - ground-effect sensitivity enabled, but the primary launch gate does not apply ground effect
- Stall:
  - safe `CLmax` scale `0.90`
  - safe `CLmax` delta `0.05`
  - local stall utilization limit `0.75`
  - turn utilization limit `0.75`
  - launch utilization limit `0.85`
  - slow speed report limit `0.85`
- Prop:
  - 2 blades
  - diameter `3.0 m`
  - RPM range `100..160`
  - BEMT proxy exists in code but is not enabled by default
- Geometry search:
  - `span_m = 30..36`
  - `wing_loading_target_Npm2 = 22..30`
  - `taper_ratio = 0.24..0.40`
  - `tip_twist_deg = -3.0..-0.5`
  - hard wing area `28..46 m2`
  - hard aspect ratio `24..36`
  - root chord min `1.20 m`, tip chord min `0.30 m`
  - tail area candidates `3.8, 4.2, 4.6 m2`
  - dihedral root candidates `0, 1, 2 deg`
  - dihedral tip candidates `4, 6, 8 deg`
- CST/airfoil:
  - seedless Sobol mode
  - 512 samples
  - constrained Pareto selection
  - robust Reynolds factors `0.85, 1.0, 1.15`
  - roughness modes `clean, rough`
  - NSGA and CMA-ES refinement enabled
- Pipeline:
  - 7 stations per half wing
  - keep top 8
  - finalist full sweep top 4
  - Julia/XFoil worker count 4
  - XFoil max iterations 40
  - XFoil panels 96
  - candidate bundle export enabled
  - OpenVSP export disabled by default

## Core Pipeline Pseudocode

This is intentionally written without code-specific object names where possible.

```text
INPUT:
  config
  output_dir
  airfoil_worker_factory
  spanwise_loader

LOAD config
CREATE output_dir

rho = humid_air_density(environment)

GEOMETRY ENUMERATION:
  primary_samples = sample span, target wing loading, taper, tip twist
  secondary_samples = sample tail area, dihedral root, dihedral tip, dihedral exponent

  for each sample:
    b = span
    WS_target = wing_loading_target_Npm2
    lambda = taper_ratio
    twist_root = config.twist_root
    twist_tip = sampled tip_twist

    initial_S = design_gross_weight_N / WS_target

    if mass_closure.enabled:
      tube_mass = estimate tapered thin-wall tube system mass
      iterate:
        wing_area_dependent_mass = rib_skin_areal_density * S
        gross_mass = pilot_mass + fixed_nonwing_aircraft_mass
                   + tube_mass + fittings + wire_terminals
                   + system_margin + wing_area_dependent_mass
        S_next = gross_mass * g / WS_target
      until |S_next - S| < tolerance

      reject if not converged
      reject if closed_gross_mass > hard gross-mass max
      S = closed_S
      design_gross_mass = closed_gross_mass

    apply jig-shape coarse deflection gate:
      estimate each half-wing as uniform-load cantilever
      reject if tip_deflection / half_span > limit

    apply lift-wire coarse tension gate:
      estimate T = W_per_wing * load_factor * fraction
      reject if T > allowable

    c_root = 2*S / (b*(1 + lambda))
    c_tip = lambda*c_root
    AR = b^2 / S
    MAC = (2/3)*c_root*(1 + lambda + lambda^2)/(1 + lambda)

    reject if hard constraints fail:
      S range, AR range, root chord min, tip chord min, segment min chord, root tc/spar depth

    build half-span segment plan and stations
    accept GeometryConcept

PREPARE EACH ACCEPTED CONCEPT:
  stations = linear spanwise stations over half wing
    y_i, chord_i, twist_i, dihedral_i

  zone_requirements = spanwise_loader(concept, stations)

  nominal path:
    spanwise_loader builds AVL cases:
      reference cruise case
      slow-speed case
      launch case
      turn case
    AVL returns strip forces / station targets:
      cl_target, cm_target, Reynolds, chord, station y, weights, reference speed/mass

  fallback path:
    if AVL-backed loader raises exception:
      log to stderr
      return fallback coarse loader payload
      mark fallback source and fallback reason

  annotate zone requirements with concept geometry

AIRFOIL SELECTION:
  Collect all zone requirements that contain points.

  Run bounded CST / seedless search:
    for each concept-zone:
      generate candidate airfoil coordinates
      reject invalid geometry
      run worker polar checks through Julia/XFoil or test/stub worker
      evaluate robust clean/rough and Reynolds-factor pass rate
      score candidates using:
        drag
        moment/trim penalty
        safe CLmax margin vs zone target
        thickness/spar-depth constraints
      select constrained Pareto / knees
      optionally refine with NSGA and CMA-ES

  For zones without points:
    use fallback selected seed airfoil candidate.

SCREENING EVALUATION FOR EACH CONCEPT:
  Build selected CST airfoil templates per zone.
  Flatten zone requirements into station points.
  Attach geometry CLmax proxy to each point if needed.

  Build worker queries:
    template_id
    coordinates
    Reynolds
    target CL samples
    roughness mode
    analysis_mode = screening_target_cl
    analysis_stage = screening

  worker_results = Julia/XFoil run_queries(...)

  Apply worker feedback:
    if result count mismatch:
      keep geometry proxy
      mark worker_result_count_mismatch

    for each station point:
      if worker result is status ok and has usable polar:
        set worker_cl, worker_cm, worker_cd
        set cl_max_effective from observed CLmax
        set cm_effective, cd_effective
      else:
        keep geometry proxy for that point

  Apply safe local CLmax model:
    raw CLmax -> safe CLmax by source-dependent scale/delta
    add tip 3D/taper penalty and washout relief

  Update selected zone candidates from station points.

  Trim summary:
    weighted wing CM and CL from reference AVL case
    compute required tail CL from tail volume balance
    check tail utilization and trim margin

  Launch summary:
    q = 0.5*rho*V_release^2
    CL_required = W/(q*S)
    CL_available = limiting safe CLmax from launch case
    primary gate does not apply ground effect
    ground effect is sensitivity only
    gate passes if CL_available >= CL_required,
      stall utilization <= launch limit,
      trim margin >= required trim margin

  Turn summary:
    use turn AVL case if available; otherwise scale reference case
    load factor n = 1/cos(bank) unless AVL turn case pre-scaled
    stationwise required CL = CL_target*n
    gate passes if trim feasible, raw CLmax not exceeded, and safe utilization <= turn limit

  Mission summary:
    speed_sweep = evenly spaced mission speed samples
    profile_cd = weighted mean cd_effective over reference AVL station points,
                 fallback to airfoil_feedback mean_cd_effective,
                 fallback to 0.020
    e = Oswald efficiency proxy
    misc_cd = fuselage_misc_cd + tail_profile_coupling_factor*(tail_area/S)*profile_cd
    trim_cd = tail induced drag proxy from required tail CL
    rigging_cd = wire CdA/S

    for each gross mass case:
      for each speed V:
        q = 0.5*rho*V^2
        CL_required = W/(q*S)
        CDi = CL_required^2/(pi*AR*e)
        CDtotal = profile_cd + CDi + misc_cd + trim_cd + rigging_cd
        Drag = q*S*CDtotal
        shaft_power = Drag*V / eta_prop
        pedal_power = shaft_power / drivetrain_efficiency

      compute unconstrained range from rider W-duration curve
      compute speed-feasibility records from local-stall utilization
      filter mission objective to only local-stall-feasible speeds
      if no feasible speeds:
        mission infeasible, best range = 0
      else:
        best range = max(V * endurance_at_pedal_power)
        mission passes if best range >= target distance

    add slow-speed report for configured slow speeds:
      uses same drag/power model
      report-only; not a cruise feasibility filter

  Local-stall summary:
    evaluate reference, launch, turn, mission/worst, and slow cases when available
    slow-speed case has role slow_speed_sensitivity and is report-only
    hard gate ignores report-only slow case
    worst hard-gate case decides local_stall_feasible

  Build ranking input:
    launch_feasible
    turn_feasible
    trim_feasible
    local_stall_feasible
    mission_feasible
    safety_margin = min selected gate margins
    mission_margin_m
    mission_score
    assembly_penalty = 0.5 * number_of_halfspan_segment_joints

RANK:
  rank concepts by:
    fully_feasible first
    fewer failed gates
    higher combined feasibility margin
    mission component
    lower assembly penalty
    concept id tie-break

  score is recorded as:
    score = 1000*failed_gate_count
          + mission_component
          - 100*combined_feasibility_margin
          + assembly_penalty

FINALIST FULL SWEEP:
  take top finalist_full_sweep_top_l concepts
  if AVL rerun context exists:
    rerun AVL with post-airfoil feasible reference condition
    up to 2 iterations if consistency audit recommends it
  re-evaluate finalists with:
    analysis_mode = full_alpha_sweep
    analysis_stage = finalist
  rerank after finalist reevaluation

OUTPUT:
  selected_concepts = fully feasible top N
  best_infeasible_concepts = best infeasible if no selected concepts
  concept_summary.json
  concept_ranked_pool.json
  frontier_summary.json
  per-concept bundles
  optional OpenVSP handoff only if export_vsp=true and concept index <= export_vsp_for_top_n
```

## Formula Sheet

Use these as the first math targets for GPT Pro to review.

### Atmosphere

```text
T_K = T_C + 273.15
p = 101325 * (1 - 2.25577e-5*h)^5.25588
p_sat = 610.94 * exp(17.625*T_C/(T_C + 243.04))
p_v = RH * p_sat
p_d = p - p_v
rho = p_d/(287.058*T_K) + p_v/(461.495*T_K)
q = 0.5*rho*V^2
```

### Wing Geometry

```text
W = m*g
target wing loading = W/S = WS_target
initial S = design_gross_weight_N / WS_target

c_root = 2*S/(b*(1 + lambda))
c_tip = lambda*c_root
AR = b^2/S
MAC = (2/3)*c_root*(1 + lambda + lambda^2)/(1 + lambda)
```

### Area/Mass Closure

```text
fixed_mass = pilot_mass + fixed_nonwing_aircraft_mass
           + tube_system_mass + fittings + wire_terminals + system_margin

wing_area_dependent_mass = wing_areal_density * S
gross_mass = fixed_mass + wing_area_dependent_mass
S_next = gross_mass*g / WS_target

iterate until |S_next - S| <= tolerance
```

This is used to generate geometry, but its own docstring calls it intentionally lightweight/report-only.

### Tapered Tube Mass

```text
half_span = b/2
D_mid = 0.5*(D_root + D_tip)
t_mid = 0.5*(t_root + t_tip)
integrand_avg = (D_root*t_root + 4*D_mid*t_mid + D_tip*t_tip)/6
mass_per_tube = rho_material*pi*integrand_avg*half_span
tube_system_mass = mass_per_tube * num_spars_per_wing * num_wings
```

### Jig-Shape Deflection Gate

```text
L = b/2
distributed_load_per_wing = m*g/(num_wings*L)
I_tube_root = pi*D_root^3*t_root/8
A_tube_root = pi*D_root*t_root
I_parallel = num_spars_per_wing*A_tube_root*(spar_vertical_separation/2)^2
I_wing = num_spars_per_wing*I_tube_root + I_parallel
EI = E*I_wing
delta_uniform = w*L^4/(8*EI)
delta = delta_uniform * deflection_taper_correction_factor
gate metric = delta/L
```

Physics concern: this is a very coarse uniform-load cantilever with root stiffness and a tuning factor, not a nonlinear aeroelastic jig-shape model.

### Lift-Wire Tension Gate

```text
T = (m*g/num_wings) * limit_load_factor * wing_lift_fraction_carried
```

Physics concern: this does not explicitly include wire angle, attachment location, catenary, or moment-arm geometry.

### Safe Local CLmax Model

```text
raw_CLmax = XFoil observed CLmax or geometry proxy

source adjustment:
  geometry_proxy: scale = safe_scale - 0.02, delta = safe_delta + 0.02
  airfoil_observed: scale = safe_scale + 0.02, delta = safe_delta - 0.01
  other: scale = safe_scale, delta = safe_delta

span_progress = smoothstep((eta - tip_3d_penalty_start_eta)/(1 - tip_3d_penalty_start_eta))
taper_severity = clamp((0.40 - taper_ratio)/0.20, 0, 1)
tip_taper_penalty = span_progress * tip_3d_penalty_max * tip_taper_penalty_weight * taper_severity
washout_relief = span_progress * washout_relief_max * clamp(washout_deg/washout_relief_deg, 0, 1)
tip_3d_penalty = max(0, span_progress*tip_3d_penalty_max + tip_taper_penalty - washout_relief)

safe_CLmax = max(0.10, scale*raw_CLmax - delta - tip_3d_penalty)
```

### Stationwise Stall / Turn / Mission Speed Scaling

```text
If station CL targets were generated at reference mass and speed:
CL_target_eval = CL_target_ref * (m_eval/m_ref) * (V_ref/V_eval)^2

required_CL = CL_target_eval * load_factor
stall_margin = safe_CLmax - required_CL
stall_utilization = required_CL / safe_CLmax

raw_CLmax_ratio = required_CL / raw_CLmax
safe_CLmax_ratio = required_CL / safe_CLmax
stall_speed_margin_ratio = 1/sqrt(CLmax_ratio)

turn load factor n = 1/cos(bank_angle)
```

### Launch Gate

```text
CL_required_launch = m*g / (0.5*rho*V_release^2*S)
stall_utilization_launch = CL_required_launch / CL_available

primary launch gate:
  ground effect = false
  pass if:
    CL_available >= CL_required_launch
    stall_utilization_launch <= launch_utilization_limit
    trim_margin_deg >= min_trim_margin_deg

ground-effect sensitivity:
  height_ratio = platform_height / wing_span
  drag_factor = max(0.82, 1 - 0.6*exp(-8*height_ratio))
  adjusted_CL_required = CL_required * drag_factor
```

Physics concern: ground effect is currently only sensitivity, and the gate is a CL/stall/trim check, not a full launch trajectory simulation.

### Trim Balance

```text
weighted_mean_CM = weighted station cm_effective
weighted_mean_CL = weighted station cl_target

CM_wing_total = CM_airfoil + CL_wing*(x_ac - x_cg) + CM_body_offset

tail_area_ratio = S_tail/S
tail_volume = tail_area_ratio * tail_arm_to_MAC * q_tail_ratio * tail_efficiency
CL_tail_required = -CM_wing_total / tail_volume

spread_tail_CL = spread_factor*cm_rms / tail_volume
effective_tail_CL_required = abs(CL_tail_required) + abs(spread_tail_CL)
tail_utilization = effective_tail_CL_required / tail_CL_limit_abs
trim_margin_deg = max(0, 6*(tail_CL_limit_abs - effective_tail_CL_required)/tail_CL_limit_abs)
```

Physics concern: static tail-volume proxy only; no dynamic stability, rudder-only control, sideslip, flexible-tail coupling, or trim-drag calibration.

### Drag and Power Model

```text
profile_cd = weighted mean of cd_effective over reference AVL station points
           else airfoil_feedback.mean_cd_effective
           else 0.020

e = clamp(e_base
          - dihedral_slope*(dihedral_tip - dihedral_root)
          - twist_slope*abs(twist_tip - twist_root),
          e_floor, e_ceiling)

CL_required = m*g/(q*S)
CD_induced = CL_required^2/(pi*AR*e)
CD_misc = fuselage_misc_cd + tail_profile_coupling_factor*(S_tail/S)*profile_cd
CD_trim = q_tail_ratio*(S_tail/S)*CL_tail_required^2/(pi*AR_tail*e_tail)
CdA_rigging = wire_Cd * wire_diameter * total_exposed_wire_length
CD_rigging = CdA_rigging/S

CD_total = profile_cd + CD_induced + CD_misc + CD_trim + CD_rigging
Drag = q*S*CD_total
shaft_power = Drag*V/eta_prop
pedal_power = shaft_power/drivetrain_efficiency
```

Physics concerns:

- 2D XFoil `cd` is being used in an aircraft-level mission CD budget by weighted station average.
- There is no full 3D viscous correction, surface waviness/wrinkling penalty, interference drag, prop-wing interaction, or nonplanar flexible-wing correction.
- `profile_cd` in mission can differ strongly from all-worker mean CD because mission only uses reference AVL station points.

### Propeller Model

Default operating-point proxy:

```text
speed_term = max(speed_floor, 1 - speed_falloff*abs(V - V_peak))
power_term = max(power_floor, 1 - power_falloff*abs(P_shaft - P_peak))
eta = clamp(design_efficiency * speed_term * power_term, eta_floor, eta_ceiling)
```

Important: in default mode, prop efficiency is independent of prop diameter, RPM range, and blade count. A BEMT-flavored proxy exists but requires `use_bemt_proxy=true`.

BEMT-flavored proxy when enabled:

```text
A_disk = pi*D^2/4
n = RPM_design/60
V_tip = pi*D*n
J = V/(n*D)
advance_ratio_term = max(J_floor, 1 - J_falloff*(J - J_peak)^2)
eta_blade = max(0, 1 - blade_loss_constant/blade_count)
eta_profile = max(0, 1 - profile_loss)

iterate eta:
  T = eta*P_shaft/V
  disk_loading_factor = 2*T/(A_disk*rho*V^2)
  eta_ideal = 2/(1 + sqrt(1 + disk_loading_factor))
  eta_new = eta_ideal*eta_blade*eta_profile*advance_ratio_term*V_tip_penalty
  eta_new = clamp(eta_new, eta_floor, eta_ceiling)
```

### Mission Objective

```text
For each speed V:
  endurance_s = rider_curve.duration_at_power(pedal_power) * 60
  range_m = V * endurance_s

  required_duration_min_for_target = target_range_m/V/60
  available_power_at_target_duration = rider_curve.power_at_duration(required_duration_min_for_target)
  power_margin = available_power_at_target_duration - pedal_power

best_range = max(range_m)
mission passes if best_range >= target_range_m

For max_range objective:
  mission_score = -best_range
```

Mission result is filtered to local-stall-feasible speed samples. If the best-power/best-range speed is below local-stall feasibility, the route uses the first feasible speed sample instead.

### Ranking

```text
safety_feasible = launch and turn and trim and local_stall
fully_feasible = safety_feasible and mission
failed_gate_count = number of failed gates among launch, turn, trim, local_stall, mission

safety_margin = min(
  launch utilization margin,
  turn/stall margin,
  trim margin,
  local stall margin
)

combined_margin = min(safety_margin, mission_margin_m/1000)

recorded_score =
  1000*failed_gate_count
  + mission_component
  - 100*combined_margin
  + assembly_penalty

sort key:
  fully feasible first
  failed gate count
  descending combined margin
  mission component
  assembly penalty
  concept id
```

## Latest Artifact Snapshot

Artifact directory: `output/birdman_mass_closure_rerun_20260424/`

Treat as latest available evidence, but rerun is needed because of config drift noted above.

Summary:

- worker backend: `julia_xfoil`
- enumerated/evaluated concepts: `40`
- selected feasible concepts: `0`
- best infeasible count: `8`
- geometry primary variables:
  - `span_m`
  - `wing_loading_target_Npm2`
  - `taper_ratio`
  - `tip_twist_deg`
- geometry sampling:
  - requested `48`
  - accepted `40`
  - rejected `8`
  - rejection reason: `aspect_ratio_above_max`
- worker statuses across artifact: `1119 ok`, `197 mini_sweep_fallback`
- top best-infeasible concept:
  - id `infeasible-24`
  - span `35.987951 m`
  - wing area `38.085973 m2`
  - aspect ratio `34.0055`
  - mass closure gross mass `106.217 kg`
  - root chord `1.6427 m`
  - tip chord `0.4739 m`
  - launch feasible: true
  - trim feasible: true
  - turn feasible: true
  - local stall feasible: false
  - mission feasible: false
  - mission best feasible range `16117 m`
  - target margin `-26078 m`
  - first feasible mission speed `7.0 m/s`
  - unconstrained best range speed `6.0 m/s`
  - mission profile CD proxy `0.00967`
  - mission misc CD proxy `0.00369`
  - mission trim CD proxy `0.000241`
  - Oswald proxy `0.7518`
  - propulsion model `simplified_prop_proxy_v1`
  - mission limiter: endurance shortfall at best feasible speed
  - power required at best feasible speed around `238 W`
  - target duration at `7.0 m/s` around `100.5 min`
  - available duration at that power around `38.4 min`
  - local-stall slow case at `6.0 m/s`:
    - required CL `1.429`
    - safe CLmax `1.335`
    - utilization `1.070`
    - limit `0.8` in artifact
    - required speed for limit `6.94 m/s`
    - required wing area for limit `50.96 m2`

Historical sanity references:

- MIT News states Daedalus flew `115 km` in `3 h 54 min` and weighed `69 lb` empty.
- Human Powered Flight lists Daedalus 88 as span `34.14 m`, wing area `30.84 m2`, empty weight `31.75 kg`, airfoil DAE-11, rudder-only lateral control.
- MDPI FSI paper notes Daedalus-style DAE airfoils and discusses low-Reynolds FSI; it also references designed tip deflection and low-speed flexible-wing behavior.

## Known High-Risk Physics Questions

Ask GPT Pro to attack these, not to be polite.

1. Is the current target physically plausible with a 60 kg pilot, `~106 kg` gross mass, `S ~38 m2`, `AR ~34`, and current power curve?
2. Does the current route over-penalize wing loading and push toward too-large area compared with Daedalus/Light Eagle-like designs?
3. Is `tail_area = 3.8..4.6 m2` too large for HPA, causing unnecessary drag and trim coupling?
4. Is mission `profile_cd` too optimistic or too pessimistic when derived from stationwise XFoil CD?
5. Is the mismatch between `airfoil_feedback.mean_cd_effective ~0.022` and mission `profile_cd_proxy ~0.0097` a real modeling issue or a reasonable case-selection difference?
6. Does the safe CLmax model double-count or misplace tip penalties relative to AVL strip-load and low-Reynolds 2D XFoil data?
7. Should the 6 m/s case be report-only, or should Birdman launch/low-altitude handling make it a hard gate?
8. Does a 10 m platform restrained pre-spin launch make Daedalus comparison misleading?
9. Does the prop model invalidate mission conclusions because default prop efficiency ignores diameter/RPM/blade count?
10. Are the tube mass, deflection, and lift-wire gates physically meaningful enough, or are they hiding a structural impossibility?
11. Does ranking by gate count and margins hide the real design direction? Should it use energy/range sensitivity or calibrated physical Pareto instead?
12. What single model error would most likely explain "no feasible 42.195 km concept"?

## Repair Order To Keep In Mind

The recommended repair order from prior review is:

1. Add `decision_grade` / `not_decision_grade_reason` to output artifacts.
2. Add hard no-silent-fallback gates for AVL fallback, worker fallback, stub worker, config hash mismatch, and missing polar data.
3. Build a Daedalus/Light Eagle benchmark config with expected `b, S, AR, W/S, V, power, CL, CD0/e`.
4. Enable BEMT or prop-map mission coupling by default for concept decisions.
5. Clarify whether 6 m/s and launch/turn low-speed cases are report-only or hard mission safety gates.
6. Pull in a stronger structural surrogate for spar mass, buckling, wire geometry, and aeroelastic deflection.
7. Turn OpenVSP/downstream handoff into a real default diagnostic bundle for top selected or best infeasible concepts.

## Copy-Paste Prompt For GPT Pro

```text
You are acting as a strict aerospace engineering reviewer and automated aircraft design/MDO reviewer.

You cannot see the code repository. Everything you need is in this prompt. Please do not assume there is hidden code that fixes missing physics. Review the described pipeline as if you were deciding whether this human-powered-aircraft concept-design route is physically trustworthy enough to guide design decisions.

Project route name:
  birdman-upstream-concept
  Chinese: Birdman 上游概念外型線

Goal:
  Upstream concept design for a human-powered aircraft / Birdman-style aircraft. The route starts from span, wing loading, wing area, taper, twist, tail area, dihedral, mass closure, rider power, AVL, CST airfoils, Julia/XFoil, and then ranks concepts by launch/turn/trim/local-stall/mission feasibility.

Mission target:
  42.195 km range.

Current baseline:
  Environment: 33 C, 80% RH, sea level.
  Pilot mass: 60 kg.
  Mass closure enabled:
    fixed non-wing aircraft mass = 24 kg
    tube system estimated from tapered thin-wall CFRP tubes
    tube root OD = 0.070 m
    tube tip OD = 0.035 m
    root wall = 0.0007 m
    tip wall = 0.0004 m
    tube material density = 1600 kg/m3
    2 spars per wing, 2 wings
    rib/skin areal density = 0.20 kg/m2
    fittings = 1.5 kg
    wire terminals = 0.6 kg
    system margin = 2.0 kg
    gross mass hard max = 107 kg
  Mission:
    objective = max_range
    target distance = 42.195 km
    current rider power curve is CSV-based; approx anchor is 254 W at 30 min
    current baseline speed sweep = 7.0..10.0 m/s with 7 points
    slow report speed = 6.0 m/s
  Launch:
    restrained pre-spin
    release speed = 8.0 m/s
    platform height = 10 m
    release RPM = 140
    ground effect is sensitivity only; primary launch gate does not use ground effect
  Stall:
    safe CLmax scale = 0.90
    safe CLmax delta = 0.05
    local stall utilization limit = 0.75
    turn utilization limit = 0.75
    launch utilization limit = 0.85
    slow-speed report utilization limit = 0.85
  Prop:
    2 blades
    diameter = 3.0 m
    RPM range = 100..160
    BEMT proxy exists but is not enabled by default; default prop efficiency ignores diameter, RPM range, and blade count.
  Geometry search:
    span = 30..36 m
    target wing loading = 22..30 N/m2
    taper ratio = 0.24..0.40
    tip twist = -3.0..-0.5 deg
    hard wing area = 28..46 m2
    hard aspect ratio = 24..36
    tail area candidates = 3.8, 4.2, 4.6 m2
    dihedral root candidates = 0,1,2 deg
    dihedral tip candidates = 4,6,8 deg

Latest available artifact snapshot:
  Note: current YAML and latest artifact may have config drift. Artifact says speed window 6..10 m/s with 9 points, while current YAML says 7..10 plus 6 m/s slow report. Treat artifact as evidence, not final current truth.

  worker backend = julia_xfoil
  concepts evaluated = 40
  selected fully feasible concepts = 0
  worker statuses across artifact = 1119 ok, 197 mini_sweep_fallback

  Best infeasible concept:
    span = 35.987951 m
    wing area = 38.085973 m2
    AR = 34.0055
    mass-closure gross mass = 106.217 kg
    root chord = 1.6427 m
    tip chord = 0.4739 m
    launch feasible = true
    trim feasible = true
    turn feasible = true
    local stall feasible = false
    mission feasible = false
    best feasible range = 16.117 km
    target range margin = -26.078 km
    first feasible mission speed = 7.0 m/s
    unconstrained best range speed = 6.0 m/s
    profile_cd_proxy in mission = 0.00967
    misc_cd_proxy = 0.00369
    trim_drag_cd_proxy = 0.000241
    Oswald efficiency proxy = 0.7518
    propulsion model = simplified_prop_proxy_v1
    limiter = endurance shortfall at best feasible speed
    power required at 7.0 m/s about 238 W
    target duration at 7.0 m/s about 100.5 min
    available duration at that power about 38.4 min
    6.0 m/s local stall/sensitivity case:
      required CL = 1.429
      safe CLmax = 1.335
      utilization = 1.070
      artifact limit = 0.8
      required speed for limit = 6.94 m/s
      required wing area for limit = 50.96 m2

Reference context:
  MIT News says Daedalus flew 115 km in 3 h 54 min and weighed 69 lb empty.
  Human Powered Flight lists Daedalus 88 as span 34.14 m, wing area 30.84 m2, empty weight 31.75 kg, airfoil DAE-11, rudder-only lateral control.
  MDPI FSI paper discusses Daedalus-style DAE airfoils, low-Reynolds FSI, and flexible-wing behavior.

Pipeline pseudocode:

  1. Load config and compute humid-air density.
  2. Enumerate geometry:
       sample span, target wing loading, taper, tip twist
       sample tail area, dihedral root/tip/exponent
       if mass closure enabled:
         estimate tube mass
         iterate S = gross_mass*g/target_wing_loading
         gross_mass = pilot + fixed non-wing + tube + fittings + wire terminals + system margin + areal_density*S
         reject if not converged or gross mass > 107 kg
       apply coarse jig-shape deflection gate
       apply coarse lift-wire tension gate
       compute root chord, tip chord, AR, MAC
       reject hard constraint violations
       build spanwise stations
  3. For each concept:
       call AVL-backed spanwise loader
       expected output: reference cruise, slow, launch, turn station cases with cl_target, cm_target, Reynolds, chord, weights
       if AVL fails, loader catches exception and returns coarse fallback payload with fallback annotations
  4. Airfoil/CST selection:
       generate bounded CST airfoil candidates
       evaluate robust clean/rough and Reynolds factors with Julia/XFoil worker
       score candidates by drag, moment/trim penalty, safe CLmax margin, thickness/spar-depth constraints
       select constrained Pareto/knees; optionally refine with NSGA/CMA-ES
  5. Screening evaluation:
       flatten zone requirements into station points
       attach geometry CLmax proxy
       run Julia/XFoil at target station points
       if worker result usable:
         station gets worker_cl, worker_cm, worker_cd, observed CLmax
       if worker result unusable:
         station keeps proxy values
       apply safe local CLmax model
  6. Gates:
       trim: weighted station CM/CL and tail volume balance
       launch: CL_required = W/(q*S) at release speed, compare to safe CLmax; ground effect sensitivity only
       turn: n = 1/cos(bank), station CL utilization vs safe CLmax
       mission: for each speed, compute drag, power, rider endurance/range, filter out local-stall-infeasible speeds
       local stall: evaluate reference/launch/turn/slow cases; slow case is report-only
  7. Ranking:
       fully_feasible = launch and turn and trim and local stall and mission
       rank fully feasible first, fewer failed gates, higher combined margin, mission component, lower assembly penalty
  8. Finalists:
       re-evaluate top finalists with full-alpha-sweep worker mode
       if AVL rerun context exists, rerun AVL with post-airfoil reference condition up to 2 iterations
       rerank
  9. Output:
       selected concepts if fully feasible
       best infeasible concepts if none feasible
       summary JSON, ranked pool, frontier summary, optional bundles
       OpenVSP handoff is disabled by default.

Formula sheet:

  Atmosphere:
    T_K = T_C + 273.15
    p = 101325*(1 - 2.25577e-5*h)^5.25588
    p_sat = 610.94*exp(17.625*T_C/(T_C + 243.04))
    p_v = RH*p_sat
    rho = (p - p_v)/(287.058*T_K) + p_v/(461.495*T_K)
    q = 0.5*rho*V^2

  Wing geometry:
    W = m*g
    S = W/target_wing_loading
    c_root = 2*S/(b*(1 + lambda))
    c_tip = lambda*c_root
    AR = b^2/S
    MAC = (2/3)*c_root*(1 + lambda + lambda^2)/(1 + lambda)

  Mass closure:
    fixed_mass = pilot + fixed_nonwing + tube + fittings + wire_terminals + margin
    gross_mass = fixed_mass + wing_areal_density*S
    S_next = gross_mass*g/target_wing_loading

  Tube mass:
    mass_per_tube = rho_material*pi*((Droot*troot + 4*Dmid*tmid + Dtip*ttip)/6)*(b/2)
    tube_system_mass = mass_per_tube*num_spars_per_wing*num_wings

  Jig-shape gate:
    w = m*g/(num_wings*(b/2))
    I_tube = pi*Droot^3*troot/8
    A_tube = pi*Droot*troot
    I_wing = n_spars*I_tube + n_spars*A_tube*(spar_vertical_separation/2)^2
    delta = w*(b/2)^4/(8*E*I_wing)*taper_correction
    gate = delta/(b/2)

  Lift-wire tension:
    T = (m*g/num_wings)*limit_load_factor*wing_lift_fraction_carried

  Safe CLmax:
    safe_CLmax = max(0.10, scale*raw_CLmax - delta - tip_3d_penalty)
    tip_3d_penalty includes smooth spanwise tip penalty, taper penalty, and washout relief.

  Station CL scaling:
    CL_target_eval = CL_target_ref*(m_eval/m_ref)*(V_ref/V_eval)^2
    stall_utilization = required_CL/safe_CLmax
    required_speed_for_limit = V_eval*sqrt(stall_utilization/stall_limit)
    required_area_for_limit = S*(stall_utilization/stall_limit)

  Trim:
    CM_total = CM_airfoil + CL_wing*(x_ac - x_cg) + CM_body
    tail_volume = (S_tail/S)*(tail_arm/MAC)*q_tail_ratio*tail_efficiency
    CL_tail_required = -CM_total/tail_volume
    tail_utilization = (abs(CL_tail_required) + spread_term)/CL_tail_limit
    trim_margin_deg = max(0, 6*(CL_tail_limit - effective_tail_CL)/CL_tail_limit)

  Drag and power:
    e = clamp(e_base - k_dihedral*(dihedral_tip - dihedral_root) - k_twist*abs(twist_tip - twist_root), e_floor, e_ceiling)
    CL = W/(q*S)
    CDi = CL^2/(pi*AR*e)
    CD_misc = fuselage_misc_cd + tail_profile_coupling_factor*(S_tail/S)*profile_cd
    CD_trim = q_tail_ratio*(S_tail/S)*CL_tail_required^2/(pi*AR_tail*e_tail)
    CdA_rigging = wire_Cd*wire_diameter*wire_length
    CD_total = profile_cd + CDi + CD_misc + CD_trim + CdA_rigging/S
    Drag = q*S*CD_total
    shaft_power = Drag*V/eta_prop
    pedal_power = shaft_power/drivetrain_efficiency

  Default prop efficiency:
    eta = clamp(design_eta
                * max(speed_floor, 1 - kV*abs(V - V_peak))
                * max(power_floor, 1 - kP*abs(P_shaft - P_peak)),
                eta_floor, eta_ceiling)
    Important: default mode ignores D, RPM, blade count.

  Mission:
    endurance_s = rider_curve.duration_at_power(pedal_power)*60
    range_m = V*endurance_s
    required_duration_min = target_range_m/V/60
    available_power = rider_curve.power_at_duration(required_duration_min)
    power_margin = available_power - pedal_power
    mission passes if max feasible range >= target_range_m

Your review tasks:

1. Give a direct verdict: is this route currently decision-grade, diagnostic-only, or physically misleading?
2. Identify the top physical flaws that could explain why no concept reaches 42.195 km.
3. Separate software/automation flaws from aerospace-physics flaws.
4. Check each formula above for dimension, sign, missing term, and likely magnitude.
5. Estimate whether the latest best infeasible concept should be anywhere near feasible under HPA historical references, especially Daedalus/Light Eagle.
6. Decide whether the current search bounds are pointing the optimizer in the wrong direction.
7. Decide whether tail area 3.8..4.6 m2 is plausible for this class, or likely too large.
8. Decide whether using stationwise XFoil profile CD as aircraft-level profile CD is acceptable for concept screening.
9. Decide whether the prop model default invalidates range conclusions.
10. Decide whether 6 m/s should be a hard gate rather than report-only for this mission.
11. Suggest a corrected physics hierarchy and exact next experiments or benchmark tests.
12. Provide a ranked list of fixes with expected impact on feasibility/range.

Please be strict. If a model is not physically meaningful enough, say so. If a number is implausible, give the order-of-magnitude reason. If more information is needed, state exactly what data would decide it.
```

## Source Links For GPT Pro

- MIT News, Daedalus 20th anniversary: https://news.mit.edu/2008/daedalus-0422
- Human Powered Flight, Daedalus 88 technical details: https://www.humanpoweredflight.co.uk/aircraft/daedalus-88
- MDPI, Optimization of a Human-Powered Aircraft Using Fluid-Structure Interaction Simulations: https://www.mdpi.com/2226-4310/3/3/26
- Mark Drela, Low-Reynolds-Number Airfoil Design for the M.I.T. Daedalus Prototype - A Case Study: https://cir.nii.ac.jp/crid/1363951794290887680
