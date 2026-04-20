# Origin SU2 High-Quality Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current `origin.vsp3 -> SU2` baseline into a repo-native, mesh-study-aware aerodynamic workflow that is good enough for comparison work, while making tail coverage explicit and traceable.

**Architecture:** Keep `origin.vsp3` as the only geometry truth, keep VSPAero and SU2 landing in the same shared aero bundle, and improve the weakest link in order: geometry/tail coverage contract, mesh preset contract, mesh generation quality, SU2 run provenance, then final mesh-study gate logic. Avoid introducing a second external workflow unless the repo-native route is proven insufficient.

**Tech Stack:** Python 3.10, pytest, OpenVSP Python bindings, Gmsh Python API, shared SU2 v8.4.0 installation, existing `hpa_mdo.aero` modules, matplotlib/pandas bundle writer.

---

## File Map

- `src/hpa_mdo/aero/origin_geometry_contract.py`
  - New focused module that builds a machine-readable summary of what `origin.vsp3` contains for the aero path, including `Main Wing / Elevator / Fin` coverage and whether controls were extracted.
- `src/hpa_mdo/aero/origin_gmsh_mesh.py`
  - Current external-flow mesher. Extend it with mesh presets, STEP/OCC-first routing, STL fallback, and mesh metadata strong enough for study comparisons.
- `src/hpa_mdo/aero/origin_su2.py`
  - Current SU2 case preparation/runner. Extend it with mesh preset selection, richer case metadata, run provenance, and convergence-quality reporting.
- `src/hpa_mdo/aero/origin_quality_gate.py`
  - New focused module for mesh-study verdict logic and summarized comparison metrics.
- `src/hpa_mdo/aero/origin_aero.py`
  - Keep this as the orchestration layer that writes the final bundle and pulls together VSPAero, SU2, geometry contract, and quality gate results.
- `scripts/origin_aero_sweep.py`
  - CLI surface for the upgraded workflow. Add mesh-preset and mesh-study controls without moving solver logic into the script.
- `docs/hi_fidelity_validation_stack.md`
  - Update the stale statement that SU2 is still blueprint-only. Keep the wording honest: runnable baseline exists, but quality still needs work.
- `tests/test_origin_geometry_contract.py`
  - New tests for tail coverage and geometry contract artifacts.
- `tests/test_origin_gmsh_mesh.py`
  - Add mesh preset and fallback routing tests.
- `tests/test_origin_su2.py`
  - Add preset propagation, case metadata, and convergence/provenance tests.
- `tests/test_origin_aero.py`
  - Add bundle integration tests for geometry contract, mesh-study outputs, and verdict wiring.
- `tests/test_origin_quality_gate.py`
  - New tests for quality gate math and verdict rules.
- `tests/test_aero_sweep.py`
  - Extend only where needed so shared SU2 ingestion preserves the new run-quality metadata and notes.

### Task 1: Freeze The Origin Geometry Contract And Tail Coverage Evidence

**Files:**
- Create: `src/hpa_mdo/aero/origin_geometry_contract.py`
- Modify: `src/hpa_mdo/aero/origin_aero.py`
- Modify: `src/hpa_mdo/aero/__init__.py`
- Create: `tests/test_origin_geometry_contract.py`
- Modify: `tests/test_origin_aero.py`
- Modify: `docs/hi_fidelity_validation_stack.md`

- [ ] **Step 1: Write the failing geometry contract tests**

Add `tests/test_origin_geometry_contract.py` with tests like:

```python
from pathlib import Path
from types import SimpleNamespace


def test_build_origin_geometry_contract_reports_empennage(monkeypatch, tmp_path: Path) -> None:
    from hpa_mdo.aero.origin_geometry_contract import build_origin_geometry_contract

    origin_vsp = tmp_path / "origin.vsp3"
    origin_vsp.write_text("stub\n", encoding="utf-8")
    cfg = SimpleNamespace(
        io=SimpleNamespace(vsp_model=origin_vsp, airfoil_dir=tmp_path / "airfoils")
    )

    monkeypatch.setattr(
        "hpa_mdo.aero.origin_geometry_contract.load_config",
        lambda _: cfg,
    )
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_geometry_contract.summarize_vsp_surfaces",
        lambda *args, **kwargs: {
            "source_path": str(origin_vsp),
            "main_wing": {"name": "Main Wing", "controls": []},
            "horizontal_tail": {"name": "Elevator", "controls": []},
            "vertical_fin": {"name": "Fin", "controls": []},
        },
    )

    contract = build_origin_geometry_contract(config_path=tmp_path / "blackcat.yaml")

    assert contract["origin_vsp_path"] == str(origin_vsp.resolve())
    assert contract["tail_geometry_confirmed"] is True
    assert contract["control_surface_contract_confirmed"] is False
    assert contract["surfaces"]["horizontal_tail"]["name"] == "Elevator"
    assert contract["surfaces"]["vertical_fin"]["name"] == "Fin"
```

