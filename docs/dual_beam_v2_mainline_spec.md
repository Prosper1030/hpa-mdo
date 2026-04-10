# Dual-Beam V2 主線規格與研究報告

產出時間：2026-04-10 CST

## 目的

這份文件釘住未來 direct dual-beam V2 主線的物理規格、邊界條件規格、設計變數方案與數值路線。它不是 code patch，也不是把 ANSYS 變成內迴圈；目標是建立一個快速、不要過度樂觀、丟去高保真 spot-check 不會直接翻車的結構設計前端。

本文件明確區分：

- 已驗證：repo 內已有程式、報告、benchmark 或本輪機制探針支持。
- 合理推論：由現有模型與數值結果推導，但還沒被獨立高保真/實驗證實。
- 尚未證實：V2 需要後續 reviewer 或實作驗證的項目。

## 證據來源

主要 repo 證據：

- `docs/ansys_equivalent_beam_validation_pass.md`
- `docs/dual_spar_spotcheck_workflow.md`
- `docs/direct_dual_beam_v1_research.md`
- `src/hpa_mdo/structure/dual_beam_analysis.py`
- `src/hpa_mdo/structure/ansys_export.py`
- `scripts/dual_beam_refinement.py`
- `scripts/benchmark_dual_beam_paths.py`
- `scripts/direct_dual_beam_v1.py`
- `output/blackcat_004_internal_dual_beam_smoke_with_ansys/dual_beam_internal_report.txt`
- `output/guardrail_experiment/guardrail_summary.json`
- `output/dual_beam_path_benchmark_v1_baseline/benchmark_report.txt`
- `output/direct_dual_beam_v1_baseline/direct_dual_beam_v1_report.txt`

本輪另做了不寫檔的機制探針：固定 equivalent optimum 幾何，只改 dual-beam link topology、wire BC 與 torque/lift load 分解，用來確認主導機制。

## A. 問題主因總結

### 已驗證

Equivalent-beam validation 已經 PASS。內部 equivalent FEM 對 equivalent-beam ANSYS 的 tip/max vertical displacement 誤差是 0.67%，reaction 與 mass 也在 gate 內。因此目前 direct dual-beam 問題不是「內部 equivalent solver 對不上 ANSYS」。

Dual-spar topology 本身，內部 dual-beam 與 dual-spar ANSYS 對得很好。Equivalent optimum 用 dual-beam/dual-spar 評估時：

| 指標 | internal dual-beam | ANSYS dual-spar | 誤差 |
| --- | ---: | ---: | ---: |
| main tip | 2837.618 mm | 2853.556 mm | 0.56% |
| max \|UZ\| | 3373.731 mm | 3390.902 mm | 0.51% |
| support reaction | 910.495 N | 910.495 N | 0.00% |
| spar mass | 9.455 kg | 9.472 kg | 0.18% |

Active displacement 從 equivalent-beam 的 main tip 轉移到 dual-beam 的 rear outboard tip：

| 設計 | main tip | rear tip / max \|UZ\| | rear/main ratio |
| --- | ---: | ---: | ---: |
| equivalent optimum evaluated as dual-beam | 2837.6 mm | 3373.7 mm | 1.1889 |
| hybrid refinement | 2457.0 mm | 2950.6 mm | 1.2009 |
| reduced direct V1 | 2455.0 mm | 2967.7 mm | 1.2088 |

Rear/main radius ratio guardrail 不是有效修法。`rear_r >= 0.40 * main_r` 讓 dual-beam mass 增加 3.26%，但 max \|UZ\| 反而變差 0.16%。這證明問題不是簡單「rear 太細，所以補 rear/main 比例」。

Radius 明顯比 thickness 有效。Equivalent optimum 附近：

- +5% all thickness：mass +4.88%，max \|UZ\| -4.38%。
- +5% all radii：mass +5.11%，max \|UZ\| -13.75%。

Main radius segments 3-4 是最強 bending lever，但 baseline main segments 1-4 已經等半徑；單獨增加 3-4 會違反 monotone taper，所以 V2 必須用 taper-preserving plateau knob，不該給 optimizer 自由破壞 taper。

