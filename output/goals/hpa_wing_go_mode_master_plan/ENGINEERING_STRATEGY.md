# Engineering Strategy

## One Sentence

Use mission power as the top objective, use Fourier as a fast spanload language
only after AVL calibration, use dual-beam structure to find realizable loaded
shapes under a tube-mass budget, use Tier2 airfoils only after actual loaded
shape `Cl/Re` is known, and keep looping until the aero and structure agree.

## Why This Is Goal-Driven

The previous MVP sequence proved that the pieces can connect, but it also showed
that "producing a report" is too weak as an endpoint. The engineering goal is
not a completed checklist. The engineering goal is a candidate that survives the
full chain:

```text
mission power
spanload
geometry
loaded shape
tube mass
jig clearance
wire
airfoil
closure
trust label
```

Go Mode should treat reports as sensors. A report should either move a candidate
toward production-facing status, expose a loopback action, or prove a blocker.

## How The Physics Pieces Interact

### Mission Drives Everything

The mission sets:

- required lift coefficient `CL_req`,
- acceptable drag / crank power,
- speed and Reynolds number range,
- mass budget,
- structural tube/spar budget.

Airfoil drag, induced drag, nonwing reserve, propeller efficiency, and drivetrain
efficiency must all be included in power. A low main-wing drag number by itself
is not mission success.

### Fourier Is A Design Language, Not A Solver Truth

Fourier coefficients are useful for describing spanload families quickly. They
are not automatically what the wing actually realizes.

The current evidence shows that commanded Fourier loading can become
outer-underloaded in AVL. Therefore every Fourier command must pass through a
measured bridge:

```text
commanded Fourier coefficients -> AVL-realized Fourier coefficients
```

If the bridge shows that the geometry cannot realize the command, Go Mode should
modify geometry or diagnose missing authority rather than keep sweeping
unrealizable Fourier targets.

### AVL Owns Actual Spanload And CDi Authority

AVL is the main fast aerodynamic truth for:

- actual spanload,
- induced drag `CDi`,
- `e_CDi`,
- trim angle,
- local `Cl/Re`,
- spanload-derived bending proxy.

AVL can still be wrong if reference area, section geometry, loaded shape, or
airfoil metadata are wrong. When AVL returns surprising results such as
superunit `e_CDi`, Go Mode should audit reference conventions and geometry
before claiming a better wing.

### Smooth Geometry Must Be Production-Like Early

The geometry route should be smooth from the beginning:

- monotone chord,
- smooth twist,
- no faceted chord as final geometry,
- VSP inspection export,
- AVL parity export.

Go Mode may use rough internal variants for diagnosis, but production-facing
candidate packaging must return to smooth geometry.

### Structure Decides Whether The Loaded Shape Is Realizable

The structure path answers:

- can the candidate hit the desired total cruise effective dihedral?
- what tube/spar mass is required?
- does jig clearance pass?
- does wire tension pass?
- are force reactions closed?
- is moment closure a physical failure or bookkeeping uncertainty?

The preferred total cruise effective dihedral target remains `6-7 deg`, but it
must be treated as a physical target, not a slogan. If the mass/clearance/wire
constraints make it impossible, Go Mode must find the nearest practical
compromise and quantify the aerodynamic and structural penalty.

### Airfoil Selection Comes After Loaded Shape

Airfoil selection depends on actual local `Cl/Re`. Actual local `Cl/Re` depends
on AVL spanload on the realizable loaded shape.

Therefore:

```text
loaded-shape AVL actual Cl/Re -> Tier2 airfoil selection
```

not:

```text
airfoil optimization first -> structure later
```

Raw best and conservative best must remain separate. Raw drag wins with query
warnings are not production recommendations.

### Closure Is The Real Test

After selecting airfoils:

1. rerun AVL with selected airfoils;
2. recompute actual spanload;
3. rerun structural response;
4. compare power, spanload, deflection, mass, clearance, and wire.

If the selected airfoil changes spanload enough to change the structure, the
pipeline must loop back. This is not failure; this is the design system behaving
like an aero-structure loop.

### FEM Is For Trust, Not Broad Search

Internal dual-beam/tube models are the daily screening tools.

CalculiX, APDL, and corrected shell FEM should be used to:

- calibrate model assumptions,
- spot-check selected candidates,
- resolve specific trust questions.

FEM should not replace the fast design loop until the candidate set is small.

## Current Engineering Bias

Given the latest closure evidence:

- raw best airfoil path is blocked by query-quality warning;
- conservative best is cleaner but changes spanload and deflection enough to
  require a Z-state loopback;
- high-Z low-mass states must not be promoted without aero and manufacturing
  scrutiny;
- `6-7 deg` target remains important but may require a better beam-to-aero z
  mapping, tube recipe search, or geometry authority change.

Go Mode should begin by attacking the active loopbacks, not by launching a broad
unstructured search.
