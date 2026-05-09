# Empennage / Trim / Stability Contract Audit

Date: 2026-05-09

## Executive Decision

The current pathfinder must not treat the horizontal and vertical tails as
late-stage accessories. For an all-moving horizontal tail and all-moving
vertical tail, the empennage is a shared contract for trim, static stability,
control authority, tailboom load, mission drag, and mass.

The main-wing Fourier spanload remains a main-wing design problem. The
empennage should not drive Fourier spanload candidate generation directly, but
it must enter the pipeline early as a low-order whole-aircraft contract:

```text
Mission contract
  -> tail volume / CG range / trim authority / stability contract
Fourier-AVL calibration
  -> main-wing spanload calibration remains wing-owned
Fourier spanload candidate generation
  -> tail feasibility filter only; no heavy tail solver
smooth production geometry realization
  -> instantiate physical all-moving H-tail / V-tail geometry and pivot axes
AVL realization check
  -> full-aircraft trim / stability / authority screening
structure-budgeted loaded-Z search
  -> include tail mass, trim-load envelope, and tailboom load implications
AVL recheck on realizable loaded shape
  -> full-aircraft loaded-shape trim / stability recheck
Tier2 full-alpha airfoil selection
  -> main-wing demand uses trimmed state; tail airfoils get discrete screening
aero-structure closure
  -> all-moving H-tail and V-tail become control DOFs / residual variables
FEM/APDL / shell buckling / load-factor checks
  -> tail spar, pivot, tailboom, bearing, linkage, and local hardware validation
```

This report is a contract insertion and roadmap. It is not a new full flight
dynamics solver, not an ASWing dependency, and not tail hardware sign-off.

## Existing Repo Capabilities

The repo already has reusable pieces, but they are not yet promoted into the
current Phase J pathfinder contract.

| capability | current location | current role |
|---|---|---|
| Tail-volume trim balance | `src/hpa_mdo/concept/safety.py::evaluate_trim_balance` and `src/hpa_mdo/concept/pipeline.py::_summarize_trim` | Concept-line proxy with explicit `tail_cl_required`, `tail_utilization`, and trim drag feedback |
| Tail sizing knobs | `src/hpa_mdo/concept/config.py::TailModelConfig` and `GeometryFamilyConfig` | Upstream concept sampling: tail arm, tail area / volume, CG |
| Horizontal tail geometry proxy | `src/hpa_mdo/concept/vsp_export.py::_horizontal_tail_proxy_spec` | Geometry-review proxy only, not final tail sizing |
| YAML-backed H-tail / V-fin geometry | `configs/blackcat_004.yaml`, `configs/blackcat_004_multi.yaml` | Legacy Black Cat / reusable geometry pattern |
| AVL full-aircraft exporter support | `src/hpa_mdo/aero/avl_exporter.py` | Supports wing, `h_stab`, `v_fin`, and control declarations |
| Stability parsing / campaign checks | `src/hpa_mdo/aero/avl_stability_parser.py`, `scripts/dihedral_sweep_campaign.py` | Reusable beta-sweep / directional / spiral / rudder-authority primitives |
| Tail sizing benchmark | `docs/research/hpa_tail_sizing_benchmark.md` | Legacy benchmark; useful ranges, not current pathfinder truth |

Open gap: `current_avl_compromise_conservative_closed` is locked as a
downstream main-wing / structure screening pathfinder, but it does not yet have
a promoted current empennage contract with all-moving tail geometry, CG range,
trim/stability pass criteria, tail drag/mass budget, and tail hardware load
envelope.

## Tail Contract V0

The first current-pathfinder empennage artifact should be a low-order contract,
not a solver. Its role is to define what the aircraft must be able to trim and
control before rib / rear-spar or aeroelastic closure results are over-trusted.

Minimum contract fields:

