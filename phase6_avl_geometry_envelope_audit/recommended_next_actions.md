# Recommended Next Actions

1. Keep the main ranking and hard gates unchanged. This audit found an envelope-policy conservatism, not a geometry-file defect.
2. Label the current archive envelope explicitly as `baseline_loaded_avl_grading_envelope`, because it is not rebuilt from each sidecar AVL rerun.
3. For diagnostics only, add a future optional report that compares `baseline_archive_required_cl` against `assignment_actual_required_cl`; do not use it as a gate unless the project decides to change policy.
4. If DAE11 rescue remains interesting, evaluate a mission-grade sidecar audit that grades DAE11 against the actual DAE11-root/mid1 sidecar AVL envelope. Keep that separate from the current archive grading policy.
5. For outer loading, focus next on small twist/incidence and Fourier target consistency studies rather than AVL file plumbing. The parsed Policy A/C files show correct loaded Z, reference dimensions, and AFILE zone mapping.
