# Architecture

## A. 核心想法

把 meshing 問題拆成 6 層：

1. **schema layer**
   - 定義輸入 config 與 manifest
2. **geometry layer**
   - 匯入與驗證幾何
3. **recipe layer**
   - 不同元件的 meshing 邏輯
4. **backend layer**
   - 呼叫 Gmsh / SU2 format export
5. **quality layer**
   - 品質檢查與 marker 驗證
6. **fallback/report layer**
   - 失敗重試與輸出報告

## B. 不要做成「一個超大 script」

禁止以下 anti-pattern：

- `if component == ...` 到處散落
- 所有 Gmsh 呼叫都寫在單一檔案
- geometry 驗證與 meshing 摻在一起
- fallback 靠 try/except 亂包
- 針對單一檔名硬寫規則

## C. 推薦 class / function 介面

### 1. schema.py
- `MeshJobConfig`
- `QualityGateConfig`
- `BoundaryLayerConfig`
- `FarfieldConfig`
- `FallbackConfig`

### 2. geometry/loader.py
- `load_occ_geometry(path) -> GeometryHandle`

### 3. geometry/validator.py
- `validate_component_geometry(handle, component, config) -> ValidationResult`

### 4. mesh/recipes.py
- `build_recipe(component, handle, config) -> MeshRecipe`

### 5. adapters/gmsh_backend.py
- `apply_recipe(recipe, handle, config) -> MeshArtifacts`

### 6. mesh/quality.py
- `check_quality(mesh_artifacts, quality_gate) -> QualityResult`

### 7. fallback/policy.py
- `run_with_fallback(job) -> RunResult`

## D. 資料流

```text
CLI/Manifest
   ↓
schema parse + defaults resolve
   ↓
geometry load
   ↓
geometry validation
   ↓
recipe build
   ↓
gmsh apply + generate
   ↓
quality check
   ↓
export .msh / .su2
   ↓
report + retry history
```

## E. 元件擴充方式

未來新增 `boom`, `prop_fairing`, `pod`, `tail_boom_joint` 時：

- 新增 config default
- 新增 geometry validator 規則
- 新增 recipe builder
- 不應改核心 CLI 介面

## F. 為什麼這樣切

因為你們現在已有 `fairing_solid` special case，可先把它包成一個 recipe；之後 main wing / tail wing / fairing_vented 再逐步長出來。  
這樣不會一開始就為了「通用」把整個 repo 弄得抽象過頭。