Rear outboard radius 對 rear amplification 有直接槓桿，但 baseline rear spar 全段都在 10 mm minimum radius；單獨增加 rear segments 5-6 也會違反 taper。因此 V2 的 rear outboard knob 不能是自由 outboard OD，必須是 upstream-carry taper projection，或改用 local layup/thickness/EI knob。

### 本輪機制探針

Baseline current dual-beam：

```text
main_tip = 2837.624 mm
rear_tip = max|UZ| = 3373.736 mm
location = rear node 60
rear/main ratio = 1.1889
```

只改 topology/load 的探針：

| 探針 | main tip | rear tip / max \|UZ\| | 解讀 |
| --- | ---: | ---: | --- |
| 無 rigid links，current loads | 1993.8 mm | 1,154,662.2 mm | rear spar 單獨承受 torque couple 時幾乎不是可用結構 |
| 每個 node 都 rigid link，current loads | 2853.6 mm | 2853.6 mm | rear amplification 消失，表示 link topology 是關鍵 |
| joint links，拿掉 wire UZ support | 23694.7 mm | 24232.6 mm | wire support 是一級 load-path feature |
| joint links，只保留 lift on main | 2948.5 mm | 2878.7 mm | 沒有 torque couple 時 active max 回到 main tip |
| joint links，只保留 torque couple | 110.9 mm | 495.1 mm | torque couple 主要製造 rear differential motion |

主導物理機制因此是：

```text
wire support 後的 bending/load-transfer
+ aerodynamic torque 被轉成 main/rear vertical force couple
+ joint-only sparse rigid link topology
+ weak rear outboard bending stiffness
= rear outboard amplification
```

這不是 global mass error、reaction mismatch 或 equivalent solver validation failure。

### 主導設計自由度

+5% grouped perturbation 結果：

| perturbation | mass delta | main tip delta | max \|UZ\| delta | 工程解讀 |
| --- | ---: | ---: | ---: | --- |
| main radius seg 3-4 only | +1.53% | -10.73% | -9.03% | 最高槓桿，但自由操作違反 taper |
| main radius seg 1-4 plateau | +2.73% | -11.20% | -9.42% | realistic main lever |
| main radius seg 5-6 | +0.98% | -1.90% | -1.78% | 次要 |
| rear radius seg 5-6 only | +0.51% | -0.30% | -2.31% | rear amplification lever，但自由操作違反 taper |
| rear radius all segments | +1.40% | -0.73% | -2.67% | realistic rear OD lever |
| all thickness | +4.88% | -4.41% | -4.38% | reserve knob |
| all radii | +5.11% | -13.69% | -13.75% | 有效但偏重 |

結論：

- main s1-4 plateau radius 是第一主槓桿。
- main s5-6 radius 是第二主槓桿。
- rear global radius 是 rear amplification 的保守槓桿。
- rear outboard 需要單獨 control knob，但不能用自由 OD 破壞 taper。
- thickness 應保留，但只能當 reserve knob，不該主導搜尋。

### Current Direct 為什麼失敗

Current direct dual-beam 的 baseline final point：

```text
success = False
dual mass = 14.258 kg
dual max|UZ| = 2504.781 mm
hard target = 2500.000 mm
violation = 4.781 mm
main radius taper min margin = -2.429 mm
```

它的 final geometry：

```text
main_r_mm = [49.735, 37.608, 32.091, 25.897, 28.326, 15.525]
rear_r_mm = [44.735, 31.951, 27.091, 20.281, 19.449, 10.525]
```

主因：

- 用 full 24D segment vector，讓 optimizer 在低槓桿與不該自由的變數上消耗迭代。
- 從 OpenMDAO initial design 冷啟動，不用 equivalent/hybrid feasible knowledge。
- 第一輪就硬壓 2.5 m max-\|UZ\|，feasible region 太窄。
- 沒有 feasible archive，local final point 失敗就整體失敗。
- raw max-\|UZ\| 與 scalar min margins 不平滑。
- current direct constraint set 漏掉 production-like radius taper 與 thickness-step margins。
- main/rear dominance 讓 rear stiffness 變貴；rear 一長大，main 必須跟著更大，導致 14.26 kg 重設計。
- hard target 只差 4.8 mm 卻不可行，表示策略問題大於物理不可達。

