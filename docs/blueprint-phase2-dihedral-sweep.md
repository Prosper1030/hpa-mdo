# Phase 2 藍圖：Dihedral Sweep 外圈完善

> 日期：2026-04-13
> 狀態：Codex MVP-1 已交付，進入修正與強化階段

---

## 現況總結

Codex 已交付 `dihedral_sweep_campaign.py` MVP-1，流程打通：
- AVL dihedral 修改 → AVL subprocess → stability parse → inverse-design inner loop → summary CSV/JSON
- Smoke 結果：multiplier 1.0→2.5，mass 23.1→13.1 kg

### 已確認的問題

| 問題 | 嚴重度 | 說明 |
|------|--------|------|
| wire allowable 太低 | **高** | steel_4130 (670MPa) + 2mm = 1052N。真實用 Dyneema SK75 (3500MPa) 2.5mm ≈ 8590N |
| 沒有完整機體 .avl | **高** | 穩定性濾網完全沒用（全部 stable_fallback） |
| subprocess 失敗中斷整個 sweep | 中 | 一個 case 炸掉就全停 |
| loaded-shape tolerance 硬編碼 | 低 | 25mm / 0.15° 寫死在 inverse_design.py |
| .lod parser 無 component filter | 低 | 目前安全（只有 wing strip），但缺防禦 |

### 已確認不是問題

- .lod 目前只有 wing component（50 strips），無尾翼汙染
- dihedral multiplier = z_scale 語義正確（同一個設計變數）
- 13-15 kg 主翼重量經日本團隊數據驗證為合理
- 3000-4000N wire tension 在升級材料後完全可行

---

## 任務分配

### Task 1：Wire 材料升級 [Codex]
**優先：最高 | 複雜度：低 | 預計：10 min**

修改 config，將 wire 從 steel_4130 升級為 dyneema_sk75。

### Task 2：建立完整機體 .avl [Codex]
**優先：最高 | 複雜度：中 | 預計：30 min**

根據 VSP 幾何建立包含 Wing + Elevator + Fin 的 AVL 模型。

### Task 3：Sweep error handling [Codex]
**優先：中 | 複雜度：低 | 預計：15 min**

改成 per-case error collection，不因單一 case 失敗中斷整個 sweep。

### Task 4：Tolerance 進 config [Codex]
**優先：低 | 複雜度：低 | 預計：10 min**

把 loaded_shape 容差從硬編碼移到 config/CLI。

### Task 5：.lod parser component filter [Codex]
**優先：低 | 複雜度：低 | 預計：15 min**

加 optional component_id filter 到 VSPAeroParser。

### Task 6：重跑 dihedral sweep [Codex，在 Task 1+2 完成後]
**優先：最高 | 複雜度：低 | 預計：20 min**

用升級後的 wire + 完整 .avl 重跑，產出真正有意義的 summary。

---

## 執行順序

```
Task 1 (wire) ─┐
               ├──→ Task 6 (重跑 sweep)
Task 2 (avl)  ─┘
Task 3 (error handling) ── 獨立，可並行
Task 4 (tolerance)      ── 獨立，可並行
Task 5 (.lod filter)    ── 獨立，可並行
```

Task 1 + 2 是 blocking，完成後才跑 Task 6。
Task 3/4/5 可以和 1/2 並行，或之後再做。

---

## 預期成果

重跑後應該能看到：
1. **wire margin 翻正** — Dyneema SK75 allowable ≈ 8590N >> 目前最大 tension 3875N
2. **Dutch Roll 真正被評估** — 有尾翼後 AVL 應能找到 lateral oscillatory mode
3. **真正的 stability-structure Pareto** — 哪個 dihedral multiplier 既穩定又輕

---

## 後續（本階段之後）

- 如果某個 dihedral 範圍明確勝出：做更細 sweep（例如 1.5~2.5 step 0.1）
- 如果穩定性和重量交叉：這就是外圈談判桌的核心成果
- 之後才進入：dynamic design space / vendor catalog / full coupling
