# HPA-MDO 目標流程標準與缺口圖

> **文件性質**：系統工程標準文件。  
> **用途**：把使用者確認的偽代碼流程升格成 repo 的目標流程標準，並明確標出目前缺口與可派工的執行命令。  
> **重要原則**：這份文件描述的是 **應該達成的流程標準**，不是宣稱 repo 現在已經全部完成。

## 1. 標準結論

本專案後續的流程標準，應以這條主線為準：

`氣動外形探索`
-> `target loaded shape / aero loads`
-> `inverse design`
-> `jig shape`
-> `ground clearance / mass / manufacturing gate`
-> `discrete CFRP layup`
-> `best design selection / drawing handoff`
-> `high-fidelity validation`
-> `aeroelastic loop closure sign-off`

這不是「理想願景而已」，而是之後審查方向對不對時應使用的主骨架。

## 2. 不可偷換的核心要求

下面這些不是可有可無的配件，而是流程標準的一部分：

- 必須有 **氣動外形探索**，不能假設 cruise shape 永遠固定。
- 必須有 **inverse design**，不能只做給定外形下的被動 sizing。
- 必須分清楚 `requested cruise shape`、`realizable loaded shape`、`jig shape` 三種 shape。
- 必須有 **ground clearance / total structural mass / manufacturing** 類實體 gate。
- 必須把 **discrete CFRP layup** 當 final design layer，不能停在 continuous thickness optimum。
- 必須有 **best design selection**，不能只吐一堆 case 給人手選。
- 必須有 **high-fidelity validation / release gate**，但它應該建立在凍結合約與 apples-to-apples case 上。
- 最終應該有 **aeroelastic loop closure**，也就是高保真受力後的形狀要回到當初被選中的 cruise-shape design intent。

## 3. 用 repo 語言重寫的標準流程

### Stage A：Aero-shape exploration

- 輸入 `origin_vsp`
- 用低維 knob 掃候選外形：
  - `dihedral multiplier`
  - `dihedral_exponent`
  - `target_shape_z_scale`
  - 之後可擴到低維 washout family
- 每個候選都必須有可比的氣動評分與載荷

### Stage B：Aero constraints / loads

- 每個候選都必須檢查最基本的 aero gate：
  - stall margin
  - stability / trim feasibility
  - 可用的載荷輸出
- 產出該候選的 `target loaded shape` 與 `aero loads`

### Stage C：Structural inverse design

- 對每個候選做 inverse design
- 產出：
  - `jig shape`
  - `realizable loaded shape`
  - mismatch diagnostics

### Stage D：Physical gates

- 每個候選都必須檢查：
  - `jig ground clearance`
  - `total structural mass`
  - wire / rigging constraints
  - manufacturing feasibility

### Stage E：Discrete CFRP layup

- 對通過前述 gate 的候選，做 discrete layup realization
- 不能只保留 continuous thickness optimum
- 產出：
  - discrete layup verdict
  - structural recheck
  - final design candidate

### Stage F：Best design selection

- 用一致的 score / gate 選出最值得往下推的設計
- 輸出：
  - winner
  - drawing-ready handoff
  - machine-readable summary

### Stage G：Hi-fi validation / release gate

- 對 finalist 做高保真驗證
- 目的不是取代主線，而是做 release gate
- 條件必須是：
  - geometry contract frozen
  - BC frozen
  - load ownership frozen
  - compare metrics frozen

### Stage H：Aeroelastic loop closure

- 高保真受力後的 shape，應回到被選中的 cruise-shape intent
- 這是最終標準的一部分
- 目前 repo 還沒完整做到，但不能從標準中刪掉

## 4. 缺口圖（Gap Map）

| 標準階段 | 目前 repo 狀態 | 判斷 | 主要缺口 | 如果跳過會怎樣 |
|---|---|---|---|---|
| Stage A 氣動外形探索 | 已有低維 knob 與 sweep 基礎 | `Partial` | 還沒有一條把 aero-shape exploration 收成正式候選比較流程的 canonical workflow | 會退回手動試 case，無法穩定選 design |
| Stage B aero gate + loads | 已有 VSP / AVL / VSPAero 基礎與部分 load refresh | `Partial` | 每個候選的 stall / stability / load contract 還沒被統一成 outer-loop contract | 候選外形之間的比較不乾淨 |
| Stage C inverse design | 主線已具備 | `Strong` | 需要更穩定地被外圈消費，而不是各 script 各自解讀 | 主線雖能跑，但不容易變成設計決策流程 |
| Stage D physical gates | clearance / mass / manufacturing 已存在 | `Strong` | 還沒被整理成單一 selection score | gate 在，但選案仍不夠直接 |
| Stage E discrete layup | 已具備且已成 final design layer | `Strong but not fully integrated` | discrete verdict 還沒有成為 outer-loop 的標配比較欄位 | 可能先選到實際不好做的 shape |
| Stage F best design selection | 有 artifact，但沒有完全 canonical | `Partial` | 還缺單一 winner summary 與 handoff contract | 使用者仍要自己從多份結果挑答案 |
| Stage G hi-fi validation | 只有 local structural spot-check | `Weak` | 目前不是 layup-aware final truth，也還沒有真正 frozen benchmark release gate | 不能當正式 sign-off |
| Stage H aeroelastic loop closure | 目前只有 lightweight refresh / mismatch logic | `Weak` | 沒有真正的 hi-fi deformation -> cruise-shape closure contract | 無法宣稱最終自洽 |

