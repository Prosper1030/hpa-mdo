# HPA-MDO 執行路線圖 (Execution Roadmap)

> **文件性質**：細化版近期規劃。這份文件不是長期願景，也不是單次待辦清單；它用來回答「接下來有哪些軌道可以推」「哪些先後順序取決於當前卡點」。
> **更新基準**：2026-04-18 repo 現況 + 已確認主線
> **搭配文件**：正式主線請看 [CURRENT_MAINLINE.md](../CURRENT_MAINLINE.md)，精簡版摘要請看 [NOW_NEXT_BLUEPRINT.md](NOW_NEXT_BLUEPRINT.md)，長期方向請看 [GRAND_BLUEPRINT.md](GRAND_BLUEPRINT.md)。

## 1. 先講結論

接下來的工作不應該再排成「只有一個 Priority 0」的線性清單，而比較像兩層：

1. 已完成 baseline 的支援軌道：Track B / C / D。
2. 下一輪主要推進軌道：Track A / E / F。

換句話說，這份 roadmap 的核心不再是「先把 B / C / D 做出來」，而是「在 B / C / D 已有 baseline 的前提下，接下來最值得怎麼推主線」。

## 1.5 目前已可視為完成的 baseline

- Track B：inverse-design validity summary / gate artifact 已成立，可轉為維護型軌道。
- Track C：Mac hi-fi 已收斂成 `local structural spot-check`，不再是要被推成 validation truth 的 blocker。
- Track D：discrete layup final-design JSON 與 summary text 已經都能表達 discrete final verdict。

## 2. 規劃原則

### A. 主線不是 producer 包裝層

正式主線是：

`VSP / target cruise shape -> inverse design -> jig shape -> realizable loaded shape -> CFRP tube / discrete layup -> manufacturing-feasible design`

`producer`、`decision interface`、`autoresearch` 仍然重要，但定位是 integration boundary，不是主 physics 本體。

### B. benchmark 先保持開放

近期不把某一份舊 APDL / ANSYS case 直接釘成唯一 benchmark 真值，原因是：

- 歷史 case 可能已經不新鮮。
- 現在主線已從 parity / equivalent-beam 轉到 dual-beam production / inverse-design。
- benchmark 的價值在於「可比、可複製、能發現 ranking flip」，不是在於它是不是最早那份舊報告。

因此比較好的做法是維持一個 `benchmark basket`：

- 歷史 ANSYS/APDL case 當 evidence
- 最新可比 case 當當前驗證目標
- 若未來有新的 Mac hi-fi / open-source aeroelastic case，再逐步加入

### C. 高保真先做 spot-check，不做阻塞器

高保真層的近期角色應該是：

- 幫忙判斷主線有沒有明顯 model-form risk
- 幫忙抓幾何、支撐、載入映射是否翻車
- 當 finalist / suspicious design 的 spot-check

不應該是：

- 每次設計都必跑的主流程
- 讓主線停下來等它成熟的 blocker
- 在目前這個階段直接背書 discrete layup 最終真值

### D. 離散 CFRP / layup 是正式主線

這不是附屬後處理。

- continuous thickness 可以當 relaxed search space / warm start
- discrete CFRP / layup 才是 final design layer
- 所有正式 sign-off 敘事都應該往可製造 layup 收斂，而不是停在連續 thickness optimum

### E. requested 與 realizable 之間的差距是問題本體

未來 outer-loop 不是直接把 target cruise shape 當硬等式追到底，而是要承認：

- `requested cruise shape`
- `realizable cruise shape`
- `jig shape`

這三者不是同一件事。

近期先不要把這件事做成高維 co-design，而是先保留成低維外圈與 descriptor mismatch 的設計原則。

## 3. 目前 repo 已具備什麼能力

### 已成立

- dual-beam production 主線
- inverse design 與 jig / loaded artifacts
- dihedral / target-shape scaling 類 shape knob
- wire / rigging / pretension / tension gate / explicit truss 能力
- generic VSP intake 與 VSP -> AVL pipeline
- CLT / PlyMaterial / discrete layup / Tsai-Wu / manufacturability 能力
- producer / decision interface / autoresearch 外部整合邊界

