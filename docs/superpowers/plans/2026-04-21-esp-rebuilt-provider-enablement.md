# ESP Rebuilt Provider Enablement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `esp_rebuilt` from a registry-only stub into a real `hpa_meshing_package` geometry provider that can materialize topology-clean geometry for `aircraft_assembly` and complete at least one real `blackcat_004` `coarse` run.

**Architecture:** Keep the existing provider-aware package contract, but replace the current `not_materialized` placeholder with a staged ESP pipeline: runtime discovery, OpenVSP-to-ESP rebuild, normalized geometry export, topology artifact generation, then the existing Gmsh route. Fail loudly and machine-readably at each stage so the package never again confuses "research spike says feasible" with "main can run it now".

**Tech Stack:** Python 3.10, `pytest`, existing `hpa_meshing_package` provider contract, local OpenVSP runtime, local ESP/OpenCSM binaries (`serveESP`, `serveCSM`, `ocsm`), Gmsh Python API

---

## Current Blocker Snapshot

- `hpa_meshing_package/src/hpa_meshing/providers/esp_rebuilt.py` is a stub that always returns `status="not_materialized"`.
- This machine does not currently expose `serveESP`, `serveCSM`, `ocsm`, or `ESP` on `PATH`.
- The last real attempt to run `esp_rebuilt` failed before meshing with `failure_code="geometry_provider_not_materialized"`.
- Repo docs contain a valid feasibility spike, but that spike was never promoted into a runnable provider; this mismatch has already confused downstream work.

## File Structure

### New files

- `hpa_meshing_package/src/hpa_meshing/providers/esp_runtime.py`
  - Runtime discovery helpers for `serveESP`, `serveCSM`, `ocsm`, version/capability probing, and machine-readable diagnostics.
- `hpa_meshing_package/src/hpa_meshing/providers/esp_pipeline.py`
  - Focused ESP materialization pipeline: prepare inputs, launch official rebuild flow, collect normalized geometry, and emit topology artifacts.
- `hpa_meshing_package/tests/test_esp_runtime.py`
  - Unit tests for runtime discovery, missing-binary reporting, and capability serialization.
- `hpa_meshing_package/tests/test_esp_rebuilt_provider.py`
  - Provider-contract tests for missing runtime, failed materialization, and successful artifact handoff.

### Existing files to modify

- `hpa_meshing_package/src/hpa_meshing/providers/esp_rebuilt.py`
  - Replace the unconditional stub path with a real provider that delegates to the new runtime/pipeline modules.
- `hpa_meshing_package/src/hpa_meshing/providers/__init__.py`
  - Keep `esp_rebuilt` registered as experimental until smoke evidence exists, but wire it to the real materializer.
- `hpa_meshing_package/src/hpa_meshing/schema.py`
  - Add more precise ESP failure metadata if the existing enums/fields are too coarse.
- `hpa_meshing_package/README.md`
  - Update the provider status section once `esp_rebuilt` can actually materialize geometry.
- `hpa_meshing_package/docs/current_status.md`
  - Promote the status wording only after the blackcat `coarse` smoke succeeds.
- `hpa_meshing_package/docs/esp_opencsm_feasibility.md`
  - Add a dated note that the spike has been superseded by implementation status once the provider is live.

## Task 1: Freeze Runtime Discovery And Fail-Loud Diagnostics

**Files:**
- Create: `hpa_meshing_package/src/hpa_meshing/providers/esp_runtime.py`
- Create: `hpa_meshing_package/tests/test_esp_runtime.py`
- Modify: `hpa_meshing_package/src/hpa_meshing/providers/esp_rebuilt.py`

- [ ] **Step 1: Write the failing runtime tests**

Create `hpa_meshing_package/tests/test_esp_runtime.py` with focused tests like:

```python
from pathlib import Path


def test_detect_esp_runtime_reports_missing_binaries(monkeypatch):
    from hpa_meshing.providers.esp_runtime import detect_esp_runtime

    monkeypatch.setattr("hpa_meshing.providers.esp_runtime.shutil.which", lambda _: None)

    runtime = detect_esp_runtime()

    assert runtime.available is False
    assert runtime.binaries["serveESP"] is None
    assert runtime.binaries["serveCSM"] is None
    assert runtime.binaries["ocsm"] is None
    assert "serveESP" in runtime.missing


def test_detect_esp_runtime_collects_binary_paths(monkeypatch, tmp_path: Path):
    from hpa_meshing.providers.esp_runtime import detect_esp_runtime

    fake_root = tmp_path / "esp" / "bin"
    fake_root.mkdir(parents=True)
    fake_serve = fake_root / "serveESP"
    fake_csm = fake_root / "serveCSM"
    fake_ocsm = fake_root / "ocsm"
    for path in (fake_serve, fake_csm, fake_ocsm):
        path.write_text("#!/bin/sh\n", encoding="utf-8")

    def fake_which(name: str):
        return str({"serveESP": fake_serve, "serveCSM": fake_csm, "ocsm": fake_ocsm}[name])

    monkeypatch.setattr("hpa_meshing.providers.esp_runtime.shutil.which", fake_which)

    runtime = detect_esp_runtime()

    assert runtime.available is True
    assert runtime.binaries["serveESP"] == str(fake_serve)
    assert runtime.binaries["serveCSM"] == str(fake_csm)
    assert runtime.binaries["ocsm"] == str(fake_ocsm)
```

