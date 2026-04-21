# ESP/OpenCSM Feasibility Spike

Date: 2026-04-20

Status: experimental-go

> 2026-04-21 implementation note: this document is a feasibility spike, not a statement that `esp_rebuilt` is runnable on current `main`. Check `README.md`, `docs/current_status.md`, and the latest blackcat smoke evidence before treating ESP as usable.

Primary conclusion: `ESP/OpenCSM` is worth keeping as an experimental upstream geometry provider for `hpa_meshing_package`, but it is not ready to be the v1 first-class provider. The strongest local evidence for cleaner topology came from OpenVSP's own `SurfaceIntersection` trimmed-CAD route, not from a completed local `serveESP` run.

## Scope

This spike answered five questions without changing `hpa_meshing_package` core dispatch:

1. On this machine, can `ESP/OpenCSM` be installed, called, and minimally used?
2. Is there a real official entry point from OpenVSP into `ESP/OpenCSM`?
3. For thin-sheet / aircraft-assembly geometry, is `ESP/OpenCSM` more likely than the current raw direct-STEP path to produce cleaner topology?
4. If we integrate this into `hpa_meshing_package`, what provider contract makes sense?
5. What should be considered v1-worthy versus explicitly experimental?

Workspace note: the current `hpa_meshing_package/` tree is untracked in the main checkout, so this isolated worktree did not contain it. I read the package context from the main absolute paths you specified and only wrote new spike artifacts inside this worktree.

## Executive Verdict

- `OpenVSP-derived normalization`: go
- `ESP/OpenCSM as a v1 first-class provider`: no-go
- `ESP/OpenCSM as an experimental provider`: go
- `Most practical next provider to prototype`: `openvsp_surface_intersection`

Reason in one sentence: the official ESP/OpenVSP bridge is real and potentially useful, but the best local topology improvement already appeared one step earlier when switching from raw `EXPORT_STEP` to OpenVSP's trimmed `SurfaceIntersection` export.

## Evidence Snapshot

| Topic | Result | Why it matters |
| --- | --- | --- |
| `openvsp` Python bindings in repo `.venv` | pass | We can already read `.vsp3`, export CAD, and run OpenVSP analyses locally. |
| Existing `tests/test_vsp_builder.py` | `12 passed in 5.48s` | Confirms this checkout can actually exercise OpenVSP bindings, not just import them. |
| Raw OpenVSP `EXPORT_STEP` | `46 surfaces`, `0 volumes` in Gmsh | This matches the current fragile shell-based normalization path. |
| Existing origin mesh metadata | `ImportedSurfaceCount=46`, `CandidateFluidVolumeCount=6`, `FluidVolumeCount=1`, `RemovedDuplicateBoundaryFacets=2`, `aircraft dropped outside volume=12` | The current route already shows cleanup / ambiguity pressure. |
| OpenVSP `SurfaceIntersection` trimmed STEP | `38 surfaces`, `3 volumes` in Gmsh | Same upstream `.vsp3`, materially cleaner topology. |
| Official ESP/OpenVSP link | confirmed | `VspSetup` and `UDPRIM vsp3` are documented official entry points. |
| Local ESP runtime | not yet completed | Official macOS arm64 prebuilt exists, but `serveESP` / `serveCSM` are not installed on this machine yet. |

## Question-By-Question Answer

### 1. On this machine, can ESP/OpenCSM be installed, called, and minimally used?

Short answer: install-feasible, not locally run end-to-end yet.

What I confirmed locally:

- Machine: `macOS 26.4.1`, `arm64`
- `openvsp` Python bindings already work from repo `.venv`
- `serveESP`, `serveCSM`, `ocsm`, `vspscript`, `vspaero` are not currently on `PATH`
- Official `ESP129-macos-arm64.tgz` prebuilt exists for this exact platform
- Rosetta is installed on this machine
- `XQuartz` does not appear to be installed, and the official macOS README lists it as a prerequisite for some CAPS apps

What I could not complete inside this spike:

- A full local `serveESP` or `OpenCSM` run from an installed ESP distribution

Why the answer is still "install-feasible":

- The official ESP prebuilt matrix includes `ESP129-macos-arm64.tgz`
- The official macOS README explicitly supports Apple arm64
- A partial download probe succeeded and wrote `/tmp/hpa_esp_probe/ESP129-macos-arm64.tgz`

Why the answer is not a full local "go" yet:

- No installed `serveESP` / `serveCSM` binary was available
- I did not complete extraction + environment setup + browser launch in this session

