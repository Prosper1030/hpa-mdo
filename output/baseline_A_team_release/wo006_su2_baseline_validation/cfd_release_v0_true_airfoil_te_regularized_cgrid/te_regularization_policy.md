# TE Regularization Policy

Allowed variants:

- `gap_0p00`: exact zero-gap baseline for mathematically sharp TE sections.
- `gap_0p02`: introduce `0.02% chord` gap only where the source TE is mathematically zero.
- `gap_0p05`: introduce `0.05% chord` gap only where the source TE is mathematically zero.
- `gap_0p10`: introduce `0.10% chord` gap only where the source TE is mathematically zero.

Rules used in this run:

- Finite true source TE endpoints are preserved. The `cst_tip` source has an
  existing finite TE gap larger than `0.10% chord`; this is source geometry, not
  newly introduced bluntness.
- Only the zero-thickness DAE31 TE endpoint pair is separated for bounded variants.
- The TE x-coordinate and chord endpoints are not moved.
- LE and mid-chord coordinates are not modified by the TE policy.
- Sref-equivalent planform effect is zero because no x-chord endpoint moves; the
  perturbation is a local section-thickness area effect.
