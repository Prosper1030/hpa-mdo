# Tail Contract V0 Foundation

Date: 2026-05-09

Candidate: `current_avl_compromise_conservative_closed`

## Scope

This creates the first committed Tail / CG / Trim / Stability Contract v0
foundation for the current pathfinder. It is deliberately low-order: it defines
the all-moving horizontal-tail and vertical-tail contract variables, records the
current data sources, computes only algebraic tail volume / reserve diagnostics,
and exposes blocking missing inputs.

This is not final tail FEM, not an ASWing binary runner, not nonlinear flight
dynamics, and not an aircraft-level trim or stability pass.

Artifacts added with this foundation:

- `configs/current_pathfinder_tail_contract_v0.yaml`
- `docs/reports/2026-05-09_tail_contract_v0_screening.json`
- `scripts/tail_contract_v0_screening.py`
- `src/hpa_mdo/aero/tail_contract.py`

## Current-Truth Basis

The contract follows only the current pathfinder basis established by:

- `CURRENT_MAINLINE.md`
- `README.md`
- `docs/reports/2026-05-09_empennage_trim_stability_contract_audit.md`
- `docs/reports/2026-05-09_phase_j_evidence_map.md`
- `docs/reports/2026-05-09_pathfinder_basis_lock.md`
- `docs/reports/2026-05-09_conservative_load_mapper_foundation.md`

Old Black Cat narrative, old README framing, and old medium-search output are
not used as current pathfinder truth.

## Primitive Audit

| primitive | current role | usable for v0? | limitation |
|---|---|---:|---|
| `src/hpa_mdo/concept/safety.py::evaluate_trim_balance` | Tail-volume pitching-moment balance proxy with `tail_cl_required`, `tail_utilization`, and trim margin fields. | Yes, as equation precedent. | It is a concept proxy, not a current full-aircraft pathfinder trim result. |
| `src/hpa_mdo/concept/config.py::TailModelConfig` | Concept-stage H-tail knobs: wing AC fraction, tail arm/MAC, q ratio, efficiency, tail CL limit, AR. | Yes, as reusable vocabulary. | It does not define V-tail authority, all-moving pivot, CG range, or current pathfinder geometry. |
| `src/hpa_mdo/aero/avl_exporter.py` | Can export wing, `h_stab`, `v_fin`, and default elevator/rudder control declarations. | Yes, for the next AVL audit. | Current default controls are hinged-control implementation proxies; v0 requires all-moving semantics to be explicit. |
| `src/hpa_mdo/aero/avl_stability_parser.py` | Parses AVL `.st` derivatives and control mappings. | Yes, for the next stability sweep. | Current pathfinder has no promoted full-aircraft `.st` derivative artifact. |
| Current final package / geometry artifacts | Provide the locked wing-only downstream screening pathfinder geometry and metrics. | Yes, for wing reference values. | Final geometry export is wing-only; empennage geometry is not yet instantiated in the final package. |

## Pathfinder Wing Reference

| field | value | source | read |
|---|---:|---|---|
| `S_w` | `33.420059598 m^2` | `final_candidate_package/geometry_exports/.../geometry_manifest.json:Sref` | Filled. |
| `b_w` | `34.332286 m` | same manifest `Bref` | Filled. |
| `cbar_w` | `1.003721543 m` | same manifest `Cref` | Filled. |
| `x_ref_avl` | `0.246276512 m` | current pathfinder AVL header `#Xref` | Reference point only. |
| `x_ac_w` | missing | no current artifact found | Blocking missing input; `Xref` is not promoted as aerodynamic center. |

Engineering read: using `Xref` as an algebraic reference is acceptable for a
placeholder tail-arm screen, but not for a trim/stability claim. The true
`x_ac_w` must come from an explicit full-aircraft aerodynamic-center or moment
contract before `C_m = 0` can be trusted.

## CG Range

Current status: missing.