### 還沒完全收成單一路徑

- `generic VSP intake -> inverse design -> discrete layup` 還沒有完全變成單一 canonical workflow
- requested-vs-realizable 的 outer-loop 更新機制還沒有正式化
- Mac 高保真雖已有 code path，但還沒成熟到可穩定驗證

## 4. 近期工作軌道

## Track A：主線收斂與入口整理

### 狀態

**NEXT / 主軸**

### 目標

把現在分散的入口、artifact 命名與對外敘事，收成更一致的主線操作方式。

### 為什麼現在值得做

- 目前最大的日常摩擦之一，是人和 agent 都還需要重新理解哪條路才是正式入口。
- 這類整理會直接降低後續所有任務的溝通成本。

### 近期交付物

- 更清楚的 canonical workflow 文件
- 一致的 artifact 命名與輸出摘要
- 把 `generic VSP intake -> inverse design -> CFRP / discrete layup` 的閱讀與操作路徑串起來

### 完成判準

- 新進協作者 30 秒內知道該從哪個入口開始
- AI agent 不需要先讀大量歷史報告才能知道主線
- 同一個設計案例的主要 artifact 不再散落成多套命名

### 風險

- 只整理文件、不整理 artifact 與腳本入口，會讓文件很快再次失真

## Track B：inverse-design 有效性與 gate

### 狀態

**baseline completed; maintain only**

### 目標

降低 frozen-load backout、exact nodal matching 與自我驗證的風險。

### 為什麼現在值得做

- 這直接影響你是否能相信目前輸出的 jig shape
- 不需要等高保真成熟，也不需要重寫整套 solver

### 近期交付物

- 若 fresh reanalysis 顯示仍有洞，再補更清楚的 mismatch / validity evidence
- 若外圈開始吃這些 artifact，再補更穩的 consumer-facing summary

### 完成判準

- baseline 已具備：
  - 同一個 inverse-design run 有清楚的 backout validity summary
  - exact nodal 不再是唯一判準
  - 明確知道哪些 run 是「可參考」而不是「可 sign-off」

### 不該先做的事

- 直接把這條線推成 full corotational / fully nonlinear rewrite

## Track C：Mac 高保真 structural spot-check

### 狀態

**baseline completed; on-demand only**

### 目標

讓 Apple Silicon 本機可以做結構級的高保真 spot-check，減少切 Windows 的頻率。

### 為什麼值得做

- 這條線直接回應現在的工作節奏痛點
- 即使它一開始只做到 structural spot-check，也已經能幫主線省下很多切換成本

### 近期交付物

- benchmark basket refresh
- apples-to-apples external benchmark definition
- finalist / suspicious design diagnosis when needed

### 完成判準

- baseline 已具備：
  - 至少一個代表性 case 能穩定在 Mac 上跑完
  - 報告裡能說清楚是 mesh / BC / load mapping 問題，還是 solver 本體問題
  - 能把它定位成「可信 spot-check」，而不是「最終真值」

### 先不要宣稱的事

- 不宣稱它已驗證 discrete layup 真值
- 不宣稱它已取代 ANSYS/APDL
- 不宣稱它已是最終 aeroelastic truth

## Track D：discrete CFRP / layup 主線化

### 狀態

**baseline completed; consume via Track A / F**

### 目標

把離散 layup 從「存在的能力」升格成「設計結果真正要收斂到的輸出層」。

### 為什麼值得做

- 你已經明確確認 continuous 做不出來
- 如果這一層沒有被正式放進輸出與判準，主線敘事會一直停在半成品

### 近期交付物

- 讓 Track A front door 能清楚暴露 discrete final-design artifact
- 讓 Track F outer loop 能直接消費 discrete final-design verdict

### 完成判準

- baseline 已具備：
  - 同一個案例可以從 target / jig / loaded 一路追到 discrete layup summary
  - 文件與實際輸出都不再把連續 thickness optimum 寫成 final answer