Also extend `tests/test_origin_aero.py` with a bundle-level assertion like:

```python
assert payload["metadata"]["origin_geometry_contract"]["tail_geometry_confirmed"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/pytest \
  tests/test_origin_geometry_contract.py \
  tests/test_origin_aero.py -q
```

Expected: FAIL because `origin_geometry_contract.py` does not exist yet and the bundle does not include this metadata.

- [ ] **Step 3: Write the minimal geometry contract implementation**

Create `src/hpa_mdo/aero/origin_geometry_contract.py` with a focused API:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hpa_mdo.aero.vsp_introspect import summarize_vsp_surfaces
from hpa_mdo.core.config import load_config


def build_origin_geometry_contract(*, config_path: str | Path) -> dict[str, Any]:
    cfg = load_config(config_path)
    origin_vsp = Path(cfg.io.vsp_model).expanduser().resolve()
    airfoil_dir = getattr(getattr(cfg, "io", None), "airfoil_dir", None)
    summary = summarize_vsp_surfaces(origin_vsp, airfoil_dir=airfoil_dir)

    surfaces = {
        key: value
        for key, value in (
            ("main_wing", summary.get("main_wing")),
            ("horizontal_tail", summary.get("horizontal_tail")),
            ("vertical_fin", summary.get("vertical_fin")),
        )
        if value is not None
    }
    tail_geometry_confirmed = "horizontal_tail" in surfaces and "vertical_fin" in surfaces
    control_surface_contract_confirmed = all(
        len(surface.get("controls") or []) > 0
        for name, surface in surfaces.items()
        if name in {"horizontal_tail", "vertical_fin"}
    )
    return {
        "origin_vsp_path": str(origin_vsp),
        "tail_geometry_confirmed": tail_geometry_confirmed,
        "control_surface_contract_confirmed": control_surface_contract_confirmed,
        "surfaces": surfaces,
    }


def write_origin_geometry_contract(output_dir: str | Path, contract: dict[str, Any]) -> str:
    path = Path(output_dir).expanduser().resolve() / "origin_geometry_contract.json"
    path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    return str(path)
```

Wire it into `src/hpa_mdo/aero/origin_aero.py` so `run_origin_aero_sweep(...)` writes the JSON artifact and injects both:

- `origin_geometry_contract`
- `origin_geometry_contract_json`

into `bundle["metadata"]`.

Export the helper from `src/hpa_mdo/aero/__init__.py`.

- [ ] **Step 4: Update the stale high-fidelity doc**

In `docs/hi_fidelity_validation_stack.md`, replace the current SU2 row with wording like:

```md
| CFD / SU2 | `src/hpa_mdo/aero/origin_su2.py`, `src/hpa_mdo/aero/origin_gmsh_mesh.py`, `scripts/origin_aero_sweep.py` | 已有 runnable baseline | 可做 origin geometry 的單一 case / alpha sweep baseline 與結果讀回；目前仍不是高品質 drag 真值，mesh study 與 near-wall quality 尚待補強 |
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/pytest \
  tests/test_origin_geometry_contract.py \
  tests/test_origin_aero.py -q
```

Expected: PASS

- [ ] **Step 6: Commit**

Run:

```bash
git add -p src/hpa_mdo/aero/origin_geometry_contract.py src/hpa_mdo/aero/origin_aero.py src/hpa_mdo/aero/__init__.py tests/test_origin_geometry_contract.py tests/test_origin_aero.py docs/hi_fidelity_validation_stack.md
git commit -m "feat: add origin geometry contract artifact"
```

### Task 2: Add A Versioned Mesh Preset Contract

**Files:**
- Modify: `src/hpa_mdo/aero/origin_gmsh_mesh.py`
- Modify: `src/hpa_mdo/aero/origin_su2.py`
- Modify: `scripts/origin_aero_sweep.py`
- Modify: `tests/test_origin_gmsh_mesh.py`
- Modify: `tests/test_origin_su2.py`

- [ ] **Step 1: Write the failing mesh preset tests**

Extend `tests/test_origin_gmsh_mesh.py` with tests like:

```python
def test_origin_mesh_presets_have_expected_names() -> None:
    from hpa_mdo.aero.origin_gmsh_mesh import ORIGIN_SU2_MESH_PRESETS

    assert set(ORIGIN_SU2_MESH_PRESETS) == {
        "baseline",
        "study_coarse",
        "study_medium",
        "study_fine",
    }