## 5. 哪些地方不能用簡化版糊過去

- 不能把 `continuous thickness optimum` 重新包裝成 final answer。
- 不能把 Track C 的 Mac CalculiX spot-check 重新包裝成最終 validation 完成。
- 不能把 `requested` 和 `realizable` 的差距當成只是報告附註，而不進 selection score。
- 不能只做 campaign，卻沒有 `winner contract`。
- 不能把 discrete layup 留在 sidecar，不接回外圈 decision。

## 6. 執行順序判斷

若現在要往這個標準實作，正確順序不是先硬衝 full hi-fi，而是：

1. 先把 **Stage A ~ F** 收成一條真正可用的 selection workflow
2. 先修正 **Stage E** 的設計空間：recipe library -> selector -> spanwise search -> zone rules
3. 再把 **Stage G** 從 local spot-check 升成真正的 frozen release gate
4. 最後才把 **Stage H** 做成真正的 aeroelastic loop closure sign-off

原因不是妥協，而是因為：

- Stage A ~ F 定義的是「怎麼選對設計」
- 其中 Stage E / F 若還停在 fixed-family round-up，後面所有更重的搜尋與驗證都會建立在偏掉的 final-design layer 上
- Stage G ~ H 定義的是「怎麼正式背書這個設計」

先把設計選擇邏輯做對，之後高保真才知道要驗的是哪一個 final candidate。

## 7. 可直接派工的 Agent Command Plan

下面這些工作包是按照上面的標準拆的。  
原則是：**每一包都要明確讓 repo 更貼近目標流程標準，而不是只補局部 code。**

### Command Pack 1：Outer-loop contract and score schema

- 目標：定義每個 aero-shape candidate 必須輸出的共同欄位
- 要補的東西：
  - candidate id
  - requested shape knobs
  - realizable mismatch metrics
  - jig ground clearance
  - total structural mass
  - manufacturing verdict
  - discrete layup verdict
  - winner score / reject reason
- 建議 write scope：
  - `scripts/direct_dual_beam_inverse_design.py`
  - `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`
  - `tests/test_inverse_design.py`
- 預估：`1 到 2 天`

### Command Pack 2：Recipe library foundation

- 目標：把 discrete layup 的材料空間從固定 family，升成少量但功能明確的 recipe library
- 要補的東西：
  - bending-dominant recipes
  - balanced torsion recipes
  - joint / hoop-rich local recipes
  - property-row / lookup contract
- 建議 write scope：
  - `src/hpa_mdo/structure/material_proxy_catalog.py`
  - `docs/dual_beam_preliminary_material_packages.md`
  - `tests/test_material_proxy_catalog.py`
- 預估：`1 到 2 天`

### Command Pack 3：Low-dimensional aero-shape campaign integration

- 目標：把 dihedral / target-shape scaling 類 knob 真的收成一條可重跑 campaign
- 要補的東西：
  - campaign runner
  - ranked summary
  - candidate comparison artifact
- 建議 write scope：
  - `scripts/dihedral_sweep_campaign.py`
  - `scripts/direct_dual_beam_inverse_design_feasibility_sweep.py`
  - `docs/task_packs/current_parallel_work/**`
- 預估：`2 到 3 天`

### Command Pack 4：Discrete layup verdict integration

- 目標：讓 outer loop 不是只看 continuous / equivalent 結果，而是把 discrete CFRP verdict 真的接回 selection
- 要補的東西：
  - candidate -> discrete final design linkage
  - structural recheck result ingestion
  - reject / pass logic
- 建議 write scope：
  - `examples/blackcat_004_optimize.py`
  - `src/hpa_mdo/utils/visualization.py`
  - `tests/test_optimizer_buckling.py`
  - `tests/test_discrete_layup.py`
- 預估：`1 到 2 天`

### Command Pack 5：Spanwise discrete search

- 目標：把整條 span 的離散疊層選擇變成正式搜尋問題，而不是逐段 first-fit round-up
- 要補的東西：
  - DP / shortest-path 類 selector
  - transition rule handling
  - spanwise mass / stiffness-aware objective
