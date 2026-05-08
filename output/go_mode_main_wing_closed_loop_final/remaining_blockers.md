# Remaining Blockers

- Candidate-specific CalculiX/APDL decks exist, but the local CalculiX displacement scale does not match the internal structural estimate closely enough to upgrade trust.
- Missing input for upgrade: an apples-to-apples candidate FEM export contract that uses the same load split, support/wire boundary conditions, spar reference geometry, and displacement target basis as the internal inverse-design structural model.
- Final verification still needs an engineer-owned shell/composite/root-joint model and external review.
- Beam-line Z remains a proxy for aerodynamic-surface geometry; the current smooth geometry is AVL/CSV-supported, not a final production CAD release.
- Stability derivative artifact was not found in the candidate package; AVL spanload/CDi are present, but full handling-quality acceptance is outside this closeout.
