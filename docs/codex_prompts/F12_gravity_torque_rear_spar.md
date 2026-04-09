# F12 — Rear Spar Gravity Torque About the Main Spar Elastic Axis

> **Priority**: M2 Phase 2 — after F6 and F8  
> **Depends on**: F6 done. F8 recommended. No other dependencies.  
> **Estimated time**: 2–3 h (includes partials and twist constraint check)

## Context

The wing has two spars:
- **Main spar** at 25% chord (`main_spar.location_xc = 0.25`)
- **Rear spar** at 70% chord (`rear_spar.location_xc = 0.70`)

The chordwise separation is:
```
d_chord_elem = (0.70 - 0.25) * chord_elem  [m]
```

This is already computed in `src/hpa_mdo/structure/groups/main.py` at line 140:
```python
d_chord_elem = (wing.rear_spar_xc - wing.main_spar_xc) * chord_elem
```

In flight, the rear spar mass creates a gravitational moment about the
**main spar elastic axis** (which the FEM beam axis follows).  The rear
spar hangs aft of the main spar — its weight pulls the wing nose-up in
local wing coordinates (trailing-edge down → positive twist when measuring
washout convention, but this is a nose-up pitching moment that increases
twist in the direction the aerodynamic pitching moment typically acts).

Currently, `ExternalLoadsComp` applies gravity only in the **flapwise (uz)**
direction — specifically the combined `spar_mass_per_length × g × element_length`
is split equally to the two element end-nodes at DOF index 2 (uz).  See
`src/hpa_mdo/structure/components/loads.py` lines 73–77:

```python
for e in range(ne):
    element_weight = mpl[e] * g * element_lengths[e]
    loads[e, 2] -= element_weight / 2.0
    loads[e + 1, 2] -= element_weight / 2.0
```

This correctly computes the **total** weight (main + rear) but places it
all at the main spar beam axis.  The rear spar contribution is offset
`d_chord_elem` aft, creating a distributed torsional moment that is
currently omitted.

The missing torque per unit span is:

```
q_torque_gravity[i] = m_rear_per_length[i] * g * d_chord[i]   [N.m/m]
```

where:
- `m_rear_per_length[i]` = rear spar linear mass density at element `i`
  = `rho_rear * tube_area(R_rear[i], t_rear[i])`   [kg/m]
- `g` = 9.80665 m/s² (= `G_STANDARD` from `hpa_mdo.core.constants`)
- `d_chord[i]` = chordwise separation at element `i`   [m]

This torque is applied as a **distributed moment** (theta_x = torsion
about the span axis) at each spanwise node.  In the FEM, DOF index 4
is `theta_y` (spanwise torsion for a beam along Y), consistent with
`ExternalLoadsComp` line 71:

```python
loads[i, 4] = torque[i] * ds[i]   # DOF 4 = My = spanwise torsion
```

The gravity torque from the rear spar should be added at DOF 4 in the
same sign convention: rear spar mass pulls trailing edge down →
nose-up moment → same sign as the aerodynamic pitching moment.  Confirm
the sign by checking that adding `q_torque_gravity` increases
`twist_max_deg` slightly (the optimizer will respond by stiffening the
spar in torsion, i.e., increasing GJ).

## Task

### Step 1: Add `rear_spar_gravity_torque` option to `ExternalLoadsComp`

In `src/hpa_mdo/structure/components/loads.py`, add an option and
thread it into the load vector.  The current `initialize()` block:

```python
def initialize(self):
    self.options.declare("n_nodes", types=int)
    self.options.declare("lift_per_span", types=np.ndarray, ...)
    self.options.declare("torque_per_span", types=np.ndarray, ...)
    self.options.declare("node_spacings", types=np.ndarray, ...)
    self.options.declare("element_lengths", types=np.ndarray, ...)
    self.options.declare("gravity_scale", types=float, default=1.0, ...)
```

Add after `gravity_scale`:

```python
self.options.declare(
    "rear_gravity_torque_per_span",
    default=None,
    allow_none=True,
    desc=(
        "(nn,) distributed torsional moment from rear spar self-weight "
        "[N.m/m] at each spanwise node. Applied at DOF 4 (My, spanwise "
        "torsion). None = disabled (legacy behaviour)."
    ),
)
```

In `compute()`, after the existing torque application (DOF 4 from
aerodynamic torque), add:

```python
rgt = self.options["rear_gravity_torque_per_span"]
if rgt is not None:
    rgt_arr = np.asarray(rgt)
    g_scale = self.options["gravity_scale"]
    for i in range(nn):
        # Same sign as aerodynamic pitching moment (trailing edge down → +My)
        loads[i, 4] += rgt_arr[i] * ds[i] * g_scale
```

The `g_scale` factor (= `load_case.gravity_scale` = `nz`) is applied
because this is an inertial/gravity load — it must scale with the manoeuvre
load factor, exactly like the spar self-weight in uz.

Important: `declare_partials` for `loads` w.r.t. `mass_per_length` already
uses sparse rows/cols targeting DOF 2 only.  The new torsion contribution
depends on `rear_gravity_torque_per_span`, which is a **fixed option** (not
an OpenMDAO input), so **no new partial declaration is needed**.

### Step 2: Compute `rear_gravity_torque_per_span` in `groups/main.py`

In `src/hpa_mdo/structure/groups/main.py`, in `HPAStructuralGroup.setup()`,
after line 140 where `d_chord_elem` is computed:

```python
d_chord_elem = (wing.rear_spar_xc - wing.main_spar_xc) * chord_elem
```

Add (immediately after, still inside `setup()`):

```python
from hpa_mdo.core.constants import G_STANDARD
from hpa_mdo.structure.spar_model import tube_area as _tube_area

if rear_on:
    # Rear spar linear mass density per element [kg/m]
    m_rear_per_elem = mat_rear.density * _tube_area(R_rear_elem, R_rear_elem * 0.15)
    # NOTE: R_rear_elem is the outer radius; use a representative t/R = 0.15
    # as an estimate for pre-assembly (the actual t is a design variable, but
    # an initial estimate is needed here since ExternalLoadsComp options are
    # fixed at setup time). Use the geometric mean of thickness_fraction_root
    # and thickness_fraction_tip from config as the wall-fraction proxy:
    #   t_frac = (cfg.rear_spar.thickness_fraction_root +
    #             cfg.rear_spar.thickness_fraction_tip) / 2.0 * 0.15
    # Actually, use a simpler estimate: rear spar mass per length
    # is roughly 0.5–1.5 kg/m for typical HPA dimensions.
    # For a more accurate approach, interpolate from nominal t:
    t_nominal_frac = (
        cfg.rear_spar.thickness_fraction_root
        + cfg.rear_spar.thickness_fraction_tip
    ) / 2.0
    # Nominal wall thickness as fraction of outer radius
    t_nominal_elem = t_nominal_frac * R_rear_elem * 0.10  # ~10% of airfoil-t-fraction
    # Clamp to physical range [min_wall_thickness, 0.4 * R]
    t_min = cfg.rear_spar.min_wall_thickness
    t_nominal_elem = np.clip(t_nominal_elem, t_min, 0.4 * R_rear_elem)

    m_rear_elem = mat_rear.density * _tube_area(R_rear_elem, t_nominal_elem)

    # Gravity torque per element [N.m/m] (node-averaged to produce per-node values)
    q_rear_grav_elem = m_rear_elem * G_STANDARD * d_chord_elem  # [N.m/m]

    # Interpolate element values to nodes (midpoint average)
    q_rear_grav_nodes = np.zeros(nn)
    q_rear_grav_nodes[0] = q_rear_grav_elem[0]
    q_rear_grav_nodes[-1] = q_rear_grav_elem[-1]
    for i in range(1, nn - 1):
        q_rear_grav_nodes[i] = (q_rear_grav_elem[i - 1] + q_rear_grav_elem[i]) / 2.0
else:
    q_rear_grav_nodes = None
```

Then pass `rear_gravity_torque_per_span=q_rear_grav_nodes` when
constructing `ExternalLoadsComp` (both in the single-case path around
line 243 and within `StructuralLoadCaseGroup`).

### Step 3: Thread through `StructuralLoadCaseGroup`

In `src/hpa_mdo/structure/groups/load_case.py`, add to `initialize()`:

```python
self.options.declare(
    "rear_gravity_torque_per_span",
    default=None,
    allow_none=True,
    desc="(nn,) rear spar gravity torque distribution [N.m/m]. None = disabled.",
)
```

