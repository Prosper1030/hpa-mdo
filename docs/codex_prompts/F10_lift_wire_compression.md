# F10 — Lift Wire Pre-Compression in Spar Stress / Buckling

> **Priority**: M2 Phase 2 — can run after F6 + F8  
> **Depends on**: F6 (thickness smoothness) done. F8 recommended.  
> **Estimated time**: 2–3 h

## Context

The current FEM applies lift-wire supports as penalty-method boundary
conditions constraining the vertical DOF (`uz = 0`) at each wire
attachment node.  This is implemented in:

```
src/hpa_mdo/structure/fem/assembly.py  lines 219–231
```

Specifically, for each wire node index in `self.options["lift_wire_nodes"]`,
the code adds:

```python
bc_dofs.append(lw_idx * 6 + 2)  # DOF 2 = vertical (z)
K_global[dof, dof] += penalty_val
f[dof] = zero_val
```

This correctly prevents vertical displacement at the wire attachment, but
it **ignores the axial compression force the wire reaction creates in the
spar tube** between the root and the wire attachment.

The wire is inclined from the attachment node (at span-station `y_att`,
fuselage height `fuselage_z`) to the fuselage anchor.  When the wing loads
push the spar upward at the attachment node, the wire tension has:
- A vertical component `Fz_wire` (the reaction force that keeps uz ≈ 0)
- A horizontal (spanwise) component `Fx_wire = Fz_wire × cos(θ) / sin(θ)`
  that acts as **axial compression** on the tube between the root and
  attachment (Newton's 3rd law: wire pulls tip of root segment inward).

Geometry:
```
wire_angle_deg  = angle of wire from horizontal plane
θ = wire_angle_deg in radians
horizontal_comp / vertical_comp = cos(θ) / sin(θ) = 1 / tan(θ)
```

For the Black Cat 004 baseline:
- Attachment at `y=7.5 m`, `fuselage_z=-1.5 m`
- Vertical drop = 1.5 m (from fuselage anchor to spar-level attachment)
- Horizontal run ≈ 7.5 m  →  `θ ≈ atan(1.5/7.5) ≈ 11.3°` from horizontal
  (but `wire_angle_deg` is configurable — do NOT hardcode this)

The **pre-compression force** that must be added to the stress check is:

```
P_comp = Fz_wire * cos(θ_wire) / sin(θ_wire)  [N, positive = compression]
```

where `Fz_wire` can be estimated from the FEM reaction (penalty × uz before
penalty, approximately equal to the integrated lift over the outboard half).
For the pre-stress computation, use a statically-derived estimate based on
the design lift load split at the wire attachment span fraction.

## Task

### Step 1: Add `wire_angle_deg` to config

In `src/hpa_mdo/core/config.py`, add `wire_angle_deg` to `LiftWireConfig`:

```python
class LiftWireConfig(BaseModel):
    enabled: bool = True
    cable_material: str = "steel_4130"
    cable_diameter: float = 2.0e-3
    max_tension_fraction: float = 0.5
    wire_angle_deg: float = Field(
        default=45.0,
        description=(
            "Inclination of lift wire from horizontal plane [deg]. "
            "Used to split wire tension into vertical (reaction) and "
            "horizontal (spar compression) components."
        ),
        gt=0.0,
        lt=90.0,
    )
    attachments: List[LiftWireAttachment] = Field(default_factory=list)
```

Also add to `configs/blackcat_004.yaml` under `lift_wires:`:

```yaml
lift_wires:
  enabled: true
  cable_material: "steel_4130"
  cable_diameter: 2.0e-3
  max_tension_fraction: 0.5
  wire_angle_deg: 11.3   # atan(1.5 m drop / 7.5 m span) ≈ 11.3 deg
  attachments:
    - { y: 7.5, fuselage_z: -1.5, label: "wire-1" }
```

The 11.3 deg comes from the existing attachment geometry
(`fuselage_z=-1.5`, `y=7.5`): `atan(1.5/7.5)` converted to degrees.
If Codex prefers, it can compute the angle from the attachment geometry
directly, but a config field is still required for cases where the
fuselage anchor x-position differs.

### Step 2: Create `src/hpa_mdo/structure/fem/wire_precompression.py`

Create a new module with a single public function:

```python
"""Pre-compression force in spar from inclined lift-wire reaction."""
from __future__ import annotations

import numpy as np


def wire_axial_precompression(
    y_nodes: np.ndarray,
    lift_per_span: np.ndarray,
    node_spacings: np.ndarray,
    wire_attachment_indices: list[int],
    wire_angle_deg: float,
) -> np.ndarray:
    """Return axial pre-compression force [N] at each FEM element.

    For each element between the root (node 0) and a wire attachment
    node, add the horizontal component of the wire tension as compressive
    pre-stress.  Elements outboard of the wire attachment carry zero
    extra axial load from this wire.

    The wire reaction (vertical component) is estimated as the total
    upward aero force outboard of the attachment:

        Fz_wire ≈ sum( lift[i] * node_spacing[i] )  for i >= attachment_idx

    The axial (horizontal) component:
        P_comp = Fz_wire * cos(theta) / sin(theta)
               = Fz_wire / tan(theta)

    Parameters
    ----------
    y_nodes : (nn,)  spanwise node positions [m]
    lift_per_span : (nn,) lift force per unit span at each node [N/m]
        (already scaled by aero_load_factor)
    node_spacings : (nn,) tributary length per node [m]
    wire_attachment_indices : node indices where wires attach
    wire_angle_deg : inclination from horizontal [deg]

    Returns
    -------
    P_precomp : (ne,) axial pre-compression per element [N], >= 0
    """
    nn = len(y_nodes)
    ne = nn - 1
    theta = np.deg2rad(wire_angle_deg)
    # Guard: avoid tan(0) → inf
    tan_theta = np.tan(theta) + 1e-30

    P_precomp = np.zeros(ne)

    for att_idx in wire_attachment_indices:
        # Total upward aero force outboard of attachment
        outboard_lift = np.sum(
            lift_per_span[att_idx:] * node_spacings[att_idx:]
        )
        outboard_lift = max(float(outboard_lift), 0.0)  # compression only

        # Horizontal (axial) component of wire tension
        p_comp_wire = outboard_lift / tan_theta

        # Apply to all elements between root and attachment (elements 0..att_idx-1)
        for e in range(min(att_idx, ne)):
            P_precomp[e] += p_comp_wire

    return P_precomp
```

### Step 3: Thread `P_precomp` into `VonMisesStressComp`

In `src/hpa_mdo/structure/components/constraints.py`, modify
`VonMisesStressComp` to accept a `wire_precompression` option:

```python
# In initialize():
self.options.declare(
    "wire_precompression",
    default=None,
    allow_none=True,
    desc="(ne,) axial pre-compression [N] from lift-wire reaction. "
         "None = no pre-stress.",
)
```

In `compute()`, add the axial stress from pre-compression to the bending
stress before computing the von Mises combination.  The axial stress in
the main tube is:

```python
# After computing sigma_bend_main for element e:
if wire_precomp is not None:
    A_main_e = tube_area(R_m[e], t_m[e])
    sigma_axial_e = wire_precomp[e] / (A_main_e + 1e-30)
else:
    sigma_axial_e = 0.0

# Combined: bending stress + axial pre-compression (both compressive at spar bottom)
sigma_total_main = np.sqrt(
    (sigma_bend_main_e + sigma_axial_e) ** 2 + 1e-30
)
```

Where `sigma_bend_main_e` is already computed in the existing element loop
as `E_m * kappa_e * (R_m[e] + dz_main_abs_e)`.

Important: the pre-compression is **additive** to the bending-induced
compression on the lower surface.  On the upper surface it partially
cancels bending tension — use the worst-case (lower surface, additive)
for a conservative check.  The formula above does this correctly because
both `sigma_bend` and `sigma_axial` are positive magnitudes.

Do **not** add pre-compression to the torsion shear term — it is purely
axial.

Repeat for rear spar using the same `wire_precompression` array
(same pre-compression applies to rear spar as it shares the same inboard
segments).

### Step 4: Thread `P_precomp` into `BucklingComp`

In `src/hpa_mdo/structure/buckling.py`, add:

```python
# In initialize():
self.options.declare(
    "wire_precompression",
    default=None,
    allow_none=True,
    desc="(ne,) axial pre-compression [N] from lift-wire reaction.",
)
```

In `compute()`, the critical shell buckling check uses bending curvature
to derive the compressive stress on the outer fibre.  Add the pre-axial
stress to the bending demand:

```python
wire_precomp = self.options["wire_precompression"]
if wire_precomp is not None:
    wire_precomp_arr = np.asarray(wire_precomp)
else:
    wire_precomp_arr = np.zeros(ne)

# Inside the element loop (or after kappa_mag is assembled):
A_main_e = _tube_area(R_main[e], t_main[e])
sigma_axial_e = wire_precomp_arr[e] / (A_main_e + 1e-30)

# Increase the effective bending stress by the axial pre-compression:
sigma_bend_main_e = E_main * (R_main[e] + dz_main_abs[e]) * kappa_mag[e]
ratio_main_e = (sigma_bend_main_e + sigma_axial_e) / (sigma_cr_main[e] + 1e-30)
```

Repeat for rear spar with `A_rear_e`.

### Step 5: Wire the pre-compression in `groups/main.py`

In `src/hpa_mdo/structure/groups/main.py`, in the `HPAStructuralGroup.setup()`
method, after computing `lw_node_indices` (around line 151), compute the
pre-compression vector and pass it as an option to `VonMisesStressComp`
and `BucklingComp`:

```python
from hpa_mdo.structure.fem.wire_precompression import wire_axial_precompression

# Compute pre-compression (uses the scaled lift from the first/only load case)
P_precomp = None
if cfg.lift_wires.enabled and lw_node_indices and len(case_entries) == 1:
    _, case_loads_single = next(iter(case_entries.values()))
    lc_single = list(case_entries.values())[0][0]
    lift_scaled = (
        np.asarray(case_loads_single["lift_per_span"]) * lc_single.aero_scale
    )
    P_precomp = wire_axial_precompression(
        y_nodes=y,
        lift_per_span=lift_scaled,
        node_spacings=node_spacings,
        wire_attachment_indices=lw_node_indices,
        wire_angle_deg=cfg.lift_wires.wire_angle_deg,
    )
```

Then pass `wire_precompression=P_precomp` to both `VonMisesStressComp`
and `BucklingComp` when instantiating them (both single-case and
multi-case branches).

For the multi-case path (`StructuralLoadCaseGroup`), add
`wire_precompression` to the group's `initialize()` options list and
forward it through to each component.

### Step 6: Verify

```
uv run python -c "
from hpa_mdo.structure.fem.wire_precompression import wire_axial_precompression
import numpy as np
y = np.linspace(0, 16.5, 60)
lift = np.ones(60) * 50.0   # 50 N/m uniform
ds = np.gradient(y)
ds[0] = ds[1] / 2; ds[-1] = ds[-2] / 2
att = [27]  # node near y=7.5m
p = wire_axial_precompression(y, lift, ds, att, wire_angle_deg=11.3)
assert p[0] > 0, 'root element must have pre-compression'
assert p[50] == 0.0, 'outboard elements must be zero'
print('wire_precompression OK, P[0]=', p[0])
"

uv run pytest tests/test_vonmises_stress.py -v
uv run pytest tests/test_buckling.py -v
uv run pytest tests/test_partials.py -v
uv run pytest -m "not slow"
uv run python examples/blackcat_004_optimize.py
```

After running the optimizer, verify:
- `failure_index` and `buckling_index` have not become catastrophically
  more positive (F10 effect is typically < 5% stress increase for HPA wires
  at shallow angles)
- Mass may increase slightly as optimizer responds to tighter constraint

### Step 7: Commit

```
feat(structure): add lift-wire axial pre-compression to stress and buckling (Finding F10)

Wire attachment nodes previously constrained uz=0 via FEM penalty BCs,
but ignored the inboard spar compression from the wire's horizontal
force component.

New module wire_precompression.py estimates the axial pre-stress
(P = Fz_outboard / tan(theta_wire)) and threads it through
VonMisesStressComp and BucklingComp as an additive compressive demand.

Config: lift_wires.wire_angle_deg = 11.3 deg for blackcat_004 baseline.
```

## Do NOT

- Modify the FEM stiffness matrix assembly (`assembly.py`) — pre-stress
  is purely a stress-recovery correction, not a stiffness change
- Change the penalty BC that enforces `uz = 0` at wire nodes — that
  remains unchanged
- Add new OpenMDAO design variables or constraints
- Change `ExternalLoadsComp` — the loads are unaffected
- Add wire tension as a separate FEM load vector — this is a pre-stress,
  not an applied nodal force in the displacement solve
- Hardcode the wire angle — it must come from `cfg.lift_wires.wire_angle_deg`
- Apply pre-compression to elements outboard of the wire attachment