## Track E：surrogate / data / catalog

### 目標

在 canonical I/O 穩住之後，把探索效率與真實 catalog realism 接回來。

### 為什麼值得做

- 這會影響 sweep 成本與最終 ranking 的採購可用性
- 而且它現在已不需要再等 B / D baseline，因為這兩條線的 machine-readable artifact 已經存在

### 近期交付物

- optional surrogate warm start
- 真實 vendor / hardware catalog 資料化
- focused crossover sweep 的觸發規則

### 完成判準

- surrogate 是接在穩定的主線 artifacts 上，而不是接在還沒對齊的舊輸出
- vendor catalog 能支撐更像真實採購決策的 ranking

## Track F：requested-to-realizable 外圈 shape 調整

### 目標

把 cruise-shape 調整從手動 sweep 慢慢變成低維 outer-loop。

近期要對齊的目標型態不是 full aeroelastic sign-off，而是先把這條「repo 近期可交付版閉環」收斂出來：

`low-dimensional aero-shape knob`
-> `target loaded shape`
-> `inverse design`
-> `jig clearance / mass / manufacturing gate`
-> `discrete CFRP / layup verdict`
-> `realizable loaded-shape mismatch score`

### 適合先放進 outer loop 的變數

- `target_shape_z_scale`
- `dihedral_exponent`
- dihedral multiplier
- 低維 twist / washout family

### 先不要急著放進 outer loop 的變數

- 高維 free-form shape
- 太早進來的 full airfoil redesign
- 太細的離散 layup decision

### 完成判準

- 外圈評分看的是 realizable loaded shape，不是 requested target 本身
- mismatch 有明確 penalty / gate，而不是完全硬等式
- discrete layup recheck 結果能被 outer-loop summary 消費，而不是停在 sidecar
- 可以明確回答「這個低維 shape 候選值不值得往 drawing / design handoff 繼續推」

## Track G：mission-driven automatic design

### 目標

長期走到：

`pilot power + weight + mission constraints`
-> `best cruise shape`
-> `inverse design`
-> `jig shape`
-> `discrete CFRP / layup`
-> `manufacturable final design`

### 為什麼現在還不是主要工作

- 這條線依賴前面幾條軌道先穩
- 否則只會把尚未收斂的誤差與建模差距放大

### 應該晚一點才接進來的東西

- XFOIL / airfoil redesign
- 更完整的 mission objective
- 更高維 planform / shape co-design

## 5. 如果現在要選先做哪一條

### 情境 A：現在最卡的是「我不確定主線到底能不能信」

先做：

- 先讀 Track B / C 的既有 artifact
- 只有在 fresh evidence 顯示還有缺口時，才補 Track B / C

### 情境 B：現在最卡的是「使用者和 agent 都還是不知道怎麼用」

先做：

- Track A：主線收斂
- 並把 Track D 的 final-design artifact 明確掛到 front door

### 情境 C：現在最卡的是「探索很慢，想加速」

前提是 A 已先講清 canonical artifact，再做：

- Track E：surrogate / data / catalog

### 情境 D：現在最卡的是「我想開始調 cruise shape 本身」

先用低維變數做：

- Track F：requested-to-realizable 外圈 shape 調整

不要直接跳去 full co-design。

## 6. 近期不建議做的事

- 先把某份老 benchmark 報告升格成唯一 sign-off 真值
- 先投入大規模 phase report 歸檔
- 先做 full free-form cruise-shape optimization
- 先把 discrete layup 深嵌到最外層 optimizer
- 先讓 ASWING 或某個商業 solver 授權狀態決定整條主線是否停擺

## 7. 文件閱讀順序

1. 先看 [CURRENT_MAINLINE.md](../CURRENT_MAINLINE.md)
2. 再看 [NOW_NEXT_BLUEPRINT.md](NOW_NEXT_BLUEPRINT.md)
3. 想看細化版工作路徑，再看這份文件
4. 需要長期 phase 脈絡時，才看 [GRAND_BLUEPRINT.md](GRAND_BLUEPRINT.md)
