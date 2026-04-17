# HPA-MDO 近期藍圖 (Now / Next Blueprint)

> **文件性質**：近期執行藍圖。這份文件只回答「repo 現在有效的是什麼」「接下來先做什麼」「哪些事情先不要做」。
> **更新基準**：2026-04-17 repo 現況
> **搭配文件**：目前正式主線請看 [CURRENT_MAINLINE.md](../CURRENT_MAINLINE.md)，長期願景請看 [GRAND_BLUEPRINT.md](GRAND_BLUEPRINT.md)，文件導航請看 [docs/README.md](README.md)。

## 1. 目前正式主線

目前要優先對齊的主線不是舊的 parity solver，而是這條：

`dual-beam production -> inverse design -> decision producer -> consumer / autoresearch`

判斷規則：

- 正式 structural truth 以 dual-beam production / inverse-design artifacts 為準。
- 正式對外 contract 以 `python -m hpa_mdo.producer` 的 decision interface JSON 為準。
- `equivalent_beam` 和舊 phase parity 路線仍可保留作 regression / 歷史參考，但不再是現在的 sign-off 主線。

## 2. 已經完成到哪裡

這些項目已不該再被當成近期主待辦：

- dual-beam mainline、inverse design MVP、decision layer 已成立。
- M7 到 M9 的多數外圈能力已完成，包括 dihedral sweep、multi-wire、Pareto、vendor-aware tube catalog、full rigging、dynamic design space、higher-fidelity load coupling。
- M11 CLT / Tsai-Wu、M13 controls matrix、M14 mass / CG / inertia budget、M-VSP Phase 2 都已完成。
- generic VSP controls 已接進 AVL / ASWING exporter。

## 3. 近期優先任務

### Priority 0：P4#18 surrogate warm start

這是目前最值得先做的主線功能。

- 為什麼值得做：它直接把 Phase I 的資料收集能力接到 Phase III 的代理模型橋接層，是目前少數不依賴商業 solver、又明確會提升探索效率的下一步。
- 什麼情況下應該先做：當目標是縮短 search 時間、改善 warm start、為後續 surrogate backend 鋪路。
- 什麼情況下不該先做：如果近期決策卡在外部 aeroelastic benchmark 真值不足，而不是 search 成本，那就應先處理下個任務。

### Priority 1：open-source aeroelastic spike

先用 SHARPy Docker first 的方向做外部非線性氣動彈驗證探索。

- 為什麼值得做：它可以降低 ASWING binary 取得門檻對主線的阻塞，補上 trim / deflection / modal 類 benchmark 的替代路徑。
- 什麼情況下應該先做：當你需要外部 benchmark 來確認主線物理可信度，或要判斷 ASWING 是否仍值得追。
- 什麼情況下不該先做：如果當前瓶頸是搜尋效率、資料利用、或內部 ranking 能力，而不是 benchmark 缺口。

### Priority 2：real vendor / hardware catalog 資料化

把目前 proxy 味道較重的 catalog，往更接近採購 reality 的方向推進。

- 為什麼值得做：離散 OD / rigging 的 ranking 目前已能工作，但是否能真正支撐採購與製造判斷，仍取決於真實 catalog。
- 什麼情況下應該先做：當你要把 ranking、BOM、rigging complexity 的判斷往實機可採購性收斂。
- 什麼情況下不該先做：如果近期重點仍是演算法主線、速度、或外部驗證，而不是採購級 realism。

### Priority 3：focused crossover sweep

把 1.5 到 2.2 附近的 crossover 區間當成條件式補跑項，不是固定待辦。

- 為什麼值得做：只有當 vendor catalog 或新幾何讓 ranking 接近交叉時，這段 sweep 才會提供新的決策資訊。
- 什麼情況下應該先做：ranking 接近翻盤，或 catalog/geometry 更新後需要重新辨識最佳區間。
- 什麼情況下不該先做：現有 ranking 很穩、沒有新 catalog、也沒有新幾何時，不值得先花計算資源。

## 4. 暫緩與條件式項目

- ASWING seed/run/report benchmark：保留，但不應再阻塞主線；等取得授權或實際 binary 後再做。
- 大規模 phase report 整理或歸檔：先不做，除非它已經干擾到主線導航。
- 額外的大 sweep campaign：只有在新資料、真值或 ranking 被動搖時才重啟。

## 5. 你現在該怎麼選

- 想跑第一個正式入口：先回 [README.md](../README.md)。
- 想接 consumer / producer contract：看 [dual_beam_consumer_integration_guide.md](dual_beam_consumer_integration_guide.md) 和 [dual_beam_decision_interface_v1_spec.md](dual_beam_decision_interface_v1_spec.md)。
- 想排近期工作：以這份文件為準。
- 想看五階段長期方向：看 [GRAND_BLUEPRINT.md](GRAND_BLUEPRINT.md)。