def test_study_fine_is_tighter_than_study_coarse() -> None:
    from hpa_mdo.aero.origin_gmsh_mesh import ORIGIN_SU2_MESH_PRESETS

    coarse = ORIGIN_SU2_MESH_PRESETS["study_coarse"]
    fine = ORIGIN_SU2_MESH_PRESETS["study_fine"]
    assert fine["near_body_size_factor"] < coarse["near_body_size_factor"]
    assert fine["farfield_size_factor"] < coarse["farfield_size_factor"]
```

Extend `tests/test_origin_su2.py` with:

```python
assert result["mesh_preset"] == "study_medium"
assert result["generated_mesh"]["PresetName"] == "study_medium"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/pytest \
  tests/test_origin_gmsh_mesh.py \
  tests/test_origin_su2.py -q
```

Expected: FAIL because no named preset catalog exists yet.

- [ ] **Step 3: Implement the preset catalog and propagation**

In `src/hpa_mdo/aero/origin_gmsh_mesh.py`, add a stable preset catalog and resolver:

```python
ORIGIN_SU2_MESH_PRESETS = {
    "baseline": {
        "upstream_factor": 1.0,
        "downstream_factor": 3.0,
        "lateral_factor": 1.2,
        "vertical_factor": 1.2,
        "near_body_size_factor": 0.035,
        "farfield_size_factor": 0.12,
        "distance_min_factor": 0.08,
        "distance_max_factor": 0.55,
    },
    "study_coarse": {
        "near_body_size_factor": 0.055,
        "farfield_size_factor": 0.18,
        "distance_min_factor": 0.12,
        "distance_max_factor": 0.80,
    },
    "study_medium": {
        "near_body_size_factor": 0.028,
        "farfield_size_factor": 0.10,
        "distance_min_factor": 0.07,
        "distance_max_factor": 0.45,
    },
    "study_fine": {
        "near_body_size_factor": 0.018,
        "farfield_size_factor": 0.075,
        "distance_min_factor": 0.05,
        "distance_max_factor": 0.30,
    },
}


