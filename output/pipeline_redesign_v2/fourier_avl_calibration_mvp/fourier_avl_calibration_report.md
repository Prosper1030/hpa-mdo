# Fourier-AVL Calibration Report

- Schema: `fourier_avl_calibration_mvp_v1`
- Scope: MVP 1 diagnostic bridge only.
- Production ranking changed: no.
- Hard gates added: no.
- Broad CST/NSGA/FEM run: no.

## Cases

| case | status | r3 command | r3 AVL | e Fourier command | e Fourier AVL-fit | e AVL CDi | RMS | outer delta | quality flags |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| rank_01_sample_1476 | outer_underloaded_authority_limited | -0.028492 | -0.212698 | 0.997565 | 0.865684 | 0.869533 | 0.202387 | 0.28401 | sparse_station_count_for_four_harmonic_fit; legacy_avl_cl_times_chord_converted_to_gamma_unit_conversion |
| rank_02_sample_0692 | outer_underloaded_authority_limited | -0.038614 | -0.217483 | 0.993603 | 0.863492 | 0.854977 | 0.189075 | 0.281396 | sparse_station_count_for_four_harmonic_fit; legacy_avl_cl_times_chord_converted_to_gamma_unit_conversion |
| rank_03_sample_1132 | outer_underloaded_authority_limited | -0.064906 | -0.229941 | 0.983561 | 0.846504 | 0.851681 | 0.178159 | 0.240683 | sparse_station_count_for_four_harmonic_fit; legacy_avl_cl_times_chord_converted_to_gamma_unit_conversion |
| rank_04_sample_1980 | outer_underloaded_authority_limited | -0.034188 | -0.227623 | 0.992338 | 0.855389 | 0.850951 | 0.206832 | 0.30616 | sparse_station_count_for_four_harmonic_fit; legacy_avl_cl_times_chord_converted_to_gamma_unit_conversion |
| rank_05_sample_1932 | outer_underloaded_authority_limited | -0.04219 | -0.235021 | 0.994436 | 0.848634 | 0.852201 | 0.209901 | 0.283287 | sparse_station_count_for_four_harmonic_fit; legacy_avl_cl_times_chord_converted_to_gamma_unit_conversion |
| rank_06_sample_0696 | outer_underloaded_authority_limited | -0.024697 | -0.206024 | 0.998038 | 0.873271 | 0.869194 | 0.194174 | 0.287923 | sparse_station_count_for_four_harmonic_fit; legacy_avl_cl_times_chord_converted_to_gamma_unit_conversion |
| rank_07_sample_0640 | outer_underloaded_authority_limited | -0.035505 | -0.233014 | 0.996216 | 0.848048 | 0.851688 | 0.216318 | 0.291555 | sparse_station_count_for_four_harmonic_fit; legacy_avl_cl_times_chord_converted_to_gamma_unit_conversion |
| rank_08_sample_0904 | outer_underloaded_authority_limited | -0.038093 | -0.227101 | 0.990507 | 0.857323 | 0.852932 | 0.208152 | 0.306246 | sparse_station_count_for_four_harmonic_fit; legacy_avl_cl_times_chord_converted_to_gamma_unit_conversion |
| rank_09_sample_0560 | outer_underloaded_authority_limited | -0.05153 | -0.219207 | 0.992019 | 0.859466 | 0.857695 | 0.181325 | 0.269491 | sparse_station_count_for_four_harmonic_fit; legacy_avl_cl_times_chord_converted_to_gamma_unit_conversion |
| rank_10_sample_1383 | outer_underloaded_authority_limited | -0.031243 | -0.218201 | 0.992017 | 0.868221 | 0.859105 | 0.201102 | 0.287137 | sparse_station_count_for_four_harmonic_fit; legacy_avl_cl_times_chord_converted_to_gamma_unit_conversion |

## Engineering Read

