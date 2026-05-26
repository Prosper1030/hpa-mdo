# Profile Drag Plausibility Check

## Scope

This report asks whether the accepted CFD drag implies an unreasonable profile/form drag when induced drag is removed.

Inputs:

- Accepted CFD Fine: `CL_primary=1.160934`, `CD_total_physical=0.03326556`
- Old clean XFOIL profile: `CD_profile=0.009368851`
- Old AVL induced drag: `CDi=0.0127613`
- Existing rough XFOIL re-integration at the same old stations: `CD_profile_rough=0.023487768`

## CFD residual after induced drag

Using the same finite-wing geometry and a plausible efficiency range:

| Assumed induced basis | Estimated CDi | CFD residual profile/form CD |
|---|---:|---:|
| `e=1.0` ideal | 0.01216374 | 0.02110182 |
| AVL total-implied `e=0.96569` | 0.01259593 | 0.02066963 |
| AVL Trefftz `e=0.9564` | 0.01271825 | 0.02054731 |
| `e=0.90` conservative | 0.01351526 | 0.01975030 |
| `e=0.85` low | 0.01431028 | 0.01895528 |

The CFD-implied non-induced residual is approximately `0.0190` to `0.0211`. A central value is about `0.0206`.

## Compare against XFOIL profile drag

| Basis | Profile/form CD | Ratio vs clean XFOIL |
|---|---:|---:|
| Old clean XFOIL profile | 0.00936885 | 1.00x |
| CFD residual after AVL-like induced drag | about 0.0206 | about 2.19x |
| Existing rough XFOIL profile re-integration | 0.02348777 | about 2.51x |

At first glance, the CFD residual is much higher than the old clean profile drag. But it is not higher than the existing rough XFOIL bracket. This strongly suggests that the old clean profile-drag basis is optimistic relative to fully turbulent or early-transition behavior.

## Pressure and viscous interpretation

Accepted Fine OpenFOAM `total_physical` split:

| Component | CD |
|---|---:|
| pressure | 0.02295001 |
| viscous | 0.01031555 |
| total | 0.03326556 |

Using AVL total-implied `CDi=0.01259593`, the pressure component still leaves:

```text
pressure residual beyond estimated induced drag
= 0.02295001 - 0.01259593
= 0.01035408
```

That is roughly another clean-XFOIL-profile-sized contribution. Meanwhile, CFD viscous drag alone is:

```text
0.01031555 / 0.00936885 = 1.10
```

So OpenFOAM is not just saying "skin friction is a little higher." It is saying:

- viscous drag alone is already slightly above the old clean XFOIL profile total;
- pressure/form/numerical residual after induced drag is also large;
- total profile/form residual is about twice clean XFOIL.

## Engineering interpretation

The CFD-implied profile/form drag is high if the real wing is assumed to behave like clean, attached, natural-transition XFOIL polars across the span. It is not obviously high if the comparison basis is fully turbulent or rough/forced-transition at `Re ~= 0.29M` to `0.57M`.

This matters because the OpenFOAM run uses SA RANS with no transition model. That is closer to a fully turbulent/early-transition assumption than the clean XFOIL profile integration. The existing rough XFOIL re-query producing `CD_profile=0.02348777` is enough to show that transition treatment alone can create a CD shift of the right order.

However, the CFD pressure/form residual is still too large to accept without a targeted check. It could include:

- real 3D pressure/form and wake losses absent from the XFOIL profile integration;
- local separation or adverse-pressure-gradient effects;
- turbulence-model overprediction under fully turbulent SA;
- mesh/TE/wake/numerical diffusion effects;
- force-group or patch-integration details not visible without spanwise and upper/lower decomposition.

## Plausibility verdict

CFD does not imply an impossible profile drag. It implies a profile/form level inconsistent with the old clean XFOIL basis but consistent in order of magnitude with existing rough/forced-transition XFOIL data.

Therefore the profile-drag evidence leans toward "old clean XFOIL underpredicted drag for a fully turbulent/early-transition comparison," but the CFD pressure/form component remains an unresolved credibility risk.
