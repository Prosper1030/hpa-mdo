# CalculiX 2.22 Manual Capability Audit for Phase 14 Beam Benchmarks

## Scope

This note records the local `docs/Manual/ccx_2.22.pdf` evidence that constrains the B2 tapered-beam and B5 torque-ownership solution hunt.

## Key Findings

| Topic | Manual finding | Engineering impact on Phase 14 |
| --- | --- | --- |
| Beam element family | Section `6.2.33` describes `B32/B32R` as the general-purpose 3D beam elements, internally expanded to volumetric elements. The manual explicitly recommends `B32R` and warns against `B32`, especially when section forces are needed. | The current Mac-local benchmark choice `B32R` is technically aligned with the manual. A B2 mismatch is therefore not enough evidence by itself that the benchmark deck is using the wrong beam element. |
| `*BEAM SECTION, SECTION=PIPE` | Section `7.3` defines `SECTION=PIPE` by outer radius and thickness. | The current beam exporter is using the documented pipe-section input format; B2 is not a simple radius/thickness card syntax bug. |
| Expanded beam output | The beam chapter and section `7.96` state that beam elements are internally expanded for 3D visualization and that `OUTPUT=3D` shows the expanded geometry. `OUTPUT=2D` averages back to the original beam nodes. | For B5, a defensible next probe is to request `OUTPUT=3D` and inspect whether expanded-node kinematics expose torsional response that the current `OUTPUT=2D` centerline `UZ` proxy misses. |
| `SECTION FORCES` | Section `6.2.33` and section `7.96` state that `SECTION FORCES` is intended for beam elements, is mutually exclusive with `OUTPUT=3D`, and replaces averaged beam-node stresses with local beam-section force components. The documented components include axial force, shear forces, torque, and bending moments in the local beam frame. | This is the strongest manual-backed route for B5 torque observability. If we want to prove or disprove `MY` ownership in CalculiX, section-force output is more defensible than continuing to rely on centerline `UZ` only. |
| `GENERAL` beam sections | The manual states that the general section can only be used for user element type `U1`. | A B2 fix that swaps normal `B32R` pipe sections to `GENERAL` is not a valid production-like CalculiX route. If B2 cannot be solved inside normal `PIPE` beams, the next honest fallback is an APDL truth route rather than a `GENERAL` workaround. |
| `*NODAL THICKNESS` | Section `7.94` says that beam elements can receive two nodal thickness values in the local 1 and 2 directions, and that the option only takes precedence when the `NODAL THICKNESS` parameter is selected on the section card. | This is a thickness-override mechanism, not clear evidence of a native tapered circular-pipe radius definition. It may support a controlled sensitivity probe, but it is not a credible one-line substitute for a tapered `PIPE` benchmark. |
| `*NODE FILE` variables | Section `7.96` documents nodal variables in `.frd`, gives `RF,NT` as a valid example, and states that beam `OUTPUT=3D` changes how 1D results are expanded/stored. The basic `U` request is displacement output. Rotational DOFs are not documented here as an obvious beam-nodal output channel. | The current Phase 14 parser only reads `DISP/U`. The manual does not give a simple, already-wired nodal-rotation path for beam torsion, so B5 should not assume that a hidden rotation channel already exists in the current output path. |
| `*NODE PRINT RF` semantics | Section `7.98` defines `RF` as external nodal forces in the `.dat` file, i.e. reactions plus concentrated and distributed loads attached to the node or adjacent elements. In the absence of those loads, they reduce to reactions. | This confirms the B4/B5 bookkeeping rule: raw `RF` totals are not automatically pure support reactions. Any parity gate that compares support forces must continue to correct for applied loads present on the printed support sets. |

## Specific Consequences for B2

1. The present B2 gap is not explained by obviously invalid element selection or pipe-card syntax.
2. `GENERAL` is not an acceptable normal-beam workaround for this benchmark line.
3. `*NODAL THICKNESS` is too ambiguous to declare victory without a controlled probe and an engineering explanation of what geometric quantity it is really varying.
4. If normal `B32R + PIPE` probes remain stuck near the existing `10%` to `12%` band, an APDL truth deck is the cleanest next truth source.

## Specific Consequences for B5

1. `UZ`-only centerline parity is too weak to certify beam-axis torque ownership.
2. The two manual-backed observability upgrades are:
   - `*EL FILE, SECTION FORCES` for local torque/bending resultants.
   - `*NODE FILE, OUTPUT=3D` for expanded-beam kinematics.
3. If neither route gives a stable, engineering-meaningful torsion observable for the current benchmark family, B5 should remain report-only or move to an APDL-required truth lane.

## Bottom-Line Engineering Judgment

The manual does not reveal an overlooked one-line CalculiX feature that obviously resolves either open warning:

- `B2`: still looks like a real tapered-pipe formulation or reference-meaning mismatch, not a trivial deck typo.
- `B5`: still lacks a trustworthy observable in the current report path, but the manual does provide two legitimate channels worth probing before declaring the route APDL-only.
