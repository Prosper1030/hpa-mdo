# Dual-Beam Mainline Theory Spec

Date: 2026-04-11 CST

## 0. Scope And Evidence Status

This document defines the proposed dual-beam mainline theory from structural
mechanics first, then maps it to implementation-ready equations. It is not a
solver patch, benchmark note, guardrail proposal, or optimizer tuning recipe.
Core solver logic is intentionally unchanged by this document.

The goal is a fast structural design front end that is not too optimistic and
does not collapse under higher-fidelity inspection. ANSYS is not the optimizer.
ANSYS is used to validate assumptions, detect model-form risk, and inspect
candidate rankings.

### Evidence Used

Repo evidence:

- `docs/ansys_equivalent_beam_validation_pass.md`
- `docs/dual_spar_spotcheck_workflow.md`
- `docs/direct_dual_beam_v1_research.md`
- `docs/dual_beam_v2_mainline_spec.md`
- `output/blackcat_004/ansys/crossval_report.txt`
- `output/blackcat_004_internal_dual_beam_smoke_with_ansys/dual_beam_internal_report.txt`
- `output/blackcat_004_dual_beam_refinement/dual_beam_refinement_report.txt`
- `output/blackcat_004_dual_beam_refinement/ansys_refined/spotcheck_summary.txt`
- `output/guardrail_experiment/guardrail_summary.json`
- `output/dual_beam_path_benchmark_v1_baseline/benchmark_report.txt`
- `output/direct_dual_beam_v1_baseline/direct_dual_beam_v1_report.txt`
- `src/hpa_mdo/structure/spar_model.py`
- `src/hpa_mdo/structure/components/spar_props.py`
- `src/hpa_mdo/structure/components/loads.py`
- `src/hpa_mdo/structure/fem/elements.py`
- `src/hpa_mdo/structure/fem/assembly.py`
- `src/hpa_mdo/structure/dual_beam_analysis.py`
- `src/hpa_mdo/structure/ansys_export.py`
- `scripts/dual_beam_refinement.py`
- `scripts/direct_dual_beam_v1.py`
- `scripts/benchmark_dual_beam_paths.py`
- `tests/test_partials.py`
- `tests/test_spar_properties_partials.py`
- `tests/test_dual_beam_analysis.py`
- `tests/test_internal_dual_beam_regression.py`
- `tests/test_direct_dual_beam_v1.py`

### What Is Verified

- Equivalent-beam internal FEM versus equivalent-beam ANSYS passes the official
  Phase I validation gate: tip and max vertical displacement error 0.67%,
  support reaction error about 0%, full-span spar beam mass error 0.17%.
- The inspected internal dual-beam topology matches dual-spar ANSYS closely:
  main tip 0.56% error, max `|UZ|` 0.51% error, support reaction 0.00% error,
  full-span spar beam mass 0.18% error.
- The model-form issue is real: equivalent optimum evaluated as dual-beam has
  rear tip / max `|UZ|` at about 3374 mm versus main tip about 2838 mm.
- A rear/main radius-ratio guardrail failed as a primary fix: mass increased
  about 3.26%, while dual-beam max `|UZ|` became about 0.16% worse.
- Hybrid and reduced V1 improve the dual-beam response to the same engineering
  band, but both are still transition paths, not a rebuilt theory.
- The current dual-beam raw active displacement is rear outboard, node 60, in
  the Black Cat 004 baseline.

### Reasonable Inferences

- The dominant mechanism is not equivalent-solver error. It is load-path and
  rear-outboard amplification in a two-spar structure with wire support,
  aerodynamic torque couple, sparse joint/rib links, and weak rear outboard
  bending stiffness.
- Radius is a higher displacement-per-mass lever than wall thickness near the
  current design. Thickness remains important for stress, buckling, local
  reserve, and manufacturable reinforcement.
- The current joint-only equal-DOF link topology is a useful ANSYS-parity mode,
  but it is not by itself a complete physical rib model.
- Dual-beam production loads should place spar self-weight on the actual spar
  lines. The rear-gravity torque used in equivalent-beam mode is a collapsed
  single-beam representation, not a separate physical load needed when the rear
  spar is an explicit beam.

### Not Yet Proven

- The physical stiffness of balsa ribs, tube joints, and fittings has not been
  calibrated.
- Dual-beam stress and buckling recovery has not been validated against
  apples-to-apples ANSYS beam/fiber extraction.
- The best robust link mode for production ranking is not yet proven.
- The proposed rear-outboard local reserve mapping must be benchmarked before
  it becomes a production default.

## Part 1. Dual-Beam Problem From First Principles

### 1A. Geometry, Coordinates, And Degrees Of Freedom

#### Spanwise Discretization

Use a half-wing structural model. Let:

- `N`: number of structural nodes per spar.
- `E = N - 1`: number of beam elements per spar.
- `i = 0, ..., N-1`: node index, root to tip.
- `e = 0, ..., E-1`: element index between nodes `e` and `e+1`.
- `k = 1, ..., K`: tube segment index, root to tip.
- `s in {m, r}`: spar index, main and rear.
- `y_i`: spanwise station.
- `c_i`: local chord.
- `x_m,i = x_m/c * c_i`, `x_r,i = x_r/c * c_i`.
- `z_m,i`, `z_r,i`: dihedral plus airfoil camber offsets.

The nodal coordinates are:

```text
p_m,i = [x_m,i, y_i, z_m,i]^T
p_r,i = [x_r,i, y_i, z_r,i]^T
d_i   = p_r,i - p_m,i
d_x,i = x_r,i - x_m,i
```

The current Black Cat 004 config has `x_m/c = 0.25`, `x_r/c = 0.70`, so
`d_x = 0.45 c` at each span station.

