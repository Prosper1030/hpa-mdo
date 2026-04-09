# M3a — FSI One-Way in Production Pipeline

> **Priority**: Phase I Milestone 3 — first M3 task  
> **Depends on**: M2 Phase 2 complete (F6 done, F8 done or deferred)  
> **Estimated time**: 4–6 h

## Context

`FSICoupling` class in `fsi/coupling.py` is **fully implemented** but
**never called** from the production pipeline. The existing
`examples/blackcat_004_optimize.py` runs a pure structural optimization
with fixed aero loads.

One-way FSI means: run aero → get loads → optimize structure → get
deformed shape → re-run aero on deformed shape → re-optimize → repeat
until tip deflection converges. `FSICoupling.run_one_way()` does a
single pass (aero → structure), while `run_two_way()` iterates.

This task creates a **new production example** that calls
`FSICoupling.run_one_way()`, demonstrating the full MDO loop.

## Task

### Step 1: Create `examples/blackcat_004_fsi.py`

Follow the same 9-step structure as `blackcat_004_optimize.py`, but
replace step 6 (direct optimization) with FSI coupling:

```python
# Steps 1-5: identical to blackcat_004_optimize.py
# (load config, build aircraft, parse VSPAero, find cruise AoA, apply load factor)

# Step 6: FSI one-way coupling (replaces direct optimization)
from hpa_mdo.fsi.coupling import FSICoupling

fsi = FSICoupling(cfg, aircraft, materials_db)
fsi_result = fsi.run_one_way(
    aero_load=design_loads,      # SpanwiseLoad from step 5
    load_factor=1.0,             # already applied in step 5
    optimizer_method="auto",     # use OpenMDAO driver
)

result = fsi_result.optimization_result  # OptimizationResult, same type as before

# Steps 7-9: identical (visualize, summarize, export STEP)
```

**Important**: `FSICoupling.__init__` takes `(cfg, aircraft, materials_db)`.
It does NOT take `load_mapper` in the required args (it's optional and
defaults to None — in which case loads are passed directly).

**Important**: The output directory should be separate:
```python
output_dir = Path(cfg.io.output_dir) / "fsi_one_way"
```

### Step 2: Add FSI config fields to `blackcat_004.yaml`

The config already has FSI stubs but they may not be populated.
Ensure these exist under a top-level `fsi:` section (or wherever
the FSI config lives):

```yaml
fsi:
  coupling: "one-way"       # "one-way" or "two-way"
  max_iterations: 20        # for two-way
  convergence_tol: 1.0e-3   # tip deflection convergence [m]
```

If the config schema doesn't have an `fsi` section yet, add the
Pydantic model in `core/config.py`.

### Step 3: Verify FSI result consistency

After running `blackcat_004_fsi.py`, compare with the pure structural
result from `blackcat_004_optimize.py`:

- Mass should be **very similar** (one-way FSI with fixed aero loads
  should give nearly identical results to pure structural optimization)
- `val_weight: <float>` must be printed as last line
- All constraints must be satisfied (failure ≤ 0, buckling ≤ 0,
  twist ≤ limit, tip_defl ≤ limit)
- STEP file must be generated

### Step 4: Add to test suite

Add a lightweight test (NOT marked slow) that imports FSICoupling
and verifies it can be instantiated without error:

```python
# tests/test_fsi_smoke.py
def test_fsi_coupling_import():
    from hpa_mdo.fsi.coupling import FSICoupling
    assert callable(FSICoupling)
```

The full end-to-end FSI test should be marked `@pytest.mark.slow`.

### Step 5: Commit

```
feat(examples): add blackcat_004_fsi.py with one-way FSI pipeline (M3a)

First production example using FSICoupling.run_one_way().
Demonstrates aero→structure single-pass coupling with the same
9-step pipeline as blackcat_004_optimize.py.

FSI config section added to blackcat_004.yaml.
```

## Do NOT

- Modify `FSICoupling` class itself (M4 already improved it with
  problem reuse — don't regress)
- Modify `blackcat_004_optimize.py` (keep pure structural as baseline)
- Implement two-way FSI in this task (that's Milestone 5)
- Change optimizer.py
- Change any structural component