- [ ] **Step 2: Run the runtime tests to verify they fail**

Run:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m pytest tests/test_esp_runtime.py -q
```

Expected: FAIL because `esp_runtime.py` does not exist yet.

- [ ] **Step 3: Write the minimal runtime discovery module**

Create `hpa_meshing_package/src/hpa_meshing/providers/esp_runtime.py` with a small focused API:

```python
from __future__ import annotations

from dataclasses import dataclass
import shutil


@dataclass(frozen=True)
class EspRuntimeStatus:
    available: bool
    binaries: dict[str, str | None]
    missing: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "binaries": self.binaries,
            "missing": self.missing,
        }


def detect_esp_runtime() -> EspRuntimeStatus:
    binaries = {
        "serveESP": shutil.which("serveESP"),
        "serveCSM": shutil.which("serveCSM"),
        "ocsm": shutil.which("ocsm"),
    }
    missing = [name for name, path in binaries.items() if path is None]
    return EspRuntimeStatus(
        available=not missing,
        binaries=binaries,
        missing=missing,
    )
```

Update `hpa_meshing_package/src/hpa_meshing/providers/esp_rebuilt.py` so the missing-runtime path is explicit:

```python
runtime = detect_esp_runtime()
if not runtime.available:
    return GeometryProviderResult(
        provider="esp_rebuilt",
        provider_stage="experimental",
        status="failed",
        geometry_source="esp_rebuilt",
        source_path=request.source_path,
        geometry_family_hint=request.geometry_family_hint,
        provider_version="esp-runtime-missing",
        topology=GeometryTopologyMetadata(
            representation="provider_failed",
            source_kind=request.source_path.suffix.lstrip(".") or "unknown",
            units=None if request.units_hint == "auto" else request.units_hint,
            notes=["ESP/OpenCSM runtime not found on PATH"],
        ),
        artifacts={"provider_log": provider_log},
        provenance={"runtime": runtime.to_dict()},
        warnings=["ESP/OpenCSM binaries missing; provider did not materialize geometry."],
        notes=[],
    )
```

- [ ] **Step 4: Run the runtime tests to verify they pass**

Run:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m pytest tests/test_esp_runtime.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -p hpa_meshing_package/src/hpa_meshing/providers/esp_runtime.py \
  hpa_meshing_package/src/hpa_meshing/providers/esp_rebuilt.py \
  hpa_meshing_package/tests/test_esp_runtime.py
git commit -m "test: 鎖定 esp runtime discovery 與 fail-loud 診斷"
```

## Task 2: Replace The Stub With A Real Materialization Pipeline

**Files:**
- Create: `hpa_meshing_package/src/hpa_meshing/providers/esp_pipeline.py`
- Create: `hpa_meshing_package/tests/test_esp_rebuilt_provider.py`
- Modify: `hpa_meshing_package/src/hpa_meshing/providers/esp_rebuilt.py`

- [ ] **Step 1: Write the failing provider-contract tests**

Create `hpa_meshing_package/tests/test_esp_rebuilt_provider.py` with tests like:

```python
from pathlib import Path

from hpa_meshing.schema import GeometryProviderRequest


def test_esp_rebuilt_reports_runtime_missing_as_failed(monkeypatch, tmp_path: Path):
    from hpa_meshing.providers.esp_rebuilt import materialize
    from hpa_meshing.providers.esp_runtime import EspRuntimeStatus

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_rebuilt.detect_esp_runtime",
        lambda: EspRuntimeStatus(
            available=False,
            binaries={"serveESP": None, "serveCSM": None, "ocsm": None},
            missing=["serveESP", "serveCSM", "ocsm"],
        ),
    )

    request = GeometryProviderRequest(
        source_path=tmp_path / "model.vsp3",
        staging_dir=tmp_path / "provider",
        geometry_family_hint="thin_sheet_aircraft_assembly",
        units_hint="m",
    )

    result = materialize(request)

    assert result.status == "failed"
    assert result.provider == "esp_rebuilt"
    assert result.provenance["runtime"]["available"] is False
    assert "missing" in result.provenance["runtime"]
```