### 2. Is there a real official entry point from OpenVSP into ESP/OpenCSM?

Yes.

The official evidence is stronger than "someone mentioned it in a forum":

- ESP manual Tool menu includes `VspSetup`, described as a way to initialize ESP from an OpenVSP model.
- The 2024 OpenVSP-to-ESP paper describes an official `UDPRIM vsp3 filename $myfile.vsp3` import path.
- The same paper explains the mechanism:
  - ESP auto-generates an AngelScript for `vspscript`
  - OpenVSP exports surfaces and curves to a STEP file
  - ESP reads that STEP file back in
  - `VspSetup` extracts OpenVSP user parameters into ESP-visible design parameters

Important nuance for this repo's `blackcat_004_origin.vsp3`:

- The file does contain a `UserParmContainer`, but the current entries look like default placeholders (`User_0` ... `User_15`, `GroupName="User_Group"`), not curated ESP-ready design parameters.
- So the geometry entry exists, but the "ESP as a parametric design bridge" value is not fully realized for this specific model yet.

### 3. For thin-sheet / aircraft assembly geometry, is ESP/OpenCSM more likely than the current raw direct-STEP path to produce cleaner topology?

Compared with the current raw direct-STEP route: yes, probably.

Compared with OpenVSP's own trimmed-CAD route: not yet proven to be better.

The most important local result from this spike:

- Raw OpenVSP STEP export gave a shell-style import in Gmsh:
  - `POINTS=144`
  - `CURVES=184`
  - `SURFACES=46`
  - `VOLUMES=0`
- OpenVSP `SurfaceIntersection` trimmed STEP gave a much cleaner import:
  - `POINTS=32`
  - `CURVES=64`
  - `SURFACES=38`
  - `VOLUMES=3`

That matters because the current origin meshing evidence already shows the shell route is forcing cleanup logic:

- `ImportedSurfaceCount=46`
- `CandidateFluidVolumeCount=6`
- `FluidVolumeCount=1`
- `RemovedDuplicateBoundaryFacets=2`
- `MarkerElementsDroppedOutsideVolume.aircraft=12`

Interpretation:

- For this style of aircraft assembly, the fragile part is not only "STEP vs ESP".
- The bigger split is "raw per-surface shell export" versus "topology-normalized trimmed export".
- ESP/OpenCSM remains interesting because:
  - ESP/EGADS emphasizes persistent attributes and watertight tessellation
  - ESP exposes effective topology tools (`ErepEd`)
  - ESP can assemble imported surfaces by component and then `UNION` bodies
- But the local evidence says the first big win is already available from OpenVSP `SurfaceIntersection`.

Practical conclusion:

- `ESP/OpenCSM` is more promising than the repo's current raw `EXPORT_STEP` path.
- It is not yet proven to beat a simpler `OpenVSP SurfaceIntersection -> trimmed STEP -> meshing` provider.

### 4. What provider contract makes sense for hpa_meshing_package?

The current package architecture already wants a geometry-loading layer, so the provider should materialize a normalized geometry artifact before the meshing pipeline.

Recommended contract:

#### Request

```json
{
  "source_kind": "vsp3",
  "source_path": "/abs/path/model.vsp3",
  "provider": "openvsp_surface_intersection",
  "target_representation": "brep_component_volumes",
  "component_hint": "aircraft_assembly",
  "units_hint": "auto",
  "staging_dir": "/abs/path/out/geometry_provider",
  "label_policy": "preserve_component_labels"
}
```

#### Response

```json
{
  "status": "success",
  "provider": "openvsp_surface_intersection",
  "provider_version": "openvsp-runtime",
  "normalized_geometry_path": "/abs/path/out/geometry_provider/normalized.step",
  "representation": "brep_component_volumes",
  "units": "mm",
  "body_count": 3,
  "surface_count": 38,
  "volume_count": 3,
  "label_schema": "component/surface labels from provider",
  "artifacts": {
    "raw_step": "/abs/path/raw.step",
    "provider_log": "/abs/path/provider.log",
    "topology_report": "/abs/path/topology.json"
  },
  "warnings": [],
  "provenance": {
    "source_path": "/abs/path/model.vsp3",
    "command": "provider-owned command or script",
    "source_hash": "..."
  }
}
```

#### Why this contract fits the package

- It preserves the current idea that the meshing core consumes a geometry handle or path.
- It keeps provider-specific complexity outside core recipe / fallback dispatch.
- It gives `hpa_meshing_package` exactly the data it needs for validation:
  - representation type
  - counts
  - units
  - labels
  - provenance
