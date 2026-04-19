# HPA-MDO 近期藍圖 (Now / Next Blueprint)

> **文件性質**：近期執行藍圖。這份文件只回答「repo 現在有效的是什麼」「近期有哪些工作軌道」「哪些事情暫時不要寫死」。
> **更新基準**：2026-04-19 repo 現況
> **搭配文件**：正式主線請看 [CURRENT_MAINLINE.md](../CURRENT_MAINLINE.md)，細化版進度規劃請看 [EXECUTION_ROADMAP.md](EXECUTION_ROADMAP.md)，目標標準的長程收斂請看 [TARGET_STANDARD_PROGRAM_PLAN.md](TARGET_STANDARD_PROGRAM_PLAN.md)，長期願景請看 [GRAND_BLUEPRINT.md](GRAND_BLUEPRINT.md)。

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
- 如果能換到更好的候選品質，quick analysis / search 可以接受約 `10 到 30 分鐘` 的解題預算，不必為了極短 runtime 把設計空間壓得過小。

## 2.5 這一輪已經可標完成的 baseline

- Track B：inverse-design validity summary / gate artifact 已落地。它現在不是「還沒開始」，而是已經有 baseline，可轉成維護型軌道。
- Track C：Mac hi-fi 已收斂到 `local structural spot-check` 的角色，不再是要被推成 validation truth 的主線 blocker。
- Track D：discrete layup 已不只存在於 sidecar；final-design JSON 與 `optimization_summary.txt` 都能直接表達 discrete final verdict。
- Track E / G：recipe library、spanwise discrete search、zone rules 已達到 baseline done enough，不需要繼續當 current 主戰場。
- Track H：rerun-aero outer-loop core + consumer contract 已立起來，campaign 與 winner selection 已能區分 `candidate rerun-aero` 與 `legacy refresh`；它現在適合當 shortlist / finalist confirm，不適合再被當成每個 coarse candidate 的預設搜尋路徑。
- Track I / J / K：rib properties foundation、rib bay surrogate、passive rib robustness、zone-wise rib design contract 已全部落地，rib 現在已進入 candidate / winner selection contract，而不只是 report-only。
- Track L：真實 smoke campaign 已經不再被 parser 卡住，solver 也不再死在 explicit wire-truss 假性不收斂；目前更直接的 blocker 已明確轉成 outer-wing ground clearance。
- Track Q：VSPAero `.lod` parser compatibility 與 candidate rerun 主翼 component filter 已修好，rerun-aero 路線已經能真正跑到 summary artifact。

這代表下一輪不需要再把 B / C / D / E / G / H / I / J / K 當成唯一主戰場；而且在 Track T 已經找到 pass-side clearance region 之後，現在更該做的是把 outer-loop 重新基準化成：

`AVL / lightweight search first -> shortlist 再 candidate_rerun_vspaero confirm`

## 3. 下一輪活躍工作軌道

### Track V：AVL spanwise ownership realignment

這包 **已完成 baseline**。

- 已確認：
  - `candidate_avl_spanwise` 不再偷偷改掉 gate / recovery / load-state semantics
  - ground-clearance recovery 已接回
  - 不再靠 `--skip-aero-gates` 假裝 full-gate 正常
- 現在的角色：
  - 作為 repaired AVL path 的 contract 修正基礎
  - 不再是目前 current wave

### Track W：AVL / legacy / rerun load-state compare

這包 **也已完成 baseline**。

- 已確認：
  - repaired `candidate_avl_spanwise` 在語意上回到「舊流程 + spanwise lift ownership」
  - 但它一開始在 numeric load-state 上仍然和舊流程不對齊
- 這一包的價值：
  - 成功阻止我們太早進 Track X
  - 把真正 blocker 定位成 structural selected state alignment，而不是 parser / recovery / plumbing

### Track Y：AVL structural load-state alignment

這是 **Track W 之後補上的對齊修正，而且現在已完成 baseline**。

- 已確認：
  - `candidate_avl_spanwise` 不再吃 `AVL trim-required AoA 12.536 deg`
  - structural selected state 已回到 legacy owner
  - candidate-owned AVL 現在只接管 spanwise lift distribution shape
  - repaired `candidate_avl_spanwise` 已可合理描述成「舊 AVL-first flow + candidate-owned spanwise lift distribution」
- 這代表：
  - 現在不再卡在「selected state 選錯」
  - `Track X` 可以正式啟動

### Track X：repaired AVL-first recovered shortlist rebuild

這包 **已完成一次，但目前不應視為 canonical shortlist**。

- 問題不是 plumbing，而是：
  - 這一版把 `dihedral_exponent = 2.2` 當成 baseline
  - 但 `2.2` 其實是 Track T recovery ladder 的 heuristic，不是舊主線的正式基準
- 所以這包的定位應改成：
  - historical / diagnostic evidence
  - 不應直接拿來當後續 Track R 的 canonical seed source