### Internal Dual-Beam 可能誤導 optimizer 的地方

已驗證：

- `dual_beam_analysis.py` 用 penalty equation 在 joint nodes coupling all 6 DOFs。
- `ansys_export.py` 的 dual-spar ANSYS 也是 joint-only all-DOF CE links，這是 parity mode，不代表真實每個 rib bay。
- Root BC 是 both spars all 6 DOFs fixed。
- Wire BC 是 main spar nearest node 的 `UZ = 0`。
- `max_vertical_displacement_m` 是 raw argmax over nodal absolute `UZ`。
- dual failure 是簡化 beam-fiber von Mises，報告中是 non-gating。
- dual support reaction 目前回報 `abs(total_applied_fz_n)`，不是 root/wire partition recovery。

合理推論：

- 如果真實 ribs 很密且 shear/rotation 很硬，joint-only model 可能高估 rear outboard amplification。
- 如果真實 ribs 很柔，all-node rigid link 則會過度樂觀。
- Current dual-spar analysis/export 沒有和 equivalent FEM 完全一致地處理 spar self-weight / rear-gravity torque load ownership；V2 production mode 必須明確化。

尚未證實：

- rib link stiffness 應該採用何種物理值。
- dense finite rib-link mode 對 V2 optimum ranking 的影響。
- dual stress/buckling 是否能取代 equivalent failure/buckling gate。
- dual production load ownership 納入 self-weight 後，對 max \|UZ\| 與 optimum 的量級影響。

## B. Dual-Beam V2 規格

### State Variables

V2 的 state variables 至少包含：

- `u_main[n_node, 6]`：main spar translations/rotations。
- `u_rear[n_node, 6]`：rear spar translations/rotations。
- `r_root_main[6]`、`r_root_rear[6]`：root reaction。
- `r_wire[k]`：wire vertical reaction；未來包含由 wire angle 推回的 axial wire load。
- `lambda_link[j, dof]`：joint/rib link constraint force 或 equivalent spring force。
- `loads_main[n_node, 6]`、`loads_rear[n_node, 6]`：load ownership 與 torque-couple split 後的 final loads。
- element states：curvature、torsion rate、axial strain、main/rear stress、buckling ratios。

Optimizer 初版不一定要用全部 state，但 V2 report 必須輸出 reaction 與 link force，否則 reviewer 無法判斷 load-transfer 是否病態。

### Design Variables

V2 design variables 必須經過 monotone manufacturable mapping 轉成 full segment arrays。不要讓 optimizer 直接擁有 full 24D。

推薦 V2 最小可行 5D：

1. `main_r_s1_4_scale`：main inboard/mid plateau radius。
2. `main_r_s5_6_scale`：main outboard radius group。
3. `rear_r_global_scale`：rear OD global taper-preserving scale。
4. `rear_outboard_ei_scale`：rear segments 5-6 的 local EI reserve。優先用 layup/thickness/EI model；若暫時用 OD，必須 upstream-carry taper projection。
5. `wall_t_global_scale`：全域 wall thickness reserve，主要用於 stress/buckling/local stiffness，不是第一槓桿。

### Objective

Primary objective：

```text
minimize total structural mass
```

V2 必須同時 report：

- `spar_tube_mass_full_kg`
- `total_structural_mass_full_kg`

如果 joint/link/fitting mass 會隨設計變數改變，objective 必須用 total structural mass。若 baseline 下 joint/link mass 固定，tube mass 可以用於 ranking，但報告不可混淆 tube-only dual mass 與 equivalent total mass。

### Hard Constraints

Geometry/manufacturing hard constraints：

- FEM solve finite，無 singular/non-finite。
- `t_main > 0`、`t_rear > 0`。
- `R_main - t_main > margin`。
- `R_rear - t_rear > rear_min_inner_radius_m`。
- `t <= max_thickness_to_radius_ratio * R`。
- OD root-to-tip monotone non-increasing，除非明確建模 sleeve/local reinforcement。
- adjacent wall-thickness step <= `max_thickness_step_m`。
- main-primary dominance 應優先用 EI-based rule；raw radius margin 可保留為製造 guard，但不能是唯一 stiffness-ratio 定義。