- [ ] **Step 2: Run the provider tests to verify they fail**

Run:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m pytest tests/test_esp_rebuilt_provider.py -q
```

Expected: FAIL because the current provider still returns the stub payload.

- [ ] **Step 3: Write the minimal pipeline abstraction**

Create `hpa_meshing_package/src/hpa_meshing/providers/esp_pipeline.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EspMaterializationResult:
    status: str
    normalized_geometry_path: Path | None
    topology_report_path: Path | None
    notes: list[str]
    warnings: list[str]


def materialize_with_esp(*, source_path: Path, staging_dir: Path) -> EspMaterializationResult:
    raise NotImplementedError("ESP/OpenCSM materialization is not implemented yet.")
```

Update `esp_rebuilt.py` so it delegates to `materialize_with_esp()` instead of inlining the entire path. That keeps the provider contract thin and the ESP orchestration testable.

- [ ] **Step 4: Run the provider tests to verify they pass**

Run:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m pytest tests/test_esp_runtime.py tests/test_esp_rebuilt_provider.py -q
```

Expected: PASS for missing-runtime and stub-replacement behavior.

- [ ] **Step 5: Commit**

```bash
git add -p hpa_meshing_package/src/hpa_meshing/providers/esp_pipeline.py \
  hpa_meshing_package/src/hpa_meshing/providers/esp_rebuilt.py \
  hpa_meshing_package/tests/test_esp_rebuilt_provider.py
git commit -m "refactor: 拆出 esp provider materialization pipeline"
```

## Task 3: Implement The Official OpenVSP To ESP Rebuild Path

**Files:**
- Modify: `hpa_meshing_package/src/hpa_meshing/providers/esp_pipeline.py`
- Modify: `hpa_meshing_package/tests/test_esp_rebuilt_provider.py`
- Optional helper create: `hpa_meshing_package/src/hpa_meshing/providers/esp_scripts.py`

- [ ] **Step 1: Write the failing materialization tests**

Extend `hpa_meshing_package/tests/test_esp_rebuilt_provider.py` with a focused success-path test:

```python
def test_esp_rebuilt_returns_normalized_geometry_when_pipeline_succeeds(monkeypatch, tmp_path: Path):
    from hpa_meshing.providers.esp_rebuilt import materialize
    from hpa_meshing.providers.esp_runtime import EspRuntimeStatus
    from hpa_meshing.providers.esp_pipeline import EspMaterializationResult

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_rebuilt.detect_esp_runtime",
        lambda: EspRuntimeStatus(
            available=True,
            binaries={"serveESP": "/opt/esp/bin/serveESP", "serveCSM": "/opt/esp/bin/serveCSM", "ocsm": "/opt/esp/bin/ocsm"},
            missing=[],
        ),
    )

    normalized = tmp_path / "normalized.stp"
    topology = tmp_path / "topology.json"
    normalized.write_text("ISO-10303-21;\n", encoding="utf-8")
    topology.write_text("{\"surface_count\": 38}\n", encoding="utf-8")

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_rebuilt.materialize_with_esp",
        lambda **_: EspMaterializationResult(
            status="success",
            normalized_geometry_path=normalized,
            topology_report_path=topology,
            notes=[],
            warnings=[],
        ),
    )

    request = GeometryProviderRequest(
        source_path=tmp_path / "model.vsp3",
        staging_dir=tmp_path / "provider",
        geometry_family_hint="thin_sheet_aircraft_assembly",
        units_hint="m",
    )

    result = materialize(request)

    assert result.status == "success"
    assert result.normalized_geometry_path == normalized
    assert result.artifacts["topology_report"] == topology
```

- [ ] **Step 2: Run the provider tests to verify they fail**

Run:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m pytest tests/test_esp_rebuilt_provider.py -q
```

Expected: FAIL because the provider does not yet emit a success payload from ESP materialization.

- [ ] **Step 3: Write the minimal OpenVSP to ESP pipeline**

Implement one official path only. Do not mix multiple strategies in the first round.

Preferred first path:

1. Prepare a provider-owned staging directory.
2. Generate the smallest reproducible ESP input from `.vsp3`.
3. Call the official ESP/OpenVSP bridge path documented in the repo spike:
   - `UDPRIM vsp3`
   - or scripted `VspSetup` if that proves more automatable on this machine
4. Export one normalized STEP artifact from ESP.
5. Run the existing topology report generation on that STEP.

Keep the core of `materialize_with_esp()` narrow:

```python
def materialize_with_esp(*, source_path: Path, staging_dir: Path) -> EspMaterializationResult:
    work_dir = staging_dir / "esp_runtime"
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1. create provider-owned ESP input / script
    # 2. call official ESP/OpenCSM command
    # 3. verify normalized STEP exists
    # 4. write topology.json
    # 5. return success or explicit failed status
