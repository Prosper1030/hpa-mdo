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
- Track H：rerun-aero outer-loop core + consumer contract 已立起來，campaign 與 winner selection 已能區分 `candidate rerun-aero` 與 `legacy refresh`。
- Track I / J / K：rib properties foundation、rib bay surrogate、passive rib robustness、zone-wise rib design contract 已全部落地，rib 現在已進入 candidate / winner selection contract，而不只是 report-only。
- Track L：真實 smoke campaign 已經不再被 parser 卡住，solver 也不再死在 explicit wire-truss 假性不收斂；目前更直接的 blocker 已明確轉成 outer-wing ground clearance。
- Track Q：VSPAero `.lod` parser compatibility 與 candidate rerun 主翼 component filter 已修好，rerun-aero 路線已經能真正跑到 summary artifact。

這代表下一輪不需要再把 B / C / D / E / G / H / I / J / K 當成唯一主戰場，而是應該先把 rerun-aero replay 裡真正的設計 blocker，也就是 ground-clearance recovery，往前推。

## 3. 下一輪活躍工作軌道

### Track T：ground-clearance recovery outer-loop

這是 **現在最值得先做的主軸**。

- 什麼情況下優先：如果 parser/runtime 與 solver 都已經能跑通真 replay，selected candidate 也不再是 sentinel crash，但 failure 已經明確轉成 `ground_clearance`。
- 近期目標：
  - 針對 outer-wing jig clearance 問題加入 recovery path
  - 先用低維 outer-loop knob / seed / search bias 把 clearance 拉回來
  - 讓 rerun-aero replay 至少能產生更有工程意義的 non-sentinel signal

### Track R：rib campaign multi-seed signal hunt

這是 **Track T 驗證後的下一波**。

- 什麼情況下優先：如果 rerun-aero 已經能跑通，而且 outer-wing jig clearance 已被往前推，現在需要真正回答 rib ranking 是不是工程合理。
- 近期目標：
  - 用 `candidate_rerun_vspaero` 跑 `2 到 4` 個較有訊號的代表性 seeds
  - 每個 seed 都比較 `rib_zonewise=off` vs `limited_zonewise`
  - 至少找出一組不是 sentinel fallback 的可比 selected-case
  - 明確判斷這套 rib contract 是 `SANE`、`SUSPICIOUS`，還是又回到新的 `BLOCKED`

### Track M：rib penalty / surrogate tuning

這是 **Track T / R 跑完之後的下一波**。

- 什麼情況下優先：如果多 seed smoke 顯示 rib-on 確實開始影響 winner，但 ranking 邏輯仍有可疑之處。
- 近期目標：
  - 調整 `rib_family_switch_penalty_kg`
  - 調整 `family_mix_max_unique`
  - 必要時微調 surrogate / summary 權重
  - 讓 rib-on winner 不是只在數學上漂亮，而是工程上可接受

### Track N：rib finalist spot-check / handoff

這是 **Track T / R / M 穩住後的第三波**。

- 什麼情況下優先：如果 smoke 結果合理，準備把 rib-on 設計推向更正式的 finalist 診斷與交接。
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
- 接下來重點不再是建立 rerun-aero contract 本身，而是把它當 rib integration 與後續 finalist release gate 的穩定上游。

### Track I / J / K：rib integration baseline

- 目前狀態：baseline 已成立。
- 接下來重點不再是再多發明 rib 自由度，而是先驗證現在這套 rib candidate contract 在真實 campaign 裡是不是合理。

### Track Q：rerun-aero parser/runtime unblock

- 目前狀態：baseline 已成立。
- 接下來重點不再是繼續修 parser，而是把新的 parser/runtime 路徑拿來支撐更有訊號的 Track R replay。

### Track L：rib campaign smoke

- 目前狀態：已從 `BLOCKED` 升到 `SUSPICIOUS`。
- 接下來重點不再是直接加更多 smoke，而是先處理 replay 現在暴露出的 ground-clearance blocker。

### Track R：multi-seed rib smoke

- 目前狀態：已完成第一輪最小多 seed replay。
- 接下來重點不是直接進 tuning，而是等待 Track T 把 ground-clearance 問題先往前推，再重跑更有訊號的 replay。

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
