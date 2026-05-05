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

## FourierTarget v2 Shadow Diagnostics

`hpa_mdo.aero.fourier_target.FourierTarget` 是 Phase 2 的 mission-aware
spanload reference。它使用 `MissionContract` 的 `CL_req`、`AR`、`span_m`、
`speed_mps`、`rho` 與 `weight_n` 建立目標循環分布：

```
A1 = CL_req / (pi * AR)
Gamma(theta) = 2 * b * V * A1 * [sin(theta) + r3 sin(3 theta) + r5 sin(5 theta)]
cl_target = 2 * Gamma / (V * chord_ref)
e_theory = 1 / (1 + 3*r3^2 + 5*r5^2)
```

目前 `inverse_chord_then_residual_twist_no_cst_no_xfoil` 路線只在 shadow mode
使用它：

- 不改變 Stage-1 ranking、objective、hard gates 或 rejection 行為。
- 不做 station-by-station airfoil 選擇，也不啟動 airfoil database / XFOIL loop。
- 用 AVL actual loading 和 FourierTarget 做 normalized half-span loading
  shape comparison，輸出 `target_vs_avl_rms_delta`、`target_vs_avl_max_delta`
  與 `target_vs_avl_outer_delta`。
- top-candidate bundle 會額外輸出 `fourier_target.json` 與
  `fourier_target.csv`，欄位包含 `eta`、`y`、`chord_ref`、
  `gamma_target`、`lprime_target`、`cl_target`。

這些欄位是後續「equivalent incidence / physical twist reconstruction」與
「AVL actual Cl 回查 airfoil database」的診斷基準，不是目前的淘汰條件。

## Airfoil Database Profile Drag Shadow

`hpa_mdo.airfoils.database` 是 Phase 3 的正式 airfoil database 介面。
目前它只放入手動 fixture：

- `fx76mp140`：使用 `docs/research/xfoil_fx76mp140_re410000/` 的單一
  Reynolds XFOIL 參考 polar。
- `clarkysm`：手動 quadratic polar fixture。
- `dae31`、`dae11`、`dae21`、`dae41`：歷史翼型 schema placeholder。

所有上述資料目前都標成 `not_mission_grade`，placeholder 不會被當成
最終任務級 polar。這個 phase 不做 CST / XFOIL closed-loop，不做 NSGA，
也不做 station-by-station greedy min-CD 選型。

`inverse_chord_then_residual_twist_no_cst_no_xfoil` 的 Phase 3 shadow route
使用固定 zone assignment：

| Zone | Airfoil |
|------|---------|
| root | FX 76-MP-140 |
| mid1 | FX 76-MP-140 |
| mid2 | ClarkY smoothed |
| tip | ClarkY smoothed |

profile drag 估算使用 AVL actual local Cl，而不是 Fourier target Cl：

```
Re_i = rho * V * chord_i / mu
cd_i = airfoil_db.lookup(airfoil_id(zone_i), Re_i, AVL_cl_i)
CD_profile = 2 / S * integral(chord_i * cd_i dy)
CD0_total_est_airfoil_db = CD_profile + CDA_nonwing_target / S
```

輸出欄位包含 `profile_cd_airfoil_db`、`cd0_total_est_airfoil_db`、
`mission_drag_budget_band_airfoil_db`、`profile_drag_station_warning_count`、
`min_stall_margin_airfoil_db`、`max_station_cl_utilization_airfoil_db` 與
`profile_cd_airfoil_db_source_quality`。top-candidate bundle 另輸出
`airfoil_profile_drag.json` / `airfoil_profile_drag.csv`。這些值仍是
shadow-only，不改變 ranking、objective、hard gate 或 rejection。

## Zone Airfoil Sidecar Shadow

Phase 4 在 `inverse_chord_then_residual_twist_no_cst_no_xfoil` 上加入第一個
airfoil closed-loop sidecar，但仍不改變主 route 的排序或淘汰條件。
流程是：

```
loaded-shape AVL actual Cl/Re
→ zone_envelope
→ zone-level airfoil top-k
→ capped AVL rerun combinations
→ rerun AVL actual Cl profile-drag integration
```

重要限制：

- 不做 station-by-station greedy min-CD airfoil selection。
- 不啟動 CST / NSGA / XFOIL closed-loop。
- fixture polar 仍標示為 `not_mission_grade_sidecar`。
- sidecar best 只輸出診斷欄位，例如 `sidecar_best_profile_cd`、
  `sidecar_best_cd0_total_est`、`sidecar_best_e_CDi`、
  `sidecar_best_target_vs_avl_rms` 與 `sidecar_improved_vs_baseline`。
- profile drag 一律使用 sidecar rerun 後的 AVL actual local Cl，而不是
  Fourier target Cl。

top-candidate bundle 會輸出：

- `zone_envelope.json` / `zone_envelope.csv`
- `airfoil_sidecar_combinations.csv`
- `airfoil_sidecar_best.json`
- `airfoil_sidecar/combination_XX_summary.json`
- `airfoil_sidecar/combination_XX_profile_drag.csv`

這些輸出用來比較固定 seed assignment 與 zone-level top-k assignment 的
loaded-shape AVL / profile-drag 變化；目前仍是 shadow-only，不新增 hard gate，
也不進入 ranking sort key。

## Loaded Shape / Jig Feasibility Shadow Diagnostics

新增 loaded-shape shadow adapter 後，route 會把目前 candidate 的
dihedral 欄位轉成半翼 loaded Z 參考，並輸出：

- `loaded_shape_mode`
- `loaded_tip_dihedral_deg`
- `loaded_tip_z_m`
- `loaded_shape_source`
- `jig_feasible_shadow`
- `jig_feasibility_band`
- `jig_tip_deflection_m`
- `jig_tip_deflection_ratio`
- `jig_effective_dihedral_deg`
- `jig_tip_deflection_preferred_status`
- `jig_warning_count`

jig feasibility 會優先重用 `hpa_mdo.concept.jig_shape.estimate_tip_deflection`
的 wire-relieved concept proxy；若缺少 config / geometry 欄位，會明確標成
`placeholder_not_structure_grade`，不會被當成結構級判定。

AVL writer 仍保留 flat fallback；當 station 帶入 explicit `z_m` 或既有
dihedral schedule 時，SECTION 的 Z coordinate 會是非零 loaded-shape geometry。
profile drag integration 現在同時輸出 AVL Cl source metadata：

- `profile_drag_cl_source_shape_mode`
- `profile_drag_cl_source_loaded_shape`
- `profile_drag_cl_source_warning_count`

若 profile drag 使用的是 flat 或尚未驗證 loaded-shape 的 AVL local Cl，
`profile_drag_cl_source_shape_mode` 會標為
`flat_or_unverified_loaded_shape`。只有確認來自 loaded-dihedral AVL geometry
時，才會標為 `loaded_dihedral_avl`。這些欄位仍是 shadow-only，不改變
ranking、objective、hard gate 或 rejection。

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