def resolve_origin_mesh_options(
    *,
    preset_name: str = "baseline",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = dict(DEFAULT_STL_EXTERNAL_FLOW_OPTIONS)
    resolved.update(ORIGIN_SU2_MESH_PRESETS[preset_name])
    if overrides:
        resolved.update(overrides)
    return resolved
```

Update `generate_stl_external_flow_mesh(...)` metadata to include:

```python
"PresetName": preset_name,
```

Update `prepare_origin_su2_alpha_sweep(...)` to accept:

```python
mesh_preset: str = "baseline"
```

and thread that into generated mesh metadata and case metadata. Add CLI support in `scripts/origin_aero_sweep.py`:

```python
parser.add_argument(
    "--su2-mesh-preset",
    default="baseline",
    choices=["baseline", "study_coarse", "study_medium", "study_fine"],
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/pytest \
  tests/test_origin_gmsh_mesh.py \
  tests/test_origin_su2.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

Run:

```bash
git add -p src/hpa_mdo/aero/origin_gmsh_mesh.py src/hpa_mdo/aero/origin_su2.py scripts/origin_aero_sweep.py tests/test_origin_gmsh_mesh.py tests/test_origin_su2.py
git commit -m "feat: add origin su2 mesh presets"
```

### Task 3: Add STEP/OCC-First Meshing With STL Fallback

**Files:**
- Modify: `src/hpa_mdo/aero/origin_gmsh_mesh.py`
- Modify: `src/hpa_mdo/aero/origin_su2.py`
- Modify: `tests/test_origin_gmsh_mesh.py`
- Modify: `tests/test_origin_su2.py`

- [ ] **Step 1: Write the failing OCC routing tests**

Add tests like:

```python
def test_generate_origin_external_flow_mesh_prefers_step_when_available(monkeypatch, tmp_path: Path) -> None:
    from hpa_mdo.aero.origin_gmsh_mesh import generate_origin_external_flow_mesh

    step_path = _write_text(tmp_path / "origin_surface.step", "ISO-10303-21;")
    stl_path = _write_text(tmp_path / "origin_surface.stl", _tetrahedron_stl())
    called = {}

    monkeypatch.setattr(
        "hpa_mdo.aero.origin_gmsh_mesh.generate_step_occ_external_flow_mesh",
        lambda *args, **kwargs: (
            called.setdefault("mode", "step"),
            {"MeshMode": "step_occ_box", "PresetName": kwargs["preset_name"]},
        )[1],
    )

    generate_origin_external_flow_mesh(
        step_path=step_path,
        stl_path=stl_path,
        output_path=tmp_path / "mesh.su2",
        preset_name="study_medium",
    )

    assert called["mode"] == "step"
```

And:

```python
def test_generate_origin_external_flow_mesh_falls_back_to_stl(monkeypatch, tmp_path: Path) -> None:
    from hpa_mdo.aero.origin_gmsh_mesh import (
        GmshExternalFlowMeshError,
        generate_origin_external_flow_mesh,
    )

    step_path = _write_text(tmp_path / "origin_surface.step", "ISO-10303-21;")
    stl_path = _write_text(tmp_path / "origin_surface.stl", _tetrahedron_stl())

    monkeypatch.setattr(
        "hpa_mdo.aero.origin_gmsh_mesh.generate_step_occ_external_flow_mesh",
        lambda *args, **kwargs: (_ for _ in ()).throw(GmshExternalFlowMeshError("bad step")),
    )
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_gmsh_mesh.generate_stl_external_flow_mesh",
        lambda *args, **kwargs: {
            "MeshMode": "stl_external_box",
            "PresetName": kwargs["preset_name"],
            "Nodes": 42,
        },
    )

    metadata = generate_origin_external_flow_mesh(
        step_path=step_path,
        stl_path=stl_path,
        output_path=tmp_path / "mesh.su2",
        preset_name="study_medium",
    )

    assert metadata["MeshMode"] == "stl_external_box_fallback"
    assert "FallbackReason" in metadata
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/pytest \
  tests/test_origin_gmsh_mesh.py \
  tests/test_origin_su2.py -q
```

Expected: FAIL because the dispatcher and OCC-first path do not exist yet.

- [ ] **Step 3: Implement the STEP/OCC dispatcher**

Add a new dispatcher in `src/hpa_mdo/aero/origin_gmsh_mesh.py`:

```python
def generate_origin_external_flow_mesh(
    *,
    step_path: str | Path | None,
    stl_path: str | Path,
    output_path: str | Path,
    preset_name: str = "baseline",
    mesh_overrides: dict[str, Any] | None = None,
    prefer_step_occ: bool = True,
) -> dict[str, Any]:
    if prefer_step_occ and step_path is not None:
        try:
            return generate_step_occ_external_flow_mesh(
                step_path,
                output_path,
                preset_name=preset_name,
                options=mesh_overrides,
            )
        except GmshExternalFlowMeshError as exc:
            fallback = generate_stl_external_flow_mesh(
                stl_path,
                output_path,
                preset_name=preset_name,
                options=mesh_overrides,
            )
            fallback["MeshMode"] = "stl_external_box_fallback"
            fallback["FallbackReason"] = str(exc)
            return fallback

    return generate_stl_external_flow_mesh(
        stl_path,
        output_path,
        preset_name=preset_name,
        options=mesh_overrides,
    )
```

Implement `generate_step_occ_external_flow_mesh(...)` in the same module using Gmsh OCC import and the same `aircraft` / `farfield` marker contract. Keep it narrow: one closed outer box, one body shell, same volume export shape as the STL route.

Update `src/hpa_mdo/aero/origin_su2.py` so auto-mesh uses:

```python
generated_mesh = generate_origin_external_flow_mesh(
    step_path=geometry["step"],
    stl_path=geometry["stl"],
    output_path=mesh_source,
    preset_name=mesh_preset,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/pytest \
  tests/test_origin_gmsh_mesh.py \
  tests/test_origin_su2.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

Run:

```bash
git add -p src/hpa_mdo/aero/origin_gmsh_mesh.py src/hpa_mdo/aero/origin_su2.py tests/test_origin_gmsh_mesh.py tests/test_origin_su2.py
git commit -m "feat: prefer step-backed origin su2 meshing"
```

### Task 4: Add SU2 Run Provenance And Convergence-Quality Metadata

**Files:**
- Modify: `src/hpa_mdo/aero/origin_su2.py`
- Modify: `src/hpa_mdo/aero/aero_sweep.py`
- Modify: `src/hpa_mdo/aero/origin_aero.py`
- Modify: `tests/test_origin_su2.py`
- Modify: `tests/test_aero_sweep.py`
- Modify: `tests/test_origin_aero.py`

- [ ] **Step 1: Write the failing provenance tests**

Add tests like:

```python
def test_run_prepared_origin_su2_alpha_sweep_records_history_summary(monkeypatch, tmp_path: Path) -> None:
    from hpa_mdo.aero.origin_su2 import (
        prepare_origin_su2_alpha_sweep,
        run_prepared_origin_su2_alpha_sweep,
    )

    origin_vsp_path = _write_text(tmp_path / "origin.vsp3", "stub")
    mesh_path = _write_text(tmp_path / "origin_mesh.su2", _sample_su2_mesh_text())
    fake_solver = _write_text(
        tmp_path / "fake_su2.sh",
        '''
        #!/bin/sh
        printf '"Time_Iter","Outer_Iter","Inner_Iter","CD","CL","CMy"\n0,0,49,0.0400,0.9900,-0.0200\n' > history.csv
        exit 0
        ''',
    )
    fake_solver.chmod(0o755)

    cfg = _fake_cfg(tmp_path, origin_vsp_path)
    monkeypatch.setattr("hpa_mdo.aero.origin_su2.load_config", lambda _: cfg)
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_su2._resolve_origin_reference_values",
        lambda _: {"sref": 35.175, "bref": 33.0, "cref": 1.13, "xcg": 0.25, "ycg": 0.0, "zcg": 0.0},
    )
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_su2._export_origin_cfd_geometry",
        lambda *, vsp3_path, output_dir: {
            "stl": str(_write_text(Path(output_dir) / "origin_surface.stl", "solid wing\nendsolid wing")),
            "step": str(_write_text(Path(output_dir) / "origin_surface.step", "ISO-10303-21;")),
        },
    )

    prepared = prepare_origin_su2_alpha_sweep(
        config_path=tmp_path / "blackcat.yaml",
        output_dir=tmp_path / "su2_alpha_sweep",
        aoa_list=[0.0],
        mesh_path=mesh_path,
    )
    summary = run_prepared_origin_su2_alpha_sweep(
        prepared["sweep_dir"],
        su2_binary=str(fake_solver),
    )

    assert summary["cases"][0]["status"] == "completed_but_weak"
    assert summary["cases"][0]["history_summary"]["final_inner_iter"] == 49
    assert summary["cases"][0]["history_summary"]["final_cl"] == 0.99
