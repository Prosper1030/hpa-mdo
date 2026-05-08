# Pipeline v2 Flowchart

## High-Level Flow

```mermaid
flowchart TD
    A["Stage 0: Mission Contract<br/>mass, speed, range, CL_req, power, structure budget"]
    B["Stage 1: Fourier-AVL Calibration<br/>fit AVL actual spanload into A1/A3/A5/A7"]
    C["Stage 2: Fourier Spanload Candidate Generator<br/>low-order spanload families"]
    D["Stage 3: Smooth Geometry Realization<br/>span, area, AR, chord, twist, provisional loaded Z"]
    E["Stage 4: AVL Realization Check<br/>CL_req, CDi, e_CDi, actual spanload, Cl/Re"]
    F["Stage 5: Structure-Budgeted Loaded-Z Search<br/>dual-beam inverse design, 6-7 deg target, 10.5-11.5 kg class"]
    G["Stage 6: AVL Recheck On Realizable Loaded Shape<br/>loaded-shape AVL spanload and local Cl/Re"]
    H["Stage 7: Tier2 Full-Alpha Airfoil Selection<br/>zone top-k, capped combos, profile drag"]
    I["Stage 8: Aero-Structure Closure<br/>rerun AVL, recompute structure, check mass/jig/wire"]
    J["Stage 9: Structural Trust Layer<br/>daily screening vs FEM spot-check vs final grade"]
    K["Stage 10: Final Verification<br/>SU2, APDL/CalculiX, CFRP layup, buckling, drawings"]

    A --> B --> C --> D --> E --> F --> G --> H --> I --> J --> K
    I -- "large mismatch" --> C
    I -- "loaded-Z issue" --> F
    I -- "airfoil loading issue" --> H
```

## Where Each Major Concept Enters

```mermaid
flowchart LR
    M["Mission<br/>42.195 km, 6.5-6.7 m/s, crank power"] --> FAVL["Fourier-AVL Calibration"]
    FAVL --> FGEN["Fourier candidate language"]
    FGEN --> AVL1["AVL actual spanload"]
    AVL1 --> Z["Structure-budgeted loaded Z / effective dihedral"]
    Z --> JIG["Canonical inverse design / jig shape"]
    JIG --> AVL2["AVL recheck on realizable loaded shape"]
    AVL2 --> T2["Tier2 full-alpha airfoil database"]
    T2 --> CLOSE["Aero-structure closure"]
    CLOSE --> FEM["CalculiX / ANSYS / shell FEM trust layer"]
```

## Important Ordering Rule

```text
Tier2 airfoil selection must come after the structurally feasible loaded shape,
because it needs the actual AVL Cl/Re envelope.
```

## Non-Goals In This Spec

- no optimization run,
- no production ranking change,
- no new hard gate,
- no broad CST/NSGA rerun,
- no final structural signoff.
