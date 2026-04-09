# M3c — STEP Export with Deformed Shape

> **Priority**: Phase I Milestone 3 — after M3a (needs FSI result)  
> **Depends on**: M3a (FSI one-way in pipeline) must be done first  
> **Estimated time**: 2–3 h

## Context

The current STEP export (`utils/cad_export.py`) generates spar geometry
at the **undeformed** (jig-shape) position. After structural optimization,
the wing deflects under load — tip deflection can be 1–2.5 meters for a
16.5m half-span.

For manufacturing and pre-cambering, teams need to see the **deformed
shape** (1g flight shape) as STEP geometry. This lets them:
1. Verify the deflected shape looks reasonable
2. Pre-camber the jig shape so the wing deflects to the target shape
3. Communicate with CNC/mandrel suppliers

`FSIResult` (from M3a) contains `.deformed_y` and `.deformed_z` —
the deflected node coordinates. The STEP export just needs to use
these instead of the straight-line node positions.

## Task

### Step 1: Add `deformed_nodes` parameter to STEP export

In `utils/cad_export.py`, modify the main export function
(`export_step_from_csv` or the underlying `_export_with_cadquery`/
`_export_with_build123d`) to accept an **optional** `deformed_nodes`
parameter:

```python
def export_step_from_csv(
    csv_path: Path,
    step_path: Path,
    engine: str = "auto",
    deformed_nodes: Optional[np.ndarray] = None,  # (n_nodes, 3) or None
) -> Path:
```

When `deformed_nodes` is provided, use those coordinates for the loft
spine instead of the straight-line y-positions from the CSV.

When `deformed_nodes` is None, behavior is unchanged (backward compat).

### Step 2: Generate deformed node coordinates from optimization result

The `OptimizationResult` contains `disp` (displacement array, shape
`(n_nodes, 6)`). The deformed coordinates are:

```python
nodes = result.nodes  # (nn, 3) — undeformed
deformed = nodes.copy()
deformed[:, 0] += result.disp[:, 0]  # ux (chordwise)
deformed[:, 1] += result.disp[:, 1]  # uy (spanwise)
deformed[:, 2] += result.disp[:, 2]  # uz (flapwise)
```

Add a helper in `utils/cad_export.py`:

```python
def compute_deformed_nodes(result) -> np.ndarray:
    """Compute deformed node positions from OptimizationResult."""
    nodes = np.array(result.nodes)
    disp = np.array(result.disp)
    return nodes + disp[:, :3]
```

### Step 3: Modify `blackcat_004_fsi.py` (from M3a) to export both shapes

In the FSI example, after optimization:

```python
# Export undeformed STEP (same as before)
export_step_from_csv(csv_path, step_path / "spar_jig_shape.step")

# Export deformed STEP
deformed = compute_deformed_nodes(result)
export_step_from_csv(csv_path, step_path / "spar_flight_shape.step",
                     deformed_nodes=deformed)
```

Also add deformed export to `blackcat_004_optimize.py` as optional
(behind a `--deformed` flag or always-on if the result has displacements).

### Step 4: Verify

- Both STEP files should open in a CAD viewer
- Deformed STEP should show visible upward deflection at the tip
- Deformed STEP should have the same tube cross-sections as undeformed
  (radii/thicknesses don't change — only the spine path changes)
- File size should be similar between the two

### Step 5: Commit

```
feat(cad): add deformed-shape STEP export for flight-shape visualization (M3c)

STEP export now accepts optional deformed_nodes parameter.
When provided, loft spine follows the deflected beam shape instead of
the straight jig-shape.

Helper compute_deformed_nodes() extracts deformed coordinates from
OptimizationResult displacements.

Both blackcat_004_fsi.py and blackcat_004_optimize.py now export
jig-shape and flight-shape STEP files.
```

## Do NOT

- Change the tube cross-section computation (radii/thickness are
  design variables, not affected by deformation)
- Modify FSICoupling class
- Modify the FEM or structural components
- Change the CSV format
- Remove the undeformed STEP export (keep both)