- 建議 write scope：
  - `src/hpa_mdo/utils/discrete_layup.py`
  - `src/hpa_mdo/utils/discrete_spanwise_search.py`
  - `tests/test_discrete_layup.py`
  - `tests/test_discrete_spanwise_search.py`
- 預估：`2 到 4 天`
- 注意：這一包應在 Command Pack 2 完成並驗證後再進行

### Command Pack 6：Zone-dependent thinning / ply-drop rules

- 目標：把全翼一刀切的 floor / drop 規則改成 zone-aware，而不是一開始就全放鬆
- 要補的東西：
  - root / joint / outboard zone rules
  - local reinforcement / termination assumptions
  - 對 outboard thinning 更誠實的 gates
- 建議 write scope：
  - `src/hpa_mdo/utils/discrete_layup.py`
  - `docs/dual_beam_preliminary_material_packages.md`
  - `tests/test_discrete_layup.py`
- 預估：`1 到 2 天`
- 注意：這一包應在 Command Pack 5 完成並驗證後再進行

### Command Pack 7：Winner handoff and drawing contract

- 目標：選出 best design 後，自動導向 drawing-ready handoff
- 要補的東西：
  - winner package
  - selected candidate metadata
  - drawing-ready linkage
- 建議 write scope：
  - `scripts/export_drawing_ready_package.py`
  - `docs/drawing_ready_package.md`
  - `tests/test_drawing_ready_package.py`
- 預估：`1 天`

### Command Pack 8：Hi-fi release gate contract

- 目標：把 hi-fi 從 spot-check 慢慢推向真正 release gate 的前置條件
- 要補的東西：
  - frozen benchmark contract
  - mass / reaction / deflection / twist compare contract
  - finalist-only release-gate rule
- 建議 write scope：
  - `docs/benchmark_contract.md`
  - `scripts/validate_benchmark_contract.py`
  - `src/hpa_mdo/hifi/**`
  - `tests/test_validate_benchmark_contract.py`
- 預估：`2 到 4 天`
- 注意：這一包 **不是** 宣稱 hi-fi 已完成，而是把它從散的工具收成 release-gate contract

### Command Pack 9：Aeroelastic loop-closure architecture

- 目標：定義從 finalist 到最終 self-consistent sign-off 所需的 interface
- 要補的東西：
  - hi-fi deformed-shape export contract
  - cruise-shape comparison contract
  - loop-closure pass line definition
  - 哪些求解器 / toolchain 可以擔任這一層
- 建議 write scope：
  - `docs/hi_fidelity_validation_stack.md`
  - `docs/GRAND_BLUEPRINT.md` 只在確認需要時才改
  - 新增 architecture / interface spec 文件
- 預估：`2 到 3 天` 做規格；真正實作通常更久

## 8. 推薦並行方式

如果你要開多個 thread，我建議這樣分：

- Thread 1：Command Pack 1
- Thread 2：Command Pack 2
- Thread 3：Command Pack 3
- Thread 4：Command Pack 4
- Thread 5：Command Pack 7
- Thread 6：Command Pack 8
- Thread 7：Command Pack 9

依賴關係：

- Pack 1 是最先要穩的，因為它定義 score schema
- Pack 2 / 3 / 4 可以平行，但都應對齊 Pack 1 contract
- Pack 5 必須等 Pack 2 穩住後再進
- Pack 6 必須等 Pack 5 穩住後再進
- Pack 7 可以和 Pack 3 / 4 平行，但不要回頭改 Pack 2 的材料 contract
- Pack 8 / 9 可以平行做，但它們不應回頭改掉主線標準

## 9. 系統工程時間預估

若以這份標準為準，時間應這樣估：

- **Phase A：把 Stage A ~ F 收成一條近期可用主線**
  - 預估：`5 到 10 個工作天`
- **Phase B：把 Stage G 收成 finalist release gate**
  - 預估：`1 到 2 週`
- **Phase C：把 Stage H 推到真正 aeroelastic loop closure sign-off**
  - 預估：`再 2 到 4 週`

所以如果只問「多久能讓流程標準開始被真正實踐」：

- 第一波可以在 **一週左右** 看到明顯收斂
- 但如果問「多久才完全達到偽代碼最後那種 sign-off 標準」，答案不應該被低估

## 10. 最後的判斷

這份標準是對的，而且值得照它規劃。  
接下來不應再討論「要不要接受這個標準」，而應該討論：

- 哪些缺口先補
- 哪些工作包可以平行
- 哪些地方屬於 release gate 而不是主線設計內圈

也就是說，後續所有規劃的問題都應該變成：

`怎麼讓 repo 更接近這份標準`

而不是：

`怎麼替目前的 repo 狀態找一個比較舒服的說法`