Equivalent validated gates 保留，直到 dual 對應模型被驗證：

- equivalent failure KS <= 0。
- equivalent buckling KS <= 0。
- equivalent twist <= configured limit。

Dual displacement hard gate：

- `dual_ks_max_abs_uz_all <= active_dual_deflection_limit`。

Target continuation 可以在搜尋前段使用 relaxed active limit，但 final production candidate 必須 against configured design limit report。

Pathology guard：

- rear/main tip ratio 只能當 loose hard guard 或 report metric，不可當主要 objective 或主要 hard target。

### Report-Only Metrics

以下只能報告，不應直接進 optimizer：

- raw max \|UZ\|。
- raw max location、active spar/node。
- rear/main tip ratio。
- `argmax` node index。
- support reaction partition，直到 reaction recovery 正式實作。
- link force hot spots，直到 link topology/stiffness 校準。
- internal dual stress/failure，直到 apples-to-apples ANSYS beam/fiber stress extraction 驗證。
- ANSYS spot-check classification。
- joint-only vs dense/finite rib-link sensitivity。

### Smoothing / Aggregation Strategy

V2 optimizer hard constraints 要用平滑量。

Displacement absolute：

```text
abs_smooth(u) = sqrt(u^2 + eps^2)
```

Dimensionless KS smooth max：

```text
uz_scale = max(reference_limit, warm_max_uz, small_floor)
g_i = abs_smooth(UZ_i) / uz_scale
dual_ks_max_abs_uz = uz_scale * KS(g_i)
```

至少輸出三個 KS：

- all main + rear nodes。
- rear only。
- rear outboard after last joint。

可以直接進 optimizer：

- smooth KS max displacement。
- equivalent KS failure/buckling/twist。
- vectorized geometry margins，或由參數化直接保證的 geometry。

不能直接進 optimizer：

- `np.argmax`。
- raw `max(abs(...))`。
- raw rear/main ratio。
- raw location switch。
- hard clip 後的隱性 design mapping。

### Boundary Conditions

Root：

- V2 parity mode 保留 current dual-spar assumption：main root 與 rear root all 6 DOFs fixed。
- 未來若加入 root fitting flexibility，必須成為 named BC mode，所有 benchmark/report 都要標明 mode。

Wire：

- wire attachment 在 configured main spar structural node。
- baseline V2 對 main spar node 加 vertical `UZ = 0`，並回收 wire reaction。
- 不可默默把 rear spar 也直接 constrain，除非物理 fitting 明確建模。
- rear support 應透過 joint/rib link model 傳遞。
- wire axial precompression 與 horizontal component 在 dual stress/buckling gating 前必須補齊。

Joint / rib links：

- tube joint links 與 physical rib links 要分開定義。
- current joint-only all-DOF rigid links 是 ANSYS-parity mode，不是 universal truth。
- V2 至少支援兩種 link mode：
  - `joint_only_rigid`：current parity mode。
  - `dense_or_finite_rib`：distributed 或 finite-stiffness ribs，用於 robustness check。
- 如果某設計只在單一脆弱 link mode 下勝出，不能算 V2 成功。

Load ownership：

- V2 必須明確定義 dual solve 是否包含 spar self-weight 與 rear self-weight torque。
- production V2 應與 equivalent FEM load ownership 對齊：aero lift、aero torque、spar self-weight、rear-gravity torque 都顯式處理。
- ANSYS-parity pure aero/torque-couple mode 可以保留，但必須標明不是 production load ownership。

### Feasible 定義

某 target stage 下，candidate feasible iff：

- geometry/manufacturing constraints 全過。
- equivalent failure/buckling/twist gates 全過。
- dual smooth max \|UZ\| <= active stage limit。
- analysis finite/repeatable。
- candidate 是 feasible archive 接受點，不只是 optimizer final point。

Production feasible iff：

- 上述條件對 final configured design limits 成立。
- report 同時列 raw max \|UZ\|、location、rear/main ratio、reaction partition、link-mode sensitivity。

### V2 成功定義

Blackcat 004 baseline 上，V2 不能只追平 hybrid。最低成功條件：

