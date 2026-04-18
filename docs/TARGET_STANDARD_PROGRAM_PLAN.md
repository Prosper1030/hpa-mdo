# HPA-MDO 收斂到目標偽代碼的長程 Program Plan

> **文件性質**：長程系統工程計畫。  
> **目的**：把「整個專案最終要貼近使用者偽代碼流程標準」這件事，從聊天共識升格成正式 program plan。  
> **搭配文件**：
> - 目標標準本體：[docs/TARGET_STANDARD_GAP_MAP.md](/Volumes/Samsung SSD/hpa-mdo/docs/TARGET_STANDARD_GAP_MAP.md)
> - 近期藍圖：[docs/NOW_NEXT_BLUEPRINT.md](/Volumes/Samsung SSD/hpa-mdo/docs/NOW_NEXT_BLUEPRINT.md)
> - 長期願景總藍圖：[docs/GRAND_BLUEPRINT.md](/Volumes/Samsung SSD/hpa-mdo/docs/GRAND_BLUEPRINT.md)

## 1. 先講結論

是，有長程規劃。  
但在這份文件之前，repo 裡的內容比較像：

- 有**長期願景**，在 `GRAND_BLUEPRINT`
- 有**近期軌道與缺口圖**，在 `NOW_NEXT_BLUEPRINT` 和 `TARGET_STANDARD_GAP_MAP`

還缺一份把這兩者中間接起來的：

`從現在 repo 狀態 -> 收斂到使用者偽代碼標準`

的正式 program plan。

這份文件就是補那一層。

## 2. 最終目標不是模糊的

本專案最終要收斂到的，不是抽象的「更完整 MDO」，而是這條主線：

`origin_vsp`
-> `外形探索`
-> `每個外圈 candidate 重建幾何並重跑氣動`
-> `aero constraints / trim / stability`
-> `inverse design`
-> `jig shape`
-> `clearance / mass / manufacturing gate`
-> `discrete CFRP layup`
-> `best design selection`
-> `finalist hi-fi validation`
-> `aeroelastic loop closure sign-off`

這裡最重要的兩個點是：

- `discrete CFRP layup` 不是 sidecar，而是 final design layer
- `run_aerodynamics(adjust_vsp)` 不是可有可無，而是最終標準的一部分

## 3. 目前 repo 與最終標準的距離

### 已經比較接近的部分

- inverse design / jig shape 主線已存在
- requested / realizable / jig 三種 shape 的觀念已存在
- discrete layup 已經進入 final-design artifact
- drawing-ready package 已成立
- Mac hi-fi spot-check 已有明確邊界

### 還明顯沒貼齊的部分

- 外圈還不是每個 candidate 都真的 `geometry rebuild + rerun aerodynamics`
- 外圈還沒有正式 trim / stability / load contract
- inverse design + discrete layup 還沒被收成單一乾淨的 workflow contract
- hi-fi 還不是 finalist release gate
- aeroelastic loop closure 還沒有真正成立

## 4. 長程收斂分期

## Phase 0：標準與邊界凍結

### 目標

先把什麼算標準、什麼不算標準講清楚，避免後續工作做反。

### 代表成果

- `TARGET_STANDARD_GAP_MAP`
- drawing-ready package 定位清楚
- Track C 正式停在 local structural spot-check
- benchmark contract 已有最小定義

### 狀態

**已啟動，且核心邊界已經立住。**

## Phase 1：把結構 final-design layer 做對

### 目標

先修正設計空間本身，不要在錯的 discrete layer 上做更多重運算。

### 核心內容

- recipe library foundation
- property-based selector
- spanwise DP discrete search
- zone-dependent thinning / ply-drop rules
- discrete final-design verdict 正式接回 outer-loop summary

### 為什麼先做這個

因為如果 Stage E / F 還停在：

`continuous thickness -> fixed family round-up`

那後面不管再加多少 aero rerun、再跑多少 hi-fi，都還是在偏掉的 final-design layer 上精煉答案。

### 完成判準

- discrete layup 不再只是 fixed-family round-up
- outer loop 的 winner selection 真正吃 discrete final verdict
- clean outboard span 不再被全翼同一個 global floor 永遠鎖死

### 目標時間

**約 1 到 2 週**

這一段就是現在已經正式排進 task pack 的主軸。

## Phase 2：把外圈升成真正的 aero candidate loop

### 目標

把現在的 lightweight load refresh，升級成更貼近偽代碼的：

`run_aerodynamics(adjust_vsp)`

### 核心內容

- 每個外圈 candidate 都能重建幾何
- 每個外圈 candidate 都能重跑 OpenVSP / VSPAero
- 每個 candidate 都有自己的 load ownership
- aero constraints / trim / stability gate 正式進入 candidate selection
- 不再只靠既有 AoA sweep 插值刷新

### 這一段是不是必要

**必要。**

它不是 optional fancy upgrade，而是你偽代碼標準裡的重要一段。

### 什麼可以 trade-off，什麼不能

可以 trade-off 的是：

- 不一定每個內圈結構小步都重跑 aero
- 可以把 aero rerun 放在外圈 candidate 層，而不是每個 structural micro-iteration

不能 trade-off 的是：

- 不應永久停留在「外形改了，但只拿舊 aero case 插值」當最終主線

### 完成判準

- 外圈 candidate 有真實 rerun aero artifact
- candidate ranking 不再只是 load refresh ranking
- trim / stability 不再只是附註，而是 gate

### 目標時間

**約 1 到 2 週**

這一段是下一個主戰場，不應再往後拖太久。

