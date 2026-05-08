# Candidate Limit Load Recommendation

## Recommendation

The safe submission design load factor is `1.75G`.

Reason: 1.75G is inside the repaired candidate-equivalent FEM checked range and has comfortable internal margins. The internal model also passes 2.0G, 2.5G, and barely 3.0G, but buckling/ovalization and joint/attach details are not candidate-specific validated shell or hardware truth.

## Key Margins

- 1.75G wire utilization: `0.578`
- 2.0G wire utilization: `0.660`
- 3.0G wire utilization: `0.990`
- estimated first fail: `wire_tension` at `n = 3.030`
- FEM checked range: up to `2.00G` on the repaired candidate-equivalent route

## Reporting Boundary

- You can report `1.75G validated for the current engineering submission package`.
- You can report `2.0G internal/FEM-equivalent pass` with the same caveat.
- Do not report `3.0G design load factor`; it is an estimated near-wire-limit point, not a validated design target.