- feasible archive result。
- mass 不高於 hybrid 超過 0.5%。
- raw dual max \|UZ\| 至少比 hybrid 低 2%，或在 equal/lower max \|UZ\| 下 mass 至少低 2%。
- 無 radius taper / thickness-step violation。
- 至少三個 seed 或 deterministic grid starts 結果穩定。
- runtime 與 hybrid 同量級，目標 <= 1.5x hybrid。

Production success 額外需要：

- selected BC/load mode 下，internal dual-beam 與 dual-spar ANSYS spot-check displacement/reaction/mass 仍在 consistent band。
- 附近候選設計不出現 active constraint flip 或 ranking surprise。

## C. 設計變數方案

### 推薦 Reduced Variable Set

V2 主線用 5D：

| variable | 用途 | 初始建議 bounds |
| --- | --- | --- |
| `main_r_s1_4_scale` | wire 後 main bending 主槓桿 | 1.00 to 1.14 |
| `main_r_s5_6_scale` | main outboard 次要槓桿 | 1.00 to 1.14 |
| `rear_r_global_scale` | rear amplification 的 taper-safe OD 槓桿 | 1.00 to 1.12 |
| `rear_outboard_ei_scale` | rear tip local reserve，避免自由 outboard OD 違反 taper | 1.00 to 1.25 |
| `wall_t_global_scale` | thickness reserve knob | 1.00 to 1.08 |

這些 bounds 是 architecture starting point，不是材料允許值；實作時必須 config-driven。

### 為什麼這樣選

- main s1-4 plateau 是最大 displacement-per-mass 槓桿。
- main s5-6 保留 outboard stiffness 調整，但不讓每段自由振盪。
- rear global radius 是目前 code 支援下最乾淨的 rear OD 槓桿。
- rear outboard 需要獨立 control knob，因為 active response 在 rear node 60；但這個 knob 不能破壞 taper。
- thickness 保留作 reserve，避免 stress/buckling/local EI 沒有退路。

### 為什麼不是 Full 24D

Full 24D 的問題不是只有慢：

- 它允許 nonmonotone radius pattern，current direct 已實際出現 main taper violation。
- 它把 optimizer 力氣分散到低槓桿 thickness 與無物理意義的局部振盪。
- 它讓黑盒局部法在狹窄 feasible region 追 raw max constraint boundary。
- 它會因 main/rear dominance constraints 產生 heavy rear-following-main 設計。
- 它不適合 raw max-\|UZ\| 的 active node switching。

### Taper Constraint 應重寫

V2 最好用參數化保證 taper，而不是事後懲罰。

規則：

```text
radius mapping monotone by construction
thickness mapping bounded by step constraints
rear_outboard_ei_scale 不可造成 OD taper violation
```

若 V2.0 還沒有 monotone-by-construction mapping，則 reduced optimizer 必須顯式加上 radius taper 與 thickness-step hard constraints，不可只依賴 equivalent OpenMDAO path。

### Thickness 是否保留

保留，但降權：

- 對 displacement-per-mass 不是第一槓桿。
- 對 stress/buckling/local EI 仍必要。
- 搜尋策略上應先探索 radius / rear EI knobs，再讓 thickness 當 reserve。

## D. 數值與實作建議

### 可以搬 equivalent optimizer 的策略

應保留：

- config-driven bounds/constraints。
- KS aggregation。
- finite-value guards 與 failed-eval normalization。
- evaluation cache。
- feasible-first final selection。
- 低維空間中的 coarse/global search。
- equivalent validation 與 dual-spar spot-check 分離。
- baseline regression tests。

不能直接搬：

- equivalent main tip deflection 作為唯一 displacement target。
- equivalent single-beam stress/torsion 解讀直接變 dual hard gate。
- full segment design vector 當 direct default。
- raw max、raw argmax、raw ratio constraints。
- cold start 第一輪硬壓 2.5 m max-\|UZ\|。

### 推薦 Optimizer 路線

Direct dual-beam V2 應走 feasibility-first + target continuation：

1. Seed archive：
   - equivalent optimum。
   - hybrid refined result。
   - V1 reduced result。
   - deterministic reduced-grid candidates。
   - optional prior feasible V2 archive。

