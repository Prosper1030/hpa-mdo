# Phase J Evidence Map Plan

> **Status**：next dedicated goal candidate
> **Purpose**：先整理 Phase J pipeline 現有證據，再決定下一步工程優先順序。不要直接跳到 rib FEM。

## Goal Objective

```text
在 /Volumes/Samsung SSD/hpa-mdo 建立 Phase J evidence map：整理 Mission contract -> Fourier-AVL calibration -> Fourier spanload candidate generation -> smooth production geometry realization -> AVL realization check -> structure-budgeted loaded-Z search -> AVL recheck on realizable loaded shape -> Tier2 full-alpha airfoil selection -> aero-structure closure -> FEM/APDL / shell buckling / load-factor checks 各階段目前使用的 artifact、candidate、關鍵數字、信任邊界與缺口，輸出成可讀表格，並標出下一步應先處理 beam-line / aerodynamic surface / clearance 對齊，而不是直接做 rib FEM。
```

## Deliverable

建立一份表格型報告，建議位置：

```text
docs/reports/2026-05-09_phase_j_evidence_map.md
```

表格至少包含：

| 欄位 | 說明 |
|---|---|
| pipeline_stage | Phase J 的階段名稱 |
| current_artifact | 目前最可信的輸入 / 輸出 artifact |
| command_or_script | 可重建該 artifact 的 script 或入口 |
| candidate_or_case | 對應 candidate / case id |
| key_numbers | 目前最重要的數字，不需要塞滿 |
| trust_level | `source_truth` / `screening` / `spot_check` / `diagnostic` / `blocked` |
| open_gap | 目前缺口 |
| next_action | 下一步要做什麼 |

## Initial Stage List

1. Mission contract
2. Fourier-AVL calibration
3. Fourier spanload candidate generation
4. Smooth production geometry realization
5. AVL realization check
6. Structure-budgeted loaded-Z search
7. AVL recheck on realizable loaded shape
8. Tier2 full-alpha airfoil selection
9. Aero-structure closure
10. FEM/APDL / shell buckling / load-factor checks

## Priority Rule

Evidence map 完成後，下一個工程優先順序暫定為：

1. beam-line / aerodynamic surface / clearance 對齊；
2. aero-structure closure 工程可信度；
3. rib modeling contract research；
4. rib FEM detail validation only if it changes closure ranking or is required for sign-off.

## Notes

- Rib 目前是 downstream physical-realization / validation issue，不是 Phase J evidence map 前的主線 blocker。
- 如果 evidence map 發現 rib / bracing assumption 會改變 `aero-structure closure` candidate 排序，才把 rib 提前。
- 如果只是 final sign-off gap，rib 留在 downstream validation queue。
