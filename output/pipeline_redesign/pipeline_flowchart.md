# Pipeline Flowchart

## High-Level Flow

```mermaid
flowchart TD
    A["MissionContract<br/>mass, speed, rho, power, span/area box"] --> B["Fourier Target Generator<br/>A1/A3/A5 spanload family"]
    B --> C["Smooth Geometry Realizer<br/>chord, twist, incidence, provisional loaded Z"]
    C --> D["AVL Realization Check<br/>CL trim, CDi, e_CDi, actual Cl/Re"]
    D --> E{"Fourier vs AVL<br/>alignment acceptable?"}
    E -- "No, AVL contract bad" --> F["Fix AVL contract<br/>Sref/Bref, paneling, trim, surfaces"]
    F --> D
    E -- "No, target unrealized" --> G["Update target or geometry<br/>relax Fourier, chord/twist authority"]
    G --> C
    E -- "Yes" --> H["Structure-Budgeted Z-State Search<br/>canonical inverse design"]
    H --> I{"Structural budget pass?<br/>mass, clearance, wire, jig, moment"}
    I -- "No" --> J["Adjust loaded-Z state<br/>or reject geometry for production"]
    J --> H
    I -- "Aero-only pass" --> K["Aero Research Candidate<br/>not production baseline"]
    I -- "Production pass" --> L["Feasible Loaded Shape Shortlist"]
    L --> M["AVL Recheck On Feasible Loaded Shape<br/>actual final Cl/Re envelopes"]
    M --> N["Tier2 Full-Alpha Zone Airfoil Search<br/>root x mid1 x mid2 x tip"]
    N --> O["AVL Rerun With AFILEs<br/>CDi, e_CDi, local Cl"]
    O --> P["Profile Drag Integration<br/>Tier2 actual-query Cd"]
    P --> Q["Dual Leaderboards"]
    Q --> R["Aerodynamic Best"]
    Q --> S["Structure-Feasible Production Candidate"]
```

## Loop Ownership

```mermaid
flowchart LR
    FT["Fourier loop<br/>target spanload shape"] --> AVL["AVL loop<br/>realized spanload"]
    AVL --> STRUCT["Structure loop<br/>requested Z -> jig -> loaded shape"]
    STRUCT --> AVL2["AVL loaded-shape recheck"]
    AVL2 --> AF["Tier2 airfoil loop<br/>profile drag and stall margin"]
    AF --> FINAL["final aero + production recommendations"]

    AVL -. "mismatch tells whether target is realizable" .-> FT
    STRUCT -. "mass/clearance tells allowed loaded-Z band" .-> FT
    STRUCT -. "feasible Z updates actual geometry" .-> AVL2
    AF -. "airfoil changes section behavior; rerun AVL" .-> AVL2
```

## Gate Timing

| Timing | Gate | Action |
|---|---|---|
| Before AVL | Search-box sanity | Reject impossible mass/span/CL cases early |
| After first AVL | Fourier-AVL realization | Update target/geometry or reject target |
| Before airfoil finalization | Structure budget | Search loaded-Z state and jig feasibility |
| After feasible loaded shape | AVL recheck | Freeze actual Cl/Re envelopes |
| After Tier2 combo search | Airfoil quality | Rank aero and production candidates |

## Important Non-Goals

- Do not rerun broad CST/NSGA just to solve a Z-state problem.
- Do not make Fourier power the ranking authority after AVL is available.
- Do not promote Phase 9 proxy or Phase 10 sidecar-only outputs to structural truth.
- Do not select final airfoils before feasible loaded shape and AVL actual Cl/Re are known.
