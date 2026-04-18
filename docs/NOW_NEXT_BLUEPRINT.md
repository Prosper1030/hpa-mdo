# HPA-MDO 近期藍圖 (Now / Next Blueprint)

> **文件性質**：近期執行藍圖。這份文件只回答「repo 現在有效的是什麼」「近期有哪些工作軌道」「哪些事情暫時不要寫死」。
> **更新基準**：2026-04-18 repo 現況
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

## 2.5 這一輪已經可標完成的 baseline

- Track B：inverse-design validity summary / gate artifact 已落地。它現在不是「還沒開始」，而是已經有 baseline，可轉成維護型軌道。
- Track C：Mac hi-fi 已收斂到 `local structural spot-check` 的角色，不再是要被推成 validation truth 的主線 blocker。
- Track D：discrete layup 已不只存在於 sidecar；final-design JSON 與 `optimization_summary.txt` 都能直接表達 discrete final verdict。

這代表下一輪不需要再把 B / C / D 當成唯一主戰場，而是可以把重心轉回主線 front door、search acceleration 與 outer loop。

## 3. 下一輪活躍工作軌道

### Track A：主線 front door / canonical workflow 收斂

這是 **下一輪最值得先做的主軸**。

把 `generic VSP intake -> inverse design -> jig shape -> CFRP / discrete layup` 收成更清楚的正式操作主線。

- 什麼情況下優先：如果現在最大問題是「會用的人不確定該跑哪條入口」。
- 近期目標：入口、文件、artifact 命名、輸出摘要一致化，讓人與 agent 都能快速走到 canonical path。

### Track E：surrogate / data / catalog

這是 **下一輪第二優先**，但前提是 Track A 至少把 canonical artifact 講清楚。

把 Phase I 的資料收集能力接回主線，先做 optional surrogate warm start，再談更完整的 catalog realism。

- 什麼情況下優先：如果目前瓶頸是探索效率、warm start 或大量 sweep 成本。
- 近期目標：surrogate warm start、真實 vendor / hardware catalog、focused crossover sweep。

### Track F：requested-to-realizable outer loop

這是 **下一輪第三優先**，建立在 A / E 已把 canonical path 與 acceleration path 穩住之後。

- 什麼情況下優先：如果你已經接受 requested 和 realizable 不會完全重合，想開始把 shape 調整變成正式外圈。
- 近期目標：先用 `target_shape_z_scale`、`dihedral_exponent`、dihedral multiplier 這類低維 knob，把下面這條「近期可交付版閉環」跑通：

`low-dimensional aero-shape exploration -> target loaded shape -> inverse design -> jig clearance / mass / manufacturing gate -> discrete CFRP layup -> realizable loaded-shape score`

- 近期交付重點不是 full hi-fi sign-off，而是：
  - requested / realizable / jig 三種 shape 的差距有清楚 score
  - discrete layup verdict 能回寫到 outer-loop summary
  - 使用者能用低維 knob 判斷「這個 cruise shape 值不值得繼續做」

## 4. 轉入維護型的軌道

### Track B：inverse-design 有效性與 gate

降低 frozen-load / exact nodal backout 對主線判斷的誤導風險。

- 目前狀態：baseline 已成立。
- 接下來只在 fresh reanalysis、descriptor mismatch、wire / clearance gate 顯示還有洞時再做補強，不需要再把它當唯一主戰場。

### Track C：Mac 上的高保真 structural spot-check

把 `Gmsh -> CalculiX -> report` 收斂成一條本機可跑、可比較、但不過度宣稱的驗證路徑。

- 目前狀態：baseline 已成立，而且共識已清楚限定為 `local structural spot-check`。
- 接下來只在 benchmark basket 更新、external benchmark 定義、或某個 finalist 需要 diagnosis 時再往前推。

### Track D：離散 CFRP / layup 正式化

把 continuous thickness 解和 final discrete layup 的角色切清楚。

- 目前狀態：baseline 已成立。
- 接下來重點不再是「證明 discrete layup 存在」，而是讓 Track A / F 能自然消費它的 final-design artifact。

## 5. 條件式後續軌道

- `requested cruise shape -> realizable cruise shape` 的 outer-loop shape 調整：先限於 dihedral / target-shape scaling / descriptor 級變數。
- open-source aeroelastic spike：保留，但不應再變成主線 blocker。
- mission-driven automatic design：未來才進到 `pilot power + weight -> best cruise shape -> jig -> discrete layup`。
- XFOIL / airfoil redesign：應該放在 planform / jig-realizability 框架穩住之後，而不是現在先衝。

## 6. 目前先不要做的事

- 不先把某個舊 APDL case 寫成唯一 sign-off benchmark。
- 不先做 full free-form 外形共優化。
- 不把 Mac 高保真目前的結果拿去背書 discrete layup 或最終複材真值。
- 不讓 ASWING binary 取得與否決定整個主線是否能前進。

## 7. 你現在該怎麼選

- 想快速知道 repo 現在到底能做到哪裡：先看 [CURRENT_MAINLINE.md](../CURRENT_MAINLINE.md)。
- 想要更細的近期進度與分軌方向：看 [EXECUTION_ROADMAP.md](EXECUTION_ROADMAP.md)。
- 想跑第一個正式入口：回 [README.md](../README.md)。
- 想接 consumer / producer contract：看 [dual_beam_consumer_integration_guide.md](dual_beam_consumer_integration_guide.md) 和 [dual_beam_decision_interface_v1_spec.md](dual_beam_decision_interface_v1_spec.md)。
- 想看五階段長期方向：看 [GRAND_BLUEPRINT.md](GRAND_BLUEPRINT.md)。