```yaml
tail_contract:
  schema_version: tail_contract_v1
  role: trim_stability_control_contract
  trust_level: screening_until_tail_fem_validated
  reference:
    pathfinder_id: current_avl_compromise_conservative_closed
    wing_area_m2: TBD
    wing_span_m: TBD
    wing_mac_m: TBD
    cg_range_x_m: [TBD_min, TBD_nominal, TBD_max]
    mission_cases:
      - name: cruise
        speed_mps: TBD
        mass_kg: TBD
        load_factor: 1.0
      - name: slow_or_launch
        speed_mps: TBD
        mass_kg: TBD
        load_factor: TBD
      - name: yaw_or_turn_correction
        speed_mps: TBD
        beta_deg: TBD
  horizontal_tail:
    type: all_moving
    design_variables:
      area_m2_range: [TBD, TBD]
      span_m_range: [TBD, TBD]
      aspect_ratio_range: [TBD, TBD]
      x_ac_m_range: [TBD, TBD]
      z_ac_m_range: [TBD, TBD]
      tail_arm_m_range: [TBD, TBD]
      incidence_zero_deg: TBD
      deflection_range_deg: [TBD_min, TBD_max]
      deflection_reserve_deg: TBD
      pivot_x_over_chord_range: [TBD, TBD]
      airfoil_candidates: [naca0009, naca0010, naca0012]
  vertical_tail:
    type: all_moving
    design_variables:
      area_m2_range: [TBD, TBD]
      height_or_span_m_range: [TBD, TBD]
      aspect_ratio_range: [TBD, TBD]
      x_ac_m_range: [TBD, TBD]
      z_ac_m_range: [TBD, TBD]
      tail_arm_m_range: [TBD, TBD]
      deflection_range_deg: [TBD_min, TBD_max]
      deflection_reserve_deg: TBD
      pivot_x_over_chord_range: [TBD, TBD]
      airfoil_candidates: [naca0008, naca0009, naca0010, naca0012]
  gates:
    longitudinal:
      require_trim_all_cases: true
      static_margin_min: TBD
      htail_cl_utilization_max: TBD
      delta_h_reserve_deg: TBD
    directional:
      cn_beta_min: TBD
      vtail_cy_utilization_max: TBD
      delta_v_reserve_deg: TBD
      yaw_roll_coupling_limit: TBD
```

The contract should explicitly say that `elevator` and `rudder` labels in legacy
AVL/control code are implementation names only. The engineering surfaces are:

```text
horizontal_tail: all-moving pitch-control lifting surface
vertical_tail: all-moving yaw-control lifting surface
```

## Minimum Equations

### Horizontal Tail

Tail volume:

```text
V_H = S_H l_H / (S_W cbar_W)
```

Effective all-moving horizontal-tail angle:

```text
alpha_H =
  alpha
  + i_H0
  + delta_H
  + theta_tailboom
  - epsilon_W(alpha)
  - alpha0_H
```

Trim requirements:

```text
L_W + L_H = W

C_m =
  C_m,W+B
  + C_L,W * (x_cg - x_ac,W) / cbar_W
  - eta_H * (S_H / S_W) * (l_H / cbar_W) * C_L,H
  = 0
```

All-moving deflection reserve:

```text
delta_H_min + delta_H_reserve <= delta_H_trim <=
delta_H_max - delta_H_reserve
```

Tail stall/utilization:

```text
abs(C_L,H / C_Lmax,H_safe) <= eta_H_tail
```

All-moving pivot moment:

```text
C_m,p,H ~= C_m,ac,H + C_L,H * ((x_ac,H - x_p,H) / cbar_H)
M_p,H = q_H S_H cbar_H C_m,p,H
```

### Vertical Tail

Vertical tail volume:

```text
V_V = S_V l_V / (S_W b_W)
```

Effective all-moving vertical-tail sideslip:

```text
beta_V =
  beta
  + i_V0
  + delta_V
  + psi_tailboom
  - sigma_W(beta)
```

Directional stability and authority:

```text
C_n_beta > C_n_beta_min

exists delta_V such that C_n(beta, delta_V) = 0
```

Deflection reserve and sideforce utilization:

```text
delta_V_min + delta_V_reserve <= delta_V_required <=
delta_V_max - delta_V_reserve

abs(C_Y,V / C_Ymax,V_safe) <= eta_V_tail
```

Yaw-roll coupling warning:

```text
C_l,V ~ Y_V z_V / (q S_W b_W)
```

## All-Moving Tail Representation

AVL `CONTROL` lines are acceptable as screening approximations, but they are not
the production representation of an all-moving tail. The production-facing
screening model should rotate the whole tail surface and rerun AVL or finite
difference the full-aircraft coefficients.

Horizontal all-moving geometry:

```text
r_H' = r_p,H + R_pitch(delta_H) * (r_H - r_p,H)
```

Vertical all-moving geometry:

