# Reference Consistency Check

- Mission CL_req used for parity: `1.168531`.
- VSPAERO was run in thin/VLM mode with `GeomSet=SET_NONE`, `ThinGeomSet=SET_ALL`, and `NCPU=1`.
- VSPAERO reference values were explicitly forced to the AVL sidecar header values before each sweep.

## policy_A_performance_candidate

- Sref / Bref / Cref: `33.420058469` / `34.332285818` / `0.985105727`
- Aspect ratio from references: `35.269413`
- AVL CL at alpha=0: `0.679130`
- VSPAERO thin/VLM CL at alpha=0: `0.652044`
- AVL alpha at CL_req: `4.840133 deg`
- VSPAERO thin/VLM alpha at CL_req: `5.110168 deg`
- Offset delta VSPAERO minus AVL: `0.270034 deg`
- AVL CDi/e_CDi at CL_req: `0.012513` / `0.984877`
- VSPAERO CDi/e_CDi at CL_req: `0.013094` / `0.941177`
- Spanload at CL_req, VSPAERO minus AVL normalized lprime RMS/max abs/outer mean abs: `0.039254` / `0.177365` / `0.038401`

## policy_C_conservative_baseline

- Sref / Bref / Cref: `33.420058469` / `34.332285818` / `0.985105727`
- Aspect ratio from references: `35.269413`
- AVL CL at alpha=0: `0.721160`
- VSPAERO thin/VLM CL at alpha=0: `0.666211`
- AVL alpha at CL_req: `4.422815 deg`
- VSPAERO thin/VLM alpha at CL_req: `4.974091 deg`
- Offset delta VSPAERO minus AVL: `0.551277 deg`
- AVL CDi/e_CDi at CL_req: `0.012528` / `0.983711`
- VSPAERO CDi/e_CDi at CL_req: `0.013084` / `0.941849`
- Spanload at CL_req, VSPAERO minus AVL normalized lprime RMS/max abs/outer mean abs: `0.042045` / `0.173782` / `0.050034`

## Judgment

The exported Phase 7 VSP files are reference-consistent with the sidecar AVL headers. The +4 to +5 degree alpha required to hit mission CL is therefore not, by itself, evidence of a broken export; it is the expected result of exporting body-axis / AVL-parity cruise geometry rather than a visualization-normalized geometry whose mission condition is stamped at alpha=0.
