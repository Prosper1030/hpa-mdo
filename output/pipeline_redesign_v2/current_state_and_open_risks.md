# Current State And Open Risks

## Current Known State

### Tier2 Full-Alpha Airfoil Database

Tier2 full-alpha airfoil database exists and works as a downstream evidence
source. It should be used after structurally plausible loaded shapes produce
actual AVL `Cl/Re` envelopes.

Do not run broad CST/NSGA now.

### Smooth Production Geometry

Smooth production geometry exists. The new pipeline should preserve smooth,
production-like geometry from the beginning:

- smooth chord,
- smooth twist,
- no faceted production chord,
- explicit chord slope and curvature diagnostics.

### Smooth Tier2 Production Candidate

A smooth Tier2 production airfoil candidate exists, but it should not be treated
as final until it is re-evaluated on the structurally feasible loaded shape.

### Canonical Inverse Design / Jig Shape

The repo's formal mainline is already:

```text
target loaded shape -> inverse design -> jig shape -> realizable loaded shape
-> CFRP tube / discrete layup
```

The new pipeline does not replace that. It places mission, Fourier-AVL
calibration, and structure-budgeted loaded-Z search before final airfoil
selection.

### Structural Validation

Recent structural validation clarified the trust boundary:

- single tube EI/GJ is relatively trusted;
- corrected mid-surface S4 shell supports tube bending/torsion well;
- APDL v3 supports tapered tube bending and single-tube torsion;
- dual-beam no-wire is useful for linear screening;
- simple vertical-wire surrogate bookkeeping is useful;
- true wire, moment bookkeeping, local stress, buckling, root cap, and joints
  are not final truth.

### 77 kg Result

The old `77 kg` class result should not be used as physical truth.

It was an artifact of selector / clearance / recipe-grid behavior. Later
diagnostics found many intermediate rows in the `16-30 kg` band, and the
dominant blocker was not simply "the wing must be 77 kg"; it involved clearance
and moment-closure logic.

### 16 kg-Class / 6-7 Deg Region

`16 kg` class recipes near `6-7 deg` total effective dihedral may be plausible,
but this is not final structure truth yet.

The remaining issues are:

- moment bookkeeping,
- FEM spot-check readiness,
- true wire model,
- mass basis clarity,
- loaded-shape definition clarity.

### 6-7 Deg Total Effective Dihedral Target

The `6-7 deg` target should remain alive.

Important: this means total cruise effective dihedral relative to root or
centerline, not extra elastic deflection only.

Do not reject the `6-7 deg` target just because one diagnostic sweep failed.

### 4.25 m / 13.9 Deg Caution

Do not promote a `4.25 m / 13.9 deg` type state just because mass appears low.

If total loaded dihedral is too high, it may damage AVL spanload, stability,
local Cl distribution, jig feasibility, or manufacturing practicality. It must
go through the same Stage 6 AVL recheck and Stage 8 closure.

## Open Risks

### Risk 1: Fourier And AVL Do Not Mean The Same Thing Yet

Fourier targets may describe an ideal lifting-line distribution that the
realized AVL geometry cannot produce. This can happen because of chord/twist
authority, airfoil alpha_L0, reference-area convention, or loaded dihedral.

Mitigation: do Fourier-AVL calibration before using Fourier as a design driver.

### Risk 2: Loaded-Z Definitions Are Mixed

Aerodynamic surface z, beam-line z, built-in geometric z, elastic deflection,
and total effective dihedral can be accidentally mixed.

Mitigation: write `z_definition_audit.md` and keep every Z field explicit.

### Risk 3: Mass Basis Is Ambiguous

`11.5 kg` can mean different things:

- main tube only,
- main + rear tube,
- full-span spar tube mass,
- tube + wire,
- total structure.

Mitigation: every mass row must write `mass_basis`.

### Risk 4: Airfoil Selection Too Early

If airfoils are selected before the loaded shape is known, the local `Cl/Re`
queries may be wrong.

Mitigation: Tier2 selection waits until Stage 7.

### Risk 5: FEM Overuse Before Model Closure

FEM is useful for trust and spot checks, but it should not replace the sizing
logic before the pipeline has a stable candidate/load/mass contract.

Mitigation: use FEM for spot checks and trust labels, not broad design search.

### Risk 6: Structural Screening Gets Mistaken For Final Structure

Dual-beam/tubing is a screening model. It is useful, but local stress, buckling,
joints, and true nonlinear wire behavior remain outside final trust.

Mitigation: every structural output must include a trust label.

## Engineering Readiness

Ready now:

- write Fourier-AVL calibration spec and module,
- fit AVL actual spanload to Fourier coefficients,
- build a command-vs-realized bridge,
- use that bridge to define structure-budgeted Z search v2.

Not ready yet:

- broad airfoil NSGA,
- final FEM signoff,
- final production ranking update,
- new hard gates,
- drawing-ready structural release.
