# Mesh-Native Main Wing Route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register and begin implementing a mesh-native main-wing CFD geometry route so STEP/BREP repair is no longer the product critical path.

**Architecture:** First add a route-level contract that marks mesh-native lifting surfaces as the preferred future main-wing CFD geometry source. Then add a small deterministic indexed surface builder with marker ownership from face creation. Finally add topology validation gates that fail before Gmsh or SU2 when marker or shell ownership is ambiguous.

**Tech Stack:** Python, Pydantic route schema, pytest, hpa_meshing package modules.

---

### Task 1: Route Contract And Readiness

**Files:**
- Modify: `hpa_meshing_package/src/hpa_meshing/schema.py`
- Modify: `hpa_meshing_package/src/hpa_meshing/dispatch.py`
- Modify: `hpa_meshing_package/src/hpa_meshing/route_readiness.py`
- Test: `hpa_meshing_package/tests/test_route_readiness.py`
- Test: `hpa_meshing_package/tests/test_geometry_family_dispatch.py`

- [ ] **Step 1: Write failing tests**

Add tests that assert `mesh_native_lifting_surface` and `gmsh_mesh_native_lifting_surface` exist, dispatch together, and appear in main-wing readiness as the next primary CFD geometry route.

- [ ] **Step 2: Verify red**

Run: `PYTHONPATH=hpa_meshing_package/src pytest hpa_meshing_package/tests/test_geometry_family_dispatch.py hpa_meshing_package/tests/test_route_readiness.py -q`
Expected: fails because the mesh-native literals and readiness fields do not exist.

- [ ] **Step 3: Implement route contract**

Extend the schema literals, route registry, route readiness row, promotion gates, and markdown rendering with mesh-native route ownership vocabulary.

- [ ] **Step 4: Verify green and commit**

Run the same pytest command. Then stage only the related hunks and commit with `feat: register mesh-native lifting surface route`.

### Task 2: Indexed Surface Builder Core

**Files:**
- Create: `hpa_meshing_package/src/hpa_meshing/mesh_native/__init__.py`
- Create: `hpa_meshing_package/src/hpa_meshing/mesh_native/wing_surface.py`
- Test: `hpa_meshing_package/tests/test_mesh_native_wing_surface.py`

- [ ] **Step 1: Write failing tests**

Add a rectangular wing fixture with three stations. Assert the builder returns deterministic vertices, quad faces, root/tip caps, marker counts, and input span/area metadata without importing Gmsh or CAD.

- [ ] **Step 2: Verify red**

Run: `PYTHONPATH=hpa_meshing_package/src pytest hpa_meshing_package/tests/test_mesh_native_wing_surface.py -q`
Expected: fails because the module does not exist.

- [ ] **Step 3: Implement minimal builder**

Add dataclasses for `Station`, `Reference`, `WingSpec`, `Face`, `SurfaceMesh`, and `build_wing_surface()`. Keep airfoil input already canonicalized for this first slice, and make every generated face carry a marker from birth.

- [ ] **Step 4: Verify green and commit**

Run the targeted test. Then stage only the new module and test and commit with `feat: add mesh-native wing surface builder`.

### Task 3: Topology Validation Gates

**Files:**
- Modify: `hpa_meshing_package/src/hpa_meshing/mesh_native/wing_surface.py`
- Test: `hpa_meshing_package/tests/test_mesh_native_wing_surface.py`

- [ ] **Step 1: Write failing tests**

Add tests for duplicate station y rejection, missing marker rejection, non-watertight edge rejection, zero-area face rejection, and strict marker allow-list behavior.

- [ ] **Step 2: Verify red**

Run: `PYTHONPATH=hpa_meshing_package/src pytest hpa_meshing_package/tests/test_mesh_native_wing_surface.py -q`
Expected: fails on missing validation behavior.

- [ ] **Step 3: Implement validation gates**

Add `validate_surface_mesh()` plus small geometry helpers. Fail before Gmsh/SU2 when a boundary face has no legal marker, a closed-shell edge incidence is not two, a face has tiny area, or required solver markers are missing.

- [ ] **Step 4: Verify green and commit**

Run the targeted test and route contract tests. Then stage only the related hunks and commit with `test: add mesh-native topology validation gates`.

### Task 4: Final Verification

**Files:**
- No source changes expected.

- [ ] **Step 1: Run focused verification**

Run: `PYTHONPATH=hpa_meshing_package/src pytest hpa_meshing_package/tests/test_geometry_family_dispatch.py hpa_meshing_package/tests/test_route_readiness.py hpa_meshing_package/tests/test_mesh_native_wing_surface.py -q`

- [ ] **Step 2: Inspect git status**

Run: `git status --short --branch`
Expected: only pre-existing unrelated dirty files remain outside this task, or no dirty files from these tasks remain after commits.

- [ ] **Step 3: Report engineering judgment**

Report that this is route-contract and topology-ownership evidence, not a SU2 aerodynamic proof. The route is promising only if the next step produces Gmsh volume and SU2 marker smoke evidence.