The contract records `reference.cg_range_x_m` as `blocking_missing` because no
committed current pathfinder CG / pilot-seat / payload manifest was found. The
concept config default `cg_xc = 0.30` exists elsewhere, but it is not promoted as
current pathfinder CG truth.

## Horizontal Tail Design Box

Seed source:
`output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_z_boundary/smooth_tier2_canonical_config.yaml:horizontal_tail`

| field | value | status |
|---|---:|---|
| Type | all-moving pitch-control lifting surface | Contract semantics; existing `elevator` label is implementation proxy. |
| `S_H` | `3.6 m^2` | Seed from current structural config, not sized by v0. |
| Span | `4.0 m` | Seed. |
| Mean chord | `0.9 m` | Seed. |
| `AR_H` | `4.444444444` | Algebraic from seed. |
| `x_ac_H` | `6.725 m` | Quarter-chord of seed tail planform. |
| `l_H` | `6.478723488 m` | Surrogate arm from `x_ac_H` to AVL `Xref`; true wing-AC arm is missing. |
| Deflection range | `[-20, 20] deg` | From current config control limit. |
| Reserve | `5 deg` | v0 screening contract placeholder. |
| Usable range after reserve | `[-15, 15] deg` | Computed by screener. |
| Pivot `x/c` | nominal `0.25`, range `[0.20, 0.30]` | All-moving screening seed, not hardware sign-off. |
| Airfoil default | `naca0010` | Discrete symmetric candidate. |
| Airfoil conservative | `naca0012` | Discrete symmetric candidate. |
| Optional comparisons | `naca0008`, `naca63012`, `fx76_100mp` | Only if coordinates/polars are curated. |

Screened algebraic result: `V_H = 0.6952987999439312`, but this is on the
AVL-`Xref` surrogate arm. It is not yet a trim pass.

## Vertical Tail Design Box

Seed source:
`output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_z_boundary/smooth_tier2_canonical_config.yaml:vertical_fin`

| field | value | status |
|---|---:|---|
| Type | all-moving yaw-control lifting surface | Contract semantics; existing `rudder` label is implementation proxy. |
| `S_V` | `1.68 m^2` | Seed from current structural config, not sized by v0. |
| Height/span | `2.4 m` | Seed. |
| Mean chord | `0.7 m` | Seed. |
| `AR_V` | `3.428571429` | Algebraic from seed. |
| `x_ac_V` | `7.175 m` | Quarter-chord of seed vertical planform. |
| `z_ac_V` | `0.5 m` | Midpoint of seed vertical extent from `z=-0.7` to `z=1.7 m`. |
| `l_V` | `6.928723488 m` | Surrogate arm from `x_ac_V` to AVL `Xref`; true wing-AC arm is missing. |
| Deflection range | `[-25, 25] deg` | From current config control limit. |
| Reserve | `5 deg` | v0 screening contract placeholder. |
| Usable range after reserve | `[-20, 20] deg` | Computed by screener. |
| Pivot `x/c` | nominal `0.25`, range `[0.20, 0.30]` | All-moving screening seed, not hardware sign-off. |
| Airfoil default | `naca0009` or `naca0010` | Discrete symmetric candidate. |
| Airfoil conservative | `naca0012` | Discrete symmetric candidate. |
| Optional comparisons | `naca0008`, `naca63012`, `fx76_100mp` | Only if coordinates/polars are curated. |

Screened algebraic result: `V_V = 0.01014501211088028`, again on the AVL-`Xref`
surrogate arm. Engineering caution: this is low enough that directional
authority could easily become a blocker, but the repo does not yet have
`C_n_beta`, `C_n_deltaV`, beta case definition, or yaw-roll coupling limits, so
v0 must not claim pass/fail.

## Budget Placement

Tail drag placeholder:

- Add tail profile drag and trim-induced drag as deltas to candidate
  `CD0_total` / `CD_total`.
- Recompute `P_crank` and `P_crank_conservative` per trimmed case.
- Required next inputs: all-moving AVL sweep or equivalent tail load cases,
  tail q-ratio, and discrete tail-airfoil polars.

Tail mass placeholder:

