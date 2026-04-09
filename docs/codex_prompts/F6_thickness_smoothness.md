# F6 — Thickness Smoothness Constraint

> **Priority**: M2 Phase 2 — next after F13+F9  
> **Depends on**: Nothing (can start immediately)  
> **Estimated time**: 1–2 h

## Context

The optimizer treats each segment's wall thickness `t_seg[i]` as fully
independent. With the gradient-based OpenMDAO driver (method="auto"),
the optimizer can exploit this to create oscillating thickness patterns
(e.g., 0.8mm / 5.0mm / 0.8mm / 4.0mm) that are:

1. **Impossible to manufacture** (each segment needs a different mandrel)
2. **Structurally unsound** (stiffness discontinuity at splice → stress
   concentration factor 1.3–2.0 that the beam model can't capture)

The monotonic taper constraint on **radius** already exists at
`structure/groups/main.py` line ~501 using the pattern:
```
ExecComp("margin = r_in - r_out") → add_constraint(lower=0.0)
```

Thickness smoothness follows the same pattern but with a **maximum step
size** rather than monotonic decrease.

## Task

Add adjacent-segment thickness-step constraints for both main and rear
spars. The constraint enforces:

```
|t_seg[i] - t_seg[i+1]| <= max_thickness_step_m
```

which is expressed as two one-sided inequalities:
```
t_seg[i] - t_seg[i+1] <= max_thickness_step_m   (no big decrease)
t_seg[i+1] - t_seg[i] <= max_thickness_step_m   (no big increase)
```

### Step 1: Add config field

In `core/config.py`, inside `SolverConfig` (or wherever `max_wall_thickness_m`
lives), add:

```python
max_thickness_step_m: float = Field(
    default=0.003,  # 3mm max step between adjacent segments
    description="Maximum wall thickness change between adjacent segments [m]",
)
```

Also add the field to `configs/blackcat_004.yaml` under `solver:`:
```yaml
max_thickness_step_m: 0.003  # 3mm max step between adjacent segments
```

### Step 2: Add constraints in `structure/groups/main.py`

Follow the exact same pattern as `main_radius_taper` (line ~501).
For **each spar** (main and rear), add TWO ExecComp subsystems:

```python
# Main spar thickness smoothness (decrease direction)
model.add_subsystem(
    "main_t_step_dec",
    om.ExecComp(
        "margin = max_step - (t_in - t_out)",
        margin={"shape": (n_seg - 1,), "units": "m"},
        t_in={"shape": (n_seg - 1,), "units": "m"},
        t_out={"shape": (n_seg - 1,), "units": "m"},
        max_step={"units": "m"},
        has_diag_partials=True,
    ),
)
model.connect("struct.seg_mapper.main_t_seg", "main_t_step_dec.t_in",
              src_indices=seg_idx_in)
model.connect("struct.seg_mapper.main_t_seg", "main_t_step_dec.t_out",
              src_indices=seg_idx_out)
# Pass max_step as a constant
model.set_input_defaults("main_t_step_dec.max_step",
                         val=cfg.solver.max_thickness_step_m, units="m")
model.add_constraint("main_t_step_dec.margin", lower=0.0)

# Main spar thickness smoothness (increase direction)
model.add_subsystem(
    "main_t_step_inc",
    om.ExecComp(
        "margin = max_step - (t_out - t_in)",
        margin={"shape": (n_seg - 1,), "units": "m"},
        t_in={"shape": (n_seg - 1,), "units": "m"},
        t_out={"shape": (n_seg - 1,), "units": "m"},
        max_step={"units": "m"},
        has_diag_partials=True,
    ),
)
# ... same connections ...
model.add_constraint("main_t_step_inc.margin", lower=0.0)
```

Repeat for rear spar: `rear_t_step_dec`, `rear_t_step_inc`.

**Important**: Use `seg_idx_in` and `seg_idx_out` arrays already defined
for the monotonic taper constraint. Do NOT re-create them.

**Important**: Only add these if `n_seg > 1` (same guard as monotonic taper).

### Step 3: Verify

- `uv run pytest tests/test_partials.py -v` — check_totals must pass
  (ExecComp has auto-diff partials, should be fine)
- `uv run pytest -m slow tests/test_golden_blackcat_004.py`
  — If the current solution already has smooth thickness, golden passes
    unchanged. If it was oscillating, mass may increase slightly →
    update `BASELINE_TOTAL_MASS_KG` if needed.
- `uv run pytest -m "not slow"`
- `uv run python examples/blackcat_004_optimize.py`
  — Inspect the output: verify no adjacent segments have thickness
    difference > 3mm.

### Step 4: Commit

```
feat(structure): add adjacent-segment thickness smoothness constraint (Finding F6)

Prevents oscillating wall thickness patterns that create stress
concentrations at splice joints and are impossible to manufacture.

max_thickness_step_m = 0.003 (3mm) added to solver config.
Constraints follow the same ExecComp pattern as monotonic radius taper.
```

## Do NOT

- Change the monotonic taper constraint on radius (already working)
- Change any FEM, stress, or buckling component
- Change optimizer.py
- Change DE parameters or penalty function
- Touch F9 warping knockdown or F13 compressive strength
- Add a regularization penalty to the objective — use hard constraints only
