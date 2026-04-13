# Phase 9e Full Wire/Rigging System Report

## Scope
- Phase 9e expands the existing positive-half-span `lift_wire_rigging.json` artifact into a mirrored full-aircraft cable schedule plus a rigging BOM.
- Cable rows now include full-aircraft quantity, total cut length, cable mass, loaded angle, elastic extension, and tension utilization.
- Hardware lines remain count-only placeholders in this phase; they are included so procurement and assembly planning can start before a detailed fitting catalog exists.

## Design Summary

| Role | Layout | Mult | Wires (aircraft) | Cut Length (m) | Cable Mass (kg) | Max Tension (N) | Max Util (%) | Min Margin (N) |
|------|--------|------|------------------|----------------|-----------------|-----------------|--------------|----------------|
| mass_first | single | 5.000 | 2 | 15.374 | 0.0732 | 3941.3 | 57.35 | 2930.9 |
| balanced | single | 2.000 | 2 | 15.382 | 0.0732 | 3695.0 | 53.77 | 3177.2 |
| aero_first | single | 1.000 | 2 | 15.401 | 0.0733 | 3071.4 | 44.69 | 3800.9 |
| dual_anchor | dual | 1.000 | 4 | 30.985 | 0.1475 | 2535.9 | 36.90 | 4336.3 |

## BOM Highlights

| Role | Item | Qty | Length Each (m) | Total Length (m) | Total Mass (kg) | Note |
|------|------|-----|-----------------|------------------|-----------------|------|
| mass_first | dyneema_sk75_2.5mm_wire-1 | 2 | 7.687 | 15.374 | 0.0732 | Mirror pair for wire-1 / wire-1 |
| mass_first | wing_fitting_placeholder | 2 | n/a | n/a | n/a | Count only; mass/cost TBD in later hardware catalog. |
| mass_first | fuselage_anchor_placeholder | 2 | n/a | n/a | n/a | Count only; mass/cost TBD in later hardware catalog. |
| mass_first | turnbuckle_placeholder | 2 | n/a | n/a | n/a | Count only; mass/cost TBD in later hardware catalog. |
| balanced | dyneema_sk75_2.5mm_wire-1 | 2 | 7.691 | 15.382 | 0.0732 | Mirror pair for wire-1 / wire-1 |
| balanced | wing_fitting_placeholder | 2 | n/a | n/a | n/a | Count only; mass/cost TBD in later hardware catalog. |
| balanced | fuselage_anchor_placeholder | 2 | n/a | n/a | n/a | Count only; mass/cost TBD in later hardware catalog. |
| balanced | turnbuckle_placeholder | 2 | n/a | n/a | n/a | Count only; mass/cost TBD in later hardware catalog. |
| aero_first | dyneema_sk75_2.5mm_wire-1 | 2 | 7.700 | 15.401 | 0.0733 | Mirror pair for wire-1 / wire-1 |
| aero_first | wing_fitting_placeholder | 2 | n/a | n/a | n/a | Count only; mass/cost TBD in later hardware catalog. |
| aero_first | fuselage_anchor_placeholder | 2 | n/a | n/a | n/a | Count only; mass/cost TBD in later hardware catalog. |
| aero_first | turnbuckle_placeholder | 2 | n/a | n/a | n/a | Count only; mass/cost TBD in later hardware catalog. |
| dual_anchor | dyneema_sk75_2.5mm_wire-1 | 2 | 4.748 | 9.495 | 0.0452 | Mirror pair for wire-1 / wire-1 |
| dual_anchor | dyneema_sk75_2.5mm_wire-2 | 2 | 10.745 | 21.489 | 0.1023 | Mirror pair for wire-2 / wire-2 |
| dual_anchor | wing_fitting_placeholder | 4 | n/a | n/a | n/a | Count only; mass/cost TBD in later hardware catalog. |
| dual_anchor | fuselage_anchor_placeholder | 4 | n/a | n/a | n/a | Count only; mass/cost TBD in later hardware catalog. |
| dual_anchor | turnbuckle_placeholder | 4 | n/a | n/a | n/a | Count only; mass/cost TBD in later hardware catalog. |

## Findings

- The lightest cable system is `mass_first` at 0.0732 kg for the full aircraft.
- The heaviest cable system is `dual_anchor` at 0.1475 kg, which is still much smaller than the tube discretization penalties found in 9d.
- The highest single-wire tension is on `mass_first` at 3941.3 N.
- Dual-wire layouts increase assembly complexity mainly through wire count and heterogeneous cut lengths, not through cable mass.
- Because the cable mass stays sub-kilogram across all representative designs, future ranking changes will be driven more by tube catalog discreteness and aerodynamic gates than by cable weight.