#### Beam Local Coordinate System

For each spar element `e`, define:

```text
l_s,e = p_s,e+1 - p_s,e
L_s,e = sqrt(l_s,e^T l_s,e)
e1_s,e = l_s,e / L_s,e
```

`e1` is the local beam axial direction. Choose a reference vector that is not
parallel to `e1`, then construct:

```text
e2_s,e = normalize(ref x e1_s,e)
e3_s,e = e1_s,e x e2_s,e
R_s,e  = [e1_s,e; e2_s,e; e3_s,e]
```

`R_s,e` maps global translational or rotational components into the element
local frame. This follows the same convention as `fem/elements.py`.

#### Nodal DOF

Each beam node has six small-displacement DOF:

```text
q_s,i = [u_x, u_y, u_z, theta_x, theta_y, theta_z]^T_s,i
```

The global unknown vector is:

```text
q = [q_m,0, ..., q_m,N-1, q_r,0, ..., q_r,N-1]^T
q in R^(12N)
```

The existing internal dual-beam implementation stores these as
`disp_main[N,6]` and `disp_rear[N,6]`.

#### Beam Chain Continuity

Adjacent tube segments share the same nodal DOF at segment boundaries:

```text
q_s,k^- = q_s,k^+
```

A tube splice joint is therefore not a new displacement DOF in the first
mainline model. Its effects enter through:

- local section change,
- joint mass,
- optional local stiffness/fitting reserve,
- cross-spar link station if a rib/joint fitting connects both spars.

#### Root Boundary

Baseline dual-beam root condition:

```text
q_m,0 = 0
q_r,0 = 0
```

This matches the current `dual_spar` inspection export and internal
`dual_beam_analysis.py`. Future root-box flexibility must be a named BC mode,
not a silent change.

#### Wire Attachment

Current parity condition:

```text
u_z,m,w = 0
```

where `w` is the main-spar node nearest the configured lift-wire attachment
station. The current code does not directly constrain the rear spar at the wire
node; rear support load enters through rib/joint links.

Production wire model should be one scalar axial constraint or spring:

```text
n_w^T u_m,w = 0                         rigid inextensible wire
f_w = k_w n_w n_w^T u_m,w               finite axial wire stiffness
```

where `n_w` points along the wire from spar attachment to fuselage attachment.
If using a taut-only cable model, compression must be excluded by active-set
logic outside the smooth optimizer loop or handled by a smooth tension-only
regularization. The near-term derivative-friendly production mode should keep
the verified vertical support and separately recover wire reaction.

#### Rib And Joint Link Kinematics

There are two physically different concepts:

- tube splice joint: continuity and reinforcement along one spar line.
- rib or cross-spar fitting: kinematic relation between main and rear spar
  nodes at a station.

For a small rigid rib at station `i`, the physically offset-aware rigid-body
relation is:

```text
u_r,i = u_m,i + theta_m,i x d_i
theta_r,i = theta_m,i
```

Using the skew matrix `S(d)` where `S(d) a = d x a`, this becomes:

```text
c_i(q) =
[
  u_r,i - u_m,i + S(d_i) theta_m,i
  theta_r,i - theta_m,i
] = 0
```

Equivalently, one may use the average rotation in the translational constraint:

```text
u_r,i - u_m,i + S(d_i) (theta_m,i + theta_r,i)/2 = 0
theta_r,i - theta_m,i = 0
```

The average-rotation form is symmetric and recommended for the mainline finite
link component. When `theta_r = theta_m`, both forms are equivalent.

Current parity mode is different:

```text
q_r,i - q_m,i = 0
```

This equal-DOF relation is what current `dual_beam_analysis.py` and
`ansys_export.py` use at joint nodes. It is verified against the inspected
ANSYS topology, but it is not the final physical rib kinematic law.

#### Finite Link Energy

A finite rib/link can be represented by constraint strain `c_i(q)` and link
stiffness `K_link,i`:

```text
U_link,i = 0.5 c_i(q)^T K_link,i c_i(q)
f_link,i = C_i^T K_link,i c_i(q)
```

where `C_i = partial c_i / partial q`. Rigid links are the limit
`K_link -> infinity`, but implementation should prefer Lagrange multipliers or
constraint elimination over very large penalties.

Recommended link modes:

```text
joint_only_equal_dof_parity
    Current ANSYS-parity mode. Use for regression and comparison only.

joint_only_offset_rigid
    Rigid links at tube joint stations with offset-aware kinematics.

dense_offset_rigid
    Offset-aware rigid links at physical rib stations.

dense_finite_rib
    Offset-aware finite translational/rotational rib stiffness. This is the
    production robustness target after rib properties are available.
```

### 1B. Material And Section Formulas

For a circular hollow tube with outer radius `R` and wall thickness `t`:

```text
r_i = R - t
A(R,t) = pi (R^2 - r_i^2) = pi (2 R t - t^2)
I(R,t) = pi/4 (R^4 - r_i^4)
J(R,t) = pi/2 (R^4 - r_i^4) = 2 I(R,t)
```

For each spar `s` and element `e`:

```text
A_s,e  = A(R_s,e, t_s,e)
Iy_s,e = I(R_s,e, t_s,e)
Iz_s,e = I(R_s,e, t_s,e)
J_s,e  = J(R_s,e, t_s,e)
EIy_s,e = E_s Iy_s,e
EIz_s,e = E_s Iz_s,e
GJ_s,e  = G_s J_s,e
mu_s,e  = rho_s A_s,e
```

Material constants:

```text
E_s   = Young's modulus [Pa]
G_s   = shear modulus [Pa]
rho_s = density [kg/m^3]
nu_s  = Poisson ratio, used for export/report if needed
```

