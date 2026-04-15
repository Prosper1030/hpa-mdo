# M-HF2 — CalculiX 線性靜力 runner（對比 OpenMDAO 翼尖位移）

## 前置條件

M-HF1 已完成（`hpa_mdo.hifi.gmsh_runner` 與 `scripts/hifi_mesh_step.py` 可用）。

## 背景

CalculiX 是 Apple Silicon 上可以 `brew install calculix-ccx` 安裝的開源
非線性有限元素 solver。本任務寫一個最小 runner：吃 `.inp` 加載檔頭
自動補 STATIC step、material、boundary condition，跑 ccx，解析 `.frd`
取翼尖撓度，再跟 `examples/blackcat_004_optimize.py` 輸出的
`result.tip_deflection_m` 比對（±5% 視為通過，印 WARN 但不 raise）。

## 目標

1. 新增 `src/hpa_mdo/hifi/calculix_runner.py`。
2. 三個 function：
   - `find_ccx(cfg)` — 仿 `find_gmsh` 的 pattern，查 `cfg.hi_fidelity.calculix.ccx_binary`
     與 `shutil.which("ccx")`。`enabled=False` 時回 `None`。
   - `prepare_static_inp(mesh_inp_path, out_inp_path, material, boundary, load, *, step_name="cruise") -> Path`
     - 讀 `mesh_inp_path` 的 NODE / ELEMENT 區段（保持原貌）。
     - 追加 `*MATERIAL`、`*ELASTIC`、`*SOLID SECTION`、`*BOUNDARY`、
       `*STEP / *STATIC`、`*CLOAD`、`*NODE FILE, OUTPUT=3D`、`*END STEP`。
     - `material` 為 `{"E": float, "nu": float, "rho": float}`。
     - `boundary` 為 root clamp node id 的 tuple `(nid, dofs_list)`。
     - `load` 為 `[(nid, dof, magnitude), ...]` 的 list。
   - `run_static(inp_path, cfg, *, timeout_s=1200) -> dict`
     - `subprocess.run([ccx, inp_path.stem], cwd=inp_path.parent, capture_output=True, timeout=timeout_s)`。
     - 成功回 `{"frd": Path, "dat": Path, "returncode": int}`，失敗回
       `{"error": msg, "returncode": int}`。**不得 raise。**
3. 新增 `src/hpa_mdo/hifi/frd_parser.py`：
   - `def parse_displacement(frd_path, *, node_set="ALL") -> np.ndarray`
     - 讀 CalculiX ASCII `.frd` 的 `-4  DISP` block。
     - 回傳 `(n_nodes, 4)` array: 每列 `[nid, ux, uy, uz]`。
4. 新增 script `scripts/hifi_validate_tip_deflection.py`：
   - 參數：`--config`、`--mesh` (已經 mesh 完的 .inp)、`--expected-tip-defl`
     (從 MDO 結果或命令列傳入)。
   - 內部流程：`prepare_static_inp` → `run_static` → `parse_displacement`
     → 找 y 最大節點的 uz → 跟 expected 比 → 印
     `hifi tip defl: X.XXX m (MDO X.XXX m, diff +/- X.XX%)`。
   - 若差異 > 5%，印 `[WARN]` 但 `return 0`。

## 驗收標準

- 在 Mac mini 上 Gmsh + ccx 裝好後，`spar_jig_shape.step` →
  `.inp` → `run_static` 可以跑完並印出翼尖 uz。
- `pytest tests/test_hifi_calculix_runner.py` 在 ccx 未安裝時跳過
  integration test 但仍測試 `prepare_static_inp` 的純文字邏輯（可以用
  固定字串 golden compare）。

## 不要做的事

- **不要**試圖從 OpenMDAO 的 `result.disp` 直接對 frd 節點 — 網格不同，
  比對翼尖（y max）單點即可。
- 不要把 ccx 包成 OpenMDAO ExplicitComponent — 這是驗證層不是最佳化
  內層。
- 不要在 runner 裡寫死 material 值。material 從 `MaterialDB` 拉
  `carbon_fiber_hm` 的 E/nu/rho，script 裡組裝傳進去。

## 建議 commit 訊息

```
feat(hifi): M-HF2 CalculiX 線性靜力 runner + FRD 位移解析

實作 hpa_mdo.hifi.calculix_runner 與 frd_parser，支援從 Gmsh 產生的 .inp
加上 STATIC step 自動 boundary/load，執行 ccx 解析 .frd 取翼尖 uz。
獨立 script scripts/hifi_validate_tip_deflection.py 拿 MDO 的 tip_defl
當期望值比對，差 >5% 印 WARN 但不改動主迴圈的 val_weight。

Co-Authored-By: Codex 5.4 (Extreme High)
```
