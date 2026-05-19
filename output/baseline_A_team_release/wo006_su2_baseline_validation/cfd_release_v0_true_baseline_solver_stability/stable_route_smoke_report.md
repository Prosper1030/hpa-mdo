# Stable Route-Smoke Report

- route: `full-wing-mirror`
- operating point: `V=6.5 m/s`, `AoA=0.18 deg`
- force groups: `{'primary': ['airfoil_upper', 'airfoil_lower'], 'total': ['airfoil_upper', 'airfoil_lower', 'physical_tip_left', 'physical_tip_right', 'te_wall'], 'physical_tip_left': ['physical_tip_left'], 'physical_tip_right': ['physical_tip_right'], 'te_wall': ['te_wall']}`
- Sref: `33.420059598 m^2` for the full-wing mirror route
- root_symmetry in force groups: `False`
- accepted_stable_route_smoke: `True`
- simpleFoam_200 returncode: `0`
- simpleFoam_500 returncode: `0`
- CD_primary: `0.03276165`
- CL_primary: `1.133291`
- CD_total: `0.05708291`
- force stability: `{'window': 50, 'Cd': {'last': 0.03276165, 'mean': 0.03275918600000001, 'min': 0.03275756, 'max': 0.03276165, 'span': 4.090000000005201e-06, 'relative_span': 0.0001248504770541368}, 'Cl': {'last': 1.133291, 'mean': 1.1347956200000002, 'min': 1.133291, 'max': 1.13654, 'span': 0.0032490000000000574, 'relative_span': 0.0028630706205933863}, 'Cs': {'last': -6.782386e-05, 'mean': -6.70639644e-05, 'min': -6.782386e-05, 'max': -6.603985e-05, 'span': 1.7840099999999958e-06, 'relative_span': 0.026601618558654668}, 'CmPitch': {'last': -0.1239779, 'mean': -0.12425506200000001, 'min': -0.124575, 'max': -0.1239779, 'span': 0.0005971000000000032, 'relative_span': 0.004805438027144545}, 'status': 'available', 'route_smoke_stable': True}`
- yPlus mean/p95/max: `{'count': 29952, 'min': 0.0189722, 'mean': 0.5678595352296987, 'p90': 0.8781874000000001, 'p95': 1.0904245, 'p99': 1.8354890999999969, 'max': 2.65697}`