## Phase 2.5：Rib Integration Foundation

### 目標

把 rib 從「簡化 proxy / 研究想法」升成結構主線可消費的正式 contract。

### 為什麼放在這裡

rib 不是 hi-fi 才要想的事，它是結構主線的一部分。
但它也不該早於 rerun-aero candidate contract 太多，否則會把 still-moving 的 load ownership 與新的 rib 設計空間混在一起。

所以正確位置是：

- 晚於 `Phase 2 rerun-aero baseline`
- 早於 `Phase 4 finalist hi-fi release gate`

### 核心內容

- `data/rib_properties.yaml`
- rib family / spacing / derived `warping_knockdown`
- rib bay surrogate（例如 `Δ/c`、shape-retention risk 類指標）
- passive rib robustness mode
- 之後才是 zone-wise rib pitch / family optimization

### 第一版不該做什麼

- 不做 per-rib 設計變數
- 不做 rib cutout / topology optimization
- 不把 rib 第一版工作丟去 hi-fi

### 完成判準

- repo 不再只靠手填 `dual_spar_warping_knockdown`
- rib 影響能以 report / robustness / surrogate 形式進入主線
- zone-wise rib optimization 的入口已被定義，但不需要在第一天就全做完

### 目標時間

**約 3 到 7 天**

在目前多 agent 節奏下，這一段不該再抓成週級別大工程。

## Phase 3：把主線收成真正乾淨的 workflow contract

### 目標

把 repo 概念上的同一條主線，收成更像你偽代碼的單一工作流。

### 核心內容

- 對外 contract 更像：
  - `run_aerodynamics(...)`
  - `optimize_structure(...)`
  - `select_best_design(...)`
- 即使內部仍保留兩段求解，也要對外形成單一 candidate contract
- 統一 summary / machine-readable artifact / reject reason

### 注意

這不代表一定要先把所有 code 重構成一個大函式。

重點是：

- workflow contract 要乾淨
- 不是所有內部實作都要先長得一樣

### 目標時間

**約 1 週**

這段可以和 Phase 2 局部重疊，但不該早於 Phase 1 太多。

## Phase 4：把 hi-fi 升成 finalist release gate

### 目標

讓 hi-fi 不再只是 diagnosis / spot-check，而是 finalist 的正式 release gate。

### 核心內容

- frozen geometry / BC / load contract
- apples-to-apples benchmark
- finalist-only compare path
- release-gate verdict schema

### 注意

這不等於一開始就要求它變成全案主流程。  
它的正確角色是：

- 先選出 finalist
- 再做更重的高保真 release check

### 目標時間

**約 1 到 2 週**

這段也會受 benchmark 與求解器穩定度影響。

## Phase 5：完成 aeroelastic loop closure sign-off

### 目標

把最終變形後的高保真 shape，真正對回當初選中的 cruise-shape intent。

### 核心內容

- hi-fi deformed-shape export contract
- cruise-shape comparison contract
- loop-closure pass line
- sign-off narrative

### 這一段的重要性

這不是加分項，而是最終標準的一部分。  
只是它不應該在前面的 selection / final-design layer 還沒收對時就先硬衝。

### 目標時間

**約 2 到 4 週**

## Phase 6：mission-driven 自動化設計

### 目標

長期走到：

`mission / pilot / constraints`
-> `best cruise shape`
-> `inverse design`
-> `jig`
-> `discrete CFRP layup`
-> `release-gated final design`

### 說明

這一段是長遠終局，但不是現在最急的主線缺口。

## 5. 現在不是只有近期規劃

如果用你最在意的標準來看，現在的規劃其實分三層：

- **標準層**：`TARGET_STANDARD_GAP_MAP`
- **近期執行層**：`NOW_NEXT_BLUEPRINT` + current task pack
- **長程收斂層**：這份 `TARGET_STANDARD_PROGRAM_PLAN`

所以答案不是「只有近期規劃」。

更準確地說是：

- 以前有長期願景與近期規劃
- 但還缺一份明確對齊你偽代碼標準的中長程收斂計畫
- 現在這份文件把那層補上了

## 6. 系統工程上的時間判斷

如果有多個 agent，而且你願意讓 quick analysis 用到 `10 到 30 分鐘` 這種比較正常的設計預算，我的實際判斷是：

- **Phase 1**：`1 到 2 週`
- **Phase 2 + Phase 3**：再 `2 到 3 週`
- **Phase 4 + Phase 5**：再 `3 到 6 週`

所以如果你的問題是：

`整個專案什麼時候會真正貼近我的偽代碼？`

我的判斷是：

- **主線前半段明顯貼近**：`約 2 到 4 週`
- **到 finalist release gate 都比較像樣**：`約 1 到 2 個月`
- **到真正的 aeroelastic loop-closure sign-off**：通常會落在 `更長的 1 到 3 個月級別`

這不是保守說法，而是因為：

- 外圈真 rerun aero
- finalist hi-fi release gate
- loop closure

這三段本來就是整個系統裡最重、最容易出 contract 問題的地方。

## 7. 接下來的直接動作

如果照這份長程計畫執行，現在最正確的順序是：

1. 先做目前已派工的 Phase 1 波次
2. 我整合驗證後，立刻開 **Phase 2 的 Wave 4 計畫**
3. 不讓外圈真 rerun aero 這件事再被無限延後

也就是說：

**不是只有近期規劃。**  
**現在已經有完整的長程 program plan，而且下一個要接的就是你最在意的外圈真 rerun aero。**