Pass it through to `ExternalLoadsComp` in `setup()`:

```python
self.add_subsystem(
    "ext_loads",
    ExternalLoadsComp(
        n_nodes=nn,
        lift_per_span=lift,
        torque_per_span=torque,
        node_spacings=self.options["node_spacings"],
        element_lengths=self.options["element_lengths"],
        gravity_scale=load_case.gravity_scale,
        rear_gravity_torque_per_span=self.options["rear_gravity_torque_per_span"],
    ),
    promotes_inputs=["mass_per_length"],
    promotes_outputs=["loads"],
)
```

Then in `HPAStructuralGroup.setup()`, when creating each
`StructuralLoadCaseGroup`, add:
```python
rear_gravity_torque_per_span=q_rear_grav_nodes,
```

### Step 4: Add `rear_spar_chordwise_offset_m` to config (documentation only)

The chordwise offset is already derived from `main_spar.location_xc`
and `rear_spar.location_xc` — it does NOT need a new config field.
Add a comment in `configs/blackcat_004.yaml` under `rear_spar:`:

```yaml
rear_spar:
  enabled: true
  # Chordwise offset from main spar (0.70 - 0.25 = 0.45c) creates a gravity
  # torque arm about the main spar elastic axis. This is accounted for in
  # ExternalLoadsComp via rear_gravity_torque_per_span (Finding F12).
  location_xc: 0.70
```

No new Pydantic field is required.

### Step 5: Verify check_partials

`ExternalLoadsComp` has analytic sparse partials for `loads` vs
`mass_per_length` (DOF 2 only — flapwise weight).  The new torsion term
depends on `rear_gravity_torque_per_span`, which is a fixed option,
so the partial is zero w.r.t. all inputs and does not affect
`check_partials`.

Run anyway to confirm no regression:

```
uv run pytest tests/test_partials.py -v
uv run pytest tests/test_spatial_beam_fem.py -v
```

### Step 6: Full verification

```
uv run pytest tests/test_partials.py -v
uv run pytest -m "not slow"
uv run python examples/blackcat_004_optimize.py
```

After running the optimizer, check:

1. `twist_max_deg` should be **slightly higher** than without F12
   (typically +0.05° to +0.2° for HPA-scale aircraft).
2. `failure_index` should be nearly unchanged (torque affects twist,
   not flapwise stress significantly).
3. If `twist_max_deg > 2.0°` after F12, the optimizer must be re-run
   (it will automatically stiffen the torsion by increasing GJ — i.e.,
   the optimizer responds by choosing larger OD or thicker rear spar).
4. `total_mass_full_kg` is still in the physical range 15–50 kg.
5. Final line: `val_weight: <float>` (required by the AI agent loop).

If `twist_max_deg` becomes the binding constraint and mass increases
significantly (> 1 kg), update `BASELINE_TOTAL_MASS_KG` in
`tests/test_golden_blackcat_004.py`.

### Step 7: Commit

```
feat(structure): add rear spar gravity torque about main spar axis (Finding F12)

The rear spar at 70% chord hangs 0.45c aft of the main spar elastic axis.
Its self-weight creates a distributed torsional moment q = m_rear * g * d_chord
that the FEM previously ignored.

ExternalLoadsComp now accepts rear_gravity_torque_per_span [N/m] applied
at DOF 4 (My, spanwise torsion) with gravity_scale (nz) applied.
Torque is estimated from nominal rear spar geometry at setup time.

This typically increases twist_max_deg by 0.05–0.2 deg, prompting the
optimizer to increase rear spar GJ.
```

## Do NOT

- Add new design variables or constraints
- Modify the FEM stiffness matrix (`assembly.py`) — this is a load change
- Change `VonMisesStressComp` or `BucklingComp`
- Add `rear_spar_chordwise_offset_m` as a new Pydantic field — the offset
  is already derivable from `main_spar.location_xc` and
  `rear_spar.location_xc`
- Use hardcoded density or material properties — read from `mat_rear`
  (which comes from `MaterialDB` using `cfg.rear_spar.material`)
- Modify the aerodynamic torque path (`torque_per_span` from `LoadMapper`)
- Apply the gravity torque to main spar mass — only the rear spar offset
  mass creates the chordwise moment arm
- Use `np.abs()` anywhere — use `np.sqrt(x**2 + 1e-30)` for CS safety