- `rank_01_sample_1476`: legacy station-table loading units were converted to Gamma before fitting; fit uses a sparse station table; treat coefficient magnitudes as diagnostic; AVL actual loading is weaker than commanded loading in the outer span; current MVP evidence cannot separate chord/twist authority, airfoil alpha_L0/camber, loaded-dihedral, and AVL setup without additional case metadata; realized Fourier efficiency is below commanded Fourier efficiency.
- `rank_02_sample_0692`: legacy station-table loading units were converted to Gamma before fitting; fit uses a sparse station table; treat coefficient magnitudes as diagnostic; AVL actual loading is weaker than commanded loading in the outer span; current MVP evidence cannot separate chord/twist authority, airfoil alpha_L0/camber, loaded-dihedral, and AVL setup without additional case metadata; realized Fourier efficiency is below commanded Fourier efficiency.
- `rank_03_sample_1132`: legacy station-table loading units were converted to Gamma before fitting; fit uses a sparse station table; treat coefficient magnitudes as diagnostic; AVL actual loading is weaker than commanded loading in the outer span; current MVP evidence cannot separate chord/twist authority, airfoil alpha_L0/camber, loaded-dihedral, and AVL setup without additional case metadata; realized Fourier efficiency is below commanded Fourier efficiency.
- `rank_04_sample_1980`: legacy station-table loading units were converted to Gamma before fitting; fit uses a sparse station table; treat coefficient magnitudes as diagnostic; AVL actual loading is weaker than commanded loading in the outer span; current MVP evidence cannot separate chord/twist authority, airfoil alpha_L0/camber, loaded-dihedral, and AVL setup without additional case metadata; realized Fourier efficiency is below commanded Fourier efficiency.
- `rank_05_sample_1932`: legacy station-table loading units were converted to Gamma before fitting; fit uses a sparse station table; treat coefficient magnitudes as diagnostic; AVL actual loading is weaker than commanded loading in the outer span; current MVP evidence cannot separate chord/twist authority, airfoil alpha_L0/camber, loaded-dihedral, and AVL setup without additional case metadata; realized Fourier efficiency is below commanded Fourier efficiency.
- `rank_06_sample_0696`: legacy station-table loading units were converted to Gamma before fitting; fit uses a sparse station table; treat coefficient magnitudes as diagnostic; AVL actual loading is weaker than commanded loading in the outer span; current MVP evidence cannot separate chord/twist authority, airfoil alpha_L0/camber, loaded-dihedral, and AVL setup without additional case metadata; realized Fourier efficiency is below commanded Fourier efficiency.
- `rank_07_sample_0640`: legacy station-table loading units were converted to Gamma before fitting; fit uses a sparse station table; treat coefficient magnitudes as diagnostic; AVL actual loading is weaker than commanded loading in the outer span; current MVP evidence cannot separate chord/twist authority, airfoil alpha_L0/camber, loaded-dihedral, and AVL setup without additional case metadata; realized Fourier efficiency is below commanded Fourier efficiency.
- `rank_08_sample_0904`: legacy station-table loading units were converted to Gamma before fitting; fit uses a sparse station table; treat coefficient magnitudes as diagnostic; AVL actual loading is weaker than commanded loading in the outer span; current MVP evidence cannot separate chord/twist authority, airfoil alpha_L0/camber, loaded-dihedral, and AVL setup without additional case metadata; realized Fourier efficiency is below commanded Fourier efficiency.
- `rank_09_sample_0560`: legacy station-table loading units were converted to Gamma before fitting; fit uses a sparse station table; treat coefficient magnitudes as diagnostic; AVL actual loading is weaker than commanded loading in the outer span; current MVP evidence cannot separate chord/twist authority, airfoil alpha_L0/camber, loaded-dihedral, and AVL setup without additional case metadata; realized Fourier efficiency is below commanded Fourier efficiency.
- `rank_10_sample_1383`: legacy station-table loading units were converted to Gamma before fitting; fit uses a sparse station table; treat coefficient magnitudes as diagnostic; AVL actual loading is weaker than commanded loading in the outer span; current MVP evidence cannot separate chord/twist authority, airfoil alpha_L0/camber, loaded-dihedral, and AVL setup without additional case metadata; realized Fourier efficiency is below commanded Fourier efficiency.

## Interpretation Boundary

This calibration can describe the current measured AVL spanload in Fourier language.
It is not a design acceptance gate and should not be interpreted as final structural or airfoil truth.
