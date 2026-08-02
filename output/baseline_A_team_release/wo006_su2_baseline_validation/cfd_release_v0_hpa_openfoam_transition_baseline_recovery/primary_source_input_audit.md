# WO-006 OpenFOAM v2512 LM Input Audit

This audit applies to the locked same-Fine-mesh diagnostic at
`rho=1.225 kg/m^3`, `U=6.5 m/s`, `nu=1.4607e-5 m^2/s`, `AoA=0.18 deg`,
`Sref=33.420059598 m^2`, and `Cref=1.003721543 m`.  It does not establish the
Phase J `33 C / 80%RH` mission environment.

## Release-local implementation authority

- OpenFOAM fork/release: OpenCFD v2512, not OpenFOAM Foundation v14.
- Installed model source:
  `/Volumes/OpenFOAM-v2512/src/TurbulenceModels/turbulenceModels/RAS/kOmegaSSTLM/`.
- Installed tutorial:
  `/Volumes/OpenFOAM-v2512/tutorials/incompressible/simpleFoam/T3A/`.
- The v2512 model requires `k`, `omega`, `nut`, `gammaInt`, and `ReThetat` and
  inherits the SST state.  The [OpenCFD LM model documentation](https://doc.openfoam.com/2306/tools/processing/models/turbulence/ras/linear-evm/rtm/kOmegaSSTLM/)
  and [NASA Turbulence Modeling Resource](https://tmbwg.github.io/turbmodels/langtrymenter_4eqn.html)
  are consistent with this field architecture.

The HPA case uses wall `zeroGradient` for `gammaInt`/`ReThetat`, external
`freestream` on the farfield, and `inletOutlet` at the nominal outlet.  This is
not textually identical to T3A's inlet/outlet layout, but it is consistent with
the official [freestream](https://doc.openfoam.com/2312/tools/processing/boundary-conditions/rtm/derived/inletOutlet/freestream/)
and [inletOutlet](https://doc.openfoam.com/2212/tools/processing/boundary-conditions/rtm/derived/outlet/inletOutlet/)
semantics for an external-aerodynamics boundary.

## Input classification

| input | value | exact role | engineering classification |
|---|---:|---|---|
| `Tu` | `0.5%` | Gives `k=1.5(U Tu)^2`; the LM correlation uses `0.5`, while the k formula uses `0.005`. | Assumed physical/model input; not measured HPA atmosphere. |
| `k` | `0.001584375 m^2/s^2` | Isotropic-turbulence mapping at `U=6.5 m/s`. | Formula-derived from assumed Tu. |
| `L` | `0.001c = 0.001003721543 m` | Gives the freestream `omega` scale. | Numerical freestream-decay stabilization input; not atmospheric truth. |
| `omega` | `72.4027593 1/s` | `sqrt(k)/(Cmu^0.25 L)`; nominal `k/(nu omega)=1.498`. | Formula-derived; physical validity inherits uncertain L. |
| `gammaInt` | `1` | Freestream/inlet intermittency convention. | Model-recommended/tutorial-derived BC; it does not make the boundary layer fully turbulent. |
| `ReThetat` | `879.6744` | Exactly `1173.51 - 589.428(0.5) + 0.2196/(0.5)^2`. | LM correlation-derived inlet value; not a measured momentum-thickness Reynolds number. |

The underlying model basis is [Langtry and Menter, AIAA Journal 47(12), 2009](https://doi.org/10.2514/1.42362).
The standard installed model does not include the later stationary-crossflow
extension, so swept-wing crossflow transition remains outside this diagnostic's
demonstrated trust boundary.

## Correlation warning interpretation

The installed `kOmegaSSTLM.C` iterates the lambda/theta fixed point until its
error tolerance is met.  `maxLambdaIter(10)` is checked afterward and only
emits a warning; it is not a ten-iteration hard stop.  Raising the setting would
hide evidence without changing the fixed-point result.  Warning frequency must
therefore be reported alongside field finiteness, force trends, and transition
field evolution.  The corresponding OpenCFD implementation is visible in the
[official source browser](https://api.openfoam.com/2506/kOmegaSSTLM_8C_source.html).

## Verified SST-to-LM compatibility rule

A warm start is allowed only after the SST case independently passes its final
100 force gate and has an evolved, finite latest checkpoint on the accepted
Fine mesh.  The transfer preserves `U`, `p`, `phi`, `k`, `omega`, and `nut`,
adds only `gammaInt` and `ReThetat`, switches the model/schemes/solvers, and
starts a fresh LM force history.  SST logs and postProcessing rows are excluded
from the LM gate.  First-order bounded convection is a recovery stabilization
choice and remains a transition-location sensitivity, not validation truth.

## yPlus definition and limitations

The native v2512 `yPlus` object reports face-count min/max/mean.  Required
percentages are calculated directly from the saved final-time patch field.  Its
default `useWallFunction=true` estimate can be optimistic where LM suppresses
k; a separate sequential `useWallFunction=false` postprocess is therefore the
preferred corroboration for an otherwise-qualified LM result.  A temporary
second-object dry-run exposed an OpenFOAM object-registry collision and did not
advance time.  Because both force/field gates subsequently failed, no separate
shear-derived pass was used to rescue or reinterpret them.  The implementation is documented in the
[v2512 yPlus source](https://api.openfoam.com/2512/yPlus_8C_source.html).

Even a qualified numerical result remains a smooth-wall, fixed-AoA,
same-Fine-mesh model-form diagnostic.  It does not cover roughness,
contamination, insects, acoustics, measured free-flight turbulence, crossflow,
mission trim, power, or LM-specific grid independence.