- Add H-tail, V-tail, pivot, bearing, linkage, and tailboom increments to total
  aircraft mass.
- Update CG range before solving longitudinal trim.
- Required next inputs: tail mass model, tailboom layout, pivot hardware
  allowance, and payload/pilot-seat CG manifest.

## Screening Output

`docs/reports/2026-05-09_tail_contract_v0_screening.json` reports:

```json
{
  "status": "required_inputs_missing",
  "computed": {
    "horizontal_tail": {
      "tail_volume_coefficient": 0.6952987999439312,
      "usable_deflection_range_deg": [-15.0, 15.0]
    },
    "vertical_tail": {
      "tail_volume_coefficient": 0.01014501211088028,
      "usable_deflection_range_deg": [-20.0, 20.0]
    }
  }
}
```

Important: this output only proves that the v0 contract has traceable
bookkeeping for volume and reserve. It explicitly does not prove trim,
stability, control authority, tail drag, or tail mass closure.

## Blocking Missing Inputs

The screener and YAML list the current blockers:

- `reference.wing.x_ac_w_m`
- `reference.cg_range_x_m`
- slow/launch trim case speed and load factor
- yaw/turn beta case
- H-tail safe `C_Lmax` for discrete airfoils
- wing downwash model `epsilon_W(alpha)`
- wing-body pitching moment contract `C_m_WB`
- all-moving H-tail control derivative or geometry sweep
- V-tail safe `C_Ymax`
- full-aircraft `C_n_beta`
- all-moving V-tail control derivative or geometry sweep
- yaw-roll coupling limit
- tail drag model charged to mission power
- tail mass/hardware model charged to mass and CG

## Required Equations

Horizontal tail volume:

```text
V_H = S_H l_H / (S_W cbar_W)
```

Effective all-moving horizontal-tail angle:

```text
alpha_H =
  alpha + i_H0 + delta_H + theta_tailboom - epsilon_W(alpha) - alpha0_H
```

Longitudinal trim:

```text
L_W + L_H = W

C_m =
  C_m,W+B
  + C_L,W * (x_cg - x_ac,W) / cbar_W
  - eta_H * (S_H / S_W) * (l_H / cbar_W) * C_L,H
  = 0
```

Horizontal-tail deflection reserve and utilization:

```text
delta_H_min + delta_H_reserve <= delta_H_trim <=
delta_H_max - delta_H_reserve

abs(C_L,H / C_Lmax,H_safe) <= eta_H_tail
```

All-moving pivot moment:

```text
C_m,p,H ~= C_m,ac,H + C_L,H * ((x_ac,H - x_p,H) / cbar_H)
M_p,H = q_H S_H cbar_H C_m,p,H
```

Vertical tail volume:

```text
V_V = S_V l_V / (S_W b_W)
```

Effective all-moving vertical-tail sideslip:

```text
beta_V =
  beta + i_V0 + delta_V + psi_tailboom - sigma_W(beta)
```

Directional requirements:

```text
C_n_beta > C_n_beta_min
exists delta_V such that C_n(beta, delta_V) = 0
```

Vertical-tail reserve, utilization, and yaw-roll warning:

```text
delta_V_min + delta_V_reserve <= delta_V_required <=
delta_V_max - delta_V_reserve

abs(C_Y,V / C_Ymax,V_safe) <= eta_V_tail

C_l,V ~ Y_V z_V / (q S_W b_W)
```

## Engineering Verdict

Go/no-go for this task: go for foundation, no-go for aircraft feasibility.

The contract now gives the pathfinder an explicit all-moving tail bookkeeping
surface and blocks over-claiming when CG, true wing aerodynamic center,
downwash, stability derivatives, tail drag, and tail mass are absent. The
horizontal-tail seed volume is plausible for a first HPA screening envelope, but
the vertical-tail seed volume is small enough to deserve early directional
stability scrutiny. The next engineering step should be the all-moving
full-aircraft AVL geometry / trim-stability audit, not ASWing binary work and
not final tail FEM.
