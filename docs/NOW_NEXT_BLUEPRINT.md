# HPA-MDO 近期藍圖 (Now / Next Blueprint)

> **文件性質**：近期執行藍圖。這份文件只回答「repo 現在有效的是什麼」「近期有哪些工作軌道」「哪些事情暫時不要寫死」。
> **更新基準**：2026-04-17 repo 現況
> **搭配文件**：正式主線請看 [CURRENT_MAINLINE.md](../CURRENT_MAINLINE.md)，細化版進度規劃請看 [EXECUTION_ROADMAP.md](EXECUTION_ROADMAP.md)，長期願景請看 [GRAND_BLUEPRINT.md](GRAND_BLUEPRINT.md)。

## 1. 目前正式主線

目前要優先對齊的不是舊的 parity solver，也不是 producer 包裝層，而是這條：

`VSP / target cruise shape -> inverse design -> jig shape -> realizable loaded shape -> CFRP tube / discrete layup / manufacturing-feasible design`

判斷規則：

- 正式 structural truth 以 dual-beam production / inverse-design artifacts 為準。
- `python -m hpa_mdo.producer` 是對外整合 contract，不是主 physics 本體。
- `equivalent_beam` 和舊 phase parity 路線仍可保留作 regression / 歷史參考，但不再是 sign-off 主線。

## 2. 近期規劃原則

這一輪不把工作排成單一線性 backlog，而是用多軌並行、條件式啟動的方式規劃：

- 不把某一份老 ANSYS/APDL case 直接寫成唯一 benchmark 真值；benchmark basket 保持開放。
- 不讓高保真驗證阻塞現在的快速設計主線；高保真先收斂成可信 spot-check。
- 不把 continuous thickness optimum 當 final answer；離散 CFRP / layup 是正式主線。
- 不在這個階段直接跳進高維 free-form cruise-shape optimization；先用低維 knob 跑通 requested vs realizable 的閉環。

## 3. 目前活躍工作軌道

### Track A：主線收斂成單一路徑

把 `generic VSP intake -> inverse design -> jig shape -> CFRP / discrete layup` 收成更清楚的正式操作主線。

- 什麼情況下優先：如果現在最大問題是「會用的人不確定該跑哪條入口」。
- 近期目標：入口、文件、artifact 命名、輸出摘要一致化。

### Track B：inverse-design 有效性與 gate

降低 frozen-load / exact nodal backout 對主線判斷的誤導風險。

- 什麼情況下優先：如果你現在最卡的是「這個 jig backout 到底能不能信」。
- 近期目標：fresh reanalysis、descriptor-based mismatch、wire / tension / twist / clearance gate。

### Track C：Mac 上的高保真 structural spot-check

把 `Gmsh -> CalculiX -> report` 收斂成一條本機可跑、可比較、但不過度宣稱的驗證路徑。

- 什麼情況下優先：如果近期決策卡在物理可信度，而不是 search 成本。
- 近期目標：先對一個新鮮且可比的 APDL case 做 tip deflection / max |UZ| / support reaction / mass 對照。

### Track D：離散 CFRP / layup 正式化

把 continuous thickness 解和 final discrete layup 的角色切清楚。

- 什麼情況下優先：如果現在最大問題是 final design 還不夠像真實可製造結果。
- 近期目標：把 discrete layup summary、failure gate、manufacturing gate 更明確納入主線輸出。

### Track E：surrogate / data / catalog

把 Phase I 的資料收集能力接回主線，但前提是 canonical I/O 先穩。

- 什麼情況下優先：如果目前瓶頸是探索效率、warm start 或大量 sweep 成本。
- 近期目標：surrogate warm start、真實 vendor / hardware catalog、focused crossover sweep。

## 4. 條件式後續軌道

- `requested cruise shape -> realizable cruise shape` 的 outer-loop shape 調整：先限於 dihedral / target-shape scaling / descriptor 級變數。
- open-source aeroelastic spike：保留，但不應再變成主線 blocker。
- mission-driven automatic design：未來才進到 `pilot power + weight -> best cruise shape -> jig -> discrete layup`。
- XFOIL / airfoil redesign：應該放在 planform / jig-realizability 框架穩住之後，而不是現在先衝。

## 5. 目前先不要做的事

- 不先把某個舊 APDL case 寫成唯一 sign-off benchmark。
- 不先做 full free-form 外形共優化。
- 不把 Mac 高保真目前的結果拿去背書 discrete layup 或最終複材真值。
- 不讓 ASWING binary 取得與否決定整個主線是否能前進。

## 6. 你現在該怎麼選

- 想快速知道 repo 現在到底能做到哪裡：先看 [CURRENT_MAINLINE.md](../CURRENT_MAINLINE.md)。
- 想要更細的近期進度與分軌方向：看 [EXECUTION_ROADMAP.md](EXECUTION_ROADMAP.md)。
- 想跑第一個正式入口：回 [README.md](../README.md)。
- 想接 consumer / producer contract：看 [dual_beam_consumer_integration_guide.md](dual_beam_consumer_integration_guide.md) 和 [dual_beam_decision_interface_v1_spec.md](dual_beam_decision_interface_v1_spec.md)。
- 想看五階段長期方向：看 [GRAND_BLUEPRINT.md](GRAND_BLUEPRINT.md)。
