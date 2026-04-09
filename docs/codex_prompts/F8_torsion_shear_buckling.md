# F8 — Torsion-Shear Buckling Interaction

> **Priority**: M2 Phase 2 — conditional, after F6  
> **Depends on**: F6 done. Check buckling_index after F6+F9. If
>   `buckling_index < -0.3` (large margin), this task can be DEFERRED
>   to Milestone 4. If `buckling_index > -0.15`, do this task.  
> **Estimated time**: 3–4 h (includes partials modification)

## Context

`BucklingComp` (structure/buckling.py) currently checks only bending-
induced axial stress against shell buckling critical stress:

```python
sigma_bend_main = E_main * (R_main + dz_main_abs) * abs_kappa  # line ~141
sigma_cr_main = coef * E_main * t_main / (R_main + 1e-30)       # line ~142
ratio_main = sigma_bend_main / (sigma_cr_main + 1e-30)          # line ~143
```

This ignores **torsion-induced shear stress**, which can cause
independent shell buckling. The combined check should use:

```
(σ_bend / σ_cr)² + (τ_torsion / τ_cr)² ≤ 1.0
```

The torsion rate (twist angle change per unit length) is already
available in BucklingComp's `disp` input — the code computes
`dtheta_local[0]` (torsion) at line ~107 but discards it.

## Task

### Step 1: Extract torsion shear stress

In `BucklingComp.compute()`, after computing `abs_kappa` (line ~113),
add torsion extraction:

```python
# Torsion rate (twist per unit length) — already computed as dtheta_local[0]
# but currently discarded. Extract it:
gamma_abs = np.sqrt(dtheta_local[0] ** 2 + 1e-30)  # [rad/m], CS-safe
```

Wait — `dtheta_local` is computed inside the per-element loop. Keep
the extraction there. For each element `e`:

```python
# Already exists in the loop:
dtheta_local = R_elem @ du_e[3:6]  # rotation vector in local frame
# dtheta_local[0] = torsion rate along beam axis
# dtheta_local[1], dtheta_local[2] = bending curvatures

gamma_e = dtheta_local[0] / L  # torsion rate [rad/m]
gamma_abs = np.sqrt(gamma_e ** 2 + 1e-30)  # CS-safe absolute value
```

Compute torsion shear stress and critical shear:

```python
# Main spar:
tau_main = G_main * R_main[e] * gamma_abs
# Critical shear for thin cylinder (Timoshenko & Gere):
tau_cr_main = 0.272 * E_main * (t_main[e] / (R_main[e] + 1e-30)) ** 1.25
# Apply knockdown for conservatism:
tau_cr_main *= knockdown

# Combined interaction (biaxial buckling):
ratio_main_combined = (
    (sigma_bend_main / (sigma_cr_main + 1e-30)) ** 2
    + (tau_main / (tau_cr_main + 1e-30)) ** 2
)
```

Replace the current `ratio_main = sigma_bend_main / sigma_cr_main`
with the square root of `ratio_main_combined` to keep the KS
aggregation consistent (ratio > 1 means buckling):

```python
ratio_main = np.sqrt(ratio_main_combined)  # combined > 1 → buckled
```

### Step 2: Add G_main, G_rear options

BucklingComp currently doesn't receive shear moduli. Add:

```python
# In initialize():
self.options.declare("G_main", types=float)
self.options.declare("G_rear", types=float, default=None)
```

Pass them from `structure/groups/main.py` or `groups/load_case.py`
where BucklingComp is instantiated — same place that passes `E_main`,
`E_rear`, `z_main`, `z_rear`.

### Step 3: Repeat for rear spar

Same formula with `G_rear`, `R_rear`, `t_rear`.

### Step 4: Verify partials

BucklingComp uses `method="cs"` for all partials. The complex-step
method will automatically handle the new torsion terms **as long as
all operations are CS-safe**:
- Use `np.sqrt(x**2 + 1e-30)` instead of `np.abs(x)` ✅
- Use `+ 1e-30` guards on all denominators ✅

After implementation:
```
uv run pytest tests/test_partials.py -v
```
This MUST pass. If check_totals shows new errors, the CS-safe casts
need debugging.

### Step 5: Full verification

```
uv run pytest tests/test_partials.py -v
uv run pytest -m slow tests/test_golden_blackcat_004.py
uv run pytest -m "not slow"
uv run python examples/blackcat_004_optimize.py
```

If buckling_index shifts significantly (from negative toward 0 or
positive), the optimizer will automatically find thicker tubes →
mass increases → update `BASELINE_TOTAL_MASS_KG` in golden test.

### Step 6: Commit

```
feat(structure): add torsion-shear buckling interaction to BucklingComp (Finding F8)

Previously only bending-induced axial stress was checked against shell
buckling. Now includes torsional shear via biaxial interaction formula:
  (σ_bend/σ_cr)² + (τ_torsion/τ_cr)² ≤ 1.0

τ_cr uses Timoshenko & Gere thin-cylinder formula with knockdown.
G_main and G_rear added as component options.
All new operations are CS-safe for complex-step partials.
```

## Do NOT

- Change VonMisesStressComp (that's stress, not buckling)
- Change the FEM assembly
- Change optimizer.py or DE parameters
- Remove the existing bending-only buckling check — augment it
- Change knockdown_factor or bending_enhancement values
- Touch anything in aero/, api/, or fsi/
