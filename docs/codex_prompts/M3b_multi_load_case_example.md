# M3b — Multi-Load-Case Production Example

> **Priority**: Phase I Milestone 3 — parallel with M3a  
> **Depends on**: Nothing (multi-case topology already exists in code)  
> **Estimated time**: 3–4 h

## Context

The OpenMDAO structural model already supports multiple load cases via
`_normalise_load_case_inputs()` and `StructuralLoadCaseGroup`. The
topology branches per-case `ext_loads/fem/stress/failure/buckling/twist/
tip_defl` while sharing `seg_mapper/spar_props/mass`. The multi-case
`check_totals` test passes.

However, there is **no production example** that exercises multi-case.
`blackcat_004_optimize.py` always runs single-case (cruise only).

This task creates a multi-load-case config and example that optimizes
for 3 simultaneous load cases:

1. **Cruise** (1.0g, nominal aero)
2. **Pull-up** (2.0g, scaled aero — represents max-g maneuver)
3. **Negative gust** (−0.5g, reduced aero — checks wire-slack scenario)

## Task

### Step 1: Create multi-case config

Create `configs/blackcat_004_multi.yaml` by copying `blackcat_004.yaml`
and adding a `load_cases` list under the `flight:` section:

```yaml
flight:
  velocity: 9.0
  air_density: 1.225
  # ... existing fields ...
  
  cases:
    - name: cruise
      aero_scale: 1.0
      nz: 1.0
      # uses parent max_tip_deflection_m and max_tip_twist_deg
      
    - name: pullup_2g
      aero_scale: 2.0
      nz: 2.0
      max_tip_deflection_m: 3.5    # relaxed for 2g
      max_tip_twist_deg: 3.0       # relaxed for 2g
      
    - name: negative_gust
      aero_scale: 0.5
      nz: -0.5
      max_tip_deflection_m: 5.0    # wire slack, large deflection OK
      max_tip_twist_deg: 4.0       # relaxed
```

**Important**: `LoadCaseConfig` fields are: `name`, `aero_scale`, `nz`,
`velocity` (optional), `air_density` (optional), `max_tip_deflection_m`
(optional), `max_tip_twist_deg` (optional).

The `nz` field scales gravity loads. `aero_scale` scales aerodynamic
loads. For pull-up: both are 2.0 (2× lift to sustain 2g + 2× gravity).
For negative gust: aero_scale=0.5, nz=−0.5 (upward gravity = wing
bends down → checks if the structure handles reversed loading).

### Step 2: Create `examples/blackcat_004_multi_case.py`

Follow the same structure as `blackcat_004_optimize.py`:

```python
# Steps 1-5: identical (config, aircraft, VSPAero, cruise AoA, load factor)

# Step 6: Multi-case optimization
# The key difference: method="auto" with multi-case config.
# HPAStructuralGroup reads cfg.structural_load_cases() and builds
# per-case branches automatically.

opt = SparOptimizer(cfg, aircraft, design_loads, materials_db)
result = opt.optimize(method="auto")  # or "openmdao" — multi-case
                                       # requires OpenMDAO driver

# Steps 7-9: visualize, summarize, export STEP
# Use output_dir = "output/blackcat_004_multi"
```

**Important**: The `_has_multiple_load_cases()` check in optimizer.py
forces `method="openmdao"` for multi-case. Verify this still works
with `method="auto"` (auto should detect multi-case and use openmdao).

**Important**: If the auto path raises `NotImplementedError` for
multi-case scipy fallback, that's expected and correct — the openmdao
path should succeed.

### Step 3: Run and validate

```bash
uv run python examples/blackcat_004_multi_case.py
```

Expected:
- `val_weight: <float>` printed (mass will be **higher** than single-case
  because the optimizer must satisfy all 3 cases simultaneously)
- All per-case constraints satisfied
- Pull-up case likely binding (highest loads)
- Negative gust case may or may not be binding
- STEP file generated

### Step 4: Add golden test variant

In `tests/test_golden_blackcat_004.py`, add a new test function
(NOT replacing the existing single-case test):

```python
@pytest.mark.slow
def test_golden_multi_case():
    """Multi-case optimization produces physically reasonable results."""
    # Similar to single-case golden test but with blackcat_004_multi.yaml
    # Use a separate BASELINE_MULTI_MASS_KG constant
    # Tolerance can be wider (0.50 kg) since multi-case is less explored
```

### Step 5: Commit

```
feat(examples): add multi-load-case optimization example (M3b)

New config blackcat_004_multi.yaml with 3 load cases:
  cruise (1g), pull-up (2g), negative gust (-0.5g).

New example blackcat_004_multi_case.py exercises the multi-case
OpenMDAO topology that was built in Milestone 1 but never had a
production example.

Golden test variant added for multi-case regression protection.
```

## Do NOT

- Modify the multi-case topology in HPAStructuralGroup or
  StructuralLoadCaseGroup (it already works)
- Modify _normalise_load_case_inputs()
- Add scipy multi-case support (correctly blocked by NotImplementedError)
- Modify the single-case config or example
- Change optimizer.py
