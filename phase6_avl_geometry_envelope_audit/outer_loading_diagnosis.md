# Outer Loading Diagnosis

## What Changed Between Archive And Sidecar Actual

The archive envelope is a baseline grading envelope. The sidecar actual envelopes are AVL reruns with different section AFILEs. Because AVL uses the section airfoil geometry/camber line in the lifting-surface model, changing AFILEs changes the local zero-lift/incidence balance and can move local Cl even when span, chord, twist, Sref, and trim CL are unchanged.

| Policy | Zone | Actual Cl max | eta at max | Fourier target max | Target - actual max | Archive Cl max |
|---|---|---:|---:|---:|---:|---:|
| A | root | 1.326623 | 0.160000 | 1.361727 | 0.035104 | 1.558129 |
| A | mid1 | 1.344053 | 0.350000 | 1.420037 | 0.075984 | 1.565775 |
| A | mid2 | 1.026055 | 0.700000 | 1.048531 | 0.022476 | 0.670381 |
| A | tip | 0.894866 | 0.820000 | 0.796663 | -0.098203 | 0.484833 |
| B | root | 1.367049 | 0.160000 | 1.361727 | -0.005322 | 1.558129 |
| B | mid1 | 1.376281 | 0.350000 | 1.420037 | 0.043756 | 1.565775 |
| B | mid2 | 0.897923 | 0.700000 | 1.048531 | 0.150608 | 0.670381 |
| B | tip | 0.885005 | 0.820000 | 0.796663 | -0.088342 | 0.484833 |
| C | root | 1.349903 | 0.160000 | 1.361727 | 0.011824 | 1.558129 |
| C | mid1 | 1.361002 | 0.350000 | 1.420037 | 0.059035 | 1.565775 |
| C | mid2 | 0.994244 | 0.700000 | 1.048531 | 0.054287 | 0.670381 |
| C | tip | 0.858974 | 0.820000 | 0.796663 | -0.062311 | 0.484833 |

## Checked Causes

- Geometry/twist/washout: Policy A and Policy C use the same section y/z/chord/incidence grid. There is no evidence that Policy C lost the loaded-shape geometry; max section Z equals AVL summary loaded tip Z.
- Airfoil alpha_L0 distribution: this is a plausible load-shift contributor. Policy C replaces the inboard seed/DAE sections with CST records, while keeping ClarkY outer sections; AVL sees different section camber/zero-lift behavior.
- Chord distribution: unchanged between policies in the audit rerun. The large outboard chord region is present, so outer underloading is not caused by an accidental tip chord collapse.
- Loaded dihedral: present in the AVL section Z coordinates. The audit does not show a flat-wing fallback.
- AVL trim/reference setup: `Sref`, `Bref`, `Cref`, trim CL, and required CL are consistent across Policy A/B/C.
- Target-vs-AVL mismatch: still present as a spanload-shape mismatch. Policy C has the lowest audit rerun target RMS among A/B/C; mid2 remains below the Fourier target while the first tip station overshoots it, so the issue is not a simple uniform outer underload.

## Airfoil Zero-Lift And Quality Context

| Policy | Zone | Airfoil | source_quality | alpha_L0 deg | safe_clmax |
|---|---|---|---|---:|---:|
| A | root | dae11 | full_polar_candidate_not_mission_grade | -6.137290 | 1.485677 |
| A | mid1 | dae11 | full_polar_candidate_not_mission_grade | -6.137290 | 1.485677 |
| A | mid2 | clarkysm | full_polar_mission_grade_candidate | -4.375424 | 1.304569 |
| A | tip | clarkysm | full_polar_mission_grade_candidate | -4.375424 | 1.304569 |
| B | root | cst_root_nsga2_g05_child_0019_00cc4dca | full_polar_mission_grade_candidate | -7.623426 | 1.637015 |
| B | mid1 | cst_mid1_nsga2_g06_child_0001_a86879e2 | full_polar_mission_grade_candidate | -5.628956 | 1.708488 |
| B | mid2 | cst_mid2_nsga2_g04_child_0024_0b55bfc3 | full_polar_mission_grade_candidate | -1.842013 | 1.247513 |
| B | tip | cst_tip_nsga2_g02_child_0085_cb99bc9c | full_polar_candidate_not_mission_grade | -4.233464 | 1.237480 |
| C | root | cst_root_nsga2_g05_child_0019_00cc4dca | full_polar_mission_grade_candidate | -7.623426 | 1.637015 |
| C | mid1 | cst_mid1_nsga2_g06_child_0001_a86879e2 | full_polar_mission_grade_candidate | -5.628956 | 1.708488 |
| C | mid2 | clarkysm | full_polar_mission_grade_candidate | -4.375424 | 1.304569 |
| C | tip | clarkysm | full_polar_mission_grade_candidate | -4.375424 | 1.304569 |

## Engineering Read

The lower Policy C inboard actual Cl is not suspicious by itself; it is a consequence of rerunning AVL after changing AFILEs. The questionable part is policy semantics: full-polar archive mission grading is tied to a baseline fixed-seed envelope that can be more demanding than the mission-grade sidecar's own actual AVL envelope. That is conservative for screening, but it can reject DAE11 even when a later sidecar assignment would not actually ask it to carry 1.5658 Cl.

This also means the outer loading mismatch should not be diagnosed as an AFILE path or zone-mapping bug from the current evidence. It is a target-vs-actual spanload/twist/camber interaction: the aircraft is trimmed correctly, but the achieved load shape is different from the Fourier target.