- It lets us compare providers without changing meshing recipes:
  - `direct_step`
  - `openvsp_surface_intersection`
  - `esp_opencsm_vspsetup`

#### Contract rule I would enforce

The provider must always emit a machine-readable topology report before meshing starts.

Minimum fields:

- `representation`
- `units`
- `body_count`
- `surface_count`
- `volume_count`
- `bbox`
- `labels_present`
- `source_kind`
- `provider`
- `provider_version`
- `warnings`

### 5. What belongs in v1, and what should stay experimental?

#### Worth putting into v1

- A provider abstraction at the `geometry` layer
- A normalized-geometry artifact directory and topology report
- An `openvsp_surface_intersection` provider experiment promoted into the first real upstream provider if repeatable
- Provider provenance logging so meshing failures can be traced back to geometry normalization choices

#### Keep experimental

- Direct `ESP/OpenCSM` runtime integration
- Any dependency on `serveESP` session management inside the meshing package
- `VspSetup`-driven design-parameter round-tripping
- Automatic `UNION` / `ErepEd` policy for whole-aircraft assemblies
- Any provider that requires model authors to maintain nontrivial ESP-specific metadata in `.vsp3`

#### My recommendation

- Do not make `ESP/OpenCSM` a first-class v1 provider.
- If you include it in v1 at all, mark it `experimental`.
- Put your first engineering effort into a provider contract plus `openvsp_surface_intersection`.
- Only escalate to `esp_opencsm` after:
  - local install is repeatable
  - at least one `serveESP` / OpenCSM minimal probe is scripted
  - the provider beats the trimmed OpenVSP route on real meshing stability, not just on theory

## Local Probe Details

### Probe A: confirm OpenVSP bindings work locally

Command:

```bash
/Volumes/Samsung SSD/hpa-mdo/.venv/bin/python -m pytest -q tests/test_vsp_builder.py
```

Result:

- `12 passed in 5.48s`

### Probe B: current raw direct-STEP style export

Command:

```bash
/Volumes/Samsung SSD/hpa-mdo/.venv/bin/python \
  /Volumes/Samsung SSD/hpa-mdo/scripts/vsp_to_cfd.py \
  --vsp /Volumes/Samsung SSD/hpa-mdo/data/blackcat_004_origin.vsp3 \
  --out /tmp/hpa_esp_probe/openvsp_export/blackcat_004_origin \
  --formats step iges
```

Artifacts:

- `/tmp/hpa_esp_probe/openvsp_export/blackcat_004_origin.step`
- `/tmp/hpa_esp_probe/openvsp_export/blackcat_004_origin.igs`

Observed sizes:

- STEP: `2105839` bytes
- IGES: `1587195` bytes

Gmsh import probe:

```bash
gmsh /tmp/hpa_esp_probe/inspect_blackcat_step.geo -parse_and_exit -nopopup
```

Result:

- `SURFACES=46`
- `VOLUMES=0`

### Probe C: OpenVSP trimmed CAD via SurfaceIntersection

Minimal command form:

```bash
/Volumes/Samsung SSD/hpa-mdo/.venv/bin/python - <<'PY'
import openvsp as vsp
from pathlib import Path
out_dir = Path('/tmp/hpa_esp_probe/surface_intersection')
out_dir.mkdir(parents=True, exist_ok=True)
vsp.ClearVSPModel()
vsp.ReadVSPFile('/Volumes/Samsung SSD/hpa-mdo/data/blackcat_004_origin.vsp3')
vsp.Update()
vsp.SetAnalysisInputDefaults('SurfaceIntersection')
vsp.SetIntAnalysisInput('SurfaceIntersection', 'STEPFileFlag', (1,))
vsp.SetStringAnalysisInput('SurfaceIntersection', 'STEPFileName', (str(out_dir / 'blackcat_004_origin_trimmed.stp'),))
vsp.SetIntAnalysisInput('SurfaceIntersection', 'IGESFileFlag', (0,))
vsp.SetIntAnalysisInput('SurfaceIntersection', 'P3DFileFlag', (0,))
vsp.SetIntAnalysisInput('SurfaceIntersection', 'SRFFileFlag', (0,))
vsp.SetIntAnalysisInput('SurfaceIntersection', 'CURVFileFlag', (0,))
vsp.ExecAnalysis('SurfaceIntersection')
PY
```

Artifacts:

- `/tmp/hpa_esp_probe/surface_intersection/blackcat_004_origin_trimmed.stp`

Observed size:

- trimmed STEP: `1973186` bytes

Gmsh import probe:

```bash
gmsh /tmp/hpa_esp_probe/inspect_blackcat_trimmed.geo -parse_and_exit -nopopup
```

Result:

- `SURFACES=38`
- `VOLUMES=3`

### Probe D: existing origin meshing evidence

Sources:

- `/Volumes/Samsung SSD/hpa-mdo/.worktrees/origin-su2-high-quality/.tmp/origin_occ_smoke_fix/output/su2_alpha_sweep/geometry/mesh_metadata.json`
- `/Volumes/Samsung SSD/hpa-mdo/.worktrees/origin-su2-high-quality/.tmp/origin_occ_smoke_fix/output/su2_alpha_sweep/alpha_0p0/surface.csv`

Relevant metadata:

- `ImportedSurfaceCount=46`
- `BodySurfaceCount=42`
- `CandidateFluidVolumeCount=6`
- `FluidVolumeCount=1`
- `RemovedDuplicateBoundaryFacets=2`
- `MarkerElementsDroppedOutsideVolume.aircraft=12`

### Probe E: ESP installability on this Mac

Checks:

- `uname -m` -> `arm64`
- `pkgutil --pkgs | rg -i 'rosetta|xquartz'` -> Rosetta present, no XQuartz hit
- `curl -I https://acdl.mit.edu/ESP/PreBuilts/ESP129-macos-arm64.tgz` -> `200 OK`

Partial download artifact:

- `/tmp/hpa_esp_probe/ESP129-macos-arm64.tgz`
- partial size at stop time: `4894720` bytes

Meaning:

- The official package exists for this machine class.
- The local blocker was not "unsupported platform".
- The remaining gap is a real install + environment setup pass, not research uncertainty.

## Why This Is Not A Full ESP Go Yet

Three reasons:

1. I did not complete a local `serveESP` / `OpenCSM` execution.
2. The current `blackcat_004_origin.vsp3` is not obviously set up with meaningful ESP-facing user parameters.
3. OpenVSP's own trimmed export already solved a large part of the topology problem with less operational cost.

That means the burden of proof has shifted.

The next question is no longer "can ESP theoretically help?"

The next question is:

"Can ESP/OpenCSM beat `openvsp_surface_intersection` enough to justify another heavyweight dependency?"

## Recommendation

Decision:

- `ESP/OpenCSM as hpa_meshing_package v1 provider`: no
- `ESP/OpenCSM as experimental provider`: yes

Recommended sequencing:

1. Define the provider contract and topology-report artifact now.
2. Prototype `openvsp_surface_intersection` against the same meshing cases.
3. Only if that still leaves topology/labeling gaps, do a second spike that actually installs ESP and tests:
   - `VspSetup`
   - `UDPRIM vsp3`
   - component assembly
   - `UNION 1`
   - optional `ErepEd`

## Official Evidence

- ESP manual:
  - `VspSetup` exists as an ESP tool for initializing from OpenVSP.
  - `ErepEd` exists for effective topology, specifically to facilitate mesh generation.
  - https://flexcompute.github.io/EngineeringSketchPad/EngSketchPad/ESP/ESP-help.html
- ESP overview paper:
  - `EGADS` adds persistent attribution and watertight tessellation.
  - `OpenCSM` adds parametric feature-tree behavior and sensitivities.
  - server stack runs on Windows, Linux, and MacOS.
  - https://acdl.mit.edu/ESP/Publications/AIAApaper2024-1315.pdf
- OpenVSP-to-ESP paper:
  - official `UDPRIM vsp3` path exists
  - mechanism uses `vspscript`
  - `VspSetup` exposes OpenVSP user parameters inside ESP
  - tested on 30+ OpenVSP models
  - https://acdl.mit.edu/esp/Publications/AIAApaper2024-4304.pdf
- OpenVSP changelog:
  - 2020: trimmed STEP/IGES export can form watertight BREP solids, but import success varies by program
  - 2025: thick/thin intersection and sliver cleanup improved
  - https://github.com/OpenVSP/OpenVSP/blob/main/CHANGELOG.md
- ESP macOS prebuilt / README:
  - official Apple arm64 prebuilt exists
  - macOS install notes and prerequisites
  - https://acdl.mit.edu/ESP/PreBuilts/
  - https://acdl.mit.edu/ESP/PreBuilts/macREADME.txt
