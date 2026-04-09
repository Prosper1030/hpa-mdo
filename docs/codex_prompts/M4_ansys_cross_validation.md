# Milestone 4e — ANSYS Cross-Validation Script

**Priority: HIGH** | **Depends on: M4a–d complete** | **Estimated: 4–6 h**

---

## Background

The internal Python FEM (`structure/fem/assembly.py`) uses Timoshenko beam
elements with a penalty-method wire constraint.  Before declaring Phase I
complete we need an independent numerical check against a commercial FE
solver.  The project already ships three ANSYS-compatible exporters:

| Format | File | Element | Use |
|--------|------|---------|-----|
| APDL macro (.mac) | `ansys_export.py → write_apdl()` | BEAM188 + MPC184 | Mechanical APDL batch |
| NASTRAN BDF (.bdf) | `ansys_export.py → write_nastran_bdf()` | CBAR + RBE2 | Nastran / Simcenter |
| Workbench CSV | `ansys_export.py → write_workbench_csv()` | N/A (data only) | External Data import |

This task creates an **automated validation script** that:

1. Runs the production single-case optimizer on `blackcat_004.yaml`
2. Exports the optimized result to APDL + BDF + CSV
3. Extracts key metrics from the internal FEM
4. Generates a structured comparison report (`ansys_crossval_report.txt`)
   ready for manual checking against ANSYS output

The script does **NOT** drive ANSYS automatically — it prepares all inputs
and the expected-value table so the engineer can run ANSYS once and compare.

---

## Step 0 — Read Before Coding (mandatory)

```bash
cat src/hpa_mdo/structure/ansys_export.py
cat src/hpa_mdo/structure/optimizer.py   # OptimizationResult fields
cat examples/blackcat_004_optimize.py     # production pipeline
cat scripts/run_optimization.py           # exports all 3 formats
```

Key facts:
- `ANSYSExporter(cfg, aircraft, result, aero_loads, mat_db)` takes the
  optimized result and mapped aero loads.
- `OptimizationResult` carries `nodes`, `disp`, `vonmises_main`,
  `vonmises_rear` (per-element arrays), `tip_deflection_m`, `twist_max_deg`.
- `write_apdl()` writes BEAM188 + CTUBE sections; loads are nodal Fz (lift)
  and Fz-couples (torque).  Fixed root BC + wire UZ=0 constraint.
- The APDL macro already includes `/POST1` commands for `PLNSOL,U,Z`,
  `PRESOL,SMISC`, and `ETABLE,VONM,S,EQV`.

---

## Step 1 — Create `scripts/ansys_crossval.py`

A standalone script that:

```python
#!/usr/bin/env python3
"""Generate ANSYS cross-validation package for Black Cat 004.

Outputs:
    output/blackcat_004/ansys/
        spar_model.mac          – APDL input deck
        spar_model.bdf          – NASTRAN bulk data
        spar_data.csv           – Workbench CSV
        crossval_report.txt     – Expected FEM results for comparison
"""
```

### 1a. Run the optimizer (reuse production path)

```python
cfg = load_config("configs/blackcat_004.yaml")
aircraft = Aircraft.from_config(cfg)
mat_db = MaterialDB()
# ... (same AoA selection as blackcat_004_optimize.py)
optimizer = SparOptimizer(cfg, aircraft, mapped_loads, mat_db)
result = optimizer.optimize(method="auto")
```

### 1b. Export all three ANSYS formats

```python
exporter = ANSYSExporter(cfg, aircraft, result, export_loads, mat_db)
apdl_path = exporter.write_apdl(ansys_dir / "spar_model.mac")
bdf_path  = exporter.write_nastran_bdf(ansys_dir / "spar_model.bdf")
csv_path  = exporter.write_workbench_csv(ansys_dir / "spar_data.csv")
```

### 1c. Extract internal FEM metrics into report

Write `crossval_report.txt` with the following structure:

```text
================================================================
  HPA-MDO ANSYS Cross-Validation Report
  Generated: <timestamp>
  Config: blackcat_004.yaml
================================================================

--- DESIGN ---
  Main spar material : carbon_fiber_hm (E=<val> GPa, G=<val> GPa)
  Rear spar material : carbon_fiber_hm
  Segments (half-span): [1.5, 3.0, 3.0, 3.0, 3.0, 3.0] m

  Main spar:
    Seg 1: OD=<val>mm, t=<val>mm
    ...
  Rear spar:
    Seg 1: OD=<val>mm, t=<val>mm
    ...

--- BOUNDARY CONDITIONS ---
  Root (y=0): fixed all 6 DOF (both spars)
  Wire at y=7.5m: UZ=0 (main spar only)

--- APPLIED LOADS ---
  Load factor: <aerodynamic_load_factor>
  Total half-span lift: <val> N
  Max lift per span: <val> N/m  (at y=<val> m)
  Max torque per span: <val> N·m/m (at y=<val> m)

--- EXPECTED RESULTS (Internal FEM) ---
  Metric                         Value          ANSYS Target (±5%)
  ─────────────────────────────  ─────────────  ──────────────────
  Tip deflection (uz, y=16.5m)   <val> mm       <val±5%> mm
  Max uz anywhere                <val> mm       <val±5%> mm
  Max Von Mises (main spar)      <val> MPa      <val±5%> MPa
  Max Von Mises (rear spar)      <val> MPa      <val±5%> MPa
  Root reaction Fz               <val> N        <val±5%> N
  Max twist angle                <val> deg      <val±5%> deg
  Total spar mass (full-span)    <val> kg       (check via APDL *GET)

--- PASS CRITERIA ---
  All metrics within ±5% of internal FEM values.
  If any metric exceeds 10%, investigate element formulation
  differences (Euler-Bernoulli vs Timoshenko, shear correction).

--- APDL POST-PROCESSING COMMANDS ---
  ! After running spar_model.mac:
  /POST1
  SET,LAST
  *GET,TIP_UZ,NODE,<tip_node>,U,Z
  *GET,MAX_VM_MAIN,ELEM,0,SMISC,31   ! BEAM188 von Mises
  PRRSOL,FZ                           ! Root reaction
================================================================
```

### 1d. Extract metrics from OptimizationResult

```python
# From result object:
tip_uz_mm = result.tip_deflection_m * 1000.0
max_vm_main_mpa = result.max_stress_main_Pa / 1e6
max_vm_rear_mpa = result.max_stress_rear_Pa / 1e6
twist_deg = result.twist_max_deg

# From the FEM displacement array:
disp = result.disp  # shape (n_nodes, 6)
uz_all = disp[:, 2] * 1000.0  # mm
max_uz_mm = float(np.max(uz_all))

# Root reaction (sum of Fz at constrained nodes):
# Compute from equilibrium: total_reaction = total_applied_lift
total_lift_half_N = float(np.sum(export_loads["lift_per_span"])
    * np.mean(np.diff(aircraft.wing.y)))
```

---

## Step 2 — Add test `tests/test_ansys_crossval.py`

Lightweight test (does NOT require ANSYS):

```python
def test_crossval_report_generation():
    """Verify the cross-validation script produces all expected files."""
    # Run the script as subprocess or import main()
    # Assert files exist:
    #   ansys/spar_model.mac
    #   ansys/spar_model.bdf
    #   ansys/spar_data.csv
    #   ansys/crossval_report.txt
    # Parse crossval_report.txt and check:
    #   - tip deflection value is positive and < 5000 mm
    #   - max VM stress is positive and < 2000 MPa
    #   - mass matches result.total_mass_full_kg
```

---

## Step 3 — Verify APDL macro completeness

Read the generated `spar_model.mac` and verify:
- All `n_beam_nodes` keypoints per spar are written
- CTUBE sections have correct OD and ID per element
- Material properties match `data/materials.yaml`
- Root BC applies `DK,1,ALL,0` and `DK,<nn+1>,ALL,0`
- Wire constraint at correct node
- Force summation ≈ total half-span lift

Add an assertion in the test:
```python
def test_apdl_force_equilibrium():
    """Sum of FK,*,FZ in APDL ≈ total_lift (within 1%)."""
    # Parse spar_model.mac, sum all FK,*,FZ values
    # Compare with export_loads["total_lift"]
```

---

## Acceptance Criteria

| Criterion | Target |
|-----------|--------|
| `spar_model.mac` parseable (no syntax errors) | ✅ |
| `spar_model.bdf` has correct GRID/CBAR/PBARL count | ✅ |
| `crossval_report.txt` has all 7 metrics | ✅ |
| APDL force sum = total lift ± 1% | ✅ |
| test_ansys_crossval passes | ✅ |
| test_golden_blackcat_004 still passes | ✅ |

---

## Do NOT

- Do NOT install or drive ANSYS programmatically
- Do NOT change the internal FEM solver
- Do NOT change existing ANSYS export methods
- Do NOT modify any config YAML
- Do NOT add new design variables or constraints

---

## Verification Commands

```bash
uv run python scripts/ansys_crossval.py
uv run pytest tests/test_ansys_crossval.py -v
uv run pytest tests/test_golden_blackcat_004.py -v
```

---

## Commit Template

```
feat: add ANSYS cross-validation script and report generator (M4-4e)

New script scripts/ansys_crossval.py exports optimized result to all
three ANSYS formats (APDL/BDF/CSV) and generates crossval_report.txt
with expected FEM metrics and ±5% pass criteria for manual comparison.

Co-Authored-By: Claude <noreply@anthropic.com>
```
