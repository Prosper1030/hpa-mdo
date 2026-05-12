# Current Pathfinder P1 Load-Path + Mass Closure

Final verdict: `p1_local_load_path_ready_for_coupon_fem`
Candidate: `eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__carbon_face_collar_y2p328__rear75`

## C04 Local Load Path

- Baseline eccentric peel margin: `-0.893`.
- Installed fix: `saddle_ring_yoke_plus_secondary_clamp`.
- Installed fix governing margin: `0.8876`.
- C04 status: `pass_with_saddle_ring_yoke_fix`.

## Mass / CG / Tail / Closure

- Added C04 fix mass: `0.093839` kg.
- Added 3 m spar-splice mass: `3.847` kg.
- Updated total screening mass basis: `106.828608` kg.
- Managed final CG: `0.75` m; forward rebalance `0.057304` m.
- Tail trim status: `pass`; delta_H margin `4.44437926207778` deg.
- Bounded physical twist: `1.906952370757391` deg.
- Root bending ratio after mass scale: `0.9715900764251212`.
- Updated closure verdict: `ready_for_fem_apdl_loadcase_package`.

## Boundary

Local load-path surrogate plus mass-integrated screening closure. Ready verdict means the P1 C04 fix may proceed to coupon/local FEM; it is not final adhesive, laminate, buckling, tail hardware, or flight-aircraft sign-off.

QPROP/XROTOR remains an independent propulsion lane and is not used in this structural blocker verdict.