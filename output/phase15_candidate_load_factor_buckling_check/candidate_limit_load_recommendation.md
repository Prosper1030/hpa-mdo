# Candidate Limit Load Recommendation

## Recommendation

The internal fixed-design load-factor boundary for submission planning is `1.75G`.

Reason: 1.75G is inside the repaired candidate-equivalent FEM checked range and has comfortable internal modeled margins. This is not a full-wing structural signoff because global buckling, rear-spar/rib bracing, root fitting, wire attach, and termination strength remain unresolved.

## Key Margins

- 1.75G wire utilization: `0.578`
- 2.0G wire utilization: `0.660`
- 3.0G wire utilization: `0.990`
- estimated first fail: `wire_tension` at `n = 3.030`
- FEM checked range: up to `2.00G` on the repaired candidate-equivalent route

## Reporting Boundary

- You can report `1.75G internal fixed-design modeled limits clear`.
- You can report `2.0G internal/FEM-equivalent modeled limits clear` with the same caveat.
- Do not report `1.5G / 1.75G full-wing pass`; full-wing global buckling and hardware details are not closed.
- Do not report `3.0G design load factor`; it is an estimated near-wire-limit point, not a validated design target.
