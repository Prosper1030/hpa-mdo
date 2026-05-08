# Autonomous Execution Policy

## Operating Principle

Codex Go Mode should continuously choose the next action that most directly
reduces uncertainty between the current candidate state and the final
production-facing success criteria.

Do not ask the user to approve every small step. Ask only when:

- the next action would change production ranking or hard gates;
- the next action requires a broad expensive run outside this plan;
- two engineering paths are both plausible but imply different design
  philosophy;
- a blocker is proven and requires a human design trade.

## Default Action Priority

At any point, choose the highest-priority unresolved item:

1. **Data integrity / convention blocker**
   - wrong units,
   - half-span/full-span mismatch,
   - AVL reference area mismatch,
   - loaded-Z definition mismatch,
   - missing mass basis.

2. **Aero authority blocker**
   - Fourier target cannot be realized by AVL,
   - outer loading is consistently weak,
   - local Cl is too high,
   - twist/chord/airfoil authority is insufficient.

3. **Structure feasibility blocker**
   - mass too high,
   - clearance fails,
   - wire fails,
   - force closure fails,
   - moment closure ambiguous.

4. **Airfoil quality blocker**
   - raw best has query warnings,
   - polar coverage missing,
   - `Cl/Re` outside envelope,
   - conservative best too draggy.

5. **Closure blocker**
   - selected airfoils change spanload too much,
   - deflection changes too much,
   - power no longer meets target,
   - geometry no longer production-like.

6. **Packaging / trust blocker**
   - candidate lacks VSP production inspection export,
   - candidate lacks AVL parity export,
   - trust label is ambiguous,
   - FEM spot-check plan is missing.

## Loopback Rules

### Fourier-AVL Loopback

If Fourier target and AVL actual spanload mismatch beyond tolerance:

1. audit definitions and units;
2. fit AVL actual spanload to Fourier coefficients;
3. update bridge/correction map;
4. test whether smoother geometry, chord distribution, twist, loaded dihedral,
   or airfoil alpha_L0/camber can reduce mismatch;
5. if none can reduce mismatch, declare geometry authority blocker.

### Structure Z-State Loopback

If `6-7 deg` total effective dihedral fails mass, clearance, or wire:

1. confirm Z definitions and beam-to-aero mapping;
2. search nearby `z(y)` families, not only scalar tip z;
3. vary tube recipe within credible mass budget;
4. test wire attach / pretension / layout if available;
5. quantify the nearest practical compromise;
6. if all credible compromises fail, declare structural budget blocker.

### Airfoil Selection Loopback

If raw best has query-quality warning:

1. identify the exact zone and airfoil causing the warning;
2. check whether `Cl/Re` is outside polar coverage;
3. choose the best query-pass candidate for that zone;
4. compare raw vs conservative power penalty;
5. reject the raw best if the warning cannot be repaired without new polar
   generation.

Do not run broad CST/NSGA unless Tier2 coverage is proven insufficient for a
production-facing candidate.

### Moment Closure Loopback

If moment closure fails:

1. split physical moment balance from bookkeeping residual;
2. verify loads, signs, root reaction, torque ownership, and half/full-span
   factors;
3. compare against available CalculiX/APDL/shell evidence if the case is small
   enough;
4. if the structure is otherwise feasible but moment closure is bookkeeping-only,
   label it `moment_bookkeeping_unresolved` rather than a hard physical fail;
5. if physical moment balance fails, declare structure model blocker or redesign
   the loading/wire/torque contract.

### Closure Loopback

If closure fails after airfoil selection:

1. if query warning exists, return to airfoil selection;
2. if spanload changes too much, return to Fourier-AVL / geometry control;
3. if deflection or clearance changes too much, return to Z-state structure
   basis;
4. if mass changes too much, return to tube recipe / structural budget;
5. if power misses target but closure is stable, search nearby airfoil or
   spanload compromises.

## When To Keep Iterating

Keep iterating when:

- a candidate improves one major metric without breaking trust labels;
- a loopback identifies a specific controllable variable;
- the design is near a threshold and a bounded local search is justified;
- a warning can be repaired with local artifact generation or a narrower rerun;
- a blocker is suspected but not yet proven by comparable evidence.

## When To Stop With Success

Stop with success only when one candidate satisfies:

- mission power target or documented acceptable compromise;
- smooth production geometry;
- corrected Fourier-AVL spanload bridge or aligned actual spanload;
- structure feasibility with explicit Z definitions;
- tube/spar mass target or quantified minimum credible compromise;
- query-pass conservative airfoil assignment;
- aero-structure closure within tolerance;
- trust label and FEM spot-check plan;
- final candidate package.

## When To Declare Blocker

Declare a blocker when:

- multiple bounded loopbacks fail on the same physical constraint;
- the remaining issue cannot be fixed without changing design philosophy,
  mission assumptions, or production gates;
- required data is missing and cannot be generated locally;
- a solver or model contradiction persists after an apples-to-apples check;
- all credible candidates miss the production-facing criteria for the same
  documented reason.

Blocker declarations must name:

- blocker type,
- evidence artifacts,
- attempted remedies,
- why further autonomous iteration would be low value,
- recommended human decision.

## Forbidden Actions

Do not:

- change production ranking without explicit instruction;
- add new hard gates;
- run broad CST/NSGA by default;
- use query-warning raw airfoil assignments as production recommendations;
- promote `77 kg` or high-Z escape states without closure evidence;
- use moment closure as an unexplained hard fail;
- hide half-span/full-span or Z-definition ambiguity;
- use FEM as broad search;
- claim final structural truth from screening models;
- silently edit unrelated files or revert user-owned changes.
