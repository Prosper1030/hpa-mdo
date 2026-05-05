# Mission Drag Budget Contract v1

## 為什麼主翼 optimizer 不能直接吃整機 CD0

主翼最佳化器（wing optimizer）的設計變數是翼梁幾何、剖面選擇、展弦比等主翼參數。
主翼幾何直接決定的是**主翼剖面阻力係數** `CD0_wing_profile`，而非整機 CD0。

整機 CD0 包含了尾翼、整流罩、輪轂、傳動系統、連接接頭、鉸接件等非主翼部件的寄生阻力。
若主翼 optimizer 直接以整機 CD0 為目標，就必須在每次評估時重算所有非主翼部件的阻力，
而這些部件的幾何在主翼最佳化階段往往尚未確定，形成**循環依賴**。

正確的作法是將整機 CD0 分解為兩個部分：

| 部分 | 符號 | 說明 |
|------|------|------|
| 主翼剖面阻力係數 | `CD0_wing_profile` | 主翼 optimizer 的直接輸出 |
| 非主翼等效阻力係數 | `CDA_nonwing / S` | 早期設計階段的保留量（reserve） |

主翼 optimizer 只需對 `CD0_wing_profile` 負責，然後由本模組的公式還原為整機估計值。

---

## 整機 CD0 估計公式

```
CD0_total_est = CD0_wing_profile + CDA_nonwing / S
```

其中：
- `CD0_wing_profile`：主翼剖面阻力係數（來自 XFOIL / AVL / 主翼 optimizer）
- `CDA_nonwing`：非主翼部件的阻力面積總和（單位 m²），從 YAML budget 讀取
- `S`：主翼面積（m²），由展弦比與翼展推導：`S = b² / AR`

CDA_nonwing 採用絕對面積（m²）而非係數，原因是非主翼部件的阻力與主翼面積無關；
若主翼面積改變，非主翼 CDA 不應等比例縮放。

---

## 螺旋槳效率不屬於 CD0

螺旋槳效率損失（`eta_prop`）表示螺旋槳輸入軸功率轉換為推進功率的效率，
其損失機制（滑流收縮、誘導損失、葉片剖面摩擦）**不等同於氣動阻力**。
若將螺旋槳損失折算進 CD0，會使阻力分析與動力分析之間的邊界模糊，
且在不同飛行狀態下會出現無法解釋的 CD0 隨速度漂移現象。

正確作法：
- 阻力計算中只計真實氣動阻力，套用 `CD0_total_est`
- 功率需求折算到飛行員曲軸輸出時，除以 `eta_prop * eta_trans`：

```
P_crank = P_aero / (eta_prop * eta_trans)
```

---

## 非主翼 Reserve 的涵蓋範圍

`CDA_nonwing` 應包含下列部件的阻力面積估計：

| 部件 | 備注 |
|------|------|
| 水平尾翼 / 垂直尾翼 | 含翼型剖面阻力與干擾阻力 |
| 前緣整流罩（fairing） | 依設計外形估算 |
| 輪轂（hub） | 螺旋槳安裝盤 |
| 傳動懸臂（pylon） | 螺旋槳驅動軸外露段 |
| 外露傳動元件 | 齒輪箱、聯軸器 |
| 機身 / 座艙架構 | 若非完全整流 |
| 金屬接頭與鉸接件 | 翼梁端接頭、升降舵鉸鏈 |
| 雜散阻力（misc） | 繩索、線材、感測器等 |

螺旋槳葉片本身的氣動效率損失應計入 `eta_prop`，不計入 `CDA_nonwing`。

---

## Main Wing Optimizer 如何使用這份 Budget

典型流程如下：