```

The first implementation must also persist:
- the exact command line used
- stdout/stderr logs
- the generated ESP script or model input

Those artifacts are non-optional; they are how we stop future ambiguity.

- [ ] **Step 4: Run the provider tests to verify they pass**

Run:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m pytest tests/test_esp_runtime.py tests/test_esp_rebuilt_provider.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -p hpa_meshing_package/src/hpa_meshing/providers/esp_pipeline.py \
  hpa_meshing_package/src/hpa_meshing/providers/esp_rebuilt.py \
  hpa_meshing_package/tests/test_esp_rebuilt_provider.py
git commit -m "feat: 實作 esp rebuilt provider materialization"
```

## Task 4: Prove The Provider On Blackcat Coarse And Then Update Product Docs

**Files:**
- Modify: `hpa_meshing_package/README.md`
- Modify: `hpa_meshing_package/docs/current_status.md`
- Modify: `hpa_meshing_package/docs/esp_opencsm_feasibility.md`
- Verification artifact only: `hpa_meshing_package/.tmp/runs/blackcat_004_coarse_esp_rebuilt/**`

- [ ] **Step 1: Run the real blackcat coarse validation**

Run:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
PYTHONPATH=src /Volumes/Samsung\ SSD/hpa-mdo/.venv/bin/python -m hpa_meshing.cli run \
  --config /tmp/blackcat_esp_rebuilt_attempt.yaml
```

Expected: `report.json` exists and no longer fails with `geometry_provider_not_materialized`.

- [ ] **Step 2: Inspect the run outputs**

Check:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo/hpa_meshing_package
sed -n '1,220p' .tmp/runs/blackcat_004_coarse_esp_rebuilt_attempt/report.json
sed -n '1,220p' .tmp/runs/blackcat_004_coarse_esp_rebuilt_attempt/artifacts/providers/esp_rebuilt/provider_log.json
```

Expected:
- provider `status=success`
- non-null `normalized_geometry_path`
- topology artifact present
- if Gmsh still fails, the failure must now be downstream of the provider

- [ ] **Step 3: Update the front-door docs only after smoke evidence exists**

Update `hpa_meshing_package/README.md` and `hpa_meshing_package/docs/current_status.md` so they say one of two truths only:

- If coarse completes provider materialization:
  - `esp_rebuilt` is runnable but still experimental
- If coarse still fails in provider stage:
  - `esp_rebuilt` remains non-runnable, with the exact blocker named

Add a dated note near the top of `hpa_meshing_package/docs/esp_opencsm_feasibility.md`:

```markdown
> 2026-04-21 implementation note: this document is a feasibility spike, not a statement that `esp_rebuilt` is runnable on current `main`. Check `README.md`, `docs/current_status.md`, and the latest blackcat smoke evidence before treating ESP as usable.
```

- [ ] **Step 4: Verify docs and smoke evidence are aligned**

Run:

```bash
cd /Volumes/Samsung\ SSD/hpa-mdo
rg -n "esp_rebuilt|runnable|experimental|not_materialized|implementation note" \
  hpa_meshing_package/README.md \
  hpa_meshing_package/docs/current_status.md \
  hpa_meshing_package/docs/esp_opencsm_feasibility.md
```

Expected: the wording is consistent across all three docs.

- [ ] **Step 5: Commit**

```bash
git add -p hpa_meshing_package/README.md \
  hpa_meshing_package/docs/current_status.md \
  hpa_meshing_package/docs/esp_opencsm_feasibility.md
git commit -m "docs: 對齊 esp provider 實作狀態與 smoke 證據"
```

## Self-Review

- Spec coverage: this plan covers the missing-runtime problem, the stub-provider problem, the missing materialization pipeline, and the documentation drift that caused the current confusion.
- Placeholder scan: no `TODO`/`TBD` placeholders remain; every task names exact files, commands, and expected outcomes.
- Type consistency: the plan uses one runtime helper (`detect_esp_runtime`) and one pipeline entrypoint (`materialize_with_esp`) throughout.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-21-esp-rebuilt-provider-enablement.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