```

And in `tests/test_origin_aero.py`:

```python
assert payload["metadata"]["su2_run_summary"]["cases"][0]["mesh_preset"] == "study_medium"
assert payload["metadata"]["su2_run_summary"]["cases"][0]["status"] in {
    "completed_converged",
    "completed_but_weak",
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/pytest \
  tests/test_origin_su2.py \
  tests/test_aero_sweep.py \
  tests/test_origin_aero.py -q
```

Expected: FAIL because the current summaries only report `completed` / `dry_run` and do not store history-derived provenance.

- [ ] **Step 3: Implement history summary and quality status**

In `src/hpa_mdo/aero/origin_su2.py`, add a helper like:

```python
def summarize_su2_history(history_path: Path, runtime_cfg: Path) -> dict[str, Any]:
    rows = _load_history_rows(history_path)
    last_row = rows[-1]
    cfg_values = _read_cfg_values(runtime_cfg)
    iter_cap = int(float(cfg_values.get("ITER", DEFAULT_SU2_ITER)))
    final_iter = int(_parse_float(last_row.get("Inner_Iter") or last_row.get("ITER")) or 0)
    final_cl = _parse_float(last_row.get("CL") or last_row.get("LIFT"))
    final_cd = _parse_float(last_row.get("CD") or last_row.get("DRAG"))
    final_cm = _parse_float(last_row.get("CMy") or last_row.get("CMY") or last_row.get("MOMENT_Y"))
    converged = final_iter < iter_cap - 1
    return {
        "final_inner_iter": final_iter,
        "iter_cap": iter_cap,
        "final_cl": final_cl,
        "final_cd": final_cd,
        "final_cm": final_cm,
        "status": "completed_converged" if converged else "completed_but_weak",
    }
```

Use that summary in `run_prepared_origin_su2_alpha_sweep(...)` and store:

- `mesh_preset`
- `geometry_export`
- `history_summary`
- run-level `status`

Then teach `src/hpa_mdo/aero/aero_sweep.py` to append a note fragment like:

```python
notes = f"alpha_source={alpha_note}; run_status={case_status}; mesh_preset={mesh_preset}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/pytest \
  tests/test_origin_su2.py \
  tests/test_aero_sweep.py \
  tests/test_origin_aero.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

Run:

```bash
git add -p src/hpa_mdo/aero/origin_su2.py src/hpa_mdo/aero/aero_sweep.py src/hpa_mdo/aero/origin_aero.py tests/test_origin_su2.py tests/test_aero_sweep.py tests/test_origin_aero.py
git commit -m "feat: add origin su2 run provenance metadata"
```

### Task 5: Add The Mesh-Study Quality Gate

**Files:**
- Create: `src/hpa_mdo/aero/origin_quality_gate.py`
- Modify: `src/hpa_mdo/aero/origin_aero.py`
- Modify: `scripts/origin_aero_sweep.py`
- Create: `tests/test_origin_quality_gate.py`
- Modify: `tests/test_origin_aero.py`

- [ ] **Step 1: Write the failing quality-gate tests**

Add `tests/test_origin_quality_gate.py` with tests like:

```python
from hpa_mdo.aero.aero_sweep import AeroSweepPoint


def test_assess_origin_mesh_study_returns_usable_for_comparison() -> None:
    from hpa_mdo.aero.origin_quality_gate import assess_origin_mesh_study

    points = {
        "study_coarse": [
            AeroSweepPoint("su2", 0.0, 1.00, 0.040, -0.020, None, None, "coarse.csv", "mesh_preset=study_coarse"),
        ],
        "study_medium": [
            AeroSweepPoint("su2", 0.0, 1.01, 0.039, -0.021, None, None, "medium.csv", "mesh_preset=study_medium"),
        ],
        "study_fine": [
            AeroSweepPoint("su2", 0.0, 1.01, 0.0385, -0.021, None, None, "fine.csv", "mesh_preset=study_fine"),
        ],
    }

    verdict = assess_origin_mesh_study(points_by_preset=points)

    assert verdict["verdict"] == "usable_for_comparison"
    assert verdict["cd_spread_abs"] < 0.002
```

And:

```python
def test_assess_origin_mesh_study_flags_baseline_only_when_spread_is_large() -> None:
    from hpa_mdo.aero.origin_quality_gate import assess_origin_mesh_study

    points = {
        "study_coarse": [
            AeroSweepPoint("su2", 0.0, 0.94, 0.060, -0.010, None, None, "coarse.csv", "mesh_preset=study_coarse"),
        ],
        "study_medium": [
            AeroSweepPoint("su2", 0.0, 1.02, 0.044, -0.021, None, None, "medium.csv", "mesh_preset=study_medium"),
        ],
        "study_fine": [
            AeroSweepPoint("su2", 0.0, 1.08, 0.036, -0.034, None, None, "fine.csv", "mesh_preset=study_fine"),
        ],
    }

    verdict = assess_origin_mesh_study(points_by_preset=points)

    assert verdict["verdict"] == "still_baseline_only"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/pytest \
  tests/test_origin_quality_gate.py \
  tests/test_origin_aero.py -q
```

Expected: FAIL because there is no mesh-study verdict module yet.

- [ ] **Step 3: Implement the verdict module and bundle wiring**

Create `src/hpa_mdo/aero/origin_quality_gate.py`:

```python
from __future__ import annotations

from typing import Any, Sequence

from hpa_mdo.aero.aero_sweep import AeroSweepPoint


def assess_origin_mesh_study(*, points_by_preset: dict[str, Sequence[AeroSweepPoint]]) -> dict[str, Any]:
    cd_values = []
    cl_values = []
    cm_values = []
    for points in points_by_preset.values():
        for point in points:
            if point.cd is not None:
                cd_values.append(float(point.cd))
            if point.cl is not None:
                cl_values.append(float(point.cl))
            if point.cm is not None:
                cm_values.append(float(point.cm))

    cd_spread = max(cd_values) - min(cd_values) if cd_values else None
    cl_spread = max(cl_values) - min(cl_values) if cl_values else None
    cm_spread = max(cm_values) - min(cm_values) if cm_values else None
    usable = (
        cd_spread is not None and cl_spread is not None and cm_spread is not None
        and cd_spread <= 0.002
        and cl_spread <= 0.03
        and cm_spread <= 0.03
    )
    return {
        "verdict": "usable_for_comparison" if usable else "still_baseline_only",
        "cd_spread_abs": cd_spread,
        "cl_spread_abs": cl_spread,
        "cm_spread_abs": cm_spread,
    }
```

Then extend `src/hpa_mdo/aero/origin_aero.py` and `scripts/origin_aero_sweep.py` so the CLI can accept multiple presets:

```python
parser.add_argument(
    "--mesh-study-presets",
    nargs="+",
    default=None,
    choices=["baseline", "study_coarse", "study_medium", "study_fine"],
)
```

When `--mesh-study-presets` is provided:

- prepare/run one SU2 sweep per preset
- collect the parsed SU2 points by preset
- write `mesh_study_summary.json`
- write `mesh_study_report.md`
- inject `mesh_study_verdict` into `analysis_bundle.json`

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/pytest \
  tests/test_origin_quality_gate.py \
  tests/test_origin_aero.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

Run:

```bash
git add -p src/hpa_mdo/aero/origin_quality_gate.py src/hpa_mdo/aero/origin_aero.py scripts/origin_aero_sweep.py tests/test_origin_quality_gate.py tests/test_origin_aero.py
git commit -m "feat: add origin su2 mesh study quality gate"
```

### Task 6: Run The End-To-End Verification Slice And Real Smokes

**Files:**
- No new source files required beyond prior tasks
- Verification artifacts expected under: `.tmp/origin_quality_smoke/`

- [ ] **Step 1: Run the full targeted test slice**

Run:

```bash
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/pytest \
  tests/test_origin_geometry_contract.py \
  tests/test_origin_gmsh_mesh.py \
  tests/test_origin_su2.py \
  tests/test_origin_quality_gate.py \
  tests/test_origin_aero.py \
  tests/test_aero_sweep.py \
  tests/test_vsp_builder.py \
  tests/test_vspaero_parser.py -q
```

Expected: PASS

- [ ] **Step 2: Run a real single-preset baseline smoke**

Run:

```bash
rm -rf .tmp/origin_quality_smoke && mkdir -p .tmp/origin_quality_smoke
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python scripts/origin_aero_sweep.py \
  --config configs/blackcat_004.yaml \
  --out .tmp/origin_quality_smoke/output \
  --aoa 0 \
  --prepare-su2 \
  --auto-mesh-su2 \
  --su2-mesh-preset study_medium \
  --run-su2
```

Expected:

- `.tmp/origin_quality_smoke/output/analysis_bundle.json` exists
- `.tmp/origin_quality_smoke/output/origin_geometry_contract.json` exists
- `.tmp/origin_quality_smoke/output/su2_results.csv` exists
- the bundle metadata includes `tail_geometry_confirmed=true`

- [ ] **Step 3: Run a real mesh-study dry run**

Run:

```bash
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python scripts/origin_aero_sweep.py \
  --config configs/blackcat_004.yaml \
  --out .tmp/origin_quality_smoke/mesh_study \
  --aoa -2 0 2 4 \
  --prepare-su2 \
  --auto-mesh-su2 \
  --mesh-study-presets study_coarse study_medium study_fine \
  --dry-run-su2
```

Expected:

- `mesh_study_summary.json` exists
- `analysis_bundle.json` contains `mesh_study_verdict`
- each preset directory preserves the `aircraft` / `farfield` marker contract

- [ ] **Step 4: Inspect the verdict bundle**

Run:

```bash
python3 - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path(".tmp/origin_quality_smoke/mesh_study/analysis_bundle.json").read_text())
print(payload["metadata"]["origin_geometry_contract"]["tail_geometry_confirmed"])
print(payload["metadata"]["mesh_study_verdict"]["verdict"])
PY
```

Expected:

- first line prints `True`
- second line prints either `usable_for_comparison` or `still_baseline_only`

- [ ] **Step 5: Commit any final report/doc adjustments**

If verification reveals a real bug, return to the matching task above,
implement the minimal fix there, and commit it with that task's scope.
If verification is clean, stop here without creating another commit.