```python
from hpa_mdo.mission.drag_budget import (
    load_mission_drag_budget,
    MissionDragBudgetInputs,
    evaluate_drag_budget_candidate,
)

budget = load_mission_drag_budget("configs/mission_drag_budget_example.yaml")

inputs = MissionDragBudgetInputs(
    speed_mps=6.5,
    span_m=35.0,
    aspect_ratio=38.0,
    mass_kg=98.5,
    cd0_wing_profile=optimizer_result.cd0_profile,   # 來自主翼 optimizer
    oswald_e=optimizer_result.oswald_e,
    cl_max_effective=1.55,
    air_density_kg_m3=1.1357,
    eta_prop=0.86,
    eta_trans=0.96,
    target_range_km=42.195,
    rider_curve=rider_curve,
    thermal_derate_factor=derate_factor,
)

result = evaluate_drag_budget_candidate(budget, inputs, reserve_mode="target")

print(f"cd0_total_est     = {result.cd0_total_est:.5f}")
print(f"drag_budget_band  = {result.drag_budget_band}")
print(f"power_margin      = {result.mission_power_margin_crank_w:.1f} W")
```

`drag_budget_band` 回傳值含義：

| Band | 條件 |
|------|------|
| `target` | `CD0_total_est ≤ target` 且 `CD0_wing_profile ≤ wing_target` |
| `boundary` | `CD0_total_est ≤ boundary` 且 `CD0_wing_profile ≤ wing_boundary` |
| `rescue` | `CD0_total_est ≤ rescue`（整機總量勉強可行） |
| `over_budget` | 超出所有限制 |

主翼 optimizer 的目標是讓候選設計落入 `target` band，並使 `mission_power_margin_crank_w ≥ 5 W`。

---

## MissionContract Shadow Adapter

`hpa_mdo.mission.contract.MissionContract` 是把 Stage-0 mission screener
seed row、`optimizer_handoff.json`、`summary.json` 與 drag-budget YAML 合併成
主翼 optimizer 可讀合約的第一層 adapter。

目前 `scripts/birdman_spanload_design_smoke.py` 只在 shadow mode 連接它：

- 不改變 `inverse_chord_then_residual_twist_no_cst_no_xfoil` 的排序。
- 不新增 hard gate，也不拒絕候選。
- 在 report JSON、compact candidate records、top-candidate bundle 的
  `mission_contract.json` / `mission_contract.csv` 輸出下列欄位：
  `mission_CL_req`、`mission_CD_wing_profile_target`、
  `mission_CD_wing_profile_boundary`、`mission_CDA_nonwing_target_m2`、
  `mission_CDA_nonwing_boundary_m2`、`mission_power_margin_required_w`、
  `mission_contract_source`。

合約中的核心公式是：

```
S = span_m^2 / aspect_ratio
CL_req = W / (0.5 * rho * V^2 * S)
CD_wing_profile_target = CD0_total_target - CDA_nonwing_target / S
CD_wing_profile_boundary = CD0_total_boundary - CDA_nonwing_boundary / S
```

這是後續「mission screener → FourierTarget v2 → zone-level airfoil
top-k → AVL actual Cl → profile drag」閉環的資料契約入口；Phase 1 只
暴露欄位與來源，不讓它成為 optimizer driver。

---

## 這只是早期設計預算，不取代高精度分析

本模組的 `CD0_total_est` 是**概念設計階段的快速估計工具**，具有以下限制：

1. `CDA_nonwing` 來自工程師根據歷史類似設計估算的保留量，**不是 CFD 或風洞量測值**。
2. `CD0_wing_profile` 在主翼 optimizer 早期使用的是剖面極曲線的 2D 值，
   未考慮展向流動、翼尖效應與三維干擾效應。
3. 干擾阻力（interference drag）在非主翼 reserve 中僅粗略涵蓋。

**高精度阻力分析必須使用 AVL（誘導阻力）、XFOIL（剖面阻力）或 CFD（完整干擾阻力）**。
本模組的任務是在早期設計迭代中提供快速 go/no-go 判斷，而非取代這些工具。

當設計進入 M9 詳細設計階段後，`CDA_nonwing` 的估計值應透過 AVL / VSPAero 分析更新，
並將更新後的值寫回 `mission_drag_budget_example.yaml` 的 `nonwing_reserve` 區塊。