Allowable stress:

```text
sigma_allow_s = min(sigma_tension_s, sigma_compression_s) / SF_material
```

The repo already uses this rule in the equivalent-beam and dual-beam reporting
paths. Stress remains non-gating for dual-beam until validated.

#### Section Derivatives

These analytic partials are already implemented and complex-step verified in
the equivalent section component:

```text
dA/dt = 2 pi (R - t)
dA/dR = 2 pi t

dI/dt = pi (R - t)^3
dI/dR = pi (R^3 - (R - t)^3)

dJ/dt = 2 pi (R - t)^3
dJ/dR = 2 pi (R^3 - (R - t)^3)
```

#### Local Rear-Outboard Reserve

A rear-outboard reserve must represent a physical addition to section stiffness
and mass. It should not be a free, massless `EI` multiplier.

Recommended first physical proxy:

```text
t_r,k = t_r,k_base + Delta_t_global + b_ob,k Delta_t_rear_ob
R_r,k = R_r,k_base_scaled
```

where `b_ob,k` is a manufacturing basis active over the rear outboard reserve
region, for example:

```text
b_ob,k = 0 for k < k_ob_start
b_ob,k = 1 for k >= k_ob_start
```

Then:

```text
EI_rear_ob,e = E_r I(R_r,e, t_r,e)
GJ_rear_ob,e = G_r J(R_r,e, t_r,e)
mu_rear_ob,e = rho_r A(R_r,e, t_r,e)
```

This represents a local sleeve, wrap, or layup reserve. It preserves outer
radius taper when `R_r` is fixed or globally scaled, while still paying mass
and changing stress/buckling through the same tube formulas.

If future data supports a ply-level proxy, replace the scalar wall-thickness
reserve with laminate stiffness resultants:

```text
EI_s,e = E_axial,eff,e I_e
GJ_s,e = G_torsion,eff,e J_e
mu_s,e = rho_lam,e A_e
```

but this must still include a mass model and allowable model.

### 1C. Element Stiffness And Global Assembly

Use a 3-D Timoshenko beam element with 6 DOF per node and local DOF order:

```text
[u, v, w, theta_x, theta_y, theta_z]_i,
[u, v, w, theta_x, theta_y, theta_z]_j
```

Let:

```text
kappa_s = shear correction factor, current code uses 0.5
GA = kappa_s G A
phi_y = 12 E Iz / (GA L^2)
phi_z = 12 E Iy / (GA L^2)
```

The local stiffness is the sum of axial, torsion, and two bending blocks.

Axial block on DOF `[u_i, u_j]`:

```text
(EA/L) [[ 1, -1],
        [-1,  1]]
```

Torsion block on DOF `[theta_x,i, theta_x,j]`:

```text
(GJ/L) [[ 1, -1],
        [-1,  1]]
```

Vertical bending in the local `x-z` plane on DOF
`[w_i, theta_y,i, w_j, theta_y,j]`:

```text
c_z = E Iy / (L^3 (1 + phi_z))

c_z *
[[ 12,        6L,       -12,        6L],
 [  6L, (4+phi_z)L^2,   -6L, (2-phi_z)L^2],
 [-12,       -6L,        12,       -6L],
 [  6L, (2-phi_z)L^2,   -6L, (4+phi_z)L^2]]
```

Lateral bending in the local `x-y` plane on DOF
`[v_i, theta_z,i, v_j, theta_z,j]`:

```text
c_y = E Iz / (L^3 (1 + phi_y))

c_y *
[[ 12,       -6L,       -12,       -6L],
 [ -6L, (4+phi_y)L^2,    6L, (2-phi_y)L^2],
 [-12,        6L,        12,        6L],
 [ -6L, (2-phi_y)L^2,    6L, (4+phi_y)L^2]]
```

For each element:

```text
T_e = blockdiag(R_e, R_e, R_e, R_e)
k_global_e = T_e^T k_local_e T_e
```

Assemble:

```text
K_beam = sum_e A_e^T k_global_e A_e
```

where `A_e` is the Boolean scatter matrix from element DOF to global DOF.

#### Constraint Assembly

For rigid constraints:

```text
C q = c0
```

Preferred solve:

```text
[K  C^T] [q     ] = [f]
[C   0 ] [lambda]   [c0]
```

or eliminate constrained DOF exactly when the constraint topology is simple.

Current penalty parity solve:

```text
K_pen = K + alpha_bc C_bc^T C_bc + alpha_link C_link^T C_link
f_pen = f + alpha_bc C_bc^T c_bc + alpha_link C_link^T c_link
```

This is useful for parity and smoke tests, but it is not the derivative-enabled
mainline target because conditioning depends on arbitrary penalty magnitude.

For finite ribs:

```text
K = K_beam + sum_i C_i^T K_link,i C_i
f = f_beam + f_external
```

Link force recovery:

```text
lambda_i = K_link,i c_i(q)
```

Rigid link multiplier recovery:

```text
lambda = solution multiplier from the saddle-point system
```

#### Static Solve

The primal static state solves:

```text
K(q-independent design) q = f
```

with linear material and small displacement assumptions. More explicitly:

```text
q = K(x)^(-1) f(x)
```

where `x` denotes design variables after geometry mapping.

### 1D. Load Model

Define node tributary length:

```text
Delta y_0     = (y_1 - y_0)/2
Delta y_i     = (y_{i+1} - y_{i-1})/2, i = 1..N-2
Delta y_N-1   = (y_N-1 - y_N-2)/2
```

For any distributed quantity `q(y)`:

```text
Q_i ~= q_i Delta y_i
```

This matches the existing trapezoidal nodal load mapping.

#### Aerodynamic Lift And Pitching Moment

Let:

- `l_i`: aerodynamic lift per span at node `i`, positive upward.
- `m_y,i`: aerodynamic pitching moment per span about the spanwise axis, using
  the existing sign convention where positive `M_y` is represented by `+F_z`
  on main and `-F_z` on rear in current dual-spar parity.
- `d_x,i = x_r,i - x_m,i > 0`.

The two vertical nodal load components should satisfy:

```text
F_m,i + F_r,i = l_i Delta y_i
M_y,i = -d_x,i F_r,i
```

Thus:

```text
F_r,i = -m_y,i Delta y_i / d_x,i
F_m,i =  l_i Delta y_i + m_y,i Delta y_i / d_x,i
```

This is the current `dual_spar` parity torque-couple convention.

If future aerodynamic data reports lift at a center of pressure `x_cp` and a
pitching moment about a different reference `x_ref`, convert first to a single
spanwise moment about the main spar:

```text
M_y,about_main = M_y,about_ref - (x_cp - x_m) L
```

with sign checked against the `r x F` convention used by the implementation.
Then use the same vertical couple equation.

#### Self-Weight In Explicit Dual-Beam Production Mode

When main and rear are explicit beam lines, spar self-weight should be applied
at the spar where the mass exists:

```text
W_m,e = n_z g rho_m A_m,e L_m,e
W_r,e = n_z g rho_r A_r,e L_r,e
```

Lump to the element endpoints:

```text
F_z,m,e_left  -= W_m,e/2
F_z,m,e_right -= W_m,e/2
F_z,r,e_left  -= W_r,e/2
F_z,r,e_right -= W_r,e/2
```

In this explicit dual-beam production model, rear spar gravity torque is not a
separate load. It is created naturally because rear weight acts on the rear
beam line at `x_r`, aft of the main spar.

#### Rear-Gravity Torque In Equivalent-Beam Mode

In the collapsed equivalent-beam model, rear spar self-weight cannot create a
moment through spatial separation because there is only one beam line. The repo
therefore adds a single-beam torsional moment:

```text
M_y,rear_gravity,e = -n_z g rho_r A_r,e d_x,e L_e
```

lumped to adjacent nodes. This is verified as part of the equivalent-beam
validation package, but it should not be double-counted in explicit dual-beam
production mode.

#### Load Modes

```text
equivalent_validation
    One equivalent beam. Nodal Fz includes lift plus total spar self-weight.
    Nodal My includes aerodynamic torque plus rear-gravity torque. This mode is
    verified against equivalent-beam ANSYS and remains the official Phase I
    solver gate.

dual_spar_ansys_parity
    Two beam lines. Lift on main, aerodynamic torque as vertical main/rear
    couple, fixed roots on both spars, main wire UZ constraint, joint-only
    equal-DOF links. Current inspected internal dual-beam and ANSYS agree in
    this mode.

dual_beam_production
    Two beam lines. Lift and aerodynamic torque split by force/moment balance.
    Main and rear self-weight applied on their own beam lines. Wire support
    applied at main attachment. Links use named physical link mode. This is the
    target mainline analysis mode.

dual_beam_robustness
    Same production loads, but repeated over link modes such as joint-only,
    dense rigid, and dense finite-rib to expose topology sensitivity.
```

### 1E. Boundary Condition Modes

```text
root_fixed_both
    q_m,0 = 0 and q_r,0 = 0. Current parity and near-term production default.

root_main_fixed_rear_linked
    q_m,0 = 0 and rear root constrained through an offset-aware root-box link.
    Future root fitting study only.

wire_main_vertical
    u_z,m,w = 0. Current verified support abstraction.

wire_main_axial
    n_w^T u_m,w = 0 or finite k_w n_w n_w^T spring. Future production upgrade
    after wire reaction and compression path are validated.

joint_only_equal_dof_parity
    q_r,i - q_m,i = 0 at tube joint stations. Verified against current ANSYS
    inspection topology, not final physical rib law.

joint_only_offset_rigid
    c_i(q) = 0 at tube joint stations using offset-aware rigid-link kinematics.

dense_finite_rib
    finite K_link,i at physical rib stations. Target robustness mode.
```

All reports and benchmark artifacts must print the chosen load mode, root mode,
wire mode, and link mode. A design that is feasible only under one fragile link
mode is not a mainline production success.

## Part 2. Solved Quantities And Optimizer-Facing Quantities

### 2A. State And Solved Quantities

Primary solved state:

```text
q_m = u_main[N,6]
q_r = u_rear[N,6]
```

Recovered equilibrium quantities:

```text
R_root_m[6], R_root_r[6]
R_wire
lambda_link[i,6] or finite-link force/moment resultants
F_applied_m[N,6], F_applied_r[N,6]
```

Element recovery:

```text
epsilon_axial_s,e
kappa_y_s,e, kappa_z_s,e
gamma_torsion_s,e
N_s,e, V_s,e, M_y_s,e, M_z_s,e, T_s,e
sigma_vm_s,e
local_buckling_ratio_s,e
torsion_shear_buckling_ratio_s,e
```

Mass quantities:

```text
spar_tube_mass_half
spar_tube_mass_full
joint_mass_half
joint_mass_full
total_structural_mass_full
```

Current `dual_beam_analysis.py` already provides `u_main`, `u_rear`, raw max
displacement, mass, and provisional stress. It does not yet recover root/wire
partition or link forces in a physically complete way.

### 2B. Quantities Allowed Into The Optimizer

Allowed, once implemented in smooth form:

```text
objective:
    minimize total_structural_mass_full

hard constraints:
    smooth dual-beam max |UZ| <= limit
    validated equivalent failure KS <= 0, until dual failure is validated
    validated equivalent buckling KS <= 0, until dual buckling is validated
    smooth twist KS <= twist limit, if twist remains a gate
    geometry constraints: R - t >= inner radius margin
    t/R constraints
    monotone radius taper, preferably by construction
    thickness step <= configured limit, preferably by construction
    solve finite and repeatable
```

Dual stress and dual buckling may become optimizer constraints only after an
apples-to-apples validation path exists.

### 2C. Report-Only Quantities

Do not use these directly as optimizer objectives or hard active constraints:

```text
raw max |UZ|
raw argmax spar
raw argmax node id
raw rear/main tip ratio
raw active node location
raw support reaction partition before recovery is validated
raw link hot-spot force before link model is calibrated
dual stress/failure before validation
ANSYS spot-check classification
catalog-snapped geometry outcomes
```

They are essential engineering report fields, but their raw forms are
nonsmooth, topology-sensitive, or not yet validated.

### 2D. Required Smoothing And Aggregation

#### Smooth Absolute Value

Use:

```text
abs_eps(x) = sqrt(x^2 + eps_abs^2)
```

Recommended displacement default:

```text
eps_abs_u = 1e-6 m
```

Use engineering-scale epsilon values, not machine epsilon, to avoid singular
derivatives near zero.

#### KS Smooth Maximum

For a vector `g_i`, define:

```text
KS_rho(g) = g_shift + (1/rho) log(sum_i exp(rho (g_i - g_shift)))
```

where `g_shift = max(real(g_i))` is used only for numerical stability. The
mathematical quantity is smooth log-sum-exp.

For displacement in meters:

```text
a_i = abs_eps(UZ_i) / u_scale
psi_u = u_scale KS_rho_u(a)
g_u = psi_u / u_limit - 1
```

Recommended:

```text
u_scale = max(u_limit, warm_dual_raw_max_uz, 1e-3 m)
rho_u = 50 to 100
```

The solver should output at least:

```text
psi_u_all          = smooth max over main and rear nodes
psi_u_rear         = smooth max over rear nodes
psi_u_rear_outboard = smooth max over rear nodes after the last main/rear joint
```

Only `psi_u_all` should be the first production hard displacement gate.
`psi_u_rear` and `psi_u_rear_outboard` are optimizer-eligible diagnostic
constraints only after sensitivity to link mode is understood.

#### Smooth Norm

For vector quantities such as link force resultants:

```text
norm_eps(v) = sqrt(sum_j v_j^2 + eps_v^2)
```

Then aggregate:

```text
psi_link = KS_rho(norm_eps(lambda_i) / lambda_scale)
```

Do not gate link forces until link stiffness and allowable loads are calibrated.

#### Failure Aggregation

For stress:

```text
r_sigma,s,e = sigma_vm,s,e / sigma_allow_s - 1
g_failure = KS_rho_sigma({r_sigma,s,e})
```

Feasible if:

```text
g_failure <= 0
```

For local buckling:

```text
r_buckling,s,e = demand_s,e / critical_s,e - 1
g_buckling = KS_rho_b({r_buckling,s,e})
```

Feasible if:

```text
g_buckling <= 0
```

The repo already uses KS failure and buckling in the equivalent-beam path.
Those remain the validated gates until the dual recovery path is validated.

#### Smooth Ratio If A Loose Guard Is Needed

Rear/main tip ratio should be report-only by default. If a loose pathology guard
is temporarily needed:

```text
ratio_tip_smooth =
    abs_eps(u_z,r,N-1) / (abs_eps(u_z,m,N-1) + delta_tip)
```

with `delta_tip` around `1e-3 m`. This guard must not be the primary objective
or the main feasibility target.

## Part 3. Physics-Driven Design Variables And Mapping

### 3A. High-Leverage Design Freedom

Verified local sensitivity around the equivalent optimum shows:

- main radius segments 3-4 are the strongest bending lever;
- a taper-preserving main segments 1-4 plateau is the realistic way to use
  that lever;
- main outboard radius has secondary but real effect;
- rear global radius controls rear amplification without violating taper;
- rear outboard needs a local reserve, but free outboard OD violates monotone
  taper unless upstream rear spar grows too;
- thickness is less efficient for displacement per mass, but important for
  local reserve, stress, buckling, and manufacturable layup changes.

### 3B. Variables That Should Be Tied

Tie these in the first mainline direct design space:

```text
main segments 1-4 radius
    They form the bending plateau that carries the high-leverage midspan
    region while preserving monotone taper.

main segments 5-6 taper recovery
    Treat as one outboard tail-shape variable before allowing per-segment
    movement.

rear global radius
    The current rear baseline is at minimum radius across the span; global
    scaling is the clean taper-safe OD lever.

global wall thickness reserve
    Keep initial wall changes tied across spars to avoid optimizer chatter in
    low-leverage local thickness variables.

rear outboard sleeve reserve
    Localize reserve to the rear outboard mode, but express it as added
    thickness/layup with mass, not as a massless stiffness multiplier.
```

### 3C. Variables That Should Not Be Free In V1 Mainline

Do not initially let the optimizer freely move:

```text
all 24 segment t/R variables independently
individual rear outboard OD without upstream taper enforcement
rib stiffness/link topology as an optimizer knob
spar chordwise locations
wire attachment node
segment break positions
catalog OD snapping
raw support/link force targets
unvalidated dual stress/buckling gates
```

These can be studied later, but the first mainline direct space should not mix
structural physics, manufacturing choices, and unvalidated topology knobs.

### 3D. Monotone Taper By Construction

Prefer a parameterization that produces:

```text
R_s,1 >= R_s,2 >= ... >= R_s,K
```

without relying on scalar min margins. A general construction is:

```text
R_s,1 = R_s,root
R_s,k+1 = R_s,k - softplus(delta_s,k)
```

where `softplus(z) = log(1 + exp(z)) / beta` after suitable scaling. This is
smooth but adds variables.

For the minimal Black Cat 004 V1 mainline, use a lower-dimensional grouped
construction that is monotone by design:

```text
P_m  = R_m,4^0 exp(a_m)
D45  = (R_m,4^0 - R_m,5^0) exp(-b_m)
D56  = (R_m,5^0 - R_m,6^0) exp(-b_m)

R_m,k = P_m                    for k = 1..4
R_m,5 = P_m - D45
R_m,6 = P_m - D45 - D56
```

with bounds chosen so:

```text
R_m,6 >= R_min
R_m,1 <= R_max
D45 >= 0
D56 >= 0
```

Increasing `a_m` raises the inboard/mid plateau. Increasing `b_m` fills in the
outboard taper by shrinking the drops, which raises segments 5-6 while keeping
root-to-tip monotone.

For the rear spar current baseline, use:

```text
R_r,k = P_r = R_r,base exp(a_r),  k = 1..6
```

This is monotone because all rear segments are tied.

### 3E. Thickness Step By Construction

Use additive thickness reserves:

```text
t_m,k = t_m,k^0 + Delta_t_global
t_r,k = t_r,k^0 + Delta_t_global + b_ob,k Delta_t_rear_ob
```

with:

```text
0 <= Delta_t_global
0 <= Delta_t_rear_ob <= max_thickness_step
```

If the base thickness vector already satisfies the step rule, then the global
addition preserves all steps. The rear outboard addition creates one step at
`k_ob_start`, bounded by construction.

Also enforce:

```text
t_s,k <= eta_tR R_s,k
R_s,k - t_s,k >= r_inner_min_s
t_s,k <= t_max
```

These may be explicit smooth constraints in V1, then migrated into the mapping
bounds when possible.

### 3F. Recommended V1 Minimal Direct Dual-Beam Mainline Variables

Use five continuous variables:

```text
x = [a_m, b_m, a_r, eta_ob, eta_t]
```

Meaning:

```text
a_m:
    main inboard/mid plateau radius log scale.

b_m:
    main outboard taper-fill variable. Higher b_m shrinks the 4-5 and 5-6
    radius drops and raises the outboard tail without violating taper.

a_r:
    rear global radius log scale.

eta_ob:
    rear outboard sleeve/layup reserve fraction.

eta_t:
    global wall thickness reserve fraction.
```

Mapping:

```text
P_m  = R_m,4^0 exp(a_m)
D45  = (R_m,4^0 - R_m,5^0) exp(-b_m)
D56  = (R_m,5^0 - R_m,6^0) exp(-b_m)

R_m,1:4 = P_m
R_m,5   = P_m - D45
R_m,6   = P_m - D45 - D56

R_r,k = R_r,k^0 exp(a_r)

Delta_t_global =
    eta_t Delta_t_global_max

Delta_t_rear_ob =
    eta_ob Delta_t_rear_ob_max

t_m,k = t_m,k^0 + Delta_t_global
t_r,k = t_r,k^0 + Delta_t_global + b_ob,k Delta_t_rear_ob
```

For the current six-segment layout:

```text
b_ob = [0, 0, 0, 0, 1, 1]
```

Bounds:

```text
0 <= a_m <= log(R_m_plateau_max / R_m,4^0)
0 <= b_m <= b_m_max
0 <= a_r <= log(R_r_max / R_r^0)
0 <= eta_ob <= 1
0 <= eta_t <= 1
```

Choose `Delta_t_global_max` and `Delta_t_rear_ob_max` from manufacturing and
geometry:

```text
Delta_t_global_max =
    min_s,k(t_max - t_s,k^0, eta_tR R_s,k - t_s,k^0)

Delta_t_rear_ob_max =
    min(max_thickness_step,
        t_max - t_r,k^0 - Delta_t_global,
        eta_tR R_r,k - t_r,k^0 - Delta_t_global)
```

For derivative-friendly implementation, avoid computing these maxima inside
the component as variable-dependent clips. Instead:

- use conservative config-driven constants for the first implementation, or
- expose the remaining margins as smooth inequality constraints.

### 3G. Why This Is Physics-Driven

This V1 set maps directly to structural mechanisms:

```text
a_m controls main bending stiffness where wire-supported load transfer is
largest.

b_m controls outboard main bending tail without creating a nonmonotone radius
pattern.

a_r raises rear beam stiffness globally in the only OD direction currently
compatible with taper.

eta_ob adds real rear outboard material where the active amplification lives,
paying mass and changing EI/GJ/stress/buckling through tube mechanics.

eta_t provides a global reserve for stress, buckling, and local stiffness,
without letting the optimizer chatter across low-leverage thickness segments.
```

It is reduced, but not heuristic in the sense of being detached from load path.
Each variable corresponds to a structural lever visible in the dual-beam
mechanism.

## Part 4. Derivatives And Numerical Strategy

### 4A. Analytic Partials Candidates

These should be analytic from the start or soon after Phase 1:

```text
reduced variable mapping:
    partial R/t arrays with respect to [a_m, b_m, a_r, eta_ob, eta_t].

tube section properties:
    A, I, J, EI, GJ, mass per length with respect to R and t.

segment-to-element mapping:
    constant sparse matrix.

structural mass:
    linear in mass_per_length and element length.

self-weight loads:
    linear in mass_per_length.

rear explicit self-weight:
    linear in rear_mass_per_length on rear beam line.

aero torque vertical couple:
    analytic in m_y and d_x if geometry is fixed.

smooth abs / KS / norm:
    closed-form derivatives.

solve derivative:
    dq/dx = K^-1 (df/dx - dK/dx q).

finite link forces:
    d(lambda_i)/dx = d(K_link c_i)/dx.
```

