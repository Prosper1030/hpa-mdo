# M14 — 質量 / 重心 / 慣性矩陣 預算（Mass / CG / Inertia Budget）

## 前置條件

- `examples/blackcat_004_optimize.py` 已能產 `result.total_mass_full_kg`
  與 `result.nodes` / `result.disp`（翼梁幾何與位移）。
- `configs/blackcat_004.yaml` 已有 `aircraft` 區段（operating mass 等），
  但**沒有**分項 mass budget schema。

## 背景

目前「飛機總重」是靠 `aircraft.operating_mass_kg` 單一數字代表；
CG 從沒算過；I_xx / I_yy / I_zz 完全空白。控制組（M13 A/B 矩陣）、
鋼索系統、ASWING 與 ANSYS 的正確 inertia 輸入都需要這三個量。
此任務做一個**乾淨的質量預算系統**，把「從哪裡來、多重、位置」一次
交代清楚，並輸出 AVL `.mass` 檔供 M13 使用。

## 目標

1. **新增** `src/hpa_mdo/mass/` 套件：
   ```
   src/hpa_mdo/mass/
     __init__.py
     budget.py        # MassBudget 聚合器
     components.py    # 點質量 / 線質量 / 體質量 dataclass
     inertia.py       # 平行軸定理 / 基本 shape inertia
   ```
2. **`components.py`** dataclass：
   - `PointMass(name, m_kg, xyz_m, sigma_kg=0.0)` — 不確定度 σ。
   - `LineMass(name, linear_kg_per_m, xyz_start_m, xyz_end_m)` — 翼梁、鋼索。
   - `DistributedMass(name, mass_fn: Callable[[np.ndarray], np.ndarray],
     nodes_m: np.ndarray)` — 給機翼結構質量（從 FEM result 取）。
3. **`budget.py`**：
   - `class MassBudget`：
     - `add(component)` — 累加任何 Point/Line/Distributed。
     - `total_mass() -> float`。
     - `center_of_gravity() -> np.ndarray`（shape (3,)）。
     - `inertia_tensor(about="cg") -> np.ndarray`（3×3）。
     - `to_yaml(path) / from_yaml(path)`。
     - `to_avl_mass(path, Lunit="m", Munit="kg", Tunit="s", g=9.81)` —
       輸出 AVL `.mass` 檔（格式：`m Ixx Iyy Izz Ixy Ixz Iyz x y z`，
       每行一個元件 + `Mbody` 結尾；header 帶單位宣告）。
4. **`inertia.py`**：
   - `point_inertia(m, r_from_cg) -> 3x3`（平行軸）。
   - `tube_inertia(m, length, r_outer, r_inner, axis="x")` — 兩端節點對 CG 的展開。
   - `distributed_lift_mass_from_result(result, rho_per_segment) -> LineMass list`
     — 把 FEM 輸出的翼梁段化為 LineMass 串（管材體積 × 密度 × 段長）。
5. **`configs/blackcat_004.yaml`** 新增 `mass_budget` 區段：
   ```yaml
   mass_budget:
     pilot:
       m_kg: 65.0
       xyz_m: [1.2, 0.0, -0.5]     # fuselage coords
       sigma_kg: 2.0
     fuselage_structure:
       m_kg: 15.0
       xyz_m: [1.5, 0.0, 0.0]
       sigma_kg: 1.5
     drivetrain:
       m_kg: 3.5
       xyz_m: [1.0, 0.0, -0.3]
       sigma_kg: 0.3
     propeller:
       m_kg: 0.8
       xyz_m: [3.8, 0.0, 0.0]
     empennage:
       m_kg: 1.5
       xyz_m: [5.5, 0.0, 0.0]
     # structure 區塊的主翼 / wire 由 MassBudget 從 result 自動填，不用在這。
   ```
   對應 Pydantic：`MassBudgetConfig` + `MassItem`（Optional；缺項印 WARN 並用 0）。
6. **script** `scripts/export_mass_budget.py`：
   - `--config ... --result output/<stem>/result.pkl`（或重跑 optimize）
   - 寫出：
     - `output/<stem>/mass_budget.yaml`（完整預算，可 round-trip）
     - `output/<stem>/mass_budget_report.md`（人讀表 + CG + I + σ 傳播）
     - `output/<stem>/avl_mass.mass`（給 M13 用）
7. **整合進** `examples/blackcat_004_optimize.py`：
   - 在 Step 9 之後加一個 Step 10「質量預算 + AVL .mass」
   - 失敗 → `try/except` 印 WARN，**不影響 val_weight**。

## 驗收標準

- `python scripts/export_mass_budget.py --config configs/blackcat_004.yaml` 可以
  獨立跑完，產出三個檔。
- `mass_budget_report.md` 的 `total_mass` 與 `cfg.aircraft.operating_mass_kg`
  差距 < 5%（這是 sanity 不是 gate）；若 >5% 印 WARN 列差異表。
- `pytest tests/test_mass_budget.py`：
  - 單位測試：兩個 point mass → CG 在中點，I_zz = Σ m r²。
  - Tube inertia 單位測試。
  - YAML round-trip test。
  - AVL `.mass` 檔字串 golden。
- 主迴圈 `val_weight: 11.95...` 不變。

## 不要做的事

- **不要**把 mass_budget 放進 optimizer 的設計變數。此為 post-process。
- **不要**硬編 pilot 重量；一律從 `cfg.mass_budget.pilot.m_kg` 讀。
- **不要**假設飛機是對稱的就 skip I_xy / I_yz；保留欄位（雖然 HPA 多半對稱），
  對 I_xz（經度-垂直耦合）要真的算。
- **不要**把座標系混用。**全部用 body axes：X 機頭前 / Y 右 / Z 下**，
  原點固定在「機頭尖」（或 `cfg.reference_point.xyz_m`）。YAML / report /
  `.mass` 檔都遵守這個慣例。座標系決定之後改動需要整個專案 sweep，不要
  在這個 PR 裡半途改。

## 建議 commit 訊息

```
feat(mass): M14 Mass / CG / Inertia 預算系統 + AVL .mass exporter

新增 hpa_mdo.mass 套件（components / budget / inertia），cfg 加
mass_budget schema，scripts/export_mass_budget.py 產出 mass_budget.yaml +
mass_budget_report.md + avl_mass.mass。examples 主流程非侵入式加 Step 10。
總質量 sanity check 對 aircraft.operating_mass_kg 差 <5% 印確認表。
主迴圈 val_weight 不變。

Co-Authored-By: Codex 5.4 (Extreme High)
```
