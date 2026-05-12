# Propulsion Interface Pack

QPROP/XROTOR is an independent propulsion lane.

It may size propeller and drivetrain interfaces for Baseline A, but it is not used to pass the P1 structural blocker and not used to change the current structural release verdict.

## Boundary

- Current role: `independent_propulsion_lane_only`.
- Used in structural blocker verdict: `False`.

## Next Work

- Define propeller interface load cases for the control/structure teams.
- Keep prop optimization out of this release-builder task.
- Feed only reviewed thrust, torque, mass, and CG deltas back into change control.