Existing `DualSparPropertiesComp` already has analytic section partials
verified by `tests/test_spar_properties_partials.py`. The full current
equivalent structural model has complex-step total derivative coverage in
`tests/test_partials.py`.

### 4B. Complex-Step Candidates

Use complex-step first for:

```text
3-D element coordinate transform and local/global stiffness assembly
full dual-beam FEM state with geometry-dependent K
offset-aware rigid link constraint matrix with camber/dihedral offsets
stress and buckling recovery before analytic formulas are finalized
reaction recovery
wire axial model, if finite-stiffness and geometry-dependent
link robustness diagnostic quantities
```

Complex-step is appropriate when the code is continuous and type-safe. It is
not a substitute for validating stress/buckling physics.

### 4C. Operations That Break Differentiability Or CS Safety

Avoid inside optimizer-facing components:

```text
np.argmax
raw max(abs(x))
raw min margins as scalar constraints
np.abs on complex-step paths
np.clip inside design mapping
np.maximum / np.minimum on design-dependent values
rounding or catalog snapping
branching on design-dependent signs or active nodes
searchsorted on design-dependent segment boundaries
float(...) casts on variables that may carry imaginary parts
real-only dtype allocation for complex-step components
penalty stiffness so large that conditioning dominates derivatives
silent failed-solve replacement with zeros
massless stiffness multipliers
support_reaction = abs(total_applied_fz) as a recovered reaction
```

Use:

```text
sqrt(x^2 + eps^2) instead of abs(x)
log-sum-exp KS instead of max
bounded optimizer variables plus explicit smooth margins instead of clips
exact constraints or finite springs instead of huge penalties
failure as AnalysisError or explicit failed-eval normalization outside
gradient components
```

### 4D. Suggested OpenMDAO / Differentiable Component Split

```text
ReducedDesignMapComp
    Inputs: [a_m, b_m, a_r, eta_ob, eta_t]
    Outputs: main_r_seg, rear_r_seg, main_t_seg, rear_t_seg
    Partials: analytic.

SegmentToElementComp
    Existing sparse constant mapping from segment arrays to element arrays.

DualBeamSectionPropsComp
    Computes per-spar A/I/J/EI/GJ/mass from explicit main/rear sections.
    Partials: reuse tube analytic formulas.

DualBeamLoadSplitComp
    Builds main/rear nodal loads for selected load mode.
    Partials: analytic for mass/self-weight and linear load splits.

DualBeamFEMComp
    Assembles two beam chains, applies selected link/root/wire mode, solves
    state. Outputs u_main, u_rear, reactions, link multipliers/forces.
    Partials: start with complex-step; later implement adjoint/direct solve.

DualBeamRecoveryComp
    Recovers element strains, curvatures, internal loads, provisional stress,
    buckling indicators.
    Partials: complex-step first, analytic later.

SmoothAggregationComp
    Computes smooth displacement, failure, buckling, twist, and optional smooth
    diagnostics.
    Partials: analytic or CS-safe simple formulas.

ReportMetricsComp
    Computes raw max, argmax, active node, rear/main ratio, and text/report
    fields. Not connected to optimizer constraints.
```

### 4E. Current Implementation That Can Be Reused

Reuse with care:

```text
tube_area, tube_Ixx, tube_J
SegmentToElementComp
DualSparPropertiesComp analytic derivative patterns
Timoshenko element stiffness and CS-compatible rotation helpers
ExternalLoadsComp logic for load factors, self-weight, and rear-gravity torque
equivalent-beam validation export and comparison workflow
dual_spar ANSYS export as parity and inspection mode
internal dual_beam_analysis as analysis-only parity baseline
V1 feasible archive and reduced search lessons
tests for partials, dual-beam smoke behavior, V1 mapping, and ANSYS comparison
```

### 4F. Current Practices To Retire

Retire as mainline behavior:

```text
full 24D cold direct dual-beam COBYLA as the default direct path
rear/main radius-ratio guardrail as primary fix
raw max |UZ| as optimizer constraint
raw argmax active node logic in optimizer path
raw rear/main tip ratio as main target
massless rear outboard EI multipliers
np.clip hidden inside design mapping
penalty-only rigid constraints as the long-term solver architecture
support reaction reported as abs(total_applied_fz)
dual stress/failure hard gate before validation
dual_spar parity load mode being mistaken for production load ownership
```

## Part 5. Verification And Implementation Plan

### Phase 0. Theory Spec Complete

Goal:

```text
Freeze the dual-beam mainline equations, mode names, optimizer quantities,
design mapping, derivative policy, and validation ladder.
```

Outputs:

```text
docs/dual_beam_mainline_theory_spec.md
review checklist for physics, derivatives, and validation
```

Verification:

```text
repo evidence cited
no solver main logic changed
reviewer confirms mode names and equations are implementation-ready
```

Success standard:

```text
Next implementer can build Phase 1 without guessing load ownership, DOF
relations, smoothing formulas, or variable mapping.
```

### Phase 1. Analysis-Only Dual-Beam Mainline

Goal:

```text
Implement a named analysis-only dual_beam_production path beside current parity
analysis. Do not optimize with it yet.
```

Outputs:

```text
DualBeamFEM analysis function/component
mode flags for root, wire, link, and load ownership
u_main/u_rear, reactions, link forces, mass, raw report metrics
production load mode with self-weight on explicit spar lines
parity mode preserved for regression
```

Verification:

```text
joint_only_equal_dof_parity reproduces current internal dual-beam baseline
dual_spar_ansys_parity still matches existing inspected ANSYS values
unit tests for offset-aware rigid link kinematics on a simple two-node system
equilibrium check: sum reactions plus applied loads close to zero
load ownership check: explicit dual self-weight equals equivalent Fz/My totals
after collapsing moments
```

Success standard:

```text
No regression in current parity baseline. Production mode produces finite,
repeatable, physically explainable rear/main responses and reports reaction
partition instead of only total applied Fz.
```

### Phase 2. Optimizer-Facing Smooth Quantities Ready

Goal:

```text
Expose smooth displacement and validated constraint quantities without changing
the production optimizer default.
```

Outputs:

```text
smooth abs / KS displacement component
psi_u_all, psi_u_rear, psi_u_rear_outboard
validated equivalent failure/buckling/twist still available
report-only raw metrics separated from optimizer outputs
failure normalization for non-finite analysis outside gradient components
```

Verification:

```text
smooth max approximates raw max within chosen tolerance on baseline cases
active-node switching perturbation remains numerically smooth
tests prove raw argmax outputs are not used in constraints
V1 reduced mapping test updated for new physics mapping if implemented
```

Success standard:

```text
A black-box feasibility-first reduced optimizer can use only smooth quantities
and produce the same or better engineering band as hybrid/V1 without raw max
constraints.
```

### Phase 3. Derivative-Enabled / CS-Safe / Partials-Verified Version

Goal:

```text
Move the dual-beam mainline toward OpenMDAO-compatible derivatives.
```

Outputs:

```text
ReducedDesignMapComp with analytic partials
DualBeamSectionPropsComp with analytic partials
DualBeamLoadSplitComp with analytic partials
DualBeamFEMComp with CS partials first, then direct/adjoint solve derivatives
SmoothAggregationComp with analytic or CS-safe partials
check_partials and check_totals tests
```

Verification:

```text
component check_partials(method=cs) passes for interior design points
whole-problem check_totals passes for reduced variables
no float casts or real-only dtype paths in derivative components
complex-step perturbation of each reduced variable changes u_main/u_rear
consistently
```

Success standard:

```text
SLSQP or equivalent gradient driver can consume reduced dual-beam quantities
without derivative fallbacks dominating the run.
```

### Phase 4. Benchmark And High-Fidelity Comparison

Goal:

```text
Compare the rebuilt mainline against equivalent, hybrid, current direct,
reduced V1, and ANSYS dual-spar inspection.
```

Outputs:

```text
benchmark table with mass, smooth constraints, raw max |UZ|, rear/main ratio,
reaction partition, link mode sensitivity, nfev, wall time
ANSYS export package for selected candidates
ranking comparison among nearby candidates
```

Verification:

```text
run equivalent/hybrid/current direct/reduced V1/new mainline on Black Cat 004
run parity and production load modes explicitly
run joint-only and dense/finite-rib robustness modes
run ANSYS dual-spar spot-check on final selected candidate
inspect whether active displacement location or candidate ranking flips
```

Success standard:

```text
new mainline is feasible under final configured limits;
mass is not higher than hybrid by more than 0.5%, or it buys a clearly lower
dual max |UZ| at comparable mass;
raw dual max |UZ| is at least 2% lower than hybrid at equal/higher confidence,
or mass is at least 2% lower at equal/lower raw max |UZ|;
no taper or thickness-step violations;
selected candidate remains in the consistent or explainable band under ANSYS
inspection;
ranking of nearby candidates does not surprise under higher fidelity.
```

## Final Conclusion

### How The Dual-Beam Mainline Should Be Rebuilt

Rebuild it as:

```text
explicit two-beam Timoshenko FEM
+ named root/wire/link/load modes
+ production load ownership with self-weight on explicit spar lines
+ offset-aware rib/joint kinematics as the physical target
+ smooth optimizer quantities
+ reduced monotone design mapping
+ real rear-outboard material reserve
+ derivative-aware OpenMDAO component boundaries
+ ANSYS parity retained as validation/inspection mode
```

The mainline should not be a full 24D black-box search over raw max
displacement. The structural variables should encode the actual load-path
levers: main plateau bending stiffness, main outboard taper fill, rear global
stiffness, rear outboard sleeve/layup reserve, and global wall reserve.

### Existing Code To Keep

Keep:

```text
equivalent-beam validation workflow
tube section formulas and analytic partial patterns
Timoshenko beam primitives
current internal dual-beam parity analysis as a regression baseline
dual_spar ANSYS export as an inspection/parity path
ExternalLoadsComp equivalent load ownership logic
V1 reduced design-space evidence and feasible archive idea
tests around partials, ANSYS comparison, dual-beam behavior, and reduced mapping
```

### Existing Practices To Remove From The Mainline

Remove from mainline status:

```text
guardrail-first rear/main radius ratio fixes
hybrid as final philosophy
current full-24D cold direct dual-beam default
raw max |UZ| / argmax / active node as optimizer quantities
unvalidated dual stress/buckling hard gates
massless local EI knobs
hidden clipping in design mapping
penalty-only constraints as the derivative target
ambiguous load mode where parity and production ownership are mixed
```

### What The Next Reviewer Should Audit First

1. Sign and ownership of aerodynamic torque, explicit spar self-weight, and
   rear-gravity torque across parity, equivalent, and production modes.
2. Offset-aware rib/joint kinematics versus current equal-DOF parity links.
3. Smooth displacement aggregation and proof that raw argmax is report-only.
4. The five-variable reduced mapping, especially monotone taper and thickness
   step guarantees.
5. Whether rear-outboard reserve pays mass and changes section properties
   through real tube/layup mechanics.
6. Reaction and link-force recovery, especially wire/root partition.
7. Dual stress and buckling validation before any hard-gating promotion.
