# WO-006H Reopened CFD HPC Package

This package is for current Baseline A main-wing CFD route escalation after
the reopened WO-006H local campaign. It targets the missing serious cases,
not just already-successful smaller no-BL controls:

- finer no-BL topology probes at `h=0.05` and `h=0.04`;
- an alternate Gmsh 3D Delaunay probe at `h=0.04`;
- preserved-interface BL/core probes with Gmsh algorithms 1 and 10;
- an interface-remesh control that must remain rejected if unmatched faces
  remain.

It does not change external geometry or authority values.

Run from a machine with this repo, Gmsh, SU2, and Python dependencies:

```bash
export REPO_ROOT=/path/to/hpa-mdo
bash /path/to/this/package/run_hpc_campaign.sh
```

For Slurm:

```bash
cd "$REPO_ROOT"
sbatch /path/to/this/package/slurm_wo006h_mesh_ladder.sbatch
```

Acceptance is not "SU2 ran." A result is usable only after authority, marker,
BL/y+, mesh quality, force stability, convergence, and mesh-sensitivity gates
pass. No-BL mesh rungs are resource/sign/marker controls, not HPA drag truth.
