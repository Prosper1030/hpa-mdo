# M13 — AVL 控制導數矩陣 Exporter（給控制組的介面）

## 前置條件

- `scripts/dihedral_sweep_campaign.py` 已有 `run_avl_stability_case` 呼叫
  AVL 跑 eigenmode / trim。Binary 路徑與 case 目錄慣例沿用。
- `data/blackcat_004_full.avl` 是 baseline 全機模型（含 wing + elevator + fin）。
- 控制面（elevator / rudder / aileron）的 AVL `CONTROL` 區段必須存在；
  若 `.avl` 缺 CONTROL，先補 baseline 的 elevator / rudder 定義再開工。

## 背景

目前我們只從 AVL 抽了**穩定性特徵值**（Dutch roll / spiral / phugoid），沒
把完整的 `.st` **stability derivatives 矩陣**與控制面 `δE / δA / δR` 的導數
交給控制組。控制組需要線性化模型 `ẋ = A x + B u` 來設計 PID / LQR，
AVL 其實可以一次吐齊，只是我們沒有 parser。

## 目標

1. **新增** `src/hpa_mdo/aero/avl_stability_parser.py`：
   - `@dataclass StabilityDerivatives`：
     ```
     # Longitudinal
     CL_alpha, CL_q, CL_de, CD_alpha, CM_alpha, CM_q, CM_de
     # Lateral-directional
     CY_beta, CY_p, CY_r, CY_da, CY_dr
     Cl_beta, Cl_p, Cl_r, Cl_da, Cl_dr
     Cn_beta, Cn_p, Cn_r, Cn_da, Cn_dr
     # Trim state（參考點）
     alpha_trim_deg, beta_trim_deg, V_inf, rho, Sref, bref, cref
     ```
   - `parse_st_file(path: Path) -> StabilityDerivatives`：
     - 讀 AVL 的 `.st` ASCII 輸出。AVL `.st` 格式是「關鍵字 = 數值」每行一條，
       用 regex `r"(\w+)\s*=\s*([-+\d.Ee]+)"` 掃過全檔。
     - 控制面名稱用 AVL 的 `d1/d2/d3` 或 `CONTROL` 宣告名；建立
       `control_name -> index` 的 mapping，再把對應欄位灌進 `CL_de` 等。
     - 任何欄位缺失時設 `math.nan`，**不 raise**。
2. **新增** `src/hpa_mdo/aero/avl_runner.py`（重構 dihedral_sweep 裡的邏輯）：
   - `run_avl_derivatives(avl_path, cfg, *, alpha_deg=None, cl_target=None,
     velocity=None, density=None, out_dir=Path) -> dict`
   - 內部命令序列：
     ```
     load <avl>
     mass <mass_file>            # 若 cfg.io.avl_mass 存在
     oper
       a a <alpha_deg>           # 或 a c <cl_target>
       m                         # 修改環境
         v <velocity>
         d <density>
       x                         # trim 執行
       st <out_stub>.st          # 導出 .st
     quit
     ```
   - 回 `{"st_path": Path, "run_path": Path, "returncode": int}`；subprocess
     失敗或 timeout 時 `{"error": ..., "returncode": N}`。**不 raise**。
3. **新增 script** `scripts/export_controls_matrix.py`：
   - CLI 參數：
     ```
     --config configs/blackcat_004.yaml
     --avl    data/blackcat_004_full.avl
     --cl     0.9                  # trim CL；預設從 cfg 推
     --out    output/<stem>/controls/
     ```
   - 流程：
     1. 載 cfg → 找 AVL binary（`cfg.hi_fidelity.avl.binary` 或 `shutil.which("avl")`）。
     2. 執行 `run_avl_derivatives` → 取 `.st`。
     3. `parse_st_file` → `StabilityDerivatives`。
     4. 組**線性化狀態空間**：
        - 狀態向量 `x = [u, w, q, θ, v, p, r, φ, ψ]`（body-axes perturbation）。
        - 控制向量 `u_ctrl = [δe, δa, δr, δT]`（throttle 在 HPA 是「pilot_power」，暫以 0 佔位）。
        - A / B 矩陣依 Etkin & Reid / Stevens & Lewis 的標準公式推導，
          用 StabilityDerivatives + cfg 裡的 mass / CG / I 計算。
        - 質量、CG、I 從 `hpa_mdo.mass.budget`（M14）取；若 M14 尚未實作
          就從 `cfg.mass_properties` 占位讀（預先加 fallback schema）。
     5. 輸出三個檔案到 `out/`：
        - `stability_derivatives.json`（人讀 friendly，附單位）
        - `state_space_A.csv` + `state_space_B.csv`（控制組直接讀）
        - `controls_matrix_report.md`（對照表 + 物理檢查：`Cm_alpha < 0`、
          `Cn_beta > 0`、`Cl_beta < 0` 等 static stability 判定 PASS/WARN）
4. **docs/controls_interface_v1.md**：
   - 控制組交付介面的正式規範文件。定義 csv / json 欄位名、座標系（body
     axes，X 前 / Y 右 / Z 下）、單位（SI），以及哪些欄位是保證存在、
     哪些 best effort。

## 驗收標準

- Mac mini 上 AVL 已安裝的前提下：
  ```
  python scripts/export_controls_matrix.py --config configs/blackcat_004.yaml \
      --avl data/blackcat_004_full.avl --cl 0.9
  ```
  跑完產出三個檔案，`controls_matrix_report.md` 顯示：
  - `Cm_alpha = ?? /rad` → 標 PASS 若 < 0
  - `Cn_beta = ?? /rad` → 標 PASS 若 > 0
  - `Cl_beta = ?? /rad` → 標 PASS 若 < 0
  - trim α、β 記錄在報告裡
- `pytest tests/test_avl_stability_parser.py` 有 golden test：
  餵一個固定 `.st` 字串 → 比對每個欄位到 1e-6。
- `examples/blackcat_004_optimize.py` 主迴圈**不受影響**，`val_weight: 11.95...`
  不變。

## 不要做的事

- **不要**把 AVL run 塞進 `examples/blackcat_004_optimize.py`。這是獨立
  post-process，由 script 觸發。
- **不要**硬編任何飛行參數；`velocity` / `density` / `CL_target` 從 cfg 讀。
- **不要**假設所有 `.st` 欄位都存在；AVL 版本之間命名會變，用 dict-of-nan
  的 defensive pattern。
- **不要**自己猜 A/B 矩陣符號慣例；寫 code 時 docstring 明確標「Etkin 慣例
  body axes, X 前 Y 右 Z 下, η pitch-up positive」。如果不確定某一項，
  PR description 裡標 TODO 給 Claude 審，不要靜默決定。
- **不要**把 M14 (mass/CG) 的呼叫寫死；若 M14 還沒 merge，用
  `try: from hpa_mdo.mass.budget import MassBudget; except ImportError: ...`
  的 soft dependency，fallback 到 cfg.mass_properties 佔位欄位。

## 建議 commit 訊息

```
feat(aero): M13 AVL 控制導數矩陣 exporter（給控制組）

新增 hpa_mdo.aero.avl_stability_parser 解析 AVL .st，avl_runner 批次
執行 trim+st；scripts/export_controls_matrix.py 產 state-space A/B 矩陣
＋ stability_derivatives.json ＋ controls_matrix_report.md。介面規範
docs/controls_interface_v1.md。主迴圈 val_weight 不變。

Co-Authored-By: Codex 5.4 (Extreme High)
```