### Track Z：AVL baseline exponent rebaseline

這是 **現在的 current wave**。

- 什麼情況下優先：你已確認舊 multiplier 本來就已經是 tip-weighted，真正要修的是 baseline 被錯放成 `exp = 2.2`。
- 近期目標：
  - 用 repaired AVL-first path 做 `exp = 1.0` vs `exp = 2.2` 的 apples-to-apples compare
  - 把 `exp = 1.0` 寫回 canonical screening baseline
  - 明確把 `exp = 2.2` 降回 recovery / sensitivity 選項
  - 基於 `exp = 1.0` 重建真正可用的 repaired shortlist

### Track R：repaired-shortlist rib smoke replay

這是 **Track Z 做完後的下一波**。

- 什麼情況下優先：如果 repaired AVL-first 搜尋已經在 **`exp = 1.0` baseline** 下產生更乾淨的 recovered shortlist，現在需要真正回答 rib ranking 是不是工程合理。
- 近期目標：
  - 用 repaired shortlist seeds，而不是舊的 drift/suspicious seeds，也不是 `exp = 2.2` 的誤基準 shortlist
  - 每個 seed 都比較 `rib_zonewise=off` vs `limited_zonewise`
  - 先用 AVL-first path 建立 shortlist，再用 `candidate_rerun_vspaero` 做 confirm
  - 至少找出一組不是 sentinel fallback 的可比 selected-case
  - 明確判斷這套 rib contract 是 `SANE`、`SUSPICIOUS`，還是新的 `BLOCKED`

### Track M：rib signal sanity tuning

這是 **Track R 跑完之後、而且已經有真實比較訊號時** 的下一波。

- 什麼情況下優先：如果 repaired-shortlist rib smoke 顯示 rib-on 確實開始影響 winner，但 ranking 邏輯仍有可疑之處。
- 近期目標：
  - 調整 `rib_family_switch_penalty_kg`
  - 調整 `family_mix_max_unique`
  - 必要時微調 surrogate / summary 權重
  - 讓 rib-on winner 不是只在數學上漂亮，而是工程上可接受

### Track N：rib finalist spot-check / handoff

這是 **Track R 結果已 sane，且 Track M 不再是 immediate need** 之後的下一波。

- 什麼情況下優先：如果 repaired-shortlist smoke 已經表明某個 rib-on 候選工程上合理，現在準備把它推向更正式的 finalist 診斷與交接。
- 近期目標：
  - 對 rib-on finalist 做 local spot-check
  - 補一份可交接的 ranking / evidence 摘要
  - 再決定 rib-on 要不要升成更正式的主線預設

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

### Track H：rerun-aero outer loop

- 目前狀態：baseline 已成立。
- 接下來重點不再是建立 rerun-aero contract 本身，而是把它降回 shortlist / finalist confirmation 的穩定上游，而不是每個 coarse outer-loop candidate 的預設路徑。

### Track I / J / K：rib integration baseline

- 目前狀態：baseline 已成立。
- 接下來重點不再是再多發明 rib 自由度，而是先驗證現在這套 rib candidate contract 在真實 campaign 裡是不是合理。

### Track Q：rerun-aero parser/runtime unblock

- 目前狀態：baseline 已成立。
- 接下來重點不再是繼續修 parser，而是把新的 parser/runtime 路徑拿來支撐更有訊號的 Track R replay。

### Track L：rib campaign smoke

- 目前狀態：已從 `BLOCKED` 升到 `SUSPICIOUS`。
- 接下來重點不再是直接加更多 smoke，而是先處理 replay 現在暴露出的 ground-clearance blocker。

### Track T：ground-clearance recovery outer-loop

- 目前狀態：baseline 已成立，並已找到第一個 pass-side clearance region。
- 接下來重點不再是把 recovery 參數直接升格成 screening baseline，而是把這個 recovery 經驗當成 `exp = 1.0` baseline 之外的 recovery-only option。

### Track U：AVL spanwise plumbing baseline

- 目前狀態：plumbing 已接通，但第一版實作 drift 過；這個問題已經由 Track V / W / Y 收斂。
- 接下來重點不再是重做 plumbing，而是先把 repaired AVL-first 的 **baseline exponent** 收回到舊主線，再重建 shortlist，然後重新回答 rib ranking。

### Track S：explicit wire-truss convergence unblock

- 目前狀態：baseline 已成立。
- 接下來重點不再是繼續修 solver，而是把已解卡的 replay 路徑拿來支撐 clearance recovery。

## 5. 條件式後續軌道

- `requested cruise shape -> realizable cruise shape` 的 outer-loop shape 調整：先限於 dihedral / target-shape scaling / descriptor 級變數。
- surrogate / warm start：保留，但不再是這一輪主線設計架構修正的第一優先。
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
