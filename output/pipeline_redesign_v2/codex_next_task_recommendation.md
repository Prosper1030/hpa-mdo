# Codex Next Task Recommendation

## Short Answer

Start with Fourier-AVL calibration.

Fourier must become a trustworthy fast spanload language before it is used to
guide structure-budgeted Z-state search.

## What Should We Do Next First?

Do MVP 1:

```text
Build the Fourier-AVL calibration layer.
```

The next Codex task should produce:

- `spanload_definition.md`
- `avl_to_fourier_fit.csv`
- `fourier_command_to_avl_realized.csv`
- `fourier_avl_calibration_report.md`
- `recommended_fourier_bridge.md`

Minimum goal:

```text
Take current AVL actual spanload rows and fit them into equivalent
A1/A3/A5/A7 Fourier coefficients, then compare commanded Fourier targets
against AVL-realized Fourier coefficients.
```

## Should We Run Fourier-AVL Calibration Before More Z Sweeps?

Yes.

Do not run more structure-budgeted Z sweeps before Fourier-AVL calibration,
except for tiny debugging checks.

Reason:

```text
Z sweeps depend on spanload.
If Fourier target and AVL actual spanload are not aligned, a Z sweep may be
structurally optimizing the wrong loading pattern.
```

Fourier should first be calibrated into a measured bridge:

```text
commanded Fourier -> AVL realized loading
```

Then structure can search loaded Z states using calibrated spanload families.

## Should We Run More Airfoil NSGA Now?

No.

Do not run broad CST/NSGA now.

Reason:

```text
Airfoil choice depends on actual local Cl/Re.
Actual local Cl/Re depends on AVL spanload.
AVL spanload depends on realized geometry and loaded shape.
Loaded shape depends on structure and mass budget.
```

So the correct order is:

```text
Fourier-AVL calibration
-> structure-budgeted loaded shape
-> AVL recheck
-> Tier2 full-alpha airfoil selection
```

Tier2 full-alpha database can be used later, but not before the structurally
feasible loaded shape is known.

## Should We Run FEM Now?

Not broad FEM.

Use FEM only as a spot-check / trust layer while the pipeline is being
integrated.

Current engineering judgment:

- single-tube EI/GJ is already relatively trusted;
- APDL v3 and corrected S4 shell support tube bending/torsion;
- dual-beam no-wire and simple vertical-wire surrogate are useful for screening;
- true wire, moment bookkeeping, local stress, buckling, joints, and root caps
  still need later validation.

So the next step is not "run FEM on everything." The next step is:

```text
make the spanload -> loaded-Z -> mass closure pipeline coherent,
then FEM-check the finalists or the specific structural quantities that remain
uncertain.
```

## What Should Not Be Done Yet?

Do not:

- run broad aero optimization,
- rerun CST/NSGA,
- change production ranking,
- add hard gates,
- promote `77 kg` as physical truth,
- promote `4.25 m / 13.9 deg` just because mass appears low,
- reject the `6-7 deg` total effective dihedral target,
- use CalculiX B32R tapered pipe mismatch as a calibration factor,
- treat current stress/buckling/joint outputs as final,
- turn FEM into the main design search loop.

## Recommended Next Codex Goal Prompt

```text
Goal: Implement MVP 1 Fourier-AVL calibration for the HPA wing pipeline.

Context:
We are rewriting the pipeline as Mission -> Fourier-AVL calibration ->
structure-budgeted loaded-shape search -> Tier2 airfoil selection.
Do not run broad optimization, do not change production ranking, do not add hard
gates, and do not rerun CST/NSGA.

Task:
Create a Fourier-AVL calibration module/reporting workflow that takes existing
or freshly generated AVL actual spanload data and fits it into equivalent
Fourier coefficients A1/A3/A5/A7.

Requirements:
1. Define one common spanload convention:
   - eta
   - theta
   - y
   - Lprime
   - cl*c
   - circulation proxy
   - normalized loading
   - half-span vs full-span convention
2. Fit AVL actual spanload to A1/A3/A5/A7.
3. Compare Fourier theoretical e and bending proxy against AVL CDi/e_CDi and
   AVL bending proxy.
4. Build a commanded-Fourier -> AVL-realized-Fourier table.
5. Diagnose mismatch:
   - definition mismatch
   - geometry realization issue
   - chord/twist authority issue
   - airfoil alpha_L0 / camber issue
   - loaded dihedral / nonplanar issue
   - AVL reference/setup issue
6. Write reports under:
   output/pipeline_redesign_v2/fourier_avl_calibration_mvp/

Expected outputs:
- spanload_definition.md
- avl_to_fourier_fit.csv
- fourier_command_to_avl_realized.csv
- fourier_avl_calibration_report.md
- recommended_fourier_bridge.md

Acceptance:
- At least one current AVL actual spanload case is fit into Fourier
  coefficients.
- The report says whether Fourier can currently be used as a fast design
  language, or what must be corrected first.
- No production ranking, hard gates, broad optimization, CST/NSGA, or
  structural calibration factors are changed.
```
