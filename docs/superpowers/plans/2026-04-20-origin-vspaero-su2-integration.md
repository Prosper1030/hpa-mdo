# Origin VSP Aero Sweep and SU2 Integration Attempt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a formal origin-VSP aero sweep CLI that produces VSPAero result bundles and, in the same round, can read SU2 alpha-sweep results into the same analysis contract.

**Architecture:** Keep the first round narrow. Reuse the existing `VSPBuilder` and `VSPAeroParser` paths for solver execution/parsing, add one shared normalization/report module, and plug in a lightweight SU2 sweep reader that consumes case directories and history files instead of trying to build a full backend immediately.

**Tech Stack:** Python 3.10, pytest, numpy, pandas, matplotlib, existing `hpa_mdo.aero` modules, existing SU2 shared installation.

---

### Task 1: Add The New Spec/Plan Docs

**Files:**
- Create: `docs/superpowers/specs/2026-04-20-origin-vspaero-su2-integration-design.md`
- Create: `docs/superpowers/plans/2026-04-20-origin-vspaero-su2-integration.md`

- [ ] **Step 1: Confirm both docs exist**

Run: `ls docs/superpowers/specs/2026-04-20-origin-vspaero-su2-integration-design.md docs/superpowers/plans/2026-04-20-origin-vspaero-su2-integration.md`
Expected: both paths exist

- [ ] **Step 2: Commit**

Run:

```bash
git add -p docs/superpowers/specs/2026-04-20-origin-vspaero-su2-integration-design.md docs/superpowers/plans/2026-04-20-origin-vspaero-su2-integration.md
git commit -m "docs: add origin aero sweep and su2 integration design"
```

### Task 2: Lock Down The Shared Aero Result Contract With Tests

**Files:**
- Create: `tests/test_origin_aero_sweep.py`
- Modify: `tests/test_vspaero_parser.py`
- Create: `src/hpa_mdo/aero/origin_aero_results.py`

- [ ] **Step 1: Write the failing tests**

Add tests that cover:

```python
def test_normalize_vspaero_rows_from_history_and_loads():
    ...

def test_parse_su2_alpha_sweep_directory_reads_history_rows():
    ...

def test_write_analysis_bundle_creates_expected_artifacts(tmp_path):
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `'/Volumes/Samsung SSD/hpa-mdo/.venv/bin/pytest' tests/test_origin_aero_sweep.py -q`
Expected: FAIL because `origin_aero_results` helpers do not exist yet

- [ ] **Step 3: Write minimal implementation**

Implement focused helpers in `src/hpa_mdo/aero/origin_aero_results.py` for:

```python
def normalize_vspaero_results(...): ...
def parse_su2_sweep_dir(...): ...
def write_origin_aero_bundle(...): ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `'/Volumes/Samsung SSD/hpa-mdo/.venv/bin/pytest' tests/test_origin_aero_sweep.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

Run:

```bash
git add -p tests/test_origin_aero_sweep.py tests/test_vspaero_parser.py src/hpa_mdo/aero/origin_aero_results.py
git commit -m "test: lock origin aero and su2 result contracts"
```

### Task 3: Implement The Formal Origin VSPAero CLI

**Files:**
- Create: `scripts/origin_aero_sweep.py`
- Modify: `src/hpa_mdo/aero/__init__.py`
- Modify: `src/hpa_mdo/aero/vsp_builder.py`
- Modify: `src/hpa_mdo/aero/vsp_aero.py`
- Test: `tests/test_origin_aero_sweep.py`

- [ ] **Step 1: Write the failing CLI-focused tests**

Add tests that cover:

```python
def test_origin_aero_cli_writes_vspaero_bundle(tmp_path):
    ...

def test_origin_aero_cli_can_read_existing_su2_directory(tmp_path):
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `'/Volumes/Samsung SSD/hpa-mdo/.venv/bin/pytest' tests/test_origin_aero_sweep.py -q`
Expected: FAIL because the CLI does not exist yet

- [ ] **Step 3: Write minimal implementation**

Implement:

- argument parsing for config, alpha range, output dir, optional SU2 input dir
- VSPAero execution using existing `VSPBuilder`
- bundle writing via the new shared module

- [ ] **Step 4: Run tests to verify they pass**

Run: `'/Volumes/Samsung SSD/hpa-mdo/.venv/bin/pytest' tests/test_origin_aero_sweep.py tests/test_vsp_builder.py tests/test_vspaero_parser.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

Run:

```bash
git add -p scripts/origin_aero_sweep.py src/hpa_mdo/aero/__init__.py src/hpa_mdo/aero/vsp_builder.py src/hpa_mdo/aero/vsp_aero.py tests/test_origin_aero_sweep.py
git commit -m "feat: add formal origin vspaero sweep cli"
```

### Task 4: Attempt SU2 Hookup And Analysis Path Integration

**Files:**
- Modify: `src/hpa_mdo/aero/origin_aero_results.py`
- Modify: `scripts/origin_aero_sweep.py`
- Create or modify: `tests/test_origin_aero_sweep.py`
- Optional artifact/output only during verification: `output/origin_aero_sweep/**`

- [ ] **Step 1: Write the failing SU2 integration tests**

Add tests that cover:

```python
def test_parse_su2_case_alpha_from_metadata_or_name(tmp_path):
    ...

def test_combined_bundle_contains_vspaero_and_su2_sections(tmp_path):
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `'/Volumes/Samsung SSD/hpa-mdo/.venv/bin/pytest' tests/test_origin_aero_sweep.py -q`
Expected: FAIL because the combined bundle behavior is incomplete

- [ ] **Step 3: Write minimal implementation**

Implement:

- SU2 case discovery and alpha extraction
- SU2 history parsing into shared normalized rows
- merge of SU2 rows into bundle/report/plot generation
- clear reporting when SU2 is missing, partial, or successful

- [ ] **Step 4: Run tests to verify they pass**

Run: `'/Volumes/Samsung SSD/hpa-mdo/.venv/bin/pytest' tests/test_origin_aero_sweep.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

Run:

```bash
git add -p src/hpa_mdo/aero/origin_aero_results.py scripts/origin_aero_sweep.py tests/test_origin_aero_sweep.py
git commit -m "feat: wire su2 sweep results into origin aero analysis"
```

### Task 5: Fresh Verification And Real Smokes

**Files:**
- No source-file requirement beyond what changed above
- Verification artifacts expected under: `output/origin_aero_sweep/`

- [ ] **Step 1: Run the unit/integration slice**

Run:

```bash
'/Volumes/Samsung SSD/hpa-mdo/.venv/bin/pytest' \
  tests/test_origin_aero_sweep.py \
  tests/test_vsp_builder.py \
  tests/test_vspaero_parser.py -q
```

Expected: PASS

- [ ] **Step 2: Run a real VSPAero smoke**

Run:

```bash
'/Volumes/Samsung SSD/hpa-mdo/.venv/bin/python' scripts/origin_aero_sweep.py \
  --config configs/blackcat_004.yaml \
  --alpha-start -2 \
  --alpha-end 2 \
  --alpha-step 2 \
  --output-dir output/origin_aero_sweep
```

Expected: VSPAero bundle files exist under `output/origin_aero_sweep/`

- [ ] **Step 3: Attempt the SU2 hookup smoke**

Run one of:

```bash
zsh -lc 'SU2_CFD -h'
```

and if a real sweep fixture/case directory exists:

```bash
'/Volumes/Samsung SSD/hpa-mdo/.venv/bin/python' scripts/origin_aero_sweep.py \
  --config configs/blackcat_004.yaml \
  --read-su2-dir <su2-sweep-dir> \
  --output-dir output/origin_aero_sweep
```

Expected: either
- real SU2 rows are merged into the bundle, or
- the smoke clearly reports the missing piece while preserving the VSPAero bundle

- [ ] **Step 4: Final commit if verification required follow-up adjustments**

Run:

```bash
git add -p <task-related-files>
git commit -m "fix: complete origin aero verification adjustments"
```
