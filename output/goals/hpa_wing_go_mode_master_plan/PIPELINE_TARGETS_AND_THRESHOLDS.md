# Pipeline Targets And Thresholds

## Use Of Thresholds

These values guide autonomous Go Mode decisions. They are not new production
hard gates unless the user explicitly promotes them. They define when a candidate
can be called production-facing, when it is a compromise, and when a blocker must
be declared.

## Mission / Power

| Quantity | Preferred | Acceptable Compromise | Blocker / Loopback |
| --- | ---: | ---: | --- |
| nominal `P_crank` | `<= 180 W` | `180-190 W` with clear benefit elsewhere | `> 190 W` unless no feasible lower-power structure exists |
| conservative `P_crank` | `<= 190 W` | `190-205 W` with explicit risk label | `> 205 W` for production-facing claim |
| power accounting | includes CDi, profile drag, nonwing reserve, prop efficiency, drivetrain efficiency | same | missing any item means no production-facing claim |
| conservative CDi | applied if AVL/reference or closure uncertainty exists | explicit margin reported | missing margin when uncertainty exists |

## Geometry

| Quantity | Preferred | Acceptable Compromise | Loopback |
| --- | --- | --- | --- |
| chord | smooth monotone | local mild deviation with manufacturing explanation | faceted or discontinuous final chord |
| twist | smooth and buildable | mild local correction with report | abrupt twist jumps |
| VSP export | `production_inspection` exists | export warning explained | missing export |
| AVL export | AVL parity export exists | warning explained | missing AVL parity |
| geometry diagnostics | chord slope and curvature reported | partial diagnostics | no diagnostics |

## Fourier-AVL Spanload

| Quantity | Preferred | Acceptable Compromise | Loopback |
| --- | ---: | ---: | --- |
| normalized spanload RMS mismatch | `<= 0.05` | `0.05-0.10` with bridge correction | `> 0.10` |
| outer loading delta | `<= 0.05` | `0.05-0.10` with bridge correction | `> 0.10` |
| `e_CDi` loss vs bridge expectation | `<= 2%` | `2-5%` | `> 5%` |
| Fourier command usability | bridge-corrected | diagnostic-only | raw commanded Fourier used as truth |
| coefficient fit quality | no unit/convention warning | warning carried forward | undefined convention |

## Structure / Loaded Shape

| Quantity | Preferred | Acceptable Compromise | Loopback |
| --- | ---: | ---: | --- |
| total cruise effective dihedral | `6-7 deg` | nearest practical `5.5-9 deg` with penalty | `> 10 deg` or `< 5 deg` without justification |
| jig ground clearance | `>= 20 mm` | `0-20 mm` with manufacturing review | `< 0 mm` |
| tube/spar mass | `10.5-11.5 kg` | `11.5-14.0 kg` if physics requires | `> 14.0 kg` unless blocker proof |
| force closure residual | `<= 2%` | `2-5%` with explanation | `> 5%` |
| support / wire reaction error vs spot check | `<= 5%` | `5-10%` | `> 10%` |
| deflection spot-check error | `<= 5%` | `5-10%` screening only | `> 10%` |
| loaded-shape RMS error | `<= 5%` | `5-8%` screening only | `> 8%` |
| wire utilization | `< 0.8` preferred | `0.8-1.0` with warning | `>= 1.0` or compression/slack unless modeled |

## Moment Closure

| Quantity | Preferred | Acceptable Compromise | Loopback |
| --- | --- | --- | --- |
| physical moment balance | passes | small residual explained | fail |
| bookkeeping residual | closed | unresolved but isolated | mixed with physical fail |
| torque ownership | documented | surrogate label | unknown |

Moment closure should not be a blind hard fail when the evidence indicates a
bookkeeping issue. It must be split into physical and bookkeeping components.

## Airfoil Quality

| Quantity | Preferred | Acceptable Compromise | Loopback |
| --- | --- | --- | --- |
| actual query quality | pass | warning only for raw diagnostic | warning in production candidate |
| archive quality | mission-grade candidate | conservative fallback with penalty | not mission grade without explanation |
| stall margin | `>= 1.0 deg` or positive safe-Cl margin | `0-1.0 deg` with warning | negative margin |
| max local utilization | `<= 0.90` | `0.90-0.95` | `> 0.95` |
| raw vs conservative | both reported | raw rejected, conservative used | raw-only decision |

## Closure Tolerances

| Quantity | Preferred | Acceptable Compromise | Loopback |
| --- | ---: | ---: | --- |
| `e_CDi` change after airfoil selection | `<= 2%` | `2-5%` | `> 5%` |
| spanload change after airfoil selection | `<= 5%` | `5-8%` | `> 8%` |
| deflection change after airfoil selection | `<= 5%` | `5-10%` | `> 10%` |
| clearance change | no sign change and `>= 20 mm` | remains positive | goes negative |
| tube mass change | `<= 2%` | `2-5%` | `> 5%` |
| wire tension change | `<= 5%` | `5-10%` | `> 10%` |

Current closure evidence with spanload changes around `6-7%` and deflection
changes around `12-17%` requires loopback, not production-facing success.

## Structural Trust / FEM

| Quantity | Trusted For | Threshold |
| --- | --- | --- |
| internal tube / dual-beam | daily screening | trust label required |
| corrected mid-surface S4 shell | thin-wall tube diagnostic | `<= 5%` vs closed form/APDL for selected quantities |
| APDL / CalculiX spot checks | selected candidate confirmation | tip deflection `<= 5%`, support/wire reaction `<= 5-10%` |
| current C3D8R solid route | not recommended for global thin-wall tube | do not use for production claim |
| local stress / buckling / joints | final verification only | no production claim until checked |

## Candidate Status Labels

| Label | Meaning |
| --- | --- |
| `production_facing_candidate` | Meets success criteria and closure tolerances with explicit trust labels. |
| `credible_compromise_candidate` | Misses one preferred target but proves why and remains physically coherent. |
| `screening_candidate` | Useful for search but not production-facing. |
| `diagnostic_case` | Used to diagnose a model/physics issue, not a design candidate. |
| `blocked_by_physics` | Bounded attempts show the mission target cannot be met under current assumptions. |
| `blocked_by_model` | Current model/solver ambiguity prevents reliable decision. |