```text
r_V' = r_p,V + R_yaw(delta_V) * (r_V - r_p,V)
```

Then compute control derivatives from geometry sweeps:

```text
C_m_deltaH ~= [C_m(+Delta delta_H) - C_m(-Delta delta_H)] / (2 Delta delta_H)
C_n_deltaV ~= [C_n(+Delta delta_V) - C_n(-Delta delta_V)] / (2 Delta delta_V)
```

Artifacts using hinged-control proxies must be marked:

```text
control_model = hinged_flap_proxy
trust = screening_only
```

## Tail Airfoil Policy

Tail airfoils should enter now as discrete contract variables, not as a
continuous NSGA2 search.

Short-line baseline candidates:

```text
horizontal_tail: naca0010 default, naca0012 conservative
vertical_tail: naca0009 or naca0010 default, naca0012 conservative
optional comparisons: naca0008, naca63012, fx76_100mp if coordinates are curated
```

If the current database lacks symmetric tail airfoils, generate NACA 00xx
coordinates directly:

```text
y_t = 5 t c [
  0.2969 sqrt(x)
  - 0.1260 x
  - 0.3516 x^2
  + 0.2843 x^3
  - 0.1015 x^4
]

y_u = +y_t
y_l = -y_t
```

Use a closed trailing edge coefficient such as `-0.1036` if the chosen local
airfoil tooling requires it.

Discrete screening objective:

```text
min_a  sum_j w_j CD_a(CL_j, Re_j)
     + lambda_p sum_j w_j abs(C_m,p,j)
     + lambda_s sum_j w_j max(0, abs(CL_j)/CLmax_safe_a - eta)^2
     + lambda_t P_t/c
     + lambda_r P_roughness
```

Constraints:

```text
abs(CL_tail_case / CLmax_tail_safe) <= eta_tail
abs(C_m,pivot_case) <= C_m,pivot_limit
t/c_min <= t/c <= t/c_max
require_symmetric_geometry = true
```

Do not open symmetric CST / NSGA2 until one of these is true:

- tail drag is a material fraction of total drag;
- tail power increment changes mission feasibility or candidate ordering;
- tail CL/CY utilization is near the allowed bound;
- NACA 00xx discrete choices change the pathfinder verdict;
- pivot moment / hardware mass becomes a limiter;
- clean vs rough polar sensitivity is large.

## Tail-Aware Roadmap

Current short-line order after `ConservativeLoadMapper`:

1. **Tail contract v0**: define CG range, H-tail / V-tail design boxes, all-moving
   control travel, reserves, tail airfoil candidates, tail drag/mass placeholders,
   and pass/fail criteria.
2. **All-moving full-aircraft AVL geometry generator / audit**: generate H-tail
   and V-tail incidence/deflection sweeps by rotating entire surfaces, not by
   silently relying on small-flap semantics.
3. **Longitudinal trim sweep**: solve or bracket `alpha` and `delta_H` for
   `L = W` and `C_m = 0` across cruise, slow/launch, and CG range.
4. **Directional stability / V-tail authority sweep**: compute `C_n_beta`,
   `C_n_deltaV`, `C_l_beta`, `C_l_deltaV`, required `delta_V`, and yaw-roll
   coupling warnings.
5. **Tail-aware rib / rear-spar sensitivity**: for each main-wing stiffness
   scenario, report `delta_H_required`, H-tail CL utilization, trim residual,
   tail load, and whether the scenario changes the pathfinder closure verdict.
6. **Tail airfoil discrete screening**: use trim-derived H-tail and V-tail demand
   points to rank NACA 00xx / curated symmetric candidates.
7. **Tail-aware aero-structure closure**: include `delta_H` and, when needed,
   `beta` / `delta_V` as closure variables instead of checking only main-wing
   local self-consistency.
8. **Tail FEM / hardware validation**: check tail spar, pivot, bearings, control
   linkage, tailboom bending/torsion, and all-moving pivot moments against the
   closure load package.

## Claim Boundary

This contract does not say the current pathfinder can trim or is directionally
stable. It says the current pathfinder cannot be promoted toward aircraft-level
closure until a tail contract exists and the main-wing load/stiffness work is
checked against that contract.

Engineering rule:

```text
Do not claim a main-wing pathfinder is aircraft-feasible until trim,
static stability, all-moving tail authority, tail drag, and tail mass have
at least screening-level ownership.
```
