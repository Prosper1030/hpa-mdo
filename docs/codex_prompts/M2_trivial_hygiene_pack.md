# M2 — Trivial Hygiene Pack（4 個小修補打包成單一 commit）

## 背景

Antigravity Opus code review 抓到 4 個各自 5 分鐘以內的小問題。
為了避免污染 git history，這 4 個一起做、用單一 commit 提交。

> 前提：本任務必須等 Codex 目前手上的 **main spar dominance** 任務完成並 push 之後再開工。

## 任務 1：刪除重複的 log 行

**檔案**：`src/hpa_mdo/structure/optimizer.py`
**行數**：545–547 附近

目前的程式碼長這樣（連續兩行一模一樣）：

```python
        # ── Phase 1: Global search with differential evolution ──
        logger.info("  [Phase 1] Differential Evolution global search...")

        logger.info("  [Phase 1] Differential Evolution global search...")
        logger.info("  已啟用多核心運算，預期 CPU 使用率將會飆高")
```

刪掉**第二個** `logger.info("  [Phase 1] Differential Evolution global search...")`。
保留註解行與剩下兩個 logger 呼叫。改完後應該是：

```python
        # ── Phase 1: Global search with differential evolution ──
        logger.info("  [Phase 1] Differential Evolution global search...")
        logger.info("  已啟用多核心運算，預期 CPU 使用率將會飆高")
```

## 任務 2：把 `g = 9.80665` 抽到共用常數模組

**目前重複的 3 個位置**：

1. `src/hpa_mdo/structure/oas_structural.py:1109`（`ExternalLoadsComp.setup` 內 `g = 9.80665`）
2. `src/hpa_mdo/structure/oas_structural.py:1130`（`ExternalLoadsComp.compute` 內 `g = 9.80665 * self.options["gravity_scale"]`）
3. `src/hpa_mdo/core/aircraft.py:122`（`Aircraft.weight_N` 內 `return self.mass_total_kg * 9.80665`）

**步驟**：

1. 新建 `src/hpa_mdo/core/constants.py`：
   ```python
   """Physical constants of nature.
   
   This module hosts only constants of nature (universal physical
   constants), NOT engineering parameters. Engineering parameters
   must live in YAML configs per CLAUDE.md iron rule #1.
   """
   from __future__ import annotations
   
   # Standard gravity [m/s^2] — ISO 80000-3 / CIPM 1901
   G_STANDARD: float = 9.80665
   ```

2. 在 3 個使用點改成：
   ```python
   from hpa_mdo.core.constants import G_STANDARD
   # ...
   g = G_STANDARD                              # oas_structural.py:1109
   g = G_STANDARD * self.options["gravity_scale"]  # oas_structural.py:1130
   return self.mass_total_kg * G_STANDARD     # aircraft.py:122
   ```

3. 在 `src/hpa_mdo/core/__init__.py` 加 export：
   ```python
   from hpa_mdo.core.constants import G_STANDARD  # noqa: F401
   ```
   （只新增、不要動既有 export）

**禁止**：
- 不要把任何**工程參數**（材料密度、安全係數、幾何尺寸）放進 `constants.py`，那會違反鐵律 #1
- `constants.py` 在這個 PR 內**只能有 `G_STANDARD` 一個常數**

## 任務 3：DataCollector 補上 `buckling_index`

**檔案**：`src/hpa_mdo/utils/data_collector.py`
**行數**：45 附近的 `_RESPONSE_COLUMNS`

目前缺少 `buckling_index`：

```python
_RESPONSE_COLUMNS = [
    "total_mass_full_kg",
    "spar_mass_full_kg",
    "tip_deflection_m",
    "twist_max_deg",
    "max_stress_main_MPa",
    "max_stress_rear_MPa",
    "failure_index",
]
```

改成：

```python
_RESPONSE_COLUMNS = [
    "total_mass_full_kg",
    "spar_mass_full_kg",
    "tip_deflection_m",
    "twist_max_deg",
    "max_stress_main_MPa",
    "max_stress_rear_MPa",
    "failure_index",
    "buckling_index",
]
```

接著要去看 `data_collector.py` 內**寫入 row 的位置**（搜尋 `failure_index` 的賦值位置），確保 `buckling_index` 也有從 `OptimizationResult` 取出來填入。`OptimizationResult.buckling_index` 已經存在，直接讀就好。

如果 `data_collector.py` 內有 schema migration 邏輯（讀舊 CSV 自動補欄位），就讓它自然處理；如果沒有，**不要**寫遷移邏輯，直接接受新 CSV 與舊 CSV 不相容（這只是訓練資料庫，沒有 production data 依賴）。

## 任務 4：visualization.py twist 計算方式註解 TODO

**檔案**：`src/hpa_mdo/utils/visualization.py`
**行數**：95 附近

目前繪圖直接讀 `result.disp[:, 4]`（全域 θy），但 `TwistConstraintComp` 是用旋轉矩陣投影到局部梁軸取最大值。對直翼（無 sweep / dihedral）兩者相同；對未來支援的 swept wing，兩者會明顯偏差。

**這次只加 TODO 註解，不要實作修正**（真正修要動 visualization 與 TwistConstraintComp 的軸定義一致性，是 4h 等級的工作，不屬於 hygiene pack）。

把現有的：

```python
        twist_deg = result.disp[:, 4] * (180.0 / math.pi)
```

改成：

```python
        # TODO: project to local beam axis to match TwistConstraintComp.
        # For straight wings (no sweep/dihedral) this is identical to disp[:, 4],
        # but for future swept-wing support we should use the same rotation matrix
        # that TwistConstraintComp applies. Tracked: M2 hygiene pack note.
        twist_deg = result.disp[:, 4] * (180.0 / math.pi)
```

## 驗收標準

1. `pytest -m "not slow"` 全綠
2. `grep -rn "9\.80665" src/` 應該**只剩 0 個**結果（除了 `constants.py` 自己）
3. `data_collector.py` 寫一筆假資料時不會 KeyError on `buckling_index`
4. visualization.py 跑舊 baseline 圖的輸出**像素級相同**（TODO 註解不影響行為）
5. 程式碼註解、log 全英文（鐵律 #8）

## 不要做的事

- 不要順手 refactor `data_collector.py` 的其他部分
- 不要動 visualization.py 的其他繪圖邏輯
- 不要把 `material_safety_factor` / `aerodynamic_load_factor` 等**工程參數**搬進 constants.py
- 不要動既有 import 順序（避免引入無關 diff）
- 不要在這個 PR 做 `oas_structural.py` 的拆解（M6 才做）

## Commit 訊息範本

```
chore: M2 trivial hygiene pack（review finding 1/2/3/4）

- 刪除 optimizer.py Phase 1 重複 log 行
- 抽出 G_STANDARD 至 core/constants.py（消除 oas_structural.py / aircraft.py 三處重複）
- DataCollector _RESPONSE_COLUMNS 補上 buckling_index 欄位
- visualization.py twist 計算加 TODO 註解（待 swept wing 支援時實作軸投影）
```

## 完成後

```
.venv/bin/python -m pytest -x -m "not slow"
git add -A src/ docs/codex_prompts/M2_trivial_hygiene_pack.md
git commit -m "..."
git pull --rebase --autostash origin main
git push origin main
```