2. Coarse grid in 5D：
   - main radius knobs 用較密 grid。
   - rear/global/outboard EI 與 thickness reserve 用稀疏 grid。
   - 同時維護 feasible archive 與 best-violation archive。

3. Local refine：
   - 有 feasible candidate 就從 best feasible 開始。
   - 沒有 feasible 就從 best violation 開始。
   - 用 smooth constraints。
   - 初期 COBYLA/COBYQA；derivative 可靠後再用 SLSQP。

4. Target schedule：
   - 第一階段先達到 hybrid-scale 或略優於 hybrid。
   - 再逐步往 final design limit 收緊。
   - local final point 失敗時，不可丟掉 feasible archive。

5. Robustness report：
   - final candidates 跑 `joint_only_rigid` 與 `dense_or_finite_rib`。
   - report 每個 mode 的 raw max \|UZ\|、location、rear/main ratio。

### DE → Local 是否適合

DE 可以用，但只限 reduced space。不要把 DE over full 24D 當 V2 主線。V1 已經證明 deterministic coarse grid + local refine 足以到 hybrid band，下一步要改善的是物理參數化與 smooth constraints，不是盲目加大黑盒搜索。

### Warm Start

Direct V2 應該 warm start。「Direct」代表 objective/active constraints 是 dual-beam，不代表要放棄 equivalent/hybrid 已知好設計。

Seed 優先序：

1. same config 的 best archived feasible V2。
2. hybrid refined candidate。
3. equivalent optimum。
4. V1 reduced candidate。
5. conservative deterministic radius-scaled candidates。

### 是否值得往可微架構走

值得，但不要因此延誤 reduced feasibility-first V2。

若要可微，現在就要按以下方向重構：

- dual-beam solver 變成 OpenMDAO component 或等價 differentiable component，具 declared partials。
- displacement 用 smooth KS aggregation。
- design mapping 用 smooth monotone parameterization。
- reaction/link force recovery differentiable。
- load ownership 與 torque-couple split 對 mass/geometry dependence 可微。
- dual stress/buckling 先驗證再 hard-gate。
- BC/link constraints 儘量用 stable elimination 或 well-conditioned constraints，不要長期依賴 opaque huge penalty。

可微路徑應避免：

- `np.argmax`
- hard `clip` inside design mapping
- raw `abs`
- raw scalar `min`
- topology discontinuous switches

## E. 結論

### 建議未來重寫成什麼 dual-beam 主線

建議 V2 主線是：

```text
5D reduced monotone design map
+ explicit dual-beam BC/load mode
+ smooth KS max displacement constraints
+ feasibility-first archive
+ coarse grid then local refine
+ equivalent/hybrid/V1 seed archive
+ link-topology robustness report
```

主線 objective 是 mass；hard constraints 是 smooth dual max-\|UZ\| 加上 validated equivalent failure/buckling/twist 與 geometry/manufacturing constraints。raw rear/main ratio、raw max node、raw argmax 不應成為 optimizer 目標。

### 必須保留

- equivalent-beam ANSYS validation 作為 Phase I solver gate。
- internal dual-beam analysis，因為它已經對 inspected dual-spar ANSYS topology 對得很好。
- hybrid 作為 near-term fallback。
- V1 的 reduced grouping insight。
- feasible archive。
- config-driven physical constraints。
- dual-spar ANSYS spot-check workflow。

### 應該淘汰

- current direct full-24D cold COBYLA mainline。
- rear/main radius-ratio guardrail 作為主要修法。
- raw max-\|UZ\| / argmax 直接進 optimizer。
- dual stress/failure 未驗證前作 hard gate。
- 任何漏掉 taper/thickness-step constraints 的 direct optimizer。
- 若未來 joint/rib/fitting mass 可變，tube-only mass objective 應淘汰。

### 下一位 reviewer 最該審查

1. BC/load ownership：root、wire、self-weight、rear-gravity torque、torque-couple sign。
2. link topology：joint-only parity 與 physical rib distribution 的差異。
3. smooth max displacement aggregation 與 target continuation。
4. reduced variable mapping 是否真的保證 monotone taper。
5. feasible archive selection 是否永遠優先於 local final point。
6. dual stress/buckling 在 hard-gating 前是否完成 apples-to-apples 驗證。
