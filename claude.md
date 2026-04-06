# HPA-MDO AI 開發規則

## 鐵律（絕不違反）

1. 所有工程參數必須來自 `configs/*.yaml` -- 絕不在程式碼中硬編碼物理常數（速度、密度、安全係數、材料屬性、幾何尺寸）。
2. 修改求解器程式碼前，務必先讀取 config.yaml。在修改任何模組前，先了解當前參數值與綱要。
3. 結構求解器必須使用 OpenMDAO 架構 -- 不得使用獨立的 scipy 梁求解器。OpenMDAO problem 位於 `structure/oas_structural.py`；scipy 僅作為包裝 OpenMDAO 模型的備援最佳化驅動器使用。
4. 安全係數必須分開：`aerodynamic_load_factor` 用於載荷（在載荷對應中套用），`material_safety_factor` 用於容許應力（計算破壞指數時套用）-- 絕不將兩者合併為單一係數。
5. 材料必須透過 `MaterialDB` 以鍵值方式從 `data/materials.yaml` 載入 -- 不得有行內材料定義，Python 程式碼中任何地方都不得有硬編碼的 E/G/density/strength 數值。
6. VSPAero 的外部氣動力載荷重新量綱化，必須使用實際飛行條件（V=config.flight.velocity、rho=config.flight.air_density）-- 絕不直接使用 VSPAero 的參考條件，因為 VSPAero 的執行 Vinf/rho 可能與實際巡航狀態不同。
7. 任何求解器崩潰或結果不符合物理時，必須輸出 `val_weight: 99999` 並優雅地結束 -- 絕不讓程序以未處理的例外中止。`val_weight` 輸出協定由上游 AI 代理迴圈消費。

## 架構規則

- 配置綱要位於 `core/config.py`（Pydantic BaseModel）-- 完全對應 YAML 結構。任何新增的配置欄位必須同時加入 YAML 與 Pydantic 模型。
- 管壁厚度為設計變數：雙翼梁配置每根翼梁 6 段 x 2 根翼梁 = 12 個設計變數。配置中的 segments 列表定義半翼展管材長度 [1.5, 3.0, 3.0, 3.0, 3.0, 3.0] m。
- 有限元素模型使用全局自由度：每個節點 [ux, uy, uz, theta_x, theta_y, theta_z] -- 對 Y 軸翼展方向的梁，繞翼展軸的扭轉為第 4 個自由度（theta_y）。
- 雙翼梁等效剛度：EI 由平行軸定理計算（各管材 EI + 各翼梁的 A*d^2），GJ 由各管材加上翹曲耦合項計算。數學實作位於 `structure/spar_model.py`。
- 接頭質量懲罰加入目標函數（total_mass_full_kg），而非注入沿梁的結構質量分佈。接頭數量由段落長度的累積和推導。
- 升力鋼索支撐 = 在鋼索連接接頭位置的垂直撓度約束條件（uz = 0）。鋼索連接 y 座標必須與段落邊界定義的接頭位置重合。
- 最佳化器採用兩階段策略：（1）差分演化法進行全局搜尋，（2）SLSQP 進行局部精修。OpenMDAO 內建驅動器在「auto」模式下優先嘗試；scipy 備援為穩健路徑。

## 檔案慣例

- 相容 Python 3.10 以上版本（依 pyproject.toml 的 requires-python）。
- 所有模組使用 `from __future__ import annotations`。
- 型別標註使用 `from typing import Optional, List`。
- 所有檔案路徑從 `config.io` 讀取 -- 絕不硬編碼。所有地方使用 `pathlib.Path`。
- 跨平台：使用 `pathlib.Path`，避免平台特定的路徑分隔符。團隊同時使用 macOS 與 Windows。
- 行長度限制：100 個字元（由 ruff 強制執行）。

## 程式碼組織

- `core/` -- 配置、飛機模型、材料資料庫。此處不放置求解器邏輯。
- `aero/` -- 氣動力解析器（VSPAero、XFLR5）與載荷對應。輸出永遠為 `SpanwiseLoad` 資料類別或對應後的載荷字典。
- `structure/` -- 有限元素元件、翼梁幾何、最佳化器與 CAE 匯出。OpenMDAO problem 在 `oas_structural.py` 中組裝。
- `fsi/` -- 流固耦合（單向與雙向 Gauss-Seidel）。
- `api/` -- FastAPI REST 伺服器與 MCP 伺服器。這些是核心流程的薄包裝層。
- `utils/` -- 視覺化與輔助函式。

## 測試與驗證

- 任何結構程式碼變更後，執行：`python examples/blackcat_004_optimize.py`
- 檢查下列驗收標準：
  - `failure_index <= 0`（應力約束條件滿足）
  - `twist_max_deg <= 2.0`（扭轉角約束條件滿足）
  - `total_mass_full_kg` 在物理上合理：全翼展翼梁系統 15-50 kg
  - `tip_deflection_m` 為正值且小於半翼展（無正負號錯誤）
- 最後輸出行必須為 `val_weight: <float>` -- 此為機器可讀的目標函數值。
- 若新增約束條件或設計變數，透過對受影響元件執行 `check_partials()` 驗證 OpenMDAO 偏導數是否正確。

## 載荷對應協定

- VSPAero 在其自身參考條件下輸出無因次係數（Cl、Cd、Cm）。
- `LoadMapper.map_loads()` 函式使用配置中的 `actual_velocity` 與 `actual_density` 重新量綱化，在實際巡航狀態下產生物理的單位展長力 [N/m]。
- `aerodynamic_load_factor` 在載荷對應期間作為乘法比例因子套用（不在有限元素求解器中套用）。
- 氣動力至結構的內插預設使用三次樣條。結構網格（60 個節點）比氣動力網格更細密。

## ANSYS 匯出

- APDL 匯出使用 BEAM188 元素（Timoshenko 梁），搭配 CTUBE 截面。
- Workbench CSV 提供幾何與載荷，用於外部資料匯入。
- NASTRAN BDF 使用 CBAR 元素，搭配 PBARL TUBE 截面。
- 三種格式均代表相同的半翼展模型，翼根採固定邊界條件。
- 匯出僅供獨立驗證使用 -- 最佳化使用內部 OpenMDAO 有限元素模型，而非 ANSYS。
