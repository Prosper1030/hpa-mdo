# Artificial Unit Mesh Report

- status: `pass`
- config: `{'case_id': 'artificial_unit', 'n_span': 4, 'n_perimeter': 16, 'radial_layers': 4, 'near_wall_layers': 2, 'first_layer_height_m': 5e-05, 'near_wall_growth': 1.12, 'farfield_chords': 3.0, 'normal_smoothing_iterations': 1, 'outer_mapping': 'normal'}`
- nodes: `490`
- cells: `384`
- faces: `1248`
- boundary face counts: `{'wing_upper': 32, 'wing_lower': 28, 'tip_left': 16, 'tip_right': 16, 'te_wall': 4, 'closure_wall': 0, 'farfield': 96}`
- non-positive hex volumes: `0`
- nonmanifold faces: `0`

This is the required tiny artificial rectangular-wing unit topology check before
Baseline A case generation.
